"""Fuentes de cámara.

Solo capturas puntuales, nunca vídeo: cada `capture()` devuelve un `Frame` ya
reducido y codificado en JPEG, listo para adjuntarlo al modelo.

`cv2` se importa de forma perezosa dentro de las funciones para que
`import sonia.vision.camera` funcione sin el extra `camera` instalado.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import logging
import sys
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from sonia.types import CameraSource, Frame
from sonia.vision.obs import ObsConnect, ObsError

if TYPE_CHECKING:
    from sonia.config import VisionSettings

logger = logging.getLogger(__name__)

#: Cuánto espera `UnityCamera` a que llegue un frame nuevo, en segundos.
DEFAULT_UNITY_TIMEOUT = 0.5

#: Antigüedad máxima del último frame de Unity. Con Unity cerrado o con su
#: cámara parada, una foto vieja es peor que ninguna: Sonia saludaría a gente
#: que ya se fue.
DEFAULT_UNITY_MAX_AGE = 10.0

#: Frames viejos que se descartan del buffer del driver antes de leer el bueno.
_STALE_FRAMES = 2

#: Tras un fallo al abrir la cámara no se reintenta hasta pasado este tiempo.
#: Reintentar en cada turno pagaría el timeout de apertura una y otra vez; no
#: reintentar nunca deja a Sonia ciega el resto del día.
OPEN_RETRY_COOLDOWN_S = 30.0

#: Lecturas fallidas seguidas antes de reabrir el dispositivo. Una lectura
#: suelta puede fallar por un fotograma perdido; dos seguidas es la cámara.
MAX_READ_FAILURES = 2

#: Tope de espera de una lectura. Los drivers (V4L2, AVFoundation) se cuelgan
#: dentro de ``read()`` cuando se pierde el dispositivo, y el hilo no se puede
#: cancelar: se abandona ese ``VideoCapture`` y se abre uno nuevo.
READ_TIMEOUT_S = 2.0


#: Cuánto espera el arranque a que alguien acepte el aviso de permiso de cámara de macOS.
PERMISSION_WAIT_S = 120.0

#: Qué hacer si macOS no deja usar la cámara (``tccutil`` lo deja sin decidir otra vez).
MAC_CAMERA_DENIED = (
    "macOS no deja usar la cámara a este proceso: Sonia no podrá mirar. Actívalo en Ajustes "
    "del Sistema > Privacidad y seguridad > Cámara para la app que lanza Sonia (la terminal o "
    "Sonnia) y vuelve a arrancarla, o ejecuta «tccutil reset Camera» para que lo pregunte otra vez."
)

#: ``AVAuthorizationStatus`` de AVFoundation.
_MAC_CAMERA_STATUS = {0: "undetermined", 1: "restricted", 2: "denied", 3: "authorized"}


def mac_camera_access() -> str | None:
    """Permiso de cámara de este proceso en macOS, sin pedirlo ni abrir nada.

    ``authorized``, ``denied``, ``restricted`` o ``undetermined`` (aún no se ha
    preguntado). ``None`` fuera de macOS o si no se puede saber.
    """
    if sys.platform != "darwin":
        return None
    try:
        import ctypes
        import ctypes.util

        objc_path = ctypes.util.find_library("objc")
        if not objc_path:
            return None
        objc = ctypes.CDLL(objc_path)
        avfoundation = ctypes.CDLL("/System/Library/Frameworks/AVFoundation.framework/AVFoundation")
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        send = objc.objc_msgSend
        send.restype = ctypes.c_long
        send.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        device_class = objc.objc_getClass(b"AVCaptureDevice")
        video = ctypes.c_void_p.in_dll(avfoundation, "AVMediaTypeVideo").value
        if not device_class or not video:
            return None
        selector = objc.sel_registerName(b"authorizationStatusForMediaType:")
        return _MAC_CAMERA_STATUS.get(int(send(device_class, selector, video)))
    except Exception:  # noqa: BLE001 - es solo un aviso
        logger.debug("No se pudo comprobar el permiso de cámara", exc_info=True)
        return None


def encode_frame(bgr: Any, max_width: int, quality: int) -> Frame | None:
    """Redimensiona un array BGR de OpenCV y lo codifica en JPEG.

    Función pura y sin cámara: se puede probar con un array de numpy.
    Devuelve ``None`` si la codificación falla o el array está vacío.
    """
    import cv2

    if bgr is None or getattr(bgr, "size", 0) == 0:
        return None

    height, width = int(bgr.shape[0]), int(bgr.shape[1])
    if max_width > 0 and width > max_width:
        # Se mantiene la proporción; al menos un píxel de alto.
        new_height = max(1, round(height * max_width / width))
        bgr = cv2.resize(bgr, (max_width, new_height), interpolation=cv2.INTER_AREA)
        height, width = new_height, max_width

    quality = max(1, min(100, int(quality)))
    ok, buffer = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        logger.warning("No se pudo codificar el frame en JPEG")
        return None

    return Frame(
        data=bytes(buffer.tobytes()),
        mime="image/jpeg",
        width=width,
        height=height,
        captured_at=time.monotonic(),
    )


def _small_buffer(cv2: Any, device: Any) -> None:
    """Buffer mínimo: queremos el frame de ahora, no el de hace medio segundo."""
    try:
        device.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:  # noqa: BLE001 - no todos los backends lo soportan
        logger.debug("El backend no soporta CAP_PROP_BUFFERSIZE")


def _release_quietly(device: Any) -> None:
    """Libera un ``VideoCapture`` sin propagar nada (ya vamos por el mal camino)."""
    try:
        device.release()
    except Exception:  # noqa: BLE001 - cerrar nunca debe romper la demo
        logger.debug("Error liberando la cámara", exc_info=True)


class NullCamera:
    """Cámara que no ve nada. Se usa con ``VISION_SOURCE=none``."""

    async def capture(self) -> Frame | None:
        return None

    async def close(self) -> None:
        return None


class OpenCVCamera:
    """Cámara USB leída con OpenCV, abierta de forma perezosa y reabrible.

    En un stand de ocho horas la cámara USB se re-enumera, el sistema la
    ocupa o el cable se mueve. Por eso ningún fallo es definitivo: una apertura
    fallida se reintenta pasado :data:`OPEN_RETRY_COOLDOWN_S`, y unas lecturas
    fallidas seguidas (o una lectura colgada) sueltan el ``VideoCapture`` para
    abrir otro en la captura siguiente.
    """

    def __init__(self, settings: VisionSettings) -> None:
        self._settings = settings
        self._capture: Any | None = None
        #: ``time.monotonic()`` antes del cual no se vuelve a intentar abrir.
        self._retry_after = 0.0
        self._read_failures = 0
        #: Lecturas colgadas cuyo hilo sigue vivo. Se guardan para que su
        #: ``VideoCapture`` no lo libere el recolector mientras se está leyendo.
        self._abandoned: set[asyncio.Task[Any]] = set()
        #: Con la resolución pedida no dio imagen: no se vuelve a pedir en las reaperturas.
        self._keep_resolution = False
        # Serializa los accesos: el objeto VideoCapture no es seguro entre hilos.
        self._lock = asyncio.Lock()

    # -- apertura ----------------------------------------------------------

    def _open_sync(self) -> Any | None:
        """Abre el dispositivo. Corre en un hilo aparte porque bloquea."""
        import cv2

        index = self._settings.camera_index
        backends: list[int] = []
        # En macOS AVFoundation evita los avisos y los tiempos de apertura largos.
        if sys.platform == "darwin" and hasattr(cv2, "CAP_AVFOUNDATION"):
            backends.append(int(cv2.CAP_AVFOUNDATION))
        backends.append(int(getattr(cv2, "CAP_ANY", 0)))

        # La configurada y, si no abre (en este equipo no existe), la de por defecto.
        for candidate in dict.fromkeys((index, 0)):
            for backend in backends:
                device = self._open_device(cv2, candidate, backend)
                if device is not None:
                    if candidate != index:
                        logger.warning(
                            "No se pudo abrir la cámara %s: se usa la de por defecto (0)", index
                        )
                    return device

        logger.warning("No se pudo abrir la cámara con índice %s", index)
        return None

    def _open_device(self, cv2: Any, index: int, backend: int) -> Any | None:
        """Un ``VideoCapture`` abierto, con buffer mínimo y la resolución pedida si se puede."""
        device = cv2.VideoCapture(index, backend)
        if not device.isOpened():
            device.release()
            return None
        _small_buffer(cv2, device)
        if self._raise_resolution(cv2, device):
            return device
        # Con la resolución pedida no dio imagen: se abre otra vez tal como venía.
        device.release()
        self._keep_resolution = True
        device = cv2.VideoCapture(index, backend)
        if not device.isOpened():
            device.release()
            return None
        _small_buffer(cv2, device)
        return device

    def _raise_resolution(self, cv2: Any, device: Any) -> bool:
        """Pide ``VISION_CAPTURE_WIDTH`` x ``VISION_CAPTURE_HEIGHT`` si la cámara abre por debajo.

        Muchas webcams abren a 640x480 en Windows aunque den 1080p, y a esa resolución
        una cara a dos metros se queda en unos 35 px (docs/caras.md). La del Mac ya abre a
        1920x1080 y no se toca. Devuelve ``False`` si con la nueva resolución no da imagen
        (hay que reabrirla como venía); si no se puede preguntar o cambiar, ``True``.
        """
        want_w = self._settings.capture_width
        want_h = self._settings.capture_height
        if want_w <= 0 or want_h <= 0 or self._keep_resolution:
            return True
        try:
            width = int(device.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            height = int(device.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            if width <= 0 or width >= want_w:
                return True
            if sys.platform != "darwin":
                # MJPG: por USB 2, 1080p en crudo (YUY2) se queda en unos 5 fotogramas por segundo.
                device.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            device.set(cv2.CAP_PROP_FRAME_WIDTH, want_w)
            device.set(cv2.CAP_PROP_FRAME_HEIGHT, want_h)
            ok, frame = device.read()
        except Exception:  # noqa: BLE001 - un backend raro: se queda con la que tenía
            logger.debug("No se pudo cambiar la resolución de la cámara", exc_info=True)
            return True
        if not ok or frame is None:
            logger.warning(
                "La cámara no da imagen a %dx%d: se queda a %dx%d", want_w, want_h, width, height
            )
            return False
        got_h, got_w = int(frame.shape[0]), int(frame.shape[1])
        logger.info("Cámara a %dx%d (abría a %dx%d)", got_w, got_h, width, height)
        return True

    async def set_index(self, index: int) -> None:
        """Cambia de cámara: suelta la abierta y la siguiente captura abre ``index``."""
        async with self._lock:
            self._settings.camera_index = max(0, int(index))
            device, self._capture = self._capture, None
            self._retry_after = 0.0
            self._read_failures = 0
        if device is not None:
            await asyncio.to_thread(_release_quietly, device)
        logger.info("Cámara cambiada a la %d", self._settings.camera_index)

    async def warm_up(
        self,
        *,
        wait_s: float = PERMISSION_WAIT_S,
        access: Callable[[], str | None] = mac_camera_access,
        poll_s: float = 1.0,
    ) -> bool:
        """Abre la cámara al arrancar para que el permiso se pida ya y no con un visitante delante.

        En macOS, la primera vez que un proceso abre la cámara el sistema enseña
        su aviso de permiso y esa apertura falla: Sonia decía «no pude tomar la
        captura» en mitad de la conversación (7 de octubre de 2026). Aquí se abre
        al arrancar, se espera a que alguien acepte el aviso (hasta ``wait_s``) y
        se vuelve a abrir, así la primera foto que pida Sonia ya sale. El frame
        de prueba se tira. Devuelve si la cámara da imagen.
        """
        status = await asyncio.to_thread(access)
        if status in ("denied", "restricted"):
            logger.warning(MAC_CAMERA_DENIED)
            return False
        frame = await self.capture()
        if frame is None and status == "undetermined":
            logger.warning(
                "macOS pide permiso para usar la cámara: acepta el aviso del sistema "
                "(se espera hasta %.0f s)",
                wait_s,
            )
            deadline = time.monotonic() + wait_s
            while status == "undetermined" and time.monotonic() < deadline:
                await asyncio.sleep(poll_s)
                status = await asyncio.to_thread(access)
            if status in ("denied", "restricted"):
                logger.warning(MAC_CAMERA_DENIED)
                return False
            if status == "authorized":
                logger.info("Permiso de cámara concedido")
                async with self._lock:
                    self._retry_after = 0.0
                frame = await self.capture()
        if frame is None:
            logger.warning(
                "La cámara %s no da imagen al arrancar: Sonia no podrá mirar hasta que se "
                "arregle (se reintenta sola cada %.0f s)",
                self._settings.camera_index,
                OPEN_RETRY_COOLDOWN_S,
            )
            return False
        logger.info(
            "Cámara lista (índice %s, %dx%d)",
            self._settings.camera_index,
            frame.width,
            frame.height,
        )
        return True

    async def _ensure_open(self) -> Any | None:
        if self._capture is not None:
            return self._capture
        if time.monotonic() < self._retry_after:
            # No reintentamos en cada turno: la demo no puede pagar el timeout.
            return None
        self._capture = await asyncio.to_thread(self._open_sync)
        if self._capture is None:
            self._retry_after = time.monotonic() + OPEN_RETRY_COOLDOWN_S
        else:
            self._read_failures = 0
        return self._capture

    # -- captura -----------------------------------------------------------

    def _read_sync(self, device: Any, max_width: int, quality: int) -> Frame | None:
        """Descarta los frames viejos del buffer, lee el actual y lo codifica.

        El redimensionado y el JPEG van en el mismo hilo que la lectura: son
        milisegundos de CPU que no deben caer sobre el bucle de audio.
        """
        for _ in range(_STALE_FRAMES):
            device.grab()
        ok, bgr = device.read()
        if not ok:
            return None
        return encode_frame(bgr, max_width, quality)

    async def capture(
        self, *, max_width: int | None = None, quality: int | None = None
    ) -> Frame | None:
        """Una captura reciente. ``max_width`` y ``quality`` cambian solo esta
        (el Modo Jean los ajusta a lo que aguanta la red)."""
        width = self._settings.max_width if max_width is None else max_width
        jpeg_quality = self._settings.jpeg_quality if quality is None else quality
        async with self._lock:
            device = await self._ensure_open()
            if device is None:
                return None
            task = asyncio.create_task(
                asyncio.to_thread(self._read_sync, device, width, jpeg_quality)
            )
            try:
                frame = await asyncio.wait_for(asyncio.shield(task), timeout=READ_TIMEOUT_S)
            except TimeoutError:
                logger.warning(
                    "La cámara se quedó colgada leyendo (%.1f s); se abandona el dispositivo",
                    READ_TIMEOUT_S,
                )
                self._abandon(device, task)
                return None
            except asyncio.CancelledError:
                # El turno se canceló: el hilo sigue dentro de read(), así que
                # ese VideoCapture ya no se puede volver a tocar desde otro hilo.
                self._abandon(device, task)
                raise
            except Exception:  # noqa: BLE001 - la demo sigue aunque la cámara falle
                logger.exception("Fallo leyendo de la cámara")
                await self._release(device)
                return None
            if frame is None:
                await self._note_read_failure(device)
                return None
            self._read_failures = 0
            return frame

    async def _note_read_failure(self, device: Any) -> None:
        """Cuenta una lectura sin frame y reabre el dispositivo si insiste."""
        self._read_failures += 1
        if self._read_failures < MAX_READ_FAILURES:
            logger.warning("La cámara no devolvió ningún frame")
            return
        logger.warning(
            "La cámara no devuelve frames (%d seguidos); se reabrirá el dispositivo",
            self._read_failures,
        )
        await self._release(device)

    def _abandon(self, device: Any, task: asyncio.Task[Any]) -> None:
        """Suelta un dispositivo cuya lectura sigue viva en un hilo."""
        if self._capture is device:
            self._capture = None
        self._read_failures = 0
        self._retry_after = 0.0
        self._abandoned.add(task)

        def _cleanup(done: asyncio.Task[Any]) -> None:
            self._abandoned.discard(done)
            with contextlib.suppress(RuntimeError):
                # Liberar puede bloquear: nunca en el bucle de eventos.
                asyncio.get_running_loop().run_in_executor(None, _release_quietly, device)

        task.add_done_callback(_cleanup)

    async def _release(self, device: Any) -> None:
        """Cierra el dispositivo para que la captura siguiente abra otro."""
        if self._capture is device:
            self._capture = None
        self._read_failures = 0
        self._retry_after = 0.0
        with contextlib.suppress(Exception):
            await asyncio.to_thread(device.release)

    async def close(self) -> None:
        async with self._lock:
            device, self._capture = self._capture, None
            if device is not None:
                await asyncio.to_thread(device.release)


class UnityCamera:
    """Cámara servida por Unity: los frames llegan por WebSocket.

    `capture()` pide un frame nuevo con ``request_frame`` y espera hasta
    ``timeout`` segundos. Si no llega a tiempo, devuelve el último que tenga
    (mejor una foto de hace un segundo que ninguna) siempre que no pase de
    ``max_age``: con Unity caído, seguir enseñándole al modelo la foto de hace
    media hora es peor que no enseñarle nada.

    ``has_clients`` (el hub) evita pagar el timeout cuando no hay nadie
    conectado que pueda responder.
    """

    def __init__(
        self,
        request_frame: Callable[[], Awaitable[None]] | None = None,
        *,
        timeout: float = DEFAULT_UNITY_TIMEOUT,
        max_age: float = DEFAULT_UNITY_MAX_AGE,
        has_clients: Callable[[], bool] | None = None,
    ) -> None:
        self._request_frame = request_frame
        self._timeout = timeout
        self._max_age = max_age
        self._has_clients = has_clients
        self._last: Frame | None = None
        self._event = asyncio.Event()

    @property
    def last_frame(self) -> Frame | None:
        return self._last

    def on_frame(self, mime: str, data_base64: str) -> None:
        """Registra un ``camera_frame`` recibido de Unity. No lanza nunca."""
        try:
            data = base64.b64decode(data_base64, validate=True)
        except (binascii.Error, ValueError):
            logger.warning("camera_frame con base64 inválido; se descarta")
            return
        if not data:
            return
        if mime not in ("image/jpeg", "image/png"):
            mime = "image/jpeg"
        self._last = Frame(
            data=data,
            mime=mime,  # type: ignore[arg-type]
            captured_at=time.monotonic(),
        )
        self._event.set()

    def _fresh(self) -> Frame | None:
        """Último frame recibido, o ``None`` si ya es demasiado viejo."""
        frame = self._last
        if frame is None:
            return None
        if self._max_age > 0 and time.monotonic() - frame.captured_at > self._max_age:
            logger.debug("El último frame de Unity pasa de %.0f s; se descarta", self._max_age)
            self._last = None
            return None
        return frame

    async def capture(self) -> Frame | None:
        self._event.clear()
        if self._request_frame is not None and (self._has_clients is None or self._has_clients()):
            try:
                await self._request_frame()
            except Exception:  # noqa: BLE001 - Unity puede estar desconectado
                logger.exception("No se pudo pedir un frame a Unity")
                return self._fresh()
            try:
                await asyncio.wait_for(self._event.wait(), timeout=self._timeout)
            except TimeoutError:
                logger.debug("Unity no envió un frame en %.0f ms", self._timeout * 1000)
        return self._fresh()

    async def close(self) -> None:
        return None


#: Tope de espera de una foto de OBS (conectar, identificarse y pedirla).
OBS_TIMEOUT_S = 3.0


def _decode_and_encode(data: bytes, max_width: int, quality: int) -> Frame | None:
    """JPEG o PNG de OBS → ``Frame`` reducido como los de la cámara."""
    import cv2
    import numpy as np

    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    return encode_frame(image, max_width, quality)


class ObsCamera:
    """Una fuente de OBS como cámara (``VISION_SOURCE=obs``): el modo reunión.

    En una videollamada (``docs/reunion.md``) OBS ya captura la ventana de Unity
    para la cámara virtual con la que la reunión ve a Sonia. Con otra fuente que
    capture la ventana de la reunión (``VISION_OBS_SOURCE``), Sonia ve la
    reunión: cada vez que mira se pide a OBS una foto de esa fuente por
    obs-websocket (``GetSourceScreenshot``). Nunca vídeo y nada a disco. Una
    conexión por foto: son pocas y así no hay nada que reabrir si OBS se reinicia.
    """

    def __init__(self, settings: VisionSettings, *, connect: ObsConnect | None = None) -> None:
        self._settings = settings
        self._connect = connect
        self._lock = asyncio.Lock()

    async def capture(
        self, *, max_width: int | None = None, quality: int | None = None
    ) -> Frame | None:
        width = self._settings.max_width if max_width is None else max_width
        jpeg_quality = self._settings.jpeg_quality if quality is None else quality
        from websockets.exceptions import ConnectionClosed

        async with self._lock:
            try:
                data = await asyncio.wait_for(self._screenshot(width), timeout=OBS_TIMEOUT_S)
            except TimeoutError:
                logger.warning("OBS no dio la foto en %.1f s", OBS_TIMEOUT_S)
                return None
            except ConnectionClosed as exc:
                # 4009: autenticación fallida (VISION_OBS_PASSWORD).
                logger.warning(
                    "OBS cerró la conexión (%s): revisa VISION_OBS_PASSWORD", exc.rcvd or exc
                )
                return None
            except OSError as exc:
                logger.warning(
                    "No se pudo hablar con OBS en %s (¿está abierto y con el servidor WebSocket "
                    "activado?): %s",
                    self._settings.obs_url,
                    exc,
                )
                return None
            except ObsError as exc:
                logger.warning("OBS no dio la foto de «%s»: %s", self._settings.obs_source, exc)
                return None
            except Exception:  # noqa: BLE001 - la demo sigue aunque OBS falle
                logger.exception("Fallo pidiendo la foto a OBS")
                return None
        return await asyncio.to_thread(_decode_and_encode, data, width, jpeg_quality)

    async def _screenshot(self, width: int) -> bytes:
        from sonia.vision.obs import obs_session

        request: dict[str, Any] = {
            "sourceName": self._settings.obs_source,
            "imageFormat": "jpg",
            "imageCompressionQuality": 90,
        }
        if width > 0:
            # OBS mantiene la proporción («scale to inner»).
            request["imageWidth"] = max(8, min(4096, width))
        async with obs_session(self._settings, self._connect) as obs:
            response = await obs.request("GetSourceScreenshot", **request)
        image = str(response.get("imageData") or "")
        try:
            return base64.b64decode(image.split(",", 1)[-1], validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ObsError("la foto no venía en base64") from exc

    async def close(self) -> None:
        return None


def _mac_screen_access() -> bool | None:
    """¿Puede este proceso grabar la pantalla en macOS? ``None`` fuera de macOS o si no se sabe.

    Si no puede, pide el permiso (macOS enseña su aviso una vez); vale al volver a
    arrancar el proceso.
    """
    if sys.platform != "darwin":
        return None
    try:
        import ctypes
        import ctypes.util

        path = ctypes.util.find_library("CoreGraphics")
        if not path:
            return None
        graphics = ctypes.CDLL(path)
        graphics.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
        if graphics.CGPreflightScreenCaptureAccess():
            return True
        graphics.CGRequestScreenCaptureAccess.restype = ctypes.c_bool
        graphics.CGRequestScreenCaptureAccess()
        return False
    except Exception:  # noqa: BLE001 - es solo un aviso
        logger.debug("No se pudo comprobar el permiso de grabación de pantalla", exc_info=True)
        return None


def _grab_monitor(monitor: int) -> Any | None:
    """Captura una pantalla con mss y la devuelve en BGR, como un frame de OpenCV."""
    import mss
    import numpy as np

    with mss.MSS() as screens:
        monitors = screens.monitors
        if not 0 <= monitor < len(monitors):
            logger.warning(
                "No hay pantalla %d (hay %d); se captura la principal", monitor, len(monitors) - 1
            )
            monitor = 1 if len(monitors) > 1 else 0
        shot = screens.grab(monitors[monitor])
    # mss da BGRA: sin el canal alfa queda como OpenCV.
    return np.ascontiguousarray(np.asarray(shot)[:, :, :3])


class ScreenCamera:
    """La pantalla del equipo como cámara (``VISION_SOURCE=screen``): el modo reunión.

    Con Sonia en una videollamada (``docs/reunion.md``), lo que «ve» es la reunión:
    una captura puntual de la pantalla ``VISION_SCREEN_MONITOR`` cada vez que mira,
    reducida y en JPEG como las de la cámara. Nunca vídeo y nada a disco. En macOS
    la app que lanza el orquestador necesita el permiso de Grabación de pantalla;
    sin él, macOS solo deja ver el fondo de escritorio.
    """

    def __init__(
        self, settings: VisionSettings, *, grab: Callable[[int], Any] | None = None
    ) -> None:
        self._settings = settings
        self._grab = grab or _grab_monitor
        # Con una captura inyectada (pruebas) no se mira el permiso del sistema.
        self._access_checked = grab is not None
        self._lock = asyncio.Lock()

    def _read_sync(self, max_width: int, quality: int) -> Frame | None:
        if not self._access_checked:
            self._access_checked = True
            if _mac_screen_access() is False:
                logger.warning(
                    "macOS no deja grabar la pantalla a este proceso: Sonia solo verá el fondo "
                    "de escritorio. Actívalo en Ajustes del Sistema > Privacidad y seguridad > "
                    "Grabación de pantalla para la app de terminal y vuelve a arrancar Sonia."
                )
        return encode_frame(self._grab(self._settings.screen_monitor), max_width, quality)

    async def capture(
        self, *, max_width: int | None = None, quality: int | None = None
    ) -> Frame | None:
        width = self._settings.max_width if max_width is None else max_width
        jpeg_quality = self._settings.jpeg_quality if quality is None else quality
        async with self._lock:
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(self._read_sync, width, jpeg_quality),
                    timeout=READ_TIMEOUT_S,
                )
            except TimeoutError:
                logger.warning("La captura de pantalla tardó más de %.1f s", READ_TIMEOUT_S)
                return None
            except Exception:  # noqa: BLE001 - la demo sigue aunque la captura falle
                logger.exception("Fallo capturando la pantalla")
                return None

    async def close(self) -> None:
        return None


def build_camera(
    settings: VisionSettings,
    request_frame: Callable[[], Awaitable[None]] | None = None,
    *,
    has_clients: Callable[[], bool] | None = None,
) -> CameraSource:
    """Elige la fuente de cámara según ``VISION_SOURCE``."""
    match settings.source:
        case "opencv":
            return OpenCVCamera(settings)
        case "unity":
            return UnityCamera(request_frame, has_clients=has_clients)
        case "obs":
            return ObsCamera(settings)
        case "screen":
            return ScreenCamera(settings)
        case _:
            return NullCamera()
