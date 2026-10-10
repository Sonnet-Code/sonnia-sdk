"""Bancos de la ruleta (``assets/games/ruleta/``), editables desde el backoffice.

- ``adivinanzas.md``: las adivinanzas geek (texto, respuesta, variantes válidas y pista).
- ``tecnologias.md``: las tecnologías del reto «explica en 20 segundos».
- ``retos-sonnet-code.md``: el reto sorpresa de Sonnet Code, una pregunta (con su
  respuesta) o un reto de stand que se le cree al visitante.

El formato de cada uno va explicado al principio de su archivo. Los analizadores nunca
lanzan: lo que no encaja se salta con un aviso legible (para el registro y para el panel
al guardar). Las longitudes tienen tope para que quepan en la tarjeta de la pantalla y
para que las reglas de cada reto no pasen de los 1200 caracteres de ``instruct``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from sonia.games.banks import BankParse, GameBank, markdown_sections

__all__ = [
    "ANSWER_MAX",
    "DESCRIPTION_MAX",
    "HINT_MAX",
    "RIDDLES",
    "RIDDLE_MAX",
    "SONNET",
    "SONNET_MAX",
    "TECHS",
    "TECH_MAX",
    "VARIANTS_MAX",
    "Riddle",
    "SonnetChallenge",
    "Tech",
    "parse_riddles",
    "parse_sonnet",
    "parse_techs",
]

#: Topes de longitud (caracteres): la tarjeta de la franja alta y el tope de ``instruct``.
RIDDLE_MAX = 200
ANSWER_MAX = 60
VARIANTS_MAX = 140
HINT_MAX = 140
TECH_MAX = 32
DESCRIPTION_MAX = 200
SONNET_MAX = 160

#: Etiquetas de los campos (sin tildes ni mayúsculas): ``- Respuesta: ...``.
_ANSWER_KEYS = frozenset({"respuesta", "solucion"})
_VARIANT_KEYS = frozenset({"tambien vale", "tambien valen", "vale tambien", "valen tambien"})
_HINT_KEYS = frozenset({"pista"})
_FIELD = re.compile(r"^[-*]\s*([^:]{1,30}):\s*(.*)$")
_TAG = re.compile(r"^\[([^\]]+)\]\s*(.*)$")


def _plain(text: str) -> str:
    """Minúsculas y sin tildes, para comparar etiquetas."""
    decomposed = unicodedata.normalize("NFD", text.strip().lower())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def _fields(lines: list[str]) -> tuple[dict[str, str], list[str]]:
    """Los campos ``- Clave: valor`` de una sección y las líneas ``> nota``."""
    fields: dict[str, str] = {}
    notes: list[str] = []
    for line in lines:
        if line.startswith(">"):
            notes.append(line.lstrip("> ").strip())
            continue
        match = _FIELD.match(line)
        if match is not None:
            fields.setdefault(_plain(match.group(1)), match.group(2).strip())
    return fields, notes


def _field(fields: dict[str, str], keys: frozenset[str]) -> str:
    return next((value for key, value in fields.items() if key in keys), "")


def _variants(raw: str) -> tuple[str, ...]:
    """«a, b, c» (o «a, b; c» con punto y coma si alguna lleva comas dentro)."""
    seen: list[str] = []
    for part in raw.split(";" if ";" in raw else ","):
        item = part.strip()
        if item.endswith(".") and item.count(".") == 1:
            item = item[:-1].strip()
        if item and item.lower() not in (s.lower() for s in seen):
            seen.append(item)
    return tuple(seen)


def _too_long(what: str, text: str, limit: int, heading: str) -> str | None:
    if len(text) > limit:
        return f"«{heading[:50]}»: {what} de {len(text)} caracteres (tope {limit})"
    return None


# ---------------------------------------------------------------------------
# Adivinanzas
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Riddle:
    """Una adivinanza geek: el texto (en pantalla y para Sonia), la respuesta, otras
    formas de decirla que también valen y la pista."""

    text: str
    answer: str
    variants: tuple[str, ...]
    hint: str


def parse_riddles(text: str) -> BankParse[Riddle]:
    """``## adivinanza`` con ``- Respuesta:``, ``- Pista:`` y, si hay, ``- También vale:``."""
    entries: list[Riddle] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for heading, lines in markdown_sections(text):
        fields, _ = _fields(lines)
        answer = _field(fields, _ANSWER_KEYS)
        hint = _field(fields, _HINT_KEYS)
        variants = _variants(_field(fields, _VARIANT_KEYS))
        if not heading:
            warnings.append("una adivinanza sin texto en su línea ##")
            continue
        if not answer:
            warnings.append(f"«{heading[:50]}» no tiene «- Respuesta:»")
            continue
        if not hint:
            warnings.append(f"«{heading[:50]}» no tiene «- Pista:»")
            continue
        problem = (
            _too_long("la adivinanza", heading, RIDDLE_MAX, heading)
            or _too_long("la respuesta", answer, ANSWER_MAX, heading)
            or _too_long("la pista", hint, HINT_MAX, heading)
            or _too_long("«También vale»", ", ".join(variants), VARIANTS_MAX, heading)
        )
        if problem:
            warnings.append(problem)
            continue
        if heading.lower() in seen:
            warnings.append(f"«{heading[:50]}» está repetida")
            continue
        seen.add(heading.lower())
        entries.append(Riddle(heading, answer, variants, hint))
    return BankParse(entries, warnings)


# ---------------------------------------------------------------------------
# Tecnologías
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Tech:
    """Una tecnología para explicar en 20 segundos y, si la hay, una nota para que Sonia
    sepa de qué va al poner la nota (no sale en pantalla)."""

    name: str
    description: str = ""


def parse_techs(text: str) -> BankParse[Tech]:
    """``## Nombre`` y, opcional, una línea ``> de qué va`` para Sonia."""
    entries: list[Tech] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for heading, lines in markdown_sections(text):
        _, notes = _fields(lines)
        description = " ".join(n for n in notes if n)
        if not heading:
            warnings.append("una tecnología sin nombre en su línea ##")
            continue
        problem = _too_long("el nombre", heading, TECH_MAX, heading) or _too_long(
            "la nota", description, DESCRIPTION_MAX, heading
        )
        if problem:
            warnings.append(problem)
            continue
        if heading.lower() in seen:
            warnings.append(f"«{heading[:50]}» está repetida")
            continue
        seen.add(heading.lower())
        entries.append(Tech(heading, description))
    return BankParse(entries, warnings)


# ---------------------------------------------------------------------------
# Retos sorpresa de Sonnet Code
# ---------------------------------------------------------------------------

SonnetKind = Literal["pregunta", "reto"]

_KINDS: dict[str, SonnetKind] = {"pregunta": "pregunta", "reto": "reto"}


@dataclass(frozen=True, slots=True)
class SonnetChallenge:
    """Un reto sorpresa de Sonnet Code.

    - ``pregunta``: una pregunta sobre Sonnet Code con su respuesta (y variantes); Sonia
      juzga lo que conteste el visitante.
    - ``reto``: algo que hacer en el stand (seguir a Sonnet Code, chocar los cinco...):
      Sonia le cree, como en la trivia.

    ``{contacto}`` en el texto se cambia por quien atiende el stand (``TRIVIA_WIN_CONTACT``).
    """

    kind: SonnetKind
    text: str
    answer: str = ""
    variants: tuple[str, ...] = ()


def parse_sonnet(text: str) -> BankParse[SonnetChallenge]:
    """``## [pregunta] ...`` con ``- Respuesta:`` (y ``- También vale:``), o ``## [reto] ...``."""
    entries: list[SonnetChallenge] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for heading, lines in markdown_sections(text):
        fields, _ = _fields(lines)
        answer = _field(fields, _ANSWER_KEYS)
        variants = _variants(_field(fields, _VARIANT_KEYS))
        body = heading
        kind: SonnetKind = "pregunta" if answer else "reto"
        tagged = _TAG.match(heading)
        if tagged is not None:
            found = _KINDS.get(_plain(tagged.group(1)))
            if found is None:
                warnings.append(f"«{heading[:50]}»: la etiqueta tiene que ser [pregunta] o [reto]")
                continue
            kind, body = found, tagged.group(2).strip()
        if not body:
            warnings.append(f"«{heading[:50]}» no tiene texto")
            continue
        if kind == "pregunta" and not answer:
            warnings.append(f"«{body[:50]}» es una pregunta sin «- Respuesta:»")
            continue
        if kind == "reto":
            answer, variants = "", ()
        problem = (
            _too_long("el texto", body, SONNET_MAX, body)
            or _too_long("la respuesta", answer, ANSWER_MAX, body)
            or _too_long("«También vale»", ", ".join(variants), VARIANTS_MAX, body)
        )
        if problem:
            warnings.append(problem)
            continue
        if body.lower() in seen:
            warnings.append(f"«{body[:50]}» está repetido")
            continue
        seen.add(body.lower())
        entries.append(SonnetChallenge(kind, body, answer, variants))
    return BankParse(entries, warnings)


# ---------------------------------------------------------------------------
# Declaración de los bancos (``RuletaGame.banks``)
# ---------------------------------------------------------------------------

RIDDLES: GameBank[Riddle] = GameBank(
    id="ruleta_adivinanzas",
    title="Adivinanzas de la ruleta",
    file="adivinanzas.md",
    parse=parse_riddles,
    min_entries=10,
)

TECHS: GameBank[Tech] = GameBank(
    id="ruleta_tecnologias",
    title="Tecnologías de la ruleta (explica en 20 segundos)",
    file="tecnologias.md",
    parse=parse_techs,
    min_entries=10,
)

SONNET: GameBank[SonnetChallenge] = GameBank(
    id="ruleta_retos_sonnet_code",
    title="Retos sorpresa de Sonnet Code (ruleta)",
    file="retos-sonnet-code.md",
    parse=parse_sonnet,
    min_entries=5,
)
