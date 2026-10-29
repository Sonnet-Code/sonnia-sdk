"""Tests of the GPT-Live engine, with no network, no key and no hardware.

GPT-Live is a local WebSocket server that mimics the Live API (``session.start``
→ ``session.started``, voice, transcript and delegation events) and records
everything the engine sends it. The avatar client is a ``websockets`` client
connected to a real ``Hub``, as in the orchestrator tests.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import re
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pytest

import sonia.live.engine as engine_module
import sonia.live.oneshot as oneshot_module
from sonia.actions import Gallery, build_default_registry
from sonia.clock import Clock
from sonia.config import (
    AudioSettings,
    LiveSettings,
    LLMSettings,
    Settings,
    ShowcaseSettings,
    VisionSettings,
    WSSettings,
)
from sonia.live.audio import ComfortNoise, NoiseGate, pcm16_from_float, rms
from sonia.live.client import LiveClient, LiveError
from sonia.live.engine import DELEGATION_FAILED_TEXT, INTERRUPT_TEXT, LiveEngine
from sonia.live.oneshot import probe_session, speak_text
from sonia.live.prompts import build_session_config, describe_live_stack, gallery_note
from sonia.live.vision import VisionNarrator
from sonia.showcase import ATTENTION_DANCE, Showcase
from sonia.types import Frame, LLMEvent, Message, TextDelta, TurnDone
from sonia.vision.policy import VisionPolicy
from sonia.ws.hub import Hub
from tests.helpers import FakeCamera, Recorder

RATE = 24_000

# ---------------------------------------------------------------------------
# Fake GPT-Live server
# ---------------------------------------------------------------------------


def tool_names(tools: list[dict[str, Any]]) -> list[str]:
    """Names of the backend tools (the built-in ones, like ``web_search``, by type)."""
    return [str(t.get("name") or t["type"]) for t in tools]


def pcm(samples: int, value: int = 1000) -> bytes:
    return np.full(samples, value, dtype="<i2").tobytes()


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


@dataclass
class FakeConn:
    """A session open against the fake server."""

    ws: Any
    start: dict[str, Any]
    authorization: str | None
    received: list[dict[str, Any]] = field(default_factory=list)
    changed: asyncio.Event = field(default_factory=asyncio.Event)

    async def send(self, event: dict[str, Any]) -> None:
        await self.ws.send(json.dumps(event))

    async def audio(self, data: bytes) -> None:
        await self.send({"type": "session.output_audio.delta", "delta": b64(data)})

    async def say(self, text: str) -> None:
        await self.send({"type": "session.output_transcript.delta", "delta": text})

    async def hear(self, text: str) -> None:
        await self.send(
            {"type": "session.input_transcript.delta", "delta": text, "start_ms": 0, "end_ms": 1}
        )

    async def response_event(
        self, nested: dict[str, Any], delegation_id: str | None = "deleg_1"
    ) -> None:
        await self.send(
            {
                "type": "response.event",
                "event_id": "ev",
                "delegation_id": delegation_id,
                "event": nested,
            }
        )

    def of_type(self, kind: str) -> list[dict[str, Any]]:
        return [m for m in self.received if m.get("type") == kind]

    def audio_in(self) -> list[bytes]:
        return [base64.b64decode(m["audio"]) for m in self.of_type("session.input_audio.append")]

    async def wait_for(
        self, predicate: Callable[[list[dict[str, Any]]], bool], limit: float = 3.0
    ) -> None:
        async with asyncio.timeout(limit):
            while not predicate(self.received):
                self.changed.clear()
                await self.changed.wait()

    async def wait_type(self, kind: str, count: int = 1, limit: float = 3.0) -> None:
        await self.wait_for(
            lambda msgs: len([m for m in msgs if m["type"] == kind]) >= count, limit
        )


class FakeLiveServer:
    """Mimics ``/v1/live/sessions``: start, commands and orderly close."""

    def __init__(
        self,
        *,
        reject: bool = False,
        drop_after_start: bool = False,
        close_after_start: str | None = None,
    ) -> None:
        self.reject = reject
        self.drop_after_start = drop_after_start
        #: If set, the server closes the session in an orderly way with this
        #: reason right after starting it (``expired``, ``content``...).
        self.close_after_start = close_after_start
        self.conns: list[FakeConn] = []
        self.attempts = 0
        self._new_conn = asyncio.Event()
        #: Called with every command received (for automatic reactions).
        self.on_message: Callable[[FakeConn, dict[str, Any]], Any] | None = None

    async def handler(self, ws: Any) -> None:
        self.attempts += 1
        start = json.loads(await ws.recv())
        authorization = ws.request.headers.get("Authorization")
        if self.reject:
            await ws.send(
                json.dumps(
                    {
                        "type": "error",
                        "event_id": "e",
                        "error": {
                            "type": "invalid_request_error",
                            "code": "model_not_found",
                            "message": "does not exist",
                            "client_event_id": start.get("event_id"),
                        },
                    }
                )
            )
            await ws.close()
            return
        session = dict(start["session"])
        session.update({"id": f"sess_{len(self.conns) + 1}", "expires_at": int(time.time()) + 3600})
        await ws.send(json.dumps({"type": "session.started", "event_id": "e0", "session": session}))
        conn = FakeConn(ws, start, authorization)
        self.conns.append(conn)
        self._new_conn.set()
        if self.drop_after_start:
            await ws.close(1011, "dropped")
            return
        if self.close_after_start is not None:
            await ws.send(
                json.dumps(
                    {
                        "type": "session.closed",
                        "event_id": "ec",
                        "reason": self.close_after_start,
                        "session": session,
                        "usage": {"seconds": 0},
                    }
                )
            )
            await ws.close()
            return
        with contextlib.suppress(Exception):
            async for raw in ws:
                message = json.loads(raw)
                conn.received.append(message)
                conn.changed.set()
                if self.on_message is not None:
                    result = self.on_message(conn, message)
                    if asyncio.iscoroutine(result):
                        await result
                if message["type"] == "session.close":
                    await ws.send(
                        json.dumps(
                            {
                                "type": "session.closed",
                                "event_id": "ec",
                                "reason": "close_requested",
                                "session": session,
                                "usage": {"seconds": 1},
                            }
                        )
                    )
                    await ws.close()
                    return

    async def wait_conn(self, count: int = 1, limit: float = 3.0) -> FakeConn:
        async with asyncio.timeout(limit):
            while len(self.conns) < count:
                self._new_conn.clear()
                await self._new_conn.wait()
        return self.conns[count - 1]


@contextlib.asynccontextmanager
async def running(server: FakeLiveServer) -> AsyncIterator[Callable[[str, dict[str, str]], Any]]:
    from websockets.asyncio.client import connect as client_connect
    from websockets.asyncio.server import serve

    async with serve(server.handler, "127.0.0.1", 0) as srv:
        port = srv.sockets[0].getsockname()[1]

        async def connect(url: str, headers: dict[str, str]) -> Any:
            return await client_connect(f"ws://127.0.0.1:{port}", additional_headers=headers)

        yield connect


# ---------------------------------------------------------------------------
# Engine setup
# ---------------------------------------------------------------------------


def make_settings(
    tmp_path: Path,
    *,
    vision_source: str = "none",
    on_turn_start: bool = True,
    idle_reset: float = 120.0,
    showcase_settings: ShowcaseSettings | None = None,
    image_auto_hide: float = 0.0,
    gallery_watch: float = 0.0,
    **live: Any,
) -> Settings:
    gallery = tmp_path / "gallery"
    gallery.mkdir(exist_ok=True)
    live_values: dict[str, Any] = {
        "api_key": "test-key",
        "segment_gap_ms": 150,
        "user_turn_gap_ms": 200,
        "reconnect_min_seconds": 0.05,
        "reconnect_max_seconds": 0.1,
        "connect_timeout": 2.0,
        "vision_min_interval_seconds": 0.0,
    }
    live_values.update(live)
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        live=LiveSettings(**live_values),
        llm=LLMSettings(
            base_url="http://llm.test/v1",
            model="vision-model",
            api_key="key",
            supports_vision=True,
            reasoning_effort="",
        ),
        audio=AudioSettings(),
        vision=VisionSettings(source=vision_source, on_turn_start=on_turn_start),  # type: ignore[arg-type]
        ws=WSSettings(host="127.0.0.1", port=0),
        showcase=showcase_settings or ShowcaseSettings(enabled=False),
        assets_dir=str(tmp_path),
        log_level="DEBUG",
        idle_reset_seconds=idle_reset,
        image_auto_hide_seconds=image_auto_hide,
        gallery_watch_seconds=gallery_watch,
    )


class FakeVisionLLM:
    """Fake vision model for the narrator."""

    def __init__(self, text: str = "A person in a blue shirt and glasses.") -> None:
        self.text = text
        self.requests: list[list[Message]] = []

    async def stream(
        self, messages: list[Message], tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[LLMEvent]:
        self.requests.append(messages)
        yield TextDelta(self.text)
        yield TurnDone(self.text)


@dataclass
class LiveRig:
    settings: Settings
    server: FakeLiveServer
    engine: LiveEngine
    hub: Hub
    client: Any
    rec: Recorder

    async def conn(self, count: int = 1) -> FakeConn:
        conn = await self.server.wait_conn(count)
        await wait_until(lambda: self.engine.session_id == f"sess_{count}")
        return conn

    async def unity(self, msg: dict[str, Any]) -> None:
        await self.client.send(json.dumps(msg))


@contextlib.asynccontextmanager
async def make_rig(
    tmp_path: Path,
    *,
    server: FakeLiveServer | None = None,
    camera: FakeCamera | None = None,
    narrator: VisionNarrator | None = None,
    showcase: Showcase | None = None,
    trivia: bool = False,
    clock: Clock | None = None,
    **settings_overrides: Any,
) -> AsyncIterator[LiveRig]:
    from websockets.asyncio.client import connect

    settings = make_settings(tmp_path, **settings_overrides)
    server = server or FakeLiveServer()
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir(exist_ok=True)
    (knowledge / "01-place.md").write_text("The museum opens at nine.", encoding="utf-8")
    policy = VisionPolicy(settings.vision, settings.llm.supports_vision)
    registry = build_default_registry(include_look=policy.enabled, include_trivia=trivia)
    hub = Hub(settings.ws, sample_rate=settings.live.sample_rate)
    async with running(server) as live_connect, hub:
        engine = LiveEngine(
            settings,
            hub=hub,
            registry=registry,
            camera=camera,
            vision_policy=policy,
            narrator=narrator,
            showcase=showcase,
            connect=live_connect,
            knowledge_dir=knowledge,
            clock=clock,
            tick_s=0.02,
        )
        async with connect(f"ws://127.0.0.1:{hub.port}/") as client:
            hello = json.loads(await asyncio.wait_for(client.recv(), 2.0))
            assert hello["type"] == "hello"
            assert hello["sample_rate"] == RATE
            rec = Recorder(client)
            task = asyncio.create_task(engine.run())
            await rec.wait_state("idle")
            try:
                yield LiveRig(settings, server, engine, hub, client, rec)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                await rec.close()


def voice_block(value: float = 0.5, samples: int = 768) -> np.ndarray[Any, Any]:
    return np.full(samples, value, dtype=np.float32)


def pcm_level(chunk: bytes) -> float:
    """RMS level (0..1) of a PCM s16le chunk like the ones GPT-Live receives."""
    return rms(np.frombuffer(chunk, dtype="<i2").astype(np.float32) / 32767.0)


async def wait_until(predicate: Callable[[], bool], limit: float = 3.0) -> None:
    async with asyncio.timeout(limit):
        while not predicate():  # noqa: ASYNC110 - polling a predicate
            await asyncio.sleep(0.01)


# ---------------------------------------------------------------------------
# Session start
# ---------------------------------------------------------------------------


async def test_session_start_carries_model_voice_format_and_actions(tmp_path: Path) -> None:
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        assert conn.authorization == "Bearer test-key"
        assert conn.start["type"] == "session.start"
        session = conn.start["session"]
        assert session["model"] == "gpt-live-1"
        assert session["audio"] == {
            "format": {"type": "audio/pcm", "rate": RATE},
            "output": {"voice": "marin"},
        }
        delegation = session["delegation"]
        assert delegation["type"] == "responses"
        backend = delegation["responses"]
        assert backend["model"] == "gpt-6-luna"
        assert backend["reasoning"] == {"effort": "low"}
        assert "service_tier" not in backend
        # Without a camera ``look`` is not offered; functions are flat (Responses API).
        assert tool_names(backend["tools"]) == [
            "show_image",
            "hide_image",
            "play_animation",
            "web_search",
        ]
        functions = [t for t in backend["tools"] if t["type"] == "function"]
        assert all("function" not in t for t in functions) and len(functions) == 3
        instructions = session["instructions"]
        assert "You are Sonia" in instructions
        assert "HOW YOU WORK (real-time voice to voice)" in instructions
        assert "The museum opens at nine." in instructions
        assert "YOUR STACK RIGHT NOW" in instructions
        assert len(instructions) < 16_384 * 3  # well below the token limit


def test_session_config_honors_the_optional_settings(tmp_path: Path) -> None:
    settings = make_settings(
        tmp_path, backend_reasoning_effort="", backend_service_tier="priority", voice="cedar"
    )
    config = build_session_config(
        settings,
        registry=build_default_registry(include_look=True),
        gallery_ids=["office-photo"],
        knowledge_dir=tmp_path,
    )
    backend = config["delegation"]["responses"]
    assert "reasoning" not in backend
    assert backend["service_tier"] == "priority"
    assert backend["parallel_tool_calls"] is False
    assert "office-photo" in backend["instructions"]
    assert config["audio"]["output"]["voice"] == "cedar"
    assert tool_names(backend["tools"]) == [
        "look",
        "show_image",
        "hide_image",
        "play_animation",
        "web_search",
    ]
    assert "Look: take a new photo" in config["instructions"]


def test_the_rules_ask_her_to_stop_when_interrupted(tmp_path: Path) -> None:
    registry = build_default_registry(include_look=False)
    instructions = build_session_config(make_settings(tmp_path), registry=registry, gallery_ids=[])[
        "instructions"
    ]
    assert "Interruption policy: If the user interrupts you, stop right away" in instructions


def test_the_live_stack_says_the_voice_runs_in_the_cloud(tmp_path: Path) -> None:
    text = describe_live_stack(make_settings(tmp_path), action_names=["show_image"])
    assert "in the cloud" in text
    assert "Do not say you run locally" in text
    assert "you cannot see anyone" in text


#: What Sonnia must not know about her stack: she explains it without brand names.
_BRANDS = ("gpt", "openai", "unity", "genies", "luna", "darwin", "windows", "macos")


@pytest.mark.parametrize("vision_source", ["opencv", "unity", "none"])
def test_sonnia_does_not_know_the_brands_of_her_stack(tmp_path: Path, vision_source: str) -> None:
    settings = make_settings(tmp_path, vision_source=vision_source)
    config = build_session_config(
        settings, registry=build_default_registry(include_look=True), gallery_ids=[]
    )
    texts = {
        "instructions": config["instructions"],
        "backend": config["delegation"]["responses"]["instructions"],
    }
    for name, text in texts.items():
        found = [b for b in _BRANDS if re.search(rf"\b{b}\b", text, re.IGNORECASE)]
        assert not found, f"{name} names {found}"


def test_the_sample_rate_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # From .env it arrives as text: it must not break loading the settings.
    monkeypatch.setenv("LIVE_SAMPLE_RATE", "16000")
    assert LiveSettings().sample_rate == 16_000
    monkeypatch.setenv("LIVE_SAMPLE_RATE", "24000")
    assert Settings(_env_file=None).live.sample_rate == 24_000  # type: ignore[call-arg]
    monkeypatch.setenv("LIVE_SAMPLE_RATE", "44100")
    with pytest.raises(ValueError, match="16000 or 24000"):
        LiveSettings()


def test_the_key_falls_back_to_openai_api_key_without_a_live_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LIVE_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    assert LiveSettings().api_key == "openai-key"
    monkeypatch.setenv("LIVE_API_KEY", "live-key")
    assert LiveSettings().api_key == "live-key"


def test_vision_uses_the_gpt_live_key_if_there_is_no_other(monkeypatch: pytest.MonkeyPatch) -> None:
    # A .env with only LIVE_API_KEY: vision on OpenAI uses it too.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LIVE_API_KEY", "live-key")
    assert LLMSettings(base_url="https://api.openai.com/v1").key == "live-key"
    # But never towards another server.
    assert LLMSettings(base_url="https://api.moonshot.ai/v1").key == ""
    # OPENAI_API_KEY takes precedence over LIVE_API_KEY.
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    assert LLMSettings(base_url="https://api.openai.com/v1").key == "openai-key"


async def test_without_a_key_it_does_not_try_to_connect() -> None:
    client = LiveClient(LiveSettings(api_key=""))
    with pytest.raises(LiveError, match="LIVE_API_KEY"):
        await client.start({"model": "gpt-live-1"})


# ---------------------------------------------------------------------------
# Sonnia's voice to the avatar client
# ---------------------------------------------------------------------------


async def test_subtitles_do_not_show_sound_tags(tmp_path: Path) -> None:
    # "[laugh]", "[tongue click]"... must not show up on the screen.
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.hear("[tongue click] Well, how's it going?")
        await conn.say("[laugh] I'd love to, ")
        await conn.audio(pcm(2_400))
        await conn.say("but I don't [sig")
        await conn.say("h] have WhatsApp.")
        await rig.rec.wait_type("speech_end")
        shown = [m["text"] for m in rig.rec.of_type("transcript")]
        shown += [m["text"] for m in rig.rec.of_type("speech_start")]
        assert shown and not any("[" in t or "]" in t for t in shown)
        assert "I'd love to, but I don't have WhatsApp." in shown


async def test_the_voice_reaches_the_avatar_as_one_utterance_with_subtitles(tmp_path: Path) -> None:
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.say("Hello, ")
        for _ in range(3):
            await conn.audio(pcm(2_400))
        await conn.say("I'm Sonia.")

        await rig.rec.wait_type("speech_end")
        speech_start = rig.rec.of_type("speech_start")[0]
        assert speech_start["utterance_id"] == 1
        assert speech_start["text"] == "Hello,"
        assert "ambient" not in speech_start
        assert "speaking" in rig.rec.states()
        frames = rig.rec.audio(1)
        assert b"".join(f[3] for f in frames) == pcm(2_400) * 3
        assert frames[-1][2] is True  # the last chunk carries the end mark
        transcripts = [m for m in rig.rec.of_type("transcript") if m["role"] == "assistant"]
        assert transcripts[-1] == {
            "type": "transcript",
            "role": "assistant",
            "text": "Hello, I'm Sonnia.",
            "final": True,
        }
        assert any(not t["final"] for t in transcripts)

        # Until the avatar client confirms playback, Sonnia is still speaking.
        await asyncio.sleep(0.1)
        assert rig.engine.state == "speaking"
        await rig.unity({"type": "playback_done", "utterance_id": 1})
        await rig.rec.wait_state("idle", count=2)


async def test_a_long_silence_splits_the_voice_into_two_utterances(tmp_path: Path) -> None:
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.audio(pcm(1_200))
        await rig.rec.wait_type("speech_end")
        await conn.audio(pcm(1_200))
        await rig.rec.wait_type("speech_end", count=2)
        assert [m["utterance_id"] for m in rig.rec.of_type("speech_start")] == [1, 2]


async def test_continuous_silence_from_gpt_live_opens_no_utterances(tmp_path: Path) -> None:
    # The real API sends audio nonstop, also when quiet (digital silence).
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        for _ in range(5):
            await conn.audio(pcm(2_400, 0))
        await asyncio.sleep(0.3)
        assert not rig.rec.of_type("speech_start")
        assert rig.engine.state == "idle"


async def test_the_utterance_closes_even_if_silence_keeps_arriving(tmp_path: Path) -> None:
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        voice, silence = pcm(2_400, 900), pcm(2_400, 0)
        await conn.audio(silence)
        await conn.audio(voice)
        await conn.audio(silence)  # short pause within the utterance
        await conn.audio(voice)
        for _ in range(4):  # silence that keeps arriving in real time
            await conn.audio(silence)
            await asyncio.sleep(0.05)
        await rig.rec.wait_type("speech_end")
        sent = b"".join(f[3] for f in rig.rec.audio(1))
        assert sent == voice + silence + voice  # without the silence before or after
        assert len(rig.rec.of_type("speech_start")) == 1


# ---------------------------------------------------------------------------
# The user's voice
# ---------------------------------------------------------------------------


async def test_what_the_user_says_sets_listening_and_closes_the_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine_module, "RESPONSE_WAIT_S", 0.3)
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.hear("What is ")
        await rig.rec.wait_state("listening")
        await conn.hear("a voice avatar?")
        await rig.rec.wait_for(
            lambda msgs: any(
                m.get("type") == "transcript" and m["role"] == "user" and m["final"]
                for m in rig.rec.json(msgs)
            )
        )
        finals = [m for m in rig.rec.of_type("transcript") if m["role"] == "user" and m["final"]]
        assert finals[-1]["text"] == "What is a voice avatar?"
        # Turn closed: it waits for the answer in ``thinking`` and, if none comes, goes idle.
        await rig.rec.wait_state("thinking")
        await rig.rec.wait_state("idle", count=2)


async def test_text_input_arrives_as_commentary(tmp_path: Path) -> None:
    # ``instructions.append`` does not make her speak (seen with the real API); ``commentary`` does.
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await rig.unity({"type": "text_input", "text": "Where is the main room?"})
        await conn.wait_type("session.commentary.append")
        append = conn.of_type("session.commentary.append")[0]
        assert "Where is the main room?" in append["content"]
        assert append["delegation_id"] is None
        await rig.rec.wait_state("thinking")
        user = [m for m in rig.rec.of_type("transcript") if m["role"] == "user"]
        assert user[-1]["text"] == "Where is the main room?" and user[-1]["final"] is True


# ---------------------------------------------------------------------------
# Microphone
# ---------------------------------------------------------------------------


def test_subtitles_spell_the_name_sonnia() -> None:
    # It is said "Sonia"; it is written "Sonnia".
    from sonia.live.engine import clean_transcript

    assert clean_transcript("Hi, I'm Sonia") == "Hi, I'm Sonnia"
    assert clean_transcript("SONIA") == "SONNIA"
    assert clean_transcript("sonía") == "sonnia"  # accented transcription of the name
    assert clean_transcript("Sonnia was already right") == "Sonnia was already right"


def test_sound_tags_are_left_out_of_the_transcript() -> None:
    from sonia.live.engine import clean_transcript

    assert (
        clean_transcript("[laugh] Hi Sonia [sigh] can you hear me?") == "Hi Sonnia can you hear me?"
    )
    assert clean_transcript("[sigh") == ""
    assert clean_transcript("] Audit everything") == "Audit everything"
    assert clean_transcript("laugh] And what do you think") == "And what do you think"
    assert clean_transcript("Hello   world ") == "Hello world"


async def test_a_turn_that_is_only_a_laugh_is_not_shown(tmp_path: Path) -> None:
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.hear("[laugh")
        await conn.hear("]")
        await asyncio.sleep(0.4)
        finals = [m for m in rig.rec.of_type("transcript") if m["role"] == "user" and m["final"]]
        assert finals == []


def test_pcm16_and_rms() -> None:
    block = np.array([0.0, 0.5, -0.5, 2.0], dtype=np.float32)
    samples = np.frombuffer(pcm16_from_float(block), dtype="<i2")
    assert samples.tolist() == [0, 16383, -16383, 32767]
    assert rms(np.full(10, 0.25, dtype=np.float32)) == pytest.approx(0.25)


def test_the_noise_gate_opens_with_voice_and_holds_through_pauses() -> None:
    gate = NoiseGate(threshold=0.1, hold_ms=500)
    assert gate.admit(0.02, now=0.0) is False
    assert gate.admit(0.3, now=1.0) is True
    assert gate.admit(0.02, now=1.4) is True  # pause between words
    assert gate.admit(0.02, now=1.6) is False
    assert NoiseGate(threshold=0.0, hold_ms=500).admit(0.0) is True


def test_comfort_noise_has_the_requested_level_and_zero_gives_zeros() -> None:
    noise = ComfortNoise(0.003, seed=1).pcm(2_400)
    assert len(noise) == 4_800
    assert pcm_level(noise) == pytest.approx(0.003, rel=0.1)
    assert ComfortNoise(0.0).pcm(10) == bytes(20)


async def test_the_mic_stays_open_while_sonnia_speaks(tmp_path: Path) -> None:
    # GPT-Live is full duplex: the user can interrupt her at any time.
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.audio(pcm(1_200))
        await rig.rec.wait_type("speech_start")
        await rig.engine.push_mic(voice_block())
        await conn.wait_type("session.input_audio.append")
        assert any(conn.audio_in()[-1])


async def test_the_noise_gate_sends_comfort_noise_below_the_threshold(tmp_path: Path) -> None:
    async with make_rig(tmp_path, gate_rms=0.1) as rig:
        conn = await rig.conn()
        await rig.engine.push_mic(voice_block(0.01))
        await rig.engine.push_mic(voice_block(0.5))
        await conn.wait_type("session.input_audio.append", count=2)
        quiet, loud = conn.audio_in()[-2:]
        assert pcm_level(quiet) == pytest.approx(0.003, rel=0.2)
        assert pcm_level(loud) == pytest.approx(0.5, rel=0.01)


async def test_gpt_live_never_hears_absolute_zeros(tmp_path: Path) -> None:
    # With absolute zeros GPT-Live was slow to answer (sonia run --no-mic, a
    # microphone without macOS permission); LIVE_COMFORT_NOISE_RMS=0 brings them back.
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await rig.engine.push_mic(voice_block(0.0))
        await conn.wait_type("session.input_audio.append")
        assert pcm_level(conn.audio_in()[-1]) == pytest.approx(0.003, rel=0.2)
    async with make_rig(tmp_path, comfort_noise_rms=0.0) as rig:
        conn = await rig.conn()
        await rig.engine.push_mic(voice_block(0.0))
        await conn.wait_type("session.input_audio.append")
        assert not any(conn.audio_in()[-1])


# ---------------------------------------------------------------------------
# Delegation and actions
# ---------------------------------------------------------------------------


async def test_show_image_by_delegation_and_backend_continuation(tmp_path: Path) -> None:
    (tmp_path / "gallery").mkdir()
    (tmp_path / "gallery" / "logo.png").write_bytes(b"\x89PNG-logo")
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.send(
            {
                "type": "session.delegation.created",
                "event_id": "ed",
                "offset_ms": 100,
                "delegation": {
                    "id": "deleg_1",
                    "type": "delegation",
                    "target": "responses",
                    "response_id": "resp_1",
                },
            }
        )
        await rig.rec.wait_state("thinking")
        await conn.response_event({"type": "response.created"})
        await conn.response_event(
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "show_image",
                    "arguments": json.dumps({"image_id": "logo", "caption": "Our logo"}),
                },
            }
        )
        await conn.response_event({"type": "response.completed"})

        await rig.rec.wait_type("show_image")
        shown = rig.rec.of_type("show_image")[0]
        assert shown["image_id"] == "logo"
        assert base64.b64decode(shown["data_base64"]) == b"\x89PNG-logo"
        await conn.wait_type("response.create")
        kinds = [m["type"] for m in conn.received if m["type"].startswith("response.")]
        assert kinds == ["response.item.create", "response.create"]
        output = conn.of_type("response.item.create")[0]["item"]
        assert output["type"] == "function_call_output"
        assert output["call_id"] == "call_1"
        assert output["output"].startswith("Showing")

        # The backend's second response only brings text: the task ends.
        await conn.response_event({"type": "response.created"})
        await conn.response_event({"type": "response.output_text.delta", "delta": "Logo shown."})
        await conn.response_event({"type": "response.completed"})
        await wait_until(lambda: not rig.engine._delegations)
        assert len(conn.of_type("response.create")) == 1


async def test_look_returns_the_photo_to_the_backend(tmp_path: Path) -> None:
    camera = FakeCamera(data=b"\xff\xd8photo")
    async with make_rig(tmp_path, camera=camera, vision_source="opencv") as rig:
        conn = await rig.conn()
        tools = conn.start["session"]["delegation"]["responses"]["tools"]
        assert "look" in tool_names(tools)
        await conn.response_event(
            {
                "type": "response.output_item.done",
                "item": {"type": "function_call", "call_id": "c", "name": "look", "arguments": ""},
            }
        )
        await conn.response_event({"type": "response.completed"})
        await conn.wait_type("response.create")
        items = [m["item"] for m in conn.of_type("response.item.create")]
        assert items[0] == {
            "type": "function_call_output",
            "call_id": "c",
            "output": "Snapshot taken.",
        }
        image = items[1]["content"][1]
        assert image["type"] == "input_image"
        assert image["image_url"] == "data:image/jpeg;base64," + b64(b"\xff\xd8photo")
        assert camera.captures == 1


async def test_an_unknown_action_returns_the_error_to_the_backend(tmp_path: Path) -> None:
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.response_event(
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "function_call",
                    "call_id": "x",
                    "name": "fly",
                    "arguments": "{",
                },
            }
        )
        await conn.response_event({"type": "response.completed"})
        await conn.wait_type("response.create")
        output = conn.of_type("response.item.create")[0]["item"]["output"]
        assert output.startswith("Error")


async def test_gallery_additions_and_removals_arrive_in_a_silent_note(
    tmp_path: Path,
) -> None:
    # The gallery can start empty and be filled while Sonnia runs, without a restart.
    async with make_rig(tmp_path, gallery_watch=0.05) as rig:
        conn = await rig.conn()
        instructions = conn.start["session"]["instructions"]
        assert "The image gallery is empty" in instructions
        assert '"[Gallery]"' in instructions

        (tmp_path / "gallery" / "offices.png").write_bytes(b"\x89PNG")
        await conn.wait_type("session.thinking.append")
        note = conn.of_type("session.thinking.append")[0]["content"]
        assert note.startswith("[Gallery] New images were added to your gallery: offices.")
        assert "exact ids): offices." in note

        (tmp_path / "gallery" / "offices.png").unlink()
        await conn.wait_type("session.thinking.append", count=2)
        note = conn.of_type("session.thinking.append")[1]["content"]
        assert note.startswith("[Gallery] Removed: offices.")
        assert "is now empty" in note
        # Silent: it opens no turn and does not make Sonnia speak.
        assert conn.of_type("session.commentary.append") == []
        assert conn.of_type("response.create") == []


async def test_a_change_undone_before_it_is_reported_sends_no_note(tmp_path: Path) -> None:
    async with make_rig(tmp_path, gallery_watch=3600.0) as rig:
        await rig.conn()
        gallery = Gallery(tmp_path / "gallery")
        (tmp_path / "gallery" / "offices.png").write_bytes(b"\x89PNG")
        await rig.engine._check_gallery(gallery)
        assert rig.engine._pending_gallery is not None
        (tmp_path / "gallery" / "offices.png").unlink()
        await rig.engine._check_gallery(gallery)
        assert rig.engine._pending_gallery is None


def test_the_gallery_note_fits_in_one_append() -> None:
    ids = [f"image-number-{n:03d}" for n in range(200)]
    note = gallery_note(ids, [], ids, max_chars=1_200)
    assert len(note) <= 1_200
    assert note.startswith("[Gallery] New images were added to your gallery: image-number-000")
    assert " more." in note
    assert note.endswith("Do not announce it: show them when they fit the conversation.")


# ---------------------------------------------------------------------------
# Vision
# ---------------------------------------------------------------------------


async def test_a_camera_note_arrives_when_someone_starts_talking(tmp_path: Path) -> None:
    camera = FakeCamera()
    llm = FakeVisionLLM()
    async with make_rig(
        tmp_path, camera=camera, narrator=VisionNarrator(llm), vision_source="opencv"
    ) as rig:
        conn = await rig.conn()
        await conn.hear("Hello")
        await conn.wait_type("session.thinking.append")
        note = conn.of_type("session.thinking.append")[0]
        assert note["content"] == "[Camera] A person in a blue shirt and glasses."
        assert note["delegation_id"] is None
        # The photo goes to the vision model as image_url, never to GPT-Live.
        content = llm.requests[0][1]["content"]
        assert any(part.get("type") == "image_url" for part in content)
        assert rig.engine.last_frame is not None


async def test_the_narrator_does_not_repeat_within_the_minimum_interval(tmp_path: Path) -> None:
    camera = FakeCamera()
    async with make_rig(
        tmp_path,
        camera=camera,
        narrator=VisionNarrator(FakeVisionLLM()),
        vision_source="opencv",
        vision_min_interval_seconds=60.0,
        user_turn_gap_ms=50,
    ) as rig:
        conn = await rig.conn()
        await conn.hear("Hello")
        await conn.wait_type("session.thinking.append")
        await asyncio.sleep(0.15)
        await conn.hear("Something else")
        await asyncio.sleep(0.2)
        assert camera.captures == 1


async def test_by_default_she_only_looks_when_sonnia_decides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No automatic photo when someone starts talking by default; only the look action.
    monkeypatch.delenv("VISION_ON_TURN_START", raising=False)
    assert VisionSettings().on_turn_start is False
    camera = FakeCamera()
    async with make_rig(
        tmp_path,
        camera=camera,
        narrator=VisionNarrator(FakeVisionLLM()),
        vision_source="opencv",
        on_turn_start=False,
        user_turn_gap_ms=50,
    ) as rig:
        conn = await rig.conn()
        await conn.hear("Hello")
        await rig.rec.wait_for(
            lambda msgs: any(m.get("type") == "transcript" and m.get("final") for m in msgs)
        )
        await asyncio.sleep(0.2)
        assert camera.captures == 0
        notes = [m["content"] for m in conn.of_type("session.thinking.append")]
        assert not [n for n in notes if n.startswith("[Camera]")]
        instructions = conn.start["session"]["instructions"]
        tools = tool_names(conn.start["session"]["delegation"]["responses"]["tools"])
    assert "look" in tools
    assert "You do not see anything on your own" in instructions
    assert "You do not know what anyone looks like or what they wear until you look" in instructions
    assert "internal notes that start with" not in instructions
    assert "you do not watch all the time" in instructions


# ---------------------------------------------------------------------------
# Interruption, reconnection and renewal
# ---------------------------------------------------------------------------


async def test_an_interrupt_from_the_avatar_cuts_the_voice_and_drops_the_rest(
    tmp_path: Path,
) -> None:
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.audio(pcm(1_200))
        await rig.rec.wait_type("speech_start")
        await rig.unity({"type": "interrupt"})
        await rig.rec.wait_type("stop_speaking")
        await conn.wait_type("session.instructions.append")
        assert conn.of_type("session.instructions.append")[0]["content"] == INTERRUPT_TEXT

        # Whatever keeps arriving from that answer is not played.
        await conn.audio(pcm(1_200))
        await asyncio.sleep(0.05)
        assert len(rig.rec.of_type("speech_start")) == 1
        # After a silence, the next voice is a new utterance.
        await asyncio.sleep(0.25)
        await conn.audio(pcm(1_200))
        await rig.rec.wait_type("speech_start", count=2)
        assert rig.rec.of_type("speech_start")[1]["utterance_id"] == 2


async def test_reconnects_when_the_session_drops(tmp_path: Path) -> None:
    server = FakeLiveServer(drop_after_start=True)
    async with make_rig(tmp_path, server=server):
        await server.wait_conn(3)
        assert server.attempts >= 3


async def test_if_gpt_live_rejects_the_session_it_reports_and_retries(tmp_path: Path) -> None:
    server = FakeLiveServer(reject=True)
    async with make_rig(tmp_path, server=server) as rig:
        await rig.rec.wait_type("error")
        message = rig.rec.of_type("error")[0]["message"]
        assert "model_not_found" in message
        await wait_until(lambda: server.attempts >= 2)
        assert not rig.engine.connected


async def test_after_a_while_with_nobody_it_opens_a_new_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine_module, "RESPONSE_WAIT_S", 0.1)
    async with make_rig(tmp_path, idle_reset=0.3) as rig:
        conn = await rig.conn()
        await conn.hear("Hello")
        await conn.wait_type("session.close", limit=4.0)
        await rig.conn(2)
        assert rig.rec.of_type("hide_image")


async def test_without_a_conversation_the_session_is_not_renewed(tmp_path: Path) -> None:
    async with make_rig(tmp_path, idle_reset=0.1) as rig:
        conn = await rig.conn()
        await asyncio.sleep(0.4)
        assert not conn.of_type("session.close")


# ---------------------------------------------------------------------------
# Idle animation
# ---------------------------------------------------------------------------


async def test_an_idle_bit_goes_as_commentary_and_plays_as_ambient(tmp_path: Path) -> None:
    showcase = Showcase(phrases=["Come on over and ask me anything!"], songs=[], gesture_chance=0)
    settings = ShowcaseSettings(
        enabled=True, first_delay_seconds=0.0, interval_min_seconds=60, interval_max_seconds=60
    )
    async with make_rig(tmp_path, showcase=showcase, showcase_settings=settings) as rig:
        conn = await rig.conn()
        await conn.wait_type("session.commentary.append")
        content = conn.of_type("session.commentary.append")[0]["content"]
        assert "Come on over and ask me anything!" in content
        await conn.audio(pcm(1_200))
        await rig.rec.wait_type("speech_start")
        assert rig.rec.of_type("speech_start")[0]["ambient"] is True
        await rig.rec.wait_type("speech_end")
        assert "speaking" not in rig.rec.states()


async def test_an_idle_line_in_two_stretches_stays_ambient(tmp_path: Path) -> None:
    showcase = Showcase(phrases=["Here's an idea: come closer."], songs=[], gesture_chance=0)
    settings = ShowcaseSettings(
        enabled=True, first_delay_seconds=0.0, interval_min_seconds=60, interval_max_seconds=60
    )
    async with make_rig(tmp_path, showcase=showcase, showcase_settings=settings) as rig:
        conn = await rig.conn()
        await conn.wait_type("session.commentary.append")
        await conn.audio(pcm(1_200))
        await rig.rec.wait_type("speech_end")
        await conn.audio(pcm(1_200))
        await rig.rec.wait_type("speech_end", count=2)
        assert [m["ambient"] for m in rig.rec.of_type("speech_start")] == [True, True]
        assert "speaking" not in rig.rec.states()


async def test_an_idle_dance_tells_the_avatar_before_asking_for_the_voice(tmp_path: Path) -> None:
    showcase = Showcase(phrases=[], songs=["La la la"], dance_chance=1.0)
    settings = ShowcaseSettings(
        enabled=True, first_delay_seconds=0.0, interval_min_seconds=60, interval_max_seconds=60
    )
    async with make_rig(tmp_path, showcase=showcase, showcase_settings=settings) as rig:
        conn = await rig.conn()
        await conn.wait_type("session.commentary.append")
        attention = rig.rec.of_type("attention")
        assert attention and attention[0]["category"] == ATTENTION_DANCE


def moments_only() -> tuple[Showcase, ShowcaseSettings]:
    showcase = Showcase(phrases=[], songs=[], gesture_chance=0, moment_chance=1.0)
    settings = ShowcaseSettings(
        enabled=True, first_delay_seconds=0.0, interval_min_seconds=60, interval_max_seconds=60
    )
    return showcase, settings


async def test_an_idle_moment_draws_on_what_the_camera_sees(tmp_path: Path) -> None:
    showcase, settings = moments_only()
    llm = FakeVisionLLM("Two people with name badges are looking at the screen.")
    async with make_rig(
        tmp_path,
        showcase=showcase,
        showcase_settings=settings,
        camera=FakeCamera(),
        narrator=VisionNarrator(llm),
        vision_source="opencv",
    ) as rig:
        conn = await rig.conn()
        await conn.wait_type("session.commentary.append")
        content = conn.of_type("session.commentary.append")[0]["content"]
        assert "Two people with name badges are looking at the screen." in content
        assert "never the body, age, skin" in content
        # What she says plays as an idle line: without changing state.
        await conn.audio(pcm(1_200))
        await rig.rec.wait_type("speech_start")
        assert rig.rec.of_type("speech_start")[0]["ambient"] is True


async def test_without_a_camera_the_moment_suggests_something_specific(tmp_path: Path) -> None:
    showcase, settings = moments_only()
    async with make_rig(tmp_path, showcase=showcase, showcase_settings=settings) as rig:
        conn = await rig.conn()
        await conn.wait_type("session.commentary.append")
        content = conn.of_type("session.commentary.append")[0]["content"]
        assert "Nobody is talking to you" in content and "trivia" in content


async def test_if_someone_talks_while_the_moment_is_prepared_it_is_not_requested(
    tmp_path: Path,
) -> None:
    showcase, settings = moments_only()
    camera = FakeCamera(delay=0.5)
    async with make_rig(
        tmp_path,
        showcase=showcase,
        showcase_settings=settings,
        camera=camera,
        narrator=VisionNarrator(FakeVisionLLM()),
        vision_source="opencv",
        on_turn_start=False,
    ) as rig:
        conn = await rig.conn()
        await wait_until(lambda: camera.captures >= 1)
        await conn.hear("Hi Sonia")
        await asyncio.sleep(0.8)
        assert not conn.of_type("session.commentary.append")


async def test_without_the_idle_animation_nothing_is_requested(tmp_path: Path) -> None:
    showcase = Showcase(phrases=["Hello"], songs=[], gesture_chance=0)
    settings = ShowcaseSettings(enabled=False, first_delay_seconds=0.0)
    async with make_rig(tmp_path, showcase=showcase, showcase_settings=settings) as rig:
        conn = await rig.conn()
        await asyncio.sleep(0.3)
        assert not conn.of_type("session.commentary.append")


# ---------------------------------------------------------------------------
# Short sessions: sonia check and sonia say
# ---------------------------------------------------------------------------


async def test_probe_session_opens_and_closes(tmp_path: Path) -> None:
    server = FakeLiveServer()
    async with running(server) as connect:
        result = await probe_session(make_settings(tmp_path).live, connect=connect)
    assert result.session_id == "sess_1"
    assert result.voice == "marin"
    assert result.expires_in_s is not None and result.expires_in_s > 3000
    assert server.conns[0].of_type("session.close")


async def test_speak_text_returns_the_gpt_live_voice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(oneshot_module, "SAY_END_GAP_S", 0.2)
    server = FakeLiveServer()

    async def react(conn: FakeConn, message: dict[str, Any]) -> None:
        if message["type"] == "session.commentary.append":
            # Like the real API: silence before and after the voice.
            await conn.audio(pcm(2_400, 0))
            await conn.audio(pcm(2_400, 700))
            await conn.audio(pcm(2_400, 700))
            for _ in range(3):
                await conn.audio(pcm(2_400, 0))

    server.on_message = react
    async with running(server) as connect:
        audio = await speak_text(make_settings(tmp_path).live, "Hello", connect=connect)
    # Without the silence before and with only a short tail after.
    assert audio.startswith(pcm(4_800, 700))
    assert len(audio) - len(pcm(4_800, 700)) <= int(RATE * 0.15) * 2
    request = server.conns[0].of_type("session.commentary.append")[0]["content"]
    assert request == "Hello"
    assert server.conns[0].of_type("session.input_audio.append")  # background silence


async def test_speak_text_cuts_what_gpt_live_adds_after_the_text(tmp_path: Path) -> None:
    # This really happened: after a recorded greeting it started announcing a made-up talk.
    server = FakeLiveServer()

    async def react(conn: FakeConn, message: dict[str, Any]) -> None:
        if message["type"] == "session.commentary.append":
            await conn.say("Today we talk about technology.")
            for _ in range(4):
                await conn.audio(pcm(2_400, 700))
            for _ in range(6):  # 0.6 s pause: less than SAY_END_GAP_S
                await conn.audio(pcm(2_400, 0))
            await conn.say(" We have a talk on artificial intelligence.")
            for _ in range(10):
                await conn.audio(pcm(2_400, 900))
            for _ in range(20):
                await conn.audio(pcm(2_400, 0))

    server.on_message = react
    async with running(server) as connect:
        audio = await speak_text(
            make_settings(tmp_path).live, "Today we talk about technology.", connect=connect
        )
    assert audio.startswith(pcm(9_600, 700))
    assert pcm(2_400, 900) not in audio  # nothing of the made-up talk


async def test_speak_text_rejects_a_reading_that_is_too_long(tmp_path: Path) -> None:
    # Without a transcript there is no telling where the text ends: the length cap rules.
    server = FakeLiveServer()

    async def react(conn: FakeConn, message: dict[str, Any]) -> None:
        if message["type"] == "session.commentary.append":
            for _ in range(40):  # 4 s of voice for a "Hello"
                await conn.audio(pcm(2_400, 700))
            for _ in range(20):
                await conn.audio(pcm(2_400, 0))

    server.on_message = react
    async with running(server) as connect:
        with pytest.raises(LiveError, match="did not stick to reading"):
            await speak_text(make_settings(tmp_path).live, "Hello", connect=connect)


def test_the_cache_discards_a_recorded_line_that_is_too_long(tmp_path: Path) -> None:
    import wave

    from sonia.live.voicecache import VoiceCache

    settings = make_settings(tmp_path)
    cache = VoiceCache(tmp_path / "voice", settings.live)
    good, bad = "Hi!", "Welcome! Come closer and say hello."
    for text, seconds in ((good, 1.0), (bad, 13.85)):
        path = cache.path_for(text)
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(RATE)
            wav.writeframes(pcm(int(RATE * seconds), 700))
    assert cache.get(good) is not None
    assert cache.missing([good, bad]) == [bad]
    assert cache.get(bad) is None
    assert not cache.path_for(bad).exists()  # deleted so it is recorded again


def test_the_narrator_trims_and_normalizes(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = FakeVisionLLM("  Two   people\n with caps. ")
    text = asyncio.run(VisionNarrator(llm).describe(Frame(data=b"x")))
    assert text == "Two people with caps."


# ---------------------------------------------------------------------------
# Cases found in review
# ---------------------------------------------------------------------------


def call_item(name: str = "hide_image", call_id: str = "call_1") -> dict[str, Any]:
    return {
        "type": "response.output_item.done",
        "item": {"type": "function_call", "call_id": call_id, "name": name, "arguments": "{}"},
    }


async def test_a_late_event_does_not_revive_a_closed_task(tmp_path: Path) -> None:
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.response_event({"type": "response.created"})
        await conn.response_event({"type": "response.output_text.delta", "delta": "Done."})
        await conn.response_event({"type": "response.completed"})
        await wait_until(lambda: not rig.engine._delegations)
        # Later events of the same task, with or without its id.
        await conn.response_event({"type": "response.output_text.delta", "delta": "x"})
        await conn.response_event({"type": "response.output_text.delta", "delta": "x"}, None)
        await asyncio.sleep(0.1)
        assert not rig.engine._delegations


async def test_an_error_on_a_backend_command_closes_the_task(tmp_path: Path) -> None:
    server = FakeLiveServer()

    async def reject_items(conn: FakeConn, message: dict[str, Any]) -> None:
        if message["type"] == "response.item.create":
            await conn.send(
                {
                    "type": "error",
                    "event_id": "err",
                    "error": {
                        "type": "invalid_request_error",
                        "code": "invalid_item",
                        "message": "no",
                        "client_event_id": message["event_id"],
                    },
                }
            )

    server.on_message = reject_items
    async with make_rig(tmp_path, server=server) as rig:
        conn = await rig.conn()
        await conn.response_event(call_item())
        await conn.wait_type("response.item.create")
        await wait_until(lambda: not rig.engine._delegations)
        assert not rig.engine._command_owner


async def test_if_the_backend_does_not_finish_sonnia_says_so_and_stops_thinking(
    tmp_path: Path,
) -> None:
    """``Responses handoff incomplete`` brings no final event: she used to think for 90 s."""
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.send(
            {
                "type": "session.delegation.created",
                "event_id": "ed",
                "delegation": {"id": "deleg_1", "type": "delegation", "target": "responses"},
            }
        )
        await rig.rec.wait_state("thinking")
        await conn.send(
            {
                "type": "error",
                "event_id": "err",
                "error": {
                    "type": "invalid_request_error",
                    "message": "Responses handoff incomplete.",
                },
            }
        )
        await conn.wait_type("session.commentary.append")
        assert not rig.engine._delegations
        assert conn.of_type("session.commentary.append")[0]["content"] == DELEGATION_FAILED_TEXT

        # Any other error does not make her say anything.
        await conn.send({"type": "error", "error": {"type": "server_error", "message": "x"}})
        await asyncio.sleep(0.1)
        assert len(conn.of_type("session.commentary.append")) == 1


async def test_an_action_without_a_delegation_id_also_continues(tmp_path: Path) -> None:
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.response_event(call_item(), None)
        await conn.response_event({"type": "response.completed"}, None)
        await conn.wait_type("response.create")


async def test_after_an_interrupt_the_audio_the_avatar_dropped_is_not_awaited(
    tmp_path: Path,
) -> None:
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.audio(pcm(RATE * 10))  # 10 s of voice at once
        await rig.rec.wait_type("speech_start")
        await rig.unity({"type": "interrupt"})
        await rig.rec.wait_type("stop_speaking")
        await asyncio.sleep(0.25)
        await conn.audio(pcm(2_400))  # 0,1 s
        await rig.rec.wait_type("speech_end")
        # Without a playback_done from the avatar, the wait is 0.1 s plus the margin, not 10 s.
        await wait_until(lambda: not rig.engine._audible, limit=2.5)


async def test_an_orderly_server_close_does_not_reconnect_nonstop(tmp_path: Path) -> None:
    server = FakeLiveServer(close_after_start="expired")
    async with make_rig(
        tmp_path, server=server, reconnect_min_seconds=0.3, reconnect_max_seconds=0.3
    ):
        await server.wait_conn(1)
        await asyncio.sleep(0.8)
        assert server.attempts <= 4


# ---------------------------------------------------------------------------
# Trivia
# ---------------------------------------------------------------------------

TRIVIA_BANK = """\
## First?
- [x] One right
- [ ] One wrong
- [ ] One worse

## Second?
- [ ] Two wrong
- [x] Two right
- [ ] Two worse
"""


async def _backend_call(conn: FakeConn, call_id: str, name: str, args: dict[str, Any]) -> str:
    """The backend requests an action; returns what the engine answers it."""
    before = len(conn.of_type("response.item.create"))
    await conn.response_event({"type": "response.created"}, delegation_id=f"deleg_{call_id}")
    await conn.response_event(
        {
            "type": "response.output_item.done",
            "item": {
                "type": "function_call",
                "call_id": call_id,
                "name": name,
                "arguments": json.dumps(args),
            },
        },
        delegation_id=f"deleg_{call_id}",
    )
    await conn.response_event({"type": "response.completed"}, delegation_id=f"deleg_{call_id}")
    await conn.wait_for(lambda msgs: len(conn.of_type("response.item.create")) > before)
    output = conn.of_type("response.item.create")[-1]["item"]
    assert output["call_id"] == call_id
    return str(output["output"])


async def test_trivia_by_voice_from_start_to_end(tmp_path: Path) -> None:
    (tmp_path / "trivia").mkdir()
    (tmp_path / "trivia" / "questions.md").write_text(TRIVIA_BANK, encoding="utf-8")
    async with make_rig(tmp_path, trivia=True) as rig:
        rig.settings.trivia.questions = 2
        rig.settings.trivia.win_threshold = 1
        rig.settings.trivia.reveal_seconds = 0.05
        rig.settings.trivia.final_wait_seconds = 0.2
        conn = await rig.conn()
        backend = conn.start["session"]["delegation"]["responses"]
        assert tool_names(backend["tools"]) == [
            "show_image",
            "hide_image",
            "play_animation",
            "start_trivia",
            "trivia_answer",
            "trivia_next",
            "restart_trivia",
            "stop_trivia",
            "web_search",
        ]
        assert "FOR SONIA:" in backend["instructions"]
        assert (
            "Trivia: the questions, their options and the card"
            in conn.start["session"]["instructions"]
        )

        # "Shall we play the trivia?": GPT-Live delegates and the backend calls start_trivia.
        script = await _backend_call(conn, "c1", "start_trivia", {"level": "medium"})
        assert script.startswith("FOR SONIA:")
        await rig.rec.wait_type("trivia_question")
        question = rig.rec.of_type("trivia_question")[0]
        assert question["number"] == 1 and question["total"] == 2
        assert question["question"] in script
        # The rules go in as an instruction, without making her speak.
        appended = [m["content"] for m in conn.of_type("session.instructions.append")]
        assert any("TRIVIA MODE ON" in text for text in appended)
        assert rig.rec.of_type("trivia_start")[0] == {
            "type": "trivia_start",
            "total": 2,
            "threshold": 1,
            "level": "medium",
        }

        # The user says "the one that..." and GPT-Live records the letter it understood.
        right = question["options"].index(
            "One right" if "First" in question["question"] else "Two right"
        )
        script = await _backend_call(conn, "c2", "trivia_answer", {"option": "ABC"[right]})
        assert "CORRECT" in script and "next question" in script
        await rig.rec.wait_type("trivia_answer")
        assert rig.rec.of_type("trivia_answer")[0]["is_correct"] is True
        # Nothing moves on by itself: the next one comes when the user asks for it.
        await asyncio.sleep(0.2)
        assert len(rig.rec.of_type("trivia_question")) == 1
        script = await _backend_call(conn, "c2b", "trivia_next", {})
        assert "question 2 of 2" in script
        await rig.rec.wait_type("trivia_question", count=2)

        # A client that connects now (a restarted avatar client) sees the current question.
        assert rig.hub.sticky("trivia_question") == rig.rec.of_type("trivia_question")[-1]

        script = await _backend_call(conn, "c3", "trivia_answer", {"option": "dont_know"})
        assert "They do not know" in script and "HAVE WON" in script
        await rig.rec.wait_type("trivia_end")
        end = rig.rec.of_type("trivia_end")[0]
        assert end == {
            "type": "trivia_end",
            "score": 1,
            "total": 2,
            "won": True,
            "reason": "finished",
        }
        assert rig.hub.sticky("trivia_question") is None
        assert rig.engine.trivia is not None and not rig.engine.trivia.active
        # Nothing was requested through commentary: everything went through the action results.
        assert conn.of_type("session.commentary.append") == []


async def test_the_trivia_is_cancelled_if_the_session_drops(tmp_path: Path) -> None:
    (tmp_path / "trivia").mkdir()
    (tmp_path / "trivia" / "questions.md").write_text(TRIVIA_BANK, encoding="utf-8")
    async with make_rig(tmp_path, trivia=True) as rig:
        rig.settings.trivia.questions = 2
        conn = await rig.conn()
        trivia = rig.engine.trivia
        assert trivia is not None
        ok, _ = await trivia.start("panel")
        assert ok
        await conn.wait_type("session.commentary.append")
        await conn.ws.close()
        await rig.rec.wait_type("trivia_end")
        assert rig.rec.of_type("trivia_end")[0]["reason"] == "cancelled"
        assert not trivia.active


async def test_dances_when_asked(tmp_path: Path) -> None:
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        assert "You are asked to dance" in conn.start["session"]["instructions"]
        # Before the avatar client sends its catalog there are no moves.
        script = await _backend_call(conn, "m1", "play_animation", {"move": "dance"})
        assert "you cannot move" in script
        # The avatar client sends the catalog when it connects; GPT-Live delegates "dance!".
        await rig.client.send(
            json.dumps(
                {
                    "type": "animations",
                    "animations": [
                        {"clip": "Wave", "group": "greeting"},
                        {"clip": "QuickAction_vibe", "group": "dance"},
                    ],
                }
            )
        )
        await wait_until(lambda: bool(rig.engine._moves.available()))
        script = await _backend_call(conn, "m2", "play_animation", {"move": "dance"})
        assert script.startswith("Done")
        await rig.rec.wait_type("play_animation")
        assert rig.rec.of_type("play_animation") == [
            {"type": "play_animation", "clip": "QuickAction_vibe", "whole": True}
        ]
        script = await _backend_call(conn, "m3", "play_animation", {"move": "peace"})
        assert "You do not have that move" in script and "dance, wave" in script


def _delegation_created(delegation_id: str = "deleg_1") -> dict[str, Any]:
    return {
        "type": "session.delegation.created",
        "event_id": "ed",
        "offset_ms": 100,
        "delegation": {
            "id": delegation_id,
            "type": "delegation",
            "target": "responses",
            "response_id": "resp_1",
        },
    }


def _activities(rig: LiveRig) -> list[str]:
    return [m["activity"] for m in rig.rec.of_type("activity")]


async def test_activity_tells_the_avatar_about_a_web_search(tmp_path: Path) -> None:
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.send(_delegation_created())
        await conn.response_event({"type": "response.created"})
        await conn.response_event(
            {
                "type": "response.output_item.added",
                "item": {"type": "web_search_call", "id": "ws_1", "status": "in_progress"},
            }
        )
        await rig.rec.wait_for(lambda _: _activities(rig) == ["search"])
        # The search's own events count too (and do not repeat the notice).
        await conn.response_event({"type": "response.web_search_call.searching", "item_id": "ws_1"})
        await conn.response_event({"type": "response.web_search_call.completed", "item_id": "ws_1"})
        await rig.rec.wait_for(lambda _: _activities(rig) == ["search", "none"])
        await conn.response_event({"type": "response.output_text.delta", "delta": "Found it."})
        await conn.response_event({"type": "response.completed"})
        await wait_until(lambda: not rig.engine._delegations)
        await asyncio.sleep(0.1)
        assert _activities(rig) == ["search", "none"]


async def test_activity_reports_a_slow_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine_module, "SLOW_TASK_S", 0.15)
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.send(_delegation_created())
        await conn.response_event({"type": "response.created"})
        await rig.rec.wait_for(lambda _: _activities(rig) == ["think"])
        await conn.response_event({"type": "response.output_text.delta", "delta": "Done."})
        await conn.response_event({"type": "response.completed"})
        await rig.rec.wait_for(lambda _: _activities(rig) == ["think", "none"])


async def test_activity_does_not_report_a_quick_task(tmp_path: Path) -> None:
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.send(_delegation_created())
        await conn.response_event({"type": "response.created"})
        await conn.response_event({"type": "response.output_text.delta", "delta": "Done."})
        await conn.response_event({"type": "response.completed"})
        await wait_until(lambda: not rig.engine._delegations)
        await asyncio.sleep(0.1)
        assert _activities(rig) == []


# ---------------------------------------------------------------------------
# On-screen waiting indicator (``busy``, sonia.busy)
# ---------------------------------------------------------------------------


def _busy(rig: LiveRig) -> list[str]:
    """The ``busy`` messages that reached the avatar client: the text of each ``on``, or ``off``."""
    return [m["text"] if m["on"] else "off" for m in rig.rec.of_type("busy")]


async def test_busy_thinking_from_the_start_of_the_delegation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine_module, "THINK_DELAY_S", 0.0)
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.send(_delegation_created())
        await rig.rec.wait_for(lambda _: _busy(rig) == ["Thinking…"])
        await rig.rec.wait_state("thinking")
        # With no delay it shows when the task is born, even before the ``thinking`` state.
        msgs = rig.rec.json()
        first_busy = next(i for i, m in enumerate(msgs) if m["type"] == "busy")
        thinking = next(
            i for i, m in enumerate(msgs) if m["type"] == "state" and m["state"] == "thinking"
        )
        assert first_busy < thinking
        assert rig.rec.of_type("busy")[0] == {
            "type": "busy",
            "on": True,
            "kind": "think",
            "text": "Thinking…",
        }
        await conn.response_event({"type": "response.created"})
        await conn.response_event({"type": "response.output_text.delta", "delta": "Done."})
        await conn.response_event({"type": "response.completed"})
        await rig.rec.wait_for(lambda _: _busy(rig) == ["Thinking…", "off"])
        # The rain and the hand on the chin are still only for the slow ones.
        assert _activities(rig) == []
        assert rig.engine.busy_board.current() is None


async def test_busy_thinking_waits_a_moment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The "Thinking…" pill waits for ``THINK_DELAY_S``; a task that ends earlier does not turn it on."""
    monkeypatch.setattr(engine_module, "THINK_DELAY_S", 0.4)
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.send(_delegation_created())
        await rig.rec.wait_state("thinking")
        assert _busy(rig) == []
        await rig.rec.wait_for(lambda _: _busy(rig) == ["Thinking…"])
        await conn.response_event({"type": "response.created"})
        await conn.response_event({"type": "response.completed"})
        await rig.rec.wait_for(lambda _: _busy(rig) == ["Thinking…", "off"])
    monkeypatch.setattr(engine_module, "THINK_DELAY_S", 5.0)
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.send(_delegation_created())
        await rig.rec.wait_state("thinking")
        await conn.response_event({"type": "response.created"})
        await conn.response_event({"type": "response.output_text.delta", "delta": "Done."})
        await conn.response_event({"type": "response.completed"})
        for _ in range(60):
            if not rig.engine._delegations:
                break
            await asyncio.sleep(0.05)
        assert not rig.engine._delegations
        await asyncio.sleep(0.15)
        assert _busy(rig) == []


async def test_busy_searching_the_web(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine_module, "THINK_DELAY_S", 0.0)
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.send(_delegation_created())
        await conn.response_event({"type": "response.created"})
        await conn.response_event(
            {
                "type": "response.output_item.added",
                "item": {"type": "web_search_call", "id": "ws_1", "status": "in_progress"},
            }
        )
        await rig.rec.wait_for(lambda _: _busy(rig) == ["Thinking…", "Searching the web…"])
        assert rig.rec.of_type("busy")[-1]["kind"] == "search"
        await conn.response_event({"type": "response.web_search_call.completed", "item_id": "ws_1"})
        await rig.rec.wait_for(
            lambda _: _busy(rig) == ["Thinking…", "Searching the web…", "Thinking…"]
        )
        await conn.response_event({"type": "response.output_text.delta", "delta": "Found it."})
        await conn.response_event({"type": "response.completed"})
        await rig.rec.wait_for(lambda _: _busy(rig)[-1:] == ["off"])
        assert _busy(rig) == ["Thinking…", "Searching the web…", "Thinking…", "off"]


async def test_busy_is_forgotten_with_the_lost_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine_module, "DELEGATION_TIMEOUT_S", 0.3)
    monkeypatch.setattr(engine_module, "THINK_DELAY_S", 0.0)
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.send(_delegation_created())
        await rig.rec.wait_for(lambda _: _busy(rig) == ["Thinking…", "off"])
        assert not rig.engine._delegations


async def test_busy_is_repeated_when_the_avatar_reconnects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from websockets.asyncio.client import connect

    monkeypatch.setattr(engine_module, "THINK_DELAY_S", 0.0)
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.send(_delegation_created())
        await rig.rec.wait_for(lambda _: _busy(rig) == ["Thinking…"])
        # The avatar client reconnects: after its ``client_hello`` it sees the running wait again.
        async with connect(f"ws://127.0.0.1:{rig.hub.port}/") as client:
            assert json.loads(await asyncio.wait_for(client.recv(), 2.0))["type"] == "hello"
            again = Recorder(client)
            try:
                await client.send(
                    json.dumps({"type": "client_hello", "client": "unity", "games": []})
                )
                await again.wait_type("busy")
                assert again.of_type("busy") == [
                    {"type": "busy", "on": True, "kind": "think", "text": "Thinking…"}
                ]
            finally:
                await again.close()
        # With nothing in progress, a ``client_hello`` does not send ``busy``.
        await conn.response_event({"type": "response.created"})
        await conn.response_event({"type": "response.completed"})
        await rig.rec.wait_for(lambda _: _busy(rig)[-1:] == ["off"])
        count = len(rig.rec.of_type("busy"))
        await rig.unity({"type": "client_hello", "client": "unity", "games": []})
        await asyncio.sleep(0.1)
        assert len(rig.rec.of_type("busy")) == count


async def test_busy_is_not_left_hanging_when_the_session_is_lost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine_module, "THINK_DELAY_S", 0.0)
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await conn.send(_delegation_created())
        await conn.response_event({"type": "response.created"})
        await conn.response_event(
            {
                "type": "response.output_item.added",
                "item": {"type": "web_search_call", "id": "ws_1", "status": "in_progress"},
            }
        )
        await rig.rec.wait_for(lambda _: _busy(rig)[-1:] == ["Searching the web…"])
        # The session drops mid-search: the pill goes away with it.
        await conn.ws.close()
        await rig.rec.wait_for(lambda _: _busy(rig)[-1:] == ["off"])
        assert rig.engine.busy_board.keys == ()
        await rig.conn(2)
        await asyncio.sleep(0.1)
        assert _busy(rig)[-1:] == ["off"]
