"""La puerta del micro: la cámara (sonia/vision/presence.py) y MicGate (sonia/live/audio.py)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from sonia.config import LiveSettings
from sonia.live.audio import MicGate
from sonia.paths import REPO_ROOT
from sonia.types import Frame
from sonia.vision.presence import SCAN_WIDTH, PresenceGate, PresenceWatch, YuNetFaces
from tests.test_live import pcm_level, wait_until

HOLD = 600.0


# ---------------------------------------------------------------------------
# Lo que sabe la cámara
# ---------------------------------------------------------------------------


def test_la_camara_no_cuenta_hasta_ver_su_primera_cara() -> None:
    # Si apunta mal y nunca ve a nadie, Sonia no se queda sorda.
    gate = PresenceGate(HOLD)
    gate.scanned(0, now=0.0)
    gate.scanned(0, now=2_000.0)
    assert gate.admits(2_000.0) and gate.status(2_000.0) == "sin caras aún"


def test_cierra_tras_diez_minutos_sin_nadie_y_abre_al_momento() -> None:
    gate = PresenceGate(HOLD)
    gate.scanned(1, now=0.0)
    assert gate.status(0.0) == "alguien" and gate.near(0.0)
    gate.scanned(0, now=599.0)
    assert gate.admits(599.0) and gate.status(599.0) == "hace poco" and not gate.near(599.0)
    gate.scanned(0, now=601.0)
    assert not gate.admits(601.0) and gate.status(601.0) == "nadie"
    gate.scanned(1, now=602.0)
    assert gate.admits(602.0) and gate.status(602.0) == "alguien"


def test_la_conversacion_cuenta_como_alguien_delante() -> None:
    gate = PresenceGate(HOLD)
    gate.scanned(1, now=0.0)
    gate.busy(500.0)
    gate.scanned(0, now=1_000.0)
    assert gate.admits(1_000.0) and gate.idle_s(1_000.0) == pytest.approx(500.0)
    gate.scanned(0, now=1_101.0)
    assert not gate.admits(1_101.0)


def test_sin_imagen_o_apagada_oye_siempre() -> None:
    gate = PresenceGate(HOLD)
    gate.scanned(1, now=0.0)
    gate.scanned(0, now=700.0)
    assert not gate.admits(700.0)
    # La cámara deja de dar imagen: no se sabe quién hay, así que oye.
    assert gate.admits(706.0) and gate.status(706.0) == "sin imagen"
    gate.scanned(0, now=707.0)
    gate.enabled = False
    assert gate.admits(707.0) and gate.status(707.0) == "apagada" and not gate.near(707.0)


# ---------------------------------------------------------------------------
# Todas las medidas juntas
# ---------------------------------------------------------------------------


@dataclass
class FakePresence:
    ok: bool = True
    close: bool = False

    def admits(self, now: float) -> bool:
        return self.ok

    def near(self, now: float) -> bool:
        return self.close


def make_gate(**overrides: Any) -> MicGate:
    values: dict[str, Any] = {
        "threshold": 0.1,
        "hold_ms": 0,
        "comfort_rms": 0.003,
        "near_scale": 0.5,
        "silence_rms": 0.0005,
    }
    values.update(overrides)
    return MicGate(**values)


def test_la_puerta_del_micro_junta_todas_las_medidas_en_orden() -> None:
    presence = FakePresence(ok=False)
    gate = make_gate(presence=presence)
    assert gate.check(0.5, 0.0, muted=True, echo=True) == "panel"
    assert gate.check(0.5, 0.0, echo=True) == "frase grabada"
    assert gate.check(0.5, 0.0) == "nadie delante"
    presence.ok = True
    assert gate.check(0.0, 0.0) == "silencio"
    assert gate.check(0.05, 0.0) == "pasillo"
    assert gate.check(0.5, 0.0) == ""


def test_con_alguien_delante_la_raya_del_ruido_baja() -> None:
    presence = FakePresence(close=True)
    gate = make_gate(presence=presence)
    assert gate.check(0.06, 0.0) == ""
    presence.close = False
    assert gate.check(0.06, 1.0) == "pasillo"
    # LIVE_PRESENCE_NEAR_GATE_SCALE=1: alguien delante no cambia la raya.
    still = make_gate(presence=FakePresence(close=True), near_scale=1.0)
    assert still.check(0.06, 0.0) == "pasillo"


def test_lo_que_no_pasa_llega_como_ruido_suave() -> None:
    block = np.full(2_400, 0.5, dtype=np.float32)
    closed = make_gate(presence=FakePresence(ok=False))
    assert pcm_level(closed.pcm(block, 0.5, 0.0)) == pytest.approx(0.003, rel=0.2)
    assert closed.reason == "nadie delante"
    open_gate = make_gate()
    assert pcm_level(open_gate.pcm(block, 0.5, 0.0)) == pytest.approx(0.5, rel=0.01)
    assert open_gate.reason == ""


def test_cada_medida_se_apaga_sola() -> None:
    # LIVE_GATE_RMS=0, sin cámara y LIVE_COMFORT_NOISE_RMS=0: pasa todo y lo vacío va en ceros.
    gate = make_gate(threshold=0.0, comfort_rms=0.0)
    assert gate.check(0.01, 0.0) == ""
    assert gate.pcm(np.zeros(10, dtype=np.float32), 0.0, 0.0) == bytes(20)
    assert gate.reason == "silencio"
    gate.set_threshold(0.1)
    assert gate.check(0.01, 0.0) == "pasillo"


# ---------------------------------------------------------------------------
# La revisión de la cámara
# ---------------------------------------------------------------------------


class FakeCamera:
    def __init__(self, frames: list[Frame | None]) -> None:
        self.frames = frames
        self.calls: list[tuple[int | None, int | None]] = []

    async def capture(
        self, *, max_width: int | None = None, quality: int | None = None
    ) -> Frame | None:
        self.calls.append((max_width, quality))
        return self.frames.pop(0) if self.frames else None


class FakeCounter:
    def __init__(self, counts: list[int]) -> None:
        self.counts = counts
        self.min_widths: list[int] = []

    def count(self, data: bytes, min_width: int) -> int:
        self.min_widths.append(min_width)
        return self.counts.pop(0) if self.counts else 0


def live(**overrides: Any) -> LiveSettings:
    values: dict[str, Any] = {
        "api_key": "x",
        "presence_gate": True,
        "presence_hold_seconds": HOLD,
        "presence_scan_seconds": 0.1,
    }
    values.update(overrides)
    return LiveSettings(**values)


def make_watch(
    tmp_path: Path,
    camera: FakeCamera,
    counter: FakeCounter,
    clock: Callable[[], float] = time.monotonic,
) -> PresenceWatch:
    model = tmp_path / "yunet.onnx"
    model.write_bytes(b"modelo")
    return PresenceWatch(
        live(), camera, model=model, counter_factory=lambda _: counter, clock=clock
    )


async def test_cada_revision_pide_una_foto_pequena_y_cuenta_las_caras(tmp_path: Path) -> None:
    camera = FakeCamera([Frame(b"jpeg", width=640, height=360), None])
    counter = FakeCounter([2])
    watch = make_watch(tmp_path, camera, counter, clock=lambda: 100.0)
    assert await watch.prepare()
    assert await watch.scan() == 2
    assert camera.calls == [(SCAN_WIDTH, 70)] and counter.min_widths == [38]
    assert await watch.scan() is None  # sin imagen: no cambia nada
    snap = watch.snapshot(101.0)
    assert snap["enabled"] and snap["ready"] and snap["status"] == "alguien"
    assert snap["hold_s"] == HOLD and snap["near_gate_scale"] == 0.5


async def test_sin_modelo_oye_siempre_y_lo_avisa_una_vez(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    watch = PresenceWatch(
        live(),
        FakeCamera([]),
        model=tmp_path / "no-esta.onnx",
        counter_factory=lambda _: FakeCounter([]),
    )
    with caplog.at_level(logging.WARNING):
        assert not await watch.prepare()
        assert not await watch.prepare()
    assert sum("Sin detector de caras" in r.getMessage() for r in caplog.records) == 1
    assert watch.gate.admits(time.monotonic()) and watch.snapshot()["ready"] is False


def test_arranca_apagada_por_defecto() -> None:
    # GPT-Live ya ignora solo las voces del pasillo: la cámara se enciende desde el panel.
    assert LiveSettings(api_key="x").presence_gate is False
    watch = PresenceWatch(LiveSettings(api_key="x"), FakeCamera([]), model=Path("no-esta.onnx"))
    assert watch.snapshot(0.0)["enabled"] is False and watch.gate.admits(0.0)


async def test_solo_mira_encendida_y_con_sesion_y_la_conversacion_cuenta(tmp_path: Path) -> None:
    camera = FakeCamera([Frame(b"jpeg", width=640, height=360)] * 50)
    watch = make_watch(tmp_path, camera, FakeCounter([]))  # nunca ve a nadie
    watch.gate.enabled = False
    state = {"active": True, "busy": False}
    task = asyncio.create_task(
        watch.run(active=lambda: state["active"], busy=lambda: state["busy"])
    )
    try:
        # Apagada no mira ni carga el detector.
        await asyncio.sleep(0.35)
        assert camera.calls == [] and not watch.watching and not watch.snapshot()["ready"]
        # Encendida pero sin sesión, tampoco.
        watch.gate.enabled = True
        state["active"] = False
        await asyncio.sleep(0.35)
        assert camera.calls == [] and not watch.watching
        state.update(active=True, busy=True)
        await wait_until(lambda: len(camera.calls) >= 2)
        assert watch.watching
        idle = watch.gate.idle_s(time.monotonic())
        assert idle is not None and idle < 1.0
        # Apagada desde el panel: deja de mirar.
        watch.gate.enabled = False
        await wait_until(lambda: not watch.watching)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def test_yunet_no_ve_caras_en_una_foto_vacia() -> None:
    cv2 = pytest.importorskip("cv2")
    model = REPO_ROOT / "cache" / "faces" / "modelos" / "face_detection_yunet_2023mar.onnx"
    if not model.is_file():
        pytest.skip("sin el modelo YuNet en cache/faces/modelos (lo baja `sonia caras`)")
    ok, jpeg = cv2.imencode(".jpg", np.zeros((360, 640, 3), np.uint8))
    assert ok
    assert YuNetFaces(model).count(jpeg.tobytes(), 38) == 0
