"""Las últimas líneas del registro, para enseñarlas en el panel.

Cada línea lleva el módulo que la escribió (``logger``, sin el ``sonia.`` del
principio) y unas etiquetas (``tags``) para los filtros del registro de
«Developer»: ``actions`` (lo que GPT-Live delega y lo que hace el backend),
``gestures`` (el director de gestos) y ``agenda`` (la agenda y el reloj). Los
avisos y errores se filtran por ``level``.
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

#: Librerías cuyo registro no aporta al personal del stand.
_QUIET = ("websockets", "httpx", "httpcore", "uvicorn", "urllib3")

#: Etiquetas que puede llevar una línea (los filtros de «Developer»).
LOG_TAGS = ("actions", "gestures", "agenda")

_ACTION_LOGGERS = ("sonia.actions", "sonia.trivia")
_GESTURE_LOGGERS = ("sonia.gestures",)
_AGENDA_LOGGERS = ("sonia.agenda", "sonia.clock")
_ENGINE_LOGGER = "sonia.live.engine"

#: Plantillas del motor que cuentan qué delega GPT-Live y qué hace el backend.
_ACTION_TEMPLATES = (
    "GPT-Live delega",
    "Acción ",
    "Backend (",
    "El backend",
    "La tarea delegada",
    "No se pudo devolver el resultado",
)

#: Palabras que, en la plantilla de una línea de Sonia, la llevan a «Agenda y reloj».
_AGENDA_WORDS = ("agenda", "reloj")


def _under(name: str, prefixes: tuple[str, ...]) -> bool:
    return any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes)


def log_tags(record: logging.LogRecord) -> list[str]:
    """Etiquetas de una línea según quién la escribió y su plantilla (no el texto final).

    Se mira la plantilla (``record.msg``) y no el mensaje ya formateado para que
    lo que dice un visitante («¿qué hay en la agenda?») no cambie la etiqueta.
    """
    name = record.name
    if not _under(name, ("sonia",)):
        return []
    template = record.msg if isinstance(record.msg, str) else ""
    tags: list[str] = []
    if _under(name, _ACTION_LOGGERS) or (
        name == _ENGINE_LOGGER and template.startswith(_ACTION_TEMPLATES)
    ):
        tags.append("actions")
    if _under(name, _GESTURE_LOGGERS):
        tags.append("gestures")
    lowered = template.lower()
    action_name = ""
    if template.startswith("Acción ") and isinstance(record.args, tuple) and record.args:
        action_name = str(record.args[0]).lower()
    if (
        _under(name, _AGENDA_LOGGERS)
        or any(word in lowered for word in _AGENDA_WORDS)
        or "agenda" in action_name
    ):
        tags.append("agenda")
    return tags


def _short_name(name: str) -> str:
    return name.removeprefix("sonia.") if name != "sonia" else name


class LogBuffer(logging.Handler):
    """Guarda las últimas líneas y avisa a quien escuche (el WebSocket del panel).

    ``logging`` puede llamar desde cualquier hilo: el aviso se pasa al bucle
    asyncio con ``call_soon_threadsafe``.
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
