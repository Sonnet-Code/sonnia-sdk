"""Microphone and camera of this machine, chosen from the Unity options menu.

By default Sonnia uses the system microphone and camera (or the ones in
``AUDIO_INPUT_DEVICE`` and ``VISION_CAMERA_INDEX``, if set). They can be changed
on the fly from the options menu (Esc): the choice is saved on this machine
(``DEVICES_FILE``, ``cache/devices.json`` by default) and takes precedence over
the ``.env``, which inside the packaged app comes from the machine it was built on.

Messages with Unity (docs/protocol.md): ``list_devices`` asks for the list,
``devices`` sends it and ``set_device`` changes the microphone or the camera.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sonia.config import Settings
from sonia.ws import protocol as p

__all__ = ["DeviceChoice", "DeviceManager", "apply_choice", "load_choice"]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DeviceChoice:
    """What was chosen on this machine. ``None``: nothing chosen (the ``.env`` applies)."""

    #: Name (or part of it) of the microphone; ``""`` is the system one.
    microphone: str | None = None
    #: Camera index (OpenCV).
    camera: int | None = None


def load_choice(path: Path) -> DeviceChoice:
    """What is saved in ``path`` (empty if there is nothing or it cannot be read)."""
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return DeviceChoice()
    except (OSError, ValueError) as exc:
        logger.warning("Could not read %s: %s", path, exc)
        return DeviceChoice()
    if not isinstance(data, dict):
        return DeviceChoice()
    microphone = data.get("microphone")
    camera = data.get("camera")
    return DeviceChoice(
        microphone=microphone if isinstance(microphone, str) else None,
        camera=camera if isinstance(camera, int) and not isinstance(camera, bool) else None,
    )


def _save_choice(path: Path, choice: DeviceChoice) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps({"microphone": choice.microphone, "camera": choice.camera}, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def apply_choice(settings: Settings, choice: DeviceChoice) -> None:
    """Applies the choice made on this machine to ``settings``, before opening anything."""
    if choice.microphone is not None:
        settings.audio.input_device = choice.microphone
        logger.info("Microphone chosen on this machine: %s", choice.microphone or "system default")
    if choice.camera is not None:
        settings.vision.camera_index = max(0, choice.camera)
        logger.info("Camera chosen on this machine: %d", choice.camera)


class DeviceManager:
    """Serves the Unity options menu: lists the devices and applies the choice."""

    def __init__(self, settings: Settings, hub: Any, *, camera: Any = None) -> None:
        self._settings = settings
        self._hub = hub
        self._camera = camera
        self._path = Path(settings.devices_file)
        self._choice = load_choice(self._path)
        #: Set when the microphone has to be reopened with another device.
        self.mic_changed = asyncio.Event()
        self._tasks: set[asyncio.Task[None]] = set()
        hub.on(p.MSG_LIST_DEVICES, lambda msg: self._spawn(self.send_devices()))
        hub.on(p.MSG_SET_DEVICE, lambda msg: self._spawn(self.on_set_device(msg)))

    def _spawn(self, coro: Any) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def send_devices(self) -> None:
        """Sends Unity the microphones of this machine and the current choice."""
        from sonia.audio.capture import default_input_name, list_input_devices

        def collect() -> tuple[list[dict[str, Any]], str]:
            return list_input_devices(), default_input_name()

        devices, default_name = await asyncio.to_thread(collect)
        microphones = [
            {"name": str(d["name"]), "default": bool(d.get("default")) or d["name"] == default_name}
            for d in devices
        ]
        await self._hub.broadcast_json(
            p.msg_devices(
                microphones=microphones,
                microphone=self._settings.audio.input_device,
                default_microphone=default_name,
                camera=self._settings.vision.camera_index,
                camera_source=self._settings.vision.source,
            )
        )

    async def on_set_device(self, msg: dict[str, Any]) -> None:
        kind = msg.get("kind")
        value = msg.get("value")
        if kind == "microphone" and isinstance(value, str):
            await self.set_microphone(value)
        elif kind == "camera" and isinstance(value, int) and not isinstance(value, bool):
            await self.set_camera(value)
        else:
            logger.warning("Invalid set_device: %r", msg)

    async def set_microphone(self, name: str) -> None:
        """Switches microphone (``""``: the system one) and reopens it right away."""
        name = name.strip()
        self._settings.audio.input_device = name
        self._choice.microphone = name
        await asyncio.to_thread(_save_choice, self._path, self._choice)
        self.mic_changed.set()
        logger.info("Microphone changed from the menu: %s", name or "system default")
        await self.send_devices()

    async def set_camera(self, index: int) -> None:
        """Switches camera: the next photo already comes from the new one."""
        index = max(0, index)
        set_index = getattr(self._camera, "set_index", None)
        if set_index is not None:
            await set_index(index)
        self._settings.vision.camera_index = index
        self._choice.camera = index
        await asyncio.to_thread(_save_choice, self._path, self._choice)
        logger.info("Camera changed from the menu: %d", index)
        await self.send_devices()
