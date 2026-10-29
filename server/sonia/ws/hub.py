"""WebSocket server that connects the orchestrator with Unity.

The hub keeps the set of connected clients, sends them ``hello`` when they join,
broadcasts JSON and binary audio frames, and dispatches incoming messages to the
callbacks registered with :meth:`Hub.on`.

Golden rule: nothing the hub does may bring the app down. If there are no
clients, if Unity drops in the middle of a send or if a callback raises, it is
logged and things go on.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import TYPE_CHECKING, Any, Self

from sonia.config import WSSettings
from sonia.types import AudioChunk
from sonia.ws import protocol as p

if TYPE_CHECKING:  # pragma: no cover - typing only
    from websockets.asyncio.server import Server, ServerConnection

logger = logging.getLogger(__name__)

#: A callback can be sync or async.
MessageCallback = Callable[[dict[str, Any]], Awaitable[None] | None]

#: Listener for the JSON messages going out to Unity (the control panel).
OutgoingListener = Callable[[dict[str, Any]], None]

#: Maximum size of an incoming message. The ``websockets`` default (1 MiB) is
#: too small for a ``camera_frame`` from Unity: a base64 JPEG from a 4K webcam
#: exceeds it and the server would close the connection with 1009.
MAX_MESSAGE_SIZE = 16 * 1024 * 1024

#: Short keepalive: a frozen Unity is detected in seconds, not in a minute.
PING_INTERVAL_S = 5.0
PING_TIMEOUT_S = 5.0

#: Timeout for a send to one client. If Unity stops reading, its write buffer
#: fills up and ``send`` never returns: that would block the whole orchestrator
#: loop (``stop_speaking``, ``state``). When it expires that client is dropped,
#: since it is not playing anything anymore anyway.
SEND_TIMEOUT_S = 1.0


class Hub:
    """Local WebSocket server. Implements ``AvatarLink`` for the actions."""

    def __init__(self, settings: WSSettings, sample_rate: int) -> None:
        self._settings = settings
        self._sample_rate = sample_rate
        self._clients: set[ServerConnection] = set()
        self._callbacks: dict[str, list[MessageCallback]] = {}
        self._listeners: list[OutgoingListener] = []
        #: Messages repeated to every new client right after ``hello``
        #: (presence, volume): the state Unity must have even if it connects
        #: or reconnects later.
        self._sticky: dict[str, dict[str, Any]] = {}
        self._server: Server | None = None
        #: Pending closes of dropped clients (strong reference).
        self._closing: set[asyncio.Task[None]] = set()

    # -- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        """Starts listening. Idempotent."""
        if self._server is not None:
            return
        from websockets.asyncio.server import serve

        self._server = await serve(
            self._handle_client,
            self._settings.host,
            self._settings.port,
            # Audio goes in small chunks; compression only adds latency.
            compression=None,
            max_size=MAX_MESSAGE_SIZE,
            ping_interval=PING_INTERVAL_S,
            ping_timeout=PING_TIMEOUT_S,
        )
        logger.info("WebSocket hub listening on ws://%s:%d/", self._settings.host, self.port)

    async def stop(self) -> None:
        """Closes the server and every connection. Idempotent."""
        server, self._server = self._server, None
        if server is None:
            return
        server.close()
        with contextlib.suppress(Exception):
            await server.wait_closed()
        self._clients.clear()
        pending, self._closing = list(self._closing), set()
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        logger.info("WebSocket hub stopped")

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.stop()

    # -- state --------------------------------------------------------------

    @property
    def client_count(self) -> int:
        """Number of clients connected right now."""
        return len(self._clients)

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def port(self) -> int:
        """Actual port it listens on (useful when port 0 was requested)."""
        if self._server is None:
            return self._settings.port
        sockets = self._server.sockets
        if not sockets:  # pragma: no cover - the server always has a socket
            return self._settings.port
        return int(sockets[0].getsockname()[1])

    # -- callbacks ----------------------------------------------------------

    def on(self, type: str, callback: MessageCallback) -> None:
        """Registers a callback for incoming messages of that ``type``.

        There can be several callbacks per type; they run in registration order.
        """
        self._callbacks.setdefault(type, []).append(callback)

    def add_listener(self, listener: OutgoingListener) -> None:
        """Registers a listener for everything sent to Unity (sync, must not block)."""
        self._listeners.append(listener)

    async def set_sticky(self, key: str, msg: dict[str, Any]) -> None:
        """Pins a message for clients that connect later and broadcasts it now."""
        self._sticky[key] = msg
        await self.broadcast_json(msg)

    def sticky(self, key: str) -> dict[str, Any] | None:
        return self._sticky.get(key)

    def clear_sticky(self, key: str) -> None:
        """Stops repeating a pinned message to new clients (sends nothing)."""
        self._sticky.pop(key, None)

    # -- sending ------------------------------------------------------------

    async def broadcast_json(self, msg: dict[str, Any]) -> None:
        """Sends a JSON message to every client. Never raises."""
        for listener in self._listeners:
            try:
                listener(msg)
            except Exception:  # noqa: BLE001 - a broken listener must not bring the app down
                logger.exception("Error in a hub listener")
        await self._broadcast(p.dumps(msg))

    async def broadcast_bytes(self, data: bytes) -> None:
        """Sends a binary frame to every client. Never raises."""
        await self._broadcast(data)

    async def send_audio(self, utterance_id: int, chunk: AudioChunk) -> None:
        """Encodes a voice audio chunk as a binary frame and broadcasts it."""
        await self.broadcast_bytes(p.encode_audio_frame(utterance_id, chunk.pcm, chunk.is_last))

    async def _broadcast(self, payload: str | bytes) -> None:
        clients = list(self._clients)
        if not clients:
            return
        await asyncio.gather(*(self._send_one(c, payload) for c in clients))

    async def _send_one(self, client: ServerConnection, payload: str | bytes) -> None:
        try:
            await asyncio.wait_for(client.send(payload), timeout=SEND_TIMEOUT_S)
        except TimeoutError:
            logger.warning(
                "A WS client did not accept data in %.1f s; dropping it so it does not block",
                SEND_TIMEOUT_S,
            )
            self._drop(client)
        except Exception as exc:  # noqa: BLE001 - a broken client must not bring the app down
            logger.debug("WS client dropped during a send (%s); discarding it", exc)
            self._drop(client)

    def _drop(self, client: ServerConnection) -> None:
        """Removes a client from the set and closes its connection in the background."""
        self._clients.discard(client)
        task = asyncio.create_task(_close_quietly(client), name="sonia-ws-close")
        self._closing.add(task)
        task.add_done_callback(self._closing.discard)

    # -- AvatarLink ---------------------------------------------------------

    async def show_image(
        self,
        *,
        image_id: str,
        source: str,
        mime: str,
        data: bytes,
        caption: str | None,
    ) -> None:
        """Shows an image on the panel of the Unity scene."""
        await self.broadcast_json(
            p.msg_show_image(
                image_id=image_id, source=source, mime=mime, data=data, caption=caption
            )
        )

    async def hide_image(self) -> None:
        """Hides the image panel."""
        await self.broadcast_json(p.msg_hide_image())

    # -- connections --------------------------------------------------------

    async def _handle_client(self, connection: ServerConnection) -> None:
        """Serves one connection from start to end."""
        self._clients.add(connection)
        logger.info("WS client connected (%d in total)", len(self._clients))
        try:
            # Unity may reconnect in the middle of an utterance: nothing is resent,
            # only the greeting with the audio format.
            await connection.send(p.dumps(p.msg_hello(self._sample_rate)))
            for msg in list(self._sticky.values()):
                await connection.send(p.dumps(msg))
            async for raw in connection:
                await self._dispatch(raw)
        except Exception as exc:  # noqa: BLE001 - abrupt closes are normal
            logger.debug("WS connection ended (%s)", exc)
        finally:
            self._clients.discard(connection)
            logger.info("WS client disconnected (%d in total)", len(self._clients))

    async def _dispatch(self, raw: str | bytes) -> None:
        """Parses an incoming message and calls its callbacks."""
        if isinstance(raw, bytes | bytearray):
            # Only text is expected from Unity; binary only goes downstream.
            return
        msg = p.parse_client_message(raw)
        if msg is None:
            logger.debug("WS message ignored (not JSON with a type)")
            return
        for callback in self._callbacks.get(msg["type"], ()):
            try:
                result = callback(msg)
                if result is not None:
                    await result
            except Exception:
                logger.exception("Error in the callback for %r", msg["type"])


async def _close_quietly(client: ServerConnection) -> None:
    """Closes a dropped connection without propagating errors or blocking."""
    with contextlib.suppress(Exception):
        await asyncio.wait_for(client.close(), timeout=SEND_TIMEOUT_S)
