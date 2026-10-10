"""Dibujos de los juegos encima de la vista en vivo: esqueletos, manos, cajas y marcas.

``docs/plan-juegos.md``, secciones 5.2, 5.4 y 6. Los juegos los combinan en un
``Overlay`` (``sonia.vision.contracts``) y se lo pasan a la vista en vivo
(``PreviewStreamer.start(overlay=...)`` o ``set_overlay``), que lo llama en un hilo con
cada frame ya reducido y, si toca, en espejo, justo antes de codificarlo.

Las coordenadas son las de los detectores: de 0 a 1 sobre la imagen **sin espejo**. Con
``mirrored`` se dibujan en ``1 - x``, así que el esqueleto cae encima de la persona
también en la imagen en espejo. El texto va con las fuentes Hershey de OpenCV, que solo
tienen ASCII: nada de tildes ni eñes («7 de 9» sí; «sí» no).

Ejemplo (poses: en verde quien hace la pose, en gris quien no)::

    frame = poses.latest()
    preview.set_overlay(skeletons(frame.people, [GREEN if ok else GREY for ok in hits]))
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Any

import numpy as np

from sonia.vision.contracts import HandReading, Overlay, Person, Point

__all__ = [
    "BLUE",
    "BODY_EDGES",
    "GREEN",
    "GREY",
    "HAND_EDGES",
    "RED",
    "WHITE",
    "YELLOW",
    "Color",
    "box_overlay",
    "compose",
    "draw_box",
    "draw_check",
    "draw_cross",
    "draw_hand",
    "draw_label",
    "draw_skeleton",
    "hands_overlay",
    "skeletons",
    "to_pixels",
]

#: Colores en BGR (los de OpenCV), de la paleta de Google del DevFest.
Color = tuple[int, int, int]
GREEN: Color = (83, 168, 52)
GREY: Color = (170, 170, 170)
BLUE: Color = (244, 133, 66)
RED: Color = (53, 67, 234)
YELLOW: Color = (5, 188, 251)
WHITE: Color = (255, 255, 255)
_SHADOW: Color = (20, 20, 20)

#: Huesos del esqueleto COCO (pares de :data:`sonia.vision.contracts.BODY_POINTS`). Sin la
#: cara salvo nariz-hombros, para que se lea limpio a 640x360.
BODY_EDGES: tuple[tuple[int, int], ...] = (
    (5, 6),  # hombros
    (5, 7),
    (7, 9),  # brazo izquierdo
    (6, 8),
    (8, 10),  # brazo derecho
    (5, 11),
    (6, 12),
    (11, 12),  # tronco
    (11, 13),
    (13, 15),  # pierna izquierda
    (12, 14),
    (14, 16),  # pierna derecha
    (0, 1),
    (0, 2),
    (1, 3),
    (2, 4),  # cara
)

#: Huesos de la mano (los 21 puntos de MediaPipe).
HAND_EDGES: tuple[tuple[int, int], ...] = (
    (0, 1),
    (1, 2),
    (2, 3),
    (3, 4),
    (0, 5),
    (5, 6),
    (6, 7),
    (7, 8),
    (5, 9),
    (9, 10),
    (10, 11),
    (11, 12),
    (9, 13),
    (13, 14),
    (14, 15),
    (15, 16),
    (13, 17),
    (0, 17),
    (17, 18),
    (18, 19),
    (19, 20),
)

#: Un punto con menos confianza no se dibuja (ni sus huesos).
MIN_POINT_SCORE = 0.3


def _cv2() -> Any:
    import cv2

    return cv2


def to_pixels(image: np.ndarray, x: float, y: float, mirrored: bool) -> tuple[int, int]:
    """De 0 a 1 sin espejo a píxeles de ``image`` (en espejo si ``mirrored``)."""
    height, width = int(image.shape[0]), int(image.shape[1])
    if mirrored:
        x = 1.0 - x
    return round(x * (width - 1)), round(y * (height - 1))


def _thickness(image: np.ndarray, base: float = 3.0) -> int:
    """Grosor proporcional: 3 px a 640 de ancho."""
    return max(1, round(base * int(image.shape[1]) / 640))


def draw_skeleton(
    image: np.ndarray,
    person: Person,
    mirrored: bool,
    color: Color = GREEN,
    *,
    min_score: float = MIN_POINT_SCORE,
    joints: bool = True,
) -> None:
    """Dibuja el esqueleto de ``person`` con huesos y articulaciones."""
    cv2 = _cv2()
    thick = _thickness(image)
    points = person.points
    if len(points) < 17:
        return
    seen = [p.score >= min_score for p in points]
    pixels = [to_pixels(image, p.x, p.y, mirrored) for p in points]
    for a, b in BODY_EDGES:
        if seen[a] and seen[b]:
            cv2.line(image, pixels[a], pixels[b], _SHADOW, thick + 2, cv2.LINE_AA)
            cv2.line(image, pixels[a], pixels[b], color, thick, cv2.LINE_AA)
    if joints:
        for index, pixel in enumerate(pixels):
            if seen[index]:
                cv2.circle(image, pixel, thick + 1, WHITE, -1, cv2.LINE_AA)
                cv2.circle(image, pixel, thick + 1, color, 1, cv2.LINE_AA)


def draw_box(
    image: np.ndarray,
    box: tuple[float, float, float, float],
    mirrored: bool,
    color: Color = BLUE,
    *,
    label: str | None = None,
) -> None:
    """Una caja ``(x, y, ancho, alto)`` de 0 a 1, con una etiqueta opcional encima."""
    cv2 = _cv2()
    x, y, w, h = box
    a = to_pixels(image, x, y, mirrored)
    b = to_pixels(image, x + w, y + h, mirrored)
    top_left = (min(a[0], b[0]), min(a[1], b[1]))
    bottom_right = (max(a[0], b[0]), max(a[1], b[1]))
    thick = _thickness(image)
    cv2.rectangle(image, top_left, bottom_right, color, thick, cv2.LINE_AA)
    if label:
        draw_label(image, label, top_left, color)


def draw_label(
    image: np.ndarray,
    text: str,
    anchor: tuple[int, int],
    color: Color = BLUE,
    *,
    scale: float = 0.6,
) -> None:
    """Texto blanco sobre una pastilla de ``color``, encima de ``anchor`` (en píxeles).

    Solo ASCII (fuentes Hershey): las tildes salen como «?».
    """
    cv2 = _cv2()
    font = cv2.FONT_HERSHEY_SIMPLEX
    factor = scale * int(image.shape[1]) / 640
    thick = max(1, round(2 * int(image.shape[1]) / 640))
    (tw, th), base = cv2.getTextSize(text, font, factor, thick)
    pad = max(2, round(4 * int(image.shape[1]) / 640))
    x = max(0, min(int(anchor[0]), int(image.shape[1]) - tw - 2 * pad))
    y = max(th + 2 * pad, int(anchor[1]))
    cv2.rectangle(image, (x, y - th - 2 * pad), (x + tw + 2 * pad, y), color, -1)
    cv2.putText(
        image, text, (x + pad, y - pad - base // 2), font, factor, WHITE, thick, cv2.LINE_AA
    )


def draw_check(
    image: np.ndarray, center: tuple[float, float], mirrored: bool, color: Color = GREEN
) -> None:
    """Una marca de acierto (✓) en un círculo, centrada en ``center`` (de 0 a 1)."""
    cv2 = _cv2()
    cx, cy = to_pixels(image, center[0], center[1], mirrored)
    radius = max(6, round(16 * int(image.shape[1]) / 640))
    thick = _thickness(image)
    cv2.circle(image, (cx, cy), radius, color, -1, cv2.LINE_AA)
    pts = np.array(
        [
            (cx - radius * 0.45, cy + radius * 0.02),
            (cx - radius * 0.1, cy + radius * 0.38),
            (cx + radius * 0.5, cy - radius * 0.35),
        ],
        dtype=np.int32,
    )
    cv2.polylines(image, [pts], False, WHITE, thick, cv2.LINE_AA)


def draw_cross(
    image: np.ndarray, center: tuple[float, float], mirrored: bool, color: Color = RED
) -> None:
    """Una marca de fallo (✗) en un círculo, centrada en ``center`` (de 0 a 1)."""
    cv2 = _cv2()
    cx, cy = to_pixels(image, center[0], center[1], mirrored)
    radius = max(6, round(16 * int(image.shape[1]) / 640))
    thick = _thickness(image)
    arm = round(radius * 0.42)
    cv2.circle(image, (cx, cy), radius, color, -1, cv2.LINE_AA)
    cv2.line(image, (cx - arm, cy - arm), (cx + arm, cy + arm), WHITE, thick, cv2.LINE_AA)
    cv2.line(image, (cx - arm, cy + arm), (cx + arm, cy - arm), WHITE, thick, cv2.LINE_AA)


def draw_hand(
    image: np.ndarray,
    hand: HandReading,
    mirrored: bool,
    color: Color = YELLOW,
    *,
    label: str | None = None,
) -> None:
    """Los 21 puntos de una mano con sus huesos; sin puntos, solo su caja."""
    cv2 = _cv2()
    if len(hand.points) < 21:
        draw_box(image, hand.box, mirrored, color, label=label)
        return
    thick = max(1, _thickness(image) - 1)
    pixels = [to_pixels(image, p.x, p.y, mirrored) for p in hand.points]
    for a, b in HAND_EDGES:
        cv2.line(image, pixels[a], pixels[b], color, thick, cv2.LINE_AA)
    for pixel in pixels:
        cv2.circle(image, pixel, thick + 1, WHITE, -1, cv2.LINE_AA)
    if label:
        x, y, _, _ = hand.box
        draw_label(image, label, to_pixels(image, x, y, mirrored), color)


def head_point(person: Person) -> tuple[float, float]:
    """Un poco por encima de la cabeza de ``person``: donde van las marcas de acierto."""
    nose: Point = person.points[0] if person.points else Point(0.5, 0.5, 0.0)
    x, y, w, _ = person.box
    if nose.score >= MIN_POINT_SCORE:
        return nose.x, max(0.03, y - 0.04)
    return x + w / 2, max(0.03, y - 0.04)


# ---------------------------------------------------------------------------
# Overlays listos para la vista en vivo
# ---------------------------------------------------------------------------


def compose(*overlays: Overlay | None) -> Overlay:
    """Varios dibujos en uno, en orden (los ``None`` se saltan)."""
    parts = [overlay for overlay in overlays if overlay is not None]

    def draw(image: np.ndarray, mirrored: bool) -> None:
        for overlay in parts:
            overlay(image, mirrored)

    return draw


def skeletons(
    people: Sequence[Person],
    colors: Sequence[Color] | None = None,
    *,
    color: Color = GREEN,
    marks: Sequence[bool | None] | None = None,
) -> Overlay:
    """Los esqueletos de ``people``, y si se dan, sus marcas.

    ``colors[i]`` es el color de cada persona (sin ``colors``, todas de ``color``; las
    que falten, en gris). ``marks[i]``: ``True`` pone ✓ encima de la cabeza, ``False``
    pone ✗ y ``None`` nada.
    """
    people = tuple(people)
    palette = list(colors) if colors is not None else [color] * len(people)
    marked = list(marks) if marks is not None else []

    def draw(image: np.ndarray, mirrored: bool) -> None:
        for index, person in enumerate(people):
            draw_skeleton(image, person, mirrored, palette[index] if index < len(palette) else GREY)
        for index, person in enumerate(people):
            mark = marked[index] if index < len(marked) else None
            if mark is True:
                draw_check(image, head_point(person), mirrored)
            elif mark is False:
                draw_cross(image, head_point(person), mirrored)

    return draw


def box_overlay(
    box: tuple[float, float, float, float], color: Color = BLUE, *, label: str | None = None
) -> Overlay:
    """Una caja (por ejemplo, la del jugador de piedra, papel o tijera)."""

    def draw(image: np.ndarray, mirrored: bool) -> None:
        draw_box(image, box, mirrored, color, label=label)

    return draw


def hands_overlay(
    hands: Iterable[HandReading],
    color: Color = YELLOW,
    *,
    label: Callable[[HandReading], str | None] | None = None,
) -> Overlay:
    """Las manos leídas, con una etiqueta opcional por mano (``label``)."""
    readings = tuple(hands)

    def draw(image: np.ndarray, mirrored: bool) -> None:
        for hand in readings:
            draw_hand(image, hand, mirrored, color, label=label(hand) if label else None)

    return draw
