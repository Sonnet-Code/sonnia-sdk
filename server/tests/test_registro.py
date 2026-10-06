"""Pruebas del registro del panel: etiquetas, módulo y líneas del motor para depurar delegaciones.

Sin red ni APIs: el motor habla con el GPT-Live falso de ``test_live``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import pytest

from sonia.panel.events import PanelEvents
from sonia.panel.logs import LogBuffer, log_tags
from sonia.ws.hub import Hub
from tests.test_live import make_rig, make_settings, wait_until


def finished_logged(caplog: pytest.LogCaptureFixture) -> bool:
    """¿Ya cerró el motor la tarea delegada (su línea «Backend (...)»)?"""
    return any(r.getMessage().startswith("Backend (") for r in caplog.records)


def record(name: str, msg: str, *args: Any, level: int = logging.INFO) -> logging.LogRecord:
    return logging.LogRecord(name, level, __file__, 1, msg, args or None, None)


def test_las_etiquetas_salen_de_quien_escribe_y_de_la_plantilla() -> None:
    engine = "sonia.live.engine"
    assert log_tags(
        record(engine, "GPT-Live delega una tarea en el backend %s (%s)%s", "r", "d", "")
    ) == ["actions"]
    assert log_tags(record(engine, "Acción %s(%s) -> %s", "play_animation", {}, "ok")) == [
        "actions"
    ]
    assert log_tags(
        record(engine, "Backend (%s, %.1f s, %s): %s", "d", 1.0, "sin acciones", "")
    ) == ["actions"]
    assert log_tags(record("sonia.actions.moves", "Baile %s", "x")) == ["actions"]
    assert log_tags(record("sonia.trivia.game", "Pregunta %d", 1)) == ["actions"]
    assert log_tags(record("sonia.gestures.director", "Gesto %s (frase %d)", "waveCalm", 1)) == [
        "gestures"
    ]
    assert log_tags(record("sonia.agenda", "Agenda leída")) == ["agenda"]
    assert log_tags(record("sonia.agenda.watcher", "Sin cambios")) == ["agenda"]
    assert log_tags(record("sonia.clock", "Hora")) == ["agenda"]
    # Una acción de la agenda es acción y agenda a la vez.
    assert log_tags(record(engine, "Acción %s(%s) -> %s", "check_agenda", {}, "sin cambios")) == [
        "actions",
        "agenda",
    ]
    assert log_tags(record(engine, "Nota de reloj: %s", "son las 7")) == ["agenda"]


def test_lo_que_dice_el_visitante_no_cambia_la_etiqueta() -> None:
    engine = "sonia.live.engine"
    said = record(engine, "Usuario (nivel %.3f): %s", 0.1, "¿Qué hay en la agenda? Acción, baila")
    assert log_tags(said) == []
    assert log_tags(record(engine, "Estado: %s -> %s", "idle", "listening")) == []
    # Ni lo que no es de Sonia (``sonia_x`` no es ``sonia``).
    assert log_tags(record("sonia_x", "agenda")) == []
    assert log_tags(record("httpx", "agenda")) == []


def test_cada_linea_lleva_modulo_y_etiquetas_y_el_bufer_es_circular() -> None:
    logs = LogBuffer(capacity=3)
    logs.handle(record("sonia.gestures.director", "Gesto %s", "waveCalm"))
    logs.handle(record("httpx", "HTTP Request: POST %s", "https://x"))  # librería ruidosa: fuera
    logs.handle(record("httpx", "Se cayó", level=logging.WARNING))  # sus avisos sí
    logs.handle(record("sonia", "Raíz"))
    lines = logs.lines()
    assert [line["text"] for line in lines] == ["Gesto waveCalm", "Se cayó", "Raíz"]
    first = lines[0]
    assert first["type"] == "log"
    assert first["logger"] == "gestures.director"
    assert first["tags"] == ["gestures"]
    assert first["level"] == "INFO"
    assert lines[1]["logger"] == "httpx" and lines[1]["tags"] == []
    assert lines[2]["logger"] == "sonia"
    logs.handle(record("sonia.live.engine", "Cuarta"))
    assert [line["text"] for line in logs.lines()] == ["Se cayó", "Raíz", "Cuarta"]


def test_el_bufer_por_defecto_guarda_quinientas_lineas() -> None:
    logs = LogBuffer()
    for n in range(600):
        logs.handle(record("sonia.live.engine", "Línea %d", n))
    lines = logs.lines()
    assert len(lines) == 500
    assert lines[0]["text"] == "Línea 100"


async def test_el_historial_y_los_suscriptores_reciben_las_etiquetas(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    hub = Hub(settings.ws, sample_rate=settings.live.sample_rate)
    logs = LogBuffer()
    logs.bind(asyncio.get_running_loop())
    events = PanelEvents(hub, logs)
    queue = events.subscribe()
    logs.handle(record("sonia.live.engine", "Acción %s(%s) -> %s", "look", {}, "Veo a dos"))
    item = await asyncio.wait_for(queue.get(), timeout=2)
    assert item["type"] == "log"
    assert item["tags"] == ["actions"]
    assert item["logger"] == "live.engine"
    history = events.history()
    assert history["logs"][-1]["tags"] == ["actions"]
    # La línea va a la nube tal cual: tiene que poder serializarse.
    json.dumps(history, ensure_ascii=False)


async def test_el_registro_dice_si_el_backend_termino_sin_acciones(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="sonia.live.engine")
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.send(
            {
                "type": "session.delegation.created",
                "event_id": "ed",
                "delegation": {
                    "id": "deleg_1",
                    "type": "delegation",
                    "target": "responses",
                    "task": "Que Sonia baile",
                },
            }
        )
        await conn.response_event({"type": "response.created"})
        await conn.response_event({"type": "response.output_text.delta", "delta": "Listo."})
        await conn.response_event({"type": "response.completed"})
        await wait_until(lambda: finished_logged(caplog))
    messages = [r.getMessage() for r in caplog.records if r.name == "sonia.live.engine"]
    delegated = next(m for m in messages if m.startswith("GPT-Live delega"))
    # Lo que traiga la delegación además de sus ids sale en el registro.
    assert "Que Sonia baile" in delegated
    finished = next(m for m in messages if m.startswith("Backend (deleg_1"))
    assert "sin acciones" in finished and "Listo." in finished


async def test_el_registro_cuenta_las_acciones_y_avisa_de_argumentos_rotos(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="sonia.live.engine")
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.response_event({"type": "response.created"})
        await conn.response_event(
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "function_call",
                    "call_id": "c1",
                    "name": "play_animation",
                    "arguments": "{no es json",
                },
            }
        )
        await conn.response_event({"type": "response.completed"})
        await conn.wait_type("response.create")
        await conn.response_event({"type": "response.created"})
        await conn.response_event({"type": "response.completed"})
        await wait_until(lambda: finished_logged(caplog))
    messages = [r.getMessage() for r in caplog.records if r.name == "sonia.live.engine"]
    assert any(
        m.startswith("Acción play_animation con argumentos que no son JSON") for m in messages
    )
    finished = next(m for m in messages if m.startswith("Backend ("))
    assert "1 acción" in finished
