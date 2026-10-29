"""The last log lines, to show them in the panel.

Each line carries the module that wrote it (``logger``, without the leading
``sonia.``) and some tags (``tags``) for the filters of the Developer log:
``actions`` (what the realtime model delegates and what the backend does).
Warnings and errors are filtered by ``level``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import deque
from collections.abc import Callable
from typing import Any

__all__ = ["LOG_TAGS", "LogBuffer", "log_tags"]

#: Libraries whose log adds nothing for the operator.
_QUIET = ("websockets", "httpx", "httpcore", "uvicorn", "urllib3")

#: Tags a line can carry (the Developer filters).
LOG_TAGS = ("actions",)

_ACTION_LOGGERS = ("sonia.actions", "sonia.trivia")
_ENGINE_LOGGER = "sonia.live.engine"

#: Engine templates that tell what the realtime model delegates and what the backend does.
_ACTION_TEMPLATES = (
    "GPT-Live delegates",
    "Action ",
    "Backend (",
    "The backend",
    "The delegated task",
    "Could not return the result",
)


def _under(name: str, prefixes: tuple[str, ...]) -> bool:
    return any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes)


def log_tags(record: logging.LogRecord) -> list[str]:
    """Tags of a line according to who wrote it and its template (not the final text).

    The template (``record.msg``) is checked and not the formatted message, so that
    what a user says cannot change the tag.
    """
    name = record.name
    if not _under(name, ("sonia",)):
        return []
    template = record.msg if isinstance(record.msg, str) else ""
    if _under(name, _ACTION_LOGGERS) or (
        name == _ENGINE_LOGGER and template.startswith(_ACTION_TEMPLATES)
    ):
        return ["actions"]
    return []


def _short_name(name: str) -> str:
    return name.removeprefix("sonia.") if name != "sonia" else name


class LogBuffer(logging.Handler):
    """Keeps the last lines and tells whoever listens (the panel WebSocket).

    ``logging`` can call from any thread: the notice is handed to the asyncio loop
    with ``call_soon_threadsafe``.
    """

    def __init__(self, capacity: int = 500) -> None:
        super().__init__(level=logging.INFO)
        self._lines: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._listeners: list[Callable[[dict[str, Any]], None]] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def add_listener(self, listener: Callable[[dict[str, Any]], None]) -> None:
        self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[dict[str, Any]], None]) -> None:
        with contextlib.suppress(ValueError):
            self._listeners.remove(listener)

    def lines(self) -> list[dict[str, Any]]:
        return list(self._lines)

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(_QUIET) and record.levelno < logging.WARNING:
            return
        try:
            text = record.getMessage()
            tags = log_tags(record)
        except Exception:  # noqa: BLE001
            return
        line = {
            "type": "log",
            "level": record.levelname,
            "time": time.strftime("%H:%M:%S", time.localtime(record.created)),
            "logger": _short_name(record.name),
            "tags": tags,
            "text": text if len(text) <= 500 else text[:499] + "…",
        }
        self._lines.append(line)
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        for listener in list(self._listeners):
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(listener, line)
