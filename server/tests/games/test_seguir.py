"""Todos los juegos piden seguir a Sonnet Code, como la trivia (Jean, 10 de octubre de 2026).

Por voz, si el visitante no ha dicho ya que sigue a Sonnet Code, ``start_game`` prepara el
juego y el guion pide preguntárselo antes; la partida queda retenida (pantalla, vista en vivo
y ``GameHost.wait_go``) hasta lo primero que pase: «Ya nos sigue» en el panel, una jugada
delegada, el turno del visitante seguido de una frase de Sonia o 45 s.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

import pytest

from sonia.actions import build_default_registry
from sonia.actions.games import game_action
from sonia.games import Game, StopReason
from sonia.games.busqueda.game import READY_CAP_FIRST_S, BusquedaGame
from sonia.games.manager import (
    CONTROL_FOLLOW,
    FOLLOW_GRACE_S,
    FOLLOW_PANEL_TEXT,
    FOLLOW_TEXT,
    STICKY_START,
    STICKY_STATE,
    GameManager,
)
from sonia.games.ruleta.game import SPIN_GRACE_S, SPIN_SECONDS, RuletaGame
from sonia.prompts import BOOK
from sonia.types import ActionContext, ActionSpec
from tests.games.fakes import (
    FakeClock,
    FakeEngine,
    FakeScreen,
    FakeVision,
    brands_in,
    game_settings,
    make_game,
    make_manager,
    settle,
)


class TimedGame(Game):
    """Un juego de cámara con tiempos: manda su pantalla, pide la vista en vivo y su primer
    paso cronometrado espera a ``wait_go``."""

    id: ClassVar[str] = "cronometro"
    title: ClassVar[str] = "Cronómetro"
    spoken: ClassVar[str] = "el cronómetro"
    settings_key: ClassVar[str] = "poses"
    needs: ClassVar[frozenset[str]] = frozenset({"camera", "preview"})

    def __init__(self, host: Any) -> None:
        super().__init__(host)
        self.went: list[bool] = []
        self.plays: list[str] = []
        self.ending_asked = 0

    @classmethod
    def actions(cls) -> list[ActionSpec]:
        async def play(game: TimedGame, arguments: dict[str, Any]) -> str:
            game.plays.append(arguments["jugada"])
            return "Jugada apuntada."

        return [
            game_action(
                cls,
                name="cronometro_jugada",
                description="Una jugada del cronómetro.",
                parameters={
                    "type": "object",
                    "properties": {"jugada": {"type": "string"}},
                    "required": ["jugada"],
                },
                play=play,
            )
        ]

    async def start(self, source: str, options: dict[str, Any]) -> str:
        await self.host.stream.acquire(self.id)
        await self.host.send("start", {"rounds": 3})
        await self.host.send("round", {"index": 1})
        await self.host.send("hint", {"text": "suelto"}, sticky=False)
        await self.host.send("round", {"index": 2})
        await self.host.preview.start(self.id, mirror=True)
        self.host.spawn(self._run(), "rondas")
        return "Explica el cronómetro con energía."

    async def _run(self) -> None:
        self.went.append(await self.host.wait_go())

    async def stop_requested(self, source: str) -> str | None:
        self.ending_asked += 1
        return None

    async def stop(self, reason: StopReason) -> None:
        await self.host.preview.stop(self.id)
        await self.host.stream.release(self.id)


async def held_manager(
    **games: Any,
) -> tuple[GameManager, FakeEngine, FakeScreen, FakeClock, FakeVision, TimedGame]:
    vision = FakeVision()
    settings = game_settings(result_seconds=0.0, final_wait_seconds=0.0, **games)
    manager, engine, screen, clock = await make_manager(
        [TimedGame], vision=vision, settings=settings
    )
    game = manager.game(TimedGame.id)
    assert isinstance(game, TimedGame)
    return manager, engine, screen, clock, vision, game


def ctx(manager: GameManager) -> ActionContext:
    return ActionContext(camera=None, avatar=None, gallery_dir="", extra={"games": manager})


# ---------------------------------------------------------------------------
# start_game y el guion
# ---------------------------------------------------------------------------


async def test_start_game_sin_decir_que_sigue_pide_seguir_y_retiene_el_juego() -> None:
    manager, _, screen, _, vision, game = await held_manager()
    registry = build_default_registry(include_look=False, games=[TimedGame])
    spec = registry.get("start_game")
    assert spec is not None and "sigue_a_sonnet_code" in spec.parameters["properties"]
    assert spec.parameters["required"] == ["juego"]
    result = await registry.execute("start_game", {"juego": TimedGame.id}, ctx(manager))
    assert result.text.startswith("PARA SONIA: Antes de empezar, pregúntale solo si ya sigue")
    assert result.text.endswith("sigue este guion: Explica el cronómetro con energía.")
    assert not brands_in(result.text)
    assert manager.following and manager.active
    # La pantalla espera: nada del juego en Unity ni la vista en vivo.
    assert screen.game_msgs() == [] and STICKY_START not in screen.sticky
    assert vision.preview.starts == []
    await settle()
    assert game.went == []  # su primer paso cronometrado espera


async def test_start_game_diciendo_que_ya_sigue_empieza_como_siempre() -> None:
    manager, _, screen, _, vision, game = await held_manager()
    registry = build_default_registry(include_look=False, games=[TimedGame])
    result = await registry.execute(
        "start_game", {"juego": TimedGame.id, "sigue_a_sonnet_code": True}, ctx(manager)
    )
    assert result.text == "PARA SONIA: Explica el cronómetro con energía."
    assert not manager.following
    assert [m["event"] for m in screen.game_msgs()] == ["start", "round", "hint", "round"]
    assert vision.preview.starts == [(TimedGame.id, True)]
    await settle()
    assert game.went == [False]


async def test_desde_el_panel_no_se_pide_seguir() -> None:
    manager, engine, screen, _, _, game = await held_manager()
    ok, _ = await manager.start(TimedGame.id, "panel", ask_follow=True)
    assert ok and not manager.following
    assert screen.game_msgs("start")
    await settle()
    assert game.went == [False]
    assert not any(FOLLOW_TEXT[:40] in text for text in engine.spoken)


async def test_la_pieza_es_editable_desde_la_nube() -> None:
    assert BOOK.default("juegos/seguir_sonnet_code") == FOLLOW_TEXT
    assert BOOK.default("juegos/ya_nos_sigue") == FOLLOW_PANEL_TEXT
    for prompt_id in ("juegos/seguir_sonnet_code", "juegos/ya_nos_sigue"):
        assert BOOK.validate(prompt_id, BOOK.default(prompt_id)) == []
        assert not brands_in(BOOK.default(prompt_id))
    manager, _, _, _, _, _ = await held_manager()
    BOOK.set_overrides({"juegos/seguir_sonnet_code": "Pregunta si nos sigue y luego:"})
    try:
        ok, script = await manager.start(TimedGame.id, "voice", ask_follow=True)
    finally:
        BOOK.set_overrides(None)
    assert ok and script == "Pregunta si nos sigue y luego: Explica el cronómetro con energía."


@pytest.mark.parametrize("game_id", ["ruleta", "poses", "akinator", "wordle", "busqueda"])
def test_el_guion_de_cada_juego_cabe_con_la_pieza_delante(game_id: str) -> None:
    """La pieza más el arranque más largo de cada juego, sin marcas y con margen."""
    scripts = [
        BOOK.default(pid)
        for pid in BOOK.ids()
        if pid.startswith(f"juegos/{game_id}/")
        and pid.rsplit("/", 1)[1] in ("empezar", "presentacion", "arranque")
    ]
    assert scripts, game_id
    for script in scripts:
        joined = f"{FOLLOW_TEXT} {script}"
        assert not brands_in(joined)
        assert len(joined) < 1200, (game_id, len(joined))


# ---------------------------------------------------------------------------
# La pantalla y la vista en vivo, retenidas y soltadas
# ---------------------------------------------------------------------------


async def test_al_soltar_sale_start_con_el_ultimo_estado_y_la_vista_en_vivo() -> None:
    manager, _, screen, _, vision, game = await held_manager()
    await manager.start(TimedGame.id, "voice", ask_follow=True)
    hidden = screen.hidden
    ok, _ = await manager.panel_control(CONTROL_FOLLOW)
    assert ok and not manager.following
    msgs = screen.game_msgs()
    # ``start`` con sus datos y solo el último estado fijo; lo suelto no se guarda.
    assert [m["event"] for m in msgs] == ["start", "round"]
    assert msgs[0]["data"] == {"title": TimedGame.title, "rounds": 3}
    assert msgs[1]["data"] == {"index": 2}
    assert screen.sticky[STICKY_START] is msgs[0] and screen.sticky[STICKY_STATE] is msgs[1]
    assert screen.hidden == hidden + 1
    assert vision.preview.starts == [(TimedGame.id, True)]
    await settle()
    assert game.went == [True]
    # Ya suelta, todo va directo.
    await game.host.send("round", {"index": 3})
    assert screen.game_msgs()[-1]["data"] == {"index": 3}


async def test_si_para_la_vista_antes_de_soltar_no_se_enciende() -> None:
    manager, _, _, _, vision, game = await held_manager()
    await manager.start(TimedGame.id, "voice", ask_follow=True)
    await game.host.preview.stop(TimedGame.id)
    await manager.panel_control(CONTROL_FOLLOW)
    assert vision.preview.starts == []


async def test_terminar_mientras_se_pregunta_no_enseña_nada() -> None:
    manager, engine, screen, _, vision, game = await held_manager()
    registry = build_default_registry(include_look=False, games=[TimedGame])
    await registry.execute("start_game", {"juego": TimedGame.id}, ctx(manager))
    result = await registry.execute("stop_game", {}, ctx(manager))
    assert "Juego terminado" in result.text
    assert game.ending_asked == 0  # no llegó a salir: no hay final que enseñar
    assert screen.game_msgs() == [] and not screen.sticky
    assert vision.preview.starts == [] and not vision.stream.owners
    assert not manager.active and not manager.following
    assert any("ha terminado" in text for text in engine.instructions)


# ---------------------------------------------------------------------------
# Las cuatro formas de soltarla
# ---------------------------------------------------------------------------


async def test_suelta_con_ya_nos_sigue_en_el_panel() -> None:
    manager, engine, screen, _, _, _ = await held_manager()
    await manager.start(TimedGame.id, "voice", ask_follow=True)
    controls = manager.snapshot()["controls"]
    assert controls[0] == {"id": CONTROL_FOLLOW, "label": "Ya nos sigue"}
    ok, message = await manager.panel_control(CONTROL_FOLLOW)
    assert ok and message == "Hecho."
    await settle()
    assert engine.spoken[-1] == FOLLOW_PANEL_TEXT.format(spoken=TimedGame.spoken)
    assert screen.game_msgs("start")
    assert CONTROL_FOLLOW not in [c["id"] for c in manager.snapshot()["controls"]]
    ok, _ = await manager.panel_control(CONTROL_FOLLOW)
    assert not ok  # ya estaba fuera


async def test_suelta_con_una_jugada_delegada() -> None:
    manager, _, screen, _, _, game = await held_manager()
    registry = build_default_registry(include_look=False, games=[TimedGame])
    await registry.execute("start_game", {"juego": TimedGame.id}, ctx(manager))
    result = await registry.execute("cronometro_jugada", {"jugada": "uno"}, ctx(manager))
    assert result.text == "PARA SONIA: Jugada apuntada."
    assert game.plays == ["uno"] and not manager.following
    assert screen.game_msgs("start")


async def test_suelta_si_vuelve_a_delegar_start_game() -> None:
    manager, _, screen, _, _, _ = await held_manager()
    registry = build_default_registry(include_look=False, games=[TimedGame])
    await registry.execute("start_game", {"juego": TimedGame.id}, ctx(manager))
    await registry.execute("start_game", {"juego": TimedGame.id}, ctx(manager))
    assert not manager.following and screen.game_msgs("start")


async def test_suelta_tras_el_turno_del_visitante_y_una_frase_de_sonia() -> None:
    manager, _, screen, clock, _, game = await held_manager()
    since = clock()
    await manager.start(TimedGame.id, "voice", ask_follow=True)
    # Sonia pregunta: su frase no suelta nada todavía.
    await manager.on_assistant_text("¿Ya sigues a Sonnet Code?", True)
    assert manager.following
    # El final del turno que pidió el juego (empezó antes) no cuenta.
    clock.advance(2)
    manager.on_user_turn_end(clock(), since - 3)
    await manager.on_assistant_text("Escanea el QR.", True)
    assert manager.following
    # Contesta y, al terminar Sonia su frase siguiente, sale.
    clock.advance(3)
    manager.on_user_turn_end(clock(), clock() - 1)
    await manager.on_assistant_text("¡Genial! Vamos con", False)
    assert manager.following
    await manager.on_assistant_text("¡Genial! Vamos con el cronómetro.", True)
    assert not manager.following and screen.game_msgs("start")
    await settle()
    assert game.went == [True]


async def test_suelta_sola_a_los_45_segundos() -> None:
    manager, _, screen, clock, _, game = await held_manager()
    await manager.start(TimedGame.id, "voice", ask_follow=True)
    clock.advance(FOLLOW_GRACE_S - 1)
    await manager.tick(clock())
    assert manager.following and screen.game_msgs() == []
    clock.advance(1)
    await manager.tick(clock())
    assert not manager.following and screen.game_msgs("start")
    await settle()
    assert game.went == [True]


async def test_queda_en_el_registro_que_la_solto(caplog: pytest.LogCaptureFixture) -> None:
    manager, _, _, _, _, _ = await held_manager()
    await manager.start(TimedGame.id, "voice", ask_follow=True)
    with caplog.at_level("INFO", logger="sonia.games.manager"):
        await manager.panel_control(CONTROL_FOLLOW)
    assert "sale en pantalla («Ya nos sigue» en el panel)" in caplog.text


# ---------------------------------------------------------------------------
# Sin abandono ni empujones mientras se pregunta
# ---------------------------------------------------------------------------


async def test_sin_abandono_ni_empujones_mientras_se_pregunta() -> None:
    manager, engine, _, clock, _, _ = await held_manager(abandon_seconds=10.0, nudge_seconds=0.5)
    await manager.start(TimedGame.id, "voice", ask_follow=True)
    game = manager.current
    assert game is not None
    game.nudge = lambda: "TRUCO: delega la jugada."  # type: ignore[method-assign]
    clock.advance(30)
    manager.on_user_turn_end(clock(), clock() - 1)
    clock.advance(5)
    await manager.tick(clock())
    await settle()
    assert manager.active and manager.following
    assert not any("TRUCO" in text for text in engine.spoken)
    # Al soltarla, el abandono cuenta desde ese momento.
    clock.advance(FOLLOW_GRACE_S)
    await manager.tick(clock())
    assert not manager.following
    clock.advance(5)
    await manager.tick(clock())
    assert manager.active
    clock.advance(6)
    await manager.tick(clock())
    assert not manager.active


# ---------------------------------------------------------------------------
# wait_go en los juegos con tiempos
# ---------------------------------------------------------------------------


async def test_wait_go_sin_retencion_vuelve_al_momento() -> None:
    manager, _, _, _, _, game = await held_manager()
    assert await manager.wait_go(TimedGame.id) is False
    await manager.start(TimedGame.id, "voice", ask_follow=True)
    waiter = asyncio.create_task(game.host.wait_go())
    await settle()
    assert not waiter.done()
    await manager.panel_control(CONTROL_FOLLOW)
    assert await waiter is True


@pytest.mark.parametrize("module", ["poses", "ppt"])
async def test_simon_dice_y_ppt_esperan_a_soltar_antes_de_su_primer_paso(module: str) -> None:
    if module == "poses":
        from sonia.games.poses.game import PosesGame as cls
    else:
        from sonia.games.ppt.game import PptGame as cls  # type: ignore[assignment]
    game, host = make_game(cls)
    host.held = asyncio.Event()
    await game.start("voice", {})
    for _ in range(20):
        await asyncio.sleep(0)
    assert host.waited_go == 1
    # Mientras espera no corre su reloj: ni avisos ni la cuenta.
    assert host.spoken == [] and host.fixed == []
    host.held.set()
    for _ in range(5):
        await asyncio.sleep(0)
    for task in host.tasks:
        task.cancel()
    await asyncio.gather(*host.tasks, return_exceptions=True)


async def test_la_busqueda_cuenta_la_primera_ronda_desde_que_sale() -> None:
    game, host = make_game(BusquedaGame)
    host.held = asyncio.Event()
    await game.start("voice", {})
    await settle()
    assert host.waited_go == 1
    host.clock.advance(60)
    host.held.set()
    await settle()
    await game.tick(host.now())
    assert not host.events("go")  # el tope de la primera ronda cuenta desde que sale
    host.clock.advance(READY_CAP_FIRST_S)
    await game.tick(host.now())
    assert host.events("go") or game.snapshot()["phase"] == "running"
    for task in host.tasks:
        task.cancel()
    await asyncio.gather(*host.tasks, return_exceptions=True)


async def test_la_ruleta_cuenta_su_primera_vuelta_desde_que_sale() -> None:
    game, host = make_game(RuletaGame)
    host.held = asyncio.Event()
    await game.start("voice", {})
    await settle()
    host.clock.advance(60)
    host.held.set()
    await settle()
    await game.tick(host.now())
    assert game.snapshot()["phase"] == "spinning"
    host.clock.advance(SPIN_SECONDS + SPIN_GRACE_S)
    await game.tick(host.now())
    assert game.snapshot()["phase"] != "spinning"
    for task in host.tasks:
        task.cancel()
    await asyncio.gather(*host.tasks, return_exceptions=True)
