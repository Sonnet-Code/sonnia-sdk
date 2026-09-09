"""Backend de síntesis de voz PROVISIONAL contra la API de Gemini.

Este módulo es la excepción consciente al principio de "todo corre local" del
proyecto (ver ``docs/decisiones/006-tts-provisional-gemini.md``): mientras no
haya GPU para ejecutar OmniVoice, la voz de Sonia se genera en la nube. Se
retira en cuanto llegue el hardware, y como implementa el protocolo
:class:`~sonia.types.TextToSpeech` el cambio es sustituir una línea en la
factoría.

Ofrece dos modos, seleccionables con ``TTS_GEMINI_MODE``:

``live``
    Live API por WebSocket crudo (sin el SDK de Google, solo ``websockets``).
    La sesión se abre una vez y se reutiliza frase tras frase, así que el coste
    de handshake se paga al arrancar y no en cada turno. El audio llega en
    streaming, que es lo que nos interesa para la latencia.

``tts``
    Modelos TTS de Gemini por REST (endpoint ``/v1beta/interactions``). Leen el
    texto literalmente, sin el riesgo de que un modelo conversacional decida
    responder en lugar de leer. Algo más de latencia, más fidelidad.

Protocolo implementado (documentación consultada el 9 de septiembre de 2026):

- https://ai.google.dev/gemini-api/docs/live-api/get-started-websocket
  URL del WebSocket y forma de pasar la clave como parámetro ``key``.
- https://ai.google.dev/api/live
  Esquema de ``BidiGenerateContentSetup`` (``responseModalities`` y
  ``speechConfig`` viven DENTRO de ``generationConfig``, no en la raíz del
  ``setup``), ``BidiGenerateContentClientContent`` (``turns`` + ``turnComplete``),
  ``BidiGenerateContentServerContent`` (``modelTurn``, ``generationComplete``,
  ``turnComplete``, ``interrupted``), ``GoAway`` (``timeLeft``) y
  ``SessionResumptionUpdate``.
- https://ai.google.dev/gemini-api/docs/live-guide
  Voces prebuilt, ``speechConfig.voiceConfig.prebuiltVoiceConfig.voiceName`` y
  el límite de 15 minutos de las sesiones de solo audio.
- https://ai.google.dev/gemini-api/docs/speech-generation y
  https://ai.google.dev/gemini-api/docs/interactions/speech-generation
  Modelos TTS, petición a ``/v1beta/interactions`` (``input``,
  ``response_format``, ``generation_config.speech_config``), streaming por SSE
  con ``stream: true`` y la cabecera ``Api-Revision``, catálogo de 30 voces.
- https://ai.google.dev/gemini-api/docs/models
  Identificadores vigentes de los modelos.

El audio de salida es PCM s16le mono a 24 kHz en los dos modos, que es
exactamente lo que espera Unity, así que no hay conversión salvo que la API
anuncie otra tasa en el ``mimeType`` (entonces se remuestrea).

Zonas donde la documentación no era concluyente y se eligió lo conservador:

- El esquema de la respuesta no-streaming de ``/v1beta/interactions`` solo está
  documentado a través del SDK (``interaction.output_audio.data``), así que el
  audio se busca de forma tolerante por todo el JSON en lugar de asumir una
  ruta fija.
- En modo ``tts`` el texto se envía tal cual, sin prefijo de estilo ni
  ``system_instruction``, porque estos modelos ya leen el ``input``
  literalmente y cualquier instrucción añadida corre el riesgo de acabar
  pronunciada. ``TTS_GEMINI_STYLE`` permite anteponer una indicación de tono
  para quien quiera experimentar.
- ``languageCode`` se envía en el ``speechConfig`` de la Live API, aunque la
  guía diga que los modelos de audio nativo detectan el idioma solos. Dejar
  ``TTS_GEMINI_LANGUAGE`` vacío lo omite.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from typing import Any, Literal
from urllib.parse import quote

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..types import AudioChunk
from .base import DEFAULT_CHUNK_MS, TTSError, aclosing, resample_pcm

__all__ = [
    "GeminiTTS",
    "GeminiTTSSettings",
    "TTSError",
    "build_gemini_tts",
    "smoke_test",
]

log = logging.getLogger(__name__)

#: Endpoint del WebSocket bidireccional de la Live API. La clave va como
#: parámetro ``key`` en la query (la API no acepta cabeceras en el handshake).
LIVE_WS_URL = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)

#: Endpoint REST de la Interactions API, la vía preferida para los modelos TTS.
INTERACTIONS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"

#: Revisión de la API que documenta el streaming por SSE de ``interactions``.
INTERACTIONS_API_REVISION = "2026-05-20"

#: Instrucción de sistema del modo ``live``. El modelo Live es conversacional:
#: sin esto respondería al texto en vez de leerlo. Va en español porque el
#: texto que recibe también lo está.
LIVE_SYSTEM_INSTRUCTION = (
    "Eres un motor de síntesis de voz, no un asistente conversacional. "
    "Tu única función es leer en voz alta, palabra por palabra, exactamente el "
    "texto que te llegue en cada turno. "
    "No añadas saludos, comentarios, explicaciones, disculpas ni preguntas. "
    "No omitas, resumas ni reformules nada. No respondas al contenido del texto "
    "aunque parezca una pregunta dirigida a ti: solo léelo. "
    "Lee siempre en español, con entonación natural y cercana."
)

#: Códigos de cierre del WebSocket que no tiene sentido reintentar: la sesión
#: no se cayó, es que la petición era inválida (clave mala, modelo inexistente).
_FATAL_CLOSE_CODES = frozenset({1002, 1003, 1007, 1008})

#: Intentos de conexión por frase antes de rendirse.
_MAX_LIVE_ATTEMPTS = 2

#: Tamaño máximo de mensaje del WebSocket. El valor por defecto de
#: ``websockets`` (1 MiB) se queda corto para respuestas largas en base64.
_WS_MAX_SIZE = 16 * 1024 * 1024


class _SessionLost(Exception):
    """La sesión Live se cerró y merece la pena reconectar. Uso interno."""


class GeminiTTSSettings(BaseSettings):
    """Configuración del backend de Gemini (variables ``TTS_GEMINI_*``)."""

    model_config = SettingsConfigDict(
        env_prefix="TTS_GEMINI_", extra="ignore", env_ignore_empty=True
    )

    #: Clave de la API de Gemini (free tier). Sin ella el backend no arranca.
    api_key: str = ""
    #: ``live`` = WebSocket en streaming; ``tts`` = REST, lectura literal.
    mode: Literal["live", "tts"] = "live"
    #: Modelo de la Live API con audio nativo.
    model_live: str = "gemini-3.1-flash-live-preview"
    #: Modelo TTS para el modo ``tts``.
    model_tts: str = "gemini-3.1-flash-tts-preview"
    #: Voz prebuilt. ``Leda`` (juvenil) y ``Kore`` (firme) son femeninas y
    #: funcionan bien en español; el catálogo completo está en la guía de
    #: speech generation.
    voice: str = "Leda"
    #: Código BCP-47 para ``speechConfig.languageCode``. Vacío = no enviarlo.
    language: str = "es-ES"
    #: Tasa de muestreo de salida. La API entrega 24 kHz; si se pide otra, se
    #: remuestrea antes de trocear.
    sample_rate: int = 24_000
    #: Segundos de espera por cada mensaje del servidor o petición HTTP.
    timeout: float = 30.0
    #: Modo ``tts``: pedir el audio en streaming (SSE) en vez de de una vez.
    stream: bool = True
    #: Modo ``tts``: indicación de tono que se antepone al texto como
    #: ``"<estilo>: <texto>"``. Vacío = enviar el texto puro (recomendado).
    style: str = ""
    #: Reciclar la sesión Live pasados estos segundos. Las sesiones de solo
    #: audio caducan a los 15 minutos; se reconecta antes para que la caducidad
    #: nunca pille una frase a medias.
    session_max_seconds: float = 600.0


# ---------------------------------------------------------------------------
# Utilidades de parseo
# ---------------------------------------------------------------------------


def _pick(node: dict[str, Any], *names: str) -> Any:
    """Devuelve el primer campo presente. La API usa camelCase, pero el
    endpoint de ``interactions`` documenta snake_case: se aceptan ambos."""
    for name in names:
        if name in node:
            return node[name]
    return None


def _rate_from_mime(mime: str | None) -> int | None:
    """Extrae la tasa de ``audio/pcm;rate=24000``. ``None`` si no la declara."""
    if not mime:
        return None
    for param in mime.split(";")[1:]:
        key, _, value = param.partition("=")
        if key.strip().lower() == "rate":
            try:
                return int(value.strip())
            except ValueError:
                return None
    return None


def _decode_b64(data: str) -> bytes:
    try:
        return base64.b64decode(data, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise TTSError(f"Gemini envió audio base64 ilegible: {exc}") from exc


def _iter_audio(node: Any) -> Iterator[tuple[bytes, int | None]]:
    """Recorre un JSON de respuesta y produce ``(pcm, tasa declarada)``.

    Se hace por búsqueda tolerante en vez de por una ruta fija porque la forma
    exacta de la respuesta de ``interactions`` no está documentada fuera del
    SDK: sirve igual para ``output_audio.data``, para las partes ``inlineData``
    del formato clásico y para los deltas de audio del streaming.
    """
    if isinstance(node, list):
        for item in node:
            yield from _iter_audio(item)
        return
    if not isinstance(node, dict):
        return

    inline = _pick(node, "inlineData", "inline_data")
    if isinstance(inline, dict):
        yield from _iter_audio(inline)

    data = node.get("data")
    if isinstance(data, str) and data:
        mime = _pick(node, "mimeType", "mime_type")
        kind = node.get("type")
        is_audio = (isinstance(mime, str) and mime.startswith("audio/")) or kind == "audio"
        if is_audio:
            rate = _pick(node, "sampleRate", "sample_rate")
            rate = (
                rate
                if isinstance(rate, int)
                else _rate_from_mime(mime if isinstance(mime, str) else None)
            )
            yield _decode_b64(data), rate
            return

    for key, value in node.items():
        # ``data`` ya se ha mirado arriba; el resto puede anidar audio.
        if key not in ("data", "inlineData", "inline_data") and isinstance(value, dict | list):
            yield from _iter_audio(value)


def _error_message(body: str) -> str:
    """Saca el ``error.message`` de una respuesta de error de Google."""
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return body.strip()[:300]
    if isinstance(parsed, dict):
        error = parsed.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str):
                return message
    return body.strip()[:300]


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------

#: Firma del inyector de conexiones WebSocket usado por los tests.
WSConnect = Callable[[str], Awaitable[Any]]


class GeminiTTS:
    """Implementa :class:`~sonia.types.TextToSpeech` sobre la API de Gemini."""

    def __init__(
        self,
        settings: GeminiTTSSettings,
        *,
        ws_connect: WSConnect | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        chunk_ms: int = DEFAULT_CHUNK_MS,
    ) -> None:
        self._settings = settings
        self._ws_connect = ws_connect
        self._transport = transport
        self._chunk_ms = max(1, chunk_ms)
        self._client: httpx.AsyncClient | None = None
        self._ws: Any = None
        #: ``time.monotonic()`` a partir del cual la sesión se recicla.
        self._ws_deadline = 0.0
        #: El servidor avisó con ``goAway``: se usa esta frase y se tira.
        self._ws_expiring = False
        #: La sesión Live es una sola: no se pueden sintetizar dos frases a la vez.
        self._lock = asyncio.Lock()

    @property
    def sample_rate(self) -> int:
        return self._settings.sample_rate

    @property
    def _bytes_per_chunk(self) -> int:
        """Bytes de un chunk de ``chunk_ms`` (siempre múltiplo de 2)."""
        samples = max(1, (self.sample_rate * self._chunk_ms) // 1000)
        return samples * 2

    # -- API pública -------------------------------------------------------

    async def synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        """Sintetiza ``text`` y produce chunks PCM s16le de ``chunk_ms``.

        El generador se cierra de forma determinista al cancelar el turno
        (``aclose``): cada nivel se envuelve en :func:`~sonia.tts.base.aclosing` para
        que la limpieza — liberar el lock y marcar la sesión Live para reciclar —
        ocurra antes de que empiece la frase siguiente, no cuando el recolector
        de basura se acuerde.
        """
        clean = text.strip()
        if not clean:
            yield AudioChunk(pcm=b"", sample_rate=self.sample_rate, is_last=True)
            return

        async with self._lock:
            if self._settings.mode == "live":
                source = self._live_pcm(clean)
            else:
                source = self._rest_pcm(clean)
            async with aclosing(self._chunked(source)) as chunks:
                async for chunk in chunks:
                    yield chunk

    async def warmup(self) -> None:
        """Abre la sesión (o hace una síntesis mínima) para pagar la latencia
        de arranque antes de la demo. Nunca lanza: el stand debe seguir."""
        try:
            if self._settings.mode == "live":
                async with self._lock:
                    await self._ensure_session()
            else:
                async for _ in self.synthesize("Hola."):
                    pass
        except Exception:  # pragma: no cover - depende de la API real
            log.exception("Falló el warmup del TTS de Gemini (modo %s)", self._settings.mode)

    async def close(self) -> None:
        """Cierra la sesión Live y el cliente HTTP."""
        await self._drop_session()
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def aclose(self) -> None:
        """Alias de :meth:`close` (el resto de backends usan este nombre)."""
        await self.close()

    # -- Troceado ----------------------------------------------------------

    async def _chunked(self, source: AsyncIterator[bytes]) -> AsyncIterator[AudioChunk]:
        """Acumula el PCM que llega y lo reparte en chunks de tamaño fijo.

        El último chunk lleva ``is_last=True`` aunque salga corto o vacío: el
        orquestador lo usa para saber que la frase terminó.
        """
        buffer = bytearray()
        size = self._bytes_per_chunk
        async with aclosing(source):
            async for pcm in source:
                buffer += pcm
                while len(buffer) >= size:
                    yield AudioChunk(
                        pcm=bytes(buffer[:size]), sample_rate=self.sample_rate, is_last=False
                    )
                    del buffer[:size]
        yield AudioChunk(pcm=bytes(buffer), sample_rate=self.sample_rate, is_last=True)

    def _to_output_rate(self, pcm: bytes, rate: int | None) -> bytes:
        if not pcm or rate is None or rate == self.sample_rate:
            return pcm
        return resample_pcm(pcm, rate, self.sample_rate)

    # -- Modo live ---------------------------------------------------------

    async def _live_pcm(self, text: str) -> AsyncIterator[bytes]:
        """Sintetiza por la Live API, reconectando si la sesión se cae.

        Solo se reintenta mientras no se haya emitido audio: repetir una frase
        a medio reproducir sonaría peor que cortarla.
        """
        produced = False
        for attempt in range(1, _MAX_LIVE_ATTEMPTS + 1):
            try:
                turn = self._live_turn(text)
                async with aclosing(turn):
                    async for pcm in turn:
                        produced = True
                        yield pcm
                return
            except _SessionLost as exc:
                await self._drop_session()
                if produced:
                    log.warning("Sesión Live cortada a media frase (%s). Se corta el audio.", exc)
                    return
                if attempt >= _MAX_LIVE_ATTEMPTS:
                    raise TTSError(f"No se pudo mantener la sesión Live de Gemini: {exc}") from exc
                log.info("Sesión Live perdida (%s). Reconectando…", exc)

    async def _live_turn(self, text: str) -> AsyncIterator[bytes]:
        """Un turno completo: envía la frase y consume el audio hasta el final.

        Si el turno no llega a su ``turnComplete`` —cancelación por barge-in,
        error o un ``interrupted`` del servidor— la sesión queda con mensajes a
        medio consumir: el audio pendiente se lo comería la frase siguiente y
        Sonia diría una cosa mientras suena otra. Por eso el ``finally`` marca
        la sesión para reciclar; ``_ensure_session`` abrirá una limpia.
        """
        ws = await self._ensure_session()
        payload = {
            "clientContent": {
                "turns": [{"role": "user", "parts": [{"text": text}]}],
                "turnComplete": True,
            }
        }
        try:
            await ws.send(json.dumps(payload))
        except Exception as exc:
            raise _SessionLost(f"no se pudo enviar la frase: {exc}") from exc

        completed = False
        try:
            while True:
                message = await self._recv_json(ws)

                if _pick(message, "goAway", "go_away") is not None:
                    # El servidor va a cerrar. Se termina este turno y se recicla.
                    log.info("Gemini Live avisó de cierre inminente (goAway).")
                    self._ws_expiring = True

                server_content = _pick(message, "serverContent", "server_content")
                if not isinstance(server_content, dict):
                    continue

                model_turn = _pick(server_content, "modelTurn", "model_turn")
                if isinstance(model_turn, dict):
                    for pcm, rate in _iter_audio(model_turn.get("parts", [])):
                        if pcm:
                            yield self._to_output_rate(pcm, rate)

                if server_content.get("interrupted"):
                    # No sabemos qué queda en la cola del socket: se recicla.
                    log.info("Gemini Live marcó el turno como interrumpido.")
                    return
                if server_content.get("turnComplete") or server_content.get("turn_complete"):
                    completed = True
                    return
        finally:
            if not completed:
                self._ws_expiring = True

    async def _recv_json(self, ws: Any) -> dict[str, Any]:
        """Espera un mensaje del servidor y lo decodifica, con timeout."""
        from websockets.exceptions import ConnectionClosed

        try:
            async with asyncio.timeout(self._settings.timeout):
                raw = await ws.recv()
        except TimeoutError as exc:
            raise TTSError(f"Gemini Live no respondió en {self._settings.timeout:g} s.") from exc
        except ConnectionClosed as exc:
            raise self._closed_error(exc) from exc

        if isinstance(raw, bytes | bytearray):
            raw = bytes(raw).decode("utf-8", errors="replace")
        try:
            message = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TTSError(f"Gemini Live envió un mensaje que no es JSON: {exc}") from exc
        if not isinstance(message, dict):
            raise TTSError("Gemini Live envió un mensaje JSON que no es un objeto.")
        return message

    def _closed_error(self, exc: Exception) -> Exception:
        """Traduce un cierre del WebSocket a error fatal o a sesión perdida."""
        code: int | None = None
        reason = ""
        for attr in ("rcvd", "sent"):
            frame = getattr(exc, attr, None)
            if frame is not None:
                code = getattr(frame, "code", None)
                reason = getattr(frame, "reason", "") or ""
                break

        if code in _FATAL_CLOSE_CODES:
            return TTSError(
                f"Gemini Live rechazó la sesión (cierre {code}: {reason or 'sin motivo'}). "
                "Suele ser una TTS_GEMINI_API_KEY inválida o sin acceso al modelo "
                f"{self._settings.model_live!r}."
            )
        return _SessionLost(f"cierre {code or 'desconocido'}: {reason or 'sin motivo'}")

    async def _ensure_session(self) -> Any:
        """Devuelve la sesión Live viva, abriéndola o reciclándola si toca."""
        if self._ws is not None and not self._ws_expiring and time.monotonic() < self._ws_deadline:
            return self._ws
        if self._ws is not None:
            await self._drop_session()
        ws = await self._open_session()
        self._ws = ws
        self._ws_deadline = time.monotonic() + self._settings.session_max_seconds
        self._ws_expiring = False
        return ws

    async def _open_session(self) -> Any:
        """Conecta, envía el ``setup`` y espera el ``setupComplete``."""
        connect = self._ws_connect or self._default_connect
        if self._ws_connect is None and not self._settings.api_key:
            raise TTSError("Falta TTS_GEMINI_API_KEY para usar el TTS de Gemini.")

        url = f"{LIVE_WS_URL}?key={quote(self._settings.api_key, safe='')}"
        try:
            ws = await connect(url)
        except Exception as exc:
            raise self._handshake_error(exc) from exc

        try:
            await ws.send(json.dumps(self._setup_payload()))
            message = await self._recv_json(ws)
        except (TTSError, _SessionLost):
            await _safe_close(ws)
            raise
        except Exception as exc:
            # Un cierre durante el setup (clave inválida, modelo inexistente)
            # llega aquí como ConnectionClosed: se traduce a algo legible.
            await _safe_close(ws)
            raise self._closed_error(exc) from exc

        if _pick(message, "setupComplete", "setup_complete") is None:
            await _safe_close(ws)
            raise TTSError(
                f"Gemini Live no confirmó el setup; respondió: {json.dumps(message)[:300]}"
            )
        log.info(
            "Sesión Live abierta con %s (voz %s).", self._settings.model_live, self._settings.voice
        )
        return ws

    def _setup_payload(self) -> dict[str, Any]:
        """Mensaje ``setup``, el primero y único de configuración de la sesión."""
        settings = self._settings
        speech_config: dict[str, Any] = {
            "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": settings.voice}}
        }
        if settings.language:
            speech_config["languageCode"] = settings.language

        model = settings.model_live
        if not model.startswith("models/"):
            model = f"models/{model}"

        return {
            "setup": {
                "model": model,
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": speech_config,
                },
                "systemInstruction": {"parts": [{"text": LIVE_SYSTEM_INSTRUCTION}]},
            }
        }

    async def _default_connect(self, url: str) -> Any:
        """Conexión real. Se importa aquí para no cargar ``websockets`` al importar."""
        from websockets.asyncio.client import connect

        return await connect(url, max_size=_WS_MAX_SIZE, open_timeout=self._settings.timeout)

    def _handshake_error(self, exc: Exception) -> Exception:
        """Traduce un fallo de handshake a un error legible."""
        status = None
        response = getattr(exc, "response", None)
        if response is not None:
            status = getattr(response, "status_code", None)
        if status in (400, 401, 403):
            return TTSError(
                f"Gemini Live rechazó la conexión (HTTP {status}). "
                "Revisa TTS_GEMINI_API_KEY y que la clave tenga acceso al modelo "
                f"{self._settings.model_live!r}."
            )
        if status is not None:
            return TTSError(f"Gemini Live devolvió HTTP {status} al conectar.")
        if isinstance(exc, TTSError):
            return exc
        return _SessionLost(f"no se pudo conectar: {exc}")

    async def _drop_session(self) -> None:
        ws, self._ws = self._ws, None
        self._ws_expiring = False
        self._ws_deadline = 0.0
        if ws is not None:
            await _safe_close(ws)

    # -- Modo tts (REST) ---------------------------------------------------

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                transport=self._transport,
                timeout=self._settings.timeout,
                headers={
                    "x-goog-api-key": self._settings.api_key,
                    "Content-Type": "application/json",
                },
            )
        return self._client

    def _rest_payload(self, text: str) -> dict[str, Any]:
        settings = self._settings
        prompt = f"{settings.style}: {text}" if settings.style else text
        payload: dict[str, Any] = {
            "model": settings.model_tts,
            "input": prompt,
            "response_format": {"type": "audio"},
            "generation_config": {"speech_config": [{"voice": settings.voice}]},
        }
        if settings.stream:
            payload["stream"] = True
        return payload

    def _rest_error(self, status: int, body: str) -> TTSError:
        detail = _error_message(body)
        if status in (400, 401, 403):
            return TTSError(
                f"Gemini rechazó la petición de TTS (HTTP {status}). "
                f"Revisa TTS_GEMINI_API_KEY y el modelo {self._settings.model_tts!r}. "
                f"Detalle: {detail}"
            )
        if status == 429:
            return TTSError(f"Gemini agotó la cuota del free tier (HTTP 429). Detalle: {detail}")
        return TTSError(f"Gemini devolvió HTTP {status} al sintetizar. Detalle: {detail}")

    async def _rest_pcm(self, text: str) -> AsyncIterator[bytes]:
        if self._transport is None and not self._settings.api_key:
            raise TTSError("Falta TTS_GEMINI_API_KEY para usar el TTS de Gemini.")
        try:
            if self._settings.stream:
                async for pcm in self._rest_stream(text):
                    yield pcm
            else:
                async for pcm in self._rest_single(text):
                    yield pcm
        except httpx.TimeoutException as exc:
            raise TTSError(
                f"Gemini no respondió en {self._settings.timeout:g} s al sintetizar."
            ) from exc
        except httpx.HTTPError as exc:
            raise TTSError(f"Error de red hablando con Gemini: {exc}") from exc

    async def _rest_single(self, text: str) -> AsyncIterator[bytes]:
        response = await self._ensure_client().post(INTERACTIONS_URL, json=self._rest_payload(text))
        if response.status_code >= 400:
            raise self._rest_error(response.status_code, response.text)
        try:
            body = response.json()
        except ValueError as exc:
            raise TTSError(f"Gemini devolvió una respuesta que no es JSON: {exc}") from exc
        for pcm, rate in _iter_audio(body):
            if pcm:
                yield self._to_output_rate(pcm, rate)

    async def _rest_stream(self, text: str) -> AsyncIterator[bytes]:
        """Consume el SSE de ``interactions``: eventos ``step.delta`` con audio.

        Solo se emiten los deltas. El evento final (``interaction.completed``)
        repite la interacción entera, así que se guarda aparte y solo se usa si
        no llegó ningún delta, para no duplicar el audio.
        """
        client = self._ensure_client()
        headers = {"Api-Revision": INTERACTIONS_API_REVISION, "Accept": "text/event-stream"}
        fallback: Any = None
        produced = False

        async with client.stream(
            "POST", INTERACTIONS_URL, json=self._rest_payload(text), headers=headers
        ) as response:
            if response.status_code >= 400:
                body = await response.aread()
                raise self._rest_error(response.status_code, body.decode("utf-8", "replace"))

            async for line in response.aiter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                raw = line[len("data:") :].strip()
                if not raw or raw == "[DONE]":
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    log.debug("Evento SSE de Gemini ilegible, se ignora: %.120s", raw)
                    continue
                if not isinstance(event, dict):
                    continue

                kind = _pick(event, "event_type", "eventType")
                if kind == "error":
                    raise TTSError(f"Gemini abortó la síntesis: {_error_message(raw)}")
                if kind is not None and kind != "step.delta":
                    if kind in ("interaction.completed", "interaction.incomplete"):
                        fallback = event
                    continue

                delta = event.get("delta", event)
                for pcm, rate in _iter_audio(delta):
                    if pcm:
                        produced = True
                        yield self._to_output_rate(pcm, rate)

        if not produced and fallback is not None:
            for pcm, rate in _iter_audio(fallback):
                if pcm:
                    yield self._to_output_rate(pcm, rate)


async def _safe_close(ws: Any) -> None:
    """Cierra una conexión sin propagar errores (ya estamos en el camino malo)."""
    try:
        await ws.close()
    except Exception:  # pragma: no cover - cerrar nunca debe romper la demo
        log.debug("Error cerrando la sesión Live de Gemini", exc_info=True)


def build_gemini_tts() -> GeminiTTS:
    """Construye el backend leyendo las variables ``TTS_GEMINI_*`` del entorno."""
    return GeminiTTS(GeminiTTSSettings())


# ---------------------------------------------------------------------------
# Prueba manual
# ---------------------------------------------------------------------------


async def smoke_test(text: str = "Hola, soy Sonia.") -> None:
    """Sintetiza ``text`` y lo guarda como ``sonia_gemini.wav`` en el cwd.

    Pensado para probar la integración en cuanto haya clave::

        export TTS_GEMINI_API_KEY=...
        uv run --no-sync python -m sonia.tts.gemini "Hola desde el stand"
    """
    import wave

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config = GeminiTTSSettings()
    tts = GeminiTTS(config)
    started = time.monotonic()
    first_chunk_at: float | None = None
    pieces: list[bytes] = []
    try:
        async for chunk in tts.synthesize(text):
            if first_chunk_at is None and chunk.pcm:
                first_chunk_at = time.monotonic() - started
            pieces.append(chunk.pcm)
    finally:
        await tts.close()

    pcm = b"".join(pieces)
    path = "sonia_gemini.wav"
    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(tts.sample_rate)
        wav.writeframes(pcm)

    seconds = len(pcm) / 2 / tts.sample_rate
    print(f"modo={config.mode} voz={config.voice}")
    print(f"primer chunk: {first_chunk_at:.2f} s" if first_chunk_at else "no llegó audio")
    print(f"audio: {seconds:.2f} s ({len(pcm)} bytes) → {path}")


if __name__ == "__main__":
    import sys

    asyncio.run(smoke_test(sys.argv[1] if len(sys.argv) > 1 else "Hola, soy Sonia."))
