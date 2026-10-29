"""Control panel tests: modes, actions, status, security and the voice cache.

No network and no key: GPT-Live is the fake server of ``test_live`` and the panel
really starts on a free port of 127.0.0.1.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import wave
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest

from sonia.actions import build_default_registry
from sonia.config import PanelSettings, Settings
from sonia.live.engine import LiveEngine
from sonia.live.voicecache import VoiceCache
from sonia.panel.control import (
    DEFAULT_AWAY_MESSAGE,
    PanelControl,
    PanelState,
    _Material,
    merge_tuning,
)
from sonia.panel.logs import LogBuffer
from sonia.panel.server import PanelServer
from sonia.ws.hub import Hub
from tests.helpers import Recorder
from tests.test_live import (
    RATE,
    FakeConn,
    FakeLiveServer,
    make_settings,
    pcm,
    pcm_level,
    running,
    wait_until,
)

GREETING = "Hi there, welcome!"
SONG = "La la la, come and dance!"


def write_clip(cache: VoiceCache, text: str, samples: int = 4_800) -> bytes:
    """Leaves a "recorded" line in the cache without going through GPT-Live."""
    data = pcm(samples, 321)
    path = cache.path_for(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(data)
    return data


def panel_settings(tmp_path: Path, **overrides: Any) -> Settings:
    settings = make_settings(tmp_path, **overrides)
    settings.panel = PanelSettings(
        port=0,
        state_file=str(tmp_path / "cache" / "panel_state.json"),
        voice_cache_dir=str(tmp_path / "cache" / "voice"),
        greeter_interval_min_seconds=60,
        greeter_interval_max_seconds=60,
    )
    return settings


@dataclass
class PanelRig:
    settings: Settings
    server: FakeLiveServer
    engine: LiveEngine
    control: PanelControl
    hub: Hub
    rec: Recorder
    cache: VoiceCache
    client: Any

    async def conn(self, count: int = 1) -> FakeConn:
        conn = await self.server.wait_conn(count)
        await wait_until(lambda: self.engine.session_id == f"sess_{count}")
        return conn


@contextlib.asynccontextmanager
async def make_panel_rig(
    tmp_path: Path,
    *,
    state: PanelState | None = None,
    material: _Material | None = None,
    **overrides: Any,
) -> AsyncIterator[PanelRig]:
    """Real panel, engine and hub against the fake GPT-Live, with a client acting as the
    avatar client."""
    from websockets.asyncio.client import connect

    settings = panel_settings(tmp_path, **overrides)
    if state is not None:
        state.save(Path(settings.panel.state_file))
    server = FakeLiveServer()
    registry = build_default_registry(include_look=False)
    hub = Hub(settings.ws, sample_rate=RATE)
    async with running(server) as live_connect, hub:
        # If something records voices (the warm-up after 20 s, "say" in greeter mode),
        # it does so against the fake GPT-Live: not a single connection to OpenAI.
        cache = VoiceCache(settings.panel.voice_cache_dir, settings.live, connect=live_connect)
        engine = LiveEngine(
            settings,
            hub=hub,
            registry=registry,
            connect=live_connect,
            knowledge_dir=tmp_path,
            voice_cache=cache,
            tick_s=0.02,
        )
        control = PanelControl(
            settings,
            hub=hub,
            registry=registry,
            engine=engine,
            voice_cache=cache,
            material=material or _Material(greetings=[GREETING], phrases=[], songs=[SONG]),
        )
        async with connect(f"ws://127.0.0.1:{hub.port}/") as client:
            rec = Recorder(client)
            await control.start()
            task = asyncio.create_task(engine.run())
            try:
                yield PanelRig(settings, server, engine, control, hub, rec, cache, client)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                await control.stop()
                await rec.close()


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------


async def test_away_closes_gpt_live_and_leaves_the_sign(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        conn = await rig.conn()
        ok, _ = await rig.control.act("set_away_message", {"text": "Back at 3"})
        assert ok
        ok, message = await rig.control.act("set_mode", {"mode": "away"})
        assert ok and "sign" in message
        await conn.wait_type("session.close")
        await rig.rec.wait_type("presence", count=2)
        presence = rig.rec.of_type("presence")[-1]
        assert presence == {"type": "presence", "present": False, "message": "Back at 3"}
        assert rig.rec.of_type("hide_image")
        await wait_until(lambda: not rig.engine.connected)
        await asyncio.sleep(0.3)
        assert rig.server.attempts == 1  # off, it does not reconnect: no cost
        status = rig.control.status()
        assert status["mode"] == "away"
        assert status["health"]["internet"]["ok"] is None
        # And back: Sonnia comes in and a new session opens.
        await rig.control.act("set_mode", {"mode": "conversation"})
        await rig.conn(2)
        assert rig.rec.of_type("presence")[-1]["present"] is True


async def test_greeter_plays_recorded_lines_without_gpt_live(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        await rig.conn()
        clip = write_clip(rig.cache, GREETING)
        await rig.control.act("set_mode", {"mode": "greeter"})
        await wait_until(lambda: not rig.engine.connected)
        ok, message = await rig.control.act("greet", {})
        assert ok and GREETING in message
        await rig.rec.wait_type("speech_end")
        assert rig.rec.of_type("attention")[-1]["category"] == "greeting"
        start = rig.rec.of_type("speech_start")[-1]
        assert start["ambient"] is True and start["text"] == GREETING
        assert b"".join(f[3] for f in rig.rec.audio(start["utterance_id"])) == clip
        assert "speaking" not in rig.rec.states()
        assert rig.server.attempts == 1


async def test_gpt_live_does_not_hear_the_recorded_line_while_it_plays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GPT-Live did not say the recorded line: if it heard it on the speakers, it would answer it."""
    import numpy as np

    monkeypatch.setattr("sonia.live.engine.CLIP_ECHO_TAIL_S", 0.05)
    loud = np.full(768, 0.5, dtype=np.float32)
    async with make_panel_rig(tmp_path) as rig:
        conn = await rig.conn()
        write_clip(rig.cache, GREETING)
        ok, _ = await rig.control.act("greet", {})
        assert ok
        await rig.rec.wait_type("speech_end")
        await rig.engine.push_mic(loud)
        await conn.wait_type("session.input_audio.append")
        assert pcm_level(conn.audio_in()[-1]) < 0.01
        # The client confirms it finished playing: after the tail, GPT-Live hears again.
        rig.engine.notify_playback_done(rig.rec.of_type("speech_start")[-1]["utterance_id"])
        await asyncio.sleep(0.1)
        await rig.engine.push_mic(loud)
        await conn.wait_type("session.input_audio.append", count=2)
        assert pcm_level(conn.audio_in()[-1]) == pytest.approx(0.5, rel=0.01)


async def test_without_a_recorded_line_it_greets_with_the_gesture_only(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        await rig.control.act("set_mode", {"mode": "greeter"})
        ok, message = await rig.control.act("greet", {})
        assert ok and "Prepare voices" in message
        await rig.rec.wait_type("attention")
        assert not rig.rec.of_type("speech_start")


async def test_the_saved_mode_applies_at_startup_without_connecting(tmp_path: Path) -> None:
    state = PanelState(mode="away", away_message="At a talk", volume=0.6)
    async with make_panel_rig(tmp_path, state=state) as rig:
        await asyncio.sleep(0.3)
        assert rig.server.attempts == 0
        assert rig.control.status()["mode"] == "away"
        # A screen that connects now gets the sign and the volume after hello.
        from websockets.asyncio.client import connect

        async with connect(f"ws://127.0.0.1:{rig.hub.port}/") as late:
            # After hello all the sticky messages arrive; the sign, the last one.
            kinds = [json.loads(await late.recv())]
            while kinds[-1]["type"] != "presence" and len(kinds) < 10:
                kinds.append(json.loads(await late.recv()))
        assert kinds[0]["type"] == "hello"
        assert {"type": "set_volume", "value": 0.6} in kinds
        assert {"type": "presence", "present": False, "message": "At a talk"} in kinds


async def test_panel_changes_are_saved(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        await rig.conn()
        await rig.control.act("set_volume", {"value": 3})
        await rig.control.act("set_mic_gate", {"value": 0.05})
        await rig.control.act("showcase", {"enabled": False})
        await rig.control.act("set_mode", {"mode": "greeter"})
    saved = PanelState.load(tmp_path / "cache" / "panel_state.json")
    assert saved.mode == "greeter"
    assert saved.volume == 1.5  # clamped to the maximum
    assert saved.mic_gate == 0.05
    assert saved.showcase is False
    assert saved.away_message == DEFAULT_AWAY_MESSAGE


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


async def test_todays_notes_reach_the_session_and_the_next_ones(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        conn = await rig.conn()
        ok, _ = await rig.control.act("set_notes", {"text": "The AI talk is in room B."})
        assert ok
        await conn.wait_type("session.instructions.append")
        assert "room B" in conn.of_type("session.instructions.append")[0]["content"]
        await rig.control.act("restart", {})
        conn2 = await rig.conn(2)
        assert "room B" in conn2.start["session"]["instructions"]
        assert "room B" in conn2.start["session"]["delegation"]["responses"]["instructions"]


async def test_say_in_conversation_goes_as_commentary(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        conn = await rig.conn()
        ok, _ = await rig.control.act("say", {"text": "Lunch is at one."})
        assert ok
        await conn.wait_type("session.commentary.append")
        assert "Lunch" in conn.of_type("session.commentary.append")[0]["content"]


async def test_malformed_actions_break_nothing(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        assert (await rig.control.act("fly", {}))[0] is False
        assert (await rig.control.act("set_mode", {"mode": "party"}))[0] is False
        assert (await rig.control.act("say", {"text": "  "}))[0] is False
        assert (await rig.control.act("mute", {"muted": "yes"}))[0] is False
        assert (await rig.control.act("set_voice", {"voice": "robot"}))[0] is False
        await rig.control.act("set_mode", {"mode": "away"})
        ok, message = await rig.control.act("gesture", {"category": "dance"})
        assert not ok and "away" in message


async def test_animations_with_the_list_the_client_sends(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        ok, message = await rig.control.act("animation", {"clip": "Dance_HipHop"})
        assert not ok and "list" in message
        await rig.client.send(
            json.dumps(
                {
                    "type": "animations",
                    "animations": [
                        {"clip": "Dance_HipHop", "group": "dance"},
                        {"clip": "Dance_HipHop", "group": "soft"},  # repeated: out
                        {"clip": "Shrug"},  # no group: out
                        "garbage",
                        {"clip": "ListeningNod", "group": "nod"},
                    ],
                }
            )
        )
        await wait_until(lambda: bool(rig.control.status()["animations"]))
        assert rig.control.status()["animations"] == [
            {"clip": "Dance_HipHop", "group": "dance"},
            {"clip": "ListeningNod", "group": "nod"},
        ]
        assert "animations" in rig.control.status()["capabilities"]
        ok, message = await rig.control.act("animation", {"clip": "Dance_HipHop"})
        assert ok and "Dance_HipHop" in message
        await rig.rec.wait_type("play_animation")
        assert rig.rec.of_type("play_animation")[-1] == {
            "type": "play_animation",
            "clip": "Dance_HipHop",
        }
        ok, message = await rig.control.act("animation", {"clip": "Moonwalk"})
        assert not ok and "not in the avatar app" in message
        await rig.control.act("set_mode", {"mode": "away"})
        ok, message = await rig.control.act("animation", {"clip": "Dance_HipHop"})
        assert not ok and "away" in message
        assert len(rig.rec.of_type("play_animation")) == 1


async def test_disabled_animations_are_saved_and_reach_the_client(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        await rig.rec.wait_type("set_disabled_animations")
        assert rig.rec.of_type("set_disabled_animations")[-1]["clips"] == []
        ok, message = await rig.control.act(
            "set_animation_enabled", {"clip": "Dance_Gangnam", "enabled": False}
        )
        assert ok and "no longer" in message
        await rig.rec.wait_type("set_disabled_animations", count=2)
        assert rig.rec.of_type("set_disabled_animations")[-1]["clips"] == ["Dance_Gangnam"]
        assert rig.control.status()["disabled_animations"] == ["Dance_Gangnam"]
        assert "animation_toggles" in rig.control.status()["capabilities"]
        # With the client list, what does not exist is rejected.
        await rig.client.send(
            json.dumps(
                {"type": "animations", "animations": [{"clip": "Dance_Gangnam", "group": "dance"}]}
            )
        )
        await wait_until(lambda: bool(rig.control.status()["animations"]))
        ok, _ = await rig.control.act(
            "set_animation_enabled", {"clip": "Moonwalk", "enabled": False}
        )
        assert not ok
        saved = PanelState.load(Path(rig.settings.panel.state_file))
        assert saved.disabled_animations == ["Dance_Gangnam"]
        ok, _ = await rig.control.act(
            "set_animation_enabled", {"clip": "Dance_Gangnam", "enabled": True}
        )
        assert ok and rig.control.status()["disabled_animations"] == []


async def test_debug_mode_turns_off_gpt_live_and_the_greetings(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        conn = await rig.conn()
        ok, message = await rig.control.act("set_debug", {"enabled": True})
        assert ok and "still" in message
        await conn.wait_type("session.close")
        await wait_until(lambda: not rig.engine.connected)
        assert rig.rec.of_type("set_debug")[-1] == {"type": "set_debug", "enabled": True}
        status = rig.control.status()
        assert status["debug"] is True and status["health"]["internet"]["ok"] is None
        # "Conversing" does not open GPT-Live while debug mode lasts.
        await rig.control.act("set_mode", {"mode": "greeter"})
        await rig.control.act("set_mode", {"mode": "conversation"})
        await asyncio.sleep(0.3)
        assert rig.server.attempts == 1
        # Nor the greeter loop: even when it is time to greet, it does not.
        write_clip(rig.cache, GREETING)
        await rig.control.act("set_mode", {"mode": "greeter"})
        rig.control._next_greet_at = 0.0
        await asyncio.sleep(1.3)
        assert not rig.rec.of_type("speech_start")
        # The panel buttons do work.
        ok, _ = await rig.control.act("greet", {})
        assert ok
        await rig.rec.wait_type("speech_start")
        # When it is turned off things go back to normal: "Conversing" opens a session.
        await rig.control.act("set_mode", {"mode": "conversation"})
        ok, _ = await rig.control.act("set_debug", {"enabled": False})
        assert ok
        await rig.conn(2)
        assert rig.rec.of_type("set_debug")[-1]["enabled"] is False


async def test_the_screen_knows_whether_sonnia_can_talk(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        await rig.conn()

        def last() -> dict[str, object]:
            return rig.rec.of_type("stage_mode")[-1]

        await rig.rec.wait_type("stage_mode")
        assert last() == {"type": "stage_mode", "mode": "conversation", "talk": True}
        await rig.control.act("set_mode", {"mode": "greeter"})
        await rig.rec.wait_type("stage_mode", count=2)
        assert last() == {"type": "stage_mode", "mode": "greeter", "talk": False}
        await rig.control.act("set_mode", {"mode": "away"})
        await rig.rec.wait_type("stage_mode", count=3)
        assert last() == {"type": "stage_mode", "mode": "away", "talk": False}
        await rig.control.act("set_mode", {"mode": "conversation"})
        await rig.rec.wait_type("stage_mode", count=4)
        assert last() == {"type": "stage_mode", "mode": "conversation", "talk": True}
        # With debug mode GPT-Live turns off: the screen stops inviting people to talk.
        await rig.control.act("set_debug", {"enabled": True})
        await rig.rec.wait_type("stage_mode", count=5)
        assert last() == {"type": "stage_mode", "mode": "conversation", "talk": False}
        # And it is sticky: a client that connects now gets it after hello.
        assert rig.hub.sticky("stage_mode") == last()


async def test_the_status_says_which_animation_plays(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        assert rig.control.status()["current_animation"] is None
        await rig.client.send(json.dumps({"type": "animation_playing", "clip": "Dance_Jazz"}))
        await wait_until(lambda: rig.control.status()["current_animation"] == "Dance_Jazz")
        await rig.client.send(json.dumps({"type": "animation_playing", "clip": None}))
        await wait_until(lambda: rig.control.status()["current_animation"] is None)


async def test_subtitles_turn_off_and_are_remembered(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        await rig.rec.wait_type("set_subtitles")
        assert rig.rec.of_type("set_subtitles")[-1]["enabled"] is True
        ok, message = await rig.control.act("set_subtitles", {"enabled": False})
        assert ok and "hidden" in message
        await rig.rec.wait_type("set_subtitles", count=2)
        assert rig.rec.of_type("set_subtitles")[-1] == {"type": "set_subtitles", "enabled": False}
        assert rig.control.status()["subtitles"] is False
        ok, _ = await rig.control.act("set_subtitles", {"enabled": "no"})
        assert not ok
    # After a restart what was saved applies, also to clients that connect later.
    state = PanelState.load(tmp_path / "cache" / "panel_state.json")
    assert state.subtitles is False
    async with make_panel_rig(tmp_path, state=state) as rig:
        await rig.rec.wait_type("set_subtitles")
        assert rig.rec.of_type("set_subtitles")[-1]["enabled"] is False


async def test_developer_tunes_mouth_and_camera_and_reaches_the_client(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        await rig.rec.wait_type("set_tuning")
        first = rig.rec.of_type("set_tuning")[-1]
        assert first["mouth"] == {"open": 1.0, "jaw": 1.0, "closure": 1.0, "speed": 1.0}
        assert first["camera"]["zoom"] == 1.0 and first["camera"]["height"] == 0.0
        assert first["idle"] == {"breath": 1.0, "accents": 1.0, "speed": 1.0}
        ok, _ = await rig.control.act(
            "set_tuning", {"mouth": {"open": 1.4, "nose": 2}, "camera": {"height": 9, "zoom": 1.2}}
        )
        assert ok
        await rig.rec.wait_type("set_tuning", count=2)
        sent = rig.rec.of_type("set_tuning")[-1]
        assert sent["mouth"] == {"open": 1.4, "jaw": 1.0, "closure": 1.0, "speed": 1.0}
        assert sent["camera"]["height"] == 0.5  # clamped to the maximum
        assert sent["camera"]["zoom"] == 1.2
        # Resetting the camera does not touch the mouth.
        ok, _ = await rig.control.act("reset_tuning", {"part": "camera"})
        assert ok
        tuning = rig.control.status()["tuning"]
        assert tuning["camera"]["height"] == 0.0 and tuning["mouth"]["open"] == 1.4
        for bad in ({}, {"mouth": 3}, {"camera": "high"}, {"idle": [1]}):
            ok, _ = await rig.control.act("set_tuning", bad)
            assert not ok
        ok, _ = await rig.control.act("reset_tuning", {"part": "feet"})
        assert not ok
    # It is remembered.
    state = PanelState.load(tmp_path / "cache" / "panel_state.json")
    assert state.tuning["mouth"]["open"] == 1.4
    async with make_panel_rig(tmp_path, state=state) as rig:
        await rig.rec.wait_type("set_tuning")
        assert rig.rec.of_type("set_tuning")[-1]["mouth"]["open"] == 1.4


AVATAR = json.dumps({"JsonVersion": "2-0-0", "equippedAssetIds": ["AvatarBase/rec1"]})


async def test_the_avatar_definition_is_validated_saved_and_sticky(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        await rig.rec.wait_type("set_avatar")
        assert rig.rec.of_type("set_avatar")[-1] == {"type": "set_avatar", "definition": None}
        assert rig.control.status()["avatar"] == {"custom": False}
        for bad in ("not json", json.dumps({"JsonVersion": "2-0-0"}), 3):
            ok, _ = await rig.control.act("set_avatar", {"definition": bad})
            assert not ok
        ok, _ = await rig.control.act("set_avatar", {"definition": AVATAR})
        assert ok
        await rig.rec.wait_type("set_avatar", count=2)
        assert rig.rec.of_type("set_avatar")[-1]["definition"] == AVATAR
        assert rig.hub.sticky("avatar") == {"type": "set_avatar", "definition": AVATAR}
        assert rig.control.status()["avatar"] == {"custom": True}
    state = PanelState.load(tmp_path / "cache" / "panel_state.json")
    assert state.avatar == AVATAR
    async with make_panel_rig(tmp_path, state=state) as rig:
        await rig.rec.wait_type("set_avatar")
        assert rig.rec.of_type("set_avatar")[-1]["definition"] == AVATAR
        ok, message = await rig.control.act("set_avatar", {"definition": None})
        assert ok and "default" in message
        await rig.rec.wait_type("set_avatar", count=2)
        assert rig.rec.of_type("set_avatar")[-1]["definition"] is None


async def test_developer_tunes_the_idle_motion(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        await rig.rec.wait_type("set_tuning")
        ok, _ = await rig.control.act(
            "set_tuning", {"idle": {"breath": 1.6, "accents": 5, "speed": 0.1}}
        )
        assert ok
        await rig.rec.wait_type("set_tuning", count=2)
        sent = rig.rec.of_type("set_tuning")[-1]
        # Clamped to its limits; mouth and camera stay as they were.
        assert sent["idle"] == {"breath": 1.6, "accents": 2.0, "speed": 0.5}
        assert sent["mouth"]["open"] == 1.0 and sent["camera"]["zoom"] == 1.0
        ok, _ = await rig.control.act("set_tuning", {"mouth": {"open": 1.2}})
        assert ok
        # Resetting the motion does not touch the mouth.
        ok, _ = await rig.control.act("reset_tuning", {"part": "idle"})
        assert ok
        tuning = rig.control.status()["tuning"]
        assert tuning["idle"] == {"breath": 1.0, "accents": 1.0, "speed": 1.0}
        assert tuning["mouth"]["open"] == 1.2


async def test_a_saved_tuning_without_idle_gets_its_defaults(tmp_path: Path) -> None:
    # Saved by an older orchestrator: mouth and camera, no "idle".
    path = tmp_path / "panel_state.json"
    path.write_text(
        json.dumps({"tuning": {"mouth": {"open": 1.3}, "camera": {"zoom": 1.1}}}), encoding="utf-8"
    )
    state = PanelState.load(path)
    assert state.tuning["mouth"]["open"] == 1.3
    assert state.tuning["idle"] == {"breath": 1.0, "accents": 1.0, "speed": 1.0}
    assert merge_tuning({"mouth": {"open": 1.3}})["idle"]["speed"] == 1.0


async def test_an_old_panel_state_loads_with_the_new_defaults(tmp_path: Path) -> None:
    path = tmp_path / "panel_state.json"
    path.write_text(
        json.dumps({"mode": "greeter", "volume": 0.7, "unknown": 1, "avatar": "bad"}),
        encoding="utf-8",
    )
    state = PanelState.load(path)
    assert state.mode == "greeter" and state.volume == 0.7 and state.subtitles is True
    assert state.disabled_animations == []
    assert state.tuning["camera"]["zoom"] == 1.0
    assert state.avatar is None


async def test_muting_the_microphone_sends_silence(tmp_path: Path) -> None:
    import numpy as np

    async with make_panel_rig(tmp_path) as rig:
        conn = await rig.conn()
        await rig.control.act("mute", {"muted": True})
        await rig.engine.push_mic(np.full(768, 0.5, dtype=np.float32))
        await conn.wait_type("session.input_audio.append")
        assert pcm_level(conn.audio_in()[-1]) < 0.01
        health = rig.control.status()["health"]["mic"]
        assert health["ok"] is False and health["muted"] is True


# ---------------------------------------------------------------------------
# Web server
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def running_panel(rig: PanelRig) -> AsyncIterator[tuple[str, PanelServer]]:
    logs = LogBuffer()
    server = PanelServer(rig.settings.panel, rig.control, rig.hub, logs)
    await server.start()
    try:
        yield f"127.0.0.1:{server.port}", server
    finally:
        await server.stop()


async def test_the_server_serves_status_gallery_and_actions(tmp_path: Path) -> None:
    (tmp_path / "gallery").mkdir(exist_ok=True)
    (tmp_path / "gallery" / "logo-team.png").write_bytes(b"\x89PNG-logo")
    async with make_panel_rig(tmp_path) as rig, running_panel(rig) as (host, _):
        await rig.conn()
        async with httpx.AsyncClient(base_url=f"http://{host}") as http:
            status = (await http.get("/api/status")).json()
            assert status["mode"] == "conversation"
            assert "modes" in status["capabilities"]
            page = await http.get("/")
            assert page.status_code == 200
            assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
            gallery = (await http.get("/api/gallery")).json()
            assert gallery == {"images": [{"id": "logo-team", "url": "/api/gallery/logo-team"}]}
            assert (await http.get("/api/gallery/logo-team")).content == b"\x89PNG-logo"

            body = {"action": "show_image", "image_id": "logo-team"}
            without_header = await http.post("/api/action", json=body)
            assert without_header.status_code == 403
            ok = await http.post("/api/action", json=body, headers={"X-Sonia-Panel": "1"})
            assert ok.status_code == 200 and ok.json()["ok"] is True
            assert (await http.get("/api/status")).json()["image"]["id"] == "logo-team"
            bad = await http.post(
                "/api/action", json={"action": "fly"}, headers={"X-Sonia-Panel": "1"}
            )
            assert bad.status_code == 400


async def test_the_websocket_sends_history_status_and_messages(tmp_path: Path) -> None:
    from websockets.asyncio.client import connect
    from websockets.exceptions import InvalidStatus

    async with make_panel_rig(tmp_path) as rig, running_panel(rig) as (host, _):
        conn = await rig.conn()
        with pytest.raises(InvalidStatus):
            async with connect(f"ws://{host}/api/events", origin="https://other-site.example"):  # type: ignore[arg-type]
                pass
        async with connect(f"ws://{host}/api/events", origin=f"http://{host}") as ws:  # type: ignore[arg-type]
            first = json.loads(await ws.recv())
            assert first["type"] == "history" and isinstance(first["logs"], list)
            second = json.loads(await ws.recv())
            assert second["type"] == "status" and second["status"]["mode"] == "conversation"
            await conn.hear("Hi Sonia")
            async with asyncio.timeout(3):
                while True:
                    item = json.loads(await ws.recv())
                    message = item.get("message") or {}
                    if message.get("type") == "transcript" and message.get("role") == "user":
                        assert "Hi Sonnia" in message["text"]
                        break


# ---------------------------------------------------------------------------
# Voice cache
# ---------------------------------------------------------------------------


async def test_the_cache_records_with_gpt_live_and_splits_by_voice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sonia.live.oneshot as oneshot

    monkeypatch.setattr(oneshot, "SAY_END_GAP_S", 0.2)
    server = FakeLiveServer()

    async def react(conn: FakeConn, message: dict[str, Any]) -> None:
        if message["type"] == "session.commentary.append":
            await conn.audio(pcm(12_000, 900))

    server.on_message = react
    settings = panel_settings(tmp_path)
    async with running(server) as connect:
        cache = VoiceCache(settings.panel.voice_cache_dir, settings.live, connect=connect)
        done = await cache.prepare([GREETING, GREETING, "  ", SONG])
    assert done == 2
    assert cache.get(GREETING) == pcm(12_000, 900)
    assert cache.count_ready([GREETING, SONG]) == 2
    settings.live.voice = "cedar"
    assert cache.get(GREETING) is None  # another voice, another recording
    assert cache.missing([GREETING]) == [GREETING]


async def test_the_cache_stops_recording_after_two_failures_in_a_row(tmp_path: Path) -> None:
    server = FakeLiveServer(reject=True)
    settings = panel_settings(tmp_path)
    async with running(server) as connect:
        cache = VoiceCache(settings.panel.voice_cache_dir, settings.live, connect=connect)
        done = await cache.prepare(["one", "two", "three", "four"])
    assert done == 0
    assert server.attempts == 2
    assert "model_not_found" in cache.last_error


async def test_todays_usage_survives_a_restart_and_starts_from_zero_each_day(
    tmp_path: Path,
) -> None:
    today = time.strftime("%Y-%m-%d")
    state_today = PanelState(usage_date=today, usage_seconds=600.0)
    async with make_panel_rig(tmp_path, state=state_today) as rig:
        await rig.conn()
        usage = rig.control.status()["usage"]
        assert usage["live_seconds"] >= 600.0
        assert usage["cost_usd"] == pytest.approx(0.5, abs=0.02)
    saved = PanelState.load(tmp_path / "cache" / "panel_state.json")
    assert saved.usage_date == today and saved.usage_seconds >= 600.0

    yesterday = PanelState(usage_date="2000-01-02", usage_seconds=9_999.0)
    (tmp_path / "other").mkdir()
    async with make_panel_rig(tmp_path / "other", state=yesterday) as rig:
        assert rig.control.status()["usage"]["live_seconds"] < 60.0


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


async def test_trivia_from_the_panel(tmp_path: Path) -> None:
    (tmp_path / "trivia").mkdir()
    (tmp_path / "trivia" / "questions.md").write_text(TRIVIA_BANK, encoding="utf-8")
    async with make_panel_rig(tmp_path) as rig:
        rig.settings.trivia.questions = 2
        rig.settings.trivia.reveal_seconds = 30.0
        conn = await rig.conn()
        assert "trivia" in rig.control.capabilities
        assert rig.control.status()["trivia"]["available"] is True

        ok, message = await rig.control.act("trivia_start", {})
        assert ok, message
        await rig.rec.wait_type("trivia_question")
        await conn.wait_type("session.commentary.append")
        question = rig.rec.of_type("trivia_question")[0]
        assert question["question"] in conn.of_type("session.commentary.append")[-1]["content"]
        status = rig.control.status()["trivia"]
        assert (
            status["active"] and status["number"] == 1 and status["options"] == question["options"]
        )

        ok, message = await rig.control.act("trivia_answer", {"option": "Z"})
        assert not ok
        ok, message = await rig.control.act("trivia_answer", {"option": "B"})
        assert ok
        await rig.rec.wait_type("trivia_answer")
        assert rig.rec.of_type("trivia_answer")[0]["chosen"] == 1
        await conn.wait_type("session.commentary.append", count=2)
        assert "by the operator" in conn.of_type("session.commentary.append")[-1]["content"]

        ok, message = await rig.control.act("trivia_restart", {})
        assert ok and "first question" in message
        await rig.rec.wait_type("trivia_end")
        assert rig.rec.of_type("trivia_end")[0]["reason"] == "cancelled"
        assert rig.control.status()["trivia"]["number"] == 1
        rig.rec.messages.clear()

        # Changing mode closes GPT-Live and the game is cancelled.
        await rig.control.act("set_mode", {"mode": "greeter"})
        await rig.rec.wait_type("trivia_end")
        assert rig.rec.of_type("trivia_end")[0]["reason"] == "cancelled"
        ok, message = await rig.control.act("trivia_start", {})
        assert not ok and "Conversing" in message
        ok, message = await rig.control.act("trivia_stop", {})
        assert ok and "There is no trivia" in message


async def test_without_a_bank_the_trivia_is_not_available(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        await rig.conn()
        assert rig.control.status()["trivia"]["available"] is False
        ok, message = await rig.control.act("trivia_start", {})
        assert not ok and "questions" in message
