"""Terminar el Wordle con la partida en marcha (por voz o desde el panel): antes de cerrar se
enseña la palabra con su pista, como al perder, y GPT-Live recibe cuál era para decirla."""

from __future__ import annotations

from sonia.games import SCRIPT_PREFIX
from sonia.games.manager import PANEL_STOP_TEXT
from sonia.games.wordle import WordleGame
from sonia.games.wordle.bank import parse_words
from tests.games.fakes import settle
from tests.games.test_wordle import HINT, bank_text, make_wordle, rig, secret_of


def hint_of(word: str) -> str:
    return {e.word: e.hint for e in parse_words(bank_text()).entries}[word]


async def test_por_voz_sin_ningun_intento_la_palabra_sale_en_el_final() -> None:
    manager, _, screen, _, registry, ctx = await rig()
    await registry.execute("start_game", {"juego": "wordle"}, ctx)
    secret = secret_of(manager)
    result = await registry.execute("stop_game", {}, ctx)
    assert result.text.startswith(SCRIPT_PREFIX) and secret in result.text
    assert hint_of(secret) in result.text
    # Sin intentos no hay fila que repetir: la palabra va en el «end» (la tarjeta de Unity).
    assert screen.game_msgs("guess") == []
    await settle()
    assert screen.game_msgs("end")[-1]["data"] == {"word": secret, "attempts": 0, "result": "lose"}


async def test_desde_el_panel_ensena_la_palabra_y_sonia_la_dice() -> None:
    manager, engine, screen, _, registry, ctx = await rig()
    await registry.execute("start_game", {"juego": "wordle"}, ctx)
    await registry.execute("wordle_guess", {"palabra": "LINUX"}, ctx)
    secret = secret_of(manager)
    ok, text = await manager.stop("panel")
    assert ok and text == "Wordle de tecnología: enseña su final y se cierra."
    last = screen.game_msgs("guess")[-1]["data"]
    assert (last["result"], last["word"], last["hint"]) == ("lose", secret, hint_of(secret))
    assert manager.snapshot()["state"]["summary"] == "Lo dejaron (1 de 6)"
    await settle()
    spoken = engine.spoken[-1]
    assert spoken.startswith(PANEL_STOP_TEXT.format(spoken="el Wordle de tecnología"))
    assert f"la palabra era {secret}" in spoken
    assert screen.game_msgs("end")[-1]["data"] == {"word": secret, "attempts": 1, "result": "lose"}
    assert not manager.active


async def test_si_ya_termino_no_hay_nada_que_ensenar() -> None:
    game, host = make_wordle()
    await game.start("voice", {})
    assert isinstance(game, WordleGame)
    await game.guess({"palabra": game.word})  # aciertan: la partida ya está cerrada
    assert await game.stop_requested("voice") is None
    assert [r for r, _ in host.finished] == ["win"]


async def test_el_juego_suelto_cierra_con_la_derrota_y_su_pista() -> None:
    game, host = make_wordle()
    await game.start("voice", {})
    await game.guess({"palabra": "LINUX"})
    script = await game.stop_requested("panel")
    assert script is not None and "la palabra era KAFKA" in script and HINT in script
    assert host.finished == [("lose", {"word": "KAFKA", "attempts": 1})]
    assert host.last("guess")["result"] == "lose"
    # Ya no entra ningún intento más.
    assert "ya ha terminado" in await game.guess({"palabra": "REACT"})
