"""La cámara en vivo de los juegos: lectura continua, préstamo del dispositivo y vista en vivo.

Sin cámara de verdad: un ``VideoCapture`` falso que da frames sintéticos (``grab`` y
``retrieve``), se cuelga o deja de dar imagen cuando se le pide. La vista en vivo se prueba
con un stream falso y un ``send`` falso.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from typing import Any

import cv2
import numpy as np
import pytest

from sonia.config import VisionSettings
from sonia.vision import stream as stream_module
from sonia.vision.camera import OpenCVCamera
from sonia.vision.stream import LivePreview, OpenCVCameraStream, render_preview
from sonia.ws.protocol import decode_preview_frame


class FakeVideo:
    """``VideoCapture`` falso con ``grab``/``retrieve``/``read``, a unos ``fps`` frames por segundo."""

    def __init__(
        self,
        *,
        fps: float = 200.0,
        size: tuple[int, int] = (64, 48),
        hang_after: int | None = None,
        fail_after: int | None = None,
    ) -> None:
        self.fps = fps
        self.size = size
        self.hang_after = hang_after
        self.fail_after = fail_after
        self.unhang = threading.Event()
        self.count = 0
        self.reads = 0
        self.retrieves = 0
        self.released = False

    def grab(self) -> bool:
        if self.released:
            return False
        if self.hang_after is not None and self.count >= self.hang_after:
            self.unhang.wait(timeout=5.0)
            return False
        if self.fail_after is not None and self.count >= self.fail_after:
            return False
        time.sleep(1.0 / self.fps)
        self.count += 1
        return True

    def retrieve(self) -> tuple[bool, Any]:
        self.retrieves += 1
        width, height = self.size
        return True, np.full((height, width, 3), self.count % 256, dtype=np.uint8)

    def read(self) -> tuple[bool, Any]:
        self.reads += 1
        if not self.grab():
            return False, None
        return self.retrieve()

    def release(self) -> None:
        self.released = True


def with_devices(
    monkeypatch: pytest.MonkeyPatch, camera: OpenCVCamera, devices: list[Any]
) -> list[Any]:
    """Cada apertura de ``camera`` devuelve el siguiente de ``devices`` (y luego ``None``)."""
    opened: list[Any] = []
    pending = list(devices)

    def open_sync() -> Any:
        device = pending.pop(0) if pending else None
        opened.append(device)
        return device

    monkeypatch.setattr(camera, "_open_sync", open_sync)
    return opened


async def wait_for(condition: Callable[[], bool], limit_s: float = 3.0) -> None:
    deadline = time.monotonic() + limit_s
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("no se cumplió a tiempo")
        await asyncio.sleep(0.01)


def make_camera() -> OpenCVCamera:
    return OpenCVCamera(VisionSettings(source="opencv"))


# ---------------------------------------------------------------------------
# OpenCVCameraStream
# ---------------------------------------------------------------------------


async def test_el_stream_lee_sin_parar_y_las_capturas_salen_de_el(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    camera = make_camera()
    device = FakeVideo()
    opened = with_devices(monkeypatch, camera, [device])
    stream = OpenCVCameraStream(camera, fps=50)

    assert await stream.acquire("juego")
    assert stream.active
    latest = stream.latest()
    assert latest is not None
    assert latest[1].shape == (48, 64, 3)
    assert time.monotonic() - latest[0] < 0.5

    # look, las caras y la presencia no leen el dispositivo mientras lo tiene el juego.
    reads = device.reads
    frame = await camera.capture(max_width=32, quality=70)
    assert frame is not None
    assert (frame.width, frame.height) == (32, 24)
    assert device.reads == reads

    await stream.release("juego")
    assert not stream.active
    assert stream.latest() is None
    # El dispositivo vuelve abierto a la cámara: la captura siguiente no lo reabre.
    assert not device.released
    assert await camera.capture() is not None
    assert device.reads == reads + 1
    assert len(opened) == 1


async def test_el_stream_solo_decodifica_los_frames_que_hacen_falta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    camera = make_camera()
    device = FakeVideo(fps=200)
    with_devices(monkeypatch, camera, [device])
    stream = OpenCVCameraStream(camera, fps=10)
    assert await stream.acquire("juego")
    await asyncio.sleep(0.5)
    await stream.release("juego")
    # Unos 30 grab (tope de 60 por segundo) y solo unos 5 retrieve (10 por segundo).
    assert device.count > device.retrieves * 2
    assert device.retrieves <= 8


async def test_varios_duenos_comparten_el_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    camera = make_camera()
    device = FakeVideo()
    opened = with_devices(monkeypatch, camera, [device])
    stream = OpenCVCameraStream(camera, fps=50)

    assert await stream.acquire("vista")
    assert await stream.acquire("poses")
    assert stream.owners == {"vista", "poses"}
    await stream.release("vista")
    assert stream.active and stream.latest() is not None
    await stream.release("poses")
    assert not stream.active
    await stream.release("poses")  # soltar dos veces no rompe nada
    assert len(opened) == 1


async def test_sin_camara_el_stream_dice_que_no(monkeypatch: pytest.MonkeyPatch) -> None:
    camera = make_camera()
    with_devices(monkeypatch, camera, [None])
    stream = OpenCVCameraStream(camera)
    assert await stream.acquire("juego") is False
    assert not stream.active
    assert stream.latest() is None


async def test_si_la_camara_se_cuelga_el_stream_abre_otra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(stream_module, "STALL_S", 0.3)
    monkeypatch.setattr(stream_module, "_WATCH_S", 0.05)
    camera = make_camera()
    hung = FakeVideo(hang_after=3)
    good = FakeVideo()
    opened = with_devices(monkeypatch, camera, [hung, good])
    stream = OpenCVCameraStream(camera, fps=100)

    assert await stream.acquire("juego")
    await wait_for(lambda: good.count > 0)
    assert len(opened) == 2
    latest = stream.latest()
    assert latest is not None and time.monotonic() - latest[0] < 0.5
    # El hilo colgado suelta su dispositivo él solo cuando el driver vuelve.
    assert not hung.released
    hung.unhang.set()
    await wait_for(lambda: hung.released)
    await stream.release("juego")
    assert not good.released


async def test_si_la_camara_deja_de_dar_imagen_el_stream_la_reabre(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(stream_module, "_WATCH_S", 0.05)
    camera = make_camera()
    dead = FakeVideo(fail_after=3)
    good = FakeVideo()
    opened = with_devices(monkeypatch, camera, [dead, good])
    stream = OpenCVCameraStream(camera, fps=100)

    assert await stream.acquire("juego")
    await wait_for(lambda: good.count > 0)
    assert dead.released
    assert len(opened) == 2
    await stream.release("juego")


async def test_al_cambiar_de_camara_en_pleno_juego_el_dispositivo_viejo_se_suelta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    camera = make_camera()
    old = FakeVideo()
    new = FakeVideo()
    with_devices(monkeypatch, camera, [old, new])
    stream = OpenCVCameraStream(camera, fps=50)
    assert await stream.acquire("juego")
    await camera.set_index(1)
    await stream.release("juego")
    assert old.released
    assert await camera.capture() is not None
    assert new.reads == 1


async def test_con_la_camara_cerrada_el_stream_no_la_reabre(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    camera = make_camera()
    device = FakeVideo()
    with_devices(monkeypatch, camera, [device])
    stream = OpenCVCameraStream(camera, fps=50)
    assert await stream.acquire("juego")
    await camera.close()
    await stream.release("juego")
    assert device.released
    assert await stream.acquire("otro") is False


# ---------------------------------------------------------------------------
# Vista en vivo
# ---------------------------------------------------------------------------


class FakeStream:
    """Stream falso: un frame fijo con la hora de ahora (cada vuelta, uno «nuevo»)."""

    def __init__(self, frame: np.ndarray, *, ok: bool = True) -> None:
        self.frame = frame
        self.ok = ok
        self.owners: set[str] = set()

    @property
    def active(self) -> bool:
        return bool(self.owners)

    async def acquire(self, owner: str) -> bool:
        if self.ok:
            self.owners.add(owner)
        return self.ok

    async def release(self, owner: str) -> None:
        self.owners.discard(owner)

    def latest(self) -> tuple[float, np.ndarray] | None:
        return (time.monotonic(), self.frame) if self.owners else None


class Sink:
    def __init__(self) -> None:
        self.json: list[dict[str, Any]] = []
        self.bytes: list[bytes] = []

    async def send_json(self, msg: dict[str, Any]) -> None:
        self.json.append(msg)

    async def send_bytes(self, data: bytes) -> None:
        self.bytes.append(data)


def make_preview(
    stream: FakeStream, sink: Sink, supported: Callable[[], bool] = lambda: True
) -> LivePreview:
    return LivePreview(stream, sink.send_json, sink.send_bytes, supported, fps=50)


async def test_la_vista_en_vivo_manda_frames_sncv_en_espejo_con_el_dibujo() -> None:
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    frame[:, :640] = 200  # la mitad izquierda clara
    stream = FakeStream(frame)
    sink = Sink()
    preview = make_preview(stream, sink)
    calls: list[tuple[tuple[int, ...], bool]] = []

    def overlay(image: np.ndarray, mirrored: bool) -> None:
        calls.append((image.shape, mirrored))

    assert await preview.start("poses", overlay=overlay)
    assert preview.active
    assert sink.json[0] == {"type": "camera_preview", "on": True, "mirror": True}
    await wait_for(lambda: len(sink.bytes) >= 3)

    seqs = []
    for data in sink.bytes[:3]:
        seq, width, height, mirrored, jpeg = decode_preview_frame(data)
        seqs.append(seq)
        assert (width, height, mirrored) == (640, 360, True)
        image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        assert image.shape == (360, 640, 3)
        # En espejo, la mitad clara sale a la derecha.
        assert image[:, 480].mean() > 150 > 50 > image[:, 160].mean()
    assert seqs == sorted(seqs) and len(set(seqs)) == 3
    assert calls[0] == ((360, 640, 3), True)
    # El frame compartido no se toca.
    assert frame[:, 640:].max() == 0

    await preview.stop("poses")
    assert not preview.active
    assert sink.json[-1] == {"type": "camera_preview", "on": False, "mirror": True}
    assert not stream.owners
    sent = len(sink.bytes)
    await asyncio.sleep(0.1)
    assert len(sink.bytes) == sent


async def test_sin_unity_que_la_pinte_no_se_manda_nada() -> None:
    stream = FakeStream(np.zeros((48, 64, 3), dtype=np.uint8))
    sink = Sink()
    preview = make_preview(stream, sink, supported=lambda: False)
    assert await preview.start("poses") is False
    assert not preview.active
    await asyncio.sleep(0.05)
    assert sink.json == [] and sink.bytes == []
    assert not stream.owners


async def test_sin_camara_la_vista_no_se_enciende() -> None:
    stream = FakeStream(np.zeros((48, 64, 3), dtype=np.uint8), ok=False)
    sink = Sink()
    preview = make_preview(stream, sink)
    assert await preview.start("poses") is False
    assert sink.json == [] and sink.bytes == []


async def test_si_unity_se_reconecta_la_vista_se_vuelve_a_anunciar() -> None:
    stream = FakeStream(np.zeros((48, 64, 3), dtype=np.uint8))
    sink = Sink()
    supported = [True]
    preview = make_preview(stream, sink, supported=lambda: supported[0])
    assert await preview.start("busqueda")
    await wait_for(lambda: len(sink.bytes) >= 1)
    supported[0] = False
    await asyncio.sleep(0.1)
    sent = len(sink.bytes)
    await asyncio.sleep(0.1)
    assert len(sink.bytes) == sent  # sin Unity que la pinte, nada
    supported[0] = True
    await wait_for(lambda: len([m for m in sink.json if m["on"]]) >= 2)
    await wait_for(lambda: len(sink.bytes) > sent)
    await preview.stop("busqueda")


async def test_un_dibujo_que_falla_no_apaga_la_vista() -> None:
    stream = FakeStream(np.zeros((48, 64, 3), dtype=np.uint8))
    sink = Sink()
    preview = make_preview(stream, sink)

    def broken(image: np.ndarray, mirrored: bool) -> None:
        raise RuntimeError("dibujo roto")

    assert await preview.start("ppt", overlay=broken)
    await wait_for(lambda: len(sink.bytes) >= 2)
    preview.set_overlay(None)
    await preview.stop("ppt")


async def test_dos_juegos_comparten_la_vista_y_se_apaga_con_el_ultimo() -> None:
    stream = FakeStream(np.zeros((48, 64, 3), dtype=np.uint8))
    sink = Sink()
    preview = make_preview(stream, sink)
    assert await preview.start("a")
    assert await preview.start("b", mirror=False)
    await preview.stop("a")
    assert preview.active
    assert [m["on"] for m in sink.json].count(False) == 0
    await preview.stop("b")
    assert sink.json[-1]["on"] is False
    assert not stream.owners


def test_render_preview_con_camara_4_3_pone_bandas_y_el_dibujo_en_su_sitio() -> None:
    frame = np.zeros((480, 640, 3), dtype=np.uint8)

    def dot(image: np.ndarray, mirrored: bool) -> None:
        height, width = image.shape[:2]
        x = 1 - 0.25 if mirrored else 0.25
        cv2.circle(image, (round(x * (width - 1)), height // 2), 6, (255, 255, 255), -1)

    rendered = render_preview(frame, mirror=True, overlay=dot, quality=95)
    assert rendered is not None
    jpeg, width, height = rendered
    assert (width, height) == (640, 360)
    image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_GRAYSCALE)
    # La imagen de 480x360 va centrada (bandas de 80 px) y el punto, en espejo, a 3/4.
    assert image[180, 80 + round(0.75 * 479)] > 200
    assert image[180, 80 + round(0.25 * 479)] < 50
    assert image[:, :70].max() < 30 and image[:, -70:].max() < 30
