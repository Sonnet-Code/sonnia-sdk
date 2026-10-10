"""Las manos del jugador de piedra, papel o tijera: 21 puntos y qué dedos están estirados.

``docs/plan-juegos.md``, secciones 5.4 y 6. En este equipo y sin guardar nada:

1. Las muñecas (y los codos y hombros) de la persona, del detector de poses, dicen dónde
   mirar: se recorta una zona alrededor de cada muñeca.
2. El detector de palmas de MediaPipe (OpenCV Zoo, ``cv2.dnn``) encuentra la palma en
   esa zona y su giro. Si no la encuentra, el giro sale del antebrazo (codo → muñeca).
3. El modelo de 21 puntos de la mano de MediaPipe los saca de un recorte girado de
   224x224 con la mano hacia arriba, como lo espera.
4. Con los puntos se mira qué dedos están estirados (:func:`extended_fingers`) y se
   clasifica con la tabla de la sección 5.4 (:func:`classify`):

   | Dedos estirados           | Lectura     |
   |---------------------------|-------------|
   | Ninguno, o solo el pulgar | piedra      |
   | Índice y corazón          | tijera      |
   | Cuatro o cinco            | papel       |
   | Cualquier otra cosa       | sin lectura |

Coordenadas de 0 a 1 sobre la imagen sin espejo, como todo ``sonia.vision.contracts``.
"""

from __future__ import annotations

import asyncio
import logging
import math
import threading
from pathlib import Path

import numpy as np

from sonia.vision.contracts import (
    L_ELBOW,
    L_SHOULDER,
    L_WRIST,
    R_ELBOW,
    R_SHOULDER,
    R_WRIST,
    HandReading,
    HandShape,
    Person,
    Point,
    Side,
)
from sonia.vision.models import HAND_LANDMARKS, PALM_DETECTOR, load_onnx, model_present

__all__ = [
    "FINGERS",
    "HandModels",
    "MediaPipeHandDetector",
    "classify",
    "decode_palms",
    "extended_fingers",
    "palm_anchors",
]

logger = logging.getLogger(__name__)

#: Entradas de los modelos.
PALM_INPUT = 192
HAND_INPUT = 224

#: Confianza mínima de la muñeca (del detector de poses) para buscar la mano.
MIN_WRIST_SCORE = 0.3
#: Confianza mínima de una palma (sigmoide de la salida del detector).
PALM_SCORE = 0.5
#: Confianza mínima de que el recorte es una mano (salida del modelo de 21 puntos). La
#: demo del OpenCV Zoo usa 0,8 sobre recortes de su detector de palmas; con el giro
#: del antebrazo el recorte es peor y sale algo más baja.
HAND_SCORE = 0.6

#: Escala de la mano respecto a los hombros: una mano mide algo menos de la mitad del
#: ancho de hombros (unos 19 cm frente a 40).
_HAND_PER_SHOULDERS = 0.45
#: Zona donde se busca la palma, en manos: centrada un poco más allá de la muñeca.
_REGION_HANDS = 3.0
_REGION_SHIFT_HANDS = 0.5

#: Recorte de la mano a partir de la palma (``RectTransformation`` de MediaPipe).
_PALM_ROI_SCALE = 2.6
_PALM_ROI_SHIFT_Y = -0.5
#: Recorte de la mano a partir del antebrazo, en manos (cuando no se encuentra la palma).
_ARM_ROI_HANDS = 2.2
_ARM_ROI_SHIFT_HANDS = 0.45

#: Los cuatro dedos largos (MCP, PIP, DIP, punta) y el pulgar, en los 21 puntos de MediaPipe.
FINGERS: dict[str, tuple[int, int, int, int]] = {
    "pulgar": (1, 2, 3, 4),
    "indice": (5, 6, 7, 8),
    "corazon": (9, 10, 11, 12),
    "anular": (13, 14, 15, 16),
    "menique": (17, 18, 19, 20),
}

#: Un dedo largo está estirado si la punta queda lejos de la muñeca (en relación con su
#: nudillo) y el dedo está casi recto en la segunda falange.
_TIP_RATIO = 1.45
_PIP_ANGLE = 130.0
#: El pulgar está estirado si la punta queda lejos del centro de la palma (en palmas: de la
#: muñeca al nudillo del corazón) y está casi recto. Abierto queda a unas 0,85 palmas;
#: recogido sobre los dedos, a unas 0,35.
_THUMB_REACH = 0.65
_THUMB_ANGLE = 140.0


def palm_anchors() -> np.ndarray:
    """Los 2016 anclajes del detector de palmas de 192x192 (rejillas de 24 y 12)."""
    rows: list[tuple[float, float]] = []
    for grid, per_cell in ((24, 2), (12, 6)):
        for y in range(grid):
            for x in range(grid):
                rows.extend([((x + 0.5) / grid, (y + 0.5) / grid)] * per_cell)
    return np.asarray(rows, dtype=np.float32)


_ANCHORS = palm_anchors()


def decode_palms(
    boxes: np.ndarray,
    scores: np.ndarray,
    *,
    scale: float,
    left: float,
    top: float,
    score_threshold: float = PALM_SCORE,
    iou_threshold: float = 0.3,
) -> list[tuple[np.ndarray, np.ndarray, float]]:
    """Palmas de la salida del detector (``[1, 2016, 18]`` y ``[1, 2016, 1]``).

    Devuelve ``(caja x1 y1 x2 y2, 7 puntos (x, y), confianza)`` en píxeles de la imagen
    que se le pasó, deshecho el letterbox (``scale``, ``left``, ``top``). Función pura.
    """
    import cv2

    raw = np.asarray(boxes, dtype=np.float32).reshape(-1, 18)
    logits = np.asarray(scores, dtype=np.float64).reshape(-1)
    probs = 1.0 / (1.0 + np.exp(-np.clip(logits, -50, 50)))
    keep = np.flatnonzero(probs >= score_threshold)
    if keep.size == 0:
        return []
    anchors = _ANCHORS[keep]
    delta = raw[keep]
    centers = delta[:, :2] / PALM_INPUT + anchors
    sizes = delta[:, 2:4] / PALM_INPUT
    xy1 = (centers - sizes / 2) * PALM_INPUT
    xy2 = (centers + sizes / 2) * PALM_INPUT
    rects = [
        [float(a), float(b), float(c - a), float(d - b)]
        for (a, b), (c, d) in zip(xy1, xy2, strict=True)
    ]
    picked = cv2.dnn.NMSBoxes(rects, probs[keep].tolist(), score_threshold, iou_threshold)
    result: list[tuple[np.ndarray, np.ndarray, float]] = []
    for i in (int(j) for j in np.asarray(picked).reshape(-1)):
        box = np.concatenate([xy1[i], xy2[i]])
        landmarks = (delta[i, 4:18].reshape(7, 2) / PALM_INPUT + anchors[i]) * PALM_INPUT
        box = (box - [left, top, left, top]) / scale
        landmarks = (landmarks - [left, top]) / scale
        result.append((box, landmarks, float(probs[keep][i])))
    result.sort(key=lambda item: -item[2])
    return result


def _angle(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    """Ángulo en ``b`` (grados) entre ``b→a`` y ``b→c``: 180 es recto."""
    u, v = a - b, c - b
    norm = float(np.linalg.norm(u) * np.linalg.norm(v))
    if norm <= 1e-9:
        return 0.0
    cosine = float(np.dot(u, v)) / norm
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def extended_fingers(points: np.ndarray) -> frozenset[str]:
    """Los dedos estirados de una mano (21 puntos ``x, y, z`` en la misma escala).

    Sin depender del giro de la mano: compara distancias a la muñeca y ángulos de los
    nudillos, no posiciones en la imagen.
    """
    p = np.asarray(points, dtype=np.float64).reshape(21, -1)
    wrist = p[0]
    palm_center = p[[0, 5, 9, 13, 17]].mean(axis=0)
    palm_size = max(1e-9, _distance(p[0], p[9]))
    extended: set[str] = set()
    for name, (base, middle, _, tip) in FINGERS.items():
        straight = _angle(p[base], p[middle], p[tip])
        if name == "pulgar":
            # La punta lejos del centro de la palma y el pulgar casi recto.
            reach = _distance(p[tip], palm_center) / palm_size
            if reach >= _THUMB_REACH and straight >= _THUMB_ANGLE:
                extended.add(name)
        elif (
            _distance(p[tip], wrist) / max(1e-9, _distance(p[base], wrist)) >= _TIP_RATIO
            and straight >= _PIP_ANGLE
        ):
            extended.add(name)
    return frozenset(extended)


def _distance(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(a - b))


def classify(extended: frozenset[str]) -> HandShape:
    """La tabla de la sección 5.4 del plan."""
    long_fingers = extended - {"pulgar"}
    if not long_fingers:
        return HandShape.ROCK
    if long_fingers == {"indice", "corazon"}:
        return HandShape.SCISSORS
    if len(extended) >= 4:
        return HandShape.PAPER
    return HandShape.UNKNOWN


def _seen(point: Point) -> bool:
    return point.score >= MIN_WRIST_SCORE


class HandModels:
    """El detector de palmas y el de 21 puntos, cargados con ``cv2.dnn``. Con candado."""

    def __init__(self, folder: Path) -> None:
        import cv2

        self._cv2 = cv2
        self._palm = load_onnx(folder / PALM_DETECTOR.name)
        self._hand = load_onnx(folder / HAND_LANDMARKS.name)
        self._palm_out = list(self._palm.getUnconnectedOutLayersNames())
        self._hand_out = list(self._hand.getUnconnectedOutLayersNames())
        self._lock = threading.Lock()

    def palms(self, region: np.ndarray) -> list[tuple[np.ndarray, np.ndarray, float]]:
        """Las palmas de una zona BGR, en sus píxeles."""
        cv2 = self._cv2
        height, width = int(region.shape[0]), int(region.shape[1])
        if width < 8 or height < 8:
            return []
        scale = min(PALM_INPUT / width, PALM_INPUT / height)
        new_w, new_h = max(1, int(width * scale)), max(1, int(height * scale))
        resized = cv2.resize(region, (new_w, new_h), interpolation=cv2.INTER_AREA)
        left, top = (PALM_INPUT - new_w) // 2, (PALM_INPUT - new_h) // 2
        canvas = np.zeros((PALM_INPUT, PALM_INPUT, 3), dtype=np.uint8)
        canvas[top : top + new_h, left : left + new_w] = resized
        blob = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB).astype(np.float32)[np.newaxis] / 255.0
        with self._lock:
            self._palm.setInput(blob)
            outputs = self._palm.forward(self._palm_out)
        named = dict(zip(self._palm_out, outputs, strict=True))
        boxes = next(o for o in named.values() if o.shape[-1] == 18)
        scores = next(o for o in named.values() if o.shape[-1] == 1)
        return decode_palms(boxes, scores, scale=scale, left=left, top=top)

    def landmarks(
        self, frame: np.ndarray, center: tuple[float, float], size: float, rotation: float
    ) -> tuple[np.ndarray, float] | None:
        """Los 21 puntos de la mano en el cuadrado girado ``(centro, lado, giro)`` de ``frame``.

        Devuelve los puntos ``(x, y, z)`` en píxeles de ``frame`` y la confianza de que hay
        una mano, o ``None`` si el recorte no sale.
        """
        cv2 = self._cv2
        if size < 8:
            return None
        matrix = _crop_matrix(center, size, rotation, HAND_INPUT)
        crop = cv2.warpAffine(
            frame,
            matrix,
            (HAND_INPUT, HAND_INPUT),
            flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0),
        )
        blob = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB).astype(np.float32)[np.newaxis] / 255.0
        with self._lock:
            self._hand.setInput(blob)
            outputs = self._hand.forward(self._hand_out)
        named = dict(zip(self._hand_out, outputs, strict=True))
        # Por nombre (``Identity`` a ``Identity_3``): puntos, confianza, mano y puntos 3D.
        points = np.asarray(named.get("Identity", outputs[0]), dtype=np.float64).reshape(21, 3)
        score = float(np.asarray(named.get("Identity_1", outputs[1])).reshape(-1)[0])
        local = np.c_[points[:, :2], np.ones(21)]
        image_xy = local @ matrix.T
        scale = size / HAND_INPUT
        return np.c_[image_xy, points[:, 2] * scale], score


def _crop_matrix(
    center: tuple[float, float], size: float, rotation: float, output: int
) -> np.ndarray:
    """Matriz afín de un píxel del recorte (``output`` x ``output``) al de la imagen.

    El recorte es un cuadrado de lado ``size`` centrado en ``center`` y girado ``rotation``
    radianes, de modo que la dirección de los dedos queda hacia arriba.
    """
    k = size / output
    cos, sin = math.cos(rotation), math.sin(rotation)
    cx, cy = center
    half = size / 2
    return np.array(
        [
            [k * cos, -k * sin, cx - half * (cos - sin)],
            [k * sin, k * cos, cy - half * (sin + cos)],
        ],
        dtype=np.float64,
    )


def _rotation(towards: tuple[float, float]) -> float:
    """El giro que deja hacia arriba la dirección ``towards`` (en píxeles de la imagen)."""
    dx, dy = towards
    angle = math.pi / 2 - math.atan2(-dy, dx)
    return angle - 2 * math.pi * math.floor((angle + math.pi) / (2 * math.pi))


class MediaPipeHandDetector:
    """``HandDetector`` con los modelos de manos de MediaPipe. Los carga al primer uso."""

    def __init__(self, folder: Path) -> None:
        self._folder = folder
        self._models: HandModels | None = None
        self._broken = False
        self._preload_lock = threading.Lock()

    @property
    def available(self) -> bool:
        if self._broken:
            return False
        if self._models is not None:
            return True
        return model_present(self._folder, PALM_DETECTOR) and model_present(
            self._folder, HAND_LANDMARKS
        )

    async def read(self, frame_bgr: np.ndarray, person: Person) -> list[HandReading]:
        models = await self._ensure_models()
        if models is None:
            return []
        try:
            return await asyncio.to_thread(read_hands, models, frame_bgr, person)
        except Exception:  # noqa: BLE001 - sin lectura, el juego repite la ronda
            logger.exception("Fallo leyendo las manos")
            return []

    def preload(self) -> bool:
        """Carga los dos modelos y los calienta en vacío. ``True`` si están listos.

        Bloquea: va en un hilo. Se llama al arrancar y, si no, en la primera lectura.
        """
        with self._preload_lock:
            if self._models is not None:
                return True
            if self._broken or not self.available:
                return False
            try:
                models = HandModels(self._folder)
                blank = np.zeros((PALM_INPUT * 2, PALM_INPUT * 2, 3), dtype=np.uint8)
                models.palms(blank)
                models.landmarks(blank, (PALM_INPUT, PALM_INPUT), PALM_INPUT, 0.0)
            except Exception:  # noqa: BLE001 - sin modelos, el juego no se ofrece
                logger.exception("No se pudieron cargar los modelos de manos")
                self._broken = True
                return False
            self._models = models
            logger.info("Modelos de manos listos")
            return True

    async def _ensure_models(self) -> HandModels | None:
        if self._models is None and not self._broken:
            await asyncio.to_thread(self.preload)
        return self._models


def read_hands(models: HandModels, frame: np.ndarray, person: Person) -> list[HandReading]:
    """Las manos de ``person`` en ``frame``: las que tienen lectura primero, y de ellas la
    más alta (la que se enseña delante del cuerpo). Bloquea: va en un hilo."""
    height, width = int(frame.shape[0]), int(frame.shape[1])
    if width <= 0 or height <= 0 or len(person.points) < 17:
        return []
    points = person.points

    def px(index: int) -> np.ndarray:
        return np.array([points[index].x * width, points[index].y * height])

    shoulders = (
        float(np.linalg.norm(px(L_SHOULDER) - px(R_SHOULDER)))
        if _seen(points[L_SHOULDER]) and _seen(points[R_SHOULDER])
        else 0.0
    )
    readings: list[tuple[HandReading, float]] = []
    sides: tuple[tuple[Side, int, int], ...] = (
        ("izquierda", L_WRIST, L_ELBOW),
        ("derecha", R_WRIST, R_ELBOW),
    )
    for side, wrist_i, elbow_i in sides:
        if not _seen(points[wrist_i]):
            continue
        wrist = px(wrist_i)
        forearm = px(wrist_i) - px(elbow_i) if _seen(points[elbow_i]) else np.array([0.0, -1.0])
        forearm_len = float(np.linalg.norm(forearm))
        direction = forearm / forearm_len if forearm_len > 1e-6 else np.array([0.0, -1.0])
        hand = _hand_size(
            shoulders, forearm_len if _seen(points[elbow_i]) else 0.0, person, width, height
        )
        reading = _read_one(models, frame, side, wrist, direction, hand)
        if reading is not None:
            readings.append((reading, float(wrist[1])))
    if all(reading.shape is HandShape.UNKNOWN for reading, _ in readings):
        # Sin muñecas a la vista (alguien muy cerca) o sin lectura por ellas: las palmas que
        # haya dentro de la caja de la persona.
        readings.extend(_read_in_box(models, frame, person))
    readings = _dedupe(readings)
    readings.sort(key=lambda item: (item[0].shape is HandShape.UNKNOWN, item[1]))
    return [reading for reading, _ in readings]


def _read_in_box(
    models: HandModels, frame: np.ndarray, person: Person
) -> list[tuple[HandReading, float]]:
    """Las manos de las palmas que se encuentren en la caja de la persona (dos como mucho)."""
    height, width = int(frame.shape[0]), int(frame.shape[1])
    x, y, w, h = person.box
    margin_x, margin_y = w * 0.1, h * 0.05
    x0, y0 = max(0, int((x - margin_x) * width)), max(0, int((y - margin_y) * height))
    x1 = min(width, int((x + w + margin_x) * width))
    y1 = min(height, int((y + h + margin_y) * height))
    if x1 - x0 < 16 or y1 - y0 < 16:
        return []
    middle = (x + w / 2) * width
    found: list[tuple[HandReading, float]] = []
    for box, keypoints, _score in models.palms(frame[y0:y1, x0:x1])[:2]:
        box = box + [x0, y0, x0, y0]
        keypoints = keypoints + [x0, y0]
        # De frente, la mano derecha de la persona sale a la izquierda de la imagen.
        side: Side = "derecha" if float(keypoints[0][0]) < middle else "izquierda"
        reading = _reading_from_roi(models, frame, side, _palm_roi(box, keypoints))
        if reading is not None:
            found.append((reading, float(keypoints[0][1])))
    return found


def _hand_size(shoulders: float, forearm: float, person: Person, width: int, height: int) -> float:
    """Largo aproximado de la mano en píxeles, de lo que se vea del cuerpo."""
    if shoulders > 0:
        return max(24.0, shoulders * _HAND_PER_SHOULDERS)
    if forearm > 0:
        return max(24.0, forearm * 0.75)
    return max(24.0, person.box[2] * width * 0.3, person.box[3] * height * 0.08)


def _read_one(
    models: HandModels,
    frame: np.ndarray,
    side: Side,
    wrist: np.ndarray,
    direction: np.ndarray,
    hand: float,
) -> HandReading | None:
    height, width = int(frame.shape[0]), int(frame.shape[1])
    # 1. Zona alrededor de la muñeca, un poco hacia donde apunta el antebrazo.
    center = wrist + direction * hand * _REGION_SHIFT_HANDS
    half = hand * _REGION_HANDS / 2
    x0, y0 = max(0, int(center[0] - half)), max(0, int(center[1] - half))
    x1, y1 = min(width, int(center[0] + half)), min(height, int(center[1] + half))
    roi: tuple[tuple[float, float], float, float] | None = None
    if x1 - x0 >= 16 and y1 - y0 >= 16:
        # 2. La palma más cercana a la muñeca.
        palms = models.palms(frame[y0:y1, x0:x1])
        best: tuple[float, tuple[tuple[float, float], float, float]] | None = None
        for box, keypoints, _score in palms:
            box = box + [x0, y0, x0, y0]
            keypoints = keypoints + [x0, y0]
            distance = float(np.linalg.norm(keypoints[0] - wrist))
            if distance > hand * 1.5:
                continue
            if best is None or distance < best[0]:
                best = (distance, _palm_roi(box, keypoints))
        if best is not None:
            roi = best[1]
    if roi is None:
        # Sin palma: el recorte sale del antebrazo.
        center_arm = wrist + direction * hand * _ARM_ROI_SHIFT_HANDS
        roi = (
            (float(center_arm[0]), float(center_arm[1])),
            hand * _ARM_ROI_HANDS,
            _rotation((float(direction[0]), float(direction[1]))),
        )
    # 3. Los 21 puntos.
    return _reading_from_roi(models, frame, side, roi)


def _reading_from_roi(
    models: HandModels,
    frame: np.ndarray,
    side: Side,
    roi: tuple[tuple[float, float], float, float],
) -> HandReading | None:
    """Los 21 puntos del recorte girado ``roi`` y su lectura, si hay una mano."""
    height, width = int(frame.shape[0]), int(frame.shape[1])
    found = models.landmarks(frame, roi[0], roi[1], roi[2])
    if found is None:
        return None
    landmarks, score = found
    if score < HAND_SCORE:
        return None
    shape = classify(extended_fingers(landmarks))
    xs, ys = landmarks[:, 0] / width, landmarks[:, 1] / height
    bx0, by0 = float(max(0.0, xs.min())), float(max(0.0, ys.min()))
    bx1, by1 = float(min(1.0, xs.max())), float(min(1.0, ys.max()))
    pts = tuple(
        Point(x=float(min(1.0, max(0.0, x))), y=float(min(1.0, max(0.0, y))), score=score)
        for x, y in zip(xs, ys, strict=True)
    )
    return HandReading(
        side=side,
        shape=shape,
        score=score,
        box=(bx0, by0, max(0.0, bx1 - bx0), max(0.0, by1 - by0)),
        points=pts,
    )


def _palm_roi(box: np.ndarray, keypoints: np.ndarray) -> tuple[tuple[float, float], float, float]:
    """El cuadrado de la mano a partir de una palma (como ``RectTransformation`` de MediaPipe)."""
    wrist, middle = keypoints[0], keypoints[2]
    rotation = _rotation((float(middle[0] - wrist[0]), float(middle[1] - wrist[1])))
    width, height = float(box[2] - box[0]), float(box[3] - box[1])
    cx, cy = float(box[0] + box[2]) / 2, float(box[1] + box[3]) / 2
    shift = _PALM_ROI_SHIFT_Y * height
    cx -= shift * math.sin(rotation)
    cy += shift * math.cos(rotation)
    return (cx, cy), max(width, height) * _PALM_ROI_SCALE, rotation


def _dedupe(readings: list[tuple[HandReading, float]]) -> list[tuple[HandReading, float]]:
    """Las dos muñecas pueden dar con la misma mano: se queda la de más confianza."""
    kept: list[tuple[HandReading, float]] = []
    for item in sorted(readings, key=lambda entry: -entry[0].score):
        if all(_iou(item[0].box, other[0].box) < 0.5 for other in kept):
            kept.append(item)
    return kept


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = a[0], a[1], a[0] + a[2], a[1] + a[3]
    bx1, by1, bx2, by2 = b[0], b[1], b[0] + b[2], b[1] + b[3]
    inter = max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(0.0, min(ay2, by2) - max(ay1, by1))
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0
