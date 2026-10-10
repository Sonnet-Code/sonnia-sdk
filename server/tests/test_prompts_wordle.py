"""Wordle de tecnología: los textos que se mandan a GPT-Live, idénticos a los de antes con los de la app.

La instantánea (``snapshots/prompts_wordle.json``) se sacó con el código de antes de hacer
editables los prompts (``sonia.prompts``). Sin red ni APIs: el juego suelto con
``FakeGameHost``.
"""

from __future__ import annotations

from typing import Any

from sonia.config import Settings
from sonia.games import NOT_SAID
from sonia.games.wordle import WordleGame
from tests.games.fakes import FakeGameHost, game_settings
from tests.games.test_wordle import SECRET, make_wordle, play, wordle_settings
from tests.prompt_snapshots import assert_snapshot


def without_contact() -> Settings:
    settings = game_settings()
    return settings.model_copy(
        update={"trivia": settings.trivia.model_copy(update={"win_contact": ""})}
    )


def live_texts(host: FakeGameHost) -> dict[str, list[str]]:
    return {"instructions": list(host.instructions), "spoken": list(host.spoken)}


async def started(**kwargs: Any) -> tuple[WordleGame, FakeGameHost, str]:
    game, host = make_wordle(**kwargs)
    script = await game.start("voice", {})
    return game, host, script


async def collect() -> dict[str, Any]:
    """Todo lo que lee GPT-Live en casos representativos, con su nombre."""
    out: dict[str, Any] = {}

    # Arranque, reanudar, empujón, intentos (con pista, todo gris, muy cerca) y lo que no vale.
    game, host, script = await started()
    out["arranque.guion"] = script
    out["arranque.reanudar"] = await game.resume()
    out["arranque.empujon"] = game.nudge()
    out["intento.gris"] = await play(game, "BOTEH")
    out["intento.normal"] = await play(game, "REDIS")
    out["invalida.vacia"] = await play(game, NOT_SAID)
    out["invalida.largo"] = await play(game, "PYTHON")
    out["invalida.letras"] = await play(game, "K8S")
    out["invalida.repetida"] = await play(game, "redis")
    out["intento.cerca"] = await play(game, "KAFKE")
    out["intento.pista"] = await play(game, "SWIFT")
    out["intento.reanudar_con_pista"] = await game.resume()
    out["intento.ultimo"] = await play(game, "FLASK")
    out["gana"] = await play(game, SECRET)
    out["gana.ya_termino"] = await play(game, "CLOUD")
    out["gana.textos"] = live_texts(host)

    # Pierde: seis intentos sin acertar.
    game, host, _ = await started(hint="Un sistema de mensajes")
    lost = [await play(game, word) for word in ("REDIS", "SWIFT", "FLASK", "SCALA", "JULIA")]
    out["pierde.intentos"] = lost
    out["pierde.guion"] = await play(game, "CLOUD")

    # Gana sin contacto del equipo.
    game, host, _ = await started(settings=without_contact())
    out["gana.sin_contacto"] = await play(game, SECRET)

    # Otras filas y sin pista: otras reglas.
    game, host, script = await started(settings=wordle_settings(rows=4, hint_after=0))
    out["sin_pista.guion"] = script
    out["sin_pista.textos"] = live_texts(host)

    # Lo terminan con la partida en marcha (por voz y desde el panel).
    game, host, _ = await started()
    await play(game, "REDIS")
    out["lo_dejan.voz"] = await game.stop_requested("voice")
    game, host, _ = await started()
    out["panel.intento"] = await game.panel_control("guess", "redis")
    out["panel.ver_la_palabra"] = await game.panel_control("reveal", "")
    return out


async def test_los_textos_del_wordle_no_cambian() -> None:
    assert_snapshot("prompts_wordle", await collect())
