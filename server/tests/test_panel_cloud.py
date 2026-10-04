"""Pruebas de la conexión de Sonia con el panel de Cloudflare, sin red.

El Durable Object es un servidor WebSocket local que imita el contrato de
``docs/panel.md`` ("Conexión de cada Sonia").
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx
import pytest

import sonia.panel.cloud as cloud_module
from sonia.config import PanelSettings
from sonia.panel.cloud import CloudLink
from sonia.panel.control import PanelState
from sonia.panel.events import PanelEvents
from sonia.panel.identity import load_identity
from sonia.panel.logs import LogBuffer
from sonia.panel.server import PanelServer
from tests.test_live import wait_until
from tests.test_panel import make_panel_rig


class FakeRoom:
    """Imita el Durable Object: graba lo que sube cada Sonia y le manda órdenes."""

    def __init__(self, *, close_after_hello: bool = False) -> None:
        self.close_after_hello = close_after_hello
        self.connections = 0
        self.headers: list[dict[str, str]] = []
        self.received: list[dict[str, Any]] = []
        self.ws: Any = None
        self._changed = asyncio.Event()

    async def handler(self, ws: Any) -> None:
        self.connections += 1
        self.headers.append({k.lower(): v for k, v in ws.request.headers.items()})
        self.ws = ws
        with contextlib.suppress(Exception):
            async for raw in ws:
                self.received.append(json.loads(raw))
                self._changed.set()
                if self.close_after_hello and self.received[-1]["type"] == "hello":
                    await ws.close()
                    return

    def of_type(self, kind: str) -> list[dict[str, Any]]:
        return [m for m in self.received if m.get("type") == kind]

    async def wait_for(self, predicate: Callable[[], bool], limit: float = 3.0) -> None:
        async with asyncio.timeout(limit):
            while not predicate():
                self._changed.clear()
                await self._changed.wait()

    async def send(self, msg: dict[str, Any]) -> None:
        await self.ws.send(json.dumps(msg))


@contextlib.asynccontextmanager
async def running_room(room: FakeRoom) -> AsyncIterator[Any]:
    from websockets.asyncio.client import connect as client_connect
    from websockets.asyncio.server import serve

    async with serve(room.handler, "127.0.0.1", 0) as srv:
        port = srv.sockets[0].getsockname()[1]

        async def connect(url: str, headers: dict[str, str]) -> Any:
            return await client_connect(f"ws://127.0.0.1:{port}", additional_headers=headers)

        yield connect


@contextlib.asynccontextmanager
async def linked(
    tmp_path: Path, room: FakeRoom, **panel: Any
) -> AsyncIterator[tuple[Any, CloudLink]]:
    async with make_panel_rig(tmp_path) as rig, running_room(room) as connect:
        settings = rig.settings.panel.model_copy(
            update={"cloud_token": "token-de-prueba", "instance_name": "Mini PC Pabellón", **panel}
        )
        identity = load_identity(settings, host="mini-pc")
        events = PanelEvents(rig.hub, None)
        link = CloudLink(settings, rig.control, events, identity, connect=connect)
        task = asyncio.create_task(link.run())
        try:
            yield rig, link
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_se_presenta_con_token_identidad_estado_e_historial(tmp_path: Path) -> None:
    room = FakeRoom()
    async with linked(tmp_path, room) as (_, link):
        await room.wait_for(lambda: bool(room.of_type("hello")))
        headers = room.headers[0]
        assert headers["authorization"] == "Bearer token-de-prueba"
        assert headers["x-sonia-instance"].startswith("mini-pc-")
        assert unquote(headers["x-sonia-name"]) == "Mini PC Pabellón"
        hello = room.of_type("hello")[0]
        assert hello["instance"]["name"] == "Mini PC Pabellón"
        assert hello["instance"]["id"] == headers["x-sonia-instance"]
        assert hello["instance"]["engine"] == "live"
        assert hello["status"]["mode"] == "conversation"
        assert set(hello["history"]) == {"messages", "logs"}
        assert isinstance(hello["gallery"], list)
        await wait_until(lambda: link.connected)


async def test_las_acciones_bajan_y_el_resultado_sube(tmp_path: Path) -> None:
    room = FakeRoom()
    async with linked(tmp_path, room) as (rig, _):
        await rig.conn()
        await room.wait_for(lambda: bool(room.of_type("hello")))
        await room.send(
            {"type": "action", "request_id": "r1", "action": "set_mode", "params": {"mode": "away"}}
        )
        await room.wait_for(lambda: bool(room.of_type("result")))
        result = room.of_type("result")[0]
        assert result["request_id"] == "r1" and result["ok"] is True
        assert rig.control.mode == "away"
        # El estado nuevo sube al momento, aunque nadie esté mirando esta Sonia.
        await room.wait_for(
            lambda: any(m["status"]["mode"] == "away" for m in room.of_type("status"))
        )
        await room.send({"type": "action", "request_id": "r2", "action": "volar", "params": {}})
        await room.wait_for(lambda: len(room.of_type("result")) == 2)
        assert room.of_type("result")[1] == {
            "type": "result",
            "request_id": "r2",
            "ok": False,
            "message": "Acción desconocida: volar",
        }


async def test_con_alguien_mirando_el_estado_sube_mas_a_menudo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cloud_module, "FAST_STATUS_S", 0.05)
    monkeypatch.setattr(cloud_module, "SLOW_STATUS_S", 5.0)
    room = FakeRoom()
    async with linked(tmp_path, room):
        await room.wait_for(lambda: bool(room.of_type("hello")))
        await asyncio.sleep(0.3)
        assert len(room.of_type("status")) == 0
        await room.send({"type": "viewers", "count": 1})
        await room.wait_for(lambda: len(room.of_type("status")) >= 3)
        await room.send({"type": "sync"})
        await room.wait_for(lambda: len(room.of_type("hello")) == 2)


async def test_la_conversacion_y_el_registro_suben_al_momento(tmp_path: Path) -> None:
    room = FakeRoom()
    async with linked(tmp_path, room) as (rig, _):
        conn = await rig.conn()
        await room.wait_for(lambda: bool(room.of_type("hello")))
        await conn.hear("Hola Sonia")
        await room.wait_for(
            lambda: any(m["message"].get("type") == "transcript" for m in room.of_type("message"))
        )
        transcript = next(
            m["message"] for m in room.of_type("message") if m["message"]["type"] == "transcript"
        )
        assert transcript["role"] == "user" and "time" in transcript


async def test_reconecta_si_cloudflare_corta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cloud_module, "RECONNECT_MIN_S", 0.05)
    room = FakeRoom(close_after_hello=True)
    async with linked(tmp_path, room):
        await room.wait_for(lambda: room.connections >= 3)


async def test_sin_token_no_se_conecta(tmp_path: Path) -> None:
    room = FakeRoom()
    async with linked(tmp_path, room, cloud_token="") as (_, link):
        await asyncio.sleep(0.2)
        assert not link.enabled and room.connections == 0


async def test_los_ajustes_cambiados_suben_a_la_nube_y_se_confirman(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cloud_module, "SETTINGS_DEBOUNCE_S", 0.05)
    room = FakeRoom()
    async with linked(tmp_path, room) as (rig, _):
        await room.wait_for(lambda: bool(room.of_type("hello")))
        hello = room.of_type("hello")[0]["settings"]
        assert hello["pending"] == [] and hello["seq"] == 0
        assert hello["values"]["volume"] == 1.0
        assert hello["values"]["tuning"]["mouth"]["open"] == 1.0
        assert "mode" not in hello["values"] and "debug" not in hello["values"]
        await room.send({"type": "settings", "settings": hello["values"], "rev": 1, "ack": 0})
        await wait_until(lambda: rig.control.status()["settings_sync"]["synced"])
        # Da igual que el cambio venga del panel local o del de Cloudflare: sube.
        await rig.control.act("set_volume", {"value": 0.6})
        await rig.control.act("set_tuning", {"mouth": {"open": 1.3}})
        await room.wait_for(lambda: any("tuning" in m["changes"] for m in room.of_type("settings")))
        up = room.of_type("settings")[-1]
        assert up["changes"]["volume"] == 0.6
        assert up["changes"]["tuning"]["mouth"]["open"] == 1.3
        assert up["seq"] == 2
        sync = rig.control.status()["settings_sync"]
        assert sync["cloud"] == "online" and sync["pending"] == ["tuning", "volume"]
        values = {**hello["values"], **up["changes"]}
        await room.send({"type": "settings", "settings": values, "rev": 2, "ack": 2})
        await wait_until(lambda: rig.control.status()["settings_sync"]["pending"] == [])
        assert rig.control.status()["settings_sync"]["rev"] == 2
    assert PanelState.load(tmp_path / "cache" / "panel_state.json").pending_settings == []


async def test_los_ajustes_de_la_nube_se_aplican_sin_pisar_lo_cambiado_aqui(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cloud_module, "SETTINGS_DEBOUNCE_S", 30.0)  # que no suba aún
    room = FakeRoom()
    async with linked(tmp_path, room) as (rig, _):
        await room.wait_for(lambda: bool(room.of_type("hello")))
        values = room.of_type("hello")[0]["settings"]["values"]
        # Cambiado aquí y todavía en camino hacia la nube (cambio número 1).
        await rig.control.act("set_subtitles", {"enabled": False})
        cloud = {
            **values,
            "volume": 0.4,
            "subtitles": True,
            "notes": "La charla de IA es en la sala B.",
            "tuning": {"camera": {"zoom": 1.5}},
            "desconocido": 1,
        }
        await room.send({"type": "settings", "settings": cloud, "rev": 7, "ack": 0})
        await wait_until(lambda: rig.control.status()["volume"] == 0.4)
        status = rig.control.status()
        assert status["subtitles"] is False  # lo de aquí es más nuevo
        assert status["notes"] == "La charla de IA es en la sala B."
        assert status["tuning"]["camera"]["zoom"] == 1.5
        assert status["tuning"]["mouth"]["open"] == 1.0
        assert status["settings_sync"]["pending"] == ["subtitles"]
        assert status["settings_sync"]["rev"] == 7
        await rig.rec.wait_for(
            lambda msgs: any(m.get("value") == 0.4 for m in rig.rec.of_type("set_volume", msgs))
        )
        await rig.rec.wait_for(
            lambda msgs: any(
                m["camera"]["zoom"] == 1.5 for m in rig.rec.of_type("set_tuning", msgs)
            )
        )
        # Un ajuste mal formado de la nube no rompe nada ni se aplica.
        await room.send({"type": "settings", "settings": {"volume": "alto"}, "rev": 8, "ack": 0})
        await wait_until(lambda: rig.control.status()["settings_sync"]["rev"] == 8)
        assert rig.control.status()["volume"] == 0.4


async def test_lo_cambiado_sin_conexion_sube_al_volver(tmp_path: Path) -> None:
    from tests.test_panel import make_panel_rig as rig_without_cloud

    # Sin nube: el cambio se guarda en el equipo como pendiente.
    async with rig_without_cloud(tmp_path) as rig:
        await rig.control.act("set_away_message", {"text": "Vuelvo en 5 minutos"})
        assert rig.control.status()["settings_sync"]["cloud"] == "off"
    saved = PanelState.load(tmp_path / "cache" / "panel_state.json")
    assert saved.pending_settings == ["away_message"]
    # Al conectar, el hello lo lleva como pendiente para que mande sobre la nube.
    room = FakeRoom()
    async with linked(tmp_path, room) as (rig, _):
        await room.wait_for(lambda: bool(room.of_type("hello")))
        settings = room.of_type("hello")[0]["settings"]
        assert settings["pending"] == ["away_message"] and settings["seq"] == 1
        assert settings["values"]["away_message"] == "Vuelvo en 5 minutos"
        values = {**settings["values"], "volume": 0.8}
        await room.send({"type": "settings", "settings": values, "rev": 3, "ack": 1})
        await wait_until(lambda: rig.control.status()["settings_sync"]["pending"] == [])
        assert rig.control.status()["away_message"] == "Vuelvo en 5 minutos"
        assert rig.control.status()["volume"] == 0.8


def test_la_identidad_es_estable_y_cambia_si_cambia_el_equipo(tmp_path: Path) -> None:
    settings = PanelSettings(state_file=str(tmp_path / "cache" / "panel_state.json"))
    first = load_identity(settings, host="Mini-PC")
    again = load_identity(settings, host="Mini-PC")
    assert first == again and first.id.startswith("mini-pc-")
    assert first.name == "Mini-PC"
    # La carpeta copiada a otro equipo no arrastra el id.
    other = load_identity(settings, host="MacBook de Jean")
    assert other.id.startswith("macbook-de-jean-") and other.id != first.id
    named = load_identity(settings.model_copy(update={"instance_name": "Stand"}), host="x")
    assert named.name == "Stand"


async def test_el_panel_local_lista_una_sola_instancia(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        identity = load_identity(rig.settings.panel, host="mini-pc")
        server = PanelServer(
            rig.settings.panel, rig.control, rig.hub, LogBuffer(), identity=identity
        )
        await server.start()
        try:
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{server.port}") as http:
                body = (await http.get("/api/instances")).json()
                status = (await http.get("/api/status?instance=lo-que-sea")).json()
        finally:
            await server.stop()
    assert [i["id"] for i in body["instances"]] == [identity.id]
    assert body["instances"][0]["connected"] is True
    assert body["conflicts"] == {"connected": [], "conversing": []}
    assert status["instance"]["id"] == identity.id and status["mode"] == "conversation"


async def test_el_avatar_de_jean_viaja_con_los_ajustes_de_la_nube(tmp_path: Path) -> None:
    from tests.test_panel import JEAN

    room = FakeRoom()
    async with linked(tmp_path, room) as (rig, _):
        await room.wait_for(lambda: bool(room.of_type("hello")))
        values = room.of_type("hello")[0]["settings"]["values"]
        assert values["guest_avatar"] is None and values["avatar"] is None
        # Una definición sin piezas de la nube no se aplica.
        empty = json.dumps({"JsonVersion": "2-0-0", "equippedAssetIds": []})
        await room.send(
            {"type": "settings", "settings": {**values, "guest_avatar": empty}, "rev": 4, "ack": 0}
        )
        await wait_until(lambda: rig.control.status()["settings_sync"]["rev"] == 4)
        assert rig.control.status()["guest_avatar"]["custom"] is False
        # La buena llega a Unity como avatar del invitado, sin tocar el de Sonia.
        await room.send(
            {"type": "settings", "settings": {**values, "guest_avatar": JEAN}, "rev": 5, "ack": 0}
        )
        await wait_until(lambda: rig.control.status()["guest_avatar"]["custom"])
        await rig.rec.wait_for(
            lambda msgs: rig.rec.of_type("set_guest_avatar", msgs)[-1]["definition"] == JEAN
        )
        assert rig.control.status()["avatar"]["custom"] is False
    assert PanelState.load(tmp_path / "cache" / "panel_state.json").guest_avatar == JEAN
