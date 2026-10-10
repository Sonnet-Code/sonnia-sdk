"""Akinator dev: el juego suelto (con ``FakeGameHost``) y de punta a punta (con ``GameManager``).

Nada llama a APIs reales ni usa la cámara. El contador de preguntas con transcripciones
parciales y finales está en ``test_akinator_preguntas.py``.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any

import pytest

from sonia.actions import build_default_registry
from sonia.config import Settings
from sonia.games import INSTRUCT_MAX_CHARS, NOT_SAID, SCRIPT_PREFIX, GameError
from sonia.games.akinator import AkinatorGame
from sonia.games.akinator.bank import (
    THEMES,
    Theme,
    parse_themes,
    safe_for_live,
    themes_for_live,
)
from sonia.games.akinator.game import MAX_GUESSES, READY_GRACE_S, clean_answer, screen_state
from sonia.games.akinator.prompts import build_rules, build_start_script
from sonia.live.engine import clean_transcript
from sonia.types import ActionContext
from sonia.ws import protocol as p
from tests.games.fakes import (
    FakeGameHost,
    brands_in,
    check_for_live,
    game_settings,
    make_game,
    make_manager,
    settle,
)
from tests.games.test_motor import games_rig
from tests.test_live import _backend_call, pcm, wait_until

BANK_FILE = Path(__file__).resolve().parents[3] / "assets" / "games" / "akinator" / "temas.md"

SMALL_BANK = """\
## Lenguajes
Python, Kotlin, Rust

## Empresas
Google, Meta

## Personajes
Linus Torvalds
"""


def sentence(*deltas: str) -> list[tuple[str, bool]]:
    """Las llamadas que haría el motor para una frase de Sonia que llega en estos trozos."""
    parts: list[str] = []
    calls: list[tuple[str, bool]] = []
    for delta in deltas:
        parts.append(delta)
        calls.append((clean_transcript("".join(parts)), False))
    calls.append((clean_transcript("".join(parts)), True))
    return calls


def deltas(text: str) -> list[str]:
    """Un texto en trozos de palabra, como los suelta el modelo."""
    words = text.split(" ")
    return [words[0], *(f" {word}" for word in words[1:])]


async def start_game(**kwargs: Any) -> tuple[AkinatorGame, FakeGameHost]:
    game, host = make_game(AkinatorGame, **kwargs)
    await game.start("voice", {})
    return game, host


async def say(game: AkinatorGame, text: str) -> None:
    """Sonia dice una frase trozo a trozo, como llega del motor."""
    for chunk, final in sentence(*deltas(text)):
        await game.on_assistant_text(chunk, final)


def visitor_speaks(game: AkinatorGame, host: FakeGameHost) -> None:
    """El visitante dice «listo»: pasa el margen de arranque y llega su transcripción."""
    host.clock.advance(READY_GRACE_S + 1)
    game.on_user_text(host.now())


async def ask(game: AkinatorGame, *questions: str) -> None:
    for question in questions:
        await say(game, f"Vale. {question}")


def questions(count: int) -> list[str]:
    return [f"¿Es la cosa número {n} de la lista?" for n in range(1, count + 1)]


def last_state(host: FakeGameHost) -> dict[str, Any]:
    return dict(host.sent[-1]["data"])


# ---------------------------------------------------------------------------
# Banco de temas
# ---------------------------------------------------------------------------


def test_el_banco_de_la_app_esta_bien_formado_y_es_un_borrador() -> None:
    text = BANK_FILE.read_text(encoding="utf-8")
    assert "pendiente de revisión de Jean" in text
    parsed = parse_themes(text)
    assert parsed.warnings == []
    assert len(parsed.entries) >= 6
    for theme in parsed.entries:
        assert len(theme.name) <= 30, "el nombre sale en la pantalla vertical"
        assert len(theme.examples) >= 3
        assert len(set(theme.examples)) == len(theme.examples)
    names = [t.name for t in parsed.entries]
    assert {
        "Lenguajes de programación",
        "Productos de Google",
        "Personajes de la informática",
    } <= set(names)


def test_el_banco_declarado_tiene_formato_id_y_minimo() -> None:
    assert AkinatorGame.banks() == [THEMES]
    assert THEMES.id == "akinator_temas" and THEMES.file == "temas.md"
    assert THEMES.min_entries == 3
    assert (BANK_FILE.parent / THEMES.file) == BANK_FILE


def test_el_banco_acepta_comas_puntos_y_comas_y_listas() -> None:
    parsed = parse_themes(
        """\
## Lenguajes
Python, Kotlin; Rust
- Go
* Swift
• Dart

## Solo nombre
"""
    )
    assert parsed.warnings == []
    assert parsed.entries[0] == Theme(
        "Lenguajes", ("Python", "Kotlin", "Rust", "Go", "Swift", "Dart")
    )
    assert parsed.entries[1] == Theme("Solo nombre", ())


def test_el_banco_salta_lo_mal_formado_con_avisos() -> None:
    long_name = "T" * 80
    long_example = "x" * 60
    parsed = parse_themes(
        f"""\
##
Python

## {long_name}
Python

## Bueno
Python, Java, {long_example}

## bueno
Otra vez

## ¿?
nada
"""
    )
    assert [t.name for t in parsed.entries] == ["Bueno"]
    assert parsed.entries[0].examples == ("Python", "Java")
    assert len(parsed.warnings) == 5
    assert any("repetido" in w for w in parsed.warnings)
    assert any("se saltan" in w for w in parsed.warnings)


def test_el_banco_ignora_el_comentario_con_el_formato() -> None:
    parsed = parse_themes("<!-- ## Falso\nPython -->\n## Real\nGo\n")
    assert [t.name for t in parsed.entries] == ["Real"]


def test_un_banco_vacio_o_sin_encabezados_no_da_temas_ni_lanza() -> None:
    assert parse_themes("").entries == []
    assert parse_themes("Python, Kotlin, Rust").entries == []


async def test_el_panel_valida_el_banco_con_su_minimo_y_su_tope() -> None:
    manager, *_ = await make_manager([AkinatorGame])
    ok, message = manager.validate_bank("akinator_temas", SMALL_BANK)
    assert ok and "3 entradas válidas" in message
    ok, message = manager.validate_bank("akinator_temas", "## Solo uno\nPython\n")
    assert not ok and "solo hay 1" in message and "hacen falta 3" in message
    ok, _ = manager.validate_bank("akinator_temas", SMALL_BANK + "x" * 15_000)
    assert not ok
    ok, message = manager.validate_bank("akinator_temas", "")
    assert ok and "vuelve el de la app" in message
    # El texto de la app se carga tal cual para editarlo.
    assert "TEMAS DEL AKINATOR DEV" in manager.bank_text("akinator_temas")


async def test_un_banco_de_la_nube_con_pocos_temas_no_vale_y_sigue_el_de_la_app() -> None:
    game, host = make_game(AkinatorGame, cloud_banks={THEMES.id: "## Solo uno\nPython\n"})
    await game.start("voice", {})
    assert len(host.events("start")[0]["themes"]) >= 6


async def test_un_banco_de_la_nube_valido_manda_sobre_el_de_la_app() -> None:
    game, host = make_game(AkinatorGame, cloud_banks={THEMES.id: SMALL_BANK})
    await game.start("voice", {})
    assert host.events("start")[0]["themes"] == ["Lenguajes", "Empresas", "Personajes"]
    assert "Python, Kotlin" in host.instructions[0]


async def test_sin_ningun_tema_no_se_puede_jugar(tmp_path: Path) -> None:
    (tmp_path / "games" / "akinator").mkdir(parents=True)
    (tmp_path / "games" / "akinator" / "temas.md").write_text("# Sin temas\n", encoding="utf-8")
    settings = Settings(_env_file=None, assets_dir=str(tmp_path))  # type: ignore[call-arg]
    game, host = make_game(AkinatorGame, settings=settings)
    with pytest.raises(GameError, match="banco de temas"):
        await game.start("voice", {})
    assert host.sent == [] and host.instructions == []


# ---------------------------------------------------------------------------
# Las reglas para GPT-Live
# ---------------------------------------------------------------------------


def app_themes() -> list[Theme]:
    return parse_themes(BANK_FILE.read_text(encoding="utf-8")).entries


def test_las_reglas_dicen_lo_que_hay_que_decir_y_caben() -> None:
    rules = build_rules(20, 5, app_themes())
    assert len(rules) <= INSTRUCT_MAX_CHARS
    for needle in (
        "sí o no",
        "sin delegar",
        "«no sé»",
        "«a veces»",
        "No repitas preguntas",
        "pregunta 5",
        "akinator: adivina",
        "akinator: resultado",
        "20",
        "ríndete",
        "nunca digas que acertaste o fallaste sin delegarlo",
        "Lenguajes de programación",
        "Productos de Google",
    ):
        assert needle in rules, needle
    check_for_live(rules, limit=INSTRUCT_MAX_CHARS)


def test_las_reglas_con_un_banco_enorme_siguen_cabiendo() -> None:
    huge = [
        Theme(f"Tema número {n} con un nombre largo", ("uno", "dos", "tres")) for n in range(80)
    ]
    rules = build_rules(20, 5, huge)
    assert len(rules) <= INSTRUCT_MAX_CHARS
    assert "Tema número 0 con un nombre largo" in rules


def test_los_temas_ceden_ejemplos_antes_que_nombres() -> None:
    themes = [
        Theme("Lenguajes", ("Python", "Kotlin", "Rust", "Go")),
        Theme("Empresas", ("Google",)),
    ]
    assert themes_for_live(themes, 500) == "Lenguajes (Python, Kotlin, Rust); Empresas (Google)"
    assert themes_for_live(themes, 40) == "Lenguajes (Python); Empresas (Google)"
    assert themes_for_live(themes, 20) == "Lenguajes; Empresas"
    assert themes_for_live(themes, 5) == "Lenguajes"


def test_lo_que_sonia_no_puede_conocer_no_llega_a_las_reglas() -> None:
    themes = [
        Theme("Motores", ("Unity", "Unreal", "Godot", "Gemini")),
        Theme("OpenAI y compañía", ("x",)),
        Theme("Herramientas", ("Git", "GPT-4", "Windows", "Docker")),
    ]
    rules = build_rules(20, 5, themes)
    assert not brands_in(rules)
    assert "Unreal" in rules and "Godot" in rules and "Git" in rules and "Docker" in rules
    assert "OpenAI" not in rules
    assert not safe_for_live("Unity") and safe_for_live("ChatGPT") and safe_for_live("Linux")


def test_el_guion_de_arranque_nombra_los_temas_y_manda_esperar() -> None:
    script = build_start_script(app_themes())
    assert "lenguajes de programación" in script
    assert "todavía no hagas ninguna pregunta" in script
    assert "?" not in script, "la apertura no lleva preguntas: no se cuentan como la primera"
    check_for_live(script)


# ---------------------------------------------------------------------------
# Empezar
# ---------------------------------------------------------------------------


async def test_empieza_con_la_tarjeta_los_temas_y_las_reglas() -> None:
    game, host = make_game(AkinatorGame)
    script = await game.start("voice", {})
    assert [m["event"] for m in host.sent] == ["start", "waiting"]
    assert host.sent[0]["data"]["max"] == 20
    assert len(host.sent[0]["data"]["themes"]) >= 6
    assert all(m["sticky"] for m in host.sent)
    state = last_state(host)
    assert state["phase"] == "waiting" and state["asked"] == 0 and state["max"] == 20
    assert len(host.instructions) == 1 and len(host.instructions[0]) <= INSTRUCT_MAX_CHARS
    assert host.spoken == [] and host.fixed == [], "el arranque lo dice ella con el guion"
    check_for_live(script)
    assert game.unavailable_reason() is None
    assert game.phrases() == []


async def test_empezar_de_nuevo_reinicia_todo() -> None:
    game, host = await start_game()
    visitor_speaks(game, host)
    await ask(game, *questions(6))
    await game.guess({"respuesta": "Kotlin"})
    await game.result({"acierto": "no", "respuesta_real": NOT_SAID})
    await game.start("voice", {})
    assert game.snapshot() == {
        "summary": "Esperando a que piense en algo",
        "phase": "waiting",
        "asked": 0,
        "max": 20,
        "question": "",
        "guess": "",
        "missed": [],
        "ready": False,
    }


async def test_respeta_el_maximo_y_el_minimo_de_los_ajustes() -> None:
    settings = game_settings()
    settings = settings.model_copy(
        update={
            "games": settings.games.model_copy(
                update={
                    "akinator": settings.games.akinator.model_copy(
                        update={"max_questions": 12, "min_questions": 3}
                    )
                }
            )
        }
    )
    game, host = await start_game(settings=settings)
    assert last_state(host)["max"] == 12
    assert "(12 como mucho)" in host.instructions[0] and "pregunta 3" in host.instructions[0]


# ---------------------------------------------------------------------------
# El contador sobre el juego
# ---------------------------------------------------------------------------


async def test_no_cuenta_nada_hasta_que_el_visitante_avisa() -> None:
    game, host = await start_game()
    await say(game, "¡Vamos! Piensa en algo y avísame. ¿Listo para jugar?")
    await ask(game, "¿Es un lenguaje de programación?")
    assert [m["event"] for m in host.sent] == ["start", "waiting"]
    # Su transcripción llega demasiado pronto: es la petición de jugar, no el aviso.
    game.on_user_text(host.now() + READY_GRACE_S / 2)
    await ask(game, "¿Es un lenguaje de programación?")
    assert [m["event"] for m in host.sent] == ["start", "waiting"]
    visitor_speaks(game, host)
    await say(game, "¡Primera! ¿Es un lenguaje de programación?")
    assert host.sent[-1]["event"] == "question"
    assert last_state(host)["asked"] == 1
    assert last_state(host)["phase"] == "asking"
    assert last_state(host)["question"] == "¿Es un lenguaje de programación?"


async def test_cada_pregunta_sube_el_contador_y_las_parciales_no() -> None:
    game, host = await start_game()
    visitor_speaks(game, host)
    for chunk, final in sentence(*deltas("Mmm, vale. ¿Se usa para hacer apps móviles?")):
        await game.on_assistant_text(chunk, final)
    asks = host.events("question")
    assert [s["asked"] for s in asks] == [1]
    await say(game, "¡Ajá! ¿Lo creó Google?")
    await say(game, "¿Lo creó Google?")
    assert [s["asked"] for s in host.events("question")] == [1, 2]
    assert game.snapshot()["asked"] == 2
    assert all(m["sticky"] for m in host.sent)


async def test_la_cuenta_se_para_en_el_maximo_y_avisa_en_silencio() -> None:
    game, host = await start_game()
    visitor_speaks(game, host)
    await ask(game, *questions(14))
    assert host.instructions[1:] == [], "todavía no hay avisos"
    await ask(game, questions(15)[-1])
    await ask(game, *questions(23)[15:])
    await host.run_tasks()
    assert last_state(host)["asked"] == 20
    assert game.snapshot()["asked"] == 20
    few = [i for i in host.instructions if "llevas 15 de 20" in i]
    last = [i for i in host.instructions if "la pregunta que acabas de hacer es la 20" in i]
    assert len(few) == 1 and len(last) == 1
    assert game.nudge() is not None and "20 preguntas" in game.nudge()  # type: ignore[operator]
    for text in host.instructions:
        check_for_live(text, limit=INSTRUCT_MAX_CHARS)


async def test_no_avisa_de_que_quedan_pocas_si_el_maximo_es_pequeno() -> None:
    settings = game_settings()
    settings = settings.model_copy(
        update={
            "games": settings.games.model_copy(
                update={"akinator": settings.games.akinator.model_copy(update={"max_questions": 8})}
            )
        }
    )
    game, host = await start_game(settings=settings)
    visitor_speaks(game, host)
    await ask(game, *questions(8))
    await host.run_tasks()
    assert [i for i in host.instructions if "llevas" in i] == []
    assert len([i for i in host.instructions if "la última" in i]) == 1


async def test_rendirse_cambia_la_pantalla_y_no_cuenta_como_pregunta() -> None:
    game, host = await start_game()
    visitor_speaks(game, host)
    await ask(game, *questions(6))
    await say(game, "¡Me rindo! ¿Qué era?")
    assert host.sent[-1]["event"] == "giveup"
    assert last_state(host)["phase"] == "giving_up"
    assert last_state(host)["asked"] == 6
    # Ya no cuenta más preguntas.
    await ask(game, "¿Es otra cosa más?")
    assert host.sent[-1]["event"] == "giveup"


# ---------------------------------------------------------------------------
# La respuesta que arriesga Sonia
# ---------------------------------------------------------------------------


async def test_arriesga_una_respuesta_y_sale_la_tarjeta() -> None:
    game, host = await start_game()
    visitor_speaks(game, host)
    await ask(game, *questions(6))
    script = await game.guess({"respuesta": "  «Kotlin»  "})
    assert "«Kotlin»" in script and "akinator: resultado" in script
    check_for_live(script)
    assert host.sent[-1]["event"] == "guess"
    state = last_state(host)
    assert state["phase"] == "guessing" and state["guess"] == "Kotlin" and state["asked"] == 6
    assert game.nudge() is not None and "pantalla" in game.nudge()  # type: ignore[operator]


async def test_no_deja_adivinar_antes_del_minimo_aunque_insista() -> None:
    game, host = await start_game()
    minimum = host.settings.games.akinator.min_questions
    visitor_speaks(game, host)
    await ask(game, *questions(2))
    for _ in range(2):
        with pytest.raises(GameError, match="pronto"):
            await game.guess({"respuesta": "Kotlin"})
    assert host.sent[-1]["event"] == "question", "no se pinta nada"
    # Con las preguntas que faltan hasta el mínimo, ya puede.
    await ask(game, *questions(minimum)[2:])
    await game.guess({"respuesta": "Kotlin"})
    assert host.sent[-1]["event"] == "guess"


async def test_si_el_contador_se_queda_corto_valen_las_respuestas_del_visitante() -> None:
    """No todas las preguntas de Sonia se cuentan (una transcripción sin «?»): si el
    visitante ya contestó al menos el mínimo de veces, se deja arriesgar."""
    game, host = await start_game()
    minimum = host.settings.games.akinator.min_questions
    visitor_speaks(game, host)
    game.on_user_turn_end(host.now(), host.now())  # el «ya lo tengo» no es una respuesta
    await ask(game, *questions(1))
    for _ in range(minimum - 1):
        host.clock.advance(5)
        game.on_user_turn_end(host.now(), host.now())
    with pytest.raises(GameError, match="pronto"):
        await game.guess({"respuesta": "Kotlin"})
    host.clock.advance(5)
    game.on_user_turn_end(host.now(), host.now())
    await game.guess({"respuesta": "Kotlin"})
    assert host.sent[-1]["event"] == "guess"


async def test_adivinar_sin_respuesta_o_sin_decirla_no_vale() -> None:
    game, _ = await start_game()
    for value in ("", "   ", NOT_SAID, "no_lo_sabe", None, 5):
        with pytest.raises(GameError, match="qué quieres adivinar"):
            await game.guess({"respuesta": value})


async def test_no_repite_una_respuesta_que_ya_fallo() -> None:
    game, host = await start_game()
    visitor_speaks(game, host)
    await ask(game, *questions(6))
    await game.guess({"respuesta": "Kotlin"})
    await game.result({"acierto": "no", "respuesta_real": NOT_SAID})
    with pytest.raises(GameError, match="no era"):
        await game.guess({"respuesta": "kotlin"})


async def test_delegar_dos_veces_la_misma_respuesta_no_la_cuenta_como_fallo() -> None:
    game, host = await start_game()
    visitor_speaks(game, host)
    await ask(game, *questions(6))
    first = await game.guess({"respuesta": "Kotlin"})
    sent = len(host.sent)
    again = await game.guess({"respuesta": " kotlin "})
    assert again == first and len(host.sent) == sent
    assert last_state(host)["missed"] == [] and last_state(host)["guess"] == "Kotlin"


async def test_arriesgar_otra_sin_resolver_la_anterior_cuenta_la_anterior_como_fallo() -> None:
    game, host = await start_game()
    visitor_speaks(game, host)
    await ask(game, *questions(6))
    await game.guess({"respuesta": "Kotlin"})
    await game.guess({"respuesta": "Swift"})
    assert last_state(host)["guess"] == "Swift"
    assert last_state(host)["missed"] == ["Kotlin"]


# ---------------------------------------------------------------------------
# El veredicto
# ---------------------------------------------------------------------------


async def test_acierta_confeti_y_sonia_presume() -> None:
    game, host = await start_game()
    visitor_speaks(game, host)
    await ask(game, *questions(9))
    await game.guess({"respuesta": "Kotlin"})
    script = await game.result({"acierto": "si", "respuesta_real": "Kotlin"})
    assert "Acertaste" in script and "9 preguntas" in script and "presumiendo" in script
    check_for_live(script)
    assert host.sent[-1]["event"] == "reveal"
    reveal = last_state(host)
    assert reveal["phase"] == "revealed" and reveal["outcome"] == "sonnia"
    assert reveal["answer"] == "Kotlin" and reveal["asked"] == 9
    assert host.finished == [
        ("win", {"outcome": "sonnia", "answer": "Kotlin", "asked": 9, "tries": 1})
    ]
    assert game.nudge() is None


async def test_el_acierto_usa_la_respuesta_arriesgada_aunque_llegue_otra() -> None:
    game, host = await start_game()
    visitor_speaks(game, host)
    await ask(game, *questions(7))
    await game.guess({"respuesta": "Kotlin"})
    await game.result({"acierto": "si", "respuesta_real": "el lenguaje de Android"})
    assert last_state(host)["answer"] == "Kotlin"


async def test_un_acierto_sin_decir_que_era_ni_haber_arriesgado_pide_la_respuesta() -> None:
    game, host = await start_game()
    visitor_speaks(game, host)
    with pytest.raises(GameError, match="respuesta_real"):
        await game.result({"acierto": "si", "respuesta_real": NOT_SAID})
    assert host.finished == []


async def test_acierto_sin_arriesgar_pero_diciendo_que_era_vale() -> None:
    # Hizo la pregunta «¿Es Kotlin?» como una más y el visitante dijo que sí.
    game, host = await start_game()
    visitor_speaks(game, host)
    await ask(game, *questions(8))
    await game.result({"acierto": "si", "respuesta_real": "Kotlin"})
    assert host.finished[0][0] == "win" and last_state(host)["answer"] == "Kotlin"


async def test_falla_y_le_quedan_preguntas_sigue_preguntando() -> None:
    game, host = await start_game()
    visitor_speaks(game, host)
    await ask(game, *questions(8))
    await game.guess({"respuesta": "Java"})
    script = await game.result({"acierto": "no", "respuesta_real": NOT_SAID})
    assert "«Java» no era" in script and "Te quedan 12 preguntas" in script
    check_for_live(script)
    assert host.sent[-1]["event"] == "miss"
    state = last_state(host)
    assert state["phase"] == "asking" and state["missed"] == ["Java"] and state["guess"] == ""
    assert host.finished == []
    # Sigue preguntando: la cuenta continúa donde iba.
    await say(game, "¿Y se usa en servidores?")
    assert last_state(host)["asked"] == 9
    assert game.nudge() is None


async def test_falla_y_dice_que_era_ganó_el_visitante() -> None:
    game, host = await start_game()
    visitor_speaks(game, host)
    await ask(game, *questions(12))
    await game.guess({"respuesta": "Java"})
    script = await game.result({"acierto": "no", "respuesta_real": "Rust"})
    assert "¡me ganaste!" in script and "«Rust»" in script
    assert "Brian o Mariel" in script and "no prometas ninguno" in script
    check_for_live(script)
    assert host.sent[-1]["event"] == "reveal"
    assert last_state(host)["outcome"] == "visitor" and last_state(host)["answer"] == "Rust"
    assert last_state(host)["missed"] == ["Java"]
    assert host.finished == [
        ("lose", {"outcome": "visitor", "answer": "Rust", "asked": 12, "tries": 1})
    ]


async def test_sin_equipo_de_contacto_no_manda_a_nadie() -> None:
    settings = game_settings()
    settings = settings.model_copy(
        update={"trivia": settings.trivia.model_copy(update={"win_contact": ""})}
    )
    game, host = await start_game(settings=settings)
    visitor_speaks(game, host)
    await ask(game, *questions(6))
    script = await game.result({"acierto": "no", "respuesta_real": "Rust"})
    assert "Brian" not in script and "hablar con" not in script


async def test_sin_preguntas_se_rinde_y_pregunta_que_era() -> None:
    game, host = await start_game()
    visitor_speaks(game, host)
    await ask(game, *questions(20))
    await game.guess({"respuesta": "Java"})
    script = await game.result({"acierto": "no", "respuesta_real": NOT_SAID})
    assert "ya no puedes arriesgar más" in script and "pregúntale qué era" in script
    assert host.sent[-1]["event"] == "giveup"
    assert last_state(host)["phase"] == "giving_up"
    assert game.nudge() is not None and "te has rendido" in game.nudge()  # type: ignore[operator]
    # El visitante dice qué era.
    script = await game.result({"acierto": "no", "respuesta_real": "Haskell"})
    assert "Haskell" in script
    assert host.finished[0][0] == "lose" and last_state(host)["answer"] == "Haskell"


async def test_tras_tres_fallos_se_rinde_aunque_queden_preguntas() -> None:
    game, host = await start_game()
    visitor_speaks(game, host)
    await ask(game, *questions(6))
    for n, guess in enumerate(["Java", "Swift", "Go"], start=1):
        await game.guess({"respuesta": guess})
        script = await game.result({"acierto": "no", "respuesta_real": NOT_SAID})
        if n < MAX_GUESSES:
            assert host.sent[-1]["event"] == "miss"
    assert host.sent[-1]["event"] == "giveup"
    assert last_state(host)["missed"] == ["Java", "Swift", "Go"]
    assert "pregúntale qué era" in script
    assert last_state(host)["asked"] == 6


async def test_si_el_visitante_cuenta_que_era_tras_rendirse_no_es_un_acierto() -> None:
    game, host = await start_game()
    visitor_speaks(game, host)
    await ask(game, *questions(20))
    await say(game, "¡Me rindo! ¿Qué era?")
    await game.result({"acierto": "si", "respuesta_real": "Haskell"})
    assert host.finished[0][0] == "lose"


async def test_no_quedo_claro_si_acerto_se_lo_pregunta() -> None:
    game, host = await start_game()
    visitor_speaks(game, host)
    await ask(game, *questions(6))
    await game.guess({"respuesta": "Kotlin"})
    script = await game.result({"acierto": NOT_SAID, "respuesta_real": NOT_SAID})
    assert "acerté" in script and host.finished == []
    assert last_state(host)["phase"] == "guessing"


async def test_sin_decir_si_acerto_pero_diciendo_que_era_lo_decide_el_orquestador() -> None:
    game, host = await start_game()
    visitor_speaks(game, host)
    await ask(game, *questions(6))
    await game.guess({"respuesta": "Kotlin"})
    await game.result({"acierto": NOT_SAID, "respuesta_real": "kotlin"})
    assert host.finished[0][0] == "win"

    game, host = await start_game()
    visitor_speaks(game, host)
    await ask(game, *questions(6))
    await game.guess({"respuesta": "Kotlin"})
    await game.result({"acierto": NOT_SAID, "respuesta_real": "Scala"})
    assert host.finished[0][0] == "lose" and last_state(host)["answer"] == "Scala"


async def test_un_no_sin_respuesta_pendiente_es_una_pregunta_normal() -> None:
    game, host = await start_game()
    visitor_speaks(game, host)
    await ask(game, *questions(6))
    before = len(host.sent)
    script = await game.result({"acierto": "no", "respuesta_real": NOT_SAID})
    assert "no se delegan" in script and len(host.sent) == before and host.finished == []
    script = await game.result({"acierto": NOT_SAID, "respuesta_real": NOT_SAID})
    assert "no se delegan" in script


async def test_un_veredicto_con_la_partida_ya_acabada_se_rechaza() -> None:
    game, host = await start_game()
    visitor_speaks(game, host)
    await ask(game, *questions(6))
    await game.result({"acierto": "no", "respuesta_real": "Rust"})
    for call in (
        game.result({"acierto": "si", "respuesta_real": "Rust"}),
        game.guess({"respuesta": "Kotlin"}),
    ):
        with pytest.raises(GameError, match="ya terminó"):
            await call
    assert len(host.finished) == 1


# ---------------------------------------------------------------------------
# Empujones, reanudar y estado
# ---------------------------------------------------------------------------


async def test_los_empujones_dependen_de_la_fase() -> None:
    game, host = await start_game()
    assert game.nudge() is None, "esperando: nada que empujar"
    visitor_speaks(game, host)
    start_nudge = game.nudge()
    assert start_nudge is not None and "primera pregunta" in start_nudge
    check_for_live(start_nudge)
    await ask(game, *questions(1))
    assert game.nudge() is None, "ya preguntó: no hay que empujar"
    await ask(game, *questions(6)[1:])
    assert game.nudge() is None, "preguntando sin delegar es lo normal"
    await game.guess({"respuesta": "Kotlin"})
    guess_nudge = game.nudge()
    assert guess_nudge is not None and "akinator: resultado" in guess_nudge
    check_for_live(guess_nudge)
    await game.result({"acierto": "no", "respuesta_real": NOT_SAID})
    assert game.nudge() is None
    await ask(game, *questions(26)[6:])
    limit = game.nudge()
    assert limit is not None and "ya hiciste tus 20 preguntas" in limit
    check_for_live(limit)


async def test_reanudar_cuenta_donde_iba() -> None:
    game, host = await start_game()
    visitor_speaks(game, host)
    await ask(game, *questions(7))
    script = await game.resume()
    assert "Llevas 7 de 20" in script and "pantalla" not in script
    await game.guess({"respuesta": "Kotlin"})
    script = await game.resume()
    assert "«Kotlin»" in script and "está en la pantalla" in script
    check_for_live(script)


async def test_el_panel_lee_una_linea_de_resumen_en_cada_fase() -> None:
    game, host = await start_game()
    assert game.snapshot()["summary"] == "Esperando a que piense en algo"
    visitor_speaks(game, host)
    await ask(game, *questions(7))
    assert game.snapshot()["summary"] == "Pregunta 7 de 20"
    await game.guess({"respuesta": "Kotlin"})
    assert game.snapshot()["summary"] == "Pregunta 7 de 20 · arriesga: Kotlin"
    await game.result({"acierto": "si", "respuesta_real": "Kotlin"})
    assert game.snapshot()["summary"] == "Acertó: Kotlin"

    game, host = await start_game()
    visitor_speaks(game, host)
    await ask(game, *questions(7))
    await say(game, "¡Me rindo! ¿Qué era?")
    assert game.snapshot()["summary"] == "Se rinde: pregunta qué era"
    await game.result({"acierto": "no", "respuesta_real": "Rust"})
    assert game.snapshot()["summary"] == "Perdió: era Rust"


async def test_el_estado_de_la_pantalla_es_el_mismo_en_el_juego_y_en_la_demo() -> None:
    game, host = await start_game()
    visitor_speaks(game, host)
    await ask(game, *questions(3))
    expected = screen_state(
        phase="asking", asked=3, max_questions=20, question=game.snapshot()["question"]
    )
    assert last_state(host) == expected
    assert set(expected) == {
        "phase",
        "asked",
        "max",
        "question",
        "guess",
        "missed",
        "outcome",
        "answer",
    }


def test_la_pantalla_pone_sonnia_y_recorta_lo_largo() -> None:
    state = screen_state(
        phase="asking",
        asked=40,
        max_questions=20,
        question="¿Es algo que Sonia conoce? " + "x" * 300,
    )
    assert state["asked"] == 20
    assert state["question"].startswith("¿Es algo que Sonnia conoce?")
    assert len(state["question"]) == 120


def test_limpia_las_respuestas_que_llegan_del_backend() -> None:
    assert clean_answer("  «Kotlin».  ") == "Kotlin"
    assert clean_answer("<b>Linus</b> Torvalds") == "Linus Torvalds"
    assert clean_answer("Sonia") == "Sonnia"
    assert clean_answer("no lo dijo") == "" and clean_answer(NOT_SAID) == ""
    assert clean_answer(None) == "" and clean_answer(3) == ""
    assert len(clean_answer("a" * 200)) == 60


# ---------------------------------------------------------------------------
# De punta a punta, con el GameManager y las acciones que delega GPT-Live
# ---------------------------------------------------------------------------


async def manager_rig() -> Any:
    manager, engine, screen, clock = await make_manager([AkinatorGame])
    registry = build_default_registry(include_look=False, games=[AkinatorGame])
    ctx = ActionContext(camera=None, avatar=None, gallery_dir="", extra={"games": manager})
    return manager, engine, screen, clock, registry, ctx


async def feed_sonia(manager: Any, text: str) -> None:
    for chunk, final in sentence(*deltas(text)):
        await manager.on_assistant_text(chunk, final)


async def test_partida_entera_por_voz_con_acierto() -> None:
    manager, engine, screen, clock, registry, ctx = await manager_rig()
    result = await registry.execute("start_game", {"juego": "akinator"}, ctx)
    assert (
        result.text.startswith(SCRIPT_PREFIX) and "todavía no hagas ninguna pregunta" in result.text
    )
    assert manager.active and manager.phase == "playing"
    assert [m["event"] for m in screen.game_msgs()] == ["start", "waiting"]
    first = screen.game_msgs()[0]
    assert first["data"]["title"] == "Akinator dev" and first["data"]["max"] == 20
    assert "AKINATOR EN MARCHA" in engine.instructions[0]

    clock.advance(5)
    manager.on_user_text(clock())
    for n in range(1, 8):
        await feed_sonia(manager, f"Vale. ¿Es la cosa número {n} de la lista?")
    asked = [m["data"]["asked"] for m in screen.game_msgs("question")]
    assert asked == [1, 2, 3, 4, 5, 6, 7]

    result = await registry.execute("akinator_guess", {"respuesta": "Kotlin"}, ctx)
    assert result.text.startswith(SCRIPT_PREFIX) and "«Kotlin»" in result.text
    assert screen.game_msgs()[-1]["event"] == "guess"
    result = await registry.execute(
        "akinator_result", {"acierto": "si", "respuesta_real": "Kotlin"}, ctx
    )
    assert result.text.startswith(SCRIPT_PREFIX) and "Acertaste" in result.text
    assert screen.game_msgs("reveal")[-1]["data"]["outcome"] == "sonnia"

    await settle()
    end = screen.game_msgs("end")[-1]
    assert end["data"] == {
        "outcome": "sonnia",
        "answer": "Kotlin",
        "asked": 7,
        "tries": 1,
        "result": "win",
    }
    assert not manager.active and screen.replay() == []
    assert "vuelve a conversar con normalidad" in engine.instructions[-1]
    seqs = [m["seq"] for m in screen.game_msgs()]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)


async def test_partida_con_fallo_y_seguir_hasta_perder() -> None:
    manager, engine, screen, clock, registry, ctx = await manager_rig()
    await registry.execute("start_game", {"juego": "akinator"}, ctx)
    clock.advance(5)
    manager.on_user_text(clock())
    for n in range(1, 11):
        await feed_sonia(manager, f"¿Es la cosa número {n} de la lista?")
    await registry.execute("akinator_guess", {"respuesta": "Java"}, ctx)
    result = await registry.execute(
        "akinator_result", {"acierto": "no", "respuesta_real": NOT_SAID}, ctx
    )
    assert "Te quedan 10 preguntas" in result.text
    assert screen.game_msgs()[-1]["event"] == "miss" and manager.phase == "playing"
    for n in range(11, 21):
        await feed_sonia(manager, f"¿Es la cosa número {n} de la lista?")
    assert screen.game_msgs("question")[-1]["data"]["asked"] == 20
    await settle()
    assert any("la última" in text for text in engine.instructions)
    await feed_sonia(manager, "¡Me rindo! ¿Qué era?")
    assert screen.game_msgs()[-1]["event"] == "giveup"
    result = await registry.execute(
        "akinator_result", {"acierto": "no", "respuesta_real": "Haskell"}, ctx
    )
    assert "Haskell" in result.text and "Brian o Mariel" in result.text
    await settle()
    end = screen.game_msgs("end")[-1]
    assert end["data"]["result"] == "lose" and end["data"]["outcome"] == "visitor"


async def test_una_unity_que_se_reconecta_recibe_el_start_y_el_ultimo_estado() -> None:
    manager, _, screen, clock, registry, ctx = await manager_rig()
    await registry.execute("start_game", {"juego": "akinator"}, ctx)
    clock.advance(5)
    manager.on_user_text(clock())
    for n in range(1, 6):
        await feed_sonia(manager, f"¿Es la cosa número {n} de la lista?")
    await feed_sonia(manager, "¿Se usa para móviles?")
    replay = screen.replay()
    assert [m["event"] for m in replay] == ["start", "question"]
    assert replay[1]["data"]["asked"] == 6
    assert replay[1]["data"]["question"] == "¿Se usa para móviles?"
    await registry.execute("akinator_guess", {"respuesta": "Kotlin"}, ctx)
    replay = screen.replay()
    assert [m["event"] for m in replay] == ["start", "guess"]
    assert replay[1]["data"]["guess"] == "Kotlin"


async def test_stop_game_cancela_y_las_jugadas_ya_no_llegan() -> None:
    manager, _, screen, clock, registry, ctx = await manager_rig()
    await registry.execute("start_game", {"juego": "akinator"}, ctx)
    result = await registry.execute("stop_game", {}, ctx)
    assert "terminado" in result.text
    assert screen.game_msgs("end")[-1]["data"]["result"] == "cancel"
    for name, args in (
        ("akinator_guess", {"respuesta": "Kotlin"}),
        ("akinator_result", {"acierto": "si", "respuesta_real": "Kotlin"}),
    ):
        result = await registry.execute(name, args, ctx)
        assert "No hay ninguna partida" in result.text and not result.text.startswith(SCRIPT_PREFIX)


async def test_las_jugadas_fuera_de_turno_devuelven_un_guion_y_nunca_una_excepcion() -> None:
    manager, engine, screen, clock, registry, ctx = await manager_rig()
    # Sin partida.
    result = await registry.execute("akinator_guess", {"respuesta": "Kotlin"}, ctx)
    assert "No hay ninguna partida" in result.text
    await registry.execute("start_game", {"juego": "akinator"}, ctx)
    # Resultado antes de arriesgar nada.
    result = await registry.execute(
        "akinator_result", {"acierto": "si", "respuesta_real": NOT_SAID}, ctx
    )
    assert "respuesta_real" in result.text and not result.text.startswith(SCRIPT_PREFIX)
    result = await registry.execute(
        "akinator_result", {"acierto": "no", "respuesta_real": NOT_SAID}, ctx
    )
    assert "no se delegan" in result.text
    # Una respuesta que el esquema no deja pasar.
    result = await registry.execute("akinator_result", {"acierto": "tal vez"}, ctx)
    assert result.text.startswith("Error: argumentos inválidos")
    # Tras ganar, la partida enseña el final: las jugadas ya no llegan.
    clock.advance(5)
    manager.on_user_text(clock())
    for n in range(1, 7):
        await feed_sonia(manager, f"¿Es la cosa número {n} de la lista?")
    await registry.execute("akinator_result", {"acierto": "no", "respuesta_real": "Rust"}, ctx)
    result = await registry.execute("akinator_guess", {"respuesta": "Kotlin"}, ctx)
    assert "ya ha terminado" in result.text
    assert manager.phase == "finishing"
    # Empezar de nuevo mientras enseña el final lo cierra al momento.
    result = await registry.execute("start_game", {"juego": "akinator"}, ctx)
    assert result.text.startswith(SCRIPT_PREFIX)
    assert manager.phase == "playing"
    assert screen.game_msgs("start")[-1]["data"]["max"] == 20


async def test_abandono_sin_voz_cancela_la_partida() -> None:
    manager, engine, screen, clock, registry, ctx = await manager_rig()
    await registry.execute("start_game", {"juego": "akinator"}, ctx)
    clock.advance(30)
    await manager.tick(clock())
    assert manager.active
    clock.advance(40)
    await manager.tick(clock())
    assert not manager.active
    assert screen.game_msgs("end")[-1]["data"]["result"] == "cancel"
    assert any("nadie sigue jugando" in text for text in engine.spoken)


async def test_se_cancela_si_se_cae_la_sesion() -> None:
    manager, _, screen, _, registry, ctx = await manager_rig()
    await registry.execute("start_game", {"juego": "akinator"}, ctx)
    await manager.on_session_lost()
    assert not manager.active
    assert screen.game_msgs("end")[-1]["data"]["result"] == "cancel"


async def test_empujon_si_el_visitante_habla_con_una_respuesta_en_pantalla_sin_delegar() -> None:
    manager, engine, _, clock, registry, ctx = await manager_rig()
    await registry.execute("start_game", {"juego": "akinator"}, ctx)
    clock.advance(5)
    manager.on_user_text(clock())
    for n in range(1, 7):
        await feed_sonia(manager, f"¿Es la cosa número {n} de la lista?")
    # Preguntando: el visitante contesta y no se empuja a nadie.
    started = clock()
    clock.advance(1)
    manager.on_user_turn_end(clock(), started)
    clock.advance(5)
    await manager.tick(clock())
    assert engine.spoken == []
    # Con su respuesta en la pantalla, sí.
    await registry.execute("akinator_guess", {"respuesta": "Kotlin"}, ctx)
    started = clock()
    clock.advance(1)
    manager.on_user_turn_end(clock(), started)
    clock.advance(5)
    await manager.tick(clock())
    await settle()
    assert len(engine.spoken) == 1 and "akinator: resultado" in engine.spoken[0]


async def test_empujon_de_arranque_si_el_visitante_avisa_y_sonia_no_pregunta() -> None:
    manager, engine, _, clock, registry, ctx = await manager_rig()
    await registry.execute("start_game", {"juego": "akinator"}, ctx)
    clock.advance(5)
    manager.on_user_text(clock())
    started = clock()
    clock.advance(1)
    manager.on_user_turn_end(clock(), started)
    # Sonia no dice nada: a los 3 s se le recuerda que haga su primera pregunta.
    clock.advance(4)
    await manager.tick(clock())
    await settle()
    assert len(engine.spoken) == 1 and "primera pregunta" in engine.spoken[0]


async def test_si_sonia_ya_pregunto_no_hay_empujon_de_arranque() -> None:
    manager, engine, _, clock, registry, ctx = await manager_rig()
    await registry.execute("start_game", {"juego": "akinator"}, ctx)
    clock.advance(5)
    manager.on_user_text(clock())
    started = clock()
    clock.advance(1)
    manager.on_user_turn_end(clock(), started)
    # Antes de que venza el empujón, Sonia hace su primera pregunta.
    await feed_sonia(manager, "¡Vamos! ¿Es un lenguaje de programación?")
    clock.advance(4)
    await manager.tick(clock())
    await settle()
    assert engine.spoken == []


async def test_el_panel_ve_el_estado_de_la_partida() -> None:
    manager, _, _, clock, registry, ctx = await manager_rig()
    await registry.execute("start_game", {"juego": "akinator"}, ctx)
    clock.advance(5)
    manager.on_user_text(clock())
    await feed_sonia(manager, "¿Es un lenguaje de programación?")
    snapshot = manager.snapshot()
    assert snapshot["active"] == "akinator" and snapshot["title"] == "Akinator dev"
    assert snapshot["state"]["asked"] == 1 and snapshot["state"]["phase"] == "asking"
    assert [b["id"] for b in snapshot["banks"]] == ["akinator_temas"]
    assert "game:akinator" in manager.capabilities() and "game_banks" in manager.capabilities()


async def test_arrancar_desde_el_panel_le_pasa_el_guion_por_commentary() -> None:
    manager, engine, _, _, _, _ = await manager_rig()
    ok, message = await manager.start("akinator", "panel")
    assert ok and "Akinator dev en marcha" in message
    await settle()
    assert len(engine.spoken) == 1
    assert "el equipo del stand ha puesto el Akinator dev" in engine.spoken[0]
    assert "todavía no hagas ninguna pregunta" in engine.spoken[0]


async def test_si_la_unity_no_sabe_pintarlo_no_se_ofrece() -> None:
    manager, *_ = await make_manager([AkinatorGame], unity_games=["wordle"])
    ok, message = await manager.start("akinator", "voice")
    assert not ok and "no sabe pintar" in message


# ---------------------------------------------------------------------------
# Esquemas de las jugadas
# ---------------------------------------------------------------------------


def test_las_jugadas_estan_declaradas_con_esquemas_estrictos() -> None:
    specs = {spec.name: spec for spec in AkinatorGame.actions()}
    assert set(specs) == {"akinator_guess", "akinator_result"}
    guess = specs["akinator_guess"].parameters
    assert guess["required"] == ["respuesta"] and list(guess["properties"]) == ["respuesta"]
    result = specs["akinator_result"].parameters
    assert result["required"] == ["acierto", "respuesta_real"]
    assert result["properties"]["acierto"]["enum"] == ["si", "no", NOT_SAID]
    assert result["properties"]["respuesta_real"]["type"] == "string"
    for spec in specs.values():
        assert not brands_in(spec.description) and len(spec.description) < 400


def test_ninguna_regla_ni_guion_nombra_el_stack() -> None:
    from sonia.games.akinator import prompts

    texts = [
        value for name, value in vars(prompts).items() if name.isupper() and isinstance(value, str)
    ]
    assert len(texts) > 15
    for text in texts:
        check_for_live(text)


def test_la_pantalla_dice_sonnia_y_lo_hablado_sonia() -> None:
    assert "Sonia" not in AkinatorGame.title and "Sonnia" not in AkinatorGame.spoken
    assert AkinatorGame.title == "Akinator dev" and AkinatorGame.spoken == "el Akinator dev"


def test_los_eventos_tienen_nombres_validos() -> None:
    for event in ("start", "waiting", "question", "guess", "miss", "giveup", "reveal"):
        assert p.is_game_name(event)


# ---------------------------------------------------------------------------
# Dentro del motor de verdad (LiveEngine, Hub y un GPT-Live falso por WebSocket)
# ---------------------------------------------------------------------------


async def sonia_says(conn: Any, *chunks: str, pause: float = 0.45) -> None:
    """Sonia habla: llega su voz con su texto, en trozos, y luego calla (se cierra la frase)."""
    for chunk in chunks:
        await conn.audio(pcm(480))
        await conn.say(chunk)
        await asyncio.sleep(0.01)
    await asyncio.sleep(pause)


def question_events(rig: Any) -> list[dict[str, Any]]:
    return [m for m in rig.rec.of_type("game") if m["event"] == "question"]


async def test_en_el_motor_cuenta_las_preguntas_de_sonia_con_parciales_y_finales(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "games" / "akinator").mkdir(parents=True)
    shutil.copy(BANK_FILE, tmp_path / "games" / "akinator" / "temas.md")
    monkeypatch.setattr("sonia.games.akinator.game.READY_GRACE_S", 0.0)
    async with games_rig(tmp_path, games=[AkinatorGame]) as rig:
        rig.settings.games.result_seconds = 0.05
        rig.settings.games.final_wait_seconds = 0.3
        rig.settings.games.akinator.min_questions = 4
        conn = await rig.conn()
        instructions = conn.start["session"]["instructions"]
        assert "el Akinator dev" in instructions and "AKINATOR EN MARCHA" not in instructions
        tools = [t.get("name") for t in conn.start["session"]["delegation"]["responses"]["tools"]]
        assert {"start_game", "akinator_guess", "akinator_result"} <= set(tools)

        script = await _backend_call(conn, "g1", "start_game", {"juego": "akinator"})
        assert script.startswith(SCRIPT_PREFIX) and "todavía no hagas ninguna pregunta" in script
        await rig.rec.wait_type("game", 2)
        assert [m["event"] for m in rig.rec.of_type("game")] == ["start", "waiting"]
        await conn.wait_for(
            lambda msgs: any(
                m["type"] == "session.instructions.append" and "AKINATOR EN MARCHA" in m["content"]
                for m in msgs
            )
        )

        # La apertura de Sonia no lleva preguntas contadas ni aunque pregunte «¿listo?».
        await sonia_says(conn, "¡Va", "mos! ", "Piensa", " en", " algo", ".", " ¿", "Listo", "?")
        assert question_events(rig) == []

        # El visitante avisa y Sonia hace la primera pregunta, en trozos, y calla.
        await conn.hear("ya, listo")
        game = rig.engine.games.game("akinator")  # type: ignore[union-attr]
        assert isinstance(game, AkinatorGame)
        await wait_until(lambda: game.snapshot()["ready"])
        await sonia_says(
            conn, "¡Ajá", "! ", "¿", "Es", " un", " lenguaje", " de", " programación", "?"
        )
        await wait_until(lambda: len(question_events(rig)) >= 1)
        # El cierre de la frase la repite entera y no sube la cuenta.
        await asyncio.sleep(0.3)
        asked = [m["data"]["asked"] for m in question_events(rig)]
        assert asked == [1], asked
        assert question_events(rig)[0]["data"]["question"] == "¿Es un lenguaje de programación?"

        # Otra pregunta distinta, y la repetición de la primera.
        await sonia_says(conn, "Mmm", ". ", "¿", "Lo", " creó", " Google", "?")
        await wait_until(lambda: len(question_events(rig)) >= 2)
        await sonia_says(
            conn, "Perdona", ", ", "¿", "Es", " un", " lenguaje", " de", " programación", "?"
        )
        await sonia_says(conn, "Y", " dime", ", ", "¿", "Se", " usa", " en", " móviles", "?")
        await wait_until(lambda: len(question_events(rig)) >= 3)
        await asyncio.sleep(0.3)
        assert [m["data"]["asked"] for m in question_events(rig)] == [1, 2, 3]

        # Arriesga antes del mínimo (4): la rechaza. Con la cuarta pregunta ya puede, y el
        # veredicto cierra la partida.
        result = await _backend_call(conn, "g2", "akinator_guess", {"respuesta": "Kotlin"})
        assert "pronto" in result and not result.startswith(SCRIPT_PREFIX)
        await sonia_says(conn, "Vale", ". ", "¿", "Es", " de", " pago", "?")
        await wait_until(lambda: len(question_events(rig)) >= 4)
        result = await _backend_call(conn, "g3", "akinator_guess", {"respuesta": "Kotlin"})
        assert result.startswith(SCRIPT_PREFIX) and "«Kotlin»" in result
        result = await _backend_call(
            conn, "g4", "akinator_result", {"acierto": "si", "respuesta_real": "Kotlin"}
        )
        assert (
            result.startswith(SCRIPT_PREFIX) and "Acertaste" in result and "4 preguntas" in result
        )
        await rig.rec.wait_for(
            lambda msgs: any(m.get("event") == "end" for m in rig.rec.of_type("game", msgs)),
            limit=10.0,
        )
        events = [m["event"] for m in rig.rec.of_type("game")]
        assert events[-3:] == ["guess", "reveal", "end"], events
        assert rig.rec.of_type("game")[-1]["data"]["result"] == "win"
        assert rig.rec.of_type("game")[-2]["data"]["outcome"] == "sonnia"
        seqs = [m["seq"] for m in rig.rec.of_type("game")]
        assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
