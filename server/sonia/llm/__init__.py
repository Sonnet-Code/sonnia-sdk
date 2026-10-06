"""Cliente de un modelo compatible con OpenAI (Chat Completions).

Con GPT-Live se usa para describir la cámara (``sonia/live/vision.py``) y para
elegir los gestos al hablar (``sonia/gestures``).
"""

from __future__ import annotations

from sonia.llm.client import Completion, LLMClient, LLMError
from sonia.llm.messages import system, user_text, user_with_image

__all__ = ["Completion", "LLMClient", "LLMError", "system", "user_text", "user_with_image"]
