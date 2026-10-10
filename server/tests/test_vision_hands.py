"""Manos de piedra, papel o tijera sin modelos de verdad: manos de 21 puntos inventadas."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from sonia.vision import hands as hands_module
from sonia.vision.contracts import (
    L_ELBOW,
    L_SHOULDER,
    L_WRIST,
    R_ELBOW,
    R_SHOULDER,
    R_WRIST,
    HandShape,
    Person,
    Point,
)
from sonia.vision.hands import (
    MediaPipeHandDetector,
    classify,
    decode_palms,
    extended_fingers,
    palm_anchors,
    read_hands,
)

# Mano derecha abierta, palma a la cámara y dedos hacia arriba (-y), en unidades en las que
# de la muñeca al nudillo del corazón hay 1. Medidas de una mano real de MediaPipe.
OPEN_HAND = {
    0: (0.0, 0.0, 0.0),
    1: (-0.25, -0.15, -0.05),
    2: (-0.45, -0.35, -0.08),
    3: (-0.6, -0.55, -0.1),
    4: (-0.75, -0.7, -0.12),
    5: (-0.25, -0.9, 0.0),
    6: (-0.3, -1.3, 0.0),
    7: (-0.33, -1.55, 0.0),
    8: (-0.35, -1.75, 0.0),
    9: (0.0, -0.95, 0.0),
    10: (0.0, -1.4, 0.0),
    11: (0.0, -1.68, 0.0),
    12: (0.0, -1.9, 0.0),
    13: (0.2, -0.9, 0.0),
    14: (0.23, -1.3, 0.0),
    15: (0.25, -1.55, 0.0),
    16: (0.27, -1.72, 0.0),
    17: (0.38, -0.8, 0.0),
    18: (0.43, -1.1, 0.0),
    19: (0.46, -1.28, 0.0),
    20: (0.48, -1.42, 0.0),
}

LONG = {"indice": 5, "corazon": 9, "anular": 13, "menique": 17}


def make_hand(extended: set[str]) -> np.ndarray:
    """Una mano con ``extended`` estirados y los demás doblados hacia la palma."""
    points = np.array([OPEN_HAND[i] for i in range(21)], dtype=np.float64)
    for name, base in LONG.items():
        if name in extended:
            continue
        mcp = points[base]
        # Puño: la primera falange hacia la cámara y el resto vuelve hacia la palma.
        points[base + 1] = mcp + (0.0, -0.15, -0.35)
        points[base + 2] = mcp + (0.0, 0.15, -0.4)
        points[base + 3] = mcp + (0.0, 0.35, -0.2)
    if "pulgar" not in extended:
        # Pulgar recogido sobre el índice y el corazón.
        points[2] = (-0.35, -0.45, -0.15)
        points[3] = (-0.2, -0.65, -0.3)
        points[4] = (-0.05, -0.75, -0.3)
    return points


def transform(
    points: np.ndarray, angle_deg: float, scale: float, shift: tuple[float, float]
) -> np.ndarray:
    """Gira en el plano de la imagen, escala y mueve: la lectura no debe cambiar."""
    angle = math.radians(angle_deg)
    rotation = np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
    out = points.copy()
    out[:, :2] = points[:, :2] @ rotation.T * scale + shift
    out[:, 2] = points[:, 2] * scale
    return out


ALL = {"pulgar", "indice", "corazon", "anular", "menique"}


@pytest.mark.parametrize(
    ("extended", "shape"),
    [
        (set(), HandShape.ROCK),
        ({"pulgar"}, HandShape.ROCK),
        ({"indice", "corazon"}, HandShape.SCISSORS),
        ({"indice", "corazon", "pulgar"}, HandShape.SCISSORS),
        (ALL, HandShape.PAPER),
        (ALL - {"pulgar"}, HandShape.PAPER),
        ({"pulgar", "indice", "corazon", "anular"}, HandShape.PAPER),
        ({"indice"}, HandShape.UNKNOWN),
        ({"indice", "menique"}, HandShape.UNKNOWN),
        ({"indice", "corazon", "anular"}, HandShape.UNKNOWN),
        ({"corazon", "anular"}, HandShape.UNKNOWN),
    ],
)
def test_la_tabla_de_piedra_papel_o_tijera(extended: set[str], shape: HandShape) -> None:
    assert classify(frozenset(extended)) is shape


@pytest.mark.parametrize("angle", [0.0, 35.0, 90.0, -60.0, 180.0])
@pytest.mark.parametrize(
    ("extended", "shape"),
    [
        (set(), HandShape.ROCK),
        ({"pulgar"}, HandShape.ROCK),
        ({"indice", "corazon"}, HandShape.SCISSORS),
        (ALL, HandShape.PAPER),
        (ALL - {"pulgar"}, HandShape.PAPER),
        ({"indice"}, HandShape.UNKNOWN),
    ],
)
def test_los_dedos_se_leen_con_la_mano_girada(
    extended: set[str], shape: HandShape, angle: float
) -> None:
    points = transform(make_hand(extended), angle, 87.0, (400.0, 300.0))
    assert extended_fingers(points) == frozenset(extended)
    assert classify(extended_fingers(points)) is shape


def test_mano_en_espejo_tambien() -> None:
    points = make_hand({"indice", "corazon"})
    points[:, 0] *= -1  # la mano izquierda
    assert classify(extended_fingers(points)) is HandShape.SCISSORS


# ---------------------------------------------------------------------------
# Detector de palmas: anclajes y salida
# ---------------------------------------------------------------------------


def test_anclajes_del_detector_de_palmas() -> None:
    anchors = palm_anchors()
    assert anchors.shape == (2016, 2)
    assert anchors[0] == pytest.approx((0.5 / 24, 0.5 / 24))
    assert anchors[2] == pytest.approx((1.5 / 24, 0.5 / 24))
    assert anchors[1152] == pytest.approx((0.5 / 12, 0.5 / 12))
    assert anchors[-1] == pytest.approx((11.5 / 12, 11.5 / 12))


def test_decode_palms_deshace_el_letterbox() -> None:
    boxes = np.zeros((1, 2016, 18), dtype=np.float32)
    scores = np.full((1, 2016, 1), -10.0, dtype=np.float32)
    index = 24 * 2 * 10 + 2 * 12  # fila 10, columna 12 de la rejilla de 24
    ax, ay = palm_anchors()[index]
    boxes[0, index, :4] = (4.0, -2.0, 40.0, 30.0)
    boxes[0, index, 4:6] = (0.0, 10.0)  # muñeca de la palma
    boxes[0, index, 8:10] = (0.0, -12.0)  # nudillo del corazón
    scores[0, index, 0] = 5.0
    scores[0, index + 1, 0] = 4.0  # la misma palma desde el anclaje vecino: NMS
    boxes[0, index + 1, :4] = (5.0, -2.0, 40.0, 30.0)
    # Zona de 384x192 metida en 192x192: escala 0,5 y 48 px de banda arriba.
    palms = decode_palms(boxes, scores, scale=0.5, left=0.0, top=48.0)
    assert len(palms) == 1
    box, keypoints, score = palms[0]
    cx, cy = (ax * 192 + 4.0) / 0.5, (ay * 192 - 2.0 - 48.0) / 0.5
    assert box == pytest.approx([cx - 40, cy - 30, cx + 40, cy + 30], abs=1e-3)
    assert keypoints[0] == pytest.approx([ax * 192 / 0.5, (ay * 192 + 10.0 - 48.0) / 0.5], abs=1e-3)
    assert keypoints[2] == pytest.approx([ax * 192 / 0.5, (ay * 192 - 12.0 - 48.0) / 0.5], abs=1e-3)
    assert score == pytest.approx(1 / (1 + math.exp(-5.0)))


def test_decode_palms_sin_palmas() -> None:
    boxes = np.zeros((1, 2016, 18), dtype=np.float32)
    scores = np.full((1, 2016, 1), -10.0, dtype=np.float32)
    assert decode_palms(boxes, scores, scale=1.0, left=0.0, top=0.0) == []


def test_recorte_girado_de_la_mano() -> None:
    # Dedos hacia la derecha de la imagen: arriba del recorte es +x de la imagen.
    rotation = hands_module._rotation((1.0, 0.0))
    assert rotation == pytest.approx(math.pi / 2)
    assert hands_module._rotation((0.0, -1.0)) == pytest.approx(0.0)
    assert abs(hands_module._rotation((0.0, 1.0))) == pytest.approx(math.pi)
    matrix = hands_module._crop_matrix((100.0, 200.0), 50.0, rotation, 224)
    top_center = matrix @ np.array([112.0, 0.0, 1.0])
    center = matrix @ np.array([112.0, 112.0, 1.0])
    assert top_center == pytest.approx([125.0, 200.0])
    assert center == pytest.approx([100.0, 200.0])


# ---------------------------------------------------------------------------
# read_hands con modelos falsos
# ---------------------------------------------------------------------------

WIDTH, HEIGHT = 1280, 720


def player(*, left_seen: bool = False) -> Person:
    """Alguien de frente con la mano derecha delante del pecho (antebrazo hacia arriba)."""
    points = [Point(0.5, 0.3, 0.1) for _ in range(17)]
    points[L_SHOULDER] = Point(0.6, 0.35, 0.9)
    points[R_SHOULDER] = Point(0.4, 0.35, 0.9)
    points[R_ELBOW] = Point(0.42, 0.75, 0.9)
    points[R_WRIST] = Point(0.45, 0.55, 0.9)
    points[L_ELBOW] = Point(0.62, 0.75, 0.9)
    points[L_WRIST] = Point(0.7, 0.8, 0.9 if left_seen else 0.1)
    return Person(box=(0.3, 0.1, 0.4, 0.9), score=0.9, points=tuple(points))


class FakeHandModels:
    """Palmas y puntos inventados: la mano sale donde se recorta, con la forma pedida."""

    def __init__(self, extended: set[str], *, palm: bool = True, score: float = 0.95) -> None:
        self.extended = extended
        self.palm = palm
        self.score = score
        self.regions: list[tuple[int, int]] = []
        self.rois: list[tuple[tuple[float, float], float, float]] = []

    def palms(self, region: np.ndarray) -> list[tuple[np.ndarray, np.ndarray, float]]:
        height, width = region.shape[:2]
        self.regions.append((width, height))
        if not self.palm:
            return []
        # Una palma en el centro de la zona, con la muñeca abajo y los dedos arriba.
        cx, cy = width / 2, height / 2
        box = np.array([cx - 30, cy - 30, cx + 30, cy + 30])
        keypoints = np.array([[cx, cy + 40]] + [[cx, cy - 20]] * 6, dtype=np.float64)
        return [(box, keypoints, 0.9)]

    def landmarks(
        self, frame: np.ndarray, center: tuple[float, float], size: float, rotation: float
    ) -> tuple[np.ndarray, float] | None:
        self.rois.append((center, size, rotation))
        hand = make_hand(self.extended)
        # De la mano canónica (dedos hacia -y) a la imagen, girada como el recorte.
        cos, sin = math.cos(rotation), math.sin(rotation)
        scale = size / 2.6
        xy = np.c_[
            center[0] + scale * (hand[:, 0] * cos - hand[:, 1] * sin),
            center[1] + scale * (hand[:, 0] * sin + hand[:, 1] * cos),
        ]
        return np.c_[xy, hand[:, 2] * scale], self.score


def frame() -> np.ndarray:
    return np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)


def test_lee_la_mano_de_la_muneca_con_su_palma() -> None:
    models = FakeHandModels({"indice", "corazon"})
    readings = read_hands(models, frame(), player())  # type: ignore[arg-type]
    assert len(readings) == 1
    (reading,) = readings
    assert reading.side == "derecha"
    assert reading.shape is HandShape.SCISSORS
    assert reading.score == pytest.approx(0.95)
    assert len(reading.points) == 21
    x, y, w, h = reading.box
    assert 0 < x < 1 and 0 < y < 1 and w > 0 and h > 0
    # La zona va alrededor de la muñeca y se busca la palma en ella.
    assert len(models.regions) == 1
    # Con palma, el recorte sale de ella: dedos hacia arriba.
    (_, _, rotation) = models.rois[0]
    assert rotation == pytest.approx(0.0, abs=1e-6)


def test_sin_palma_el_recorte_sale_del_antebrazo() -> None:
    models = FakeHandModels(ALL, palm=False)
    (reading,) = read_hands(models, frame(), player())  # type: ignore[arg-type]
    assert reading.shape is HandShape.PAPER
    (center, size, rotation) = models.rois[0]
    # Del codo (0,42; 0,75) a la muñeca (0,45; 0,55): hacia arriba y algo a la derecha.
    elbow = np.array([0.42 * WIDTH, 0.75 * HEIGHT])
    wrist = np.array([0.45 * WIDTH, 0.55 * HEIGHT])
    direction = (wrist - elbow) / np.linalg.norm(wrist - elbow)
    assert rotation == pytest.approx(hands_module._rotation((direction[0], direction[1])))
    assert center[1] < wrist[1]  # por encima de la muñeca
    assert size > 100


def test_dos_manos_la_que_tiene_lectura_y_mas_alta_primero() -> None:
    models = FakeHandModels({"pulgar"})
    readings = read_hands(models, frame(), player(left_seen=True))  # type: ignore[arg-type]
    assert [r.side for r in readings] == ["derecha", "izquierda"]
    assert all(r.shape is HandShape.ROCK for r in readings)


def test_si_el_modelo_no_ve_una_mano_no_hay_lectura() -> None:
    models = FakeHandModels(ALL, score=0.2)
    assert read_hands(models, frame(), player()) == []  # type: ignore[arg-type]


def test_sin_munecas_se_buscan_las_palmas_en_la_caja_de_la_persona() -> None:
    # Alguien muy cerca de la cámara: no se le ven las muñecas, pero sí la mano.
    nobody = Person(
        box=(0.4, 0.1, 0.2, 0.5),
        score=0.8,
        points=tuple(Point(0.5, 0.5, 0.1) for _ in range(17)),
    )
    models = FakeHandModels(ALL)
    (reading,) = read_hands(models, frame(), nobody)  # type: ignore[arg-type]
    assert reading.shape is HandShape.PAPER
    assert len(models.regions) == 1  # una sola búsqueda, en la caja
    region_w, region_h = models.regions[0]
    assert region_w == pytest.approx(0.24 * WIDTH, abs=2)
    assert region_h == pytest.approx(0.55 * HEIGHT, abs=2)
    # Sin palmas en la caja, nada (sin muñecas no hay antebrazo del que tirar).
    assert read_hands(FakeHandModels(ALL, palm=False), frame(), nobody) == []  # type: ignore[arg-type]


def test_si_por_la_muneca_no_hay_lectura_se_mira_la_caja() -> None:
    models = FakeHandModels({"indice"})  # un dedo: sin lectura
    readings = read_hands(models, frame(), player())  # type: ignore[arg-type]
    assert len(models.regions) == 2  # la zona de la muñeca y la caja de la persona
    assert all(reading.shape is HandShape.UNKNOWN for reading in readings)


async def test_sin_modelos_no_se_ofrece(tmp_path: Path) -> None:
    detector = MediaPipeHandDetector(tmp_path)
    assert not detector.available
    assert await detector.read(frame(), player()) == []
