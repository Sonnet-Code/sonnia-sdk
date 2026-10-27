"""El renderizador: «Sonnia Video.app», una build de Unity que se queda abierta esperando trabajos.

Se arranca con ``-sonnia-video -sonnia-video-port <puerto> -logFile <ruta>`` en un
proceso aparte que sobrevive a ``sonnia-video`` (cargar el avatar de Genies tarda de
10 s a varios minutos la primera vez: mejor no pagarlo en cada vídeo) y se le habla
por HTTP en ``127.0.0.1:<puerto>`` (``docs/video.md``, «Contrato con Unity»):
``/status``, ``/catalog``, ``/job``, ``/cancel`` y ``/quit``. ``sonnia-video cerrar``
la cierra.

Dónde se busca la app: ``SONNIA_VIDEO_APP``; si ``sonnia-video`` va congelado dentro
de una app (``X.app/Contents/Resources/sonnia-video/``), esa; la build del repo
(``unity/Build/macOS-video/Sonnia Video.app``); y ``/Applications``.
"""

from __future__ import annotations

import contextlib
import logging
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

import httpx

from sonia.paths import REPO_ROOT, frozen
from sonia.video.errors import VideoError

__all__ = [
    "STALL_RESTART_S",
    "AvatarTimeout",
    "Cancelled",
    "DEFAULT_PORT",
    "Progress",
    "RendererClient",
    "app_executable",
    "ensure_started",
    "find_app",
    "launch",
    "launch_args",
    "port",
    "quit_and_wait",
    "run_job",
    "wait_ready",
]

logger = logging.getLogger(__name__)

DEFAULT_PORT = 8795
APP_NAME = "Sonnia Video"

#: Lo que se espera a que cargue el avatar (la primera vez descarga de Genies).
READY_TIMEOUT_S = 15 * 60.0
#: Si el avatar no llega en este tiempo, se relanza la app una vez: a veces, en el primer
#: arranque de una app recién compilada o copiada, Genies monta las mallas pero se queda con
#: texturas sin bajar y ya no se recupera en ese proceso; el segundo arranque carga en segundos.
STALL_RESTART_S = 120.0
#: Sin respuesta durante un trabajo, se da por caída la app.
SILENT_TIMEOUT_S = 60.0
POLL_S = 0.5


class Cancelled(VideoError):
    """Se canceló el trabajo (Ctrl+C o desde la app)."""


class AvatarTimeout(VideoError):
    """El avatar de Genies no cargó a tiempo."""


def port() -> int:
    """El puerto del renderizador (``SONNIA_VIDEO_PORT`` o 8795)."""
    raw = os.environ.get("SONNIA_VIDEO_PORT", "").strip()
    try:
        return int(raw) if raw else DEFAULT_PORT
    except ValueError:
        raise VideoError(f"SONNIA_VIDEO_PORT={raw!r} no es un puerto") from None


def _candidates() -> list[Path]:
    out: list[Path] = []
    explicit = os.environ.get("SONNIA_VIDEO_APP", "").strip()
    if explicit:
        return [Path(explicit).expanduser()]
    if frozen():
        exe = Path(sys.executable).resolve()
        for parent in list(exe.parents)[:5]:
            if parent.suffix == ".app":
                out.append(parent)
                break
            sibling = parent / f"{APP_NAME}.exe"
            if sibling.is_file():
                out.append(sibling)
                break
    build = REPO_ROOT / "unity" / "Build"
    out += [build / "macOS-video" / f"{APP_NAME}.app", build / "Windows-video" / f"{APP_NAME}.exe"]
    out += [
        Path("/Applications") / f"{APP_NAME}.app",
        Path.home() / "Applications" / f"{APP_NAME}.app",
    ]
    return out


def find_app() -> Path:
    """La app del renderizador, o un error que dice dónde se buscó."""
    candidates = _candidates()
    for candidate in candidates:
        if candidate.exists():
            return candidate
    looked = "\n".join(f"  {c}" for c in candidates)
    raise VideoError(
        f"No encuentro «{APP_NAME}». Busqué en:\n{looked}\n"
        f"Pon SONNIA_VIDEO_APP con la ruta de la app (o de su ejecutable)."
    )


def app_executable(app: Path) -> Path:
    """El ejecutable de la app (``.app/Contents/MacOS/<único archivo>``) o la propia ruta."""
    if app.is_file():
        return app
    if app.suffix == ".app":
        folder = app / "Contents" / "MacOS"
        files = sorted(p for p in folder.iterdir() if p.is_file()) if folder.is_dir() else []
        if files:
            return files[0]
        raise VideoError(f"{app} no tiene ejecutable en Contents/MacOS")
    exes = sorted(app.glob("*.exe")) if app.is_dir() else []
    if exes:
        return exes[0]
    raise VideoError(f"{app} no es una app que se pueda lanzar")


def idle_minutes() -> int | None:
    """``SONNIA_VIDEO_IDLE_MIN``: minutos sin peticiones hasta que la app se cierra sola
    (``None``: los de la app, 45)."""
    raw = os.environ.get("SONNIA_VIDEO_IDLE_MIN", "").strip()
    if not raw:
        return None
    try:
        return max(1, int(raw))
    except ValueError:
        raise VideoError(f"SONNIA_VIDEO_IDLE_MIN={raw!r} no es un número de minutos") from None


def launch_args(
    exe: Path,
    listen_port: int,
    log_file: Path,
    *,
    outfit: str = "staff",
    idle_min: int | None = None,
) -> list[str]:
    """La orden de arranque: siempre ``-batchmode`` (sin ventana ni icono en el Dock).

    La camiseta se pone al cargar el avatar, así que va aquí y no en el trabajo:
    ``-sin-camiseta-staff`` para la lisa.
    """
    args = [str(exe), "-batchmode", "-sonnia-video", "-sonnia-video-port", str(listen_port)]
    if idle_min is not None:
        args += ["-sonnia-video-idle-min", str(idle_min)]
    if outfit == "plain":
        args.append("-sin-camiseta-staff")
    return [*args, "-logFile", str(log_file)]


def launch(
    app: Path, listen_port: int, log_file: Path, *, outfit: str = "staff"
) -> subprocess.Popen[bytes]:
    """Lanza el renderizador en un proceso aparte que sigue vivo al acabar ``sonnia-video``."""
    exe = app_executable(app)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    args = launch_args(exe, listen_port, log_file, outfit=outfit, idle_min=idle_minutes())
    options: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        options["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    try:
        return subprocess.Popen(args, **options)
    except OSError as exc:
        raise VideoError(f"No se pudo abrir {exe}: {exc}") from None


class RendererClient:
    """HTTP con el renderizador (síncrono: es una conversación lenta y sencilla)."""

    def __init__(
        self,
        listen_port: int | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout_s: float = 5.0,
    ) -> None:
        self.port = port() if listen_port is None else listen_port
        self._client = httpx.Client(
            base_url=f"http://127.0.0.1:{self.port}",
            transport=transport,
            timeout=httpx.Timeout(timeout_s, connect=2.0),
            trust_env=False,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> RendererClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def status(self) -> dict[str, Any] | None:
        """El estado de la app, o ``None`` si no contesta (cerrada o arrancando)."""
        try:
            response = self._client.get("/status")
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        try:
            data = response.json()
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    def catalog(self) -> dict[str, Any]:
        """El catálogo de gestos (el mensaje ``gesture_catalog``)."""
        try:
            response = self._client.get("/catalog", timeout=30.0)
        except httpx.HTTPError as exc:
            raise VideoError(f"El renderizador no dio el catálogo de gestos: {exc}") from None
        if response.status_code == 503:
            raise VideoError("El renderizador aún no tiene el avatar cargado.")
        if response.status_code != 200:
            raise VideoError(
                f"El renderizador devolvió {response.status_code} al pedir los gestos."
            )
        data = response.json()
        if not isinstance(data, dict):
            raise VideoError("El catálogo de gestos no es un objeto JSON.")
        return data

    def submit(self, job: dict[str, Any]) -> str:
        """Manda un trabajo. Devuelve su id."""
        try:
            response = self._client.post("/job", json=job, timeout=30.0)
        except httpx.HTTPError as exc:
            raise VideoError(f"No se pudo mandar el trabajo al renderizador: {exc}") from None
        if response.status_code == 409:
            raise VideoError(
                "El renderizador está ocupado con otro trabajo. Espera a que acabe "
                "(sonnia-video estado) o ciérralo con sonnia-video cerrar."
            )
        if response.status_code >= 400:
            raise VideoError(
                f"El renderizador rechazó el trabajo ({response.status_code}): "
                f"{response.text[:400]}"
            )
        try:
            data = response.json()
        except ValueError:
            data = {}
        return str(data.get("id") or job.get("id") or "") if isinstance(data, dict) else ""

    def cancel(self) -> None:
        with contextlib.suppress(httpx.HTTPError):
            self._client.post("/cancel")

    def quit(self) -> bool:
        """Cierra la app. ``False`` si no contestaba."""
        try:
            self._client.post("/quit")
        except httpx.HTTPError:
            return False
        return True


class Progress:
    """Una sola línea de progreso que se reescribe (en una terminal) o líneas sueltas cada poco."""

    def __init__(self, stream: TextIO | None = None, *, every_s: float = 5.0) -> None:
        self._stream = stream if stream is not None else sys.stderr
        self._tty = bool(getattr(self._stream, "isatty", lambda: False)())
        self._every_s = every_s
        self._last = ""
        self._last_at = float("-inf")
        self._width = 0

    def update(self, text: str) -> None:
        if self._tty:
            pad = max(0, self._width - len(text))
            self._stream.write("\r" + text + " " * pad)
            self._stream.flush()
            self._width = len(text)
        else:
            now = time.monotonic()
            if text != self._last and now - self._last_at >= self._every_s:
                self._stream.write(text + "\n")
                self._stream.flush()
                self._last_at = now
        self._last = text

    def job(self, current: dict[str, Any]) -> None:
        """El estado del trabajo en curso (``job`` de ``/status``)."""
        self.update(_job_line(current))

    def done(self, text: str = "") -> None:
        if self._tty and self._width:
            self._stream.write("\r" + " " * self._width + "\r")
        self._width = 0
        if text:
            self._stream.write(text + "\n")
        self._stream.flush()


def _clock(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60}:{seconds % 60:02d}"


def quit_and_wait(
    client: RendererClient,
    *,
    timeout_s: float = 30.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Cierra la app y espera a que deje de contestar."""
    client.quit()
    started = clock()
    while client.status() is not None:
        if clock() - started > timeout_s:
            raise VideoError("El renderizador no se cerró: ciérralo con sonnia-video cerrar.")
        sleep(0.5)


#: La última app lanzada en cada puerto: mientras arranca aún no contesta, y no hay que
#: lanzar otra.
_LAUNCHED: dict[int, subprocess.Popen[bytes]] = {}


def ensure_started(
    client: RendererClient,
    log_file: Path,
    *,
    app: Path | None = None,
    outfit: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> subprocess.Popen[bytes] | None:
    """Lanza la app si no contesta. Devuelve el proceso que está arrancando (``None`` si ya
    contestaba).

    Si la que está abierta lleva otra camiseta que ``outfit`` (``staff`` o ``plain``; ``None``
    vale cualquiera), la cierra y la vuelve a abrir con la pedida: la camiseta se pone al
    cargar el avatar.
    """
    status = client.status()
    if status is not None:
        current = status.get("outfit")
        if outfit is None or current is None or current == outfit:
            return None
        if status.get("busy"):
            raise VideoError(
                "El renderizador abierto lleva otra camiseta y está ocupado con otro trabajo: "
                "espera a que acabe (sonnia-video estado)."
            )
        logger.info(
            "El renderizador lleva otra camiseta (%s): lo abro de nuevo con %s", current, outfit
        )
        quit_and_wait(client, sleep=sleep)
    else:
        starting = _LAUNCHED.get(client.port)
        if starting is not None and starting.poll() is None:
            return starting
    process = launch(app or find_app(), client.port, log_file, outfit=outfit or "staff")
    _LAUNCHED[client.port] = process
    return process


def wait_ready(
    client: RendererClient,
    *,
    process: subprocess.Popen[bytes] | None = None,
    log_file: Path | None = None,
    progress: Progress | None = None,
    timeout_s: float = READY_TIMEOUT_S,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Espera a que el avatar esté cargado (``ready``). Devuelve el estado.

    En modo vídeo no hay doble de respaldo: si Genies no entrega el avatar, sigue en
    ``loading`` hasta el tope y se cuenta el error.
    """
    started = clock()
    where = f" Registro: {log_file}" if log_file else ""
    while True:
        status = client.status()
        elapsed = clock() - started
        if status is not None and status.get("avatar") == "ready":
            if progress is not None:
                progress.done()
            return status
        if process is not None and process.poll() is not None and status is None:
            if progress is not None:
                progress.done()
            raise VideoError(f"El renderizador se cerró al arrancar.{where}")
        if elapsed > timeout_s:
            if progress is not None:
                progress.done()
            raise AvatarTimeout(
                f"El avatar de Genies no cargó en {_clock(timeout_s)} (¿hay red?). Ciérralo con "
                f"sonnia-video cerrar y vuelve a intentarlo.{where}"
            )
        if progress is not None:
            what = "Abriendo Sonnia Video" if status is None else "Cargando el avatar de Sonnia"
            progress.update(
                f"{what}… {_clock(elapsed)} (la primera vez puede tardar varios minutos)"
            )
        sleep(1.0)


def _job_line(job: dict[str, Any]) -> str:
    state = job.get("state")
    if state == "preparing":
        return "Preparando la escena…"
    if state == "encoding":
        return "Terminando el vídeo…"
    frame = int(job.get("frame") or 0)
    frames = int(job.get("frames") or 0)
    fps = float(job.get("render_fps") or 0.0)
    line = f"Renderizando cuadro {frame}/{frames}" if frames else "Renderizando"
    if fps > 0:
        line += f" · {fps:.1f} cuadros/s".replace(".", ",")
        if frames:
            line += f" · quedan {_clock((frames - frame) / fps)}"
    return line


def run_job(
    client: RendererClient,
    job: dict[str, Any],
    *,
    progress: Progress | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    log_file: Path | None = None,
) -> dict[str, Any]:
    """Manda el trabajo y espera a que acabe, con el progreso en una línea.

    Ctrl+C cancela el trabajo en la app (``/cancel``) y lanza :class:`Cancelled`.
    """
    job_id = client.submit(job) or str(job.get("id"))
    where = f" Registro: {log_file}" if log_file else ""
    silent_since: float | None = None
    try:
        while True:
            status = client.status()
            now = clock()
            if status is None:
                silent_since = now if silent_since is None else silent_since
                if now - silent_since > SILENT_TIMEOUT_S:
                    raise VideoError(f"El renderizador dejó de contestar (¿se cerró?).{where}")
                sleep(POLL_S)
                continue
            silent_since = None
            current = status.get("job")
            if isinstance(current, dict) and str(current.get("id")) == job_id:
                state = current.get("state")
                if state == "done":
                    if progress is not None:
                        progress.done()
                    return current
                if state == "error":
                    raise VideoError(
                        f"El renderizador falló: {current.get('error') or 'sin detalle'}.{where}"
                    )
                if state == "cancelled":
                    raise Cancelled("Trabajo cancelado en el renderizador.")
                if progress is not None:
                    progress.job(current)
            sleep(POLL_S)
    except KeyboardInterrupt:
        client.cancel()
        raise Cancelled("Cancelado: se le pidió al renderizador que pare.") from None
    finally:
        if progress is not None:
            progress.done()
