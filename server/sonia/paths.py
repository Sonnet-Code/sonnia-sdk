"""Dónde viven los datos de Sonia: en el repo al desarrollar y fuera de la app empaquetada.

Hay dos raíces:

- ``BUNDLE_ROOT``: lo de solo lectura que va con el programa (``assets/``). Es el
  repo al desarrollar y, en el orquestador congelado con PyInstaller, la carpeta
  donde PyInstaller descomprime sus datos (``sys._MEIPASS``).
- ``home()``: lo que cambia y lo que es de cada equipo (``cache/`` y
  ``overrides.env``). Es el repo al desarrollar; en la app, ``SONIA_HOME`` (lo pone
  Unity al lanzar el orquestador) o la carpeta de datos del usuario, para que la
  caché sobreviva a cada build.

El ``.env`` (``env_files()``): en la app va empaquetado junto al ejecutable (lo copia
la build; Jean: «los envs deben inyectarse en el build»), y por encima manda
``overrides.env`` de ``home()``, que escribe el backoffice para cambiar variables de
ese equipo sin recompilar.

Es la única excepción a «nadie lee ``os.environ``» (``sonia/config.py``): el
``.env`` sale de aquí, así que hay que saberlo antes de cargar la configuración.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

__all__ = [
    "BUNDLE_ROOT",
    "OVERRIDES_FILE",
    "REPO_ROOT",
    "env_files",
    "frozen",
    "home",
    "user_data_dir",
]

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Variables de este equipo que mandan sobre el `.env` (las escribe el backoffice).
OVERRIDES_FILE = "overrides.env"


def frozen() -> bool:
    """¿Es el orquestador congelado (PyInstaller) que va dentro de la app?"""
    return bool(getattr(sys, "frozen", False))


def _bundle_root() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if frozen() and base else REPO_ROOT


BUNDLE_ROOT = _bundle_root()


def user_data_dir() -> Path:
    """Carpeta de datos de Sonia para este usuario (macOS, Windows o Linux)."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Sonia"
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "Sonia"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "sonia"


def home() -> Path:
    """Raíz de ``cache/`` y ``overrides.env``: ``SONIA_HOME``, la carpeta del usuario (app) o el repo."""
    explicit = os.environ.get("SONIA_HOME", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return user_data_dir() if frozen() else REPO_ROOT


def env_files() -> list[Path]:
    """Archivos de variables, del que más manda al que menos.

    Primero ``overrides.env`` de ``home()`` (cambios desde el backoffice); después el
    ``.env`` de la app empaquetada (junto al ejecutable del orquestador) o el del
    repo al desarrollar.
    """
    bundled = Path(sys.executable).resolve().parent / ".env" if frozen() else REPO_ROOT / ".env"
    return [home() / OVERRIDES_FILE, bundled]
