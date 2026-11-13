"""``show_emotion`` action: joy, sadness or surprise on Sonnia's face.

It is the worked example of ``docs/actions.md``, small on purpose: a JSON Schema
for the arguments, a handler that never raises, one protocol message
(``show_emotion``) and its Unity side (``SoniaBootstrap.HandleShowEmotion``, which
calls ``FacialExpressionController.ShowEmotion``). It is off by default
(``SHOW_EMOTION_ENABLED``) because every emotion is a task delegated to the backend.
"""

from __future__ import annotations

import logging
from typing import Any

from sonia.actions.builtin import NO_AVATAR
from sonia.types import ActionContext, ActionResult, ActionSpec
from sonia.ws import protocol as p

logger = logging.getLogger(__name__)

#: How long an emotion stays when the backend does not say.
DEFAULT_SECONDS = 3.0

SHOW_EMOTION_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "emotion": {
            "type": "string",
            "enum": list(p.EMOTIONS),
            "description": "joy (a big smile), sad (a sad face) or surprise (raised brows, open eyes).",
        },
        "seconds": {
            "type": "number",
            "description": (
                f"How long to hold it, from 0.5 to {p.EMOTION_MAX_SECONDS:g} seconds "
                f"({DEFAULT_SECONDS:g} if not given)."
            ),
        },
    },
    "required": ["emotion"],
}


async def show_emotion(ctx: ActionContext, arguments: dict[str, Any]) -> ActionResult:
    """Shows the emotion on the avatar's face.

    The registry has already checked the arguments against the schema: ``emotion``
    is one of :data:`sonia.ws.protocol.EMOTIONS` and ``seconds``, if present, a number.
    """
    if ctx.avatar is None:
        return ActionResult(text=NO_AVATAR)
    emotion: str = arguments["emotion"]
    seconds = float(arguments.get("seconds") or DEFAULT_SECONDS)
    seconds = min(max(seconds, 0.5), p.EMOTION_MAX_SECONDS)
    await ctx.avatar.show_emotion(emotion, seconds)
    logger.info("Emotion on the face: %s for %.1f s", emotion, seconds)
    # The text goes back to the model: short, and it tells her what to do next.
    return ActionResult(text=f"Done: your face shows {emotion} on screen. Keep talking naturally.")


SHOW_EMOTION = ActionSpec(
    name="show_emotion",
    description=(
        "Show an emotion on your avatar's face for a few seconds: joy, sadness or surprise. "
        "Use it when the user asks you to make a face, or to react to good news, a sad "
        "story or a surprising fact."
    ),
    parameters=SHOW_EMOTION_PARAMETERS,
    handler=show_emotion,
)
