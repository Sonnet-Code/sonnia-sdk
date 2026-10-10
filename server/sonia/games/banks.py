"""Bancos de los juegos editables desde el backoffice (``docs/juegos.md``, «Bancos»).

Funcionan como el banco de la trivia en la nube (``trivia_bank``, ``docs/panel.md``):

- El contenido de la app va en ``assets/games/<juego>/<archivo>.md``, con su formato
  explicado al principio del archivo (en un comentario HTML, que se ignora).
- Desde el panel se carga el banco en uso, se edita y se guarda en la nube, en el
  ajuste compartido ``game_banks`` (``{banco: texto}``). Manda sobre el archivo de la
  app y llega a todas las Sonnias sin instalar nada. «Volver al de la app» lo borra.
- Antes de guardarlo, el orquestador lo valida con el analizador del juego: un banco
  de más de :data:`BANK_MAX_CHARS` caracteres o con menos entradas válidas que
  ``min_entries`` no se guarda.
- Cada partida lo relee al empezar (:meth:`sonia.games.base.GameHost.load_bank`): lo
  mal formado se salta con un aviso en el registro, y si el de la nube no llega a
  ``min_entries``, se sigue con el de la app.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

__all__ = [
    "BANK_MAX_CHARS",
    "BankParse",
    "GameBank",
    "is_bank_id",
    "markdown_sections",
    "strip_comments",
]

#: Tope de un banco guardado en la nube: la nube guarda todos los ajustes compartidos en
#: un documento de 256 KB, y el banco de la trivia ya ocupa hasta 100 000 caracteres.
BANK_MAX_CHARS = 15_000

_BANK_ID = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def is_bank_id(value: object) -> bool:
    """¿Es un id de banco válido (``ruleta_adivinanzas``: minúsculas, cifras y ``_``)?"""
    return isinstance(value, str) and _BANK_ID.match(value) is not None


@dataclass(frozen=True, slots=True)
class BankParse[T]:
    """Lo que saca un analizador de un banco: las entradas válidas y un aviso por cada
    una que se salta (para el registro y para el panel al guardar)."""

    entries: list[T]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class GameBank[T]:
    """Un banco de un juego (lo declara :meth:`sonia.games.base.Game.banks`).

    - ``id``: clave en ``game_banks``, única entre todos los juegos: ``<juego>_<banco>``
      (``ruleta_adivinanzas``).
    - ``title``: lo que ve el equipo en el panel («Adivinanzas de la ruleta»).
    - ``file``: el archivo de la app dentro de ``assets/games/<id del juego>/``
      (``adivinanzas.md``).
    - ``parse``: el analizador del juego. Nunca lanza: lo que no entiende va a ``warnings``.
    - ``min_entries``: con menos entradas válidas no se guarda en la nube ni se juega.
    """

    id: str
    title: str
    file: str
    parse: Callable[[str], BankParse[T]]
    min_entries: int = 1


def strip_comments(text: str) -> str:
    """El texto sin comentarios HTML (``<!-- ... -->``): ahí va la explicación del formato."""
    return _COMMENT.sub("", text)


def markdown_sections(text: str, *, level: int = 2) -> list[tuple[str, list[str]]]:
    """Las secciones de un banco en Markdown: ``[(encabezado, líneas no vacías), ...]``.

    Una sección empieza en cada encabezado de ``level`` almohadillas (``## Kotlin``).
    Ignora los comentarios HTML y lo que hay antes del primer encabezado. Útil para
    bancos con el formato de la trivia (``assets/trivia/preguntas.md``).
    """
    marker = "#" * level + " "
    sections: list[tuple[str, list[str]]] = []
    for raw in strip_comments(text).splitlines():
        line = raw.strip()
        if line.startswith(marker):
            sections.append((line[len(marker) :].strip(), []))
        elif line and sections and not line.startswith("#"):
            sections[-1][1].append(line)
    return sections
