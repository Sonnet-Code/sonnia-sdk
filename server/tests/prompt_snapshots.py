"""Instantáneas de los textos que se mandan a los modelos (juez, gestos, trivia y juegos).

Se sacaron con el código de antes de hacerlos editables desde la nube (``sonia.prompts``):
con los textos de la app, lo que se monta tiene que ser idéntico, byte a byte. Para
rehacer una a propósito: ``SONIA_WRITE_SNAPSHOTS=1 uv run --no-sync pytest -q <test>``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sonia.prompts import BOOK

SNAPSHOTS = Path(__file__).parent / "snapshots"


def assert_snapshot(name: str, data: Any) -> None:
    """Compara ``data`` (tipos JSON) con ``snapshots/<name>.json``."""
    path = SNAPSHOTS / f"{name}.json"
    text = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if os.environ.get("SONIA_WRITE_SNAPSHOTS") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return
    assert path.exists(), f"Falta la instantánea {path.name} (SONIA_WRITE_SNAPSHOTS=1)"
    expected = json.loads(path.read_text(encoding="utf-8"))
    assert json.loads(text) == expected


@contextmanager
def cloud_prompts(overrides: dict[str, str]) -> Iterator[None]:
    """Versiones «de la nube» en el registro de la app mientras dura el ``with``. Tienen que
    validar: si no, el test falla (se usaría la de la app sin darse cuenta)."""
    warnings = BOOK.set_overrides(overrides)
    assert warnings == [], warnings
    assert all(BOOK.source(prompt_id) == "nube" for prompt_id in overrides)
    try:
        yield
    finally:
        BOOK.set_overrides(None)
