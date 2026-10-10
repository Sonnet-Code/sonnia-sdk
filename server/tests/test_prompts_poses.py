"""Textos de Simón dice para GPT-Live, editables desde la nube (``sonia.prompts``).

Las instantáneas (``snapshots/prompts_poses.json``) se sacaron con el código de antes de
hacerlos editables: con los textos de la app, todo lo que va a GPT-Live (reglas, guiones,
reacciones a cada ronda, avisos y el final) tiene que salir idéntico. Sin cámara ni red: la
gente es la :class:`Crowd` de ``tests/games/test_poses.py``.
"""

from __future__ import annotations

from typing import Any

from tests.games.fakes import FakeGameHost, game_settings
from tests.games.test_controles_camara import PanelCrowd, play_poses
from tests.games.test_poses import Crowd, crowd_game
from tests.prompt_snapshots import assert_snapshot


def live(host: FakeGameHost, **extra: Any) -> dict[str, Any]:
    """Todo lo que el juego le pasó a GPT-Live (y las órdenes grabadas, que no cambian)."""
    return {
        "instructions": list(host.instructions),
        "spoken": list(host.spoken),
        "fixed": [text for text, _ in host.fixed],
        **extra,
    }


async def full_game(crowd: Crowd, **kwargs: Any) -> dict[str, Any]:
    game, host, _ = crowd_game(crowd, **kwargs)
    script = await game.start("voice", {})
    nudge = game.nudge()
    await host.run_tasks()
    return live(host, script=script, nudge=nudge, after=game.nudge())


def no_contact_settings(**games: Any) -> Any:
    settings = game_settings(**games)
    trivia = settings.trivia.model_copy(update={"win_contact": ""})
    return settings.model_copy(update={"trivia": trivia})


async def poses_texts() -> dict[str, Any]:
    out: dict[str, Any] = {}
    # Arranque y reanudar.
    game, host, _ = crowd_game(Crowd())
    script = await game.start("voice", {})
    host.tasks[0].cancel()
    out["arranque"] = live(host, script=script, resume=await game.resume())
    # Partidas enteras: unos sí y otros no, todos, nadie la hace, trampas con y sin caídos.
    out["algunos"] = await full_game(Crowd(players=5, doers=3, fallers=1))
    out["todos"] = await full_game(Crowd(players=4, doers=4, fallers=0, far=3))
    out["ninguno"] = await full_game(Crowd(players=3, doers=0, fallers=2))
    settings = game_settings()
    no_tricks = settings.games.poses.model_copy(update={"tricks": 0, "rounds": 3})
    out["sin_trampas_ni_contacto"] = await full_game(
        Crowd(players=2, doers=1, fallers=0), settings=no_contact_settings(poses=no_tricks)
    )
    # Colocación: alguien muy cerca, nadie delante (y se acaba), la cámara que falla.
    out["muy_cerca"] = await full_game(Crowd(players=2, close=1))
    out["nadie"] = await full_game(Crowd(players=0))
    out["falla"] = await full_game(Crowd(fail=True))
    # El panel corrige una ronda ya contada.
    crowd = PanelCrowd("did", "result", {1}, players=5, doers=3, fallers=1)
    _, host = await play_poses(crowd)
    out["correccion"] = live(host, scripts=[p.result() for p in crowd.presses])
    return out


async def test_con_los_textos_de_la_app_nada_cambia() -> None:
    assert_snapshot("prompts_poses", await poses_texts())
