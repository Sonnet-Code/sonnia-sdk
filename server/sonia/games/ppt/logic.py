"""Lo que decide piedra, papel o tijera sin tocar nada: quién juega, qué mano cuenta,
qué lectura es estable, quién gana y dónde cae el «¡ya!» de la frase grabada.

Funciones puras (``docs/juegos/piedra_papel_tijera.md``), probadas con lecturas
inventadas en ``tests/games/test_ppt.py``. Coordenadas de 0 a 1 sobre la imagen de la
cámara **sin espejo**, como ``sonia.vision.contracts``. Nada de esto reconoce a nadie:
el jugador es solo «la persona más grande y centrada» de cada momento.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np

from sonia.vision.contracts import L_HIP, R_HIP, HandReading, HandShape, Person, PoseFrame

__all__ = [
    "MOVES",
    "NO_HAND",
    "Box",
    "Sample",
    "Winner",
    "contradicted",
    "iou",
    "pick_player",
    "player_score",
    "read_sample",
    "says_ya",
    "settle",
    "winner_of",
    "ya_onset",
]

#: Caja ``(x, y, ancho, alto)`` de 0 a 1.
Box = tuple[float, float, float, float]

#: Quién gana una tirada.
Winner = Literal["sonnia", "player", "tie"]

#: Las tres jugadas, en el orden en que se sortean.
MOVES: tuple[HandShape, ...] = (HandShape.ROCK, HandShape.PAPER, HandShape.SCISSORS)

#: Qué gana a qué: piedra a tijera, tijera a papel y papel a piedra.
_BEATS: dict[HandShape, HandShape] = {
    HandShape.ROCK: HandShape.SCISSORS,
    HandShape.SCISSORS: HandShape.PAPER,
    HandShape.PAPER: HandShape.ROCK,
}

# -- quién juega ------------------------------------------------------------

#: Confianza mínima de una persona para contar.
MIN_PERSON_SCORE = 0.3
#: Área mínima de su caja (fracción de la imagen): más pequeña, está lejos y no juega.
MIN_PERSON_AREA = 0.01
#: Cuánto pesa estar descentrado: en el borde, la puntuación se queda en la mitad.
OFF_CENTER_PENALTY = 0.5
#: Se sigue con el jugador de antes si su caja solapa (IoU) al menos esto...
KEEP_IOU = 0.3
#: ...y su puntuación es al menos esta fracción de la del mejor (si no, otro está claramente delante).
KEEP_RATIO = 0.7

# -- qué mano cuenta --------------------------------------------------------

#: Confianza mínima de una cadera para trazar la línea de las caderas.
MIN_HIP_SCORE = 0.3
#: Una mano cuyo centro queda por debajo de la línea de las caderas (menos este margen)
#: cuelga: no se está enseñando.
HANGING_MARGIN = 0.02
#: Dos manos levantadas a menos de esta diferencia de altura van «a la vez».
SAME_HEIGHT = 0.06

# -- lectura estable --------------------------------------------------------

#: Lecturas iguales seguidas (sin contar huecos) para dar una jugada por estable.
MIN_RUN = 2


def winner_of(sonnia: HandShape, player: HandShape) -> Winner:
    """Quién gana la tirada: ``sonnia``, ``player`` o ``tie``."""
    if sonnia == player:
        return "tie"
    return "sonnia" if _BEATS.get(sonnia) == player else "player"


# ---------------------------------------------------------------------------
# Quién juega
# ---------------------------------------------------------------------------


def iou(a: Box, b: Box) -> float:
    """Intersección sobre unión de dos cajas ``(x, y, ancho, alto)``."""
    ax2, ay2 = a[0] + a[2], a[1] + a[3]
    bx2, by2 = b[0] + b[2], b[1] + b[3]
    inter = max(0.0, min(ax2, bx2) - max(a[0], b[0])) * max(0.0, min(ay2, by2) - max(a[1], b[1]))
    union = max(0.0, a[2]) * max(0.0, a[3]) + max(0.0, b[2]) * max(0.0, b[3]) - inter
    return inter / union if union > 0 else 0.0


def _area(box: Box) -> float:
    return max(0.0, box[2]) * max(0.0, box[3])


def player_score(person: Person) -> float:
    """Lo grande (cerca) y centrada que está una persona: área de su caja, rebajada si
    está descentrada (hasta la mitad en el borde de la imagen)."""
    x, _, w, _ = person.box
    off = min(1.0, abs((x + w / 2) - 0.5) / 0.5)
    return _area(person.box) * (1.0 - OFF_CENTER_PENALTY * off)


def pick_player(frame: PoseFrame | None, previous: Box | None = None) -> Person | None:
    """El jugador: la persona más cercana y centrada (la de cuerpo más grande).

    Las demás no cuentan. Para que no salte entre dos personas parecidas, se sigue con
    la de antes (``previous``: su caja en el frame anterior) mientras su caja solape y no
    haya otra claramente más grande. Si otra se pone delante, pasa a jugar ella: el
    juego sigue igual. Sin nadie, ``None``.
    """
    if frame is None:
        return None
    people = [
        person
        for person in frame.people
        if person.score >= MIN_PERSON_SCORE and _area(person.box) >= MIN_PERSON_AREA
    ]
    if not people:
        return None
    best = max(people, key=player_score)
    if previous is not None:
        same = max(people, key=lambda person: iou(person.box, previous))
        if iou(same.box, previous) >= KEEP_IOU and player_score(same) >= KEEP_RATIO * player_score(
            best
        ):
            return same
    return best


# ---------------------------------------------------------------------------
# Qué mano cuenta
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Sample:
    """Una muestra de la lectura: la jugada de la mano que juega (``None`` sin lectura),
    si se vio alguna mano enseñándose (para distinguir «no te vi la mano» de «no te la
    entendí») y la caja de esa mano (para la vista en vivo)."""

    shape: HandShape | None
    seen: bool = False
    box: Box | None = None


NO_HAND = Sample(None)


def _center_y(reading: HandReading) -> float:
    return reading.box[1] + reading.box[3] / 2


def _hip_line(person: Person) -> float | None:
    """La altura de las caderas que se ven (la media), o ``None`` si no se ve ninguna."""
    ys = [
        person.points[i].y
        for i in (L_HIP, R_HIP)
        if i < len(person.points) and person.points[i].score >= MIN_HIP_SCORE
    ]
    return sum(ys) / len(ys) if ys else None


def read_sample(readings: Sequence[HandReading], person: Person) -> Sample:
    """La mano que juega entre las lecturas de ``person``: la levantada delante del cuerpo.

    - Una mano que cuelga por debajo de las caderas no se está enseñando: no cuenta.
    - De las levantadas, la más alta; si otra está a su misma altura, las dos van a la
      vez: si enseñan jugadas distintas no vale ninguna (muestra sin lectura), y si una
      no se entiende, vale la otra.
    """
    hands = [r for r in readings if r.box[2] > 0 and r.box[3] > 0]
    if not hands:
        return NO_HAND
    hips = _hip_line(person)
    raised = [r for r in hands if hips is None or _center_y(r) < hips - HANGING_MARGIN]
    if not raised:
        return NO_HAND
    raised.sort(key=_center_y)
    top = raised[0]
    together = [r for r in raised if _center_y(r) - _center_y(top) < SAME_HEIGHT]
    shapes = {r.shape for r in together if r.shape is not HandShape.UNKNOWN}
    if len(shapes) == 1:
        shape = next(iter(shapes))
        hand = next(r for r in together if r.shape is shape)
        return Sample(shape, True, hand.box)
    return Sample(None, True, top.box)


# ---------------------------------------------------------------------------
# Lectura estable
# ---------------------------------------------------------------------------


def settle(samples: Sequence[HandShape | None], min_run: int = MIN_RUN) -> HandShape | None:
    """La jugada estable de una ventana de lecturas, o ``None`` si no la hay.

    Los huecos (``None``: esa vez no se vio la mano) no cortan los tramos. Vale el último
    tramo de al menos ``min_run`` lecturas iguales (el puño que se agita antes del
    «¡ya!» lee piedra: manda lo que viene después), y si no lo hay pero todas las
    lecturas dicen lo mismo, eso. Si cambian sin parar, ``None``.
    """
    runs: list[tuple[HandShape, int]] = []
    for shape in samples:
        if shape is None:
            continue
        if runs and runs[-1][0] is shape:
            runs[-1] = (shape, runs[-1][1] + 1)
        else:
            runs.append((shape, 1))
    if not runs:
        return None
    for shape, count in reversed(runs):
        if count >= min_run:
            return shape
    return runs[0][0] if len(runs) == 1 else None


def contradicted(samples: Sequence[HandShape | None], shape: HandShape | None) -> bool:
    """¿La última lectura dice otra jugada que ``shape``? (Un hueco no contradice.)"""
    if not samples or shape is None:
        return False
    last = samples[-1]
    return last is not None and last is not shape


def says_ya(text: str) -> bool:
    """¿Ha llegado Sonia al «¡ya!» de la cuenta? Sigue lo que dice ella, no al visitante.

    Sirve cuando la frase no está grabada y la dice en directo: el «ya» que va después de
    «tijera» (o, si la transcripción no trae «tijera», como última palabra).
    """
    plain = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    words: list[str] = re.findall(r"[a-z]+", plain)
    if "ya" not in words:
        return False
    cuts = [i for i, word in enumerate(words) if word in ("tijera", "tijeras")]
    if cuts:
        return "ya" in words[cuts[-1] + 1 :]
    return words[-1] == "ya"


# ---------------------------------------------------------------------------
# El «¡ya!» de la frase grabada
# ---------------------------------------------------------------------------

#: Ventana de la envolvente.
_HOP_S = 0.01
#: Un tramo con voz llega a esta fracción del pico de la frase.
_VOICED = 0.12
#: Silencios más cortos que esto no separan palabras.
_GAP_S = 0.12
#: Un tramo más corto o más flojo que esto no es una palabra (un clic, una respiración).
_MIN_WORD_S = 0.08
_MIN_WORD_PEAK = 0.25
#: Si el último tramo dura más que esto, el «ya» va pegado a «tijera»: se toma desde el
#: final menos lo que dura un «¡ya!».
_YA_ALONE_S = 0.7
_YA_SECONDS = 0.45


def ya_onset(pcm: bytes, sample_rate: int) -> float | None:
    """Segundos desde el principio de la frase grabada hasta el «¡ya!» (``None`` si no se sabe).

    ``pcm``: s16le mono a ``sample_rate``. El «ya» es la última palabra, separada por los
    puntos suspensivos: el principio del último tramo con voz de la envolvente RMS.
    """
    if sample_rate <= 0 or len(pcm) < 4:
        return None
    audio = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0
    hop = max(1, int(sample_rate * _HOP_S))
    count = audio.size // hop
    if count < 10:
        return None
    rms = np.sqrt(np.mean(audio[: count * hop].reshape(count, hop) ** 2, axis=1))
    peak = float(rms.max())
    if peak < 1e-3:
        return None
    voiced = rms >= peak * _VOICED
    segments: list[tuple[int, int]] = []
    start: int | None = None
    for index, on in enumerate(voiced):
        if on and start is None:
            start = index
        elif not on and start is not None:
            segments.append((start, index))
            start = None
    if start is not None:
        segments.append((start, count))
    gap = max(1, round(_GAP_S / _HOP_S))
    merged: list[tuple[int, int]] = []
    for segment in segments:
        if merged and segment[0] - merged[-1][1] < gap:
            merged[-1] = (merged[-1][0], segment[1])
        else:
            merged.append(segment)
    words = [
        (a, b)
        for a, b in merged
        if (b - a) * _HOP_S >= _MIN_WORD_S and float(rms[a:b].max()) >= peak * _MIN_WORD_PEAK
    ]
    if not words:
        return None
    first, last = words[-1]
    onset = first * _HOP_S
    if (last - first) * _HOP_S > _YA_ALONE_S:
        onset = max(onset, last * _HOP_S - _YA_SECONDS)
    return round(onset, 3)
