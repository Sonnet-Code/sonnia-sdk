"""Textos de piedra, papel o tijera para GPT-Live, editables desde la nube (``sonia.prompts``).

Las instantáneas (``snapshots/prompts_ppt.json``) se sacaron con el código de antes de
hacerlos editables: con los textos de la app, todo lo que va a GPT-Live (reglas, guiones,
cada resultado con su marcador, repeticiones, avisos y el final) tiene que salir idéntico.
Sin cámara ni red: las manos y las personas de ``tests/games/test_ppt.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from sonia.games.ppt import game as ppt_game
from sonia.games.ppt.game import PptGame
from sonia.vision.contracts import HandReading, HandShape
from tests.games.fakes import FakeGameHost, FakePoses, game_settings, pose_frame
from tests.games.test_ppt import by_throw, hand, loses, make_ppt, nothing, tie, wins
from tests.prompt_snapshots import assert_snapshot


@pytest.fixture(autouse=True)
def _sin_frase_grabada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin leer la caché de voces de verdad del equipo (como en ``test_ppt.py``)."""
    monkeypatch.setattr(ppt_game, "phrase_go_seconds", lambda settings: None)


def live(host: FakeGameHost, **extra: Any) -> dict[str, Any]:
    """Todo lo que el juego le pasó a GPT-Live (y la cuenta grabada, que no cambia)."""
    return {
        "instructions": list(host.instructions),
        "spoken": list(host.spoken),
        "fixed": [text for text, _ in host.fixed],
        **extra,
    }


async def match(plan: Callable[[PptGame], list[HandReading]], **kwargs: Any) -> dict[str, Any]:
    game, host, _ = make_ppt(plan, **kwargs)
    script = await game.start("voice", {})
    resume = await game.resume()
    await host.run_tasks()
    return live(host, script=script, resume=resume, after=await game.resume())


def rounds_settings(rounds: int) -> Any:
    return game_settings(ppt=game_settings().games.ppt.model_copy(update={"rounds": rounds}))


async def ppt_texts() -> dict[str, Any]:
    def blurry(game: PptGame) -> list[HandReading]:
        return [hand(HandShape.UNKNOWN)]

    return {
        "gana_el_jugador": await match(wins),
        "gana_sonia": await match(loses, seed=5),
        "empate_y_sigue": await match(by_throw(tie, wins, loses, wins)),
        "sin_mano": await match(by_throw(nothing, nothing, wins, wins)),
        "no_se_entiende": await match(by_throw(blurry, wins, wins)),
        "no_ve_la_mano": await match(nothing),
        "la_cuenta_no_suena": await match(wins, connected=False),
        "nadie_delante": await match(wins, poses=FakePoses([pose_frame()])),
        "final_empate": await match(tie, settings=rounds_settings(1)),
        "al_mejor_de_5": await match(by_throw(wins, loses), settings=rounds_settings(5)),
    }


async def test_con_los_textos_de_la_app_nada_cambia() -> None:
    assert_snapshot("prompts_ppt", await ppt_texts())
