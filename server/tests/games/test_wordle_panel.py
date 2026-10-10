"""El Wordle llevado a mano desde el panel (``docs/juegos.md``, «Control a mano desde el
panel»): «Probar palabra» es un intento como el de GPT-Live y «Ver la palabra» la termina
enseñándola. Sin red, sin Unity y sin cámara."""

from __future__ import annotations

import pytest

from sonia.games import GameError
from sonia.games.manager import PANEL_CONTROL_TEXT
from sonia.games.wordle.game import PANEL_OVER_TEXT, PANEL_UNKNOWN_TEXT
from tests.games.fakes import settle
from tests.games.test_wordle import HINT, SECRET, make_wordle, rig, secret_of


def ids(controls: list[dict[str, object]]) -> list[object]:
    return [control["id"] for control in controls]


async def test_los_controles_cambian_con_la_fase() -> None:
    game, _ = make_wordle()
    assert game.panel_controls() == []  # sin partida
    await game.start("panel", {})
    guess, reveal = game.panel_controls()
    assert guess == {
        "id": "guess",
        "label": "Probar palabra",
        "kind": "text",
        "placeholder": "5 letras",
    }
    assert reveal == {"id": "reveal", "label": "Ver la palabra"}
    await game.panel_control("guess", "linux")
    assert ids(game.panel_controls()) == ["guess", "reveal"]  # sigue la partida
    await game.panel_control("guess", SECRET)
    assert game.panel_controls() == []  # acertaron: ya no hay nada que llevar
    # Otra partida, terminada con «Ver la palabra».
    await game.start("panel", {})
    assert ids(game.panel_controls()) == ["guess", "reveal"]
    await game.panel_control("reveal", "")
    assert game.panel_controls() == []


async def test_probar_palabra_es_un_intento_como_el_de_gpt_live() -> None:
    by_voice, voice_host = make_wordle()
    by_panel, panel_host = make_wordle()
    await by_voice.start("voice", {})
    await by_panel.start("panel", {})
    for word in ("flask", "Línux", "REACT"):
        spoken = await by_voice.guess({"palabra": word})
        typed = await by_panel.panel_control("guess", word)
        assert typed == spoken
    # La misma pantalla: el tablero entero en cada intento, con sus colores.
    assert panel_host.sent == voice_host.sent
    assert [row["letters"] for row in panel_host.last("guess")["board"]] == [
        "FLASK",
        "LINUX",
        "REACT",
    ]
    assert by_panel.snapshot()["attempts"] == 3


async def test_una_errata_del_panel_no_gasta_intento_ni_sacude_la_fila() -> None:
    game, host = make_wordle()
    await game.start("panel", {})
    cases = [
        ("web", "«web» tiene 3 letras: tienen que ser 5."),
        ("Kubernetes", "«Kubernetes» tiene 10 letras: tienen que ser 5."),
        ("ab1cd", "solo letras, sin números ni símbolos"),
        ("", "Escribe la palabra que dijeron: 5 letras."),
        ("   ", "Escribe la palabra"),
    ]
    for value, text in cases:
        with pytest.raises(GameError) as error:
            await game.panel_control("guess", value)
        assert text in str(error.value)
    await game.panel_control("guess", "LINUX")
    with pytest.raises(GameError) as error:
        await game.panel_control("guess", "linux")
    assert str(error.value) == "«LINUX» ya está en el tablero."
    # Nada de eso llegó a la pantalla ni a Sonia: un solo intento, sin sacudidas.
    assert host.events("invalid") == [] and host.spoken == []
    assert len(host.events("guess")) == 1 and game.snapshot()["attempts"] == 1


async def test_acertar_desde_el_panel_cierra_la_partida() -> None:
    game, host = make_wordle()
    await game.start("panel", {})
    script = await game.panel_control("guess", "kafka")
    assert "LO HAN ADIVINADO en el intento 1 de 6" in script and HINT in script
    assert host.finished == [("win", {"word": SECRET, "attempts": 1})]
    assert host.last("guess")["result"] == "win"
    for control in ("guess", "reveal"):
        with pytest.raises(GameError) as error:
            await game.panel_control(control, "LINUX")
        assert str(error.value) == PANEL_OVER_TEXT
    assert len(host.finished) == 1


async def test_ver_la_palabra_la_ensena_y_cierra_como_terminar() -> None:
    game, host = make_wordle()
    await game.start("panel", {})
    await game.panel_control("guess", "LINUX")
    script = await game.panel_control("reveal", "")
    # Lo mismo que «Terminar» con la partida en marcha (``stop_requested``).
    assert "la palabra era KAFKA" in script and HINT in script
    assert host.finished == [("lose", {"word": SECRET, "attempts": 1, "stopped": True})]
    state = host.last("guess")
    assert (state["result"], state["word"], state["stopped"], state["row"]) == (
        "lose",
        SECRET,
        True,
        0,
    )
    assert game.snapshot()["summary"] == "Lo dejaron (1 de 6)"


async def test_fuera_de_turno_o_sin_control_da_game_error() -> None:
    game, host = make_wordle()
    for control in ("guess", "reveal"):
        with pytest.raises(GameError) as error:
            await game.panel_control(control, "LINUX")  # aún no hay partida
        assert str(error.value) == PANEL_OVER_TEXT
    await game.start("panel", {})
    with pytest.raises(GameError) as error:
        await game.panel_control("spin", "")
    assert str(error.value) == PANEL_UNKNOWN_TEXT
    assert host.events("guess") == [] and host.finished == []


async def test_desde_el_manager_el_intento_llega_a_la_pantalla_y_a_sonia() -> None:
    manager, engine, screen, _, _, _ = await rig()
    ok, _ = await manager.start("wordle", "panel")
    assert ok
    assert ids(manager.snapshot()["controls"]) == ["guess", "reveal", "restart", "stop"]
    ok, text = await manager.panel_control("guess", "linux")
    assert ok and text == "Hecho."
    await settle()
    assert screen.game_msgs("guess")[-1]["data"]["letters"] == "LINUX"
    spoken = engine.spoken[-1]
    assert spoken.startswith(PANEL_CONTROL_TEXT) and "Intento 1 de 6, «LINUX»" in spoken
    # Una errata vuelve al equipo, sin tocar la partida.
    ok, text = await manager.panel_control("guess", "web")
    assert not ok and "tiene 3 letras" in text
    assert len(screen.game_msgs("guess")) == 1 and screen.game_msgs("invalid") == []
    # «Ver la palabra» enseña la palabra y cierra; ya solo quedan los controles comunes.
    secret = secret_of(manager)
    ok, _ = await manager.panel_control("reveal")
    assert ok and manager.phase == "finishing"
    assert ids(manager.snapshot()["controls"]) == ["restart", "stop"]
    last = screen.game_msgs("guess")[-1]["data"]
    assert (last["word"], last["stopped"]) == (secret, True)
    await settle()
    assert screen.game_msgs("end")[-1]["data"] == {
        "word": secret,
        "attempts": 1,
        "stopped": True,
        "result": "lose",
    }
    assert not manager.active


async def test_el_final_desde_el_panel_tambien_lo_dice_sonia() -> None:
    manager, engine, _, _, _, _ = await rig()
    await manager.start("wordle", "panel")
    await settle()
    assert len(engine.spoken) == 1  # la explicación del juego
    secret = secret_of(manager)
    ok, _ = await manager.panel_control("reveal")
    assert ok
    await settle()
    assert len(engine.spoken) == 2
    spoken = engine.spoken[-1]
    assert spoken.startswith(PANEL_CONTROL_TEXT) and f"la palabra era {secret}" in spoken
