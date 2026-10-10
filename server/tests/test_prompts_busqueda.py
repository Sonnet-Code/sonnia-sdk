"""Búsqueda relámpago: los textos que se mandan a GPT-Live, idénticos a los de antes con los de la app.

La instantánea (``snapshots/prompts_busqueda.json``) se sacó con el código de antes de hacer
editables los prompts (``sonia.prompts``). Sin red ni APIs: el juego suelto con
``FakeGameHost`` y un juez guionizado (nunca el modelo de verdad).
"""

from __future__ import annotations

from typing import Any

from sonia.games.busqueda.game import BusquedaGame
from tests.games.fakes import FakeGameHost, FakeVision, game_settings, make_game
from tests.games.test_busqueda import (
    MISS,
    SEEN,
    RoundJudge,
    game_where,
    go,
    new_game,
    next_round,
    play_game,
    pump,
)
from tests.prompt_snapshots import assert_snapshot


def live_texts(host: FakeGameHost) -> dict[str, list[str]]:
    return {"instructions": list(host.instructions), "spoken": list(host.spoken)}


async def after_voice(game: BusquedaGame, host: FakeGameHost) -> None:
    """Tras una ronda cerrada por una jugada (no por el reloj): Sonia tarda en contarlo, habla
    y calla, y sale el anuncio de la siguiente (como en ``test_busqueda.py``)."""
    await pump(game, host, 5.0)
    host.quiet = 0.0
    await pump(game, host, 2.0)
    host.quiet = 3.0
    await pump(game, host, 0.2)
    assert game.snapshot()["phase"] == "ready"


async def collect() -> dict[str, Any]:
    """Todo lo que lee GPT-Live en casos representativos, con su nombre."""
    out: dict[str, Any] = {}

    # Arranque, empujones, busqueda_check en cada caso y las dos rondas llevadas desde el panel.
    game, host, _ = new_game(MISS, None, SEEN)
    out["arranque.guion"] = await game.start("voice", {})
    out["arranque.reanudar"] = await game.resume()
    out["arranque.empujon"] = game.nudge()
    out["arranque.check_antes_de_la_salida"] = await game.check({})
    await go(game, host)
    out["ronda.empujon"] = game.nudge()
    out["ronda.check_no_se_ve"] = await game.check({})
    out["ronda.check_sin_respuesta"] = await game.check({})
    out["ronda.check_lo_ve"] = await game.check({})
    out["ronda.check_ya_contada"] = await game.check({})
    await after_voice(game, host)
    out["ronda2.reanudar"] = await game.resume()
    await go(game, host)
    out["ronda2.panel_saltar"] = await game.panel_control("skip", "")
    await after_voice(game, host)
    await go(game, host)
    out["ronda3.panel_encontrado"] = await game.panel_control("found", "")
    out["ronda3.empujon_final"] = game.nudge()
    out["partida.textos"] = live_texts(host)

    # Sin miradas: el tope de la ronda.
    game, host, _ = new_game(MISS, max_checks=1)
    await game.start("voice", {})
    await go(game, host)
    out["tope.check_no_se_ve"] = await game.check({})
    out["tope.check_sin_miradas"] = await game.check({})

    # La cámara no contesta: ronda muda y, a la segunda, se cancela.
    game, host, _ = new_game(*[None] * 60)
    await game.start("voice", {})
    await go(game, host)
    await pump(game, host, 26.0)
    await next_round(game, host)
    await go(game, host)
    await pump(game, host, 26.0)
    out["muda.textos"] = live_texts(host)

    # Finales: gana con contacto, pierde, pleno y ninguna.
    for name, outcomes in (
        ("gana", [True, False, True]),
        ("pierde", [True, False, False]),
        ("pleno", [True, True, True]),
        ("ninguna", [False, False, False]),
    ):
        game, host, _ = game_where(*outcomes)
        await game.start("voice", {})
        await play_game(game, host, outcomes)
        out[f"final.{name}"] = live_texts(host)

    # Pleno sin contacto del equipo, con otras rondas y otros segundos.
    settings = game_settings()
    settings = settings.model_copy(
        update={
            "trivia": settings.trivia.model_copy(update={"win_contact": ""}),
            "games": settings.games.model_copy(
                update={
                    "busqueda": settings.games.busqueda.model_copy(
                        update={"rounds": 2, "round_seconds": 20.0}
                    )
                }
            ),
        }
    )
    game, host = make_game(
        BusquedaGame, settings=settings, vision=FakeVision(judge=RoundJudge([1, 2]))
    )
    out["sin_contacto.guion"] = await game.start("voice", {})
    await play_game(game, host, [True, True])
    out["sin_contacto.textos"] = live_texts(host)
    return out


async def test_los_textos_de_la_busqueda_no_cambian() -> None:
    assert_snapshot("prompts_busqueda", await collect())
