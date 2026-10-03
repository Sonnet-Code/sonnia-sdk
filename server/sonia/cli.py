"""Línea de comandos de Sonia.

Subcomandos:

- ``sonia run``: demo completa (micrófono, cámara, modelo, voz, WebSocket).
- ``sonia chat``: conversar por texto desde la consola, sin micrófono ni cámara.
  Con ``--speak`` reproduce el audio localmente con sounddevice.
- ``sonia say "texto"``: sintetiza y reproduce (o guarda a WAV con ``--out``).
- ``sonia check``: comprueba micrófono, cámara, voz, modelo y galería, e
  imprime OK/FALLO por línea.
- ``sonia mcp``: arranca solo el servidor MCP con las acciones.

``VOICE_ENGINE`` elige el motor: ``live`` (GPT-Live voz a voz, ADR 007) o
``pipeline`` (VAD + STT + LLM + TTS). ``run``, ``chat``, ``say`` y ``check``
funcionan con los dos.

Todas las dependencias pesadas (sounddevice, torch, cv2, mcp...) se importan
dentro de las funciones que las usan: importar este módulo es barato.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
import sys
import time
import wave
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sonia import __version__
from sonia.actions import Gallery, build_default_registry
from sonia.actions.registry import ActionRegistry
from sonia.audio.capture import list_input_devices, resolve_input_device
from sonia.config import Settings, load_settings
from sonia.glossary import load_glossary
from sonia.live.audio import silence_blocks
from sonia.live.engine import LiveEngine
from sonia.live.oneshot import probe_session, speak_text
from sonia.live.vision import VisionNarrator
from sonia.live.voicecache import VoiceCache
from sonia.llm.client import LLMClient
from sonia.mcp.server import MCPServer
from sonia.mcp.server import is_available as mcp_available
from sonia.orchestrator import Orchestrator
from sonia.panel.control import StandControl
from sonia.panel.logs import LogBuffer
from sonia.persona import DEFAULT_KNOWLEDGE_DIR
from sonia.stt import build_stt
from sonia.stt.mock import MockSTT
from sonia.tts import build_tts
from sonia.types import ActionContext, AudioChunk, CameraSource, TextToSpeech
from sonia.vision.camera import build_camera
from sonia.vision.policy import VisionPolicy
from sonia.ws import protocol as p
from sonia.ws.hub import Hub, MessageCallback

__all__ = ["build_parser", "main", "run_checks"]

logger = logging.getLogger(__name__)

#: Texto que se sintetiza en ``sonia check`` para medir el TTS.
CHECK_TTS_TEXT = "Hola"

#: Palabras que terminan ``sonia chat``.
_CHAT_EXIT_WORDS = frozenset({"salir", "exit", "quit"})

#: Cuánto espera ``sonia chat`` a que Sonia termine de hablar antes de salir.
CHAT_EXIT_GRACE_S = 30.0

#: Espera antes de reabrir el micrófono cuando falla o deja de entregar audio.
MIC_RETRY_DELAY_S = 5.0

#: JPEG gris de 16x16 para comprobar que el endpoint acepta ``image_url``.
#: Va embebido para que ``sonia check`` no dependa del extra de la cámara.
_PROBE_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAA0JCgsKCA0LCgsODg0PEyAVExISEyccHhcgLikxMC4p"
    "LSwzOko+MzZGNywtQFdBRkxOUlNSMj5aYVpQYEpRUk//2wBDAQ4ODhMREyYVFSZPNS01T09PT09P"
    "T09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT0//wAARCAAQABADASIA"
    "AhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQA"
    "AAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3"
    "ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWm"
    "p6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEA"
    "AwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSEx"
    "BhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElK"
    "U1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3"
    "uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwAooooA"
    "/9k="
)


# ---------------------------------------------------------------------------
# Utilidades comunes
# ---------------------------------------------------------------------------


def configure_logging(level: str) -> None:
    """Configura el logging raíz con el nivel de ``LOG_LEVEL``."""
    numeric = logging.getLevelName(level.upper())
    if not isinstance(numeric, int):
        numeric = logging.INFO
    logging.basicConfig(
        level=numeric,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Estas librerías son muy habladoras en DEBUG y no aportan a la demo.
    for noisy in ("websockets", "httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(max(numeric, logging.INFO))


def _run(coro: Coroutine[Any, Any, int]) -> int:
    """Ejecuta una corrutina principal con salida limpia por Ctrl+C o SIGTERM."""

    async def guarded() -> int:
        task = asyncio.current_task()
        assert task is not None
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError, RuntimeError):
                loop.add_signal_handler(sig, task.cancel)
        try:
            return await coro
        except asyncio.CancelledError:
            print("\nSaliendo.", file=sys.stderr)
            return 0

    try:
        return asyncio.run(guarded())
    except KeyboardInterrupt:
        print("\nSaliendo.", file=sys.stderr)
        return 0


async def _warmup(name: str, fn: Callable[[], Awaitable[Any]] | None) -> None:
    """Precalienta un componente sin dejar que un fallo tumbe el arranque."""
    if fn is None:
        return
    started = time.monotonic()
    try:
        await fn()
    except Exception as exc:
        logger.warning("El warmup de %s falló: %s", name, exc)
        return
    logger.info("%s listo en %.1f s", name, time.monotonic() - started)


async def _aclose(obj: Any) -> None:
    """Cierra un componente si expone ``aclose``/``close`` asíncronos."""
    for method in ("aclose", "close"):
        fn = getattr(obj, method, None)
        if callable(fn):
            with contextlib.suppress(Exception):
                result = fn()
                if asyncio.iscoroutine(result):
                    await result
            return


def _write_wav(path: Path, pcm: bytes, sample_rate: int) -> None:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(sample_rate)
        out.writeframes(pcm)


async def _collect_pcm(tts: TextToSpeech, text: str) -> bytes:
    return b"".join([chunk.pcm async for chunk in tts.synthesize(text)])


def _play_pcm_blocking(pcm: bytes, sample_rate: int) -> None:
    """Reproduce PCM s16le con sounddevice (bloqueante; llamar desde un hilo)."""
    import numpy as np
    import sounddevice as sd

    samples = np.frombuffer(pcm, dtype="<i2")
    sd.play(samples, sample_rate, blocking=True)


# ---------------------------------------------------------------------------
# Reproductor local y "tap" de consola para `sonia chat`
# ---------------------------------------------------------------------------


class LocalPlayer:
    """Reproduce por el altavoz los chunks que irían a Unity (``chat --speak``)."""

    def __init__(self, sample_rate: int, on_done: Callable[[int], None]) -> None:
        self._sample_rate = sample_rate
        self._on_done = on_done
        self._queue: asyncio.Queue[tuple[int, AudioChunk]] = asyncio.Queue()
        self._stream: Any = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        import sounddevice as sd

        self._stream = sd.OutputStream(samplerate=self._sample_rate, channels=1, dtype="int16")
        self._stream.start()
        self._task = asyncio.create_task(self._loop(), name="local-player")

    def enqueue(self, utterance_id: int, chunk: AudioChunk) -> None:
        self._queue.put_nowait((utterance_id, chunk))

    def flush(self) -> None:
        """Descarta lo que quede por reproducir (``stop_speaking``)."""
        while not self._queue.empty():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()

    async def _loop(self) -> None:
        import numpy as np

        while True:
            utterance_id, chunk = await self._queue.get()
            if chunk.pcm and self._stream is not None:
                samples = np.frombuffer(chunk.pcm, dtype="<i2")
                await asyncio.to_thread(self._stream.write, samples)
            if chunk.is_last:
                self._on_done(utterance_id)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._stream is not None:
            with contextlib.suppress(Exception):
                self._stream.stop()
                self._stream.close()
            self._stream = None


class ConsoleTap:
    """Envuelve el hub: imprime por consola lo relevante y reenvía todo a Unity.

    Sin reproductor local, confirma cada frase (``playback_done``) en cuanto
    termina de enviarse, para que el orquestador no espere a un Unity que
    puede no estar conectado.
    """

    def __init__(self, inner: Hub, *, player: LocalPlayer | None = None) -> None:
        self._inner = inner
        self._player = player
        #: Lo fija quien construye el orquestador (``Orchestrator.notify_playback_done``).
        self.playback_done: Callable[[int], None] | None = None

    def notify_playback_done(self, utterance_id: int) -> None:
        if self.playback_done is not None:
            self.playback_done(utterance_id)

    def on(self, type: str, callback: MessageCallback) -> None:
        self._inner.on(type, callback)

    async def broadcast_json(self, msg: dict[str, Any]) -> None:
        kind = msg.get("type")
        if kind == p.MSG_STATE:
            print(f"  [{msg['state']}]", flush=True)
        elif kind == p.MSG_TRANSCRIPT and msg.get("role") == "assistant" and msg.get("final", True):
            # GPT-Live manda el texto a trozos (``final`` falso) mientras habla:
            # en consola solo se imprime la frase completa.
            print(f"Sonia: {msg['text']}", flush=True)
        elif kind == p.MSG_ERROR:
            print(f"  [error] {msg['message']}", flush=True)
        elif kind == p.MSG_STOP_SPEAKING:
            print("  [interrumpida]", flush=True)
            if self._player is not None:
                self._player.flush()
        elif kind == p.MSG_SPEECH_END and self._player is None and self._inner.client_count == 0:
            # Sin reproductor local y sin Unity no hay quien confirme la frase.
            # Si Unity está conectado sí lo hay, y confirmar aquí adelantaría el
            # `idle` hasta dos segundos: el avatar volvería a la animación de
            # reposo con la boca todavía en marcha.
            self.notify_playback_done(int(msg["utterance_id"]))
        await self._inner.broadcast_json(msg)

    async def send_audio(self, utterance_id: int, chunk: AudioChunk) -> None:
        if self._player is not None:
            self._player.enqueue(utterance_id, chunk)
        await self._inner.send_audio(utterance_id, chunk)

    async def show_image(
        self,
        *,
        image_id: str,
        source: str,
        mime: str,
        data: bytes,
        caption: str | None,
    ) -> None:
        extra = f" — {caption}" if caption else ""
        print(f"  [imagen: {image_id} ({source}, {len(data)} bytes){extra}]", flush=True)
        await self._inner.show_image(
            image_id=image_id, source=source, mime=mime, data=data, caption=caption
        )

    async def hide_image(self) -> None:
        print("  [imagen retirada]", flush=True)
        await self._inner.hide_image()


# ---------------------------------------------------------------------------
# Construcción de componentes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Components:
    """Todo lo que necesita el orquestador, construido desde la configuración."""

    settings: Settings
    hub: Hub
    tts: TextToSpeech
    llm: LLMClient
    camera: CameraSource
    policy: VisionPolicy
    registry: ActionRegistry

    def action_context(self) -> ActionContext:
        return ActionContext(
            camera=self.camera,
            avatar=self.hub,
            gallery_dir=str(self.settings.gallery_dir),
        )

    async def close(self) -> None:
        await self.llm.aclose()
        await _aclose(self.tts)
        await _aclose(self.camera)


def build_components(settings: Settings, *, with_camera: bool = True) -> Components:
    tts = build_tts(settings)
    hub = Hub(settings.ws, sample_rate=tts.sample_rate)

    async def request_frame() -> None:
        await hub.broadcast_json(p.msg_request_frame())

    vision = settings.vision
    if not with_camera:
        vision = vision.model_copy(update={"source": "none"})
    camera = build_camera(vision, request_frame, has_clients=lambda: hub.client_count > 0)
    policy = VisionPolicy(vision, settings.llm.supports_vision)
    registry = build_default_registry(include_look=policy.enabled)
    return Components(
        settings=settings,
        hub=hub,
        tts=tts,
        llm=LLMClient(settings.llm),
        camera=camera,
        policy=policy,
        registry=registry,
    )


def _log_summary(settings: Settings, components: Components) -> None:
    logger.info(
        "Sonia %s | WS ws://%s:%d | LLM %s (%s, acciones=%s, visión=%s) | STT %s | TTS %s | cámara %s",
        __version__,
        settings.ws.host,
        settings.ws.port,
        settings.llm.model,
        settings.llm.base_url,
        settings.llm.tool_mode,
        "sí" if components.policy.enabled else "no",
        settings.stt.backend,
        settings.tts.backend,
        settings.vision.source if components.policy.enabled else "no",
    )


def _apply_glossary(stt: Any) -> None:
    """Pasa los nombres del glosario al reconocedor como palabras clave, si lo admite."""
    names = load_glossary(DEFAULT_KNOWLEDGE_DIR)
    setter = getattr(stt, "set_hotwords", None)
    if names and callable(setter):
        setter(names)
        logging.getLogger(__name__).info(
            "Glosario: %d nombres como palabras clave del reconocedor", len(names)
        )


# ---------------------------------------------------------------------------
# Motor GPT-Live
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class LiveComponents:
    """Lo que necesita el motor GPT-Live: no hay STT, TTS ni VAD."""

    settings: Settings
    hub: Hub
    camera: CameraSource
    policy: VisionPolicy
    registry: ActionRegistry
    #: Modelo de visión que describe la cámara (``LLM_*``), si la visión está activa.
    llm: LLMClient | None
    narrator: VisionNarrator | None

    def action_context(self) -> ActionContext:
        return ActionContext(
            camera=self.camera,
            avatar=self.hub,
            gallery_dir=str(self.settings.gallery_dir),
        )

    async def close(self) -> None:
        if self.llm is not None:
            await self.llm.aclose()
        await _aclose(self.camera)


def build_live_components(settings: Settings, *, with_camera: bool = True) -> LiveComponents:
    hub = Hub(settings.ws, sample_rate=settings.live.sample_rate)

    async def request_frame() -> None:
        await hub.broadcast_json(p.msg_request_frame())

    vision = settings.vision
    if not with_camera:
        vision = vision.model_copy(update={"source": "none"})
    camera = build_camera(vision, request_frame, has_clients=lambda: hub.client_count > 0)
    policy = VisionPolicy(vision, settings.llm.supports_vision)
    registry = build_default_registry(include_look=policy.enabled)
    llm = LLMClient(settings.llm) if policy.enabled else None
    return LiveComponents(
        settings=settings,
        hub=hub,
        camera=camera,
        policy=policy,
        registry=registry,
        llm=llm,
        narrator=VisionNarrator(llm) if llm is not None else None,
    )


def _missing_live_key(settings: Settings) -> bool:
    if settings.live.api_key:
        return False
    print(
        "Falta LIVE_API_KEY (u OPENAI_API_KEY) en .env para usar GPT-Live. "
        "Para el motor anterior: VOICE_ENGINE=pipeline.",
        file=sys.stderr,
    )
    return True


def _log_live_summary(settings: Settings, components: LiveComponents) -> None:
    live = settings.live
    logger.info(
        "Sonia %s | WS ws://%s:%d | GPT-Live %s (voz %s, %d Hz) | backend %s | visión %s | cámara %s",
        __version__,
        settings.ws.host,
        settings.ws.port,
        live.model,
        live.voice,
        live.sample_rate,
        live.backend_model,
        settings.llm.model if components.narrator is not None else "no",
        settings.vision.source if components.policy.enabled else "no",
    )


async def _feed_silence(engine: LiveEngine, settings: Settings, seconds: float | None) -> None:
    """Silencio a tiempo real hacia GPT-Live (sin micrófono o mientras se reabre)."""
    deadline = None if seconds is None else time.monotonic() + seconds
    async for block in silence_blocks(settings.live.sample_rate, settings.audio.block_ms):
        if deadline is not None and time.monotonic() >= deadline:
            return
        await engine.push_mic(block)


async def _live_mic_loop(settings: Settings, engine: LiveEngine) -> None:
    """Micrófono → GPT-Live, reabriendo si falla.

    Igual que el bucle del otro motor, reintenta indefinidamente; mientras el
    micrófono está caído se manda silencio para que la sesión siga viva y
    ``text_input`` siga funcionando.
    """
    from sonia.audio.capture import MicCapture

    while True:
        try:
            async with MicCapture(settings.audio, sample_rate=settings.live.sample_rate) as mic:
                async for block in mic.blocks():
                    await engine.push_mic(block)
            logger.warning("El micrófono se cerró solo; se reabre en %.0f s", MIC_RETRY_DELAY_S)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "El micrófono falló (%s); se reintenta en %.0f s. Mientras tanto, "
                "Sonia solo responde a text_input por WebSocket",
                exc,
                MIC_RETRY_DELAY_S,
                exc_info=logger.isEnabledFor(logging.DEBUG),
            )
        await _feed_silence(engine, settings, MIC_RETRY_DELAY_S)


@dataclass(slots=True)
class _Panel:
    control: StandControl
    server: Any
    logs: LogBuffer


async def _start_panel(
    settings: Settings,
    hub: Hub,
    registry: ActionRegistry,
    *,
    engine: LiveEngine | None = None,
    orchestrator: Orchestrator | None = None,
    voice_cache: VoiceCache | None = None,
) -> _Panel | None:
    """Arranca el panel de control (``docs/panel.md``). Antes de ``engine.run()``.

    El control se arranca aunque falte el servidor web: aplica el modo
    guardado (por ejemplo, seguir "Fuera" tras un reinicio sin gastar).
    """
    if not settings.panel.enabled:
        return None
    from sonia.panel.server import PanelServer
    from sonia.panel.server import is_available as panel_available

    logs = LogBuffer()
    logging.getLogger().addHandler(logs)
    control = StandControl(
        settings,
        hub=hub,
        registry=registry,
        engine=engine,
        orchestrator=orchestrator,
        voice_cache=voice_cache,
    )
    await control.start()
    server: Any = None
    if panel_available():
        server = PanelServer(settings.panel, control, hub, logs)
        try:
            await server.start()
        except Exception as exc:
            logger.warning("No se pudo arrancar el panel de control: %s", exc)
            server = None
    else:
        logger.warning("Falta el extra 'panel' (uv sync --extra panel): panel de control apagado")
    return _Panel(control, server, logs)


async def _stop_panel(panel: _Panel | None) -> None:
    if panel is None:
        return
    if panel.server is not None:
        with contextlib.suppress(Exception):
            await panel.server.stop()
    await panel.control.stop()
    logging.getLogger().removeHandler(panel.logs)


async def cmd_run_live(settings: Settings, *, use_mic: bool = True) -> int:
    if _missing_live_key(settings):
        return 1
    components = build_live_components(settings)
    _log_live_summary(settings, components)
    voice_cache = VoiceCache(settings.panel.voice_cache_dir, settings.live)
    engine = LiveEngine(
        settings,
        hub=components.hub,
        registry=components.registry,
        camera=components.camera,
        vision_policy=components.policy,
        narrator=components.narrator,
        voice_cache=voice_cache,
    )

    mcp: MCPServer | None = None
    if settings.mcp.enabled:
        if mcp_available():
            mcp = MCPServer(components.registry, components.action_context, settings.mcp)
        else:
            logger.warning("MCP_ENABLED=true pero el extra 'mcp' no está instalado")

    tasks: list[asyncio.Task[None]] = []
    panel: _Panel | None = None
    try:
        async with components.hub:
            if mcp is not None:
                try:
                    await mcp.start()
                except Exception:
                    logger.exception("No se pudo arrancar el servidor MCP; se sigue sin él")
                    mcp = None
            panel = await _start_panel(
                settings,
                components.hub,
                components.registry,
                engine=engine,
                voice_cache=voice_cache,
            )
            tasks.append(asyncio.create_task(engine.run(), name="live-engine"))
            source = (
                _live_mic_loop(settings, engine)
                if use_mic
                else _feed_silence(engine, settings, None)
            )
            tasks.append(asyncio.create_task(source, name="microphone"))
            logger.info("Sonia lista con GPT-Live. Ctrl+C para salir.")
            await tasks[0]
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await _stop_panel(panel)
        if mcp is not None:
            await mcp.stop()
        await components.close()
    return 0


async def cmd_chat_live(settings: Settings, *, speak: bool = False) -> int:
    if _missing_live_key(settings):
        return 1
    components = build_live_components(settings, with_camera=False)
    player: LocalPlayer | None = None
    if speak:
        player = LocalPlayer(settings.live.sample_rate, lambda uid: tap.notify_playback_done(uid))
    tap = ConsoleTap(components.hub, player=player)
    engine = LiveEngine(
        settings,
        hub=tap,
        registry=components.registry,
        camera=None,
        vision_policy=components.policy,
        narrator=None,
    )
    tap.playback_done = engine.notify_playback_done

    tasks: list[asyncio.Task[None]] = []
    try:
        try:
            await components.hub.start()
        except OSError as exc:
            print(f"(sin WebSocket: {exc}; ¿hay otra Sonia corriendo?)", file=sys.stderr)
        if player is not None:
            await player.start()
        tasks.append(asyncio.create_task(engine.run(), name="live-engine"))
        tasks.append(asyncio.create_task(_feed_silence(engine, settings, None), name="silence"))
        print("Conectando con GPT-Live...", flush=True)
        for _ in range(int(settings.live.connect_timeout * 10)):
            if engine.connected:
                break
            await asyncio.sleep(0.1)
        print("Escribe y pulsa Enter. 'salir' o Ctrl+D para terminar.", flush=True)
        async for line in _stdin_lines():
            text = line.strip()
            if not text:
                continue
            if text.lower() in _CHAT_EXIT_WORDS:
                break
            await engine.submit_text(text)
        await engine.wait_idle(limit_s=CHAT_EXIT_GRACE_S)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if player is not None:
            await player.stop()
        await components.hub.stop()
        await components.close()
    return 0


async def cmd_say_live(settings: Settings, text: str, out: Path | None = None) -> int:
    if _missing_live_key(settings):
        return 1
    started = time.monotonic()
    pcm = await speak_text(settings.live, text)
    elapsed = time.monotonic() - started
    rate = settings.live.sample_rate
    print(
        f"{len(pcm) / 2 / rate:.2f} s de audio a {rate} Hz con la voz {settings.live.voice} "
        f"en {elapsed:.2f} s",
        flush=True,
    )
    if out is not None:
        _write_wav(out, pcm, rate)
        print(f"Guardado en {out}", flush=True)
    elif pcm:
        await asyncio.to_thread(_play_pcm_blocking, pcm, rate)
    return 0


# ---------------------------------------------------------------------------
# sonia run
# ---------------------------------------------------------------------------


async def cmd_run(settings: Settings, *, use_mic: bool = True) -> int:
    if settings.voice_engine == "live":
        return await cmd_run_live(settings, use_mic=use_mic)
    components = build_components(settings)
    stt = build_stt(settings)
    _apply_glossary(stt)
    _log_summary(settings, components)

    detector: Any = None
    vad: Any = None
    if use_mic:
        try:
            from sonia.audio.vad import TurnDetector, VoiceActivityDetector

            vad = VoiceActivityDetector()
            detector = TurnDetector(settings.audio, vad)
        except Exception as exc:
            logger.warning("No se pudo preparar el detector de voz (%s): solo text_input", exc)

    orchestrator = Orchestrator(
        settings,
        stt=stt,
        llm=components.llm,
        tts=components.tts,
        hub=components.hub,
        camera=components.camera,
        vision_policy=components.policy,
        registry=components.registry,
        on_speaking_changed=detector.set_speaking if detector is not None else None,
    )

    mcp: MCPServer | None = None
    if settings.mcp.enabled:
        if mcp_available():
            mcp = MCPServer(components.registry, components.action_context, settings.mcp)
        else:
            logger.warning("MCP_ENABLED=true pero el extra 'mcp' no está instalado")

    tasks: list[asyncio.Task[None]] = []
    panel: _Panel | None = None
    try:
        async with components.hub:
            await asyncio.gather(
                _warmup("STT", getattr(stt, "warmup", None)),
                _warmup("TTS", getattr(components.tts, "warmup", None)),
                _warmup("VAD", (lambda: asyncio.to_thread(vad.warmup)) if vad else None),
            )
            if mcp is not None:
                try:
                    await mcp.start()
                except Exception:
                    logger.exception("No se pudo arrancar el servidor MCP; se sigue sin él")
                    mcp = None
            panel = await _start_panel(
                settings, components.hub, components.registry, orchestrator=orchestrator
            )

            tasks.append(asyncio.create_task(orchestrator.run(), name="orchestrator"))
            if detector is not None:
                tasks.append(
                    asyncio.create_task(
                        _mic_loop(settings, detector, orchestrator), name="microphone"
                    )
                )
            logger.info("Sonia lista. Ctrl+C para salir.")
            await tasks[0]
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await _stop_panel(panel)
        if mcp is not None:
            await mcp.stop()
        await components.close()
    return 0


async def _mic_loop(settings: Settings, detector: Any, orchestrator: Orchestrator) -> None:
    """Micrófono → detector de turnos → orquestador, reabriendo si hace falta.

    Es el componente más frágil del stand: el cable se mueve, el hub USB
    re-enumera el dispositivo o el sistema cambia la entrada por defecto. Nada
    de eso puede dejar a Sonia sorda el resto del día, así que el bucle
    reintenta indefinidamente. Mientras tanto sigue funcionando ``text_input``.
    """
    from sonia.audio.capture import MicCapture

    while True:
        try:
            async with MicCapture(settings.audio) as mic:
                await orchestrator.feed(detector.events(mic.blocks()))
            logger.warning("El micrófono se cerró solo; se reabre en %.0f s", MIC_RETRY_DELAY_S)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "El micrófono falló (%s); se reintenta en %.0f s. Mientras tanto, "
                "Sonia solo responde a text_input por WebSocket",
                exc,
                MIC_RETRY_DELAY_S,
                exc_info=logger.isEnabledFor(logging.DEBUG),
            )
        with contextlib.suppress(Exception):
            detector.reset()
        await asyncio.sleep(MIC_RETRY_DELAY_S)


# ---------------------------------------------------------------------------
# sonia chat
# ---------------------------------------------------------------------------


async def _stdin_lines() -> Any:
    """Lee líneas de stdin sin bloquear el bucle (cancelable con Ctrl+C)."""
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    try:
        await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
    except (OSError, ValueError, NotImplementedError):
        reader = None  # type: ignore[assignment]

    while True:
        if reader is not None:
            raw = await reader.readline()
            line = raw.decode("utf-8", errors="replace")
        else:
            line = await asyncio.to_thread(sys.stdin.readline)
        if not line:
            return
        yield line.rstrip("\r\n")


async def cmd_chat(settings: Settings, *, speak: bool = False) -> int:
    if settings.voice_engine == "live":
        return await cmd_chat_live(settings, speak=speak)
    components = build_components(settings, with_camera=False)
    player: LocalPlayer | None = None
    if speak:
        # El reproductor avisa al tap, y el tap al orquestador (que aún no existe).
        player = LocalPlayer(components.tts.sample_rate, lambda uid: tap.notify_playback_done(uid))
    tap = ConsoleTap(components.hub, player=player)
    orchestrator = Orchestrator(
        settings,
        stt=MockSTT(),
        llm=components.llm,
        tts=components.tts,
        hub=tap,
        camera=None,
        vision_policy=components.policy,
        registry=components.registry,
    )
    tap.playback_done = orchestrator.notify_playback_done

    run_task: asyncio.Task[None] | None = None
    try:
        try:
            await components.hub.start()
        except OSError as exc:
            print(f"(sin WebSocket: {exc}; ¿hay otra Sonia corriendo?)", file=sys.stderr)
        if player is not None:
            await player.start()
        await _warmup("TTS", getattr(components.tts, "warmup", None))
        run_task = asyncio.create_task(orchestrator.run(), name="orchestrator")
        print("Escribe y pulsa Enter. 'salir' o Ctrl+D para terminar.", flush=True)
        async for line in _stdin_lines():
            text = line.strip()
            if not text:
                continue
            if text.lower() in _CHAT_EXIT_WORDS:
                break
            await orchestrator.submit_text(text)
        # Al salir por EOF o 'salir' se deja terminar la respuesta en curso.
        await orchestrator.wait_idle(limit_s=CHAT_EXIT_GRACE_S)
    finally:
        if run_task is not None:
            run_task.cancel()
            await asyncio.gather(run_task, return_exceptions=True)
        if player is not None:
            await player.stop()
        await components.hub.stop()
        await components.close()
    return 0


# ---------------------------------------------------------------------------
# sonia say
# ---------------------------------------------------------------------------


async def cmd_say(settings: Settings, text: str, out: Path | None = None) -> int:
    if settings.voice_engine == "live":
        return await cmd_say_live(settings, text, out)
    tts = build_tts(settings)
    try:
        started = time.monotonic()
        pcm = await _collect_pcm(tts, text)
        elapsed = time.monotonic() - started
        duration = len(pcm) / 2 / tts.sample_rate
        print(f"{duration:.2f} s de audio a {tts.sample_rate} Hz en {elapsed:.2f} s", flush=True)
        if out is not None:
            _write_wav(out, pcm, tts.sample_rate)
            print(f"Guardado en {out}", flush=True)
        elif pcm:
            await asyncio.to_thread(_play_pcm_blocking, pcm, tts.sample_rate)
    finally:
        await _aclose(tts)
    return 0


# ---------------------------------------------------------------------------
# sonia check
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    #: Si falla algo crítico, ``sonia check`` sale con código 1.
    critical: bool = True


async def check_audio(settings: Settings) -> CheckResult:
    devices = await asyncio.to_thread(list_input_devices)
    if not devices:
        return CheckResult(
            "Micrófono", False, "no hay dispositivos de entrada (¿extra 'audio' instalado?)"
        )
    try:
        chosen = await asyncio.to_thread(resolve_input_device, settings.audio.input_device)
    except Exception as exc:
        return CheckResult("Micrófono", False, str(exc))
    if chosen is None:
        default = next((d for d in devices if d.get("default")), devices[0])
        name = f"por defecto: {default['name']}"
    else:
        match = next((d for d in devices if d["index"] == chosen), None)
        name = f"#{chosen}: {match['name']}" if match else f"#{chosen}"
    return CheckResult("Micrófono", True, f"{len(devices)} dispositivo(s); {name}")


async def check_camera(settings: Settings) -> CheckResult:
    source = settings.vision.source
    if not settings.llm.supports_vision:
        return CheckResult("Cámara", True, "visión desactivada (LLM_SUPPORTS_VISION=false)", False)
    if source == "none":
        return CheckResult("Cámara", True, "desactivada (VISION_SOURCE=none)", False)
    if source == "unity":
        return CheckResult("Cámara", True, "la envía Unity por WebSocket (no se comprueba)", False)
    camera = build_camera(settings.vision)
    try:
        started = time.monotonic()
        frame = await asyncio.wait_for(camera.capture(), timeout=10.0)
        elapsed = time.monotonic() - started
    except Exception as exc:
        return CheckResult("Cámara", False, f"índice {settings.vision.camera_index}: {exc}", False)
    finally:
        await _aclose(camera)
    if frame is None:
        return CheckResult(
            "Cámara", False, f"índice {settings.vision.camera_index}: sin imagen", False
        )
    return CheckResult(
        "Cámara",
        True,
        f"índice {settings.vision.camera_index}: {frame.width}x{frame.height}, "
        f"{len(frame.data)} bytes en {elapsed * 1000:.0f} ms",
        False,
    )


async def check_stt(settings: Settings) -> CheckResult:
    """Carga el modelo de voz y transcribe medio segundo de silencio.

    Comprueba lo que ``sonia run`` solo descubriría en el primer turno: que el
    extra ``stt`` está instalado y que los pesos de ``STT_MODEL`` ya están en la
    caché local. Sin esto, un cambio de modelo la noche antes deja el check en
    verde y a Sonia sorda todo el día.
    """
    backend = settings.stt.backend
    if backend != "faster_whisper":
        return CheckResult("STT", True, f"backend {backend} (no se comprueba)", False)
    try:
        import numpy as np

        from sonia.types import Utterance

        stt = build_stt(settings)
        started = time.monotonic()
        warmup = getattr(stt, "warmup", None)
        if callable(warmup):
            await warmup()
        loaded = time.monotonic() - started
        silence = Utterance(audio=np.zeros(8_000, dtype=np.float32))
        await stt.transcribe(silence)
    except Exception as exc:
        return CheckResult("STT", False, f"modelo '{settings.stt.model}': {exc}")
    return CheckResult(
        "STT", True, f"modelo '{settings.stt.model}' cargado en {loaded:.1f} s ({backend})"
    )


async def check_vad(settings: Settings) -> CheckResult:
    """Carga Silero VAD y evalúa un bloque de silencio."""
    try:
        import numpy as np

        from sonia.audio.vad import VAD_WINDOW, VoiceActivityDetector

        vad = VoiceActivityDetector()
        started = time.monotonic()
        await asyncio.to_thread(vad.warmup)
        loaded = time.monotonic() - started
        await asyncio.to_thread(vad.probability, np.zeros(VAD_WINDOW, dtype=np.float32))
    except Exception as exc:
        return CheckResult("VAD", False, f"Silero VAD: {exc}")
    return CheckResult("VAD", True, f"Silero VAD cargado en {loaded:.1f} s")


async def check_llm(settings: Settings) -> CheckResult:
    """Una única petición mínima (``max_tokens=5``) al endpoint configurado."""
    target = f"{settings.llm.base_url} ({settings.llm.model})"
    try:
        async with LLMClient(settings.llm) as client:
            started = time.monotonic()
            reply = await asyncio.wait_for(client.ping(), timeout=settings.llm.request_timeout)
            elapsed = time.monotonic() - started
    except Exception as exc:
        return CheckResult("LLM", False, f"{target}: {exc}")
    return CheckResult("LLM", True, f"{target}: '{reply}' en {elapsed * 1000:.0f} ms")


async def check_live(settings: Settings) -> CheckResult:
    """Abre y cierra una sesión de GPT-Live (unos segundos de sesión, céntimos)."""
    live = settings.live
    target = f"{live.model} (voz {live.voice})"
    if not live.api_key:
        return CheckResult("GPT-Live", False, f"{target}: falta LIVE_API_KEY u OPENAI_API_KEY")
    try:
        result = await probe_session(live)
    except Exception as exc:
        return CheckResult("GPT-Live", False, f"{target}: {exc}")
    expiry = (
        f"; la sesión dura {result.expires_in_s / 60:.0f} min"
        if result.expires_in_s is not None
        else ""
    )
    return CheckResult(
        "GPT-Live",
        True,
        f"{live.model} (voz {result.voice}): sesión abierta en "
        f"{result.elapsed_s * 1000:.0f} ms{expiry}; backend {live.backend_model}",
    )


async def check_vision_model(settings: Settings) -> CheckResult:
    """Con GPT-Live, ``LLM_*`` solo describe la cámara: ping y una imagen mínima."""
    policy = VisionPolicy(settings.vision, settings.llm.supports_vision)
    if not policy.enabled:
        return CheckResult(
            "Visión", True, "desactivada (sin cámara o LLM_SUPPORTS_VISION=false)", False
        )
    llm = await check_llm(settings)
    if not llm.ok:
        return CheckResult("Visión", False, llm.detail, False)
    features = await check_llm_features(settings, build_default_registry(), want_tools=False)
    if features is not None and not features.ok:
        return CheckResult("Visión", False, features.detail, False)
    return CheckResult("Visión", True, f"{llm.detail}; acepta imágenes", False)


async def run_live_checks(settings: Settings) -> list[CheckResult]:
    """Comprobaciones del motor GPT-Live: no hay VAD, STT ni TTS locales."""
    return [
        await check_audio(settings),
        await check_camera(settings),
        await check_live(settings),
        await check_vision_model(settings),
        check_gallery(settings),
    ]


async def check_llm_features(
    settings: Settings, registry: ActionRegistry, *, want_tools: bool = True
) -> CheckResult | None:
    """Comprueba que el endpoint acepta imágenes y ``tools``, como en cada turno.

    ``ping`` solo manda texto plano: un servidor sin ``mmproj`` o sin tool
    calling pasa el check y luego rechaza el 100 % de los turnos con un 400.
    Son dos peticiones de cinco tokens, y solo las que hagan falta según la
    configuración. Es un aviso, no un fallo crítico: puede ser el servidor el
    que no soporte el parámetro y aun así funcionar bajando la configuración.
    """
    wanted: list[str] = []
    if settings.llm.supports_vision:
        wanted.append("visión")
    if want_tools and settings.llm.tool_mode == "native" and len(registry) > 0:
        wanted.append("acciones")
    if not wanted:
        return None

    detail: list[str] = []
    ok = True
    async with LLMClient(settings.llm) as client:
        if "visión" in wanted:
            image = {
                "role": "user",
                "content": [
                    {"type": "text", "text": "ping"},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{_PROBE_JPEG_B64}"},
                    },
                ],
            }
            try:
                await asyncio.wait_for(
                    client.probe(image=image), timeout=settings.llm.request_timeout
                )
                detail.append("visión: OK")
            except Exception as exc:
                ok = False
                detail.append(f"visión: FALLO ({exc}); prueba LLM_SUPPORTS_VISION=false")
        if "acciones" in wanted:
            try:
                await asyncio.wait_for(
                    client.probe(tools=registry.to_openai_tools()),
                    timeout=settings.llm.request_timeout,
                )
                detail.append("acciones: OK")
            except Exception as exc:
                ok = False
                detail.append(f"acciones: FALLO ({exc}); prueba LLM_TOOL_MODE=prompt")
    return CheckResult("Capacidad", ok, "; ".join(detail), False)


async def check_tts(settings: Settings) -> CheckResult:
    backend = settings.tts.backend
    try:
        tts = build_tts(settings)
    except Exception as exc:
        return CheckResult("TTS", False, f"backend {backend}: {exc}")
    try:
        started = time.monotonic()
        first: float | None = None
        pcm = bytearray()
        async for chunk in tts.synthesize(CHECK_TTS_TEXT):
            if first is None:
                first = time.monotonic() - started
            pcm += chunk.pcm
        elapsed = time.monotonic() - started
    except Exception as exc:
        return CheckResult("TTS", False, f"backend {backend}: {exc}")
    finally:
        await _aclose(tts)
    if not pcm:
        return CheckResult("TTS", False, f"backend {backend}: no devolvió audio")
    duration = len(pcm) / 2 / tts.sample_rate
    return CheckResult(
        "TTS",
        True,
        f"backend {backend}: '{CHECK_TTS_TEXT}' -> {duration:.2f} s de audio a "
        f"{tts.sample_rate} Hz; primer chunk en {(first or 0.0) * 1000:.0f} ms, "
        f"total {elapsed * 1000:.0f} ms",
    )


def check_gallery(settings: Settings) -> CheckResult:
    gallery = Gallery(settings.gallery_dir)
    if not gallery.path.is_dir():
        return CheckResult("Galería", False, f"no existe {gallery.path}", False)
    ids = gallery.ids()
    if not ids:
        return CheckResult("Galería", False, f"{gallery.path} no tiene imágenes", False)
    return CheckResult("Galería", True, f"{len(ids)} imagen(es): {', '.join(ids)}", False)


async def run_checks(settings: Settings) -> list[CheckResult]:
    """Ejecuta todas las comprobaciones en orden y devuelve sus resultados."""
    if settings.voice_engine == "live":
        return await run_live_checks(settings)
    policy = VisionPolicy(settings.vision, settings.llm.supports_vision)
    registry = build_default_registry(include_look=policy.enabled)
    llm = await check_llm(settings)
    results = [
        await check_audio(settings),
        await check_vad(settings),
        await check_stt(settings),
        await check_camera(settings),
        llm,
    ]
    if llm.ok:
        # Sin endpoint sano no tiene sentido gastar dos peticiones más.
        features = await check_llm_features(settings, registry)
        if features is not None:
            results.append(features)
    results.append(await check_tts(settings))
    results.append(check_gallery(settings))
    return results


def print_results(results: list[CheckResult]) -> bool:
    """Imprime una línea por comprobación. Devuelve ``True`` si nada crítico falló."""
    all_ok = True
    for result in results:
        label = "OK   " if result.ok else ("FALLO" if result.critical else "AVISO")
        print(f"{label}  {result.name:<10} {result.detail}", flush=True)
        if not result.ok and result.critical:
            all_ok = False
    print("Todo listo." if all_ok else "Hay fallos críticos.", flush=True)
    return all_ok


async def cmd_check(settings: Settings) -> int:
    results = await run_checks(settings)
    return 0 if print_results(results) else 1


# ---------------------------------------------------------------------------
# sonia mcp
# ---------------------------------------------------------------------------


async def cmd_mcp(settings: Settings) -> int:
    if not mcp_available():
        print("El extra 'mcp' no está instalado: uv sync --extra mcp", file=sys.stderr)
        return 1
    components = build_components(settings)
    server = MCPServer(components.registry, components.action_context, settings.mcp)
    try:
        # El hub también arranca: así `show_image` llega a Unity si está conectado.
        async with components.hub:
            await server.start()
            print(
                f"Servidor MCP en {server.url} con las acciones: "
                + ", ".join(components.registry.names()),
                flush=True,
            )
            await asyncio.Event().wait()
    finally:
        await server.stop()
        await components.close()
    return 0


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sonia",
        description="Asistente de voz con avatar 3D para el stand de Sonnet Code.",
    )
    parser.add_argument("--version", action="version", version=f"sonia {__version__}")
    parser.add_argument(
        "--log-level",
        default=None,
        help="Nivel de log (por defecto, LOG_LEVEL del entorno).",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="demo completa: micrófono, cámara, modelo y avatar")
    run.add_argument(
        "--no-mic",
        action="store_true",
        help="no abrir el micrófono; solo text_input por WebSocket",
    )

    chat = commands.add_parser("chat", help="conversar por texto sin micrófono ni cámara")
    chat.add_argument("--speak", action="store_true", help="reproducir el audio localmente")

    say = commands.add_parser("say", help="sintetizar un texto y reproducirlo")
    say.add_argument("text", help="texto a sintetizar")
    say.add_argument("--out", type=Path, default=None, help="guardar a WAV en vez de reproducir")

    commands.add_parser("check", help="comprobar micrófono, cámara, voz, modelo y galería")
    commands.add_parser("mcp", help="arrancar solo el servidor MCP con las acciones")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings()
    configure_logging(args.log_level or settings.log_level)

    match args.command:
        case "run":
            return _run(cmd_run(settings, use_mic=not args.no_mic))
        case "chat":
            return _run(cmd_chat(settings, speak=args.speak))
        case "say":
            return _run(cmd_say(settings, args.text, args.out))
        case "check":
            return _run(cmd_check(settings))
        case "mcp":
            return _run(cmd_mcp(settings))
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
