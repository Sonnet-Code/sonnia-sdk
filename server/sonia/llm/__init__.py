"""Cliente de un modelo compatible con OpenAI (Chat Completions).

Con GPT-Live solo se usa para describir la cámara (``sonia/live/vision.py``).
"""

from __future__ import annotations

from sonia.llm.client import LLMClient, LLMError
from sonia.llm.messages import system, user_text, user_with_image

__all__ = ["LLMClient", "LLMError", "system", "user_text", "user_with_image"]
