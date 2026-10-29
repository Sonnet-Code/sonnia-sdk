"""Idle animation: what Sonnia does on her own when there is no conversation.

Nobody comes up to an avatar that is silent and still. When she has been ``idle``
for a while, the orchestrator plays a "bit" every now and then: a short line
(a greeting, a fun fact, an invitation) sometimes with a fourth-wall gesture, a
dance with a "sung" line over it, or a **moment**: an invitation the realtime
model improvises from what is happening now (what the camera sees or something
people can try), which the engine prepares when it comes up
(``LiveEngine._request_moment``).

The lines live in ``assets/showcase/lines.md`` and the chants in
``assets/showcase/chants.md`` (one per line; ``#`` comments). They are fixed
texts: if the line is in the voice cache (``cache/voice``) it plays as is at no
cost; if not, the engine asks the realtime model to say it with its voice.

The avatar receives the lines like any other (``speech_start`` with
``ambient: true``) but **without changing state**: the choreographer stays idle or
dancing and only the mouth, brows and eyes move.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["Showcase", "ShowcaseBit", "load_lines"]

#: Attention gesture categories the avatar client understands.
ATTENTION_DANCE = "dance"
ATTENTION_FOURTH_WALL = "fourth_wall"
ATTENTION_SOFT = "soft"


def load_lines(path: Path) -> list[str]:
    """Reads a file of lines: one per line, without comments or empty lines."""
    if not path.is_file():
        return []
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


@dataclass(frozen=True)
class ShowcaseBit:
    """An idle bit: what to say and which gesture goes with it (or none).

    A moment (``moment``) has no text: the realtime model improvises it from what is
    happening now.
    """

    text: str
    attention: str | None = None
    moment: bool = False

    @property
    def is_dance(self) -> bool:
        return self.attention == ATTENTION_DANCE


@dataclass
class Showcase:
    """Picks the next bit without repeating the previous one.

    ``dance_chance`` is the probability that the bit is a sung dance; of the rest,
    ``moment_chance`` are moments and everything else fixed lines. Lines and moments
    come with a fourth-wall gesture with ``gesture_chance``.
    """

    phrases: list[str]
    songs: list[str]
    dance_chance: float = 0.3
    gesture_chance: float = 0.5
    moment_chance: float = 0.0
    rng: random.Random = field(default_factory=random.Random)
    _last_text: str | None = field(default=None, init=False)

    @classmethod
    def from_dir(
        cls,
        directory: Path,
        *,
        dance_chance: float = 0.3,
        gesture_chance: float = 0.5,
        moment_chance: float = 0.0,
    ) -> Showcase:
        phrases = load_lines(directory / "lines.md")
        songs = load_lines(directory / "chants.md")
        logger.info("Idle animation: %d lines and %d chants", len(phrases), len(songs))
        return cls(
            phrases,
            songs,
            dance_chance=dance_chance,
            gesture_chance=gesture_chance,
            moment_chance=moment_chance,
        )

    @property
    def enabled(self) -> bool:
        return bool(self.phrases or self.songs or self.moment_chance > 0)

    def next_bit(self) -> ShowcaseBit | None:
        """Returns the next bit, or ``None`` if there is no material."""
        if not self.enabled:
            return None
        talk = bool(self.phrases) or self.moment_chance > 0
        want_dance = self.songs and (not talk or self.rng.random() < self.dance_chance)
        if want_dance:
            text = self._pick(self.songs)
            return ShowcaseBit(text, ATTENTION_DANCE)
        gesture = ATTENTION_FOURTH_WALL if self.rng.random() < self.gesture_chance else None
        if self.moment_chance > 0 and (not self.phrases or self.rng.random() < self.moment_chance):
            return ShowcaseBit("", gesture, moment=True)
        return ShowcaseBit(self._pick(self.phrases), gesture)

    def _pick(self, pool: list[str]) -> str:
        candidates = [line for line in pool if line != self._last_text] or pool
        text = self.rng.choice(candidates)
        self._last_text = text
        return text
