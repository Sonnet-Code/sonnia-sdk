"""Types and interfaces shared by every module of the orchestrator.

This file is the contract between modules (GPT-Live engine, vision, actions,
WebSocket): each one implements or consumes these types and does not depend
on the internals of the others.
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

#: Default microphone sample rate (the one used by GPT-Live sessions).
INPUT_SAMPLE_RATE = 24_000

#: Mono float32 audio in the range [-1, 1].
AudioArray = npt.NDArray[np.float32]


@dataclass(slots=True)
class AudioChunk:
    """A chunk of Sonnia's voice, ready to be sent to the avatar.

    ``pcm`` is mono PCM s16le at the GPT-Live session rate, the one announced
    to Unity in the ``hello`` message.
    """

    pcm: bytes
    sample_rate: int
    is_last: bool = False

    @property
    def duration(self) -> float:
        return len(self.pcm) / 2 / self.sample_rate


# ---------------------------------------------------------------------------
# Assistant states (sent to Unity as they are)
# ---------------------------------------------------------------------------


class AssistantState(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


# ---------------------------------------------------------------------------
# Vision
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Frame:
    """A camera snapshot, already downscaled and encoded, ready for the model."""

    data: bytes
    mime: Literal["image/jpeg", "image/png"] = "image/jpeg"
    width: int = 0
    height: int = 0
    captured_at: float = 0.0  # time.monotonic()

    def to_data_url(self) -> str:
        import base64

        return f"data:{self.mime};base64,{base64.b64encode(self.data).decode('ascii')}"


# ---------------------------------------------------------------------------
# Language model
# ---------------------------------------------------------------------------

#: A message in OpenAI format (``role`` + ``content``).
Message = dict[str, Any]


@dataclass(slots=True)
class TextDelta:
    text: str


@dataclass(slots=True)
class TurnDone:
    """The model finished its turn with text. ``content`` is the full text."""

    content: str
    reasoning_content: str | None = None
    finish_reason: str | None = None


LLMEvent = TextDelta | TurnDone


# ---------------------------------------------------------------------------
# Stage interfaces
# ---------------------------------------------------------------------------


@runtime_checkable
class CameraSource(Protocol):
    async def capture(self) -> Frame | None:
        """Returns a recent snapshot, or ``None`` if there is no camera."""
        ...


#: Handler of an action: receives the already validated arguments and a context.
ActionHandler = Callable[["ActionContext", dict[str, Any]], Awaitable["ActionResult"]]


@dataclass(slots=True)
class ActionResult:
    """Result of an action.

    ``text`` goes back to the model as the result of the tool call. ``image``
    (if any) is attached for the model as an image in a later user message,
    because tool results in the OpenAI format only accept text.
    """

    text: str
    image: Frame | None = None


@dataclass(slots=True)
class ActionSpec:
    """Single definition of an action. It is translated into an OpenAI tool and an MCP tool."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema of the arguments object
    handler: ActionHandler


class AvatarLink(Protocol):
    """What actions can ask of the avatar (implemented by the WS hub)."""

    async def show_image(
        self, *, image_id: str, source: str, mime: str, data: bytes, caption: str | None
    ) -> None: ...
    async def hide_image(self) -> None: ...


@dataclass(slots=True)
class ActionContext:
    """Context that action handlers receive."""

    camera: CameraSource | None
    avatar: AvatarLink | None
    gallery_dir: str
    last_frame: Frame | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    #: Images uploaded from the panel (``GALLERY_UPLOAD_DIR``); empty = none.
    gallery_upload_dir: str = ""
