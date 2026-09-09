"""Interfaz de reconocimiento de voz.

El contrato vive en ``sonia.types``; aquí solo se reexporta para que los
módulos de esta etapa importen desde ``sonia.stt.base``.
"""

from __future__ import annotations

from sonia.types import INPUT_SAMPLE_RATE, AudioArray, SpeechToText, Utterance

__all__ = ["INPUT_SAMPLE_RATE", "AudioArray", "SpeechToText", "Utterance"]
