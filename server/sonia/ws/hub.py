"""Servidor WebSocket que conecta el orquestador con Unity.

El hub mantiene el conjunto de clientes conectados, les envía ``hello`` al
entrar, difunde JSON y frames binarios de audio, y despacha los mensajes
entrantes a los callbacks registrados con :meth:`Hub.on`.

Regla de oro para el stand: nada de lo que hace el hub puede tumbar la demo.
Si no hay clientes, si Unity se cae en mitad de un envío o si un callback
lanza, se registra y se sigue.
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

if TYPE_CHECKING:  # pragma: no cover - solo para tipado
    from websockets.asyncio.server import Server, ServerConnection

logger = logging.getLogger(__name__)

#: Un callback puede ser síncrono o asíncrono.
MessageCallback = Callable[[dict[str, Any]], Awaitable[None] | None]

#: Tamaño máximo de un mensaje entrante. El valor por defecto de ``websockets``
#: (1 MiB) se queda corto para un ``camera_frame`` de Unity: un JPEG de una
#: webcam 4K en base64 lo supera y el servidor cerraría la conexión con 1009.
MAX_MESSAGE_SIZE = 16 * 1024 * 1024

#: Keepalive corto: un Unity congelado se detecta en segundos, no en un minuto.
PING_INTERVAL_S = 5.0
PING_TIMEOUT_S = 5.0

#: Tope de espera de un envío a un cliente. Si Unity deja de leer, su buffer de
#: escritura se llena y ``send`` no vuelve nunca: eso bloquearía el bucle del
#: orquestador entero (``stop_speaking``, ``state``). Al vencer se descarta ese
#: cliente, que de todas formas ya no está reproduciendo nada.
SEND_TIMEOUT_S = 1.0


class Hub:
    """Servidor WebSocket local. Implementa ``AvatarLink`` para las acciones."""

    def __init__(self, settings: WSSettings, sample_rate: int) -> None:
        self._settings = settings
        self._sample_rate = sample_rate
        self._clients: set[ServerConnection] = set()
        self._callbacks: dict[str, list[MessageCallback]] = {}
        self._server: Server | None = None
        #: Cierres en curso de clientes descartados (referencia fuerte).
        self._closing: set[asyncio.Task[None]] = set()

    # -- ciclo de vida ------------------------------------------------------

    async def start(self) -> None:
        """Empieza a escuchar. Idempotente."""
        if self._server is not None:
            return
        from websockets.asyncio.server import serve

        self._server = await serve(
            self._handle_client,
            self._settings.host,
            self._settings.port,
            # El audio va en chunks pequeños; comprimir solo añade latencia.
            compression=None,
            max_size=MAX_MESSAGE_SIZE,
            ping_interval=PING_INTERVAL_S,
            ping_timeout=PING_TIMEOUT_S,
        )
        logger.info("Hub WebSocket escuchando en ws://%s:%d/", self._settings.host, self.port)

    async def stop(self) -> None:
        """Cierra el servidor y todas las conexiones. Idempotente."""
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
        logger.info("Hub WebSocket detenido")

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

    # -- estado -------------------------------------------------------------

    @property
    def client_count(self) -> int:
        """Número de clientes conectados ahora mismo."""
        return len(self._clients)

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def port(self) -> int:
        """Puerto real en el que escucha (útil cuando se pidió el puerto 0)."""
        if self._server is None:
            return self._settings.port
        sockets = self._server.sockets
        if not sockets:  # pragma: no cover - el servidor siempre trae socket
            return self._settings.port
        return int(sockets[0].getsockname()[1])

    # -- callbacks ----------------------------------------------------------

    def on(self, type: str, callback: MessageCallback) -> None:
        """Registra un callback para los mensajes entrantes de ese ``type``.

        Puede haber varios callbacks por tipo; se ejecutan en orden de registro.
        """
        self._callbacks.setdefault(type, []).append(callback)

    # -- envío --------------------------------------------------------------

    async def broadcast_json(self, msg: dict[str, Any]) -> None:
        """Envía un mensaje JSON a todos los clientes. Nunca lanza."""
        await self._broadcast(p.dumps(msg))

    async def broadcast_bytes(self, data: bytes) -> None:
        """Envía un frame binario a todos los clientes. Nunca lanza."""
        await self._broadcast(data)

    async def send_audio(self, utterance_id: int, chunk: AudioChunk) -> None:
        """Codifica un chunk de TTS como frame binario y lo difunde."""
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
                "Un cliente WS no acepta datos en %.1f s; se descarta para no bloquear la demo",
                SEND_TIMEOUT_S,
            )
            self._drop(client)
        except Exception as exc:  # noqa: BLE001 - un cliente roto no tumba la demo
            logger.debug("Cliente WS caído durante el envío (%s); se descarta", exc)
            self._drop(client)

    def _drop(self, client: ServerConnection) -> None:
        """Saca a un cliente del conjunto y cierra su conexión en segundo plano."""
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
        """Muestra una imagen en el panel de la escena de Unity."""
        await self.broadcast_json(
            p.msg_show_image(
                image_id=image_id, source=source, mime=mime, data=data, caption=caption
            )
        )

    async def hide_image(self) -> None:
        """Retira el panel de imágenes."""
        await self.broadcast_json(p.msg_hide_image())

    # -- conexiones ---------------------------------------------------------

    async def _handle_client(self, connection: ServerConnection) -> None:
        """Atiende una conexión de principio a fin."""
        self._clients.add(connection)
        logger.info("Cliente WS conectado (%d en total)", len(self._clients))
        try:
            # Unity puede reconectar en mitad de una frase: no reenviamos nada,
            # solo el saludo con el formato de audio.
            await connection.send(p.dumps(p.msg_hello(self._sample_rate)))
            async for raw in connection:
                await self._dispatch(raw)
        except Exception as exc:  # noqa: BLE001 - cierres bruscos son normales
            logger.debug("Conexión WS terminada (%s)", exc)
        finally:
            self._clients.discard(connection)
            logger.info("Cliente WS desconectado (%d en total)", len(self._clients))

    async def _dispatch(self, raw: str | bytes) -> None:
        """Parsea un mensaje entrante y llama a sus callbacks."""
        if isinstance(raw, bytes | bytearray):
            # De Unity solo esperamos texto; el binario es solo de bajada.
            return
        msg = p.parse_client_message(raw)
        if msg is None:
            logger.debug("Mensaje WS ignorado (no es JSON con type)")
            return
        for callback in self._callbacks.get(msg["type"], ()):
            try:
                result = callback(msg)
                if result is not None:
                    await result
            except Exception:
                logger.exception("Error en el callback de %r", msg["type"])


async def _close_quietly(client: ServerConnection) -> None:
    """Cierra una conexión descartada sin propagar errores ni bloquear."""
    with contextlib.suppress(Exception):
        await asyncio.wait_for(client.close(), timeout=SEND_TIMEOUT_S)
