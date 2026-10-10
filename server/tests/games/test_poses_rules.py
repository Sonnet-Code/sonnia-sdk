"""Reglas de las poses de «Simón dice» con personas inventadas (``sonia.games.poses.rules``).

Cada persona es un monigote de frente a la cámara con sus 17 puntos puestos a mano en
anchos de hombros (``S``) desde sus hombros, como los daría el detector. Se prueba que
cada pose salta con la suya, que no salta con las demás y que nada salta con la gente en
reposo (brazos caídos, cruzados, en los bolsillos, en jarras o con el móvil en la mano).
"""

from __future__ import annotations

import pytest

from sonia.games.poses.rules import (
    POSE_IDS,
    body_of,
    count_frame,
    does_pose,
    is_player,
    placement_of,
    too_close,
)
from sonia.vision.contracts import (
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
)
from tests.games.fakes import person, pose_frame

WIDTH, HEIGHT = 640, 360

#: Un brazo: (codo, muñeca) en S desde su hombro; x positiva = hacia fuera del cuerpo,
#: y positiva = hacia abajo.
ArmPose = tuple[tuple[float, float], tuple[float, float]]

DOWN: ArmPose = ((0.05, 0.84), (0.1, 1.45))
UP: ArmPose = ((0.0, -0.84), (0.0, -1.5))
UP_V: ArmPose = ((0.42, -0.73), (0.75, -1.3))
T: ArmPose = ((0.84, 0.0), (1.5, 0.0))
T_LOW: ArmPose = ((0.79, 0.29), (1.41, 0.51))  # 20° por debajo de la horizontal
HEAD_TOP: ArmPose = ((0.55, -0.3), (-0.25, -0.75))
HEAD_SIDE: ArmPose = ((0.6, -0.15), (-0.2, -0.45))
BICEPS: ArmPose = ((0.8, -0.05), (0.75, -0.7))
CHIN: ArmPose = ((0.05, 0.8), (-0.4, 0.05))
CROSSED: ArmPose = ((0.15, 0.85), (-0.9, 0.7))
POCKET: ArmPose = ((0.2, 0.8), (0.05, 1.35))
HIPS: ArmPose = ((0.55, 0.65), (0.0, 1.25))
PHONE: ArmPose = ((0.05, 0.85), (-0.35, 0.45))
WAIST_PHONE: ArmPose = ((0.1, 0.9), (-0.3, 0.75))


def puppet(
    left: ArmPose = DOWN,
    right: ArmPose = DOWN,
    *,
    cx: float = 320.0,
    sy: float = 150.0,
    s: float = 60.0,
    hide: tuple[int, ...] = (),
    flip: bool = False,
) -> Person:
    """Un monigote de frente: hombros en ``sy``, centro en ``cx`` y ``s`` píxeles entre hombros.

    La izquierda de la persona sale a la derecha de la imagen (sin espejo). ``flip`` da la
    vuelta a la imagen sin cambiar los nombres de los puntos (como si el detector confundiera
    los lados): las reglas tienen que dar lo mismo.
    """
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
        sx, sy_ = pts[shoulder]
        (ex, ey), (wx, wy) = arm
        pts[elbow] = (sx + sign * ex * s, sy_ + ey * s)
        pts[wrist] = (sx + sign * wx * s, sy_ + wy * s)
    normalized = {
        index: ((WIDTH - x if flip else x) / WIDTH, y / HEIGHT)
        for index, (x, y) in pts.items()
        if index not in hide
    }
    return person(normalized)


def poses_of(p: Person) -> set[str]:
    body = body_of(p, WIDTH, HEIGHT)
    assert body is not None
    return {pose for pose in POSE_IDS if does_pose(body, pose)}


# ---------------------------------------------------------------------------
# Cada pose salta con la suya y no con las demás
# ---------------------------------------------------------------------------

CASES: list[tuple[str, Person, set[str]]] = [
    ("brazos arriba", puppet(UP, UP), {"brazos_arriba"}),
    ("brazos arriba en V", puppet(UP_V, UP_V), {"brazos_arriba"}),
    ("un brazo (izquierdo)", puppet(UP, DOWN), {"un_brazo"}),
    ("un brazo (derecho, en V)", puppet(DOWN, UP_V), {"un_brazo"}),
    ("pose T", puppet(T, T), {"pose_t"}),
    ("pose T algo caída", puppet(T_LOW, T_LOW), {"pose_t"}),
    ("manos encima de la cabeza", puppet(HEAD_TOP, HEAD_TOP), {"manos_cabeza"}),
    ("manos a los lados de la cabeza", puppet(HEAD_SIDE, HEAD_SIDE), {"manos_cabeza"}),
    ("bíceps", puppet(BICEPS, BICEPS), {"biceps"}),
    ("mano derecha en la barbilla", puppet(DOWN, CHIN), {"barbilla"}),
    ("mano izquierda en la barbilla", puppet(CHIN, CROSSED), {"barbilla"}),
]


@pytest.mark.parametrize(("name", "who", "expected"), CASES, ids=[c[0] for c in CASES])
def test_cada_pose_salta_con_la_suya_y_solo_con_ella(
    name: str, who: Person, expected: set[str]
) -> None:
    assert poses_of(who) == expected, name


@pytest.mark.parametrize(("name", "who", "expected"), CASES, ids=[c[0] for c in CASES])
def test_da_igual_de_que_lado_salga_en_la_imagen(
    name: str, who: Person, expected: set[str]
) -> None:
    # La misma persona con la imagen al revés y los nombres de los lados sin cambiar.
    flipped = Person(
        box=who.box,
        score=who.score,
        points=tuple(
            type(pt)(1.0 - pt.x, pt.y, pt.score) if pt.score > 0 else pt for pt in who.points
        ),
    )
    assert poses_of(flipped) == expected, name


@pytest.mark.parametrize(("cx", "sy", "s"), [(120.0, 90.0, 30.0), (500.0, 200.0, 45.0)])
def test_vale_en_cualquier_sitio_y_tamano(cx: float, sy: float, s: float) -> None:
    assert poses_of(puppet(UP, UP, cx=cx, sy=sy, s=s)) == {"brazos_arriba"}
    assert poses_of(puppet(T, T, cx=cx, sy=sy, s=s)) == {"pose_t"}
    assert poses_of(puppet(BICEPS, BICEPS, cx=cx, sy=sy, s=s)) == {"biceps"}
    assert poses_of(puppet(DOWN, DOWN, cx=cx, sy=sy, s=s)) == set()


# ---------------------------------------------------------------------------
# En reposo no salta nada
# ---------------------------------------------------------------------------

REST: list[tuple[str, Person]] = [
    ("brazos caídos", puppet(DOWN, DOWN)),
    ("brazos cruzados", puppet(CROSSED, CROSSED)),
    ("manos en los bolsillos", puppet(POCKET, POCKET)),
    ("en jarras", puppet(HIPS, HIPS)),
    ("móvil en la mano, a la altura del pecho", puppet(DOWN, PHONE)),
    ("móvil con las dos manos", puppet(PHONE, PHONE)),
    ("móvil a la altura de la cintura", puppet(WAIST_PHONE, DOWN)),
    ("una mano en el bolsillo y la otra caída", puppet(POCKET, DOWN)),
]


@pytest.mark.parametrize(("name", "who"), REST, ids=[r[0] for r in REST])
def test_en_reposo_no_salta_ninguna_pose(name: str, who: Person) -> None:
    assert poses_of(who) == set(), name


# ---------------------------------------------------------------------------
# Permisivas: si falta la muñeca, cuenta el codo; un brazo que no se ve no cuenta en contra
# ---------------------------------------------------------------------------


def test_sin_munecas_cuenta_el_codo() -> None:
    no_wrists = (L_WRIST, R_WRIST)
    assert "brazos_arriba" in poses_of(puppet(UP, UP, hide=no_wrists))
    assert "pose_t" in poses_of(puppet(T, T, hide=no_wrists))
    assert "manos_cabeza" in poses_of(puppet(HEAD_TOP, HEAD_TOP, hide=no_wrists))
    assert "biceps" in poses_of(puppet(BICEPS, BICEPS, hide=no_wrists))
    # Con los codos caídos y sin muñecas, nada.
    assert poses_of(puppet(DOWN, DOWN, hide=no_wrists)) == set()


def test_un_brazo_que_no_se_ve_no_cuenta_en_contra() -> None:
    hidden_left = (L_ELBOW, L_WRIST)
    assert "brazos_arriba" in poses_of(puppet(UP, UP, hide=hidden_left))
    assert "pose_t" in poses_of(puppet(T, T, hide=hidden_left))
    assert "manos_cabeza" in poses_of(puppet(HEAD_TOP, HEAD_TOP, hide=hidden_left))
    assert "biceps" in poses_of(puppet(BICEPS, BICEPS, hide=hidden_left))
    # Pero sin ver ningún brazo, no se da nada por hecho.
    both = (L_ELBOW, L_WRIST, R_ELBOW, R_WRIST)
    assert poses_of(puppet(UP, UP, hide=both)) == set()


def test_un_brazo_arriba_y_el_otro_sin_ver_vale_para_las_dos() -> None:
    assert poses_of(puppet(UP, DOWN, hide=(R_ELBOW, R_WRIST))) == {"brazos_arriba", "un_brazo"}


def test_los_dos_brazos_arriba_no_son_un_brazo() -> None:
    assert "un_brazo" not in poses_of(puppet(UP, UP))


def test_la_barbilla_no_cuenta_solo_con_el_codo() -> None:
    assert "barbilla" not in poses_of(puppet(DOWN, CHIN, hide=(R_WRIST,)))


def test_sin_nariz_se_estima_la_cabeza() -> None:
    assert poses_of(puppet(UP, UP, hide=(NOSE,))) == {"brazos_arriba"}
    assert poses_of(puppet(DOWN, CHIN, hide=(NOSE, L_EYE, R_EYE))) == {"barbilla"}
    assert poses_of(puppet(DOWN, DOWN, hide=(NOSE, L_EYE, R_EYE, L_EAR, R_EAR))) == set()


def test_sin_los_dos_hombros_no_se_mide() -> None:
    assert body_of(puppet(UP, UP, hide=(L_SHOULDER,)), WIDTH, HEIGHT) is None


def test_una_pose_sin_regla_nunca_se_da_por_hecha() -> None:
    body = body_of(puppet(UP, UP), WIDTH, HEIGHT)
    assert body is not None
    assert not does_pose(body, "voltereta")


# ---------------------------------------------------------------------------
# Quién juega y colocación
# ---------------------------------------------------------------------------


def test_juega_quien_llega_a_la_altura_minima() -> None:
    near = puppet(cx=200.0)
    far = puppet(cx=500.0, sy=100.0, s=15.0)  # unos 60 px de alto en 360
    assert is_player(near, 0.25) and not is_player(far, 0.25)
    frame = pose_frame(near, far, width=WIDTH, height=HEIGHT)
    assert placement_of(frame, 0.25).players == 1


def test_demasiado_cerca() -> None:
    normal = puppet()
    assert not too_close(normal, WIDTH, HEIGHT)
    # Hombros enormes en la imagen.
    assert too_close(puppet(cx=320.0, sy=250.0, s=0.33 * WIDTH), WIDTH, HEIGHT)
    # Hombros grandes y ninguna muñeca: los brazos se salen del encuadre.
    big = puppet(cx=320.0, sy=200.0, s=0.2 * WIDTH, hide=(L_WRIST, R_WRIST))
    assert too_close(big, WIDTH, HEIGHT)
    # La cabeza pegada al borde de arriba: los brazos levantados no caben.
    assert too_close(puppet(sy=40.0), WIDTH, HEIGHT)
    # Solo se le ve la cara.
    face = person(
        {NOSE: (0.5, 0.5), L_EYE: (0.55, 0.4), R_EYE: (0.45, 0.4)},
        box=(0.2, 0.0, 0.6, 0.95),
    )
    assert too_close(face, WIDTH, HEIGHT)


def test_la_colocacion_cuenta_jugadores_y_los_que_estan_cerca() -> None:
    frame = pose_frame(puppet(cx=150.0), puppet(cx=480.0, sy=40.0), width=WIDTH, height=HEIGHT)
    placement = placement_of(frame, 0.25)
    assert placement.players == 2 and placement.close == 1 and not placement.ready
    assert placement_of(pose_frame(puppet(), width=WIDTH, height=HEIGHT), 0.25).ready
    assert not placement_of(None, 0.25).ready


def test_el_recuento_de_un_frame() -> None:
    frame = pose_frame(
        puppet(UP, UP, cx=100.0),
        puppet(UP_V, UP_V, cx=250.0),
        puppet(DOWN, DOWN, cx=400.0),
        puppet(UP, UP, cx=560.0, sy=80.0, s=12.0),  # al fondo: no juega
        width=WIDTH,
        height=HEIGHT,
    )
    counted = count_frame(frame, "brazos_arriba", 0.25)
    assert (counted.doing, counted.players) == (2, 3)
    assert [mark for _, mark in counted.marks] == ["ok", "ok", "no"]
    # Sin pose (entre rondas), todos en gris.
    idle = count_frame(frame, None, 0.25)
    assert idle.doing == 0 and {mark for _, mark in idle.marks} == {"no"}
    assert count_frame(None, "brazos_arriba", 0.25).players == 0
