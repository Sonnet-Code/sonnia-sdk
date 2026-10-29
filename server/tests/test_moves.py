"""Moves by voice (``play_animation``): the client catalog, the clip choice and the message."""

from __future__ import annotations

import random
from typing import Any

from sonia.actions.moves import MOVES, NO_MOVES, PLAY_ANIMATION, MoveCatalog, play_animation
from sonia.actions.registry import ActionRegistry
from sonia.types import ActionContext

#: A catalog like the one the avatar client sends.
CLIENT_CATALOG: dict[str, Any] = {
    "type": "animations",
    "animations": [
        {"clip": "Wave", "group": "greeting"},
        {"clip": "QuickAction_vibe", "group": "dance"},
        {"clip": "Peace", "group": "fourth_wall"},
        {"clip": "QuickAction_salute", "group": "fourth_wall"},
        {"clip": "QuickAction_twoThumbsUp", "group": "fourth_wall"},
        {"clip": "actions-0224-lookAtObject_Trimmed", "group": "thinking"},
        {"clip": "actions-presentItem_intro", "group": "present"},
    ],
}


class Sent:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def __call__(self, msg: dict[str, Any]) -> None:
        self.messages.append(msg)


def make_catalog(msg: dict[str, Any] | None = CLIENT_CATALOG) -> tuple[MoveCatalog, Sent]:
    sent = Sent()
    catalog = MoveCatalog(sent, rng=random.Random(1))
    if msg is not None:
        catalog.update(msg)
    return catalog, sent


def ctx_with(catalog: MoveCatalog | None) -> ActionContext:
    extra: dict[str, Any] = {} if catalog is None else {"moves": catalog}
    return ActionContext(camera=None, avatar=None, gallery_dir="", extra=extra)


def test_every_move_is_in_the_client_set() -> None:
    catalog, _ = make_catalog()
    assert catalog.available() == list(MOVES)


def test_moves_count_by_group_and_by_name() -> None:
    catalog, _ = make_catalog()
    assert catalog.clips_for("wave") == ["Wave"]
    assert catalog.clips_for("peace") == ["Peace"]
    assert catalog.clips_for("dance") == ["QuickAction_vibe"]
    assert catalog.clips_for("missing") == []


async def test_plays_the_whole_clip() -> None:
    catalog, sent = make_catalog()
    result = await play_animation(ctx_with(catalog), {"move": "dance"})
    assert result.text.startswith("Done")
    assert sent.messages == [{"type": "play_animation", "clip": "QuickAction_vibe", "whole": True}]


async def test_a_move_the_app_lacks_offers_the_available_ones() -> None:
    catalog, sent = make_catalog(
        {"type": "animations", "animations": [{"clip": "Peace", "group": "x"}]}
    )
    result = await play_animation(ctx_with(catalog), {"move": "dance"})
    assert "You do not have that move" in result.text
    assert "peace" in result.text
    assert sent.messages == []


async def test_without_a_client_catalog_she_does_not_move() -> None:
    catalog, sent = make_catalog(None)
    assert (await play_animation(ctx_with(catalog), {"move": "dance"})).text == NO_MOVES
    assert (await play_animation(ctx_with(None), {"move": "dance"})).text == NO_MOVES
    assert sent.messages == []


async def test_the_registry_rejects_an_invented_move() -> None:
    registry = ActionRegistry()
    registry.register(PLAY_ANIMATION)
    catalog, sent = make_catalog()
    result = await registry.execute("play_animation", {"move": "fly"}, ctx_with(catalog))
    assert result.text.startswith("Error")
    assert sent.messages == []
