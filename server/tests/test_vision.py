"""Tests de la capa de visión: codificación de frames, cámaras y política.

No se abre ninguna cámara real: `encode_frame` se prueba con un array de numpy
y `UnityCamera` con un `request_frame` falso.
"""

from __future__ import annotations

import asyncio
import base64
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from sonia.config import VisionSettings
from sonia.types import Frame
from sonia.vision import camera as camera_module
from sonia.vision.camera import NullCamera, OpenCVCamera, UnityCamera, build_camera, encode_frame
from sonia.vision.policy import VisionPolicy

# ---------------------------------------------------------------------------
# encode_frame
# ---------------------------------------------------------------------------


def make_bgr(width: int, height: int) -> np.ndarray:
    """Array BGR con un degradado, para que el JPEG no sea trivial."""
    rng = np.random.default_rng(seed=7)
    return rng.integers(0, 255, size=(height, width, 3), dtype=np.uint8)


def test_encode_frame_redimensiona_manteniendo_proporcion() -> None:
    frame = encode_frame(make_bgr(1920, 1080), max_width=768, quality=80)
    assert frame is not None
    assert frame.width == 768
    assert frame.height == 432  # 1080 * 768 / 1920
    assert frame.mime == "image/jpeg"
    assert frame.data[:2] == b"\xff\xd8"  # cabecera JPEG
    assert frame.captured_at > 0


def test_encode_frame_no_amplia_imagenes_pequenas() -> None:
    frame = encode_frame(make_bgr(320, 240), max_width=768, quality=80)
    assert frame is not None
    assert (frame.width, frame.height) == (320, 240)


def test_encode_frame_la_calidad_cambia_el_tamano() -> None:
    bgr = make_bgr(640, 480)
    alta = encode_frame(bgr, max_width=640, quality=95)
    baja = encode_frame(bgr, max_width=640, quality=20)
    assert alta is not None and baja is not None
    assert len(baja.data) < len(alta.data)


def test_encode_frame_se_puede_decodificar() -> None:
    import cv2

    frame = encode_frame(make_bgr(800, 600), max_width=400, quality=90)
    assert frame is not None
    decoded = cv2.imdecode(np.frombuffer(frame.data, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded is not None
    assert decoded.shape == (300, 400, 3)


def test_encode_frame_con_array_vacio() -> None:
    assert encode_frame(np.zeros((0, 0, 3), dtype=np.uint8), 768, 80) is None
    assert encode_frame(None, 768, 80) is None


# ---------------------------------------------------------------------------
# NullCamera y build_camera
# ---------------------------------------------------------------------------


async def test_null_camera() -> None:
    assert await NullCamera().capture() is None


def test_build_camera_segun_source() -> None:
    assert isinstance(build_camera(VisionSettings(source="none")), NullCamera)
    assert isinstance(build_camera(VisionSettings(source="opencv")), OpenCVCamera)
    assert isinstance(build_camera(VisionSettings(source="unity")), UnityCamera)


# ---------------------------------------------------------------------------
# OpenCVCamera: recuperación sin reiniciar el proceso
# ---------------------------------------------------------------------------


class _FakeDevice:
    """`VideoCapture` falso: no hace falta cv2 ni una cámara de verdad."""

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
    """Hace que cada apertura devuelva el siguiente elemento de ``devices``."""
    abiertos: list[Any] = []
    pendientes = list(devices)

    def open_sync() -> Any:
        device = pendientes.pop(0) if pendientes else None
        abiertos.append(device)
        return device

    monkeypatch.setattr(camera, "_open_sync", open_sync)
    return abiertos


async def test_opencv_camera_reintenta_la_apertura_tras_el_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un fallo de apertura no puede dejar a Sonia ciega el resto del día."""
    monkeypatch.setattr(camera_module, "OPEN_RETRY_COOLDOWN_S", 0.05)
    camera = OpenCVCamera(VisionSettings(source="opencv"))
    bueno = _FakeDevice()
    abiertos = _with_devices(monkeypatch, camera, [None, bueno])

    assert await camera.capture() is None
    # Dentro del cooldown no se vuelve a pagar el timeout de apertura.
    assert await camera.capture() is None
    assert len(abiertos) == 1

    await asyncio.sleep(0.06)
    frame = await camera.capture()
    assert frame is not None
    assert len(abiertos) == 2


async def test_opencv_camera_reabre_si_deja_de_dar_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cámara desconectada a media tarde: se suelta el dispositivo muerto."""
    muerto = _FakeDevice(ok=False)
    vivo = _FakeDevice()
    camera = OpenCVCamera(VisionSettings(source="opencv"))
    abiertos = _with_devices(monkeypatch, camera, [muerto, vivo])

    for _ in range(camera_module.MAX_READ_FAILURES):
        assert await camera.capture() is None
    assert muerto.released is True
    assert len(abiertos) == 1

    frame = await camera.capture()
    assert frame is not None
    assert len(abiertos) == 2


async def test_opencv_camera_abandona_una_lectura_colgada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El driver se cuelga dentro de read(): el turno no puede quedarse ahí."""
    monkeypatch.setattr(camera_module, "READ_TIMEOUT_S", 0.05)
    bloqueo = threading.Event()
    colgado = _FakeDevice(block=bloqueo)
    vivo = _FakeDevice()
    camera = OpenCVCamera(VisionSettings(source="opencv"))
    abiertos = _with_devices(monkeypatch, camera, [colgado, vivo])

    inicio = time.monotonic()
    assert await camera.capture() is None
    assert time.monotonic() - inicio < 1.0

    # La captura siguiente no reutiliza el dispositivo que sigue leyendo.
    frame = await camera.capture()
    assert frame is not None
    assert len(abiertos) == 2

    bloqueo.set()
    await asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# UnityCamera
# ---------------------------------------------------------------------------


async def test_unity_camera_recibe_el_frame_pedido() -> None:
    payload = base64.b64encode(b"jpeg-de-unity").decode("ascii")
    camaras: list[UnityCamera] = []

    async def request_frame() -> None:
        # Unity responde con un `camera_frame` poco después de la petición.
        loop = asyncio.get_running_loop()
        loop.call_later(0.01, camaras[0].on_frame, "image/jpeg", payload)

    camera = UnityCamera(request_frame, timeout=1.0)
    camaras.append(camera)
    frame = await camera.capture()
    assert frame is not None
    assert frame.data == b"jpeg-de-unity"
    assert frame.mime == "image/jpeg"


async def test_unity_camera_timeout_sin_frame_previo() -> None:
    llamadas = 0

    async def request_frame() -> None:
        nonlocal llamadas
        llamadas += 1

    camera = UnityCamera(request_frame, timeout=0.05)
    inicio = time.monotonic()
    assert await camera.capture() is None
    assert llamadas == 1
    assert time.monotonic() - inicio >= 0.04


async def test_unity_camera_timeout_devuelve_el_ultimo_frame() -> None:
    async def request_frame() -> None:
        return None  # Unity no responde nunca

    camera = UnityCamera(request_frame, timeout=0.05)
    camera.on_frame("image/png", base64.b64encode(b"viejo").decode("ascii"))
    frame = await camera.capture()
    assert frame is not None
    assert frame.data == b"viejo"
    assert frame.mime == "image/png"


async def test_unity_camera_descarta_el_ultimo_frame_si_es_muy_viejo() -> None:
    """Unity caído: una foto de hace un rato es peor que ninguna."""

    async def request_frame() -> None:
        return None

    camera = UnityCamera(request_frame, timeout=0.01, max_age=0.05)
    camera.on_frame("image/jpeg", base64.b64encode(b"viejo").decode("ascii"))
    assert await camera.capture() is not None

    await asyncio.sleep(0.08)
    assert await camera.capture() is None
    assert camera.last_frame is None


async def test_unity_camera_sin_clientes_no_paga_el_timeout() -> None:
    peticiones = 0

    async def request_frame() -> None:
        nonlocal peticiones
        peticiones += 1

    camera = UnityCamera(request_frame, timeout=5.0, has_clients=lambda: False)
    inicio = time.monotonic()
    assert await camera.capture() is None
    assert peticiones == 0
    assert time.monotonic() - inicio < 0.5


async def test_unity_camera_ignora_base64_invalido() -> None:
    camera = UnityCamera(timeout=0.01)
    camera.on_frame("image/jpeg", "esto-no-es-base64!!")
    assert camera.last_frame is None


async def test_unity_camera_sin_request_frame_devuelve_el_ultimo() -> None:
    camera = UnityCamera(None, timeout=0.01)
    assert await camera.capture() is None
    camera.on_frame("image/jpeg", base64.b64encode(b"x").decode("ascii"))
    frame = await camera.capture()
    assert frame is not None and frame.data == b"x"


async def test_unity_camera_si_request_frame_falla_no_lanza() -> None:
    async def request_frame() -> None:
        raise RuntimeError("Unity desconectado")

    camera = UnityCamera(request_frame, timeout=0.01)
    assert await camera.capture() is None


# ---------------------------------------------------------------------------
# VisionPolicy
# ---------------------------------------------------------------------------


def test_policy_sin_soporte_de_vision_todo_desactivado(tmp_path: Path) -> None:
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
    activa = VisionPolicy(VisionSettings(on_turn_start=True), supports_vision=True)
    assert activa.should_capture_on_turn_start() is True

    inactiva = VisionPolicy(VisionSettings(on_turn_start=False), supports_vision=True)
    assert inactiva.should_capture_on_turn_start() is False


def test_policy_source_none_desactiva() -> None:
    policy = VisionPolicy(VisionSettings(source="none", on_turn_start=True), supports_vision=True)
    assert policy.should_capture_on_turn_start() is False


def test_policy_periodic_desactivado_por_defecto() -> None:
    policy = VisionPolicy(VisionSettings(interval_seconds=0.0), supports_vision=True)
    assert policy.should_capture_periodic(now=100.0) is False


def test_policy_periodic_con_tiempos_simulados() -> None:
    policy = VisionPolicy(VisionSettings(interval_seconds=10.0), supports_vision=True)
    # Sin ninguna captura previa, toca capturar.
    assert policy.should_capture_periodic(now=100.0) is True

    policy.note_captured(now=100.0)
    assert policy.should_capture_periodic(now=105.0) is False
    assert policy.should_capture_periodic(now=109.999) is False
    assert policy.should_capture_periodic(now=110.0) is True

    policy.note_captured(now=110.0)
    assert policy.should_capture_periodic(now=115.0) is False
    assert policy.should_capture_periodic(now=121.0) is True


def test_policy_no_guarda_frames_por_defecto(tmp_path: Path) -> None:
    debug_dir = tmp_path / "debug"
    policy = VisionPolicy(
        VisionSettings(debug_save_frames=False, debug_dir=str(debug_dir)),
        supports_vision=True,
    )
    assert policy.maybe_save_debug(Frame(data=b"jpeg")) is None
    assert not debug_dir.exists()


def test_policy_guarda_frames_en_modo_debug(tmp_path: Path) -> None:
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

    otra = policy.maybe_save_debug(Frame(data=b"png-bytes", mime="image/png"))
    assert otra is not None
    assert otra.suffix == ".png"
    assert len(list(debug_dir.iterdir())) == 2


def test_policy_maybe_save_debug_sin_frame(tmp_path: Path) -> None:
    policy = VisionPolicy(
        VisionSettings(debug_save_frames=True, debug_dir=str(tmp_path)),
        supports_vision=True,
    )
    assert policy.maybe_save_debug(None) is None


@pytest.mark.parametrize("supports_vision", [True, False])
def test_policy_enabled(supports_vision: bool) -> None:
    policy = VisionPolicy(VisionSettings(source="opencv"), supports_vision=supports_vision)
    assert policy.enabled is supports_vision
