"""Los juegos del stand (``docs/juegos.md``, ``docs/plan-juegos.md``).

- :mod:`sonia.games.base`: el contrato de un juego (:class:`Game`) y lo que puede usar
  (:class:`GameHost`).
- :mod:`sonia.games.banks`: los bancos editables desde el backoffice (:class:`GameBank`).
- :mod:`sonia.games.manager`: :class:`GameManager`, uno a la vez sobre el motor.
- :mod:`sonia.games.host`: el ``GameHost`` de cada juego sobre el manager y el motor.
- :mod:`sonia.games.registry`: la lista de los juegos, una línea por juego.
- :mod:`sonia.games.demo`: los pasos de las secuencias del orquestador falso
  (``scripts/juegos_demo.py``).
- Un paquete por juego: ``ruleta``, ``poses``, ``akinator``, ``ppt``, ``wordle`` y
  ``busqueda``.

Las acciones comunes (``start_game``, ``stop_game``) y el mecanismo de las jugadas
(:func:`sonia.actions.games.game_action`) viven en :mod:`sonia.actions.games`.
"""

from __future__ import annotations

from sonia.games.banks import BANK_MAX_CHARS, BankParse, GameBank
from sonia.games.base import (
    INSTRUCT_MAX_CHARS,
    NEEDS,
    NOT_SAID,
    NOT_SAID_VALUES,
    SCRIPT_PREFIX,
    Game,
    GameError,
    GameHost,
    GameResult,
    StopReason,
)
from sonia.games.manager import normalize_games_judge, normalize_games_off, normalize_pose_model

__all__ = [
    "BANK_MAX_CHARS",
    "INSTRUCT_MAX_CHARS",
    "NEEDS",
    "NOT_SAID",
    "NOT_SAID_VALUES",
    "SCRIPT_PREFIX",
    "BankParse",
    "Game",
    "GameBank",
    "GameError",
    "GameHost",
    "GameResult",
    "StopReason",
    "normalize_games_judge",
    "normalize_games_off",
    "normalize_pose_model",
]
