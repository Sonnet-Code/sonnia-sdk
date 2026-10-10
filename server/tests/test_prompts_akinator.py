"""Akinator dev: los textos que se mandan a GPT-Live, idénticos a los de antes con los de la app.

La instantánea (``snapshots/prompts_akinator.json``) se sacó con el código de antes de hacer
editables los prompts (``sonia.prompts``). Con una versión de la nube se usa esa y no la de la
app. Sin red ni APIs: el juego suelto con ``FakeGameHost``.
"""

from __future__ import annotations

from typing import Any

from sonia.config import Settings
from sonia.games import INSTRUCT_MAX_CHARS, NOT_SAID, GameError
from sonia.games.akinator import AkinatorGame
from sonia.games.akinator.bank import Theme
from sonia.games.akinator.game import GUESS_REMIND_S
from sonia.games.akinator.prompts import RULES_MARGIN, build_rules, prompt_specs
from sonia.prompts import BOOK
from tests.games.fakes import FakeGameHost, game_settings, make_game
from tests.games.test_akinator import SMALL_BANK, ask, questions, say, visitor_speaks
from tests.prompt_snapshots import assert_snapshot, cloud_prompts


def with_akinator(**update: Any) -> Settings:
    settings = game_settings()
    return settings.model_copy(
        update={
            "games": settings.games.model_copy(
                update={"akinator": settings.games.akinator.model_copy(update=update)}
            )
        }
    )


def without_contact() -> Settings:
    settings = game_settings()
    return settings.model_copy(
        update={"trivia": settings.trivia.model_copy(update={"win_contact": ""})}
    )


async def error_of(call: Any) -> str:
    """El mensaje del ``GameError`` (lo que lee GPT-Live como resultado)."""
    try:
        await call
    except GameError as exc:
        return str(exc)
    raise AssertionError("tenía que dar GameError")


def live_texts(host: FakeGameHost) -> dict[str, list[str]]:
    return {"instructions": list(host.instructions), "spoken": list(host.spoken)}


async def started(**kwargs: Any) -> tuple[AkinatorGame, FakeGameHost, str]:
    game, host = make_game(AkinatorGame, **kwargs)
    script = await game.start("voice", {})
    return game, host, script


async def collect() -> dict[str, Any]:
    """Todo lo que lee GPT-Live en casos representativos, con su nombre."""
    out: dict[str, Any] = {}

    # Arranque con el banco de la app, reanudar y empujones de la espera.
    game, host, script = await started()
    out["arranque.guion"] = script
    out["arranque.empujon_esperando"] = game.nudge()
    out["arranque.reanudar"] = await game.resume()
    visitor_speaks(game, host)
    out["arranque.empujon_sin_preguntar"] = game.nudge()
    out["arranque.adivina_pronto"] = await error_of(game.guess({"respuesta": "Kotlin"}))
    out["arranque.adivina_sin_respuesta"] = await error_of(game.guess({"respuesta": NOT_SAID}))
    out["arranque.resultado_sin_respuesta"] = await game.result(
        {"acierto": "no", "respuesta_real": NOT_SAID}
    )
    out["arranque.acierto_sin_nada"] = await error_of(
        game.result({"acierto": "si", "respuesta_real": NOT_SAID})
    )
    await ask(game, *questions(7))
    say_long = 3.0
    game.on_user_turn_end(host.now() + say_long, host.now())
    out["preguntando.empujon_turno_largo"] = game.nudge()
    out["preguntando.reanudar"] = await game.resume()
    out["adivina.guion"] = await game.guess({"respuesta": "Kotlin"})
    out["adivina.otra_vez"] = await game.guess({"respuesta": " kotlin "})
    out["adivina.empujon"] = game.nudge()
    out["adivina.reanudar"] = await game.resume()
    out["adivina.no_quedo_claro"] = await game.result(
        {"acierto": NOT_SAID, "respuesta_real": NOT_SAID}
    )
    # El recordatorio: el visitante habló y pasa el tiempo sin resultado.
    game.on_user_text(host.now())
    host.clock.advance(GUESS_REMIND_S + 1)
    await game.tick(host.now())
    await host.run_tasks()
    out["fallo.guion"] = await game.result({"acierto": "no", "respuesta_real": NOT_SAID})
    out["fallo.repetida"] = await error_of(game.guess({"respuesta": "kotlin"}))
    await game.guess({"respuesta": "Swift"})
    out["acierto.guion"] = await game.result({"acierto": "si", "respuesta_real": "Swift"})
    out["acierto.ya_termino"] = await error_of(game.guess({"respuesta": "Go"}))
    out["acierto.textos"] = live_texts(host)

    # Pierde y lo dice: con contacto y sin él.
    game, host, _ = await started()
    visitor_speaks(game, host)
    await ask(game, *questions(12))
    await game.guess({"respuesta": "Java"})
    out["pierde.con_contacto"] = await game.result({"acierto": "no", "respuesta_real": "Rust"})
    game, host, _ = await started(settings=without_contact())
    visitor_speaks(game, host)
    await ask(game, *questions(6))
    out["pierde.sin_contacto"] = await game.result({"acierto": "no", "respuesta_real": "Rust"})

    # Sin preguntas: avisos silenciosos, empujón del tope y se rinde.
    game, host, _ = await started()
    visitor_speaks(game, host)
    await ask(game, *questions(20))
    await host.run_tasks()
    out["tope.empujon"] = game.nudge()
    await game.guess({"respuesta": "Java"})
    out["tope.se_rinde"] = await game.result({"acierto": "no", "respuesta_real": NOT_SAID})
    out["tope.empujon_rendido"] = game.nudge()
    out["tope.se_rinde_sin_respuesta"] = await game.result(
        {"acierto": "no", "respuesta_real": NOT_SAID}
    )
    out["tope.dice_que_era"] = await game.result({"acierto": "no", "respuesta_real": "Haskell"})
    out["tope.textos"] = live_texts(host)

    # Se rinde por voz («¿qué era?»).
    game, host, _ = await started()
    visitor_speaks(game, host)
    await ask(game, *questions(8))
    await say(game, "¡Me rindo! ¿Qué era?")
    out["rendido.empujon"] = game.nudge()

    # Tres fallos.
    game, host, _ = await started()
    visitor_speaks(game, host)
    await ask(game, *questions(6))
    fails: list[str] = []
    for guess in ("Java", "Swift", "Go"):
        await game.guess({"respuesta": guess})
        fails.append(await game.result({"acierto": "no", "respuesta_real": NOT_SAID}))
    out["tres_fallos"] = fails

    # Banco pequeño y otro máximo y mínimo (otras cifras en las reglas).
    game, host, script = await started(
        settings=with_akinator(max_questions=12, min_questions=3),
        cloud_banks={"akinator_temas": SMALL_BANK},
    )
    out["pequeno.guion"] = script
    visitor_speaks(game, host)
    await ask(game, *questions(12))
    await host.run_tasks()
    out["pequeno.textos"] = live_texts(host)

    # Control a mano desde el panel.
    game, host, _ = await started()
    out["panel.ya_lo_penso"] = await game.panel_control("ready", "")
    await ask(game, *questions(6))
    out["panel.respuestas"] = [
        await game.panel_control(control, "") for control in ("yes", "no", "dont_know")
    ]
    await game.guess({"respuesta": "Kotlin"})
    out["panel.fallo"] = await game.panel_control("wrong", "")
    await game.guess({"respuesta": "Java"})
    out["panel.acierto"] = await game.panel_control("right", "")
    game, host, _ = await started()
    visitor_speaks(game, host)
    await ask(game, *questions(20))
    await say(game, "¡Me rindo! ¿Qué era?")
    out["panel.dice_que_era"] = await game.panel_control("answer", "Rust")

    # Las reglas montadas con temas largos (el presupuesto de los temas).
    themes = list(game._themes)
    out["reglas.muchos_temas"] = build_rules(20, 5, themes * 6)
    return out


async def test_los_textos_del_akinator_no_cambian() -> None:
    assert_snapshot("prompts_akinator", await collect())


def test_las_piezas_de_la_app_validan_y_estan_registradas() -> None:
    specs = prompt_specs()
    assert specs and len({spec.id for spec in specs}) == len(specs)
    for spec in specs:
        assert spec.id.startswith("juegos/akinator/") and spec.group == "Juego: Akinator"
        assert spec.id in BOOK and BOOK.source(spec.id) == "app"
        assert BOOK.validate(spec.id, BOOK.default(spec.id)) == [], spec.id
    assert BOOK.spec("juegos/akinator/reglas").max_len == INSTRUCT_MAX_CHARS


async def test_con_la_version_de_la_nube_se_usa_solo_esa() -> None:
    cloud = {
        "juegos/akinator/reglas": "JUEGO DE ADIVINAR: {max} preguntas, desde la {min}. Temas: {themes}.",
        "juegos/akinator/acierto": "Ganaste con «{answer}» en {asked}.",
        "juegos/akinator/empujon_adivina": "AKINATOR: delega el resultado.",
    }
    with cloud_prompts(cloud):
        game, host, _ = await started()
        visitor_speaks(game, host)
        await ask(game, *questions(6))
        await game.guess({"respuesta": "Kotlin"})
        nudge = game.nudge()
        script = await game.result({"acierto": "si", "respuesta_real": "Kotlin"})
    (rules,) = host.instructions
    assert rules.startswith("JUEGO DE ADIVINAR: 20 preguntas, desde la 5. Temas: Lenguajes")
    assert "AKINATOR EN MARCHA" not in rules
    assert nudge == "AKINATOR: delega el resultado."
    assert script == "Ganaste con «Kotlin» en 6."
    # Fuera del ``with`` vuelve la de la app.
    assert BOOK.source("juegos/akinator/reglas") == "app"


def test_los_temas_caben_en_lo_que_dejan_las_reglas_de_la_nube() -> None:
    themes = [Theme(f"Tema {n}", ("Uno", "Dos", "Tres")) for n in range(40)]
    long_rules = "R" * 900 + " {max} {min} Temas: {themes}"
    with cloud_prompts({"juegos/akinator/reglas": long_rules}):
        text = build_rules(20, 5, themes)
    assert text.startswith("R" * 900) and "Tema 0" in text
    assert len(text) <= INSTRUCT_MAX_CHARS - RULES_MARGIN
