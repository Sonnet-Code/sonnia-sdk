"""Tipos e interfaces compartidos por todos los módulos del orquestador.

Este archivo es el contrato entre módulos (motor GPT-Live, visión, acciones,
WebSocket): cada uno implementa o consume estos tipos y no depende de los
detalles internos de los demás.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, Protocol, runtime_checkable

import numpy as np
import numpy.typing as npt

# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------

#: Tasa de muestreo por defecto del micrófono (la de las sesiones de GPT-Live).
INPUT_SAMPLE_RATE = 24_000

#: Audio mono en float32 en el rango [-1, 1].
AudioArray = npt.NDArray[np.float32]


@dataclass(slots=True)
class AudioChunk:
    """Fragmento de la voz de Sonia, listo para enviarse al avatar.

    ``pcm`` es PCM s16le mono a la tasa de la sesión de GPT-Live, la que se
    anuncia a Unity en el mensaje ``hello``.
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

#: Un mensaje en formato OpenAI (``role`` + ``content``).
Message = dict[str, Any]


@dataclass(slots=True)
class TextDelta:
    text: str


@dataclass(slots=True)
class TurnDone:
    """El modelo terminó su turno con texto. ``content`` es el texto completo."""

    content: str
    reasoning_content: str | None = None
    finish_reason: str | None = None


LLMEvent = TextDelta | TurnDone


# ---------------------------------------------------------------------------
# Interfaces de las etapas
# ---------------------------------------------------------------------------


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
