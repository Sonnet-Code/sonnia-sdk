"""Trivia question bank (``assets/trivia/questions.md``).

Each question is a ``## `` line followed by three options as a list, with
``- [x]`` on the correct one and ``- [ ]`` on the others, and optionally a ``> ``
line with a short fact for when the answer is revealed. The level goes at the
start of the question in brackets (``## [hard] ...?``: easy, medium or hard);
without it, medium. A malformed question is skipped with a warning: a typo while
editing the file cannot leave Sonnia without trivia.
"""

from __future__ import annotations

import logging
import random
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_LEVEL",
    "LEVELS",
    "OPTION_LETTERS",
    "TriviaBank",
    "TriviaQuestion",
    "count_headings",
    "normalize_level",
]

#: Option letters, in the order they appear on screen.
OPTION_LETTERS = ("A", "B", "C")

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_OPTION = re.compile(r"^[-*]\s*\[( |x|X)\]\s*(.+)$")
_LEVEL = re.compile(r"^\[([^\]]+)\]\s*(.+)$")

#: Trivia levels, from easiest to hardest.
LEVELS = ("easy", "medium", "hard")
DEFAULT_LEVEL = "medium"

_LEVEL_ALIASES = {
    "easy": "easy",
    "basic": "easy",
    "beginner": "easy",
    "medium": "medium",
    "intermediate": "medium",
    "normal": "medium",
    "hard": "hard",
    "difficult": "hard",
    "advanced": "hard",
    "expert": "hard",
}


def normalize_level(value: str | None) -> str | None:
    """Maps "Easy", "basic", "Beginner"... to ``easy``; ``None`` if it is not a level."""
    if not value:
        return None
    return _LEVEL_ALIASES.get(value.strip().lower())


@dataclass(frozen=True, slots=True)
class TriviaQuestion:
    """A question with its three options and the index of the correct one."""

    text: str
    options: tuple[str, str, str]
    correct: int
    fact: str = ""
    level: str = DEFAULT_LEVEL

    def shuffled(self, rng: random.Random) -> TriviaQuestion:
        """The same question with the options in another order."""
        order = [0, 1, 2]
        rng.shuffle(order)
        options = (self.options[order[0]], self.options[order[1]], self.options[order[2]])
        return TriviaQuestion(self.text, options, order.index(self.correct), self.fact, self.level)


class TriviaBank:
    """The valid questions of a file."""

    def __init__(self, questions: list[TriviaQuestion]) -> None:
        self.questions = questions

    def __len__(self) -> int:
        return len(self.questions)

    @classmethod
    def from_file(cls, path: Path) -> TriviaBank:
        if not path.is_file():
            return cls([])
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not read the trivia bank %s: %s", path, exc)
            return cls([])
        return cls(parse_questions(text, source=path.name))

    @classmethod
    def from_text(cls, text: str, *, source: str) -> TriviaBank:
        """The valid questions of a text in the file format."""
        return cls(parse_questions(text, source=source))

    def levels(self) -> dict[str, int]:
        """How many questions there are of each level."""
        counts = dict.fromkeys(LEVELS, 0)
        for question in self.questions:
            counts[question.level] = counts.get(question.level, 0) + 1
        return counts

    def draw(
        self,
        count: int,
        rng: random.Random,
        level: str | None = None,
        *,
        recent: Mapping[str, int] | None = None,
    ) -> list[TriviaQuestion]:
        """``count`` different random questions, with their options shuffled.

        With ``level``, first the ones of that level and, if there are not enough,
        those of the closest levels. With ``recent`` (question -> game in which it
        last came up), within each level first the ones that never came up and then
        the ones that came up longest ago: none repeats until the level runs out.
        """
        pool = list(self.questions)
        rng.shuffle(pool)
        target = LEVELS.index(level) if level in LEVELS else None
        seen = recent or {}

        def order(question: TriviaQuestion) -> tuple[int, int]:
            distance = 0 if target is None else abs(LEVELS.index(question.level) - target)
            return distance, seen.get(question.text, -1)

        pool.sort(key=order)
        return [q.shuffled(rng) for q in pool[: min(count, len(pool))]]


def count_headings(text: str) -> int:
    """How many questions (``## `` lines) a text has, valid or not."""
    lines = _COMMENT.sub("", text).splitlines()
    return sum(1 for line in lines if line.strip().startswith("## "))


def parse_questions(text: str, *, source: str = "questions.md") -> list[TriviaQuestion]:
    """Reads the questions in the bank format. Malformed ones are skipped."""
    questions: list[TriviaQuestion] = []
    current: str | None = None
    options: list[tuple[str, bool]] = []
    fact: list[str] = []

    def close() -> None:
        if current is None:
            return
        correct = [i for i, (_, ok) in enumerate(options) if ok]
        if len(options) != 3 or len(correct) != 1:
            logger.warning(
                "Trivia question skipped in %s (it needs 3 options and 1 correct one): %s",
                source,
                current,
            )
            return
        texts = (options[0][0], options[1][0], options[2][0])
        text, level = current, DEFAULT_LEVEL
        tagged = _LEVEL.match(current)
        if tagged is not None and normalize_level(tagged.group(1)) is not None:
            text, level = tagged.group(2).strip(), normalize_level(tagged.group(1)) or DEFAULT_LEVEL
        questions.append(TriviaQuestion(text, texts, correct[0], " ".join(fact), level))

    for raw in _COMMENT.sub("", text).splitlines():
        line = raw.strip()
        if line.startswith("## "):
            close()
            current, options, fact = line[3:].strip(), [], []
            continue
        if current is None:
            continue
        option = _OPTION.match(line)
        if option is not None:
            options.append((option.group(2).strip(), option.group(1) != " "))
        elif line.startswith(">"):
            fact.append(line.lstrip("> ").strip())
    close()
    return questions
