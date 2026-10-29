"""What happens in Sonnia, handed out to whoever watches (the panel WebSockets).

It listens to everything the orchestrator sends to the avatar client and to the
log, keeps the latest to draw the page when it opens and hands it out to each
subscriber (a panel WebSocket) through its own queue: if a subscriber gets
stuck, it loses messages but slows nobody down.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import deque
from typing import TYPE_CHECKING, Any

from sonia.panel.logs import LogBuffer
from sonia.ws import protocol as p

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sonia.ws.hub import Hub

__all__ = ["PanelEvents"]

#: Messages to the avatar client the panel does not care about.
_SKIP_MESSAGES = frozenset({p.MSG_REQUEST_FRAME, p.MSG_HELLO})

#: Messages kept to draw the page when it opens.
_HISTORY_MESSAGES = frozenset(
    {p.MSG_TRANSCRIPT, p.MSG_SHOW_IMAGE, p.MSG_HIDE_IMAGE, p.MSG_PRESENCE, p.MSG_ERROR}
)


class PanelEvents:
    """Hands out to the panel WebSockets what goes to the avatar client and the log."""

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
        # Copy for the panel: without the base64 image and with the time.
        msg = {k: v for k, v in msg.items() if k != "data_base64"}
        msg["time"] = time.strftime("%H:%M:%S")
        if kind in _HISTORY_MESSAGES and (kind != p.MSG_TRANSCRIPT or msg.get("final")):
            self._history.append(msg)
        self._publish({"type": "message", "message": msg})

    def _publish(self, item: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(item)
