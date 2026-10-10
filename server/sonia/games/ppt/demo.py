"""La secuencia de piedra, papel o tijera para el orquestador falso (``scripts/juegos_demo.py``).

Pasa por cada estado de la pantalla con una captura en cada uno: empezar (con la vista
en vivo y el jugador resaltado), la cuenta (Sonnia agitando el puño), el «¡ya!» (su mano
fuera), una ronda ganada por el visitante, una ganada por Sonnia, una sin mano que se
repite y el final. La vista en vivo es sintética, con las marcas que pinta el juego
(:mod:`sonia.games.ppt.overlay`): nunca la cámara de nadie.

    uv run --no-sync python ../scripts/juegos_demo.py --juego piedra_papel_tijera --puerto 8795
"""

from __future__ import annotations

from typing import Any

import numpy as np

from sonia.games.demo import Capture, GameMsg, Preview, Step, Wait
from sonia.games.ppt.overlay import OverlayState, draw_state

__all__ = ["steps"]

ROUNDS = 3
TARGET = 2
#: Del principio de la frase grabada al «¡ya!» en la demo (una grabación típica).
GO_S = 1.8

#: Lo que pinta el juego en la vista en vivo: el jugador y, en la lectura, su mano.
WITH_HAND = OverlayState(
    player=(0.33, 0.12, 0.34, 0.86), hand=(0.44, 0.42, 0.1, 0.17), hand_ok=True
)


def _draw(image: np.ndarray, mirrored: bool) -> None:
    draw_state(image, WITH_HAND, mirrored)


def _score(sonnia: int, player: int) -> dict[str, int]:
    return {"sonnia": sonnia, "player": player}


def _base(number: int, sonnia: int, player: int) -> dict[str, Any]:
    return {"round": number, "rounds": ROUNDS, "target": TARGET, "score": _score(sonnia, player)}


def _throw(number: int, move: str, sonnia: int, player: int, *, retry: bool = False) -> list[Step]:
    """Una tirada hasta el «¡ya!»: ``round``, ``ready``, ``countdown`` y ``go``."""
    return [
        GameMsg("round", {**_base(number, sonnia, player), "retry": retry}),
        GameMsg("ready", {"round": number}),
        Wait(0.8),
        GameMsg("countdown", {"round": number, "sonnia": move, "go_s": GO_S, "beats": 3}),
    ]


def _result(
    number: int,
    move: str,
    shown: str | None,
    winner: str,
    sonnia: int,
    player: int,
    *,
    reason: str = "",
    retry: bool = False,
) -> GameMsg:
    return GameMsg(
        "result",
        {
            **_base(number, sonnia, player),
            "sonnia": move,
            "player": shown,
            "winner": winner,
            "reason": reason,
            "retry": retry,
        },
    )


def steps() -> list[Step]:
    return [
        GameMsg("start", {"title": "Piedra, papel o tijera", **_base(1, 0, 0)}),
        Preview(75.0, draw=_draw, off=True),
        Capture("ppt-1-empezar", settle_s=2.0),
        # Ronda 1: el puño arriba, la cuenta (varias capturas seguidas), el «¡ya!» con la
        # tijera y gana el visitante.
        GameMsg("round", {**_base(1, 0, 0), "retry": False}),
        GameMsg("ready", {"round": 1}),
        Capture("ppt-2a-puno-arriba", settle_s=0.6),
        GameMsg("countdown", {"round": 1, "sonnia": "tijera", "go_s": GO_S, "beats": 3}),
        Capture("ppt-2b-cuenta", settle_s=0.45),
        Capture("ppt-2c-cuenta", settle_s=0.1),
        Capture("ppt-2d-cuenta", settle_s=0.1),
        GameMsg("go", {"round": 1, "sonnia": "tijera"}),
        Capture("ppt-3a-ya-tijera", settle_s=0.4),
        Capture("ppt-3b-tijera", settle_s=0.1),
        _result(1, "tijera", "piedra", "player", 0, 1),
        Capture("ppt-4-acierto", settle_s=1.2),
        Wait(1.5),
        # Ronda 2: el papel de Sonnia y gana ella.
        *_throw(2, "papel", 0, 1),
        Wait(GO_S + 0.15),
        GameMsg("go", {"round": 2, "sonnia": "papel"}),
        Capture("ppt-5a-ya-papel", settle_s=0.4),
        Wait(0.5),
        _result(2, "papel", "piedra", "sonnia", 1, 1),
        Capture("ppt-5-fallo", settle_s=1.2),
        Wait(1.5),
        # Ronda 3: la piedra de Sonnia; no se ve la mano del visitante y se repite.
        *_throw(3, "piedra", 1, 1),
        Wait(GO_S + 0.15),
        GameMsg("go", {"round": 3, "sonnia": "piedra"}),
        Capture("ppt-6a-ya-piedra", settle_s=0.4),
        Wait(0.5),
        _result(3, "piedra", None, "none", 1, 1, reason="no_hand", retry=True),
        Capture("ppt-6-sin-mano", settle_s=1.2),
        Wait(1.5),
        # La repetición: gana el visitante y con eso la partida.
        *_throw(3, "piedra", 1, 1, retry=True),
        Wait(GO_S + 0.15),
        GameMsg("go", {"round": 3, "sonnia": "piedra"}),
        Wait(1.0),
        _result(3, "piedra", "papel", "player", 1, 2),
        GameMsg(
            "final",
            {
                "winner": "player",
                "score": _score(1, 2),
                "rounds": ROUNDS,
                "target": TARGET,
                "sonnia": "piedra",
                "player": "papel",
                "contact": "Brian o Mariel",
            },
        ),
        Capture("ppt-7-final", settle_s=3.0),
        GameMsg("end", {"result": "win", "winner": "player", "score": _score(1, 2)}),
        Wait(1.5),
    ]
