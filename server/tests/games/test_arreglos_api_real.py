"""Los arreglos del banco de pruebas con la API real (10 de octubre de 2026).

- La línea de juegos: solo se juega delegando, y despedirse también termina.
- Los empujones son órdenes cortas y el manager les añade que son una nota interna (en voz
  alta se oían); el juego decide su empujón después de ver el turno del visitante.
- El Akinator: empujón tras un turno largo mientras pregunta (parar o decir qué era), un
  recordatorio si su respuesta se queda sin resultado y los avisos solo con todos callados.
- La ruleta: despedirse termina, también mientras gira; no juzga ella las adivinanzas.
- El Wordle: el backend pasa la palabra tal como llega y nunca la rechaza él.
- La búsqueda y Simón dice: empujón para parar.
"""

from __future__ import annotations

from typing import Any, ClassVar

from sonia.games import Game
from sonia.games.akinator import prompts as akinator_text
from sonia.games.akinator.game import GUESS_REMIND_S
from sonia.games.manager import NUDGE_TAIL
from sonia.games.poses.game import NUDGE_STOP, PosesGame
from sonia.games.registry import games_line_for
from sonia.games.ruleta import texts as ruleta_text
from sonia.games.wordle.game import WordleGame
from tests.games.fakes import brands_in, make_game, make_manager, settle
from tests.games.test_akinator import ask, questions, start_game, visitor_speaks


def test_la_linea_de_juegos_dice_que_solo_se_juega_delegando() -> None:
    line = games_line_for(["el Akinator dev", "el Wordle de tecnología"])
    assert line.count("\n") == 0 and not brands_in(line)
    assert "nunca lo juegues por tu cuenta" in line and "no sale en tu pantalla" in line
    assert "se despiden" in line and "delega terminarlo" in line


class TurnGame(Game):
    """Pide empujón solo tras un turno largo (como el Akinator mientras pregunta)."""

    id: ClassVar[str] = "turno"
    title: ClassVar[str] = "Turno"
    spoken: ClassVar[str] = "el juego del turno"
    settings_key: ClassVar[str] = "akinator"

    long_turn = False

    async def start(self, source: str, options: dict[str, Any]) -> str:
        return "Arranca."

    def on_user_turn_end(self, now: float, started_at: float) -> None:
        self.long_turn = now - started_at >= 3.0

    def nudge(self) -> str | None:
        return "TURNO: si pidió parar, delega terminar el juego." if self.long_turn else None


async def test_el_juego_decide_su_empujon_despues_de_ver_el_turno() -> None:
    manager, engine, _, clock = await make_manager([TurnGame])
    await manager.start("turno", "voice")
    manager.on_user_turn_end(clock(), clock() - 1.0)  # turno corto: nada
    clock.advance(5)
    await manager.tick(clock())
    await settle()
    assert engine.spoken == []
    manager.on_user_turn_end(clock(), clock() - 4.0)  # turno largo: empujón con la nota final
    clock.advance(5)
    await manager.tick(clock())
    await settle()
    assert engine.spoken == ["TURNO: si pidió parar, delega terminar el juego." + NUDGE_TAIL]
    assert NUDGE_TAIL.endswith("no la leas ni la comentes.")


async def test_akinator_tras_un_turno_largo_mientras_pregunta_empuja_a_parar() -> None:
    game, host = await start_game()
    visitor_speaks(game, host)
    await ask(game, *questions(2))
    gap = host.settings.live.user_turn_gap_ms / 1000.0
    game.on_user_turn_end(host.now(), host.now() - gap - 0.2)  # «Sí»
    assert game.nudge() is None
    game.on_user_turn_end(host.now(), host.now() - gap - 2.0)  # «Espera, mejor lo dejamos»
    assert game.nudge() == akinator_text.ASKING_NUDGE


async def test_akinator_recuerda_una_vez_el_resultado_que_falta() -> None:
    game, host = await start_game()
    visitor_speaks(game, host)
    await ask(game, *questions(6))
    script = await game.guess({"respuesta": "Python"})
    assert "Python" in script
    await game.tick(host.now() + GUESS_REMIND_S + 1)
    assert host.spoken == []  # el visitante aún no ha hablado desde que arriesgó
    game.on_user_text(host.now())
    await game.tick(host.now() + GUESS_REMIND_S + 1)
    await host.run_tasks()
    await game.tick(host.now() + GUESS_REMIND_S + 5)
    await host.run_tasks()
    assert host.spoken == [akinator_text.GUESS_REMIND_TEXT]


async def test_akinator_avisa_de_las_ultimas_preguntas_solo_con_todos_callados() -> None:
    game, host = await start_game()
    visitor_speaks(game, host)
    host.idle = False
    before = len(host.instructions)
    await ask(game, *questions(15))
    assert len(host.instructions) == before  # mientras habla alguien, nada
    host.idle = True
    await ask(game, questions(16)[-1])
    await host.run_tasks()
    assert any("llevas 15 de 20" in i for i in host.instructions)


def test_akinator_sabe_parar_y_registrar_el_resultado_antes_de_celebrar() -> None:
    rules = akinator_text.build_rules(20, 5, [])
    assert "decir «paramos» no lo para" in rules and "antes de celebrar" in rules
    assert "nunca «adivina» con lo que te diga" in rules and len(rules) <= 1200


def test_ruleta_despedirse_termina_y_no_juzga_ella_la_adivinanza() -> None:
    assert "se despiden" in ruleta_text.RULES_TEXT
    assert "se despidió" in ruleta_text.NUDGE_CHALLENGE
    assert "se despidió" in ruleta_text.NUDGE_RESULT
    assert "se despidió" in ruleta_text.NUDGE_SPINNING
    assert "Aunque sepas que no es, no lo digas tú" in ruleta_text.RIDDLE_RULES
    for announce in (
        ruleta_text.TRIVIA_ANNOUNCE,
        ruleta_text.RIDDLE_ANNOUNCE,
        ruleta_text.SONNET_QUESTION_ANNOUNCE,
    ):
        assert "no digas si acierta" in announce


def test_wordle_pasa_la_palabra_tal_cual_y_no_la_rechaza() -> None:
    spec = WordleGame.actions()[0]
    assert "CAFKA vale" in spec.description and "nunca la rechaces" in spec.description
    prop = spec.parameters["properties"]["palabra"]["description"]
    assert "aunque dudes" in prop and "Solo si en la tarea no hay ninguna palabra" in prop


async def test_simon_dice_empuja_a_parar_salvo_en_la_ventana_de_la_pose() -> None:
    game, _ = make_game(PosesGame)
    assert game.nudge() is None  # sin partida
    game._phase = "round"  # noqa: SLF001 - fase de la partida
    assert game.nudge() == NUDGE_STOP
    game._phase = "window"  # noqa: SLF001
    assert game.nudge() is None


def test_ningun_empujon_nombra_el_stack_ni_es_largo() -> None:
    from sonia.games.busqueda import texts as busqueda_text
    from sonia.games.wordle.game import NUDGE_TEXT

    nudges = [
        NUDGE_TEXT,
        NUDGE_STOP,
        busqueda_text.NUDGE_RUNNING,
        busqueda_text.NUDGE_STOP,
        ruleta_text.NUDGE_CHALLENGE,
        ruleta_text.NUDGE_RESULT,
        ruleta_text.NUDGE_SPINNING,
        akinator_text.GUESS_NUDGE,
        akinator_text.START_NUDGE,
        akinator_text.GIVEUP_NUDGE,
        akinator_text.ASKING_NUDGE,
        akinator_text.LIMIT_NUDGE.format(max=20),
    ]
    for text in nudges:
        assert not brands_in(text + NUDGE_TAIL)
        assert len(text) <= 220, text  # órdenes cortas: en voz alta se oían
