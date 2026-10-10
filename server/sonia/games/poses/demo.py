"""La secuencia de «Simón dice con poses» para el orquestador falso (``scripts/juegos_demo.py``).

Pasa por cada estado de la pantalla y pide una captura en cada uno: colocación (con alguien
demasiado cerca), ronda con la demostración de Sonnia, orden, ventana, acierto, fallo,
trampa, las demás demostraciones, el final y el cierre.

La vista en vivo es sintética: una sala dibujada con monigotes (``puppets.py``) y, encima,
los esqueletos de verdad del juego (``overlay.py``), en verde, gris, rojo o amarillo. No sale
de ninguna foto ni de ninguna cámara.

``uv run --no-sync python ../scripts/juegos_demo.py --juego poses --puerto 8793``
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import numpy as np

from sonia.games.demo import Capture, GameMsg, Preview, Send, Step, Wait
from sonia.games.poses.bank import PoseEntry
from sonia.games.poses.game import HINT_CLOSE, PosesGame
from sonia.games.poses.overlay import Skeleton, Skeletons, Tint
from sonia.games.poses.puppets import DOWN, POSE_ARMS, ArmPose, puppet, puppet_points
from sonia.vision.contracts import (
    L_ANKLE,
    L_ELBOW,
    L_HIP,
    L_KNEE,
    L_SHOULDER,
    L_WRIST,
    NOSE,
    R_ANKLE,
    R_ELBOW,
    R_HIP,
    R_KNEE,
    R_SHOULDER,
    R_WRIST,
)

__all__ = ["steps"]

WIDTH, HEIGHT = 640, 360
ROUNDS = 6
WINDOW_S = 1.8

#: Las poses de la secuencia (como en el banco de la app).
POSES = {
    "brazos_arriba": PoseEntry("brazos_arriba", "Pasaron todos los tests", "brazos arriba"),
    "un_brazo": PoseEntry("un_brazo", "Subiendo a producción", "un brazo arriba"),
    "pose_t": PoseEntry("pose_t", "Pose T, la del avatar sin animar", "brazos en cruz"),
    "manos_cabeza": PoseEntry("manos_cabeza", "Deploy un viernes", "manos a la cabeza"),
    "biceps": PoseEntry("biceps", "Compiló a la primera", "saquen bíceps"),
    "barbilla": PoseEntry("barbilla", "Revisando el PR", "mano en la barbilla"),
}

#: Dónde está cada persona de la sala: centro, altura de los hombros y ancho de hombros (px).
SLOTS: tuple[tuple[float, float, float], ...] = (
    (112.0, 168.0, 40.0),
    (240.0, 176.0, 44.0),
    (378.0, 172.0, 42.0),
    (520.0, 166.0, 40.0),
)
#: Alguien pegado a la cámara (para la colocación).
CLOSE_SLOT = (470.0, 300.0, 210.0)

#: Ropa de cada persona (BGR), con los colores de Google algo apagados.
SHIRTS = ((170, 110, 50), (60, 70, 190), (40, 150, 200), (70, 140, 60), (120, 90, 140))
SKIN = ((150, 180, 220), (110, 140, 190), (80, 110, 160), (130, 160, 205), (95, 125, 175))
PANTS = (50, 45, 40)


def _state(phase: str, entry: PoseEntry | None = None, **fields: Any) -> dict[str, Any]:
    """El estado completo de la pantalla, como lo manda el juego (``PosesGame._state``)."""
    state: dict[str, Any] = {
        "phase": phase,
        "round": 0,
        "rounds": ROUNDS,
        "pose": entry.id if entry else "",
        "label": entry.label if entry else "",
        "meme": entry.meme if entry else "",
        "demo": entry.demo if entry else "",
        "order": "",
        "simon": True,
        "seconds": 0.0,
        "count": 0,
        "total": 0,
        "players": len(SLOTS),
        "hint": "",
        "done": 0,
        "possible": 0,
        "fell": 0,
    }
    state.update(fields)
    return state


# ---------------------------------------------------------------------------
# La sala sintética
# ---------------------------------------------------------------------------


def _room(frame: np.ndarray) -> None:
    """Fondo de sala: pared en degradado, un panel del stand y el suelo."""
    import cv2

    height, width = frame.shape[:2]
    top = np.array((58, 46, 38), dtype=np.float32)
    bottom = np.array((92, 80, 70), dtype=np.float32)
    ramp = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None, None]
    frame[:] = (top + (bottom - top) * ramp).astype(np.uint8)
    floor = int(height * 0.8)
    frame[floor:] = (66, 74, 84)
    cv2.rectangle(
        frame,
        (int(width * 0.06), int(height * 0.1)),
        (int(width * 0.3), int(height * 0.55)),
        (120, 72, 30),
        -1,
    )
    cv2.rectangle(
        frame,
        (int(width * 0.72), int(height * 0.08)),
        (int(width * 0.95), int(height * 0.5)),
        (40, 40, 140),
        -1,
    )


def _px(point: tuple[float, float], mirrored: bool) -> tuple[int, int]:
    x, y = point
    return round(WIDTH - x if mirrored else x), round(y)


def _body(
    frame: np.ndarray, pts: dict[int, tuple[float, float]], s: float, look: int, mirrored: bool
) -> None:
    """Una persona dibujada a brochazos sobre sus puntos (en píxeles, sin espejo)."""
    import cv2

    shirt = SHIRTS[look % len(SHIRTS)]
    skin = SKIN[look % len(SKIN)]
    limb = max(4, round(s * 0.28))
    p = {i: _px(xy, mirrored) for i, xy in pts.items()}
    for a, b in ((L_HIP, L_KNEE), (L_KNEE, L_ANKLE), (R_HIP, R_KNEE), (R_KNEE, R_ANKLE)):
        cv2.line(frame, p[a], p[b], PANTS, limb + 2, cv2.LINE_AA)
    torso = np.array([p[L_SHOULDER], p[R_SHOULDER], p[R_HIP], p[L_HIP]], dtype=np.int32)
    cv2.fillConvexPoly(frame, torso, shirt, cv2.LINE_AA)
    for a, b in ((L_SHOULDER, L_ELBOW), (R_SHOULDER, R_ELBOW)):
        cv2.line(frame, p[a], p[b], shirt, limb, cv2.LINE_AA)
    for a, b in ((L_ELBOW, L_WRIST), (R_ELBOW, R_WRIST)):
        cv2.line(frame, p[a], p[b], skin, max(3, limb - 2), cv2.LINE_AA)
    for wrist in (L_WRIST, R_WRIST):
        cv2.circle(frame, p[wrist], max(3, round(s * 0.13)), skin, -1, cv2.LINE_AA)
    neck = ((p[L_SHOULDER][0] + p[R_SHOULDER][0]) // 2, (p[L_SHOULDER][1] + p[R_SHOULDER][1]) // 2)
    cv2.line(frame, neck, p[NOSE], skin, max(3, round(s * 0.2)), cv2.LINE_AA)
    cv2.circle(
        frame,
        (p[NOSE][0], p[NOSE][1] - round(s * 0.08)),
        max(5, round(s * 0.32)),
        skin,
        -1,
        cv2.LINE_AA,
    )


def _scene(
    arms: Sequence[tuple[ArmPose, ArmPose]],
    tints: Sequence[Tint],
    *,
    close: bool = False,
) -> Callable[[np.ndarray, bool], None]:
    """La sala con una persona por hueco (con sus brazos) y sus esqueletos encima."""
    placed = [(slot, pair) for slot, pair in zip(SLOTS, arms, strict=False)]
    people = [
        puppet(left, right, cx=cx, sy=sy, s=s, width=WIDTH, height=HEIGHT)
        for (cx, sy, s), (left, right) in placed
    ]
    marks = [Skeleton(p, tint) for p, tint in zip(people, tints, strict=False)]
    if close:
        cx, sy, s = CLOSE_SLOT
        near = puppet(cx=cx, sy=sy, s=s, width=WIDTH, height=HEIGHT)
        marks.append(Skeleton(near, "close"))
    skeletons = Skeletons()
    skeletons.show(marks)

    def draw(frame: np.ndarray, mirrored: bool) -> None:
        _room(frame)
        for index, ((cx, sy, s), (left, right)) in enumerate(placed):
            _body(frame, puppet_points(left, right, cx=cx, sy=sy, s=s), s, index, mirrored)
        if close:
            cx, sy, s = CLOSE_SLOT
            _body(frame, puppet_points(cx=cx, sy=sy, s=s), s, 4, mirrored)
        skeletons.draw(frame, mirrored)

    return draw


def _rest(n: int = len(SLOTS)) -> list[tuple[ArmPose, ArmPose]]:
    return [(DOWN, DOWN)] * n


def _doing(pose: str, doers: int, n: int = len(SLOTS)) -> list[tuple[ArmPose, ArmPose]]:
    return [POSE_ARMS[pose] if i < doers else (DOWN, DOWN) for i in range(n)]


# ---------------------------------------------------------------------------
# Una ronda
# ---------------------------------------------------------------------------


def _round(
    number: int,
    pose: str,
    *,
    simon: bool,
    doing: int,
    shots: Sequence[str] = (),
    prefix: str = "",
) -> list[Step]:
    """Los pasos de una ronda; ``shots`` dice en qué momentos se captura (demo, orden,
    ventana, resultado), con el nombre ``<prefix>-<momento>``."""
    entry = POSES[pose]
    players = len(SLOTS)
    order = entry.order(simon)
    hit: Tint = "ok" if simon else "fell"
    steps: list[Step] = [
        GameMsg("round", _state("round", entry, round=number)),
        Preview(40.0, draw=_scene(_rest(), ["no"] * players)),
    ]
    steps.append(Capture(f"{prefix}-demo", settle_s=1.6) if "demo" in shots else Wait(1.4))
    steps += [
        GameMsg("command", _state("command", entry, round=number, order=order, simon=simon)),
        Send({"type": "transcript", "role": "assistant", "text": order, "final": True}),
    ]
    steps.append(Capture(f"{prefix}-orden", settle_s=1.0) if "orden" in shots else Wait(2.2))
    tints: list[Tint] = [hit if i < doing else "no" for i in range(players)]
    steps += [
        GameMsg(
            "window",
            _state("window", entry, round=number, order=order, simon=simon, seconds=WINDOW_S),
        ),
        Preview(40.0, draw=_scene(_doing(pose, doing), tints)),
    ]
    steps.append(
        Capture(f"{prefix}-ventana", settle_s=0.9) if "ventana" in shots else Wait(WINDOW_S)
    )
    steps.append(
        GameMsg(
            "result",
            _state(
                "result", entry, round=number, order=order, simon=simon, count=doing, total=players
            ),
        )
    )
    steps.append(
        Capture(f"{prefix}-resultado", settle_s=1.2) if "resultado" in shots else Wait(1.5)
    )
    return steps


def steps() -> list[Step]:
    players = len(SLOTS)
    out: list[Step] = [
        GameMsg("start", {"title": PosesGame.title, "rounds": ROUNDS}),
        Preview(40.0, draw=_scene(_rest(), ["no"] * players, close=True)),
        GameMsg("placement", _state("placement", players=players, hint=HINT_CLOSE)),
        Capture("poses-01-colocacion", settle_s=2.0),
        GameMsg("placement", _state("placement", players=players)),
        Wait(1.0),
    ]
    # Ronda 1: brazos arriba, 3 de 4 (demostración, orden, ventana y acierto).
    out += _round(
        1,
        "brazos_arriba",
        simon=True,
        doing=3,
        shots=("demo", "orden", "ventana", "resultado"),
        prefix="poses-02-brazos_arriba",
    )
    # Ronda 2: pose T, solo 1 de 4 (fallo).
    out += _round(
        2, "pose_t", simon=True, doing=1, shots=("demo", "resultado"), prefix="poses-03-pose_t"
    )
    # Ronda 3: trampa con las manos a la cabeza: caen 2.
    out += _round(
        3,
        "manos_cabeza",
        simon=False,
        doing=2,
        shots=("demo", "orden", "ventana", "resultado"),
        prefix="poses-04-trampa-manos_cabeza",
    )
    # Rondas 4 a 6: las demás demostraciones de Sonnia.
    out += _round(
        4, "un_brazo", simon=True, doing=4, shots=("demo", "resultado"), prefix="poses-05-un_brazo"
    )
    out += _round(5, "biceps", simon=True, doing=2, shots=("demo",), prefix="poses-06-biceps")
    out += _round(6, "barbilla", simon=True, doing=3, shots=("demo",), prefix="poses-07-barbilla")
    final = _state("final", players=players, done=17, possible=24, fell=2)
    out += [
        GameMsg("final", final),
        # Como de verdad: la vista en vivo se apaga al soltar la partida, antes del «end».
        Preview(3.0, draw=_scene(_rest(), ["no"] * players), off=True),
        Capture("poses-08-final", settle_s=2.0),
        Wait(1.5),
        GameMsg("end", {**final, "result": "win"}),
        Capture("poses-09-fin", settle_s=1.5),
    ]
    return out
