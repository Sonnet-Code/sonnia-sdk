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

#: Marca de los frames binarios con la voz del invitado del Modo Jean (misma
#: cabecera que ``MAGIC``; los Unity antiguos los ignoran).
GUEST_MAGIC = b"SNGU"

#: Fases del Modo Jean que Unity puede contar en ``guest_state``.
GUEST_PHASES = ("entering", "live", "leaving", "off")

#: De quién es el personaje que se edita: Sonia (por defecto) o el invitado del Modo Jean.
AVATAR_TARGETS = ("sonia", "guest")

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
MSG_STAGE_MODE = "stage_mode"
MSG_SET_VOLUME = "set_volume"
MSG_PLAY_ANIMATION = "play_animation"
MSG_GESTURE = "gesture"
MSG_SET_SUBTITLES = "set_subtitles"
MSG_SET_DISABLED_ANIMATIONS = "set_disabled_animations"
MSG_SET_DEBUG = "set_debug"
MSG_SET_TUNING = "set_tuning"
MSG_SET_AVATAR = "set_avatar"
MSG_OPEN_AVATAR_EDITOR = "open_avatar_editor"
MSG_CLOSE_AVATAR_EDITOR = "close_avatar_editor"
MSG_GUEST_MODE = "guest_mode"
MSG_SET_GUEST_AVATAR = "set_guest_avatar"
MSG_GUEST_ANIMATION = "guest_animation"
MSG_TRIVIA_START = "trivia_start"
MSG_TRIVIA_QUESTION = "trivia_question"
MSG_TRIVIA_ANSWER = "trivia_answer"
MSG_TRIVIA_END = "trivia_end"

# Mensajes de Unity hacia el orquestador.
MSG_CLIENT_HELLO = "client_hello"
MSG_INTERRUPT = "interrupt"
MSG_PLAYBACK_DONE = "playback_done"
MSG_TEXT_INPUT = "text_input"
MSG_CAMERA_FRAME = "camera_frame"
MSG_ANIMATIONS = "animations"
MSG_GESTURE_CATALOG = "gesture_catalog"
MSG_ANIMATION_PLAYING = "animation_playing"
MSG_AVATAR_EDITOR = "avatar_editor"
MSG_AVATAR_SAVED = "avatar_saved"
MSG_GUEST_STATE = "guest_state"

#: Tope de clips que se aceptan en ``animations`` (el set real tiene unos 40).
MAX_ANIMATIONS = 200

#: Tope de gestos que se aceptan en ``gesture_catalog`` (Sage tiene 162).
MAX_GESTURES = 400

#: Valores de las fichas de ``gesture_catalog`` (los de ``llmMetadata`` de Genies).
GESTURE_FREQUENCIES = ("Standard", "Uncommon", "Rare")
GESTURE_TIMINGS = ("Instant", "Short", "Long")
GESTURE_IMPACTS = ("NoImpact", "LowImpact", "HighImpact")

#: Tope de la definición del avatar de Genies (JSON en texto; la real ronda 4 KB).
MAX_AVATAR_DEFINITION = 64 * 1024


Role = Literal["user", "assistant"]
ImageSource = Literal["gallery", "camera", "agenda"]


# ---------------------------------------------------------------------------
# Frames binarios de audio
# ---------------------------------------------------------------------------


def encode_audio_frame(utterance_id: int, pcm: bytes, is_last: bool) -> bytes:
    """Empaqueta un chunk de PCM s16le con la cabecera del protocolo."""
    flags = FLAG_LAST if is_last else 0
    return struct.pack(HEADER_FORMAT, MAGIC, utterance_id, flags) + pcm


def encode_guest_audio_frame(utterance_id: int, pcm: bytes, is_last: bool) -> bytes:
    """Como ``encode_audio_frame`` pero con la voz del invitado (marca ``SNGU``)."""
    flags = FLAG_LAST if is_last else 0
    return struct.pack(HEADER_FORMAT, GUEST_MAGIC, utterance_id & 0xFFFFFFFF, flags) + pcm


def decode_audio_frame(data: bytes, *, magic: bytes = MAGIC) -> tuple[int, bool, bytes]:
    """Deshace ``encode_audio_frame`` (o, con ``magic=GUEST_MAGIC``, ``encode_guest_audio_frame``).

    Devuelve ``(utterance_id, is_last, pcm)``. Lanza ``ValueError`` si el frame
    es demasiado corto o la marca no es la esperada.
    """
    if len(data) < HEADER_SIZE:
        raise ValueError(f"frame de audio demasiado corto: {len(data)} bytes")
    found, utterance_id, flags = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
    if found != magic:
        raise ValueError(f"marca de frame inválida: {found!r}")
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


def msg_play_animation(clip: str, *, whole: bool = False) -> dict[str, Any]:
    """Reproduce un clip concreto del set de animaciones.

    Desde el panel, el clip se corta si Sonia pasa a pensar o a hablar. Con
    ``whole`` (movimientos pedidos de viva voz, ``play_animation``) suena entero
    aunque Sonia hable mientras tanto.
    """
    msg: dict[str, Any] = {"type": MSG_PLAY_ANIMATION, "clip": str(clip)}
    if whole:
        msg["whole"] = True
    return msg


def msg_gesture(name: str, utterance_id: int | None) -> dict[str, Any]:
    """Un gesto de hablar del catálogo de ``gesture_catalog`` para la frase ``utterance_id``.

    Lo elige el director de gestos (``sonia/gestures``). Unity lo reproduce
    enseguida si esa frase sigue sonando y lo descarta si ya terminó. ``None``
    es «para la próxima frase»: Unity lo guarda unos segundos y lo lanza con el
    siguiente ``speech_start`` no ambiental (el gesto de apertura).
    """
    return {
        "type": MSG_GESTURE,
        "name": str(name),
        "utterance_id": None if utterance_id is None else int(utterance_id),
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


def msg_presence(present: bool, message: str = "") -> dict[str, Any]:
    """Sonia está en pantalla o se ha ido (y deja un letrero con ``message``)."""
    return {"type": MSG_PRESENCE, "present": bool(present), "message": str(message)}


def msg_stage_mode(mode: str, talk: bool) -> dict[str, Any]:
    """Modo del stand para la pantalla: ``talk`` dice si Sonia puede conversar ahora.

    Unity solo enseña la invitación a hablar cuando ``talk`` es cierto: en «Solo
    saludos», «Fuera», el modo debug, el editor de personaje o el Modo Jean,
    GPT-Live está apagada y Sonia no contestaría.
    """
    return {"type": MSG_STAGE_MODE, "mode": str(mode), "talk": bool(talk)}


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
    """Ajustes de «Developer»: boca y movimiento (multiplicadores) y cámara (desplazamientos y zoom).

    ``mouth``: ``open``, ``jaw``, ``closure`` y ``speed`` multiplican lo que
    trae la escena (1 = tal cual). ``camera``: ``height``, ``distance`` y
    ``side`` en metros sobre el plano base, ``zoom`` (más de 1 acerca) y
    ``tilt`` en grados (positivo mira más abajo). ``idle``: ``breath``,
    ``accents`` y ``speed`` multiplican la respiración, los acentos del cuerpo
    al hablar y el ritmo del reposo (1 = tal cual).
    """
    return {
        "type": MSG_SET_TUNING,
        "mouth": {k: float(v) for k, v in tuning.get("mouth", {}).items()},
        "camera": {k: float(v) for k, v in tuning.get("camera", {}).items()},
        "idle": {k: float(v) for k, v in tuning.get("idle", {}).items()},
    }


def msg_set_avatar(definition: str | None) -> dict[str, Any]:
    """Aspecto de Sonia: definición del avatar de Genies (JSON en texto).

    ``None`` es el personaje que trae la app (``SoniaGeniesAvatar.json``).
    """
    return {"type": MSG_SET_AVATAR, "definition": definition}


def msg_open_avatar_editor(target: str = "sonia") -> dict[str, Any]:
    """La pantalla de Sonia pasa a la escena de editar personaje.

    ``target`` dice de quién: ``sonia`` (por defecto) o ``guest``, el invitado
    del Modo Jean. Unity contesta con el mismo ``target`` en ``avatar_editor`` y
    ``avatar_saved``.
    """
    return {"type": MSG_OPEN_AVATAR_EDITOR, "target": target}


def msg_set_guest_avatar(definition: str | None) -> dict[str, Any]:
    """Aspecto del invitado del Modo Jean; ``None`` es el avatar de prueba de la app."""
    return {"type": MSG_SET_GUEST_AVATAR, "definition": definition}


def parse_avatar_target(msg: dict[str, Any]) -> str:
    """``target`` de ``avatar_editor`` y ``avatar_saved``: sin él (Unity antigua), Sonia."""
    target = msg.get("target")
    return target if target in AVATAR_TARGETS else "sonia"


def msg_close_avatar_editor() -> dict[str, Any]:
    """Sale del editor de personaje sin guardar y vuelve a Sonia."""
    return {"type": MSG_CLOSE_AVATAR_EDITOR}


def msg_guest_mode(phase: str, name: str, sample_rate: int) -> dict[str, Any]:
    """Modo Jean: ``enter`` (Sonia presenta al invitado y le deja el sitio) o ``leave``.

    La voz del invitado llega en frames ``SNGU`` a ``sample_rate``.
    """
    return {"type": MSG_GUEST_MODE, "phase": phase, "name": name, "sample_rate": int(sample_rate)}


def msg_guest_animation(clip: str) -> dict[str, Any]:
    """Un clip de una sola vez en el avatar del invitado."""
    return {"type": MSG_GUEST_ANIMATION, "clip": str(clip)}


def msg_trivia_start(total: int, threshold: int, level: str = "") -> dict[str, Any]:
    """Empieza una trivia: gorro de fiesta, tema de la trivia, marcador a cero y su nivel."""
    return {
        "type": MSG_TRIVIA_START,
        "total": int(total),
        "threshold": int(threshold),
        "level": str(level),
    }


def msg_trivia_question(
    number: int, total: int, question: str, options: list[str], score: int
) -> dict[str, Any]:
    """Pregunta ``number`` (desde 1) de ``total`` con sus tres opciones (A, B y C)."""
    return {
        "type": MSG_TRIVIA_QUESTION,
        "number": int(number),
        "total": int(total),
        "question": str(question),
        "options": [str(o) for o in options],
        "score": int(score),
    }


def msg_trivia_answer(
    number: int, chosen: int, correct: int, is_correct: bool, score: int
) -> dict[str, Any]:
    """Resultado de la pregunta ``number``. ``chosen`` es -1 si el visitante no lo sabía."""
    return {
        "type": MSG_TRIVIA_ANSWER,
        "number": int(number),
        "chosen": int(chosen),
        "correct": int(correct),
        "is_correct": bool(is_correct),
        "score": int(score),
    }


def msg_trivia_end(
    score: int, total: int, *, won: bool, reason: str, prize: str = ""
) -> dict[str, Any]:
    """Fin de la trivia: ``reason`` es ``finished`` (con ``won`` y el premio) o ``cancelled``."""
    return {
        "type": MSG_TRIVIA_END,
        "score": int(score),
        "total": int(total),
        "won": bool(won),
        "reason": str(reason),
        "prize": str(prize),
    }


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
    """Definición de ``avatar_saved``, o ``None`` si no vale.

    Tiene que ser una definición de Genies (``JsonVersion`` y al menos una pieza
    en ``equippedAssetIds``): una vacía dejaría sin cuerpo ni ropa a todas las
    Sonias, porque se guarda en la nube y la cargan todas.
    """
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
    if not isinstance(parsed, dict) or not isinstance(parsed.get("JsonVersion"), str):
        return None
    pieces = parsed.get("equippedAssetIds")
    if not isinstance(pieces, list) or not any(isinstance(p, str) and p for p in pieces):
        return None
    return definition


def parse_guest_state(msg: dict[str, Any]) -> str | None:
    """Fase del Modo Jean que cuenta Unity en ``guest_state`` (``None`` si no vale)."""
    phase = msg.get("phase")
    return phase if phase in GUEST_PHASES else None


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


def parse_gesture_catalog(msg: dict[str, Any]) -> dict[str, Any]:
    """Catálogo de un mensaje ``gesture_catalog``, normalizado.

    Devuelve ``{"character", "transition_s", "gestures"}``. Cada gesto trae
    todos los campos de la ficha con su tipo (``critical_beat``,
    ``min_duration`` e ``intensity`` pueden ser ``None``; los textos, cadena
    vacía). Es tolerante: un campo que falta o no vale toma su valor por
    defecto, los números pueden llegar como texto, una frecuencia desconocida
    cuenta como ``Standard`` y los nombres repetidos o vacíos se ignoran.
    """
    character = msg.get("character")
    items = msg.get("gestures")
    gestures: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items[:MAX_GESTURES] if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str):
            continue
        name = name.strip()
        if not 0 < len(name) <= 80 or name in seen:
            continue
        seen.add(name)
        duration = _number(item.get("duration")) or 0.0
        core_stop = _number(item.get("core_stop"))
        intensity = _number(item.get("intensity"))
        gestures.append(
            {
                "name": name,
                "lists": _texts(item.get("lists")),
                "duration": max(0.0, duration),
                "core_start": max(0.0, _number(item.get("core_start")) or 0.0),
                # Sin núcleo, el gesto ocupa entero.
                "core_stop": max(0.0, core_stop if core_stop is not None else duration),
                "critical_beat": _number(item.get("critical_beat")),
                "held": item.get("held") is True,
                "min_duration": _number(item.get("min_duration")),
                "frequency": _choice(item.get("frequency"), GESTURE_FREQUENCIES) or "Standard",
                "timing": _choice(item.get("timing"), GESTURE_TIMINGS),
                "impact": _choice(item.get("impact"), GESTURE_IMPACTS),
                # De 1 a 4 en las fichas; 0 o nada es que no la tiene.
                "intensity": int(intensity) if intensity is not None and intensity >= 1 else None,
                "special": item.get("special") is True,
                "description": _text(item.get("description"), 400),
                "intents": _texts(item.get("intents")),
                "intent_description": _text(item.get("intent_description"), 600),
                "tags": _texts(item.get("tags")),
            }
        )
    return {
        "character": _text(character, 80),
        "transition_s": _number(msg.get("transition_s")),
        "gestures": gestures,
    }


def _number(value: Any) -> float | None:
    """Un número finito (también escrito como texto, como en las fichas de Genies) o ``None``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return None
    if isinstance(value, int | float) and value == value and abs(value) != float("inf"):
        return float(value)
    return None


def _text(value: Any, limit: int) -> str:
    """Texto recortado a ``limit`` caracteres (cadena vacía si no es texto)."""
    return value.strip()[:limit] if isinstance(value, str) else ""


def _texts(value: Any, limit: int = 30) -> list[str]:
    """Lista de textos cortos no vacíos (como mucho ``limit``)."""
    if not isinstance(value, list):
        return []
    texts = [v.strip()[:80] for v in value if isinstance(v, str) and v.strip()]
    return texts[:limit]


def _choice(value: Any, options: tuple[str, ...]) -> str:
    """El valor de ``options`` que coincide sin mirar mayúsculas, o cadena vacía."""
    if isinstance(value, str):
        wanted = value.strip().lower()
        for option in options:
            if option.lower() == wanted:
                return option
    return ""
