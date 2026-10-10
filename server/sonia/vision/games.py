"""Monta la visión en vivo de los juegos (``docs/plan-juegos.md``, sección 6).

Es la costura entre los cimientos de los juegos (``sonia.games``, que llaman a
:func:`build_game_vision` al arrancar el motor) y la visión de verdad:

- ``stream``: la lectura continua de la cámara USB (``sonia.vision.stream``);
- ``preview``: la vista en vivo hacia Unity, en frames ``SNCV`` (``sonia.vision.stream``);
- ``poses``: YOLOv8-pose con ``cv2.dnn`` (``sonia.vision.poses``);
- ``hands``: las manos de MediaPipe para piedra, papel o tijera (``sonia.vision.hands``);
- ``judge``: la pregunta cerrada al modelo de visión (``sonia.vision.judge``);
- ``referee``: el juez de las rondas de Simón dice y de piedra, papel o tijera
  (``sonia.vision.referee``). Con ``GAMES_JUDGE=gemini`` y ``GEMINI_API_KEY`` es Gemini, el
  modelo de los gestos, y la búsqueda también pregunta a Gemini; con ``local`` o sin clave,
  todo como antes: deciden las detecciones locales y la búsqueda va al modelo de visión.

Sin cámara USB (``VISION_SOURCE`` distinto de ``opencv``) todo dice que no está disponible y
los juegos de cámara no se ofrecen. Cada pieza se apaga sola si le falta lo suyo (los modelos,
la Unity que sabe pintar la vista, el modelo de visión).
"""

from __future__ import annotations

import importlib.util
import logging
import threading
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import numpy as np

from sonia.vision.contracts import (
    GameReferee,
    GameVision,
    HandReading,
    JudgeAnswer,
    NoReferee,
    Overlay,
    Person,
    PoseFrame,
    VisionJudge,
)

if TYPE_CHECKING:
    from sonia.config import Settings
    from sonia.llm import LLMClient
    from sonia.types import CameraSource

__all__ = ["SendBytes", "SendJson", "build_game_vision", "unavailable_game_vision"]

logger = logging.getLogger(__name__)

#: Manda un mensaje JSON a Unity (``Hub.broadcast_json``).
SendJson = Callable[[dict[str, Any]], Awaitable[None]]

#: Manda un frame binario a Unity (``Hub.broadcast_bytes``): los ``SNCV`` de la vista en vivo.
SendBytes = Callable[[bytes], Awaitable[None]]


class NoCameraStream:
    """Sin cámara USB: nunca hay frames."""

    @property
    def active(self) -> bool:
        return False

    async def acquire(self, owner: str) -> bool:
        return False

    async def release(self, owner: str) -> None:
        return None

    def latest(self) -> tuple[float, np.ndarray] | None:
        return None


class NoPreview:
    """Sin vista en vivo."""

    @property
    def active(self) -> bool:
        return False

    async def start(
        self, owner: str, *, mirror: bool = True, overlay: Overlay | None = None
    ) -> bool:
        return False

    def set_overlay(self, overlay: Overlay | None) -> None:
        return None

    async def stop(self, owner: str) -> None:
        return None


class NoPoses:
    """Sin detector de poses."""

    @property
    def available(self) -> bool:
        return False

    async def acquire(self, owner: str, fps: float) -> bool:
        return False

    async def release(self, owner: str) -> None:
        return None

    def latest(self, max_age_s: float = 0.5) -> PoseFrame | None:
        return None

    async def detect(self, frame_bgr: np.ndarray, at: float) -> PoseFrame:
        height, width = frame_bgr.shape[:2]
        return PoseFrame(at=at, width=int(width), height=int(height), people=())


class NoHands:
    """Sin lector de manos."""

    @property
    def available(self) -> bool:
        return False

    async def read(self, frame_bgr: np.ndarray, person: Person) -> list[HandReading]:
        return []


class NoJudge:
    """Sin modelo de visión para la búsqueda relámpago."""

    @property
    def available(self) -> bool:
        return False

    async def ask(self, question: str) -> JudgeAnswer | None:
        return None


def unavailable_game_vision() -> GameVision:
    """La visión de los juegos sin nada disponible (tests, otra fuente de cámara o sin modelos)."""
    return GameVision(
        stream=NoCameraStream(),
        preview=NoPreview(),
        poses=NoPoses(),
        hands=NoHands(),
        judge=NoJudge(),
    )


def build_game_vision(
    *,
    settings: Settings,
    camera: CameraSource | None,
    send_json: SendJson,
    send_bytes: SendBytes,
    preview_supported: Callable[[], bool],
    vision_llm: LLMClient | None,
    download_models: bool = True,
) -> GameVision:
    """Monta la visión de los juegos sobre la cámara del motor.

    - ``camera``: la cámara del motor (``OpenCVCamera`` con ``VISION_SOURCE=opencv``); si es de
      otro tipo o ``None``, no hay visión de juegos.
    - ``send_json`` y ``send_bytes``: hacia Unity (``camera_preview`` y los frames ``SNCV``).
    - ``preview_supported``: ``True`` si la Unity conectada anuncia ``camera_preview`` en
      ``client_hello.features``; si no, la vista en vivo no se enciende.
    - ``vision_llm``: el cliente del modelo de visión, para :class:`VisionJudge`, o ``None``.
    - ``download_models``: si faltan los modelos de poses y manos, bajarlos en segundo plano
      (en un hilo); hasta que lleguen, esos juegos no se ofrecen. Los tests lo apagan.

    Nunca lanza: si algo falla, lo que falle queda como no disponible.
    """
    try:
        return _build(
            settings=settings,
            camera=camera,
            send_json=send_json,
            send_bytes=send_bytes,
            preview_supported=preview_supported,
            vision_llm=vision_llm,
            download_models=download_models,
        )
    except Exception:  # noqa: BLE001 - sin visión de juegos, Sonia sigue
        logger.exception("No se pudo montar la visión de los juegos: sin juegos de cámara")
        return unavailable_game_vision()


def _build(
    *,
    settings: Settings,
    camera: CameraSource | None,
    send_json: SendJson,
    send_bytes: SendBytes,
    preview_supported: Callable[[], bool],
    vision_llm: LLMClient | None,
    download_models: bool,
) -> GameVision:
    from sonia.vision.camera import OpenCVCamera

    if settings.vision.source != "opencv" or not isinstance(camera, OpenCVCamera):
        return unavailable_game_vision()
    if importlib.util.find_spec("cv2") is None:
        logger.warning("Sin OpenCV (uv sync --extra camera): no hay juegos de cámara")
        return unavailable_game_vision()

    from sonia.vision.hands import MediaPipeHandDetector
    from sonia.vision.judge import FALLBACK_TIMEOUT_S, ModelJudge
    from sonia.vision.models import (
        DEFAULT_POSE_VARIANT,
        download_game_models,
        game_models,
        games_models_dir,
        model_present,
        pose_variant,
    )
    from sonia.vision.poses import YoloPoseDetector
    from sonia.vision.referee import GeminiReferee, gemini_llm_settings
    from sonia.vision.stream import LivePreview, OpenCVCameraStream

    folder = games_models_dir(settings)
    configured = _setting(settings, ("games", "poses", "model"), DEFAULT_POSE_VARIANT)
    variant = pose_variant(configured) or DEFAULT_POSE_VARIANT
    stream = OpenCVCameraStream(camera)
    preview = LivePreview(stream, send_json, send_bytes, preview_supported)
    poses = YoloPoseDetector(stream, folder, variant=variant, download=download_models)
    hands = MediaPipeHandDetector(folder)
    luna = vision_llm if vision_llm is not None and settings.llm.supports_vision else None
    judge: VisionJudge = ModelJudge(luna, camera) if luna is not None else NoJudge()
    # El juez de las rondas (GAMES_JUDGE). Con Gemini, un solo cliente para las rondas y la
    # búsqueda (la conexión se reutiliza), con el plazo de GAMES_JUDGE_TIMEOUT_SECONDS. En la
    # búsqueda, si Gemini falla, la misma foto va al modelo de visión (luna), si lo hay: no
    # se sabe si la clave de Gemini tiene topes por minuto o por día, y los gestos ya la usan
    # todo el día. Sin Gemini, todo como antes.
    referee: GameReferee = NoReferee()
    gemini: LLMClient | None = None
    referee_name = "local"
    if settings.games.judge == "gemini":
        timeout_s = max(0.5, float(settings.games.judge_timeout_seconds))
        gemini_settings = gemini_llm_settings(settings, timeout_s)
        if gemini_settings is None:
            logger.warning(
                "GAMES_JUDGE=gemini sin Gemini (falta GEMINI_API_KEY o los gestos van por otro "
                "servidor): los juegos de cámara deciden en local"
            )
        else:
            from sonia.llm import LLMClient

            gemini = LLMClient(gemini_settings)
            referee = GeminiReferee(gemini, timeout_s=timeout_s)
            judge = ModelJudge(
                gemini,
                camera,
                timeout_s=timeout_s,
                fallback=luna,
                fallback_timeout_s=FALLBACK_TIMEOUT_S,
            )
            referee_name = f"Gemini ({gemini_settings.model}, plazo {timeout_s:g} s)"
    # Al arrancar solo se exigen el de poses de GAME_POSES_MODEL y los de manos: el otro de
    # poses (la app lleva los dos) se baja la primera vez que se pide desde el panel.
    missing = tuple(model for model in game_models(variant) if not model_present(folder, model))
    if download_models or not missing:

        def prepare() -> None:
            # Si faltan, se bajan; después se cargan y se calientan, para que la primera
            # ronda no pague la carga. Todo en este hilo, fuera del bucle de audio.
            if missing:
                try:
                    fetched = download_game_models(folder, missing)
                except Exception as exc:  # noqa: BLE001 - sin red: al volver a arrancar
                    logger.warning("No se pudieron bajar los modelos de los juegos: %s", exc)
                    return
                if fetched:
                    logger.info("Modelos de los juegos en %s: %s", folder, ", ".join(fetched))
            poses.preload()
            hands.preload()

        threading.Thread(target=prepare, name="sonia-modelos-juegos", daemon=True).start()

    async def close() -> None:
        await preview.close()
        await poses.close()
        for owner in list(stream.owners):
            await stream.release(owner)
        if gemini is not None:
            try:
                await gemini.aclose()
            except Exception:  # noqa: BLE001 - cerrar nunca tumba nada
                logger.debug("No se pudo cerrar el cliente del juez de Gemini", exc_info=True)

    logger.info(
        "Visión de los juegos: poses %s (%s), manos %s, juez de rondas %s, búsqueda %s",
        "lista" if poses.available else "sin modelo",
        variant,
        "listas" if hands.available else "sin modelo",
        referee_name,
        (
            ("con Gemini" + (" y respaldo del modelo de visión" if luna is not None else ""))
            if gemini is not None
            else "con el modelo de visión"
        )
        if judge.available
        else "sin modelo de visión",
    )
    return GameVision(
        stream=stream,
        preview=preview,
        poses=poses,
        hands=hands,
        judge=judge,
        close=close,
        referee=referee,
    )


def _setting(settings: Any, path: tuple[str, ...], default: Any) -> Any:
    """Un ajuste de los cimientos por su ruta (``settings.games.poses.model``), o ``default``."""
    value: Any = settings
    for name in path:
        value = getattr(value, name, None)
        if value is None:
            return default
    return value
