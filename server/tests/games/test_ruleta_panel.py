"""Control a mano de la ruleta desde el panel (``docs/juegos.md``, «Control a mano»): sin red.

Cada control hace lo mismo que la jugada de GPT-Live a la que sustituye (mismo guion y la
misma pantalla), solo sale cuando vale y, fuera de turno, da un ``GameError`` para el equipo.
"""

from __future__ import annotations

from typing import Any

import pytest

from sonia.games import GameError
from sonia.games.manager import PANEL_CONTROL_TEXT
from sonia.games.ruleta import texts as t
from sonia.games.ruleta.banks import SONNET
from sonia.games.ruleta.game import (
    PANEL_BAD_SCORE,
    PANEL_GOOD_SCORE,
    PANEL_NO_PREDICTION,
    PANEL_NO_ROUND,
    PANEL_NOT_NOW,
    PANEL_PROBABILITY,
    PANEL_ROUND_OVER,
    PANEL_SPINNING,
    RuletaGame,
)
from sonia.trivia.bank import TriviaQuestion
from sonia.ws import protocol as p
from tests.games.fakes import make_manager, settle
from tests.games.test_ruleta import (
    ONLY,
    QUESTION,
    SONNET_QUESTIONS,
    SONNET_TASKS,
    current,
    landed,
    new_game,
    ruleta_settings,
    started,
    stop_wheel,
)

TASKS = {SONNET.id: SONNET_TASKS}
QUESTIONS = {SONNET.id: SONNET_QUESTIONS}


def ids(controls: list[dict[str, Any]]) -> list[str]:
    return [c["id"] for c in controls]


def labels(controls: list[dict[str, Any]]) -> list[str]:
    return [c["label"] for c in controls]


# ---------------------------------------------------------------------------
# Qué controles salen en cada fase y en cada reto
# ---------------------------------------------------------------------------


async def test_los_controles_cambian_segun_la_fase() -> None:
    game, host = await started("trivia")
    assert game.panel_controls() == []  # girando: solo los comunes del manager
    await stop_wheel(game, host)
    controls = game.panel_controls()
    assert ids(controls) == ["A", "B", "C", "pass", "spin"]
    assert labels(controls) == [
        "A: Google, directamente",
        "B: GDG Santo Domingo",
        "C: La Biblioteca Nacional",
        "No lo sabe",
        "Cambiar de reto",
    ]
    await game.panel_control("B", "")
    assert game.panel_controls() == [{"id": "spin", "label": "Girar"}]
    await game.panel_control("spin", "")
    assert game.panel_controls() == []
    await stop_wheel(game, host)
    assert ids(game.panel_controls())[-1] == "spin"
    await game.stop("panel")
    assert game.panel_controls() == []


@pytest.mark.parametrize(
    ("kind", "banks", "expected"),
    [
        ("adivinanza", None, ["Acertó", "Falló", "Se rinde"]),
        (
            "explica",
            None,
            [f"Bien (nota {PANEL_GOOD_SCORE})", f"Flojo (nota {PANEL_BAD_SCORE})", "Se rinde"],
        ),
        ("sonnet", QUESTIONS, ["Acertó", "Falló", "Se rinde"]),
        ("sonnet", TASKS, ["Lo hizo", "No lo hizo", "Se rinde"]),
    ],
)
async def test_cada_reto_tiene_sus_botones(
    kind: str, banks: dict[str, str] | None, expected: list[str]
) -> None:
    game, _ = await landed(kind, cloud_banks=banks)
    controls = game.panel_controls()
    assert ids(controls) == ["right", "wrong", "pass", "spin"]
    assert labels(controls) == [*expected, "Cambiar de reto"]
    assert all("kind" not in c for c in controls)


async def test_la_prediccion_es_un_campo_de_texto() -> None:
    game, _ = await landed("futuro")
    predict, give_up, spin = game.panel_controls()
    assert predict["id"] == "predict" and predict["kind"] == "text" and predict["placeholder"]
    assert (give_up["id"], spin["id"]) == ("pass", "spin")


async def test_las_opciones_largas_se_cortan_en_el_boton() -> None:
    long_question = TriviaQuestion(
        "¿Qué hace Sonia?",
        ("Habla con la gente del stand y le cuenta cosas del DevFest " * 2, "B", "C"),
        0,
        "",
        "fácil",
    )
    game, _ = await landed("trivia", trivia_questions=[long_question])
    label = game.panel_controls()[0]["label"]
    assert label.startswith("A: Habla con la gente") and label.endswith("…")
    assert len(label) <= len("A: ") + 32


# ---------------------------------------------------------------------------
# Cada control mueve el juego y la pantalla como la jugada de GPT-Live
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "banks", "control", "play", "arguments"),
    [
        ("trivia", None, "B", "answer", {"respuesta": "B"}),
        ("trivia", None, "A", "answer", {"respuesta": "A"}),
        ("trivia", None, "pass", "answer", {"respuesta": "se_rinden"}),
        ("adivinanza", None, "right", "answer", {"respuesta": "acierto"}),
        ("adivinanza", None, "wrong", "answer", {"respuesta": "fallo"}),
        ("adivinanza", None, "pass", "answer", {"respuesta": "se_rinden"}),
        ("explica", None, "right", "score", {"nota": PANEL_GOOD_SCORE}),
        ("explica", None, "wrong", "score", {"nota": PANEL_BAD_SCORE}),
        ("explica", None, "pass", "answer", {"respuesta": "se_rinden"}),
        ("futuro", None, "pass", "answer", {"respuesta": "se_rinden"}),
        ("sonnet", TASKS, "right", "answer", {"respuesta": "acierto"}),
        ("sonnet", TASKS, "wrong", "answer", {"respuesta": "fallo"}),
        ("sonnet", TASKS, "pass", "answer", {"respuesta": "se_rinden"}),
        ("sonnet", QUESTIONS, "right", "answer", {"respuesta": "acierto"}),
        ("sonnet", QUESTIONS, "wrong", "answer", {"respuesta": "fallo"}),
        ("sonnet", QUESTIONS, "pass", "answer", {"respuesta": "se_rinden"}),
    ],
)
async def test_el_control_hace_lo_mismo_que_la_jugada(
    kind: str,
    banks: dict[str, str] | None,
    control: str,
    play: str,
    arguments: dict[str, Any],
) -> None:
    # La misma partida dos veces (misma semilla): una a mano y otra por voz.
    panel, panel_host = await landed(kind, cloud_banks=banks)
    voice, voice_host = await landed(kind, cloud_banks=banks)
    script = await panel.panel_control(control, "")
    assert script == await getattr(voice, play)(arguments)
    assert panel_host.sent == voice_host.sent
    assert panel.snapshot() == voice.snapshot()


async def test_un_fallo_a_mano_deja_seguir_el_reto_con_la_pista() -> None:
    game, host = await landed("adivinanza")
    riddle = current(game)
    script = await game.panel_control("wrong", "")
    assert riddle.hint in script and "Le quedan 2 intentos" in script
    assert host.last("challenge")["misses"] == 1
    assert ids(game.panel_controls()) == ["right", "wrong", "pass", "spin"]


async def test_la_nota_a_mano_sale_en_la_pantalla() -> None:
    game, host = await landed("explica")
    script = await game.panel_control("right", "")
    assert script.startswith(t.EXPLAIN_SCORE.format(score=PANEL_GOOD_SCORE))
    assert host.last("result")["score"] == PANEL_GOOD_SCORE
    assert game.snapshot()["wins"] == 1  # 8 supera el reto, como por voz


async def test_la_prediccion_a_mano() -> None:
    panel, panel_host = await landed("futuro")
    voice, voice_host = await landed("futuro")
    for empty in ("", "   ", "«»"):
        with pytest.raises(GameError, match=PANEL_NO_PREDICTION):
            await panel.panel_control("predict", empty)
    assert panel.snapshot()["phase"] == "challenge"
    # El mismo dado en las dos partidas: la probabilidad que saldrá a mano.
    probability = voice_host.rng.randint(*PANEL_PROBABILITY)
    text = "La IA escribirá los tests por nosotros"
    script = await panel.panel_control("predict", text)
    assert script == await voice.predict({"prediccion": text, "probabilidad": probability})
    assert panel_host.sent == voice_host.sent
    result = panel_host.last("result")
    assert result["prediction"] == text
    assert PANEL_PROBABILITY[0] <= result["probability"] <= PANEL_PROBABILITY[1]


@pytest.mark.parametrize("answered", [False, True])
async def test_girar_a_mano_es_otra_vuelta(answered: bool) -> None:
    settings = ruleta_settings("1,1,0,0,0")
    panel, panel_host = await landed("trivia", settings=settings)
    voice, voice_host = await landed("trivia", settings=settings)
    if answered:
        await panel.panel_control("B", "")
        await voice.answer({"respuesta": "B"})
    script = await panel.panel_control("spin", "")
    assert script == await voice.spin_again({})
    assert script == (t.SPIN_TEXT if answered else t.SKIP_TEXT)
    assert panel_host.sent == voice_host.sent
    assert panel_host.last("spin")["spin"] == 2
    assert panel.snapshot()["phase"] == "spinning"


# ---------------------------------------------------------------------------
# Fuera de turno
# ---------------------------------------------------------------------------


async def test_fuera_de_turno_da_game_error_sin_tocar_nada() -> None:
    game, host = new_game("adivinanza")
    with pytest.raises(GameError, match=PANEL_NO_ROUND):
        await game.panel_control("spin", "")
    await game.start("panel", {})
    sent = len(host.sent)
    for control in ("spin", "right", "nada"):
        with pytest.raises(GameError, match=PANEL_SPINNING):
            await game.panel_control(control, "")
    assert len(host.sent) == sent and game.snapshot()["phase"] == "spinning"
    await stop_wheel(game, host)
    sent = len(host.sent)
    for control in ("A", "predict", "nada", ""):
        with pytest.raises(GameError, match=PANEL_NOT_NOW):
            await game.panel_control(control, "algo")
    assert len(host.sent) == sent and game.snapshot()["phase"] == "challenge"
    await game.panel_control("right", "")
    sent = len(host.sent)
    for control in ("right", "wrong", "pass", "B"):
        with pytest.raises(GameError, match=PANEL_ROUND_OVER):
            await game.panel_control(control, "")
    assert len(host.sent) == sent and game.snapshot()["phase"] == "result"
    await game.stop("panel")
    with pytest.raises(GameError, match=PANEL_NO_ROUND):
        await game.panel_control("spin", "")


# ---------------------------------------------------------------------------
# De punta a punta con el GameManager
# ---------------------------------------------------------------------------


async def test_de_punta_a_punta_con_el_manager() -> None:
    manager, engine, screen, _ = await make_manager(
        [RuletaGame],
        settings=ruleta_settings(ONLY["trivia"]),
        trivia_draw=lambda level: QUESTION,
    )
    ok, _ = await manager.start("ruleta", "panel")
    assert ok
    assert ids(manager.snapshot()["controls"]) == ["restart", "stop"]  # girando
    spin = screen.game_msgs("spin")[-1]["data"]
    await manager.on_game_event(
        {
            "type": p.MSG_GAME_EVENT,
            "game": RuletaGame.id,
            "event": "wheel_stopped",
            "data": {"spin": spin["spin"], "segment": spin["segment"]},
        }
    )
    await settle()
    assert ids(manager.snapshot()["controls"]) == [
        "A",
        "B",
        "C",
        "pass",
        "spin",
        "restart",
        "stop",
    ]
    ok, message = await manager.panel_control("B")
    assert ok and message == "Hecho."
    await settle()
    assert engine.spoken[-1].startswith(PANEL_CONTROL_TEXT)
    assert "es CORRECTA" in engine.spoken[-1]
    assert screen.game_msgs("result")[-1]["data"]["outcome"] == "win"
    ok, message = await manager.panel_control("A")
    assert not ok and message == PANEL_ROUND_OVER
    assert ids(manager.snapshot()["controls"]) == ["spin", "restart", "stop"]
    ok, _ = await manager.panel_control("spin")
    assert ok and len(screen.game_msgs("spin")) == 2
    await settle()
    assert engine.spoken[-1] == PANEL_CONTROL_TEXT + t.SPIN_TEXT
