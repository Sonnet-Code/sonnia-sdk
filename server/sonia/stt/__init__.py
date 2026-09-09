"""Etapa de reconocimiento de voz."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sonia.stt.base import SpeechToText
from sonia.stt.faster_whisper import FasterWhisperSTT
from sonia.stt.mock import MockSTT

if TYPE_CHECKING:
    from sonia.config import STTSettings

__all__ = ["FasterWhisperSTT", "MockSTT", "SpeechToText", "build_stt"]


def build_stt(settings: Any) -> SpeechToText:
    """Construye el motor de STT según `STT_BACKEND`.

    Acepta un `STTSettings` o el `Settings` completo (usa su campo ``stt``).
    """
    stt_settings: STTSettings = getattr(settings, "stt", settings)
    backend = getattr(stt_settings, "backend", "faster_whisper")
    if backend == "mock":
        return MockSTT()
    if backend == "faster_whisper":
        return FasterWhisperSTT(stt_settings)
    raise ValueError(f"Backend de STT desconocido: {backend!r}")
