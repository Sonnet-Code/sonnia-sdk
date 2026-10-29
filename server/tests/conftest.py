"""Settings common to all tests: no network and no touching the machine's cache."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _separate_devices(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A test's microphone and camera choice does not touch the machine's."""
    monkeypatch.setenv("DEVICES_FILE", str(tmp_path / "devices.json"))


@pytest.fixture(autouse=True)
def _separate_gallery_uploads(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Images a test uploads to the gallery do not go to the machine's ``cache/gallery``."""
    monkeypatch.setenv("GALLERY_UPLOAD_DIR", str(tmp_path / "gallery-uploads"))
