"""Partidas al azar de la búsqueda relámpago contra el ``GameManager``.

El principio del stand es que nada de lo que pase en una partida tumba el proceso ni la deja
colgada ocho horas seguidas. Aquí una Sonia y un juez caprichosos (con semilla, así que
repetibles) hacen de todo: el juez ve, no ve, no contesta o contesta algo raro; Sonia habla y
calla cuando quiere; alguien delega ``busqueda_check`` a destiempo, grita, se queda mudo o se
cae la sesión. Pase lo que pase, tienen que cumplirse unas invariantes: ningún error en el
registro, nunca dos miradas a la vez, cada ronda se cuenta una sola vez, el estado va en JSON y,
al terminar, la cámara y la pantalla quedan sueltas con un solo ``end``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any

import pytest

from sonia.actions import build_default_registry
from sonia.games.busqueda.game import BusquedaGame
from sonia.types import ActionContext
from sonia.vision.contracts import JudgeAnswer
from tests.games.fakes import FakeJudge, FakeVision, game_settings, make_manager
from tests.games.test_busqueda import MISS, SEEN, quiesce

WHATS = ["botella azul", "un hombre con camisa azul", "", "x" * 100, "<b>hola</b>", "llaves rojas"]


class ChaosJudge(FakeJudge):
    """Ve, no ve, no contesta o tarda, al azar, y lleva la cuenta de las miradas a la vez."""

    def __init__(self, rng: random.Random, *, see: float, silent: float) -> None:
        super().__init__()
        self.rng = rng
        self.see = see  # probabilidad de ver el objeto en cada mirada
        self.silent = silent  # probabilidad de no contestar
        self.rounds = 0
        self.running = 0
        self.max_running = 0

    def start_round(self, max_calls: int | None) -> None:
        self.rounds += 1

    async def ask(self, question: str) -> JudgeAnswer | None:
        self.questions.append(question)
        self.running += 1
        self.max_running = max(self.max_running, self.running)
        try:
            for _ in range(self.rng.choice([0, 0, 0, 1, 5, 30])):
                await asyncio.sleep(0)
            roll = self.rng.random()
            if roll < self.silent:
                return None
            if roll < self.silent + self.see:
                return JudgeAnswer(seen=True, what=self.rng.choice(WHATS))
            return MISS
        finally:
            self.running -= 1


@pytest.mark.parametrize("seed", range(40))
async def test_partidas_al_azar_nunca_cuelgan_ni_fallan(
    seed: int, caplog: pytest.LogCaptureFixture
) -> None:
    rng = random.Random(seed)
    judge = ChaosJudge(
        rng, see=rng.choice([0.0, 0.03, 0.1, 0.3]), silent=rng.choice([0.0, 0.12, 0.5, 1.0])
    )
    vision = FakeVision(judge=judge)
    recorded = {"¡Ya!", "¡Lo veo!", "¡Tiempo!"} if rng.random() < 0.5 else set()
    # Sin abandono: una partida colgada se vería como una partida que nunca acaba.
    settings = game_settings(
        result_seconds=0.0, final_wait_seconds=0.0, abandon_seconds=1_000_000.0
    )
    manager, engine, screen, clock = await make_manager(
        [BusquedaGame], settings=settings, vision=vision, recorded=recorded, seed=seed
    )
    registry = build_default_registry(include_look=False, games=[BusquedaGame])
    ctx = ActionContext(camera=None, avatar=None, gallery_dir="", extra={"games": manager})

    with caplog.at_level(logging.INFO, logger="sonia"):
        result = await registry.execute(
            "start_game", {"juego": "busqueda", "sigue_a_sonnet_code": True}, ctx
        )
        assert "ronda 1 de 3" in result.text
        game = manager.current
        assert isinstance(game, BusquedaGame)
        stopped_by_test = False

        for _ in range(4_000):
            clock.advance(rng.choice([0.05, 0.05, 0.1, 0.25, 0.5, 1.0]))
            await manager.tick(clock())
            await quiesce()
            if not manager.active:
                break
            roll = rng.random()
            if roll < 0.06:
                engine.quiet = rng.choice([0.0, 0.0, 0.3, 0.8, 2.0, 6.0])
            elif roll < 0.12:
                name = game.snapshot()["object"]
                text = rng.choice([f"¡El primero que me enseñe {name}!", "Dale, dale", name, ""])
                await manager.on_assistant_text(text, rng.random() < 0.3)
            elif roll < 0.17:
                await registry.execute("busqueda_check", {}, ctx)
            elif roll < 0.19:
                manager.on_user_text(clock())
            elif roll < 0.195:
                manager.on_delegation(clock())
            elif roll < 0.1903:
                await manager.stop("panel")
                stopped_by_test = True
            elif roll < 0.1905:
                await manager.on_session_lost()
                stopped_by_test = True

            # Invariantes de cada paso.
            snapshot = game.snapshot()
            assert json.loads(json.dumps(snapshot)) == snapshot
            assert 0 <= snapshot["found"] <= max(snapshot["round"], 0) <= snapshot["rounds"]
            assert judge.max_running <= 1, "dos miradas a la vez"
        else:
            pytest.fail(f"la partida no terminó (fase {game.snapshot()['phase']})")
        await quiesce()

    # Sin errores en el registro (un fallo de una tarea o del juego se anota como error).
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert not errors, [r.getMessage() for r in errors]
    # La partida terminó del todo: cámara y vista en vivo sueltas, nada fijo y un solo end.
    assert not manager.active and screen.replay() == []
    assert not vision.stream.active and not vision.preview.active
    assert len(screen.game_msgs("end")) == 1
    # Cada ronda se cuenta una sola vez y en orden.
    outcomes = [
        m["data"]["index"] for m in screen.game_msgs() if m["event"] in ("found", "timeout")
    ]
    assert outcomes == sorted(set(outcomes)), outcomes
    starts = [m["data"]["index"] for m in screen.game_msgs("round")]
    assert starts == sorted(set(starts)) and starts[:1] == [1]
    # Lo que se le dijo a GPT-Live no se pasó de largo ni se coló lo que dice el modelo.
    for text in [*engine.spoken, *engine.instructions]:
        assert "<b>" not in text and "x" * 50 not in text and "hombre" not in text
    if not stopped_by_test:
        end = screen.game_msgs("end")[-1]["data"]
        assert end["result"] in ("win", "lose", "cancel") and end["total"] == 3
        assert end["found"] == len([1 for m in screen.game_msgs("found")])
    _ = (SEEN, Any)
