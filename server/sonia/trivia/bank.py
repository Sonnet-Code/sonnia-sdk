"""Banco de preguntas de la trivia (``assets/trivia/preguntas.md``).

Cada pregunta es una línea ``## `` seguida de tres opciones en lista, con
``- [x]`` en la correcta y ``- [ ]`` en las otras, y opcionalmente una línea
``> `` con un dato corto para cuando se revela la respuesta. Una pregunta mal
formada se salta con un aviso: un error al editar el archivo durante el evento
no puede dejar a Sonia sin trivia.
"""

from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["OPTION_LETTERS", "TriviaBank", "TriviaQuestion"]

#: Letras de las opciones, en el orden en que salen en pantalla.
OPTION_LETTERS = ("A", "B", "C")

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_OPTION = re.compile(r"^[-*]\s*\[( |x|X)\]\s*(.+)$")


@dataclass(frozen=True, slots=True)
class TriviaQuestion:
    """Una pregunta con sus tres opciones y el índice de la correcta."""

    text: str
    options: tuple[str, str, str]
    correct: int
    fact: str = ""

    def shuffled(self, rng: random.Random) -> TriviaQuestion:
        """La misma pregunta con las opciones en otro orden."""
        order = [0, 1, 2]
        rng.shuffle(order)
        options = (self.options[order[0]], self.options[order[1]], self.options[order[2]])
        return TriviaQuestion(self.text, options, order.index(self.correct), self.fact)


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

    def draw(self, count: int, rng: random.Random) -> list[TriviaQuestion]:
        """``count`` preguntas distintas al azar, con las opciones barajadas."""
        picked = rng.sample(self.questions, min(count, len(self.questions)))
        return [q.shuffled(rng) for q in picked]


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
        questions.append(TriviaQuestion(current, texts, correct[0], " ".join(fact)))

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
