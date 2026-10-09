"""Modo trivia: preguntas de opción múltiple en la pantalla de Unity, conducidas por GPT-Live."""

from __future__ import annotations

from sonia.trivia.bank import (
    DEFAULT_LEVEL,
    LEVELS,
    OPTION_LETTERS,
    TriviaBank,
    TriviaQuestion,
    count_headings,
    normalize_level,
    parse_questions,
)
from sonia.trivia.game import PASS, TriviaGame, TriviaHost, TriviaPhase, TriviaScreen

__all__ = [
    "DEFAULT_LEVEL",
    "LEVELS",
    "OPTION_LETTERS",
    "PASS",
    "TriviaBank",
    "TriviaGame",
    "TriviaHost",
    "TriviaPhase",
    "TriviaQuestion",
    "TriviaScreen",
    "count_headings",
    "normalize_level",
    "parse_questions",
]
