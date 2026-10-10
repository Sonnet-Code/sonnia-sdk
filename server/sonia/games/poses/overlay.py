"""Los esqueletos de quienes juegan, encima de la vista en vivo (con ``sonia.vision.overlay``).

- En verde quien hace la pose (con ✓ encima), en gris quien no.
- En las trampas, en rojo quien cae (con ✗).
- En amarillo quien está demasiado cerca, para que se aparte.

Lo llama la vista en vivo en su hilo, sobre el frame ya reducido y (si toca) en espejo, antes
de codificarlo: nada de esto toca el bucle de ``asyncio``. Solo dibuja; no guarda nada.

El juego deja sus marcas en un :class:`Skeletons` (una tupla que se cambia entera, así que el
hilo de la vista nunca ve una a medias) y le da a la vista :meth:`Skeletons.draw`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

import numpy as np

from sonia.vision.contracts import Person
from sonia.vision.overlay import (
    GREEN,
    GREY,
    RED,
    YELLOW,
    Color,
    draw_check,
    draw_cross,
    draw_skeleton,
    head_point,
)

__all__ = ["TINTS", "Skeleton", "Skeletons", "Tint"]

#: Cómo sale cada persona: hace la pose, no la hace, cayó en la trampa o está muy cerca.
Tint = Literal["ok", "no", "fell", "close"]

TINTS: dict[str, Color] = {"ok": GREEN, "no": GREY, "fell": RED, "close": YELLOW}


@dataclass(frozen=True, slots=True)
class Skeleton:
    """Una persona para dibujar, con su color."""

    person: Person
    tint: Tint


class Skeletons:
    """Las marcas que pinta la vista en vivo. El juego las cambia con :meth:`show`; la vista
    llama a :meth:`draw` desde su hilo."""

    def __init__(self) -> None:
        self._shown: tuple[Skeleton, ...] = ()

    @property
    def shown(self) -> tuple[Skeleton, ...]:
        return self._shown

    def show(self, skeletons: Iterable[Skeleton]) -> None:
        self._shown = tuple(skeletons)

    def clear(self) -> None:
        self._shown = ()

    def draw(self, image: np.ndarray, mirrored: bool) -> None:
        """El ``Overlay`` de la vista en vivo: esqueletos y, encima, las marcas ✓ y ✗."""
        shown = self._shown
        for item in shown:
            draw_skeleton(image, item.person, mirrored, TINTS.get(item.tint, GREY))
        for item in shown:
            if item.tint == "ok":
                draw_check(image, head_point(item.person), mirrored)
            elif item.tint == "fell":
                draw_cross(image, head_point(item.person), mirrored)
