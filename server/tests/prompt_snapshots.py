"""Snapshots of the texts sent to the models (realtime session, backend, vision and trivia).

A change to a prompt shows up as a test failure with the full diff, so it is always
deliberate. To rewrite the snapshots on purpose:
``SONIA_WRITE_SNAPSHOTS=1 uv run --no-sync pytest -q tests/test_prompts_live.py
tests/test_prompts_trivia.py`` from ``server/``, then review the diff.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

SNAPSHOTS = Path(__file__).parent / "snapshots"


def assert_snapshot(name: str, data: Any) -> None:
    """Compares ``data`` (JSON types) with ``snapshots/<name>.json``."""
    path = SNAPSHOTS / f"{name}.json"
    text = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if os.environ.get("SONIA_WRITE_SNAPSHOTS") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return
    assert path.exists(), f"Snapshot {path.name} is missing (SONIA_WRITE_SNAPSHOTS=1)"
    expected = json.loads(path.read_text(encoding="utf-8"))
    assert json.loads(text) == expected
