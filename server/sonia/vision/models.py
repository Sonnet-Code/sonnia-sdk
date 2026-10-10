"""Modelos de la visión de los juegos: poses (YOLOv8-pose) y manos (MediaPipe), en ONNX.

``docs/plan-juegos.md``, sección 6. Se descargan una vez a ``GAMES_MODELS_DIR``
(``cache/games/modelos``), con la revisión fijada y comprobados por SHA-256, como los de
las caras (``sonia/faces/model.py``). La app los lleva todos dentro, los dos de poses (``n`` y
``s``) y los de manos (``scripts/build_orquestador.sh``), y los copia a su carpeta de datos al
arrancar (``sonia.paths.SEEDED``). Al arrancar solo exige el de poses de ``GAME_POSES_MODEL``
y los de manos: si faltan, el motor los baja en segundo plano y, hasta que llegan, los juegos
de cámara no se ofrecen. El otro de poses se baja la primera vez que se pide desde el panel.

Para bajarlos a mano (o antes de congelar el orquestador), desde ``server/``::

    uv run --no-sync python -m sonia.vision.models
"""

from __future__ import annotations

import hashlib
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

__all__ = [
    "DEFAULT_POSE_VARIANT",
    "HAND_LANDMARKS",
    "PALM_DETECTOR",
    "POSE_MODELS",
    "POSE_VARIANTS",
    "GameModel",
    "GameModelError",
    "all_game_models",
    "download_game_models",
    "game_models",
    "games_models_dir",
    "load_onnx",
    "model_present",
    "pose_variant",
]

logger = logging.getLogger(__name__)


class GameModelError(RuntimeError):
    """No se pudo descargar un modelo de los juegos."""


@dataclass(frozen=True, slots=True)
class GameModel:
    name: str
    url: str
    sha256: str
    size: int


_HF = "https://huggingface.co"

#: YOLOv8-pose exportado a ONNX (Ultralytics, AGPL-3.0; demo sin ánimo de lucro). Entrada
#: 640x640 RGB, salida ``[1, 56, 8400]``. ``n`` (por defecto) gasta la mitad de CPU; ``s``
#: acierta algo más con gente tapada. La app lleva los dos y se cambia desde el panel.
POSE_MODELS: dict[str, GameModel] = {
    "s": GameModel(
        "yolov8s-pose.onnx",
        f"{_HF}/Xenova/yolov8s-pose/resolve/9dd2818a340ad6682eb38c9d99b6c67dc054da4b/onnx/model.onnx",
        "5c92815cc509a9ccb6a817f4c2816de800092964319ad179a2751eda6df35d83",
        46_787_284,
    ),
    "n": GameModel(
        "yolov8n-pose.onnx",
        f"{_HF}/Xenova/yolov8n-pose/resolve/da4224085e2f6ce4c9ff9b670e28765194619db2/onnx/model.onnx",
        "04f6d2416266f2aba6c5ba8b26de33ed9eba3279f972ac02e33f9f1366547586",
        13_484_153,
    ),
}

#: Los 21 puntos de la mano de MediaPipe (OpenCV Zoo, Apache 2.0). Entrada 224x224 RGB.
HAND_LANDMARKS = GameModel(
    "handpose_estimation_mediapipe_2023feb.onnx",
    f"{_HF}/opencv/handpose_estimation_mediapipe/resolve/"
    "4b2a0b446e5cf2f11fb6b2c7251091c035d2c1f7/handpose_estimation_mediapipe_2023feb.onnx",
    "db0898ae717b76b075d9bf563af315b29562e11f8df5027a1ef07b02bef6d81c",
    4_099_621,
)

#: El detector de palmas de MediaPipe (OpenCV Zoo, Apache 2.0). Entrada 192x192 RGB: encuentra
#: la palma cerca de la muñeca y su giro, para recortar la mano como la espera el de los puntos.
PALM_DETECTOR = GameModel(
    "palm_detection_mediapipe_2023feb.onnx",
    f"{_HF}/opencv/palm_detection_mediapipe/resolve/"
    "233e619dcea1759bf6de707b9b904fe30881ea55/palm_detection_mediapipe_2023feb.onnx",
    "78ff51c38496b7fc8b8ebdb6cc8c1abb02fa6c38427c6848254cdaba57fcce7c",
    3_905_734,
)


#: Las variantes del modelo de poses, de la ligera a la precisa (así las ofrece el panel).
POSE_VARIANTS = ("n", "s")

#: La de ``GAME_POSES_MODEL`` por defecto: la mitad de CPU que ``s`` con Unity en marcha y
#: de frente detecta casi igual (10 de octubre de 2026, ``docs/juegos-vision.md``).
DEFAULT_POSE_VARIANT = "n"


def pose_variant(raw: Any) -> str | None:
    """``n`` o ``s`` a partir de lo que llegue (ajustes, panel); ``None`` si no es ninguna."""
    if not isinstance(raw, str):
        return None
    value = raw.strip().lower()
    return value if value in POSE_MODELS else None


def game_models(pose_variant_id: str = DEFAULT_POSE_VARIANT) -> tuple[GameModel, ...]:
    """Lo que exige la app al arrancar: el modelo de poses de ``GAME_POSES_MODEL`` y los de
    manos. El otro de poses se baja la primera vez que se pide (``set_variant``)."""
    pose = POSE_MODELS[pose_variant(pose_variant_id) or DEFAULT_POSE_VARIANT]
    return (pose, PALM_DETECTOR, HAND_LANDMARKS)


def all_game_models() -> tuple[GameModel, ...]:
    """Todos: los dos de poses y los de manos (los que lleva la app, ``python -m``)."""
    return (*(POSE_MODELS[v] for v in POSE_VARIANTS), PALM_DETECTOR, HAND_LANDMARKS)


def games_models_dir(settings: Any | None = None) -> Path:
    """``GAMES_MODELS_DIR`` si los cimientos lo definen; si no, ``cache/games/modelos``."""
    games = getattr(settings, "games", None)
    custom = str(getattr(games, "models_dir", "") or "").strip()
    if custom:
        return Path(custom).expanduser()
    from sonia.paths import home

    return home() / "cache" / "games" / "modelos"


def model_present(folder: Path, model: GameModel) -> bool:
    """¿Está el archivo con su tamaño? Sin leerlo entero: vale para decidir rápido."""
    path = folder / model.name
    try:
        return path.is_file() and path.stat().st_size == model.size
    except OSError:
        return False


def load_onnx(path: Path) -> Any:
    """Carga un ONNX con ``cv2.dnn``, con el motor clásico si lo hay.

    En OpenCV 5 el motor clásico gasta bastante menos CPU con estos modelos que el nuevo
    (medido el 10-oct-2026 en el Mac: YOLOv8s-pose, 300 ms de CPU por foto frente a 510, y
    58 ms frente a 67 de reloj). Si no carga con él, se usa el de por defecto.
    """
    import cv2

    classic = getattr(cv2.dnn, "ENGINE_CLASSIC", None)
    if classic is not None:
        try:
            return cv2.dnn.readNetFromONNX(str(path), engine=classic)
        except cv2.error:
            logger.info("%s no carga con el motor clásico de OpenCV: se usa el nuevo", path.name)
    return cv2.dnn.readNetFromONNX(str(path))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _valid(path: Path, sha256: str) -> bool:
    return path.is_file() and _sha256(path) == sha256


def download_game_models(
    folder: Path,
    models: tuple[GameModel, ...] | None = None,
    *,
    timeout_s: float = 120.0,
    client: httpx.Client | None = None,
) -> list[str]:
    """Descarga los modelos que falten o no cuadren por SHA-256. Devuelve los que bajó.

    Bloquea (red y disco): va en un hilo o en un script. Lanza :class:`GameModelError` si
    no puede (sin red, la descarga cambió...).
    """
    wanted = models if models is not None else game_models()
    folder.mkdir(parents=True, exist_ok=True)
    own = client is None
    http = client or httpx.Client(
        timeout=httpx.Timeout(timeout_s, connect=min(10.0, timeout_s)), follow_redirects=True
    )
    downloaded: list[str] = []
    try:
        for model in wanted:
            path = folder / model.name
            if _valid(path, model.sha256):
                continue
            logger.info("Descargando el modelo de los juegos %s", model.name)
            try:
                response = http.get(model.url)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise GameModelError(f"no se pudo descargar {model.name}: {exc}") from exc
            data = response.content
            digest = hashlib.sha256(data).hexdigest()
            if digest != model.sha256:
                raise GameModelError(
                    f"{model.name} llegó con otra huella SHA-256 ({digest[:12]}…); no se usa"
                )
            partial = path.with_name(path.name + ".part")
            partial.write_bytes(data)
            partial.replace(path)
            downloaded.append(model.name)
    finally:
        if own:
            http.close()
    return downloaded


def main(argv: list[str] | None = None) -> int:
    """Baja todos los modelos de los juegos (los dos de poses y los de manos)."""
    args = sys.argv[1:] if argv is None else argv
    folder = Path(args[0]).expanduser() if args else games_models_dir()
    every = all_game_models()
    try:
        downloaded = download_game_models(folder, every)
    except GameModelError as exc:
        print(f"No se pudieron bajar los modelos de los juegos: {exc}")
        return 1
    print(f"Modelos de los juegos en {folder}: {len(every)} ({len(downloaded)} descargados ahora)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
