"""La cámara en vivo de los juegos: lectura continua y vista en vivo en Unity.

``docs/plan-juegos.md``, sección 6. Dos piezas:

- :class:`OpenCVCameraStream` (``CameraStream``): mientras algún juego la pida, un hilo
  lee la cámara USB sin parar y guarda solo el último frame, en memoria. El dispositivo
  es el mismo ``OpenCVCamera`` de ``look``, las caras y la presencia, que se lo presta
  (``lend_device``): mientras dura, sus capturas salen de aquí y nunca hay dos lecturas
  a la vez. Si la cámara se cuelga o se desconecta, se abandona ese dispositivo y se
  abre otro, como hace ``OpenCVCamera``.
- :class:`LivePreview` (``PreviewStreamer``): unos 10 frames por segundo, en espejo, a
  640x360 y en JPEG de calidad 60, con lo que dibuje el juego encima, en frames binarios
  ``SNCV`` hacia Unity. Solo si la Unity conectada sabe pintarla (``camera_preview`` en
  ``client_hello.features``). Nada se guarda en disco.

Todo el trabajo de CPU (leer, reducir, dibujar, codificar) va en hilos: el bucle de
``asyncio`` lleva el micrófono a GPT-Live a tiempo real.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import numpy as np

from sonia.vision.camera import READ_TIMEOUT_S, encode_frame
from sonia.vision.contracts import CameraStream, Overlay
from sonia.ws.protocol import encode_preview_frame, msg_camera_preview

if TYPE_CHECKING:
    from sonia.types import Frame
    from sonia.vision.camera import OpenCVCamera

__all__ = [
    "PREVIEW_FPS",
    "PREVIEW_HEIGHT",
    "PREVIEW_QUALITY",
    "PREVIEW_WIDTH",
    "STREAM_FPS",
    "LivePreview",
    "OpenCVCameraStream",
    "render_preview",
]

logger = logging.getLogger(__name__)

#: Frames por segundo que se decodifican como mucho. La vista en vivo va a 10 y las poses
#: a 8: con 15 el frame más nuevo nunca tiene más de 70 ms, y los demás que manda la
#: cámara (unos 30) se descartan sin decodificar (``grab`` sin ``retrieve``).
STREAM_FPS = 15.0

#: Tope de vueltas del hilo lector: algún backend no espera al frame siguiente en ``grab()``.
_MIN_GRAB_INTERVAL_S = 1.0 / 60.0

#: Sin frames nuevos en este tiempo, el driver se ha colgado: se abandona el dispositivo.
STALL_S = 3.0

#: ``grab()`` fallidos seguidos antes de soltar el dispositivo y abrir otro.
MAX_GRAB_FAILURES = 5

#: Espera al primer frame al encender la lectura.
FIRST_FRAME_TIMEOUT_S = 3.0

#: Sin dispositivo (no abre), cada cuánto se vuelve a intentar.
RETRY_S = 2.0

#: Cada cuánto mira el vigilante si el hilo sigue dando frames.
_WATCH_S = 0.5

#: Espera al hilo lector al apagar; si sigue dentro de ``grab()``, se le deja el dispositivo.
_JOIN_TIMEOUT_S = 1.0

#: Un frame más viejo no vale para ``capture()`` (``look``, caras, presencia).
SNAPSHOT_MAX_AGE_S = 0.5

#: Vista en vivo (``docs/protocolo.md``, frames ``SNCV``).
PREVIEW_FPS = 10.0
PREVIEW_WIDTH = 640
PREVIEW_HEIGHT = 360
PREVIEW_QUALITY = 60

#: Un frame más viejo no se manda a la vista: Unity la retira sola a los 2 s sin imagen.
PREVIEW_MAX_AGE_S = 1.0

#: Cada cuánto se repite ``camera_preview`` encendido, por si Unity se reconectó.
PREVIEW_REANNOUNCE_S = 2.0

#: Prefijos de los dueños del stream, para que la vista y las poses no se pisen.
PREVIEW_OWNER = "vista:"

#: Manda un mensaje JSON o un frame binario a Unity (``Hub.broadcast_json`` / ``broadcast_bytes``).
SendJson = Callable[[dict[str, Any]], Awaitable[None]]
SendBytes = Callable[[bytes], Awaitable[None]]


def _release_quietly(device: Any) -> None:
    try:
        device.release()
    except Exception:  # noqa: BLE001 - cerrar nunca debe romper la demo
        logger.debug("Error liberando la cámara", exc_info=True)


class _Reader:
    """Hilo que lee un dispositivo sin parar y publica el último frame.

    Hace ``grab()`` de cada frame (así el siguiente es siempre el de ahora) y solo
    decodifica (``retrieve()``) los que hacen falta para ``fps``. Si se cuelga dentro de
    ``grab()``, no se le puede parar: :meth:`abandon` le deja el dispositivo y lo suelta
    él al salir.
    """

    def __init__(
        self, device: Any, publish: Callable[[float, np.ndarray], None], fps: float
    ) -> None:
        self.device = device
        self._publish = publish
        self._interval = 1.0 / fps if fps > 0 else 0.0
        self.stop = threading.Event()
        #: Dejó de dar frames (``grab()`` fallido varias veces o una excepción).
        self.failed = False
        self.started_at = time.monotonic()
        self._handoff = threading.Lock()
        self._exited = False
        self._release_on_exit = False
        self._thread = threading.Thread(target=self._run, name="sonia-camara-juegos", daemon=True)

    def start(self) -> None:
        self.started_at = time.monotonic()
        self._thread.start()

    @property
    def alive(self) -> bool:
        return self._thread.is_alive()

    def join(self, timeout: float) -> bool:
        """Espera a que salga; ``True`` si salió. Bloquea: va en un hilo."""
        self._thread.join(timeout)
        return not self._thread.is_alive()

    def abandon(self) -> bool:
        """Le deja el dispositivo al hilo colgado, que lo suelta al salir.

        ``False`` si ya había salido: entonces lo suelta quien llama.
        """
        with self._handoff:
            self.stop.set()
            if self._exited:
                return False
            self._release_on_exit = True
            return True

    def _run(self) -> None:
        failures = 0
        next_at = 0.0
        try:
            while not self.stop.is_set():
                grabbed_at = time.monotonic()
                if not self.device.grab():
                    failures += 1
                    if failures >= MAX_GRAB_FAILURES:
                        self.failed = True
                        return
                    time.sleep(0.05)
                    continue
                failures = 0
                now = time.monotonic()
                if now >= next_at:
                    ok, frame = self.device.retrieve()
                    if ok and frame is not None and getattr(frame, "size", 0):
                        self._publish(now, frame)
                        next_at = now + self._interval
                spare = _MIN_GRAB_INTERVAL_S - (time.monotonic() - grabbed_at)
                if spare > 0:
                    time.sleep(spare)
        except Exception:  # noqa: BLE001 - un driver roto no tumba la demo
            logger.exception("Fallo leyendo la cámara de los juegos")
            self.failed = True
        finally:
            with self._handoff:
                self._exited = True
                release = self._release_on_exit
            if release:
                _release_quietly(self.device)


class OpenCVCameraStream:
    """``CameraStream`` sobre la cámara USB de ``OpenCVCamera`` (``docs/plan-juegos.md``, sección 6)."""

    def __init__(self, camera: OpenCVCamera, *, fps: float = STREAM_FPS) -> None:
        self._camera = camera
        self._fps = fps
        self._owners: set[str] = set()
        self._lock = asyncio.Lock()
        self._frame_lock = threading.Lock()
        self._latest: tuple[float, np.ndarray] | None = None
        self._reader: _Reader | None = None
        self._watchdog: asyncio.Task[None] | None = None
        self._retry_at = 0.0
        #: Frames decodificados desde que se creó (para medir).
        self.frames = 0

    # -- CameraStream ----------------------------------------------------------

    @property
    def active(self) -> bool:
        return bool(self._owners)

    @property
    def owners(self) -> frozenset[str]:
        """Quién la está pidiendo ahora."""
        return frozenset(self._owners)

    async def acquire(self, owner: str) -> bool:
        async with self._lock:
            if owner not in self._owners:
                if not self._owners:
                    self._retry_at = 0.0
                    if not await self._open_reader():
                        logger.warning("Los juegos no pueden leer la cámara: no abre")
                        return False
                    self._watchdog = asyncio.create_task(self._watch(), name="sonia-camara-vigia")
                self._owners.add(owner)
        if await self._wait_frame(FIRST_FRAME_TIMEOUT_S, SNAPSHOT_MAX_AGE_S) is None:
            logger.warning("La cámara no da imagen a los juegos (%s)", owner)
            await self.release(owner)
            return False
        return True

    async def release(self, owner: str) -> None:
        async with self._lock:
            if owner not in self._owners:
                return
            self._owners.discard(owner)
            if self._owners:
                return
            watchdog, self._watchdog = self._watchdog, None
            if watchdog is not None:
                # No se espera: puede estar esperando este mismo candado.
                watchdog.cancel()
            await self._close_reader()
            with self._frame_lock:
                self._latest = None

    def latest(self) -> tuple[float, np.ndarray] | None:
        if not self._owners:
            return None
        with self._frame_lock:
            return self._latest

    # -- LiveFeed (las capturas de OpenCVCamera mientras lee el juego) ---------

    async def snapshot(self, max_width: int, quality: int) -> Frame | None:
        latest = await self._wait_frame(READ_TIMEOUT_S, SNAPSHOT_MAX_AGE_S)
        if latest is None:
            return None
        return await asyncio.to_thread(encode_frame, latest[1], max_width, quality)

    # -- interno -----------------------------------------------------------------

    def _publish(self, at: float, frame: np.ndarray) -> None:
        with self._frame_lock:
            self._latest = (at, frame)
            self.frames += 1

    async def _wait_frame(
        self, timeout_s: float, max_age_s: float
    ) -> tuple[float, np.ndarray] | None:
        """El último frame si no pasa de ``max_age_s``; si no lo hay, espera hasta ``timeout_s``."""
        deadline = time.monotonic() + timeout_s
        while True:
            latest = self.latest()
            now = time.monotonic()
            if latest is not None and now - latest[0] <= max_age_s:
                return latest
            if not self._owners or now >= deadline:
                return None
            await asyncio.sleep(0.02)

    async def _open_reader(self) -> bool:
        """Pide el dispositivo a la cámara y arranca el hilo lector. Con ``self._lock``."""
        device = await self._camera.lend_device(self)
        if device is None:
            return False
        reader = _Reader(device, self._publish, self._fps)
        reader.start()
        self._reader = reader
        return True

    async def _close_reader(self) -> None:
        """Para el hilo y devuelve el dispositivo a la cámara. Con ``self._lock``."""
        reader, self._reader = self._reader, None
        if reader is None:
            return
        reader.stop.set()
        finished = await asyncio.to_thread(reader.join, _JOIN_TIMEOUT_S)
        if finished and not reader.failed:
            await self._camera.end_loan(reader.device)
            return
        await self._drop(reader, finished=finished)

    async def _drop(self, reader: _Reader, *, finished: bool) -> None:
        """Suelta un dispositivo roto o colgado y se lo dice a la cámara. Con ``self._lock``."""
        if finished or not reader.abandon():
            await asyncio.to_thread(_release_quietly, reader.device)
        await self._camera.end_loan(None)

    async def _watch(self) -> None:
        """Reabre la cámara si el hilo deja de dar frames o si no abría."""
        while True:
            await asyncio.sleep(_WATCH_S)
            async with self._lock:
                if not self._owners:
                    return
                reader = self._reader
                now = time.monotonic()
                if reader is None:
                    if now >= self._retry_at and not await self._open_reader():
                        self._retry_at = now + RETRY_S
                    continue
                latest = self.latest()
                last = max(reader.started_at, latest[0] if latest is not None else 0.0)
                if reader.failed or not reader.alive or now - last > STALL_S:
                    logger.warning(
                        "La cámara de los juegos dejó de dar imagen (%.1f s); se abre otra vez",
                        now - last,
                    )
                    self._reader = None
                    await self._drop(reader, finished=not reader.alive)
                    self._retry_at = 0.0


# ---------------------------------------------------------------------------
# Vista en vivo
# ---------------------------------------------------------------------------


def render_preview(
    frame: np.ndarray,
    *,
    mirror: bool = True,
    overlay: Overlay | None = None,
    width: int = PREVIEW_WIDTH,
    height: int = PREVIEW_HEIGHT,
    quality: int = PREVIEW_QUALITY,
) -> tuple[bytes, int, int] | None:
    """Un frame de la vista en vivo: reducido, en espejo, con el dibujo encima y en JPEG.

    Si la cámara no es 16:9, la imagen va centrada con bandas negras: el dibujo se hace
    antes, sobre la imagen sin bandas, así que sus coordenadas (0 a 1) siguen valiendo.
    Nunca toca ``frame`` (lo comparten los demás). Devuelve ``(jpeg, ancho, alto)``.
    Bloquea unos milisegundos: va en un hilo.
    """
    import cv2

    src_h, src_w = int(frame.shape[0]), int(frame.shape[1])
    if src_w <= 0 or src_h <= 0:
        return None
    scale = min(width / src_w, height / src_h)
    size = (max(1, round(src_w * scale)), max(1, round(src_h * scale)))
    image = cv2.resize(frame, size, interpolation=cv2.INTER_AREA)
    if mirror:
        image = cv2.flip(image, 1)
    if np.shares_memory(image, frame):
        image = image.copy()
    if overlay is not None:
        try:
            overlay(image, mirror)
        except Exception:  # noqa: BLE001 - un dibujo roto no apaga la vista
            logger.debug("Fallo dibujando encima de la vista en vivo", exc_info=True)
    if size != (width, height):
        canvas = np.zeros((height, width, 3), dtype=np.uint8)
        left, top = (width - size[0]) // 2, (height - size[1]) // 2
        canvas[top : top + size[1], left : left + size[0]] = image
        image = canvas
    ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        return None
    return bytes(buffer.tobytes()), width, height


class LivePreview:
    """``PreviewStreamer``: la vista en vivo de la cámara encima de Sonnia (frames ``SNCV``)."""

    def __init__(
        self,
        stream: CameraStream,
        send_json: SendJson,
        send_bytes: SendBytes,
        supported: Callable[[], bool],
        *,
        fps: float = PREVIEW_FPS,
        width: int = PREVIEW_WIDTH,
        height: int = PREVIEW_HEIGHT,
        quality: int = PREVIEW_QUALITY,
    ) -> None:
        self._stream = stream
        self._send_json = send_json
        self._send_bytes = send_bytes
        self._supported = supported
        self._fps = fps
        self._size = (width, height)
        self._quality = quality
        self._owners: set[str] = set()
        self._mirror = True
        self._overlay: Overlay | None = None
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._seq = 0
        #: Frames mandados y milisegundos de preparar el último (para medir).
        self.frames_sent = 0
        self.render_ms = 0.0

    @property
    def active(self) -> bool:
        return bool(self._owners)

    async def start(
        self, owner: str, *, mirror: bool = True, overlay: Overlay | None = None
    ) -> bool:
        if not self._supported():
            return False
        async with self._lock:
            if owner not in self._owners:
                if not await self._stream.acquire(PREVIEW_OWNER + owner):
                    return False
                self._owners.add(owner)
            self._mirror = mirror
            self._overlay = overlay
            if self._task is None:
                await self._announce(True)
                self._task = asyncio.create_task(self._run(), name="sonia-vista-en-vivo")
        return True

    def set_overlay(self, overlay: Overlay | None) -> None:
        self._overlay = overlay

    async def stop(self, owner: str) -> None:
        async with self._lock:
            if owner not in self._owners:
                return
            self._owners.discard(owner)
            task = None
            if not self._owners:
                task, self._task = self._task, None
                self._overlay = None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            if self._supported():
                await self._announce(False)
        await self._stream.release(PREVIEW_OWNER + owner)

    async def close(self) -> None:
        """Apaga la vista de todos (al apagar el motor)."""
        for owner in list(self._owners):
            await self.stop(owner)

    async def _announce(self, on: bool) -> None:
        try:
            await self._send_json(msg_camera_preview(on, mirror=self._mirror))
        except Exception:  # noqa: BLE001 - Unity puede estar desconectada
            logger.debug("No se pudo mandar camera_preview", exc_info=True)

    async def _run(self) -> None:
        period = 1.0 / self._fps if self._fps > 0 else 0.1
        last_at: float | None = None
        was_supported = True
        next_announce = time.monotonic() + PREVIEW_REANNOUNCE_S
        failures = 0
        while True:
            started = time.monotonic()
            try:
                supported = self._supported()
                if supported and (not was_supported or started >= next_announce):
                    # Por si Unity se reconectó: la vista vuelve sola.
                    await self._announce(True)
                    next_announce = started + PREVIEW_REANNOUNCE_S
                was_supported = supported
                latest = self._stream.latest() if supported else None
                if (
                    latest is not None
                    and latest[0] != last_at
                    and started - latest[0] <= PREVIEW_MAX_AGE_S
                ):
                    last_at = latest[0]
                    await self._send_frame(latest[1])
                failures = 0
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - la vista no tumba el juego
                failures += 1
                if failures == 1:
                    logger.exception("Fallo mandando la vista en vivo")
            await asyncio.sleep(max(0.0, period - (time.monotonic() - started)))

    async def _send_frame(self, frame: np.ndarray) -> None:
        mirror, overlay = self._mirror, self._overlay
        width, height = self._size
        started = time.perf_counter()
        rendered = await asyncio.to_thread(
            render_preview,
            frame,
            mirror=mirror,
            overlay=overlay,
            width=width,
            height=height,
            quality=self._quality,
        )
        self.render_ms = (time.perf_counter() - started) * 1000
        if rendered is None:
            return
        jpeg, out_w, out_h = rendered
        self._seq += 1
        await self._send_bytes(encode_preview_frame(self._seq, out_w, out_h, jpeg, mirrored=mirror))
        self.frames_sent += 1
