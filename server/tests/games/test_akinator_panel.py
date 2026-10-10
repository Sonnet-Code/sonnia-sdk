"""Akinator dev: el control a mano desde el panel (``panel_controls`` y ``panel_control``).

Sin red ni APIs reales: el juego suelto con ``FakeGameHost`` y de punta a punta con el
``GameManager``. Lo demás del juego está en ``test_akinator.py``.
"""

from __future__ import annotations

import pytest

from sonia.games import NOT_SAID, GameError
from sonia.games.akinator import AkinatorGame
from sonia.games.manager import PANEL_CONTROL_TEXT
from tests.games.fakes import FakeGameHost, check_for_live, settle
from tests.games.test_akinator import (
    ask,
    feed_sonia,
    last_state,
    manager_rig,
    questions,
    say,
    start_game,
    visitor_speaks,
)


def control_ids(controls: list[dict[str, object]]) -> list[object]:
    return [control["id"] for control in controls]


async def guessing(answer: str = "Kotlin", asked: int = 9) -> tuple[AkinatorGame, FakeGameHost]:
    """Una partida con ``asked`` preguntas y la respuesta ``answer`` en la pantalla."""
    game, host = await start_game()
    visitor_speaks(game, host)
    await ask(game, *questions(asked))
    await game.guess({"respuesta": answer})
    return game, host


async def test_los_controles_cambian_con_la_fase() -> None:
    game, host = await start_game()
    assert game.panel_controls() == [{"id": "ready", "label": "Ya lo pensó"}]
    visitor_speaks(game, host)
    await ask(game, *questions(6))
    assert game.panel_controls() == [
        {"id": "yes", "label": "Sí"},
        {"id": "no", "label": "No"},
        {"id": "dont_know", "label": "No sé"},
    ]
    for guess in ("Java", "Swift", "Go"):
        await game.guess({"respuesta": guess})
        assert control_ids(game.panel_controls()) == ["right", "wrong"]
        await game.panel_control("wrong", "")
    # Tres fallos: se rinde y pregunta qué era; el equipo lo puede escribir.
    assert last_state(host)["phase"] == "giving_up"
    assert game.panel_controls() == [
        {"id": "answer", "label": "Decir qué era", "kind": "text", "placeholder": "Kotlin"}
    ]
    await game.panel_control("answer", "Rust")
    assert last_state(host)["phase"] == "revealed"
    assert game.panel_controls() == []


async def test_ya_lo_penso_empieza_la_cuenta_aunque_no_se_oiga_al_visitante() -> None:
    game, host = await start_game()
    # Sin el aviso del visitante (no se le oye) no se cuenta ninguna pregunta.
    await ask(game, "¿Es un lenguaje de programación?")
    assert [m["event"] for m in host.sent] == ["start", "waiting"]
    script = await game.panel_control("ready", "")
    assert "primera pregunta" in script
    check_for_live(script)
    await say(game, "¡Vamos! ¿Es un lenguaje de programación?")
    assert host.sent[-1]["event"] == "question"
    assert last_state(host)["asked"] == 1 and last_state(host)["phase"] == "asking"


async def test_si_no_y_no_se_cuentan_como_un_turno_corto_del_visitante() -> None:
    """Como en ``test_si_el_contador_se_queda_corto_valen_las_respuestas_del_visitante``,
    pero con el visitante mudo y el equipo contestando por él desde el panel."""
    game, host = await start_game()
    minimum = host.settings.games.akinator.min_questions
    await game.panel_control("ready", "")
    await ask(game, *questions(1))
    for answer, said in (("yes", "«sí»"), ("no", "«no»"), ("dont_know", "«no sé»")):
        script = await game.panel_control(answer, "")
        assert said in script and "pregunta de sí o no" in script
        check_for_live(script)
    for _ in range(minimum - 1 - 3):
        await game.panel_control("yes", "")
    # Las respuestas no cambian la pantalla: la cambia la siguiente pregunta de Sonia.
    assert [m["event"] for m in host.sent] == ["start", "waiting", "question"]
    with pytest.raises(GameError, match="pronto"):
        await game.guess({"respuesta": "Kotlin"})
    await game.panel_control("no", "")
    await game.guess({"respuesta": "Kotlin"})
    assert host.sent[-1]["event"] == "guess"


async def test_una_respuesta_del_panel_quita_el_empujon_de_un_turno_largo() -> None:
    game, host = await start_game()
    visitor_speaks(game, host)
    await ask(game, *questions(3))
    game.on_user_turn_end(host.now(), host.now() - 10)  # habló un rato: no fue un «sí»
    assert game.nudge() is not None
    await game.panel_control("no", "")
    assert game.nudge() is None


async def test_acerto_y_fallo_son_el_mismo_veredicto_que_por_voz() -> None:
    for control, verdict in (("right", "si"), ("wrong", "no")):
        by_voice, voice_host = await guessing()
        by_panel, panel_host = await guessing()
        expected = await by_voice.result({"acierto": verdict, "respuesta_real": NOT_SAID})
        assert await by_panel.panel_control(control, "") == expected
        assert panel_host.sent == voice_host.sent
        assert panel_host.finished == voice_host.finished


async def test_acerto_confeti_y_sonia_presume() -> None:
    game, host = await guessing("Kotlin", asked=9)
    script = await game.panel_control("right", "")
    assert "Acertaste" in script and "9 preguntas" in script
    check_for_live(script)
    assert host.sent[-1]["event"] == "reveal"
    reveal = last_state(host)
    assert reveal["phase"] == "revealed" and reveal["outcome"] == "sonnia"
    assert reveal["answer"] == "Kotlin"
    assert host.finished == [
        ("win", {"outcome": "sonnia", "answer": "Kotlin", "asked": 9, "tries": 1})
    ]


async def test_fallo_sigue_preguntando_si_le_quedan() -> None:
    game, host = await guessing("Java", asked=8)
    script = await game.panel_control("wrong", "")
    assert "«Java» no era" in script and "Te quedan 12 preguntas" in script
    assert host.sent[-1]["event"] == "miss"
    state = last_state(host)
    assert state["phase"] == "asking" and state["missed"] == ["Java"] and state["guess"] == ""
    assert host.finished == []


async def test_tras_rendirse_el_equipo_escribe_que_era_y_gana_el_visitante() -> None:
    game, host = await start_game()
    visitor_speaks(game, host)
    await ask(game, *questions(20))
    await say(game, "¡Me rindo! ¿Qué era?")
    assert last_state(host)["phase"] == "giving_up"
    for empty in ("", "   ", NOT_SAID, "¿?"):
        with pytest.raises(GameError, match="Escribe qué era"):
            await game.panel_control("answer", empty)
    script = await game.panel_control("answer", "  Rust. ")
    assert "«Rust»" in script and "¡me ganaste!" in script and "Brian o Mariel" in script
    check_for_live(script)
    assert host.sent[-1]["event"] == "reveal"
    assert last_state(host)["outcome"] == "visitor" and last_state(host)["answer"] == "Rust"
    assert host.finished == [
        ("lose", {"outcome": "visitor", "answer": "Rust", "asked": 20, "tries": 0})
    ]


async def test_fuera_de_turno_dan_game_error_y_no_tocan_nada() -> None:
    game, host = await start_game()
    for control in ("yes", "no", "dont_know"):
        with pytest.raises(GameError, match="hace una pregunta"):
            await game.panel_control(control, "")
    for control in ("right", "wrong"):
        with pytest.raises(GameError, match="arriesga"):
            await game.panel_control(control, "")
    with pytest.raises(GameError, match="se rinde"):
        await game.panel_control("answer", "Rust")
    with pytest.raises(GameError, match="no está disponible"):
        await game.panel_control("nada", "")

    visitor_speaks(game, host)
    await ask(game, *questions(6))
    with pytest.raises(GameError, match="piense"):
        await game.panel_control("ready", "")
    for control in ("right", "wrong"):
        with pytest.raises(GameError, match="arriesga"):
            await game.panel_control(control, "")

    await game.guess({"respuesta": "Kotlin"})
    before = list(host.sent)
    for control in ("yes", "no", "dont_know"):
        with pytest.raises(GameError, match="hace una pregunta"):
            await game.panel_control(control, "")
    with pytest.raises(GameError, match="se rinde"):
        await game.panel_control("answer", "Rust")
    assert host.sent == before and host.finished == []

    await game.panel_control("right", "")
    for control in ("ready", "yes", "right", "wrong"):
        with pytest.raises(GameError):
            await game.panel_control(control, "")
    with pytest.raises(GameError):
        await game.panel_control("answer", "Rust")
    assert len(host.finished) == 1


async def test_de_punta_a_punta_con_el_manager() -> None:
    manager, engine, screen, _, registry, ctx = await manager_rig()
    ok, _ = await manager.start("akinator", "panel")
    assert ok
    await settle()
    assert control_ids(manager.snapshot()["controls"]) == ["ready", "restart", "stop"]

    ok, message = await manager.panel_control("ready")
    assert ok and message
    await settle()
    assert engine.spoken[-1].startswith(PANEL_CONTROL_TEXT)
    assert "primera pregunta" in engine.spoken[-1]
    for n in range(1, 6):
        await feed_sonia(manager, f"¿Es la cosa número {n} de la lista?")
    assert screen.game_msgs("question")[-1]["data"]["asked"] == 5
    assert control_ids(manager.snapshot()["controls"]) == [
        "yes",
        "no",
        "dont_know",
        "restart",
        "stop",
    ]
    ok, _ = await manager.panel_control("dont_know")
    await settle()
    assert ok and "«no sé»" in engine.spoken[-1]

    # Fuera de turno: un mensaje para el equipo, sin excepción ni nada que decir.
    spoken = len(engine.spoken)
    ok, text = await manager.panel_control("right")
    await settle()
    assert not ok and "arriesga" in text and len(engine.spoken) == spoken

    await registry.execute("akinator_guess", {"respuesta": "Kotlin"}, ctx)
    assert control_ids(manager.snapshot()["controls"]) == ["right", "wrong", "restart", "stop"]
    ok, _ = await manager.panel_control("right")
    assert ok
    assert screen.game_msgs("reveal")[-1]["data"]["outcome"] == "sonnia"
    assert control_ids(manager.snapshot()["controls"]) == ["restart", "stop"]
    await settle()
    end = screen.game_msgs("end")[-1]
    assert end["data"]["result"] == "win" and end["data"]["answer"] == "Kotlin"
    assert not manager.active
