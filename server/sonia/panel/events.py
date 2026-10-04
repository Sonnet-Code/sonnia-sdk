"""Lo que pasa en Sonia, repartido a quien lo mire (panel local y Cloudflare).

Escucha todo lo que el orquestador manda a Unity y el registro, guarda lo
último para pintar la página al abrirla y lo reparte a cada suscriptor
(un WebSocket del panel local o la conexión con el panel de Cloudflare) por
una cola propia: si un suscriptor se atasca, pierde mensajes pero no frena a
nadie.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import deque
from typing import TYPE_CHECKING, Any

from sonia.panel.logs import LogBuffer
from sonia.ws import protocol as p

if TYPE_CHECKING:  # pragma: no cover - solo para tipado
    from sonia.ws.hub import Hub

__all__ = ["PanelEvents"]

#: Mensajes hacia Unity que no interesan en el panel.
_SKIP_MESSAGES = frozenset({p.MSG_REQUEST_FRAME, p.MSG_HELLO})

#: Mensajes que se guardan para pintar la página al abrirla.
_HISTORY_MESSAGES = frozenset(
    {p.MSG_TRANSCRIPT, p.MSG_SHOW_IMAGE, p.MSG_HIDE_IMAGE, p.MSG_PRESENCE, p.MSG_ERROR}
)


class PanelEvents:
    """Reparte a los WebSocket del panel lo que va a Unity y el registro."""

    def __init__(self, hub: Hub, logs: LogBuffer | None) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._history: deque[dict[str, Any]] = deque(maxlen=80)
        self._logs = logs
        hub.add_listener(self._on_message)
        if logs is not None:
            logs.add_listener(self._publish)

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=500)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def history(self) -> dict[str, Any]:
        return {
            "type": "history",
            "messages": list(self._history),
            "logs": self._logs.lines() if self._logs is not None else [],
        }

    def _on_message(self, msg: dict[str, Any]) -> None:
        kind = msg.get("type")
        if kind in _SKIP_MESSAGES:
            return
        # Copia para el panel: sin la imagen en base64 y con la hora.
        msg = {k: v for k, v in msg.items() if k != "data_base64"}
        msg["time"] = time.strftime("%H:%M:%S")
        if kind in _HISTORY_MESSAGES and (kind != p.MSG_TRANSCRIPT or msg.get("final")):
            self._history.append(msg)
        self._publish({"type": "message", "message": msg})

    def _publish(self, item: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(item)
