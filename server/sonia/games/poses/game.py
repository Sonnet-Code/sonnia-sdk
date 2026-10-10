"""Simón dice con poses (``poses``): órdenes con nombre de meme dev; la cámara cuenta quién hace la pose (plan, 5.2).

Esqueleto de los cimientos: lo completa su agente (A3) en este paquete
(``docs/juegos.md``, «Cómo se hace un juego»). Mientras ``unavailable_reason``
diga que no está listo y su línea de ``games/registry.py`` siga apagada, no se ofrece.
"""

from __future__ import annotations

from typing import ClassVar

from sonia.games.base import Game


class PosesGame(Game):
    """Órdenes con nombre de meme dev; la cámara cuenta quién hace la pose (plan, 5.2)."""

    id: ClassVar[str] = "poses"
    title: ClassVar[str] = "Simón dice con poses"
    spoken: ClassVar[str] = "Simón dice con poses"
    needs: ClassVar[frozenset[str]] = frozenset({"camera", "preview", "poses"})
    settings_key: ClassVar[str] = "poses"

    def unavailable_reason(self) -> str | None:
        return "Aún no está listo."
