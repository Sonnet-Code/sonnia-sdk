"""Tests de la capa de visión: codificación de frames, cámaras y política.

No se abre ninguna cámara real: `encode_frame` se prueba con un array de numpy,
`UnityCamera` con un `request_frame` falso, `ObsCamera` con un OBS falso
(obs-websocket 5 en un puerto local) y `ScreenCamera` con una captura inyectada.
"""

from __future__ import annotations

import asyncio
import base64
import json
import socket
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
from sonia.vision import obs as obs_module
from sonia.vision.camera import (
    NullCamera,
    ObsCamera,
    OpenCVCamera,
    ScreenCamera,
    UnityCamera,
    build_camera,
    encode_frame,
)
from sonia.vision.obs import obs_auth
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
    assert isinstance(build_camera(VisionSettings(source="obs")), ObsCamera)
    assert isinstance(build_camera(VisionSettings(source="screen")), ScreenCamera)


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
# Modo reunión: ObsCamera (obs-websocket 5) y ScreenCamera
# ---------------------------------------------------------------------------


class FakeObs:
    """OBS falso: Hello con autenticación, Identify, GetSourceScreenshot."""

    salt = "sal"
    challenge = "reto"

    def __init__(self, *, password: str = "secreto", source: str = "Reunión") -> None:
        self.password = password
        self.source = source
        self.requests: list[dict[str, Any]] = []

    async def handler(self, ws: Any) -> None:
        import cv2

        auth = {"salt": self.salt, "challenge": self.challenge}
        await ws.send(json.dumps({"op": 0, "d": {"rpcVersion": 1, "authentication": auth}}))
        identify = json.loads(await ws.recv())["d"]
        if identify.get("authentication") != obs_auth(self.password, self.salt, self.challenge):
            await ws.close(4009, "Authentication failed.")
            return
        await ws.send(json.dumps({"op": 2, "d": {"negotiatedRpcVersion": 1}}))
        request = json.loads(await ws.recv())["d"]
        self.requests.append(request)
        reply: dict[str, Any] = {
            "requestType": request["requestType"],
            "requestId": request["requestId"],
        }
        if request["requestData"]["sourceName"] != self.source:
            reply["requestStatus"] = {"result": False, "code": 600, "comment": "No source"}
        else:
            jpg = cv2.imencode(".jpg", make_bgr(1280, 720))[1].tobytes()
            reply["requestStatus"] = {"result": True, "code": 100}
            reply["responseData"] = {
                "imageData": "data:image/jpg;base64," + base64.b64encode(jpg).decode()
            }
        await ws.send(json.dumps({"op": 7, "d": reply}))
        await ws.wait_closed()


async def obs_camera(fake: FakeObs, **vision: Any) -> tuple[ObsCamera, Any]:
    from websockets.asyncio.server import serve

    server = await serve(fake.handler, "127.0.0.1", 0)
    port = next(iter(server.sockets)).getsockname()[1]
    settings = VisionSettings(
        source="obs", obs_url=f"ws://127.0.0.1:{port}", obs_password="secreto", **vision
    )
    return ObsCamera(settings), server


async def test_obs_camera_pide_la_foto_de_la_fuente_de_la_reunion() -> None:
    fake = FakeObs()
    camera, server = await obs_camera(fake, max_width=640)
    try:
        frame = await camera.capture()
    finally:
        server.close()
    assert frame is not None
    assert (frame.width, frame.height) == (640, 360)
    assert frame.data[:2] == b"\xff\xd8"  # JPEG
    request = fake.requests[0]
    assert request["requestType"] == "GetSourceScreenshot"
    assert request["requestData"]["sourceName"] == "Reunión"
    assert request["requestData"]["imageWidth"] == 640


async def test_obs_camera_lee_la_contrasena_de_la_configuracion_de_obs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"server_password": "secreto"}), encoding="utf-8")
    monkeypatch.setattr(obs_module, "obs_websocket_config", lambda: config)
    camera, server = await obs_camera(FakeObs())
    camera._settings = camera._settings.model_copy(update={"obs_password": ""})
    try:
        assert await camera.capture() is not None
    finally:
        server.close()


async def test_obs_camera_con_la_contrasena_mala_no_lanza() -> None:
    camera, server = await obs_camera(FakeObs(password="otra"))
    try:
        assert await camera.capture() is None
    finally:
        server.close()


async def test_obs_camera_con_una_fuente_que_no_existe_no_lanza() -> None:
    camera, server = await obs_camera(FakeObs(source="Otra"))
    try:
        assert await camera.capture() is None
    finally:
        server.close()


async def test_obs_camera_con_obs_cerrado_no_lanza() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    camera = ObsCamera(VisionSettings(source="obs", obs_url=f"ws://127.0.0.1:{port}"))
    assert await camera.capture() is None


class FakeObsStudio:
    """OBS falso con estado para ``prepare_meeting``: escenas, fuentes y ventanas."""

    def __init__(self, windows: list[str]) -> None:
        self.windows = windows
        self.inputs: dict[str, dict[str, Any]] = {}
        self.items: dict[int, dict[str, Any]] = {1: {"source": "Unity", "x": 0.0, "locked": False}}
        self.virtualcam = False
        self.calls: list[str] = []

    def handle(self, kind: str, data: dict[str, Any]) -> dict[str, Any] | None:
        import cv2

        self.calls.append(kind)
        if kind == "GetCurrentProgramScene":
            return {"currentProgramSceneName": "Sonia"}
        if kind == "GetInputList":
            return {"inputs": [{"inputName": name} for name in self.inputs]}
        if kind == "CreateInput":
            self.inputs[data["inputName"]] = dict(data["inputSettings"])
            self.items[2] = {"source": data["inputName"], "x": 0.0, "locked": False}
            return {}
        if kind == "GetSceneItemId":
            found = [k for k, v in self.items.items() if v["source"] == data["sourceName"]]
            return {"sceneItemId": found[0]} if found else None
        if kind == "GetInputSettings":
            return {"inputSettings": self.inputs[data["inputName"]]}
        if kind == "GetInputPropertiesListPropertyItems":
            return {
                "propertyItems": [
                    {"itemName": name, "itemValue": index, "itemEnabled": True}
                    for index, name in enumerate(self.windows, start=10)
                ]
            }
        if kind == "SetInputSettings":
            self.inputs[data["inputName"]].update(data["inputSettings"])
            return {}
        if kind == "GetVideoSettings":
            return {"baseWidth": 1920, "baseHeight": 1080}
        if kind == "SetSceneItemTransform":
            self.items[data["sceneItemId"]]["x"] = data["sceneItemTransform"]["positionX"]
            return {}
        if kind == "SetSceneItemLocked":
            self.items[data["sceneItemId"]]["locked"] = data["sceneItemLocked"]
            return {}
        if kind == "SetSceneItemEnabled":
            return {}
        if kind == "GetVirtualCamStatus":
            return {"outputActive": self.virtualcam}
        if kind == "StartVirtualCam":
            self.virtualcam = True
            return {}
        if kind == "GetSourceScreenshot":
            if "window" not in self.inputs.get(data["sourceName"], {}):
                return None  # 702: fuente vacía
            jpg = cv2.imencode(".jpg", make_bgr(320, 180))[1].tobytes()
            return {"imageData": "data:image/jpg;base64," + base64.b64encode(jpg).decode()}
        raise AssertionError(f"petición inesperada: {kind}")

    async def handler(self, ws: Any) -> None:
        await ws.send(json.dumps({"op": 0, "d": {"rpcVersion": 1}}))
        await ws.recv()
        await ws.send(json.dumps({"op": 2, "d": {"negotiatedRpcVersion": 1}}))
        async for raw in ws:
            request = json.loads(raw)["d"]
            response = self.handle(request["requestType"], request.get("requestData") or {})
            status = {"result": response is not None, "code": 100 if response is not None else 600}
            reply = {
                "requestType": request["requestType"],
                "requestId": request["requestId"],
                "requestStatus": status,
                "responseData": response,
            }
            await ws.send(json.dumps({"op": 7, "d": reply}))


async def run_prepare(
    fake: FakeObsStudio, monkeypatch: pytest.MonkeyPatch, **options: Any
) -> list[str]:
    from websockets.asyncio.server import serve

    monkeypatch.setattr(obs_module, "TEST_SHOT_DELAY_S", 0.0)
    async with serve(fake.handler, "127.0.0.1", 0) as server:
        port = next(iter(server.sockets)).getsockname()[1]
        settings = VisionSettings(source="obs", obs_url=f"ws://127.0.0.1:{port}")
        return await obs_module.prepare_meeting(settings, **options)


async def test_prepare_meeting_crea_la_fuente_fuera_del_lienzo_con_la_ventana_de_meet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeObsStudio(["[Google Chrome] Gmail", "[Google Chrome] Meet - abc-defg-hij"])
    report = await run_prepare(fake, monkeypatch)
    assert fake.inputs["Reunión"]["window"] == 11
    reunion = fake.items[2]
    assert reunion["x"] > 1920 and reunion["locked"]
    assert fake.items[1]["x"] == 0.0  # la de Sonia no se toca
    assert not fake.virtualcam  # se comparte pantalla desde Meet
    assert any("Meet - abc-defg-hij" in line for line in report)
    assert any("se ve bien" in line for line in report)


async def test_prepare_meeting_con_varias_reuniones_no_adivina_y_elige_la_pedida(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    windows = ["[Google Chrome] Meet - ujp-ijit-ejb", "[Google Chrome] Meet - Standup meeting V42"]
    fake = FakeObsStudio(windows)
    report = await run_prepare(fake, monkeypatch)
    assert "window" not in fake.inputs["Reunión"]
    assert any("Hay varias reuniones abiertas" in line for line in report)

    fake = FakeObsStudio(windows)
    report = await run_prepare(fake, monkeypatch, window="standup", virtual_camera=True)
    assert fake.inputs["Reunión"]["window"] == 11
    assert fake.virtualcam
    assert any("Standup meeting V42" in line for line in report)


async def test_prepare_meeting_sin_ventana_de_reunion_lo_dice_y_no_lanza(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeObsStudio(["[Google Chrome] Gmail"])
    report = await run_prepare(fake, monkeypatch)
    assert "window" not in fake.inputs["Reunión"]
    assert any("No encuentro la ventana de la reunión" in line for line in report)
    assert any("no salió" in line for line in report)


async def test_screen_camera_reduce_la_captura_de_la_pantalla() -> None:
    monitors: list[int] = []

    def grab(monitor: int) -> np.ndarray:
        monitors.append(monitor)
        return make_bgr(1920, 1080)

    camera = ScreenCamera(VisionSettings(source="screen", screen_monitor=2), grab=grab)
    frame = await camera.capture()
    assert frame is not None and frame.width == 768
    assert monitors == [2]


async def test_screen_camera_si_la_captura_falla_no_lanza() -> None:
    def grab(monitor: int) -> np.ndarray:
        raise RuntimeError("sin pantalla")

    camera = ScreenCamera(VisionSettings(source="screen"), grab=grab)
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


class _FakeCv2:
    """``cv2`` falso: solo abre las cámaras de ``present``."""

    CAP_ANY = 0

    def __init__(self, present: set[int]) -> None:
        self.present = present
        self.opened: list[int] = []

    def VideoCapture(self, index: int, backend: int = 0) -> Any:  # noqa: N802 - como cv2
        cv2 = self

        class _Device(_FakeDevice):
            def isOpened(self) -> bool:  # noqa: N802 - como cv2
                return index in cv2.present

            def set(self, prop: int, value: Any) -> bool:
                return True

        if index in self.present:
            self.opened.append(index)
        return _Device()


def test_si_la_camara_configurada_no_abre_se_usa_la_0(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    fake = _FakeCv2({0})
    monkeypatch.setitem(sys.modules, "cv2", fake)
    camera = OpenCVCamera(VisionSettings(source="opencv", camera_index=3))
    assert camera._open_sync() is not None
    assert fake.opened == [0]
    assert "se usa la de por defecto" in caplog.text


async def test_se_puede_cambiar_de_camara_en_marcha(monkeypatch: pytest.MonkeyPatch) -> None:
    primera, segunda = _FakeDevice(), _FakeDevice()
    settings = VisionSettings(source="opencv")
    camera = OpenCVCamera(settings)
    abiertos = _with_devices(monkeypatch, camera, [primera, segunda])
    assert await camera.capture() is not None
    await camera.set_index(2)
    assert primera.released and settings.camera_index == 2
    assert await camera.capture() is not None
    assert abiertos == [primera, segunda]
