"""Monigotes inventados: personas de frente con sus 17 puntos puestos a mano.

Para probar las reglas sin cámara (``tests/games/test_poses*.py``) y para la vista en vivo
sintética del orquestador falso (``demo.py``). No sale de ninguna foto ni de nadie.

Cada brazo es ``(codo, muñeca)`` en anchos de hombros (``S``) desde su hombro: ``x``
positiva es hacia fuera del cuerpo e ``y`` positiva, hacia abajo.
"""

from __future__ import annotations

from collections.abc import Mapping

from sonia.vision.contracts import (
    BODY_POINTS,
    L_ANKLE,
    L_EAR,
    L_ELBOW,
    L_EYE,
    L_HIP,
    L_KNEE,
    L_SHOULDER,
    L_WRIST,
    NOSE,
    R_ANKLE,
    R_EAR,
    R_ELBOW,
    R_EYE,
    R_HIP,
    R_KNEE,
    R_SHOULDER,
    R_WRIST,
    Person,
    Point,
)

__all__ = [
    "BICEPS",
    "CHIN",
    "CROSSED",
    "DOWN",
    "HEAD_SIDE",
    "HEAD_TOP",
    "HIPS",
    "PHONE",
    "POCKET",
    "POSE_ARMS",
    "T",
    "T_LOW",
    "UP",
    "UP_V",
    "WAIST_PHONE",
    "ArmPose",
    "puppet",
    "puppet_points",
]

ArmPose = tuple[tuple[float, float], tuple[float, float]]

DOWN: ArmPose = ((0.05, 0.84), (0.1, 1.45))
UP: ArmPose = ((0.0, -0.84), (0.0, -1.5))
UP_V: ArmPose = ((0.42, -0.73), (0.75, -1.3))
T: ArmPose = ((0.84, 0.0), (1.5, 0.0))
#: Pose T unos 20° por debajo de la horizontal.
T_LOW: ArmPose = ((0.79, 0.29), (1.41, 0.51))
HEAD_TOP: ArmPose = ((0.55, -0.3), (-0.25, -0.75))
HEAD_SIDE: ArmPose = ((0.6, -0.15), (-0.2, -0.45))
BICEPS: ArmPose = ((0.8, -0.05), (0.75, -0.7))
CHIN: ArmPose = ((0.05, 0.8), (-0.4, 0.05))
CROSSED: ArmPose = ((0.15, 0.85), (-0.9, 0.7))
POCKET: ArmPose = ((0.2, 0.8), (0.05, 1.35))
HIPS: ArmPose = ((0.55, 0.65), (0.0, 1.25))
PHONE: ArmPose = ((0.05, 0.85), (-0.35, 0.45))
WAIST_PHONE: ArmPose = ((0.1, 0.9), (-0.3, 0.75))

#: Los brazos (izquierdo, derecho) de cada pose del juego.
POSE_ARMS: dict[str, tuple[ArmPose, ArmPose]] = {
    "brazos_arriba": (UP_V, UP_V),
    "un_brazo": (UP, DOWN),
    "pose_t": (T, T),
    "manos_cabeza": (HEAD_TOP, HEAD_TOP),
    "biceps": (BICEPS, BICEPS),
    "barbilla": (DOWN, CHIN),
}


def puppet_points(
    left: ArmPose = DOWN,
    right: ArmPose = DOWN,
    *,
    cx: float = 320.0,
    sy: float = 150.0,
    s: float = 60.0,
) -> dict[int, tuple[float, float]]:
    """Los 17 puntos en píxeles de un monigote de frente: hombros a la altura ``sy``, centrado
    en ``cx`` y con ``s`` píxeles entre hombros. Su izquierda sale a la derecha de la imagen
    (sin espejo)."""
    pts: dict[int, tuple[float, float]] = {
        NOSE: (cx, sy - 0.4 * s),
        L_EYE: (cx + 0.09 * s, sy - 0.48 * s),
        R_EYE: (cx - 0.09 * s, sy - 0.48 * s),
        L_EAR: (cx + 0.2 * s, sy - 0.42 * s),
        R_EAR: (cx - 0.2 * s, sy - 0.42 * s),
        L_SHOULDER: (cx + 0.5 * s, sy),
        R_SHOULDER: (cx - 0.5 * s, sy),
        L_HIP: (cx + 0.3 * s, sy + 1.3 * s),
        R_HIP: (cx - 0.3 * s, sy + 1.3 * s),
        L_KNEE: (cx + 0.3 * s, sy + 2.4 * s),
        R_KNEE: (cx - 0.3 * s, sy + 2.4 * s),
        L_ANKLE: (cx + 0.3 * s, sy + 3.4 * s),
        R_ANKLE: (cx - 0.3 * s, sy + 3.4 * s),
    }
    for arm, sign, (shoulder, elbow, wrist) in (
        (left, 1.0, (L_SHOULDER, L_ELBOW, L_WRIST)),
        (right, -1.0, (R_SHOULDER, R_ELBOW, R_WRIST)),
    ):
        sx, ssy = pts[shoulder]
        (ex, ey), (wx, wy) = arm
        pts[elbow] = (sx + sign * ex * s, ssy + ey * s)
        pts[wrist] = (sx + sign * wx * s, ssy + wy * s)
    return pts


def puppet(
    left: ArmPose = DOWN,
    right: ArmPose = DOWN,
    *,
    cx: float = 320.0,
    sy: float = 150.0,
    s: float = 60.0,
    width: int = 640,
    height: int = 360,
    hide: tuple[int, ...] = (),
    flip: bool = False,
    score: float = 0.9,
) -> Person:
    """Un monigote como lo daría el detector: puntos de 0 a 1 sobre la imagen sin espejo.

    ``hide``: puntos que no se ven. ``flip``: la imagen al revés sin cambiar los nombres de los
    puntos (como si el detector confundiera los lados).
    """
    pts = puppet_points(left, right, cx=cx, sy=sy, s=s)
    shown: Mapping[int, tuple[float, float]] = {
        index: ((width - x if flip else x) / width, y / height)
        for index, (x, y) in pts.items()
        if index not in hide
    }
    points = tuple(
        Point(shown[i][0], shown[i][1], score) if i in shown else Point(0.0, 0.0, 0.0)
        for i in range(len(BODY_POINTS))
    )
    xs = [x for x, _ in shown.values()] or [0.0]
    ys = [y for _, y in shown.values()] or [0.0]
    box = (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
    return Person(box=box, score=score, points=points)
