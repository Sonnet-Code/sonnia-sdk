"""Tests for the vision layer: frame encoding, cameras and policy.

No real camera is opened: `encode_frame` is tested with a numpy array,
`UnityCamera` with a fake `request_frame`.
"""

from __future__ import annotations

import asyncio
import base64
import sys
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from sonia.config import VisionSettings
from sonia.types import Frame
from sonia.vision import camera as camera_module
from sonia.vision.camera import (
    NullCamera,
    OpenCVCamera,
    UnityCamera,
    build_camera,
    encode_frame,
)
from sonia.vision.policy import VisionPolicy

# ---------------------------------------------------------------------------
# encode_frame
# ---------------------------------------------------------------------------


def make_bgr(width: int, height: int) -> np.ndarray:
    """BGR array with random noise, so the JPEG is not trivial."""
    rng = np.random.default_rng(seed=7)
    return rng.integers(0, 255, size=(height, width, 3), dtype=np.uint8)


def test_encode_frame_resizes_keeping_aspect_ratio() -> None:
    frame = encode_frame(make_bgr(1920, 1080), max_width=768, quality=80)
    assert frame is not None
    assert frame.width == 768
    assert frame.height == 432  # 1080 * 768 / 1920
    assert frame.mime == "image/jpeg"
    assert frame.data[:2] == b"\xff\xd8"  # JPEG header
    assert frame.captured_at > 0


def test_encode_frame_does_not_upscale_small_images() -> None:
    frame = encode_frame(make_bgr(320, 240), max_width=768, quality=80)
    assert frame is not None
    assert (frame.width, frame.height) == (320, 240)


def test_encode_frame_quality_changes_the_size() -> None:
    bgr = make_bgr(640, 480)
    high = encode_frame(bgr, max_width=640, quality=95)
    low = encode_frame(bgr, max_width=640, quality=20)
    assert high is not None and low is not None
    assert len(low.data) < len(high.data)


def test_encode_frame_can_be_decoded() -> None:
    import cv2

    frame = encode_frame(make_bgr(800, 600), max_width=400, quality=90)
    assert frame is not None
    decoded = cv2.imdecode(np.frombuffer(frame.data, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded is not None
    assert decoded.shape == (300, 400, 3)


def test_encode_frame_with_empty_array() -> None:
    assert encode_frame(np.zeros((0, 0, 3), dtype=np.uint8), 768, 80) is None
    assert encode_frame(None, 768, 80) is None


# ---------------------------------------------------------------------------
# NullCamera and build_camera
# ---------------------------------------------------------------------------


async def test_null_camera() -> None:
    assert await NullCamera().capture() is None


def test_build_camera_by_source() -> None:
    assert isinstance(build_camera(VisionSettings(source="none")), NullCamera)
    assert isinstance(build_camera(VisionSettings(source="opencv")), OpenCVCamera)
    assert isinstance(build_camera(VisionSettings(source="unity")), UnityCamera)


# ---------------------------------------------------------------------------
# OpenCVCamera: recovery without restarting the process
# ---------------------------------------------------------------------------


class _FakeDevice:
    """Fake `VideoCapture`: no cv2 or real camera needed."""

    def __init__(self, *, ok: bool = True, block: threading.Event | None = None) -> None:
        self.ok = ok
        self.block = block
        self.reads = 0
        self.released = False

    def grab(self) -> bool:
        return self.ok

    def read(self) -> tuple[bool, Any]:
        self.reads += 1
        if self.block is not None:
            self.block.wait(timeout=5.0)
        if not self.ok:
            return False, None
        return True, make_bgr(32, 24)

    def release(self) -> None:
        self.released = True


def _with_devices(
    monkeypatch: pytest.MonkeyPatch, camera: OpenCVCamera, devices: list[Any]
) -> list[Any]:
    """Makes each open return the next item of ``devices``."""
    opened: list[Any] = []
    pending = list(devices)

    def open_sync() -> Any:
        device = pending.pop(0) if pending else None
        opened.append(device)
        return device

    monkeypatch.setattr(camera, "_open_sync", open_sync)
    return opened


async def test_opencv_camera_retries_opening_after_the_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed open must not leave Sonnia blind for the rest of the day."""
    monkeypatch.setattr(camera_module, "OPEN_RETRY_COOLDOWN_S", 0.05)
    camera = OpenCVCamera(VisionSettings(source="opencv"))
    good = _FakeDevice()
    opened = _with_devices(monkeypatch, camera, [None, good])

    assert await camera.capture() is None
    # Within the cooldown the open timeout is not paid again.
    assert await camera.capture() is None
    assert len(opened) == 1

    await asyncio.sleep(0.06)
    frame = await camera.capture()
    assert frame is not None
    assert len(opened) == 2


async def test_opencv_camera_reopens_when_it_stops_giving_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Camera disconnected mid-session: the dead device is released."""
    dead = _FakeDevice(ok=False)
    alive = _FakeDevice()
    camera = OpenCVCamera(VisionSettings(source="opencv"))
    opened = _with_devices(monkeypatch, camera, [dead, alive])

    for _ in range(camera_module.MAX_READ_FAILURES):
        assert await camera.capture() is None
    assert dead.released is True
    assert len(opened) == 1

    frame = await camera.capture()
    assert frame is not None
    assert len(opened) == 2


async def test_opencv_camera_abandons_a_hung_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The driver hangs inside read(): the turn cannot get stuck there."""
    monkeypatch.setattr(camera_module, "READ_TIMEOUT_S", 0.05)
    unblock = threading.Event()
    hung = _FakeDevice(block=unblock)
    alive = _FakeDevice()
    camera = OpenCVCamera(VisionSettings(source="opencv"))
    opened = _with_devices(monkeypatch, camera, [hung, alive])

    start = time.monotonic()
    assert await camera.capture() is None
    assert time.monotonic() - start < 1.0

    # The next capture does not reuse the device that is still reading.
    frame = await camera.capture()
    assert frame is not None
    assert len(opened) == 2

    unblock.set()
    await asyncio.sleep(0.05)


async def test_warm_up_waits_for_the_macos_permission_and_leaves_the_camera_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The permission prompt shows up at startup, not with someone in front of the camera."""
    camera = OpenCVCamera(VisionSettings(source="opencv"))
    # Without permission yet, macOS does not let it open; once the prompt is accepted, it does.
    opened = _with_devices(monkeypatch, camera, [None, _FakeDevice()])
    states = iter(["undetermined", "undetermined", "undetermined", "authorized"])

    assert await camera.warm_up(access=lambda: next(states), poll_s=0.01)
    # The failed open does not leave Sonnia waiting for the cooldown: it already gives an image.
    assert len(opened) == 2
    assert await camera.capture() is not None


def test_macos_camera_permission_is_queried_without_requesting_it() -> None:
    # Only queries (shows no prompt); outside macOS it is unknown.
    states = (None, "authorized", "denied", "restricted", "undetermined")
    assert camera_module.mac_camera_access() in states


async def test_warm_up_with_permission_denied_says_so_without_opening_anything(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    camera = OpenCVCamera(VisionSettings(source="opencv"))
    opened = _with_devices(monkeypatch, camera, [_FakeDevice()])
    assert not await camera.warm_up(access=lambda: "denied")
    assert opened == []
    assert "Privacy & Security > Camera" in caplog.text


async def test_warm_up_outside_macos_only_opens_the_camera(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    camera = OpenCVCamera(VisionSettings(source="opencv"))
    _with_devices(monkeypatch, camera, [_FakeDevice()])
    assert await camera.warm_up(access=lambda: None)
    camera = OpenCVCamera(VisionSettings(source="opencv"))
    _with_devices(monkeypatch, camera, [None])
    assert not await camera.warm_up(access=lambda: None, wait_s=0)
    assert "gives no image at startup" in caplog.text


# ---------------------------------------------------------------------------
# UnityCamera
# ---------------------------------------------------------------------------


async def test_unity_camera_receives_the_requested_frame() -> None:
    payload = base64.b64encode(b"jpeg-from-unity").decode("ascii")
    cameras: list[UnityCamera] = []

    async def request_frame() -> None:
        # Unity answers with a `camera_frame` shortly after the request.
        loop = asyncio.get_running_loop()
        loop.call_later(0.01, cameras[0].on_frame, "image/jpeg", payload)

    camera = UnityCamera(request_frame, timeout=1.0)
    cameras.append(camera)
    frame = await camera.capture()
    assert frame is not None
    assert frame.data == b"jpeg-from-unity"
    assert frame.mime == "image/jpeg"


async def test_unity_camera_timeout_without_a_previous_frame() -> None:
    calls = 0

    async def request_frame() -> None:
        nonlocal calls
        calls += 1

    camera = UnityCamera(request_frame, timeout=0.05)
    start = time.monotonic()
    assert await camera.capture() is None
    assert calls == 1
    assert time.monotonic() - start >= 0.04


async def test_unity_camera_timeout_returns_the_last_frame() -> None:
    async def request_frame() -> None:
        return None  # Unity never answers

    camera = UnityCamera(request_frame, timeout=0.05)
    camera.on_frame("image/png", base64.b64encode(b"old").decode("ascii"))
    frame = await camera.capture()
    assert frame is not None
    assert frame.data == b"old"
    assert frame.mime == "image/png"


async def test_unity_camera_drops_the_last_frame_when_too_old() -> None:
    """Unity down: a photo from a while ago is worse than none."""

    async def request_frame() -> None:
        return None

    camera = UnityCamera(request_frame, timeout=0.01, max_age=0.05)
    camera.on_frame("image/jpeg", base64.b64encode(b"old").decode("ascii"))
    assert await camera.capture() is not None

    await asyncio.sleep(0.08)
    assert await camera.capture() is None
    assert camera.last_frame is None


async def test_unity_camera_without_clients_does_not_pay_the_timeout() -> None:
    requests = 0

    async def request_frame() -> None:
        nonlocal requests
        requests += 1

    camera = UnityCamera(request_frame, timeout=5.0, has_clients=lambda: False)
    start = time.monotonic()
    assert await camera.capture() is None
    assert requests == 0
    assert time.monotonic() - start < 0.5


async def test_unity_camera_ignores_invalid_base64() -> None:
    camera = UnityCamera(timeout=0.01)
    camera.on_frame("image/jpeg", "this-is-not-base64!!")
    assert camera.last_frame is None


async def test_unity_camera_without_request_frame_returns_the_last_one() -> None:
    camera = UnityCamera(None, timeout=0.01)
    assert await camera.capture() is None
    camera.on_frame("image/jpeg", base64.b64encode(b"x").decode("ascii"))
    frame = await camera.capture()
    assert frame is not None and frame.data == b"x"


async def test_unity_camera_does_not_raise_if_request_frame_fails() -> None:
    async def request_frame() -> None:
        raise RuntimeError("Unity disconnected")

    camera = UnityCamera(request_frame, timeout=0.01)
    assert await camera.capture() is None


# ---------------------------------------------------------------------------
# VisionPolicy
# ---------------------------------------------------------------------------


def test_policy_without_vision_support_disables_everything(tmp_path: Path) -> None:
    settings = VisionSettings(
        on_turn_start=True,
        interval_seconds=1.0,
        debug_save_frames=True,
        debug_dir=str(tmp_path),
    )
    policy = VisionPolicy(settings, supports_vision=False)
    assert policy.enabled is False
    assert policy.should_capture_on_turn_start() is False
    assert policy.should_capture_periodic(now=1000.0) is False
    assert policy.maybe_save_debug(Frame(data=b"x")) is None


def test_policy_on_turn_start() -> None:
    enabled = VisionPolicy(VisionSettings(on_turn_start=True), supports_vision=True)
    assert enabled.should_capture_on_turn_start() is True

    disabled = VisionPolicy(VisionSettings(on_turn_start=False), supports_vision=True)
    assert disabled.should_capture_on_turn_start() is False


def test_policy_source_none_disables() -> None:
    policy = VisionPolicy(VisionSettings(source="none", on_turn_start=True), supports_vision=True)
    assert policy.should_capture_on_turn_start() is False


def test_policy_periodic_disabled_by_default() -> None:
    policy = VisionPolicy(VisionSettings(interval_seconds=0.0), supports_vision=True)
    assert policy.should_capture_periodic(now=100.0) is False


def test_policy_periodic_with_simulated_times() -> None:
    policy = VisionPolicy(VisionSettings(interval_seconds=10.0), supports_vision=True)
    # With no previous capture, it is time to capture.
    assert policy.should_capture_periodic(now=100.0) is True

    policy.note_captured(now=100.0)
    assert policy.should_capture_periodic(now=105.0) is False
    assert policy.should_capture_periodic(now=109.999) is False
    assert policy.should_capture_periodic(now=110.0) is True

    policy.note_captured(now=110.0)
    assert policy.should_capture_periodic(now=115.0) is False
    assert policy.should_capture_periodic(now=121.0) is True


def test_policy_does_not_save_frames_by_default(tmp_path: Path) -> None:
    debug_dir = tmp_path / "debug"
    policy = VisionPolicy(
        VisionSettings(debug_save_frames=False, debug_dir=str(debug_dir)),
        supports_vision=True,
    )
    assert policy.maybe_save_debug(Frame(data=b"jpeg")) is None
    assert not debug_dir.exists()


def test_policy_saves_frames_in_debug_mode(tmp_path: Path) -> None:
    debug_dir = tmp_path / "debug"
    policy = VisionPolicy(
        VisionSettings(debug_save_frames=True, debug_dir=str(debug_dir)),
        supports_vision=True,
    )
    path = policy.maybe_save_debug(Frame(data=b"jpeg-bytes", mime="image/jpeg"))
    assert path is not None
    assert path.parent == debug_dir
    assert path.suffix == ".jpg"
    assert path.read_bytes() == b"jpeg-bytes"

    other = policy.maybe_save_debug(Frame(data=b"png-bytes", mime="image/png"))
    assert other is not None
    assert other.suffix == ".png"
    assert len(list(debug_dir.iterdir())) == 2


def test_policy_maybe_save_debug_without_frame(tmp_path: Path) -> None:
    policy = VisionPolicy(
        VisionSettings(debug_save_frames=True, debug_dir=str(tmp_path)),
        supports_vision=True,
    )
    assert policy.maybe_save_debug(None) is None


@pytest.mark.parametrize("supports_vision", [True, False])
def test_policy_enabled(supports_vision: bool) -> None:
    policy = VisionPolicy(VisionSettings(source="opencv"), supports_vision=supports_vision)
    assert policy.enabled is supports_vision


class _FakeCv2:
    """Fake ``cv2``: only opens the cameras in ``present``."""

    CAP_ANY = 0

    def __init__(self, present: set[int]) -> None:
        self.present = present
        self.opened: list[int] = []

    def VideoCapture(self, index: int, backend: int = 0) -> Any:  # noqa: N802 - like cv2
        cv2 = self

        class _Device(_FakeDevice):
            def isOpened(self) -> bool:  # noqa: N802 - like cv2
                return index in cv2.present

            def set(self, prop: int, value: Any) -> bool:
                return True

        if index in self.present:
            self.opened.append(index)
        return _Device()


def test_if_the_configured_camera_does_not_open_camera_0_is_used(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    fake = _FakeCv2({0})
    monkeypatch.setitem(sys.modules, "cv2", fake)
    camera = OpenCVCamera(VisionSettings(source="opencv", camera_index=3))
    assert camera._open_sync() is not None
    assert fake.opened == [0]
    assert "using the default one" in caplog.text


class _SizedCv2:
    """Fake ``cv2`` with resolution: cameras open at ``start`` and, at the requested one,
    give an image or not depending on ``works``."""

    CAP_ANY = 0
    CAP_PROP_FRAME_WIDTH = 3
    CAP_PROP_FRAME_HEIGHT = 4
    CAP_PROP_FOURCC = 6
    CAP_PROP_BUFFERSIZE = 38

    def __init__(self, start: tuple[int, int], *, works: bool = True) -> None:
        self.start = start
        self.works = works
        self.devices: list[Any] = []

    @staticmethod
    def VideoWriter_fourcc(*chars: str) -> int:  # noqa: N802 - like cv2
        return 1196444237

    def VideoCapture(self, index: int, backend: int = 0) -> Any:  # noqa: N802 - like cv2
        cv2 = self

        class _Device(_FakeDevice):
            def __init__(self) -> None:
                super().__init__()
                self.size = list(cv2.start)
                self.changed = False

            def isOpened(self) -> bool:  # noqa: N802 - like cv2
                return True

            def get(self, prop: int) -> float:
                sizes = {
                    cv2.CAP_PROP_FRAME_WIDTH: self.size[0],
                    cv2.CAP_PROP_FRAME_HEIGHT: self.size[1],
                }
                return float(sizes.get(prop, 0))

            def set(self, prop: int, value: Any) -> bool:
                if prop in (cv2.CAP_PROP_FRAME_WIDTH, cv2.CAP_PROP_FRAME_HEIGHT):
                    self.size[prop == cv2.CAP_PROP_FRAME_HEIGHT] = int(value)
                    self.changed = True
                return True

            def read(self) -> tuple[bool, Any]:
                self.reads += 1
                if self.changed and not cv2.works:
                    return False, None
                return True, make_bgr(self.size[0], self.size[1])

        device = _Device()
        self.devices.append(device)
        return device


def test_a_camera_opening_at_low_resolution_is_asked_for_more(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Windows opens many webcams at 640x480, too small to see people further away.
    fake = _SizedCv2((640, 480))
    monkeypatch.setitem(sys.modules, "cv2", fake)
    caplog.set_level("INFO", logger="sonia.vision.camera")
    device = OpenCVCamera(VisionSettings(source="opencv"))._open_sync()
    assert device is fake.devices[0] and device.size == [1920, 1080]
    assert "Camera at 1920x1080 (opened at 640x480)" in caplog.text


def test_if_the_requested_resolution_gives_no_image_it_reopens_as_it_came(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _SizedCv2((640, 480), works=False)
    monkeypatch.setitem(sys.modules, "cv2", fake)
    camera = OpenCVCamera(VisionSettings(source="opencv"))
    device = camera._open_sync()
    assert len(fake.devices) == 2 and fake.devices[0].released
    assert device is fake.devices[1] and device.size == [640, 480]
    # Reopens no longer ask for it again.
    again = camera._open_sync()
    assert again is fake.devices[2] and not again.changed


@pytest.mark.parametrize(
    ("start", "width"), [((1920, 1080), 1920), ((640, 480), 0)], ids=["already-1080p", "off"]
)
def test_resolution_is_left_alone_if_already_there_or_disabled(
    monkeypatch: pytest.MonkeyPatch, start: tuple[int, int], width: int
) -> None:
    fake = _SizedCv2(start)
    monkeypatch.setitem(sys.modules, "cv2", fake)
    device = OpenCVCamera(VisionSettings(source="opencv", capture_width=width))._open_sync()
    assert device is not None and not device.changed and device.reads == 0


async def test_camera_can_be_switched_on_the_fly(monkeypatch: pytest.MonkeyPatch) -> None:
    first, second = _FakeDevice(), _FakeDevice()
    settings = VisionSettings(source="opencv")
    camera = OpenCVCamera(settings)
    opened = _with_devices(monkeypatch, camera, [first, second])
    assert await camera.capture() is not None
    await camera.set_index(2)
    assert first.released and settings.camera_index == 2
    assert await camera.capture() is not None
    assert opened == [first, second]
