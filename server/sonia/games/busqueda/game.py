"""Búsqueda relámpago (``busqueda``): «¡El primero que me enseñe algo azul!»: la cámara comprueba quién lo trae (plan, 5.6).

Esqueleto de los cimientos: lo completa su agente (A7) en este paquete
(``docs/juegos.md``, «Cómo se hace un juego»). Mientras ``unavailable_reason``
diga que no está listo y su línea de ``games/registry.py`` siga apagada, no se ofrece.
"""

from __future__ import annotations

from typing import ClassVar

from sonia.games.base import Game


class BusquedaGame(Game):
    """«¡El primero que me enseñe algo azul!»: la cámara comprueba quién lo trae (plan, 5.6)."""

    id: ClassVar[str] = "busqueda"
    title: ClassVar[str] = "Búsqueda relámpago"
    spoken: ClassVar[str] = "la búsqueda relámpago"
    needs: ClassVar[frozenset[str]] = frozenset({"camera", "preview", "vision_llm"})
    settings_key: ClassVar[str] = "busqueda"

    def unavailable_reason(self) -> str | None:
        return "Aún no está listo."
