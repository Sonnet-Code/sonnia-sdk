"""Microphone and camera chosen from the Unity options menu (``sonia/devices.py``)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from sonia import devices as devices_module
from sonia.config import AudioSettings, Settings, VisionSettings
from sonia.devices import DeviceChoice, DeviceManager, apply_choice, load_choice
from sonia.ws import protocol as p


class FakeHub:
    def __init__(self) -> None:
        self.callbacks: dict[str, Any] = {}
        self.sent: list[dict[str, Any]] = []

    def on(self, kind: str, callback: Any) -> None:
        self.callbacks[kind] = callback

    async def broadcast_json(self, msg: dict[str, Any]) -> None:
        self.sent.append(msg)


class FakeCamera:
    def __init__(self) -> None:
        self.indexes: list[int] = []

    async def set_index(self, index: int) -> None:
        self.indexes.append(index)


def make_settings(tmp_path: Path, **audio: Any) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        audio=AudioSettings(**audio),
        vision=VisionSettings(source="opencv"),
        devices_file=str(tmp_path / "devices.json"),
    )


@pytest.fixture
def fake_audio(monkeypatch: pytest.MonkeyPatch) -> None:
    import sonia.audio.capture as capture

    monkeypatch.setattr(
        capture,
        "list_input_devices",
        lambda: [
            {"index": 0, "name": "MacBook Pro Microphone", "default": True},
            {"index": 3, "name": "Condenser USB", "default": False},
        ],
    )
    monkeypatch.setattr(capture, "default_input_name", lambda: "MacBook Pro Microphone")


def test_choice_made_on_this_machine_takes_precedence_over_env(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, input_device="condenser")
    assert load_choice(Path(settings.devices_file)) == DeviceChoice()
    apply_choice(settings, DeviceChoice())
    assert settings.audio.input_device == "condenser"  # no choice: the .env
    (tmp_path / "devices.json").write_text(json.dumps({"microphone": "", "camera": 1}))
    apply_choice(settings, load_choice(Path(settings.devices_file)))
    assert settings.audio.input_device == ""  # the system one
    assert settings.vision.camera_index == 1
    (tmp_path / "devices.json").write_text("{broken")
    assert load_choice(Path(settings.devices_file)) == DeviceChoice()


async def test_menu_lists_and_switches_mic_and_camera(tmp_path: Path, fake_audio: None) -> None:
    settings = make_settings(tmp_path, input_device="condenser")
    hub, camera = FakeHub(), FakeCamera()
    manager = DeviceManager(settings, hub, camera=camera)

    hub.callbacks[p.MSG_LIST_DEVICES]({"type": "list_devices"})
    await asyncio.sleep(0.05)
    devices = hub.sent[-1]
    assert devices["type"] == "devices"
    assert devices["microphones"] == [
        {"name": "MacBook Pro Microphone", "default": True},
        {"name": "Condenser USB", "default": False},
    ]
    assert devices["microphone"] == "condenser"
    assert devices["default_microphone"] == "MacBook Pro Microphone"
    assert devices["camera"] == 0 and devices["camera_source"] == "opencv"

    hub.callbacks[p.MSG_SET_DEVICE]({"type": "set_device", "kind": "microphone", "value": ""})
    await asyncio.sleep(0.05)
    assert settings.audio.input_device == "" and manager.mic_changed.is_set()
    hub.callbacks[p.MSG_SET_DEVICE]({"type": "set_device", "kind": "camera", "value": 2})
    await asyncio.sleep(0.05)
    assert camera.indexes == [2]
    assert json.loads((tmp_path / "devices.json").read_text()) == {"microphone": "", "camera": 2}
    assert hub.sent[-1]["camera"] == 2

    # Odd input breaks nothing.
    hub.callbacks[p.MSG_SET_DEVICE]({"type": "set_device", "kind": "camera", "value": "x"})
    await asyncio.sleep(0.05)
    assert camera.indexes == [2]
    assert devices_module.load_choice(tmp_path / "devices.json").camera == 2
