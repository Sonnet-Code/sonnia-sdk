"""Galería local de imágenes que Sonia puede mostrar en su panel.

Son dos directorios planos con archivos png/jpg/jpeg: el de la app
(``assets/gallery``) y el de las imágenes subidas desde el panel
(``GALLERY_UPLOAD_DIR``, por defecto ``cache/gallery``), que es escribible: en la
``.app`` de macOS ``assets`` va dentro del paquete y escribir ahí rompe la firma.
El id de una imagen es su nombre sin extensión; si un id está en las dos, gana la
de la app. La carga está protegida contra path traversal: el modelo escribe estos
ids y no queremos que un nombre creativo lea archivos de fuera de los directorios.

Nada de WebP: Unity decodifica el panel con ``ImageConversion.LoadImage``, que
solo entiende PNG y JPEG. Aceptar un ``.webp`` aquí haría que Sonia anunciara
en voz alta una imagen que en la pantalla no aparece nunca.
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

#: Extensiones aceptadas, por orden de preferencia si hay varias con el mismo id.
GALLERY_EXTENSIONS: tuple[str, ...] = (".png", ".jpg", ".jpeg")

MIME_BY_EXTENSION: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}

#: Lo que pesa como mucho una imagen subida desde el panel, ya decodificada. El
#: panel la reduce antes (1280 px y ~220 KB en JPEG) para que quepa en una acción.
UPLOAD_MAX_BYTES = 400 * 1024
#: Lado mínimo y máximo, en píxeles, de una imagen subida.
UPLOAD_MIN_SIDE = 16
UPLOAD_MAX_SIDE = 4096
#: Largo máximo del nombre saneado, sin la hora.
UPLOAD_SLUG_MAX = 40

#: Extensiones que se quitan del nombre que manda el panel (el de la foto).
_NAME_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".jpe", ".heic", ".heif", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
)

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
#: Marcadores SOF de JPEG (todos los C0-CF menos DHT, JPG y DAC): llevan el tamaño.
_JPEG_SOF = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}


class GalleryError(ValueError):
    """Imagen subida que no se puede guardar (el texto va tal cual al panel)."""


def _is_safe_id(image_id: str) -> bool:
    """Rechaza ids con separadores de ruta, referencias relativas o vacíos."""
    if not image_id or not image_id.strip():
        return False
    if "/" in image_id or "\\" in image_id or "\x00" in image_id:
        return False
    if ".." in image_id:
        return False
    return image_id not in (".", "..")


def _scan(directory: Path) -> dict[str, Path]:
    """Archivos válidos de ``directory`` indexados por id, leyendo el directorio una vez.

    Se recorre el directorio en lugar de probar ``id + extensión`` para que
    un ``LOGO.PNG`` se resuelva igual que se anuncia: en un sistema de
    archivos que distingue mayúsculas, probar solo minúsculas listaba ids
    que después no se podían cargar.
    """
    result: dict[str, Path] = {}
    if not directory.is_dir():
        return result
    preference = {extension: rank for rank, extension in enumerate(GALLERY_EXTENSIONS)}
    for entry in sorted(directory.iterdir()):
        if not entry.is_file():
            continue
        rank = preference.get(entry.suffix.lower())
        if rank is None:
            continue
        current = result.get(entry.stem)
        if current is None or rank < preference[current.suffix.lower()]:
            result[entry.stem] = entry
    return result


def _inside(path: Path, base: Path) -> Path | None:
    """Comprueba que el archivo queda dentro de ``base``."""
    try:
        resolved_base = base.resolve()
        resolved = path.resolve()
    except OSError:
        return None
    if not resolved.is_relative_to(resolved_base):
        logger.warning("Archivo de galería fuera del directorio: %s", path.name)
        return None
    return resolved if resolved.is_file() else None


def image_info(data: bytes) -> tuple[str, int, int]:
    """``(extensión, ancho, alto)`` de una imagen subida, leídos de su cabecera.

    Se mira el contenido (los bytes mágicos), no el nombre: una foto HEIC
    renombrada a ``.jpg`` no llega a la pantalla. Lanza :class:`GalleryError` con
    el motivo si no es un PNG o un JPEG válido o si no cumple los límites.
    """
    if len(data) > UPLOAD_MAX_BYTES:
        raise GalleryError(f"La imagen pesa demasiado (máximo {UPLOAD_MAX_BYTES // 1024} KB).")
    if data.startswith(_PNG_SIGNATURE):
        extension, size = ".png", _png_size(data)
    elif data.startswith(b"\xff\xd8\xff"):
        extension, size = ".jpg", _jpeg_size(data)
    else:
        raise GalleryError("Usa una foto JPG o PNG.")
    if size is None:
        raise GalleryError("La imagen está dañada: vuelve a elegirla.")
    width, height = size
    if not (
        UPLOAD_MIN_SIDE <= width <= UPLOAD_MAX_SIDE and UPLOAD_MIN_SIDE <= height <= UPLOAD_MAX_SIDE
    ):
        raise GalleryError(
            f"La imagen mide {width}x{height}: tiene que medir de {UPLOAD_MIN_SIDE} a "
            f"{UPLOAD_MAX_SIDE} píxeles por lado."
        )
    return extension, width, height


def _png_size(data: bytes) -> tuple[int, int] | None:
    """Ancho y alto del bloque ``IHDR``, que en un PNG va siempre el primero."""
    if len(data) < 24 or data[12:16] != b"IHDR":
        return None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    """Ancho y alto del marcador SOF, recorriendo los segmentos desde el principio."""
    index, end = 2, len(data)
    while index + 4 <= end:
        if data[index] != 0xFF:
            return None
        marker = data[index + 1]
        if marker == 0xFF:  # relleno entre segmentos
            index += 1
            continue
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:  # marcadores sin longitud
            index += 2
            continue
        if marker in (0xD9, 0xDA):  # fin de imagen o datos antes del tamaño
            return None
        length = int.from_bytes(data[index + 2 : index + 4], "big")
        if length < 2:
            return None
        if marker in _JPEG_SOF:
            if length < 7 or index + 9 > end:
                return None
            height = int.from_bytes(data[index + 5 : index + 7], "big")
            width = int.from_bytes(data[index + 7 : index + 9], "big")
            return width, height
        index += 2 + length
    return None


def upload_slug(name: str) -> str:
    """El nombre que manda el panel, legible y seguro: ``Logo GDG.png`` -> ``logo-gdg``.

    Sin tildes, en minúsculas, solo letras, números y guiones. Vacío si no queda
    nada (``../``, solo símbolos).
    """
    base = re.split(r"[\\/]", name.strip())[-1]
    stem, dot, suffix = base.rpartition(".")
    if dot and stem and f".{suffix.lower()}" in _NAME_SUFFIXES:
        base = stem
    ascii_text = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:UPLOAD_SLUG_MAX].strip("-")


class Gallery:
    """Las imágenes de la app y las subidas desde el panel.

    Leer es seguro en cualquier hilo; :meth:`add_upload` y :meth:`remove_upload`
    tocan el disco y se llaman en un hilo, nunca en el bucle de ``asyncio``.
    """

    def __init__(
        self,
        dir: Path | str,  # noqa: A002 - nombre fijado por el diseño
        upload_dir: Path | str | None = None,
    ) -> None:
        self.dir = Path(dir)
        # Una ruta vacía sería el directorio actual: sin carpeta de subidas.
        self.upload_dir = Path(upload_dir) if upload_dir and str(upload_dir).strip() else None

    @property
    def path(self) -> Path:
        return self.dir

    def _entries(self) -> dict[str, tuple[Path, bool]]:
        """``id -> (archivo, ¿subida?)`` de las dos carpetas; con el mismo id gana la app."""
        result: dict[str, tuple[Path, bool]] = {}
        if self.upload_dir is not None:
            result.update({i: (path, True) for i, path in _scan(self.upload_dir).items()})
        result.update({i: (path, False) for i, path in _scan(self.dir).items()})
        return result

    def _safe_path(self, path: Path, uploaded: bool) -> Path | None:
        """Comprueba que el archivo queda dentro de la carpeta de la que salió."""
        base = self.upload_dir if uploaded and self.upload_dir is not None else self.dir
        return _inside(path, base)

    def ids(self) -> list[str]:
        """Ids disponibles (nombre sin extensión), ordenados alfabéticamente.

        Solo se anuncian los que ``resolve`` sabe encontrar: el modelo recibe
        esta lista en el prompt y no debe pedir imágenes que fallarán.
        """
        return sorted(
            image_id
            for image_id, (path, uploaded) in self._entries().items()
            if self._safe_path(path, uploaded) is not None
        )

    def uploads(self) -> list[str]:
        """Los ids que vienen de la carpeta de subidas (los que el panel puede quitar)."""
        return sorted(
            image_id
            for image_id, (path, uploaded) in self._entries().items()
            if uploaded and self._safe_path(path, uploaded) is not None
        )

    def resolve(self, image_id: str) -> Path | None:
        """Devuelve la ruta del archivo de ``image_id``, o ``None`` si no es válido."""
        if not _is_safe_id(image_id):
            logger.warning("Id de galería rechazado por inseguro: %r", image_id)
            return None
        entry = self._entries().get(image_id)
        if entry is None:
            return None
        return self._safe_path(*entry)

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

    def add_upload(self, name: str, data: bytes, *, now: datetime) -> str:
        """Guarda una imagen subida desde el panel y devuelve su id (``logo-gdg-0731``).

        El id es el nombre saneado más la hora (``HHMM``), sin chocar con ninguno de
        las dos carpetas. Se escribe en un temporal y se renombra: el vigilante de la
        galería nunca ve una imagen a medias. Quien llama no lanza dos a la vez.
        """
        if self.upload_dir is None:
            raise GalleryError("Esta Sonnia no tiene dónde guardar imágenes.")
        extension, _, _ = image_info(data)
        slug = upload_slug(name)
        if not slug:
            raise GalleryError("Ponle a la imagen un nombre con letras o números.")
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        taken = set(self._entries()) | {
            entry.stem for entry in self.upload_dir.iterdir() if entry.is_file()
        }
        base = f"{slug}-{now:%H%M}"
        image_id = next(
            (
                candidate
                for candidate in (base, *(f"{base}-{n}" for n in range(2, 100)))
                if candidate not in taken
            ),
            None,
        )
        if image_id is None:
            raise GalleryError("Ya hay demasiadas imágenes con ese nombre: usa otro.")
        final = self.upload_dir / f"{image_id}{extension}"
        temp = self.upload_dir / f".{image_id}-{uuid.uuid4().hex[:8]}.part"
        try:
            with temp.open("wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, final)
        finally:
            temp.unlink(missing_ok=True)
        logger.info("Imagen subida a la galería: %s (%d bytes)", image_id, len(data))
        return image_id

    def remove_upload(self, image_id: str) -> bool:
        """Borra una imagen subida. ``False`` si no existe o es de la app (esas no se tocan)."""
        if self.upload_dir is None or not _is_safe_id(image_id):
            return False
        entry = self._entries().get(image_id)
        if entry is None or not entry[1]:
            return False
        path = self._safe_path(*entry)
        if path is None:
            return False
        path.unlink(missing_ok=True)
        # Si quedaba otra con el mismo id y otra extensión, también: si no, reaparecería.
        for extension in GALLERY_EXTENSIONS:
            for candidate in (f"{image_id}{extension}", f"{image_id}{extension.upper()}"):
                other = _inside(self.upload_dir / candidate, self.upload_dir)
                if other is not None:
                    other.unlink(missing_ok=True)
        logger.info("Imagen subida quitada de la galería: %s", image_id)
        return True
