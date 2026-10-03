"""Motor de voz a voz con GPT-Live de OpenAI (``VOICE_ENGINE=live``, ADR 007)."""

from __future__ import annotations

from sonia.live.client import LiveClient, LiveError
from sonia.live.engine import LiveEngine
from sonia.live.oneshot import ProbeResult, probe_session, speak_text
from sonia.live.vision import VisionNarrator

__all__ = [
    "LiveClient",
    "LiveEngine",
    "LiveError",
    "ProbeResult",
    "VisionNarrator",
    "probe_session",
    "speak_text",
]
