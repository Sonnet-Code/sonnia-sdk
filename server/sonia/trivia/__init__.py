"""Modo trivia: preguntas de opción múltiple en la pantalla de Unity, conducidas por GPT-Live."""

from __future__ import annotations

from sonia.trivia.bank import OPTION_LETTERS, TriviaBank, TriviaQuestion, parse_questions
from sonia.trivia.game import PASS, TriviaGame, TriviaHost, TriviaPhase, TriviaScreen

__all__ = [
    "OPTION_LETTERS",
    "PASS",
    "TriviaBank",
    "TriviaGame",
    "TriviaHost",
    "TriviaPhase",
    "TriviaQuestion",
    "TriviaScreen",
    "parse_questions",
]
