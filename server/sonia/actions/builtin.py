"""Built-in actions: `look`, `show_image`, `hide_image` and `play_animation`.

The trivia actions live in their own module and are registered here.

The texts they return go back to the model as the tool call result, so they are
short: the model uses them to decide what to say out loud. No action raises;
problems are told in the text.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sonia.actions.gallery import Gallery
from sonia.actions.registry import ActionRegistry
from sonia.types import ActionContext, ActionResult, ActionSpec, Frame

logger = logging.getLogger(__name__)

#: Maximum wait for a snapshot requested by the model. A hung camera driver cannot
#: leave the turn in ``thinking`` forever: better to tell the model it could not
#: look and go on with the conversation.
CAPTURE_TIMEOUT_S = 3.0

NO_CAMERA = "There is no camera available."
NO_AVATAR = "The avatar is not connected."


# ---------------------------------------------------------------------------
# look
# ---------------------------------------------------------------------------

LOOK_SPEC_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
}


async def _capture(ctx: ActionContext) -> Frame | None:
    """Snapshot from the context camera, also stored in ``ctx.last_frame``."""
    if ctx.camera is None:
        return None
    try:
        frame = await asyncio.wait_for(ctx.camera.capture(), timeout=CAPTURE_TIMEOUT_S)
    except TimeoutError:
        logger.warning("The camera did not answer the action within %.1f s", CAPTURE_TIMEOUT_S)
        return None
    if frame is not None:
        ctx.last_frame = frame
    return frame


async def look(ctx: ActionContext, arguments: dict[str, Any]) -> ActionResult:
    """Takes a fresh snapshot and returns it to the model as an image."""
    if ctx.camera is None:
        return ActionResult(text=NO_CAMERA)
    frame = await _capture(ctx)
    if frame is None:
        return ActionResult(text="I could not take the camera snapshot.")
    return ActionResult(text="Snapshot taken.", image=frame)


# ---------------------------------------------------------------------------
# show_image
# ---------------------------------------------------------------------------

SHOW_IMAGE_SPEC_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "image_id": {
            "type": "string",
            "description": "Id of an image of the local gallery (file name without extension).",
        },
        "caption": {
            "type": "string",
            "description": "Optional short caption.",
        },
    },
    "required": ["image_id"],
}


#: With the trivia on screen, the top strip is taken: the image would not be seen and
#: Sonia would point at nothing. The realtime model reads it.
SCREEN_BUSY_TRIVIA = (
    "There is a trivia game on your screen right now: {what} cannot be shown until it ends. "
    "Tell it with words."
)


def screen_busy(ctx: ActionContext, what: str = "the image") -> str | None:
    """Why ``what`` cannot be shown now (the trivia on screen), or ``None``.

    Looks at ``ctx.extra["trivia"]`` (the ``TriviaGame``: ``active``) by attribute.
    """
    trivia = ctx.extra.get("trivia")
    if trivia is not None and getattr(trivia, "active", False):
        return SCREEN_BUSY_TRIVIA.format(what=what)
    return None


async def show_image(ctx: ActionContext, arguments: dict[str, Any]) -> ActionResult:
    """Shows an image in the image panel of the avatar's scene."""
    image_id: str = arguments["image_id"]
    caption: str | None = arguments.get("caption") or None

    if ctx.avatar is None:
        return ActionResult(text=NO_AVATAR)
    busy = screen_busy(ctx)
    if busy:
        return ActionResult(text=busy)

    gallery = Gallery(ctx.gallery_dir, ctx.gallery_upload_dir)
    loaded = gallery.load(image_id)
    if loaded is None:
        available = ", ".join(gallery.ids()) or "none"
        return ActionResult(
            text=f"There is no image '{image_id}' in the gallery. Available: {available}."
        )

    data, mime = loaded
    await ctx.avatar.show_image(
        image_id=image_id,
        source="gallery",
        mime=mime,
        data=data,
        caption=caption,
    )
    return ActionResult(text=f"Showing the image '{image_id}'.")


# ---------------------------------------------------------------------------
# hide_image
# ---------------------------------------------------------------------------

HIDE_IMAGE_SPEC_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
}


async def hide_image(ctx: ActionContext, arguments: dict[str, Any]) -> ActionResult:
    """Hides the image panel."""
    if ctx.avatar is None:
        return ActionResult(text=NO_AVATAR)
    await ctx.avatar.hide_image()
    return ActionResult(text="Image panel hidden.")


# ---------------------------------------------------------------------------
# Definitions
# ---------------------------------------------------------------------------

LOOK = ActionSpec(
    name="look",
    description=(
        "Look through your camera and take a photo to see it. Use it when you are asked "
        "what you see or when someone shows you something and you have no recent image."
    ),
    parameters=LOOK_SPEC_PARAMETERS,
    handler=look,
)

SHOW_IMAGE = ActionSpec(
    name="show_image",
    description="Shows an image from the local gallery on your screen, next to you.",
    parameters=SHOW_IMAGE_SPEC_PARAMETERS,
    handler=show_image,
)

HIDE_IMAGE = ActionSpec(
    name="hide_image",
    description="Hides the image you are showing on your screen.",
    parameters=HIDE_IMAGE_SPEC_PARAMETERS,
    handler=hide_image,
)


def build_default_registry(
    *,
    include_look: bool = True,
    include_trivia: bool = False,
) -> ActionRegistry:
    """Registry with the built-in actions.

    ``include_look`` allows not announcing ``look`` when the configured model does
    not support images (``LLM_SUPPORTS_VISION=false``) or there is no camera.
    ``play_animation`` (dances and gestures by voice, :mod:`sonia.actions.moves`) is
    always there. ``include_trivia`` announces ``start_trivia``, ``trivia_answer``,
    ``trivia_next``, ``restart_trivia`` and ``stop_trivia`` when there is a question
    bank (``assets/trivia/questions.md``).
    """
    from sonia.actions.moves import PLAY_ANIMATION
    from sonia.actions.trivia import (
        RESTART_TRIVIA,
        START_TRIVIA,
        STOP_TRIVIA,
        TRIVIA_ANSWER,
        TRIVIA_NEXT,
    )

    registry = ActionRegistry()
    if include_look:
        registry.register(LOOK)
    registry.register(SHOW_IMAGE)
    registry.register(HIDE_IMAGE)
    registry.register(PLAY_ANIMATION)
    if include_trivia:
        registry.register(START_TRIVIA)
        registry.register(TRIVIA_ANSWER)
        registry.register(TRIVIA_NEXT)
        registry.register(RESTART_TRIVIA)
        registry.register(STOP_TRIVIA)
    return registry
