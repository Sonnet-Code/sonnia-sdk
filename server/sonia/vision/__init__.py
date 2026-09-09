"""Capa de visión: captura puntual de cámara y política de cuándo mirar."""

from __future__ import annotations

from sonia.vision.camera import (
    NullCamera,
    OpenCVCamera,
    UnityCamera,
    build_camera,
    encode_frame,
)
from sonia.vision.policy import VisionPolicy

__all__ = [
    "NullCamera",
    "OpenCVCamera",
    "UnityCamera",
    "VisionPolicy",
    "build_camera",
    "encode_frame",
]
