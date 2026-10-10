"""Textos de Simón dice para GPT-Live, editables desde la nube (``sonia.prompts``).

Las instantáneas (``snapshots/prompts_poses.json``) se sacaron con el código de antes de
hacerlos editables: con los textos de la app, todo lo que va a GPT-Live (reglas, guiones,
reacciones a cada ronda, avisos y el final) tiene que salir idéntico. Sin cámara ni red: la
gente es la :class:`Crowd` de ``tests/games/test_poses.py``.
"""

from __future__ import annotations

from typing import Any

from sonia.games.poses import game as poses_game
from sonia.prompts import BOOK
from tests.games.fakes import FakeGameHost, game_settings
from tests.games.test_controles_camara import PanelCrowd, play_poses
from tests.games.test_poses import Crowd, crowd_game
from tests.prompt_snapshots import assert_snapshot, cloud_prompts


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


def test_las_piezas_de_la_app_validan_y_son_los_textos_del_juego() -> None:
    ids = [prompt_id for prompt_id in BOOK.ids() if prompt_id.startswith("juegos/poses/")]
    assert len(ids) == 16
    for prompt_id in ids:
        assert BOOK.validate(prompt_id, BOOK.default(prompt_id)) == [], prompt_id
        assert BOOK.spec(prompt_id).group == "Juego: Simón dice"
    assert BOOK.default("juegos/poses/reglas") == poses_game.RULES_TEXT
    assert BOOK.spec("juegos/poses/reglas").max_len == 1200
    # Los trozos que van pegados se guardan sin el espacio de delante (la nube lo quitaría).
    assert BOOK.default("juegos/poses/siguiente") == poses_game.NEXT_TEXT.strip()
    assert BOOK.default("juegos/poses/premios") == poses_game.WIN_CONTACT_TEXT.strip()


async def test_con_la_version_de_la_nube_se_usa_esa_y_no_la_de_la_app() -> None:
    cloud = {
        "juegos/poses/reglas": "REGLAS DE LA NUBE: {rounds} rondas.",
        "juegos/poses/presentacion": "Preséntalo en una frase: {rounds} rondas.",
        "juegos/poses/ronda_algunos": "{count} de {total}, ¡bien!",
        "juegos/poses/trampa_cayeron": "trampa: cayeron {count}.",
        "juegos/poses/siguiente": "Y a callar.",
        "juegos/poses/final": "FIN: {done} de {possible}{trap}.",
        "juegos/poses/premios": "Premios: {contact}.",
    }
    with cloud_prompts(cloud):
        data = await full_game(Crowd(players=5, doers=3, fallers=1))
    assert data["instructions"] == ["REGLAS DE LA NUBE: 6 rondas."]
    assert data["script"] == "Preséntalo en una frase: 6 rondas."
    rounds, final = data["spoken"][:-1], data["spoken"][-1]
    assert rounds[0].startswith("JUEGO: ronda 1 de 6, «")
    assert rounds[0].endswith("»: 3 de 5, ¡bien! Y a callar.")
    assert any(text.endswith(": trampa: cayeron 1. Y a callar.") for text in rounds)
    assert final == "FIN: 19 de 30 y en las trampas cayeron 1. Premios: Brian o Mariel."
    joined = " ".join([*data["instructions"], data["script"], *data["spoken"]])
    for app in ("SIMÓN DICE CON POSES EN MARCHA", "Explícalo con energía", "Reacciona en una"):
        assert app not in joined
    # Fuera del «with», otra vez los de la app.
    assert BOOK.source("juegos/poses/reglas") == "app"
