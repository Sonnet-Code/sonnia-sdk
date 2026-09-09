"""Capa del modelo de lenguaje: cliente de streaming, mensajes e historial."""

from __future__ import annotations

from sonia.llm.client import LLMClient, LLMError
from sonia.llm.conversation import Conversation
from sonia.llm.messages import (
    assistant_text,
    assistant_tool_calls,
    has_image,
    strip_images,
    system,
    tool_result,
    user_text,
    user_with_image,
)
from sonia.llm.prompt_tools import PromptToolParser, render_tools_prompt

__all__ = [
    "Conversation",
    "LLMClient",
    "LLMError",
    "PromptToolParser",
    "assistant_text",
    "assistant_tool_calls",
    "has_image",
    "render_tools_prompt",
    "strip_images",
    "system",
    "tool_result",
    "user_text",
    "user_with_image",
]
