"""El error que ve quien usa ``sonnia-video``: un mensaje claro en español, sin traza."""

from __future__ import annotations

__all__ = ["VideoError"]


class VideoError(RuntimeError):
    """Algo que impide hacer el vídeo y que se le cuenta tal cual a quien lo pidió."""
