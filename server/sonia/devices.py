"""Micrófono y cámara de este equipo, elegidos desde el menú de opciones de Unity.

Por defecto Sonia usa el micrófono y la cámara del sistema (o los de
``AUDIO_INPUT_DEVICE`` y ``VISION_CAMERA_INDEX``, si están). Desde el menú de
opciones (Esc, «Micrófono, cámara y pantalla») se pueden cambiar en marcha: la
elección se guarda en este equipo (``DEVICES_FILE``, por defecto
``cache/devices.json``) y manda sobre el ``.env``, que en la app viene del equipo
donde se compiló.

Mensajes con Unity (docs/protocolo.md): ``list_devices`` pide la lista,
``devices`` la manda y ``set_device`` cambia el micrófono o la cámara.
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
    """Lo elegido en este equipo. ``None``: no se eligió (vale el ``.env``)."""

    #: Nombre (o parte) del micrófono; ``""`` es el del sistema.
    microphone: str | None = None
    #: Índice de la cámara (OpenCV).
    camera: int | None = None


def load_choice(path: Path) -> DeviceChoice:
    """Lo guardado en ``path`` (vacío si no hay nada o no se puede leer)."""
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return DeviceChoice()
    except (OSError, ValueError) as exc:
        logger.warning("No se pudo leer %s: %s", path, exc)
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
    """Pone en ``settings`` lo elegido en este equipo, antes de abrir nada."""
    if choice.microphone is not None:
        settings.audio.input_device = choice.microphone
        logger.info("Micrófono elegido en este equipo: %s", choice.microphone or "el del sistema")
    if choice.camera is not None:
        settings.vision.camera_index = max(0, choice.camera)
        logger.info("Cámara elegida en este equipo: %d", choice.camera)


class DeviceManager:
    """Atiende el menú de opciones de Unity: lista los dispositivos y aplica la elección."""

    def __init__(self, settings: Settings, hub: Any, *, camera: Any = None) -> None:
        self._settings = settings
        self._hub = hub
        self._camera = camera
        self._path = Path(settings.devices_file)
        self._choice = load_choice(self._path)
        #: Se pone cuando hay que reabrir el micrófono con otro dispositivo.
        self.mic_changed = asyncio.Event()
        self._tasks: set[asyncio.Task[None]] = set()
        hub.on(p.MSG_LIST_DEVICES, lambda msg: self._spawn(self.send_devices()))
        hub.on(p.MSG_SET_DEVICE, lambda msg: self._spawn(self.on_set_device(msg)))

    def _spawn(self, coro: Any) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def send_devices(self) -> None:
        """Manda a Unity los micrófonos de este equipo y lo que está elegido."""
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
            logger.warning("set_device no válido: %r", msg)

    async def set_microphone(self, name: str) -> None:
        """Cambia de micrófono (``""``: el del sistema) y lo reabre ya."""
        name = name.strip()
        self._settings.audio.input_device = name
        self._choice.microphone = name
        await asyncio.to_thread(_save_choice, self._path, self._choice)
        self.mic_changed.set()
        logger.info("Micrófono cambiado desde el menú: %s", name or "el del sistema")
        await self.send_devices()

    async def set_camera(self, index: int) -> None:
        """Cambia de cámara: la siguiente foto ya sale de la nueva."""
        index = max(0, index)
        set_index = getattr(self._camera, "set_index", None)
        if set_index is not None:
            await set_index(index)
        self._settings.vision.camera_index = index
        self._choice.camera = index
        await asyncio.to_thread(_save_choice, self._path, self._choice)
        logger.info("Cámara cambiada desde el menú: %d", index)
        await self.send_devices()
