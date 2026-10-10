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
from sonia.games.ppt.game import PROMPT, PptGame
from sonia.prompts import BOOK
from sonia.vision.contracts import HandReading, HandShape
from tests.games.fakes import FakeGameHost, FakePoses, game_settings, pose_frame
from tests.games.test_ppt import by_throw, hand, loses, make_ppt, nothing, tie, wins
from tests.prompt_snapshots import assert_snapshot, cloud_prompts


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


def test_las_piezas_de_la_app_validan_y_son_los_textos_del_juego() -> None:
    ids = [prompt_id for prompt_id in BOOK.ids() if prompt_id.startswith(PROMPT)]
    assert len(ids) == 17
    for prompt_id in ids:
        assert BOOK.validate(prompt_id, BOOK.default(prompt_id)) == [], prompt_id
        assert BOOK.spec(prompt_id).group == "Juego: Piedra, papel o tijera"
    assert BOOK.default(PROMPT + "reglas") == ppt_game.RULES
    assert BOOK.spec(PROMPT + "reglas").max_len == 1200
    # Los trozos que van pegados se guardan sin el espacio de delante (la nube lo quitaría).
    assert BOOK.default(PROMPT + "marcador") == ppt_game.GOES_ON.strip()
    assert BOOK.default(PROMPT + "final_gana_jugador") == ppt_game.FINAL_PLAYER.strip()
    # Sin decir quién ganó la ronda, no vale.
    assert BOOK.validate(PROMPT + "ronda_ganada", "Ronda {round}: {sonnia} y {player}.")


async def test_con_la_version_de_la_nube_se_usa_esa_y_no_la_de_la_app() -> None:
    cloud = {
        PROMPT + "reglas": "REGLAS DE LA NUBE: al mejor de {rounds}, gana quien llegue a {target}.",
        PROMPT + "presentacion": "¡A jugar al mejor de {rounds}!",
        PROMPT + "ronda_ganada": "Ronda {round}: {who}.",
        PROMPT + "marcador": "Van {sonnia} a {player}.",
        PROMPT + "final_gana_jugador": "¡Ganó {player} a {sonnia}! Que vea a {contact}.",
    }
    with cloud_prompts(cloud):
        data = await match(wins)
    assert data["instructions"] == ["REGLAS DE LA NUBE: al mejor de 3, gana quien llegue a 2."]
    assert data["script"] == "¡A jugar al mejor de 3!"
    assert data["spoken"] == [
        "Ronda 1: gana el jugador. Van 0 a 1.",
        "Ronda 2: gana el jugador. ¡Ganó 2 a 0! Que vea a Brian o Mariel.",
    ]
    joined = " ".join([*data["instructions"], data["script"], *data["spoken"]])
    for app in ("JUEGO EN MARCHA", "Di en una o dos frases", "RESULTADO de la ronda", "Marcador:"):
        assert app not in joined
    assert BOOK.source(PROMPT + "reglas") == "app"
