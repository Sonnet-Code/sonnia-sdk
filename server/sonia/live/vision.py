"""Sonnia's eyes with the GPT-Live engine.

GPT-Live does not accept images. So that Sonnia can greet people with a
compliment about what she sees, when someone starts talking to her a snapshot is
taken, a vision model (the ``LLM_*`` one, any OpenAI-compatible endpoint)
describes it in one or two sentences and the description goes into the session
as a silent note (``session.thinking.append``). The photo never goes from here to
GPT-Live and is never written to disk.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Protocol

from sonia.llm.messages import user_with_image
from sonia.types import Frame, LLMEvent, Message, TextDelta, TurnDone

__all__ = ["NARRATOR_PROMPT", "VisionNarrator"]

logger = logging.getLogger(__name__)

NARRATOR_PROMPT = """\
You are the eyes of Sonia, a virtual assistant who talks with people in person through an animated 3D avatar. You receive a photo from her camera. Describe in one or two short sentences, in English, what is useful for Sonia to greet people and talk with them: how many people are in front of the camera and whether they are looking at it, clothes and colors, glasses, caps, badges, logos or readable text on clothes and any object they are showing to the camera. Never talk about the body, weight, age or skin, and never guess origin, gender or profession. If there is nobody in front of the camera, answer only "There is nobody in front of the camera." No markdown or lists."""

#: User text that goes with the photo.
NARRATOR_REQUEST = "What does the camera see right now?"

#: Maximum length of the description sent to the session.
MAX_DESCRIPTION_CHARS = 500


class _StreamingLLM(Protocol):
    def stream(self, messages: list[Message]) -> AsyncIterator[LLMEvent]: ...


class VisionNarrator:
    """Turns a snapshot into a short description with a vision model."""

    def __init__(self, llm: _StreamingLLM, *, timeout_s: float = 12.0) -> None:
        self._llm = llm
        self._timeout_s = timeout_s

    async def describe(self, frame: Frame) -> str:
        """Returns the description, or an empty string if the model said nothing."""
        messages: list[Message] = [
            {"role": "system", "content": NARRATOR_PROMPT},
            user_with_image(NARRATOR_REQUEST, frame),
        ]
        parts: list[str] = []
        final = ""
        async with asyncio.timeout(self._timeout_s):
            async for event in self._llm.stream(messages):
                if isinstance(event, TextDelta):
                    parts.append(event.text)
                elif isinstance(event, TurnDone):
                    final = event.content
                    break
                else:
                    break
        text = " ".join((final or "".join(parts)).split())
        if len(text) > MAX_DESCRIPTION_CHARS:
            text = text[: MAX_DESCRIPTION_CHARS - 1].rstrip() + "…"
        return text
