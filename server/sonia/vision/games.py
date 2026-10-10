"""Monta la visión en vivo de los juegos (``docs/plan-juegos.md``, sección 6).

Es la costura entre los cimientos de los juegos (``sonia.games``, que llaman a
:func:`build_game_vision` al arrancar el motor) y la visión de verdad (``stream``, ``poses``,
``hands`` y ``judge``, del agente de visión, que rellena este archivo). Sin cámara USB
(``VISION_SOURCE`` distinto de ``opencv``) o mientras no haya visión de verdad, todo dice que no
está disponible y los juegos de cámara no se ofrecen.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import numpy as np

from sonia.vision.contracts import (
    GameVision,
    HandReading,
    JudgeAnswer,
    Overlay,
    Person,
    PoseFrame,
)

if TYPE_CHECKING:
    from sonia.config import Settings
    from sonia.llm import LLMClient
    from sonia.types import CameraSource

__all__ = ["SendBytes", "SendJson", "build_game_vision", "unavailable_game_vision"]

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
) -> GameVision:
    """Monta la visión de los juegos sobre la cámara del motor.

    - ``camera``: la cámara del motor (``OpenCVCamera`` con ``VISION_SOURCE=opencv``); si es de
      otro tipo o ``None``, no hay visión de juegos.
    - ``send_json`` y ``send_bytes``: hacia Unity (``camera_preview`` y los frames ``SNCV``).
    - ``preview_supported``: ``True`` si la Unity conectada anuncia ``camera_preview`` en
      ``client_hello.features``; si no, la vista en vivo no se enciende.
    - ``vision_llm``: el cliente del modelo de visión, para :class:`VisionJudge`, o ``None``.

    Nunca lanza: si algo falla, lo que falle queda como no disponible.
    """
    del settings, camera, send_json, send_bytes, preview_supported, vision_llm
    return unavailable_game_vision()
