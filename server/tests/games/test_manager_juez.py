"""El juez de las rondas de cámara desde el panel (``games_judge``): ``GameManager.set_judge``."""

from __future__ import annotations

from typing import Any, ClassVar

import numpy as np

from sonia.games import Game, normalize_games_judge
from sonia.games.manager import GameManager
from sonia.vision.contracts import GameVision, JudgeAnswer, JudgeSwitch, PoseVerdict
from sonia.vision.games import NoJudge, SwitchedJudge, SwitchedReferee
from tests.games.fakes import (
    FakeEngine,
    FakeJudge,
    FakeReferee,
    FakeScreen,
    FakeVision,
    game_settings,
    make_manager,
)

VERDICT = PoseVerdict(people=1, counts={"brazos_arriba": 1})


class RoundsGame(Game):
    """Un juego de cámara que, como Simón dice y la búsqueda, mira el juez en cada ronda."""

    id: ClassVar[str] = "rondas"
    title: ClassVar[str] = "Rondas"
    spoken: ClassVar[str] = "las rondas"
    settings_key: ClassVar[str] = "poses"
    needs: ClassVar[frozenset[str]] = frozenset({"camera"})

    async def start(self, source: str, options: dict[str, Any]) -> str:
        return "Empieza."

    async def round(self) -> PoseVerdict | None:
        referee = self.host.referee
        if not referee.available:
            return None
        return await referee.poses(np.zeros((32, 32, 3), dtype=np.uint8))


class SwitchVision(FakeVision):
    """La visión falsa con el conmutador del juez, como la monta ``build_game_vision``."""

    def __init__(self, app_mode: str = "gemini", *, gemini: bool = True) -> None:
        self.gemini_referee = FakeReferee(poses=[VERDICT, VERDICT, VERDICT])
        self.gemini_judge = FakeJudge([JudgeAnswer(seen=True, what="una taza")])
        super().__init__(judge=FakeJudge())
        self.switch = JudgeSwitch(app_mode, gemini=gemini)

    def game_vision(self) -> GameVision:
        vision = super().game_vision()
        vision.referee = SwitchedReferee(self.switch, self.gemini_referee)
        vision.judge = SwitchedJudge(self.switch, self.gemini_judge, NoJudge())
        vision.judge_switch = self.switch
        return vision


def test_normalize_games_judge() -> None:
    assert normalize_games_judge("gemini") == "gemini"
    assert normalize_games_judge(" LOCAL ") == "local"
    for raw in ("", "app", "luna", None, 3, ["local"]):
        assert normalize_games_judge(raw) is None


async def test_sin_conmutador_no_hay_selector() -> None:
    manager, _, _, _ = await make_manager([RoundsGame])
    assert manager.snapshot()["judge"] is None
    assert "game_judge" not in manager.capabilities()
    manager.set_judge("local")  # no hace nada ni lanza


async def test_el_panel_cambia_el_juez() -> None:
    vision = SwitchVision()
    manager, _, _, _ = await make_manager([RoundsGame], vision=vision)
    assert "game_judge" in manager.capabilities()
    assert manager.snapshot()["judge"] == {
        "mode": "gemini",
        "app": "gemini",
        "requested": None,
        "gemini": True,
    }
    manager.set_judge("local")
    assert manager.snapshot()["judge"] == {
        "mode": "local",
        "app": "gemini",
        "requested": "local",
        "gemini": True,
    }
    assert not manager.vision.referee.available
    # La búsqueda en local, sin modelo de visión: no se ofrece.
    assert not manager.vision.judge.available
    # None (o algo que no es un modo) vuelve al de GAMES_JUDGE.
    manager.set_judge("xx")
    assert manager.snapshot()["judge"]["mode"] == "gemini"
    assert manager.snapshot()["judge"]["requested"] is None


async def test_el_cambio_vale_a_media_partida() -> None:
    vision = SwitchVision()
    manager, _, _, _ = await make_manager([RoundsGame], vision=vision)
    ok, _ = await manager.start("rondas", "voice")
    assert ok
    game = manager.game("rondas")
    assert isinstance(game, RoundsGame)
    assert await game.round() == VERDICT
    # Gemini va lento: el equipo pone Local desde el panel con la partida en marcha.
    manager.set_judge("local")
    assert await game.round() is None
    assert len(vision.gemini_referee.photos) == 1
    assert manager.active
    # Y de vuelta al de la app, en la ronda siguiente.
    manager.set_judge(None)
    assert await game.round() == VERDICT
    assert len(vision.gemini_referee.photos) == 2


async def test_sin_gemini_el_estado_lo_dice() -> None:
    vision = SwitchVision(gemini=False)
    manager, _, _, _ = await make_manager([RoundsGame], vision=vision)
    manager.set_judge("gemini")
    assert manager.snapshot()["judge"] == {
        "mode": "local",
        "app": "gemini",
        "requested": "gemini",
        "gemini": False,
    }
    assert not manager.vision.referee.available


async def test_lo_pedido_antes_de_montar_la_vision_se_aplica_al_llegar() -> None:
    manager = GameManager(
        game_settings(), engine=FakeEngine(), screen=FakeScreen(), games=[RoundsGame]
    )
    manager.set_judge("local")  # aún sin visión: se guarda
    vision = SwitchVision()
    manager.attach_vision(vision.game_vision())
    assert vision.switch.mode == "local"
    assert manager.snapshot()["judge"]["requested"] == "local"
