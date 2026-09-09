"""Política de visión: cuándo se adjunta una captura al turno.

No se captura en cada frame ni se manda vídeo al modelo. Solo:
- al empezar un turno, si ``VISION_ON_TURN_START``;
- cada ``VISION_INTERVAL_SECONDS`` mientras hay actividad, si es mayor que cero.

Si el modelo configurado no soporta imágenes, todo queda desactivado.
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
    """Decide si toca capturar, y guarda frames en disco solo en modo debug."""

    def __init__(self, settings: VisionSettings, supports_vision: bool) -> None:
        self._settings = settings
        self._supports_vision = supports_vision
        self._last_capture: float | None = None

    @property
    def enabled(self) -> bool:
        """La visión está activa si el modelo la soporta y hay una fuente."""
        return self._supports_vision and self._settings.source != "none"

    def should_capture_on_turn_start(self) -> bool:
        """¿Se adjunta una captura cuando el usuario empieza a hablar?"""
        if not self.enabled:
            return False
        return self._settings.on_turn_start

    def should_capture_periodic(self, now: float | None = None) -> bool:
        """¿Ha pasado el intervalo desde la última captura?"""
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
        """Registra el instante de la última captura."""
        self._last_capture = time.monotonic() if now is None else now

    def maybe_save_debug(self, frame: Frame | None) -> Path | None:
        """Guarda el frame en ``debug_dir`` solo si ``debug_save_frames``.

        Fuera del modo debug no se persiste ninguna captura: es una demo
        pública con visitantes reales. Devuelve la ruta escrita, o ``None``.
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
            logger.exception("No se pudo guardar el frame de depuración en %s", path)
            return None
        logger.debug("Frame de depuración guardado en %s", path)
        return path
