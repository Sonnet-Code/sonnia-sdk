"""Pregunta cerrada al modelo de visión sobre una foto fresca de la cámara (búsqueda relámpago).

``docs/plan-juegos.md``, secciones 5.6 y 6. Es lo único de los juegos que manda una foto
fuera de este equipo, y solo al modelo de visión que ya usa Sonia (``LLM_*``), nunca a
GPT-Live:

- una foto fresca y reducida (``JUDGE_WIDTH``), sin guardarla;
- una pregunta cerrada que pone el juego («¿alguien enseña algo azul a la cámara?»);
- respuesta en JSON estricto, ``{"visto": bool, "objeto": str}``, que habla solo del
  objeto: el prompt prohíbe describir a las personas;
- con plazo (``JUDGE_TIMEOUT_S``) y con tope de llamadas por ronda, que pone quien llama
  (:meth:`ModelJudge.start_round`): pasado el tope, ``ask`` no llama y devuelve ``None``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import TYPE_CHECKING, Any, Protocol

from sonia.llm.messages import system, user_with_image
from sonia.prompts import BOOK, PromptSpec
from sonia.vision.contracts import JudgeAnswer

if TYPE_CHECKING:
    from sonia.llm import Completion
    from sonia.types import Frame, Message

__all__ = [
    "JUDGE_PROMPT",
    "JUDGE_QUALITY",
    "JUDGE_TIMEOUT_S",
    "JUDGE_WIDTH",
    "FallbackJudge",
    "ModelJudge",
    "parse_judge_answer",
    "prompt_specs",
]

logger = logging.getLogger(__name__)

#: Ancho de la foto que se manda: con el ``detail`` bajo de la API sobra.
JUDGE_WIDTH = 640
JUDGE_QUALITY = 75

#: Plazo de cada pregunta. El modelo de visión tarda unos 2 s (medido el 7-oct-2026); una
#: respuesta que llega a los 8 ya no sirve en una ronda de 25 s.
JUDGE_TIMEOUT_S = 8.0

#: Tope de caracteres de ``objeto``: Sonia lo dice en voz alta.
MAX_WHAT_CHARS = 60

JUDGE_PROMPT = """\
Eres el juez de un juego de búsqueda en un stand de un evento de tecnología. Te llega una foto de la cámara del stand y una pregunta cerrada sobre un objeto que alguien tiene que enseñar a la cámara. Responde solo con un objeto JSON, sin markdown ni texto alrededor: {"visto": true o false, "objeto": "el objeto, en pocas palabras"}.
- "visto" es true solo si en la foto se ve con claridad un objeto que cumple la pregunta. En la duda, false.
- "objeto" nombra solo el objeto que lo cumple, en español y en menos de seis palabras, por ejemplo "botella azul" o "llaves con llavero rojo". Si "visto" es false, "objeto" va vacío.
- Nunca describas a las personas: ni la cara, el cuerpo, el pelo, la edad, la piel, el género ni la ropa que llevan puesta. Lo que alguien lleva puesto o colgado (la ropa, las gafas, el pelo, las gorras, el gafete o la credencial con su cordón) no cuenta mientras siga puesto o colgando; sí cuenta si lo sostiene con la mano y lo enseña a la cámara. Si solo cumple la pregunta algo puesto o colgando, "visto" es false."""

#: Id del prompt en el panel (``sonia.prompts``): editable desde la nube.
JUDGE_PROMPT_ID = "juez/busqueda"


def prompt_specs() -> list[PromptSpec]:
    """El prompt del juez de la búsqueda relámpago, editable desde el panel."""
    return [
        PromptSpec(
            id=JUDGE_PROMPT_ID,
            group="Juez (Gemini)",
            title="Búsqueda relámpago: ¿enseñan el objeto a la cámara?",
            default=lambda: JUDGE_PROMPT,
            must_contain=("JSON", '"visto"', '"objeto"'),
            applies="peticion",
            help=(
                "Mensaje de sistema del juez de la búsqueda relámpago (Gemini y, si falla, el "
                "modelo de visión). Con cada foto le llega la pregunta del reto. Tiene que "
                'seguir pidiendo el JSON con "visto" (true o false) y "objeto": sin eso, '
                "el juego no entiende la respuesta y la ronda no cuenta. Sin marcadores."
            ),
        )
    ]


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
    """``VisionJudge`` con el modelo de visión de Sonia y la cámara del motor.

    Lleva la cuenta de las llamadas de la ronda: el juego la empieza con
    :meth:`start_round` y su tope (``GAME_BUSQUEDA_MAX_CHECKS``). Sin ronda empezada no
    hay tope propio, solo el de ``max_calls`` si se dio. Las preguntas van de una en una.
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
    ) -> None:
        self._llm = llm
        self._camera = camera
        self._timeout_s = timeout_s
        self._width = width
        self._quality = quality
        self._limit = max_calls
        self._lock = asyncio.Lock()
        #: Llamadas al modelo en la ronda actual y en total (el total, para medir el gasto).
        self.calls = 0
        self.total_calls = 0
        #: Segundos que tardó la última respuesta.
        self.last_seconds = 0.0
        #: ``True`` si la última pregunta se quedó sin respuesta por el modelo (un fallo, el
        #: plazo o una respuesta sin el JSON esperado), no por falta de foto o por el tope.
        self.last_failed = False

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
            self.last_failed = False
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
                system(BOOK.text(JUDGE_PROMPT_ID, JUDGE_PROMPT)),
                user_with_image(question.strip(), frame),
            ]
            started = time.monotonic()
            try:
                completion = await asyncio.wait_for(
                    self._llm.complete(messages), timeout=self._timeout_s
                )
            except TimeoutError:
                logger.warning("El modelo de visión no juzgó la foto en %.0f s", self._timeout_s)
                self.last_failed = True
                return None
            except Exception as exc:  # noqa: BLE001 - sin respuesta, el juego sigue
                logger.warning("El modelo de visión no pudo juzgar la foto: %s", exc)
                self.last_failed = True
                return None
            finally:
                self.last_seconds = time.monotonic() - started
            answer = parse_judge_answer(completion.content)
            if answer is None:
                logger.warning(
                    "Respuesta del juez sin el JSON esperado: %r", completion.content[:200]
                )
                self.last_failed = True
            return answer


class FallbackJudge:
    """Gemini primero y, si falla, el modelo de visión de ``LLM_*`` (búsqueda relámpago).

    ``primary`` (Gemini, con ``GAMES_JUDGE=gemini``) lleva el tope de fotos de la ronda. Si
    no contesta por un fallo, por el plazo o sin el JSON esperado (un 429 de la clave, por
    ejemplo: los gestos también la usan todo el día), la misma pregunta va a ``secondary``
    con una foto nueva. Sin foto o con el tope alcanzado no se repite. Como cada pregunta
    cuenta una vez en el tope de ``primary``, el total de fotos no pasa del tope.
    """

    def __init__(self, primary: ModelJudge, secondary: ModelJudge) -> None:
        self._primary = primary
        self._secondary = secondary
        #: Preguntas que acabaron en ``secondary`` (para el registro y las pruebas).
        self.fallbacks = 0

    @property
    def available(self) -> bool:
        return self._primary.available or self._secondary.available

    @property
    def remaining(self) -> int | None:
        return self._primary.remaining

    @property
    def calls(self) -> int:
        return self._primary.calls

    @property
    def total_calls(self) -> int:
        return self._primary.total_calls + self._secondary.total_calls

    @property
    def last_seconds(self) -> float:
        return self._primary.last_seconds

    def start_round(self, max_calls: int | None) -> None:
        self._primary.start_round(max_calls)
        self._secondary.start_round(None)

    async def ask(self, question: str) -> JudgeAnswer | None:
        answer = await self._primary.ask(question)
        if answer is not None or not self._primary.last_failed:
            return answer
        self.fallbacks += 1
        logger.info("El juez de Gemini no contestó: la pregunta va al modelo de visión")
        return await self._secondary.ask(question)
