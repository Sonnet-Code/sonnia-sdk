"""Subtítulos SRT con los tiempos de las palabras ya colocadas en el vídeo.

Como piden las redes: líneas de 42 caracteres como mucho y dos líneas por subtítulo
como mucho, sin mezclar frases. Dentro de una frase se corta por donde se cortaría al
leer en voz alta (pedido de Jean, 27-oct-2026):

- mejor tras un punto, una coma o dos puntos; si no, antes de un nexo («y», «que»,
  «en»...); nunca tras un artículo o una preposición sueltos;
- nunca dentro de un nombre propio («Santo Domingo», «Sonnet Code», «Pedro Henríquez
  Ureña»);
- nunca una palabra sola en un subtítulo ni en una línea, y las dos líneas equilibradas.

Se elige el reparto de menos coste de toda la frase (programación dinámica), no el
primero que llena el subtítulo. Cada subtítulo sale con su primera palabra y se queda
un poco después de la última, sin pisar al siguiente. El texto es el que se lee
(«Sonnia»).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

__all__ = ["Cue", "SrtWord", "build_cues", "format_srt", "split_lines", "timestamp"]

MAX_LINE = 42
MAX_LINES = 2
#: Lo que se queda un subtítulo tras su última palabra, y lo mínimo que dura.
HOLD_S = 0.4
MIN_DURATION_S = 0.8
#: Hueco mínimo entre un subtítulo y el siguiente.
GAP_S = 0.04

#: Costes de cortar entre dos palabras (un subtítulo o una línea).
COST_SENTENCE = 0.0
COST_CLAUSE = 2.0
COST_CONNECTOR = 4.0
COST_PLAIN = 8.0
#: Cortar tras un artículo, una preposición o una conjunción que se queda colgando.
COST_DANGLING = 12.0
#: Cortar dentro de un nombre propio: solo si no queda otra.
COST_NAME = 1000.0
#: Una palabra sola en un subtítulo o en una línea.
COST_ORPHAN = 40.0
#: Un subtítulo muy corto (menos de ``SHORT_CHARS``).
COST_SHORT = 8.0
SHORT_CHARS = 12
#: Cada subtítulo de más: mejor pocos y llenos que muchos a medias.
COST_CUE = 6.0
#: Desequilibrio entre las dos líneas, por carácter de diferencia.
COST_IMBALANCE = 1 / 3

_SENTENCE_END = re.compile(r"[.!?…][\"'»”)\]]*$")
_CLAUSE_END = re.compile(r"[,;:][\"'»”)\]]*$")
_DASHES = frozenset({"—", "–", "-"})
_OPENERS = "¡¿«\"'“(["

#: Palabras ante las que se corta bien (empiezan una cláusula o un complemento).
CONNECTORS = frozenset(
    [
        "y",
        "e",
        "o",
        "u",
        "ni",
        "pero",
        "sino",
        "que",
        "porque",
        "pues",
        "aunque",
        "mientras",
        "cuando",
        "donde",
        "como",
        "si",
        "para",
        "por",
        "con",
        "sin",
        "en",
        "desde",
        "hasta",
        "tras",
        "sobre",
        "entre",
        "hacia",
    ]
)
#: Palabras tras las que no se corta (se quedarían colgando al final de la línea).
DANGLING = frozenset(
    [
        "el",
        "la",
        "los",
        "las",
        "lo",
        "un",
        "una",
        "unos",
        "unas",
        "al",
        "del",
        "de",
        "a",
        "en",
        "con",
        "por",
        "para",
        "sin",
        "y",
        "e",
        "o",
        "u",
        "que",
        "mi",
        "tu",
        "su",
        "mis",
        "tus",
        "sus",
        "nuestro",
        "nuestra",
        "este",
        "esta",
        "ese",
        "esa",
        "muy",
        "mas",
        "todo",
        "toda",
        "todos",
        "todas",
    ]
)
#: Lo que puede ir dentro de un nombre propio en minúscula («Plaza de la Cultura»).
NAME_GLUE = frozenset({"de", "del", "la", "las", "los"})
#: Un corte entre dos subtítulos pesa más que uno entre dos líneas del mismo subtítulo:
#: los subtítulos se cortan por frases y cláusulas; las líneas, también por los nexos.
CUE_CUT_FACTOR = 2.0


@dataclass(frozen=True, slots=True)
class SrtWord:
    """Un trozo de texto en pantalla con su tiempo en el vídeo y su frase."""

    text: str
    start: float
    end: float
    phrase: int


@dataclass(frozen=True, slots=True)
class Cue:
    start: float
    end: float
    lines: tuple[str, ...]


def _bare(text: str) -> str:
    """La palabra en minúsculas, sin tildes ni signos."""
    plain = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return re.sub(r"[^\w]", "", plain)


def _capitalized(text: str) -> bool:
    stripped = text.lstrip(_OPENERS)
    return bool(stripped) and stripped[0].isupper()


def _ends(text: str, pattern: re.Pattern[str]) -> bool:
    return bool(pattern.search(text))


class _Phrase:
    """Las palabras de una frase y lo que cuesta cortar entre cada dos."""

    def __init__(self, words: Sequence[str]) -> None:
        self.words = list(words)
        count = len(self.words)
        self.starts_sentence = [
            k == 0 or _ends(self.words[k - 1], _SENTENCE_END) for k in range(count)
        ]
        self.cut = [self._cost(k) for k in range(count + 1)]

    def _name(self, k: int) -> bool:
        """¿Es nombre propio la palabra ``k``? (mayúscula que no empieza oración)."""
        return (
            0 <= k < len(self.words) and _capitalized(self.words[k]) and not self.starts_sentence[k]
        )

    def _inside_name(self, k: int) -> bool:
        """¿Cortar antes de la palabra ``k`` parte un nombre propio?

        Lo parte si a la izquierda, saltando las palabras de enlace («de la»), hay una
        mayúscula y a la derecha, saltándolas también, un nombre propio, sin signos por en
        medio: «Santo | Domingo», «Sonnet | Code», «Plaza de | la Cultura».
        """
        words = self.words
        left = k - 1
        while left >= 0 and _bare(words[left]) in NAME_GLUE:
            left -= 1
        if left < 0 or not _capitalized(words[left]):
            return False
        if any(
            _ends(words[i], _SENTENCE_END) or _ends(words[i], _CLAUSE_END) for i in range(left, k)
        ):
            return False
        right = k
        while right < len(words) and _bare(words[right]) in NAME_GLUE:
            if _ends(words[right], _SENTENCE_END) or _ends(words[right], _CLAUSE_END):
                return False
            right += 1
        return self._name(right)

    def _cost(self, k: int) -> float:
        """Lo que cuesta cortar antes de la palabra ``k`` (0 y el final de la frase: nada)."""
        if k == 0 or k == len(self.words):
            return 0.0
        prev, nxt = self.words[k - 1], self.words[k]
        if self._inside_name(k):
            return COST_NAME
        if prev in _DASHES:
            return COST_DANGLING
        if _ends(prev, _SENTENCE_END):
            return COST_SENTENCE
        if _ends(prev, _CLAUSE_END) or nxt in _DASHES:
            return COST_CLAUSE
        cost = COST_CONNECTOR if _bare(nxt) in CONNECTORS else COST_PLAIN
        if _bare(prev) in DANGLING:
            cost += COST_DANGLING
        return cost

    def text(self, a: int, b: int) -> str:
        return " ".join(self.words[a:b])

    def lines(self, a: int, b: int) -> tuple[list[str], float] | None:
        """Las palabras ``a..b`` en una o dos líneas, y su coste (``None`` si no caben)."""
        text = self.text(a, b)
        if len(text) <= MAX_LINE:
            return [text], 0.0
        best: tuple[list[str], float] | None = None
        for m in range(a + 1, b):
            first, second = self.text(a, m), self.text(m, b)
            if len(first) > MAX_LINE or len(second) > MAX_LINE:
                continue
            cost = self.cut[m] + COST_IMBALANCE * abs(len(first) - len(second))
            if m - a == 1 or b - m == 1:
                cost += COST_ORPHAN
            if best is None or cost < best[1]:
                best = ([first, second], cost)
        return best

    def cues(self) -> list[tuple[int, int, list[str]]]:
        """El reparto de menos coste en subtítulos: ``(desde, hasta, líneas)``."""
        count = len(self.words)
        inf = float("inf")
        best = [inf] * (count + 1)
        back: list[tuple[int, list[str]] | None] = [None] * (count + 1)
        best[0] = 0.0
        for b in range(1, count + 1):
            for a in range(b - 1, -1, -1):
                if best[a] == inf:
                    continue
                fitted = self.lines(a, b)
                if fitted is None:
                    if b - a > 1:
                        continue
                    # Una palabra más larga que dos líneas: va sola, como sea.
                    fitted = ([self.text(a, b)], COST_NAME)
                lines, cost = fitted
                cost += CUE_CUT_FACTOR * self.cut[b] + COST_CUE
                if b - a == 1 and count > 1:
                    cost += COST_ORPHAN
                if len(self.text(a, b)) < SHORT_CHARS and count > 1:
                    cost += COST_SHORT
                if best[a] + cost < best[b]:
                    best[b] = best[a] + cost
                    back[b] = (a, lines)
        out: list[tuple[int, int, list[str]]] = []
        b = count
        while b > 0:
            step = back[b]
            assert step is not None
            a, lines = step
            out.append((a, b, lines))
            b = a
        return out[::-1]


def split_lines(words: Sequence[str]) -> list[list[str]]:
    """Las líneas de cada subtítulo de una frase (para probar el reparto sin tiempos)."""
    phrase = _Phrase(words)
    return [lines for _, _, lines in phrase.cues()]


def build_cues(words: Sequence[SrtWord]) -> list[Cue]:
    visible = [w for w in words if w.text.strip()]
    groups: list[list[SrtWord]] = []
    for word in visible:
        if groups and groups[-1][-1].phrase == word.phrase:
            groups[-1].append(word)
        else:
            groups.append([word])
    pieces: list[tuple[list[SrtWord], list[str]]] = []
    for group in groups:
        phrase = _Phrase([w.text for w in group])
        for a, b, lines in phrase.cues():
            pieces.append((group[a:b], lines))
    cues: list[Cue] = []
    for index, (group, lines) in enumerate(pieces):
        start = group[0].start
        end = max(group[-1].end + HOLD_S, start + MIN_DURATION_S)
        if index + 1 < len(pieces):
            end = min(end, pieces[index + 1][0][0].start - GAP_S)
        end = max(end, start + 0.1)
        cues.append(Cue(start, end, tuple(lines)))
    return cues


def timestamp(seconds: float) -> str:
    """``HH:MM:SS,mmm``."""
    millis = max(0, round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def format_srt(cues: Sequence[Cue]) -> str:
    blocks = [
        f"{i}\n{timestamp(c.start)} --> {timestamp(c.end)}\n" + "\n".join(c.lines)
        for i, c in enumerate(cues, 1)
    ]
    return "\n\n".join(blocks) + "\n" if blocks else ""
