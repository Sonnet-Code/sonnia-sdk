"""Gestos al hablar: un modelo de texto elige el gesto de cada frase (``docs/gestos.md``)."""

from __future__ import annotations

from sonia.gestures.catalog import FILLER_LIST, Gesture, GestureCatalog
from sonia.gestures.director import GestureDirector
from sonia.gestures.prompt import build_system_prompt, build_user_message, parse_choice

__all__ = [
    "FILLER_LIST",
    "Gesture",
    "GestureCatalog",
    "GestureDirector",
    "build_system_prompt",
    "build_user_message",
    "parse_choice",
]
