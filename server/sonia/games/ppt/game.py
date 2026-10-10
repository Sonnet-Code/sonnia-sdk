"""Piedra, papel o tijera (``piedra_papel_tijera``): uno contra Sonia: la cámara lee la mano del jugador (plan, 5.4).

Esqueleto de los cimientos: lo completa su agente (A5) en este paquete
(``docs/juegos.md``, «Cómo se hace un juego»). Mientras ``unavailable_reason``
diga que no está listo y su línea de ``games/registry.py`` siga apagada, no se ofrece.
"""

from __future__ import annotations

from typing import ClassVar

from sonia.games.base import Game


class PptGame(Game):
    """Uno contra Sonia: la cámara lee la mano del jugador (plan, 5.4)."""

    id: ClassVar[str] = "piedra_papel_tijera"
    title: ClassVar[str] = "Piedra, papel o tijera"
    spoken: ClassVar[str] = "piedra, papel o tijera"
    needs: ClassVar[frozenset[str]] = frozenset({"camera", "preview", "poses", "hands"})
    settings_key: ClassVar[str] = "ppt"

    def unavailable_reason(self) -> str | None:
        return "Aún no está listo."
