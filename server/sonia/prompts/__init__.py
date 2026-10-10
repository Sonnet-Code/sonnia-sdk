"""Prompts de Sonnia editables desde el panel de la nube (petición de Jean del 10-oct-2026).

Todo texto que se le da a un modelo se registra aquí con su versión de la app: la persona,
el conocimiento, las reglas de GPT-Live, el backend, la visión, los gestos, el juez y los
juegos. Desde «Developer» en el panel se guarda otra versión en la nube (ajuste compartido
``prompts``). Si es válida, Sonnia usa SOLO esa, nunca las dos, para no darle información
doble; si no, la de la app.

    from sonia.prompts import BOOK
    BOOK.text("juez/busqueda")                       # el texto en uso
    BOOK.render("juegos/ruleta/reto", reto="...")    # con sus marcadores {reto} rellenos

Las piezas se declaran en ``specs_conversa.py`` (persona, conocimiento, GPT-Live, backend
y visión) y ``specs_modelos.py`` (juez, gestos, trivia y juegos), con su texto de la app
perezoso para no crear importaciones circulares.
"""

from sonia.prompts.book import (
    APPLIES_TEXT,
    BOOK,
    PLACEHOLDER,
    PROMPT_ID,
    PROMPT_MAX_LEN,
    PromptBook,
    PromptSpec,
    register,
)

__all__ = [
    "APPLIES_TEXT",
    "BOOK",
    "PLACEHOLDER",
    "PROMPT_ID",
    "PROMPT_MAX_LEN",
    "PromptBook",
    "PromptSpec",
    "load_specs",
    "register",
]


def load_specs() -> None:
    """Registra todas las piezas. La llama el panel antes de enseñar el catálogo, y cualquier
    módulo puede llamarla: es idempotente."""
    from sonia.prompts import specs_conversa, specs_modelos

    specs_conversa.register_all()
    specs_modelos.register_all()


BOOK.set_loader(load_specs)
