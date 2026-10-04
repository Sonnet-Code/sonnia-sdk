"""Protocolo WebSocket entre el orquestador y Unity (versión 1).

Este módulo es la única fuente de verdad de los nombres y las formas de los
mensajes descritos en ``docs/protocolo.md``. Nadie debe construir a mano un
diccionario del protocolo: siempre se pasa por las funciones ``msg_*``.

Hay dos tipos de frame:

- Texto: JSON con un campo ``type`` obligatorio.
- Binario: audio PCM s16le mono con una cabecera fija de 12 bytes.
"""

from __future__ import annotations

import json
import struct
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

#: Versión del protocolo que se anuncia en ``hello``.
PROTOCOL_VERSION = 1

#: Marca de los frames binarios de audio.
MAGIC = b"SNIA"

#: Cabecera binaria: magic (4 bytes) + utterance_id (uint32) + flags (uint32).
HEADER_FORMAT = "<4sII"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)  # 12

#: Bit 0 de ``flags``: último chunk de la frase.
FLAG_LAST = 1

#: Formato del audio que se anuncia en ``hello``.
AUDIO_FORMAT = "pcm_s16le"
AUDIO_CHANNELS = 1

# Mensajes del orquestador hacia Unity.
MSG_HELLO = "hello"
MSG_STATE = "state"
MSG_TRANSCRIPT = "transcript"
MSG_SPEECH_START = "speech_start"
MSG_ATTENTION = "attention"
MSG_SPEECH_END = "speech_end"
MSG_STOP_SPEAKING = "stop_speaking"
MSG_SHOW_IMAGE = "show_image"
MSG_HIDE_IMAGE = "hide_image"
MSG_ERROR = "error"
MSG_REQUEST_FRAME = "request_frame"
MSG_PRESENCE = "presence"
MSG_SET_VOLUME = "set_volume"
MSG_PLAY_ANIMATION = "play_animation"
MSG_SET_SUBTITLES = "set_subtitles"
MSG_SET_DISABLED_ANIMATIONS = "set_disabled_animations"
MSG_SET_DEBUG = "set_debug"
MSG_SET_TUNING = "set_tuning"
MSG_SET_AVATAR = "set_avatar"
MSG_OPEN_AVATAR_EDITOR = "open_avatar_editor"
MSG_CLOSE_AVATAR_EDITOR = "close_avatar_editor"

# Mensajes de Unity hacia el orquestador.
MSG_CLIENT_HELLO = "client_hello"
MSG_INTERRUPT = "interrupt"
MSG_PLAYBACK_DONE = "playback_done"
MSG_TEXT_INPUT = "text_input"
MSG_CAMERA_FRAME = "camera_frame"
MSG_ANIMATIONS = "animations"
MSG_ANIMATION_PLAYING = "animation_playing"
MSG_AVATAR_EDITOR = "avatar_editor"
MSG_AVATAR_SAVED = "avatar_saved"

#: Tope de clips que se aceptan en ``animations`` (el set real tiene unos 40).
MAX_ANIMATIONS = 200

#: Tope de la definición del avatar de Genies (JSON en texto; la real ronda 4 KB).
MAX_AVATAR_DEFINITION = 64 * 1024


Role = Literal["user", "assistant"]
ImageSource = Literal["gallery", "camera"]


# ---------------------------------------------------------------------------
# Frames binarios de audio
# ---------------------------------------------------------------------------


def encode_audio_frame(utterance_id: int, pcm: bytes, is_last: bool) -> bytes:
    """Empaqueta un chunk de PCM s16le con la cabecera del protocolo."""
    flags = FLAG_LAST if is_last else 0
    return struct.pack(HEADER_FORMAT, MAGIC, utterance_id, flags) + pcm


def decode_audio_frame(data: bytes) -> tuple[int, bool, bytes]:
    """Deshace ``encode_audio_frame``.

    Devuelve ``(utterance_id, is_last, pcm)``. Lanza ``ValueError`` si el frame
    es demasiado corto o la marca no es la esperada.
    """
    if len(data) < HEADER_SIZE:
        raise ValueError(f"frame de audio demasiado corto: {len(data)} bytes")
    magic, utterance_id, flags = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
    if magic != MAGIC:
        raise ValueError(f"marca de frame inválida: {magic!r}")
    return utterance_id, bool(flags & FLAG_LAST), data[HEADER_SIZE:]


# ---------------------------------------------------------------------------
# Constructores de mensajes JSON (orquestador → Unity)
# ---------------------------------------------------------------------------


def msg_hello(sample_rate: int) -> dict[str, Any]:
    """Primer mensaje tras conectar: anuncia el formato del audio."""
    return {
        "type": MSG_HELLO,
        "version": PROTOCOL_VERSION,
        "sample_rate": int(sample_rate),
        "channels": AUDIO_CHANNELS,
        "format": AUDIO_FORMAT,
    }


def msg_state(state: str) -> dict[str, Any]:
    """Cambio de estado del asistente (``idle``, ``listening``, ...)."""
    return {"type": MSG_STATE, "state": str(state)}


def msg_transcript(role: Role | str, text: str, final: bool) -> dict[str, Any]:
    """Texto del usuario o de Sonia, para subtítulos y depuración."""
    return {"type": MSG_TRANSCRIPT, "role": str(role), "text": text, "final": bool(final)}


def msg_speech_start(utterance_id: int, text: str, *, ambient: bool = False) -> dict[str, Any]:
    """Empieza una frase sintetizada; a partir de aquí llegan frames binarios.

    ``ambient`` marca las frases de la animación de stand: el avatar mueve la
    boca pero no cambia de estado ni interrumpe el baile o el idle.
    """
    msg: dict[str, Any] = {
        "type": MSG_SPEECH_START,
        "utterance_id": int(utterance_id),
        "text": text,
    }
    if ambient:
        msg["ambient"] = True
    return msg


def msg_attention(category: str, clip: str | None = None) -> dict[str, Any]:
    """Pide al avatar un gesto de atención: ``dance``, ``fourth_wall`` o ``soft``."""
    msg: dict[str, Any] = {"type": MSG_ATTENTION, "category": category}
    if clip:
        msg["clip"] = clip
    return msg


def msg_play_animation(clip: str) -> dict[str, Any]:
    """Reproduce un clip concreto del set de animaciones (botones del panel)."""
    return {"type": MSG_PLAY_ANIMATION, "clip": str(clip)}


def msg_speech_end(utterance_id: int) -> dict[str, Any]:
    """No habrá más audio de esa frase."""
    return {"type": MSG_SPEECH_END, "utterance_id": int(utterance_id)}


def msg_stop_speaking(reason: str = "interrupted") -> dict[str, Any]:
    """Interrupción: Unity descarta el audio en cola y para la boca."""
    return {"type": MSG_STOP_SPEAKING, "reason": str(reason)}


def msg_show_image(
    image_id: str,
    source: ImageSource | str,
    mime: str,
    data: bytes,
    caption: str | None = None,
) -> dict[str, Any]:
    """Muestra una imagen en el panel de la escena. ``data`` va en base64."""
    import base64

    return {
        "type": MSG_SHOW_IMAGE,
        "image_id": str(image_id),
        "source": str(source),
        "mime": str(mime),
        "data_base64": base64.b64encode(data).decode("ascii"),
        "caption": caption,
    }


def msg_hide_image() -> dict[str, Any]:
    """Retira el panel de imágenes."""
    return {"type": MSG_HIDE_IMAGE}


def msg_error(message: str) -> dict[str, Any]:
    """Error legible para mostrar o registrar en el cliente."""
    return {"type": MSG_ERROR, "message": str(message)}


def msg_presence(present: bool, message: str = "") -> dict[str, Any]:
    """Sonia está en pantalla o se ha ido (y deja un letrero con ``message``)."""
    return {"type": MSG_PRESENCE, "present": bool(present), "message": str(message)}


def msg_set_volume(value: float) -> dict[str, Any]:
    """Volumen de la voz de Sonia en Unity (0 a 1,5; 1 es el normal)."""
    return {"type": MSG_SET_VOLUME, "value": round(max(0.0, min(1.5, float(value))), 3)}


def msg_set_subtitles(enabled: bool) -> dict[str, Any]:
    """Subtítulos en la pantalla de Unity sí o no (lo que dicen el visitante y Sonia)."""
    return {"type": MSG_SET_SUBTITLES, "enabled": bool(enabled)}


def msg_set_disabled_animations(clips: list[str]) -> dict[str, Any]:
    """Clips que Sonia no debe usar por su cuenta (sí se pueden lanzar con ``play_animation``)."""
    return {"type": MSG_SET_DISABLED_ANIMATIONS, "clips": sorted(set(clips))}


def msg_set_debug(enabled: bool) -> dict[str, Any]:
    """Modo debug: el avatar no lanza gestos, bailes ni variaciones por su cuenta."""
    return {"type": MSG_SET_DEBUG, "enabled": bool(enabled)}


def msg_set_tuning(tuning: dict[str, dict[str, float]]) -> dict[str, Any]:
    """Ajustes de «Developer»: boca (multiplicadores) y cámara (desplazamientos y zoom).

    ``mouth``: ``open``, ``jaw``, ``closure`` y ``speed`` multiplican lo que
    trae la escena (1 = tal cual). ``camera``: ``height``, ``distance`` y
    ``side`` en metros sobre el plano base, ``zoom`` (más de 1 acerca) y
    ``tilt`` en grados (positivo mira más abajo).
    """
    return {
        "type": MSG_SET_TUNING,
        "mouth": {k: float(v) for k, v in tuning.get("mouth", {}).items()},
        "camera": {k: float(v) for k, v in tuning.get("camera", {}).items()},
    }


def msg_set_avatar(definition: str | None) -> dict[str, Any]:
    """Aspecto de Sonia: definición del avatar de Genies (JSON en texto).

    ``None`` es el personaje que trae la app (``SoniaGeniesAvatar.json``).
    """
    return {"type": MSG_SET_AVATAR, "definition": definition}


def msg_open_avatar_editor() -> dict[str, Any]:
    """La pantalla de Sonia pasa a la escena de editar personaje."""
    return {"type": MSG_OPEN_AVATAR_EDITOR}


def msg_close_avatar_editor() -> dict[str, Any]:
    """Sale del editor de personaje sin guardar y vuelve a Sonia."""
    return {"type": MSG_CLOSE_AVATAR_EDITOR}


def msg_request_frame() -> dict[str, Any]:
    """Pide a Unity una captura de su cámara (solo con ``VISION_SOURCE=unity``)."""
    return {"type": MSG_REQUEST_FRAME}


# ---------------------------------------------------------------------------
# Serialización y parseo
# ---------------------------------------------------------------------------


def dumps(msg: dict[str, Any]) -> str:
    """Serializa un mensaje a JSON conservando los acentos."""
    return json.dumps(msg, ensure_ascii=False)


def parse_client_message(text: str | bytes) -> dict[str, Any] | None:
    """Parsea un mensaje entrante.

    Devuelve ``None`` si no es JSON válido, si no es un objeto o si no trae un
    campo ``type`` de tipo cadena: el protocolo dice que esos mensajes se
    ignoran en silencio.
    """
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    if not isinstance(parsed.get("type"), str):
        return None
    return parsed


def parse_animation_playing(msg: dict[str, Any]) -> str | None:
    """Clip del catálogo que suena ahora según ``animation_playing`` (``None``: ninguno)."""
    clip = msg.get("clip")
    if isinstance(clip, str) and 0 < len(clip.strip()) <= 80:
        return clip.strip()
    return None


def parse_avatar_definition(msg: dict[str, Any]) -> str | None:
    """Definición de ``avatar_saved``: un objeto JSON en texto, o ``None`` si no vale."""
    definition = msg.get("definition")
    if not isinstance(definition, str):
        return None
    definition = definition.strip()
    if not definition or len(definition) > MAX_AVATAR_DEFINITION:
        return None
    try:
        parsed = json.loads(definition)
    except ValueError:
        return None
    return definition if isinstance(parsed, dict) else None


def parse_animations(msg: dict[str, Any]) -> list[dict[str, str]]:
    """Catálogo de un mensaje ``animations``: ``[{"clip", "group"}, ...]``.

    Se queda con las entradas bien formadas, sin repetir clip y en el orden
    en que llegan; lo demás se ignora en silencio.
    """
    items = msg.get("animations")
    if not isinstance(items, list):
        return []
    catalog: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items[:MAX_ANIMATIONS]:
        if not isinstance(item, dict):
            continue
        clip, group = item.get("clip"), item.get("group")
        if not isinstance(clip, str) or not isinstance(group, str):
            continue
        clip, group = clip.strip(), group.strip()
        if 0 < len(clip) <= 80 and 0 < len(group) <= 40 and clip not in seen:
            seen.add(clip)
            catalog.append({"clip": clip, "group": group})
    return catalog
