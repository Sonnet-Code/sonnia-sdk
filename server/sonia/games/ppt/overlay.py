"""Lo que piedra, papel o tijera dibuja encima de la vista en vivo (sin OpenCV: numpy).

- Esquinas amarillas alrededor del jugador (la persona más cercana y centrada): los
  demás no cuentan y no se marcan.
- Durante la lectura y el resultado, una caja alrededor de la mano que juega: verde si
  se entendió la jugada, roja si no.

Se dibuja en el hilo de la vista en vivo, sobre el frame BGR y antes de codificarlo, en
su sitio también con el espejo (``x`` → ``1 - x``). Nunca se guarda nada.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from sonia.games.ppt.logic import Box

__all__ = [
    "GREEN",
    "RED",
    "YELLOW",
    "OverlayState",
    "draw_corners",
    "draw_rect",
    "draw_state",
]

#: Colores (BGR) de Google, los del DevFest.
YELLOW = (4, 188, 251)
GREEN = (83, 168, 52)
RED = (53, 67, 234)


@dataclass(frozen=True, slots=True)
class OverlayState:
    """Lo que hay que dibujar ahora: se sustituye entero (el hilo de la vista solo lo lee)."""

    player: Box | None = None
    hand: Box | None = None
    hand_ok: bool = False


def _pixels(image: np.ndarray, box: Box, mirrored: bool) -> tuple[int, int, int, int] | None:
    """La caja en píxeles ``(x0, y0, x1, y1)`` dentro de la imagen, o ``None`` si queda fuera."""
    height, width = int(image.shape[0]), int(image.shape[1])
    x, y, w, h = box
    if mirrored:
        x = 1.0 - (x + w)
    x0 = max(0, min(width - 1, round(x * width)))
    y0 = max(0, min(height - 1, round(y * height)))
    x1 = max(0, min(width - 1, round((x + w) * width)))
    y1 = max(0, min(height - 1, round((y + h) * height)))
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def _thickness(image: np.ndarray) -> int:
    return max(2, round(int(image.shape[0]) / 120))


def draw_rect(
    image: np.ndarray, box: Box, color: tuple[int, int, int], mirrored: bool, thickness: int = 0
) -> None:
    """Un rectángulo hueco."""
    found = _pixels(image, box, mirrored)
    if found is None:
        return
    x0, y0, x1, y1 = found
    t = thickness or _thickness(image)
    image[y0 : y0 + t, x0 : x1 + 1] = color
    image[max(y0, y1 - t + 1) : y1 + 1, x0 : x1 + 1] = color
    image[y0 : y1 + 1, x0 : x0 + t] = color
    image[y0 : y1 + 1, max(x0, x1 - t + 1) : x1 + 1] = color


def draw_corners(
    image: np.ndarray, box: Box, color: tuple[int, int, int], mirrored: bool, thickness: int = 0
) -> None:
    """Las cuatro esquinas de una caja (como un visor), con trazos de un cuarto del lado corto."""
    found = _pixels(image, box, mirrored)
    if found is None:
        return
    x0, y0, x1, y1 = found
    t = thickness or _thickness(image) + 1
    arm = max(t * 2, min(x1 - x0, y1 - y0) // 4)
    for cx, dx in ((x0, 1), (x1, -1)):
        for cy, dy in ((y0, 1), (y1, -1)):
            xs = sorted((cx, cx + dx * arm))
            ys = sorted((cy, cy + dy * arm))
            ty = sorted((cy, cy + dy * (t - 1)))
            tx = sorted((cx, cx + dx * (t - 1)))
            image[ty[0] : ty[1] + 1, xs[0] : xs[1] + 1] = color
            image[ys[0] : ys[1] + 1, tx[0] : tx[1] + 1] = color


def draw_state(image: np.ndarray, state: OverlayState, mirrored: bool) -> None:
    """Dibuja el jugador y su mano según ``state``."""
    if state.player is not None:
        draw_corners(image, state.player, YELLOW, mirrored)
    if state.hand is not None:
        draw_rect(image, state.hand, GREEN if state.hand_ok else RED, mirrored)
