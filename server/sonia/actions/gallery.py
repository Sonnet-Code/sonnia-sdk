"""Local gallery of images Sonnia can show on her panel.

Two flat directories with png/jpg/jpeg files: the app's (``assets/gallery``) and
the one for images uploaded from the control panel (``GALLERY_UPLOAD_DIR``, by
default ``cache/gallery``), which is writable: in a macOS ``.app`` ``assets`` lives
inside the bundle and writing there breaks the signature. An image's id is its
name without extension; if an id is in both, the app's wins. Uploads are
recognized by their id, which starts with ``upload-`` (:data:`UPLOAD_PREFIX`):
that way the panel knows which ones can be removed from the list of ids alone.
Loading is protected against path traversal: the model writes these ids and we
do not want a creative name to read files outside the directories.

No WebP: Unity decodes the panel with ``ImageConversion.LoadImage``, which only
understands PNG and JPEG. Accepting a ``.webp`` here would make Sonnia announce
out loud an image that never shows up on screen.
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

#: Accepted extensions, in order of preference if several share the same id.
GALLERY_EXTENSIONS: tuple[str, ...] = (".png", ".jpg", ".jpeg")

MIME_BY_EXTENSION: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}

#: Maximum size of an image uploaded from the panel, already decoded. The panel
#: shrinks it first (1280 px and ~220 KB as JPEG) so it fits in one action.
UPLOAD_MAX_BYTES = 400 * 1024
#: Minimum and maximum side, in pixels, of an uploaded image.
UPLOAD_MIN_SIDE = 16
UPLOAD_MAX_SIDE = 4096
#: Maximum length of the sanitized name, without the time.
UPLOAD_SLUG_MAX = 40
#: What the id of an image uploaded from the panel starts with (``upload-team-logo-0731``).
#: The panel shows its remove button based on this prefix: it must match ``UPLOAD_PREFIX``
#: in ``panel/static/panel.js``.
UPLOAD_PREFIX = "upload-"

#: Extensions stripped from the name the panel sends (the photo's file name).
_NAME_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".jpe", ".heic", ".heif", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
)

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
#: JPEG SOF markers (all of C0-CF except DHT, JPG and DAC): they carry the size.
_JPEG_SOF = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}


class GalleryError(ValueError):
    """Uploaded image that cannot be saved (the text goes to the panel as is)."""


def _is_safe_id(image_id: str) -> bool:
    """Rejects ids with path separators, relative references, or empty ones."""
    if not image_id or not image_id.strip():
        return False
    if "/" in image_id or "\\" in image_id or "\x00" in image_id:
        return False
    if ".." in image_id:
        return False
    return image_id not in (".", "..")


def _scan(directory: Path) -> dict[str, Path]:
    """Valid files in ``directory`` indexed by id, reading the directory once.

    The directory is listed instead of trying ``id + extension`` so that a
    ``LOGO.PNG`` resolves the same way it is announced: on a case-sensitive
    file system, trying only lowercase listed ids that could not be loaded
    afterwards.
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
    """Checks that the file stays inside ``base``."""
    try:
        resolved_base = base.resolve()
        resolved = path.resolve()
    except OSError:
        return None
    if not resolved.is_relative_to(resolved_base):
        logger.warning("Gallery file outside the directory: %s", path.name)
        return None
    return resolved if resolved.is_file() else None


def image_info(data: bytes) -> tuple[str, int, int]:
    """``(extension, width, height)`` of an uploaded image, read from its header.

    The content (the magic bytes) is checked, not the name: a HEIC photo renamed
    to ``.jpg`` never reaches the screen. Raises :class:`GalleryError` with the
    reason if it is not a valid PNG or JPEG or if it breaks the limits.
    """
    if len(data) > UPLOAD_MAX_BYTES:
        raise GalleryError(f"The image is too big (at most {UPLOAD_MAX_BYTES // 1024} KB).")
    if data.startswith(_PNG_SIGNATURE):
        extension, size = ".png", _png_size(data)
    elif data.startswith(b"\xff\xd8\xff"):
        extension, size = ".jpg", _jpeg_size(data)
    else:
        raise GalleryError("Use a JPG or PNG picture.")
    if size is None:
        raise GalleryError("The image is damaged: pick it again.")
    width, height = size
    if not (
        UPLOAD_MIN_SIDE <= width <= UPLOAD_MAX_SIDE and UPLOAD_MIN_SIDE <= height <= UPLOAD_MAX_SIDE
    ):
        raise GalleryError(
            f"The image is {width}x{height}: each side must be from {UPLOAD_MIN_SIDE} to "
            f"{UPLOAD_MAX_SIDE} pixels."
        )
    return extension, width, height


def _png_size(data: bytes) -> tuple[int, int] | None:
    """Width and height from the ``IHDR`` chunk, which always comes first in a PNG."""
    if len(data) < 24 or data[12:16] != b"IHDR":
        return None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    """Width and height from the SOF marker, walking the segments from the start."""
    index, end = 2, len(data)
    while index + 4 <= end:
        if data[index] != 0xFF:
            return None
        marker = data[index + 1]
        if marker == 0xFF:  # fill byte between segments
            index += 1
            continue
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:  # markers without a length
            index += 2
            continue
        if marker in (0xD9, 0xDA):  # end of image, or data before the size
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
    """The name the panel sends, readable and safe: ``Team Logo.png`` -> ``team-logo``.

    No accents, lowercase, only letters, digits and hyphens. Empty if nothing is
    left (``../``, only symbols).
    """
    base = re.split(r"[\\/]", name.strip())[-1]
    stem, dot, suffix = base.rpartition(".")
    if dot and stem and f".{suffix.lower()}" in _NAME_SUFFIXES:
        base = stem
    ascii_text = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:UPLOAD_SLUG_MAX].strip("-")


class Gallery:
    """The app's images and the ones uploaded from the panel.

    Reading is safe from any thread; :meth:`add_upload` and :meth:`remove_upload`
    touch the disk and are called in a worker thread, never on the ``asyncio`` loop.
    """

    def __init__(
        self,
        dir: Path | str,  # noqa: A002 - name fixed by the design
        upload_dir: Path | str | None = None,
    ) -> None:
        self.dir = Path(dir)
        # An empty path would be the current directory: no upload folder.
        self.upload_dir = Path(upload_dir) if upload_dir and str(upload_dir).strip() else None

    @property
    def path(self) -> Path:
        return self.dir

    def _entries(self) -> dict[str, tuple[Path, bool]]:
        """``id -> (file, uploaded?)`` from both folders; for the same id the app's wins."""
        result: dict[str, tuple[Path, bool]] = {}
        if self.upload_dir is not None:
            result.update({i: (path, True) for i, path in _scan(self.upload_dir).items()})
        result.update({i: (path, False) for i, path in _scan(self.dir).items()})
        return result

    def _safe_path(self, path: Path, uploaded: bool) -> Path | None:
        """Checks that the file stays inside the folder it came from."""
        base = self.upload_dir if uploaded and self.upload_dir is not None else self.dir
        return _inside(path, base)

    def ids(self) -> list[str]:
        """Available ids (name without extension), sorted alphabetically.

        Only the ones ``resolve`` can find are announced: the model gets this
        list in the prompt and must not ask for images that will fail.
        """
        return sorted(
            image_id
            for image_id, (path, uploaded) in self._entries().items()
            if self._safe_path(path, uploaded) is not None
        )

    def resolve(self, image_id: str) -> Path | None:
        """Returns the file path for ``image_id``, or ``None`` if it is not valid."""
        if not _is_safe_id(image_id):
            logger.warning("Gallery id rejected as unsafe: %r", image_id)
            return None
        entry = self._entries().get(image_id)
        if entry is None:
            return None
        return self._safe_path(*entry)

    def load(self, image_id: str) -> tuple[bytes, str] | None:
        """Loads the image and returns ``(bytes, mime)``, or ``None`` if it does not exist."""
        path = self.resolve(image_id)
        if path is None:
            return None
        try:
            data = path.read_bytes()
        except OSError:
            logger.exception("Could not read the image '%s'", image_id)
            return None
        mime = MIME_BY_EXTENSION.get(path.suffix.lower(), "application/octet-stream")
        return data, mime

    def add_upload(self, name: str, data: bytes, *, now: datetime) -> str:
        """Saves an image uploaded from the panel and returns its id (``upload-team-logo-0731``).

        The id is :data:`UPLOAD_PREFIX`, the sanitized name and the time (``HHMM``),
        without clashing with any id in either folder. It is written to a temporary
        file and renamed: the gallery watcher never sees a half-written image. The
        caller never runs two at once.
        """
        if self.upload_dir is None:
            raise GalleryError("This Sonnia has nowhere to save images.")
        extension, _, _ = image_info(data)
        slug = upload_slug(name)
        if not slug:
            raise GalleryError("Give the image a name with letters or numbers.")
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        taken = set(self._entries()) | {
            entry.stem for entry in self.upload_dir.iterdir() if entry.is_file()
        }
        base = f"{UPLOAD_PREFIX}{slug}-{now:%H%M}"
        image_id = next(
            (
                candidate
                for candidate in (base, *(f"{base}-{n}" for n in range(2, 100)))
                if candidate not in taken
            ),
            None,
        )
        if image_id is None:
            raise GalleryError("There are too many images with that name already: use another one.")
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
        logger.info("Image uploaded to the gallery: %s (%d bytes)", image_id, len(data))
        return image_id

    def remove_upload(self, image_id: str) -> bool:
        """Deletes an uploaded image. ``False`` if it does not exist, does not start with
        ``upload-`` or is not in the upload folder (the app's images are never touched)."""
        if (
            self.upload_dir is None
            or not image_id.startswith(UPLOAD_PREFIX)
            or not _is_safe_id(image_id)
        ):
            return False
        entry = self._entries().get(image_id)
        if entry is None or not entry[1]:
            return False
        path = self._safe_path(*entry)
        if path is None:
            return False
        path.unlink(missing_ok=True)
        # Also any other file with the same id and another extension: otherwise it reappears.
        for extension in GALLERY_EXTENSIONS:
            for candidate in (f"{image_id}{extension}", f"{image_id}{extension.upper()}"):
                other = _inside(self.upload_dir / candidate, self.upload_dir)
                if other is not None:
                    other.unlink(missing_ok=True)
        logger.info("Uploaded image removed from the gallery: %s", image_id)
        return True
