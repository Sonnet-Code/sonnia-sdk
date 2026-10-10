"""Dibujos encima de la vista en vivo: esqueletos, manos, cajas y marcas en su sitio."""

from __future__ import annotations

import numpy as np

from sonia.vision.contracts import L_SHOULDER, R_SHOULDER, HandReading, HandShape, Person, Point
from sonia.vision.overlay import (
    GREEN,
    GREY,
    box_overlay,
    compose,
    draw_check,
    draw_cross,
    draw_label,
    hands_overlay,
    skeletons,
    to_pixels,
)


def canvas() -> np.ndarray:
    return np.zeros((360, 640, 3), dtype=np.uint8)


def person(x: float) -> Person:
    points = [Point(x, 0.5, 0.0) for _ in range(17)]
    points[L_SHOULDER] = Point(x + 0.05, 0.4, 0.9)
    points[R_SHOULDER] = Point(x - 0.05, 0.4, 0.9)
    return Person(box=(x - 0.1, 0.2, 0.2, 0.7), score=0.9, points=tuple(points))


def color_at(image: np.ndarray, x: float, y: float, mirrored: bool) -> tuple[int, ...]:
    px, py = to_pixels(image, x, y, mirrored)
    return tuple(int(v) for v in image[py, px])


def test_to_pixels_en_espejo() -> None:
    image = canvas()
    assert to_pixels(image, 0.0, 0.0, False) == (0, 0)
    assert to_pixels(image, 0.0, 0.0, True) == (639, 0)
    assert to_pixels(image, 0.25, 1.0, True) == (round(0.75 * 639), 359)


def test_esqueletos_en_verde_y_gris_y_en_espejo() -> None:
    image = canvas()
    draw = skeletons([person(0.3), person(0.7)], [GREEN, GREY])
    draw(image, True)
    # El hombro a hombro de la persona de x=0,3 sale en espejo, a 0,7 de la imagen.
    assert color_at(image, 0.3, 0.4, True) == GREEN
    assert color_at(image, 0.7, 0.4, True) == GREY
    # Los puntos con poca confianza (la cara, aquí) no se dibujan.
    assert color_at(image, 0.3, 0.5, True) == (0, 0, 0)


def test_marcas_de_acierto_y_fallo() -> None:
    image = canvas()
    skeletons([person(0.3), person(0.7)], marks=[True, False])(image, False)
    assert image.any()
    draw_check(image, (0.0, 0.0), False)  # en la esquina no rompe nada
    draw_cross(image, (1.0, 1.0), True)
    draw_label(image, "7 de 9", (630, 5))


def test_caja_mano_y_composicion() -> None:
    image = canvas()
    hand = HandReading(
        side="derecha",
        shape=HandShape.PAPER,
        score=0.9,
        box=(0.4, 0.4, 0.1, 0.2),
        points=tuple(Point(0.4 + i * 0.004, 0.45, 0.9) for i in range(21)),
    )
    no_points = HandReading(
        side="izquierda", shape=HandShape.UNKNOWN, score=0.5, box=(0.1, 0.1, 0.1, 0.1)
    )
    calls: list[bool] = []
    draw = compose(
        box_overlay((0.2, 0.2, 0.5, 0.6), label="Jugador"),
        None,
        hands_overlay([hand, no_points], label=lambda reading: reading.shape.value),
        lambda img, mirrored: calls.append(mirrored),
    )
    draw(image, True)
    assert calls == [True]
    assert image.any()
