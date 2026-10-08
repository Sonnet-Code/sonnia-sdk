"""Caras con OpenCV en este equipo: YuNet las encuentra y SFace saca la huella de cada una.

Nada sale del equipo: cada foto se analiza en memoria y se olvida. Los dos
modelos son los ONNX del OpenCV Model Zoo (YuNet, licencia MIT; SFace, Apache
2.0); se descargan una vez a ``cache/faces/modelos`` y se comprueban por SHA-256.

Medido el 7-oct-2026 en el Mac de desarrollo: 7-13 ms para encontrar las caras
de una foto de 768 px y unos 5 ms por huella, en la CPU.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx
import numpy as np

__all__ = [
    "DETECTOR",
    "MODEL_FILES",
    "RECOGNIZER",
    "Face",
    "FaceAnalyzer",
    "FaceModel",
    "FaceModelError",
    "ensure_models",
    "models_ready",
]

logger = logging.getLogger(__name__)


class FaceModelError(RuntimeError):
    """No se pudieron descargar o cargar los modelos de caras."""


@dataclass(frozen=True, slots=True)
class ModelFile:
    name: str
    url: str
    sha256: str


_ZOO = "https://github.com/opencv/opencv_zoo/raw/main/models"

DETECTOR = ModelFile(
    "face_detection_yunet_2023mar.onnx",
    f"{_ZOO}/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
)
RECOGNIZER = ModelFile(
    "face_recognition_sface_2021dec.onnx",
    f"{_ZOO}/face_recognition_sface/face_recognition_sface_2021dec.onnx",
    "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
)
MODEL_FILES = (DETECTOR, RECOGNIZER)

#: Confianza mínima del detector. Los ejemplos de OpenCV usan 0,8, pero con la webcam del Mac
#: dejaba sin detectar ocho de cada veinte fotos de alguien sentado delante, algo girado
#: (8-oct-2026). Una «cara» que no lo es no se parece a nadie: el umbral de parecido manda.
DETECT_SCORE = 0.6


@dataclass(frozen=True, slots=True)
class Face:
    """Una cara encontrada en una foto."""

    #: Ancho de la cara en píxeles, en la foto tal como se analizó.
    width: int
    #: Confianza del detector (0-1).
    score: float
    #: Huella de SFace (128 valores), normalizada: la similitud es el producto escalar.
    embedding: np.ndarray[Any, Any]


class FaceAnalyzer(Protocol):
    """Lo que necesita el reconocimiento de un modelo de caras (los tests ponen uno falso)."""

    def decode(self, data: bytes, max_side: int = 0) -> Any | None: ...

    def faces(self, image: Any, *, min_width: int = 0, limit: int = 0) -> list[Face]: ...


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _valid(path: Path, sha256: str) -> bool:
    return path.is_file() and _sha256(path) == sha256


def models_ready(folder: Path) -> bool:
    """¿Están los dos modelos en ``folder`` y sin corromper? Lee los archivos: va en un hilo."""
    return all(_valid(folder / model.name, model.sha256) for model in MODEL_FILES)


async def ensure_models(
    folder: Path, *, timeout_s: float = 60.0, transport: httpx.AsyncBaseTransport | None = None
) -> list[str]:
    """Descarga los modelos que falten o no cuadren por SHA-256. Devuelve los que bajó.

    Lanza :class:`FaceModelError` si no puede (sin red, la descarga cambió...).
    """
    downloaded: list[str] = []
    await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_s, connect=min(10.0, timeout_s)),
        follow_redirects=True,
        transport=transport,
    ) as client:
        for model in MODEL_FILES:
            path = folder / model.name
            if await asyncio.to_thread(_valid, path, model.sha256):
                continue
            logger.info("Descargando el modelo de caras %s", model.name)
            try:
                response = await client.get(model.url)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise FaceModelError(f"no se pudo descargar {model.name}: {exc}") from exc
            data = response.content
            digest = hashlib.sha256(data).hexdigest()
            if digest != model.sha256:
                raise FaceModelError(
                    f"{model.name} llegó con otra huella SHA-256 ({digest[:12]}…); no se usa"
                )
            partial = path.with_name(path.name + ".part")
            await asyncio.to_thread(partial.write_bytes, data)
            partial.replace(path)
            downloaded.append(model.name)
    return downloaded


class FaceModel:
    """YuNet y SFace cargados desde ``folder``.

    Sus métodos hacen milisegundos de CPU: se llaman desde un hilo
    (``asyncio.to_thread``), nunca desde el bucle de audio. Los objetos de OpenCV
    no son seguros entre hilos, así que van con un candado.
    """

    def __init__(self, folder: Path) -> None:
        import cv2

        if not hasattr(cv2, "FaceDetectorYN") or not hasattr(cv2, "FaceRecognizerSF"):
            raise FaceModelError(f"este OpenCV ({cv2.__version__}) no trae YuNet ni SFace")
        self._cv2 = cv2
        try:
            self._detector = cv2.FaceDetectorYN.create(
                str(folder / DETECTOR.name), "", (320, 320), DETECT_SCORE, 0.3, 5000
            )
            self._recognizer = cv2.FaceRecognizerSF.create(str(folder / RECOGNIZER.name), "")
        except cv2.error as exc:
            raise FaceModelError(f"no se pudieron cargar los modelos de caras: {exc}") from exc
        self._lock = threading.Lock()

    def decode(self, data: bytes, max_side: int = 0) -> Any | None:
        """JPEG, PNG o WebP a imagen BGR, reducida a ``max_side`` si es más grande."""
        cv2 = self._cv2
        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return None
        height, width = image.shape[:2]
        side = max(height, width)
        if max_side > 0 and side > max_side:
            scale = max_side / side
            size = (max(1, round(width * scale)), max(1, round(height * scale)))
            image = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
        return image

    def faces(self, image: Any, *, min_width: int = 0, limit: int = 0) -> list[Face]:
        """Las caras de ``image`` de al menos ``min_width`` px, de la más grande a la más pequeña."""
        height, width = image.shape[:2]
        with self._lock:
            self._detector.setInputSize((width, height))
            _, found = self._detector.detect(image)
            if found is None:
                return []
            rows = [row for row in found if float(row[2]) >= min_width]
            rows.sort(key=lambda row: float(row[2]) * float(row[3]), reverse=True)
            if limit > 0:
                rows = rows[:limit]
            result: list[Face] = []
            for row in rows:
                crop = self._recognizer.alignCrop(image, row)
                vector = np.asarray(self._recognizer.feature(crop), dtype=np.float32).reshape(-1)
                norm = float(np.linalg.norm(vector))
                if norm > 0:
                    result.append(
                        Face(width=int(row[2]), score=float(row[14]), embedding=vector / norm)
                    )
            return result
