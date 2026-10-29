"""Message builders in OpenAI format.

The format is the standard one of the chat completions API, so it works with
any compatible server. With GPT-Live they are only used to describe the
camera.
"""

from __future__ import annotations

from typing import Any

from sonia.types import Frame, Message

__all__ = ["system", "user_text", "user_with_image"]


def system(text: str) -> Message:
    """System message (the personality prompt)."""
    return {"role": "system", "content": text}


def user_text(text: str) -> Message:
    """User turn, text only."""
    return {"role": "user", "content": text}


def user_with_image(text: str, frame: Frame, detail: str = "low") -> Message:
    """User turn with a snapshot attached.

    The image travels as ``image_url`` with a data URL, which is the standard
    format. ``detail`` is OpenAI's field: outside OpenAI it is not documented,
    so ``LLMClient`` replaces it with ``LLM_IMAGE_DETAIL`` (or removes it with
    ``off``) before sending.
    """
    content: list[dict[str, Any]] = []
    if text:
        content.append({"type": "text", "text": text})
    content.append(
        {
            "type": "image_url",
            "image_url": {"url": frame.to_data_url(), "detail": detail},
        }
    )
    return {"role": "user", "content": content}
