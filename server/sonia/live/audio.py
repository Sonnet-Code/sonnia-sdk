"""Input audio towards GPT-Live: PCM, the microphone gate and silence.

GPT-Live is a full-duplex model: it expects a continuous real-time microphone
stream, also while it speaks. :class:`MicGate` decides on each block whether the
realtime model hears the microphone or a very soft noise of the same size
(:class:`ComfortNoise`), putting all the measures together: the microphone muted
from the panel, the recorded lines and the noise gate. The stream is never cut,
so the session timeline does not stop.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Literal

import numpy as np

from sonia.types import AudioArray

__all__ = [
    "ComfortNoise",
    "MicGate",
    "NoiseGate",
    "Reason",
    "pcm16_from_float",
    "rms",
    "silence_blocks",
]


def pcm16_from_float(block: AudioArray) -> bytes:
    """Float32 in [-1, 1] to mono PCM s16le."""
    clipped = np.clip(np.asarray(block, dtype=np.float32), -1.0, 1.0)
    return (clipped * 32767.0).astype("<i2").tobytes()


def rms(block: AudioArray) -> float:
    """RMS level of a float32 block (0..1)."""
    if len(block) == 0:
        return 0.0
    samples = np.asarray(block, dtype=np.float32)
    return float(np.sqrt(np.mean(samples * samples)))


class NoiseGate:
    """Lets the microphone through only when someone speaks close by.

    It opens as soon as a block goes over ``threshold`` and closes after
    ``hold_ms`` without any above it: that way it does not cut the pauses between
    words. With ``threshold`` 0 it is always open. It keeps no audio from before
    opening: losing a few milliseconds of the start of the first syllable does not
    affect a voice model, and feeding late audio would shift the session timeline.
    """

    def __init__(self, threshold: float, hold_ms: int) -> None:
        self._threshold = max(0.0, threshold)
        self._hold_s = max(0, hold_ms) / 1000.0
        self._open_until = 0.0

    @property
    def enabled(self) -> bool:
        return self._threshold > 0.0

    def admit(self, level: float, now: float | None = None) -> bool:
        """Does the block with this RMS level get through?"""
        if not self.enabled:
            return True
        now = time.monotonic() if now is None else now
        if level >= self._threshold:
            self._open_until = now + self._hold_s
            return True
        return now < self._open_until


class ComfortNoise:
    """Very soft noise sent to GPT-Live instead of the microphone.

    With absolute zeros GPT-Live understood the user 7 to 40 s late and did not
    say the result of a delegated task until it heard something again; with room
    noise, right away. With ``level`` 0 it sends zeros.
    """

    def __init__(self, level: float, seed: int | None = None) -> None:
        self._level = max(0.0, level)
        self._rng = np.random.default_rng(seed)

    def pcm(self, samples: int) -> bytes:
        """``samples`` samples of noise in PCM s16le, with RMS ``level``."""
        if self._level <= 0.0:
            return bytes(samples * 2)
        noise = self._rng.standard_normal(samples).astype(np.float32) * self._level
        return pcm16_from_float(noise)


#: Why GPT-Live does not hear a microphone block; empty if it does.
Reason = Literal["", "muted", "recorded line", "silence", "noise gate"]


class MicGate:
    """The microphone gate: what GPT-Live hears on each block, the microphone or a soft noise.

    All the measures decide together, in this order; the first one that does not
    let the block through gives the reason (``reason``, shown by the panel):

    1. ``muted``: the microphone is muted from the panel.
    2. ``recorded line``: a line from ``cache/voice`` is playing (GPT-Live did not
       say it and would answer it).
    3. ``silence``: the block is empty (``--no-mic``, a microphone without permission).
    4. ``noise gate``: it does not reach the noise gate (``LIVE_GATE_RMS``).

    What does not get through arrives as :class:`ComfortNoise`
    (``LIVE_COMFORT_NOISE_RMS``), never as zeros. Each measure can be turned off:
    ``LIVE_GATE_RMS=0`` (or the "Noise gate" control of the panel) and
    ``LIVE_COMFORT_NOISE_RMS=0``.
    """

    def __init__(
        self,
        *,
        threshold: float,
        hold_ms: int,
        comfort_rms: float,
        silence_rms: float = 0.0,
    ) -> None:
        self._hold_ms = hold_ms
        self._noise = NoiseGate(threshold, hold_ms)
        self._comfort = ComfortNoise(comfort_rms)
        self._silence_rms = silence_rms
        #: Why GPT-Live did not hear the last block (empty if it did).
        self.reason: Reason = ""

    def set_threshold(self, threshold: float) -> None:
        """Changes the noise gate (the "Noise gate" control of the panel)."""
        self._noise = NoiseGate(threshold, self._hold_ms)

    def check(self, level: float, now: float, *, muted: bool = False, echo: bool = False) -> Reason:
        """Why GPT-Live would not hear a block with this RMS level (empty: it hears it)."""
        if muted:
            return "muted"
        if echo:
            return "recorded line"
        if level <= self._silence_rms:
            return "silence"
        if not self._noise.admit(level, now):
            return "noise gate"
        return ""

    def pcm(
        self,
        block: AudioArray,
        level: float,
        now: float,
        *,
        muted: bool = False,
        echo: bool = False,
    ) -> bytes:
        """What is sent to GPT-Live for this block: the microphone or the soft noise."""
        self.reason = self.check(level, now, muted=muted, echo=echo)
        if self.reason:
            return self._comfort.pcm(len(block))
        return pcm16_from_float(block)


async def silence_blocks(sample_rate: int, block_ms: int) -> AsyncIterator[AudioArray]:
    """Silence blocks at real-time pace, for when there is no microphone.

    It is scheduled against the clock (not with a fixed ``sleep``) so that loop
    delays do not add up and the stream does not fall behind real time.
    """
    samples = max(1, sample_rate * block_ms // 1000)
    period = samples / sample_rate
    block: AudioArray = np.zeros(samples, dtype=np.float32)
    next_at = time.monotonic()
    while True:
        yield block
        next_at += period
        delay = next_at - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        elif delay < -1.0:
            # The loop was blocked: lost time is not recovered in bursts, it
            # resynchronizes with the clock.
            next_at = time.monotonic()
