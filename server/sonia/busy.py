"""On-screen waiting indicator (``busy``): people get impatient when nothing seems to happen.

While Sonnia waits for something the user cannot see (a task delegated to the backend, a
web search), the avatar client shows a pill with animated dots. Several waits can overlap;
each one is registered with its key and the client only sees the highest-priority one
(``BUSY_KINDS``, in order), with its text. When none is left, ``busy`` with ``on: false``.

The client shows it right away and keeps it at least a moment so it does not flicker; this
side only sends the state when it changes (and whole: :meth:`BusyBoard.message` is used to
repeat it to a client that reconnects).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from sonia.ws import protocol as p

__all__ = [
    "TEXT_SEARCH",
    "TEXT_THINK",
    "BusyBoard",
    "BusyKind",
]

logger = logging.getLogger(__name__)

#: Waiting kinds, from highest to lowest priority (``protocol.BUSY_KINDS``).
BusyKind = Literal["search", "think"]

# Pill texts: short, to be read from 2-3 m away.
TEXT_THINK = "Thinking…"
TEXT_SEARCH = "Searching the web…"

SendJson = Callable[[dict[str, Any]], Awaitable[None]]


class BusyBoard:
    """The running waits, by key; sends ``busy`` to the client when the visible one changes.

    Without ``send_json`` (tests, or before connecting to the client) it only keeps count.
    Never raises: a failure to send goes to the log and the wait stays registered anyway.
    """

    def __init__(self, send_json: SendJson | None = None) -> None:
        self._send = send_json
        #: key → (kind, text), in arrival order.
        self._waits: dict[str, tuple[BusyKind, str]] = {}
        self._shown: dict[str, Any] = p.msg_busy(False)

    def bind(self, send_json: SendJson | None) -> None:
        """Changes where it sends to (the engine's ``Hub``)."""
        self._send = send_json

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(self._waits)

    def current(self) -> tuple[BusyKind, str] | None:
        """The visible wait: the highest-priority one and, among equals, the most recent."""
        best: tuple[BusyKind, str] | None = None
        best_rank = len(p.BUSY_KINDS)
        for kind, text in self._waits.values():
            rank = p.BUSY_KINDS.index(kind)
            if rank <= best_rank:
                best, best_rank = (kind, text), rank
        return best

    def message(self) -> dict[str, Any]:
        """The ``busy`` message for now (for a client that just connected)."""
        shown = self.current()
        return p.msg_busy(False) if shown is None else p.msg_busy(True, shown[0], shown[1])

    async def set(self, key: str, kind: BusyKind, text: str) -> None:
        """Starts (or changes) the wait ``key``."""
        self._waits.pop(key, None)
        self._waits[key] = (kind, text)
        await self._publish()

    async def clear(self, key: str) -> None:
        """Ends the wait ``key`` (nothing if it was not there)."""
        if self._waits.pop(key, None) is not None:
            await self._publish()

    async def clear_prefix(self, prefix: str) -> None:
        """Ends every wait whose key starts with ``prefix``."""
        gone = [key for key in self._waits if key.startswith(prefix)]
        for key in gone:
            del self._waits[key]
        if gone:
            await self._publish()

    async def _publish(self) -> None:
        message = self.message()
        if message == self._shown:
            return
        self._shown = message
        logger.debug("Waiting indicator: %s", message)
        if self._send is None:
            return
        try:
            await self._send(message)
        except Exception:  # noqa: BLE001 - without the indicator, Sonnia goes on
            logger.warning("Could not send the waiting indicator to the client", exc_info=True)
