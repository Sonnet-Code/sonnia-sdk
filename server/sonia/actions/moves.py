"""``play_animation`` action: dances and gestures people ask Sonnia for out loud.

The realtime model delegates it when the user asks her to dance, wave, make the
peace sign... The backend picks a move from a fixed list of names (:data:`MOVES`)
and the clip is looked up here in the catalog the avatar client sends when it
connects (``animations`` message, the same one the panel uses), so only what the
app has can play. It goes to the client as ``play_animation`` with
``whole: true``: the clip plays to the end even if Sonnia talks meanwhile
(otherwise the "here I go!" would cut it when switching to ``speaking``).

The engine leaves the catalog in ``ctx.extra["moves"]``.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sonia.types import ActionContext, ActionResult, ActionSpec
from sonia.ws import protocol as p

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Move:
    """A move that can be requested: which clips of the client catalog do it."""

    #: What it is, for the backend.
    description: str
    #: Catalog groups whose clips all count (``dance``, ``greeting``...).
    groups: tuple[str, ...] = ()
    #: Specific clips, by name.
    clips: tuple[str, ...] = ()


#: Moves that can be requested out loud. If the avatar client has none of their
#: clips, that move is not available.
MOVES: dict[str, Move] = {
    "dance": Move("a short dance", groups=("dance",)),
    "wave": Move("wave hello", groups=("greeting",)),
    "peace": Move("the peace sign with the fingers", clips=("Peace",)),
    "salute": Move("a military salute", clips=("QuickAction_salute",)),
    "thumbs_up": Move("two thumbs up", clips=("QuickAction_twoThumbsUp",)),
    "celebrate": Move("celebrate happily", clips=("QuickAction_vibe",)),
    "think": Move("look thoughtful", groups=("thinking",)),
}

NO_MOVES = (
    "Right now you cannot move on request (the avatar app is not connected). "
    "Say so with good humor and keep talking."
)

#: Sends a JSON message to the avatar client (``hub.broadcast_json``).
SendJson = Callable[[dict[str, Any]], Awaitable[None]]


class MoveCatalog:
    """Clips of the avatar client that can be played, per move."""

    def __init__(self, send: SendJson, *, rng: random.Random | None = None) -> None:
        self._send = send
        self._rng = rng or random.Random()
        self._clips: list[dict[str, str]] = []

    def update(self, msg: dict[str, Any]) -> None:
        """New catalog (``animations`` message from the client)."""
        self._clips = p.parse_animations(msg)

    def clips_for(self, move: str) -> list[str]:
        """Catalog clips that do ``move`` (empty if the app does not have it)."""
        spec = MOVES.get(move)
        if spec is None:
            return []
        return [
            item["clip"]
            for item in self._clips
            if item["group"] in spec.groups or item["clip"] in spec.clips
        ]

    def available(self) -> list[str]:
        """Moves the app can do right now."""
        return [name for name in MOVES if self.clips_for(name)]

    async def play(self, move: str) -> str | None:
        """Plays a random clip of ``move`` and returns its name (``None`` if there is none)."""
        clips = self.clips_for(move)
        if not clips:
            return None
        clip = self._rng.choice(clips)
        await self._send(p.msg_play_animation(clip, whole=True))
        return clip


async def play_animation(ctx: ActionContext, arguments: dict[str, Any]) -> ActionResult:
    """Does the move the user asked for."""
    catalog = ctx.extra.get("moves")
    if not isinstance(catalog, MoveCatalog):
        return ActionResult(text=NO_MOVES)
    move = str(arguments.get("move") or "").strip()
    if not move:
        return ActionResult(text="Error: say which move (move).")
    clip = await catalog.play(move)
    if clip is None:
        available = catalog.available()
        if not available:
            return ActionResult(text=NO_MOVES)
        return ActionResult(
            text=(
                f"You do not have that move ({move}). You can do: {', '.join(available)}. "
                "Offer another one with good humor."
            )
        )
    logger.info("Move by voice: %s -> %s", move, clip)
    return ActionResult(
        text=f"Done: Sonia is doing '{move}' on screen. She should go along with it in a "
        "short sentence."
    )


PLAY_ANIMATION = ActionSpec(
    name="play_animation",
    description=(
        "Make a move or gesture with your avatar on the screen. Use it when the user asks "
        "you to dance, wave or make one of these gestures."
    ),
    parameters={
        "type": "object",
        "properties": {
            "move": {
                "type": "string",
                "enum": list(MOVES),
                "description": "One of these: "
                + "; ".join(f"{name}: {move.description}" for name, move in MOVES.items())
                + ".",
            },
        },
        "required": ["move"],
    },
    handler=play_animation,
)
