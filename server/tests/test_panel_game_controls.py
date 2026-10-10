"""Pruebas de «Control del juego» en el panel (acción ``game_control``): llevar a mano la
partida en marcha por si falla la voz o la cámara (``docs/juegos.md``, «Control a mano
desde el panel»).

Panel, motor y hub de verdad contra el GPT-Live falso (``make_panel_rig``) con un juego de
mentira que tiene sus controles: nada llama a APIs reales ni usa la cámara.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sonia.games import GameError
from sonia.games.manager import PANEL_CONTROL_TEXT
from sonia.panel.control import GAME_CONTROL_VALUE_MAX_LEN
from sonia.panel.server import STATIC_DIR
from sonia.ws import protocol as p
from tests.test_live import wait_until
from tests.test_panel import PanelRig, make_panel_rig
from tests.test_panel_games import QuizGame, games_status, unity_hello, write_app_bank

SOLVED_SCRIPT = "ACIERTO: felicítale por la respuesta."


class ControlQuiz(QuizGame):
    """El quiz de prueba con sus controles a mano: «Acertó» mientras no está resuelta y un
    campo para escribir la respuesta del visitante."""

    solved = False

    async def start(self, source: str, options: dict[str, Any]) -> str:
        self.solved = False
        self.typed: list[str] = []
        return await super().start(source, options)

    def panel_controls(self) -> list[dict[str, Any]]:
        if self.solved:
            return []
        return [
            {"id": "right", "label": "Acertó"},
            {"id": "answer", "label": "Responder", "kind": "text", "placeholder": "Dart"},
        ]

    async def panel_control(self, control: str, value: str) -> str:
        if self.solved:
            raise GameError("La pregunta ya está resuelta.")
        if control == "answer":
            if not value:
                raise GameError("Escribe la respuesta del visitante.")
            self.typed.append(value)
            return f"El visitante responde «{value}»."
        if control != "right":
            raise GameError("Ese control no está disponible ahora.")
        self.solved = True
        await self.host.send("result", {"correct": True})
        return SOLVED_SCRIPT


def control_ids(rig: PanelRig) -> list[str]:
    return [c["id"] for c in games_status(rig)["controls"]]


def game_events(rig: PanelRig, event: str) -> list[dict[str, Any]]:
    return [m for m in rig.rec.of_type(p.MSG_GAME) if m["event"] == event]


async def start_quiz(rig: PanelRig) -> Any:
    conn = await rig.conn()
    await unity_hello(rig, ["quiz"])
    ok, message = await rig.control.act("game_start", {"game": "quiz"})
    assert ok, message
    await conn.wait_type("session.commentary.append")
    return conn


async def test_los_controles_mueven_el_juego_y_sonia_lo_cuenta(tmp_path: Path) -> None:
    write_app_bank(tmp_path)
    async with make_panel_rig(tmp_path, games=[ControlQuiz]) as rig:
        assert "game_controls" in rig.control.capabilities
        # Sin juego en marcha no hay controles ni se pueden usar.
        assert games_status(rig)["controls"] == []
        ok, message = await rig.control.act("game_control", {"control": "right"})
        assert not ok and "No hay ningún juego" in message

        conn = await start_quiz(rig)
        controls = games_status(rig)["controls"]
        assert [c["id"] for c in controls] == ["right", "answer", "restart", "stop"]
        assert controls[1] == {
            "id": "answer",
            "label": "Responder",
            "kind": "text",
            "placeholder": "Dart",
        }

        # Un campo de texto: el texto llega al juego sin los espacios de más.
        ok, message = await rig.control.act(
            "game_control", {"control": "answer", "value": " Dart "}
        )
        assert ok, message
        manager = rig.engine.games
        assert manager is not None and manager.current is not None
        assert manager.current.typed == ["Dart"]
        # Lo que el juego rechaza vuelve al equipo con su mensaje.
        ok, message = await rig.control.act("game_control", {"control": "answer"})
        assert not ok and "Escribe la respuesta" in message

        # «Acertó» mueve la pantalla y Sonia lo cuenta en cuanto calla, sin hablar del panel.
        ok, message = await rig.control.act("game_control", {"control": "right"})
        assert ok, message
        await rig.rec.wait_for(lambda msgs: bool(game_events(rig, "result")))
        assert game_events(rig, "result")[-1]["data"] == {"correct": True}

        def solved_said(msgs: list[dict[str, Any]]) -> bool:
            return any(
                SOLVED_SCRIPT in m.get("content", "")
                for m in msgs
                if m.get("type") == "session.commentary.append"
            )

        # Cada guion espera a que Sonia calle (hasta 3 s con el GPT-Live falso, que no contesta).
        await conn.wait_for(solved_said, limit=8.0)
        spoken = [
            m["content"]
            for m in conn.of_type("session.commentary.append")
            if SOLVED_SCRIPT in m["content"]
        ]
        assert spoken == [PANEL_CONTROL_TEXT + SOLVED_SCRIPT]

        # Resuelta, solo quedan los de todos los juegos y lo de antes ya no vale.
        assert control_ids(rig) == ["restart", "stop"]
        ok, message = await rig.control.act("game_control", {"control": "right"})
        assert not ok and "ya está resuelta" in message


async def test_reiniciar_y_terminar_desde_el_control_del_juego(tmp_path: Path) -> None:
    write_app_bank(tmp_path)
    async with make_panel_rig(tmp_path, games=[ControlQuiz]) as rig:
        await start_quiz(rig)
        ok, message = await rig.control.act("game_control", {"control": "right"})
        assert ok, message
        assert control_ids(rig) == ["restart", "stop"]

        # «Reiniciar»: la misma partida desde cero, con sus controles otra vez.
        ok, message = await rig.control.act("game_control", {"control": "restart"})
        assert ok and "en marcha" in message, message
        await wait_until(lambda: len(game_events(rig, "start")) == 2)
        assert control_ids(rig) == ["right", "answer", "restart", "stop"]

        # «Terminar»: como «Terminar juego».
        ok, message = await rig.control.act("game_control", {"control": "stop"})
        assert ok and "terminado" in message, message
        await rig.rec.wait_for(lambda msgs: bool(game_events(rig, "end")))
        assert games_status(rig)["active"] is None and games_status(rig)["controls"] == []
        ok, message = await rig.control.act("game_control", {"control": "stop"})
        assert not ok and "No hay ningún juego" in message


async def test_el_control_del_juego_pide_lo_mismo_que_empezar(tmp_path: Path) -> None:
    write_app_bank(tmp_path)
    async with make_panel_rig(tmp_path, games=[ControlQuiz]) as rig:
        await start_quiz(rig)
        # Sin pasar de verdad por el modo debug (cerraría la sesión y el juego): solo lo
        # que mira el panel antes de mover la partida.
        rig.control.state.debug = True
        for control in ("right", "restart"):
            ok, message = await rig.control.act("game_control", {"control": control})
            assert not ok and "debug" in message, (control, message)
        # Terminar vale siempre, como «Terminar juego».
        ok, message = await rig.control.act("game_control", {"control": "stop"})
        assert ok and "terminado" in message, message
        rig.control.state.debug = False


async def test_el_control_del_juego_valida_lo_que_llega(tmp_path: Path) -> None:
    write_app_bank(tmp_path)
    async with make_panel_rig(tmp_path, games=[ControlQuiz]) as rig:
        await start_quiz(rig)
        too_long = "x" * (GAME_CONTROL_VALUE_MAX_LEN + 1)
        cases: list[tuple[dict[str, Any], str]] = [
            ({}, "Falta el control"),
            ({"control": "  "}, "Falta el control"),
            ({"control": 3}, "Falta el control"),
            ({"control": "answer", "value": 5}, "tiene que ser texto"),
            ({"control": "answer", "value": too_long}, "Demasiado largo"),
            ({"control": "nada"}, "no está disponible"),
        ]
        for params, expected in cases:
            ok, message = await rig.control.act("game_control", params)
            assert not ok and expected in message, (params, message)
        assert games_status(rig)["active"] == "quiz"


async def test_sin_juegos_no_hay_control_del_juego(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path, games=[]) as rig:
        assert "game_controls" not in rig.control.capabilities
        ok, message = await rig.control.act("game_control", {"control": "stop"})
        assert not ok and "no tiene juegos" in message


def test_el_panel_pinta_los_controles_del_juego() -> None:
    """La sección «Control del juego» lleva su capacidad (las Sonnias anteriores no la
    tienen) y su nota, y el panel manda ``game_control`` con lo que pinta."""
    page = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    script = (STATIC_DIR / "panel.js").read_text(encoding="utf-8")
    assert re.search(r'id="game-controls"[^>]*data-cap="game_controls"', page)
    assert 'data-cap-note="game_controls"' in page
    assert 'id="game-control-list"' in page
    # «Terminar juego» sigue para las Sonnias sin controles a mano.
    assert re.search(r'id="game-stop-btn"[^>]*data-cap="games"', page)
    assert '"game_control"' in script
    assert '"data-cap": "game_controls"' in script
    assert f"const GAME_CONTROL_MAX_CHARS = {GAME_CONTROL_VALUE_MAX_LEN};" in script
    # Los que pone el manager para todos se confirman antes de mandarlos.
    assert 'new Set(["restart", "stop"])' in script
