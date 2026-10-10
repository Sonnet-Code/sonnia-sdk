"""El juez de las rondas de cámara desde el panel (``games_judge``), sin red.

Se cambia desde el panel local y desde la nube (ajuste compartido, en todas las Sonnias), al
momento, y manda sobre ``GAMES_JUDGE``. La página lo enseña solo en las Sonnias que anuncian
la capacidad ``game_judge``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from sonia.games.manager import GameManager
from sonia.panel.control import SHARED_SETTINGS, PanelState
from sonia.panel.server import STATIC_DIR
from tests.test_panel import make_panel_rig
from tests.test_panel_games import GAMES


class JudgeCalls:
    """``GameManager.set_judge`` y su estado, falsos: apunta los modos que le llegan
    (``None``: el de la app, ``GAMES_JUDGE``) y dice si hay Gemini."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, gemini: bool = True) -> None:
        self.calls: list[str | None] = []
        calls = self.calls
        original = GameManager.snapshot

        def set_judge(manager: GameManager, mode: str | None) -> None:
            calls.append(mode)

        def snapshot(manager: GameManager) -> dict[str, Any]:
            snap = original(manager)
            requested = calls[-1] if calls else None
            snap["judge"] = {
                "mode": (requested or "gemini") if gemini else "local",
                "app": "gemini",
                "requested": requested,
                "gemini": gemini,
            }
            return snap

        monkeypatch.setattr(GameManager, "set_judge", set_judge)
        monkeypatch.setattr(GameManager, "snapshot", snapshot)


async def test_el_juez_se_cambia_desde_el_panel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    judge = JudgeCalls(monkeypatch)
    async with make_panel_rig(tmp_path, games=GAMES) as rig:
        # Al arrancar, el de la app.
        assert judge.calls == [None]
        assert rig.control.status()["games_judge"] is None

        ok, message = await rig.control.act("set_game_judge", {"judge": "local"})
        assert ok and "local" in message and "todas las Sonnias" in message, message
        assert judge.calls[-1] == "local"
        assert rig.control.state.games_judge == "local"
        assert rig.control.shared_settings()["games_judge"] == "local"
        status = rig.control.status()
        assert status["games_judge"] == "local"
        assert status["games"]["judge"]["mode"] == "local"
        assert status["settings_sync"]["pending"] == ["games_judge"]

        ok, message = await rig.control.act("set_game_judge", {"judge": " Gemini "})
        assert ok and "Gemini" in message and "aquí sigue" not in message, message
        assert judge.calls[-1] == "gemini" and rig.control.state.games_judge == "gemini"

        ok, message = await rig.control.act("set_game_judge", {"judge": "luna"})
        assert not ok and judge.calls[-1] == "gemini"
        ok, message = await rig.control.act("set_game_judge", {"judge": 3})
        assert not ok

        # «El de la app» borra el ajuste.
        ok, message = await rig.control.act("set_game_judge", {"judge": ""})
        assert ok and "app" in message
        assert judge.calls[-1] is None and rig.control.state.games_judge is None
        ok, message = await rig.control.act("set_game_judge", {"judge": "app"})
        assert ok and "ya usan" in message
    saved = PanelState.load(tmp_path / "cache" / "panel_state.json")
    assert saved.games_judge is None


async def test_sin_gemini_se_guarda_pero_avisa(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El ajuste es de todas las Sonnias: se guarda aunque esta no tenga Gemini, y lo dice."""
    judge = JudgeCalls(monkeypatch, gemini=False)
    async with make_panel_rig(tmp_path, games=GAMES) as rig:
        ok, message = await rig.control.act("set_game_judge", {"judge": "gemini"})
        assert ok and "aquí sigue en local" in message, message
        assert judge.calls[-1] == "gemini" and rig.control.state.games_judge == "gemini"


async def test_el_juez_llega_de_la_nube_y_sobrevive_al_reinicio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    judge = JudgeCalls(monkeypatch)
    state = PanelState(games_judge="local")
    async with make_panel_rig(tmp_path, games=GAMES, state=state) as rig:
        assert judge.calls == ["local"]
        assert rig.control.status()["games_judge"] == "local"
        values = rig.control.shared_settings()
        changed = await rig.control.apply_cloud_settings(
            {**values, "games_judge": "gemini"}, rev=2, ack=0
        )
        assert changed == ["games_judge"] and judge.calls[-1] == "gemini"
        # Lo que no es un juez se ignora.
        changed = await rig.control.apply_cloud_settings({"games_judge": "luna"}, rev=3, ack=0)
        assert changed == [] and rig.control.state.games_judge == "gemini"
        changed = await rig.control.apply_cloud_settings({"games_judge": None}, rev=4, ack=0)
        assert changed == ["games_judge"] and judge.calls[-1] is None


async def test_el_juez_de_verdad_cambia_con_la_accion(tmp_path: Path) -> None:
    """Sin falsos en el manager: la acción llega al conmutador de la visión de los juegos."""
    from sonia.vision.contracts import JudgeSwitch

    async with make_panel_rig(tmp_path, games=GAMES) as rig:
        games = rig.control._games
        assert games is not None
        switch = JudgeSwitch("gemini", gemini=True)
        games.vision.judge_switch = switch
        assert "game_judge" in rig.control.capabilities
        ok, _ = await rig.control.act("set_game_judge", {"judge": "local"})
        assert ok and switch.mode == "local"
        assert rig.control.status()["games"]["judge"]["mode"] == "local"
        # La nube ya tiene ese cambio (``ack``) y otro panel vuelve al de la app.
        _, seq = rig.control.pending_settings()
        changed = await rig.control.apply_cloud_settings({"games_judge": None}, rev=2, ack=seq)
        assert changed == ["games_judge"] and switch.mode == "gemini"


async def test_sin_juegos_no_se_cambia_el_juez(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path, games=[]) as rig:
        ok, message = await rig.control.act("set_game_judge", {"judge": "local"})
        assert not ok and "no tiene juegos" in message
        assert rig.control.state.games_judge is None


def test_el_juez_es_compartido_y_un_estado_viejo_carga(tmp_path: Path) -> None:
    assert "games_judge" in SHARED_SETTINGS
    path = tmp_path / "panel_state.json"
    # El estado de una Sonnia anterior (sin la clave nueva).
    path.write_text(json.dumps({"mode": "greeter", "games_pose_model": "s"}), encoding="utf-8")
    state = PanelState.load(path)
    assert state.games_judge is None and state.games_pose_model == "s"
    # Lo mal formado en disco no rompe la carga.
    path.write_text(json.dumps({"games_judge": "luna"}), encoding="utf-8")
    assert PanelState.load(path).games_judge is None
    PanelState(games_judge="local").save(path)
    assert PanelState.load(path).games_judge == "local"


def test_el_selector_del_juez_lleva_su_capacidad() -> None:
    """Con una Sonnia anterior (sin ``game_judge``), el selector sale desactivado con su nota."""
    page = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    script = (STATIC_DIR / "panel.js").read_text(encoding="utf-8")
    assert re.search(r'id="game-judge-select"[^>]*data-cap="game_judge"', page)
    assert 'data-cap-note="game_judge"' in page
    assert "Si Gemini va lento o falla, pon Local" in page
    assert '"set_game_judge"' in script
    for value in ("gemini", "local"):
        assert re.search(rf'<option value="{value}">', page), value
