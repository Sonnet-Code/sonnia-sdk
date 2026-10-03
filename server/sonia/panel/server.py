"""Servidor web del panel de control (Starlette servido con uvicorn).

Escucha solo en ``PANEL_HOST`` (127.0.0.1). Desde internet se llega por un
Cloudflare Tunnel con Cloudflare Access delante: toda petición que trae
cabeceras de Cloudflare tiene que traer también un JWT de Access válido para
la aplicación configurada (``PANEL_ACCESS_TEAM_DOMAIN`` y ``PANEL_ACCESS_AUD``);
si faltan, se rechaza. Las acciones exigen la cabecera ``X-Sonia-Panel`` y el
WebSocket comprueba el ``Origin``, para que ninguna otra web pueda manejar a
Sonia con la sesión del operador.

``starlette``, ``uvicorn`` y ``jwt`` se importan de forma perezosa (extra
``panel``): el paquete se puede importar sin ellos.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from importlib.util import find_spec
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from sonia.config import PanelSettings
from sonia.panel.control import StandControl
from sonia.panel.logs import LogBuffer
from sonia.ws import protocol as p

if TYPE_CHECKING:  # pragma: no cover - solo para tipado
    from starlette.applications import Starlette

    from sonia.ws.hub import Hub

__all__ = ["AccessVerifier", "PanelEvents", "PanelServer", "build_app", "is_available"]

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"

#: Cada cuánto se manda el estado completo por el WebSocket.
STATUS_INTERVAL_S = 0.5

#: Cabecera obligatoria en las acciones (protección contra peticiones de otras webs).
ACTION_HEADER = "x-sonia-panel"

#: Mensajes hacia Unity que no interesan en el panel.
_SKIP_MESSAGES = frozenset({p.MSG_VISEMES, p.MSG_ENVELOPE, p.MSG_REQUEST_FRAME, p.MSG_HELLO})

#: Mensajes que se guardan para pintar la página al abrirla.
_HISTORY_MESSAGES = frozenset(
    {p.MSG_TRANSCRIPT, p.MSG_SHOW_IMAGE, p.MSG_HIDE_IMAGE, p.MSG_PRESENCE, p.MSG_ERROR}
)

#: Política de contenido: todo del propio panel, nada de terceros.
_CSP = (
    "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; connect-src 'self' ws: wss:; frame-ancestors 'none'; base-uri 'none'"
)

Verifier = Callable[[str], Awaitable[bool]]


def is_available() -> bool:
    """¿Están instalados los extras del panel (``starlette``, ``uvicorn``, ``jwt``)?"""
    try:
        return all(find_spec(name) is not None for name in ("starlette", "uvicorn", "jwt"))
    except (ImportError, ValueError):  # pragma: no cover - entornos raros
        return False


class AccessVerifier:
    """Valida el JWT que Cloudflare Access pone en cada petición que deja pasar."""

    def __init__(self, team_domain: str, aud: str) -> None:
        team = team_domain.strip().removeprefix("https://").rstrip("/")
        self._team = team
        self._aud = aud.strip()
        self._client: Any = None
        #: Tokens ya validados y hasta cuándo valen (evita repetir trabajo).
        self._ok: dict[str, float] = {}

    @property
    def configured(self) -> bool:
        return bool(self._team and self._aud)

    async def __call__(self, token: str) -> bool:
        if not self.configured or not token:
            return False
        now = time.time()
        cached = self._ok.get(token)
        if cached is not None and cached > now:
            return True
        try:
            claims = await asyncio.to_thread(self._decode, token)
        except Exception as exc:  # noqa: BLE001 - cualquier fallo es un "no"
            logger.warning("Acceso remoto al panel rechazado: %s", exc)
            return False
        expires = float(claims.get("exp") or now + 60)
        if len(self._ok) > 256:
            self._ok.clear()
        self._ok[token] = min(expires, now + 300)
        return True

    def _decode(self, token: str) -> dict[str, Any]:
        import jwt

        if self._client is None:
            self._client = jwt.PyJWKClient(
                f"https://{self._team}/cdn-cgi/access/certs", cache_keys=True, lifespan=3600
            )
        key = self._client.get_signing_key_from_jwt(token)
        claims: dict[str, Any] = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            audience=self._aud,
            issuer=f"https://{self._team}",
        )
        return claims


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


def _headers(scope: dict[str, Any]) -> dict[str, str]:
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}


def _cookie(headers: dict[str, str], name: str) -> str:
    for part in headers.get("cookie", "").split(";"):
        key, _, value = part.strip().partition("=")
        if key == name:
            return value
    return ""


#: Cabeceras de seguridad de todas las respuestas HTTP.
_SECURITY_HEADERS = [
    (b"content-security-policy", _CSP.encode()),
    (b"x-frame-options", b"DENY"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"same-origin"),
]


class AccessGuard:
    """Middleware ASGI del panel.

    Lo que llega por Cloudflare necesita un JWT de Access válido, y todas las
    respuestas HTTP llevan las cabeceras de seguridad.
    """

    def __init__(self, app: Any, verifier: Verifier) -> None:
        self._app = app
        self._verify = verifier

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return
        headers = _headers(scope)
        remote = "cf-connecting-ip" in headers or "cf-ray" in headers
        if remote:
            token = headers.get("cf-access-jwt-assertion") or _cookie(headers, "CF_Authorization")
            if not await self._verify(token):
                await _deny(scope, send)
                return
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        async def send_with_headers(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                present = {k.lower() for k, _ in message.get("headers", [])}
                extra = [(k, v) for k, v in _SECURITY_HEADERS if k not in present]
                message = {**message, "headers": [*message.get("headers", []), *extra]}
            await send(message)

        await self._app(scope, receive, send_with_headers)


async def _deny(scope: dict[str, Any], send: Any) -> None:
    if scope["type"] == "websocket":
        await send({"type": "websocket.close", "code": 1008})
        return
    body = b"Acceso no autorizado al panel de Sonia."
    await send(
        {
            "type": "http.response.start",
            "status": 403,
            "headers": [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _same_origin(headers: dict[str, str]) -> bool:
    """El ``Origin`` del navegador tiene que ser el propio panel (o no venir)."""
    origin = headers.get("origin")
    if not origin:
        return True
    return urlparse(origin).netloc.lower() == headers.get("host", "").lower()


def build_app(
    control: StandControl,
    events: PanelEvents,
    *,
    verifier: Verifier,
    static_dir: Path = STATIC_DIR,
) -> Starlette:
    """La aplicación Starlette del panel."""
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response
    from starlette.routing import Mount, Route, WebSocketRoute
    from starlette.staticfiles import StaticFiles
    from starlette.websockets import WebSocket, WebSocketDisconnect

    async def index(request: Request) -> Response:
        page = static_dir / "index.html"
        if not page.is_file():
            return HTMLResponse("<h1>Panel de Sonia</h1><p>Falta la página del panel.</p>")
        return FileResponse(page, headers={"Cache-Control": "no-store"})

    async def status(request: Request) -> Response:
        return JSONResponse(control.status(), headers={"Cache-Control": "no-store"})

    async def gallery(request: Request) -> Response:
        ids = control.gallery().ids()
        return JSONResponse({"images": [{"id": i, "url": f"/api/gallery/{i}"} for i in ids]})

    async def gallery_image(request: Request) -> Response:
        loaded = control.gallery().load(str(request.path_params["image_id"]))
        if loaded is None:
            return JSONResponse({"ok": False, "message": "No existe esa imagen."}, status_code=404)
        data, mime = loaded
        return Response(data, media_type=mime, headers={"Cache-Control": "max-age=60"})

    async def action(request: Request) -> Response:
        if request.headers.get(ACTION_HEADER) != "1":
            return JSONResponse({"ok": False, "message": "Petición no permitida."}, status_code=403)
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict) or not isinstance(body.get("action"), str):
            return JSONResponse({"ok": False, "message": "Petición mal formada."}, status_code=400)
        params = {k: v for k, v in body.items() if k != "action"}
        ok, message = await control.act(body["action"], params)
        return JSONResponse({"ok": ok, "message": message}, status_code=200 if ok else 400)

    async def events_ws(ws: WebSocket) -> None:
        if not _same_origin({k.lower(): v for k, v in ws.headers.items()}):
            await ws.close(code=1008)
            return
        await ws.accept()
        queue = events.subscribe()

        async def drain() -> None:
            # Solo para enterarse de que el navegador cerró la conexión.
            with contextlib.suppress(Exception):
                while True:
                    await ws.receive_text()

        receiver = asyncio.create_task(drain(), name="sonia-panel-ws-drain")
        try:
            await ws.send_json(events.history())
            await ws.send_json({"type": "status", "status": control.status()})
            last_status = time.monotonic()
            while not receiver.done():
                timeout = max(0.05, STATUS_INTERVAL_S - (time.monotonic() - last_status))
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=timeout)
                    await ws.send_json(item)
                except TimeoutError:
                    pass
                if time.monotonic() - last_status >= STATUS_INTERVAL_S:
                    await ws.send_json({"type": "status", "status": control.status()})
                    last_status = time.monotonic()
        except (WebSocketDisconnect, RuntimeError, OSError):
            pass
        finally:
            events.unsubscribe(queue)
            receiver.cancel()
            await asyncio.gather(receiver, return_exceptions=True)

    from starlette.middleware import Middleware

    return Starlette(
        middleware=[Middleware(AccessGuard, verifier=verifier)],
        routes=[
            Route("/", index),
            Route("/api/status", status),
            Route("/api/gallery", gallery),
            Route("/api/gallery/{image_id}", gallery_image),
            Route("/api/action", action, methods=["POST"]),
            WebSocketRoute("/api/events", events_ws),
            Mount("/static", StaticFiles(directory=static_dir, check_dir=False), name="static"),
        ],
    )


class PanelServer:
    """Arranca y para el panel dentro del proceso del orquestador."""

    def __init__(
        self,
        settings: PanelSettings,
        control: StandControl,
        hub: Hub,
        logs: LogBuffer | None = None,
        *,
        verifier: Verifier | None = None,
    ) -> None:
        self._settings = settings
        self._control = control
        self._logs = logs
        self.events = PanelEvents(hub, logs)
        access = AccessVerifier(settings.access_team_domain, settings.access_aud)
        self._verifier: Verifier = verifier or access
        self._access_configured = verifier is not None or access.configured
        self._uvicorn: Any = None
        self._task: asyncio.Task[None] | None = None

    @property
    def url(self) -> str:
        return f"http://{self._settings.host}:{self.port}/"

    @property
    def port(self) -> int:
        servers = getattr(self._uvicorn, "servers", None) or []
        for server in servers:
            for sock in getattr(server, "sockets", None) or []:
                return int(sock.getsockname()[1])
        return self._settings.port

    async def start(self) -> None:
        import uvicorn

        if self._logs is not None:
            self._logs.bind(asyncio.get_running_loop())
        app = build_app(self._control, self.events, verifier=self._verifier)
        config = uvicorn.Config(
            app,
            host=self._settings.host,
            port=self._settings.port,
            log_level="warning",
            lifespan="off",
            access_log=False,
        )
        self._uvicorn = uvicorn.Server(config)
        # ``_serve`` en vez de ``serve`` para no secuestrar las señales del
        # proceso (igual que el servidor MCP).
        run = getattr(self._uvicorn, "_serve", None) or self._uvicorn.serve
        self._task = asyncio.create_task(run(), name="sonia-panel")
        for _ in range(100):
            if getattr(self._uvicorn, "started", False):
                break
            if self._task.done():
                exc = self._task.exception()
                raise RuntimeError(f"el panel no arrancó: {exc}")
            await asyncio.sleep(0.05)
        if not self._access_configured:
            logger.warning(
                "Panel sin Cloudflare Access configurado (PANEL_ACCESS_TEAM_DOMAIN y "
                "PANEL_ACCESS_AUD): solo funciona en este equipo"
            )
        logger.info("Panel de control en %s", self.url)

    async def stop(self) -> None:
        server, self._uvicorn = self._uvicorn, None
        task, self._task = self._task, None
        if server is not None:
            server.should_exit = True
        if task is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(task, timeout=5.0)
