"""WebSocket client for the OpenAI Live API (GPT-Live), without an SDK.

Only ``websockets`` and JSON. This module knows nothing about Unity or the
conversation: it opens the session, sends commands and hands over the server
events as they come. The logic lives in :mod:`sonia.live.engine`.

Implemented protocol:

- https://developers.openai.com/api/docs/models/gpt-live-1 and
  https://developers.openai.com/api/docs/guides/live-conversations
  ``wss://api.openai.com/v1/live/sessions`` with ``Authorization: Bearer``; the
  first message is ``session.start`` and nothing else is sent until
  ``session.started`` arrives.
- https://learn.microsoft.com/azure/foundry/openai/gpt-live-reference
  Full reference of client and server events, and the audio format:
  headerless mono PCM s16le, in base64.
- https://developers.openai.com/api/docs/guides/live-delegation
  Delegation to a Responses API backend (``response.event``,
  ``response.item.create``, ``response.create``).
- Types of the official ``openai`` SDK 3.24 (``openai/types/live``): exact fields
  of ``SessionConfig`` (``audio.format`` with ``rate`` 16000 or 24000, a limit of
  16 384 tokens in ``instructions``) and of each event.

The appends (``session.thinking.append`` and friends) accept at most 500
tokens; the text is trimmed before sending so it does not trigger an error.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any

from sonia.config import LiveSettings

__all__ = ["APPEND_MAX_CHARS", "LiveClient", "LiveError", "WsConnect", "describe_error"]

logger = logging.getLogger(__name__)

#: ``(url, headers) -> connection``. Tests inject one that points to a fake
#: server.
WsConnect = Callable[[str, dict[str, str]], Awaitable[Any]]

#: Safety trim for the appends (500 tokens are about 2,000 characters of
#: ordinary prose; numbers, URLs or emojis cost more tokens, so a wide margin
#: is left).
APPEND_MAX_CHARS = 1_200

#: Cap on an incoming message. GPT-Live events are small, but a
#: ``session.started`` returns the full instructions.
_WS_MAX_SIZE = 16 * 1024 * 1024

#: How long to wait for ``session.closed`` when closing before cutting the socket.
_CLOSE_WAIT_S = 2.0


class LiveError(RuntimeError):
    """Failure opening or using a GPT-Live session."""


class LiveClient:
    """One GPT-Live session over a primary WebSocket.

    Usage::

        client = LiveClient(settings.live)
        session = await client.start(config)
        async for event in client.events():
            ...
        await client.close()
    """

    def __init__(self, settings: LiveSettings, *, connect: WsConnect | None = None) -> None:
        self._settings = settings
        self._connect = connect
        self._ws: Any = None
        self._session: dict[str, Any] = {}
        #: Events that arrived before ``session.started`` (``info``, for example).
        self._early: list[dict[str, Any]] = []
        self._counter = 0
        self._send_lock = asyncio.Lock()
        self._closed = asyncio.Event()
        #: True while someone is consuming :meth:`events`.
        self._reading = False
        self.close_reason = ""

    # -- properties ---------------------------------------------------------

    @property
    def session(self) -> dict[str, Any]:
        """The session resource returned by ``session.started``."""
        return self._session

    @property
    def session_id(self) -> str:
        return str(self._session.get("id") or "")

    @property
    def expires_at(self) -> float | None:
        """Unix time at which the session expires, if the server said so."""
        value = self._session.get("expires_at")
        return float(value) if isinstance(value, int | float) else None

    @property
    def is_open(self) -> bool:
        return self._ws is not None and not self._closed.is_set()

    # -- startup ------------------------------------------------------------

    async def start(self, session: dict[str, Any]) -> dict[str, Any]:
        """Connects, sends ``session.start`` and waits for ``session.started``."""
        settings = self._settings
        if self._connect is None and not settings.api_key:
            raise LiveError("Missing LIVE_API_KEY (or OPENAI_API_KEY) in .env to use GPT-Live.")
        connect = self._connect or self._default_connect
        headers = {"Authorization": f"Bearer {settings.api_key}"}
        try:
            async with asyncio.timeout(settings.connect_timeout):
                self._ws = await connect(settings.url, headers)
        except Exception as exc:
            raise self._handshake_error(exc) from exc

        try:
            await self.send({"type": "session.start", "session": session})
            async with asyncio.timeout(settings.connect_timeout):
                while True:
                    event = await self._recv()
                    if event is None:
                        raise LiveError(
                            "GPT-Live closed the connection before confirming the session"
                            f" ({self.close_reason or 'no reason given'})."
                        )
                    kind = event.get("type")
                    if kind == "session.started":
                        resource = event.get("session")
                        self._session = resource if isinstance(resource, dict) else {}
                        return self._session
                    if kind == "error":
                        raise LiveError(f"GPT-Live rejected the session: {describe_error(event)}")
                    self._early.append(event)
        except TimeoutError as exc:
            await self._abort()
            raise LiveError(
                f"GPT-Live did not confirm the session within {settings.connect_timeout:g} s."
            ) from exc
        except BaseException:
            await self._abort()
            raise

    # -- server events ------------------------------------------------------

    async def events(self) -> AsyncGenerator[dict[str, Any]]:
        """Server events in order until the connection closes."""
        early, self._early = self._early, []
        self._reading = True
        try:
            for queued in early:
                yield queued
            while True:
                event = await self._recv()
                if event is None:
                    return
                yield event
                if event.get("type") == "session.closed":
                    return
        finally:
            self._reading = False

    async def _recv(self) -> dict[str, Any] | None:
        """Next JSON event, or ``None`` if the connection ended."""
        from websockets.exceptions import ConnectionClosed

        ws = self._ws
        if ws is None:
            return None
        while True:
            try:
                raw = await ws.recv()
            except ConnectionClosed as exc:
                frame = getattr(exc, "rcvd", None) or getattr(exc, "sent", None)
                if frame is not None and not self.close_reason:
                    code = getattr(frame, "code", "?")
                    self.close_reason = (
                        f"close {code}: {getattr(frame, 'reason', '') or 'no reason given'}"
                    )
                self._closed.set()
                return None
            if isinstance(raw, bytes | bytearray):
                raw = bytes(raw).decode("utf-8", errors="replace")
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                logger.debug("GPT-Live sent something that is not JSON; ignoring it")
                continue
            if isinstance(event, dict) and isinstance(event.get("type"), str):
                if event["type"] == "session.closed":
                    self.close_reason = str(event.get("reason") or "")
                    self._closed.set()
                return event

    # -- commands -----------------------------------------------------------

    def next_event_id(self, prefix: str = "sonia") -> str:
        self._counter += 1
        return f"{prefix}_{self._counter}"

    async def send(self, event: dict[str, Any]) -> str:
        """Sends a command. Returns its ``event_id`` (to match errors)."""
        ws = self._ws
        if ws is None:
            raise LiveError("The GPT-Live session is not open.")
        payload = dict(event)
        event_id = str(payload.get("event_id") or self.next_event_id())
        payload["event_id"] = event_id
        async with self._send_lock:
            await ws.send(json.dumps(payload, ensure_ascii=False))
        return event_id

    async def append_audio(self, pcm: bytes) -> None:
        """Microphone audio (mono PCM s16le at the session rate). No acknowledgement."""
        if not pcm:
            return
        if len(pcm) % 2:
            pcm = pcm[:-1]
        ws = self._ws
        if ws is None:
            return
        # No event_id: audio has no acknowledgement and this saves bytes on every block.
        message = json.dumps(
            {
                "type": "session.input_audio.append",
                "audio": base64.b64encode(pcm).decode("ascii"),
            }
        )
        async with self._send_lock:
            await ws.send(message)

    async def append_instructions(self, content: str, delegation_id: str | None = None) -> str:
        """Trusted instructions that change what the model does or says."""
        return await self._append("session.instructions.append", content, delegation_id)

    async def append_thinking(self, content: str, delegation_id: str | None = None) -> str:
        """Silent context: the model uses it but does not say it when it arrives."""
        return await self._append("session.thinking.append", content, delegation_id)

    async def append_commentary(self, content: str, delegation_id: str | None = None) -> str:
        """Content the model must say out loud (it may paraphrase it)."""
        return await self._append("session.commentary.append", content, delegation_id)

    async def _append(self, kind: str, content: str, delegation_id: str | None) -> str:
        text = content.strip()
        if len(text) > APPEND_MAX_CHARS:
            text = text[: APPEND_MAX_CHARS - 1].rstrip() + "…"
        # ``delegation_id`` is required even when it is null.
        return await self.send({"type": kind, "content": text, "delegation_id": delegation_id})

    async def create_item(self, item: dict[str, Any]) -> str:
        """Adds an item (an action result, a message) to the Responses backend."""
        return await self.send({"type": "response.item.create", "item": item})

    async def create_response(self) -> str:
        """Resumes the backend response that was waiting for action results."""
        return await self.send({"type": "response.create"})

    # -- shutdown -----------------------------------------------------------

    async def close(self, *, wait: bool = True) -> None:
        """Orderly close: ``session.close`` and wait for ``session.closed``.

        If another task is reading :meth:`events`, it will see ``session.closed``
        and finish; if nobody is reading, it is read here. With ``wait=False``
        (on shutdown) the close is requested and the socket is cut without
        waiting for a reply.
        """
        ws = self._ws
        if ws is None:
            return
        if not self._closed.is_set():
            with contextlib.suppress(Exception):
                await self.send({"type": "session.close"})
            if wait:
                with contextlib.suppress(TimeoutError):
                    async with asyncio.timeout(_CLOSE_WAIT_S):
                        if self._reading:
                            await self._closed.wait()
                        else:
                            while not self._closed.is_set() and await self._recv() is not None:
                                pass
        await self._abort()

    async def _abort(self) -> None:
        ws, self._ws = self._ws, None
        self._closed.set()
        if ws is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(ws.close(), timeout=_CLOSE_WAIT_S)

    # -- real connection ----------------------------------------------------

    async def _default_connect(self, url: str, headers: dict[str, str]) -> Any:
        """Real connection. Imported here so ``websockets`` is not loaded on import."""
        from websockets.asyncio.client import connect

        return await connect(
            url,
            additional_headers=headers,
            max_size=_WS_MAX_SIZE,
            open_timeout=self._settings.connect_timeout,
            # Base64 audio barely compresses and compressing adds latency.
            compression=None,
        )

    def _handshake_error(self, exc: Exception) -> LiveError:
        """Turns a connection failure into an error that makes sense without the code."""
        if isinstance(exc, LiveError):
            return exc
        if isinstance(exc, TimeoutError):
            return LiveError(
                "GPT-Live did not accept the connection within "
                f"{self._settings.connect_timeout:g} s."
            )
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (401, 403):
            return LiveError(
                f"GPT-Live rejected the connection (HTTP {status}). Check LIVE_API_KEY and that "
                f"the project has access to {self._settings.model!r}."
            )
        if status is not None:
            return LiveError(f"GPT-Live returned HTTP {status} when connecting.")
        return LiveError(f"Could not connect to GPT-Live: {exc}")


def describe_error(event: dict[str, Any]) -> str:
    """Readable text of a GPT-Live ``error`` event."""
    error = event.get("error")
    if not isinstance(error, dict):
        return json.dumps(event, ensure_ascii=False)[:300]
    code = error.get("code") or error.get("type") or "error"
    message = error.get("message") or ""
    param = error.get("param")
    detail = f"{code}: {message}" if message else str(code)
    return f"{detail} (param {param})" if param else detail
