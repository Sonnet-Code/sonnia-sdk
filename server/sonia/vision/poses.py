"""Personas y sus 17 puntos con YOLOv8-pose (ONNX con ``cv2.dnn``), en este equipo.

``docs/plan-juegos.md``, sección 6. Nada sale del equipo y nada se guarda: cada frame se
analiza en memoria y se olvida, y no se reconoce a nadie (solo dónde están los hombros,
los codos, las muñecas...).

- Entrada de 640x640 con letterbox (bandas grises de 114, como en el entrenamiento),
  ÷255 y en RGB.
- Salida ``[1, 56, 8400]``: por candidato, la caja (centro, ancho y alto), la confianza de
  que sea una persona y 17 puntos con ``x``, ``y`` y su visibilidad (0 a 1). Se filtra por
  confianza y se quitan los duplicados con NMS.
- Coordenadas de 0 a 1 sobre la imagen sin espejo (``sonia.vision.contracts``).

Tiempos en el Mac de desarrollo (OpenCV 5.0): unos 30 ms con ``n`` y 70 ms con ``s``.
OpenCV usa varios hilos por detección: se limitan (``DNN_THREADS``) para dejar CPU a Unity.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
from pathlib import Path
from typing import Protocol

import numpy as np

from sonia.vision.contracts import CameraStream, Person, Point, PoseFrame
from sonia.vision.models import POSE_MODELS, GameModel, model_present

__all__ = [
    "DNN_THREADS",
    "INPUT_SIZE",
    "PERSON_SCORE",
    "PoseEstimator",
    "PoseModel",
    "YoloPoseDetector",
    "decode_yolo_pose",
    "letterbox",
]

logger = logging.getLogger(__name__)

#: Lado de la entrada del modelo.
INPUT_SIZE = 640

#: Gris de las bandas del letterbox (el de Ultralytics).
_PAD_VALUE = 114

#: Confianza mínima para dar a alguien por persona. Con 0,25 (la de Ultralytics) salían
#: personas a medias en el fondo; los juegos se quedan además con las grandes.
PERSON_SCORE = 0.35

#: Solape máximo entre dos cajas de la misma persona (NMS).
NMS_IOU = 0.5

#: Personas como mucho por frame.
MAX_PEOPLE = 30

#: Hilos de OpenCV para la detección: deja el resto de la CPU a Unity y al audio.
#: ``cv2.setNumThreads`` es de todo el proceso: también vale para las caras.
DNN_THREADS = 4

#: Si una detección suelta llega con el modelo sin cargar, espera a que cargue.
_LOAD_TIMEOUT_S = 20.0


def letterbox(image: np.ndarray, size: int = INPUT_SIZE) -> tuple[np.ndarray, float, int, int]:
    """Reduce la imagen a ``size`` x ``size`` sin deformarla, centrada con bandas grises.

    Devuelve la imagen, la escala y el desplazamiento (``izquierda``, ``arriba``) para
    deshacerlo: ``x_original = (x - izquierda) / escala``.
    """
    import cv2

    height, width = int(image.shape[0]), int(image.shape[1])
    scale = min(size / width, size / height)
    new_w, new_h = max(1, round(width * scale)), max(1, round(height * scale))
    interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    resized = cv2.resize(image, (new_w, new_h), interpolation=interpolation)
    left, top = (size - new_w) // 2, (size - new_h) // 2
    canvas = np.full((size, size, 3), _PAD_VALUE, dtype=np.uint8)
    canvas[top : top + new_h, left : left + new_w] = resized
    return canvas, scale, left, top


def decode_yolo_pose(
    output: np.ndarray,
    *,
    scale: float,
    left: int,
    top: int,
    width: int,
    height: int,
    score_threshold: float = PERSON_SCORE,
    iou_threshold: float = NMS_IOU,
    max_people: int = MAX_PEOPLE,
) -> tuple[Person, ...]:
    """Personas de la salida ``[1, 56, N]`` de YOLOv8-pose, en coordenadas de 0 a 1.

    Función pura (sin modelo): se prueba con salidas inventadas. Ordenadas de la de más
    confianza a la de menos.
    """
    import cv2

    rows = np.asarray(output, dtype=np.float32).reshape(56, -1).T
    scores = rows[:, 4]
    keep = np.flatnonzero(scores >= score_threshold)
    if keep.size == 0:
        return ()
    rows = rows[keep]
    scores = scores[keep]
    boxes = [
        [float(cx - w / 2), float(cy - h / 2), float(w), float(h)] for cx, cy, w, h in rows[:, :4]
    ]
    picked = cv2.dnn.NMSBoxes(boxes, scores.tolist(), score_threshold, iou_threshold)
    order = sorted(
        (int(i) for i in np.asarray(picked).reshape(-1)), key=lambda i: -float(scores[i])
    )
    people: list[Person] = []
    for index in order[:max_people]:
        x, y, w, h = boxes[index]
        x0 = (x - left) / scale / width
        y0 = (y - top) / scale / height
        x1 = (x + w - left) / scale / width
        y1 = (y + h - top) / scale / height
        x0, x1 = max(0.0, min(1.0, x0)), max(0.0, min(1.0, x1))
        y0, y1 = max(0.0, min(1.0, y0)), max(0.0, min(1.0, y1))
        keypoints = rows[index, 5:56].reshape(17, 3)
        points = tuple(
            Point(
                x=max(0.0, min(1.0, (float(px) - left) / scale / width)),
                y=max(0.0, min(1.0, (float(py) - top) / scale / height)),
                score=max(0.0, min(1.0, float(pv))),
            )
            for px, py, pv in keypoints
        )
        people.append(
            Person(box=(x0, y0, x1 - x0, y1 - y0), score=float(scores[index]), points=points)
        )
    return tuple(people)


class PoseEstimator(Protocol):
    """Lo que necesita el detector de un modelo de poses (los tests ponen uno falso)."""

    def detect(self, frame_bgr: np.ndarray) -> tuple[Person, ...]: ...


class PoseModel:
    """YOLOv8-pose cargado con ``cv2.dnn``. No es seguro entre hilos: va con candado."""

    def __init__(self, path: Path, *, threads: int = DNN_THREADS) -> None:
        import cv2

        if threads > 0:
            cv2.setNumThreads(threads)
        self._cv2 = cv2
        self._net = cv2.dnn.readNetFromONNX(str(path))
        self._lock = threading.Lock()

    def detect(self, frame_bgr: np.ndarray) -> tuple[Person, ...]:
        """Las personas de un frame BGR. Bloquea decenas de milisegundos: va en un hilo."""
        height, width = int(frame_bgr.shape[0]), int(frame_bgr.shape[1])
        if width <= 0 or height <= 0:
            return ()
        canvas, scale, left, top = letterbox(frame_bgr)
        blob = self._cv2.dnn.blobFromImage(
            canvas, 1 / 255.0, (INPUT_SIZE, INPUT_SIZE), swapRB=True, crop=False
        )
        with self._lock:
            self._net.setInput(blob)
            output = self._net.forward()
        return decode_yolo_pose(output, scale=scale, left=left, top=top, width=width, height=height)


class YoloPoseDetector:
    """``PoseDetector`` sobre la cámara en vivo de los juegos (``CameraStream``).

    El modelo se carga la primera vez que hace falta, en un hilo. Con varios dueños,
    detecta a las ``fps`` más altas que pidan. ``detect`` suelto vale sin stream.
    """

    def __init__(
        self,
        stream: CameraStream,
        folder: Path,
        *,
        variant: str = "s",
        threads: int = DNN_THREADS,
        model: PoseEstimator | None = None,
    ) -> None:
        """``model``: un modelo ya cargado (los tests ponen uno falso); si no, el de ``folder``."""
        self._stream = stream
        self._folder = folder
        self._model_file: GameModel = POSE_MODELS.get(variant, POSE_MODELS["s"])
        if variant not in POSE_MODELS:
            logger.warning("GAME_POSES_MODEL=%s no existe: se usa «s»", variant)
        self._threads = threads
        self._model: PoseEstimator | None = model
        self._broken = False
        self._load_lock = asyncio.Lock()
        self._owners: dict[str, float] = {}
        self._task: asyncio.Task[None] | None = None
        self._latest: PoseFrame | None = None
        #: Milisegundos de la última detección y cuántas lleva (para medir).
        self.detect_ms = 0.0
        self.detections = 0

    @property
    def variant(self) -> str:
        return "n" if self._model_file is POSE_MODELS["n"] else "s"

    @property
    def available(self) -> bool:
        if self._broken:
            return False
        return self._model is not None or model_present(self._folder, self._model_file)

    async def acquire(self, owner: str, fps: float) -> bool:
        if not await self._ensure_model():
            return False
        if owner not in self._owners and not await self._stream.acquire("poses:" + owner):
            return False
        self._owners[owner] = max(0.5, float(fps))
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="sonia-poses")
        return True

    async def release(self, owner: str) -> None:
        if self._owners.pop(owner, None) is None:
            return
        if not self._owners:
            task, self._task = self._task, None
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            self._latest = None
        await self._stream.release("poses:" + owner)

    def latest(self, max_age_s: float = 0.5) -> PoseFrame | None:
        frame = self._latest
        if frame is None or time.monotonic() - frame.at > max_age_s:
            return None
        return frame

    async def detect(self, frame_bgr: np.ndarray, at: float) -> PoseFrame:
        height, width = int(frame_bgr.shape[0]), int(frame_bgr.shape[1])
        empty = PoseFrame(at=at, width=width, height=height, people=())
        if not await self._ensure_model():
            return empty
        try:
            return await asyncio.to_thread(self._detect_sync, frame_bgr, at)
        except Exception:  # noqa: BLE001 - una detección fallida no tumba el juego
            logger.exception("Fallo detectando poses")
            return empty

    async def close(self) -> None:
        for owner in list(self._owners):
            await self.release(owner)

    # -- interno -----------------------------------------------------------------

    def _detect_sync(self, frame_bgr: np.ndarray, at: float) -> PoseFrame:
        model = self._model
        height, width = int(frame_bgr.shape[0]), int(frame_bgr.shape[1])
        if model is None:
            return PoseFrame(at=at, width=width, height=height, people=())
        started = time.perf_counter()
        people = model.detect(frame_bgr)
        self.detect_ms = (time.perf_counter() - started) * 1000
        self.detections += 1
        return PoseFrame(at=at, width=width, height=height, people=people)

    async def _ensure_model(self) -> bool:
        if self._model is not None:
            return True
        if self._broken:
            return False
        try:
            async with asyncio.timeout(_LOAD_TIMEOUT_S):
                async with self._load_lock:
                    if self._model is None and not self._broken:
                        await self._load()
        except TimeoutError:
            logger.warning("El modelo de poses tarda demasiado en cargar")
        return self._model is not None

    async def _load(self) -> None:
        path = self._folder / self._model_file.name
        if not model_present(self._folder, self._model_file):
            logger.info("Falta el modelo de poses %s: los juegos de poses no se ofrecen", path)
            return
        try:
            self._model = await asyncio.to_thread(PoseModel, path, threads=self._threads)
        except Exception:  # noqa: BLE001 - sin modelo, el juego no se ofrece
            logger.exception("No se pudo cargar el modelo de poses %s", path)
            self._broken = True
            return
        logger.info("Modelo de poses listo (%s)", self._model_file.name)

    async def _run(self) -> None:
        """Detecta sobre el último frame del stream a las ``fps`` pedidas."""
        last_at: float | None = None
        failures = 0
        while self._owners:
            started = time.monotonic()
            period = 1.0 / max(self._owners.values())
            latest = self._stream.latest()
            if latest is not None and latest[0] != last_at:
                last_at = latest[0]
                try:
                    self._latest = await asyncio.to_thread(self._detect_sync, latest[1], latest[0])
                    failures = 0
                except Exception:  # noqa: BLE001 - se sigue con el frame siguiente
                    failures += 1
                    if failures == 1:
                        logger.exception("Fallo detectando poses")
            await asyncio.sleep(max(0.005, period - (time.monotonic() - started)))
