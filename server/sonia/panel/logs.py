"""Las últimas líneas del registro, para enseñarlas en el panel."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import deque
from collections.abc import Callable
from typing import Any

__all__ = ["LogBuffer"]

#: Librerías cuyo registro no aporta al personal del stand.
_QUIET = ("websockets", "httpx", "httpcore", "uvicorn", "urllib3")


class LogBuffer(logging.Handler):
    """Guarda las últimas líneas y avisa a quien escuche (el WebSocket del panel).

    ``logging`` puede llamar desde cualquier hilo: el aviso se pasa al bucle
    asyncio con ``call_soon_threadsafe``.
    """

    def __init__(self, capacity: int = 300) -> None:
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
        except Exception:  # noqa: BLE001
            return
        line = {
            "type": "log",
            "level": record.levelname,
            "time": time.strftime("%H:%M:%S", time.localtime(record.created)),
            "text": text if len(text) <= 500 else text[:499] + "…",
        }
        self._lines.append(line)
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        for listener in list(self._listeners):
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(listener, line)
