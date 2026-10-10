"""Pregunta cerrada al modelo de visión sobre una foto fresca de la cámara (búsqueda relámpago).

``docs/plan-juegos.md``, secciones 5.6 y 6. Es lo único de los juegos que manda una foto
fuera de este equipo, y solo al modelo de visión que ya usa Sonia (``LLM_*``), nunca a
GPT-Live:

- una foto fresca y reducida (``JUDGE_WIDTH``), sin guardarla;
- una pregunta cerrada que pone el juego («¿alguien enseña algo azul a la cámara?»);
- respuesta en JSON estricto, ``{"visto": bool, "objeto": str}``, que habla solo del
  objeto: el prompt prohíbe describir a las personas;
- con plazo (``JUDGE_TIMEOUT_S``) y con tope de llamadas por ronda, que pone quien llama
  (:meth:`ModelJudge.start_round`): pasado el tope, ``ask`` no llama y devuelve ``None``;
- con un modelo de respaldo opcional (``fallback``): con ``GAMES_JUDGE=gemini`` el juez es
  Gemini y, si falla (error, 429, plazo o JSON roto), la misma foto va al modelo de visión de
  Sonia (``LLM_*``). Una pregunta es una foto: cuenta una sola vez para el tope.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import TYPE_CHECKING, Any, Protocol

from sonia.llm.messages import system, user_with_image
from sonia.vision.contracts import JudgeAnswer

if TYPE_CHECKING:
    from sonia.llm import Completion
    from sonia.types import Frame, Message

__all__ = [
    "FALLBACK_TIMEOUT_S",
    "JUDGE_PROMPT",
    "JUDGE_QUALITY",
    "JUDGE_TIMEOUT_S",
    "JUDGE_WIDTH",
    "ModelJudge",
    "parse_judge_answer",
]

logger = logging.getLogger(__name__)

#: Ancho de la foto que se manda: con el ``detail`` bajo de la API sobra.
JUDGE_WIDTH = 640
JUDGE_QUALITY = 75

#: Plazo de cada pregunta. El modelo de visión tarda unos 2 s (medido el 7-oct-2026); una
#: respuesta que llega a los 8 ya no sirve en una ronda de 25 s.
JUDGE_TIMEOUT_S = 8.0

#: Plazo del modelo de respaldo cuando el principal falla. Con los 4 s de Gemini
#: (``GAMES_JUDGE_TIMEOUT_SECONDS``) cabe en los 12 s con los que la búsqueda espera cada
#: mirada (``sonia.games.busqueda.game.JUDGE_TIMEOUT_S``); luna tardó 3,6 s como mucho.
FALLBACK_TIMEOUT_S = 6.0

#: Tope de caracteres de ``objeto``: Sonia lo dice en voz alta.
MAX_WHAT_CHARS = 60

JUDGE_PROMPT = """\
Eres el juez de un juego de búsqueda en un stand de un evento de tecnología. Te llega una foto de la cámara del stand y una pregunta cerrada sobre un objeto que alguien tiene que enseñar a la cámara. Responde solo con un objeto JSON, sin markdown ni texto alrededor: {"visto": true o false, "objeto": "el objeto, en pocas palabras"}.
- "visto" es true solo si en la foto se ve con claridad un objeto que cumple la pregunta. En la duda, false.
- "objeto" nombra solo el objeto que lo cumple, en español y en menos de seis palabras, por ejemplo "botella azul" o "llaves con llavero rojo". Si "visto" es false, "objeto" va vacío.
- Nunca describas a las personas: ni la cara, el cuerpo, el pelo, la edad, la piel, el género ni la ropa que llevan puesta. La ropa, las gafas o el pelo de alguien no cuentan como objeto: si solo eso cumple la pregunta, "visto" es false."""


class _VisionLLM(Protocol):
    async def complete(self, messages: list[Message]) -> Completion: ...


class _Camera(Protocol):
    async def capture(
        self, *, max_width: int | None = None, quality: int | None = None
    ) -> Frame | None: ...


_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def parse_judge_answer(text: str) -> JudgeAnswer | None:
    """``{"visto": bool, "objeto": str}`` → :class:`JudgeAnswer`. ``None`` si no cuadra.

    Tolera que el modelo envuelva el JSON en ```` ```json ```` o en una frase; no tolera
    que falte ``visto`` o que no sea booleano.
    """
    match = _JSON_OBJECT.search(text or "")
    if match is None:
        return None
    try:
        data: Any = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    seen = data.get("visto")
    if not isinstance(seen, bool):
        return None
    what = data.get("objeto", "")
    what = " ".join(what.split()) if isinstance(what, str) else ""
    if len(what) > MAX_WHAT_CHARS:
        what = what[: MAX_WHAT_CHARS - 1].rstrip() + "…"
    return JudgeAnswer(seen=seen, what=what if seen else "")


class ModelJudge:
    """``VisionJudge`` con un modelo con visión (Gemini o el de Sonia) y la cámara del motor.

    Lleva la cuenta de las fotos de la ronda: el juego la empieza con :meth:`start_round` y
    su tope (``GAME_BUSQUEDA_MAX_CHECKS``). Sin ronda empezada no hay tope propio, solo el
    de ``max_calls`` si se dio. Las preguntas van de una en una. Con ``fallback``, si ``llm``
    falla (error, plazo o JSON roto), la misma foto va a ``fallback`` con su plazo
    (``fallback_timeout_s``); sin foto o pasado el tope, no se pregunta a ninguno.
    """

    def __init__(
        self,
        llm: _VisionLLM,
        camera: _Camera,
        *,
        timeout_s: float = JUDGE_TIMEOUT_S,
        width: int = JUDGE_WIDTH,
        quality: int = JUDGE_QUALITY,
        max_calls: int | None = None,
        fallback: _VisionLLM | None = None,
        fallback_timeout_s: float = FALLBACK_TIMEOUT_S,
    ) -> None:
        self._llm = llm
        self._camera = camera
        self._timeout_s = timeout_s
        self._fallback = fallback
        self._fallback_timeout_s = fallback_timeout_s
        self._width = width
        self._quality = quality
        self._limit = max_calls
        self._lock = asyncio.Lock()
        #: Fotos juzgadas en la ronda actual y en total (el total, para medir el gasto).
        self.calls = 0
        self.total_calls = 0
        #: Preguntas que acabaron en el modelo de respaldo.
        self.fallback_calls = 0
        #: Segundos que tardó la última respuesta.
        self.last_seconds = 0.0

    @property
    def available(self) -> bool:
        return True

    @property
    def remaining(self) -> int | None:
        """Llamadas que quedan en la ronda (``None``: sin tope)."""
        return None if self._limit is None else max(0, self._limit - self.calls)

    def start_round(self, max_calls: int | None) -> None:
        """Empieza la cuenta de una ronda nueva con su tope (``None``: sin tope)."""
        self._limit = None if max_calls is None else max(0, int(max_calls))
        self.calls = 0

    async def ask(self, question: str) -> JudgeAnswer | None:
        async with self._lock:
            if self._limit is not None and self.calls >= self._limit:
                logger.info("Tope de fotos de la ronda alcanzado (%d): no se pregunta", self._limit)
                return None
            frame = await self._camera.capture(max_width=self._width, quality=self._quality)
            if frame is None:
                logger.info("Sin foto de la cámara para el juez")
                return None
            self.calls += 1
            self.total_calls += 1
            messages: list[Message] = [
                system(JUDGE_PROMPT),
                user_with_image(question.strip(), frame),
            ]
            started = time.monotonic()
            try:
                answer = await self._judge(self._llm, messages, self._timeout_s, "")
                if answer is None and self._fallback is not None:
                    # La misma foto al de respaldo: una pregunta, una foto para el tope.
                    self.fallback_calls += 1
                    answer = await self._judge(
                        self._fallback, messages, self._fallback_timeout_s, " de respaldo"
                    )
            finally:
                self.last_seconds = time.monotonic() - started
            return answer

    async def _judge(
        self, llm: _VisionLLM, messages: list[Message], timeout_s: float, label: str
    ) -> JudgeAnswer | None:
        """Una pregunta a ``llm`` con plazo. ``None`` si falla, no llega o no cuadra."""
        started = time.monotonic()
        try:
            completion = await asyncio.wait_for(llm.complete(messages), timeout=timeout_s)
        except TimeoutError:
            logger.warning("El juez%s no juzgó la foto en %.0f s", label, timeout_s)
            return None
        except Exception as exc:  # noqa: BLE001 - sin respuesta, el juego sigue
            logger.warning("El juez%s no pudo juzgar la foto: %s", label, exc)
            return None
        answer = parse_judge_answer(completion.content)
        if answer is None:
            logger.warning(
                "Respuesta del juez%s sin el JSON esperado: %r", label, completion.content[:200]
            )
        else:
            logger.info("Juez%s de la búsqueda: %.2f s", label, time.monotonic() - started)
        return answer
