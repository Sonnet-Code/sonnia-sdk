"""The texts sent to the realtime model, its backend and the vision model, as snapshots.

Every instruction is compared with ``tests/snapshots/prompts_live.json``: changing a
prompt is always deliberate and reviewed in the diff (see ``tests/prompt_snapshots.py``
to rewrite the snapshots).

No network and no APIs: settings, registries and knowledge for testing.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

import sonia.live.engine as engine_module
from sonia.actions import build_default_registry
from sonia.actions.registry import ActionRegistry
from sonia.config import LiveSettings, LLMSettings, Settings, VisionSettings
from sonia.live.client import APPEND_MAX_CHARS
from sonia.live.prompts import build_session_config, gallery_note
from sonia.live.vision import VisionNarrator
from sonia.persona import DEFAULT_KNOWLEDGE_DIR, load_knowledge
from sonia.types import Frame, LLMEvent, Message, TextDelta, TurnDone
from tests.prompt_snapshots import assert_snapshot

DATA = Path(__file__).parent / "data"
KNOWLEDGE = DATA / "knowledge"

NOTES = "Today at five there is a robot demo in the main hall."
CLOCK = "Friday, May 9, 2025, 10:30 (10:30 in the morning)"


def snapshot_settings(
    *,
    vision_source: str = "opencv",
    on_turn_start: bool = False,
    interval: float = 0.0,
    web_search: bool = True,
    gallery_watch: float = 0.0,
    llm_url: str = "https://api.openai.com/v1",
    supports_vision: bool = True,
) -> Settings:
    """Fixed settings, without ``.env``: only what changes the instructions."""
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        live=LiveSettings(api_key="test-key", backend_web_search=web_search),
        llm=LLMSettings(
            base_url=llm_url,
            model="vision-model",
            api_key="key",
            supports_vision=supports_vision,
        ),
        vision=VisionSettings(
            source=vision_source,  # type: ignore[arg-type]
            on_turn_start=on_turn_start,
            interval_seconds=interval,
        ),
        gallery_watch_seconds=gallery_watch,
        assets_dir=str(DATA),
    )


def snapshot_registry(kind: str) -> ActionRegistry | None:
    if kind == "full":
        return build_default_registry(include_look=True, include_trivia=True)
    if kind == "basic":
        return build_default_registry(include_look=True)
    if kind == "no_look":
        return build_default_registry(include_look=False, include_trivia=True)
    assert kind == "none"
    return None


#: Representative settings: camera notes, look and none; search, gallery, notes and
#: clock, with and without.
CASES: dict[str, dict[str, Any]] = {
    "look_full": {
        "settings": {"gallery_watch": 5.0},
        "registry": "full",
        "gallery": ["team-photo", "map"],
        "notes": NOTES,
        "clock": CLOCK,
    },
    "notes_local_model": {
        "settings": {
            "on_turn_start": True,
            "llm_url": "http://localhost:1234/v1",
            "web_search": False,
        },
        "registry": "basic",
    },
    "notes_cloud_model": {
        "settings": {"interval": 30.0},
        "registry": "full",
        "notes": NOTES,
    },
    "no_camera": {
        "settings": {"vision_source": "none"},
        "registry": "no_look",
        "gallery": ["team-photo"],
        "clock": CLOCK,
    },
    "no_vision_model": {
        "settings": {"supports_vision": False, "gallery_watch": 5.0},
        "registry": "basic",
    },
    "client_camera_look": {
        "settings": {"vision_source": "unity"},
        "registry": "basic",
        "clock": CLOCK,
    },
    "no_actions": {
        "settings": {"web_search": False, "vision_source": "none"},
        "registry": "none",
    },
}


def session_instructions(case: dict[str, Any]) -> dict[str, str]:
    """The realtime model and backend instructions of one configuration."""
    config = build_session_config(
        snapshot_settings(**case["settings"]),
        registry=snapshot_registry(case["registry"]),
        gallery_ids=list(case.get("gallery", [])),
        knowledge_dir=case.get("knowledge", KNOWLEDGE),
        notes=case.get("notes", ""),
        clock_text=case.get("clock", ""),
    )
    return {
        "live": config["instructions"],
        "backend": config["delegation"]["responses"]["instructions"],
    }


SCENE = "Two people in blue T-shirts and a red cap."


class FakeVisionLLM:
    """Fake vision model: it records what it is asked."""

    def __init__(self) -> None:
        self.requests: list[list[Message]] = []

    async def stream(self, messages: list[Message]) -> AsyncIterator[LLMEvent]:
        self.requests.append(messages)
        yield TextDelta("Nobody.")
        yield TurnDone("Nobody.")


def narrator_messages() -> list[Message]:
    llm = FakeVisionLLM()
    asyncio.run(VisionNarrator(llm).describe(Frame(data=b"x")))
    (messages,) = llm.requests
    return messages


def request_prompts() -> dict[str, str]:
    """What goes in each request: vision, "look", the idle animation and engine notes."""
    e = engine_module
    system, user = narrator_messages()
    return {
        "vision/narrator": str(system["content"]),
        "vision/request": str(user["content"][0]["text"]),  # type: ignore[index]
        "vision/look": e.LOOK_IMAGE_TEXT,
        "moment/camera": e.moment_prompt(e.moment_focus("camera", SCENE)),
        "moment/invitation": e.moment_prompt(e.moment_focus("invitation")),
        "idle_line": e.showcase_prompt("Come closer, I don't bite!"),
        "typed_text": e.TEXT_INPUT_TEMPLATE.format(text="Where are the restrooms?"),
        "interruption": e.INTERRUPT_TEXT,
        "announcement": e.ANNOUNCE_TEMPLATE.format(text="The 11 o'clock talk moves to room 2."),
        "notes": e.NOTES_TEMPLATE.format(text="Raffle at five."),
        "notes_cleared": e.NOTES_CLEARED_TEXT,
        "delegation_failed": e.DELEGATION_FAILED_TEXT,
        "gallery": gallery_note(["new"], ["old"], ["logo", "new"], max_chars=1200),
    }


@pytest.mark.parametrize("name", sorted(CASES))
def test_session_instructions_match_the_snapshot(name: str) -> None:
    assert_snapshot(f"prompts_live_{name}", session_instructions(CASES[name]))


def test_request_prompts_match_the_snapshot() -> None:
    assert_snapshot("prompts_live_requests", request_prompts())


def test_the_knowledge_skips_the_readme_and_keeps_the_order() -> None:
    text = load_knowledge(KNOWLEDGE)
    assert text.startswith("# The place")
    assert "# Activities" in text and "README" not in text
    # Braces in the knowledge are kept as they are.
    assert "{like_this}" in session_instructions(CASES["look_full"])["live"]


def test_the_shipped_knowledge_loads() -> None:
    text = load_knowledge(DEFAULT_KNOWLEDGE_DIR)
    assert text and "Sonia" in text


#: What Sonnia must not know about her stack: she explains it without brands.
_BRANDS = ("gpt", "openai", "unity", "genies", "luna", "darwin", "windows", "macos")


@pytest.mark.parametrize("name", sorted(CASES))
def test_sonnia_does_not_know_the_brands_of_her_stack(name: str) -> None:
    texts = session_instructions({**CASES[name], "knowledge": DEFAULT_KNOWLEDGE_DIR})
    for part, text in texts.items():
        found = [b for b in _BRANDS if re.search(rf"\b{b}\b", text, re.IGNORECASE)]
        assert not found, f"{part} names {found}"


def test_the_delegation_reminder_is_the_last_thing_the_model_reads() -> None:
    live = session_instructions(CASES["look_full"])["live"]
    reminder = live.rfind("BEFORE EVERY ANSWER, REMEMBER")
    assert reminder > live.rfind("YOUR STACK RIGHT NOW") > 0
    for heading in ("Backchannel policy:", "Interruption policy:", "Delegation policy:"):
        assert heading in live


def test_the_fixed_part_of_each_append_leaves_room_for_its_text() -> None:
    """Appends are cut at ``APPEND_MAX_CHARS``: the fixed part must leave room for the text."""
    e = engine_module
    for template in (
        e.MOMENT_TEMPLATE.format(focus=e.MOMENT_FOCUS["camera"]),
        e.SHOWCASE_TEMPLATE,
        e.TEXT_INPUT_TEMPLATE,
        e.ANNOUNCE_TEMPLATE,
        e.NOTES_TEMPLATE,
    ):
        assert len(template) < APPEND_MAX_CHARS // 2, template
