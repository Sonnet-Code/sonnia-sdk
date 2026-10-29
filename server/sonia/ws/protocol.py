"""WebSocket protocol between the orchestrator and the avatar client (version 1).

This module is the single source of truth for the names and shapes of the
messages described in ``docs/protocol.md``. Nobody should build a protocol
dictionary by hand: always go through the ``msg_*`` functions.

There are two kinds of frames:

- Text: JSON with a mandatory ``type`` field.
- Binary: mono PCM s16le audio with a fixed 12-byte header.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Protocol version announced in ``hello``.
PROTOCOL_VERSION = 1

#: Magic of the binary audio frames.
MAGIC = b"SNIA"

#: Binary header: magic (4 bytes) + utterance_id (uint32) + flags (uint32).
HEADER_FORMAT = "<4sII"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)  # 12

#: Bit 0 of ``flags``: last chunk of the utterance.
FLAG_LAST = 1

#: Values of ``activity``: nothing, a task that takes a while or a web search.
ACTIVITIES = ("none", "think", "search")

#: Kinds of the waiting indicator (``busy``), from highest to lowest priority: a web
#: search and a task delegated to the backend (``sonia.busy``).
BUSY_KINDS = ("search", "think")

#: Audio format announced in ``hello``.
AUDIO_FORMAT = "pcm_s16le"
AUDIO_CHANNELS = 1

# Messages from the orchestrator to the client.
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
MSG_DEVICES = "devices"
MSG_PLAY_ANIMATION = "play_animation"
MSG_SET_SUBTITLES = "set_subtitles"
MSG_SET_DISABLED_ANIMATIONS = "set_disabled_animations"
MSG_SET_DEBUG = "set_debug"
MSG_SET_TUNING = "set_tuning"
MSG_SET_AVATAR = "set_avatar"
MSG_TRIVIA_START = "trivia_start"
MSG_TRIVIA_QUESTION = "trivia_question"
MSG_TRIVIA_ANSWER = "trivia_answer"
MSG_TRIVIA_END = "trivia_end"
MSG_ACTIVITY = "activity"
#: On-screen waiting indicator (``sonia.busy``): a pill with animated dots.
MSG_BUSY = "busy"

# Messages from the client to the orchestrator.
MSG_CLIENT_HELLO = "client_hello"
MSG_INTERRUPT = "interrupt"
MSG_PLAYBACK_DONE = "playback_done"
MSG_TEXT_INPUT = "text_input"
MSG_CAMERA_FRAME = "camera_frame"
MSG_ANIMATIONS = "animations"
#: The client's options menu: asks for the devices and picks a microphone or camera.
MSG_LIST_DEVICES = "list_devices"
MSG_SET_DEVICE = "set_device"
MSG_ANIMATION_PLAYING = "animation_playing"

#: Maximum number of clips accepted in ``animations``.
MAX_ANIMATIONS = 200

#: Maximum size of an avatar definition (a JSON string; a real one is about 4 KB).
MAX_AVATAR_DEFINITION = 64 * 1024

#: Maximum number of features accepted in ``client_hello``.
MAX_HELLO_ITEMS = 50

Role = Literal["user", "assistant"]
ImageSource = Literal["gallery"]


# ---------------------------------------------------------------------------
# Binary audio frames
# ---------------------------------------------------------------------------


def encode_audio_frame(utterance_id: int, pcm: bytes, is_last: bool) -> bytes:
    """Packs a PCM s16le chunk with the protocol header."""
    flags = FLAG_LAST if is_last else 0
    return struct.pack(HEADER_FORMAT, MAGIC, utterance_id, flags) + pcm


def decode_audio_frame(data: bytes) -> tuple[int, bool, bytes]:
    """Undoes ``encode_audio_frame``.

    Returns ``(utterance_id, is_last, pcm)``. Raises ``ValueError`` if the frame
    is too short or the magic is not the expected one.
    """
    if len(data) < HEADER_SIZE:
        raise ValueError(f"audio frame too short: {len(data)} bytes")
    found, utterance_id, flags = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
    if found != MAGIC:
        raise ValueError(f"invalid frame magic: {found!r}")
    return utterance_id, bool(flags & FLAG_LAST), data[HEADER_SIZE:]


# ---------------------------------------------------------------------------
# JSON message builders (orchestrator → client)
# ---------------------------------------------------------------------------


def msg_hello(sample_rate: int) -> dict[str, Any]:
    """First message after connecting: announces the audio format."""
    return {
        "type": MSG_HELLO,
        "version": PROTOCOL_VERSION,
        "sample_rate": int(sample_rate),
        "channels": AUDIO_CHANNELS,
        "format": AUDIO_FORMAT,
    }


def msg_state(state: str) -> dict[str, Any]:
    """Assistant state change (``idle``, ``listening``, ...)."""
    return {"type": MSG_STATE, "state": str(state)}


def msg_transcript(role: Role | str, text: str, final: bool) -> dict[str, Any]:
    """What the user or Sonnia says, for subtitles and debugging."""
    return {"type": MSG_TRANSCRIPT, "role": str(role), "text": text, "final": bool(final)}


def msg_speech_start(utterance_id: int, text: str, *, ambient: bool = False) -> dict[str, Any]:
    """An utterance starts; binary frames follow from here.

    ``ambient`` marks idle lines: the avatar moves its mouth but does not change
    state or interrupt the current dance or idle.
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
    """Asks the avatar for an attention gesture: ``dance``, ``fourth_wall``, ``soft`` or ``greeting``."""
    msg: dict[str, Any] = {"type": MSG_ATTENTION, "category": category}
    if clip:
        msg["clip"] = clip
    return msg


def msg_play_animation(clip: str, *, whole: bool = False) -> dict[str, Any]:
    """Plays a specific clip from the animation set.

    From the panel, the clip is cut if Sonnia starts thinking or speaking. With
    ``whole`` (moves requested by voice, ``play_animation``) it plays to the end
    even if Sonnia speaks meanwhile.
    """
    msg: dict[str, Any] = {"type": MSG_PLAY_ANIMATION, "clip": str(clip)}
    if whole:
        msg["whole"] = True
    return msg


def msg_speech_end(utterance_id: int) -> dict[str, Any]:
    """No more audio for that utterance."""
    return {"type": MSG_SPEECH_END, "utterance_id": int(utterance_id)}


def msg_stop_speaking(reason: str = "interrupted") -> dict[str, Any]:
    """Interruption: the client drops the queued audio and stops the mouth."""
    return {"type": MSG_STOP_SPEAKING, "reason": str(reason)}


def msg_show_image(
    image_id: str,
    source: ImageSource | str,
    mime: str,
    data: bytes,
    caption: str | None = None,
) -> dict[str, Any]:
    """Shows an image in the scene's image panel. ``data`` goes as base64."""
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
    """Hides the image panel."""
    return {"type": MSG_HIDE_IMAGE}


def msg_error(message: str) -> dict[str, Any]:
    """Human-readable error to show or log on the client."""
    return {"type": MSG_ERROR, "message": str(message)}


def msg_presence(present: bool, message: str = "") -> dict[str, Any]:
    """Sonnia is on screen or has left (leaving a sign with ``message``)."""
    return {"type": MSG_PRESENCE, "present": bool(present), "message": str(message)}


def msg_stage_mode(mode: str, talk: bool) -> dict[str, Any]:
    """Operating mode for the screen: ``talk`` says whether Sonnia can converse right now.

    The client only shows the "come and talk to me" invitation when ``talk`` is
    true: in "Greeter", "Away" or debug mode the realtime model is off and Sonnia
    would not answer.
    """
    return {"type": MSG_STAGE_MODE, "mode": str(mode), "talk": bool(talk)}


def msg_devices(
    *,
    microphones: list[dict[str, Any]],
    microphone: str,
    default_microphone: str,
    camera: int,
    camera_source: str,
) -> dict[str, Any]:
    """Microphones of this machine and the current choice, for the client's options menu.

    ``microphone`` is the configured one (empty: the system one, called
    ``default_microphone``). Cameras are listed by the client itself: ``camera``
    is the index the orchestrator uses and ``camera_source`` where snapshots come
    from (``opencv``, ``unity``...).
    """
    return {
        "type": MSG_DEVICES,
        "microphones": microphones,
        "microphone": str(microphone),
        "default_microphone": str(default_microphone),
        "camera": int(camera),
        "camera_source": str(camera_source),
    }


def msg_set_volume(value: float) -> dict[str, Any]:
    """Volume of Sonnia's voice on the client (0 to 1.5; 1 is normal)."""
    return {"type": MSG_SET_VOLUME, "value": round(max(0.0, min(1.5, float(value))), 3)}


def msg_set_subtitles(enabled: bool) -> dict[str, Any]:
    """Subtitles on the client's screen, yes or no (what the user and Sonnia say)."""
    return {"type": MSG_SET_SUBTITLES, "enabled": bool(enabled)}


def msg_set_disabled_animations(clips: list[str]) -> dict[str, Any]:
    """Clips Sonnia must not use on her own (``play_animation`` can still play them)."""
    return {"type": MSG_SET_DISABLED_ANIMATIONS, "clips": sorted(set(clips))}


def msg_set_debug(enabled: bool) -> dict[str, Any]:
    """Debug mode: the avatar plays no gestures, dances or idle variations on its own."""
    return {"type": MSG_SET_DEBUG, "enabled": bool(enabled)}


def msg_set_tuning(tuning: dict[str, dict[str, float]]) -> dict[str, Any]:
    """Developer tuning: mouth and idle motion (multipliers) and camera (offsets and zoom).

    ``mouth``: ``open``, ``jaw``, ``closure`` and ``speed`` multiply what the
    scene ships with (1 = as authored). ``camera``: ``height``, ``distance`` and
    ``side`` in meters over the base framing, ``zoom`` (above 1 gets closer) and
    ``tilt`` in degrees (positive looks further down). ``idle``: ``breath``,
    ``accents`` and ``speed`` multiply breathing, body accents while speaking and
    the pace of the idle motion (1 = as authored).
    """
    return {
        "type": MSG_SET_TUNING,
        "mouth": {k: float(v) for k, v in tuning.get("mouth", {}).items()},
        "camera": {k: float(v) for k, v in tuning.get("camera", {}).items()},
        "idle": {k: float(v) for k, v in tuning.get("idle", {}).items()},
    }


def msg_set_avatar(definition: str | None) -> dict[str, Any]:
    """Sonnia's look: a Genies avatar definition (a JSON string).

    ``None`` is the character the client ships with. Clients without the Genies
    Avatar SDK ignore it.
    """
    return {"type": MSG_SET_AVATAR, "definition": definition}


def msg_trivia_start(total: int, threshold: int, level: str = "") -> dict[str, Any]:
    """A trivia game starts: trivia theme, score at zero and its level."""
    return {
        "type": MSG_TRIVIA_START,
        "total": int(total),
        "threshold": int(threshold),
        "level": str(level),
    }


def msg_trivia_question(
    number: int, total: int, question: str, options: list[str], score: int
) -> dict[str, Any]:
    """Question ``number`` (from 1) of ``total`` with its three options (A, B and C)."""
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
    """Result of question ``number``. ``chosen`` is -1 if the player did not know."""
    return {
        "type": MSG_TRIVIA_ANSWER,
        "number": int(number),
        "chosen": int(chosen),
        "correct": int(correct),
        "is_correct": bool(is_correct),
        "score": int(score),
    }


def msg_trivia_end(score: int, total: int, *, won: bool, reason: str) -> dict[str, Any]:
    """End of the trivia: ``reason`` is ``finished`` (with ``won``) or ``cancelled``."""
    return {
        "type": MSG_TRIVIA_END,
        "score": int(score),
        "total": int(total),
        "won": bool(won),
        "reason": str(reason),
    }


def msg_activity(activity: str) -> dict[str, Any]:
    """What Sonnia does behind the scenes: ``search`` (web search), ``think`` (a slow task) or ``none``."""
    if activity not in ACTIVITIES:
        raise ValueError(f"unknown activity: {activity!r}")
    return {"type": MSG_ACTIVITY, "activity": activity}


def msg_busy(on: bool, kind: str = "", text: str = "") -> dict[str, Any]:
    """The on-screen waiting indicator: ``on`` with its kind (:data:`BUSY_KINDS`) and text, or off.

    It is the whole state (not a change): the client shows ``text`` while ``on``
    arrives and hides it with ``on: false``, keeping it at least a moment so it
    does not flicker.
    """
    if not on:
        return {"type": MSG_BUSY, "on": False}
    if kind not in BUSY_KINDS:
        raise ValueError(f"unknown waiting kind: {kind!r}")
    return {"type": MSG_BUSY, "on": True, "kind": kind, "text": str(text)}


def msg_request_frame() -> dict[str, Any]:
    """Asks the client for a snapshot from its camera (only with ``VISION_SOURCE=unity``)."""
    return {"type": MSG_REQUEST_FRAME}


# ---------------------------------------------------------------------------
# Serialization and parsing
# ---------------------------------------------------------------------------


def dumps(msg: dict[str, Any]) -> str:
    """Serializes a message to JSON keeping non-ASCII characters."""
    return json.dumps(msg, ensure_ascii=False)


def parse_client_message(text: str | bytes) -> dict[str, Any] | None:
    """Parses an incoming message.

    Returns ``None`` if it is not valid JSON, not an object or has no string
    ``type`` field: the protocol says those messages are silently ignored.
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


@dataclass(frozen=True, slots=True)
class ClientHello:
    """What a client announces in ``client_hello``: who it is and what it supports."""

    client: str
    version: str
    features: frozenset[str]


def parse_client_hello(msg: dict[str, Any]) -> ClientHello:
    """Normalized ``client_hello``. Tolerant: whatever is not valid is ignored."""
    raw_features = msg.get("features")
    features = (
        frozenset(
            f.strip()
            for f in raw_features[:MAX_HELLO_ITEMS]
            if isinstance(f, str) and 0 < len(f.strip()) <= 40
        )
        if isinstance(raw_features, list)
        else frozenset()
    )
    return ClientHello(
        client=_text(msg.get("client"), 40),
        version=_text(msg.get("version"), 40),
        features=features,
    )


def parse_animation_playing(msg: dict[str, Any]) -> str | None:
    """Catalog clip playing now according to ``animation_playing`` (``None``: none)."""
    clip = msg.get("clip")
    if isinstance(clip, str) and 0 < len(clip.strip()) <= 80:
        return clip.strip()
    return None


def parse_avatar_definition(value: Any) -> str | None:
    """A valid avatar definition for ``set_avatar``, or ``None``.

    It must be a Genies definition (a ``JsonVersion`` and at least one piece in
    ``equippedAssetIds``): an empty one would leave the character without a body
    or clothes.
    """
    if not isinstance(value, str):
        return None
    definition = value.strip()
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


def parse_animations(msg: dict[str, Any]) -> list[dict[str, str]]:
    """Catalog of an ``animations`` message: ``[{"clip", "group"}, ...]``.

    Keeps the well-formed entries, without repeating a clip and in arrival
    order; everything else is silently ignored.
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


def _text(value: Any, limit: int) -> str:
    """Text cut to ``limit`` characters (empty string if it is not text)."""
    return value.strip()[:limit] if isinstance(value, str) else ""
