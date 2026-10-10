"""Los ojos de Sonia con el motor GPT-Live.

GPT-Live no acepta imágenes. Para que Sonia pueda saludar con un cumplido
sobre lo que ve, cuando alguien empieza a hablarle se toma una captura, un
modelo con visión (el de ``LLM_*``, cualquiera compatible con OpenAI) la
describe en una o dos frases y la descripción entra en la sesión como nota
silenciosa (``session.thinking.append``). La foto no sale de aquí hacia
GPT-Live ni se guarda en disco.

El prompt y la pregunta que acompaña a la foto se pueden cambiar desde el panel
(``vision/narrador`` y ``vision/pregunta``, ver ``sonia/prompts``).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Protocol

from sonia.llm.messages import user_with_image
from sonia.prompts import BOOK
from sonia.types import Frame, LLMEvent, Message, TextDelta, TurnDone

__all__ = ["NARRATOR_PROMPT", "VisionNarrator"]

logger = logging.getLogger(__name__)

NARRATOR_PROMPT = """\
Eres los ojos de Sonia, la asistente virtual del stand de Sonnet Code en el DevFest Santo Domingo 2026. Te llega una foto de la cámara del stand. Describe en una o dos frases cortas, en español, lo útil para que Sonia salude y converse: cuántas personas hay delante y si miran a la cámara, prendas y colores, gafas, gorras, gafetes del evento, logos o textos legibles en la ropa y cualquier objeto que estén enseñando a la cámara. Nunca hables del cuerpo, el peso, la edad o la piel, ni supongas origen, género o profesión. Si no hay nadie delante, responde solo "No hay nadie delante de la cámara." Sin markdown ni listas."""

#: Texto del usuario que acompaña a la foto.
NARRATOR_REQUEST = "¿Qué ve ahora mismo la cámara del stand?"

#: Tope de la descripción que se manda a la sesión.
MAX_DESCRIPTION_CHARS = 500


class _StreamingLLM(Protocol):
    def stream(self, messages: list[Message]) -> AsyncIterator[LLMEvent]: ...


class VisionNarrator:
    """Convierte una captura en una descripción corta con un modelo de visión."""

    def __init__(self, llm: _StreamingLLM, *, timeout_s: float = 12.0) -> None:
        self._llm = llm
        self._timeout_s = timeout_s

    async def describe(self, frame: Frame) -> str:
        """Devuelve la descripción, o cadena vacía si el modelo no dijo nada."""
        messages: list[Message] = [
            {"role": "system", "content": BOOK.text("vision/narrador", fallback=NARRATOR_PROMPT)},
            user_with_image(BOOK.text("vision/pregunta", fallback=NARRATOR_REQUEST), frame),
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
