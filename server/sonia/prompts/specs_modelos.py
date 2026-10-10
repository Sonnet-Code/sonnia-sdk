"""Piezas de los otros modelos y de los juegos: juez, gestos, trivia y los seis juegos.

Cada pieza se declara junto a su texto, en una función ``prompt_specs()`` del módulo que la
usa (así el texto y sus marcadores no se separan), y :func:`register_all` las registra en el
orden del panel. El módulo pide su texto con ``BOOK.text(id, fallback)`` o
``BOOK.render(id, fallback=..., **valores)`` en el momento de usarla. Con las versiones de la
app el resultado tiene que ser idéntico, byte a byte, al de antes (lo comprueban las
instantáneas de ``tests/snapshots/prompts_*.json``).
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable, Iterable

from sonia.prompts.book import PromptSpec, register

logger = logging.getLogger(__name__)

#: Los módulos que declaran piezas con ``prompt_specs()``, en el orden del panel. Se
#: importan al registrar (perezoso), así ``sonia.prompts`` no crea ciclos.
MODULES: tuple[str, ...] = (
    "sonia.vision.judge",
    "sonia.vision.referee",
    "sonia.gestures.prompt",
    "sonia.trivia.game",
    "sonia.games.manager",
    "sonia.games.ruleta.texts",
    "sonia.games.poses.game",
    "sonia.games.akinator.prompts",
    "sonia.games.ppt.game",
    "sonia.games.wordle.game",
    "sonia.games.busqueda.texts",
)


def module_specs(name: str) -> list[PromptSpec]:
    """Las piezas que declara el módulo ``name`` (ninguna si no tiene ``prompt_specs``)."""
    module = importlib.import_module(name)
    declare: Callable[[], Iterable[PromptSpec]] | None = getattr(module, "prompt_specs", None)
    return list(declare()) if declare is not None else []


def register_all() -> None:
    """Registra las piezas de este grupo (idempotente: cada id sustituye al anterior). Un
    módulo que falla no impide registrar los demás; los suyos usan su texto de la app."""
    for name in MODULES:
        try:
            specs = module_specs(name)
        except Exception:  # noqa: BLE001 - sin sus piezas, ese módulo usa su texto de la app
            logger.exception("No se pudieron declarar los prompts de %s", name)
            continue
        for spec in specs:
            register(spec)
