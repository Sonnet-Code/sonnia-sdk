"""Línea de comandos de Sonia.

Subcomandos:

- ``sonia run``: demo completa (micrófono, cámara, GPT-Live, Unity y panel).
- ``sonia chat``: escribir a Sonia desde la consola, sin micrófono ni cámara.
  Con ``--speak`` reproduce su voz por el altavoz.
- ``sonia say "texto"``: GPT-Live lee el texto con su voz (o lo guarda a WAV
  con ``--out``). Sirve para elegir la voz.
- ``sonia check``: comprueba micrófono, cámara, GPT-Live, el modelo de visión y
  la galería, e imprime OK/FALLO por línea.

Todas las dependencias pesadas (sounddevice, cv2, starlette...) se importan
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
from sonia.config import Settings, is_openai_url, load_settings
from sonia.guest.link import FrameGrabber
from sonia.live.audio import silence_blocks
from sonia.live.engine import LiveEngine
from sonia.live.oneshot import probe_session, speak_text
from sonia.live.vision import VisionNarrator
from sonia.live.voicecache import VoiceCache
from sonia.llm.client import LLMClient
from sonia.panel.control import StandControl
from sonia.panel.logs import LogBuffer
from sonia.paths import seed_home
from sonia.types import ActionContext, AudioChunk, CameraSource
from sonia.vision.camera import build_camera
from sonia.vision.policy import VisionPolicy
from sonia.ws import protocol as p
from sonia.ws.hub import Hub, MessageCallback

__all__ = ["build_parser", "main", "run_checks"]

logger = logging.getLogger(__name__)

#: Palabras que terminan ``sonia chat``.
_CHAT_EXIT_WORDS = frozenset({"salir", "exit", "quit"})

#: Cuánto espera ``sonia chat`` a que Sonia termine de hablar antes de salir.
CHAT_EXIT_GRACE_S = 30.0

#: Espera antes de reabrir el micrófono cuando falla o deja de entregar audio.
MIC_RETRY_DELAY_S = 5.0

#: JPEG gris de 112x112 para comprobar que el endpoint acepta ``image_url``. Tiene que
#: ser un JPEG que cualquier decodificador lea (``tests/test_cli.py`` lo comprueba): el
#: anterior, de 16x16, tenía una tabla de cuantización truncada, un servidor que valida
#: la imagen lo rechazaba y ``sonia check`` daba la visión por rota (y sugería apagarla).
#: Va embebido para que ``sonia check`` no dependa del extra de la cámara.
_PROBE_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAYEBQYFBAYGBQYHBwYIChAKCgkJChQODwwQFxQY"
    "GBcUFhYaHSUfGhsjHBYWICwgIyYnKSopGR8tMC0oMCUoKSj/2wBDAQcHBwoIChMKChMoGhYa"
    "KCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCj/wAAR"
    "CABwAHADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAA"
    "AgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkK"
    "FhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWG"
    "h4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl"
    "5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREA"
    "AgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYk"
    "NOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOE"
    "hYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk"
    "5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwAooooAKKKKACiiigAooooAKKKKACiiigAo"
    "oooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKK"
    "ACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAo"
    "oooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKK"
    "ACiiigAooooA/9k="
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
        elif kind == p.MSG_TRIVIA_ANSWER:
            print(f"  [trivia: {'acierto' if msg['is_correct'] else 'fallo'}]", flush=True)
        elif kind == p.MSG_TRIVIA_END:
            print(f"  [trivia: {msg['score']} de {msg['total']}, {msg['reason']}]", flush=True)
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

    async def set_sticky(self, key: str, msg: dict[str, Any]) -> None:
        if msg.get("type") == p.MSG_TRIVIA_QUESTION:
            letters = ("A", "B", "C")
            options = "  ".join(f"{letters[i]}) {o}" for i, o in enumerate(msg["options"][:3]))
            print(f"  [trivia {msg['number']}/{msg['total']}] {msg['question']}  {options}")
        await self._inner.set_sticky(key, msg)

    def clear_sticky(self, key: str) -> None:
        self._inner.clear_sticky(key)

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


@dataclass(slots=True)
class Components:
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


def build_components(settings: Settings, *, with_camera: bool = True) -> Components:
    hub = Hub(settings.ws, sample_rate=settings.live.sample_rate)

    async def request_frame() -> None:
        await hub.broadcast_json(p.msg_request_frame())

    vision = settings.vision
    if not with_camera:
        vision = vision.model_copy(update={"source": "none"})
    camera = build_camera(vision, request_frame, has_clients=lambda: hub.client_count > 0)
    policy = VisionPolicy(vision, _vision_model_ready(settings))
    registry = build_default_registry(
        include_look=policy.enabled, include_trivia=_trivia_ready(settings)
    )
    llm = LLMClient(settings.llm) if policy.enabled else None
    return Components(
        settings=settings,
        hub=hub,
        camera=camera,
        policy=policy,
        registry=registry,
        llm=llm,
        narrator=VisionNarrator(llm) if llm is not None else None,
    )


def _trivia_ready(settings: Settings) -> bool:
    """¿Hay banco de preguntas para la trivia? Sin él no se anuncian sus acciones."""
    if not settings.trivia.enabled:
        return False
    from sonia.trivia import TriviaBank

    count = len(TriviaBank.from_file(settings.trivia_file))
    if count < settings.trivia.questions:
        logger.warning(
            "Trivia apagada: %s tiene %d preguntas válidas y hacen falta %d",
            settings.trivia_file,
            count,
            settings.trivia.questions,
        )
        return False
    return True


def _vision_model_ready(settings: Settings, *, warn: bool = True) -> bool:
    """¿Hay modelo de visión con clave? Sin clave, la cámara se apaga con un aviso claro."""
    llm = settings.llm
    if not llm.supports_vision:
        return False
    if llm.key:
        return True
    if warn:
        logger.warning("Cámara apagada: %s", _missing_vision_key(settings))
    return False


def _missing_vision_key(settings: Settings) -> str:
    """Qué clave falta para el modelo de visión, dicho para quien edita el ``.env``."""
    base_url = settings.llm.base_url
    if is_openai_url(base_url):
        return (
            f"falta la clave de OpenAI para {base_url} (OPENAI_API_KEY, LIVE_API_KEY o LLM_API_KEY)"
        )
    return (
        f"falta LLM_API_KEY para {base_url} (la clave de OpenAI solo se usa con la API de OpenAI)"
    )


def _missing_live_key(settings: Settings) -> bool:
    if settings.live.api_key:
        return False
    print(
        "Falta LIVE_API_KEY (u OPENAI_API_KEY) en .env para usar GPT-Live.",
        file=sys.stderr,
    )
    return True


def _log_summary(settings: Settings, components: Components) -> None:
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
    ``text_input`` siga funcionando. Antes de reabrir se vuelven a leer los
    dispositivos, para que aparezca el micro USB si se desenchufó y se volvió a
    enchufar (aquí no hay más streams de audio abiertos).
    """
    from sonia.audio.capture import MicCapture, refresh_devices

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
        await asyncio.to_thread(refresh_devices)


@dataclass(slots=True)
class _Panel:
    control: StandControl
    server: Any
    logs: LogBuffer
    cloud: asyncio.Task[None] | None = None


@dataclass(slots=True)
class _RoomCamera:
    """Cámara de la sala de vídeo (Modo Jean y «Ver cámara»)."""

    grab: FrameGrabber
    available: bool
    #: Suelta el dispositivo al cerrarse la sala, si era una cámara solo suya.
    release: Callable[[], Awaitable[None]] | None


def _room_camera(settings: Settings, camera: CameraSource | None) -> _RoomCamera:
    """Cámara de la sala: tamaño y calidad por captura, según lo que aguante la red.

    Comparte el dispositivo con la visión de Sonia: si la visión usa la cámara
    USB, es el mismo ``OpenCVCamera`` (un solo dispositivo abierto; las capturas
    se turnan con su candado y leen y codifican en un hilo, fuera del bucle).
    Con la visión apagada (``VISION_SOURCE=none``) la sala abre la cámara USB por
    su cuenta y la suelta al cerrarse; con la cámara de Unity se usa tal cual llega.
    """
    import importlib.util

    from sonia.vision.camera import OpenCVCamera, UnityCamera

    shared = camera if isinstance(camera, OpenCVCamera) else None
    unity = camera if isinstance(camera, UnityCamera) else None
    own: OpenCVCamera | None = None
    if shared is None and unity is None:
        if importlib.util.find_spec("cv2") is not None:
            own = OpenCVCamera(settings.vision)
        else:
            logger.warning(
                "Sala de vídeo sin cámara: falta el extra 'camera' (uv sync --extra camera)"
            )
    usb = shared or own

    async def grab(width: int, quality: int) -> bytes | None:
        if usb is not None:
            frame = await usb.capture(max_width=width, quality=quality)
        elif unity is not None:
            frame = await unity.capture()
        else:
            return None
        return frame.data if frame is not None else None

    return _RoomCamera(
        grab=grab,
        available=usb is not None or unity is not None,
        release=own.close if own is not None else None,
    )


async def _start_panel(
    settings: Settings,
    hub: Hub,
    registry: ActionRegistry,
    *,
    engine: LiveEngine,
    voice_cache: VoiceCache | None = None,
    camera: CameraSource | None = None,
) -> _Panel | None:
    """Arranca el panel de control (``docs/panel.md``). Antes de ``engine.run()``.

    El control se arranca aunque falte el servidor web: aplica el modo
    guardado (por ejemplo, seguir "Fuera" tras un reinicio sin gastar).
    """
    if not settings.panel.enabled:
        return None
    from sonia.panel.cloud import CloudLink
    from sonia.panel.events import PanelEvents
    from sonia.panel.identity import load_identity
    from sonia.panel.server import PanelServer
    from sonia.panel.server import is_available as panel_available

    logs = LogBuffer()
    logs.bind(asyncio.get_running_loop())
    logging.getLogger().addHandler(logs)
    identity = load_identity(settings.panel)
    events = PanelEvents(hub, logs)
    control = StandControl(
        settings,
        hub=hub,
        registry=registry,
        engine=engine,
        voice_cache=voice_cache,
    )
    await control.start()
    server: Any = None
    if panel_available():
        server = PanelServer(settings.panel, control, hub, logs, events=events, identity=identity)
        try:
            await server.start()
        except Exception as exc:
            logger.warning("No se pudo arrancar el panel de control local: %s", exc)
            server = None
    else:
        logger.warning("Falta el extra 'panel' (uv sync --extra panel): panel local apagado")
    cloud: asyncio.Task[None] | None = None
    link = CloudLink(settings.panel, control, events, identity)
    if link.enabled:
        cloud = asyncio.create_task(link.run(), name="sonia-cloud-panel")
        # Sala de vídeo (Modo Jean y «Ver cámara»): solo abierta mientras alguien la necesita.
        from sonia.guest.link import GuestLink
        from sonia.guest.mode import GuestMode
        from sonia.guest.room import RoomSupervisor

        rate = settings.live.sample_rate
        room_camera = _room_camera(settings, camera)
        room = RoomSupervisor(
            GuestLink(
                settings.panel,
                identity,
                sink=hub,
                unity_rate=rate,
                mic_rate=rate,
                grab=room_camera.grab,
            ),
            engine,
            camera_available=room_camera.available,
            release_camera=room_camera.release,
        )
        control.attach_room(room)
        control.attach_guest(
            GuestMode(
                hub=hub,
                engine=engine,
                room=room,
                voice_cache=voice_cache,
                intro_lines=control.guest_intro_lines,
                unity_rate=rate,
                on_change=control.guest_changed,
            )
        )
    else:
        logger.info("Sin PANEL_CLOUD_TOKEN: esta Sonia no se conecta al panel de Cloudflare")
    return _Panel(control, server, logs, cloud)


async def _stop_panel(panel: _Panel | None) -> None:
    if panel is None:
        return
    if panel.cloud is not None:
        panel.cloud.cancel()
        await asyncio.gather(panel.cloud, return_exceptions=True)
    if panel.server is not None:
        with contextlib.suppress(Exception):
            await panel.server.stop()
    await panel.control.stop()
    logging.getLogger().removeHandler(panel.logs)


async def cmd_run(settings: Settings, *, use_mic: bool = True) -> int:
    if _missing_live_key(settings):
        return 1
    components = build_components(settings)
    _log_summary(settings, components)
    # En la app empaquetada, las frases ya grabadas que trae pasan a este equipo.
    seeded = await asyncio.to_thread(seed_home)
    if seeded:
        logger.info("Frases grabadas de la app copiadas a este equipo: %d", seeded)
    voice_cache = VoiceCache(settings.panel.voice_cache_dir, settings.live)
    engine = LiveEngine(
        settings,
        hub=components.hub,
        registry=components.registry,
        camera=components.camera,
        vision_policy=components.policy,
        narrator=components.narrator,
        voice_cache=voice_cache,
        knowledge_dir=settings.knowledge_dir,
    )

    tasks: list[asyncio.Task[None]] = []
    panel: _Panel | None = None
    try:
        async with components.hub:
            panel = await _start_panel(
                settings,
                components.hub,
                components.registry,
                engine=engine,
                voice_cache=voice_cache,
                camera=components.camera,
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
        await components.close()
    return 0


async def cmd_chat(settings: Settings, *, speak: bool = False) -> int:
    if _missing_live_key(settings):
        return 1
    components = build_components(settings, with_camera=False)
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
        knowledge_dir=settings.knowledge_dir,
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


async def cmd_say(settings: Settings, text: str, out: Path | None = None) -> int:
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
    if not _vision_model_ready(settings, warn=False):
        return CheckResult("Visión", False, _missing_vision_key(settings), False)
    llm = await check_llm(settings)
    if not llm.ok:
        return CheckResult("Visión", False, llm.detail, False)
    features = await check_vision_features(settings)
    if not features.ok:
        return CheckResult("Visión", False, features.detail, False)
    return CheckResult("Visión", True, f"{llm.detail}; acepta imágenes", False)


async def run_checks(settings: Settings) -> list[CheckResult]:
    """Ejecuta todas las comprobaciones en orden y devuelve sus resultados."""
    return [
        await check_audio(settings),
        await check_camera(settings),
        await check_live(settings),
        await check_vision_model(settings),
        check_gallery(settings),
    ]


async def check_vision_features(settings: Settings) -> CheckResult:
    """Una petición mínima con imagen, tal como se describe la cámara en cada turno.

    ``ping`` solo manda texto: un modelo sin visión pasaría el check y luego
    fallaría en cada descripción. Es un aviso, no un fallo crítico: Sonia
    conversa igual sin ojos.
    """
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
        async with LLMClient(settings.llm) as client:
            await asyncio.wait_for(client.probe(image), timeout=settings.llm.request_timeout)
    except Exception as exc:
        return CheckResult(
            "Visión",
            False,
            f"no acepta imágenes ({exc}); revisa LLM_BASE_URL, LLM_MODEL y LLM_API_KEY "
            "(docs/informe-vision.md)",
            False,
        )
    return CheckResult("Visión", True, "acepta imágenes", False)


def check_gallery(settings: Settings) -> CheckResult:
    gallery = Gallery(settings.gallery_dir)
    if not gallery.path.is_dir():
        return CheckResult("Galería", False, f"no existe {gallery.path}", False)
    ids = gallery.ids()
    if not ids:
        return CheckResult("Galería", False, f"{gallery.path} no tiene imágenes", False)
    return CheckResult("Galería", True, f"{len(ids)} imagen(es): {', '.join(ids)}", False)


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

    run = commands.add_parser("run", help="demo completa: micrófono, cámara, GPT-Live y avatar")
    run.add_argument(
        "--no-mic",
        action="store_true",
        help="no abrir el micrófono; solo texto desde el panel",
    )

    chat = commands.add_parser("chat", help="escribir a Sonia desde la consola")
    chat.add_argument("--speak", action="store_true", help="reproducir su voz por el altavoz")

    say = commands.add_parser("say", help="que GPT-Live lea un texto con su voz")
    say.add_argument("text", help="texto que leer")
    say.add_argument("--out", type=Path, default=None, help="guardar a WAV en vez de reproducir")

    commands.add_parser("check", help="comprobar micrófono, cámara, GPT-Live, visión y galería")
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
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
