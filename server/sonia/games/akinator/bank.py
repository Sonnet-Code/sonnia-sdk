"""El banco de temas del Akinator dev (``assets/games/akinator/temas.md``).

Cada tema es una categoría en la que puede pensar el visitante («Lenguajes de
programación») con unos ejemplos que le dicen a Sonia qué nivel de cosas valen. Se edita
desde el backoffice como el banco de la trivia (``docs/juegos.md``, «Bancos»). El formato
está explicado al principio del archivo.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from sonia.games.banks import BankParse, GameBank, strip_comments

__all__ = [
    "MAX_EXAMPLES",
    "MIN_THEMES",
    "THEMES",
    "Theme",
    "normalize",
    "parse_themes",
    "safe_for_live",
    "theme_names",
    "themes_for_live",
]

#: Con menos temas, el banco ni se guarda desde el panel ni se juega.
MIN_THEMES = 3
#: Largo máximo del nombre de un tema (Sonia lo dice en voz alta; la pantalla no lo pinta) y de
#: cada ejemplo.
MAX_NAME_CHARS = 60
MAX_EXAMPLE_CHARS = 40
#: Ejemplos que se guardan de cada tema.
MAX_EXAMPLES = 24

#: Palabras que GPT-Live no puede leer (``test_sonia_no_conoce_las_marcas_de_su_stack``): Sonia
#: no conoce su stack. Un tema editado desde el panel puede traerlas («Unity» es un motor de
#: juegos muy conocido): salen en la pantalla pero no entran en las instrucciones.
_HIDDEN = re.compile(
    r"\b(gpt|openai|unity|genies|gemini|yolo|yolov8|opencv|mediapipe|onnx|luna|obs|darwin|windows)\b",
    re.IGNORECASE,
)
_BULLET = re.compile(r"^\s*[-*•]\s*")
_SPLIT = re.compile(r"[,;]")
#: «## Nombre» (también «##» a solas, que ``markdown_sections`` no ve como encabezado: aquí un
#: tema sin nombre se avisa y no se mezcla con el anterior). «###» no es un tema.
_HEADING = re.compile(r"^##(?!#)\s*(.*)$")


@dataclass(frozen=True, slots=True)
class Theme:
    """Un tema en el que puede pensar el visitante y unos ejemplos de lo que vale."""

    name: str
    examples: tuple[str, ...] = ()


def normalize(text: str) -> str:
    """Minúsculas, sin tildes ni signos y con los espacios colapsados (para comparar)."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9\s]", " ", plain).split())


def _sections(text: str) -> list[tuple[str, list[str]]]:
    """``[(nombre, líneas), ...]`` de un banco: una sección por cada ``## Tema``.

    Sin comentarios HTML; lo de antes del primer tema y las líneas de otros niveles
    (``# Título``, ``### Nota``) se ignoran.
    """
    sections: list[tuple[str, list[str]]] = []
    for raw in strip_comments(text).splitlines():
        line = raw.strip()
        heading = _HEADING.match(line)
        if heading is not None:
            sections.append((heading.group(1), []))
        elif line and sections and not line.startswith("#"):
            sections[-1][1].append(line)
    return sections


def parse_themes(text: str) -> BankParse[Theme]:
    """``## Tema`` y debajo ejemplos separados por comas. Lo que no encaja, aviso y fuera. Nunca lanza."""
    entries: list[Theme] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for heading, lines in _sections(text):
        name = " ".join(heading.split())
        if not name:
            warnings.append("hay un tema sin nombre (una línea «##» sin nada detrás)")
            continue
        if len(name) > MAX_NAME_CHARS:
            warnings.append(f"«{name[:30]}…»: el nombre pasa de {MAX_NAME_CHARS} caracteres")
            continue
        key = normalize(name)
        if not key:
            warnings.append(f"«{name}»: el nombre no tiene letras ni cifras")
            continue
        if key in seen:
            warnings.append(f"«{name}»: tema repetido")
            continue
        seen.add(key)
        examples: list[str] = []
        listed: set[str] = set()
        skipped = 0
        for line in lines:
            for piece in _SPLIT.split(_BULLET.sub("", line)):
                example = " ".join(piece.split())
                example_key = normalize(example)
                if not example_key or example_key in listed:
                    continue
                if len(example) > MAX_EXAMPLE_CHARS:
                    skipped += 1
                    continue
                listed.add(example_key)
                examples.append(example)
        if skipped:
            warnings.append(
                f"«{name}»: {skipped} ejemplo(s) pasan de {MAX_EXAMPLE_CHARS} caracteres y se saltan"
            )
        entries.append(Theme(name, tuple(examples[:MAX_EXAMPLES])))
    return BankParse(entries, warnings)


THEMES: GameBank[Theme] = GameBank(
    id="akinator_temas",
    title="Temas del Akinator dev",
    file="temas.md",
    parse=parse_themes,
    min_entries=MIN_THEMES,
)


def theme_names(themes: Sequence[Theme]) -> list[str]:
    """Los nombres de los temas, tal cual salen en la pantalla."""
    return [theme.name for theme in themes]


def safe_for_live(text: str) -> bool:
    """¿Puede leerlo GPT-Live? (sin marcas del stack)."""
    return _HIDDEN.search(text) is None


def themes_for_live(themes: Sequence[Theme], budget: int) -> str:
    """Los temas como los lee GPT-Live: ``Lenguajes (Python, Kotlin); Empresas (Google, Meta)``.

    Cabe en ``budget`` caracteres: primero se intenta con 3 ejemplos por tema y se baja a 2, 1
    y a solo los nombres; si aun así no cabe, se quitan temas del final (nunca quedan menos de
    uno). Sin las palabras que Sonia no puede conocer (:data:`_HIDDEN`).
    """
    usable = [t for t in themes if safe_for_live(t.name)]
    if not usable:
        return ""

    def render(items: Sequence[Theme], per_theme: int) -> str:
        parts: list[str] = []
        for theme in items:
            shown = [e for e in theme.examples if safe_for_live(e)][:per_theme]
            parts.append(f"{theme.name} ({', '.join(shown)})" if shown else theme.name)
        return "; ".join(parts)

    for per_theme in (3, 2, 1, 0):
        line = render(usable, per_theme)
        if len(line) <= budget:
            return line
    items = list(usable)
    while len(items) > 1:
        items.pop()
        line = render(items, 0)
        if len(line) <= budget:
            return line
    # Ni uno cabe: se queda el primero entero (quien monta el texto corta el total).
    return render(items, 0)
