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
    await registry.execute("start_game", {"juego": "wordle", "sigue_a_sonnet_code": True}, ctx)
    secret = secret_of(manager)
    result = await registry.execute("stop_game", {}, ctx)
    assert result.text.startswith(SCRIPT_PREFIX) and secret in result.text
    assert hint_of(secret) in result.text
    # Sin intentos no hay fila que repetir, pero la pantalla recibe ya la palabra y su pista (en el
    # estado «lo dejan»: sin fila, tablero vacío) y no tiene que esperar al «end».
    (state,) = [m["data"] for m in screen.game_msgs("guess")]
    assert state["stopped"] is True and state["row"] == -1 and state["board"] == []
    assert (state["letters"], state["marks"], state["result"]) == ("", "", "lose")
    assert (state["word"], state["hint"]) == (secret, hint_of(secret))
    assert state["used"] == {"g": "", "y": "", "x": ""}
    assert manager.snapshot()["state"]["summary"] == "Lo dejaron (0 de 6)"
    await settle()
    assert screen.game_msgs("end")[-1]["data"] == {
        "word": secret,
        "attempts": 0,
        "stopped": True,
        "result": "lose",
    }


async def test_desde_el_panel_ensena_la_palabra_y_sonia_la_dice() -> None:
    manager, engine, screen, _, registry, ctx = await rig()
    await registry.execute("start_game", {"juego": "wordle", "sigue_a_sonnet_code": True}, ctx)
    await registry.execute("wordle_guess", {"palabra": "LINUX"}, ctx)
    secret = secret_of(manager)
    ok, text = await manager.stop("panel")
    assert ok and text == "Wordle de tecnología: enseña su final y se cierra."
    last = screen.game_msgs("guess")[-1]["data"]
    assert (last["result"], last["word"], last["hint"]) == ("lose", secret, hint_of(secret))
    # La misma fila y el mismo tablero, marcados como «lo dejan»: no es un intento nuevo.
    assert last["stopped"] is True and last["row"] == 0 and len(last["board"]) == 1
    assert manager.snapshot()["state"]["summary"] == "Lo dejaron (1 de 6)"
    await settle()
    spoken = engine.spoken[-1]
    assert spoken.startswith(PANEL_STOP_TEXT.format(spoken="el Wordle de tecnología"))
    assert f"la palabra era {secret}" in spoken
    assert screen.game_msgs("end")[-1]["data"] == {
        "word": secret,
        "attempts": 1,
        "stopped": True,
        "result": "lose",
    }
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
    assert host.finished == [("lose", {"word": "KAFKA", "attempts": 1, "stopped": True})]
    assert host.last("guess")["result"] == "lose" and host.last("guess")["stopped"] is True
    # Ya no entra ningún intento más.
    assert "ya ha terminado" in await game.guess({"palabra": "REACT"})


async def test_una_pantalla_que_se_reconecta_al_dejarlo_recibe_el_tablero_con_la_palabra() -> None:
    manager, _, screen, _, registry, ctx = await rig()
    await registry.execute("start_game", {"juego": "wordle", "sigue_a_sonnet_code": True}, ctx)
    await registry.execute("wordle_guess", {"palabra": "LINUX"}, ctx)
    await registry.execute("wordle_guess", {"palabra": "REACT"}, ctx)
    secret = secret_of(manager)
    await registry.execute("stop_game", {}, ctx)
    # Mientras enseña el final (aún no ha mandado el «end»), un hello nuevo repite el start y el
    # último estado: el tablero entero (las dos filas) con la palabra y la marca de «lo dejan».
    replay = screen.replay()
    assert [m["event"] for m in replay] == ["start", "guess"]
    state = replay[1]["data"]
    assert state["stopped"] is True and state["word"] == secret and state["result"] == "lose"
    assert [row["letters"] for row in state["board"]] == ["LINUX", "REACT"]
    await settle()


async def test_dejarlo_sin_intentos_ni_palabra_repetida_cuenta_cero() -> None:
    game, host = make_wordle()
    await game.start("voice", {})
    assert await game.stop_requested("voice") is not None
    state = host.last("guess")
    assert (state["row"], state["board"], state["stopped"]) == (-1, [], True)
    assert game.snapshot()["summary"] == "Lo dejaron (0 de 6)"
    assert game.snapshot()["result"] == "stopped" and game.snapshot()["over"] is True
    # Pedirlo otra vez no hace nada más: ya está cerrada.
    assert await game.stop_requested("panel") is None
    assert len(host.finished) == 1
