"""WebSocket layer: protocol with Unity and the server (hub)."""

from __future__ import annotations

from sonia.ws.hub import Hub
from sonia.ws.protocol import (
    FLAG_LAST,
    HEADER_SIZE,
    MAGIC,
    PROTOCOL_VERSION,
    decode_audio_frame,
    dumps,
    encode_audio_frame,
    msg_error,
    msg_hello,
    msg_hide_image,
    msg_request_frame,
    msg_show_image,
    msg_speech_end,
    msg_speech_start,
    msg_state,
    msg_stop_speaking,
    msg_transcript,
    parse_client_message,
)

__all__ = [
    "FLAG_LAST",
    "HEADER_SIZE",
    "MAGIC",
    "PROTOCOL_VERSION",
    "Hub",
    "decode_audio_frame",
    "dumps",
    "encode_audio_frame",
    "msg_error",
    "msg_hello",
    "msg_hide_image",
    "msg_request_frame",
    "msg_show_image",
    "msg_speech_end",
    "msg_speech_start",
    "msg_state",
    "msg_stop_speaking",
    "msg_transcript",
    "parse_client_message",
]
