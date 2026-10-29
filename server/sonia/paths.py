"""Where Sonnia's data lives.

There are two roots:

- ``BUNDLE_ROOT``: the read-only data that ships with the program (``assets/``). It is
  the root of the repository.
- ``home()``: what changes and what belongs to each machine (``cache/`` and
  ``overrides.env``). It is ``SONIA_HOME`` if set (for example when the avatar client
  launches the orchestrator) and the root of the repository otherwise.

The variables files (``env_files()``): ``overrides.env`` in ``home()`` wins over the
repository ``.env``, so a machine can change a few variables without touching it.

This is the only exception to "nobody reads ``os.environ``" (``sonia/config.py``): the
``.env`` location comes from here, so it has to be known before loading the settings.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["BUNDLE_ROOT", "OVERRIDES_FILE", "REPO_ROOT", "env_files", "home"]

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Read-only data that ships with the orchestrator (``assets/``).
BUNDLE_ROOT = REPO_ROOT

#: Variables of this machine that win over the `.env`.
OVERRIDES_FILE = "overrides.env"


def home() -> Path:
    """Root of ``cache/`` and ``overrides.env``: ``SONIA_HOME`` or the repository."""
    explicit = os.environ.get("SONIA_HOME", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return REPO_ROOT


def env_files() -> list[Path]:
    """Variables files, from the one that wins to the one that loses: ``overrides.env``
    in ``home()`` and the repository ``.env``."""
    return [home() / OVERRIDES_FILE, REPO_ROOT / ".env"]
