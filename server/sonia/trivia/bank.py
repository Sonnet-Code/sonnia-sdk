"""Banco de preguntas de la trivia (``assets/trivia/preguntas.md``).

Cada pregunta es una línea ``## `` seguida de tres opciones en lista, con
``- [x]`` en la correcta y ``- [ ]`` en las otras, y opcionalmente una línea
``> `` con un dato corto para cuando se revela la respuesta. El nivel va al
principio de la pregunta entre corchetes (``## [difícil] ¿…?``: fácil,
intermedio o difícil); sin él, intermedio. Una pregunta mal
formada se salta con un aviso: un error al editar el archivo durante el evento
no puede dejar a Sonia sin trivia.
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

#: Letras de las opciones, en el orden en que salen en pantalla.
OPTION_LETTERS = ("A", "B", "C")

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_OPTION = re.compile(r"^[-*]\s*\[( |x|X)\]\s*(.+)$")
_LEVEL = re.compile(r"^\[([^\]]+)\]\s*(.+)$")

#: Niveles de la trivia, de menos a más difícil.
LEVELS = ("fácil", "intermedio", "difícil")
DEFAULT_LEVEL = "intermedio"

_LEVEL_ALIASES = {
    "facil": "fácil",
    "basico": "fácil",
    "intermedio": "intermedio",
    "medio": "intermedio",
    "normal": "intermedio",
    "dificil": "difícil",
    "avanzado": "difícil",
}


def normalize_level(value: str | None) -> str | None:
    """«Fácil», «facil», «básico»… → ``fácil``; ``None`` si no es un nivel."""
    if not value:
        return None
    plain = value.strip().lower().translate(str.maketrans("áéíóú", "aeiou"))
    return _LEVEL_ALIASES.get(plain)


@dataclass(frozen=True, slots=True)
class TriviaQuestion:
    """Una pregunta con sus tres opciones y el índice de la correcta."""

    text: str
    options: tuple[str, str, str]
    correct: int
    fact: str = ""
    level: str = DEFAULT_LEVEL

    def shuffled(self, rng: random.Random) -> TriviaQuestion:
        """La misma pregunta con las opciones en otro orden."""
        order = [0, 1, 2]
        rng.shuffle(order)
        options = (self.options[order[0]], self.options[order[1]], self.options[order[2]])
        return TriviaQuestion(self.text, options, order.index(self.correct), self.fact, self.level)


class TriviaBank:
    """Las preguntas válidas de un archivo."""

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
            logger.warning("No se pudo leer el banco de la trivia %s: %s", path, exc)
            return cls([])
        return cls(parse_questions(text, source=path.name))

    @classmethod
    def from_text(cls, text: str, *, source: str) -> TriviaBank:
        """Las preguntas válidas de un texto con el formato del archivo (el banco de la nube)."""
        return cls(parse_questions(text, source=source))

    def levels(self) -> dict[str, int]:
        """Cuántas preguntas hay de cada nivel."""
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
        """``count`` preguntas distintas al azar, con las opciones barajadas.

        Con ``level``, primero las de ese nivel y, si no llegan, las de los niveles
        más cercanos. Con ``recent`` (pregunta -> partida en que salió por última
        vez), dentro de cada nivel primero las que nunca han salido y después las
        que hace más que salieron: no se repite ninguna hasta agotar las del nivel.
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
    """Cuántas preguntas (líneas ``## ``) tiene un texto, válidas o no."""
    lines = _COMMENT.sub("", text).splitlines()
    return sum(1 for line in lines if line.strip().startswith("## "))


def parse_questions(text: str, *, source: str = "preguntas.md") -> list[TriviaQuestion]:
    """Lee las preguntas del formato del banco. Las mal formadas se saltan."""
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
                "Pregunta de la trivia saltada en %s (necesita 3 opciones y 1 correcta): %s",
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
