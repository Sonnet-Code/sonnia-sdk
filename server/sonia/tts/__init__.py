"""Síntesis de voz: interfaz común, motores y utilidades de audio.

Importar este paquete no carga torch ni omnivoice: las dependencias pesadas se
importan dentro de los métodos que las necesitan.
"""

from __future__ import annotations

from ..types import TextToSpeech
from .base import (
    TTSError,
    chunk_pcm,
    float_to_pcm16,
    pcm16_to_float,
    resample,
    resample_pcm,
    wav_to_pcm,
)
from .factory import build_tts
from .gemini import GeminiTTS, GeminiTTSSettings
from .http import HTTPTTS
from .mock import MockTTS
from .omnivoice import OmniVoiceTTS
from .system import SystemTTS

__all__ = [
    "GeminiTTS",
    "GeminiTTSSettings",
    "HTTPTTS",
    "MockTTS",
    "OmniVoiceTTS",
    "SystemTTS",
    "TTSError",
    "TextToSpeech",
    "build_tts",
    "chunk_pcm",
    "float_to_pcm16",
    "pcm16_to_float",
    "resample",
    "resample_pcm",
    "wav_to_pcm",
]
