"""La ruleta de Sonnia (``ruleta``): una ruleta en pantalla elige uno de cinco retos (plan, 5.1).

Esqueleto de los cimientos: lo completa su agente (A2) en este paquete
(``docs/juegos.md``, «Cómo se hace un juego»). Mientras ``unavailable_reason``
diga que no está listo y su línea de ``games/registry.py`` siga apagada, no se ofrece.
"""

from __future__ import annotations

from typing import ClassVar

from sonia.games.base import Game


class RuletaGame(Game):
    """Una ruleta en pantalla elige uno de cinco retos (plan, 5.1)."""

    id: ClassVar[str] = "ruleta"
    title: ClassVar[str] = "La ruleta de Sonnia"
    spoken: ClassVar[str] = "la ruleta de Sonia"
    needs: ClassVar[frozenset[str]] = frozenset()
    settings_key: ClassVar[str] = "ruleta"

    def unavailable_reason(self) -> str | None:
        return "Aún no está listo."
