"""Web server of the control panel (Starlette served with uvicorn).

It only listens on ``PANEL_HOST`` (127.0.0.1 by default) and has no login of its
own: do not expose it to a network you do not trust. Actions require the
``X-Sonia-Panel`` header and the WebSocket checks the ``Origin``, so that no other
web page can drive Sonnia from the operator's browser.

``starlette`` and ``uvicorn`` are imported lazily (``panel`` extra): the package can
be imported without them.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from importlib.util import find_spec
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from sonia.config import PanelSettings
from sonia.panel.control import PanelControl
from sonia.panel.events import PanelEvents
from sonia.panel.logs import LogBuffer

if TYPE_CHECKING:  # pragma: no cover - typing only
    from starlette.applications import Starlette

    from sonia.ws.hub import Hub

__all__ = ["PanelServer", "build_app", "is_available"]

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"

#: How often the full status is sent over the WebSocket.
STATUS_INTERVAL_S = 0.5

#: Mandatory header on actions (protection against requests from other web pages).
ACTION_HEADER = "x-sonia-panel"


#: Content policy: everything from the panel itself, nothing from third parties.
_CSP = (
    "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; connect-src 'self' ws: wss:; frame-ancestors 'none'; base-uri 'none'"
)


def is_available() -> bool:
    """Are the panel extras (``starlette``, ``uvicorn``) installed?"""
    try:
        return all(find_spec(name) is not None for name in ("starlette", "uvicorn"))
    except (ImportError, ValueError):  # pragma: no cover - odd environments
        return False


#: Security headers of every HTTP response.
_SECURITY_HEADERS = [
    (b"content-security-policy", _CSP.encode()),
    (b"x-frame-options", b"DENY"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"same-origin"),
]


class SecurityHeaders:
    """ASGI middleware of the panel: every HTTP response carries the security headers."""

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
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


def _same_origin(headers: dict[str, str]) -> bool:
    """The browser ``Origin`` has to be the panel itself (or be missing)."""
    origin = headers.get("origin")
    if not origin:
        return True
    return urlparse(origin).netloc.lower() == headers.get("host", "").lower()


def build_app(
    control: PanelControl,
    events: PanelEvents,
    *,
    static_dir: Path = STATIC_DIR,
) -> Starlette:
    """The Starlette application of the panel."""
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.requests import Request
    from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response
    from starlette.routing import Mount, Route, WebSocketRoute
    from starlette.staticfiles import StaticFiles
    from starlette.websockets import WebSocket, WebSocketDisconnect

    async def index(request: Request) -> Response:
        page = static_dir / "index.html"
        if not page.is_file():
            return HTMLResponse("<h1>Sonnia panel</h1><p>The panel page is missing.</p>")
        return FileResponse(page, headers={"Cache-Control": "no-store"})

    async def status(request: Request) -> Response:
        return JSONResponse(control.status(), headers={"Cache-Control": "no-store"})

    async def gallery(request: Request) -> Response:
        # The disk is read in a thread. Uploads from the panel start with ``upload-``.
        ids = await asyncio.to_thread(control.gallery().ids)
        images = [{"id": i, "url": f"/api/gallery/{i}"} for i in ids]
        return JSONResponse({"images": images}, headers={"Cache-Control": "no-store"})

    async def gallery_image(request: Request) -> Response:
        image_id = str(request.path_params["image_id"])
        loaded = await asyncio.to_thread(control.gallery().load, image_id)
        if loaded is None:
            return JSONResponse({"ok": False, "message": "No such image."}, status_code=404)
        data, mime = loaded
        return Response(data, media_type=mime, headers={"Cache-Control": "max-age=60"})

    async def action(request: Request) -> Response:
        if request.headers.get(ACTION_HEADER) != "1":
            return JSONResponse({"ok": False, "message": "Request not allowed."}, status_code=403)
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict) or not isinstance(body.get("action"), str):
            return JSONResponse({"ok": False, "message": "Malformed request."}, status_code=400)
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
            # Only to notice that the browser closed the connection.
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

    return Starlette(
        middleware=[Middleware(SecurityHeaders)],
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
    """Starts and stops the panel inside the orchestrator process."""

    def __init__(
        self,
        settings: PanelSettings,
        control: PanelControl,
        hub: Hub,
        logs: LogBuffer | None = None,
        *,
        events: PanelEvents | None = None,
    ) -> None:
        self._settings = settings
        self._control = control
        self._logs = logs
        self.events = events or PanelEvents(hub, logs)
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
        app = build_app(self._control, self.events)
        config = uvicorn.Config(
            app,
            host=self._settings.host,
            port=self._settings.port,
            log_level="warning",
            lifespan="off",
            access_log=False,
        )
        self._uvicorn = uvicorn.Server(config)
        # ``_serve`` instead of ``serve`` so the process signals are not hijacked.
        run = getattr(self._uvicorn, "_serve", None) or self._uvicorn.serve
        self._task = asyncio.create_task(run(), name="sonia-panel")
        for _ in range(100):
            if getattr(self._uvicorn, "started", False):
                break
            if self._task.done():
                exc = self._task.exception()
                raise RuntimeError(f"the panel did not start: {exc}")
            await asyncio.sleep(0.05)
        logger.info("Control panel at %s", self.url)

    async def stop(self) -> None:
        server, self._uvicorn = self._uvicorn, None
        task, self._task = self._task, None
        if server is not None:
            server.should_exit = True
        if task is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(task, timeout=5.0)
