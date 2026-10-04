"""Conexión de esta Sonia con el panel de Cloudflare (``docs/panel.md``).

El panel vive en un Worker de Cloudflare y cada Sonia se conecta a él hacia
fuera por WebSocket (``PANEL_CLOUD_URL``, con ``PANEL_CLOUD_TOKEN``): no hace
falta abrir puertos ni túneles en el equipo del stand, y el panel ve todas las
Sonias conectadas, también las duplicadas.

Por la conexión sube lo mismo que ve el panel local (estado, conversación,
registro) y baja cada acción del operador, que se ejecuta con
:meth:`StandControl.act` exactamente igual que desde el panel local.

También viajan los ajustes compartidos (``SHARED_SETTINGS``): la nube guarda
una copia única para todas las Sonias. Lo que cambia cualquier panel, también
el local, sube como ``settings`` y la nube lo reparte a las demás; al conectar,
el ``hello`` lleva lo cambiado aquí sin conexión y la nube contesta con sus
ajustes, que esta Sonia aplica.

Nada de esto puede tumbar a Sonia: si Cloudflare no responde, se reintenta con
espera creciente y la demo sigue igual.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from sonia import __version__
from sonia.config import PanelSettings
from sonia.panel.control import StandControl
from sonia.panel.events import PanelEvents
from sonia.panel.identity import InstanceIdentity

__all__ = ["CloudLink"]

logger = logging.getLogger(__name__)

#: ``(url, cabeceras) -> conexión``; los tests inyectan uno contra un servidor falso.
CloudConnect = Callable[[str, dict[str, str]], Awaitable[Any]]

#: Estado cada medio segundo si alguien mira esta Sonia; si no, cada 15 s.
FAST_STATUS_S = 0.5
SLOW_STATUS_S = 15.0

RECONNECT_MIN_S = 1.0
RECONNECT_MAX_S = 30.0

#: Una conexión que aguantó esto reinicia la espera entre reintentos.
HEALTHY_CONNECTION_S = 60.0

#: Tope de un mensaje entrante (las acciones son pequeñas).
_MAX_SIZE = 1024 * 1024

#: Los cambios de ajustes se juntan durante esto antes de subir (un deslizador
#: del panel manda varios por segundo mientras se arrastra).
SETTINGS_DEBOUNCE_S = 0.4

#: Marca interna para despertar el bucle de envío (no se manda a Cloudflare).
_WAKE: dict[str, Any] = {"type": "_wake"}

#: Marca interna: hay ajustes cambiados que subir.
_SETTINGS: dict[str, Any] = {"type": "_settings"}


class CloudLink:
    """Mantiene la conexión con el panel de Cloudflare mientras corre Sonia."""

    def __init__(
        self,
        settings: PanelSettings,
        control: StandControl,
        events: PanelEvents,
        identity: InstanceIdentity,
        *,
        connect: CloudConnect | None = None,
    ) -> None:
        self._settings = settings
        self._control = control
        self._events = events
        self._identity = identity
        self._connect = connect or _default_connect
        self._viewers = 0
        self._send_lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[None]] = set()
        self._queue: asyncio.Queue[dict[str, Any]] | None = None
        self.connected = False
        control.add_settings_listener(self._on_settings_changed)
        control.set_cloud_state("offline" if self.enabled else "off")

    @property
    def enabled(self) -> bool:
        return bool(self._settings.cloud_url and self._settings.cloud_token)

    # -- bucle -----------------------------------------------------------------

    async def run(self) -> None:
        """Conecta y reconecta para siempre. Solo termina al cancelarlo."""
        if not self.enabled:
            return
        delay = RECONNECT_MIN_S
        while True:
            started = time.monotonic()
            try:
                ws = await self._connect(self._settings.cloud_url, self._headers())
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - sin panel en la nube, Sonia sigue
                logger.warning("No se pudo conectar con el panel de Cloudflare: %s", _reason(exc))
            else:
                try:
                    await self._session(ws)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Se cortó la conexión con el panel de Cloudflare: %s", exc)
                finally:
                    self.connected = False
                    self._control.set_cloud_state("offline")
                    with contextlib.suppress(Exception):
                        await ws.close()
            if time.monotonic() - started > HEALTHY_CONNECTION_S:
                delay = RECONNECT_MIN_S
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX_S)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._settings.cloud_token}",
            "X-Sonia-Instance": self._identity.id,
            "X-Sonia-Name": _header_safe(self._identity.name),
        }

    async def _session(self, ws: Any) -> None:
        queue = self._events.subscribe()
        self._queue = queue
        reader = asyncio.create_task(self._read(ws), name="sonia-cloud-read")
        getter: asyncio.Task[dict[str, Any]] | None = None
        flush_at: float | None = None
        try:
            await self._send(ws, self._hello())
            self.connected = True
            self._control.set_cloud_state("online")
            logger.info(
                "Conectada al panel de Cloudflare como «%s» (%s)",
                self._identity.name,
                self._identity.id,
            )
            last_status = time.monotonic()
            while True:
                interval = FAST_STATUS_S if self._viewers > 0 else SLOW_STATUS_S
                timeout = max(0.05, interval - (time.monotonic() - last_status))
                if flush_at is not None:
                    timeout = min(timeout, max(0.0, flush_at - time.monotonic()))
                if getter is None:
                    getter = asyncio.create_task(queue.get(), name="sonia-cloud-queue")
                # Se espera a la vez lo que hay que subir y al lector: si
                # Cloudflare corta, se reconecta sin esperar al siguiente estado.
                done, _ = await asyncio.wait(
                    {getter, reader}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
                )
                if reader in done:
                    reader.result()  # si terminó por un error, que se vea
                    return
                if getter in done:
                    item = getter.result()
                    getter = None
                    if item is _SETTINGS:
                        if flush_at is None:
                            flush_at = time.monotonic() + SETTINGS_DEBOUNCE_S
                    elif item is not _WAKE:
                        await self._send(ws, item)
                if flush_at is not None and time.monotonic() >= flush_at:
                    flush_at = None
                    await self._send_settings(ws)
                if time.monotonic() - last_status >= interval:
                    await self._send(ws, {"type": "status", "status": self._control.status()})
                    last_status = time.monotonic()
        finally:
            self._queue = None
            self._events.unsubscribe(queue)
            pending = [t for t in (reader, getter, *self._tasks) if t is not None]
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    async def _read(self, ws: Any) -> None:
        from websockets.exceptions import ConnectionClosed

        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                if not isinstance(msg, dict):
                    continue
                kind = msg.get("type")
                if kind == "action":
                    task = asyncio.create_task(self._run_action(ws, msg), name="sonia-cloud-act")
                    self._tasks.add(task)
                    task.add_done_callback(self._tasks.discard)
                elif kind == "viewers":
                    count = msg.get("count")
                    if isinstance(count, int) and not isinstance(count, bool):
                        self._viewers = max(0, count)
                        # Despierta al bucle para que cambie de ritmo ya.
                        if self._queue is not None:
                            with contextlib.suppress(asyncio.QueueFull):
                                self._queue.put_nowait(_WAKE)
                elif kind == "sync":
                    await self._send(ws, self._hello())
                elif kind == "settings":
                    await self._apply_settings(msg)
        except ConnectionClosed:
            return

    async def _apply_settings(self, msg: dict[str, Any]) -> None:
        """Ajustes que manda la nube (al conectar o porque otro panel los cambió)."""
        values = msg.get("settings")
        if not isinstance(values, dict):
            return
        try:
            await self._control.apply_cloud_settings(
                values, rev=_int(msg.get("rev")), ack=_int(msg.get("ack"))
            )
        except Exception:
            logger.exception("No se pudieron aplicar los ajustes de la nube")

    def _on_settings_changed(self) -> None:
        if self._queue is not None:
            with contextlib.suppress(asyncio.QueueFull):
                self._queue.put_nowait(_SETTINGS)

    async def _send_settings(self, ws: Any) -> None:
        changes, seq = self._control.pending_settings()
        if changes:
            await self._send(ws, {"type": "settings", "changes": changes, "seq": seq})

    async def _run_action(self, ws: Any, msg: dict[str, Any]) -> None:
        request_id = msg.get("request_id")
        action = msg.get("action")
        params = msg.get("params")
        if not isinstance(action, str):
            ok, message = False, "Acción mal formada."
        else:
            ok, message = await self._control.act(
                action, params if isinstance(params, dict) else {}
            )
        with contextlib.suppress(Exception):
            await self._send(
                ws, {"type": "result", "request_id": request_id, "ok": ok, "message": message}
            )
            # El estado nuevo sube ya: si nadie mira esta Sonia, el siguiente
            # tardaría hasta 15 s y el panel seguiría mostrando el modo anterior.
            await self._send(ws, {"type": "status", "status": self._control.status()})

    def _hello(self) -> dict[str, Any]:
        history = self._events.history()
        identity = self._identity
        control = self._control
        status = control.status()
        pending, seq = control.pending_settings()
        return {
            "type": "hello",
            "instance": {
                "id": identity.id,
                "name": identity.name,
                "host": identity.host,
                "engine": status.get("engine"),
                "version": __version__,
            },
            "status": status,
            "history": {"messages": history["messages"], "logs": history["logs"]},
            "gallery": control.gallery().ids(),
            # Todos los ajustes (por si la nube aún no tiene ninguno) y cuáles
            # cambiaron aquí sin conexión: esos mandan sobre los de la nube.
            "settings": {
                "values": control.shared_settings(),
                "pending": sorted(pending),
                "seq": seq,
            },
        }

    async def _send(self, ws: Any, item: dict[str, Any]) -> None:
        payload = json.dumps(item, ensure_ascii=False)
        async with self._send_lock:
            await ws.send(payload)


async def _default_connect(url: str, headers: dict[str, str]) -> Any:
    from websockets.asyncio.client import connect

    return await connect(
        url,
        additional_headers=headers,
        max_size=_MAX_SIZE,
        open_timeout=15,
        ping_interval=20,
        ping_timeout=20,
        compression=None,
    )


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _header_safe(text: str) -> str:
    """Las cabeceras HTTP solo admiten ASCII: el nombre va codificado como URL."""
    from urllib.parse import quote

    return quote(text[:80], safe=" ")


def _reason(exc: Exception) -> str:
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status in (401, 403):
        return f"HTTP {status}: revisa PANEL_CLOUD_TOKEN"
    if status is not None:
        return f"HTTP {status}"
    return str(exc) or type(exc).__name__
