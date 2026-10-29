"""Tests for the WebSocket protocol and the hub.

Neither Unity nor an external network is needed: the hub starts on a free
localhost port and a test ``websockets`` client connects to it.
"""

from __future__ import annotations

import asyncio
import base64
import json
import struct
import time
from collections.abc import Callable
from typing import Any

import pytest

from sonia.config import WSSettings
from sonia.types import AudioChunk
from sonia.ws import protocol as p
from sonia.ws.hub import Hub

# ---------------------------------------------------------------------------
# Binary frames
# ---------------------------------------------------------------------------


def test_encode_decode_round_trip() -> None:
    pcm = b"\x01\x02\x03\x04" * 10
    frame = p.encode_audio_frame(7, pcm, is_last=False)

    assert frame[:4] == p.MAGIC
    assert len(frame) == p.HEADER_SIZE + len(pcm)

    utterance_id, is_last, payload = p.decode_audio_frame(frame)
    assert utterance_id == 7
    assert is_last is False
    assert payload == pcm


def test_encode_marks_last_chunk() -> None:
    frame = p.encode_audio_frame(3, b"\x00\x00", is_last=True)
    _, _, flags = struct.unpack(p.HEADER_FORMAT, frame[: p.HEADER_SIZE])
    assert flags & p.FLAG_LAST

    utterance_id, is_last, payload = p.decode_audio_frame(frame)
    assert (utterance_id, is_last, payload) == (3, True, b"\x00\x00")


def test_encode_accepts_empty_pcm() -> None:
    utterance_id, is_last, payload = p.decode_audio_frame(p.encode_audio_frame(1, b"", True))
    assert (utterance_id, is_last, payload) == (1, True, b"")


def test_decode_rejects_bad_magic() -> None:
    bad = b"NOPE" + struct.pack("<II", 1, 0) + b"\x00\x00"
    with pytest.raises(ValueError, match="magic"):
        p.decode_audio_frame(bad)


def test_decode_rejects_short_frame() -> None:
    with pytest.raises(ValueError, match="too short"):
        p.decode_audio_frame(b"SNIA\x00\x00")


def test_header_layout_matches_docs() -> None:
    # 12 bytes little endian: magic + uint32 + uint32.
    assert p.HEADER_SIZE == 12
    assert p.MAGIC == b"SNIA"
    assert p.FLAG_LAST == 1


# ---------------------------------------------------------------------------
# Exact shape of the JSON messages (docs/protocol.md)
# ---------------------------------------------------------------------------


def test_msg_hello() -> None:
    assert p.msg_hello(24_000) == {
        "type": "hello",
        "version": 1,
        "sample_rate": 24_000,
        "channels": 1,
        "format": "pcm_s16le",
    }


def test_msg_state() -> None:
    assert p.msg_state("idle") == {"type": "state", "state": "idle"}


def test_msg_transcript() -> None:
    assert p.msg_transcript("user", "hello there", True) == {
        "type": "transcript",
        "role": "user",
        "text": "hello there",
        "final": True,
    }


def test_msg_speech_start() -> None:
    assert p.msg_speech_start(7, "Hi, how are you?") == {
        "type": "speech_start",
        "utterance_id": 7,
        "text": "Hi, how are you?",
    }


def test_msg_speech_end_and_stop_speaking() -> None:
    assert p.msg_speech_end(7) == {"type": "speech_end", "utterance_id": 7}
    assert p.msg_stop_speaking("interrupted") == {
        "type": "stop_speaking",
        "reason": "interrupted",
    }


def test_msg_show_and_hide_image() -> None:
    data = b"\x89PNG\r\n"
    msg = p.msg_show_image("team-logo", "gallery", "image/png", data, "Our team")
    assert msg == {
        "type": "show_image",
        "image_id": "team-logo",
        "source": "gallery",
        "mime": "image/png",
        "data_base64": base64.b64encode(data).decode("ascii"),
        "caption": "Our team",
    }
    assert p.msg_hide_image() == {"type": "hide_image"}


def test_msg_error_and_request_frame() -> None:
    assert p.msg_error("the model went down") == {
        "type": "error",
        "message": "the model went down",
    }
    assert p.msg_request_frame() == {"type": "request_frame"}


def test_msg_set_avatar_and_definition_check() -> None:
    assert p.msg_set_avatar(None) == {"type": "set_avatar", "definition": None}
    good = json.dumps({"JsonVersion": "2-0-0", "equippedAssetIds": ["AvatarBase/rec1"]})
    assert p.parse_avatar_definition(good) == good
    assert p.parse_avatar_definition(json.dumps({"JsonVersion": "2-0-0"})) is None
    assert p.parse_avatar_definition("not json") is None
    assert p.parse_avatar_definition(3) is None


def test_parse_client_hello() -> None:
    hello = p.parse_client_hello(
        {"type": "client_hello", "client": "unity", "version": "1.0.0", "features": ["x", 3]}
    )
    assert hello == p.ClientHello(client="unity", version="1.0.0", features=frozenset({"x"}))
    assert p.parse_client_hello({"type": "client_hello"}).features == frozenset()


def test_msg_activity() -> None:
    assert p.msg_activity("search") == {"type": "activity", "activity": "search"}
    assert p.msg_activity("think")["activity"] == "think"
    assert p.msg_activity("none")["activity"] == "none"
    with pytest.raises(ValueError):
        p.msg_activity("dancing")


def test_dumps_keeps_accents() -> None:
    # Non-ASCII on purpose: ``dumps`` must keep these characters as is, not escape them.
    text = p.dumps(p.msg_speech_start(1, "naïve café"))
    assert "naïve café" in text
    assert json.loads(text)["utterance_id"] == 1


# ---------------------------------------------------------------------------
# Parsing incoming messages
# ---------------------------------------------------------------------------


def test_parse_client_message_ok() -> None:
    assert p.parse_client_message('{"type": "interrupt"}') == {"type": "interrupt"}
    assert p.parse_client_message(b'{"type": "playback_done", "utterance_id": 2}') == {
        "type": "playback_done",
        "utterance_id": 2,
    }


@pytest.mark.parametrize(
    "raw",
    ["not json", "[1, 2, 3]", '"just text"', "{}", '{"type": 3}', "null"],
)
def test_parse_client_message_rejects(raw: str) -> None:
    assert p.parse_client_message(raw) is None


# ---------------------------------------------------------------------------
# Hub: real integration with a websockets client
# ---------------------------------------------------------------------------


async def _wait_for(condition: Callable[[], object], limit: float = 2.0) -> None:
    """Short busy wait, so as not to depend on the loop's timing."""
    async with asyncio.timeout(limit):
        while not condition():  # noqa: ASYNC110 - deliberate polling in tests
            await asyncio.sleep(0.01)


async def test_hub_end_to_end() -> None:
    from websockets.asyncio.client import connect

    hub = Hub(WSSettings(host="127.0.0.1", port=0), sample_rate=24_000)
    interrupts: list[dict[str, Any]] = []
    texts: list[dict[str, Any]] = []
    hub.on("interrupt", lambda msg: interrupts.append(msg))
    hub.on("interrupt", lambda msg: interrupts.append({"second": True}))

    async def on_text(msg: dict[str, Any]) -> None:
        texts.append(msg)

    hub.on("text_input", on_text)

    async with hub:
        assert hub.port != 0
        assert hub.client_count == 0

        async with connect(f"ws://127.0.0.1:{hub.port}/") as client:
            # 1) hello on connect
            hello = json.loads(await asyncio.wait_for(client.recv(), 2.0))
            assert hello == p.msg_hello(24_000)
            assert hub.client_count == 1

            # 2) incoming message dispatched to both callbacks
            await client.send(json.dumps({"type": "interrupt"}))
            await _wait_for(lambda: len(interrupts) == 2)
            assert interrupts[0] == {"type": "interrupt"}

            # 3) a message without a registered callback breaks nothing
            await client.send(json.dumps({"type": "unknown"}))
            await client.send("this is not json")
            await client.send(json.dumps({"type": "text_input", "text": "how are you?"}))
            await _wait_for(lambda: texts)
            assert texts[0]["text"] == "how are you?"

            # 4) broadcast JSON
            await hub.broadcast_json(p.msg_state("thinking"))
            assert json.loads(await asyncio.wait_for(client.recv(), 2.0)) == {
                "type": "state",
                "state": "thinking",
            }

            # 5) binary broadcast and audio
            await hub.broadcast_bytes(p.encode_audio_frame(1, b"\x01\x02", False))
            raw = await asyncio.wait_for(client.recv(), 2.0)
            assert isinstance(raw, bytes)
            assert p.decode_audio_frame(raw) == (1, False, b"\x01\x02")

            await hub.send_audio(1, AudioChunk(pcm=b"\x03\x04", sample_rate=24_000, is_last=True))
            raw = await asyncio.wait_for(client.recv(), 2.0)
            assert isinstance(raw, bytes)
            assert p.decode_audio_frame(raw) == (1, True, b"\x03\x04")

            # 6) AvatarLink
            await hub.show_image(
                image_id="team-logo",
                source="gallery",
                mime="image/png",
                data=b"\x89PNG",
                caption=None,
            )
            shown = json.loads(await asyncio.wait_for(client.recv(), 2.0))
            assert shown["type"] == "show_image"
            assert base64.b64decode(shown["data_base64"]) == b"\x89PNG"
            assert shown["caption"] is None

            await hub.hide_image()
            assert json.loads(await asyncio.wait_for(client.recv(), 2.0)) == {"type": "hide_image"}

        # 7) after disconnecting, broadcasting does not raise even with nobody there
        await _wait_for(lambda: hub.client_count == 0)
        await hub.broadcast_json(p.msg_state("idle"))
        await hub.broadcast_bytes(p.encode_audio_frame(2, b"\x00", True))
        await hub.hide_image()

    assert hub.client_count == 0


async def test_hub_broadcast_without_clients_or_server() -> None:
    """The orchestrator may start before the hub and must not notice."""
    hub = Hub(WSSettings(host="127.0.0.1", port=0), sample_rate=24_000)
    await hub.broadcast_json(p.msg_state("idle"))
    await hub.broadcast_bytes(b"whatever")
    await hub.stop()  # stopping without having started is valid


async def test_hub_callback_that_raises_does_not_break_the_hub() -> None:
    from websockets.asyncio.client import connect

    calls: list[str] = []

    def explode(msg: dict[str, Any]) -> None:
        calls.append("explode")
        raise RuntimeError("broken callback")

    async def keep_going(msg: dict[str, Any]) -> None:
        calls.append("keep_going")

    hub = Hub(WSSettings(host="127.0.0.1", port=0), sample_rate=16_000)
    hub.on("interrupt", explode)
    hub.on("interrupt", keep_going)

    async with hub, connect(f"ws://127.0.0.1:{hub.port}/") as client:
        await asyncio.wait_for(client.recv(), 2.0)  # hello
        await client.send(json.dumps({"type": "interrupt"}))
        await _wait_for(lambda: "keep_going" in calls)

        # The connection is still alive: it gets a later broadcast.
        await hub.broadcast_json(p.msg_state("listening"))
        assert json.loads(await asyncio.wait_for(client.recv(), 2.0))["state"] == "listening"

    assert calls == ["explode", "keep_going"]


async def test_hub_accepts_a_large_camera_frame() -> None:
    """The websockets default limit (1 MiB) cuts off large webcams."""
    from websockets.asyncio.client import connect

    received: list[dict[str, Any]] = []
    hub = Hub(WSSettings(host="127.0.0.1", port=0), sample_rate=24_000)
    hub.on("camera_frame", lambda msg: received.append(msg))

    large = base64.b64encode(b"\xff\xd8" * 1_200_000).decode("ascii")  # ~3.2 MiB
    async with hub, connect(f"ws://127.0.0.1:{hub.port}/", max_size=None) as client:
        await asyncio.wait_for(client.recv(), 2.0)  # hello
        await client.send(json.dumps({"type": "camera_frame", "data_base64": large}))
        await _wait_for(lambda: received, 5.0)
        assert received[0]["data_base64"] == large
        # The connection is still alive: it was not closed with 1009.
        await hub.broadcast_json(p.msg_state("idle"))
        assert json.loads(await asyncio.wait_for(client.recv(), 2.0))["state"] == "idle"


async def test_hub_a_client_that_does_not_read_does_not_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A frozen Unity: sends to it must not hang the orchestrator loop."""
    from websockets.asyncio.client import connect

    import sonia.ws.hub as hub_module

    monkeypatch.setattr(hub_module, "SEND_TIMEOUT_S", 0.2)
    hub = Hub(WSSettings(host="127.0.0.1", port=0), sample_rate=24_000)

    async with hub:
        uri = f"ws://127.0.0.1:{hub.port}/"
        async with connect(uri, max_size=None, max_queue=1, close_timeout=0.2) as client:  # noqa: F841
            await _wait_for(lambda: hub.client_count == 1)
            # The client never calls recv(): its write buffer fills up.
            payload = p.encode_audio_frame(1, b"\x00" * 4_000_000, False)
            start = time.monotonic()
            async with asyncio.timeout(20.0):
                while hub.client_count == 1:
                    await hub.broadcast_bytes(payload)
            # The client was dropped instead of waiting forever.
            assert hub.client_count == 0
            # A later broadcast returns right away.
            before = time.monotonic()
            await hub.broadcast_json(p.msg_stop_speaking("interrupted"))
            assert time.monotonic() - before < 1.0
            assert time.monotonic() - start < 20.0


async def test_hub_several_clients_receive_the_same() -> None:
    from websockets.asyncio.client import connect

    hub = Hub(WSSettings(host="127.0.0.1", port=0), sample_rate=24_000)
    async with hub:
        uri = f"ws://127.0.0.1:{hub.port}/"
        async with connect(uri) as a, connect(uri) as b:
            await asyncio.wait_for(a.recv(), 2.0)
            await asyncio.wait_for(b.recv(), 2.0)
            await _wait_for(lambda: hub.client_count == 2)

            await hub.broadcast_json(p.msg_speech_end(9))
            for client in (a, b):
                assert json.loads(await asyncio.wait_for(client.recv(), 2.0)) == {
                    "type": "speech_end",
                    "utterance_id": 9,
                }
