"""Camera sources.

One-off snapshots only, never video: each `capture()` returns a `Frame` already
downscaled and JPEG-encoded, ready to attach for the model.

`cv2` is imported lazily inside the functions so that
`import sonia.vision.camera` works without the `camera` extra installed.
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

if TYPE_CHECKING:
    from sonia.config import VisionSettings

logger = logging.getLogger(__name__)

#: How long `UnityCamera` waits for a new frame, in seconds.
DEFAULT_UNITY_TIMEOUT = 0.5

#: Maximum age of the last Unity frame. With Unity closed or its camera
#: stopped, an old photo is worse than none: Sonnia would greet people who
#: already left.
DEFAULT_UNITY_MAX_AGE = 10.0

#: Stale frames dropped from the driver buffer before reading the good one.
_STALE_FRAMES = 2

#: After a failure to open the camera, no retry until this much time has passed.
#: Retrying on every turn would pay the open timeout again and again; never
#: retrying would leave Sonnia blind for the rest of the day.
OPEN_RETRY_COOLDOWN_S = 30.0

#: Consecutive failed reads before reopening the device. A single read can
#: fail because of a dropped frame; two in a row means the camera.
MAX_READ_FAILURES = 2

#: Maximum wait for a read. Drivers (V4L2, AVFoundation) hang inside
#: ``read()`` when the device is lost, and the thread cannot be cancelled:
#: that ``VideoCapture`` is abandoned and a new one is opened.
READ_TIMEOUT_S = 2.0


#: How long startup waits for someone to accept the macOS camera permission prompt.
PERMISSION_WAIT_S = 120.0

#: What to do if macOS does not allow using the camera (``tccutil`` makes it undecided again).
MAC_CAMERA_DENIED = (
    "macOS does not let this process use the camera: Sonnia will not be able to look. Enable "
    "it in System Settings > Privacy & Security > Camera for the app that launches Sonnia (the "
    "terminal or the avatar app) and start it again, or run 'tccutil reset Camera' so that "
    "macOS asks again."
)

#: AVFoundation's ``AVAuthorizationStatus``.
_MAC_CAMERA_STATUS = {0: "undetermined", 1: "restricted", 2: "denied", 3: "authorized"}


def mac_camera_access() -> str | None:
    """Camera permission of this process on macOS, without requesting it or opening anything.

    ``authorized``, ``denied``, ``restricted`` or ``undetermined`` (not asked
    yet). ``None`` outside macOS or if it cannot be determined.
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
    except Exception:  # noqa: BLE001 - it is only a hint
        logger.debug("Could not check the camera permission", exc_info=True)
        return None


def encode_frame(bgr: Any, max_width: int, quality: int) -> Frame | None:
    """Resizes an OpenCV BGR array and encodes it as JPEG.

    Pure function with no camera: it can be tested with a numpy array.
    Returns ``None`` if encoding fails or the array is empty.
    """
    import cv2

    if bgr is None or getattr(bgr, "size", 0) == 0:
        return None

    height, width = int(bgr.shape[0]), int(bgr.shape[1])
    if max_width > 0 and width > max_width:
        # Keep the aspect ratio; at least one pixel tall.
        new_height = max(1, round(height * max_width / width))
        bgr = cv2.resize(bgr, (max_width, new_height), interpolation=cv2.INTER_AREA)
        height, width = new_height, max_width

    quality = max(1, min(100, int(quality)))
    ok, buffer = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        logger.warning("Could not encode the frame as JPEG")
        return None

    return Frame(
        data=bytes(buffer.tobytes()),
        mime="image/jpeg",
        width=width,
        height=height,
        captured_at=time.monotonic(),
    )


def _small_buffer(cv2: Any, device: Any) -> None:
    """Minimal buffer: we want the current frame, not the one from half a second ago."""
    try:
        device.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:  # noqa: BLE001 - not every backend supports it
        logger.debug("The backend does not support CAP_PROP_BUFFERSIZE")


def _release_quietly(device: Any) -> None:
    """Releases a ``VideoCapture`` without propagating anything (already on the error path)."""
    try:
        device.release()
    except Exception:  # noqa: BLE001 - closing must never break the app
        logger.debug("Error releasing the camera", exc_info=True)


class NullCamera:
    """Camera that sees nothing. Used with ``VISION_SOURCE=none``."""

    async def capture(self) -> Frame | None:
        return None

    async def close(self) -> None:
        return None


class OpenCVCamera:
    """USB camera read with OpenCV, opened lazily and reopenable.

    Over a full day of running, the USB camera gets re-enumerated, the system
    grabs it or the cable moves. That is why no failure is final: a failed open
    is retried after :data:`OPEN_RETRY_COOLDOWN_S`, and consecutive failed reads
    (or a hung read) drop the ``VideoCapture`` so the next capture opens another.
    """

    def __init__(self, settings: VisionSettings) -> None:
        self._settings = settings
        self._capture: Any | None = None
        #: ``time.monotonic()`` before which no new open is attempted.
        self._retry_after = 0.0
        self._read_failures = 0
        #: Hung reads whose thread is still alive. Kept so the garbage collector
        #: does not release their ``VideoCapture`` while it is being read.
        self._abandoned: set[asyncio.Task[Any]] = set()
        #: The requested resolution gave no image: it is not requested again on reopens.
        self._keep_resolution = False
        # Serializes access: the VideoCapture object is not thread-safe.
        self._lock = asyncio.Lock()
        self._closed = False

    # -- opening -----------------------------------------------------------

    def _open_sync(self) -> Any | None:
        """Opens the device. Runs in a separate thread because it blocks."""
        import cv2

        index = self._settings.camera_index
        backends: list[int] = []
        # On macOS, AVFoundation avoids warnings and long open times.
        if sys.platform == "darwin" and hasattr(cv2, "CAP_AVFOUNDATION"):
            backends.append(int(cv2.CAP_AVFOUNDATION))
        backends.append(int(getattr(cv2, "CAP_ANY", 0)))

        # The configured one and, if it does not open (it does not exist on this
        # machine), the default one.
        for candidate in dict.fromkeys((index, 0)):
            for backend in backends:
                device = self._open_device(cv2, candidate, backend)
                if device is not None:
                    if candidate != index:
                        logger.warning("Could not open camera %s: using the default one (0)", index)
                    return device

        logger.warning("Could not open the camera with index %s", index)
        return None

    def _open_device(self, cv2: Any, index: int, backend: int) -> Any | None:
        """An open ``VideoCapture`` with a minimal buffer and, if possible, the requested size."""
        device = cv2.VideoCapture(index, backend)
        if not device.isOpened():
            device.release()
            return None
        _small_buffer(cv2, device)
        if self._raise_resolution(cv2, device):
            return device
        # The requested resolution gave no image: reopen it as it came.
        device.release()
        self._keep_resolution = True
        device = cv2.VideoCapture(index, backend)
        if not device.isOpened():
            device.release()
            return None
        _small_buffer(cv2, device)
        return device

    def _raise_resolution(self, cv2: Any, device: Any) -> bool:
        """Asks for ``VISION_CAPTURE_WIDTH`` x ``VISION_CAPTURE_HEIGHT`` if the camera opens below.

        Many webcams open at 640x480 on Windows even though they do 1080p, and a higher
        resolution helps the vision model see people further away. The Mac camera already
        opens at 1920x1080 and is left alone. Returns ``False`` if the new resolution gives
        no image (it has to be reopened as it came); ``True`` if it cannot be queried or changed.
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
                # MJPG: over USB 2, raw 1080p (YUY2) drops to about 5 frames per second.
                device.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            device.set(cv2.CAP_PROP_FRAME_WIDTH, want_w)
            device.set(cv2.CAP_PROP_FRAME_HEIGHT, want_h)
            ok, frame = device.read()
        except Exception:  # noqa: BLE001 - an odd backend: keep what it had
            logger.debug("Could not change the camera resolution", exc_info=True)
            return True
        if not ok or frame is None:
            logger.warning(
                "The camera gives no image at %dx%d: staying at %dx%d",
                want_w,
                want_h,
                width,
                height,
            )
            return False
        got_h, got_w = int(frame.shape[0]), int(frame.shape[1])
        logger.info("Camera at %dx%d (opened at %dx%d)", got_w, got_h, width, height)
        return True

    async def set_index(self, index: int) -> None:
        """Switches camera: releases the open one and the next capture opens ``index``."""
        async with self._lock:
            self._settings.camera_index = max(0, int(index))
            device, self._capture = self._capture, None
            self._retry_after = 0.0
            self._read_failures = 0
        if device is not None:
            await asyncio.to_thread(_release_quietly, device)
        logger.info("Camera switched to %d", self._settings.camera_index)

    async def warm_up(
        self,
        *,
        wait_s: float = PERMISSION_WAIT_S,
        access: Callable[[], str | None] = mac_camera_access,
        poll_s: float = 1.0,
    ) -> bool:
        """Opens the camera at startup so permission is asked now, not with someone in front of it.

        On macOS, the first time a process opens the camera the system shows its
        permission prompt and that open fails: Sonnia would say "I couldn't take
        the snapshot" in the middle of a conversation. Here it is opened at
        startup, we wait for someone to accept the prompt (up to ``wait_s``) and
        it is opened again, so the first photo Sonnia asks for already works. The
        test frame is discarded. Returns whether the camera gives an image.
        """
        status = await asyncio.to_thread(access)
        if status in ("denied", "restricted"):
            logger.warning(MAC_CAMERA_DENIED)
            return False
        frame = await self.capture()
        if frame is None and status == "undetermined":
            logger.warning(
                "macOS is asking for permission to use the camera: accept the system prompt "
                "(waiting up to %.0f s)",
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
                logger.info("Camera permission granted")
                async with self._lock:
                    self._retry_after = 0.0
                frame = await self.capture()
        if frame is None:
            logger.warning(
                "Camera %s gives no image at startup: Sonnia will not be able to look until "
                "it is fixed (retrying on its own every %.0f s)",
                self._settings.camera_index,
                OPEN_RETRY_COOLDOWN_S,
            )
            return False
        logger.info(
            "Camera ready (index %s, %dx%d)",
            self._settings.camera_index,
            frame.width,
            frame.height,
        )
        return True

    async def _ensure_open(self) -> Any | None:
        if self._capture is not None:
            return self._capture
        if time.monotonic() < self._retry_after:
            # No retry on every turn: the conversation cannot pay the timeout.
            return None
        self._capture = await asyncio.to_thread(self._open_sync)
        if self._capture is None:
            self._retry_after = time.monotonic() + OPEN_RETRY_COOLDOWN_S
        else:
            self._read_failures = 0
        return self._capture

    # -- capture -----------------------------------------------------------

    def _read_sync(self, device: Any, max_width: int, quality: int) -> Frame | None:
        """Drops the stale frames from the buffer, reads the current one and encodes it.

        Resizing and JPEG encoding run in the same thread as the read: they are
        milliseconds of CPU that must not land on the audio loop.
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
        """A fresh snapshot. ``max_width`` and ``quality`` only apply to this one."""
        width = self._settings.max_width if max_width is None else max_width
        jpeg_quality = self._settings.jpeg_quality if quality is None else quality
        async with self._lock:
            return await self._capture_locked(width, jpeg_quality)

    async def _capture_locked(self, width: int, jpeg_quality: int) -> Frame | None:
        """Reads from the device. Called with ``self._lock`` held."""
        device = await self._ensure_open()
        if device is None:
            return None
        task = asyncio.create_task(asyncio.to_thread(self._read_sync, device, width, jpeg_quality))
        try:
            frame = await asyncio.wait_for(asyncio.shield(task), timeout=READ_TIMEOUT_S)
        except TimeoutError:
            logger.warning(
                "The camera hung while reading (%.1f s); abandoning the device",
                READ_TIMEOUT_S,
            )
            self._abandon(device, task)
            return None
        except asyncio.CancelledError:
            # The turn was cancelled: the thread is still inside read(), so
            # that VideoCapture can no longer be touched from another thread.
            self._abandon(device, task)
            raise
        except Exception:  # noqa: BLE001 - keep going even if the camera fails
            logger.exception("Failed to read from the camera")
            await self._release(device)
            return None
        if frame is None:
            await self._note_read_failure(device)
            return None
        self._read_failures = 0
        return frame

    async def _note_read_failure(self, device: Any) -> None:
        """Counts a read with no frame and reopens the device if it keeps happening."""
        self._read_failures += 1
        if self._read_failures < MAX_READ_FAILURES:
            logger.warning("The camera returned no frame")
            return
        logger.warning(
            "The camera returns no frames (%d in a row); the device will be reopened",
            self._read_failures,
        )
        await self._release(device)

    def _abandon(self, device: Any, task: asyncio.Task[Any]) -> None:
        """Drops a device whose read is still alive in a thread."""
        if self._capture is device:
            self._capture = None
        self._read_failures = 0
        self._retry_after = 0.0
        self._abandoned.add(task)

        def _cleanup(done: asyncio.Task[Any]) -> None:
            self._abandoned.discard(done)
            with contextlib.suppress(RuntimeError):
                # Releasing can block: never on the event loop.
                asyncio.get_running_loop().run_in_executor(None, _release_quietly, device)

        task.add_done_callback(_cleanup)

    async def _release(self, device: Any) -> None:
        """Closes the device so the next capture opens another one."""
        if self._capture is device:
            self._capture = None
        self._read_failures = 0
        self._retry_after = 0.0
        with contextlib.suppress(Exception):
            await asyncio.to_thread(device.release)

    async def close(self) -> None:
        async with self._lock:
            self._closed = True
            device, self._capture = self._capture, None
            if device is not None:
                await asyncio.to_thread(device.release)


class UnityCamera:
    """Camera served by Unity: frames arrive over the WebSocket.

    `capture()` asks for a new frame with ``request_frame`` and waits up to
    ``timeout`` seconds. If it does not arrive in time, it returns the last one
    it has (a photo from a second ago is better than none) as long as it is not
    older than ``max_age``: with Unity down, still showing the model a photo from
    half an hour ago is worse than showing it nothing.

    ``has_clients`` (the hub) avoids paying the timeout when nobody is connected
    to answer.
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
        """Stores a ``camera_frame`` received from Unity. Never raises."""
        try:
            data = base64.b64decode(data_base64, validate=True)
        except (binascii.Error, ValueError):
            logger.warning("camera_frame with invalid base64; dropped")
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
        """Last frame received, or ``None`` if it is already too old."""
        frame = self._last
        if frame is None:
            return None
        if self._max_age > 0 and time.monotonic() - frame.captured_at > self._max_age:
            logger.debug("The last Unity frame is older than %.0f s; dropped", self._max_age)
            self._last = None
            return None
        return frame

    async def capture(self) -> Frame | None:
        self._event.clear()
        if self._request_frame is not None and (self._has_clients is None or self._has_clients()):
            try:
                await self._request_frame()
            except Exception:  # noqa: BLE001 - Unity may be disconnected
                logger.exception("Could not request a frame from Unity")
                return self._fresh()
            try:
                await asyncio.wait_for(self._event.wait(), timeout=self._timeout)
            except TimeoutError:
                logger.debug("Unity did not send a frame within %.0f ms", self._timeout * 1000)
        return self._fresh()

    async def close(self) -> None:
        return None


def build_camera(
    settings: VisionSettings,
    request_frame: Callable[[], Awaitable[None]] | None = None,
    *,
    has_clients: Callable[[], bool] | None = None,
) -> CameraSource:
    """Picks the camera source from ``VISION_SOURCE``."""
    match settings.source:
        case "opencv":
            return OpenCVCamera(settings)
        case "unity":
            return UnityCamera(request_frame, has_clients=has_clients)
        case _:
            return NullCamera()
