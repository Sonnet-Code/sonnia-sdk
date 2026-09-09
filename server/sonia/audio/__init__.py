"""Entrada de audio: captura de micrófono y detección de voz y de turnos."""

from __future__ import annotations

from sonia.audio.capture import (
    MicCapture,
    MicStalled,
    list_input_devices,
    resolve_input_device,
)
from sonia.audio.vad import (
    VAD_WINDOW,
    BargeIn,
    SpeechDiscarded,
    SpeechStarted,
    TurnDetector,
    TurnEvent,
    VadLike,
    VoiceActivityDetector,
    resample_to_16k,
)

__all__ = [
    "VAD_WINDOW",
    "MicCapture",
    "MicStalled",
    "BargeIn",
    "SpeechDiscarded",
    "SpeechStarted",
    "TurnDetector",
    "TurnEvent",
    "VadLike",
    "VoiceActivityDetector",
    "list_input_devices",
    "resample_to_16k",
    "resolve_input_device",
]
