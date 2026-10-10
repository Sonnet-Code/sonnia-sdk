"""El modelo de poses desde el panel (``games_pose_model``): ``GameManager.set_pose_model``."""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from sonia.games import Game, normalize_pose_model
from sonia.games.manager import GameManager
from tests.games.fakes import (
    FakeEngine,
    FakePoses,
    FakeScreen,
    FakeVision,
    game_settings,
    make_manager,
)


class PosesGame(Game):
    id: ClassVar[str] = "posturas"
    title: ClassVar[str] = "Posturas"
    spoken: ClassVar[str] = "las posturas"
    settings_key: ClassVar[str] = "poses"
    needs: ClassVar[frozenset[str]] = frozenset({"camera", "poses"})


class SwitchablePoses(FakePoses):
    """Un detector falso que admite ``set_variant``, como ``YoloPoseDetector``."""

    def __init__(self, variant: str = "n", *, fail: bool = False) -> None:
        super().__init__()
        self.variant = variant
        self.fail = fail
        self.asked: list[str] = []

    def set_variant(self, variant: str) -> None:
        self.asked.append(variant)
        if self.fail:
            raise RuntimeError("roto")
        self.variant = variant


async def manager_with(poses: FakePoses, **settings: Any) -> GameManager:
    vision = FakeVision()
    vision.poses = poses
    config = game_settings()
    for key, value in settings.items():
        setattr(config.games.poses, key, value)
    manager, _, _, _ = await make_manager([PosesGame], vision=vision, settings=config)
    return manager


def test_normalize_pose_model() -> None:
    assert normalize_pose_model("n") == "n"
    assert normalize_pose_model(" S ") == "s"
    for raw in ("", "m", "ligero", None, 3, ["s"]):
        assert normalize_pose_model(raw) is None


async def test_sin_un_detector_que_cambie_no_hay_selector() -> None:
    manager, _, _, _ = await make_manager([PosesGame])
    assert manager.snapshot()["pose_model"] is None
    assert "game_pose_model" not in manager.capabilities()
    manager.set_pose_model("s")  # no hace nada ni lanza


async def test_el_panel_cambia_el_modelo_de_poses() -> None:
    poses = SwitchablePoses()
    manager = await manager_with(poses)
    assert manager.snapshot()["pose_model"] == {
        "current": "n",
        "default": "n",
        "options": ["n", "s"],
    }
    assert "game_pose_model" in manager.capabilities()

    manager.set_pose_model("s")
    assert poses.asked == ["s"]
    assert manager.snapshot()["pose_model"]["current"] == "s"
    # None (o algo que no es n ni s) vuelve al de GAME_POSES_MODEL.
    manager.set_pose_model(None)
    manager.set_pose_model("xl")
    assert poses.asked == ["s", "n", "n"]
    assert manager.snapshot()["pose_model"]["current"] == "n"


async def test_el_de_por_defecto_es_el_de_game_poses_model() -> None:
    poses = SwitchablePoses("s")
    manager = await manager_with(poses, model="s")
    assert manager.snapshot()["pose_model"] == {
        "current": "s",
        "default": "s",
        "options": ["n", "s"],
    }
    manager.set_pose_model("n")
    manager.set_pose_model(None)
    assert poses.asked == ["n", "s"]


async def test_lo_pedido_antes_de_montar_la_vision_se_aplica_al_llegar() -> None:
    manager = GameManager(
        game_settings(), engine=FakeEngine(), screen=FakeScreen(), games=[PosesGame]
    )
    manager.set_pose_model("s")  # aún sin visión: se guarda
    poses = SwitchablePoses()
    vision = FakeVision()
    vision.poses = poses
    manager.attach_vision(vision.game_vision())
    assert poses.asked == ["s"]


async def test_si_el_detector_falla_no_se_rompe_nada(caplog: pytest.LogCaptureFixture) -> None:
    poses = SwitchablePoses(fail=True)
    manager = await manager_with(poses)
    manager.set_pose_model("s")
    assert poses.asked == ["s"]
    assert "No se pudo cambiar el modelo de poses" in caplog.text
    assert manager.snapshot()["pose_model"]["current"] == "n"
