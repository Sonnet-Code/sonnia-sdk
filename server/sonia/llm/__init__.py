"""Client for an OpenAI-compatible model (Chat Completions).

With GPT-Live it is used to describe the camera (``sonia/live/vision.py``).
"""

from __future__ import annotations

from sonia.llm.client import Completion, LLMClient, LLMError
from sonia.llm.messages import system, user_text, user_with_image

__all__ = ["Completion", "LLMClient", "LLMError", "system", "user_text", "user_with_image"]
