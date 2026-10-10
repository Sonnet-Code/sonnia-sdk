"""El banco de objetos de la búsqueda relámpago (``assets/games/busqueda/objetos.md``).

Cada objeto es una sección del Markdown, con el formato explicado al principio del
archivo (un comentario HTML que el analizador ignora)::

    ## algo azul
    > En la foto, ¿se ve algo azul bien a la vista...?    (opcional: la pregunta cerrada)
    color: azul                                           (opcional: el color de la tarjeta)

- El encabezado es el objeto **tal como lo dice Sonia** después de «el primero que me
  enseñe» (con su artículo: «una botella», «unas llaves», «algo azul»). Es también lo que
  se lee en la tarjeta de la pantalla.
- La pregunta es la que se le hace a la cámara (``VisionJudge.ask``): cerrada (sí o no) y
  sin hablar de personas. Sin ella se usa una genérica con el nombre del objeto.
- El color es solo el de la tarjeta de la pantalla.

Nada que obligue a hablar de la persona: ni gafas ni ropa ni lo que lleve puesto. Lo vigila
el analizador (:func:`mentions_person`), que se salta lo que no cumple con un aviso.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from sonia.games.banks import BankParse, GameBank, markdown_sections

__all__ = [
    "COLORS",
    "DEFAULT_QUESTION",
    "NAME_MAX",
    "NAME_MIN",
    "OBJECTS",
    "ObjectEntry",
    "announced",
    "clean_what",
    "fold",
    "key_words",
    "mentions_person",
    "parse_objects",
    "words",
]

#: Largo del nombre del objeto que sale en la tarjeta y que dice Sonia.
NAME_MIN = 3
NAME_MAX = 48

#: Largo de una pregunta propia para la cámara.
QUESTION_MIN = 20
QUESTION_MAX = 320

#: Tope de lo que se acepta del modelo como descripción del objeto (``JudgeAnswer.what``).
WHAT_MAX_CHARS = 40
WHAT_MAX_WORDS = 6

#: Colores de la tarjeta por nombre: los de Google (los del DevFest) y algunos más.
COLORS: dict[str, str] = {
    "azul": "#4285F4",
    "rojo": "#EA4335",
    "amarillo": "#FBBC04",
    "verde": "#34A853",
    "naranja": "#F28B29",
    "morado": "#8E5BD9",
    "rosa": "#EC6FA8",
    "blanco": "#F2F5FA",
    "negro": "#2B2F36",
    "gris": "#9AA3AF",
}

#: Pregunta por defecto para la cámara. Cerrada, sin hablar de personas y sin dejar que
#: cuente la ropa ni el fondo (con «algo azul», cualquier camiseta azul valdría).
DEFAULT_QUESTION = (
    "En la foto, ¿se ve {name} bien a la vista, en una mano o frente a la cámara? "
    "No cuentan la ropa ni el fondo."
)

#: Palabras que hablan de la persona: quién es, su cuerpo o lo que lleva puesto. Ni el
#: objeto del banco ni su pregunta ni lo que diga el modelo pueden llevarlas (principio del
#: juego: nunca se habla de las personas). Sin tildes ni eñes (:func:`fold`).
_PERSON_WORDS = frozenset(
    """
    persona personas gente hombre hombres mujer mujeres chico chica chicos chicas muchacho
    muchacha nino nina ninos ninas nene nena joven jovenes senor senora senorita caballero dama
    amigo amiga companero companera visitante asistente participante usuario individuo sujeto
    adulto anciano anciana bebe

    cara rostro pelo cabello barba bigote ojo ojos boca nariz labios sonrisa piel cuerpo cabeza
    dedo dedos brazo brazos pecho cuello oreja orejas

    ropa camisa camiseta playera blusa pantalon pantalones short shorts falda vestido chaqueta
    chamarra abrigo chaleco sudadera sueter gorra gorro sombrero lentes gafas anteojos bufanda
    zapatos tenis sandalias calcetines pulsera collar aretes uniforme hoodie jeans vaqueros
    """.split()  # noqa: SIM905 - una palabra por línea ocuparía un centenar de líneas
)

#: En una pregunta para la cámara sí vale decir que la ropa no cuenta («No cuentan la ropa»).
_QUESTION_WORDS = _PERSON_WORDS - {"ropa"}

#: Además, en lo que dice el modelo de la foto (no en una pregunta): quién lo sostiene y cómo.
_WHAT_ONLY_WORDS = frozenset({"alguien", "nadie", "mano", "manos", "puesto", "puesta", "puestos"})

#: Un gerundio («sosteniendo», «llevando») es una acción de alguien, no un objeto.
_GERUND = re.compile(r"\b\w{3,}(?:ando|iendo|yendo)\b")

#: Lo único que puede llevar un objeto dicho por el modelo: letras, cifras y poca puntuación.
_SAFE_WHAT = re.compile(r"^[\w\s\-/+.,'&]+$")

_COLOR_LINE = re.compile(r"^color\s*:\s*(.+)$", re.IGNORECASE)
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class ObjectEntry:
    """Un objeto del banco: su nombre, la pregunta para la cámara y el color de la tarjeta."""

    name: str
    question: str
    #: ``#RRGGBB`` o vacío (sin color propio).
    color: str = ""


def fold(text: str) -> str:
    """Minúsculas y sin tildes ni eñes: para comparar palabras sin que importe cómo se escriban."""
    decomposed = unicodedata.normalize("NFD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def words(text: str) -> list[str]:
    """Las palabras de un texto, sin tildes ni mayúsculas."""
    return re.findall(r"[a-z0-9]+", fold(text))


def mentions_person(text: str, kind: Literal["name", "question", "what"] = "name") -> bool:
    """¿Habla de la persona (quién es, su cuerpo o su ropa)?

    - ``name``: el nombre de un objeto del banco.
    - ``question``: una pregunta para la cámara (puede decir que la ropa no cuenta).
    - ``what``: lo que dice el modelo de una foto; además, si es una acción de alguien
      («sosteniendo una botella») o dice quién la tiene («alguien», «en la mano»).
    """
    found = words(text)
    banned = _QUESTION_WORDS if kind == "question" else _PERSON_WORDS
    if any(w in banned for w in found):
        return True
    if kind != "what":
        return False
    if any(w in _WHAT_ONLY_WORDS for w in found):
        return True
    return _GERUND.search(fold(text)) is not None


def clean_what(what: str, fallback: str) -> str:
    """El objeto que dice el modelo de la foto, listo para decirlo y para la pantalla.

    Solo se acepta una frase corta de objeto («botella azul»): si lleva algo de la persona,
    una acción, caracteres raros o es larga, se usa ``fallback`` (el objeto que se pidió). Es
    lo único que sale de la descripción del modelo hacia GPT-Live y la pantalla.
    """
    text = _SPACES.sub(" ", (what or "").strip()).strip(" .,;:!¡¿?\"'«»()[]")
    if not text or len(text) > WHAT_MAX_CHARS or not _SAFE_WHAT.match(text):
        return fallback
    if len(text.split()) > WHAT_MAX_WORDS or mentions_person(text, "what"):
        return fallback
    return text


#: Palabras sin peso al buscar un objeto en lo que dice Sonia («un», «algo», «de»...).
_STOP_WORDS = frozenset(
    "el la los las un una unos unas algo de del al con y o a en su tu".split()  # noqa: SIM905
)


def key_words(name: str) -> list[str]:
    """Las palabras que importan del nombre de un objeto («algo azul» -> ``azul``)."""
    return [w for w in words(name) if w not in _STOP_WORDS and len(w) > 2]


def announced(text: str, name: str) -> bool:
    """¿Ha dicho Sonia el objeto ``name`` en ``text``? Basta con la mitad de sus palabras clave.

    Sirve para sincronizar la pantalla con su voz (cuándo da la salida), no para entender a
    nadie. Sin palabras clave en el nombre no hay nada que comprobar y vale.
    """
    keys = key_words(name)
    if not keys:
        return True
    heard = set(words(text))
    return sum(1 for key in keys if key in heard) * 2 >= len(keys)


def _clean_heading(heading: str) -> str:
    """El encabezado sin énfasis de Markdown ni espacios de más."""
    return _SPACES.sub(" ", heading.strip().strip("*_`")).strip()


def parse_objects(text: str) -> BankParse[ObjectEntry]:
    """Lee el banco. Nunca lanza: lo que no encaja se salta con un aviso legible.

    Se salta el objeto con un nombre que no vale (muy corto o largo, con ``<``/``>``, repetido
    o que habla de la persona). Una pregunta o un color que no valen no tiran el objeto: se
    avisa y se usa la pregunta genérica o ningún color.
    """
    entries: list[ObjectEntry] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for heading, lines in markdown_sections(text):
        name = _clean_heading(heading)
        if not NAME_MIN <= len(name) <= NAME_MAX or re.search(r"[<>|]", name):
            warnings.append(
                f"«{heading[:40]}»: el nombre debe tener de {NAME_MIN} a {NAME_MAX} letras"
                " y sin < > |"
            )
            continue
        if mentions_person(name):
            warnings.append(f"«{name}»: habla de la persona (ropa, cuerpo...); se salta")
            continue
        key = fold(name)
        if key in seen:
            warnings.append(f"«{name}»: está repetido; se salta")
            continue

        question_parts: list[str] = []
        color = ""
        for line in lines:
            if line.startswith(">"):
                question_parts.append(line[1:].strip())
                continue
            match = _COLOR_LINE.match(line)
            if match:
                wanted = fold(match.group(1).strip())
                if wanted in COLORS:
                    color = COLORS[wanted]
                else:
                    warnings.append(f"«{name}»: color «{match.group(1).strip()}» desconocido")
                continue
            warnings.append(f"«{name}»: línea que no entiendo («{line[:40]}»); se ignora")

        question = _SPACES.sub(" ", " ".join(question_parts)).strip()
        if question and not _valid_question(question):
            warnings.append(
                f"«{name}»: la pregunta debe ser cerrada (con «?»), de {QUESTION_MIN} a "
                f"{QUESTION_MAX} letras y sin hablar de personas; se usa la genérica"
            )
            question = ""
        if not question:
            question = DEFAULT_QUESTION.format(name=name)

        seen.add(key)
        entries.append(ObjectEntry(name=name, question=question, color=color))
    return BankParse(entries, warnings)


def _valid_question(question: str) -> bool:
    return (
        QUESTION_MIN <= len(question) <= QUESTION_MAX
        and "?" in question
        and not re.search(r"[<>]", question)
        and not mentions_person(question, "question")
    )


#: El banco de la app (``assets/games/busqueda/objetos.md``) y el que se edita en el panel.
OBJECTS: GameBank[ObjectEntry] = GameBank(
    id="busqueda_objetos",
    title="Objetos de la búsqueda relámpago",
    file="objetos.md",
    parse=parse_objects,
    min_entries=6,
)
