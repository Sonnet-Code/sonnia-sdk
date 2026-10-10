"""El banco de palabras del Wordle (``assets/games/wordle/palabras.md``).

Es un banco editable desde el panel (``docs/juegos.md``, «Bancos»): lo que se guarda allí
manda sobre el archivo de la app. Cada palabra son dos líneas: un encabezado ``## `` con la
palabra (cinco letras, sin tildes) y una línea ``> `` con su pista. Una entrada mal formada
se salta con un aviso: un error al editar durante el evento no puede dejar a Sonia sin
Wordle.
"""

from __future__ import annotations

import random
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sonia.games.banks import BankParse, GameBank, markdown_sections
from sonia.games.wordle.logic import WORD_LENGTH, check_word

__all__ = [
    "HINT_MAX_CHARS",
    "MIN_WORDS",
    "WORDS",
    "WordleWord",
    "parse_words",
    "pick_word",
]

#: Una pista más larga no cabe bien en la tarjeta de la pantalla vertical ni se lee en una
#: frase.
HINT_MAX_CHARS = 160

#: Con menos palabras válidas el banco ni se guarda desde el panel ni se juega.
MIN_WORDS = 10


@dataclass(frozen=True, slots=True)
class WordleWord:
    """Una palabra secreta (cinco letras, mayúsculas, sin tildes) y su pista."""

    word: str
    hint: str


def _fold(text: str) -> str:
    """Mayúsculas y sin tildes, conservando espacios y signos (para buscar una palabra dentro)."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.category(c).startswith("M")).upper()


def _why_not(reason: str, word: str) -> str:
    if reason == "length":
        return f"no tiene {WORD_LENGTH} letras (tiene {len(word)})"
    if reason == "chars":
        return "lleva algo que no es una letra"
    return "está vacía"


def parse_words(text: str) -> BankParse[WordleWord]:
    """Las palabras válidas de un banco y un aviso por cada entrada que se salta. Nunca lanza.

    Se salta una entrada si su palabra no tiene cinco letras, si está repetida, si no tiene
    pista, si la pista pasa de :data:`HINT_MAX_CHARS` caracteres o si la pista dice la
    propia palabra (no sería una pista).
    """
    entries: list[WordleWord] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for heading, lines in markdown_sections(text):
        checked = check_word(heading)
        if not checked.ok:
            warnings.append(f"«{heading}» {_why_not(checked.reason, checked.word)}")
            continue
        word = checked.word
        if word in seen:
            warnings.append(f"«{word}» está repetida")
            continue
        quoted = [line.lstrip(">").strip() for line in lines if line.startswith(">")]
        plain = [line for line in lines if not line.startswith(">")]
        hint = " ".join(part for part in (quoted or plain) if part).strip()
        if not hint:
            warnings.append(f"«{word}» no tiene pista (una línea que empiece por >)")
            continue
        if len(hint) > HINT_MAX_CHARS:
            warnings.append(
                f"la pista de «{word}» es muy larga ({len(hint)} de {HINT_MAX_CHARS} caracteres)"
            )
            continue
        if word in _fold(hint):
            warnings.append(f"la pista de «{word}» dice la propia palabra")
            continue
        seen.add(word)
        entries.append(WordleWord(word, hint))
    return BankParse(entries, warnings)


def pick_word(
    words: Sequence[WordleWord], rng: random.Random, recent: Mapping[str, int]
) -> WordleWord:
    """Una palabra al azar entre las que nunca han salido o hace más que salieron.

    ``recent`` es ``{palabra: número de partida en que salió}``: no se repite ninguna
    hasta agotar las del banco (como la trivia). Lanza ``ValueError`` si ``words`` está vacío.
    """
    if not words:
        raise ValueError("no hay palabras")
    oldest = min(recent.get(entry.word, -1) for entry in words)
    return rng.choice([entry for entry in words if recent.get(entry.word, -1) == oldest])


WORDS: GameBank[WordleWord] = GameBank(
    id="wordle_palabras",
    title="Palabras del Wordle",
    file="palabras.md",
    parse=parse_words,
    min_entries=MIN_WORDS,
)
