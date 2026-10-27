"""Carpeta de datos de Sonnia Video y claves de las APIs.

En la carpeta de datos van la caché de voces (para no volver a pagar la misma toma),
los trabajos que se le mandan a Unity, el registro de la app y, por defecto, los
vídeos: ``~/Library/Application Support/Sonnia Video`` en macOS,
``%APPDATA%/Sonnia Video`` en Windows (``SONNIA_VIDEO_HOME`` la cambia).

Las claves (``GEMINI_API_KEY``, ``ELEVENLABS_API_KEY``) salen del entorno o de un
``.env``: el de ``home()``, el que la build deja junto al ejecutable congelado y,
al ejecutarlo desde el repo, el del repo. Las variables del entorno mandan y entre
los archivos manda el primero que la define. Nada de esto se imprime nunca.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from sonia.paths import REPO_ROOT, frozen
from sonia.video.errors import VideoError

__all__ = [
    "ELEVENLABS_KEY",
    "GEMINI_KEY",
    "env_files",
    "home",
    "load_env",
    "require_key",
]

APP_DIR_NAME = "Sonnia Video"
GEMINI_KEY = "GEMINI_API_KEY"
ELEVENLABS_KEY = "ELEVENLABS_API_KEY"


def home() -> Path:
    """Raíz de la caché, los trabajos y los vídeos (``SONNIA_VIDEO_HOME`` o la del usuario)."""
    explicit = os.environ.get("SONNIA_VIDEO_HOME", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_DIR_NAME
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "sonnia-video"


def env_files() -> list[Path]:
    """Los ``.env`` que se miran, del que más manda al que menos."""
    files = [home() / ".env"]
    if frozen():
        files.append(Path(sys.executable).resolve().parent / ".env")
    else:
        files.append(REPO_ROOT / ".env")
    return files


def load_env() -> list[Path]:
    """Carga los ``.env`` que existan sin pisar el entorno. Devuelve los que cargó."""
    from dotenv import load_dotenv

    loaded: list[Path] = []
    for path in env_files():
        if path.is_file():
            load_dotenv(path, override=False)
            loaded.append(path)
    return loaded


def require_key(name: str, what: str) -> str:
    """El valor de la clave ``name`` o un error que dice dónde ponerla (sin enseñar nada)."""
    value = os.environ.get(name, "").strip()
    if value:
        return value
    raise VideoError(
        f"Falta {name} para {what}. Ponla en {home() / '.env'} (una línea «{name}=...») "
        "o en el entorno antes de lanzar sonnia-video."
    )
