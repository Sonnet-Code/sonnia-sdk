"""Pruebas del motor GPT-Live, sin red, sin clave y sin hardware.

GPT-Live es un servidor WebSocket local que imita la API Live (``session.start``
→ ``session.started``, eventos de voz, transcripción y delegación) y graba
todo lo que le manda el motor. Unity es un cliente ``websockets`` conectado a
un ``Hub`` real, igual que en las pruebas del orquestador.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pytest

import sonia.live.engine as engine_module
import sonia.live.oneshot as oneshot_module
from sonia.actions import build_default_registry
from sonia.config import (
    AudioSettings,
    LiveSettings,
    LLMSettings,
    Settings,
    ShowcaseSettings,
    VisionSettings,
    WSSettings,
)
from sonia.live.audio import NoiseGate, pcm16_from_float, rms
from sonia.live.client import LiveClient, LiveError
from sonia.live.engine import INTERRUPT_TEXT, LiveEngine
from sonia.live.oneshot import probe_session, speak_text
from sonia.live.prompts import build_session_config, describe_live_stack
from sonia.live.vision import VisionNarrator
from sonia.showcase import ATTENTION_DANCE, Showcase
from sonia.types import Frame, LLMEvent, Message, TextDelta, TurnDone
from sonia.vision.policy import VisionPolicy
from sonia.ws.hub import Hub
from tests.helpers import FakeCamera, Recorder

RATE = 24_000

# ---------------------------------------------------------------------------
# Servidor GPT-Live falso
# ---------------------------------------------------------------------------


def pcm(samples: int, value: int = 1000) -> bytes:
    return np.full(samples, value, dtype="<i2").tobytes()


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


@dataclass
class FakeConn:
    """Una sesión abierta contra el servidor falso."""

    ws: Any
    start: dict[str, Any]
    authorization: str | None
    received: list[dict[str, Any]] = field(default_factory=list)
    changed: asyncio.Event = field(default_factory=asyncio.Event)

    async def send(self, event: dict[str, Any]) -> None:
        await self.ws.send(json.dumps(event))

    async def audio(self, data: bytes) -> None:
        await self.send({"type": "session.output_audio.delta", "delta": b64(data)})

    async def say(self, text: str) -> None:
        await self.send({"type": "session.output_transcript.delta", "delta": text})

    async def hear(self, text: str) -> None:
        await self.send(
            {"type": "session.input_transcript.delta", "delta": text, "start_ms": 0, "end_ms": 1}
        )

    async def response_event(
        self, nested: dict[str, Any], delegation_id: str | None = "deleg_1"
    ) -> None:
        await self.send(
            {
                "type": "response.event",
                "event_id": "ev",
                "delegation_id": delegation_id,
                "event": nested,
            }
        )

    def of_type(self, kind: str) -> list[dict[str, Any]]:
        return [m for m in self.received if m.get("type") == kind]

    def audio_in(self) -> list[bytes]:
        return [base64.b64decode(m["audio"]) for m in self.of_type("session.input_audio.append")]

    async def wait_for(
        self, predicate: Callable[[list[dict[str, Any]]], bool], limit: float = 3.0
    ) -> None:
        async with asyncio.timeout(limit):
            while not predicate(self.received):
                self.changed.clear()
                await self.changed.wait()

    async def wait_type(self, kind: str, count: int = 1, limit: float = 3.0) -> None:
        await self.wait_for(
            lambda msgs: len([m for m in msgs if m["type"] == kind]) >= count, limit
        )


class FakeLiveServer:
    """Imita ``/v1/live/sessions``: arranque, comandos y cierre ordenado."""

    def __init__(
        self,
        *,
        reject: bool = False,
        drop_after_start: bool = False,
        close_after_start: str | None = None,
    ) -> None:
        self.reject = reject
        self.drop_after_start = drop_after_start
        #: Si se define, el servidor cierra la sesión de forma ordenada con
        #: este motivo nada más arrancarla (``expired``, ``content``...).
        self.close_after_start = close_after_start
        self.conns: list[FakeConn] = []
        self.attempts = 0
        self._new_conn = asyncio.Event()
        #: Se llama con cada comando recibido (para reacciones automáticas).
        self.on_message: Callable[[FakeConn, dict[str, Any]], Any] | None = None

    async def handler(self, ws: Any) -> None:
        self.attempts += 1
        start = json.loads(await ws.recv())
        authorization = ws.request.headers.get("Authorization")
        if self.reject:
            await ws.send(
                json.dumps(
                    {
                        "type": "error",
                        "event_id": "e",
                        "error": {
                            "type": "invalid_request_error",
                            "code": "model_not_found",
                            "message": "no existe",
                            "client_event_id": start.get("event_id"),
                        },
                    }
                )
            )
            await ws.close()
            return
        session = dict(start["session"])
        session.update({"id": f"sess_{len(self.conns) + 1}", "expires_at": int(time.time()) + 3600})
        await ws.send(json.dumps({"type": "session.started", "event_id": "e0", "session": session}))
        conn = FakeConn(ws, start, authorization)
        self.conns.append(conn)
        self._new_conn.set()
        if self.drop_after_start:
            await ws.close(1011, "caída")
            return
        if self.close_after_start is not None:
            await ws.send(
                json.dumps(
                    {
                        "type": "session.closed",
                        "event_id": "ec",
                        "reason": self.close_after_start,
                        "session": session,
                        "usage": {"seconds": 0},
                    }
                )
            )
            await ws.close()
            return
        with contextlib.suppress(Exception):
            async for raw in ws:
                message = json.loads(raw)
                conn.received.append(message)
                conn.changed.set()
                if self.on_message is not None:
                    result = self.on_message(conn, message)
                    if asyncio.iscoroutine(result):
                        await result
                if message["type"] == "session.close":
                    await ws.send(
                        json.dumps(
                            {
                                "type": "session.closed",
                                "event_id": "ec",
                                "reason": "close_requested",
                                "session": session,
                                "usage": {"seconds": 1},
                            }
                        )
                    )
                    await ws.close()
                    return

    async def wait_conn(self, count: int = 1, limit: float = 3.0) -> FakeConn:
        async with asyncio.timeout(limit):
            while len(self.conns) < count:
                self._new_conn.clear()
                await self._new_conn.wait()
        return self.conns[count - 1]


@contextlib.asynccontextmanager
async def running(server: FakeLiveServer) -> AsyncIterator[Callable[[str, dict[str, str]], Any]]:
    from websockets.asyncio.client import connect as client_connect
    from websockets.asyncio.server import serve

    async with serve(server.handler, "127.0.0.1", 0) as srv:
        port = srv.sockets[0].getsockname()[1]

        async def connect(url: str, headers: dict[str, str]) -> Any:
            return await client_connect(f"ws://127.0.0.1:{port}", additional_headers=headers)

        yield connect


# ---------------------------------------------------------------------------
# Montaje del motor
# ---------------------------------------------------------------------------


def make_settings(
    tmp_path: Path,
    *,
    vision_source: str = "none",
    idle_reset: float = 120.0,
    showcase_settings: ShowcaseSettings | None = None,
    image_auto_hide: float = 0.0,
    **live: Any,
) -> Settings:
    gallery = tmp_path / "gallery"
    gallery.mkdir(exist_ok=True)
    live_values: dict[str, Any] = {
        "api_key": "clave-de-prueba",
        "segment_gap_ms": 150,
        "user_turn_gap_ms": 200,
        "reconnect_min_seconds": 0.05,
        "reconnect_max_seconds": 0.1,
        "connect_timeout": 2.0,
        "vision_min_interval_seconds": 0.0,
    }
    live_values.update(live)
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        live=LiveSettings(**live_values),
        llm=LLMSettings(
            base_url="http://llm.test/v1",
            model="modelo-de-vision",
            api_key="clave",
            supports_vision=True,
            reasoning_effort="",
        ),
        audio=AudioSettings(),
        vision=VisionSettings(source=vision_source, on_turn_start=True),  # type: ignore[arg-type]
        ws=WSSettings(host="127.0.0.1", port=0),
        showcase=showcase_settings or ShowcaseSettings(enabled=False),
        assets_dir=str(tmp_path),
        log_level="DEBUG",
        idle_reset_seconds=idle_reset,
        image_auto_hide_seconds=image_auto_hide,
    )


class FakeVisionLLM:
    """Modelo de visión falso para el narrador."""

    def __init__(self, text: str = "Una persona con camisa azul y gafas.") -> None:
        self.text = text
        self.requests: list[list[Message]] = []

    async def stream(
        self, messages: list[Message], tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[LLMEvent]:
        self.requests.append(messages)
        yield TextDelta(self.text)
        yield TurnDone(self.text)


@dataclass
class LiveRig:
    settings: Settings
    server: FakeLiveServer
    engine: LiveEngine
    hub: Hub
    client: Any
    rec: Recorder

    async def conn(self, count: int = 1) -> FakeConn:
        conn = await self.server.wait_conn(count)
        await wait_until(lambda: self.engine.session_id == f"sess_{count}")
        return conn

    async def unity(self, msg: dict[str, Any]) -> None:
        await self.client.send(json.dumps(msg))


@contextlib.asynccontextmanager
async def make_rig(
    tmp_path: Path,
    *,
    server: FakeLiveServer | None = None,
    camera: FakeCamera | None = None,
    narrator: VisionNarrator | None = None,
    showcase: Showcase | None = None,
    **settings_overrides: Any,
) -> AsyncIterator[LiveRig]:
    from websockets.asyncio.client import connect

    settings = make_settings(tmp_path, **settings_overrides)
    server = server or FakeLiveServer()
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir(exist_ok=True)
    (knowledge / "01-evento.md").write_text("El DevFest es el 9 y 10 de octubre.", encoding="utf-8")
    policy = VisionPolicy(settings.vision, settings.llm.supports_vision)
    registry = build_default_registry(include_look=policy.enabled)
    hub = Hub(settings.ws, sample_rate=settings.live.sample_rate)
    async with running(server) as live_connect, hub:
        engine = LiveEngine(
            settings,
            hub=hub,
            registry=registry,
            camera=camera,
            vision_policy=policy,
            narrator=narrator,
            showcase=showcase,
            connect=live_connect,
            knowledge_dir=knowledge,
            tick_s=0.02,
        )
        async with connect(f"ws://127.0.0.1:{hub.port}/") as client:
            hello = json.loads(await asyncio.wait_for(client.recv(), 2.0))
            assert hello["type"] == "hello"
            assert hello["sample_rate"] == RATE
            rec = Recorder(client)
            task = asyncio.create_task(engine.run())
            await rec.wait_state("idle")
            try:
                yield LiveRig(settings, server, engine, hub, client, rec)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                await rec.close()


def voice_block(value: float = 0.5, samples: int = 768) -> np.ndarray[Any, Any]:
    return np.full(samples, value, dtype=np.float32)


async def wait_until(predicate: Callable[[], bool], limit: float = 3.0) -> None:
    async with asyncio.timeout(limit):
        while not predicate():  # noqa: ASYNC110 - sondeo de un predicado
            await asyncio.sleep(0.01)


# ---------------------------------------------------------------------------
# Arranque de la sesión
# ---------------------------------------------------------------------------


async def test_session_start_lleva_modelo_voz_formato_y_acciones(tmp_path: Path) -> None:
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        assert conn.authorization == "Bearer clave-de-prueba"
        assert conn.start["type"] == "session.start"
        session = conn.start["session"]
        assert session["model"] == "gpt-live-1"
        assert session["audio"] == {
            "format": {"type": "audio/pcm", "rate": RATE},
            "output": {"voice": "marin"},
        }
        delegation = session["delegation"]
        assert delegation["type"] == "responses"
        backend = delegation["responses"]
        assert backend["model"] == "gpt-6-luna"
        assert backend["reasoning"] == {"effort": "low"}
        assert "service_tier" not in backend
        # Sin cámara no se anuncia ``look``; las funciones van planas (API Responses).
        assert [t["name"] for t in backend["tools"]] == ["show_image", "hide_image"]
        assert all(t["type"] == "function" and "function" not in t for t in backend["tools"])
        instructions = session["instructions"]
        assert "Eres Sonia" in instructions
        assert "CÓMO FUNCIONAS (voz a voz en tiempo real)" in instructions
        assert "El DevFest es el 9 y 10 de octubre." in instructions
        assert "TU STACK AHORA MISMO" in instructions
        assert len(instructions) < 16_384 * 3  # muy por debajo del límite de tokens


def test_session_config_respeta_los_opcionales(tmp_path: Path) -> None:
    settings = make_settings(
        tmp_path, backend_reasoning_effort="", backend_service_tier="priority", voice="cedar"
    )
    config = build_session_config(
        settings,
        registry=build_default_registry(include_look=True),
        gallery_ids=["logo-sonnet"],
        knowledge_dir=tmp_path,
    )
    backend = config["delegation"]["responses"]
    assert "reasoning" not in backend
    assert backend["service_tier"] == "priority"
    assert backend["parallel_tool_calls"] is False
    assert "logo-sonnet" in backend["instructions"]
    assert config["audio"]["output"]["voice"] == "cedar"
    assert [t["name"] for t in backend["tools"]] == ["look", "show_image", "hide_image"]
    assert "Mirar: tomar una foto nueva" in config["instructions"]


def test_las_reglas_piden_parar_si_la_interrumpen(tmp_path: Path) -> None:
    registry = build_default_registry(include_look=False)
    instructions = build_session_config(make_settings(tmp_path), registry=registry, gallery_ids=[])[
        "instructions"
    ]
    assert "Si te interrumpe, para enseguida" in instructions


def test_el_stack_de_live_dice_que_la_voz_va_en_la_nube(tmp_path: Path) -> None:
    text = describe_live_stack(make_settings(tmp_path), action_names=["show_image"])
    assert "gpt-live-1" in text
    assert "en la nube" in text
    assert "No digas que corres en local" in text
    assert "no puedes ver a nadie" in text


def test_la_tasa_de_muestreo_se_lee_del_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    # Desde .env llega como texto: no puede tumbar la carga de la configuración.
    monkeypatch.setenv("LIVE_SAMPLE_RATE", "16000")
    assert LiveSettings().sample_rate == 16_000
    monkeypatch.setenv("LIVE_SAMPLE_RATE", "24000")
    assert Settings(_env_file=None).live.sample_rate == 24_000  # type: ignore[call-arg]
    monkeypatch.setenv("LIVE_SAMPLE_RATE", "44100")
    with pytest.raises(ValueError, match="16000 o 24000"):
        LiveSettings()


def test_la_clave_sale_de_openai_api_key_si_no_hay_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LIVE_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "clave-openai")
    assert LiveSettings().api_key == "clave-openai"
    monkeypatch.setenv("LIVE_API_KEY", "clave-live")
    assert LiveSettings().api_key == "clave-live"


async def test_sin_clave_no_intenta_conectar() -> None:
    client = LiveClient(LiveSettings(api_key=""))
    with pytest.raises(LiveError, match="LIVE_API_KEY"):
        await client.start({"model": "gpt-live-1"})


# ---------------------------------------------------------------------------
# Voz de Sonia hacia Unity
# ---------------------------------------------------------------------------


async def test_los_subtitulos_no_muestran_marcas_de_sonido(tmp_path: Path) -> None:
    # "[laugh]", "[tongue click]"... no deben verse en la pantalla del stand.
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.hear("[tongue click] Bueno, ¿cómo te va?")
        await conn.say("[laugh] Me encantaría, ")
        await conn.audio(pcm(2_400))
        await conn.say("pero no [sig")
        await conn.say("h] tengo WhatsApp.")
        await rig.rec.wait_type("speech_end")
        shown = [m["text"] for m in rig.rec.of_type("transcript")]
        shown += [m["text"] for m in rig.rec.of_type("speech_start")]
        assert shown and not any("[" in t or "]" in t for t in shown)
        assert "Me encantaría, pero no tengo WhatsApp." in shown


async def test_la_voz_llega_a_unity_como_una_frase_con_subtitulos(tmp_path: Path) -> None:
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.say("Hola, ")
        for _ in range(3):
            await conn.audio(pcm(2_400))
        await conn.say("soy Sonia.")

        await rig.rec.wait_type("speech_end")
        speech_start = rig.rec.of_type("speech_start")[0]
        assert speech_start["utterance_id"] == 1
        assert speech_start["text"] == "Hola,"
        assert "ambient" not in speech_start
        assert "speaking" in rig.rec.states()
        frames = rig.rec.audio(1)
        assert b"".join(f[3] for f in frames) == pcm(2_400) * 3
        assert frames[-1][2] is True  # el último chunk lleva la marca de fin
        transcripts = [m for m in rig.rec.of_type("transcript") if m["role"] == "assistant"]
        assert transcripts[-1] == {
            "type": "transcript",
            "role": "assistant",
            "text": "Hola, soy Sonia.",
            "final": True,
        }
        assert any(not t["final"] for t in transcripts)

        # Hasta que Unity no confirma la reproducción, Sonia sigue hablando.
        await asyncio.sleep(0.1)
        assert rig.engine.state == "speaking"
        await rig.unity({"type": "playback_done", "utterance_id": 1})
        await rig.rec.wait_state("idle", count=2)


async def test_un_silencio_largo_parte_la_voz_en_dos_frases(tmp_path: Path) -> None:
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.audio(pcm(1_200))
        await rig.rec.wait_type("speech_end")
        await conn.audio(pcm(1_200))
        await rig.rec.wait_type("speech_end", count=2)
        assert [m["utterance_id"] for m in rig.rec.of_type("speech_start")] == [1, 2]


async def test_el_silencio_continuo_de_gpt_live_no_abre_frases(tmp_path: Path) -> None:
    # La API real manda audio sin parar, también callada (silencio digital).
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        for _ in range(5):
            await conn.audio(pcm(2_400, 0))
        await asyncio.sleep(0.3)
        assert not rig.rec.of_type("speech_start")
        assert rig.engine.state == "idle"


async def test_la_frase_se_cierra_aunque_siga_llegando_silencio(tmp_path: Path) -> None:
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        voz, silencio = pcm(2_400, 900), pcm(2_400, 0)
        await conn.audio(silencio)
        await conn.audio(voz)
        await conn.audio(silencio)  # pausa corta dentro de la frase
        await conn.audio(voz)
        for _ in range(4):  # silencio que sigue llegando a ritmo real
            await conn.audio(silencio)
            await asyncio.sleep(0.05)
        await rig.rec.wait_type("speech_end")
        sent = b"".join(f[3] for f in rig.rec.audio(1))
        assert sent == voz + silencio + voz  # sin el silencio de delante ni el de detrás
        assert len(rig.rec.of_type("speech_start")) == 1


# ---------------------------------------------------------------------------
# Voz del visitante
# ---------------------------------------------------------------------------


async def test_lo_que_dice_el_visitante_pone_listening_y_cierra_el_turno(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine_module, "RESPONSE_WAIT_S", 0.3)
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.hear("¿Qué es ")
        await rig.rec.wait_state("listening")
        await conn.hear("Sonnet Code?")
        await rig.rec.wait_for(
            lambda msgs: any(
                m.get("type") == "transcript" and m["role"] == "user" and m["final"]
                for m in rig.rec.json(msgs)
            )
        )
        finals = [m for m in rig.rec.of_type("transcript") if m["role"] == "user" and m["final"]]
        assert finals[-1]["text"] == "¿Qué es Sonnet Code?"
        # Turno cerrado: espera la respuesta en ``thinking`` y, si no llega, vuelve a idle.
        await rig.rec.wait_state("thinking")
        await rig.rec.wait_state("idle", count=2)


async def test_text_input_llega_como_commentary(tmp_path: Path) -> None:
    # ``instructions.append`` no la hace hablar (probado con la API real); ``commentary`` sí.
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await rig.unity({"type": "text_input", "text": "¿Dónde es el DevFest?"})
        await conn.wait_type("session.commentary.append")
        append = conn.of_type("session.commentary.append")[0]
        assert "¿Dónde es el DevFest?" in append["content"]
        assert append["delegation_id"] is None
        await rig.rec.wait_state("thinking")
        user = [m for m in rig.rec.of_type("transcript") if m["role"] == "user"]
        assert user[-1]["text"] == "¿Dónde es el DevFest?" and user[-1]["final"] is True


# ---------------------------------------------------------------------------
# Micrófono
# ---------------------------------------------------------------------------


def test_las_marcas_de_sonido_no_salen_en_la_transcripcion() -> None:
    from sonia.live.engine import clean_transcript

    assert clean_transcript("[laugh] Hola Sonia [sigh] ¿me oyes?") == "Hola Sonia ¿me oyes?"
    assert clean_transcript("[sigh") == ""
    assert clean_transcript("] Audita todo") == "Audita todo"
    assert clean_transcript("laugh] Y qué opinas") == "Y qué opinas"
    assert clean_transcript("Hola   mundo ") == "Hola mundo"


async def test_un_turno_que_solo_es_una_risa_no_se_muestra(tmp_path: Path) -> None:
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.hear("[laugh")
        await conn.hear("]")
        await asyncio.sleep(0.4)
        finals = [m for m in rig.rec.of_type("transcript") if m["role"] == "user" and m["final"]]
        assert finals == []


def test_pcm16_y_rms() -> None:
    block = np.array([0.0, 0.5, -0.5, 2.0], dtype=np.float32)
    samples = np.frombuffer(pcm16_from_float(block), dtype="<i2")
    assert samples.tolist() == [0, 16383, -16383, 32767]
    assert rms(np.full(10, 0.25, dtype=np.float32)) == pytest.approx(0.25)


def test_la_puerta_de_ruido_se_abre_con_voz_y_aguanta_las_pausas() -> None:
    gate = NoiseGate(threshold=0.1, hold_ms=500)
    assert gate.admit(0.02, now=0.0) is False
    assert gate.admit(0.3, now=1.0) is True
    assert gate.admit(0.02, now=1.4) is True  # pausa entre palabras
    assert gate.admit(0.02, now=1.6) is False
    assert NoiseGate(threshold=0.0, hold_ms=500).admit(0.0) is True


async def test_el_micro_sigue_abierto_mientras_habla_sonia(tmp_path: Path) -> None:
    # GPT-Live es full duplex: el visitante puede interrumpirla en cualquier momento.
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.audio(pcm(1_200))
        await rig.rec.wait_type("speech_start")
        await rig.engine.push_mic(voice_block())
        await conn.wait_type("session.input_audio.append")
        assert any(conn.audio_in()[-1])


async def test_la_puerta_de_ruido_manda_silencio_por_debajo_del_umbral(tmp_path: Path) -> None:
    async with make_rig(tmp_path, gate_rms=0.1) as rig:
        conn = await rig.conn()
        await rig.engine.push_mic(voice_block(0.01))
        await rig.engine.push_mic(voice_block(0.5))
        await conn.wait_type("session.input_audio.append", count=2)
        quiet, loud = conn.audio_in()[-2:]
        assert not any(quiet) and any(loud)


# ---------------------------------------------------------------------------
# Delegación y acciones
# ---------------------------------------------------------------------------


async def test_show_image_por_delegacion_y_continuacion_del_backend(tmp_path: Path) -> None:
    (tmp_path / "gallery").mkdir()
    (tmp_path / "gallery" / "logo-sonnet.png").write_bytes(b"\x89PNG-logo")
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.send(
            {
                "type": "session.delegation.created",
                "event_id": "ed",
                "offset_ms": 100,
                "delegation": {
                    "id": "deleg_1",
                    "type": "delegation",
                    "target": "responses",
                    "response_id": "resp_1",
                },
            }
        )
        await rig.rec.wait_state("thinking")
        await conn.response_event({"type": "response.created"})
        await conn.response_event(
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "show_image",
                    "arguments": json.dumps({"image_id": "logo-sonnet", "caption": "Sonnet Code"}),
                },
            }
        )
        await conn.response_event({"type": "response.completed"})

        await rig.rec.wait_type("show_image")
        shown = rig.rec.of_type("show_image")[0]
        assert shown["image_id"] == "logo-sonnet"
        assert base64.b64decode(shown["data_base64"]) == b"\x89PNG-logo"
        await conn.wait_type("response.create")
        kinds = [m["type"] for m in conn.received if m["type"].startswith("response.")]
        assert kinds == ["response.item.create", "response.create"]
        output = conn.of_type("response.item.create")[0]["item"]
        assert output["type"] == "function_call_output"
        assert output["call_id"] == "call_1"
        assert output["output"].startswith("Mostrando")

        # La segunda respuesta del backend solo trae texto: la tarea termina.
        await conn.response_event({"type": "response.created"})
        await conn.response_event({"type": "response.output_text.delta", "delta": "Logo mostrado."})
        await conn.response_event({"type": "response.completed"})
        await wait_until(lambda: not rig.engine._delegations)
        assert len(conn.of_type("response.create")) == 1


async def test_look_devuelve_la_foto_al_backend(tmp_path: Path) -> None:
    camera = FakeCamera(data=b"\xff\xd8foto")
    async with make_rig(tmp_path, camera=camera, vision_source="opencv") as rig:
        conn = await rig.conn()
        tools = conn.start["session"]["delegation"]["responses"]["tools"]
        assert "look" in [t["name"] for t in tools]
        await conn.response_event(
            {
                "type": "response.output_item.done",
                "item": {"type": "function_call", "call_id": "c", "name": "look", "arguments": ""},
            }
        )
        await conn.response_event({"type": "response.completed"})
        await conn.wait_type("response.create")
        items = [m["item"] for m in conn.of_type("response.item.create")]
        assert items[0] == {
            "type": "function_call_output",
            "call_id": "c",
            "output": "Captura tomada.",
        }
        image = items[1]["content"][1]
        assert image["type"] == "input_image"
        assert image["image_url"] == "data:image/jpeg;base64," + b64(b"\xff\xd8foto")
        assert camera.captures == 1


async def test_una_accion_desconocida_devuelve_el_error_al_backend(tmp_path: Path) -> None:
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.response_event(
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "function_call",
                    "call_id": "x",
                    "name": "volar",
                    "arguments": "{",
                },
            }
        )
        await conn.response_event({"type": "response.completed"})
        await conn.wait_type("response.create")
        output = conn.of_type("response.item.create")[0]["item"]["output"]
        assert output.startswith("Error")


# ---------------------------------------------------------------------------
# Visión
# ---------------------------------------------------------------------------


async def test_al_empezar_a_hablar_alguien_llega_una_nota_de_la_camara(tmp_path: Path) -> None:
    camera = FakeCamera()
    llm = FakeVisionLLM()
    async with make_rig(
        tmp_path, camera=camera, narrator=VisionNarrator(llm), vision_source="opencv"
    ) as rig:
        conn = await rig.conn()
        await conn.hear("Hola")
        await conn.wait_type("session.thinking.append")
        note = conn.of_type("session.thinking.append")[0]
        assert note["content"] == "[Cámara] Una persona con camisa azul y gafas."
        assert note["delegation_id"] is None
        # La foto va al modelo de visión como image_url, nunca a GPT-Live.
        content = llm.requests[0][1]["content"]
        assert any(part.get("type") == "image_url" for part in content)
        assert rig.engine.last_frame is not None


async def test_el_narrador_no_repite_dentro_del_intervalo_minimo(tmp_path: Path) -> None:
    camera = FakeCamera()
    async with make_rig(
        tmp_path,
        camera=camera,
        narrator=VisionNarrator(FakeVisionLLM()),
        vision_source="opencv",
        vision_min_interval_seconds=60.0,
        user_turn_gap_ms=50,
    ) as rig:
        conn = await rig.conn()
        await conn.hear("Hola")
        await conn.wait_type("session.thinking.append")
        await asyncio.sleep(0.15)
        await conn.hear("Otra cosa")
        await asyncio.sleep(0.2)
        assert camera.captures == 1


# ---------------------------------------------------------------------------
# Interrupción, reconexión y renovación
# ---------------------------------------------------------------------------


async def test_interrupt_de_unity_corta_la_voz_y_descarta_el_resto(tmp_path: Path) -> None:
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.audio(pcm(1_200))
        await rig.rec.wait_type("speech_start")
        await rig.unity({"type": "interrupt"})
        await rig.rec.wait_type("stop_speaking")
        await conn.wait_type("session.instructions.append")
        assert conn.of_type("session.instructions.append")[0]["content"] == INTERRUPT_TEXT

        # Lo que siga llegando de esa respuesta no suena.
        await conn.audio(pcm(1_200))
        await asyncio.sleep(0.05)
        assert len(rig.rec.of_type("speech_start")) == 1
        # Tras un silencio, la siguiente voz es una frase nueva.
        await asyncio.sleep(0.25)
        await conn.audio(pcm(1_200))
        await rig.rec.wait_type("speech_start", count=2)
        assert rig.rec.of_type("speech_start")[1]["utterance_id"] == 2


async def test_reconecta_si_se_cae_la_sesion(tmp_path: Path) -> None:
    server = FakeLiveServer(drop_after_start=True)
    async with make_rig(tmp_path, server=server):
        await server.wait_conn(3)
        assert server.attempts >= 3


async def test_si_gpt_live_rechaza_la_sesion_avisa_y_reintenta(tmp_path: Path) -> None:
    server = FakeLiveServer(reject=True)
    async with make_rig(tmp_path, server=server) as rig:
        await rig.rec.wait_type("error")
        message = rig.rec.of_type("error")[0]["message"]
        assert "model_not_found" in message
        await wait_until(lambda: server.attempts >= 2)
        assert not rig.engine.connected


async def test_tras_un_rato_sin_nadie_abre_una_sesion_nueva(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine_module, "RESPONSE_WAIT_S", 0.1)
    async with make_rig(tmp_path, idle_reset=0.3) as rig:
        conn = await rig.conn()
        await conn.hear("Hola")
        await conn.wait_type("session.close", limit=4.0)
        await rig.conn(2)
        assert rig.rec.of_type("hide_image")


async def test_sin_conversacion_no_renueva_la_sesion(tmp_path: Path) -> None:
    async with make_rig(tmp_path, idle_reset=0.1) as rig:
        conn = await rig.conn()
        await asyncio.sleep(0.4)
        assert not conn.of_type("session.close")


# ---------------------------------------------------------------------------
# Animación de stand
# ---------------------------------------------------------------------------


async def test_el_numero_del_stand_va_como_commentary_y_suena_como_ambient(tmp_path: Path) -> None:
    showcase = Showcase(phrases=["¡Pasa y pregúntame lo que quieras!"], songs=[], gesture_chance=0)
    settings = ShowcaseSettings(
        enabled=True, first_delay_seconds=0.0, interval_min_seconds=60, interval_max_seconds=60
    )
    async with make_rig(tmp_path, showcase=showcase, showcase_settings=settings) as rig:
        conn = await rig.conn()
        await conn.wait_type("session.commentary.append")
        content = conn.of_type("session.commentary.append")[0]["content"]
        assert "¡Pasa y pregúntame lo que quieras!" in content
        await conn.audio(pcm(1_200))
        await rig.rec.wait_type("speech_start")
        assert rig.rec.of_type("speech_start")[0]["ambient"] is True
        await rig.rec.wait_type("speech_end")
        assert "speaking" not in rig.rec.states()


async def test_un_baile_del_stand_avisa_a_unity_antes_de_pedir_la_voz(tmp_path: Path) -> None:
    showcase = Showcase(phrases=[], songs=["La la la"], dance_chance=1.0)
    settings = ShowcaseSettings(
        enabled=True, first_delay_seconds=0.0, interval_min_seconds=60, interval_max_seconds=60
    )
    async with make_rig(tmp_path, showcase=showcase, showcase_settings=settings) as rig:
        conn = await rig.conn()
        await conn.wait_type("session.commentary.append")
        attention = rig.rec.of_type("attention")
        assert attention and attention[0]["category"] == ATTENTION_DANCE


async def test_sin_animacion_de_stand_no_pide_nada(tmp_path: Path) -> None:
    showcase = Showcase(phrases=["Hola"], songs=[], gesture_chance=0)
    settings = ShowcaseSettings(enabled=False, first_delay_seconds=0.0)
    async with make_rig(tmp_path, showcase=showcase, showcase_settings=settings) as rig:
        conn = await rig.conn()
        await asyncio.sleep(0.3)
        assert not conn.of_type("session.commentary.append")


# ---------------------------------------------------------------------------
# Sesiones cortas: sonia check y sonia say
# ---------------------------------------------------------------------------


async def test_probe_session_abre_y_cierra(tmp_path: Path) -> None:
    server = FakeLiveServer()
    async with running(server) as connect:
        result = await probe_session(make_settings(tmp_path).live, connect=connect)
    assert result.session_id == "sess_1"
    assert result.voice == "marin"
    assert result.expires_in_s is not None and result.expires_in_s > 3000
    assert server.conns[0].of_type("session.close")


async def test_speak_text_devuelve_la_voz_de_gpt_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(oneshot_module, "SAY_END_GAP_S", 0.2)
    server = FakeLiveServer()

    async def react(conn: FakeConn, message: dict[str, Any]) -> None:
        if message["type"] == "session.commentary.append":
            # Como la API real: silencio antes y después de la voz.
            await conn.audio(pcm(2_400, 0))
            await conn.audio(pcm(2_400, 700))
            await conn.audio(pcm(2_400, 700))
            for _ in range(3):
                await conn.audio(pcm(2_400, 0))

    server.on_message = react
    async with running(server) as connect:
        audio = await speak_text(make_settings(tmp_path).live, "Hola", connect=connect)
    # Sin el silencio de delante y con solo una cola corta detrás.
    assert audio.startswith(pcm(4_800, 700))
    assert len(audio) - len(pcm(4_800, 700)) <= int(RATE * 0.15) * 2
    request = server.conns[0].of_type("session.commentary.append")[0]["content"]
    assert request == "Hola"
    assert server.conns[0].of_type("session.input_audio.append")  # silencio de fondo


async def test_speak_text_corta_lo_que_gpt_live_anade_tras_el_texto(tmp_path: Path) -> None:
    # Pasó de verdad: tras un saludo grabado se puso a anunciar una charla inventada.
    server = FakeLiveServer()

    async def react(conn: FakeConn, message: dict[str, Any]) -> None:
        if message["type"] == "session.commentary.append":
            await conn.say("Hoy se habla de tecnología.")
            for _ in range(4):
                await conn.audio(pcm(2_400, 700))
            for _ in range(6):  # pausa de 0,6 s: menos que SAY_END_GAP_S
                await conn.audio(pcm(2_400, 0))
            await conn.say(" Tenemos una charla sobre inteligencia artificial.")
            for _ in range(10):
                await conn.audio(pcm(2_400, 900))
            for _ in range(20):
                await conn.audio(pcm(2_400, 0))

    server.on_message = react
    async with running(server) as connect:
        audio = await speak_text(
            make_settings(tmp_path).live, "Hoy se habla de tecnología.", connect=connect
        )
    assert audio.startswith(pcm(9_600, 700))
    assert pcm(2_400, 900) not in audio  # nada de la charla inventada


async def test_speak_text_rechaza_una_lectura_demasiado_larga(tmp_path: Path) -> None:
    # Sin transcripción no se sabe dónde acaba el texto: manda el tope de duración.
    server = FakeLiveServer()

    async def react(conn: FakeConn, message: dict[str, Any]) -> None:
        if message["type"] == "session.commentary.append":
            for _ in range(40):  # 4 s de voz para un "Hola"
                await conn.audio(pcm(2_400, 700))
            for _ in range(20):
                await conn.audio(pcm(2_400, 0))

    server.on_message = react
    async with running(server) as connect:
        with pytest.raises(LiveError, match="no se limitó a leer"):
            await speak_text(make_settings(tmp_path).live, "Hola", connect=connect)


def test_la_cache_descarta_una_frase_grabada_demasiado_larga(tmp_path: Path) -> None:
    import wave

    from sonia.live.voicecache import VoiceCache

    settings = make_settings(tmp_path)
    cache = VoiceCache(tmp_path / "voice", settings.live)
    good, bad = "¡Hola!", "¡Bienvenido a la Biblioteca Nacional!"
    for text, seconds in ((good, 1.0), (bad, 13.85)):
        path = cache.path_for(text)
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(RATE)
            wav.writeframes(pcm(int(RATE * seconds), 700))
    assert cache.get(good) is not None
    assert cache.missing([good, bad]) == [bad]
    assert cache.get(bad) is None
    assert not cache.path_for(bad).exists()  # se borra para volver a grabarla


def test_narrador_recorta_y_normaliza(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = FakeVisionLLM("  Dos   personas\n con gorras. ")
    text = asyncio.run(VisionNarrator(llm).describe(Frame(data=b"x")))
    assert text == "Dos personas con gorras."


# ---------------------------------------------------------------------------
# Casos que encontró la revisión
# ---------------------------------------------------------------------------


def call_item(name: str = "hide_image", call_id: str = "call_1") -> dict[str, Any]:
    return {
        "type": "response.output_item.done",
        "item": {"type": "function_call", "call_id": call_id, "name": name, "arguments": "{}"},
    }


async def test_un_evento_tardio_no_resucita_una_tarea_cerrada(tmp_path: Path) -> None:
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.response_event({"type": "response.created"})
        await conn.response_event({"type": "response.output_text.delta", "delta": "Listo."})
        await conn.response_event({"type": "response.completed"})
        await wait_until(lambda: not rig.engine._delegations)
        # Eventos posteriores de la misma tarea, con su id o sin él.
        await conn.response_event({"type": "response.output_text.delta", "delta": "x"})
        await conn.response_event({"type": "response.output_text.delta", "delta": "x"}, None)
        await asyncio.sleep(0.1)
        assert not rig.engine._delegations


async def test_un_error_a_un_comando_del_backend_cierra_la_tarea(tmp_path: Path) -> None:
    server = FakeLiveServer()

    async def reject_items(conn: FakeConn, message: dict[str, Any]) -> None:
        if message["type"] == "response.item.create":
            await conn.send(
                {
                    "type": "error",
                    "event_id": "err",
                    "error": {
                        "type": "invalid_request_error",
                        "code": "invalid_item",
                        "message": "no",
                        "client_event_id": message["event_id"],
                    },
                }
            )

    server.on_message = reject_items
    async with make_rig(tmp_path, server=server) as rig:
        conn = await rig.conn()
        await conn.response_event(call_item())
        await conn.wait_type("response.item.create")
        await wait_until(lambda: not rig.engine._delegations)
        assert not rig.engine._command_owner


async def test_una_accion_sin_id_de_delegacion_tambien_continua(tmp_path: Path) -> None:
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.response_event(call_item(), None)
        await conn.response_event({"type": "response.completed"}, None)
        await conn.wait_type("response.create")


async def test_tras_un_interrupt_no_se_espera_el_audio_que_unity_ya_tiro(tmp_path: Path) -> None:
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.audio(pcm(RATE * 10))  # 10 s de voz de golpe
        await rig.rec.wait_type("speech_start")
        await rig.unity({"type": "interrupt"})
        await rig.rec.wait_type("stop_speaking")
        await asyncio.sleep(0.25)
        await conn.audio(pcm(2_400))  # 0,1 s
        await rig.rec.wait_type("speech_end")
        # Sin playback_done de Unity, la espera es la de 0,1 s más el margen, no 10 s.
        await wait_until(lambda: not rig.engine._audible, limit=2.5)


async def test_un_cierre_ordenado_del_servidor_no_reconecta_sin_freno(tmp_path: Path) -> None:
    server = FakeLiveServer(close_after_start="expired")
    async with make_rig(
        tmp_path, server=server, reconnect_min_seconds=0.3, reconnect_max_seconds=0.3
    ):
        await server.wait_conn(1)
        await asyncio.sleep(0.8)
        assert server.attempts <= 4
