"""Modo trivia: banco de preguntas, partida y acciones, sin red ni GPT-Live real."""

from __future__ import annotations

import asyncio
import random
from pathlib import Path
from typing import Any

from sonia.actions import build_default_registry
from sonia.actions.trivia import SCRIPT_PREFIX
from sonia.config import TriviaSettings
from sonia.trivia import PASS, TriviaBank, TriviaGame, TriviaPhase, parse_questions
from sonia.trivia.game import STICKY_QUESTION, STICKY_START
from sonia.types import ActionContext

REPO_BANK = Path(__file__).resolve().parents[2] / "assets" / "trivia" / "preguntas.md"

BANK = """\
<!-- Comentario que se ignora.
## Esto no es una pregunta
- [x] Ni esto una opción
-->
# Preguntas

## ¿Pregunta uno?
- [x] Correcta uno
- [ ] Mala uno
- [ ] Peor uno
> Dato de la uno.

## ¿Pregunta dos?
- [ ] Mala dos
- [x] Correcta dos
- [ ] Peor dos

## ¿Pregunta tres?
- [ ] Mala tres
- [ ] Peor tres
- [X] Correcta tres

## ¿Pregunta mal formada sin correcta?
- [ ] Una
- [ ] Dos
- [ ] Tres

## ¿Pregunta mal formada con dos opciones?
- [x] Una
- [ ] Dos
"""


class FakeHost:
    """El motor GPT-Live visto por la partida."""

    def __init__(self) -> None:
        self.connected = True
        self.quiet = 10.0
        self.spoken: list[str] = []
        self.instructions: list[str] = []
        self.touches = 0

    def quiet_for(self) -> float:
        return self.quiet

    async def speak(self, prompt: str) -> bool:
        self.spoken.append(prompt)
        return True

    async def instruct(self, text: str) -> bool:
        self.instructions.append(text)
        return True

    async def wait_idle(self, limit_s: float | None = None) -> bool:
        return True

    def touch(self) -> None:
        self.touches += 1


class FakeScreen:
    """El hub de Unity visto por la partida."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.sticky: dict[str, dict[str, Any]] = {}
        self.hidden = 0

    async def broadcast_json(self, msg: dict[str, Any]) -> None:
        self.sent.append(msg)

    async def set_sticky(self, key: str, msg: dict[str, Any]) -> None:
        self.sticky[key] = msg
        self.sent.append(msg)

    def clear_sticky(self, key: str) -> None:
        self.sticky.pop(key, None)

    async def hide_image(self) -> None:
        self.hidden += 1

    def of_type(self, kind: str) -> list[dict[str, Any]]:
        return [m for m in self.sent if m["type"] == kind]


def make_game(
    tmp_path: Path, *, questions: int = 3, threshold: int = 2, **overrides: Any
) -> tuple[TriviaGame, FakeHost, FakeScreen]:
    bank = tmp_path / "preguntas.md"
    bank.write_text(BANK, encoding="utf-8")
    values: dict[str, Any] = {"reveal_seconds": 0.0, "final_wait_seconds": 0.0, **overrides}
    settings = TriviaSettings(questions=questions, win_threshold=threshold, **values)
    host, screen = FakeHost(), FakeScreen()
    game = TriviaGame(settings, bank, host=host, screen=screen, rng=random.Random(7))
    return game, host, screen


async def settle() -> None:
    """Deja correr las tareas de la partida (``reveal_seconds`` es 0)."""
    for _ in range(5):
        await asyncio.sleep(0)


def current(screen: FakeScreen) -> dict[str, Any]:
    return screen.sticky[STICKY_QUESTION]


def correct_index(game: TriviaGame) -> int:
    question = game._current
    assert question is not None
    return question.correct


# ---------------------------------------------------------------------------
# Banco
# ---------------------------------------------------------------------------


def test_el_banco_salta_las_preguntas_mal_formadas_y_los_comentarios() -> None:
    questions = parse_questions(BANK)
    assert [q.text for q in questions] == ["¿Pregunta uno?", "¿Pregunta dos?", "¿Pregunta tres?"]
    assert [q.correct for q in questions] == [0, 1, 2]
    assert questions[0].fact == "Dato de la uno."
    assert questions[1].fact == ""


def test_barajar_conserva_la_respuesta_correcta() -> None:
    question = parse_questions(BANK)[1]
    rng = random.Random(3)
    for _ in range(20):
        shuffled = question.shuffled(rng)
        assert sorted(shuffled.options) == sorted(question.options)
        assert shuffled.options[shuffled.correct] == "Correcta dos"


def test_el_banco_del_repo_tiene_preguntas_validas_y_cortas() -> None:
    bank = TriviaBank.from_file(REPO_BANK)
    assert len(bank) >= 15
    for question in bank.questions:
        assert len(question.options) == 3
        # Salen en la pantalla vertical: opciones cortas.
        assert all(len(option) <= 40 for option in question.options), question.text
    assert len({q.text for q in bank.questions}) == len(bank)


def test_las_reglas_caben_en_una_instruccion() -> None:
    from sonia.live.client import APPEND_MAX_CHARS
    from sonia.trivia.game import RULES_TEXT

    # session.instructions.append recorta lo que pase de APPEND_MAX_CHARS.
    assert (
        len(RULES_TEXT.format(total=10, threshold=10, level="intermedio")) < APPEND_MAX_CHARS - 50
    )


def test_sin_banco_no_hay_trivia(tmp_path: Path) -> None:
    host, screen = FakeHost(), FakeScreen()
    game = TriviaGame(TriviaSettings(), tmp_path / "no-existe.md", host=host, screen=screen)
    assert not game.available
    assert len(TriviaBank.from_file(tmp_path / "no-existe.md")) == 0


# ---------------------------------------------------------------------------
# Partida
# ---------------------------------------------------------------------------


async def answer_and_next(game: TriviaGame, choice: int) -> str:
    """Contesta y, si no era la última, pide la siguiente (como haría GPT-Live)."""
    ok, script = await game.answer(choice, "voice")
    assert ok, script
    if game.phase is TriviaPhase.REVEALING and not game._final:
        assert (await game.next("voice"))[0]
    await settle()
    return script


async def test_partida_ganada_por_voz(tmp_path: Path) -> None:
    game, host, screen = make_game(tmp_path)
    ok, script = await game.start("voice")
    assert ok
    assert game.phase is TriviaPhase.ASKING
    assert screen.hidden == 1
    assert screen.sticky[STICKY_START] == {
        "type": "trivia_start",
        "total": 3,
        "threshold": 2,
        "level": "intermedio",
    }
    first = current(screen)
    assert first["number"] == 1 and first["total"] == 3 and first["score"] == 0
    assert len(first["options"]) == 3
    # La pregunta va para leerla; las opciones, solo para que GPT-Live sepa las letras.
    assert first["question"] in script and "lee solo la pregunta" in script
    assert "No leas las opciones" in script
    assert all(option in script for option in first["options"])
    assert "CORRECTA" not in script
    # Por voz no se le pide nada por commentary: el guion va en el resultado.
    assert host.spoken == []
    assert "MODO TRIVIA EN MARCHA" in host.instructions[0]
    assert "nunca las opciones" in host.instructions[0]

    for number in (1, 2, 3):
        right = correct_index(game)
        ok, script = await game.answer(right, "voice")
        assert ok and "CORRECTA" in script and "Explica" in script
        answer = screen.of_type("trivia_answer")[-1]
        assert answer == {
            "type": "trivia_answer",
            "number": number,
            "chosen": right,
            "correct": right,
            "is_correct": True,
            "score": number,
        }
        if number < 3:
            # Nada avanza solo: pregunta si quiere la siguiente y espera.
            assert "siguiente pregunta" in script and "pregunta 2" not in script
            await settle()
            assert game.phase is TriviaPhase.REVEALING
            assert current(screen)["number"] == number
            ok, script = await game.next("voice")
            assert ok and f"pregunta {number + 1} de 3" in script
            assert current(screen)["number"] == number + 1
        else:
            assert "HA GANADO" in script
            assert "un sticker o un pin" in script
        await settle()

    end = screen.of_type("trivia_end")[-1]
    assert end == {
        "type": "trivia_end",
        "score": 3,
        "total": 3,
        "won": True,
        "reason": "finished",
        "prize": "un sticker o un pin de Sonnet Code",
    }
    assert not game.active
    assert screen.sticky == {}
    assert "ha terminado" in host.instructions[-1]


async def test_la_ultima_respuesta_siempre_cierra_la_partida(tmp_path: Path) -> None:
    # Lo que se vio en la demo: la pantalla no puede quedarse en la última pregunta.
    game, host, screen = make_game(tmp_path, questions=3)
    await game.start("voice")
    await answer_and_next(game, 0)
    await answer_and_next(game, 0)
    await answer_and_next(game, 0)
    assert not game.active
    assert screen.of_type("trivia_end")[-1]["reason"] == "finished"


async def test_la_pantalla_final_espera_a_que_sonia_termine(tmp_path: Path) -> None:
    game, host, screen = make_game(tmp_path, questions=1, threshold=1, final_wait_seconds=5.0)
    await game.start("voice")
    host.quiet = 10.0
    await game.answer(correct_index(game), "voice")
    await asyncio.sleep(0.3)
    assert game.active  # aún no ha empezado a contarlo
    host.quiet = 0.0  # habla
    await asyncio.sleep(0.3)
    assert game.active
    host.quiet = 2.0  # calla
    await asyncio.sleep(0.6)
    assert not game.active
    assert screen.of_type("trivia_end")[-1]["won"] is True


async def test_la_siguiente_solo_cuando_toca(tmp_path: Path) -> None:
    game, _, screen = make_game(tmp_path)
    await game.start("voice")
    ok, message = await game.next("voice")
    assert not ok and "aún espera respuesta" in message
    await game.answer(0, "voice")
    # Una respuesta con el resultado en pantalla no se pierde en silencio: se le explica.
    ok, message = await game.answer(1, "voice")
    assert not ok and "siguiente pregunta" in message
    assert len(screen.of_type("trivia_answer")) == 1
    assert (await game.next("voice"))[0]
    assert (await game.answer(1, "voice"))[0]


async def test_partida_perdida_dice_la_buena_y_anima(tmp_path: Path) -> None:
    game, host, screen = make_game(tmp_path)
    await game.start("voice")
    wrong = (correct_index(game) + 1) % 3
    question = game._current
    assert question is not None
    ok, script = await game.answer(wrong, "voice")
    assert ok
    assert "NO es correcta" in script
    assert question.options[question.correct] in script
    answer = screen.of_type("trivia_answer")[-1]
    assert answer["is_correct"] is False and answer["chosen"] == wrong
    await game.next("voice")
    ok, script = await game.answer(PASS, "voice")
    assert ok and "No lo sabe" in script
    assert screen.of_type("trivia_answer")[-1]["chosen"] == -1
    await game.next("voice")
    ok, script = await game.answer(correct_index(game), "voice")
    assert "le faltaron aciertos" in script
    await settle()
    end = screen.of_type("trivia_end")[-1]
    assert end["won"] is False and end["score"] == 1 and end["reason"] == "finished"
    assert end["prize"] == "un sticker o un pin de Sonnet Code"


async def test_ganar_en_dificil_se_lleva_la_gorra(tmp_path: Path) -> None:
    game, _, screen = make_game(tmp_path)
    ok, script = await game.start("voice", "Difícil")
    assert ok and "nivel difícil" in script
    for _ in range(3):
        last = await answer_and_next(game, correct_index(game))
    assert "una gorra de Sonnet Code" in last
    assert screen.of_type("trivia_end")[-1]["prize"] == "una gorra de Sonnet Code"


def test_niveles_del_banco() -> None:
    from sonia.trivia import normalize_level

    text = BANK.replace("## ¿Pregunta dos?", "## [difícil] ¿Pregunta dos?").replace(
        "## ¿Pregunta tres?", "## [Facil] ¿Pregunta tres?"
    )
    questions = parse_questions(text)
    assert [q.level for q in questions] == ["intermedio", "difícil", "fácil"]
    assert questions[1].text == "¿Pregunta dos?"
    assert normalize_level("básico") == "fácil" and normalize_level("nada") is None
    bank = TriviaBank(questions)
    first = bank.draw(1, random.Random(1), "difícil")[0]
    assert first.text == "¿Pregunta dos?"
    # Si el nivel no llega, se completa con el más cercano.
    assert len(bank.draw(3, random.Random(1), "fácil")) == 3


async def test_el_dato_de_la_pregunta_va_en_el_guion(tmp_path: Path) -> None:
    game, _, _ = make_game(tmp_path)
    await game.start("voice")
    while game._current is not None and game._current.text != "¿Pregunta uno?":
        await answer_and_next(game, 0)
    _, script = await game.answer(0, "voice")
    assert "Dato de la uno." in script


async def test_desde_el_panel_se_lo_pide_a_gpt_live(tmp_path: Path) -> None:
    game, host, screen = make_game(tmp_path)
    ok, message = await game.start("panel", "fácil")
    assert ok and "Trivia en marcha, nivel fácil" in message
    await settle()
    assert len(host.spoken) == 1
    assert current(screen)["question"] in host.spoken[0]
    ok, message = await game.answer(correct_index(game), "panel")
    assert ok and "acierto" in message
    assert "registrada por el equipo del stand" in host.spoken[-1]
    assert "CORRECTA" in host.spoken[-1]
    ok, message = await game.next("panel")
    assert ok and "Pregunta 2 de 3" in message
    await settle()
    assert "pregunta 2 de 3" in host.spoken[-1]


async def test_no_se_registra_sin_pregunta_ni_con_letra_mala(tmp_path: Path) -> None:
    game, _, screen = make_game(tmp_path)
    ok, _ = await game.answer(0, "voice")
    assert not ok
    await game.start("voice")
    ok, _ = await game.answer(5, "voice")
    assert not ok
    assert screen.of_type("trivia_answer") == []


async def test_no_empieza_dos_veces_ni_sin_sesion(tmp_path: Path) -> None:
    game, host, _ = make_game(tmp_path)
    assert (await game.start("voice"))[0]
    ok, message = await game.start("panel")
    assert not ok and "Ya hay" in message
    await game.stop("panel")
    host.connected = False
    ok, message = await game.start("panel")
    assert not ok and "no está conectada" in message


async def test_faltan_preguntas(tmp_path: Path) -> None:
    game, _, _ = make_game(tmp_path, questions=5)
    assert not game.available
    ok, message = await game.start("voice")
    assert not ok and "hacen falta 5" in message


async def test_reiniciar_empieza_de_cero(tmp_path: Path) -> None:
    game, host, screen = make_game(tmp_path)
    await game.start("voice")
    await game.answer(correct_index(game), "voice")
    ok, script = await game.restart("voice")
    assert ok and "pregunta 1 de 3" in script
    assert game.phase is TriviaPhase.ASKING
    assert screen.of_type("trivia_end")[-1]["reason"] == "cancelled"
    assert screen.sticky[STICKY_QUESTION]["number"] == 1
    assert screen.sticky[STICKY_QUESTION]["score"] == 0
    # Sin partida en marcha, reiniciar es empezar.
    await game.stop("panel")
    ok, _ = await game.restart("voice")
    assert ok and game.active


async def test_cancelar_desde_el_panel(tmp_path: Path) -> None:
    game, host, screen = make_game(tmp_path)
    await game.start("voice")
    ok, _ = await game.stop("panel")
    assert ok and not game.active
    end = screen.of_type("trivia_end")[-1]
    assert end["reason"] == "cancelled" and end["won"] is False
    assert screen.sticky == {}
    assert "equipo del stand ha terminado" in host.spoken[-1]


async def test_si_se_cae_la_sesion_se_cancela_sin_hablar(tmp_path: Path) -> None:
    game, host, screen = make_game(tmp_path)
    await game.start("voice")
    host.connected = False
    await game.on_session_lost()
    assert not game.active
    assert screen.of_type("trivia_end")[-1]["reason"] == "cancelled"
    assert host.spoken == []


async def test_recuerda_la_pregunta_y_luego_la_da_por_abandonada(tmp_path: Path) -> None:
    game, host, screen = make_game(tmp_path, remind_seconds=20.0, abandon_seconds=60.0)
    await game.start("voice")
    host.quiet = 1000.0  # Sonia lleva rato callada
    start = game._asked_at
    await game.tick(start + 10)
    assert host.spoken == []
    await game.tick(start + 21)
    await settle()
    assert len(host.spoken) == 1 and "repite la pregunta" in host.spoken[0]
    assert "sin leer las opciones" in host.spoken[0]
    await game.tick(start + 30)
    await settle()
    assert len(host.spoken) == 1  # una sola vez por pregunta
    # Si se oye al visitante, no se da por abandonada.
    game.on_user_text(start + 50)
    await game.tick(start + 61)
    assert game.active
    await game.tick(start + 111)
    assert not game.active
    assert screen.of_type("trivia_end")[-1]["reason"] == "cancelled"
    assert "queda para otro momento" in host.spoken[-1]


async def test_mientras_habla_sonia_no_recuerda_ni_abandona(tmp_path: Path) -> None:
    game, host, _ = make_game(tmp_path, remind_seconds=20.0, abandon_seconds=60.0)
    await game.start("voice")
    host.quiet = 0.0
    await game.tick(game._asked_at + 100)
    assert game.active and host.spoken == []


# ---------------------------------------------------------------------------
# Acciones
# ---------------------------------------------------------------------------


async def test_acciones_de_la_trivia(tmp_path: Path) -> None:
    game, _, screen = make_game(tmp_path)
    registry = build_default_registry(include_look=False, include_trivia=True)
    assert registry.names() == [
        "show_image",
        "hide_image",
        "play_animation",
        "start_trivia",
        "trivia_answer",
        "trivia_next",
        "restart_trivia",
        "stop_trivia",
    ]
    ctx = ActionContext(camera=None, avatar=None, gallery_dir="", extra={"trivia": game})

    result = await registry.execute("start_trivia", {"nivel": "fácil"}, ctx)
    assert result.text.startswith(SCRIPT_PREFIX) and "nivel fácil" in result.text
    assert current(screen)["question"] in result.text

    letter = "ABC"[correct_index(game)]
    result = await registry.execute("trivia_answer", {"option": letter}, ctx)
    assert result.text.startswith(SCRIPT_PREFIX) and "CORRECTA" in result.text

    result = await registry.execute("trivia_answer", {"option": "D"}, ctx)
    assert result.text.startswith("Error")

    result = await registry.execute("trivia_next", {}, ctx)
    assert result.text.startswith(SCRIPT_PREFIX) and "pregunta 2 de 3" in result.text
    assert current(screen)["number"] == 2

    result = await registry.execute("restart_trivia", {}, ctx)
    assert result.text.startswith(SCRIPT_PREFIX) and "desde cero" in result.text
    assert current(screen)["number"] == 1

    result = await registry.execute("stop_trivia", {}, ctx)
    assert "terminada" in result.text
    assert not game.active

    sin_partida = ActionContext(camera=None, avatar=None, gallery_dir="")
    result = await registry.execute("start_trivia", {}, sin_partida)
    assert "no está disponible" in result.text


def test_sin_trivia_no_se_anuncian_sus_acciones() -> None:
    names = build_default_registry(include_look=False).names()
    assert "start_trivia" not in names and "trivia_answer" not in names
