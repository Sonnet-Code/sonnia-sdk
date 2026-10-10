"""Akinator dev (``akinator``): el visitante piensa en algo tech y Sonia lo adivina con preguntas de sí o no (plan, 5.3).

Esqueleto de los cimientos: lo completa su agente (A4) en este paquete
(``docs/juegos.md``, «Cómo se hace un juego»). Mientras ``unavailable_reason``
diga que no está listo y su línea de ``games/registry.py`` siga apagada, no se ofrece.
"""

from __future__ import annotations

from typing import ClassVar

from sonia.games.base import Game


class AkinatorGame(Game):
    """El visitante piensa en algo tech y Sonia lo adivina con preguntas de sí o no (plan, 5.3)."""

    id: ClassVar[str] = "akinator"
    title: ClassVar[str] = "Akinator dev"
    spoken: ClassVar[str] = "el Akinator dev"
    needs: ClassVar[frozenset[str]] = frozenset()
    settings_key: ClassVar[str] = "akinator"

    def unavailable_reason(self) -> str | None:
        return "Aún no está listo."
