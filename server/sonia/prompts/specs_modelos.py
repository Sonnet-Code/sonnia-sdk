"""Piezas de los otros modelos y de los juegos: juez, gestos, trivia y los seis juegos.

Cada pieza se registra en :func:`register_all` con su texto de la app en una función
perezosa (importa el módulo dentro, para no crear ciclos), y el módulo que la usa pide su
texto con ``BOOK.text(id)`` o ``BOOK.render(id, ...)`` en el momento de usarla. Con las
versiones de la app el resultado tiene que ser idéntico, byte a byte, al de antes.
"""

from __future__ import annotations


def register_all() -> None:
    """Registra las piezas de este grupo (idempotente)."""
