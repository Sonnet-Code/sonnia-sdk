"""Las reglas del Wordle, sin red ni pantalla: normalizar la palabra, colorearla y contarla.

Todo son funciones puras para poder probarlas a fondo (``tests/games/test_wordle_logica.py``):

- :func:`check_word` entiende lo que llega de GPT-Live: mayúsculas, sin tildes ni
  diéresis, la Ñ como N, y sin espacios ni signos entre las letras (si la deletrean,
  «L I N U X»). Vale cualquier palabra de cinco letras: no hay diccionario (es más
  divertido y evita discusiones).
- :func:`score_guess` colorea un intento con la regla del Wordle de verdad, también con
  letras repetidas: primero se marcan las verdes y solo después se reparten las
  amarillas entre las letras que sobran, de izquierda a derecha.
- :func:`used_letters` resume el teclado: cada letra con el mejor color que ha sacado.
- :func:`describe_marks` es el resumen corto para que Sonia anime al grupo.

Las marcas de cada ficha son las del protocolo (``docs/protocolo.md``): ``g`` verde (en su
sitio), ``y`` amarilla (está, pero en otro sitio) y ``x`` gris (no está).
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

__all__ = [
    "GRAY",
    "GREEN",
    "NOT_A_WORD",
    "WORD_LENGTH",
    "YELLOW",
    "WordCheck",
    "check_word",
    "describe_marks",
    "normalize_text",
    "score_guess",
    "used_letters",
]

#: Letras de cada palabra: la rejilla es de cinco columnas.
WORD_LENGTH = 5

#: Marcas de una ficha (las del protocolo).
GREEN = "g"
YELLOW = "y"
GRAY = "x"

#: Lo que se pone en ``palabra`` cuando el grupo no dijo ninguna (valor de «no lo dijo»).
NOT_A_WORD = "no_lo_dijo"

_ORDINALS = ("primera", "segunda", "tercera", "cuarta", "quinta")
_COUNTS = {1: "una", 2: "dos", 3: "tres", 4: "cuatro", 5: "cinco"}

#: Letras que se aceptan tal cual tras quitar tildes: la A-Z del alfabeto latino básico.
_LETTERS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ")


@dataclass(frozen=True, slots=True)
class WordCheck:
    """Lo que se entendió de la palabra que llegó.

    - ``ok``: es una palabra de cinco letras A-Z y vale como intento.
    - ``word``: las letras normalizadas (mayúsculas, sin tildes); con ``ok`` son cinco.
    - ``reason``: si no vale, por qué: ``empty`` (no se dijo ninguna), ``length`` (no tiene
      cinco letras) o ``chars`` (lleva algo que no es una letra, como cifras o símbolos).
    - ``shown``: lo que se pinta en la fila al sacudirla (hasta cinco letras, o signos
      de interrogación si no hay nada que enseñar).
    """

    ok: bool
    word: str
    reason: str = ""
    shown: str = ""


def normalize_text(raw: object) -> str:
    """Letras en mayúsculas, sin tildes, diéresis ni cedillas; la Ñ queda como N.

    Quita los espacios y los signos de puntuación de entre las letras (para el caso de
    que la deletreen: ``L-I-N-U-X``). Lo que no es una letra latina (cifras, símbolos,
    otros alfabetos) se conserva para que :func:`check_word` lo rechace.
    """
    if not isinstance(raw, str):
        return ""
    out: list[str] = []
    for char in unicodedata.normalize("NFKD", raw):
        category = unicodedata.category(char)
        if category.startswith(("M", "Z", "P", "C")):
            # Marcas de tilde y diéresis, espacios, puntuación y caracteres de control.
            continue
        out.append(char.upper())
    return "".join(out)


#: ``no_lo_dijo`` ya normalizado (sin guiones bajos y en mayúsculas).
_NOT_A_WORD_TEXT = normalize_text(NOT_A_WORD)


def check_word(raw: object) -> WordCheck:
    """Entiende ``raw`` como una palabra de cinco letras. Nunca lanza."""
    text = normalize_text(raw)
    if not text or text == _NOT_A_WORD_TEXT:
        return WordCheck(ok=False, word="", reason="empty", shown="")
    if not all(char in _LETTERS for char in text):
        shown = "".join(char for char in text if char in _LETTERS)[:WORD_LENGTH]
        return WordCheck(ok=False, word=text, reason="chars", shown=shown)
    if len(text) != WORD_LENGTH:
        return WordCheck(ok=False, word=text, reason="length", shown=text[:WORD_LENGTH])
    return WordCheck(ok=True, word=text, shown=text)


def score_guess(guess: str, answer: str) -> str:
    """Colora ``guess`` contra ``answer`` como el Wordle de verdad: una marca por letra.

    1. Las letras en su sitio son verdes y se retiran de la palabra secreta.
    2. De izquierda a derecha, cada letra que no es verde es amarilla si a la palabra
       secreta aún le queda una de esas letras sin repartir (y se la gasta); si no, gris.

    Así una letra repetida en el intento solo se marca tantas veces como aparece en la
    palabra: con ``ABIDE`` y ``SPEED`` la primera E es amarilla y la segunda, gris; y una
    letra en su sitio nunca deja amarilla a otra igual que va antes.
    """
    if len(guess) != len(answer):
        raise ValueError(f"«{guess}» y «{answer}» no tienen las mismas letras")
    marks = [GRAY] * len(guess)
    left: Counter[str] = Counter()
    for index, (said, secret) in enumerate(zip(guess, answer, strict=True)):
        if said == secret:
            marks[index] = GREEN
        else:
            left[secret] += 1
    for index, said in enumerate(guess):
        if marks[index] != GREEN and left[said] > 0:
            marks[index] = YELLOW
            left[said] -= 1
    return "".join(marks)


def used_letters(rows: Sequence[tuple[str, str]]) -> dict[str, str]:
    """El teclado: ``{"g": "LX", "y": "OU", "x": "CDIN"}`` con el mejor color de cada letra.

    ``rows`` son los intentos ``(letras, marcas)``. Una letra va solo en un grupo: el
    mejor que haya sacado (verde antes que amarillo y amarillo antes que gris). Cada
    grupo va en orden alfabético.
    """
    best: dict[str, str] = {}
    rank = {GRAY: 0, YELLOW: 1, GREEN: 2}
    for letters, marks in rows:
        for letter, mark in zip(letters, marks, strict=True):
            if letter not in best or rank[mark] > rank[best[letter]]:
                best[letter] = mark
    return {
        mark: "".join(sorted(letter for letter, got in best.items() if got == mark))
        for mark in (GREEN, YELLOW, GRAY)
    }


def _join(items: Sequence[str]) -> str:
    """«a, b y c»."""
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + f" y {items[-1]}"


def describe_marks(letters: str, marks: str) -> str:
    """El resumen de un intento para que Sonia lo cuente: qué está bien, qué en otro sitio y qué no.

    «bien colocadas (verdes): L (primera) y X (quinta); en otro sitio (amarillas): U; no
    están (grises): I y N». Si una letra sale repetida en el intento y en la palabra hay
    menos copias, lo avisa («de la E solo hay una en la palabra») para que no confunda
    la ficha gris con que la letra no existe.
    """
    greens: dict[str, list[int]] = {}
    yellows: Counter[str] = Counter()
    grays: Counter[str] = Counter()
    for index, (letter, mark) in enumerate(zip(letters, marks, strict=True)):
        if mark == GREEN:
            greens.setdefault(letter, []).append(index)
        elif mark == YELLOW:
            yellows[letter] += 1
        else:
            grays[letter] += 1

    parts: list[str] = []
    if greens:
        shown = [
            f"{letter} ({_join([_ORDINALS[i] for i in places])})"
            for letter, places in greens.items()
        ]
        parts.append(f"bien colocadas (verdes): {_join(shown)}")
    if yellows:
        shown = [
            letter if count == 1 else f"{letter} ({_COUNTS.get(count, 'varias')} veces)"
            for letter, count in yellows.items()
        ]
        parts.append(f"en otro sitio (amarillas): {_join(shown)}")
    absent = [letter for letter in grays if letter not in greens and letter not in yellows]
    if absent:
        parts.append(f"no están (grises): {_join(absent)}")
    text = "; ".join(parts) or "sin letras"

    capped = [
        f"de la {letter} solo hay {_COUNTS.get(len(greens.get(letter, [])) + yellows[letter], 'varias')} "
        "en la palabra"
        for letter in grays
        if letter in greens or letter in yellows
    ]
    if capped:
        text += ". Ojo: " + _join(capped)
    return text
