"""OBS por obs-websocket 5: los ojos de Sonia en el modo reunión (docs/reunion.md).

En una videollamada OBS hace dos cosas a la vez:

- Su cámara virtual lleva a la reunión lo que emite la escena en programa: la
  ventana de Unity con Sonia.
- La fuente ``VISION_OBS_SOURCE`` («Reunión») captura la ventana de la reunión
  para que Sonia la vea: cada vez que mira, ``ObsCamera`` pide a OBS una foto de
  esa fuente (``GetSourceScreenshot``).

OBS solo captura las fuentes activas: una fuente que no está en la escena en
programa da la foto en negro (comprobado con OBS 32.2 en macOS). Por eso la
fuente de la reunión va en la escena en programa pero fuera del lienzo, donde la
cámara virtual no la enseña. ``prepare_meeting`` lo deja así solo.

Sin dependencias nuevas: ``websockets`` ya está en el proyecto.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import itertools
import json
import logging
import os
import sys
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from sonia.config import VisionSettings

__all__ = [
    "MEETING_WINDOW_HINTS",
    "ObsConnect",
    "ObsError",
    "ObsSession",
    "local_obs_password",
    "obs_auth",
    "obs_session",
    "obs_websocket_config",
    "prepare_meeting",
    "start_obs",
]

logger = logging.getLogger(__name__)

#: Cliente de WebSocket inyectable (en las pruebas, un OBS falso).
ObsConnect = Callable[..., Any]

#: Lo que se busca en el título de las ventanas para elegir la de la reunión.
MEETING_WINDOW_HINTS = ("Meet", "Zoom", "Teams")

#: Cuánto se aparta la fuente de la reunión del borde derecho del lienzo.
OFF_CANVAS_MARGIN = 100.0

#: Espera antes de la foto de prueba: OBS tarda un momento en tener el primer fotograma.
TEST_SHOT_DELAY_S = 1.0


class ObsError(Exception):
    """OBS contestó que no a una petición (fuente que no existe, escena…)."""


def obs_auth(password: str, salt: str, challenge: str) -> str:
    """La cadena de autenticación de obs-websocket 5."""
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()


def obs_websocket_config() -> Path:
    """El archivo de ajustes de obs-websocket de este usuario (macOS, Windows o Linux)."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "obs-studio" / "plugin_config" / "obs-websocket" / "config.json"


def local_obs_password(url: str) -> str:
    """La contraseña de obs-websocket guardada en este equipo, si OBS es local.

    Así no hay que copiarla al ``.env``: OBS la genera al instalarse y la guarda
    en su configuración. Nunca se escribe en ningún registro.
    """
    if urlsplit(url).hostname not in ("127.0.0.1", "localhost", "::1"):
        return ""
    try:
        config = json.loads(obs_websocket_config().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    password = config.get("server_password") if isinstance(config, dict) else None
    return password if isinstance(password, str) else ""


class ObsSession:
    """Una conexión ya identificada con obs-websocket 5."""

    def __init__(self, ws: Any) -> None:
        self._ws = ws
        self._ids = itertools.count(1)

    async def request(self, kind: str, **data: Any) -> dict[str, Any]:
        """Hace una petición y devuelve su ``responseData``; ``ObsError`` si OBS dice que no."""
        request_id = f"sonia-{next(self._ids)}"
        await self._ws.send(
            json.dumps(
                {"op": 6, "d": {"requestType": kind, "requestId": request_id, "requestData": data}}
            )
        )
        while True:
            message = json.loads(await self._ws.recv())
            body = message.get("d") or {}
            if message.get("op") == 7 and body.get("requestId") == request_id:
                break
        status = body.get("requestStatus") or {}
        if not status.get("result"):
            detail = status.get("comment") or "sin detalle"
            raise ObsError(f"{kind}: {status.get('code')} {detail}")
        response = body.get("responseData")
        return response if isinstance(response, dict) else {}


@contextlib.asynccontextmanager
async def obs_session(
    settings: VisionSettings, connect: ObsConnect | None = None
) -> AsyncIterator[ObsSession]:
    """Conecta con OBS (``VISION_OBS_URL``), se identifica y da la sesión.

    La contraseña es ``VISION_OBS_PASSWORD`` o, si está vacía, la de la
    configuración de OBS de este equipo. Con la contraseña mala OBS cierra la
    conexión (código 4009) y sale ``ConnectionClosed`` de ``websockets``.
    """
    if connect is None:
        from websockets.asyncio.client import connect as default_connect

        connect = default_connect
    async with connect(settings.obs_url, max_size=16 * 1024 * 1024) as ws:
        hello = json.loads(await ws.recv())
        identify: dict[str, Any] = {"rpcVersion": 1, "eventSubscriptions": 0}
        auth = (hello.get("d") or {}).get("authentication")
        if auth:
            password = settings.obs_password or await asyncio.to_thread(
                local_obs_password, settings.obs_url
            )
            identify["authentication"] = obs_auth(password, auth["salt"], auth["challenge"])
        await ws.send(json.dumps({"op": 1, "d": identify}))
        # Hasta «Identified» no se piden cosas.
        while json.loads(await ws.recv()).get("op") != 2:
            pass
        yield ObsSession(ws)


def _is_meeting_window(name: str) -> bool:
    lowered = name.lower()
    return any(hint.lower() in lowered for hint in MEETING_WINDOW_HINTS)


async def prepare_meeting(
    settings: VisionSettings, *, connect: ObsConnect | None = None
) -> list[str]:
    """Deja OBS listo para el modo reunión y devuelve qué hizo, en frases.

    - La fuente ``VISION_OBS_SOURCE`` existe (si no, la crea como captura de
      ventana) y está en la escena en programa, fuera del lienzo y bloqueada.
    - Captura la ventana de la reunión: si la que tiene no es de Meet, Zoom o
      Teams, elige la primera que lo sea.
    - La cámara virtual está encendida.
    - Una foto de prueba de la fuente (no se guarda) dice si se ve algo.
    """
    report: list[str] = []
    source = settings.obs_source
    async with obs_session(settings, connect) as obs:
        scene = (await obs.request("GetCurrentProgramScene")).get("currentProgramSceneName", "")
        inputs = (await obs.request("GetInputList")).get("inputs") or []
        if not any(item.get("inputName") == source for item in inputs):
            kind, base = (
                ("screen_capture", {"type": 1})
                if sys.platform == "darwin"
                else ("window_capture", {})
            )
            await obs.request(
                "CreateInput", sceneName=scene, inputName=source, inputKind=kind, inputSettings=base
            )
            report.append(f"Fuente «{source}» creada en la escena «{scene}».")
        try:
            item_id = (await obs.request("GetSceneItemId", sceneName=scene, sourceName=source))[
                "sceneItemId"
            ]
        except ObsError:
            item_id = (await obs.request("CreateSceneItem", sceneName=scene, sourceName=source))[
                "sceneItemId"
            ]
            report.append(f"Fuente «{source}» añadida a la escena «{scene}».")

        # La ventana de la reunión.
        current = (await obs.request("GetInputSettings", inputName=source)).get("inputSettings", {})
        windows = (
            await obs.request(
                "GetInputPropertiesListPropertyItems", inputName=source, propertyName="window"
            )
        ).get("propertyItems") or []
        names = {item.get("itemValue"): str(item.get("itemName") or "") for item in windows}
        chosen = current.get("window")
        if not _is_meeting_window(names.get(chosen, "")):
            match = next(
                (item for item in windows if _is_meeting_window(names[item.get("itemValue")])), None
            )
            if match is None:
                report.append(
                    "No encuentro la ventana de la reunión (Meet, Zoom o Teams): ábrela y vuelve "
                    f"a lanzar, o elígela a mano en las propiedades de «{source}» en OBS."
                )
            else:
                chosen = match.get("itemValue")
                update: dict[str, Any] = {"window": chosen}
                if current.get("type") is not None or sys.platform == "darwin":
                    update["type"] = 1
                await obs.request("SetInputSettings", inputName=source, inputSettings=update)
        if _is_meeting_window(names.get(chosen, "")):
            report.append(f"Sonnia ve la ventana «{names[chosen]}».")

        # Activa (en la escena en programa) pero fuera del lienzo y bloqueada.
        video = await obs.request("GetVideoSettings")
        await obs.request(
            "SetSceneItemEnabled", sceneName=scene, sceneItemId=item_id, sceneItemEnabled=True
        )
        await obs.request(
            "SetSceneItemTransform",
            sceneName=scene,
            sceneItemId=item_id,
            sceneItemTransform={
                "positionX": float(video.get("baseWidth") or 1920) + OFF_CANVAS_MARGIN,
                "positionY": 0.0,
            },
        )
        await obs.request(
            "SetSceneItemLocked", sceneName=scene, sceneItemId=item_id, sceneItemLocked=True
        )
        report.append(f"«{source}» está fuera del lienzo: la cámara virtual no la enseña.")

        if not (await obs.request("GetVirtualCamStatus")).get("outputActive"):
            await obs.request("StartVirtualCam")
            report.append("Cámara virtual encendida.")
        else:
            report.append("Cámara virtual ya encendida.")

        await asyncio.sleep(TEST_SHOT_DELAY_S)
        try:
            shot = await obs.request(
                "GetSourceScreenshot", sourceName=source, imageFormat="jpg", imageWidth=320
            )
        except ObsError:
            # 702 si la fuente está vacía (sin ventana elegida o ya cerrada).
            shot = {}
    report.append(_describe_test_shot(str(shot.get("imageData") or ""), source))
    return report


def _describe_test_shot(image: str, source: str) -> str:
    """«Se ve bien» o por qué no, sin guardar la foto."""
    import cv2
    import numpy as np

    pixels = None
    if image:
        try:
            data = base64.b64decode(image.split(",", 1)[-1], validate=True)
            pixels = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        except Exception:  # noqa: BLE001 - base64 o JPEG roto: no hay foto
            pixels = None
    if pixels is None:
        return f"La foto de prueba de «{source}» no salió: falta elegir la ventana de la reunión."
    if float(pixels.std()) < 1.0:
        return (
            f"La foto de prueba de «{source}» sale en negro: revisa que la ventana de la reunión "
            "esté abierta (no minimizada) y que OBS tenga permiso de Grabación de pantalla."
        )
    return f"Foto de prueba de «{source}»: {pixels.shape[1]}x{pixels.shape[0]}, se ve bien."


def _enable_websocket_server() -> bool:
    """Activa el servidor de obs-websocket en su configuración. ¿Cambió algo?

    Solo con OBS cerrado: OBS reescribe su configuración al salir.
    """
    path = obs_websocket_config()
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(config, dict) or config.get("server_enabled"):
        return False
    config["server_enabled"] = True
    path.write_text(json.dumps(config, indent=4), encoding="utf-8")
    return True


async def _port_open(url: str) -> bool:
    parts = urlsplit(url)
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(parts.hostname or "127.0.0.1", parts.port or 4455), timeout=1.0
        )
    except (OSError, TimeoutError):
        return False
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()
    return True


async def start_obs(settings: VisionSettings, *, wait_s: float = 25.0) -> list[str]:
    """Si OBS no escucha en ``VISION_OBS_URL``, lo abre (macOS) con el servidor activado."""
    if await _port_open(settings.obs_url):
        return []
    if sys.platform != "darwin":
        return ["OBS no responde: ábrelo y activa Herramientas > Ajustes del servidor WebSocket."]
    running = await asyncio.create_subprocess_exec(
        "pgrep", "-xq", "obs", stdout=asyncio.subprocess.DEVNULL
    )
    if await running.wait() == 0:
        return [
            "OBS está abierto pero sin servidor WebSocket: actívalo en Herramientas > Ajustes "
            "del servidor WebSocket (o ciérralo y vuelve a lanzar)."
        ]
    report = []
    if await asyncio.to_thread(_enable_websocket_server):
        report.append("Servidor WebSocket de OBS activado.")
    opener = await asyncio.create_subprocess_exec("open", "-a", "OBS")
    await opener.wait()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_s
    while loop.time() < deadline:
        if await _port_open(settings.obs_url):
            report.append("OBS abierto.")
            return report
        await asyncio.sleep(0.5)
    report.append(f"OBS no respondió en {wait_s:.0f} s.")
    return report
