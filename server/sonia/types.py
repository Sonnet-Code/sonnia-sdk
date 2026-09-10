"""Tipos e interfaces compartidos por todos los módulos del orquestador.

Este archivo es el contrato entre etapas. Cada etapa (VAD, STT, LLM, TTS,
visión, acciones, WebSocket) implementa o consume estos tipos y no depende de
los detalles internos de las demás.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, Protocol, runtime_checkable

import numpy as np
import numpy.typing as npt

# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------

#: Tasa de muestreo del micrófono y de todo lo que entra al VAD y al STT.
INPUT_SAMPLE_RATE = 16_000

#: Audio mono en float32 en el rango [-1, 1].
AudioArray = npt.NDArray[np.float32]


@dataclass(slots=True)
class Utterance:
    """Un turno completo del usuario, tal como sale del detector de voz."""

    audio: AudioArray
    sample_rate: int = INPUT_SAMPLE_RATE
    started_at: float = 0.0  # time.monotonic() cuando empezó a hablar
    ended_at: float = 0.0  # time.monotonic() cuando terminó
    level: float = 0.0  # RMS medio de los bloques con voz (0..1)

    @property
    def duration(self) -> float:
        return len(self.audio) / self.sample_rate


@dataclass(slots=True)
class AudioChunk:
    """Fragmento de audio sintetizado, listo para enviarse al avatar.

    ``pcm`` es PCM s16le mono. ``sample_rate`` lo decide el motor de TTS
    (OmniVoice produce 24 kHz) y se anuncia a Unity en el mensaje ``hello``.
    """

    pcm: bytes
    sample_rate: int
    is_last: bool = False

    @property
    def duration(self) -> float:
        return len(self.pcm) / 2 / self.sample_rate


# ---------------------------------------------------------------------------
# Estados del asistente (se envían tal cual a Unity)
# ---------------------------------------------------------------------------


class AssistantState(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


# ---------------------------------------------------------------------------
# Visión
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Frame:
    """Una captura de cámara ya reducida y codificada, lista para el modelo."""

    data: bytes
    mime: Literal["image/jpeg", "image/png"] = "image/jpeg"
    width: int = 0
    height: int = 0
    captured_at: float = 0.0  # time.monotonic()

    def to_data_url(self) -> str:
        import base64

        return f"data:{self.mime};base64,{base64.b64encode(self.data).decode('ascii')}"


# ---------------------------------------------------------------------------
# Modelo de lenguaje
# ---------------------------------------------------------------------------

#: Un mensaje en formato OpenAI (``role`` + ``content`` o ``tool_calls``).
Message = dict[str, Any]


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class TextDelta:
    text: str


@dataclass(slots=True)
class ToolCallsEvent:
    """El modelo terminó su turno pidiendo ejecutar acciones."""

    calls: list[ToolCall]
    #: Contenido de razonamiento (Kimi y otros lo devuelven y esperan que se
    #: reenvíe en el mensaje del asistente al continuar tras las tool calls).
    reasoning_content: str | None = None
    #: Texto que el modelo emitió antes de las tool calls, si lo hubo.
    content: str = ""


@dataclass(slots=True)
class TurnDone:
    """El modelo terminó su turno con texto. ``content`` es el texto completo."""

    content: str
    reasoning_content: str | None = None
    finish_reason: str | None = None


LLMEvent = TextDelta | ToolCallsEvent | TurnDone


# ---------------------------------------------------------------------------
# Visemas (lip-sync)
# ---------------------------------------------------------------------------

#: Conjunto de visemas Oculus/Ready Player Me. Unity los mapea a blendshapes.
VisemeId = Literal[
    "sil", "PP", "FF", "TH", "DD", "kk", "CH", "SS", "nn", "RR", "aa", "E", "ih", "oh", "ou"
]


@dataclass(slots=True)
class VisemeFrame:
    t: float  # segundos desde el inicio de la frase
    viseme: VisemeId
    weight: float = 1.0


# ---------------------------------------------------------------------------
# Interfaces de las etapas
# ---------------------------------------------------------------------------


@runtime_checkable
class SpeechToText(Protocol):
    async def transcribe(self, utterance: Utterance) -> str:
        """Devuelve el texto transcrito (cadena vacía si no hay habla)."""
        ...


@runtime_checkable
class TextToSpeech(Protocol):
    @property
    def sample_rate(self) -> int: ...

    def synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        """Sintetiza ``text`` y produce chunks PCM en streaming."""
        ...


@runtime_checkable
class CameraSource(Protocol):
    async def capture(self) -> Frame | None:
        """Devuelve una captura reciente o ``None`` si no hay cámara."""
        ...


#: Handler de una acción: recibe los argumentos ya validados y un contexto.
ActionHandler = Callable[["ActionContext", dict[str, Any]], Awaitable["ActionResult"]]


@dataclass(slots=True)
class ActionResult:
    """Resultado de una acción.

    ``text`` vuelve al modelo como resultado de la tool call. ``image`` (si la
    hay) se adjunta al modelo como imagen en un mensaje de usuario posterior,
    porque los resultados de herramientas del formato OpenAI solo aceptan texto.
    """

    text: str
    image: Frame | None = None


@dataclass(slots=True)
class ActionSpec:
    """Definición única de una acción. Se traduce a tool de OpenAI y a tool MCP."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema del objeto de argumentos
    handler: ActionHandler


class AvatarLink(Protocol):
    """Lo que las acciones pueden pedirle al avatar (implementado por el hub WS)."""

    async def show_image(
        self, *, image_id: str, source: str, mime: str, data: bytes, caption: str | None
    ) -> None: ...
    async def hide_image(self) -> None: ...


@dataclass(slots=True)
class ActionContext:
    """Contexto que reciben los handlers de acciones."""

    camera: CameraSource | None
    avatar: AvatarLink | None
    gallery_dir: str
    last_frame: Frame | None = None
    extra: dict[str, Any] = field(default_factory=dict)
