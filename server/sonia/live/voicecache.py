"""Cache of fixed lines read once by GPT-Live.

The "Greeter only" mode and the idle animation say fixed lines (greetings,
lines and chants from ``assets/showcase``). Instead of opening a GPT-Live
session every time, each line is read only once with the configured voice,
saved as WAV and then played from disk: the same voice as in the conversation
and zero cost while Sonnia only greets.

The key of each file combines voice, rate and text: when the voice changes,
the lines are recorded again on their own.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import wave
from collections.abc import Iterable
from pathlib import Path

from sonia.config import LiveSettings
from sonia.live.client import WsConnect
from sonia.live.oneshot import max_reading_seconds, speak_text

__all__ = ["VoiceCache"]

logger = logging.getLogger(__name__)

#: Lines shorter than this count as failed (GPT-Live said nothing).
_MIN_SECONDS = 0.3

#: Consecutive failures after which recording stops.
_MAX_FAILURES = 2

#: Margin for the silence tail kept at the end of each recording.
_TAIL_SLACK_S = 0.3


class VoiceCache:
    """Fixed lines as WAV files inside ``directory``."""

    def __init__(
        self, directory: str | Path, settings: LiveSettings, *, connect: WsConnect | None = None
    ) -> None:
        self._dir = Path(directory)
        self._settings = settings
        self._connect = connect
        self._lock = asyncio.Lock()
        self.busy = False
        self.last_error = ""

    @property
    def directory(self) -> Path:
        return self._dir

    def path_for(self, text: str) -> Path:
        settings = self._settings
        key = f"{settings.voice}\n{settings.sample_rate}\n{text.strip()}"
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
        return self._dir / settings.voice / f"{digest}.wav"

    def has(self, text: str) -> bool:
        return self._usable(text)

    def get(self, text: str) -> bytes | None:
        """Mono PCM s16le of the line, or ``None`` if it is not recorded (or not usable)."""
        if not self._usable(text):
            return None
        path = self.path_for(text)
        try:
            with wave.open(str(path), "rb") as wav:
                return wav.readframes(wav.getnframes())
        except (OSError, wave.Error, EOFError):
            logger.warning("Unreadable recorded line: %s", path)
            return None

    def _usable(self, text: str) -> bool:
        """Is there a recording of the line with the expected format and length?

        A recording longer than the text can last means GPT-Live added something
        of its own (it happened: it made up a talk after a greeting). It is
        deleted so that "Prepare voices" records it again.
        """
        path = self.path_for(text)
        if not path.is_file():
            return False
        try:
            with wave.open(str(path), "rb") as wav:
                if (
                    wav.getnchannels() != 1
                    or wav.getsampwidth() != 2
                    or wav.getframerate() != self._settings.sample_rate
                ):
                    return False
                seconds = wav.getnframes() / wav.getframerate()
        except (OSError, wave.Error, EOFError):
            logger.warning("Unreadable recorded line: %s", path)
            return False
        if seconds > max_reading_seconds(text) + _TAIL_SLACK_S:
            logger.warning(
                "Recorded line too long (%.1f s) for %r: discarded, it will be recorded again",
                seconds,
                text[:60],
            )
            with contextlib.suppress(OSError):
                path.unlink()
            return False
        return True

    def count_ready(self, texts: Iterable[str]) -> int:
        return sum(1 for text in texts if self.has(text))

    def missing(self, texts: Iterable[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for text in texts:
            text = text.strip()
            if text and text not in seen and not self.has(text):
                seen.add(text)
                out.append(text)
        return out

    async def record(self, text: str) -> bytes:
        """Records a line with GPT-Live (opens a short session) and saves it."""
        pcm = await speak_text(self._settings, text, connect=self._connect)
        if len(pcm) / 2 / self._settings.sample_rate < _MIN_SECONDS:
            raise RuntimeError("GPT-Live returned no voice for the line")
        path = self.path_for(text)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with wave.open(str(tmp), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self._settings.sample_rate)
            wav.writeframes(pcm)
        tmp.replace(path)
        return pcm

    async def prepare(self, texts: Iterable[str]) -> int:
        """Records the missing lines, one at a time. Returns how many it recorded.

        Without a key it does nothing. A single failure does not stop the rest;
        two in a row (bad key, no network) do.
        """
        if not self._settings.api_key and self._connect is None:
            self.last_error = "LIVE_API_KEY is required to record the lines."
            return 0
        async with self._lock:
            pending = self.missing(texts)
            if not pending:
                return 0
            self.busy = True
            self.last_error = ""
            done = 0
            try:
                logger.info(
                    "Recording %d fixed lines with the voice %s", len(pending), self._settings.voice
                )
                failures = 0
                for text in pending:
                    try:
                        await self.record(text)
                        done += 1
                        failures = 0
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001 - carry on with the rest
                        self.last_error = str(exc)
                        failures += 1
                        logger.warning("Could not record the line %r: %s", text[:60], exc)
                        if failures >= _MAX_FAILURES:
                            # Bad key or no network: no point in retrying line by line.
                            logger.warning("Recording stopped after %d failures in a row", failures)
                            break
                logger.info("Fixed lines recorded: %d of %d", done, len(pending))
            finally:
                self.busy = False
            return done

    def clear_partial(self) -> None:
        """Deletes the temporary files of an interrupted recording."""
        for tmp in self._dir.glob("*/*.tmp"):
            with contextlib.suppress(OSError):
                tmp.unlink()
