"""La secuencia de la búsqueda relámpago para el orquestador falso (``scripts/juegos_demo.py``).

Pasa por cada estado de su pantalla y pide una captura 9:16 en cada uno: la ronda lista
(el objeto y «¿listos?»), el contador, la cámara mirando, ¡encontrado!, ¡tiempo!, un objeto
con nombre largo y el final. Los mensajes son los mismos que manda
:class:`~sonia.games.busqueda.game.BusquedaGame` (lo comprueba ``test_busqueda_demo``).

La vista en vivo sale de una imagen sintética o, si existe la variable de entorno
``BUSQUEDA_DEMO_FOTO``, de una foto pública que tengas en tu scratchpad (nunca en el repo ni la
cámara de nadie)::

    BUSQUEDA_DEMO_FOTO=/ruta/a/foto.jpg \\
      scripts/juegos_capturas.sh --juego busqueda --puerto 8797 --salida <scratchpad>/capturas
"""

from __future__ import annotations

import os
from typing import Any

from sonia.games.demo import Capture, GameMsg, Preview, Step, Wait

__all__ = ["steps"]

TITLE = "Búsqueda relámpago"
ROUNDS = 3
SECONDS = 25.0

#: Los colores de Google de la tarjeta (``sonia.games.busqueda.bank.COLORS``).
BLUE = "#4285F4"
RED = "#EA4335"


def _state(
    index: int, name: str, color: str, phase: str, found: int, **extra: Any
) -> dict[str, Any]:
    """El estado completo de una ronda, con las mismas claves que ``BusquedaGame._state``."""
    data: dict[str, Any] = {
        "index": index,
        "total": ROUNDS,
        "object": name,
        "color": color,
        "seconds": SECONDS,
        "found": found,
        "phase": phase,
    }
    data.update(extra)
    return data


def steps() -> list[Step]:
    photo = os.environ.get("BUSQUEDA_DEMO_FOTO", "").strip()
    return [
        # La vista en vivo, en segundo plano durante toda la secuencia.
        Preview(120.0, source=photo, off=True),
        # Ronda 1: algo azul, con su color. Lista, contador y la cámara mirando.
        GameMsg(
            "start", {"title": TITLE, "rounds": ROUNDS, "round_seconds": SECONDS, "preview": True}
        ),
        GameMsg("round", _state(1, "algo azul", BLUE, "ready", 0)),
        Capture("busqueda-1-ronda-lista", settle_s=2.0),
        GameMsg("go", _state(1, "algo azul", BLUE, "running", 0)),
        Capture("busqueda-2-contador", settle_s=2.5),
        GameMsg("checking", {"n": 2, "max": 10}),
        Capture("busqueda-3-mirando", settle_s=0.35),
        # ¡Lo veo!: el confeti y lo que vio el modelo.
        GameMsg("found", _state(1, "algo azul", BLUE, "found", 1, what="botella azul")),
        Capture("busqueda-4-encontrado", settle_s=0.7),
        Capture("busqueda-5-encontrado-despues", settle_s=2.0),
        # Ronda 2: una botella (sin color) y se acaba el tiempo.
        GameMsg("round", _state(2, "una botella", "", "ready", 1)),
        Capture("busqueda-6-ronda-sin-color", settle_s=1.5),
        GameMsg("go", _state(2, "una botella", "", "running", 1)),
        Wait(3.0),
        GameMsg("timeout", _state(2, "una botella", "", "timeout", 1, silent=False)),
        Capture("busqueda-7-tiempo", settle_s=1.2),
        # Ronda 3: un nombre largo en la tarjeta.
        GameMsg("round", _state(3, "algo con el logo de Google", RED, "ready", 1)),
        Capture("busqueda-8-nombre-largo", settle_s=1.5),
        GameMsg("go", _state(3, "algo con el logo de Google", RED, "running", 1)),
        Wait(2.0),
        GameMsg(
            "found",
            _state(
                3, "algo con el logo de Google", RED, "found", 2, what="taza con logo de Google"
            ),
        ),
        Capture("busqueda-9-encontrado-largo", settle_s=1.0),
        # El final: dos de tres, gana.
        GameMsg("end", {"result": "win", "found": 2, "total": ROUNDS, "photos": 14}),
        Capture("busqueda-10-final", settle_s=2.5),
        # Otra partida: la cámara no contesta a ninguna mirada y termina sin llegar a la mitad.
        Wait(2.5),
        GameMsg(
            "start", {"title": TITLE, "rounds": ROUNDS, "round_seconds": SECONDS, "preview": True}
        ),
        GameMsg("round", _state(1, "unas llaves", "", "ready", 0)),
        GameMsg("go", _state(1, "unas llaves", "", "running", 0)),
        Wait(1.5),
        GameMsg("timeout", _state(1, "unas llaves", "", "timeout", 0, silent=True)),
        Capture("busqueda-11-sin-respuesta", settle_s=1.2),
        GameMsg("end", {"result": "lose", "found": 0, "total": ROUNDS, "photos": 9}),
        Capture("busqueda-12-final-casi", settle_s=2.5),
        # Una Unity que se reconecta a mitad: solo le llegan el start y el último estado (un
        # go de la ronda 2 con una encontrada), y con eso se repinta todo.
        Wait(2.5),
        GameMsg(
            "start", {"title": TITLE, "rounds": ROUNDS, "round_seconds": SECONDS, "preview": True}
        ),
        GameMsg("go", _state(2, "un celular", "", "running", 1)),
        Capture("busqueda-13-repintado-tras-reconectar", settle_s=1.5),
        GameMsg("end", {"result": "cancel", "found": 1, "total": ROUNDS, "photos": 6}),
    ]
