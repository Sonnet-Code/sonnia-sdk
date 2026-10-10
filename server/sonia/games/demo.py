"""El orquestador falso para probar las pantallas de los juegos (``scripts/juegos_demo.py``).

Cada juego escribe su secuencia en ``sonia/games/<paquete>/demo.py`` con una función
``steps() -> list[Step]``: lo que el orquestador falso le manda a Unity, paso a paso,
y cuándo pedir una captura (``docs/juegos.md``, «Probar la pantalla sin Sonia»).

:func:`serve_demo` es un servidor WebSocket que habla el protocolo con Unity: al
conectar manda ``hello`` y ``set_volume`` a 0 (las pruebas van en silencio), espera el
``client_hello`` de Unity, pone el sobre de los mensajes de juego (``type``, ``game`` y
``seq``) y, al acabar, manda ``dev_done``. Nunca llama a ninguna API ni abre ninguna
cámara: la vista en vivo sale de fotos o vídeos públicos que tengas en tu scratchpad
(nunca en el repo) o de una imagen sintética.

Ejemplo::

    from sonia.games.demo import Capture, GameMsg, Step, Wait

    def steps() -> list[Step]:
        return [
            GameMsg("start", {"title": "Wordle de tecnología", "rows": 6}),
            Capture("wordle-1-empezar"),
            GameMsg("guess", {"row": 0, "letters": "LINUX", "marks": "gyxxg"}),
            Wait(1.5),
            Capture("wordle-2-jugada"),
            GameMsg("end", {"result": "win"}),
            Capture("wordle-3-final", settle_s=2.0),
        ]
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import json
import math
import re
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from sonia.ws import protocol as p

if TYPE_CHECKING:
    from websockets.asyncio.server import ServerConnection

__all__ = [
    "ESPERA",
    "EXAMPLE",
    "MSG_DEV_CAPTURE",
    "MSG_DEV_DONE",
    "Audio",
    "Capture",
    "GameMsg",
    "Preview",
    "Send",
    "Step",
    "Wait",
    "WaitEvent",
    "example_steps",
    "load_demo",
    "serve_demo",
]

#: Mensajes de pruebas, fuera del protocolo de producción: solo los manda el orquestador
#: falso y solo los entiende la herramienta de capturas en batch de Unity
#: (``docs/juegos.md`` y ``docs/juegos-unity.md``). Una Unity normal los ignora.
MSG_DEV_CAPTURE = "dev_capture"
MSG_DEV_DONE = "dev_done"

#: ``--juego`` de la secuencia de ejemplo: solo los eventos comunes y la vista en vivo.
EXAMPLE = "ejemplo"

#: ``--juego`` de la secuencia del aviso de espera (``busy``) en todos los encuadres: no es un
#: juego (``sonia/games/espera_demo.py``).
ESPERA = "espera"

#: Tamaño de los frames de la vista en vivo (como la de verdad).
PREVIEW_SIZE = (640, 360)
PREVIEW_JPEG_QUALITY = 60

_CAPTURE_NAME = re.compile(r"[^A-Za-z0-9._-]")


@dataclass(frozen=True, slots=True)
class Wait:
    """Esperar ``seconds`` (animaciones, giros, contadores)."""

    seconds: float


@dataclass(frozen=True, slots=True)
class Send:
    """Un mensaje JSON del protocolo tal cual (``speech_start``, ``transcript``, ``state``...)."""

    msg: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Audio:
    """Frames binarios de voz de Sonia tal cual (``encode_audio_frame``), todos de una vez.

    Unity los encola y los reproduce a su ritmo, así que van entre un ``speech_start`` y un
    ``speech_end`` (con :class:`Send`) para ver a Sonnia hablando: boca, gestos al hablar.
    """

    frames: tuple[bytes, ...]


@dataclass(frozen=True, slots=True)
class GameMsg:
    """Un mensaje de la pantalla del juego: el orquestador falso pone ``type``, ``game`` y ``seq``.

    ``game`` vacío es el juego de la secuencia (``--juego``).
    """

    event: str
    data: dict[str, Any] = field(default_factory=dict)
    game: str = ""


@dataclass(frozen=True, slots=True)
class Preview:
    """La vista en vivo durante ``seconds``, **en segundo plano**: los pasos siguientes van a la vez.

    Manda ``camera_preview`` encendido y unos ``fps`` frames ``SNCV`` por segundo, en espejo
    si ``mirror`` (con el bit de «ya va en espejo», como la de verdad). ``source``: ruta de
    una foto o un vídeo público en tu scratchpad (nunca en el repo); vacío, una imagen
    sintética. ``draw`` pinta encima de cada frame BGR antes de codificarlo, como el
    ``Overlay`` de la vista en vivo (esqueletos, marcas): recibe el frame y si ya va en
    espejo. ``off``: al acabar, ``camera_preview`` apagado (si no, Unity la retira a los
    2 s sin frames). Otra ``Preview`` sustituye a la que esté en marcha.
    """

    seconds: float
    source: str = ""
    fps: float = 10.0
    mirror: bool = True
    draw: Callable[[np.ndarray, bool], None] | None = None
    off: bool = False


@dataclass(frozen=True, slots=True)
class Capture:
    """Pide una captura 9:16 a la herramienta de Unity: ``{"type": "dev_capture", "name": ...}``.

    Espera antes ``settle_s`` para que acaben las animaciones de entrada. ``name``: letras,
    números, ``-``, ``_`` y ``.`` (el PNG sale como ``<name>.png``).
    """

    name: str
    settle_s: float = 1.0


@dataclass(frozen=True, slots=True)
class WaitEvent:
    """Espera un ``game_event`` de Unity (``wheel_stopped``...) como mucho ``timeout`` segundos."""

    event: str
    timeout: float = 10.0


Step = Wait | Send | Audio | GameMsg | Preview | Capture | WaitEvent
_STEP_TYPES = (Wait, Send, Audio, GameMsg, Preview, Capture, WaitEvent)


def example_steps() -> list[Step]:
    """La secuencia de ejemplo: la pantalla común (``start``, ``end``) y la vista en vivo."""
    return [
        GameMsg("start", {"title": "Juego de ejemplo"}),
        Capture("ejemplo-1-empezar"),
        Preview(4.0, off=True),
        Capture("ejemplo-2-vista-en-vivo", settle_s=1.5),
        Wait(3.0),
        GameMsg("end", {"result": "win"}),
        Capture("ejemplo-3-final", settle_s=1.0),
    ]


def load_demo(game_id: str) -> list[Step]:
    """Los pasos de la secuencia de un juego (``sonia/games/<paquete>/demo.py:steps``).

    ``ejemplo`` es :func:`example_steps` y ``espera``, la del aviso de espera. Lanza
    ``LookupError`` si el juego no existe o aún no tiene secuencia.
    """
    if game_id == EXAMPLE:
        return example_steps()
    if game_id == ESPERA:
        from sonia.games.espera_demo import steps as busy_steps

        return busy_steps()
    from sonia.games.registry import find_game

    cls = find_game(game_id)
    if cls is None:
        raise LookupError(f"no hay ningún juego «{game_id}»")
    package = cls.__module__.rsplit(".", 1)[0]
    try:
        module = importlib.import_module(f"{package}.demo")
    except ModuleNotFoundError as exc:
        if exc.name != f"{package}.demo":
            raise
        raise LookupError(f"{game_id} aún no tiene secuencia ({package}/demo.py)") from exc
    steps = getattr(module, "steps", None)
    if not callable(steps):
        raise LookupError(f"{package}/demo.py no tiene steps()")
    result = list(steps())
    bad = [s for s in result if not isinstance(s, _STEP_TYPES)]
    if bad:
        raise LookupError(f"pasos desconocidos en {package}/demo.py: {bad[:3]}")
    return result


def capture_name(name: str) -> str:
    """El nombre de una captura como lo guarda Unity: letras, números, ``-``, ``_`` y ``.``."""
    return _CAPTURE_NAME.sub("_", name.strip()) or "captura"


# ---------------------------------------------------------------------------
# Frames de la vista en vivo
# ---------------------------------------------------------------------------


def _fit(frame: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """Recorta al centro y escala a ``size`` (ancho, alto) sin deformar."""
    import cv2

    width, height = size
    h, w = frame.shape[:2]
    scale = max(width / w, height / h)
    resized = cv2.resize(frame, (max(width, round(w * scale)), max(height, round(h * scale))))
    rh, rw = resized.shape[:2]
    top, left = (rh - height) // 2, (rw - width) // 2
    return np.ascontiguousarray(resized[top : top + height, left : left + width])


def _synthetic_frames(size: tuple[int, int]) -> Iterator[np.ndarray]:
    """Una imagen sintética que se mueve: degradado, rejilla y un círculo que va y viene."""
    import cv2

    width, height = size
    x = np.linspace(0, 1, width, dtype=np.float32)
    y = np.linspace(0, 1, height, dtype=np.float32)[:, None]
    base = np.zeros((height, width, 3), dtype=np.uint8)
    base[..., 0] = (120 + 100 * x).astype(np.uint8)
    base[..., 1] = (60 + 80 * y).astype(np.uint8)
    base[..., 2] = 40
    base[::40, :] = (90, 90, 90)
    base[:, ::40] = (90, 90, 90)
    cv2.putText(base, "IZQUIERDA", (16, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
    tick = 0
    while True:
        frame = base.copy()
        cx = int(width / 2 + width / 3 * math.sin(tick / 10))
        cv2.circle(frame, (cx, height // 2), 40, (0, 200, 255), -1)
        tick += 1
        yield frame


def _file_frames(source: str, size: tuple[int, int]) -> Iterator[np.ndarray]:
    """Los frames de una foto (siempre la misma) o de un vídeo (en bucle)."""
    import cv2

    path = Path(source).expanduser()
    image = cv2.imread(str(path))
    if image is not None:
        fitted = _fit(image, size)
        while True:
            yield fitted.copy()
    video = cv2.VideoCapture(str(path))
    try:
        if not video.isOpened():
            raise ValueError(f"no se puede abrir {path} como foto ni como vídeo")
        while True:
            ok, frame = video.read()
            if not ok:
                video.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = video.read()
                if not ok:
                    raise ValueError(f"el vídeo {path} no tiene frames")
            yield _fit(frame, size)
    finally:
        video.release()


def _encode(frame: np.ndarray) -> bytes:
    import cv2

    ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, PREVIEW_JPEG_QUALITY])
    if not ok:
        raise ValueError("no se pudo codificar el frame")
    return bytes(jpeg.tobytes())


# ---------------------------------------------------------------------------
# El servidor
# ---------------------------------------------------------------------------


class _Session:
    """La Unity conectada al orquestador falso y lo que va contando."""

    def __init__(self, log: Callable[[str], None]) -> None:
        self.log = log
        self.unity: ServerConnection | None = None
        self.hello = asyncio.Event()
        self.gone = asyncio.Event()
        self.events: asyncio.Queue[tuple[str, str, dict[str, Any]]] = asyncio.Queue()
        self.seq = 0
        self.preview_seq = 0

    async def send(self, msg: dict[str, Any] | bytes) -> None:
        if self.unity is None:
            raise ConnectionError("Unity no está conectada")
        payload = msg if isinstance(msg, bytes) else p.dumps(msg)
        await self.unity.send(payload)


async def serve_demo(
    steps: Sequence[Step],
    *,
    game: str,
    host: str = "127.0.0.1",
    port: int = 8791,
    sample_rate: int = 24_000,
    connect_timeout: float = 180.0,
    after_capture_s: float = 0.5,
    stay: bool = False,
    on_ready: Callable[[int], None] | None = None,
    log: Callable[[str], None] = print,
) -> int:
    """Sirve la secuencia ``steps`` del juego ``game`` a la primera Unity que se conecte.

    Devuelve 0 si la secuencia terminó, 1 si Unity no llegó a tiempo
    (``connect_timeout``), 2 si Unity se fue a mitad y 3 si un paso falló. Con ``stay``
    no manda ``dev_done`` y sigue sirviendo hasta que lo cancelen. ``on_ready`` recibe el
    puerto en el que escucha (con ``port=0``, uno libre).
    """
    from websockets.asyncio.server import serve

    session = _Session(log)

    async def handler(conn: ServerConnection) -> None:
        await conn.send(p.dumps(p.msg_hello(sample_rate)))
        await conn.send(p.dumps(p.msg_set_volume(0.0)))
        try:
            async for raw in conn:
                if isinstance(raw, bytes):
                    continue
                msg = p.parse_client_message(raw)
                if msg is None:
                    continue
                kind = msg["type"]
                if kind == p.MSG_CLIENT_HELLO:
                    hello = p.parse_client_hello(msg)
                    log(
                        f"client_hello de {hello.client or '?'} {hello.version or '?'}: juegos "
                        f"{sorted(hello.games) if hello.games is not None else 'ninguno'}, "
                        f"capacidades {sorted(hello.features)}"
                    )
                    if session.unity is None:
                        session.unity = conn
                        session.hello.set()
                elif kind == p.MSG_GAME_EVENT:
                    parsed = p.parse_game_event(msg)
                    if parsed is not None:
                        log(f"game_event {parsed[0]}.{parsed[1]} {json.dumps(parsed[2])}")
                        await session.events.put(parsed)
        finally:
            if conn is session.unity:
                session.gone.set()

    async with serve(handler, host, port, compression=None, max_size=16 * 1024 * 1024) as server:
        real_port = int(next(iter(server.sockets)).getsockname()[1])
        log(f"Orquestador falso en ws://{host}:{real_port}/ esperando a Unity ({game})")
        if on_ready is not None:
            on_ready(real_port)
        try:
            await asyncio.wait_for(session.hello.wait(), timeout=connect_timeout)
        except TimeoutError:
            log(f"Unity no se conectó en {connect_timeout:.0f} s")
            return 1
        code = await _run_steps(session, steps, game, after_capture_s)
        if code == 0 and not stay:
            with contextlib.suppress(Exception):
                await session.send({"type": MSG_DEV_DONE})
            log("dev_done")
            await asyncio.sleep(0.5)
        elif code == 0:
            log("Secuencia terminada; sigo sirviendo (Ctrl+C para salir)")
            await session.gone.wait()
        return code


async def _run_steps(
    session: _Session, steps: Sequence[Step], game: str, after_capture_s: float
) -> int:
    preview: asyncio.Task[None] | None = None
    started = time.monotonic()
    try:
        for index, step in enumerate(steps, start=1):
            if session.gone.is_set():
                session.log("Unity se desconectó a mitad de la secuencia")
                return 2
            stamp = f"{time.monotonic() - started:6.2f}s paso {index}/{len(steps)}"
            try:
                if isinstance(step, Wait):
                    session.log(f"{stamp} espera {step.seconds:.1f} s")
                    await asyncio.sleep(max(0.0, step.seconds))
                elif isinstance(step, Send):
                    session.log(f"{stamp} {step.msg.get('type')}")
                    await session.send(step.msg)
                elif isinstance(step, Audio):
                    session.log(f"{stamp} audio, {len(step.frames)} frames")
                    for frame in step.frames:
                        await session.send(frame)
                elif isinstance(step, GameMsg):
                    session.seq += 1
                    msg = p.msg_game(step.game or game, step.event, session.seq, step.data)
                    session.log(f"{stamp} game {msg['game']}.{step.event} {json.dumps(step.data)}")
                    await session.send(msg)
                elif isinstance(step, Preview):
                    if preview is not None:
                        preview.cancel()
                        await asyncio.gather(preview, return_exceptions=True)
                    session.log(
                        f"{stamp} vista en vivo {step.seconds:.1f} s ({step.source or 'sintética'})"
                    )
                    preview = asyncio.create_task(_stream_preview(session, step))
                elif isinstance(step, Capture):
                    await asyncio.sleep(max(0.0, step.settle_s))
                    name = capture_name(step.name)
                    session.log(f"{stamp} captura {name}")
                    await session.send({"type": MSG_DEV_CAPTURE, "name": name})
                    await asyncio.sleep(max(0.0, after_capture_s))
                elif isinstance(step, WaitEvent):
                    session.log(f"{stamp} espera el game_event {step.event}")
                    await _wait_event(session, step)
            except TimeoutError:
                session.log(f"{stamp} no llegó a tiempo: {step}")
                return 3
            except ConnectionError:
                session.log("Unity se desconectó a mitad de la secuencia")
                return 2
            except Exception as exc:  # noqa: BLE001 - un paso roto se cuenta y se para
                session.log(f"{stamp} falló {step}: {exc}")
                return 3
        if preview is not None:
            await asyncio.gather(preview, return_exceptions=True)
        return 0
    finally:
        if preview is not None and not preview.done():
            preview.cancel()
            await asyncio.gather(preview, return_exceptions=True)


async def _wait_event(session: _Session, step: WaitEvent) -> None:
    async with asyncio.timeout(step.timeout):
        while True:
            _, event, _ = await session.events.get()
            if event == step.event:
                return


async def _stream_preview(session: _Session, step: Preview) -> None:
    """Manda la vista en vivo de un paso :class:`Preview` (en segundo plano)."""
    import cv2

    frames = (
        _file_frames(step.source, PREVIEW_SIZE) if step.source else _synthetic_frames(PREVIEW_SIZE)
    )
    await session.send(p.msg_camera_preview(True, mirror=step.mirror))
    period = 1.0 / max(1.0, step.fps)
    deadline = time.monotonic() + max(0.0, step.seconds)
    try:
        while time.monotonic() < deadline:
            tick = time.monotonic()
            frame = await asyncio.to_thread(next, frames)
            if step.mirror:
                frame = cv2.flip(frame, 1)
            if step.draw is not None:
                step.draw(frame, step.mirror)
            jpeg = await asyncio.to_thread(_encode, frame)
            session.preview_seq += 1
            height, width = frame.shape[:2]
            await session.send(
                p.encode_preview_frame(
                    session.preview_seq, width, height, jpeg, mirrored=step.mirror
                )
            )
            await asyncio.sleep(max(0.0, period - (time.monotonic() - tick)))
        if step.off:
            await session.send(p.msg_camera_preview(False, mirror=step.mirror))
    finally:
        close = getattr(frames, "close", None)
        if callable(close):
            close()
