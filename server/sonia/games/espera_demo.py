"""La secuencia del aviso de espera (``busy``) para el orquestador falso (``scripts/juegos_demo.py``).

Pinta la pastilla de Unity (``BusyIndicator``) en cada encuadre y pide capturas 9:16: fuera
de juego en reposo y conversando («Pensando…», «Buscando en internet…»), unos frames
seguidos de la entrada y la salida (un ``on`` que se apaga enseguida se queda 0,6 s), el
texto que cambia en el sitio, y en juego: Simón dice con «Mirando las poses…», piedra,
papel o tijera con «Mirando tu mano…» en su resultado, la búsqueda con «Encendiendo la
cámara…» y «Mirando lo que enseñas…», y el Wordle (sin cámara) con «Preparando el
juego…» y «Pensando…». Los mensajes de los juegos salen de sus propias secuencias
(``sonia/games/<juego>/demo.py``).

La vista en vivo es sintética o, con ``BUSQUEDA_DEMO_FOTO``, una foto pública de tu
scratchpad (nunca la cámara de nadie)::

    scripts/juegos_capturas.sh --orquestador \\
      "uv run --no-sync python ../scripts/juegos_demo.py --juego espera --puerto 8796 --tras-captura 0.05" \\
      --clon <clon compartido> --salida <scratchpad>/capturas-espera
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import replace

from sonia.busy import (
    TEXT_CAMERA,
    TEXT_GAME,
    TEXT_HAND,
    TEXT_LOOK,
    TEXT_POSES,
    TEXT_SEARCH,
    TEXT_THINK,
)
from sonia.games.busqueda import demo as busqueda_demo
from sonia.games.demo import Capture, GameMsg, Preview, Send, Step, Wait
from sonia.games.poses import demo as poses_demo
from sonia.games.poses.game import PosesGame
from sonia.games.ppt import demo as ppt_demo
from sonia.games.wordle import demo as wordle_demo
from sonia.ws import protocol as p

__all__ = ["steps"]

OFF = Send(p.msg_busy(False))


def _on(kind: str, text: str) -> Send:
    return Send(p.msg_busy(True, kind, text))


def _as(game: str, items: Sequence[Step]) -> list[Step]:
    """Los pasos de la secuencia de un juego, con sus mensajes a nombre de ese juego."""
    return [replace(s, game=game) if isinstance(s, GameMsg) and not s.game else s for s in items]


def _split(items: Sequence[Step], event: str) -> tuple[list[Step], list[Step]]:
    """Parte los pasos justo antes del primer mensaje de juego ``event``."""
    for index, step in enumerate(items):
        if isinstance(step, GameMsg) and step.event == event:
            return list(items[:index]), list(items[index:])
    return list(items), []


def _outside() -> list[Step]:
    """Fuera de juego: reposo, conversación, entrada y salida, y el texto que cambia."""
    return [
        # Reposo: tras 8 s sin nadie, el plano de rodillas para arriba con la invitación.
        Wait(9.0),
        Capture("espera-01-reposo", settle_s=0.0),
        _on("think", TEXT_THINK),
        Capture("espera-02-reposo-pensando", settle_s=0.8),
        _on("search", TEXT_SEARCH),
        Capture("espera-03-reposo-buscando", settle_s=0.8),
        OFF,
        Capture("espera-04-reposo-retirado", settle_s=1.2),
        # Conversando: el plano de medio muslo para arriba, con subtítulos.
        Send(p.msg_state("listening")),
        Send(p.msg_transcript("user", "¿Qué charla hay ahora en la sala principal?", True)),
        Wait(0.6),
        Send(p.msg_state("thinking")),
        _on("think", TEXT_THINK),
        Capture("espera-05-conversa-pensando", settle_s=1.6),
        _on("search", TEXT_SEARCH),
        Send(p.msg_activity("search")),
        Capture("espera-06-conversa-buscando", settle_s=1.4),
        Send(p.msg_activity("none")),
        OFF,
        Send(p.msg_state("speaking")),
        Send(
            p.msg_transcript(
                "assistant", "Ahora mismo hay una charla de inteligencia artificial.", False
            )
        ),
        Capture("espera-07-conversa-retirado", settle_s=1.2),
        Send(p.msg_state("listening")),
        Wait(1.5),
        # Entrada y salida, frames seguidos: el off llega enseguida y aun así se queda 0,6 s.
        _on("think", TEXT_THINK),
        Capture("espera-08a-entrada", settle_s=0.0),
        Capture("espera-08b-entrada", settle_s=0.0),
        OFF,
        Capture("espera-08c-off", settle_s=0.0),
        Capture("espera-08d", settle_s=0.05),
        Capture("espera-08e", settle_s=0.05),
        Capture("espera-08f", settle_s=0.05),
        Capture("espera-08g", settle_s=0.05),
        Capture("espera-08h", settle_s=0.05),
        Capture("espera-08i", settle_s=0.05),
        Wait(1.0),
        # El texto cambia en el sitio, sin salir y volver a entrar.
        _on("think", TEXT_THINK),
        Capture("espera-09a-pensando", settle_s=0.5),
        _on("search", TEXT_SEARCH),
        Capture("espera-09b-cambia", settle_s=0.0),
        Capture("espera-09c-cambia", settle_s=0.05),
        Capture("espera-09d-buscando", settle_s=0.4),
        OFF,
        Wait(1.5),
    ]


def _poses() -> list[Step]:
    """Simón dice: la cámara que arranca y el juez mirando las poses de la ronda."""
    players = len(poses_demo.SLOTS)
    rest = poses_demo._scene(poses_demo._rest(), ["no"] * players, close=True)
    ronda = poses_demo._round(1, "brazos_arriba", simon=True, doing=3, prefix="espera-poses")
    before, after = _split(ronda, "result")
    out: list[Step] = [
        GameMsg("start", {"title": PosesGame.title, "rounds": poses_demo.ROUNDS}),
        _on("camera", TEXT_CAMERA),
        Capture("espera-10-poses-camara", settle_s=1.2),
        Preview(40.0, draw=rest),
        OFF,
        GameMsg("placement", poses_demo._state("placement", players=players)),
        Wait(1.5),
        *before,
        _on("judge", TEXT_POSES),
        Capture("espera-11-poses-mirando", settle_s=0.6),
        after[0],
        Capture("espera-12-poses-resultado-con-aviso", settle_s=0.5),
        OFF,
        Capture("espera-13-poses-resultado", settle_s=1.0),
        GameMsg("end", {"result": "cancel"}),
        Preview(0.2, draw=rest, off=True),
        Wait(2.0),
    ]
    return _as("poses", out)


def _ppt() -> list[Step]:
    """Piedra, papel o tijera: el juez mirando la mano y el resultado con el aviso encima."""
    game = "piedra_papel_tijera"
    out: list[Step] = [
        GameMsg("start", {"title": "Piedra, papel o tijera", **ppt_demo._base(1, 0, 0)}),
        Preview(40.0, draw=ppt_demo._draw),
        Wait(2.0),
        *ppt_demo._throw(1, "tijera", 0, 0),
        Wait(ppt_demo.GO_S + 0.15),
        GameMsg("go", {"round": 1, "sonnia": "tijera"}),
        _on("judge", TEXT_HAND),
        Capture("espera-20-ppt-mirando-mano", settle_s=0.5),
        ppt_demo._result(1, "tijera", "piedra", "player", 0, 1),
        ppt_demo.SPEAKING,
        Capture("espera-21-ppt-resultado-con-aviso", settle_s=0.6),
        OFF,
        Capture("espera-22-ppt-resultado", settle_s=1.0),
        GameMsg("end", {"result": "cancel", "winner": "", "score": ppt_demo._score(0, 1)}),
        Preview(0.2, draw=ppt_demo._draw, off=True),
        Wait(2.0),
    ]
    return _as(game, out)


def _busqueda() -> list[Step]:
    """La búsqueda: la cámara que arranca y el juez mirando lo que enseñan."""
    photo = os.environ.get("BUSQUEDA_DEMO_FOTO", "").strip()
    bq = busqueda_demo
    out: list[Step] = [
        GameMsg(
            "start",
            {"title": bq.TITLE, "rounds": bq.ROUNDS, "round_seconds": bq.SECONDS, "preview": True},
        ),
        GameMsg("round", bq._state(1, "algo azul", bq.BLUE, "ready", 0)),
        _on("camera", TEXT_CAMERA),
        Capture("espera-30-busqueda-camara", settle_s=1.2),
        Preview(30.0, source=photo),
        OFF,
        Wait(1.5),
        GameMsg("go", bq._state(1, "algo azul", bq.BLUE, "running", 0)),
        Wait(1.5),
        GameMsg("checking", {"n": 2, "max": 10}),
        _on("judge", TEXT_LOOK),
        Capture("espera-31-busqueda-mirando", settle_s=0.6),
        OFF,
        GameMsg("found", bq._state(1, "algo azul", bq.BLUE, "found", 1, what="botella azul")),
        Capture("espera-32-busqueda-encontrado", settle_s=1.0),
        GameMsg("end", {"result": "cancel", "found": 1, "total": bq.ROUNDS, "photos": 2}),
        Preview(0.2, source=photo, off=True),
        Wait(2.0),
    ]
    return _as("busqueda", out)


def _wordle() -> list[Step]:
    """El Wordle, sin cámara: el juego que se prepara y Sonia pensando la jugada."""
    secret, hint = wordle_demo.WON
    guesses = wordle_demo.WON_GUESSES
    out: list[Step] = [
        _on("game", TEXT_GAME),
        Capture("espera-40-preparando-juego", settle_s=0.8),
        GameMsg("start", wordle_demo.start_data()),
        OFF,
        Wait(1.6),
        GameMsg("guess", wordle_demo.guess_data(guesses[:1], secret, hint)),
        Wait(2.0),
        _on("think", TEXT_THINK),
        Capture("espera-41-wordle-pensando", settle_s=0.8),
        OFF,
        GameMsg("guess", wordle_demo.guess_data(guesses[:2], secret, hint)),
        Capture("espera-42-wordle-jugada", settle_s=1.6),
        GameMsg("end", {"word": secret, "attempts": 2, "stopped": True, "result": "cancel"}),
        Wait(1.5),
    ]
    return _as("wordle", out)


def steps() -> list[Step]:
    """Toda la secuencia: fuera de juego y en cuatro juegos (tres con cámara y el Wordle)."""
    return [
        Send(p.msg_state("idle")),
        *_outside(),
        *_poses(),
        *_ppt(),
        *_busqueda(),
        *_wordle(),
        Capture("espera-50-fin", settle_s=1.0),
    ]
