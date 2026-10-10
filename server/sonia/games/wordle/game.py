"""Wordle de tecnología (``wordle``): adivinar una palabra tech de 5 letras en 6 intentos, gritando palabras (plan, 5.5).

Esqueleto de los cimientos: lo completa su agente (A6) en este paquete
(``docs/juegos.md``, «Cómo se hace un juego»). Mientras ``unavailable_reason``
diga que no está listo y su línea de ``games/registry.py`` siga apagada, no se ofrece.
"""

from __future__ import annotations

from typing import ClassVar

from sonia.games.base import Game


class WordleGame(Game):
    """Adivinar una palabra tech de 5 letras en 6 intentos, gritando palabras (plan, 5.5)."""

    id: ClassVar[str] = "wordle"
    title: ClassVar[str] = "Wordle de tecnología"
    spoken: ClassVar[str] = "el Wordle de tecnología"
    needs: ClassVar[frozenset[str]] = frozenset()
    settings_key: ClassVar[str] = "wordle"

    def unavailable_reason(self) -> str | None:
        return "Aún no está listo."
