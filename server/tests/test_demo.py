"""Offline demo (``sonia demo``): the scripted show, its voice and its picture."""

from __future__ import annotations

import asyncio
import json
import random
import zlib
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from sonia.actions.gallery import image_info
from sonia.config import BUNDLE_ROOT, WSSettings
from sonia.demo import (
    TYPED_REPLY,
    DemoContent,
    DemoDirector,
    demo_picture,
    gallery_picture,
    synth_speech,
)
from sonia.live.engine import OUTPUT_VOICE_RMS
from sonia.types import AudioChunk
from sonia.ws import protocol as p
from sonia.ws.hub import Hub

RATE = 24_000


class FakeLink:
    """Records what the director sends, as one connected client would see it."""

    def __init__(self, clients: int = 1) -> None:
        self.client_count = clients
        self.sample_rate = RATE
        self.messages: list[dict[str, Any]] = []
        self.audio: list[tuple[int, AudioChunk]] = []
        self.sticky: dict[str, dict[str, Any]] = {}

    async def broadcast_json(self, msg: dict[str, Any]) -> None:
        json.dumps(msg)  # every message must be serializable
        self.messages.append(msg)

    async def send_audio(self, utterance_id: int, chunk: AudioChunk) -> None:
        self.audio.append((utterance_id, chunk))

    async def set_sticky(self, key: str, msg: dict[str, Any]) -> None:
        self.sticky[key] = msg
        await self.broadcast_json(msg)

    def clear_sticky(self, key: str) -> None:
        self.sticky.pop(key, None)

    def types(self) -> list[str]:
        return [m["type"] for m in self.messages]


def _content() -> DemoContent:
    return DemoContent.load(BUNDLE_ROOT / "assets", random.Random(1))


async def test_one_show_uses_every_part_of_the_client() -> None:
    link = FakeLink()
    await DemoDirector(link, _content(), time_scale=0, seed=1).run(loops=1)

    types = set(link.types())
    for expected in (
        p.MSG_STATE,
        p.MSG_TRANSCRIPT,
        p.MSG_SPEECH_START,
        p.MSG_SPEECH_END,
        p.MSG_ATTENTION,
        p.MSG_BUSY,
        p.MSG_ACTIVITY,
        p.MSG_SHOW_IMAGE,
        p.MSG_HIDE_IMAGE,
        p.MSG_TRIVIA_START,
        p.MSG_TRIVIA_QUESTION,
        p.MSG_TRIVIA_ANSWER,
        p.MSG_TRIVIA_END,
    ):
        assert expected in types, expected
    assert link.sticky["stage_mode"] == p.msg_stage_mode("conversation", True)
    # Nothing is left on screen for a client that reconnects after the show.
    assert "busy" not in link.sticky
    assert "trivia" not in link.sticky
    states = {m["state"] for m in link.messages if m["type"] == p.MSG_STATE}
    assert states == {"idle", "listening", "thinking", "speaking"}


async def test_every_utterance_has_audio_and_ends() -> None:
    link = FakeLink()
    await DemoDirector(link, _content(), time_scale=0, seed=2).run(loops=1)

    starts = [m["utterance_id"] for m in link.messages if m["type"] == p.MSG_SPEECH_START]
    ends = [m["utterance_id"] for m in link.messages if m["type"] == p.MSG_SPEECH_END]
    assert starts == ends == sorted(set(starts))
    assert any(m.get("ambient") for m in link.messages if m["type"] == p.MSG_SPEECH_START)
    for uid in starts:
        chunks = [chunk for u, chunk in link.audio if u == uid]
        assert sum(len(chunk.pcm) for chunk in chunks) > 0
        assert chunks[-1].is_last and not any(chunk.is_last for chunk in chunks[:-1])
        assert all(len(chunk.pcm) <= int(RATE * 0.1) * 2 for chunk in chunks)


async def test_trivia_round_is_consistent() -> None:
    link = FakeLink()
    content = _content()
    await DemoDirector(link, content, time_scale=0, seed=3).run(loops=1)

    start = next(m for m in link.messages if m["type"] == p.MSG_TRIVIA_START)
    questions = [m for m in link.messages if m["type"] == p.MSG_TRIVIA_QUESTION]
    answers = [m for m in link.messages if m["type"] == p.MSG_TRIVIA_ANSWER]
    end = next(m for m in link.messages if m["type"] == p.MSG_TRIVIA_END)
    total = len(content.questions)
    assert start["total"] == total == len(questions) == len(answers)
    assert [q["number"] for q in questions] == list(range(1, total + 1))
    assert all(len(q["options"]) == 3 for q in questions)
    for answer, question in zip(answers, content.questions, strict=True):
        assert answer["correct"] == question.correct
        assert answer["is_correct"] == (answer["chosen"] == answer["correct"])
    assert end["score"] == answers[-1]["score"] == total - 1
    assert end["won"] == (end["score"] >= start["threshold"])


async def test_typed_text_gets_the_canned_answer() -> None:
    link = FakeLink()
    director = DemoDirector(link, _content(), time_scale=0, seed=4)
    director.on_text_input({"type": "text_input", "text": "  hello there  "})
    director.on_text_input({"type": "text_input", "text": "   "})
    await director.run(loops=1)

    finals = [
        (m["role"], m["text"])
        for m in link.messages
        if m["type"] == p.MSG_TRANSCRIPT and m["final"]
    ]
    assert finals[0] == ("user", "hello there")
    assert finals[1] == ("assistant", TYPED_REPLY)


async def test_interrupt_cuts_the_current_utterance() -> None:
    link = FakeLink()
    director = DemoDirector(link, _content(), time_scale=0, seed=5)
    original = link.send_audio

    async def send_and_interrupt(uid: int, chunk: AudioChunk) -> None:
        await original(uid, chunk)
        if uid == 1 and len(link.audio) == 2:
            director.on_interrupt({"type": "interrupt"})

    link.send_audio = send_and_interrupt  # type: ignore[method-assign]
    await director.run(loops=1)

    first = [chunk for uid, chunk in link.audio if uid == 1]
    assert len(first) == 3 and first[-1].is_last  # two chunks, then the closing one
    assert p.MSG_STOP_SPEAKING in link.types()
    # The next utterance plays whole: the cut does not stick.
    second = [chunk for uid, chunk in link.audio if uid == 2]
    assert len(second) > 3


async def test_waits_for_a_client_before_starting() -> None:
    link = FakeLink(clients=0)
    task = asyncio.create_task(DemoDirector(link, _content(), time_scale=0).run(loops=1))
    await asyncio.sleep(0.3)
    assert link.types() == [p.MSG_STAGE_MODE]
    link.client_count = 1
    await asyncio.wait_for(task, 5)
    assert link.messages


# -- voice -----------------------------------------------------------------


def test_synthetic_voice_is_speech_like() -> None:
    text = "Hi! I can chat with you, show pictures and host a trivia game."
    pcm = synth_speech(text, RATE)
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float64) / 32768
    seconds = len(samples) / RATE
    assert 2.0 < seconds < 8.0
    assert np.max(np.abs(samples)) <= 0.31
    # Loud enough for the engine's own voice threshold, with pauses between words.
    block = int(RATE * 0.05)
    levels = [
        float(np.sqrt(np.mean(samples[i : i + block] ** 2)))
        for i in range(0, len(samples) - block, block)
    ]
    assert max(levels) > 10 * OUTPUT_VOICE_RMS
    assert min(levels) < OUTPUT_VOICE_RMS
    assert synth_speech(text, RATE) == pcm
    assert synth_speech(text, RATE, seed=1) != pcm


@pytest.mark.parametrize("rate", [16_000, 24_000])
def test_synthetic_voice_follows_the_sample_rate(rate: int) -> None:
    pcm = synth_speech("Hello there.", rate)
    assert len(pcm) % 2 == 0
    assert 0.4 < len(pcm) / 2 / rate < 2.0


def test_synthetic_voice_handles_empty_text() -> None:
    assert len(synth_speech("", RATE)) > 0


# -- picture ---------------------------------------------------------------


def test_demo_picture_is_a_valid_png() -> None:
    data = demo_picture(320, 200)
    assert image_info(data) == (".png", 320, 200)
    # The pixel data decompresses to one filter byte plus RGB per row.
    start = data.index(b"IDAT") + 4
    length = int.from_bytes(data[start - 8 : start - 4], "big")
    assert len(zlib.decompress(data[start : start + length])) == 200 * (1 + 320 * 3)


def test_gallery_picture_prefers_the_gallery(tmp_path: Path) -> None:
    rng = random.Random(0)
    assert gallery_picture(tmp_path, rng)[0] == "demo"
    (tmp_path / "logo.png").write_bytes(demo_picture(40, 30))
    image_id, data, mime = gallery_picture(tmp_path, rng)
    assert (image_id, mime) == ("logo", "image/png")
    assert image_info(data)[1:] == (40, 30)


def test_content_falls_back_without_assets(tmp_path: Path) -> None:
    content = DemoContent.load(tmp_path, random.Random(0))
    assert content.idle_lines
    assert len(content.questions) == 3
    assert content.picture[0] == "demo"


# -- end to end ------------------------------------------------------------


async def test_show_reaches_a_real_websocket_client(monkeypatch: pytest.MonkeyPatch) -> None:
    from websockets.asyncio.client import connect

    # Short utterances: the show is the same, only with less audio to push through.
    monkeypatch.setattr(
        "sonia.demo.synth_speech", lambda text, rate, seed=0: synth_speech("Hi.", rate)
    )

    hub = Hub(WSSettings(host="127.0.0.1", port=0), sample_rate=RATE)
    director = DemoDirector(hub, _content(), time_scale=0, seed=6)
    hub.on(p.MSG_TEXT_INPUT, director.on_text_input)
    received: list[dict[str, Any]] = []
    frames = 0
    async with hub, connect(f"ws://127.0.0.1:{hub.port}/", max_size=None) as client:
        show = asyncio.create_task(director.run(loops=1))
        await client.send(json.dumps({"type": "text_input", "text": "hi"}))
        async with asyncio.timeout(20):
            while True:
                raw = await client.recv()
                if isinstance(raw, bytes):
                    p.decode_audio_frame(raw)
                    frames += 1
                    continue
                received.append(json.loads(raw))
                if received[-1]["type"] == p.MSG_TRIVIA_END:
                    break
        await show
    assert received[0] == p.msg_hello(RATE)
    assert received[1] == p.msg_stage_mode("conversation", True)
    assert frames > 50
    assert any(m["type"] == p.MSG_SHOW_IMAGE for m in received)
