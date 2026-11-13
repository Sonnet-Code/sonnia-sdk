"""The ``show_emotion`` action, the worked example of docs/actions.md, end to end.

One test per layer: the protocol message, the handler, the registry, the prompts,
the wiring from ``SHOW_EMOTION_ENABLED`` and a real WebSocket client.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from sonia import cli
from sonia.actions import build_default_registry
from sonia.actions.builtin import NO_AVATAR
from sonia.actions.emotion import DEFAULT_SECONDS, SHOW_EMOTION
from sonia.config import LiveSettings, Settings, VisionSettings, WSSettings
from sonia.live.prompts import build_live_instructions
from sonia.types import ActionContext
from sonia.ws import protocol as p
from sonia.ws.hub import Hub


@dataclass
class FakeAvatar:
    """Records what the action asks of the avatar."""

    emotions: list[tuple[str, float]] = field(default_factory=list)

    async def show_image(self, **kwargs: Any) -> None:
        raise AssertionError("show_emotion must not show images")

    async def hide_image(self) -> None:
        raise AssertionError("show_emotion must not hide images")

    async def show_emotion(self, emotion: str, seconds: float) -> None:
        self.emotions.append((emotion, seconds))


def _ctx(avatar: FakeAvatar | None) -> ActionContext:
    return ActionContext(camera=None, avatar=avatar, gallery_dir="/does/not/exist")


def _settings(tmp_path: Path, **values: Any) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        live=LiveSettings(api_key="test-key", backend_web_search=False),
        vision=VisionSettings(source="none"),
        assets_dir=str(tmp_path),
        **values,
    )


# -- protocol --------------------------------------------------------------


def test_the_message_holds_the_emotion_and_clamps_the_seconds() -> None:
    assert p.msg_show_emotion("joy", 2) == {
        "type": "show_emotion",
        "emotion": "joy",
        "seconds": 2.0,
    }
    assert p.msg_show_emotion("sad", 99)["seconds"] == p.EMOTION_MAX_SECONDS
    assert p.msg_show_emotion("surprise", 0)["seconds"] == 0.5
    with pytest.raises(ValueError, match="unknown emotion"):
        p.msg_show_emotion("anger")


def test_the_action_offers_exactly_the_emotions_of_the_protocol() -> None:
    assert SHOW_EMOTION.parameters["properties"]["emotion"]["enum"] == list(p.EMOTIONS)


# -- handler ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ({"emotion": "joy"}, ("joy", DEFAULT_SECONDS)),
        ({"emotion": "surprise", "seconds": 1.5}, ("surprise", 1.5)),
        ({"emotion": "sad", "seconds": 60}, ("sad", p.EMOTION_MAX_SECONDS)),
    ],
)
async def test_the_handler_shows_the_emotion(
    arguments: dict[str, Any], expected: tuple[str, float]
) -> None:
    avatar = FakeAvatar()
    result = await build_default_registry(include_emotion=True).execute(
        "show_emotion", arguments, _ctx(avatar)
    )
    assert avatar.emotions == [expected]
    assert result.text.startswith("Done:")


async def test_a_made_up_emotion_never_reaches_the_avatar() -> None:
    avatar = FakeAvatar()
    registry = build_default_registry(include_emotion=True)
    result = await registry.execute("show_emotion", {"emotion": "anger"}, _ctx(avatar))
    assert result.text.startswith("Error: invalid arguments")
    assert avatar.emotions == []


async def test_without_an_avatar_the_model_is_told() -> None:
    registry = build_default_registry(include_emotion=True)
    result = await registry.execute("show_emotion", {"emotion": "joy"}, _ctx(None))
    assert result.text == NO_AVATAR


# -- registry and prompts ----------------------------------------------------


def test_it_is_only_offered_when_enabled() -> None:
    assert "show_emotion" not in build_default_registry()
    tools = build_default_registry(include_emotion=True).to_responses_tools()
    assert [t["name"] for t in tools if t["name"] == "show_emotion"] == ["show_emotion"]


def test_the_voice_model_is_told_when_to_delegate_it(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    without = build_live_instructions(
        settings, registry=build_default_registry(include_look=False), gallery_ids=[]
    )
    with_it = build_live_instructions(
        settings,
        registry=build_default_registry(include_look=False, include_emotion=True),
        gallery_ids=[],
    )
    assert "show joy, sadness or surprise" not in without
    assert "- Face: show joy, sadness or surprise on your face" in with_it
    assert "You are asked to make a face" in with_it
    assert "showing an emotion on your face" in with_it  # the delegation reminder


@pytest.mark.parametrize("enabled", [False, True])
async def test_the_setting_decides_the_registry(tmp_path: Path, enabled: bool) -> None:
    components = cli.build_components(
        _settings(tmp_path, show_emotion_enabled=enabled), with_camera=False
    )
    try:
        assert ("show_emotion" in components.registry) is enabled
    finally:
        await components.close()


# -- end to end ------------------------------------------------------------


async def test_a_real_client_receives_the_message() -> None:
    from websockets.asyncio.client import connect

    hub = Hub(WSSettings(host="127.0.0.1", port=0), sample_rate=24_000)
    ctx = ActionContext(camera=None, avatar=hub, gallery_dir="/does/not/exist")
    registry = build_default_registry(include_emotion=True)
    async with hub, connect(f"ws://127.0.0.1:{hub.port}/") as client:
        # The hub registers the client before it sends hello.
        assert json.loads(await client.recv())["type"] == p.MSG_HELLO
        await registry.execute("show_emotion", {"emotion": "surprise", "seconds": 2}, ctx)
        async with asyncio.timeout(5):
            while True:
                msg = json.loads(await client.recv())
                if msg["type"] == p.MSG_SHOW_EMOTION:
                    break
    assert msg == {"type": "show_emotion", "emotion": "surprise", "seconds": 2.0}
