"""Pruebas del backend provisional de TTS contra Gemini.

No se llama a la API real: el modo ``live`` se prueba contra un servidor
WebSocket local que imita el protocolo ``BidiGenerateContent`` y el modo
``tts`` contra un ``httpx.MockTransport``.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import numpy as np
import pytest

from sonia.tts.gemini import (
    GeminiTTS,
    GeminiTTSSettings,
    TTSError,
    build_gemini_tts,
)

# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

SAMPLE_RATE = 24_000
CHUNK_MS = 100
#: Bytes de un chunk de 100 ms a 24 kHz en PCM s16le.
CHUNK_BYTES = (SAMPLE_RATE * CHUNK_MS // 1000) * 2


def pcm(n_samples: int, value: int = 1234) -> bytes:
    """PCM s16le mono sintético, con un valor constante fácil de reconocer."""
    return np.full(n_samples, value, dtype="<i2").tobytes()


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def settings(**overrides: Any) -> GeminiTTSSettings:
    """Configuración base de los tests: sin leer el entorno del usuario."""
    base: dict[str, Any] = {
        "api_key": "clave-de-prueba",
        "mode": "live",
        "sample_rate": SAMPLE_RATE,
        "timeout": 5.0,
        "voice": "Leda",
        "language": "es-ES",
    }
    base.update(overrides)
    return GeminiTTSSettings(**base)


async def collect(tts: GeminiTTS, text: str) -> list[Any]:
    return [chunk async for chunk in tts.synthesize(text)]


def assert_well_formed(chunks: list[Any], expected: bytes) -> None:
    """Comprueba el contrato de troceado: tamaño, is_last y audio íntegro."""
    assert chunks, "siempre debe salir al menos un chunk"
    assert chunks[-1].is_last is True
    assert all(not chunk.is_last for chunk in chunks[:-1])
    assert all(chunk.sample_rate == SAMPLE_RATE for chunk in chunks)
    assert all(len(chunk.pcm) == CHUNK_BYTES for chunk in chunks[:-1])
    assert len(chunks[-1].pcm) <= CHUNK_BYTES
    assert b"".join(chunk.pcm for chunk in chunks) == expected


# ---------------------------------------------------------------------------
# Servidor WebSocket falso que imita BidiGenerateContent
# ---------------------------------------------------------------------------


class FakeLiveServer:
    """Imita el protocolo Live: setup → setupComplete, clientContent → audio."""

    def __init__(
        self,
        *,
        parts: int = 3,
        samples_per_part: int = 2_000,
        rate: int = SAMPLE_RATE,
        drop_on_turn: set[int] | None = None,
        close_code: int | None = None,
        close_reason: str = "",
        go_away_on: set[int] | None = None,
        silent: bool = False,
        tag_turns: bool = False,
    ) -> None:
        self.parts = parts
        self.samples_per_part = samples_per_part
        self.rate = rate
        #: Marca cada muestra con el número de turno, para saber de qué frase
        #: es el audio que recibe el cliente.
        self.tag_turns = tag_turns
        #: Turnos (empezando en 1) en los que el servidor corta el socket.
        self.drop_on_turn = drop_on_turn or set()
        #: Si se define, el servidor cierra con este código nada más conectar.
        self.close_code = close_code
        self.close_reason = close_reason
        #: Turnos en los que se envía un ``goAway`` junto al audio.
        self.go_away_on = go_away_on or set()
        #: No responder nunca al ``clientContent`` (para probar el timeout).
        self.silent = silent

        self.connections = 0
        self.setups: list[dict[str, Any]] = []
        self.turns: list[dict[str, Any]] = []
        self.urls: list[str] = []

    @property
    def audio(self) -> bytes:
        """El PCM completo que devuelve por turno."""
        return pcm(self.samples_per_part) * self.parts

    def _value(self, turn: int) -> int:
        return turn if self.tag_turns else 1234

    async def handler(self, ws: Any) -> None:
        self.connections += 1
        if self.close_code is not None:
            await ws.close(self.close_code, self.close_reason)
            return

        setup = json.loads(await ws.recv())
        self.setups.append(setup)
        await ws.send(json.dumps({"setupComplete": {}}))

        async for raw in ws:
            message = json.loads(raw)
            self.turns.append(message)
            # El contador es global a todas las conexiones: así un turno que ya
            # cortó una vez no vuelve a cortar en el reintento.
            turn = len(self.turns)

            if turn in self.drop_on_turn:
                # Sesión caída a lo bruto, sin close handshake.
                await ws.close(1011, "sesión caída")
                return
            if self.silent:
                continue

            if turn in self.go_away_on:
                await ws.send(json.dumps({"goAway": {"timeLeft": "5s"}}))

            for _ in range(self.parts):
                await ws.send(
                    json.dumps(
                        {
                            "serverContent": {
                                "modelTurn": {
                                    "parts": [
                                        {
                                            "inlineData": {
                                                "mimeType": f"audio/pcm;rate={self.rate}",
                                                "data": b64(
                                                    pcm(
                                                        self.samples_per_part,
                                                        self._value(turn),
                                                    )
                                                ),
                                            }
                                        }
                                    ]
                                }
                            }
                        }
                    )
                )
            await ws.send(json.dumps({"serverContent": {"generationComplete": True}}))
            await ws.send(json.dumps({"serverContent": {"turnComplete": True}}))


@contextlib.asynccontextmanager
async def running(server: FakeLiveServer) -> AsyncIterator[Callable[[str], Any]]:
    """Arranca el servidor en un puerto libre y devuelve un ``ws_connect``."""
    from websockets.asyncio.client import connect as client_connect
    from websockets.asyncio.server import serve

    async with serve(server.handler, "127.0.0.1", 0) as running_server:
        port = running_server.sockets[0].getsockname()[1]
        local = f"ws://127.0.0.1:{port}"

        async def ws_connect(url: str) -> Any:
            # Se guarda la URL que construye el backend para poder revisarla.
            server.urls.append(url)
            return await client_connect(local, max_size=None)

        yield ws_connect


def build_live(server_connect: Callable[[str], Any], **overrides: Any) -> GeminiTTS:
    return GeminiTTS(settings(**overrides), ws_connect=server_connect, chunk_ms=CHUNK_MS)


# ---------------------------------------------------------------------------
# Modo live: camino feliz
# ---------------------------------------------------------------------------


async def test_live_produce_chunks_con_is_last() -> None:
    server = FakeLiveServer()
    async with running(server) as connect:
        tts = build_live(connect)
        try:
            chunks = await collect(tts, "Hola, soy Sonia.")
        finally:
            await tts.close()

    assert_well_formed(chunks, server.audio)
    # 12 000 bytes = 2 chunks completos de 4 800 + un resto de 2 400.
    assert [len(c.pcm) for c in chunks] == [CHUNK_BYTES, CHUNK_BYTES, 2_400]


async def test_live_setup_lleva_modalidad_audio_voz_e_instruccion() -> None:
    server = FakeLiveServer()
    async with running(server) as connect:
        tts = build_live(connect, voice="Kore", language="es-US", model_live="modelo-x")
        try:
            await collect(tts, "Hola.")
        finally:
            await tts.close()

    setup = server.setups[0]["setup"]
    assert setup["model"] == "models/modelo-x"
    generation = setup["generationConfig"]
    assert generation["responseModalities"] == ["AUDIO"]
    speech = generation["speechConfig"]
    assert speech["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == "Kore"
    assert speech["languageCode"] == "es-US"

    instruction = setup["systemInstruction"]["parts"][0]["text"]
    assert "exactamente" in instruction
    assert "español" in instruction

    # La clave viaja en la query de la URL, no en cabeceras.
    assert "key=clave-de-prueba" in server.urls[0]


async def test_live_envia_client_content_con_turn_complete() -> None:
    server = FakeLiveServer()
    async with running(server) as connect:
        tts = build_live(connect)
        try:
            await collect(tts, "Buenas tardes.")
        finally:
            await tts.close()

    content = server.turns[0]["clientContent"]
    assert content["turnComplete"] is True
    assert content["turns"] == [{"role": "user", "parts": [{"text": "Buenas tardes."}]}]


async def test_live_sin_language_no_manda_language_code() -> None:
    server = FakeLiveServer()
    async with running(server) as connect:
        tts = build_live(connect, language="")
        try:
            await collect(tts, "Hola.")
        finally:
            await tts.close()

    speech = server.setups[0]["setup"]["generationConfig"]["speechConfig"]
    assert "languageCode" not in speech


async def test_live_reutiliza_la_sesion_entre_frases() -> None:
    server = FakeLiveServer()
    async with running(server) as connect:
        tts = build_live(connect)
        try:
            primera = await collect(tts, "Primera frase.")
            segunda = await collect(tts, "Segunda frase.")
        finally:
            await tts.close()

    assert server.connections == 1
    assert len(server.setups) == 1
    assert len(server.turns) == 2
    assert_well_formed(primera, server.audio)
    assert_well_formed(segunda, server.audio)


async def test_live_remuestrea_si_la_api_anuncia_otra_tasa() -> None:
    # El servidor dice 16 kHz; el backend entrega 24 kHz: 1,5x muestras.
    server = FakeLiveServer(parts=1, samples_per_part=1_600, rate=16_000)
    async with running(server) as connect:
        tts = build_live(connect)
        try:
            chunks = await collect(tts, "Hola.")
        finally:
            await tts.close()

    total = b"".join(c.pcm for c in chunks)
    assert len(total) == 2_400 * 2
    assert chunks[-1].is_last is True


async def test_texto_vacio_devuelve_un_unico_chunk_final() -> None:
    server = FakeLiveServer()
    async with running(server) as connect:
        tts = build_live(connect)
        try:
            chunks = await collect(tts, "   ")
        finally:
            await tts.close()

    assert len(chunks) == 1
    assert chunks[0].pcm == b""
    assert chunks[0].is_last is True
    assert server.connections == 0, "no debe abrirse sesión para texto vacío"


# ---------------------------------------------------------------------------
# Modo live: reconexión y errores
# ---------------------------------------------------------------------------


async def test_live_reconecta_si_la_sesion_se_cae() -> None:
    # El primer turno corta el socket antes de mandar audio; el backend
    # reconecta y repite la frase, así que el audio llega igualmente.
    server = FakeLiveServer(drop_on_turn={1})
    async with running(server) as connect:
        tts = build_live(connect)
        try:
            chunks = await collect(tts, "Hola de nuevo.")
        finally:
            await tts.close()

    assert server.connections == 2
    assert len(server.setups) == 2
    assert_well_formed(chunks, server.audio)


async def test_live_recicla_la_sesion_tras_go_away() -> None:
    server = FakeLiveServer(go_away_on={1})
    async with running(server) as connect:
        tts = build_live(connect)
        try:
            primera = await collect(tts, "Primera.")
            segunda = await collect(tts, "Segunda.")
        finally:
            await tts.close()

    # La frase del goAway se completa; la siguiente abre sesión nueva.
    assert_well_formed(primera, server.audio)
    assert_well_formed(segunda, server.audio)
    assert server.connections == 2


async def test_live_cortar_una_frase_a_medias_no_desfasa_la_siguiente() -> None:
    """Barge-in: el turno cortado deja audio en la sesión, así que se recicla.

    Sin esto, la frase siguiente lee lo que quedó del turno anterior y a partir
    de ahí Sonia dice una cosa mientras suena otra hasta que caduque la sesión.
    """
    server = FakeLiveServer(parts=4, samples_per_part=2_400, tag_turns=True)
    async with running(server) as connect:
        tts = build_live(connect)
        try:
            # Se consume un chunk y se corta, como hace el orquestador al
            # cancelar el turno (`aclosing` sobre el generador del TTS).
            frase_uno = tts.synthesize("Frase uno.")
            primero = await anext(frase_uno)
            await frase_uno.aclose()

            segunda = await collect(tts, "Frase dos.")
        finally:
            await tts.close()

    assert set(np.frombuffer(primero.pcm, dtype="<i2").tolist()) == {1}
    valores = set(np.frombuffer(b"".join(c.pcm for c in segunda), dtype="<i2").tolist())
    assert valores == {2}, "la segunda frase suena con el audio de la primera"
    assert server.connections == 2, "la sesión sucia debe reciclarse"


async def test_live_turno_interrumpido_por_el_servidor_recicla_la_sesion() -> None:
    class InterruptingServer(FakeLiveServer):
        async def handler(self, ws: Any) -> None:
            self.connections += 1
            self.setups.append(json.loads(await ws.recv()))
            await ws.send(json.dumps({"setupComplete": {}}))
            async for raw in ws:
                self.turns.append(json.loads(raw))
                if len(self.turns) == 1:
                    await ws.send(json.dumps({"serverContent": {"interrupted": True}}))
                    continue
                await ws.send(json.dumps({"serverContent": {"turnComplete": True}}))

    server = InterruptingServer()
    async with running(server) as connect:
        tts = build_live(connect)
        try:
            await collect(tts, "Frase uno.")
            await collect(tts, "Frase dos.")
        finally:
            await tts.close()

    assert server.connections == 2


async def test_live_clave_invalida_da_tts_error_legible() -> None:
    server = FakeLiveServer(close_code=1008, close_reason="API key not valid")
    async with running(server) as connect:
        tts = build_live(connect)
        try:
            with pytest.raises(TTSError) as error:
                await collect(tts, "Hola.")
        finally:
            await tts.close()

    mensaje = str(error.value)
    assert "1008" in mensaje
    assert "API key not valid" in mensaje
    assert "TTS_GEMINI_API_KEY" in mensaje
    # Un rechazo de la API no se reintenta: no tiene sentido insistir.
    assert server.connections == 1


async def test_live_timeout_da_tts_error() -> None:
    server = FakeLiveServer(silent=True)
    async with running(server) as connect:
        tts = build_live(connect, timeout=0.2)
        try:
            with pytest.raises(TTSError, match="no respondió"):
                await collect(tts, "Hola.")
        finally:
            await tts.close()


async def test_live_sin_clave_no_intenta_conectar() -> None:
    tts = GeminiTTS(settings(api_key=""), chunk_ms=CHUNK_MS)
    try:
        with pytest.raises(TTSError, match="TTS_GEMINI_API_KEY"):
            await collect(tts, "Hola.")
    finally:
        await tts.close()


async def test_live_si_no_conecta_nunca_da_tts_error() -> None:
    async def connect_falla(_url: str) -> Any:
        raise OSError("conexión rechazada")

    tts = GeminiTTS(settings(), ws_connect=connect_falla, chunk_ms=CHUNK_MS)
    try:
        with pytest.raises(TTSError, match="sesión Live"):
            await collect(tts, "Hola.")
    finally:
        await tts.close()


async def test_live_warmup_no_lanza_aunque_falle() -> None:
    async def connect_falla(_url: str) -> Any:
        raise OSError("sin red")

    tts = GeminiTTS(settings(), ws_connect=connect_falla, chunk_ms=CHUNK_MS)
    try:
        await tts.warmup()  # no debe propagar nada
    finally:
        await tts.close()


async def test_live_warmup_abre_la_sesion_una_sola_vez() -> None:
    server = FakeLiveServer()
    async with running(server) as connect:
        tts = build_live(connect)
        try:
            await tts.warmup()
            assert server.connections == 1
            assert server.turns == []
            await collect(tts, "Hola.")
        finally:
            await tts.close()

    assert server.connections == 1


# ---------------------------------------------------------------------------
# Modo tts (REST sobre /v1beta/interactions)
# ---------------------------------------------------------------------------


def mock_tts(handler: Callable[[httpx.Request], httpx.Response], **overrides: Any) -> GeminiTTS:
    transport = httpx.MockTransport(handler)
    return GeminiTTS(settings(mode="tts", **overrides), transport=transport, chunk_ms=CHUNK_MS)


def sse(events: list[dict[str, Any]]) -> bytes:
    lines = []
    for event in events:
        lines.append(f"event: {event.get('event_type', 'message')}")
        lines.append(f"data: {json.dumps(event)}")
        lines.append("")
    lines.append("data: [DONE]")
    lines.append("")
    return "\n".join(lines).encode("utf-8")


async def test_tts_streaming_produce_chunks() -> None:
    trozos = [pcm(2_000, 111), pcm(2_000, 222), pcm(2_000, 333)]
    peticiones: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        peticiones.append(request)
        eventos = [
            {"event_type": "interaction.created", "interaction": {"id": "x"}},
            *[
                {
                    "event_type": "step.delta",
                    "delta": {
                        "type": "audio",
                        "mime_type": f"audio/pcm;rate={SAMPLE_RATE}",
                        "data": b64(trozo),
                    },
                }
                for trozo in trozos
            ],
        ]
        return httpx.Response(200, content=sse(eventos))

    tts = mock_tts(handler, voice="Kore", model_tts="modelo-tts")
    try:
        chunks = await collect(tts, "Hola, soy Sonia.")
    finally:
        await tts.close()

    assert_well_formed(chunks, b"".join(trozos))

    request = peticiones[0]
    assert str(request.url) == "https://generativelanguage.googleapis.com/v1beta/interactions"
    assert request.headers["x-goog-api-key"] == "clave-de-prueba"
    assert request.headers["Api-Revision"]
    cuerpo = json.loads(request.content)
    assert cuerpo["model"] == "modelo-tts"
    assert cuerpo["input"] == "Hola, soy Sonia."
    assert cuerpo["response_format"] == {"type": "audio"}
    assert cuerpo["generation_config"]["speech_config"] == [{"voice": "Kore"}]
    assert cuerpo["stream"] is True


async def test_tts_sin_streaming_lee_output_audio() -> None:
    audio = pcm(5_000, 77)

    def handler(request: httpx.Request) -> httpx.Response:
        assert "stream" not in json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "int_1",
                "status": "completed",
                "output_audio": {
                    "data": b64(audio),
                    "mime_type": f"audio/pcm;rate={SAMPLE_RATE}",
                },
            },
        )

    tts = mock_tts(handler, stream=False)
    try:
        chunks = await collect(tts, "Hola.")
    finally:
        await tts.close()

    assert_well_formed(chunks, audio)


async def test_tts_estilo_se_antepone_al_texto() -> None:
    cuerpos: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        cuerpos.append(json.loads(request.content))
        return httpx.Response(200, json={"output_audio": {"data": b64(pcm(100))}})

    tts = mock_tts(handler, stream=False, style="Di con alegría")
    try:
        await collect(tts, "Hola.")
    finally:
        await tts.close()

    assert cuerpos[0]["input"] == "Di con alegría: Hola."


async def test_tts_usa_el_evento_final_si_no_hubo_deltas() -> None:
    audio = pcm(3_000, 55)

    def handler(_request: httpx.Request) -> httpx.Response:
        eventos = [
            {
                "event_type": "interaction.completed",
                "interaction": {
                    "output_audio": {
                        "data": b64(audio),
                        "mime_type": f"audio/pcm;rate={SAMPLE_RATE}",
                    }
                },
            }
        ]
        return httpx.Response(200, content=sse(eventos))

    tts = mock_tts(handler)
    try:
        chunks = await collect(tts, "Hola.")
    finally:
        await tts.close()

    assert_well_formed(chunks, audio)


async def test_tts_no_duplica_audio_si_llegan_deltas_y_evento_final() -> None:
    delta = pcm(2_000, 9)

    def handler(_request: httpx.Request) -> httpx.Response:
        eventos = [
            {
                "event_type": "step.delta",
                "delta": {"type": "audio", "data": b64(delta)},
            },
            {
                "event_type": "interaction.completed",
                "interaction": {"output_audio": {"data": b64(delta)}},
            },
        ]
        return httpx.Response(200, content=sse(eventos))

    tts = mock_tts(handler)
    try:
        chunks = await collect(tts, "Hola.")
    finally:
        await tts.close()

    assert_well_formed(chunks, delta)


async def test_tts_error_de_clave_da_tts_error_legible() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={
                "error": {
                    "code": 403,
                    "message": "API key not valid.",
                    "status": "PERMISSION_DENIED",
                }
            },
        )

    tts = mock_tts(handler)
    try:
        with pytest.raises(TTSError) as error:
            await collect(tts, "Hola.")
    finally:
        await tts.close()

    mensaje = str(error.value)
    assert "403" in mensaje
    assert "API key not valid." in mensaje
    assert "TTS_GEMINI_API_KEY" in mensaje


async def test_tts_cuota_agotada_lo_dice_claro() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "Quota exceeded"}})

    tts = mock_tts(handler, stream=False)
    try:
        with pytest.raises(TTSError, match="cuota"):
            await collect(tts, "Hola.")
    finally:
        await tts.close()


async def test_tts_timeout_da_tts_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("demasiado lento", request=request)

    tts = mock_tts(handler)
    try:
        with pytest.raises(TTSError, match="no respondió"):
            await collect(tts, "Hola.")
    finally:
        await tts.close()


async def test_tts_error_de_red_da_tts_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin ruta al host", request=request)

    tts = mock_tts(handler, stream=False)
    try:
        with pytest.raises(TTSError, match="Error de red"):
            await collect(tts, "Hola.")
    finally:
        await tts.close()


async def test_tts_evento_de_error_aborta_la_sintesis() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        eventos = [{"event_type": "error", "error": {"message": "modelo sobrecargado"}}]
        return httpx.Response(200, content=sse(eventos))

    tts = mock_tts(handler)
    try:
        with pytest.raises(TTSError, match="modelo sobrecargado"):
            await collect(tts, "Hola.")
    finally:
        await tts.close()


async def test_tts_sin_clave_no_llama_a_la_api() -> None:
    tts = GeminiTTS(settings(mode="tts", api_key=""), chunk_ms=CHUNK_MS)
    try:
        with pytest.raises(TTSError, match="TTS_GEMINI_API_KEY"):
            await collect(tts, "Hola.")
    finally:
        await tts.close()


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------


async def test_build_gemini_tts_lee_el_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TTS_GEMINI_API_KEY", "abc123")
    monkeypatch.setenv("TTS_GEMINI_MODE", "tts")
    monkeypatch.setenv("TTS_GEMINI_VOICE", "Aoede")
    monkeypatch.setenv("TTS_GEMINI_SAMPLE_RATE", "16000")

    tts = build_gemini_tts()
    try:
        assert tts.sample_rate == 16_000
    finally:
        await tts.close()


async def test_los_valores_por_defecto_son_razonables() -> None:
    config = GeminiTTSSettings(_env_file=None)  # type: ignore[call-arg]
    assert config.mode == "live"
    assert config.sample_rate == 24_000
    assert "live" in config.model_live
    assert "tts" in config.model_tts
    assert config.language.startswith("es")


async def test_sintesis_concurrente_se_serializa() -> None:
    # Una sola sesión Live no admite dos turnos a la vez: el lock los ordena.
    server = FakeLiveServer(parts=1, samples_per_part=1_000)
    async with running(server) as connect:
        tts = build_live(connect)
        try:
            resultados = await asyncio.gather(
                collect(tts, "Una."), collect(tts, "Dos."), collect(tts, "Tres.")
            )
        finally:
            await tts.close()

    assert server.connections == 1
    assert len(server.turns) == 3
    for chunks in resultados:
        assert_well_formed(chunks, server.audio)
