"""Cliente WebSocket de la API Live de OpenAI (GPT-Live), sin SDK.

Solo ``websockets`` y JSON, igual que el TTS de Gemini. Este módulo no sabe
nada de Unity ni de la conversación: abre la sesión, manda comandos y entrega
los eventos del servidor tal cual. La lógica vive en :mod:`sonia.live.engine`.

Protocolo implementado (consultado el 3 de octubre de 2026):

- https://developers.openai.com/api/docs/models/gpt-live-1 y
  https://developers.openai.com/api/docs/guides/live-conversations
  ``wss://api.openai.com/v1/live/sessions`` con ``Authorization: Bearer``; el
  primer mensaje es ``session.start`` y no se manda nada más hasta recibir
  ``session.started``.
- https://learn.microsoft.com/azure/foundry/openai/gpt-live-reference
  Referencia completa de eventos de cliente y de servidor, y formato de audio:
  PCM s16le mono sin cabecera, en base64.
- https://developers.openai.com/api/docs/guides/live-delegation
  Delegación en un backend de la API Responses (``response.event``,
  ``response.item.create``, ``response.create``).
- Tipos del SDK oficial ``openai`` 3.24 (``openai/types/live``): campos exactos
  de ``SessionConfig`` (``audio.format`` con ``rate`` 16000 o 24000, límite de
  16 384 tokens en ``instructions``) y de cada evento.

Los appends (``session.thinking.append`` y compañía) admiten como mucho 500
tokens; el texto se recorta antes de enviarlo para no provocar un error.
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

#: ``(url, cabeceras) -> conexión``. Los tests inyectan uno que apunta a un
#: servidor falso.
WsConnect = Callable[[str, dict[str, str]], Awaitable[Any]]

#: Recorte de seguridad para los appends (500 tokens son unos 2 000
#: caracteres en español; se deja margen).
APPEND_MAX_CHARS = 1_600

#: Tope de un mensaje entrante. Los eventos de GPT-Live son pequeños, pero un
#: ``session.started`` devuelve las instrucciones completas.
_WS_MAX_SIZE = 16 * 1024 * 1024

#: Lo que se espera a ``session.closed`` al cerrar antes de cortar el socket.
_CLOSE_WAIT_S = 2.0


class LiveError(RuntimeError):
    """Fallo al abrir o usar una sesión de GPT-Live."""


class LiveClient:
    """Una sesión de GPT-Live sobre un WebSocket primario.

    Uso::

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
        #: Eventos que llegaron antes de ``session.started`` (``info``, por ejemplo).
        self._early: list[dict[str, Any]] = []
        self._counter = 0
        self._send_lock = asyncio.Lock()
        self._closed = asyncio.Event()
        #: Cierto mientras alguien consume :meth:`events`.
        self._reading = False
        self.close_reason = ""

    # -- propiedades --------------------------------------------------------

    @property
    def session(self) -> dict[str, Any]:
        """El recurso de sesión que devolvió ``session.started``."""
        return self._session

    @property
    def session_id(self) -> str:
        return str(self._session.get("id") or "")

    @property
    def expires_at(self) -> float | None:
        """Instante Unix en que caduca la sesión, si el servidor lo dijo."""
        value = self._session.get("expires_at")
        return float(value) if isinstance(value, int | float) else None

    @property
    def is_open(self) -> bool:
        return self._ws is not None and not self._closed.is_set()

    # -- arranque -----------------------------------------------------------

    async def start(self, session: dict[str, Any]) -> dict[str, Any]:
        """Conecta, envía ``session.start`` y espera ``session.started``."""
        settings = self._settings
        if self._connect is None and not settings.api_key:
            raise LiveError("Falta LIVE_API_KEY (u OPENAI_API_KEY) en .env para usar GPT-Live.")
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
                            "GPT-Live cerró la conexión antes de confirmar la sesión"
                            f" ({self.close_reason or 'sin motivo'})."
                        )
                    kind = event.get("type")
                    if kind == "session.started":
                        resource = event.get("session")
                        self._session = resource if isinstance(resource, dict) else {}
                        return self._session
                    if kind == "error":
                        raise LiveError(f"GPT-Live rechazó la sesión: {describe_error(event)}")
                    self._early.append(event)
        except TimeoutError as exc:
            await self._abort()
            raise LiveError(
                f"GPT-Live no confirmó la sesión en {settings.connect_timeout:g} s."
            ) from exc
        except BaseException:
            await self._abort()
            raise

    # -- eventos del servidor -----------------------------------------------

    async def events(self) -> AsyncGenerator[dict[str, Any]]:
        """Eventos del servidor en orden hasta que la conexión se cierra."""
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
        """Siguiente evento JSON, o ``None`` si la conexión terminó."""
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
                        f"cierre {code}: {getattr(frame, 'reason', '') or 'sin motivo'}"
                    )
                self._closed.set()
                return None
            if isinstance(raw, bytes | bytearray):
                raw = bytes(raw).decode("utf-8", errors="replace")
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                logger.debug("GPT-Live envió algo que no es JSON; se ignora")
                continue
            if isinstance(event, dict) and isinstance(event.get("type"), str):
                if event["type"] == "session.closed":
                    self.close_reason = str(event.get("reason") or "")
                    self._closed.set()
                return event

    # -- comandos -----------------------------------------------------------

    def next_event_id(self, prefix: str = "sonia") -> str:
        self._counter += 1
        return f"{prefix}_{self._counter}"

    async def send(self, event: dict[str, Any]) -> str:
        """Envía un comando. Devuelve su ``event_id`` (para casar errores)."""
        ws = self._ws
        if ws is None:
            raise LiveError("La sesión de GPT-Live no está abierta.")
        payload = dict(event)
        event_id = str(payload.get("event_id") or self.next_event_id())
        payload["event_id"] = event_id
        async with self._send_lock:
            await ws.send(json.dumps(payload, ensure_ascii=False))
        return event_id

    async def append_audio(self, pcm: bytes) -> None:
        """Audio del micrófono (PCM s16le mono a la tasa de la sesión). Sin acuse."""
        if not pcm:
            return
        if len(pcm) % 2:
            pcm = pcm[:-1]
        ws = self._ws
        if ws is None:
            return
        # Sin event_id: el audio no tiene acuse y ahorra bytes en cada bloque.
        message = json.dumps(
            {
                "type": "session.input_audio.append",
                "audio": base64.b64encode(pcm).decode("ascii"),
            }
        )
        async with self._send_lock:
            await ws.send(message)

    async def append_instructions(self, content: str, delegation_id: str | None = None) -> str:
        """Instrucciones de confianza que cambian lo que hace o dice el modelo."""
        return await self._append("session.instructions.append", content, delegation_id)

    async def append_thinking(self, content: str, delegation_id: str | None = None) -> str:
        """Contexto silencioso: el modelo lo usa pero no lo dice al recibirlo."""
        return await self._append("session.thinking.append", content, delegation_id)

    async def append_commentary(self, content: str, delegation_id: str | None = None) -> str:
        """Contenido que el modelo debe decir en voz alta (puede parafrasearlo)."""
        return await self._append("session.commentary.append", content, delegation_id)

    async def _append(self, kind: str, content: str, delegation_id: str | None) -> str:
        text = content.strip()
        if len(text) > APPEND_MAX_CHARS:
            text = text[: APPEND_MAX_CHARS - 1].rstrip() + "…"
        # ``delegation_id`` es obligatorio aunque sea null.
        return await self.send({"type": kind, "content": text, "delegation_id": delegation_id})

    async def create_item(self, item: dict[str, Any]) -> str:
        """Añade un item (resultado de una acción, mensaje) al backend Responses."""
        return await self.send({"type": "response.item.create", "item": item})

    async def create_response(self) -> str:
        """Continúa la respuesta del backend que esperaba resultados de acciones."""
        return await self.send({"type": "response.create"})

    # -- cierre -------------------------------------------------------------

    async def close(self, *, wait: bool = True) -> None:
        """Cierre ordenado: ``session.close`` y espera a ``session.closed``.

        Si otra tarea está leyendo :meth:`events`, verá ``session.closed`` y
        terminará; si nadie lee, se lee aquí. Con ``wait=False`` (al apagar) se
        pide el cierre y se corta sin esperar respuesta.
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

    # -- conexión real ------------------------------------------------------

    async def _default_connect(self, url: str, headers: dict[str, str]) -> Any:
        """Conexión real. Se importa aquí para no cargar ``websockets`` al importar."""
        from websockets.asyncio.client import connect

        return await connect(
            url,
            additional_headers=headers,
            max_size=_WS_MAX_SIZE,
            open_timeout=self._settings.connect_timeout,
            # El audio en base64 apenas se comprime y comprimir añade latencia.
            compression=None,
        )

    def _handshake_error(self, exc: Exception) -> LiveError:
        """Traduce un fallo al conectar a un error que se entienda sin el código."""
        if isinstance(exc, LiveError):
            return exc
        if isinstance(exc, TimeoutError):
            return LiveError(
                f"GPT-Live no aceptó la conexión en {self._settings.connect_timeout:g} s."
            )
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (401, 403):
            return LiveError(
                f"GPT-Live rechazó la conexión (HTTP {status}). Revisa LIVE_API_KEY y que el "
                f"proyecto tenga acceso a {self._settings.model!r}."
            )
        if status is not None:
            return LiveError(f"GPT-Live devolvió HTTP {status} al conectar.")
        return LiveError(f"No se pudo conectar con GPT-Live: {exc}")


def describe_error(event: dict[str, Any]) -> str:
    """Texto legible de un evento ``error`` de GPT-Live."""
    error = event.get("error")
    if not isinstance(error, dict):
        return json.dumps(event, ensure_ascii=False)[:300]
    code = error.get("code") or error.get("type") or "error"
    message = error.get("message") or ""
    param = error.get("param")
    detail = f"{code}: {message}" if message else str(code)
    return f"{detail} (param {param})" if param else detail
