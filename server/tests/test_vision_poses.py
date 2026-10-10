"""Detector de poses de los juegos sin modelo de verdad: salidas y personas inventadas."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import numpy as np
import pytest

from sonia.vision.contracts import NOSE, R_WRIST, Person, Point
from sonia.vision.poses import (
    INPUT_SIZE,
    YoloPoseDetector,
    decode_yolo_pose,
    letterbox,
)

WIDTH, HEIGHT = 1280, 720
# Letterbox de 1280x720 a 640x640: escala 0,5, sin banda lateral y 140 px arriba.
SCALE, LEFT, TOP = 0.5, 0, 140


def to_input(x: float, y: float) -> tuple[float, float]:
    """De 0 a 1 en la imagen original a píxeles de la entrada del modelo."""
    return x * WIDTH * SCALE + LEFT, y * HEIGHT * SCALE + TOP


def candidate(
    box: tuple[float, float, float, float],
    score: float,
    points: dict[int, tuple[float, float, float]] | None = None,
) -> np.ndarray:
    """Una columna de la salida de YOLOv8-pose (56 valores) para una persona inventada."""
    x0, y0, x1, y1 = box
    ax, ay = to_input(x0, y0)
    bx, by = to_input(x1, y1)
    column = np.zeros(56, dtype=np.float32)
    column[:5] = [(ax + bx) / 2, (ay + by) / 2, bx - ax, by - ay, score]
    for index, (x, y, visible) in (points or {}).items():
        px, py = to_input(x, y)
        column[5 + index * 3 : 8 + index * 3] = [px, py, visible]
    return column


def make_output(columns: list[np.ndarray]) -> np.ndarray:
    output = np.zeros((1, 56, 8400), dtype=np.float32)
    for index, column in enumerate(columns):
        output[0, :, 100 + index * 7] = column
    return output


def test_letterbox_centra_sin_deformar() -> None:
    image = np.full((HEIGHT, WIDTH, 3), 30, dtype=np.uint8)
    canvas, scale, left, top = letterbox(image)
    assert canvas.shape == (INPUT_SIZE, INPUT_SIZE, 3)
    assert (scale, left, top) == (SCALE, LEFT, TOP)
    assert canvas[0, 0, 0] == 114 and canvas[-1, -1, 0] == 114
    assert canvas[TOP, 0, 0] == 30 and canvas[TOP + 359, 639, 0] == 30
    assert canvas[TOP + 360, 0, 0] == 114


def test_decode_saca_las_personas_en_coordenadas_de_la_imagen() -> None:
    first = candidate(
        (0.25, 0.2, 0.45, 0.9),
        0.92,
        {NOSE: (0.35, 0.25, 0.95), R_WRIST: (0.3, 0.1, 0.4)},
    )
    duplicate = candidate((0.252, 0.2, 0.452, 0.9), 0.80)
    second = candidate((0.6, 0.3, 0.8, 0.95), 0.6)
    faint = candidate((0.05, 0.1, 0.15, 0.4), 0.2)
    people = decode_yolo_pose(
        make_output([duplicate, faint, second, first]),
        scale=SCALE,
        left=LEFT,
        top=TOP,
        width=WIDTH,
        height=HEIGHT,
    )
    assert len(people) == 2
    best, other = people
    assert best.score == pytest.approx(0.92)
    assert best.box == pytest.approx((0.25, 0.2, 0.2, 0.7), abs=1e-3)
    assert len(best.points) == 17
    assert (best.points[NOSE].x, best.points[NOSE].y) == pytest.approx((0.35, 0.25), abs=1e-3)
    assert best.points[NOSE].score == pytest.approx(0.95)
    assert best.points[R_WRIST].score == pytest.approx(0.4)
    assert other.box == pytest.approx((0.6, 0.3, 0.2, 0.65), abs=1e-3)


def test_decode_sin_nadie_y_coordenadas_fuera_de_la_imagen() -> None:
    assert (
        decode_yolo_pose(
            make_output([]), scale=SCALE, left=LEFT, top=TOP, width=WIDTH, height=HEIGHT
        )
        == ()
    )
    # Una caja que se sale por arriba (gente pegada a la cámara) se recorta a la imagen.
    tall = candidate((0.4, -0.2, 0.6, 0.8), 0.9, {NOSE: (0.5, -0.1, 0.9)})
    (person,) = decode_yolo_pose(
        make_output([tall]), scale=SCALE, left=LEFT, top=TOP, width=WIDTH, height=HEIGHT
    )
    assert person.box[1] == 0.0
    assert person.points[NOSE].y == 0.0


# ---------------------------------------------------------------------------
# YoloPoseDetector con un modelo y un stream falsos
# ---------------------------------------------------------------------------


def someone(x: float = 0.5) -> Person:
    points = tuple(Point(x, 0.3 + i * 0.02, 0.9) for i in range(17))
    return Person(box=(x - 0.1, 0.2, 0.2, 0.7), score=0.9, points=points)


class FakeModel:
    def __init__(self, people: tuple[Person, ...] = (), *, fail: bool = False) -> None:
        self.people = people
        self.fail = fail
        self.frames: list[np.ndarray] = []

    def detect(self, frame_bgr: np.ndarray) -> tuple[Person, ...]:
        self.frames.append(frame_bgr)
        if self.fail:
            raise RuntimeError("modelo roto")
        return self.people


class FakeStream:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.owners: set[str] = set()
        self.frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)

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


async def test_deteccion_continua_a_las_fps_pedidas(tmp_path: Path) -> None:
    stream = FakeStream()
    model = FakeModel((someone(0.3), someone(0.7)))
    detector = YoloPoseDetector(stream, tmp_path, model=model)
    assert detector.available
    assert await detector.acquire("poses", fps=20)
    assert stream.owners == {"poses:poses"}
    await asyncio.sleep(0.3)
    frame = detector.latest()
    assert frame is not None
    assert (frame.width, frame.height) == (WIDTH, HEIGHT)
    assert len(frame.people) == 2
    assert time.monotonic() - frame.at < 0.5
    # Unas 6 detecciones en 0,3 s a 20 por segundo, no una por vuelta del bucle.
    assert 3 <= len(model.frames) <= 9

    await detector.release("poses")
    assert detector.latest() is None
    assert not stream.owners
    seen = len(model.frames)
    await asyncio.sleep(0.1)
    assert len(model.frames) == seen


async def test_una_deteccion_vieja_no_vale(tmp_path: Path) -> None:
    detector = YoloPoseDetector(FakeStream(), tmp_path, model=FakeModel((someone(),)))
    assert await detector.acquire("ppt", fps=20)
    await asyncio.sleep(0.15)
    assert detector.latest(max_age_s=0.5) is not None
    await detector.release("ppt")
    assert detector.latest(max_age_s=10.0) is None


async def test_deteccion_suelta_y_modelo_que_falla(tmp_path: Path) -> None:
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    detector = YoloPoseDetector(FakeStream(), tmp_path, model=FakeModel((someone(),)))
    result = await detector.detect(frame, 12.5)
    assert (result.at, result.width, result.height, len(result.people)) == (12.5, 640, 360, 1)

    broken = YoloPoseDetector(FakeStream(), tmp_path, model=FakeModel(fail=True))
    result = await broken.detect(frame, 1.0)
    assert result.people == ()
    # En continuo, un fallo tampoco para el bucle.
    assert await broken.acquire("poses", fps=30)
    await asyncio.sleep(0.15)
    assert broken.latest() is None
    await broken.release("poses")


async def test_sin_modelo_no_se_ofrece(tmp_path: Path) -> None:
    stream = FakeStream()
    detector = YoloPoseDetector(stream, tmp_path / "vacia")
    assert not detector.available
    assert await detector.acquire("poses", fps=8) is False
    assert not stream.owners
    frame = await detector.detect(np.zeros((10, 20, 3), dtype=np.uint8), 0.0)
    assert frame.people == ()


async def test_sin_camara_no_detecta(tmp_path: Path) -> None:
    detector = YoloPoseDetector(FakeStream(ok=False), tmp_path, model=FakeModel())
    assert await detector.acquire("poses", fps=8) is False
    assert detector.latest() is None


def test_variante_por_defecto_n_y_desconocida_tambien(tmp_path: Path) -> None:
    assert YoloPoseDetector(FakeStream(), tmp_path).variant == "n"
    assert YoloPoseDetector(FakeStream(), tmp_path, variant="x").variant == "n"
    assert YoloPoseDetector(FakeStream(), tmp_path, variant=" S ").variant == "s"
