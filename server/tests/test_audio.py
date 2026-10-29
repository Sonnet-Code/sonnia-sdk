"""Tests for microphone capture.

No real device is opened: ``sounddevice`` is replaced with a fake one.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator, Callable
from typing import Any

import numpy as np
import pytest

from sonia.audio.capture import (
    QUEUE_MAXSIZE,
    MicCapture,
    MicStalled,
    list_input_devices,
    refresh_devices,
    resolve_input_device,
)
from sonia.config import AudioSettings
from sonia.types import INPUT_SAMPLE_RATE, AudioArray

BLOCK_MS = 32
BLOCK_SAMPLES = BLOCK_MS * INPUT_SAMPLE_RATE // 1000


def make_settings(**overrides: object) -> AudioSettings:
    """Deterministic audio settings for the tests (32 ms blocks)."""
    defaults: dict[str, object] = {"block_ms": BLOCK_MS}
    defaults.update(overrides)
    return AudioSettings(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Lazy imports
# ---------------------------------------------------------------------------


def test_modules_import_without_heavy_dependencies() -> None:
    import sonia.audio
    import sonia.audio.capture as capture

    assert hasattr(sonia.audio, "MicCapture")
    assert callable(capture.list_input_devices)


# ---------------------------------------------------------------------------
# Microphone capture (with a fake sounddevice: no hardware is ever opened)
# ---------------------------------------------------------------------------


class _FakeStream:
    """Fake sounddevice stream: keeps the callback and records its lifecycle."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs: dict[str, Any] = kwargs
        self.callback: Callable[..., None] = kwargs["callback"]
        self.started = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def close(self) -> None:
        self.closed = True


class _FakeSounddevice:
    """Fake `sounddevice` with two input devices."""

    DEVICES: list[dict[str, Any]] = [
        {
            "name": "MacBook Pro Microphone",
            "index": 0,
            "max_input_channels": 1,
            "default_samplerate": 48_000.0,
        },
        {"name": "Speakers", "index": 1, "max_input_channels": 0, "default_samplerate": 48_000.0},
        {
            "name": "Yeti Nano USB",
            "index": 2,
            "max_input_channels": 2,
            "default_samplerate": 44_100.0,
        },
    ]

    class default:  # noqa: N801 - mimics the sounddevice API
        device = [0, 1]

    def __init__(self) -> None:
        self.streams: list[_FakeStream] = []
        self.restarts: list[str] = []

    def query_devices(self) -> list[dict[str, Any]]:
        return list(self.DEVICES)

    def _terminate(self) -> None:
        self.restarts.append("terminate")

    def _initialize(self) -> None:
        self.restarts.append("initialize")

    def InputStream(self, **kwargs: Any) -> _FakeStream:  # noqa: N802 - sounddevice API
        stream = _FakeStream(**kwargs)
        self.streams.append(stream)
        return stream


@pytest.fixture
def fake_sd(monkeypatch: pytest.MonkeyPatch) -> _FakeSounddevice:
    fake = _FakeSounddevice()
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    return fake


def test_list_input_devices_only_returns_inputs(fake_sd: _FakeSounddevice) -> None:
    devices = list_input_devices()

    assert [d["index"] for d in devices] == [0, 2]
    assert devices[0]["default"] is True
    assert devices[1]["name"] == "Yeti Nano USB"


def test_resolve_input_device_accepts_index_name_and_empty(fake_sd: _FakeSounddevice) -> None:
    assert resolve_input_device("") is None
    assert resolve_input_device("  ") is None
    assert resolve_input_device("3") == 3
    assert resolve_input_device("yeti") == 2
    assert resolve_input_device("USB") == 2
    with pytest.raises(ValueError):
        resolve_input_device("missing microphone")


def test_missing_configured_mic_falls_back_to_the_system_one(
    fake_sd: _FakeSounddevice, caplog: pytest.LogCaptureFixture
) -> None:
    """The .env of another machine (or the app's) names a mic that does not exist here."""
    from sonia.audio.capture import input_device_or_default

    assert input_device_or_default("yeti") == 2
    assert input_device_or_default("condenser") is None
    assert "Using the system default microphone" in caplog.text


async def test_mic_capture_delivers_the_callback_blocks(fake_sd: _FakeSounddevice) -> None:
    settings = make_settings(input_device="yeti")

    async with MicCapture(settings) as mic:
        stream = fake_sd.streams[0]
        assert stream.started
        assert stream.kwargs["samplerate"] == INPUT_SAMPLE_RATE
        assert stream.kwargs["blocksize"] == BLOCK_SAMPLES
        assert stream.kwargs["channels"] == 1
        assert stream.kwargs["dtype"] == "float32"
        assert stream.kwargs["device"] == 2

        # The callback comes from the audio thread with (frames, channels) data.
        for value in (1.0, 2.0):
            stream.callback(
                np.full((BLOCK_SAMPLES, 1), value, dtype=np.float32), BLOCK_SAMPLES, None, None
            )

        received: list[AudioArray] = []
        async for block in mic.blocks():
            received.append(block)
            if len(received) == 2:
                break

    assert [float(b[0]) for b in received] == [1.0, 2.0]
    assert all(b.shape == (BLOCK_SAMPLES,) for b in received)
    assert stream.closed


async def test_mic_capture_drops_the_oldest_blocks(fake_sd: _FakeSounddevice) -> None:
    async with MicCapture(make_settings()) as mic:
        stream = fake_sd.streams[0]
        total = QUEUE_MAXSIZE + 5
        for value in range(total):
            stream.callback(
                np.full((BLOCK_SAMPLES, 1), float(value), dtype=np.float32),
                BLOCK_SAMPLES,
                None,
                None,
            )
        # The callbacks queue with call_soon_threadsafe: the loop has to yield.
        await asyncio.sleep(0)

        assert mic.dropped_blocks == 5
        first = await anext(mic.blocks())

    # The latest blocks were kept, not the first ones.
    assert float(first[0]) == 5.0


async def test_mic_capture_ends_the_iterator_on_close(fake_sd: _FakeSounddevice) -> None:
    mic = MicCapture(make_settings())
    async with mic:
        blocks = mic.blocks()
        task = asyncio.create_task(_drain(blocks))
        await asyncio.sleep(0)
    await asyncio.wait_for(task, timeout=1.0)


async def _drain(blocks: AsyncIterator[AudioArray]) -> list[AudioArray]:
    return [block async for block in blocks]


async def test_mic_capture_without_context_manager_fails() -> None:
    mic = MicCapture(make_settings())
    with pytest.raises(RuntimeError):
        await anext(mic.blocks())


async def test_mic_capture_raises_when_audio_stops_arriving(fake_sd: _FakeSounddevice) -> None:
    """PortAudio stops calling the callback: without this, `blocks()` never returns.

    That is what happens when the USB mic is disconnected or the default device
    changes: no exception arrives and Sonnia would silently go deaf.
    """
    async with MicCapture(make_settings(), stall_timeout=0.05) as mic:
        stream = fake_sd.streams[0]
        stream.callback(np.zeros((BLOCK_SAMPLES, 1), dtype=np.float32), BLOCK_SAMPLES, None, None)

        blocks = mic.blocks()
        assert (await anext(blocks)).shape == (BLOCK_SAMPLES,)
        with pytest.raises(MicStalled):
            await anext(blocks)


async def test_mic_capture_closing_is_not_mistaken_for_a_stall(
    fake_sd: _FakeSounddevice,
) -> None:
    mic = MicCapture(make_settings(), stall_timeout=0.05)
    async with mic:
        task = asyncio.create_task(_drain(mic.blocks()))
        await asyncio.sleep(0)
    assert await asyncio.wait_for(task, timeout=1.0) == []


async def test_mic_capture_reopens_if_only_zeros_arrive_after_hearing_something(
    fake_sd: _FakeSounddevice,
) -> None:
    """USB mic unplugged and plugged back in: blocks keep arriving, but all zeros."""
    async with MicCapture(make_settings(), silence_timeout=0.05) as mic:
        callback = fake_sd.streams[0].callback
        blocks = mic.blocks()
        callback(np.full((BLOCK_SAMPLES, 1), 0.01, dtype=np.float32), BLOCK_SAMPLES, None, None)
        await anext(blocks)
        callback(np.zeros((BLOCK_SAMPLES, 1), dtype=np.float32), BLOCK_SAMPLES, None, None)
        await anext(blocks)
        await asyncio.sleep(0.06)
        callback(np.zeros((BLOCK_SAMPLES, 1), dtype=np.float32), BLOCK_SAMPLES, None, None)
        with pytest.raises(MicStalled):
            await anext(blocks)


async def test_mic_capture_does_not_reopen_a_mic_mute_from_the_start(
    fake_sd: _FakeSounddevice,
) -> None:
    """Muted with its button since it was opened: reopening it fixes nothing."""
    async with MicCapture(make_settings(), silence_timeout=0.05) as mic:
        callback = fake_sd.streams[0].callback
        blocks = mic.blocks()
        for _ in range(3):
            callback(np.zeros((BLOCK_SAMPLES, 1), dtype=np.float32), BLOCK_SAMPLES, None, None)
            assert not (await anext(blocks)).any()
            await asyncio.sleep(0.03)


def test_refresh_devices_restarts_portaudio(fake_sd: _FakeSounddevice) -> None:
    refresh_devices()

    assert fake_sd.restarts == ["terminate", "initialize"]


def test_refresh_devices_does_not_raise_if_portaudio_fails(
    fake_sd: _FakeSounddevice, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom() -> None:
        raise RuntimeError("PortAudio not responding")

    monkeypatch.setattr(fake_sd, "_initialize", boom)

    refresh_devices()

    assert fake_sd.restarts == ["terminate"]
