"""Tiempos de cada palabra del guion en la toma de voz.

Las palabras con tiempo llegan de una transcripción (Gemini) o de la alineación por
caracteres de ElevenLabs, y no coinciden una a una con el guion: los números salen
en cifra o en letra («2026», «dos mil veintiséis»), los signos y las tildes cambian y
algunas palabras se parten o se juntan («DevFest», «Dev Fest»). Por eso las dos
listas se pasan a «átomos» (minúsculas, sin tildes, números en letra) y se alinean
con programación dinámica, que admite sustituciones parecidas, huecos y uniones de
dos átomos con uno. Lo que no casa se interpola por longitud entre sus vecinas.

Si no hay transcripción, el respaldo local reparte las palabras por los tramos con
voz de la toma según su longitud, buscando antes las pausas entre frases.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from sonia.video.audio import Samples, voiced_runs

__all__ = [
    "TimedWord",
    "align_words",
    "atoms",
    "distribute",
    "fill_gaps",
    "similarity",
    "spell_number",
    "words_from_characters",
]


@dataclass(frozen=True, slots=True)
class TimedWord:
    """Una palabra oída con su inicio y su fin en la toma (segundos)."""

    text: str
    start: float
    end: float


# ---------------------------------------------------------------------------
# Números en letra
# ---------------------------------------------------------------------------

_UNITS = [
    "cero",
    "uno",
    "dos",
    "tres",
    "cuatro",
    "cinco",
    "seis",
    "siete",
    "ocho",
    "nueve",
    "diez",
    "once",
    "doce",
    "trece",
    "catorce",
    "quince",
    "dieciseis",
    "diecisiete",
    "dieciocho",
    "diecinueve",
    "veinte",
    "veintiuno",
    "veintidos",
    "veintitres",
    "veinticuatro",
    "veinticinco",
    "veintiseis",
    "veintisiete",
    "veintiocho",
    "veintinueve",
]
_TENS = {
    3: "treinta",
    4: "cuarenta",
    5: "cincuenta",
    6: "sesenta",
    7: "setenta",
    8: "ochenta",
    9: "noventa",
}
_HUNDREDS = {
    1: "ciento",
    2: "doscientos",
    3: "trescientos",
    4: "cuatrocientos",
    5: "quinientos",
    6: "seiscientos",
    7: "setecientos",
    8: "ochocientos",
    9: "novecientos",
}


def _below_thousand(n: int) -> str:
    if n < 30:
        return _UNITS[n]
    if n < 100:
        tens, unit = divmod(n, 10)
        return _TENS[tens] + (f" y {_UNITS[unit]}" if unit else "")
    if n == 100:
        return "cien"
    hundreds, rest = divmod(n, 100)
    return _HUNDREDS[hundreds] + (f" {_below_thousand(rest)}" if rest else "")


def spell_number(n: int) -> str:
    """Un número entero en letra, en español y sin tildes (hasta 999 999 999)."""
    if n < 0:
        return "menos " + spell_number(-n)
    if n < 1000:
        return _below_thousand(n)
    if n < 1_000_000:
        thousands, rest = divmod(n, 1000)
        head = "mil" if thousands == 1 else f"{_below_thousand(thousands)} mil"
        return head + (f" {_below_thousand(rest)}" if rest else "")
    if n < 1_000_000_000:
        millions, rest = divmod(n, 1_000_000)
        head = "un millon" if millions == 1 else f"{spell_number(millions)} millones"
        return head + (f" {spell_number(rest)}" if rest else "")
    return " ".join(_UNITS[int(d)] for d in str(n))


# ---------------------------------------------------------------------------
# Átomos y parecido
# ---------------------------------------------------------------------------

_PIECE = re.compile(r"\d+|[a-z]+")


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def atoms(word: str) -> list[str]:
    """Los átomos de una palabra: trozos en minúsculas, sin tildes y con los números en letra."""
    out: list[str] = []
    for piece in _PIECE.findall(_plain(word)):
        if piece.isdigit():
            out.extend(spell_number(int(piece)).split() if len(piece) <= 9 else list(piece))
        else:
            out.append(piece)
    return out


def similarity(a: str, b: str) -> float:
    """1 − distancia de edición / longitud mayor (1: iguales, 0: nada que ver)."""
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            current[j] = min(
                previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (0 if ca == cb else 1)
            )
        previous = current
    return 1.0 - previous[len(b)] / max(len(a), len(b))


#: Coste de dejar un átomo sin pareja.
_GAP = 0.8
#: Recargo de unir dos átomos con uno (a igualdad, mejor uno con uno).
_MERGE = 0.1


def _cost(a: str, b: str) -> float:
    s = similarity(a, b)
    return 0.0 if s >= 0.8 else 0.45 if s >= 0.5 else 1.3


def _joins(a: str, b: str) -> bool:
    return similarity(a, b) >= 0.8


@dataclass(frozen=True, slots=True)
class _Atom:
    text: str
    #: Índice de la palabra de la que sale.
    word: int
    start: float = 0.0
    end: float = 0.0


def _heard_atoms(heard: Sequence[TimedWord]) -> list[_Atom]:
    out: list[_Atom] = []
    for index, word in enumerate(heard):
        pieces = atoms(word.text)
        if not pieces:
            continue
        total = sum(len(p) for p in pieces)
        cursor = word.start
        span = max(0.0, word.end - word.start)
        for piece in pieces:
            length = span * len(piece) / total
            out.append(_Atom(piece, index, cursor, cursor + length))
            cursor += length
    return out


def align_words(
    script_words: Sequence[str], heard: Sequence[TimedWord]
) -> list[tuple[float, float] | None]:
    """Inicio y fin de cada palabra del guion según las palabras oídas (``None`` si no casa)."""
    script = [_Atom(piece, i) for i, word in enumerate(script_words) for piece in atoms(word)]
    other = _heard_atoms(heard)
    n, m = len(script), len(other)
    inf = float("inf")
    cost = [[inf] * (m + 1) for _ in range(n + 1)]
    move: list[list[tuple[int, int]]] = [[(0, 0)] * (m + 1) for _ in range(n + 1)]
    cost[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            here = cost[i][j]
            if here == inf:
                continue
            steps: list[tuple[int, int, float]] = [(1, 0, _GAP), (0, 1, _GAP)]
            if i < n and j < m:
                steps.append((1, 1, _cost(script[i].text, other[j].text)))
            # Uniones solo si casan bien: «Dev» + «Fest» con «DevFest».
            if i < n and j + 1 < m and _joins(script[i].text, other[j].text + other[j + 1].text):
                steps.append((1, 2, _MERGE))
            if i + 1 < n and j < m and _joins(script[i].text + script[i + 1].text, other[j].text):
                steps.append((2, 1, _MERGE))
            for di, dj, extra in steps:
                ni, nj = i + di, j + dj
                if ni > n or nj > m:
                    continue
                if here + extra < cost[ni][nj]:
                    cost[ni][nj] = here + extra
                    move[ni][nj] = (di, dj)
    times: list[tuple[float, float] | None] = [None] * len(script_words)
    i, j = n, m
    while i > 0 or j > 0:
        di, dj = move[i][j]
        if di and dj:
            start = other[j - dj].start
            end = other[j - 1].end
            for k in range(i - di, i):
                word = script[k].word
                current = times[word]
                times[word] = (
                    (start, end)
                    if current is None
                    else (min(current[0], start), max(current[1], end))
                )
        i, j = i - di, j - dj
    return times


def fill_gaps(
    times: Sequence[tuple[float, float] | None],
    words: Sequence[str],
    *,
    end: float,
) -> list[tuple[float, float]]:
    """Da tiempo a las palabras que no casaron: repartidas por longitud entre sus vecinas.

    También deja los tiempos en orden (cada palabra empieza donde acabó la anterior o
    después) y dentro de ``[0, end]``.
    """
    out: list[tuple[float, float] | None] = list(times)
    count = len(out)
    i = 0
    while i < count:
        if out[i] is not None:
            i += 1
            continue
        j = i
        while j < count and out[j] is None:
            j += 1
        previous = out[i - 1] if i > 0 else None
        following = out[j] if j < count else None
        t0 = previous[1] if previous is not None else 0.0
        t1 = following[0] if following is not None else end
        if t1 < t0:
            t1 = t0
        weights = [len(words[k]) + 1 for k in range(i, j)]
        total = sum(weights)
        cursor = t0
        for k, weight in zip(range(i, j), weights, strict=True):
            step = (t1 - t0) * weight / total
            out[k] = (cursor, cursor + step)
            cursor += step
        i = j
    ordered: list[tuple[float, float]] = []
    floor = 0.0
    for item in out:
        assert item is not None
        start = min(max(item[0], floor), end)
        stop = min(max(item[1], start), end)
        ordered.append((start, stop))
        floor = start
    return ordered


def words_from_characters(
    characters: Sequence[str], starts: Sequence[float], ends: Sequence[float]
) -> list[TimedWord]:
    """Palabras con tiempo a partir de la alineación por caracteres (ElevenLabs)."""
    out: list[TimedWord] = []
    text = ""
    start = end = 0.0
    for char, a, b in zip(characters, starts, ends, strict=False):
        if char.isspace():
            if text:
                out.append(TimedWord(text, start, end))
                text = ""
            continue
        if not text:
            start = float(a)
        text += char
        end = float(b)
    if text:
        out.append(TimedWord(text, start, end))
    return out


# ---------------------------------------------------------------------------
# Respaldo local
# ---------------------------------------------------------------------------

#: Cuánto pesa la distancia a la posición esperada frente al largo de una pausa (por segundo).
_BOUNDARY_PULL = 0.3


def _voiced_to_time(runs: list[tuple[float, float]], position: float) -> float:
    """El instante de la toma que cae a ``position`` segundos de voz desde el principio."""
    for a, b in runs:
        if position <= b - a:
            return a + position
        position -= b - a
    return runs[-1][1] if runs else 0.0


def _spread(
    words: Sequence[str], runs: list[tuple[float, float]], start: float, end: float
) -> list[tuple[float, float]]:
    """Reparte ``words`` por la voz de ``runs`` recortados a ``[start, end]``."""
    clipped = [(max(a, start), min(b, end)) for a, b in runs if b > start and a < end]
    clipped = [(a, b) for a, b in clipped if b > a] or [(start, max(start, end))]
    voiced = sum(b - a for a, b in clipped)
    weights = [max(1, len("".join(atoms(w)))) + 1 for w in words]
    total = sum(weights) or 1
    out: list[tuple[float, float]] = []
    cursor = 0.0
    for weight in weights:
        length = voiced * weight / total
        out.append((_voiced_to_time(clipped, cursor), _voiced_to_time(clipped, cursor + length)))
        cursor += length
    return out


def distribute(
    phrases: Sequence[Sequence[str]], samples: Samples, rate: int
) -> list[tuple[float, float]]:
    """Tiempos de todas las palabras (en orden) sin transcripción: por la energía de la toma."""
    duration = len(samples) / rate if rate else 0.0
    runs = voiced_runs(samples, rate) or [(0.0, duration)]
    count = len(phrases)
    sizes = [sum(len("".join(atoms(w))) + 1 for w in words) for words in phrases]
    total_size = sum(sizes) or 1
    gaps = [(runs[k][1], runs[k + 1][0]) for k in range(len(runs) - 1)]
    voiced_total = sum(b - a for a, b in runs)
    bounds: list[float] = []
    if count > 1 and len(gaps) >= count - 1:
        chosen = -1
        cumulative = 0
        for b in range(1, count):
            cumulative += sizes[b - 1]
            expected = _voiced_to_time(runs, voiced_total * cumulative / total_size)
            last_allowed = len(gaps) - (count - 1 - b)
            best = None
            best_score = -float("inf")
            for g in range(chosen + 1, last_allowed):
                a, z = gaps[g]
                score = (z - a) - _BOUNDARY_PULL * abs((a + z) / 2 - expected)
                if score > best_score:
                    best, best_score = g, score
            assert best is not None
            chosen = best
            bounds.append((gaps[best][0] + gaps[best][1]) / 2)
    if len(bounds) != count - 1:
        # Sin pausas suficientes: todas las palabras seguidas por la voz de la toma.
        flat = [w for words in phrases for w in words]
        return _spread(flat, runs, 0.0, duration)
    edges = [0.0, *bounds, duration]
    out: list[tuple[float, float]] = []
    for index, words in enumerate(phrases):
        out.extend(_spread(words, runs, edges[index], edges[index + 1]))
    return out
