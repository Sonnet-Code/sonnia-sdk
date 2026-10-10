"""Contratos de la visión en vivo de los juegos (``docs/plan-juegos.md``, secciones 4 y 6).

Los implementa ``sonia.vision`` (``stream``, ``poses``, ``hands`` y ``judge``) y los usan
los juegos a través de ``GameHost`` (``sonia.games``). Todo corre en este equipo y en
memoria: nunca se guarda una imagen ni un dato de nadie y no se reconoce a nadie. Solo
:class:`VisionJudge` manda una foto reducida al modelo de visión, y solo en la búsqueda
relámpago.

Coordenadas normalizadas de 0 a 1 sobre la imagen de la cámara **sin espejo**: el espejo
es solo de la vista en vivo (:class:`PreviewStreamer`). Izquierda y derecha de las
personas son las suyas, no las de la imagen (orden COCO).

El trabajo de CPU (leer la cámara, detectar, codificar JPEG) va siempre en hilos: el
bucle de ``asyncio`` lleva el micrófono a GPT-Live a tiempo real y no puede esperar.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol

import numpy as np

__all__ = [
    "BODY_POINTS",
    "L_ANKLE",
    "L_EAR",
    "L_ELBOW",
    "L_EYE",
    "L_HIP",
    "L_KNEE",
    "L_SHOULDER",
    "L_WRIST",
    "NOSE",
    "R_ANKLE",
    "R_EAR",
    "R_ELBOW",
    "R_EYE",
    "R_HIP",
    "R_KNEE",
    "R_SHOULDER",
    "R_WRIST",
    "CameraStream",
    "HandDetector",
    "HandReading",
    "HandShape",
    "JudgeAnswer",
    "Overlay",
    "Person",
    "Point",
    "PoseDetector",
    "PoseFrame",
    "PreviewStreamer",
    "Side",
    "VisionJudge",
]

#: Los 17 puntos del cuerpo, en el orden COCO que dan los modelos de pose.
BODY_POINTS = (
    "nariz",
    "ojo_izquierdo",
    "ojo_derecho",
    "oreja_izquierda",
    "oreja_derecha",
    "hombro_izquierdo",
    "hombro_derecho",
    "codo_izquierdo",
    "codo_derecho",
    "muneca_izquierda",
    "muneca_derecha",
    "cadera_izquierda",
    "cadera_derecha",
    "rodilla_izquierda",
    "rodilla_derecha",
    "tobillo_izquierdo",
    "tobillo_derecho",
)

(
    NOSE,
    L_EYE,
    R_EYE,
    L_EAR,
    R_EAR,
    L_SHOULDER,
    R_SHOULDER,
    L_ELBOW,
    R_ELBOW,
    L_WRIST,
    R_WRIST,
    L_HIP,
    R_HIP,
    L_KNEE,
    R_KNEE,
    L_ANKLE,
    R_ANKLE,
) = range(len(BODY_POINTS))


@dataclass(frozen=True, slots=True)
class Point:
    """Un punto con su confianza (0 a 1). Con confianza baja, no se ha visto."""

    x: float
    y: float
    score: float


@dataclass(frozen=True, slots=True)
class Person:
    """Una persona detectada: caja ``(x, y, ancho, alto)`` y sus 17 puntos (:data:`BODY_POINTS`)."""

    box: tuple[float, float, float, float]
    score: float
    points: tuple[Point, ...]


@dataclass(frozen=True, slots=True)
class PoseFrame:
    """Las personas de un frame. ``at`` es el ``time.monotonic()`` de la captura."""

    at: float
    width: int
    height: int
    people: tuple[Person, ...]


class HandShape(StrEnum):
    """Lo que hace una mano en piedra, papel o tijera."""

    ROCK = "piedra"
    PAPER = "papel"
    SCISSORS = "tijera"
    UNKNOWN = "sin_lectura"


#: Mano izquierda o derecha de la persona (no de la imagen).
Side = Literal["izquierda", "derecha"]


@dataclass(frozen=True, slots=True)
class HandReading:
    """La lectura de una mano: forma, confianza, caja y, si los hay, sus 21 puntos."""

    side: Side
    shape: HandShape
    score: float
    box: tuple[float, float, float, float]
    points: tuple[Point, ...] = ()


@dataclass(frozen=True, slots=True)
class JudgeAnswer:
    """Respuesta del modelo de visión a una pregunta cerrada sobre una foto.

    ``what`` dice qué objeto vio, para que Sonia lo celebre («¡esa botella azul!»).
    Nunca describe a una persona.
    """

    seen: bool
    what: str = ""


#: Dibuja sobre el frame BGR de la vista en vivo, en su sitio y antes de codificarlo.
#: El segundo argumento dice si el frame ya va en espejo: entonces ``x`` se dibuja en
#: ``1 - x``.
Overlay = Callable[[np.ndarray, bool], None]


class CameraStream(Protocol):
    """Lectura continua de la cámara USB mientras algún juego la pida.

    Mientras está activa, ``OpenCVCamera.capture()`` (``look``, caras, presencia) coge
    el último frame de aquí en vez de leer el dispositivo: nunca dos lecturas a la vez.
    """

    @property
    def active(self) -> bool: ...

    async def acquire(self, owner: str) -> bool:
        """Empieza (o sigue) leyendo para ``owner``. ``False`` si no hay cámara."""
        ...

    async def release(self, owner: str) -> None:
        """``owner`` ya no la necesita; sin dueños, deja de leer y suelta el hilo."""
        ...

    def latest(self) -> tuple[float, np.ndarray] | None:
        """El último frame BGR sin espejo y su ``time.monotonic()``, o ``None``."""
        ...


class PreviewStreamer(Protocol):
    """La vista en vivo de la cámara en la pantalla de Unity (frames ``SNCV``).

    Manda ``camera_preview`` (``on``/``off``) y unos 10 frames por segundo, en espejo,
    con lo que dibuje ``overlay`` encima. Solo mientras dura el juego que la pide.
    """

    @property
    def active(self) -> bool: ...

    async def start(
        self, owner: str, *, mirror: bool = True, overlay: Overlay | None = None
    ) -> bool:
        """Enciende la vista para ``owner``. ``False`` si no hay cámara o Unity no la sabe pintar."""
        ...

    def set_overlay(self, overlay: Overlay | None) -> None:
        """Cambia lo que se dibuja encima (esqueletos, marcas, manos)."""
        ...

    async def stop(self, owner: str) -> None:
        """Apaga la vista de ``owner`` (y la retira de la pantalla si no queda nadie)."""
        ...


class PoseDetector(Protocol):
    """Personas con sus 17 puntos, en este equipo y sin guardar nada."""

    @property
    def available(self) -> bool:
        """``False`` si falta el modelo o la cámara: el juego no se ofrece."""
        ...

    async def acquire(self, owner: str, fps: float) -> bool:
        """Detecta sin parar sobre el stream, unas ``fps`` veces por segundo, para ``owner``."""
        ...

    async def release(self, owner: str) -> None: ...

    def latest(self, max_age_s: float = 0.5) -> PoseFrame | None:
        """La última detección continua si no es más vieja que ``max_age_s``."""
        ...

    async def detect(self, frame_bgr: np.ndarray, at: float) -> PoseFrame:
        """Una detección suelta sobre un frame (en un hilo)."""
        ...


class HandDetector(Protocol):
    """Las manos de una persona ya detectada, para piedra, papel o tijera."""

    @property
    def available(self) -> bool: ...

    async def read(self, frame_bgr: np.ndarray, person: Person) -> list[HandReading]:
        """Lee las manos de ``person`` en ``frame_bgr`` (en un hilo). Vacío si no ve ninguna."""
        ...


class VisionJudge(Protocol):
    """Pregunta cerrada al modelo de visión sobre una foto fresca y reducida de la cámara.

    Solo la usa la búsqueda relámpago, con un tope de llamadas por ronda. La respuesta
    llega en JSON estricto y nunca describe a las personas.
    """

    @property
    def available(self) -> bool: ...

    async def ask(self, question: str) -> JudgeAnswer | None:
        """``None`` si no hubo foto o el modelo no contestó a tiempo."""
        ...
