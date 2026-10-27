"""El guion de un vídeo: lectura del TOML, validación, opciones y la regla del nombre.

El guion se escribe en español (``sonnia-video ejemplo`` enseña todas las opciones) y
aquí se traduce a lo que entiende el renderizador de Unity (``scene`` del trabajo,
``docs/video.md``). Los atributos van en inglés y las claves del TOML en español
(``alias`` de pydantic): los errores hablan con las claves del TOML.

Regla del nombre (CLAUDE.md, principio 6): lo que se lee dice «Sonnia» y lo que se
dice, «Sonia». El texto de cada frase se enseña con «Sonnia» (subtítulos y SRT) y al
TTS le llega «Sonia», además de la tabla ``[pronunciacion]`` (lo que se ve → lo que
se dice). Cada palabra que se ve sabe qué palabras dichas le tocan (``Unit``), para
poner en pantalla «sonnetcode.com» mientras suena «sónet code punto com».
"""

from __future__ import annotations

import re
import tomllib
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticUndefined

from sonia.video.errors import VideoError

__all__ = [
    "EXAMPLE",
    "Overrides",
    "PhraseText",
    "Quality",
    "Script",
    "Unit",
    "apply_overrides",
    "load_script",
    "parse_script",
    "phrase_texts",
    "quality",
    "scene_message",
    "script_from_text",
    "slug",
    "spoken",
    "split_sentences",
    "title_of",
    "tts_text",
    "video_size",
    "written",
]

WRITTEN_NAME = "Sonnia"
SPOKEN_NAME = "Sonia"

#: «Sonia» (o «Sonía») escrito en el guion: en pantalla sale «Sonnia».
_SPOKEN_NAME_RE = re.compile(r"\bson[ií]a\b", re.IGNORECASE)
#: «Sonnia» en lo que va al TTS: se dice «Sonia».
_WRITTEN_NAME_RE = re.compile(r"\bsonnia\b", re.IGNORECASE)


def _same_case(word: str, name: str) -> str:
    if word.isupper():
        return name.upper()
    return name if word[0].isupper() else name.lower()


def written(text: str) -> str:
    """El texto como se lee: el nombre siempre «Sonnia»."""
    return _SPOKEN_NAME_RE.sub(lambda m: _same_case(m.group(0), WRITTEN_NAME), text)


def spoken(text: str) -> str:
    """El texto como se dice: el nombre siempre «Sonia»."""
    return _WRITTEN_NAME_RE.sub(lambda m: _same_case(m.group(0), SPOKEN_NAME), text)


# ---------------------------------------------------------------------------
# Opciones
# ---------------------------------------------------------------------------

#: Formatos con nombre: ancho y alto en píxeles.
FORMATS: dict[str, tuple[int, int]] = {
    "vertical": (1080, 1920),
    "cuadrado": (1080, 1080),
    "horizontal": (1920, 1080),
    # Sobre todo para fotos (sonnia-video foto).
    "4k-vertical": (2160, 3840),
}
_SIZE_RE = re.compile(r"^\s*(\d{2,5})\s*[x×X]\s*(\d{2,5})\s*$")
MIN_SIDE = 64
MAX_SIDE = 4096

#: Nombres del guion → nombres del contrato con Unity.
LIGHTS = {
    "stand": "stand",
    "estudio": "studio",
    "suave": "soft",
    "calida": "warm",
    "fria": "cool",
    "dramatica": "dramatic",
}
FRAMINGS = {
    "stand": "stand",
    "primer-plano": "close",
    "medio": "medium",
    "americano": "cowboy",
    "cuerpo": "full",
}
BACKGROUNDS = {
    "stand": "stand",
    "color": "color",
    "degradado": "gradient",
    "imagen": "image",
    "transparente": "transparent",
}
OUTFITS = {"staff": "staff", "lisa": "plain"}
EMOTIONS = {"alegre": "joy", "neutra": "neutral"}

_COLOR_RE = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


@dataclass(frozen=True, slots=True)
class Quality:
    """Cómo renderiza Unity y cómo codifica ffmpeg cada calidad."""

    supersample: int
    subframes: int
    shutter: float
    crf: int
    preset: str


QUALITIES: dict[str, Quality] = {
    "borrador": Quality(supersample=1, subframes=1, shutter=0.5, crf=23, preset="veryfast"),
    "normal": Quality(supersample=2, subframes=1, shutter=0.5, crf=18, preset="medium"),
    "alta": Quality(supersample=2, subframes=4, shutter=0.5, crf=14, preset="slow"),
}


def _plain(value: Any) -> Any:
    """Minúsculas y sin tildes (``cálida`` → ``calida``), para aceptar las dos formas."""
    if not isinstance(value, str):
        return value
    text = unicodedata.normalize("NFKD", value.strip().lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.replace(" ", "-").replace("_", "-")


def _color(value: str, *, allow_empty: bool = False) -> str:
    value = value.strip()
    if allow_empty and not value:
        return ""
    match = _COLOR_RE.match(value)
    if match is None:
        raise ValueError(f"«{value}» no es un color: escríbelo como #142752")
    return "#" + match.group(1).upper()


def _es(name: str, default: Any = PydanticUndefined, **options: Any) -> Any:
    """Un campo que en el TOML se llama ``name`` (en español)."""
    return Field(default, validation_alias=name, serialization_alias=name, **options)


#: Opciones de escena que ya no existen (los vídeos salen sin HUD del stand, decisión de Jean
#: del 27-oct-2026): con ellas el guion da un error que lo explica.
REMOVED_SCENE_KEYS = ("logo", "qr", "subtitulos")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, validate_assignment=True)


class VoiceOptions(_Model):
    """``[voz]``: quién pone la voz y cómo."""

    engine: Literal["gemini", "elevenlabs", "archivo"] = _es("motor", "gemini")
    #: Gemini: nombre de la voz; ElevenLabs: su id o su nombre. Vacío: la de cada motor.
    voice: str = _es("voz", "")
    #: Vacío: el de cada motor.
    model: str = _es("modelo", "")
    #: Gemini: indicación de estilo (texto; vacío, la de acento latinoamericano; «ninguno», sin
    #: estilo). ElevenLabs: exageración del estilo, de 0 a 1.
    style: str | float | None = _es("estilo", None)
    stability: float | None = _es("estabilidad", None, ge=0.0, le=1.0)
    similarity: float | None = _es("similitud", None, ge=0.0, le=1.0)
    speed: float | None = _es("velocidad", None, ge=0.5, le=2.0)
    #: ElevenLabs: ``language_code`` (``es``); también el idioma de la transcripción
    #: (``es-419`` si se deja vacío).
    language: str = _es("idioma", "")
    #: Motor ``archivo``: el WAV o MP3 grabado.
    file: str = _es("archivo", "")

    @field_validator("engine", mode="before")
    @classmethod
    def _engine(cls, value: Any) -> Any:
        return _plain(value)

    @field_validator("style")
    @classmethod
    def _style(cls, value: str | float | None, info: ValidationInfo) -> str | float | None:
        engine = info.data.get("engine")
        if value is None or isinstance(value, bool):
            return None if value is None else float(value)
        if engine == "gemini" and not isinstance(value, str):
            raise ValueError("con Gemini, estilo es un texto que describe cómo hablar")
        if engine == "elevenlabs":
            if isinstance(value, str):
                if not value.strip():
                    return None
                try:
                    value = float(value.replace(",", "."))
                except ValueError:
                    raise ValueError("con ElevenLabs, estilo es un número de 0 a 1") from None
            if not 0 <= value <= 1:
                raise ValueError("con ElevenLabs, estilo va de 0 a 1")
            return float(value)
        return value

    @model_validator(mode="after")
    def _per_engine(self) -> VoiceOptions:
        if self.engine == "archivo" and not self.file.strip():
            raise ValueError('con motor = "archivo" hace falta archivo = "voz.wav"')
        return self


class VideoOptions(_Model):
    """``[video]``: tamaño, ritmo, calidad y márgenes."""

    format: str = _es("formato", "vertical")
    fps: int = Field(default=30, ge=1, le=120)
    quality: Literal["borrador", "normal", "alta"] = _es("calidad", "normal")
    #: Segundos de reposo antes de la primera frase y después de la última.
    lead_s: float = _es("antes", 0.6, ge=0.0, le=30.0)
    tail_s: float = _es("despues", 1.5, ge=0.0, le=60.0)
    #: Carpeta de un reel de ``media/reels/<id>`` (repo de Sonnet Code): con fondo transparente,
    #: el paquete de Sonnia va directo a ``<reel>/assets/sonnia/``.
    reel: str = _es("reel", "")

    @field_validator("format", mode="before")
    @classmethod
    def _format(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        name = _plain(value)
        if name in FORMATS:
            return name
        match = _SIZE_RE.match(value)
        if match is None:
            raise ValueError(
                f"«{value}» no es un formato: usa vertical, cuadrado, horizontal o ANCHOxALTO"
            )
        width, height = int(match.group(1)), int(match.group(2))
        for side in (width, height):
            if not MIN_SIDE <= side <= MAX_SIDE:
                raise ValueError(f"cada lado va de {MIN_SIDE} a {MAX_SIDE} píxeles")
            if side % 2:
                raise ValueError("ancho y alto tienen que ser pares (lo pide H.264)")
        return f"{width}x{height}"

    @field_validator("quality", mode="before")
    @classmethod
    def _quality(cls, value: Any) -> Any:
        return _plain(value)


class SceneOptions(_Model):
    """``[escena]``: fondo, luz, encuadre y vestuario."""

    background: Literal["stand", "color", "degradado", "imagen", "transparente"] = _es(
        "fondo", "stand"
    )
    color: str = "#142752"
    color2: str = "#0B1322"
    image: str = _es("imagen", "")
    particles: bool = _es("particulas", True)
    light: Literal["stand", "estudio", "suave", "calida", "fria", "dramatica"] = _es("luz", "stand")
    light_intensity: float = _es("luz_intensidad", 1.0, ge=0.0, le=4.0)
    ambient: float = _es("luz_ambiente", 1.0, ge=0.0, le=4.0)
    rim: str = _es("contraluz", "")
    rim_intensity: float = _es("contraluz_intensidad", 1.5, ge=0.0, le=5.0)
    exposure: float = _es("exposicion", 0.0, ge=-4.0, le=4.0)
    framing: Literal["stand", "primer-plano", "medio", "americano", "cuerpo"] = _es(
        "encuadre", "stand"
    )
    zoom: float = Field(default=1.0, ge=0.25, le=4.0)
    offset_x: float = _es("desplazar_x", 0.0, ge=-1.0, le=1.0)
    offset_y: float = _es("desplazar_y", 0.0, ge=-1.0, le=1.0)
    outfit: Literal["staff", "lisa"] = _es("camiseta", "staff")
    cap: bool = _es("gorra", False)
    emotion: Literal["alegre", "neutra"] = _es("emocion", "alegre")

    @model_validator(mode="before")
    @classmethod
    def _gone(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for key in REMOVED_SCENE_KEYS:
                if key in data:
                    raise ValueError(
                        f"«{key}» ya no existe: los vídeos salen sin logo, QR ni subtítulos en "
                        "pantalla (los subtítulos van aparte, en el .srt); quítalo del guion"
                    )
        return data

    @field_validator("background", "light", "framing", "outfit", "emotion", mode="before")
    @classmethod
    def _names(cls, value: Any) -> Any:
        return _plain(value)

    @field_validator("color", "color2")
    @classmethod
    def _colors(cls, value: str) -> str:
        return _color(value)

    @field_validator("rim")
    @classmethod
    def _rim(cls, value: str) -> str:
        return _color(value, allow_empty=True)

    @model_validator(mode="after")
    def _image(self) -> SceneOptions:
        if self.background == "imagen" and not self.image.strip():
            raise ValueError('con fondo = "imagen" hace falta imagen = "fondo.png"')
        return self


class GestureOptions(_Model):
    """``[gestos]``: ``auto`` (el modelo elige; los de cada frase mandan), ``manual`` (solo los
    escritos en cada frase) o ``ninguno``."""

    mode: Literal["auto", "manual", "ninguno"] = _es("modo", "auto")

    @field_validator("mode", mode="before")
    @classmethod
    def _mode(cls, value: Any) -> Any:
        return _plain(value)


class Phrase(_Model):
    """``[[frase]]``: lo que dice Sonnia, con su gesto y su pausa opcionales."""

    text: str = _es("texto", min_length=1)
    gesture: str = _es("gesto", "")
    #: Silencio extra después de la frase, en segundos.
    pause: float = _es("pausa", 0.0, ge=0.0, le=20.0)

    @field_validator("text")
    @classmethod
    def _text(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("la frase está vacía")
        return value


class Action(_Model):
    """``[[accion]]``: un gesto suelto a esa hora del vídeo, fuera de las frases."""

    at: float = Field(
        validation_alias=AliasChoices("en", "segundo"), serialization_alias="en", ge=0.0
    )
    gesture: str = _es("gesto", min_length=1)
    mirror: bool = _es("espejo", False)


class Script(_Model):
    """Un guion entero."""

    title: str = _es("titulo", "")
    voice: VoiceOptions = _es("voz", default_factory=VoiceOptions)
    pronunciation: dict[str, str] = _es("pronunciacion", default_factory=dict)
    video: VideoOptions = Field(default_factory=VideoOptions)
    scene: SceneOptions = _es("escena", default_factory=SceneOptions)
    gestures: GestureOptions = _es("gestos", default_factory=GestureOptions)
    phrases: list[Phrase] = _es("frase", min_length=1)
    actions: list[Action] = _es("accion", default_factory=list)

    @model_validator(mode="after")
    def _reel(self) -> Script:
        if self.video.reel.strip() and self.scene.background != "transparente":
            raise ValueError(
                'el paquete para un reel (reel = "...") necesita fondo = "transparente" en [escena]'
            )
        return self


# ---------------------------------------------------------------------------
# Lectura y errores
# ---------------------------------------------------------------------------

_MESSAGES = {
    "extra_forbidden": "opción desconocida",
    "missing": "falta",
    "string_too_short": "no puede estar vacío",
    "too_short": "hace falta al menos una",
    "float_parsing": "tiene que ser un número",
    "float_type": "tiene que ser un número",
    "int_parsing": "tiene que ser un número entero",
    "int_type": "tiene que ser un número entero",
    "int_from_float": "tiene que ser un número entero",
    "bool_parsing": "tiene que ser true o false",
    "bool_type": "tiene que ser true o false",
    "string_type": "tiene que ser un texto entre comillas",
    "dict_type": "tiene que ser una tabla",
    "model_type": "tiene que ser una tabla",
    "model_attributes_type": "tiene que ser una tabla",
    "list_type": "tiene que ser una lista",
}


def _where(loc: tuple[int | str, ...]) -> str:
    parts: list[str] = []
    for item in loc:
        if isinstance(item, int):
            parts.append(f"{item + 1}")
        elif item not in {"str", "float", "int"}:
            parts.append(str(item))
    return " → ".join(parts) or "guion"


def explain(error: ValidationError) -> str:
    """Los errores de validación del guion, uno por línea y en español."""
    lines: list[str] = []
    for item in error.errors():
        kind = item["type"]
        ctx = item.get("ctx") or {}
        if kind == "value_error":
            message = str(ctx.get("error") or item["msg"]).removeprefix("Value error, ")
        elif kind == "literal_error":
            expected = str(ctx.get("expected", "")).replace("'", "").replace(" or ", " o ")
            message = f"valor no válido; vale {expected}"
        elif kind in {"greater_than_equal", "greater_than"}:
            limit = ctx.get("ge", ctx.get("gt"))
            message = f"tiene que ser {'≥' if kind == 'greater_than_equal' else '>'} {limit}"
        elif kind in {"less_than_equal", "less_than"}:
            limit = ctx.get("le", ctx.get("lt"))
            message = f"tiene que ser {'≤' if kind == 'less_than_equal' else '<'} {limit}"
        else:
            message = _MESSAGES.get(kind, item["msg"])
        line = f"  {_where(tuple(item['loc']))}: {message}"
        if line not in lines:
            lines.append(line)
    return "\n".join(lines)


def parse_script(data: dict[str, Any], *, base_dir: Path | None = None, source: str = "") -> Script:
    """Valida un guion ya leído (dict del TOML) y resuelve sus rutas relativas a ``base_dir``."""
    try:
        script = Script.model_validate(data)
    except ValidationError as exc:
        where = f" en {source}" if source else ""
        raise VideoError(f"El guion tiene errores{where}:\n{explain(exc)}") from None
    if base_dir is not None:
        _resolve_paths(script, base_dir)
    return script


def load_script(path: Path) -> Script:
    """Lee y valida un guion TOML."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise VideoError(f"No existe el guion {path}") from None
    except OSError as exc:
        raise VideoError(f"No se pudo leer el guion {path}: {exc}") from None
    try:
        data = tomllib.loads(raw)
    except tomllib.TOMLDecodeError as exc:
        raise VideoError(f"El guion {path.name} no es un TOML válido: {exc}") from None
    return parse_script(data, base_dir=path.resolve().parent, source=path.name)


def _resolve_paths(script: Script, base_dir: Path) -> None:
    if script.voice.file.strip():
        script.voice.file = str((base_dir / Path(script.voice.file).expanduser()).resolve())
    if script.scene.image.strip():
        script.scene.image = str((base_dir / Path(script.scene.image).expanduser()).resolve())
    if script.video.reel.strip():
        script.video.reel = str((base_dir / Path(script.video.reel).expanduser()).resolve())


def check_files(script: Script) -> None:
    """Que existan los archivos que nombra el guion (antes de gastar en nada)."""
    if script.voice.engine == "archivo" and not Path(script.voice.file).is_file():
        raise VideoError(f"No existe el audio de la voz: {script.voice.file}")
    if script.scene.background == "imagen" and not Path(script.scene.image).is_file():
        raise VideoError(f"No existe la imagen del fondo: {script.scene.image}")


# ---------------------------------------------------------------------------
# Opciones de la línea de órdenes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Overrides:
    """Lo que se pide con flags y pisa lo del guion (``None``: no se tocó)."""

    voice: str | None = None
    format: str | None = None
    fps: int | None = None
    quality: str | None = None
    reel: str | None = None
    light: str | None = None
    background: str | None = None
    framing: str | None = None
    emotion: str | None = None
    no_gestures: bool = False
    title: str | None = None


def apply_overrides(script: Script, overrides: Overrides) -> Script:
    """Una copia del guion con los flags aplicados (validados como el guion)."""
    data = script.model_dump(by_alias=True)
    if overrides.voice is not None:
        engine, sep, voice = overrides.voice.partition(":")
        if sep:
            engine = _plain(engine)
            if engine != data["voz"]["motor"]:
                # Otro motor: lo propio del anterior (modelo, ajustes) no vale.
                data["voz"] = {"motor": engine}
            if engine == "archivo":
                data["voz"]["archivo"] = str(Path(voice).expanduser().resolve())
            else:
                data["voz"]["voz"] = voice.strip()
        else:
            data["voz"]["voz"] = overrides.voice.strip()
    if overrides.format is not None:
        data["video"]["formato"] = overrides.format
    if overrides.fps is not None:
        data["video"]["fps"] = overrides.fps
    if overrides.quality is not None:
        data["video"]["calidad"] = overrides.quality
    if overrides.reel is not None:
        data["video"]["reel"] = str(Path(overrides.reel).expanduser().resolve())
        # Un reel monta a Sonnia sobre su propio fondo.
        data["escena"]["fondo"] = "transparente"
    if overrides.light is not None:
        data["escena"]["luz"] = overrides.light
    if overrides.background is not None:
        _background(data["escena"], overrides.background)
    if overrides.framing is not None:
        data["escena"]["encuadre"] = overrides.framing
    if overrides.emotion is not None:
        data["escena"]["emocion"] = overrides.emotion
    if overrides.no_gestures:
        data["gestos"]["modo"] = "ninguno"
    if overrides.title is not None:
        data["titulo"] = overrides.title
    return parse_script(data, source="las opciones")


def _background(scene: dict[str, Any], value: str) -> None:
    """``--fondo``: un modo (stand, color...), un color (#000000) o una imagen."""
    value = value.strip()
    if _plain(value) in BACKGROUNDS:
        scene["fondo"] = _plain(value)
    elif _COLOR_RE.match(value):
        scene["fondo"] = "color"
        scene["color"] = value
    else:
        scene["fondo"] = "imagen"
        scene["imagen"] = str(Path(value).expanduser().resolve())


# ---------------------------------------------------------------------------
# Traducción al contrato con Unity
# ---------------------------------------------------------------------------


def video_size(video: VideoOptions) -> tuple[int, int]:
    """Ancho y alto en píxeles."""
    if video.format in FORMATS:
        return FORMATS[video.format]
    width, _, height = video.format.partition("x")
    return int(width), int(height)


def quality(video: VideoOptions) -> Quality:
    return QUALITIES[video.quality]


def scene_message(scene: SceneOptions) -> dict[str, Any]:
    """``scene`` del trabajo, con los nombres del contrato."""
    return {
        "background": {
            "mode": BACKGROUNDS[scene.background],
            "color": scene.color,
            "color2": scene.color2,
            "image": scene.image if scene.background == "imagen" else "",
        },
        "particles": scene.particles,
        "lighting": {
            "preset": LIGHTS[scene.light],
            "key": scene.light_intensity,
            "ambient": scene.ambient,
            "rim_color": scene.rim,
            "rim_intensity": scene.rim_intensity if scene.rim else 0.0,
            "exposure": scene.exposure,
        },
        "framing": {
            "preset": FRAMINGS[scene.framing],
            "zoom": scene.zoom,
            "offset_x": scene.offset_x,
            "offset_y": scene.offset_y,
        },
        "outfit": OUTFITS[scene.outfit],
        "cap": scene.cap,
        "emotion": EMOTIONS[scene.emotion],
    }


# ---------------------------------------------------------------------------
# Texto de las frases: lo que se ve y lo que se dice
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Unit:
    """Un trozo de lo que se ve (una palabra o una entrada de ``[pronunciacion]``) y las
    palabras que se dicen por él (ninguna si es solo puntuación, como «—»)."""

    display: str
    spoken: tuple[str, ...]
    #: Lo que va al TTS por este trozo (con su puntuación).
    spoken_text: str


@dataclass(frozen=True, slots=True)
class PhraseText:
    """Una frase lista: lo que se ve, lo que se dice y sus trozos."""

    display: str
    spoken: str
    units: tuple[Unit, ...]

    @property
    def spoken_words(self) -> list[str]:
        return [word for unit in self.units for word in unit.spoken]


_HAS_ALNUM = re.compile(r"\w")
_END_PUNCT = re.compile(r"[.!?…;:][\"'»”)\]]*$")


def _pronunciation_re(table: dict[str, str]) -> tuple[re.Pattern[str] | None, dict[str, str]]:
    lookup: dict[str, str] = {}
    for key, value in table.items():
        key = " ".join(written(key).split())
        if key:
            lookup[key.lower()] = " ".join(value.split())
    if not lookup:
        return None, lookup
    keys = sorted(lookup, key=len, reverse=True)
    pattern = r"(?<!\w)(" + "|".join(re.escape(k) for k in keys) + r")(?!\w)"
    return re.compile(pattern, re.IGNORECASE), lookup


def _phrase(text: str, pattern: re.Pattern[str] | None, lookup: dict[str, str]) -> PhraseText:
    display = " ".join(written(text).split())
    matches = list(pattern.finditer(display)) if pattern is not None else []
    inside = [False] * len(display)
    for match in matches:
        for i in range(match.start(), match.end()):
            inside[i] = True
    # Trozos: se corta en los espacios que no caen dentro de una entrada de la tabla.
    spans: list[tuple[int, int]] = []
    start: int | None = None
    for i, char in enumerate(display):
        if char.isspace() and not inside[i]:
            if start is not None:
                spans.append((start, i))
                start = None
        elif start is None:
            start = i
    if start is not None:
        spans.append((start, len(display)))
    units: list[Unit] = []
    for a, b in spans:
        pieces: list[str] = []
        cursor = a
        for match in matches:
            if match.start() >= a and match.end() <= b:
                pieces.append(display[cursor : match.start()])
                pieces.append(lookup[match.group(0).lower()])
                cursor = match.end()
        pieces.append(display[cursor:b])
        said = spoken("".join(pieces))
        words = tuple(w for w in said.split() if _HAS_ALNUM.search(w))
        units.append(Unit(display=display[a:b], spoken=words, spoken_text=said))
    said_text = " ".join(u.spoken_text for u in units if u.spoken_text)
    if said_text and not _END_PUNCT.search(said_text):
        # Sin punto final, el TTS encadena la frase con la siguiente y no hay dónde cortar.
        said_text += "."
    return PhraseText(display=display, spoken=said_text, units=tuple(units))


def phrase_texts(script: Script) -> list[PhraseText]:
    """Las frases del guion con lo que se ve («Sonnia») y lo que se dice («Sonia»)."""
    pattern, lookup = _pronunciation_re(script.pronunciation)
    return [_phrase(phrase.text, pattern, lookup) for phrase in script.phrases]


def tts_text(phrases: list[PhraseText]) -> str:
    """El texto de la toma entera: todas las frases seguidas."""
    return " ".join(p.spoken for p in phrases if p.spoken)


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

#: Fin de frase en ``sonnia-video decir``: . ! ? o … seguidos de espacio.
_SENTENCE_END = re.compile(r"(?<=[.!?…])[\"'»”)\]]*\s+")


def split_sentences(text: str) -> list[str]:
    """Las frases de un texto suelto, cortado tras . ! ? o … (``sonnia-video.com`` no corta)."""
    parts: list[str] = []
    cursor = 0
    for match in _SENTENCE_END.finditer(text):
        parts.append(text[cursor : match.start() + len(match.group(0).rstrip())])
        cursor = match.end()
    parts.append(text[cursor:])
    return [" ".join(p.split()) for p in parts if p.strip()]


def script_from_text(text: str) -> Script:
    """Un guion con las opciones por defecto y una frase por cada oración de ``text``."""
    sentences = split_sentences(text)
    if not sentences:
        raise VideoError("No hay nada que decir: el texto está vacío.")
    return parse_script({"frase": [{"texto": s} for s in sentences]}, source="el texto")


def slug(text: str, limit: int = 60) -> str:
    """Un nombre de archivo seguro: minúsculas, sin tildes, con guiones."""
    plain = unicodedata.normalize("NFKD", text)
    plain = "".join(c for c in plain if not unicodedata.combining(c)).lower()
    plain = re.sub(r"[^a-z0-9]+", "-", plain).strip("-")
    return plain[:limit].strip("-")


def title_of(script: Script) -> str:
    """El título del vídeo (su nombre de archivo): ``titulo`` o las primeras palabras."""
    if script.title.strip():
        return slug(script.title) or "sonnia"
    words = written(" ".join(p.text for p in script.phrases)).split()[:6]
    return slug(" ".join(words)) or "sonnia"


EXAMPLE = """\
# Guion de Sonnia Video (sonnia-video render guion.toml).
# Todo es opcional salvo las frases. Lo que se escribe «Sonnia» se dice «Sonia».

titulo = "gracias-devfest"        # nombre de los archivos: gracias-devfest.mp4 (o .mov) y .srt
# Subtítulos: solo el .srt aparte; el vídeo sale sin logo, QR ni subtítulos en pantalla.

[voz]
motor = "gemini"                  # gemini | elevenlabs | archivo
voz = "es-es-techagent-5"         # lista: sonnia-video voces gemini
modelo = "gemini-3.8-flash-tts"
# estilo: cómo habla (Gemini). Vacío: acento latinoamericano, cercana y alegre.
# «ninguno»: sin indicación de estilo.
estilo = ""
# idioma = "es-419"               # idioma de la transcripción que da los tiempos de cada palabra

# Con ElevenLabs (clave ELEVENLABS_API_KEY; voces: sonnia-video voces elevenlabs):
# motor = "elevenlabs"
# voz = "Nombre de la voz o su voice_id"
# modelo = "eleven_v4"            # o eleven_multilingual_v2
# estabilidad = 0.5               # 0 a 1: más baja, más expresiva
# similitud = 0.75                # 0 a 1: parecido a la voz original
# estilo = 0.0                    # 0 a 1: exageración del estilo
# velocidad = 1.0                 # 0,7 a 1,2
# idioma = "es"                   # language_code (no lo aceptan los modelos multilingual_v2)

# Con un audio grabado (WAV o MP3; los textos de las frases tienen que ser lo que se oye):
# motor = "archivo"
# archivo = "voz.wav"             # relativo a este guion

[pronunciacion]                   # lo que se ve → lo que se dice
"sonnetcode.com" = "sónet code punto com"
"DevFest" = "dev fest"

[video]
formato = "vertical"              # vertical (1080x1920) | cuadrado (1080x1080) | horizontal (1920x1080) | 4k-vertical (2160x3840) | ANCHOxALTO
fps = 30
calidad = "alta"                  # borrador (rápido) | normal | alta (desenfoque de movimiento, tarda ~4 veces más)
antes = 0.6                       # segundos de reposo antes de hablar
despues = 1.5                     # segundos de reposo al acabar
# reel = "~/Documents/git/sonnet-code/media/reels/mi-reel"   # con fondo transparente: el paquete va a <reel>/assets/sonnia/

[escena]
fondo = "stand"                   # stand | color | degradado | imagen | transparente (.mov ProRes 4444 con alfa y cuadros PNG)
color = "#142752"                 # color del fondo (y el de arriba en el degradado)
color2 = "#0B1322"                # color de abajo en el degradado
imagen = ""                       # con fondo = "imagen": PNG o JPG que cubre el cuadro
particulas = true                 # motas del escenario
luz = "stand"                     # stand | estudio | suave | calida | fria | dramatica
luz_intensidad = 1.0              # multiplica la luz principal
luz_ambiente = 1.0                # multiplica la luz ambiente
contraluz = ""                    # color de un contraluz extra ("#7FB2FF"); vacío: sin contraluz
contraluz_intensidad = 1.5
exposicion = 0.0                  # en pasos (EV): +1 el doble de luz, -1 la mitad
encuadre = "stand"                # stand | primer-plano | medio | americano | cuerpo
zoom = 1.0                        # > 1 acerca
desplazar_x = 0.0                 # fracción del cuadro: positivo, Sonnia a la derecha
desplazar_y = 0.0                 # positivo, Sonnia más abajo
camiseta = "staff"                # staff (la del DevFest) | lisa
gorra = false
emocion = "alegre"                # alegre | neutra

[gestos]
modo = "auto"                     # auto (los elige el modelo; los de cada frase mandan) | manual | ninguno

[[frase]]
texto = "¡Hola! Soy Sonnia, la asistente virtual del DevFest Santo Domingo."
gesto = "waveCalm"                # opcional: un gesto del catálogo (sonnia-video gestos)

[[frase]]
texto = "Gracias a todos los que pasaron por el stand de Sonnet Code."
pausa = 0.3                       # opcional: silencio extra después de la frase

[[frase]]
texto = "Nos vemos en sonnetcode.com."

# Gestos sueltos a una hora del vídeo, fuera de las frases, para coreografiar (opcional):
# [[accion]]
# gesto = "knockKnock"
# en = 0.0                        # segundo del vídeo
# espejo = true                   # con la otra mano
"""
