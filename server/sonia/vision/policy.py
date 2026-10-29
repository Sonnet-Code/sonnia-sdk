"""Vision policy: when a snapshot is attached to the turn.

No capture on every frame and no video is sent to the model. Only:
- when a turn starts, if ``VISION_ON_TURN_START``;
- every ``VISION_INTERVAL_SECONDS`` while there is activity, if greater than zero.

If the configured model does not support images, everything is disabled.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from sonia.types import Frame

if TYPE_CHECKING:
    from sonia.config import VisionSettings

logger = logging.getLogger(__name__)

_EXTENSION_BY_MIME = {"image/jpeg": "jpg", "image/png": "png"}


class VisionPolicy:
    """Decides whether it is time to capture, and saves frames to disk only in debug mode."""

    def __init__(self, settings: VisionSettings, supports_vision: bool) -> None:
        self._settings = settings
        self._supports_vision = supports_vision
        self._last_capture: float | None = None

    @property
    def enabled(self) -> bool:
        """Vision is active if the model supports it and there is a source."""
        return self._supports_vision and self._settings.source != "none"

    def should_capture_on_turn_start(self) -> bool:
        """Is a snapshot attached when the user starts speaking?"""
        if not self.enabled:
            return False
        return self._settings.on_turn_start

    def should_capture_periodic(self, now: float | None = None) -> bool:
        """Has the interval elapsed since the last capture?"""
        if not self.enabled:
            return False
        interval = self._settings.interval_seconds
        if interval <= 0:
            return False
        now = time.monotonic() if now is None else now
        if self._last_capture is None:
            return True
        return (now - self._last_capture) >= interval

    def note_captured(self, now: float | None = None) -> None:
        """Records the time of the last capture."""
        self._last_capture = time.monotonic() if now is None else now

    def maybe_save_debug(self, frame: Frame | None) -> Path | None:
        """Saves the frame to ``debug_dir`` only if ``debug_save_frames``.

        Outside debug mode no snapshot is ever persisted: the camera sees real
        people in public. Returns the written path, or ``None``.
        """
        if frame is None or not self.enabled or not self._settings.debug_save_frames:
            return None

        directory = Path(self._settings.debug_dir)
        extension = _EXTENSION_BY_MIME.get(frame.mime, "jpg")
        name = (
            f"frame-{time.strftime('%Y%m%d-%H%M%S')}-{time.monotonic_ns() % 1_000_000}.{extension}"
        )
        path = directory / name
        try:
            directory.mkdir(parents=True, exist_ok=True)
            path.write_bytes(frame.data)
        except OSError:
            logger.exception("Could not save the debug frame to %s", path)
            return None
        logger.debug("Debug frame saved to %s", path)
        return path
