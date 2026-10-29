"""Microphone capture with `sounddevice`, delivered to the asyncio loop in blocks.

The PortAudio callback runs in its own thread and must not block: it only
copies the block and hands it to the loop with ``loop.call_soon_threadsafe``.
The queue is bounded; if the consumer falls behind, the oldest blocks are
dropped (better to lose old audio than to build up latency).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator
from types import TracebackType
from typing import Any, Self

import numpy as np

from sonia.config import AudioSettings
from sonia.types import INPUT_SAMPLE_RATE, AudioArray

_log = logging.getLogger(__name__)

#: Maximum blocks in the queue (with 32 ms blocks that is ~1.6 s of audio).
QUEUE_MAXSIZE = 50

#: Minimum seconds between two identical warnings, so the log is not flooded.
_WARN_INTERVAL_S = 5.0

#: If PortAudio stops delivering blocks for this long, the microphone is
#: considered dead. While the stream is alive the callback keeps coming even
#: in absolute silence, so a gap of seconds only happens when the device
#: disappears or the stream is aborted without notice.
DEFAULT_STALL_TIMEOUT_S = 3.0

#: If, after sound has arrived, only digital silence (every sample exactly
#: zero) arrives for this long, the stream is considered stuck: a real
#: microphone always carries some noise. It happens when a USB mic is unplugged
#: and plugged back in: PortAudio keeps delivering blocks, but empty ones, from
#: the device that no longer exists.
DEFAULT_SILENCE_TIMEOUT_S = 5.0


class MicStalled(RuntimeError):
    """The microphone stopped delivering audio (or only delivers zeros) but the stream is open."""


def refresh_devices() -> None:
    """Reloads the system audio devices.

    PortAudio only reads them when it initializes, so a USB microphone that is
    unplugged and plugged back in does not show up (or still points to the one
    that no longer exists) until the process restarts. Only call it with no
    stream open. If it fails, it warns and keeps the previous list.
    """
    try:
        import sounddevice as sd

        sd._terminate()
        sd._initialize()
    except Exception as exc:  # noqa: BLE001 - depends on the hardware and PortAudio
        _log.warning("Could not reload the list of audio devices: %s", exc)


def list_input_devices() -> list[dict[str, Any]]:
    """Returns the available input devices (for ``sonia check``).

    Each item has ``index``, ``name``, ``channels``, ``sample_rate`` and
    ``default``. If `sounddevice` is not installed or PortAudio fails, it returns
    an empty list instead of raising: the app must still start.
    """
    try:
        import sounddevice as sd
    except Exception:  # pragma: no cover - depends on the environment
        _log.warning("sounddevice is not available: cannot list microphones")
        return []

    try:
        devices = sd.query_devices()
        default_index = _default_input_index(sd)
    except Exception as exc:  # pragma: no cover - depends on the hardware
        _log.warning("Could not query the audio devices: %s", exc)
        return []

    result: list[dict[str, Any]] = []
    for position, device in enumerate(devices):
        if int(device.get("max_input_channels", 0)) <= 0:
            continue
        index = int(device.get("index", position))
        result.append(
            {
                "index": index,
                "name": str(device.get("name", "")),
                "channels": int(device.get("max_input_channels", 0)),
                "sample_rate": float(device.get("default_samplerate", 0.0)),
                "default": index == default_index,
            }
        )
    return result


def _default_input_index(sd: Any) -> int | None:
    """Index of the default input device, or ``None`` if there is none."""
    try:
        default = sd.default.device
    except Exception:  # pragma: no cover - depends on the hardware
        return None
    value = default[0] if isinstance(default, list | tuple) and default else default
    try:
        index = int(value)
    except (TypeError, ValueError):
        return None
    return index if index >= 0 else None


def resolve_input_device(spec: str) -> int | None:
    """Translates the ``input_device`` setting into a sounddevice id.

    Accepts a numeric index, a fragment of the device name (case-insensitive
    substring match) or an empty string for the default device.
    """
    spec = (spec or "").strip()
    if not spec:
        return None

    try:
        return int(spec)
    except ValueError:
        pass

    import sounddevice as sd

    needle = spec.casefold()
    devices = sd.query_devices()
    for position, device in enumerate(devices):
        if int(device.get("max_input_channels", 0)) <= 0:
            continue
        if needle in str(device.get("name", "")).casefold():
            return int(device.get("index", position))

    available = ", ".join(d["name"] for d in list_input_devices()) or "none"
    raise ValueError(f"No microphone found whose name contains {spec!r}. Available: {available}")


def input_device_or_default(spec: str) -> int | None:
    """Like :func:`resolve_input_device`, but falls back to the system one if that mic is missing.

    The ``.env`` of one machine (or the one bundled in the app) may name a
    microphone that does not exist on another machine: then it warns and uses
    the default one, instead of ending up with no microphone.
    """
    try:
        return resolve_input_device(spec)
    except ValueError as exc:
        _log.warning("%s. Using the system default microphone.", exc)
        return None


def default_input_name() -> str:
    """Name of the system default microphone (empty if unknown)."""
    try:
        import sounddevice as sd

        device = sd.query_devices(kind="input")
    except Exception:  # noqa: BLE001 - depends on the hardware
        return ""
    return str(device.get("name", "")) if isinstance(device, dict) else ""


class MicCapture:
    """Mono float32 microphone as an asynchronous stream of blocks.

    At ``INPUT_SAMPLE_RATE`` by default. The GPT-Live engine opens it at its
    session rate (``LIVE_SAMPLE_RATE``) to avoid resampling.

    Usage::

        async with MicCapture(settings.audio) as mic:
            async for block in mic.blocks():
                ...
    """

    def __init__(
        self,
        settings: AudioSettings,
        *,
        stall_timeout: float = DEFAULT_STALL_TIMEOUT_S,
        silence_timeout: float = DEFAULT_SILENCE_TIMEOUT_S,
        sample_rate: int = INPUT_SAMPLE_RATE,
    ) -> None:
        self._settings = settings
        self._stall_timeout = stall_timeout
        self._silence_timeout = silence_timeout
        self._sample_rate = sample_rate
        self._block_samples = max(1, settings.block_ms * sample_rate // 1000)
        self._queue: asyncio.Queue[AudioArray | None] = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stream: Any = None
        self._closed = False
        self._dropped = 0
        self._last_warning: dict[str, float] = {}

    # -- properties ------------------------------------------------------

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def block_samples(self) -> int:
        """Samples per block (``block_ms`` at the microphone rate)."""
        return self._block_samples

    @property
    def dropped_blocks(self) -> int:
        """Blocks dropped because of a full queue since the microphone was opened."""
        return self._dropped

    # -- context manager -------------------------------------------------

    async def __aenter__(self) -> Self:
        import sounddevice as sd

        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
        self._closed = False
        self._dropped = 0

        device = input_device_or_default(self._settings.input_device)
        self._stream = sd.InputStream(
            samplerate=self._sample_rate,
            blocksize=self._block_samples,
            device=device,
            channels=1,
            dtype="float32",
            callback=self._on_audio,
        )
        self._stream.start()
        _log.info(
            "Microphone open (device=%s, %d Hz, blocks of %d samples)",
            "default" if device is None else device,
            self._sample_rate,
            self._block_samples,
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Closes the stream and ends the block iterator."""
        self._closed = True
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception as err:  # pragma: no cover - depends on the hardware
                _log.warning("Error closing the microphone: %s", err)
        if self._dropped:
            _log.info("Dropped %d audio blocks because of a full queue", self._dropped)
        # Sentinel to unblock whoever is waiting in blocks(). If the queue is
        # full, make room by dropping the oldest block.
        if self._queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
        with contextlib.suppress(asyncio.QueueFull):
            self._queue.put_nowait(None)

    # -- block stream ----------------------------------------------------

    async def blocks(self) -> AsyncIterator[AudioArray]:
        """Yields mono float32 audio blocks until the stream is closed.

        If PortAudio stops calling the callback (microphone disconnected,
        default device changed, stream aborted) no exception arrives on its own:
        the coroutine would wait forever and Sonnia would silently go deaf. So
        the gap between blocks is watched and :class:`MicStalled` is raised,
        which the caller uses to reopen. Same if, after hearing something, only
        exact zeros arrive (the USB mic was unplugged and plugged back in); a mic
        that is mute from the start (with its mute button) is not reopened in a loop.
        """
        if self._stream is None and not self._closed:
            raise RuntimeError(
                "MicCapture.blocks() requires opening the microphone with 'async with'"
            )
        heard = False
        silent_since: float | None = None
        while True:
            timeout = self._stall_timeout if self._stall_timeout > 0 else None
            try:
                block = await asyncio.wait_for(self._queue.get(), timeout=timeout)
            except TimeoutError:
                if self._closed:
                    break
                raise MicStalled(
                    f"the microphone has delivered no audio for {self._stall_timeout:g} s "
                    f"(stream active: {self.stream_active})"
                ) from None
            if block is None:
                break
            if self._silence_timeout > 0:
                if block.any():
                    heard = True
                    silent_since = None
                elif heard:
                    now = time.monotonic()
                    if silent_since is None:
                        silent_since = now
                    elif now - silent_since >= self._silence_timeout:
                        raise MicStalled(
                            "the microphone has delivered only digital silence for "
                            f"{self._silence_timeout:g} s (was it unplugged?)"
                        )
            yield block

    @property
    def stream_active(self) -> bool:
        """Does PortAudio say the stream is still alive? (informational only)."""
        stream = self._stream
        if stream is None:
            return False
        try:
            return bool(stream.active)
        except Exception:  # noqa: BLE001 - depends on the PortAudio backend
            return False

    # -- internals -------------------------------------------------------

    def _on_audio(
        self,
        indata: np.ndarray[Any, Any],
        frames: int,
        time_info: Any,
        status: Any,
    ) -> None:
        """PortAudio callback. Runs in the audio thread: no blocking."""
        if status:
            self._warn_throttled("status", "Audio stream status: %s", status)
        loop = self._loop
        if loop is None or self._closed:
            return
        block: AudioArray = np.array(indata[:, 0], dtype=np.float32, copy=True)
        # If the loop is already closed, the block is simply lost.
        with contextlib.suppress(RuntimeError):  # pragma: no cover
            loop.call_soon_threadsafe(self._push, block)

    def _push(self, block: AudioArray) -> None:
        """Queues a block on the asyncio loop, dropping the oldest one if needed."""
        if self._closed:
            return
        if self._queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
            self._dropped += 1
            self._warn_throttled(
                "drop",
                "Audio queue full: dropping blocks (%d in total). Slow consumer?",
                self._dropped,
            )
        try:
            self._queue.put_nowait(block)
        except asyncio.QueueFull:  # pragma: no cover - unlikely race
            self._dropped += 1

    def _warn_throttled(self, key: str, message: str, *args: Any) -> None:
        """Logs a warning at most once every ``_WARN_INTERVAL_S`` seconds per key."""
        now = time.monotonic()
        if now - self._last_warning.get(key, 0.0) < _WARN_INTERVAL_S:
            return
        self._last_warning[key] = now
        _log.warning(message, *args)
