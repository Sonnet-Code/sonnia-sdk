"""Secuencias del orquestador falso para probar las pantallas (``scripts/juegos_demo.py``).

Cada juego escribe la suya en ``sonia/games/<paquete>/demo.py`` con una función
``steps() -> list[Step]``: lo que el orquestador falso le manda a Unity, paso a paso,
y cuándo pedir una captura (``docs/juegos.md``, «Probar la pantalla sin Sonia»).

El orquestador falso pone el sobre de los mensajes de juego (``type``, ``game`` y
``seq``), manda ``hello`` y ``set_volume`` a 0 al conectar, espera al ``client_hello``
de Unity antes del primer paso y, al acabar, manda ``dev_done``. Nunca llama a ninguna
API ni usa la cámara de nadie: la vista en vivo sale de fotos o vídeos públicos que
tengas en tu scratchpad (nunca en el repo) o de una imagen sintética.

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

import importlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

__all__ = [
    "Capture",
    "GameMsg",
    "Preview",
    "Send",
    "Step",
    "Wait",
    "WaitEvent",
    "load_demo",
]


@dataclass(frozen=True, slots=True)
class Wait:
    """Esperar ``seconds`` (animaciones, giros, contadores)."""

    seconds: float


@dataclass(frozen=True, slots=True)
class Send:
    """Un mensaje JSON del protocolo tal cual (``speech_start``, ``transcript``, ``state``...)."""

    msg: dict[str, Any]


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
    """La vista en vivo durante ``seconds``: ``camera_preview`` y frames ``SNCV``.

    ``source``: ruta de una foto o un vídeo público en tu scratchpad (nunca en el repo);
    vacío, una imagen sintética. ``draw`` pinta encima de cada frame BGR antes de
    codificarlo, como el ``Overlay`` de la vista en vivo (esqueletos, marcas). ``off``:
    al acabar, ``camera_preview`` apagado.
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


Step = Wait | Send | GameMsg | Preview | Capture | WaitEvent


def load_demo(game_id: str) -> list[Step]:
    """Los pasos de la secuencia de un juego (``sonia/games/<paquete>/demo.py:steps``).

    Lanza ``LookupError`` si el juego no existe o aún no tiene secuencia.
    """
    from sonia.games.registry import find_game

    cls = find_game(game_id)
    if cls is None:
        raise LookupError(f"no hay ningún juego «{game_id}»")
    package = cls.__module__.rsplit(".", 1)[0]
    try:
        module = importlib.import_module(f"{package}.demo")
    except ModuleNotFoundError as exc:
        raise LookupError(f"{game_id} aún no tiene secuencia ({package}/demo.py)") from exc
    steps = getattr(module, "steps", None)
    if not callable(steps):
        raise LookupError(f"{package}/demo.py no tiene steps()")
    result = list(steps())
    bad = [
        s
        for s in result
        if not isinstance(s, Wait | Send | GameMsg | Preview | Capture | WaitEvent)
    ]
    if bad:
        raise LookupError(f"pasos desconocidos en {package}/demo.py: {bad[:3]}")
    return result
