"""Las reglas de las seis poses de «Simón dice» (``docs/juegos/poses.md``, plan 5.2).

Funciones puras sobre las personas que da el detector de poses
(:class:`~sonia.vision.contracts.PoseFrame`): no guardan nada ni reconocen a nadie.

- **Todo relativo al cuerpo.** Las coordenadas del frame (0 a 1 sobre la imagen sin espejo)
  se pasan a píxeles con su ancho y su alto, para que los ángulos valgan igual en los dos
  ejes, y cada distancia se mide en anchos de hombros (``S``) desde los hombros, la nariz o
  la cabeza de esa persona. Nunca posiciones absolutas en la imagen: vale igual de cerca que
  de lejos y en cualquier sitio del encuadre.
- **Permisivas.** El veredicto es colectivo y generoso: si falta la muñeca, cuenta el codo;
  en las poses de dos brazos, un brazo que no se ve no cuenta en contra (en un grupo
  apretado los brazos se tapan). Mejor contar de más que de menos.
- **Que no salten en reposo.** Brazos caídos, cruzados, en los bolsillos, en la cintura o
  el móvil en la mano a la altura del pecho no hacen ninguna pose (hay tests).

Proporciones de referencia (adulto de 1,70 m, ``S`` ≈ 38 cm entre hombros): la nariz va
unos 0,4 S por encima de la línea de los hombros, la barbilla 0,2 S y la coronilla 0,8 S;
del hombro al codo hay 0,85 S y del hombro a la muñeca, 1,5 S.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from sonia.vision.contracts import (
    L_EAR,
    L_ELBOW,
    L_EYE,
    L_HIP,
    L_SHOULDER,
    L_WRIST,
    NOSE,
    R_EAR,
    R_ELBOW,
    R_EYE,
    R_HIP,
    R_SHOULDER,
    R_WRIST,
    Person,
    PoseFrame,
)

__all__ = [
    "MIN_POINT_SCORE",
    "POSE_IDS",
    "Arm",
    "Body",
    "FrameCount",
    "Mark",
    "Placement",
    "body_of",
    "count_frame",
    "does_pose",
    "is_player",
    "placement_of",
    "too_close",
]

#: Las poses que sabe detectar el juego, en el orden del plan. Una pose nueva necesita su
#: regla aquí (el banco solo cambia frases, instrucciones y cuáles están activas).
POSE_IDS: tuple[str, ...] = (
    "brazos_arriba",
    "un_brazo",
    "pose_t",
    "manos_cabeza",
    "biceps",
    "barbilla",
)

#: Confianza mínima de un punto para darlo por visto.
MIN_POINT_SCORE = 0.35

#: Menos de esto (en píxeles) entre hombros: la persona está demasiado lejos para medirla.
MIN_SCALE_PX = 6.0

# -- escala y cabeza --------------------------------------------------------------

#: Del centro de los hombros al de las caderas hay entre 1,5 y 1,8 S (con los hombros del
#: detector, algo por dentro de los de verdad): con los hombros de perfil (encogidos en la
#: imagen), el torso da una escala más fiel. Se divide de más a propósito para que solo mande
#: cuando los hombros salen muy encogidos: con 1,6, en una foto pública de frente con el
#: torso largo los brazos arriba no llegaban.
TORSO_PER_SHOULDER = 2.0
#: Entre orejas hay unos 0,45 S (mismo uso que el torso: se divide de más). Con 0,5, en
#: los primeros planos la escala salía inflada (foto pública de un doble bíceps).
EARS_PER_SHOULDER = 0.6
#: Sin nariz: los ojos van un poco más arriba y las orejas casi a su altura.
NOSE_BELOW_EYES = 0.08
NOSE_BELOW_EARS = 0.05
#: Sin cara: la nariz se supone a esta altura sobre los hombros.
NOSE_ABOVE_SHOULDERS = 0.4

# -- brazos arriba (brazos_arriba, un_brazo) ------------------------------------------

#: La muñeca, al menos esto por encima de la nariz (la coronilla queda a unos 0,4 S): con
#: los brazos arriba va a 1,1 S; abiertos en V a 45°, a 0,65 S.
UP_WRIST_ABOVE_NOSE = 0.45
#: Y el codo (si se ve), al menos esto por encima del hombro: con las manos en la cabeza
#: los codos quedan casi a la altura de los hombros, así que no cuentan como arriba. Con
#: 0,4 se perdía la celebración con los puños arriba y los codos doblados (foto pública de
#: un remero, 10 de octubre de 2026).
UP_ELBOW_ABOVE_SHOULDER = 0.25
#: Sin muñeca, el codo tiene que pasar de la nariz.
UP_ELBOW_ABOVE_NOSE = 0.1

# -- pose T ---------------------------------------------------------------------------

#: Ángulo máximo del brazo (del hombro a la muñeca, o al codo) con la horizontal (plan: 35°).
T_MAX_ANGLE_DEG = 35.0
#: El brazo estirado hacia fuera: la muñeca al menos a esto del hombro (estirado, 1,5 S)...
T_MIN_REACH_WRIST = 0.85
#: ...o el codo, si no se ve la muñeca (el brazo, 0,85 S).
T_MIN_REACH_ELBOW = 0.45
#: Con codo y muñeca, el brazo no puede ir muy doblado (180° es recto).
T_MIN_ELBOW_ANGLE_DEG = 130.0

# -- manos a la cabeza ----------------------------------------------------------------

#: El centro de la cabeza, por encima de la nariz.
HEAD_CENTER_ABOVE_NOSE = 0.15
#: La muñeca, como mucho a esto del centro de la cabeza.
HEAD_REACH = 0.85
#: Y no más abajo que esto bajo la nariz (la barbilla está a 0,2 S): el móvil en el pecho no
#: es la cabeza.
HEAD_LOWEST_BELOW_NOSE = 0.3
#: Ni más arriba que esto sobre la nariz (la coronilla está a 0,4 S): los brazos estirados
#: hacia arriba junto a la cabeza no son las manos en la cabeza.
HEAD_HIGHEST_ABOVE_NOSE = 0.6
#: Sin muñeca: el codo levantado por encima del hombro...
HEAD_ELBOW_ABOVE_SHOULDER = 0.1
#: ...pero sin llegar a lo de los brazos arriba.
HEAD_ELBOW_MAX_ABOVE_NOSE = 0.25

# -- bíceps ---------------------------------------------------------------------------

#: El codo a la altura del hombro, con este margen arriba o abajo.
BICEPS_ELBOW_BAND = 0.45
#: Y abierto hacia fuera del hombro al menos esto.
BICEPS_ELBOW_OUT = 0.3
#: La muñeca, por encima del codo al menos esto (el detector pone a veces la muñeca a media
#: altura del antebrazo cuando este va hacia la cámara)...
BICEPS_WRIST_ABOVE_ELBOW = 0.15
#: ...con el antebrazo más vertical que horizontal (con las manos en la cabeza, el
#: antebrazo va hacia dentro y se queda tumbado).
BICEPS_FOREARM_MAX_FROM_VERTICAL_DEG = 45.0

# -- barbilla ---------------------------------------------------------------------------

#: La muñeca por debajo de la nariz y como mucho esto por debajo de la línea de los hombros
#: (con la mano en la barbilla queda casi en esa línea; el móvil en el pecho, a 0,3 S o más).
CHIN_LOWEST_BELOW_SHOULDER = 0.2
#: Y cerca del centro de la cara en horizontal.
CHIN_REACH_X = 0.45

# -- quién juega y colocación -----------------------------------------------------------

#: Hombros más anchos que esto (fracción del ancho de la imagen): demasiado cerca (a menos
#: de un metro, con una webcam normal). Para la pose T a 2 m caben de sobra.
CLOSE_SHOULDER_SHARE = 0.3
#: Hombros más anchos que esto y sin ninguna muñeca a la vista: pegado (los brazos se salen).
CLOSE_NO_WRISTS_SHOULDER_SHARE = 0.18
#: Sin sitio para levantar los brazos: la nariz a menos de esto (en S) del borde de arriba.
CLOSE_HEAD_ROOM = 0.5
#: Sin hombros a la vista pero con la caja así de alta: solo se le ve la cara.
CLOSE_FACE_BOX = 0.45

Side = Literal["izquierda", "derecha"]
_ARM_POINTS: dict[Side, tuple[int, int, int]] = {
    "izquierda": (L_SHOULDER, L_ELBOW, L_WRIST),
    "derecha": (R_SHOULDER, R_ELBOW, R_WRIST),
}

XY = tuple[float, float]


@dataclass(frozen=True, slots=True)
class Arm:
    """Un brazo en píxeles: el hombro siempre; codo y muñeca si se ven."""

    shoulder: XY
    elbow: XY | None
    wrist: XY | None

    @property
    def seen(self) -> bool:
        """¿Se ve algo del brazo además del hombro?"""
        return self.elbow is not None or self.wrist is not None


@dataclass(frozen=True, slots=True)
class Body:
    """Una persona medible: en píxeles, con su escala (``scale``, el ancho de hombros ``S``)."""

    points: dict[int, XY]
    scale: float
    mid_x: float
    shoulder_y: float
    nose: XY
    width: int
    height: int

    def arm(self, side: Side) -> Arm:
        shoulder, elbow, wrist = _ARM_POINTS[side]
        return Arm(self.points[shoulder], self.points.get(elbow), self.points.get(wrist))

    def arms(self) -> tuple[Arm, Arm]:
        return self.arm("izquierda"), self.arm("derecha")

    def outward(self, arm: Arm) -> float:
        """+1 o -1: hacia dónde queda «fuera del cuerpo» en x para ese brazo."""
        return 1.0 if arm.shoulder[0] >= self.mid_x else -1.0


def _visible(person: Person, width: int, height: int) -> dict[int, XY]:
    return {
        index: (point.x * width, point.y * height)
        for index, point in enumerate(person.points)
        if point.score >= MIN_POINT_SCORE
    }


def _mid(a: XY, b: XY) -> XY:
    return (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0


def _dist(a: XY, b: XY) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def body_of(person: Person, width: int, height: int) -> Body | None:
    """La persona medible, o ``None`` si no se le ven los dos hombros (o está muy lejos)."""
    if width <= 0 or height <= 0:
        return None
    pts = _visible(person, width, height)
    left, right = pts.get(L_SHOULDER), pts.get(R_SHOULDER)
    if left is None or right is None:
        return None
    shoulders = _mid(left, right)
    scale = _dist(left, right)
    hips = [pts[i] for i in (L_HIP, R_HIP) if i in pts]
    if hips:
        hip = (sum(x for x, _ in hips) / len(hips), sum(y for _, y in hips) / len(hips))
        scale = max(scale, _dist(shoulders, hip) / TORSO_PER_SHOULDER)
    if L_EAR in pts and R_EAR in pts:
        scale = max(scale, _dist(pts[L_EAR], pts[R_EAR]) / EARS_PER_SHOULDER)
    if scale < MIN_SCALE_PX:
        return None
    nose = pts.get(NOSE)
    if nose is None:
        if L_EYE in pts and R_EYE in pts:
            eyes = _mid(pts[L_EYE], pts[R_EYE])
            nose = (eyes[0], eyes[1] + NOSE_BELOW_EYES * scale)
        elif L_EAR in pts and R_EAR in pts:
            ears = _mid(pts[L_EAR], pts[R_EAR])
            nose = (ears[0], ears[1] + NOSE_BELOW_EARS * scale)
        else:
            nose = (shoulders[0], shoulders[1] - NOSE_ABOVE_SHOULDERS * scale)
    return Body(
        points=pts,
        scale=scale,
        mid_x=shoulders[0],
        shoulder_y=shoulders[1],
        nose=nose,
        width=width,
        height=height,
    )


# ---------------------------------------------------------------------------
# Cada brazo: True (lo hace), False (no lo hace) o None (no se ve)
# ---------------------------------------------------------------------------


def _arm_up(body: Body, arm: Arm) -> bool | None:
    """¿Brazo arriba, por encima de la cabeza? Sin muñeca, cuenta el codo."""
    s = body.scale
    if arm.wrist is not None:
        if arm.wrist[1] >= body.nose[1] - UP_WRIST_ABOVE_NOSE * s:
            return False
        return arm.elbow is None or arm.elbow[1] < arm.shoulder[1] - UP_ELBOW_ABOVE_SHOULDER * s
    if arm.elbow is not None:
        return arm.elbow[1] < body.nose[1] - UP_ELBOW_ABOVE_NOSE * s
    return None


def _angle_at(vertex: XY, a: XY, b: XY) -> float:
    """Ángulo en ``vertex`` entre ``a`` y ``b``, en grados (180: en línea recta)."""
    ax, ay = a[0] - vertex[0], a[1] - vertex[1]
    bx, by = b[0] - vertex[0], b[1] - vertex[1]
    na, nb = math.hypot(ax, ay), math.hypot(bx, by)
    if na == 0 or nb == 0:
        return 0.0
    cos = max(-1.0, min(1.0, (ax * bx + ay * by) / (na * nb)))
    return math.degrees(math.acos(cos))


def _arm_t(body: Body, arm: Arm) -> bool | None:
    """¿Brazo en cruz: estirado hacia fuera y a menos de 35° de la horizontal?"""
    s = body.scale
    if arm.wrist is not None:
        end, reach = arm.wrist, T_MIN_REACH_WRIST
    elif arm.elbow is not None:
        end, reach = arm.elbow, T_MIN_REACH_ELBOW
    else:
        return None
    dx, dy = end[0] - arm.shoulder[0], end[1] - arm.shoulder[1]
    if dx * body.outward(arm) <= 0:
        return False
    if math.hypot(dx, dy) < reach * s:
        return False
    if math.degrees(math.atan2(abs(dy), abs(dx))) > T_MAX_ANGLE_DEG:
        return False
    if arm.wrist is not None and arm.elbow is not None:
        return _angle_at(arm.elbow, arm.shoulder, arm.wrist) >= T_MIN_ELBOW_ANGLE_DEG
    return True


def _hand_on_head(body: Body, arm: Arm) -> bool | None:
    """¿Mano en la cabeza (encima o a los lados)? Sin muñeca, el codo levantado."""
    s = body.scale
    nose_x, nose_y = body.nose
    if arm.wrist is not None:
        head = (nose_x, nose_y - HEAD_CENTER_ABOVE_NOSE * s)
        if _dist(arm.wrist, head) > HEAD_REACH * s:
            return False
        wy = arm.wrist[1]
        return nose_y - HEAD_HIGHEST_ABOVE_NOSE * s <= wy <= nose_y + HEAD_LOWEST_BELOW_NOSE * s
    if arm.elbow is not None:
        above_shoulder = arm.elbow[1] < arm.shoulder[1] - HEAD_ELBOW_ABOVE_SHOULDER * s
        below_raised = arm.elbow[1] > nose_y - HEAD_ELBOW_MAX_ABOVE_NOSE * s
        return above_shoulder and below_raised
    return None


def _arm_biceps(body: Body, arm: Arm) -> bool | None:
    """¿Bíceps: codo a la altura del hombro y abierto, muñeca por encima del codo?"""
    s = body.scale
    if arm.elbow is None:
        return None if arm.wrist is None else False
    ex, ey = arm.elbow
    if abs(ey - arm.shoulder[1]) > BICEPS_ELBOW_BAND * s:
        return False
    out = (ex - arm.shoulder[0]) * body.outward(arm)
    if out < BICEPS_ELBOW_OUT * s:
        return False
    if arm.wrist is None:
        return True
    wx, wy = arm.wrist
    rise = ey - wy
    if rise < BICEPS_WRIST_ABOVE_ELBOW * s:
        return False
    return math.degrees(math.atan2(abs(wx - ex), rise)) <= BICEPS_FOREARM_MAX_FROM_VERTICAL_DEG


def _hand_on_chin(body: Body, arm: Arm) -> bool:
    """¿Mano en la barbilla: muñeca bajo la nariz, cerca de la cara y con el codo debajo?

    Aquí el codo solo no dice nada (cruzar los brazos lo pone igual), así que sin muñeca no
    cuenta.
    """
    if arm.wrist is None:
        return False
    s = body.scale
    wx, wy = arm.wrist
    nose_x, nose_y = body.nose
    if wy <= nose_y or wy > arm.shoulder[1] + CHIN_LOWEST_BELOW_SHOULDER * s:
        return False
    if abs(wx - nose_x) > CHIN_REACH_X * s:
        return False
    return arm.elbow is None or arm.elbow[1] > wy


def _both(left: bool | None, right: bool | None) -> bool:
    """Los dos brazos lo hacen; uno que no se ve no cuenta en contra (pero uno tiene que verse)."""
    return (
        (left is True or left is None)
        and (right is True or right is None)
        and (left is True or right is True)
    )


def _brazos_arriba(body: Body) -> bool:
    left, right = body.arms()
    return _both(_arm_up(body, left), _arm_up(body, right))


def _un_brazo(body: Body) -> bool:
    left, right = (_arm_up(body, arm) for arm in body.arms())
    return (left is True) != (right is True)


def _pose_t(body: Body) -> bool:
    left, right = body.arms()
    return _both(_arm_t(body, left), _arm_t(body, right))


def _manos_cabeza(body: Body) -> bool:
    left, right = body.arms()
    return _both(_hand_on_head(body, left), _hand_on_head(body, right))


def _biceps(body: Body) -> bool:
    left, right = body.arms()
    return _both(_arm_biceps(body, left), _arm_biceps(body, right))


def _barbilla(body: Body) -> bool:
    return any(_hand_on_chin(body, arm) for arm in body.arms())


_RULES: dict[str, Callable[[Body], bool]] = {
    "brazos_arriba": _brazos_arriba,
    "un_brazo": _un_brazo,
    "pose_t": _pose_t,
    "manos_cabeza": _manos_cabeza,
    "biceps": _biceps,
    "barbilla": _barbilla,
}


def does_pose(body: Body, pose: str) -> bool:
    """¿Hace ``body`` la pose ``pose``? Una pose sin regla nunca se da por hecha."""
    rule = _RULES.get(pose)
    return rule(body) if rule is not None else False


# ---------------------------------------------------------------------------
# Quién juega, colocación y recuento de un frame
# ---------------------------------------------------------------------------


def is_player(person: Person, min_height: float) -> bool:
    """¿Juega? Su caja ocupa al menos ``min_height`` de la altura de la imagen
    (``GAME_POSES_MIN_PERSON``): la gente del fondo o de paso no cuenta."""
    return person.box[3] >= min_height


def too_close(person: Person, width: int, height: int, body: Body | None = None) -> bool:
    """¿Está demasiado cerca para jugar (hasta unos 2 m)? Lo mira la colocación.

    - Hombros muy anchos en la imagen.
    - Hombros a la vista sin ninguna muñeca (los brazos se salen del encuadre).
    - La cabeza pegada al borde de arriba: los brazos levantados no caben.
    - Sin hombros pero con una caja enorme: solo se le ve la cara.

    ``body``: el de :func:`body_of` si ya se tiene.
    """
    if body is None:
        body = body_of(person, width, height)
    if body is None:
        return person.box[3] >= CLOSE_FACE_BOX and NOSE in _visible(person, width, height)
    share = body.scale / width
    if share >= CLOSE_SHOULDER_SHARE:
        return True
    no_wrists = L_WRIST not in body.points and R_WRIST not in body.points
    if share >= CLOSE_NO_WRISTS_SHOULDER_SHARE and no_wrists:
        return True
    return body.nose[1] < CLOSE_HEAD_ROOM * body.scale


@dataclass(frozen=True, slots=True)
class Placement:
    """Cómo están colocados: cuántos juegan y cuántos están demasiado cerca."""

    players: int
    close: int

    @property
    def ready(self) -> bool:
        return self.players > 0 and self.close == 0


#: Cómo sale cada persona en la vista en vivo: hace la pose, no la hace o está muy cerca.
Mark = Literal["ok", "no", "close"]


@dataclass(frozen=True, slots=True)
class FrameCount:
    """El recuento de un frame: cuántos hacen la pose de cuántos juegan, cuántos están
    demasiado cerca y la marca de cada persona que se dibuja."""

    doing: int
    players: int
    close: int
    marks: tuple[tuple[Person, Mark], ...]

    @property
    def placement(self) -> Placement:
        return Placement(self.players, self.close)


def count_frame(frame: PoseFrame | None, pose: str | None, min_height: float) -> FrameCount:
    """Cuenta quién hace ``pose`` entre quienes juegan (``None``: nadie la hace, todos en gris).

    Juegan las personas medibles (con los dos hombros) que llegan a ``min_height``. Quien está
    demasiado cerca sigue jugando si se le puede medir, pero sale en naranja si no hace la pose
    (para que se aparte); si solo se le ve la cara, no juega.
    """
    if frame is None:
        return FrameCount(0, 0, 0, ())
    doing = players = close = 0
    marks: list[tuple[Person, Mark]] = []
    for person in frame.people:
        body = body_of(person, frame.width, frame.height)
        near = too_close(person, frame.width, frame.height, body)
        if near:
            close += 1
        if body is None or not is_player(person, min_height):
            if near:
                marks.append((person, "close"))
            continue
        players += 1
        if pose is not None and does_pose(body, pose):
            doing += 1
            marks.append((person, "ok"))
        else:
            marks.append((person, "close" if near else "no"))
    return FrameCount(doing, players, close, tuple(marks))


def placement_of(frame: PoseFrame | None, min_height: float) -> Placement:
    """La colocación en un frame (sin frame, nadie)."""
    return count_frame(frame, None, min_height).placement
