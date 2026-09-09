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
from collections.abc import Iterable, Sequence
from typing import Any, Literal

from sonia.types import VisemeFrame

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
MSG_VISEMES = "visemes"
MSG_ENVELOPE = "envelope"
MSG_SPEECH_END = "speech_end"
MSG_STOP_SPEAKING = "stop_speaking"
MSG_SHOW_IMAGE = "show_image"
MSG_HIDE_IMAGE = "hide_image"
MSG_ERROR = "error"
MSG_REQUEST_FRAME = "request_frame"

# Mensajes de Unity hacia el orquestador.
MSG_CLIENT_HELLO = "client_hello"
MSG_INTERRUPT = "interrupt"
MSG_PLAYBACK_DONE = "playback_done"
MSG_TEXT_INPUT = "text_input"
MSG_CAMERA_FRAME = "camera_frame"

#: Decimales con los que se serializan los tiempos y los pesos.
_TIME_DECIMALS = 3

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


def msg_visemes(utterance_id: int, frames: Iterable[VisemeFrame]) -> dict[str, Any]:
    """Visemas de la frase, con el instante relativo a ``speech_start``."""
    return {
        "type": MSG_VISEMES,
        "utterance_id": int(utterance_id),
        "frames": [
            {"t": round(float(f.t), _TIME_DECIMALS), "v": f.viseme, "w": float(f.weight)}
            for f in frames
        ],
    }


def msg_envelope(utterance_id: int, interval_ms: int, values: Sequence[float]) -> dict[str, Any]:
    """Envolvente de amplitud (0 a 1) de la frase, un valor cada ``interval_ms``."""
    return {
        "type": MSG_ENVELOPE,
        "utterance_id": int(utterance_id),
        "interval_ms": int(interval_ms),
        "values": [round(float(v), _TIME_DECIMALS) for v in values],
    }


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
