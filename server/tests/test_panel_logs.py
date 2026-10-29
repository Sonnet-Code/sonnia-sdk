"""Tests of the panel log: tags, module and the engine lines used to debug delegations.

No network and no APIs: the engine talks to the fake GPT-Live of ``test_live``.
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
    """Has the engine closed the delegated task yet (its "Backend (...)" line)?"""
    return any(r.getMessage().startswith("Backend (") for r in caplog.records)


def record(name: str, msg: str, *args: Any, level: int = logging.INFO) -> logging.LogRecord:
    return logging.LogRecord(name, level, __file__, 1, msg, args or None, None)


def test_tags_come_from_the_writer_and_the_template() -> None:
    engine = "sonia.live.engine"
    assert log_tags(
        record(engine, "GPT-Live delegates a task to the backend %s (%s)%s", "r", "d", "")
    ) == ["actions"]
    assert log_tags(record(engine, "Action %s(%s) -> %s", "play_animation", {}, "ok")) == [
        "actions"
    ]
    assert log_tags(record(engine, "Backend (%s, %.1f s, %s): %s", "d", 1.0, "no actions", "")) == [
        "actions"
    ]
    assert log_tags(record("sonia.actions.moves", "Dance %s", "x")) == ["actions"]
    assert log_tags(record("sonia.trivia.game", "Question %d", 1)) == ["actions"]
    assert log_tags(record("sonia.clock", "Time")) == []


def test_what_the_user_says_does_not_change_the_tag() -> None:
    engine = "sonia.live.engine"
    said = record(engine, "User (level %.3f): %s", 0.1, "Action! The backend, dance")
    assert log_tags(said) == []
    assert log_tags(record(engine, "State: %s -> %s", "idle", "listening")) == []
    # Nor what is not Sonnia's (``sonia_x`` is not ``sonia``).
    assert log_tags(record("sonia_x", "Action ")) == []
    assert log_tags(record("httpx", "Action ")) == []


def test_each_line_carries_module_and_tags_and_the_buffer_is_circular() -> None:
    logs = LogBuffer(capacity=3)
    logs.handle(record("sonia.actions.moves", "Move %s", "dance"))
    logs.handle(record("httpx", "HTTP Request: POST %s", "https://x"))  # noisy library: out
    logs.handle(record("httpx", "It went down", level=logging.WARNING))  # its warnings do count
    logs.handle(record("sonia", "Root"))
    lines = logs.lines()
    assert [line["text"] for line in lines] == ["Move dance", "It went down", "Root"]
    first = lines[0]
    assert first["type"] == "log"
    assert first["logger"] == "actions.moves"
    assert first["tags"] == ["actions"]
    assert first["level"] == "INFO"
    assert lines[1]["logger"] == "httpx" and lines[1]["tags"] == []
    assert lines[2]["logger"] == "sonia"
    logs.handle(record("sonia.live.engine", "Fourth"))
    assert [line["text"] for line in logs.lines()] == ["It went down", "Root", "Fourth"]


def test_the_default_buffer_keeps_five_hundred_lines() -> None:
    logs = LogBuffer()
    for n in range(600):
        logs.handle(record("sonia.live.engine", "Line %d", n))
    lines = logs.lines()
    assert len(lines) == 500
    assert lines[0]["text"] == "Line 100"


async def test_history_and_subscribers_get_the_tags(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    hub = Hub(settings.ws, sample_rate=settings.live.sample_rate)
    logs = LogBuffer()
    logs.bind(asyncio.get_running_loop())
    events = PanelEvents(hub, logs)
    queue = events.subscribe()
    logs.handle(record("sonia.live.engine", "Action %s(%s) -> %s", "look", {}, "I see two"))
    item = await asyncio.wait_for(queue.get(), timeout=2)
    assert item["type"] == "log"
    assert item["tags"] == ["actions"]
    assert item["logger"] == "live.engine"
    history = events.history()
    assert history["logs"][-1]["tags"] == ["actions"]
    # The line goes to the browser as is: it has to be serializable.
    json.dumps(history, ensure_ascii=False)


async def test_the_log_says_when_the_backend_finished_without_actions(
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
                    "task": "Make Sonia dance",
                },
            }
        )
        await conn.response_event({"type": "response.created"})
        await conn.response_event({"type": "response.output_text.delta", "delta": "Done."})
        await conn.response_event({"type": "response.completed"})
        await wait_until(lambda: finished_logged(caplog))
    messages = [r.getMessage() for r in caplog.records if r.name == "sonia.live.engine"]
    delegated = next(m for m in messages if m.startswith("GPT-Live delegates"))
    # Whatever the delegation brings besides its ids shows up in the log.
    assert "Make Sonia dance" in delegated
    finished = next(m for m in messages if m.startswith("Backend (deleg_1"))
    assert "no actions" in finished and "Done." in finished


async def test_the_log_counts_actions_and_warns_about_broken_arguments(
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
                    "arguments": "{not json",
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
        m.startswith("Action play_animation with arguments that are not valid JSON")
        for m in messages
    )
    finished = next(m for m in messages if m.startswith("Backend ("))
    assert "1 action" in finished
