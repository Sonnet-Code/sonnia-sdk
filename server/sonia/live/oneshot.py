"""Short GPT-Live sessions for ``sonia check`` and ``sonia say``.

Each one opens a session, does the bare minimum and closes it. Sessions are
billed per second, so they last only as long as needed: a few seconds.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Any

from sonia.config import LiveSettings
from sonia.live.audio import silence_blocks
from sonia.live.client import LiveClient, LiveError, WsConnect, describe_error

__all__ = ["ProbeResult", "max_reading_seconds", "probe_session", "speak_text"]

#: Instructions of the ``sonia say`` reading session.
SAY_INSTRUCTIONS = (
    "You are a read-aloud voice. Say every text you receive out loud exactly as it is "
    "written, in its own language, without adding, removing or commenting on anything, and "
    "then stay silent. Do not greet or speak on your own."
)

SAY_REQUEST = "{text}"

#: Silence after the last voice after which the reading counts as finished.
SAY_END_GAP_S = 1.5

#: The same once its transcript has reached the end of the text: GPT-Live
#: sometimes keeps talking on its own after a short pause (it once made up a
#: talk after a greeting), and that must not end up recorded.
SAY_COVERED_GAP_S = 0.4

#: Maximum reasonable length of a reading: a fixed margin plus seconds per
#: character (normal speech runs at about 0.06-0.08 s per character; singing, a bit more).
_MAX_BASE_S = 1.5
_MAX_PER_CHAR_S = 0.11

#: RMS level (0..1) above which a chunk counts as voice (GPT-Live sends digital silence, 0).
VOICE_RMS = 0.003

#: Silence kept at the end of the recording so it does not sound cut off.
_TAIL_S = 0.15

#: Silence blocks that keep the session timeline going.
_SILENCE_BLOCK_MS = 40


def max_reading_seconds(text: str) -> float:
    """The longest the reading of ``text`` can last without anything added to it."""
    return _MAX_BASE_S + _MAX_PER_CHAR_S * len(text.strip())


@dataclass(slots=True)
class ProbeResult:
    session_id: str
    elapsed_s: float
    voice: str
    expires_in_s: float | None


def _session(settings: LiveSettings, instructions: str) -> dict[str, Any]:
    return {
        "model": settings.model,
        "instructions": instructions,
        "audio": {
            "format": {"type": "audio/pcm", "rate": int(settings.sample_rate)},
            "output": {"voice": settings.voice},
        },
    }


async def probe_session(settings: LiveSettings, *, connect: WsConnect | None = None) -> ProbeResult:
    """Opens and closes a session: checks the key, access to the model and the voice."""
    client = LiveClient(settings, connect=connect)
    started = time.monotonic()
    try:
        session = await client.start(_session(settings, "Answer in English."))
        elapsed = time.monotonic() - started
    finally:
        await client.close()
    audio = session.get("audio")
    output = audio.get("output") if isinstance(audio, dict) else None
    voice = output.get("voice") if isinstance(output, dict) else None
    expires = client.expires_at
    return ProbeResult(
        session_id=client.session_id,
        elapsed_s=elapsed,
        voice=str(voice or settings.voice),
        expires_in_s=(expires - time.time()) if expires is not None else None,
    )


async def speak_text(
    settings: LiveSettings,
    text: str,
    *,
    connect: WsConnect | None = None,
    timeout_s: float = 30.0,
) -> bytes:
    """Makes GPT-Live read ``text`` and returns the mono PCM s16le of its voice.

    GPT-Live sends audio nonstop (silence too), so the reading starts with the
    first voiced chunk and ends after ``SAY_END_GAP_S`` of unvoiced audio, or
    ``SAY_COVERED_GAP_S`` if its transcript has already reached the end of the
    text. The silence before and after is trimmed. If the voice lasts longer
    than :func:`max_reading_seconds`, GPT-Live added something of its own and
    :class:`LiveError` is raised instead of returning it.
    """
    client = LiveClient(settings, connect=connect)
    await client.start(_session(settings, SAY_INSTRUCTIONS))
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def feed_silence() -> None:
        with contextlib.suppress(Exception):
            async for block in silence_blocks(settings.sample_rate, _SILENCE_BLOCK_MS):
                await client.append_audio(bytes(len(block) * 2))

    async def read() -> None:
        # A separate reader: cancelling a wait never closes the event stream.
        with contextlib.suppress(Exception):
            async for event in client.events():
                await queue.put(event)
        await queue.put(None)

    tasks = [
        asyncio.create_task(feed_silence(), name="sonia-say-silence"),
        asyncio.create_task(read(), name="sonia-say-read"),
    ]
    chunks: list[bytes] = []
    last_voice_index = -1
    rate = int(settings.sample_rate)
    limit_s = max_reading_seconds(text)
    tail_words = _words(text)[-2:]
    transcript: list[str] = []
    covered = False
    try:
        # ``commentary`` is what makes her speak (``instructions`` does not).
        await client.append_commentary(SAY_REQUEST.format(text=text))
        deadline = time.monotonic() + timeout_s
        last_voice: float | None = None
        voiced_s = 0.0  # audio since the first voice
        silent_run_s = 0.0  # unvoiced audio since the last voice
        while True:
            now = time.monotonic()
            gap = SAY_COVERED_GAP_S if covered else SAY_END_GAP_S
            if now >= deadline or (last_voice is not None and now - last_voice >= SAY_END_GAP_S):
                break
            if last_voice is not None and (silent_run_s >= gap or voiced_s > limit_s + 1.0):
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=0.2)
            except TimeoutError:
                continue
            if event is None:
                break
            kind = event.get("type")
            if kind == "session.output_audio.delta":
                data = event.get("delta")
                if not isinstance(data, str) or not data:
                    continue
                with contextlib.suppress(binascii.Error, ValueError):
                    pcm = base64.b64decode(data)
                    if len(pcm) % 2:
                        pcm = pcm[:-1]
                    seconds = len(pcm) / 2 / rate
                    if _rms(pcm) >= VOICE_RMS:
                        if last_voice is None:
                            chunks.clear()  # drop the silence before
                        last_voice = time.monotonic()
                        chunks.append(pcm)
                        last_voice_index = len(chunks) - 1
                        voiced_s += seconds
                        silent_run_s = 0.0
                    elif last_voice is not None:
                        chunks.append(pcm)
                        voiced_s += seconds
                        silent_run_s += seconds
            elif kind == "session.output_transcript.delta":
                delta = event.get("delta")
                if isinstance(delta, str) and delta and not covered and tail_words:
                    transcript.append(delta)
                    covered = _contains(_words("".join(transcript)), tail_words)
            elif kind == "error":
                raise LiveError(describe_error(event))
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await client.close()
    # Drop the silence after, except a short tail so it does not sound cut off.
    kept = b"".join(chunks[: last_voice_index + 1] if last_voice_index >= 0 else [])
    if len(kept) / 2 / rate > limit_s:
        raise LiveError(
            f"GPT-Live did not stick to reading the text: {len(kept) / 2 / rate:.1f} s of voice "
            f"for {len(text.strip())} characters (maximum {limit_s:.1f} s)"
        )
    tail = b"".join(chunks[last_voice_index + 1 :])[: int(rate * _TAIL_S) * 2]
    return kept + tail


def _words(text: str) -> list[str]:
    """Lowercase words, without accents, punctuation or tags like "[laugh]"."""
    text = re.sub(r"\[[^\[\]]*\]?", " ", text)
    plain = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9ñ]+", plain)


def _contains(words: list[str], needle: list[str]) -> bool:
    """Does ``needle`` appear as a contiguous run inside ``words``?"""
    n = len(needle)
    return any(words[i : i + n] == needle for i in range(len(words) - n + 1))


def _rms(pcm: bytes) -> float:
    import numpy as np

    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    return float(np.sqrt(np.mean(samples * samples))) if len(samples) else 0.0
