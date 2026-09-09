"""Construcción del motor de TTS a partir de la configuración."""

from __future__ import annotations

from typing import Any

from ..config import TTSSettings
from ..types import TextToSpeech

__all__ = ["build_tts"]


def _as_tts_settings(settings: Any) -> TTSSettings:
    """Acepta tanto un ``Settings`` completo como su sección ``tts``."""
    inner = getattr(settings, "tts", None)
    return inner if isinstance(inner, TTSSettings) else settings


def build_tts(settings: Any) -> TextToSpeech:
    """Devuelve el motor indicado por ``TTS_BACKEND``.

    Los backends se importan aquí dentro para que ``import sonia.tts`` no
    arrastre torch ni httpx si no hacen falta.
    """
    tts_settings = _as_tts_settings(settings)
    backend = tts_settings.backend

    if backend == "mock":
        from .mock import MockTTS

        return MockTTS(sample_rate=tts_settings.sample_rate)
    if backend == "http":
        from .http import HTTPTTS

        return HTTPTTS(tts_settings)
    if backend == "omnivoice":
        from .omnivoice import OmniVoiceTTS

        return OmniVoiceTTS(tts_settings)
    if backend == "system":
        from .system import SystemTTS

        return SystemTTS(tts_settings)
    if backend == "gemini":
        # Provisional mientras no hay GPU para OmniVoice. Lee TTS_GEMINI_*.
        from .gemini import build_gemini_tts

        return build_gemini_tts()

    raise ValueError(f"backend de TTS desconocido: {backend!r}")
