"""La ruleta de Sonnia (``docs/juegos/ruleta.md``): sin red, sin Unity y sin APIs reales.

1. Los bancos (lo bien formado, lo mal formado, el mínimo y el tope del panel).
2. El giro: pesos, sin repetir la anterior y sin esperar a Unity para siempre.
3. Cada reto con un ``FakeGameHost``: jugadas, contadores, acierto, fallo y rendirse.
4. Las jugadas fuera de turno, los empujones y los textos para GPT-Live (tope y marcas).
5. De punta a punta con el ``GameManager``: voz, reconexión, abandono y sesión perdida.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sonia.actions import build_default_registry
from sonia.config import Settings
from sonia.games import BANK_MAX_CHARS, INSTRUCT_MAX_CHARS, NOT_SAID, SCRIPT_PREFIX, GameError
from sonia.games.demo import Capture, GameMsg, WaitEvent, load_demo
from sonia.games.ruleta import texts as t
from sonia.games.ruleta.banks import (
    ANSWER_MAX,
    DESCRIPTION_MAX,
    HINT_MAX,
    RIDDLE_MAX,
    RIDDLES,
    SONNET,
    SONNET_MAX,
    TECH_MAX,
    TECHS,
    VARIANTS_MAX,
    parse_riddles,
    parse_sonnet,
    parse_techs,
)
from sonia.games.ruleta.demo import steps as demo_steps
from sonia.games.ruleta.game import (
    ANNOUNCE_FALLBACK_S,
    ANNOUNCE_WAIT_S,
    ANSWER_VALUES,
    DEFAULT_WEIGHTS,
    EXPLAIN_AUTOSTART_S,
    PREDICTION_MAX,
    QUIZ_REMIND_GRACE_S,
    SPIN_GRACE_S,
    SPIN_SECONDS,
    WIN_MARK,
    Round,
    RuletaGame,
    build_segments,
    clean_prediction,
    for_live,
    for_screen,
    parse_weights,
)
from sonia.trivia.bank import TriviaQuestion
from sonia.types import ActionContext
from sonia.ws import protocol as p
from tests.games.fakes import (
    FakeGameHost,
    brands_in,
    game_settings,
    make_game,
    make_manager,
    settle,
)

QUESTION = TriviaQuestion(
    "¿Quién organiza el DevFest Santo Domingo?",
    ("Google, directamente", "GDG Santo Domingo", "La Biblioteca Nacional"),
    1,
    "Lo organiza la comunidad, con voluntarios.",
    "fácil",
)

#: Pesos que fuerzan cada casilla.
ONLY = {
    "trivia": "1,0,0,0,0",
    "adivinanza": "0,1,0,0,0",
    "explica": "0,0,1,0,0",
    "futuro": "0,0,0,1,0",
    "sonnet": "0,0,0,0,1",
}
INDEX = {kind: i for i, kind in enumerate(ONLY)}

SONNET_TASKS = "\n".join(
    f"## [reto] Reto de stand número {i}: choca los cinco con {{contacto}}." for i in range(5)
)
SONNET_QUESTIONS = "\n".join(
    f"## [pregunta] ¿Pregunta {i} sobre Sonnet Code?\n- Respuesta: respuesta {i}\n"
    f"- También vale: otra {i}"
    for i in range(5)
)


def ruleta_settings(weights: str = "1,1,1,1,1", **fields: Any) -> Settings:
    base = game_settings(result_seconds=0.0, final_wait_seconds=0.0)
    block = base.games.ruleta.model_copy(update={"weights": weights, **fields})
    return base.model_copy(update={"games": base.games.model_copy(update={"ruleta": block})})


def new_game(kind: str = "", **kwargs: Any) -> tuple[RuletaGame, FakeGameHost]:
    kwargs.setdefault("settings", ruleta_settings(ONLY[kind] if kind else "1,1,1,1,1"))
    kwargs.setdefault("trivia_questions", [QUESTION] * 8)
    return make_game(RuletaGame, **kwargs)


async def started(kind: str = "", **kwargs: Any) -> tuple[RuletaGame, FakeGameHost]:
    game, host = new_game(kind, **kwargs)
    await game.start("voice", {})
    return game, host


async def stop_wheel(game: RuletaGame, host: FakeGameHost) -> None:
    """Unity dice que la ruleta paró, y corre el anuncio del reto."""
    spin = host.last("spin")
    await game.on_unity_event("wheel_stopped", {"spin": spin["spin"], "segment": spin["segment"]})
    await host.run_tasks()


async def landed(kind: str, **kwargs: Any) -> tuple[RuletaGame, FakeGameHost]:
    game, host = await started(kind, **kwargs)
    await stop_wheel(game, host)
    return game, host


async def announced(game: RuletaGame, host: FakeGameHost) -> None:
    """Sonia lee el anuncio del reto y calla: desde ahí cuentan los contadores."""
    host.quiet = 0.0
    await game.tick(host.now())
    host.quiet = 1.0
    await game.tick(host.now())


def current(game: RuletaGame) -> Round:
    round_ = game._round
    assert round_ is not None
    return round_


# ---------------------------------------------------------------------------
# 1. Bancos
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bank", [RIDDLES, TECHS, SONNET], ids=lambda b: b.id)
def test_los_bancos_de_la_app_se_leen_enteros_y_caben_en_el_panel(bank: Any) -> None:
    path = game_settings().games_dir / RuletaGame.id / bank.file
    text = path.read_text(encoding="utf-8")
    parsed = bank.parse(text)
    assert parsed.warnings == []
    assert len(parsed.entries) >= bank.min_entries
    assert len(text) <= BANK_MAX_CHARS, "el panel no lo podría guardar"
    assert "pendiente de revisión de Jean" in text
    assert bank in RuletaGame.banks()


def test_los_bancos_tienen_lo_que_pide_el_plan() -> None:
    games_dir = game_settings().games_dir / RuletaGame.id
    riddles = parse_riddles((games_dir / RIDDLES.file).read_text(encoding="utf-8")).entries
    techs = parse_techs((games_dir / TECHS.file).read_text(encoding="utf-8")).entries
    sonnet = parse_sonnet((games_dir / SONNET.file).read_text(encoding="utf-8")).entries
    assert len(riddles) >= 30 and len(techs) >= 40 and len(sonnet) >= 12
    assert {c.kind for c in sonnet} == {"pregunta", "reto"}
    # Nada de lo que lee GPT-Live nombra el stack.
    for riddle in riddles:
        assert not brands_in(" ".join((riddle.text, riddle.answer, riddle.hint, *riddle.variants)))
    for tech in techs:
        assert not brands_in(f"{tech.name} {tech.description}")
    for challenge in sonnet:
        assert not brands_in(" ".join((challenge.text, challenge.answer, *challenge.variants)))


def test_adivinanzas_mal_formadas_se_saltan_con_aviso() -> None:
    text = f"""\
<!-- ## Esto es un comentario y no cuenta -->
# Título que no cuenta

## ¿Qué tiene teclas?
- Respuesta: el teclado
- También vale: teclado, keyboard.
- Pista: Sirve para escribir.

## Sin respuesta
- Pista: algo

## Sin pista
- Respuesta: algo

## {"x" * (RIDDLE_MAX + 1)}
- Respuesta: algo
- Pista: algo

## ¿Qué tiene teclas?
- Respuesta: repetida
- Pista: repetida

## ¿Con comas dentro?
- RESPUESTA: Santo Domingo, Madrid
- tambien vale: Madrid, Santo Domingo; las dos ciudades
- pista: dos ciudades
"""
    parsed = parse_riddles(text)
    assert [r.text for r in parsed.entries] == ["¿Qué tiene teclas?", "¿Con comas dentro?"]
    first, second = parsed.entries
    assert first.answer == "el teclado" and first.variants == ("teclado", "keyboard")
    assert second.variants == ("Madrid, Santo Domingo", "las dos ciudades")
    assert len(parsed.warnings) == 4
    assert any("Respuesta" in w for w in parsed.warnings)
    assert any("Pista" in w for w in parsed.warnings)
    assert any("tope" in w for w in parsed.warnings)
    assert any("repetida" in w for w in parsed.warnings)


def test_tecnologias_con_su_nota_opcional() -> None:
    parsed = parse_techs(
        f"## Kubernetes\n> Orquesta contenedores.\n\n## Git\n\n## {'k' * (TECH_MAX + 1)}\n\n"
        f"## Docker\n> {'d' * (DESCRIPTION_MAX + 1)}\n\n## git\n"
    )
    assert [(x.name, x.description) for x in parsed.entries] == [
        ("Kubernetes", "Orquesta contenedores."),
        ("Git", ""),
    ]
    assert len(parsed.warnings) == 3


def test_retos_de_sonnet_code_preguntas_y_retos() -> None:
    parsed = parse_sonnet(
        "## [pregunta] ¿Lema?\n- Respuesta: Equipos que entregan\n- También vale: entregan\n\n"
        "## [reto] Choca los cinco con {contacto}.\n- Respuesta: se ignora\n\n"
        "## ¿Sin etiqueta y con respuesta?\n- Respuesta: sí\n\n"
        "## Sin etiqueta ni respuesta: un reto\n\n"
        "## [pregunta] Sin respuesta\n\n"
        "## [concurso] Etiqueta rara\n\n"
        f"## [reto] {'r' * (SONNET_MAX + 1)}\n"
    )
    kinds = [(c.kind, c.text, c.answer) for c in parsed.entries]
    assert kinds == [
        ("pregunta", "¿Lema?", "Equipos que entregan"),
        ("reto", "Choca los cinco con {contacto}.", ""),
        ("pregunta", "¿Sin etiqueta y con respuesta?", "sí"),
        ("reto", "Sin etiqueta ni respuesta: un reto", ""),
    ]
    assert len(parsed.warnings) == 3


def test_un_banco_de_la_nube_corto_no_se_usa() -> None:
    game, host = new_game(
        "adivinanza", cloud_banks={RIDDLES.id: "## ¿Una sola?\n- Respuesta: sí\n- Pista: no"}
    )
    entries = host.read_bank(RIDDLES)
    assert len(entries) >= RIDDLES.min_entries  # el de la app


# ---------------------------------------------------------------------------
# 2. El giro
# ---------------------------------------------------------------------------


def test_los_pesos() -> None:
    assert parse_weights("1,1,1,1,1") == DEFAULT_WEIGHTS
    assert parse_weights(" 2; 0 1.5 1,1") == (2.0, 0.0, 1.5, 1.0, 1.0)
    for bad in ("", "1,1,1", "1,1,1,1,1,1", "a,1,1,1,1", "-1,1,1,1,1", "0,0,0,0,0", "nan,1,1,1,1"):
        assert parse_weights(bad) == DEFAULT_WEIGHTS, bad


async def test_la_ruleta_no_repite_la_casilla_anterior_ni_saca_las_de_peso_cero() -> None:
    game, _ = await started(settings=ruleta_settings("1,1,0,1,1"))
    seen = set()
    for _ in range(200):
        previous = game._previous
        index = game._choose()
        assert index is not None and index != previous and index != INDEX["explica"]
        seen.add(index)
        game._previous = index
    assert seen == {0, 1, 3, 4}


async def test_con_una_sola_casilla_se_repite() -> None:
    game, host = await landed("futuro")
    await game.answer({"respuesta": "se_rinden"})
    await game.spin_again({})
    assert [d["segment"] for d in host.events("spin")] == [INDEX["futuro"]] * 2


async def test_empezar_monta_la_ruleta_pasa_las_reglas_y_gira() -> None:
    game, host = new_game()
    script = await game.start("voice", {})
    assert script == t.START_TEXT
    assert [m["event"] for m in host.sent] == ["start", "spin"]
    start = host.last("start")
    assert [s["id"] for s in start["segments"]] == list(ONLY)
    assert all(s["label"] and s["icon"] and not s["off"] for s in start["segments"])
    assert start["segments"][2]["label"] == "Explica en 20 s"
    spin = host.last("spin")
    assert spin == {"spin": 1, "segment": spin["segment"], "duration_s": SPIN_SECONDS, "wins": 0}
    assert host.sent[-1]["sticky"]
    # Las reglas: una instrucción con los cinco retos y sin decir ninguno todavía.
    (rules,) = host.instructions
    assert len(rules) <= INSTRUCT_MAX_CHARS
    for name in ("trivia relámpago", "adivinanza geek", "explica una tecnología en 20 segundos"):
        assert name in rules
    assert "Brian o Mariel" in rules
    assert game.snapshot()["phase"] == "spinning"


async def test_sin_retos_no_empieza(tmp_path: Path) -> None:
    folder = tmp_path / "games" / RuletaGame.id
    folder.mkdir(parents=True)
    for bank in (RIDDLES, TECHS, SONNET):
        (folder / bank.file).write_text("<!-- vacío -->\n", encoding="utf-8")
    settings = ruleta_settings("1,1,1,0,1").model_copy(update={"assets_dir": str(tmp_path)})
    game, host = new_game(settings=settings, trivia_questions=[])
    with pytest.raises(GameError):
        await game.start("voice", {})
    # Sin trivia (apagada) pero con banco, la casilla de la trivia no sale.
    game, host = new_game(settings=ruleta_settings("5,1,0,0,0"), trivia_questions=[])
    await game.start("voice", {})
    assert host.last("spin")["segment"] == INDEX["adivinanza"]
    assert INDEX["trivia"] in game._off


async def test_la_ruleta_para_y_llega_el_reto() -> None:
    game, host = await started("adivinanza")
    await stop_wheel(game, host)
    challenge = host.last("challenge")
    assert challenge["kind"] == "adivinanza" and challenge["spin"] == 1
    assert challenge["title"] == "ADIVINANZA GEEK" and challenge["hint"] == ""
    # Las reglas del reto y, en cuanto calla, el anuncio con la adivinanza.
    riddle = current(game)
    assert riddle.prompt in host.instructions[-1] and riddle.answer in host.instructions[-1]
    assert host.spoken[-1].startswith("RULETA: ha caído en ADIVINANZA GEEK")
    assert riddle.prompt in host.spoken[-1] and riddle.answer not in host.spoken[-1]
    assert game.snapshot()["phase"] == "challenge"


async def test_si_unity_no_contesta_la_ruleta_para_sola() -> None:
    game, host = await started("futuro")
    await game.tick(host.now() + SPIN_SECONDS)
    assert not host.events("challenge")
    await game.tick(host.now() + SPIN_SECONDS + SPIN_GRACE_S)
    await host.run_tasks()
    assert host.last("challenge")["kind"] == "futuro"
    # Un wheel_stopped que llega tarde no hace nada.
    sent = len(host.sent)
    await game.on_unity_event("wheel_stopped", {"spin": 1, "segment": INDEX["futuro"]})
    assert len(host.sent) == sent


async def test_wheel_stopped_de_otra_vuelta_o_raro_se_ignora() -> None:
    game, host = await started("futuro")
    await game.on_unity_event("wheel_stopped", {"spin": 7, "segment": 3})
    await game.on_unity_event("otra_cosa", {})
    assert not host.events("challenge")
    # Sin datos vale (y la casilla la manda el orquestador).
    await game.on_unity_event("wheel_stopped", {"segment": 0})
    assert host.last("challenge")["segment"] == INDEX["futuro"]


# ---------------------------------------------------------------------------
# 3. Los retos
# ---------------------------------------------------------------------------


async def test_trivia_relampago_acierto() -> None:
    game, host = await landed("trivia")
    rules = host.instructions[-1]
    for option in QUESTION.options:
        assert option in rules
    # GPT-Live no sabe la buena hasta el resultado.
    assert "CORRECTA" not in " ".join(host.instructions + host.spoken)
    assert "No sabes cuál es la buena" in rules
    assert QUESTION.text in host.spoken[-1] and QUESTION.options[0] not in host.spoken[-1]
    card = host.last("challenge")
    assert card["options"] == list(QUESTION.options)
    assert card["timer"] == {"seconds": 20.0, "running": False}
    script = await game.answer({"respuesta": "B"})
    assert "es CORRECTA" in script and QUESTION.fact in script and t.AGAIN_TEXT in script
    result = host.last("result")
    assert (result["outcome"], result["chosen"], result["correct"]) == ("win", 1, 1)
    assert "timer" not in result
    assert game.snapshot()["wins"] == 1


async def test_trivia_relampago_fallo_y_se_rinden() -> None:
    game, host = await landed("trivia")
    script = await game.answer({"respuesta": "A"})
    assert "NO es correcta" in script and "la B, «GDG Santo Domingo»" in script
    assert host.last("result")["outcome"] == "lose"
    await game.spin_again({})
    await stop_wheel(game, host)
    script = await game.answer({"respuesta": "se_rinden"})
    assert script.startswith("No lo sabe") and host.last("result")["outcome"] == "pass"
    assert host.last("result")["chosen"] == -1


async def test_trivia_relampago_pide_la_letra() -> None:
    game, host = await landed("trivia")
    for value in ("acierto", "fallo"):
        with pytest.raises(GameError, match="letra"):
            await game.answer({"respuesta": value})
    with pytest.raises(GameError, match="Aún no ha contestado"):
        await game.answer({"respuesta": NOT_SAID})
    assert game.snapshot()["phase"] == "challenge"


async def test_trivia_relampago_contador_y_recordatorio() -> None:
    game, host = await landed("trivia")
    await announced(game, host)
    assert host.last("challenge")["timer"]["running"] is True
    spoken = len(host.spoken)
    await game.tick(host.now() + 20.0)
    assert len(host.spoken) == spoken  # el contador es solo visual
    host.quiet = 0.2  # Sonia habla: no se la pisa
    await game.tick(host.now() + 20.0 + QUIZ_REMIND_GRACE_S)
    await host.run_tasks()
    assert len(host.spoken) == spoken
    host.quiet = 2.0
    await game.tick(host.now() + 20.0 + QUIZ_REMIND_GRACE_S)
    await game.tick(host.now() + 40.0)
    await host.run_tasks()
    assert host.spoken[spoken:] == [t.QUIZ_REMIND_TEXT]  # una sola vez


async def test_adivinanza_acierto() -> None:
    game, host = await landed("adivinanza")
    riddle = current(game)
    script = await game.answer({"respuesta": "acierto"})
    assert riddle.answer in script and t.AGAIN_TEXT in script
    result = host.last("result")
    assert result["outcome"] == "win" and result["answer"] == for_screen(riddle.answer)


async def test_adivinanza_fallos_pista_y_derrota() -> None:
    game, host = await landed("adivinanza")
    riddle = current(game)
    script = await game.answer({"respuesta": "fallo"})
    # Con el primer fallo sale la pista, en pantalla y para que la diga.
    assert riddle.hint in script and "Le quedan 2 intentos" in script
    assert riddle.answer not in script
    card = host.last("challenge")
    assert card["misses"] == 1 and card["hint"] == for_screen(riddle.hint)
    script = await game.answer({"respuesta": "fallo"})
    assert "Le queda un intento" in script and riddle.hint not in script
    script = await game.answer({"respuesta": "fallo"})
    assert riddle.answer in script and "se acabaron los intentos" in script
    assert host.last("result")["outcome"] == "lose"
    with pytest.raises(GameError, match="ya terminó"):
        await game.answer({"respuesta": "acierto"})


async def test_adivinanza_la_pista_sale_sola() -> None:
    game, host = await landed("adivinanza")
    riddle = current(game)
    await announced(game, host)
    hint_at = host.now() + 30.0
    await game.tick(hint_at - 0.1)
    assert host.last("challenge")["hint"] == ""
    await game.tick(hint_at)
    await host.run_tasks()
    assert host.last("challenge")["hint"] == for_screen(riddle.hint)
    assert host.spoken[-1] == t.HINT_TEXT.format(hint=for_live(riddle.hint))
    # Rendirse da la solución.
    script = await game.answer({"respuesta": "se_rinden"})
    assert riddle.answer in script and host.last("result")["outcome"] == "pass"


async def test_explica_el_tiempo_arranca_al_hablar() -> None:
    game, host = await landed("explica")
    tech = current(game).prompt
    assert "EN 20 SEGUNDOS" in host.instructions[-1] and tech.upper() in host.instructions[-1]
    assert host.last("challenge")["timer"] == {"seconds": 20.0, "running": False}
    game.on_user_text(host.now())  # mientras anuncia: no cuenta
    await announced(game, host)
    await game.tick(host.now())
    assert host.last("challenge")["timer"]["running"] is False
    game.on_user_text(host.now())
    await game.tick(host.now())
    assert host.last("challenge")["timer"]["running"] is True
    assert game.nudge() is None  # está explicando


async def test_explica_el_tiempo_arranca_solo_y_acaba_con_tiempo_y_nota() -> None:
    game, host = await landed("explica", recorded=[t.TIME_PHRASE])
    await announced(game, host)
    start = host.now() + EXPLAIN_AUTOSTART_S
    await game.tick(start - 0.1)
    assert host.last("challenge")["timer"]["running"] is False
    await game.tick(start)
    assert host.last("challenge")["timer"]["running"] is True
    await game.tick(start + 19.9)
    assert host.last("challenge")["time_up"] is False
    await game.tick(start + 20.0)
    await host.run_tasks()
    assert host.last("challenge")["time_up"] is True
    assert host.fixed == [(t.TIME_PHRASE, True)]
    assert host.spoken[-1] == t.TIME_UP_TEXT
    assert game.nudge() == t.NUDGE_CHALLENGE
    script = await game.score({"nota": 8})
    assert "Nota 8 de 10" in script
    result = host.last("result")
    assert result["outcome"] == "done" and result["score"] == 8
    assert game.snapshot()["wins"] == 1  # 8 cuenta como superado


async def test_explica_si_el_tiempo_no_suena_lo_dice_ella() -> None:
    game, host = await landed("explica", connected=False)
    await game.tick(host.now() + ANNOUNCE_WAIT_S + ANNOUNCE_FALLBACK_S)  # sin sesión: no se la oye
    await game.tick(host.now() + ANNOUNCE_WAIT_S + ANNOUNCE_FALLBACK_S + EXPLAIN_AUTOSTART_S)
    await game.tick(host.now() + 200.0)
    await host.run_tasks()
    assert host.spoken[-1] == t.TIME_UP_SAY_TEXT


async def test_explica_nota_antes_de_tiempo_y_fuera_de_rango() -> None:
    game, host = await landed("explica")
    script = await game.score({"nota": 42})
    assert "Nota 10 de 10" in script and host.last("result")["score"] == 10
    await game.spin_again({})
    await stop_wheel(game, host)
    await game.score({"nota": -3})
    assert host.last("result")["score"] == 1
    assert game.snapshot()["wins"] == 1


async def test_explica_pide_nota_y_se_puede_rendir() -> None:
    game, host = await landed("explica")
    with pytest.raises(GameError, match="nota"):
        await game.answer({"respuesta": "acierto"})
    script = await game.answer({"respuesta": "se_rinden"})
    assert script.startswith(t.EXPLAIN_PASS) and host.last("result")["outcome"] == "pass"


async def test_futuro_prediccion_y_probabilidad() -> None:
    game, host = await landed("futuro")
    assert "120 caracteres" in host.instructions[-1]
    with pytest.raises(GameError, match="predicción"):
        await game.answer({"respuesta": "acierto"})
    with pytest.raises(GameError, match="Aún no hay predicción"):
        await game.predict({"prediccion": "  «»  ", "probabilidad": 40})
    script = await game.predict(
        {"prediccion": "«Sonia tendrá cuerpo de robot»", "probabilidad": 140}
    )
    assert "Sonia tendrá cuerpo de robot" in script and "100 %" in script
    result = host.last("result")
    assert result["prediction"] == "Sonnia tendrá cuerpo de robot"
    assert result["probability"] == 100 and result["outcome"] == "done"


def test_la_prediccion_se_corta_en_una_linea() -> None:
    long = "La inteligencia artificial " + "cambiará todo " * 20
    text = clean_prediction(long)
    assert len(text) <= PREDICTION_MAX and text.endswith("…")
    assert clean_prediction(None) == "" and clean_prediction("  ") == ""


async def test_sonnet_reto_de_stand_cumplido() -> None:
    game, host = await landed("sonnet", cloud_banks={SONNET.id: SONNET_TASKS})
    card = host.last("challenge")
    assert card["task"] is True and "Brian o Mariel" in card["prompt"]
    assert "{contacto}" not in host.instructions[-1] and "créele" in host.instructions[-1]
    script = await game.answer({"respuesta": "acierto"})
    assert script.startswith(t.SONNET_DONE)
    assert host.last("result")["outcome"] == "win" and "answer" not in host.last("result")


async def test_sonnet_reto_de_stand_sin_hacer() -> None:
    game, host = await landed("sonnet", cloud_banks={SONNET.id: SONNET_TASKS})
    script = await game.answer({"respuesta": "se_rinden"})
    assert script.startswith(t.SONNET_TASK_PASS) and host.last("result")["outcome"] == "pass"


async def test_sonnet_pregunta_fallo_y_derrota() -> None:
    game, host = await landed("sonnet", cloud_banks={SONNET.id: SONNET_QUESTIONS})
    question = current(game)
    assert question.answer in host.instructions[-1]  # para juzgar
    assert question.answer not in host.spoken[-1]
    with pytest.raises(GameError, match="Sonnet Code"):
        await game.answer({"respuesta": "C"})
    script = await game.answer({"respuesta": "fallo"})
    assert "Le queda un intento" in script and question.answer not in script
    assert host.last("challenge")["misses"] == 1
    script = await game.answer({"respuesta": "fallo"})
    assert question.answer in script and host.last("result")["outcome"] == "lose"
    assert host.last("result")["answer"] == question.answer


# ---------------------------------------------------------------------------
# 4. Fuera de turno, empujones, textos
# ---------------------------------------------------------------------------


async def test_jugadas_fuera_de_turno_reconducen() -> None:
    game, host = await started("trivia")
    for play, args in (
        (game.answer, {"respuesta": "A"}),
        (game.score, {"nota": 5}),
        (game.predict, {"prediccion": "algo", "probabilidad": 5}),
    ):
        with pytest.raises(GameError, match="girando"):
            await play(args)
    with pytest.raises(GameError, match="ya está girando"):
        await game.spin_again({})
    await stop_wheel(game, host)
    with pytest.raises(GameError, match="letra"):
        await game.score({"nota": 5})
    with pytest.raises(GameError, match="letra"):
        await game.predict({"prediccion": "algo", "probabilidad": 5})
    await game.answer({"respuesta": "B"})
    for play, args in (
        (game.answer, {"respuesta": "B"}),
        (game.score, {"nota": 5}),
        (game.predict, {"prediccion": "algo", "probabilidad": 5}),
    ):
        with pytest.raises(GameError, match="ya terminó"):
            await play(args)


async def test_otra_vuelta_con_un_reto_a_medias_lo_salta() -> None:
    game, host = await landed("trivia", settings=ruleta_settings("1,1,0,0,0"))
    assert host.last("challenge")["kind"] == "trivia"
    script = await game.spin_again({})
    assert script == t.SKIP_TEXT
    spin = host.last("spin")
    assert spin["spin"] == 2 and spin["segment"] == INDEX["adivinanza"]
    # Lo que le quedaba al reto saltado no llega: ni el anuncio ni los contadores.
    await game.tick(host.now() + 100.0)
    assert host.last("challenge")["spin"] == 2  # aterrizó solo, ya en la vuelta nueva


async def test_resume_dice_por_donde_va() -> None:
    game, host = await started("futuro")
    assert await game.resume() == t.RESUME_SPINNING
    await stop_wheel(game, host)
    assert "predice el futuro de la IA" in await game.resume()
    await game.answer({"respuesta": "se_rinden"})
    assert await game.resume() == t.RESUME_RESULT


async def test_empujones_segun_la_fase() -> None:
    game, host = await started("adivinanza")
    assert game.nudge() == t.NUDGE_SPINNING  # girando: solo parar
    await stop_wheel(game, host)
    assert game.nudge() == t.NUDGE_CHALLENGE
    await game.answer({"respuesta": "acierto"})
    assert game.nudge() == t.NUDGE_RESULT


async def test_tres_retos_superados_manda_con_el_equipo_una_vez() -> None:
    game, host = await landed("adivinanza", settings=ruleta_settings("0,1,0,0,0"))
    scripts = []
    for _ in range(WIN_MARK + 1):
        scripts.append(await game.answer({"respuesta": "acierto"}))
        await game.spin_again({})
        await stop_wheel(game, host)
    with_contact = [s for s in scripts if "Brian o Mariel" in s]
    assert len(with_contact) == 1 and with_contact[0] is scripts[WIN_MARK - 1]
    assert "premios" in with_contact[0]


async def test_snapshot_y_parar() -> None:
    game, host = await landed("adivinanza")
    snap = game.snapshot()
    assert snap["phase"] == "challenge" and snap["challenge"] == "adivinanza"
    assert snap["title"] == "ADIVINANZA GEEK" and snap["spins"] == 1
    assert snap["summary"] == "Vuelta 1: Adivinanza geek"
    await game.answer({"respuesta": "acierto"})
    assert game.snapshot()["summary"] == "Vuelta 1: Adivinanza geek, superado · 1 superado"
    await game.spin_again({})
    assert game.snapshot()["summary"] == "Vuelta 2: girando · 1 superado"
    await game.stop("voice")
    assert game.snapshot()["phase"] == "idle"
    assert game.snapshot()["summary"] == "Sin vuelta en marcha"
    # Tras parar, nada se mueve.
    sent = len(host.sent)
    await game.tick(host.now() + 500.0)
    assert len(host.sent) == sent


def test_frases_grabadas() -> None:
    game, _ = new_game()
    assert game.phrases() == [t.TIME_PHRASE]


def _longest_round(kind: str, **fields: Any) -> Round:
    return Round(1, INDEX[kind], kind, **fields)  # type: ignore[arg-type]


async def test_las_instrucciones_caben_con_las_entradas_mas_largas() -> None:
    contact = "Brian, Mariel o cualquier persona del equipo de Sonnet Code del stand"
    settings = ruleta_settings().model_copy(
        update={"trivia": game_settings().trivia.model_copy(update={"win_contact": contact})}
    )
    game, host = new_game(settings=settings)
    await game.start("voice", {})
    assert len(host.instructions[0]) <= INSTRUCT_MAX_CHARS
    word = "palabra "
    worst = [
        _longest_round(
            "trivia",
            prompt=(word * 40)[:300],
            options=((word * 12)[:90],) * 3,
            correct=0,
            timer_s=20.0,
        ),
        _longest_round(
            "adivinanza",
            prompt="a" * RIDDLE_MAX,
            answer="r" * ANSWER_MAX,
            variants=("v" * 20,) * (VARIANTS_MAX // 22),
            hint="h" * HINT_MAX,
            tries=3,
        ),
        _longest_round(
            "explica", prompt="T" * TECH_MAX, description="d" * DESCRIPTION_MAX, timer_s=20.0
        ),
        _longest_round("futuro", prompt="x"),
        _longest_round(
            "sonnet",
            prompt="s" * SONNET_MAX,
            answer="r" * ANSWER_MAX,
            variants=("v" * 20,) * (VARIANTS_MAX // 22),
            tries=2,
        ),
        _longest_round("sonnet", prompt="s" * SONNET_MAX, task=True),
    ]
    for round_ in worst:
        rules = game._rules_for(round_)
        assert len(rules) <= INSTRUCT_MAX_CHARS, (round_.kind, len(rules))
        assert not rules.endswith("…"), "no debería hacer falta recortar"
        assert not brands_in(rules) and "Sonnia" not in rules


def test_ningun_texto_para_sonia_nombra_el_stack_ni_dice_sonnia() -> None:
    texts = [v for k, v in vars(t).items() if k.isupper() and isinstance(v, str)]
    texts += [v for v in t.WRONG_PLAY.values()]
    assert len(texts) > 40
    for text in texts:
        assert not brands_in(text), text[:80]
        assert "Sonnia" not in text, text[:80]
    for spec in RuletaGame.actions():
        assert not brands_in(spec.description) and "Sonnia" not in spec.description


def test_en_pantalla_sonnia_y_para_ella_sonia() -> None:
    assert for_screen("Choca los cinco con Sonia") == "Choca los cinco con Sonnia"
    assert for_live("Hazte una foto con Sonnia") == "Hazte una foto con Sonia"
    assert for_screen("Sonnia") == "Sonnia" and for_live("Sonia") == "Sonia"
    assert "Sonnia" in RuletaGame.title and "Sonia" in RuletaGame.spoken
    for segment in build_segments(20.0):
        assert not brands_in(segment.spoken) and "Sonnia" not in segment.spoken


async def test_el_reto_dice_sonnia_en_pantalla_y_sonia_a_ella() -> None:
    bank = "\n".join(
        f"## [reto] Hazte la foto número {i} con Sonnia y etiqueta a @sonnetcode." for i in range(5)
    )
    game, host = await landed("sonnet", cloud_banks={SONNET.id: bank})
    assert "con Sonnia" in host.last("challenge")["prompt"]
    assert "con Sonia" in host.instructions[-1] and "Sonnia" not in host.instructions[-1]


def test_esquemas_de_las_jugadas() -> None:
    specs = {spec.name: spec for spec in RuletaGame.actions()}
    assert set(specs) == {"ruleta_spin", "ruleta_answer", "ruleta_score", "ruleta_prediccion"}
    answer = specs["ruleta_answer"].parameters
    assert answer["required"] == ["respuesta"]
    assert answer["properties"]["respuesta"]["enum"] == list(ANSWER_VALUES)
    assert {"A", "B", "C", "acierto", "fallo", "se_rinden", NOT_SAID} == set(ANSWER_VALUES)
    score = specs["ruleta_score"].parameters["properties"]["nota"]
    assert (score["type"], score["minimum"], score["maximum"]) == ("integer", 1, 10)
    prediction = specs["ruleta_prediccion"].parameters
    assert set(prediction["required"]) == {"prediccion", "probabilidad"}
    assert prediction["properties"]["prediccion"]["maxLength"] == PREDICTION_MAX
    assert specs["ruleta_spin"].parameters == {"type": "object", "properties": {}, "required": []}


def test_la_secuencia_del_orquestador_falso() -> None:
    steps = demo_steps()
    assert load_demo(RuletaGame.id) == steps
    events = [s.event for s in steps if isinstance(s, GameMsg)]
    assert events[0] == "start" and events[-1] == "end"
    assert {"spin", "challenge", "result"} <= set(events)
    captures = [s.name for s in steps if isinstance(s, Capture)]
    assert len(captures) == len(set(captures)) >= 15
    waits = [s for s in steps if isinstance(s, WaitEvent)]
    assert waits and all(w.event == "wheel_stopped" for w in waits)
    kinds = {s.data.get("kind") for s in steps if isinstance(s, GameMsg) and s.event == "result"}
    assert kinds == set(ONLY)


# ---------------------------------------------------------------------------
# 5. De punta a punta con el GameManager
# ---------------------------------------------------------------------------


async def _manager(weights: str = "1,0,0,0,0") -> tuple[Any, Any, Any, Any, Any, Any]:
    manager, engine, screen, clock = await make_manager(
        [RuletaGame], settings=ruleta_settings(weights), trivia_draw=lambda level: QUESTION
    )
    registry = build_default_registry(include_look=False, games=[RuletaGame])
    ctx = ActionContext(camera=None, avatar=None, gallery_dir="", extra={"games": manager})
    return manager, engine, screen, clock, registry, ctx


def _wheel_stopped(screen: Any) -> dict[str, Any]:
    spin = screen.game_msgs("spin")[-1]["data"]
    return {
        "type": p.MSG_GAME_EVENT,
        "game": RuletaGame.id,
        "event": "wheel_stopped",
        "data": {"spin": spin["spin"], "segment": spin["segment"]},
    }


async def test_partida_entera_por_voz() -> None:
    manager, engine, screen, clock, registry, ctx = await _manager("1,1,0,0,0")
    result = await registry.execute("start_game", {"juego": "ruleta"}, ctx)
    assert result.text == f"{SCRIPT_PREFIX} {t.START_TEXT}"
    assert [m["event"] for m in screen.game_msgs()] == ["start", "spin"]
    assert screen.game_msgs("start")[0]["data"]["title"] == "La ruleta de Sonnia"
    # Una jugada mientras gira reconduce, sin la marca del guion.
    result = await registry.execute("ruleta_answer", {"respuesta": "B"}, ctx)
    assert result.text == t.SPINNING_WAIT
    await manager.on_game_event(_wheel_stopped(screen))
    await settle()
    challenge = screen.game_msgs("challenge")[-1]["data"]
    assert engine.spoken and engine.spoken[-1].startswith("RULETA: ha caído en")
    if challenge["kind"] == "trivia":
        result = await registry.execute("ruleta_answer", {"respuesta": "B"}, ctx)
        assert "es CORRECTA" in result.text
    else:
        result = await registry.execute("ruleta_answer", {"respuesta": "acierto"}, ctx)
        assert "ACIERTO" in result.text
    assert result.text.startswith(SCRIPT_PREFIX)
    assert screen.game_msgs("result")[-1]["data"]["outcome"] == "win"
    result = await registry.execute("ruleta_spin", {}, ctx)
    assert result.text == f"{SCRIPT_PREFIX} {t.SPIN_TEXT}"
    spins = screen.game_msgs("spin")
    assert len(spins) == 2 and spins[1]["data"]["segment"] != spins[0]["data"]["segment"]
    result = await registry.execute("stop_game", {}, ctx)
    assert "terminado" in result.text
    assert screen.game_msgs("end")[-1]["data"]["result"] == "cancel"
    assert not manager.active and screen.replay() == []
    assert "vuelve a conversar con normalidad" in engine.instructions[-1]
    seqs = [m["seq"] for m in screen.game_msgs()]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    # Sin partida, las jugadas no llegan al juego.
    result = await registry.execute("ruleta_spin", {}, ctx)
    assert "No hay ninguna partida" in result.text


async def test_la_reconexion_repite_el_estado_completo() -> None:
    manager, _, screen, _, registry, ctx = await _manager()
    await registry.execute("start_game", {"juego": "ruleta"}, ctx)
    assert [m["event"] for m in screen.replay()] == ["start", "spin"]
    await manager.on_game_event(_wheel_stopped(screen))
    await settle()
    replay = screen.replay()
    assert [m["event"] for m in replay] == ["start", "challenge"]
    assert replay[1]["data"]["options"] == list(QUESTION.options)
    await registry.execute("ruleta_answer", {"respuesta": "C"}, ctx)
    assert [m["event"] for m in screen.replay()] == ["start", "result"]


async def test_sin_unity_la_ruleta_sigue_y_el_abandono_la_cancela() -> None:
    manager, engine, screen, clock, registry, ctx = await _manager()
    await registry.execute("start_game", {"juego": "ruleta"}, ctx)
    clock.advance(SPIN_SECONDS + SPIN_GRACE_S)
    await manager.tick(clock())
    await settle()
    assert screen.game_msgs("challenge"), "la ruleta para sola si Unity no contesta"
    clock.advance(61.0)
    await manager.tick(clock())
    await settle()
    assert not manager.active
    assert screen.game_msgs("end")[-1]["data"]["result"] == "cancel"


async def test_la_sesion_perdida_cancela_la_partida() -> None:
    manager, _, screen, _, registry, ctx = await _manager()
    await registry.execute("start_game", {"juego": "ruleta"}, ctx)
    await manager.on_session_lost()
    assert not manager.active and screen.game_msgs("end")[-1]["data"]["result"] == "cancel"


async def test_la_ruleta_no_empieza_con_la_trivia_en_marcha() -> None:
    manager, engine, screen, clock = await make_manager(
        [RuletaGame], settings=ruleta_settings(), busy=lambda: "Hay una trivia en marcha."
    )
    ok, message = await manager.start("ruleta", "voice")
    assert not ok and "trivia" in message and not screen.game_msgs()
