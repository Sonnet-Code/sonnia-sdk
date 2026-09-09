"""Galería local de imágenes que Sonia puede mostrar en su panel.

Es un directorio plano con archivos png/jpg/jpeg. El id de una imagen es su
nombre sin extensión. La carga está protegida contra path traversal: el modelo
escribe estos ids y no queremos que un nombre creativo lea archivos de fuera
del directorio.

Nada de WebP: Unity decodifica el panel con ``ImageConversion.LoadImage``, que
solo entiende PNG y JPEG. Aceptar un ``.webp`` aquí haría que Sonia anunciara
en voz alta una imagen que en la pantalla no aparece nunca.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

#: Extensiones aceptadas, por orden de preferencia si hay varias con el mismo id.
GALLERY_EXTENSIONS: tuple[str, ...] = (".png", ".jpg", ".jpeg")

MIME_BY_EXTENSION: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


def _is_safe_id(image_id: str) -> bool:
    """Rechaza ids con separadores de ruta, referencias relativas o vacíos."""
    if not image_id or not image_id.strip():
        return False
    if "/" in image_id or "\\" in image_id or "\x00" in image_id:
        return False
    if ".." in image_id:
        return False
    return image_id not in (".", "..")


class Gallery:
    """Acceso de solo lectura a un directorio de imágenes."""

    def __init__(self, dir: Path | str) -> None:  # noqa: A002 - nombre fijado por el diseño
        self.dir = Path(dir)

    @property
    def path(self) -> Path:
        return self.dir

    def _entries(self) -> dict[str, Path]:
        """Archivos válidos indexados por id, leyendo el directorio una vez.

        Se recorre el directorio en lugar de probar ``id + extensión`` para que
        un ``LOGO.PNG`` se resuelva igual que se anuncia: en un sistema de
        archivos que distingue mayúsculas, probar solo minúsculas listaba ids
        que después no se podían cargar.
        """
        result: dict[str, Path] = {}
        if not self.dir.is_dir():
            return result
        preference = {extension: rank for rank, extension in enumerate(GALLERY_EXTENSIONS)}
        for entry in sorted(self.dir.iterdir()):
            if not entry.is_file():
                continue
            rank = preference.get(entry.suffix.lower())
            if rank is None:
                continue
            current = result.get(entry.stem)
            if current is None or rank < preference[current.suffix.lower()]:
                result[entry.stem] = entry
        return result

    def _safe_path(self, path: Path) -> Path | None:
        """Comprueba que el archivo queda dentro del directorio de la galería."""
        try:
            base = self.dir.resolve()
            resolved = path.resolve()
        except OSError:
            return None
        if not resolved.is_relative_to(base):
            logger.warning("Archivo de galería fuera del directorio: %s", path.name)
            return None
        return resolved if resolved.is_file() else None

    def ids(self) -> list[str]:
        """Ids disponibles (nombre sin extensión), ordenados alfabéticamente.

        Solo se anuncian los que ``resolve`` sabe encontrar: el modelo recibe
        esta lista en el prompt y no debe pedir imágenes que fallarán.
        """
        return sorted(
            image_id
            for image_id, path in self._entries().items()
            if self._safe_path(path) is not None
        )

    def resolve(self, image_id: str) -> Path | None:
        """Devuelve la ruta del archivo de ``image_id``, o ``None`` si no es válido."""
        if not _is_safe_id(image_id):
            logger.warning("Id de galería rechazado por inseguro: %r", image_id)
            return None
        path = self._entries().get(image_id)
        if path is None:
            return None
        return self._safe_path(path)

    def load(self, image_id: str) -> tuple[bytes, str] | None:
        """Carga la imagen y devuelve ``(bytes, mime)``, o ``None`` si no existe."""
        path = self.resolve(image_id)
        if path is None:
            return None
        try:
            data = path.read_bytes()
        except OSError:
            logger.exception("No se pudo leer la imagen '%s'", image_id)
            return None
        mime = MIME_BY_EXTENSION.get(path.suffix.lower(), "application/octet-stream")
        return data, mime
