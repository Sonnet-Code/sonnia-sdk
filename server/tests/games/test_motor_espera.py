"""El aviso de espera (``busy``) de un juego dentro del motor: GPT-Live falso, ``Hub`` de
verdad y una Unity de mentira. Sin red ni APIs reales."""

from __future__ import annotations

from pathlib import Path

from sonia.busy import TEXT_GAME, TEXT_THINK
from tests.games.test_motor import games_rig
from tests.test_live import LiveRig, _backend_call


def _screen(rig: LiveRig) -> list[str]:
    """``busy:<texto>`` y ``game:<evento>`` en el orden en que le llegaron a Unity."""
    out = []
    for m in rig.rec.json():
        if m["type"] == "busy":
            out.append(f"busy:{m['text'] if m['on'] else 'off'}")
        elif m["type"] == "game":
            out.append(f"game:{m['event']}")
    return out


async def test_start_game_avisa_hasta_la_primera_pantalla(tmp_path: Path) -> None:
    async with games_rig(tmp_path) as rig:
        assert rig.engine.games is not None
        conn = await rig.conn()
        await _backend_call(conn, "g1", "start_game", {"juego": "sonda"})
        expected = [
            f"busy:{TEXT_THINK}",
            f"busy:{TEXT_GAME}",
            "game:start",
            f"busy:{TEXT_THINK}",
        ]
        await rig.rec.wait_for(lambda _: _screen(rig) == expected)
        # El backend termina la tarea: ya no se espera nada.
        await conn.response_event({"type": "response.created"}, delegation_id="deleg_g1")
        await conn.response_event({"type": "response.completed"}, delegation_id="deleg_g1")
        await rig.rec.wait_for(lambda _: _screen(rig) == [*expected, "busy:off"])
        assert rig.engine.busy_board.keys == ()
