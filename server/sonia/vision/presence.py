"""¿Hay alguien delante del stand? Lo que ve la cámara para la puerta del micro.

OpenCV (YuNet) busca caras en la cámara cada ``LIVE_PRESENCE_SCAN_SECONDS``, en
este equipo y en memoria: no se guarda ninguna foto ni se reconoce a nadie (eso
es ``sonia.faces``, que baja el modelo). Lo que ve entra en la puerta del micro
de GPT-Live (:class:`sonia.live.audio.MicGate`) junto con la puerta de ruido y el
ruido suave: con alguien delante ahora mismo, la puerta de ruido deja pasar
voces más bajas; sin ninguna cara cerca ni conversación en
``LIVE_PRESENCE_HOLD_SECONDS`` (diez minutos), GPT-Live deja de oír el micro
hasta que llega alguien.

La espera es muy generosa a propósito: dejar sorda a Sonia con alguien delante
es mucho peor que oír el pasillo un rato. Por eso la conversación cuenta como
presencia, y la cámara no cuenta (GPT-Live oye) mientras está apagada, hasta
que ve su primera cara (si apunta mal, nunca cierra) y si deja de dar imagen.

`cv2` se importa de forma perezosa, como en ``sonia.vision.camera``.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

import numpy as np

from sonia.types import Frame

if TYPE_CHECKING:
    from sonia.config import LiveSettings

__all__ = ["SCAN_WIDTH", "PresenceGate", "PresenceWatch", "YuNetFaces"]

logger = logging.getLogger(__name__)

#: Ancho de la foto que se analiza (``LIVE_PRESENCE_MIN_FACE_PX`` va en esta escala).
SCAN_WIDTH = 640
SCAN_QUALITY = 70
#: Tope de una captura para la revisión.
SCAN_TIMEOUT_S = 3.0
#: Sin una revisión con imagen en este tiempo, la cámara no cuenta: micro abierto.
STALE_AFTER_S = 5.0
#: Una cara en estos últimos segundos es «alguien delante ahora mismo».
NEAR_S = 10.0
#: Revisiones seguidas sin imagen antes de avisar en el log.
BLIND_WARN_SCANS = 10
#: Cada cuánto se vuelve a buscar el modelo si falta (la primera vez que arranca
#: lo está bajando el reconocimiento de caras).
MODEL_RETRY_S = 30.0
#: Con el micro cerrado, cada cuánto se recuerda en el log que nadie se pone delante.
CLOSED_REMINDER_S = 30 * 60.0
#: Confianza mínima de YuNet. Más baja que la del reconocimiento (0,8): aquí
#: sobra una cara de más (oye el pasillo un rato) y falta una de menos (sorda).
YUNET_SCORE = 0.7

Status = Literal["apagada", "sin imagen", "sin caras aún", "alguien", "hace poco", "nadie"]


class SizedCamera(Protocol):
    """Una cámara a la que se le puede pedir una foto más pequeña (``OpenCVCamera``)."""

    async def capture(
        self, *, max_width: int | None = None, quality: int | None = None
    ) -> Frame | None: ...


class FaceCounter(Protocol):
    """Cuenta las caras de una foto (los tests ponen uno falso)."""

    def count(self, data: bytes, min_width: int) -> int: ...


class YuNetFaces:
    """Caras con YuNet, el detector de OpenCV (OpenCV 5 ya no trae los Haar).

    ``count`` hace milisegundos de CPU: se llama desde un hilo, nunca desde el
    bucle de audio. Los objetos de OpenCV no son seguros entre hilos: va con candado.
    """

    def __init__(self, model: Path) -> None:
        import cv2

        if not hasattr(cv2, "FaceDetectorYN"):
            raise RuntimeError(f"este OpenCV ({cv2.__version__}) no trae YuNet")
        self._cv2 = cv2
        self._lock = threading.Lock()
        self._detector: Any = cv2.FaceDetectorYN.create(
            str(model), "", (320, 320), YUNET_SCORE, 0.3, 50
        )

    def count(self, data: bytes, min_width: int) -> int:
        """Caras de al menos ``min_width`` px (en la escala de :data:`SCAN_WIDTH`)."""
        cv2 = self._cv2
        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return 0
        height, width = image.shape[:2]
        limit = min_width * width / SCAN_WIDTH
        with self._lock:
            self._detector.setInputSize((width, height))
            _, found = self._detector.detect(image)
        if found is None:
            return 0
        return sum(1 for row in found if float(row[2]) >= limit)


class PresenceGate:
    """Lo que la puerta del micro sabe de quién hay delante: abre al momento, cierra muy despacio."""

    def __init__(
        self,
        hold_s: float,
        *,
        enabled: bool = True,
        near_s: float = NEAR_S,
        stale_s: float = STALE_AFTER_S,
    ) -> None:
        #: El interruptor del panel: apagada, GPT-Live oye como si no existiera.
        self.enabled = enabled
        self.hold_s = max(0.0, hold_s)
        self._near_s = near_s
        self._stale_s = stale_s
        #: Última cara cerca, última conversación y última revisión con imagen (monotonic).
        self._last_face: float | None = None
        self._last_busy: float | None = None
        self._last_scan: float | None = None

    def scanned(self, faces: int, now: float) -> None:
        """Una revisión con imagen y las caras cerca que salieron."""
        self._last_scan = now
        if faces > 0:
            self._last_face = now

    def busy(self, now: float) -> None:
        """Sonia escucha, piensa o habla: cuenta como si hubiera alguien delante."""
        self._last_busy = now

    def sees(self, now: float) -> bool:
        """¿Hay una revisión con imagen reciente?"""
        return self._last_scan is not None and now - self._last_scan <= self._stale_s

    @property
    def trusted(self) -> bool:
        """¿Ha visto ya alguna cara? Hasta entonces no se fía (puede apuntar mal)."""
        return self._last_face is not None

    def counts(self, now: float) -> bool:
        """¿Decide ahora la cámara? Si no, GPT-Live oye."""
        return self.enabled and self.trusted and self.sees(now)

    def idle_s(self, now: float) -> float | None:
        """Segundos desde la última cara cerca o la última conversación."""
        times = [t for t in (self._last_face, self._last_busy) if t is not None]
        return now - max(times) if times else None

    def near(self, now: float) -> bool:
        """¿Hay alguien delante ahora mismo?"""
        face = self._last_face
        return self.counts(now) and face is not None and now - face <= self._near_s

    def admits(self, now: float) -> bool:
        """¿Puede oír GPT-Live el micro?"""
        if not self.counts(now):
            return True
        idle = self.idle_s(now)
        return idle is not None and idle <= self.hold_s

    def status(self, now: float) -> Status:
        if not self.enabled:
            return "apagada"
        if not self.sees(now):
            return "sin imagen"
        if not self.trusted:
            return "sin caras aún"
        if self.near(now):
            return "alguien"
        return "hace poco" if self.admits(now) else "nadie"


class PresenceWatch:
    """Revisa la cámara con sesión abierta y lleva la :class:`PresenceGate`."""

    def __init__(
        self,
        settings: LiveSettings,
        camera: SizedCamera,
        *,
        model: Path,
        counter_factory: Callable[[Path], FaceCounter] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.gate = PresenceGate(settings.presence_hold_seconds, enabled=settings.presence_gate)
        self.scan_seconds = max(0.1, settings.presence_scan_seconds)
        self._min_face_px = max(1, settings.presence_min_face_px)
        self._near_scale = min(1.0, max(0.0, settings.presence_near_gate_scale))
        self._model = model
        self._camera = camera
        self._factory: Callable[[Path], FaceCounter] = counter_factory or YuNetFaces
        self._counter: FaceCounter | None = None
        self._clock = clock
        self._misses = 0
        self._warned_model = False
        #: ¿Está mirando la cámara ahora? (sesión abierta y encendida)
        self.watching = False

    def snapshot(self, now: float | None = None) -> dict[str, Any]:
        """Para el panel: si está encendida, qué ve y cuánto lleva sin nadie."""
        now = self._clock() if now is None else now
        idle = self.gate.idle_s(now)
        return {
            "enabled": self.gate.enabled,
            "ready": self._counter is not None,
            "watching": self.watching,
            "status": self.gate.status(now),
            "idle_s": round(idle, 1) if idle is not None else None,
            "hold_s": self.gate.hold_s,
            "near_gate_scale": self._near_scale,
        }

    async def prepare(self) -> bool:
        """Carga el detector. Sin él, GPT-Live oye (y se vuelve a intentar)."""
        if self._counter is not None:
            return True
        try:
            if not await asyncio.to_thread(self._model.is_file):
                raise FileNotFoundError(f"falta {self._model} (lo baja `sonia caras`)")
            self._counter = await asyncio.to_thread(self._factory, self._model)
        except Exception as exc:  # noqa: BLE001 - sin detector, Sonia sigue oyendo
            if not self._warned_model:
                self._warned_model = True
                logger.warning(
                    "Sin detector de caras (%s): GPT-Live oye el micro sin mirar si hay "
                    "alguien delante",
                    exc,
                )
            return False
        logger.info(
            "Puerta del micro con la cámara lista: sin nadie delante ni conversación en "
            "%.0f min, GPT-Live deja de oír el micro",
            self.gate.hold_s / 60,
        )
        return True

    async def scan(self) -> int | None:
        """Una revisión: cuántas caras cerca hay, o ``None`` si la cámara no dio imagen."""
        counter = self._counter
        if counter is None:
            return None
        try:
            frame = await asyncio.wait_for(
                self._camera.capture(max_width=SCAN_WIDTH, quality=SCAN_QUALITY),
                timeout=SCAN_TIMEOUT_S,
            )
        except TimeoutError:
            frame = None
        if frame is None:
            self._misses += 1
            if self._misses == BLIND_WARN_SCANS:
                logger.warning(
                    "La cámara no da imagen: GPT-Live oye el micro sin mirar si hay alguien delante"
                )
            return None
        if self._misses >= BLIND_WARN_SCANS:
            logger.info("La cámara vuelve a dar imagen")
        self._misses = 0
        faces = await asyncio.to_thread(counter.count, frame.data, self._min_face_px)
        self.gate.scanned(faces, self._clock())
        return faces

    async def run(self, *, active: Callable[[], bool], busy: Callable[[], bool]) -> None:
        """Revisa cada ``scan_seconds`` mientras ``active()`` (hay sesión) y está encendida.

        ``busy()`` dice si hay conversación: cuenta como presencia. El detector se
        carga la primera vez que se enciende.
        """
        gate = self.gate
        last: Status | None = None
        reminded = 0.0
        retry_at = 0.0
        while True:
            await asyncio.sleep(self.scan_seconds)
            self.watching = active() and gate.enabled
            if not self.watching:
                # Apagada o sin sesión no se mira; al volver, GPT-Live oye hasta la
                # primera revisión.
                last = None
                continue
            if self._counter is None:
                # Mientras falte el modelo (puede estar bajándolo el reconocimiento
                # de caras), GPT-Live oye; se vuelve a buscar cada MODEL_RETRY_S.
                if self._clock() < retry_at:
                    continue
                if not await self.prepare():
                    retry_at = self._clock() + MODEL_RETRY_S
                    continue
            if busy():
                gate.busy(self._clock())
            try:
                await self.scan()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - una revisión fallida no para las demás
                logger.debug("Revisión de presencia fallida: %s", exc)
            now = self._clock()
            status = gate.status(now)
            if status != last:
                self._log_change(last, status)
                last = status
                reminded = now
            elif status == "nadie" and now - reminded >= CLOSED_REMINDER_S:
                reminded = now
                idle = gate.idle_s(now) or 0.0
                logger.warning(
                    "Nadie delante desde hace %.0f min y GPT-Live no oye el micro: si hay gente "
                    "en el stand, revisa que la cámara apunte a los visitantes o apaga «Oír solo "
                    "con alguien delante» en el panel",
                    idle / 60,
                )

    def _log_change(self, before: Status | None, now: Status) -> None:
        hold_min = self.gate.hold_s / 60
        if now == "nadie":
            logger.info(
                "Nadie delante ni conversación en %.0f min: GPT-Live deja de oír el micro",
                hold_min,
            )
        elif before == "nadie":
            logger.info("Alguien delante: GPT-Live vuelve a oír el micro")
        elif now == "sin caras aún" and before is None:
            logger.info(
                "La cámara aún no ha visto ninguna cara: GPT-Live oye el micro hasta que la vea"
            )
        elif now in ("alguien", "hace poco") and before == "sin caras aún":
            logger.info(
                "La cámara ya ve caras: GPT-Live dejará de oír el micro tras %.0f min sin "
                "nadie delante ni conversación",
                hold_min,
            )
