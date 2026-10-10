"""Ajustes comunes a todos los tests: nada de red ni de tocar la caché del equipo."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _agenda_sin_red(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """La agenda nunca se baja de la web ni escribe en ``cache/`` en un test."""
    monkeypatch.setenv("AGENDA_URL", "off")
    monkeypatch.setenv("AGENDA_CACHE_FILE", str(tmp_path / "agenda-cache.json"))


@pytest.fixture(autouse=True)
def _dispositivos_aparte(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """La elección de micrófono y cámara de un test no toca la del equipo."""
    monkeypatch.setenv("DEVICES_FILE", str(tmp_path / "devices.json"))


@pytest.fixture(autouse=True)
def _subidas_de_galeria_aparte(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Las imágenes que un test sube a la galería no van a ``cache/gallery`` del equipo."""
    monkeypatch.setenv("GALLERY_UPLOAD_DIR", str(tmp_path / "gallery-uploads"))
