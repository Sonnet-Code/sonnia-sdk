"""Juez de las rondas de cámara con Gemini (``GAMES_JUDGE=gemini``, ``docs/juegos-vision.md``).

Encargo de Jean del 10 de octubre de 2026: en Simón dice y en piedra, papel o tijera decide
Gemini, el modelo de los gestos (``settings.gestures``), con una foto por ronda. La detección
local sigue para la vista en vivo y elige el momento de la foto; si Gemini no contesta a
tiempo, decide ella, como antes.

- Una foto reducida (:data:`REFEREE_WIDTH`, JPEG :data:`REFEREE_QUALITY`), codificada en un
  hilo, en memoria y sin guardarla.
- Respuesta en JSON, con los prompts validados en el banco de pruebas del 10-oct-2026 (80
  fotos públicas etiquetadas: mediana 1,25 s, p90 1,7 s; aciertos por encima de lo local).
- Con plazo (``GAMES_JUDGE_TIMEOUT_SECONDS``). ``None`` si no contesta a tiempo, si falla o
  si el JSON no es el esperado: nunca lanza.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import unicodedata
from typing import TYPE_CHECKING, Any, Protocol

import numpy as np

from sonia.config import is_gemini_url
from sonia.llm.messages import system, user_with_image
from sonia.prompts import BOOK, PromptSpec
from sonia.vision.contracts import HandShape, HandVerdict, PoseVerdict

if TYPE_CHECKING:
    from sonia.config import LLMSettings, Settings
    from sonia.llm import Completion
    from sonia.types import Frame, Message

__all__ = [
    "HANDS_PROMPT",
    "HANDS_QUESTION",
    "POSES_PROMPT",
    "POSES_QUESTION",
    "POSE_KEYS",
    "REFEREE_MAX_TOKENS",
    "REFEREE_QUALITY",
    "REFEREE_WIDTH",
    "GeminiReferee",
    "gemini_llm_settings",
    "parse_hand_verdict",
    "parse_pose_verdict",
    "prompt_specs",
]

logger = logging.getLogger(__name__)

#: Ancho y calidad de la foto: los del banco de pruebas (``detail`` no cambiaba nada).
REFEREE_WIDTH = 640
REFEREE_QUALITY = 75
#: Tope de la respuesta: Gemini 3 razona (``minimal``) y lo que razona cuenta en el tope.
REFEREE_MAX_TOKENS = 1024

#: Las poses que sabe juzgar (las de ``sonia.games.poses.rules.POSE_IDS``, en el prompt).
POSE_KEYS: tuple[str, ...] = (
    "brazos_arriba",
    "un_brazo",
    "pose_t",
    "manos_cabeza",
    "biceps",
    "barbilla",
)

POSES_PROMPT = """\
Eres el juez de «Simón dice» en un stand de un evento de tecnología. Te llega una foto de la cámara del stand. Cuenta las personas que se ven (al menos de medio cuerpo o con los brazos a la vista; no cuentes dibujos de carteles ni murales) y cuántas hacen cada pose de esta lista:
- brazos_arriba: los dos brazos estirados hacia arriba.
- un_brazo: solo un brazo arriba, el otro abajo.
- pose_t: los dos brazos en cruz, horizontales a los lados.
- manos_cabeza: las dos manos sobre la cabeza.
- biceps: saca bíceps (brazo doblado con el puño hacia arriba, en uno o en los dos brazos).
- barbilla: una mano en la barbilla, como pensando.
- ninguna: ninguna de las anteriores.
Cada persona cuenta en una sola pose. Responde solo con un objeto JSON, sin markdown ni texto alrededor: {"personas": N, "brazos_arriba": n, "un_brazo": n, "pose_t": n, "manos_cabeza": n, "biceps": n, "barbilla": n, "ninguna": n}. Nunca describas a las personas."""

# El del banco, con un solo ajuste: la mano que cuenta es la que enseña a la cámara la
# persona más cercana (el jugador), la primera de la lista.
HANDS_PROMPT = """\
Eres el juez de piedra, papel o tijera en un stand de un evento de tecnología. Te llega una foto de la cámara del stand. Fíjate en la mano que enseña a la cámara la persona más cercana y di qué gesto de piedra, papel o tijera hace: piedra (puño cerrado), papel (mano abierta con los dedos estirados) o tijera (índice y corazón estirados en V y el resto doblados). Responde solo con un objeto JSON, sin markdown ni texto alrededor: {"manos": ["piedra" | "papel" | "tijera", ...]}, un elemento por cada mano que haga un gesto claro: primero la mano que enseña a la cámara la persona más cercana y después las demás, de la más visible a la menos visible. Si ninguna mano hace un gesto claro, la lista va vacía. Nunca describas a las personas."""

POSES_QUESTION = "Analiza la foto."
HANDS_QUESTION = "¿Qué gestos de piedra, papel o tijera se ven?"

#: Ids de los prompts en el panel (``sonia.prompts``): editables desde la nube.
POSES_PROMPT_ID = "juez/poses"
HANDS_PROMPT_ID = "juez/piedra_papel_tijera"


def prompt_specs() -> list[PromptSpec]:
    """Los prompts del juez de Simón dice y de piedra, papel o tijera, editables desde el panel."""
    pose_keys = tuple(f'"{key}"' for key in POSE_KEYS)
    return [
        PromptSpec(
            id=POSES_PROMPT_ID,
            group="Juez (Gemini)",
            title="Simón dice: cuántas personas hacen cada pose",
            default=lambda: POSES_PROMPT,
            must_contain=("JSON", '"personas"', *pose_keys),
            applies="peticion",
            help=(
                "Mensaje de sistema del juez de cada ronda de Simón dice (una foto por ronda). "
                'Tiene que seguir pidiendo el JSON con "personas" y la cuenta de cada pose '
                "con estas claves exactas: " + ", ".join(POSE_KEYS) + ". Si falta una, esa "
                "pose la decide la detección local; si el JSON no se entiende, toda la ronda. "
                "Sin marcadores."
            ),
        ),
        PromptSpec(
            id=HANDS_PROMPT_ID,
            group="Juez (Gemini)",
            title="Piedra, papel o tijera: qué gesto enseña la mano",
            default=lambda: HANDS_PROMPT,
            must_contain=("JSON", '"manos"', '"piedra"', '"papel"', '"tijera"'),
            applies="peticion",
            help=(
                "Mensaje de sistema del juez de cada ronda de piedra, papel o tijera (una foto "
                'por ronda). Tiene que seguir pidiendo el JSON con "manos": una lista con '
                '"piedra", "papel" o "tijera", la primera la de la persona más cercana (la '
                "que juega). Si el JSON no se entiende, decide la detección local. Sin "
                "marcadores."
            ),
        ),
    ]


#: Cómo puede escribir Gemini cada jugada (sin tildes ni mayúsculas).
_SHAPES: dict[str, HandShape] = {
    "piedra": HandShape.ROCK,
    "rock": HandShape.ROCK,
    "papel": HandShape.PAPER,
    "paper": HandShape.PAPER,
    "tijera": HandShape.SCISSORS,
    "tijeras": HandShape.SCISSORS,
    "scissors": HandShape.SCISSORS,
}

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


class _VisionLLM(Protocol):
    async def complete(self, messages: list[Message]) -> Completion: ...


def gemini_llm_settings(settings: Settings, request_timeout: float) -> LLMSettings | None:
    """Los ajustes del cliente de Gemini del juez, o ``None`` si no se puede usar.

    Son los del director de gestos (``settings.gestures.llm_settings``: Gemini con
    ``GEMINI_API_KEY`` y razonamiento ``minimal``), como en el banco de pruebas, con
    :data:`REFEREE_MAX_TOKENS` y ``request_timeout``. ``None`` si los gestos no van por
    Gemini o no hay clave: entonces deciden los juegos en local.
    """
    llm = settings.gestures.llm_settings(settings.llm)
    if not is_gemini_url(llm.base_url) or not llm.key:
        return None
    return llm.model_copy(
        update={"max_tokens": REFEREE_MAX_TOKENS, "request_timeout": max(0.5, request_timeout)}
    )


class GeminiReferee:
    """``GameReferee`` con Gemini: una foto reducida por ronda, con plazo y sin guardarla.

    ``llm`` es el cliente (``LLMClient`` con :func:`gemini_llm_settings`); quien lo crea lo
    cierra al apagar (``build_game_vision``). Sin ``llm`` no está disponible.
    """

    def __init__(
        self,
        llm: _VisionLLM | None,
        *,
        timeout_s: float,
        width: int = REFEREE_WIDTH,
        quality: int = REFEREE_QUALITY,
    ) -> None:
        self._llm = llm
        self._timeout_s = max(0.1, float(timeout_s))
        self._width = width
        self._quality = quality
        #: Fotos juzgadas (para medir el gasto) y segundos de la última respuesta.
        self.calls = 0
        self.last_seconds = 0.0

    @property
    def available(self) -> bool:
        return self._llm is not None

    async def poses(self, frame_bgr: np.ndarray) -> PoseVerdict | None:
        prompt = BOOK.text(POSES_PROMPT_ID, POSES_PROMPT)
        text = await self._ask("poses", prompt, POSES_QUESTION, frame_bgr)
        if text is None:
            return None
        verdict = parse_pose_verdict(text)
        if verdict is None:
            logger.warning("Respuesta del juez de poses sin el JSON esperado: %r", text[:200])
        return verdict

    async def hands(self, frame_bgr: np.ndarray) -> HandVerdict | None:
        prompt = BOOK.text(HANDS_PROMPT_ID, HANDS_PROMPT)
        text = await self._ask("manos", prompt, HANDS_QUESTION, frame_bgr)
        if text is None:
            return None
        verdict = parse_hand_verdict(text)
        if verdict is None:
            logger.warning("Respuesta del juez de manos sin el JSON esperado: %r", text[:200])
        return verdict

    async def _ask(
        self, task: str, prompt: str, question: str, frame_bgr: np.ndarray
    ) -> str | None:
        """La foto y la pregunta a Gemini; el texto de la respuesta o ``None``. Nunca lanza."""
        llm = self._llm
        if llm is None:
            return None
        started = time.monotonic()
        try:
            completion = await asyncio.wait_for(
                self._complete(llm, prompt, question, frame_bgr), timeout=self._timeout_s
            )
        except TimeoutError:
            logger.warning(
                "El juez de %s no contestó en %.1f s: decide lo local", task, self._timeout_s
            )
            return None
        except Exception as exc:  # noqa: BLE001 - sin juez, decide lo local
            logger.warning("El juez de %s falló (%s): decide lo local", task, exc)
            return None
        finally:
            self.last_seconds = time.monotonic() - started
        if completion is None:
            return None
        logger.info(
            "Juez de %s: %.2f s (%s tokens de entrada)",
            task,
            self.last_seconds,
            completion.prompt_tokens if completion.prompt_tokens is not None else "?",
        )
        return completion.content

    async def _complete(
        self, llm: _VisionLLM, prompt: str, question: str, frame_bgr: np.ndarray
    ) -> Completion | None:
        frame = await asyncio.to_thread(_encode, frame_bgr, self._width, self._quality)
        if frame is None:
            logger.info("El juez no pudo codificar la foto: decide lo local")
            return None
        self.calls += 1
        messages: list[Message] = [system(prompt), user_with_image(question, frame)]
        return await llm.complete(messages)


def _encode(frame_bgr: np.ndarray, width: int, quality: int) -> Frame | None:
    """La foto reducida a ``width`` de ancho y en JPEG (en un hilo; nunca se guarda)."""
    from sonia.vision.camera import encode_frame

    return encode_frame(frame_bgr, width, quality)


# ---------------------------------------------------------------------------
# Respuestas
# ---------------------------------------------------------------------------


def parse_pose_verdict(text: str) -> PoseVerdict | None:
    """``{"personas": N, "brazos_arriba": n, ...}`` → :class:`PoseVerdict`. ``None`` si no cuadra.

    Sin ``personas`` válido no hay veredicto. Las cuentas, sin negativos y sin pasar de
    ``personas``; las claves que no son poses del juego (``ninguna`` incluida) se ignoran, y
    una pose sin cuenta válida queda fuera (el juego usa entonces su recuento local).
    """
    data = _json_object(text)
    if data is None:
        return None
    people = _count(data.get("personas"))
    if people is None:
        return None
    counts: dict[str, int] = {}
    for key in POSE_KEYS:
        value = _count(data.get(key))
        if value is not None:
            counts[key] = min(value, people)
    return PoseVerdict(people, counts)


def parse_hand_verdict(text: str) -> HandVerdict | None:
    """``{"manos": ["piedra", ...]}`` → :class:`HandVerdict`. ``None`` si no cuadra.

    Las formas desconocidas se descartan; una lista vacía (o solo con desconocidas) es que
    ninguna mano hace un gesto claro.
    """
    data = _json_object(text)
    if data is None:
        return None
    hands = data.get("manos")
    if not isinstance(hands, list):
        return None
    shapes = tuple(shape for shape in (_shape(item) for item in hands) if shape is not None)
    return HandVerdict(shapes)


def _json_object(text: str) -> dict[str, Any] | None:
    """El objeto JSON de la respuesta, aunque venga entre ```` ``` ```` o con texto alrededor."""
    text = text or ""
    match = _JSON_OBJECT.search(text)
    if match is not None:
        try:
            data: Any = json.loads(match.group(0))
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            return data
    # Más de un objeto o texto con llaves: el primero que se lea entero.
    decoder = json.JSONDecoder()
    for start in (i for i, char in enumerate(text) if char == "{"):
        try:
            data, _ = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def _count(value: Any) -> int | None:
    """Un número de personas: entero, sin negativos. ``None`` si no es un número."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float) and value == value and abs(value) != float("inf"):
        return max(0, round(value))
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return max(0, int(value.strip()))
    return None


def _shape(value: Any) -> HandShape | None:
    if not isinstance(value, str):
        return None
    plain = unicodedata.normalize("NFKD", value.strip().lower())
    plain = "".join(char for char in plain if not unicodedata.combining(char))
    return _SHAPES.get(plain)
