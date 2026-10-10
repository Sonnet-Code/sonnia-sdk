"""La lista de los juegos del stand, una línea por juego (``docs/juegos.md``).

Cada agente solo cambia su línea: ``on=True`` cuando su juego está listo y
verificado. Apagado (``on=False``), el juego no se ofrece a GPT-Live ni sale en el
panel. Encendido, se ofrece si además lo dejan sus ajustes (``GAMES_ENABLED`` y
``GAME_<X>_ENABLED``); en el stand, el equipo lo apaga desde el panel (``games_off``)
sin reinstalar.

El orden es el del panel y el de la línea de juegos de las instrucciones de GPT-Live.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sonia.games.akinator.game import AkinatorGame
from sonia.games.base import Game
from sonia.games.busqueda.game import BusquedaGame
from sonia.games.poses.game import PosesGame
from sonia.games.ppt.game import PptGame
from sonia.games.ruleta.game import RuletaGame
from sonia.games.wordle.game import WordleGame

if TYPE_CHECKING:
    from sonia.config import Settings

__all__ = [
    "GAMES",
    "GameEntry",
    "all_games",
    "enabled_games",
    "find_game",
    "games_line",
    "games_line_for",
]


@dataclass(frozen=True, slots=True)
class GameEntry:
    """Un juego del registro y si está encendido (lo enciende su agente al terminarlo)."""

    game: type[Game]
    on: bool


GAMES: tuple[GameEntry, ...] = (
    # A2: la ruleta de Sonnia (docs/juegos/ruleta.md).
    GameEntry(RuletaGame, on=False),
    #
    # A3: Simón dice con poses (docs/juegos/poses.md).
    GameEntry(PosesGame, on=True),
    #
    # A4: Akinator dev (docs/juegos/akinator.md).
    GameEntry(AkinatorGame, on=False),
    #
    # A5: piedra, papel o tijera (docs/juegos/piedra_papel_tijera.md).
    GameEntry(PptGame, on=False),
    #
    # A6: Wordle de tecnología (docs/juegos/wordle.md).
    GameEntry(WordleGame, on=False),
    #
    # A7: búsqueda relámpago (docs/juegos/busqueda.md).
    GameEntry(BusquedaGame, on=False),
)


def all_games() -> list[type[Game]]:
    """Todos los juegos, encendidos o no."""
    return [entry.game for entry in GAMES]


def enabled_games(settings: Settings) -> list[type[Game]]:
    """Los juegos encendidos aquí y en sus ajustes (``GAMES_ENABLED``, ``GAME_<X>_ENABLED``)."""
    if not settings.games.enabled:
        return []
    out: list[type[Game]] = []
    for entry in GAMES:
        block = getattr(settings.games, entry.game.settings_key, None)
        if entry.on and getattr(block, "enabled", False):
            out.append(entry.game)
    return out


def find_game(game_id: str) -> type[Game] | None:
    """La clase de un juego por su id, encendido o no."""
    return next((entry.game for entry in GAMES if entry.game.id == game_id), None)


def games_line(games: Sequence[type[Game]]) -> str:
    """La línea de juegos de las instrucciones de GPT-Live (la única: las reglas llegan al empezar)."""
    return games_line_for([g.spoken for g in games])


def games_line_for(names: Sequence[str]) -> str:
    """:func:`games_line` con los nombres ya puestos (los de ``Game.spoken``)."""
    names = [n for n in names if n]
    if not names:
        return ""
    listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + f" y {names[-1]}"
    return (
        f"- Juegos en tu pantalla: {listed}. Delega empezarlos y terminarlos; las reglas te "
        "llegan al empezar."
    )
