"""Sonnia command line.

Subcommands:

- ``sonia run``: the full experience (microphone, camera, GPT-Live, avatar client
  and control panel).
- ``sonia chat``: type to Sonnia from the console, without microphone or camera.
  With ``--speak`` her voice plays on the speaker.
- ``sonia say "text"``: GPT-Live reads the text with its voice (or saves it to a WAV
  with ``--out``). Useful to pick a voice.
- ``sonia check``: checks the microphone, the camera, GPT-Live, the vision model and
  the gallery, and prints OK/FAIL per line.

All heavy dependencies (sounddevice, cv2, starlette...) are imported inside the
functions that use them: importing this module is cheap.
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
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sonia import __version__
from sonia.actions import Gallery, build_default_registry
from sonia.actions.registry import ActionRegistry
from sonia.audio.capture import list_input_devices, resolve_input_device
from sonia.config import Settings, is_openai_url, load_settings
from sonia.devices import DeviceManager, apply_choice, load_choice
from sonia.live.audio import silence_blocks
from sonia.live.engine import LiveEngine
from sonia.live.oneshot import probe_session, speak_text
from sonia.live.vision import VisionNarrator
from sonia.live.voicecache import VoiceCache
from sonia.llm.client import LLMClient
from sonia.panel.control import PanelControl
from sonia.panel.logs import LogBuffer
from sonia.parent import watch_parent
from sonia.types import ActionContext, AudioChunk, CameraSource
from sonia.vision.camera import OpenCVCamera, build_camera
from sonia.vision.policy import VisionPolicy
from sonia.ws import protocol as p
from sonia.ws.hub import Hub, MessageCallback

__all__ = ["build_parser", "main", "run_checks"]

logger = logging.getLogger(__name__)

#: Words that end ``sonia chat``.
_CHAT_EXIT_WORDS = frozenset({"exit", "quit", "bye"})

#: How long ``sonia chat`` waits for Sonnia to finish speaking before leaving.
CHAT_EXIT_GRACE_S = 30.0

#: Wait before reopening the microphone when it fails or stops delivering audio.
MIC_RETRY_DELAY_S = 5.0

#: A 112x112 gray JPEG to check that the endpoint accepts ``image_url``. It has to be a
#: JPEG any decoder can read (``tests/test_cli.py`` checks it): a server that validates
#: the image rejects a broken one and ``sonia check`` would report vision as broken.
#: It is embedded so that ``sonia check`` does not depend on the camera extra.
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
# Common helpers
# ---------------------------------------------------------------------------


def configure_logging(level: str) -> None:
    """Configures the root logger with the ``LOG_LEVEL`` level."""
    numeric = logging.getLevelName(level.upper())
    if not isinstance(numeric, int):
        numeric = logging.INFO
    logging.basicConfig(
        level=numeric,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # These libraries are very chatty in DEBUG and add nothing.
    for noisy in ("websockets", "httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(max(numeric, logging.INFO))


def _run(coro: Coroutine[Any, Any, int]) -> int:
    """Runs a main coroutine with a clean exit on Ctrl+C or SIGTERM."""

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
            print("\nExiting.", file=sys.stderr)
            return 0

    try:
        return asyncio.run(guarded())
    except KeyboardInterrupt:
        print("\nExiting.", file=sys.stderr)
        return 0


async def _aclose(obj: Any) -> None:
    """Closes a component if it exposes an async ``aclose``/``close``."""
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
    """Plays PCM s16le with sounddevice (blocking; call it from a thread)."""
    import numpy as np
    import sounddevice as sd

    samples = np.frombuffer(pcm, dtype="<i2")
    sd.play(samples, sample_rate, blocking=True)


# ---------------------------------------------------------------------------
# Local player and console "tap" for `sonia chat`
# ---------------------------------------------------------------------------


class LocalPlayer:
    """Plays on the speaker the chunks that would go to the avatar client (``chat --speak``)."""

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
        """Drops whatever is left to play (``stop_speaking``)."""
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
    """Wraps the hub: prints what matters to the console and forwards everything to the client.

    Without a local player, it confirms each utterance (``playback_done``) as soon
    as it has been sent, so the orchestrator does not wait for an avatar client
    that may not be connected.
    """

    def __init__(self, inner: Hub, *, player: LocalPlayer | None = None) -> None:
        self._inner = inner
        self._player = player
        #: Set by whoever builds the engine (``LiveEngine.notify_playback_done``).
        self.playback_done: Callable[[int], None] | None = None

    def notify_playback_done(self, utterance_id: int) -> None:
        if self.playback_done is not None:
            self.playback_done(utterance_id)

    def on(self, type: str, callback: MessageCallback) -> None:
        self._inner.on(type, callback)

    @property
    def client_count(self) -> int:
        return self._inner.client_count

    async def broadcast_bytes(self, data: bytes) -> None:
        await self._inner.broadcast_bytes(data)

    async def broadcast_json(self, msg: dict[str, Any]) -> None:
        kind = msg.get("type")
        if kind == p.MSG_STATE:
            print(f"  [{msg['state']}]", flush=True)
        elif kind == p.MSG_TRANSCRIPT and msg.get("role") == "assistant" and msg.get("final", True):
            # GPT-Live sends the text in pieces (``final`` false) while it speaks: the
            # console only prints the complete sentence.
            print(f"Sonnia: {msg['text']}", flush=True)
        elif kind == p.MSG_ERROR:
            print(f"  [error] {msg['message']}", flush=True)
        elif kind == p.MSG_TRIVIA_ANSWER:
            print(f"  [trivia: {'correct' if msg['is_correct'] else 'wrong'}]", flush=True)
        elif kind == p.MSG_TRIVIA_END:
            print(f"  [trivia: {msg['score']} of {msg['total']}, {msg['reason']}]", flush=True)
        elif kind == p.MSG_STOP_SPEAKING:
            print("  [interrupted]", flush=True)
            if self._player is not None:
                self._player.flush()
        elif kind == p.MSG_SPEECH_END and self._player is None and self._inner.client_count == 0:
            # Without a local player and without a client nobody confirms the utterance.
            # If a client is connected it does, and confirming here would bring ``idle``
            # forward by up to two seconds: the avatar would go back to its idle
            # animation with the mouth still moving.
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
        print(f"  [image: {image_id} ({source}, {len(data)} bytes){extra}]", flush=True)
        await self._inner.show_image(
            image_id=image_id, source=source, mime=mime, data=data, caption=caption
        )

    async def hide_image(self) -> None:
        print("  [image hidden]", flush=True)
        await self._inner.hide_image()


@dataclass(slots=True)
class Components:
    """What the GPT-Live engine needs: there is no STT, TTS or VAD."""

    settings: Settings
    hub: Hub
    camera: CameraSource
    policy: VisionPolicy
    registry: ActionRegistry
    #: Vision model that describes the camera (``LLM_*``), if vision is on.
    llm: LLMClient | None
    narrator: VisionNarrator | None

    def action_context(self) -> ActionContext:
        return ActionContext(
            camera=self.camera,
            avatar=self.hub,
            gallery_dir=str(self.settings.gallery_dir),
            gallery_upload_dir=self.settings.gallery_upload_dir,
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
        include_look=policy.enabled,
        include_trivia=_trivia_ready(settings),
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
    """Is there a question bank for the trivia? Without one its actions are not announced."""
    if not settings.trivia.enabled:
        return False
    from sonia.trivia import TriviaBank

    count = len(TriviaBank.from_file(settings.trivia_file))
    if count < settings.trivia.questions:
        logger.warning(
            "Trivia off: %s has %d valid questions and %d are needed",
            settings.trivia_file,
            count,
            settings.trivia.questions,
        )
        return False
    return True


def _vision_model_ready(settings: Settings, *, warn: bool = True) -> bool:
    """Is there a vision model with a key? Without a key the camera turns off with a clear warning."""
    llm = settings.llm
    if not llm.supports_vision:
        return False
    if llm.key:
        return True
    if warn:
        logger.warning("Camera off: %s", _missing_vision_key(settings))
    return False


def _missing_vision_key(settings: Settings) -> str:
    """Which key the vision model lacks, told for whoever edits the ``.env``."""
    base_url = settings.llm.base_url
    if is_openai_url(base_url):
        return f"the OpenAI key is missing for {base_url} (OPENAI_API_KEY, LIVE_API_KEY or LLM_API_KEY)"
    return f"LLM_API_KEY is missing for {base_url} (the OpenAI key is only used with OpenAI's API)"


def _missing_live_key(settings: Settings) -> bool:
    if settings.live.api_key:
        return False
    print(
        "LIVE_API_KEY (or OPENAI_API_KEY) is missing in .env to use GPT-Live.",
        file=sys.stderr,
    )
    return True


def _log_summary(settings: Settings, components: Components) -> None:
    live = settings.live
    logger.info(
        "Sonnia %s | WS ws://%s:%d | GPT-Live %s (voice %s, %d Hz) | backend %s | vision %s | "
        "camera %s",
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
    """Real-time silence towards GPT-Live (without a microphone or while it reopens)."""
    deadline = None if seconds is None else time.monotonic() + seconds
    async for block in silence_blocks(settings.live.sample_rate, settings.audio.block_ms):
        if deadline is not None and time.monotonic() >= deadline:
            return
        await engine.push_mic(block)


async def _live_mic_loop(
    settings: Settings, engine: LiveEngine, switch: asyncio.Event | None = None
) -> None:
    """Microphone → GPT-Live, reopening it when it fails.

    It retries forever; while the microphone is down, silence is sent so the
    session stays alive and ``text_input`` keeps working. Before reopening, the
    devices are read again so a USB microphone shows up if it was unplugged and
    plugged back in (there are no other audio streams open here).
    """
    from sonia.audio.capture import MicCapture, refresh_devices

    while True:
        switched = False
        try:
            async with MicCapture(settings.audio, sample_rate=settings.live.sample_rate) as mic:
                async for block in mic.blocks():
                    await engine.push_mic(block)
                    if switch is not None and switch.is_set():
                        # Another microphone was picked in the options menu (sonia/devices.py).
                        switch.clear()
                        switched = True
                        break
            if switched:
                await asyncio.to_thread(refresh_devices)
                continue
            logger.warning(
                "The microphone closed on its own; reopening in %.0f s", MIC_RETRY_DELAY_S
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "The microphone failed (%s); retrying in %.0f s. Meanwhile Sonnia only "
                "answers text_input over the WebSocket",
                exc,
                MIC_RETRY_DELAY_S,
                exc_info=logger.isEnabledFor(logging.DEBUG),
            )
        await _feed_silence(engine, settings, MIC_RETRY_DELAY_S)
        await asyncio.to_thread(refresh_devices)


@dataclass(slots=True)
class _Panel:
    control: PanelControl
    server: Any
    logs: LogBuffer


async def _start_panel(
    settings: Settings,
    hub: Hub,
    registry: ActionRegistry,
    *,
    engine: LiveEngine,
    voice_cache: VoiceCache | None = None,
) -> _Panel | None:
    """Starts the control panel. Before ``engine.run()``.

    The control starts even if the web server is missing: it applies the saved
    mode (for example, staying "Away" after a restart without spending).
    """
    if not settings.panel.enabled:
        return None
    from sonia.panel.events import PanelEvents
    from sonia.panel.server import PanelServer
    from sonia.panel.server import is_available as panel_available

    logs = LogBuffer()
    logs.bind(asyncio.get_running_loop())
    logging.getLogger().addHandler(logs)
    events = PanelEvents(hub, logs)
    control = PanelControl(
        settings,
        hub=hub,
        registry=registry,
        engine=engine,
        voice_cache=voice_cache,
    )
    await control.start()
    server: Any = None
    if panel_available():
        server = PanelServer(settings.panel, control, hub, logs, events=events)
        try:
            await server.start()
        except Exception as exc:
            logger.warning("Could not start the local control panel: %s", exc)
            server = None
    else:
        logger.warning("The 'panel' extra is missing (uv sync --extra panel): no local panel")
    return _Panel(control, server, logs)


async def _stop_panel(panel: _Panel | None) -> None:
    if panel is None:
        return
    if panel.server is not None:
        with contextlib.suppress(Exception):
            await panel.server.stop()
    await panel.control.stop()
    logging.getLogger().removeHandler(panel.logs)


async def _warm_up_camera(camera: OpenCVCamera) -> None:
    await camera.warm_up()


async def cmd_run(settings: Settings, *, use_mic: bool = True) -> int:
    if _missing_live_key(settings):
        return 1
    # Microphone and camera picked in the options menu of this machine (sonia/devices.py).
    apply_choice(settings, load_choice(Path(settings.devices_file)))
    components = build_components(settings)
    _log_summary(settings, components)
    voice_cache = VoiceCache(settings.panel.voice_cache_dir, settings.live)
    engine = LiveEngine(
        settings,
        hub=components.hub,
        registry=components.registry,
        camera=components.camera,
        vision_policy=components.policy,
        narrator=components.narrator,
        voice_cache=voice_cache,
        knowledge_dir=settings.knowledge_dirs,
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
            )
            tasks.append(asyncio.create_task(engine.run(), name="live-engine"))
            if isinstance(components.camera, OpenCVCamera) and components.policy.enabled:
                # The camera permission is asked at startup, not with someone in front.
                tasks.append(
                    asyncio.create_task(_warm_up_camera(components.camera), name="camera-warm-up")
                )
            devices = DeviceManager(settings, components.hub, camera=components.camera)
            source = (
                _live_mic_loop(settings, engine, devices.mic_changed)
                if use_mic
                else _feed_silence(engine, settings, None)
            )
            tasks.append(asyncio.create_task(source, name="microphone"))
            if settings.sonia_parent_pid is not None:
                # Launched by the avatar app: if the app dies, exit as with Ctrl+C
                # (sonia/parent.py).
                main = asyncio.current_task()
                assert main is not None
                tasks.append(
                    asyncio.create_task(
                        watch_parent(settings.sonia_parent_pid, main.cancel), name="parent-watch"
                    )
                )
            logger.info("Sonnia is ready with GPT-Live. Ctrl+C to exit.")
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
        knowledge_dir=settings.knowledge_dirs,
    )
    tap.playback_done = engine.notify_playback_done

    tasks: list[asyncio.Task[None]] = []
    try:
        try:
            await components.hub.start()
        except OSError as exc:
            print(f"(no WebSocket: {exc}; is another Sonnia running?)", file=sys.stderr)
        if player is not None:
            await player.start()
        tasks.append(asyncio.create_task(engine.run(), name="live-engine"))
        tasks.append(asyncio.create_task(_feed_silence(engine, settings, None), name="silence"))
        print("Connecting to GPT-Live...", flush=True)
        for _ in range(int(settings.live.connect_timeout * 10)):
            if engine.connected:
                break
            await asyncio.sleep(0.1)
        print("Type and press Enter. 'exit' or Ctrl+D to finish.", flush=True)
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
        f"{len(pcm) / 2 / rate:.2f} s of audio at {rate} Hz with the {settings.live.voice} voice "
        f"in {elapsed:.2f} s",
        flush=True,
    )
    if out is not None:
        _write_wav(out, pcm, rate)
        print(f"Saved to {out}", flush=True)
    elif pcm:
        await asyncio.to_thread(_play_pcm_blocking, pcm, rate)
    return 0


async def _stdin_lines() -> Any:
    """Reads stdin lines without blocking the loop (cancellable with Ctrl+C)."""
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
    #: If something critical fails, ``sonia check`` exits with code 1.
    critical: bool = True


async def check_audio(settings: Settings) -> CheckResult:
    devices = await asyncio.to_thread(list_input_devices)
    if not devices:
        return CheckResult(
            "Microphone", False, "no input devices (is the 'audio' extra installed?)"
        )
    try:
        chosen = await asyncio.to_thread(resolve_input_device, settings.audio.input_device)
    except Exception as exc:
        return CheckResult("Microphone", False, str(exc))
    if chosen is None:
        default = next((d for d in devices if d.get("default")), devices[0])
        name = f"default: {default['name']}"
    else:
        match = next((d for d in devices if d["index"] == chosen), None)
        name = f"#{chosen}: {match['name']}" if match else f"#{chosen}"
    return CheckResult("Microphone", True, f"{len(devices)} device(s); {name}")


async def check_camera(settings: Settings) -> CheckResult:
    source = settings.vision.source
    if not settings.llm.supports_vision:
        return CheckResult("Camera", True, "vision disabled (LLM_SUPPORTS_VISION=false)", False)
    if source == "none":
        return CheckResult("Camera", True, "disabled (VISION_SOURCE=none)", False)
    if source == "unity":
        return CheckResult(
            "Camera", True, "sent by the avatar client over the WebSocket (not checked)", False
        )
    camera = build_camera(settings.vision)
    which = f"index {settings.vision.camera_index}"
    try:
        started = time.monotonic()
        frame = await asyncio.wait_for(camera.capture(), timeout=10.0)
        elapsed = time.monotonic() - started
    except Exception as exc:
        return CheckResult("Camera", False, f"{which}: {exc}", False)
    finally:
        await _aclose(camera)
    if frame is None:
        return CheckResult("Camera", False, f"{which}: no image", False)
    return CheckResult(
        "Camera",
        True,
        f"{which}: {frame.width}x{frame.height}, {len(frame.data)} bytes in {elapsed * 1000:.0f} ms",
        False,
    )


async def check_llm(settings: Settings) -> CheckResult:
    """A single minimal request (``max_tokens=5``) to the configured endpoint."""
    target = f"{settings.llm.base_url} ({settings.llm.model})"
    try:
        async with LLMClient(settings.llm) as client:
            started = time.monotonic()
            reply = await asyncio.wait_for(client.ping(), timeout=settings.llm.request_timeout)
            elapsed = time.monotonic() - started
    except Exception as exc:
        return CheckResult("LLM", False, f"{target}: {exc}")
    return CheckResult("LLM", True, f"{target}: '{reply}' in {elapsed * 1000:.0f} ms")


async def check_live(settings: Settings) -> CheckResult:
    """Opens and closes a GPT-Live session (a few seconds of session, cents)."""
    live = settings.live
    target = f"{live.model} (voice {live.voice})"
    if not live.api_key:
        return CheckResult("GPT-Live", False, f"{target}: LIVE_API_KEY or OPENAI_API_KEY missing")
    try:
        result = await probe_session(live)
    except Exception as exc:
        return CheckResult("GPT-Live", False, f"{target}: {exc}")
    expiry = (
        f"; the session lasts {result.expires_in_s / 60:.0f} min"
        if result.expires_in_s is not None
        else ""
    )
    return CheckResult(
        "GPT-Live",
        True,
        f"{live.model} (voice {result.voice}): session opened in "
        f"{result.elapsed_s * 1000:.0f} ms{expiry}; backend {live.backend_model}",
    )


async def check_vision_model(settings: Settings) -> CheckResult:
    """With GPT-Live, ``LLM_*`` only describes the camera: a ping and a minimal image."""
    policy = VisionPolicy(settings.vision, settings.llm.supports_vision)
    if not policy.enabled:
        return CheckResult(
            "Vision", True, "disabled (no camera or LLM_SUPPORTS_VISION=false)", False
        )
    if not _vision_model_ready(settings, warn=False):
        return CheckResult("Vision", False, _missing_vision_key(settings), False)
    llm = await check_llm(settings)
    if not llm.ok:
        return CheckResult("Vision", False, llm.detail, False)
    features = await check_vision_features(settings)
    if not features.ok:
        return CheckResult("Vision", False, features.detail, False)
    return CheckResult("Vision", True, f"{llm.detail}; accepts images", False)


async def run_checks(settings: Settings) -> list[CheckResult]:
    """Runs every check in order and returns their results."""
    return [
        await check_audio(settings),
        await check_camera(settings),
        await check_live(settings),
        await check_vision_model(settings),
        check_gallery(settings),
    ]


async def check_vision_features(settings: Settings) -> CheckResult:
    """A minimal request with an image, just like the camera is described on each turn.

    ``ping`` only sends text: a model without vision would pass the check and then
    fail on every description. It is a warning, not a critical failure: Sonnia
    converses without eyes too.
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
            "Vision",
            False,
            f"it does not accept images ({exc}); check LLM_BASE_URL, LLM_MODEL and LLM_API_KEY",
            False,
        )
    return CheckResult("Vision", True, "accepts images", False)


def check_gallery(settings: Settings) -> CheckResult:
    gallery = Gallery(settings.gallery_dir, settings.gallery_upload_dir)
    if not gallery.path.is_dir():
        return CheckResult("Gallery", False, f"{gallery.path} does not exist", False)
    ids = gallery.ids()
    if not ids:
        return CheckResult("Gallery", False, f"{gallery.path} has no images", False)
    return CheckResult("Gallery", True, f"{len(ids)} image(s): {', '.join(ids)}", False)


def print_results(results: list[CheckResult]) -> bool:
    """Prints one line per check. Returns ``True`` if nothing critical failed."""
    all_ok = True
    for result in results:
        label = "OK  " if result.ok else ("FAIL" if result.critical else "WARN")
        print(f"{label}  {result.name:<10} {result.detail}", flush=True)
        if not result.ok and result.critical:
            all_ok = False
    print("All set." if all_ok else "There are critical failures.", flush=True)
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
        description="Sonnia: a real-time voice assistant with a 3D avatar.",
    )
    parser.add_argument("--version", action="version", version=f"sonia {__version__}")
    parser.add_argument(
        "--log-level",
        default=None,
        help="log level (default: LOG_LEVEL from the environment).",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser(
        "run", help="full experience: microphone, camera, GPT-Live and avatar"
    )
    run.add_argument(
        "--no-mic",
        action="store_true",
        help="do not open the microphone; typed text only (panel or text_input)",
    )

    chat = commands.add_parser("chat", help="type to Sonnia from the console")
    chat.add_argument("--speak", action="store_true", help="play her voice on the speaker")

    say = commands.add_parser("say", help="have GPT-Live read a text with its voice")
    say.add_argument("text", help="text to read")
    say.add_argument("--out", type=Path, default=None, help="save to a WAV instead of playing it")

    commands.add_parser("check", help="check microphone, camera, GPT-Live, vision and gallery")
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
