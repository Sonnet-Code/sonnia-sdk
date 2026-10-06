"""Capa de visión: captura puntual de cámara y política de cuándo mirar."""

from __future__ import annotations

from sonia.vision.camera import (
    NullCamera,
    ObsCamera,
    OpenCVCamera,
    ScreenCamera,
    UnityCamera,
    build_camera,
    encode_frame,
)
from sonia.vision.policy import VisionPolicy

__all__ = [
    "NullCamera",
    "ObsCamera",
    "OpenCVCamera",
    "ScreenCamera",
    "UnityCamera",
    "VisionPolicy",
    "build_camera",
    "encode_frame",
]
