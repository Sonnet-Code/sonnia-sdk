"""GPT-Live voice engine: joins the microphone, the GPT-Live session, the actions and the avatar.

GPT-Live is full duplex: it hears the microphone continuously, decides on its
own when it is being spoken to and when to answer, goes quiet when interrupted
and streams its voice back. This engine only:

- Sends it the microphone as is, always (silence only when the panel mutes it
  or below the noise gate ``LIVE_GATE_RMS``).
- Translates its voice into the avatar protocol: GPT-Live sends audio nonstop,
  also when it is quiet, so each voiced stretch separated by a silence is an
  utterance (``speech_start`` + binary frames + ``speech_end``), and the
  transcript travels as a partial ``transcript``.
- Infers the avatar state (``listening``, ``thinking``, ``speaking``,
  ``idle``) from what arrives: GPT-Live does not emit turn events.
- Runs the actions requested by the Responses backend it delegates to
  (``response.event`` with ``function_call``) and returns the result.
- Gives it eyes: when someone starts speaking, describes the camera with a
  vision model and passes it on as a silent note.
- Keeps the session alive: reconnects with growing backoff if it drops and
  starts a clean session after a while with nobody around (kiosk mode).

Golden rule: nothing that happens in a session brings the engine down. A failure is
logged, the avatar client is told and the engine reconnects.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import json
import logging
import re
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any, Protocol

from sonia.actions.gallery import Gallery
from sonia.actions.moves import MoveCatalog
from sonia.actions.registry import ActionRegistry
from sonia.busy import TEXT_SEARCH, TEXT_THINK, BusyBoard, BusyKind
from sonia.clock import Clock, clock_for, place_of, resolve_timezone, spoken_now
from sonia.config import Settings
from sonia.live.audio import MicGate, rms
from sonia.live.client import APPEND_MAX_CHARS, LiveClient, WsConnect, describe_error
from sonia.live.prompts import CAMERA_NOTE_PREFIX, build_session_config, gallery_note
from sonia.live.vision import VisionNarrator
from sonia.live.voicecache import VoiceCache
from sonia.persona import KnowledgeSource
from sonia.showcase import Showcase
from sonia.trivia import TriviaGame
from sonia.types import (
    ActionContext,
    ActionResult,
    AssistantState,
    AudioArray,
    AudioChunk,
    AvatarLink,
    CameraSource,
    Frame,
)
from sonia.vision.policy import VisionPolicy
from sonia.ws import protocol as p
from sonia.ws.hub import MessageCallback

__all__ = ["LiveEngine"]

logger = logging.getLogger(__name__)

#: Margin over the estimated duration when waiting for the avatar client's ``playback_done``.
PLAYBACK_GRACE_S = 1.0

#: After Sonnia goes quiet, wait this long before changing the avatar state: a
#: pause between two sentences of the same answer must not go through ``idle``.
SPEECH_HOLD_S = 0.6

#: How long it stays in ``thinking`` waiting for GPT-Live to answer.
RESPONSE_WAIT_S = 4.0

#: A delegated task that does not finish in this time is given up as lost.
DELEGATION_TIMEOUT_S = 90.0

#: A delegated task that takes longer than this is reported to the avatar client
#: (``activity`` ``think``) so she thinks with her hand on her chin (the
#: Matrix-style rain is only for web searches). In real sessions, tasks with
#: actions took 3.4 s at the median (4.8 s at the 75th percentile): with less, the
#: gesture would show up on almost all of them (showing an image, for example)
#: and not only on the ones that really take long.
SLOW_TASK_S = 5.0

#: Prefix of the waiting-indicator keys (``sonia.busy``) the engine sets: one per
#: delegated task (``think``) and another while that task searches the web (``search``).
BUSY_PREFIX = "live:"

#: "Thinking…" only shows if the delegated task is still running after this: one that
#: ends right away does not light up the pill and does not flicker (the other waits show at once).
THINK_DELAY_S = 0.3

#: Window in which Sonnia's next voice is taken as the requested idle bit.
AMBIENT_WAIT_S = 8.0
#: After a stretch of an idle line, whatever GPT-Live says within this time is its
#: continuation: a long moment came out in two stretches and the second one no
#: longer went as an idle line (the avatar switched to "speaking").
AMBIENT_CONTINUE_S = 2.5

#: Audio lead over real time above which a warning is logged.
LEAD_WARN_S = 1.5

#: Maximum wait for a capture to describe.
CAPTURE_TIMEOUT_S = 3.0

#: Before the session expires, another one is opened at the next quiet moment.
EXPIRY_MARGIN_S = 120.0

#: A session that lasted longer than this resets the wait between reconnections.
HEALTHY_SESSION_S = 60.0

#: Roughly 16,000 tokens: above this a warning is logged.
INSTRUCTIONS_WARN_CHARS = 50_000

#: Text that goes with the photo requested by the ``look`` action in the backend.
LOOK_IMAGE_TEXT = "[Camera photo requested by the look action]"

#: How a typed text is passed to GPT-Live (``text_input`` or the panel).
TEXT_INPUT_TEMPLATE = (
    'A user has typed this to you (they did not say it out loud): "{text}". Answer them '
    "out loud now as if they had said it."
)

#: Instruction after an interruption from the avatar client (for example, touching the screen).
INTERRUPT_TEXT = "The user has interrupted you: stop talking now and listen to what they say."

#: How a panel announcement is passed so she says it out loud.
ANNOUNCE_TEMPLATE = (
    "Announcement from the people who run you, for everyone around. Say it out loud now, in "
    'your own words but without changing the facts: "{text}"'
)

#: How the notes of the day are passed when they change during a session.
NOTES_TEMPLATE = (
    "Today's notes from the people who run you (they are newer than your knowledge base; "
    "if they clash, these win): {text}"
)
NOTES_CLEARED_TEXT = "The people who run you have removed today's notes: they no longer apply."

#: How GPT-Live is told that its delegated task ended without a result: it does not
#: find out on its own and kept stalling ("I'm working out how to explain it").
DELEGATION_FAILED_TEXT = (
    "Your backend could not finish the task you gave it and you do not have the result. Tell "
    "the user now in one sentence, without making up the answer, and offer to try another "
    "way or to tell them what you do know."
)

#: RMS level (0..1) above which a chunk of GPT-Live's voice counts as voice.
#: GPT-Live sends audio nonstop, also when it is quiet (digital silence, 0):
#: utterances to the avatar client are split by level, not by gaps in the stream.
OUTPUT_VOICE_RMS = 0.003

#: Per-block decay of the microphone level meter.
MIC_LEVEL_DECAY = 0.85

#: Level below which a block counts as absolute silence.
MIC_SILENCE_RMS = 0.0005

#: Seconds the microphone keeps sending silence to GPT-Live after a recorded
#: line (the avatar client's buffer and the speaker's tail in the room).
CLIP_ECHO_TAIL_S = 0.8

#: How an idle-animation bit is requested.
SHOWCASE_TEMPLATE = (
    "Nobody is talking to you right now. To liven things up, say out loud, only once and as "
    'is, this sentence: "{text}"'
)

#: How GPT-Live is asked for a moment (``{focus}``: what it draws on).
MOMENT_TEMPLATE = (
    "Nobody is talking to you right now. To liven things up, say out loud one short, new "
    "sentence, different from the ones you have already said, that invites the people "
    "passing by to come and talk to you. {focus} Just say it: do not greet as if someone had "
    "spoken to you and do not explain why you say it."
)

#: What each moment draws on, taking turns among the available ones. Not the time:
#: she said it too often.
MOMENT_FOCUS = {
    "camera": (
        "Use what your camera sees right now, in a friendly tone: at most a piece of "
        "clothing, a badge or an object, never the body, age, skin or anything personal. "
        "What it sees: {text}"
    ),
    "invitation": (
        "Suggest something specific to try: playing the trivia, asking you anything, asking "
        "you to dance, or interrupting you to see that you talk in real time."
    ),
}


def showcase_prompt(text: str) -> str:
    """How GPT-Live is asked for a fixed idle-animation line."""
    return SHOWCASE_TEMPLATE.format(text=text)


def moment_focus(kind: str, text: str = "") -> str:
    """What a moment draws on (``camera`` or ``invitation``), with its text."""
    return MOMENT_FOCUS[kind].format(text=text)


def moment_prompt(focus: str) -> str:
    """How GPT-Live is asked for a moment."""
    return MOMENT_TEMPLATE.format(focus=focus)


#: Cap for preparing a moment (the photo and its description): meanwhile no other bit comes out.
MOMENT_PREP_S = 15.0


class HubLike(AvatarLink, Protocol):
    """What the engine uses from the WebSocket hub (and the avatar actions)."""

    @property
    def client_count(self) -> int: ...
    def on(self, type: str, callback: MessageCallback) -> None: ...
    async def broadcast_json(self, msg: dict[str, Any]) -> None: ...
    async def broadcast_bytes(self, data: bytes) -> None: ...
    async def send_audio(self, utterance_id: int, chunk: AudioChunk) -> None: ...
    async def set_sticky(self, key: str, msg: dict[str, Any]) -> None: ...
    def clear_sticky(self, key: str) -> None: ...


def _log_stage_failure(msg: str, *args: Any) -> None:
    """One readable line per failure; the traceback only with ``LOG_LEVEL=DEBUG``."""
    logger.error(msg, *args, exc_info=logger.isEnabledFor(logging.DEBUG))


@dataclass(slots=True)
class _Segment:
    """A continuous stretch of Sonnia's voice: one utterance for the avatar client."""

    uid: int
    ambient: bool
    parts: list[str] = field(default_factory=list)
    seconds: float = 0.0
    #: Silence received after the last voice: sent only if the voice comes back
    #: (a pause within the utterance); if the utterance ends, it is dropped.
    held_silence: list[bytes] = field(default_factory=list)

    @property
    def text(self) -> str:
        # Without "[laugh]" or "[sigh]": it goes to the subtitles people see.
        return clean_transcript("".join(self.parts))


@dataclass(slots=True)
class _Delegation:
    """A task GPT-Live delegated to the Responses backend."""

    id: str
    created_at: float
    rounds: int = 0
    #: Actions running (result not sent yet).
    running_calls: int = 0
    #: Actions requested in the backend's current response.
    calls_in_response: int = 0
    #: Actions requested over the whole task (for the log).
    calls_total: int = 0
    #: The backend's current response has finished (``response.completed``...).
    response_done: bool = False
    text: list[str] = field(default_factory=list)
    #: Web searches (``web_search``) in progress, by item id.
    searches: set[str] = field(default_factory=set)


#: Nested events that close a backend response.
_TERMINAL_RESPONSE_EVENTS = frozenset(
    {"response.completed", "response.failed", "response.incomplete", "response.cancelled", "error"}
)


def _is_web_search_event(kind: Any, item: Any) -> bool:
    """Backend events of a web search: its own or those of its output item."""
    if isinstance(kind, str) and kind.startswith("response.web_search_call."):
        return True
    return (
        kind in ("response.output_item.added", "response.output_item.done")
        and isinstance(item, dict)
        and item.get("type") == "web_search_call"
    )


class LiveEngine:
    """Sonnia's engine on top of GPT-Live. Every dependency comes in through the constructor."""

    def __init__(
        self,
        settings: Settings,
        *,
        hub: HubLike,
        registry: ActionRegistry | None = None,
        camera: CameraSource | None = None,
        vision_policy: VisionPolicy | None = None,
        narrator: VisionNarrator | None = None,
        showcase: Showcase | None = None,
        connect: WsConnect | None = None,
        knowledge_dir: KnowledgeSource = None,
        voice_cache: VoiceCache | None = None,
        clock: Clock | None = None,
        tick_s: float = 0.05,
    ) -> None:
        self._settings = settings
        self._voice_cache = voice_cache
        self._live = settings.live
        self._hub = hub
        self._registry = registry
        self._camera = camera
        self._policy = vision_policy or VisionPolicy(settings.vision, settings.llm.supports_vision)
        self._narrator = narrator
        self._connect = connect
        self._knowledge_dir = knowledge_dir
        self._tick = max(0.01, tick_s)
        self._rate = int(self._live.sample_rate)
        #: What GPT-Live hears on each block: all the microphone measures together.
        self._mic = MicGate(
            threshold=self._live.gate_rms,
            hold_ms=self._live.gate_hold_ms,
            comfort_rms=self._live.comfort_noise_rms,
            silence_rms=MIC_SILENCE_RMS,
        )

        self._client: LiveClient | None = None
        #: With ``False`` no session is opened: GPT-Live off, no spending.
        self._active = True
        self._active_event = asyncio.Event()
        self._active_event.set()
        self._state = AssistantState.IDLE
        self._utterance_counter = 0
        self._tasks: set[asyncio.Task[Any]] = set()

        # Sonnia's voice.
        self._segment: _Segment | None = None
        self._pending_assistant: list[str] = []
        self._last_audio_at = 0.0
        self._last_voice_at = 0.0
        self._playback_end_at = 0.0
        self._last_closed_uid = 0
        self._last_closed_deadline = 0.0
        self._playback_done_id = 0
        self._audible = False
        self._settle_after = 0.0
        self._discard_audio = False
        self._lead_warned = False

        # The user's voice.
        self._user_parts: list[str] = []
        self._user_turn_open = False
        self._user_turn_started_at = 0.0
        self._last_input_at = 0.0
        self._turn_level = 0.0
        self._expect_response_until = 0.0

        # Microphone (for the panel).
        self._mic_manual_mute = False
        #: Until when the microphone sends silence because a recorded line is playing.
        self._clip_mute_until = 0.0
        self._clip_uid = 0
        self._mic_level = 0.0
        self._last_mic_at = 0.0
        self._last_sound_at = 0.0

        # Backend and session.
        self._delegations: dict[str, _Delegation] = {}
        self._last_delegation_id: str | None = None
        #: The last thing told to the avatar client in ``activity``.
        self._activity = "none"
        #: ``event_id`` of the commands sent to the backend → delegation, to
        #: close the task if the API answers one of them with ``error``.
        self._command_owner: dict[str, str] = {}
        self._session_conversation = False
        self._session_started_at = 0.0
        self._context_full = False
        self._restarting = False
        self._last_activity = time.monotonic()
        #: Notes of the day the operators write in the panel.
        self._notes = ""
        self._usage_closed_s = 0.0
        self._usage_session_s = 0.0
        self._context_ratio: float | None = None
        self.last_error = ""

        # Camera and on-screen image.
        self._last_frame: Frame | None = None
        self._vision_task: asyncio.Task[None] | None = None
        self._last_vision_at = float("-inf")
        self._camera_ok: bool | None = None
        self._image_hide_task: asyncio.Task[None] | None = None
        #: Gallery images known to the open session and those of the last check.
        self._session_gallery: list[str] | None = None
        self._gallery_seen: list[str] | None = None
        #: ``[Gallery]`` note waiting for a quiet moment, with the list it reports.
        self._pending_gallery: tuple[str, list[str]] | None = None

        # Idle animation.
        # Always loaded (if there is material) so it can be turned on from the panel.
        show = settings.showcase
        if showcase is None:
            showcase = Showcase.from_dir(
                settings.showcase_dir,
                dance_chance=show.dance_chance,
                gesture_chance=show.gesture_chance,
                moment_chance=show.moment_chance,
            )
        self._showcase = showcase if showcase.enabled else None
        self._showcase_enabled = show.enabled
        self._next_showcase_at = time.monotonic() + max(0.0, show.first_delay_seconds)
        self._ambient_expected_until = 0.0
        #: Idle moments requested: what the next one draws on takes turns.
        self._moment_turn = 0

        #: On-screen waiting indicator (``sonia.busy``) of the delegated tasks.
        self._busy_board = BusyBoard(hub.broadcast_json)

        # Trivia mode (``sonia.trivia``): GPT-Live runs it; the answer key and the screen live here.
        self._trivia: TriviaGame | None = (
            TriviaGame(
                settings.trivia,
                settings.trivia_file,
                host=self,
                screen=hub,
            )
            if settings.trivia.enabled
            else None
        )

        # Date and time (``TIMEZONE``), for the instructions of each session.
        tz = resolve_timezone(settings.timezone)
        self._place = place_of(settings.timezone)
        self._now: Clock = clock or clock_for(tz)

        # Moves by voice (``play_animation``): the avatar client sends the catalog when it connects.
        self._moves = MoveCatalog(hub.broadcast_json)
        hub.on(p.MSG_ANIMATIONS, self._moves.update)

        hub.on(p.MSG_CLIENT_HELLO, self._on_client_hello)
        hub.on(p.MSG_INTERRUPT, lambda msg: self._spawn(self._on_interrupt(), "interrupt"))
        hub.on(p.MSG_PLAYBACK_DONE, self._on_ws_playback_done)
        hub.on(p.MSG_TEXT_INPUT, self._on_ws_text_input)
        on_frame = getattr(camera, "on_frame", None)
        if callable(on_frame):
            hub.on(p.MSG_CAMERA_FRAME, lambda msg: _forward_camera_frame(on_frame, msg))

    # -- properties ----------------------------------------------------------

    @property
    def state(self) -> AssistantState:
        return self._state

    @property
    def session_id(self) -> str:
        return self._client.session_id if self._client is not None else ""

    @property
    def connected(self) -> bool:
        return self._client is not None

    @property
    def last_frame(self) -> Frame | None:
        return self._last_frame

    @property
    def active(self) -> bool:
        return self._active

    @property
    def showcase(self) -> Showcase | None:
        return self._showcase

    @property
    def trivia(self) -> TriviaGame | None:
        return self._trivia

    @property
    def busy_board(self) -> BusyBoard:
        """The on-screen waiting indicator (``sonia.busy``)."""
        return self._busy_board

    def _playing(self) -> bool:
        """Is there a trivia on screen? (pauses the idle animation and session renewal)"""
        return self._trivia is not None and self._trivia.active

    # -- input ---------------------------------------------------------------

    async def push_mic(self, block: AudioArray) -> None:
        """A microphone block (mono float32 at the session rate).

        It always goes to GPT-Live, also while Sonnia speaks: that way she can be
        interrupted by speaking. :class:`MicGate` decides whether GPT-Live hears the
        block or a very soft noise of the same size (microphone muted, recorded
        line, noise gate, silence), because GPT-Live needs a continuous stream and
        lags behind with absolute zeros. Without a session, the block is dropped.
        """
        now = time.monotonic()
        level = rms(block)
        self._mic_level = max(level, self._mic_level * MIC_LEVEL_DECAY)
        self._last_mic_at = now
        if level > MIC_SILENCE_RMS:
            self._last_sound_at = now
        client = self._client
        if client is None or self._restarting:
            return
        echo = now < self._clip_mute_until
        if self._user_turn_open and not (self._mic_manual_mute or echo):
            self._turn_level = max(self._turn_level, level)
        pcm = self._mic.pcm(block, level, now, muted=self._mic_manual_mute, echo=echo)
        try:
            await client.append_audio(pcm)
        except Exception as exc:  # noqa: BLE001 - the session reconnects on its own
            logger.debug("Could not send audio to GPT-Live: %s", exc)

    async def submit_text(self, text: str) -> None:
        """A typed text (``text_input`` from the avatar client or the ``sonia chat`` console)."""
        text = text.strip()
        if not text:
            return
        now = time.monotonic()
        self._touch()
        self._session_conversation = True
        self._ambient_expected_until = 0.0
        await self._hub.broadcast_json(p.msg_transcript("user", text, True))
        logger.info("User (text): %s", text)
        client = self._client
        if client is None:
            logger.warning("Text ignored: GPT-Live is not connected")
            await self._hub.broadcast_json(p.msg_error("GPT-Live is not connected"))
            return
        try:
            # ``instructions.append`` does not make her speak; ``commentary`` does.
            await client.append_commentary(TEXT_INPUT_TEMPLATE.format(text=text))
        except Exception as exc:  # noqa: BLE001
            _log_stage_failure("Could not pass the text to GPT-Live: %s", exc)
            return
        self._expect_response_until = now + RESPONSE_WAIT_S
        if not self._audible:
            await self._set_state(AssistantState.THINKING)

    def notify_playback_done(self, utterance_id: int) -> None:
        """The avatar client (or the local player) finished playing ``utterance_id``."""
        self._playback_done_id = max(self._playback_done_id, utterance_id)
        if utterance_id == self._clip_uid:
            # The avatar client knows better than the estimate when the recorded line ended.
            self._clip_mute_until = time.monotonic() + CLIP_ECHO_TAIL_S

    async def wait_idle(self, limit_s: float | None = None) -> bool:
        """Waits until Sonnia is not speaking, not thinking and nobody is talking."""
        deadline = None if limit_s is None else time.monotonic() + limit_s
        while not self._is_idle(time.monotonic()):
            if deadline is not None and time.monotonic() >= deadline:
                return False
            await asyncio.sleep(0.05)
        return True

    # -- hub callbacks -------------------------------------------------------

    def _on_ws_playback_done(self, msg: dict[str, Any]) -> None:
        utterance_id = msg.get("utterance_id")
        if isinstance(utterance_id, int) and not isinstance(utterance_id, bool):
            self.notify_playback_done(utterance_id)

    def _on_ws_text_input(self, msg: dict[str, Any]) -> None:
        text = msg.get("text")
        if isinstance(text, str) and text.strip():
            self._spawn(self.submit_text(text), "text-input")

    # -- main loop -----------------------------------------------------------

    async def run(self) -> None:
        """Keeps a GPT-Live session open. Only ends when cancelled."""
        live = self._live
        logger.info(
            "GPT-Live engine running (model %s, voice %s, backend %s, vision %s)",
            live.model,
            live.voice,
            live.backend_model,
            "yes" if self._narrator is not None and self._policy.enabled else "no",
        )
        await self._hub.broadcast_json(p.msg_state(self._state))
        ticker = asyncio.create_task(self._tick_loop(), name="sonia-live-tick")
        gallery: asyncio.Task[None] | None = None
        if self._settings.gallery_watch_seconds > 0:
            gallery = asyncio.create_task(
                self._gallery_loop(self._settings.gallery_watch_seconds), name="sonia-gallery"
            )
        delay = live.reconnect_min_seconds
        try:
            while True:
                if not self._active:
                    await self._active_event.wait()
                    delay = live.reconnect_min_seconds
                started = time.monotonic()
                renewed = False
                try:
                    renewed = await self._run_session()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    _log_stage_failure("GPT-Live session down: %s", exc)
                    self.last_error = str(exc)
                    await self._hub.broadcast_json(p.msg_error(f"GPT-Live: {exc}"))
                if renewed or time.monotonic() - started > HEALTHY_SESSION_S:
                    delay = live.reconnect_min_seconds
                if renewed:
                    continue
                # Any other ending (expiry, content filter, network, a server that
                # closes right after opening) waits before reconnecting: opening
                # sessions unchecked for hours costs money.
                logger.info("Retrying the GPT-Live connection in %.0f s", delay)
                await asyncio.sleep(delay)
                delay = min(max(delay * 2, live.reconnect_min_seconds), live.reconnect_max_seconds)
        finally:
            extra = [task for task in (gallery,) if task is not None]
            for task in (ticker, *extra):
                task.cancel()
            await asyncio.gather(ticker, *extra, return_exceptions=True)
            await self._shutdown()

    async def _run_session(self) -> bool:
        """One session from start to end. Returns whether it ended because the engine renewed it."""
        client = LiveClient(self._live, connect=self._connect)
        clock_text = spoken_now(self._now(), self._place)
        gallery_ids = Gallery(self._settings.gallery_dir, self._settings.gallery_upload_dir).ids()
        config = build_session_config(
            self._settings,
            registry=self._registry,
            gallery_ids=gallery_ids,
            knowledge_dir=self._knowledge_dir,
            notes=self._notes,
            clock_text=clock_text,
        )
        self._session_gallery = self._gallery_seen = gallery_ids
        self._pending_gallery = None
        if len(config["instructions"]) > INSTRUCTIONS_WARN_CHARS:
            logger.warning(
                "The GPT-Live instructions take %d characters: they may go over the limit of "
                "16,384 tokens. Trim assets/knowledge.",
                len(config["instructions"]),
            )
        try:
            await client.start(config)
            self._begin_session(client)
            expires = client.expires_at
            logger.info(
                "GPT-Live session ready (%s%s)",
                client.session_id or "no id",
                f"; expires in {(expires - time.time()) / 60:.0f} min" if expires else "",
            )
            async for event in client.events():
                try:
                    await self._handle_event(event)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Error handling GPT-Live event %s", event.get("type"))
            logger.info(
                "The GPT-Live session ended (%s)", client.close_reason or "connection closed"
            )
            return self._restarting
        finally:
            self._client = None
            # If the engine is shutting down, the reply to the close is not awaited.
            await client.close(wait=False)
            await self._end_session()

    def _begin_session(self, client: LiveClient) -> None:
        self._client = client
        self.last_error = ""
        self._usage_session_s = 0.0
        self._context_ratio = None
        self._session_conversation = False
        self._session_started_at = time.monotonic()
        self._context_full = False
        self._restarting = False
        self._lead_warned = False
        self._delegations.clear()
        self._last_delegation_id = None
        self._command_owner.clear()

    async def _end_session(self) -> None:
        """Leaves the avatar client in a consistent state when the session drops."""
        if self._session_started_at:
            lasted = time.monotonic() - self._session_started_at
            self._usage_closed_s += max(self._usage_session_s, lasted)
            self._session_started_at = 0.0
            self._usage_session_s = 0.0
        if self._segment is not None:
            with contextlib.suppress(Exception):
                await self._close_segment(time.monotonic())
        self._pending_assistant = []
        self._discard_audio = False
        self._playback_end_at = min(self._playback_end_at, time.monotonic())
        self._delegations.clear()
        self._user_turn_open = False
        self._user_parts = []
        self._expect_response_until = 0.0
        if self._trivia is not None:
            with contextlib.suppress(Exception):
                await self._trivia.on_session_lost()
        # Without a session nothing is awaited: clear every wait, in case one was left behind.
        with contextlib.suppress(Exception):
            await self._busy_board.clear_prefix("")

    async def _shutdown(self) -> None:
        for task in [*self._tasks, self._vision_task, self._image_hide_task]:
            if task is not None and not task.done():
                task.cancel()
        client, self._client = self._client, None
        if client is not None:
            with contextlib.suppress(Exception):
                await client.close(wait=False)

    # -- GPT-Live events -----------------------------------------------------

    async def _handle_event(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        match kind:
            case "session.output_audio.delta":
                await self._on_output_audio(event)
            case "session.output_transcript.delta":
                await self._on_output_transcript(event)
            case "session.input_transcript.delta":
                await self._on_input_transcript(event)
            case "session.delegation.created":
                await self._on_delegation_created(event)
            case "response.event":
                await self._on_response_event(event)
            case "session.usage.updated":
                self._on_usage(event)
            case "error":
                self.last_error = describe_error(event)
                logger.warning("GPT-Live reported an error: %s", self.last_error)
                self._on_command_error(event)
                await self._on_handoff_error(event)
            case "session.closed":
                logger.info("GPT-Live closed the session (%s)", event.get("reason"))
            case _:
                logger.debug("GPT-Live event: %s", kind)

    async def _on_output_audio(self, event: dict[str, Any]) -> None:
        data = event.get("delta")
        if not isinstance(data, str) or not data:
            return
        try:
            pcm = base64.b64decode(data)
        except (binascii.Error, ValueError):
            logger.debug("GPT-Live audio with invalid base64; dropped")
            return
        if len(pcm) % 2:
            pcm = pcm[:-1]
        if not pcm:
            return
        now = time.monotonic()
        self._last_audio_at = now
        voiced = _pcm16_rms(pcm) >= OUTPUT_VOICE_RMS
        if voiced:
            self._last_voice_at = now
        if self._discard_audio:
            return
        segment = self._segment
        if segment is None:
            if not voiced:
                return  # GPT-Live is quiet: nothing to send to the avatar client
            segment = await self._open_segment(now)
        if not voiced:
            segment.held_silence.append(pcm)
            return
        for chunk in [*segment.held_silence, pcm]:
            seconds = len(chunk) / 2 / self._rate
            segment.seconds += seconds
            self._playback_end_at = max(self._playback_end_at, now) + seconds
            await self._hub.send_audio(segment.uid, AudioChunk(pcm=chunk, sample_rate=self._rate))
        segment.held_silence.clear()
        lead = self._playback_end_at - now
        if lead > LEAD_WARN_S and not self._lead_warned:
            self._lead_warned = True
            logger.warning(
                "GPT-Live is sending its voice %.1f s ahead of real time: when interrupted, "
                "the avatar client will keep playing what it has queued",
                lead,
            )

    async def _open_segment(self, now: float) -> _Segment:
        self._utterance_counter += 1
        ambient = now < self._ambient_expected_until and not self._user_turn_open
        self._ambient_expected_until = 0.0
        segment = _Segment(uid=self._utterance_counter, ambient=ambient)
        segment.parts, self._pending_assistant = self._pending_assistant, []
        self._segment = segment
        self._audible = True
        await self._hub.broadcast_json(
            p.msg_speech_start(segment.uid, segment.text, ambient=ambient)
        )
        if not ambient:
            self._touch()
            self._session_conversation = True
            self._expect_response_until = 0.0
            await self._set_state(AssistantState.SPEAKING)
        if segment.text:
            await self._hub.broadcast_json(p.msg_transcript("assistant", segment.text, False))
        return segment

    async def _close_segment(self, now: float) -> None:
        segment, self._segment = self._segment, None
        if segment is None:
            return
        hub = self._hub
        text = segment.text
        if text:
            await hub.broadcast_json(p.msg_transcript("assistant", text, True))
        await hub.send_audio(segment.uid, AudioChunk(pcm=b"", sample_rate=self._rate, is_last=True))
        await hub.broadcast_json(p.msg_speech_end(segment.uid))
        logger.info(
            "Sonnia (%s%d, %.2f s): %s",
            "ambient, " if segment.ambient else "",
            segment.uid,
            segment.seconds,
            text or "(no transcript)",
        )
        self._last_closed_uid = segment.uid
        self._last_closed_deadline = max(self._playback_end_at, now) + PLAYBACK_GRACE_S
        if segment.ambient and not self._user_turn_open:
            self._ambient_expected_until = max(
                self._ambient_expected_until, now + AMBIENT_CONTINUE_S
            )

    async def _on_output_transcript(self, event: dict[str, Any]) -> None:
        delta = event.get("delta")
        if not isinstance(delta, str) or not delta or self._discard_audio:
            return
        segment = self._segment
        if segment is None:
            # The text can arrive slightly ahead of its audio.
            self._pending_assistant.append(delta)
            return
        segment.parts.append(delta)
        text = segment.text
        await self._hub.broadcast_json(p.msg_transcript("assistant", text, False))

    async def _on_input_transcript(self, event: dict[str, Any]) -> None:
        delta = event.get("delta")
        if not isinstance(delta, str) or not delta:
            return
        if not self._user_turn_open and not delta.strip():
            return
        now = time.monotonic()
        if not self._user_turn_open:
            self._user_turn_open = True
            self._user_turn_started_at = now
            self._user_parts = []
            self._turn_level = 0.0
            self._session_conversation = True
            # Someone is talking: the next thing Sonnia says is an answer.
            self._ambient_expected_until = 0.0
            self._maybe_look(turn_start=True)
        self._user_parts.append(delta)
        self._last_input_at = now
        self._touch()
        if self._trivia is not None:
            self._trivia.on_user_text(now)
        await self._hub.broadcast_json(p.msg_transcript("user", self._user_text, False))
        if not self._audible:
            await self._set_state(AssistantState.LISTENING)

    @property
    def _user_text(self) -> str:
        return clean_transcript("".join(self._user_parts))

    async def _finish_user_turn(self, now: float) -> None:
        self._user_turn_open = False
        text = self._user_text
        self._user_parts = []
        if text:
            await self._hub.broadcast_json(p.msg_transcript("user", text, True))
            logger.info("User (level %.3f): %s", self._turn_level, text)
        if not self._audible:
            self._expect_response_until = now + RESPONSE_WAIT_S
        if self._trivia is not None and text:
            self._trivia.on_user_turn_end(now, self._user_turn_started_at)

    # -- delegation and actions ----------------------------------------------

    async def _on_delegation_created(self, event: dict[str, Any]) -> None:
        delegation = event.get("delegation")
        if not isinstance(delegation, dict) or not isinstance(delegation.get("id"), str):
            return
        delegation_id = delegation["id"]
        target = delegation.get("target")
        now = time.monotonic()
        self._delegations[delegation_id] = _Delegation(delegation_id, now)
        self._last_delegation_id = delegation_id
        self._session_conversation = True
        self._touch()
        # Whatever the delegation brings besides its ids (the task, if the API sends it).
        details = {
            k: v for k, v in delegation.items() if k not in ("id", "type", "target", "response_id")
        }
        logger.info(
            "GPT-Live delegates a task to the backend %s (%s)%s",
            target,
            delegation_id,
            f": {json.dumps(details, ensure_ascii=False)[:300]}" if details else "",
        )
        if self._trivia is not None:
            self._trivia.on_delegation(now)
        await self._update_busy()
        if not self._audible:
            await self._set_state(AssistantState.THINKING)

    async def _on_response_event(self, event: dict[str, Any]) -> None:
        nested = event.get("event")
        if not isinstance(nested, dict):
            return
        kind = nested.get("type")
        item = nested.get("item")
        is_call = (
            kind == "response.output_item.done"
            and isinstance(item, dict)
            and item.get("type") == "function_call"
        )
        delegation_id = event.get("delegation_id") or self._last_delegation_id
        delegation = (
            self._delegations.get(delegation_id) if isinstance(delegation_id, str) else None
        )
        created = False
        if delegation is None and (kind == "response.created" or is_call):
            # New work without ``session.delegation.created`` (lost, or without an id
            # that can be matched): it gets a delegation so it can be continued.
            # Any other late event of a task that is already closed is ignored.
            new_id = delegation_id if isinstance(delegation_id, str) else "no-id"
            delegation = _Delegation(new_id, time.monotonic())
            self._delegations[new_id] = delegation
            self._last_delegation_id = new_id
            created = True

        searching = False
        if delegation is not None and _is_web_search_event(kind, item):
            self._track_search(delegation, kind, nested)
            searching = True
        if created or searching:
            await self._update_busy()
        if kind == "response.created" and delegation is not None:
            delegation.response_done = False
            delegation.calls_in_response = 0
        elif kind == "response.output_text.delta" and delegation is not None:
            delta = nested.get("delta")
            if isinstance(delta, str):
                delegation.text.append(delta)
        elif is_call and isinstance(item, dict):
            self._start_call(delegation, item)
        elif kind in _TERMINAL_RESPONSE_EVENTS:
            if kind != "response.completed":
                logger.warning(
                    "The backend did not finish the task properly (%s): %s",
                    kind,
                    json.dumps(nested.get("response", nested.get("error", "")), ensure_ascii=False)[
                        :300
                    ],
                )
            if delegation is not None:
                delegation.response_done = True
                delegation.searches.clear()
                await self._maybe_continue(delegation)

    def _track_search(self, delegation: _Delegation, kind: Any, nested: dict[str, Any]) -> None:
        """Tracks which backend web searches are still running."""
        item = nested.get("item")
        item_id = nested.get("item_id") or (item.get("id") if isinstance(item, dict) else None)
        key = str(item_id or "web_search")
        done = kind in ("response.web_search_call.completed", "response.output_item.done")
        if done:
            delegation.searches.discard(key)
        elif key not in delegation.searches:
            delegation.searches.add(key)
            logger.info("The backend is searching the web (%s)", delegation.id)

    def _start_call(self, delegation: _Delegation | None, item: dict[str, Any]) -> None:
        name = str(item.get("name") or "")
        call_id = str(item.get("call_id") or "")
        raw = item.get("arguments")
        arguments: dict[str, Any] | None
        try:
            parsed = json.loads(raw) if isinstance(raw, str) and raw.strip() else {}
            arguments = parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            arguments = None
        if arguments is None:
            logger.warning(
                "Action %s with arguments that are not valid JSON: %s", name, str(raw)[:200]
            )
        if delegation is not None:
            delegation.running_calls += 1
            delegation.calls_in_response += 1
            delegation.calls_total += 1
        self._spawn(
            self._run_call(self._client, delegation, name, call_id, arguments), f"action-{name}"
        )

    async def _run_call(
        self,
        client: LiveClient | None,
        delegation: _Delegation | None,
        name: str,
        call_id: str,
        arguments: dict[str, Any] | None,
    ) -> None:
        try:
            if arguments is None:
                result = ActionResult(text=f"Error: the arguments of '{name}' are not valid JSON.")
            else:
                result = await self._execute(name, arguments)
            if client is None or client is not self._client:
                # The session that requested the action is gone: the result goes nowhere else.
                return
            sent = await client.create_item(
                {"type": "function_call_output", "call_id": call_id, "output": result.text}
            )
            self._own_command(sent, delegation)
            if result.image is not None:
                sent = await client.create_item(
                    {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": LOOK_IMAGE_TEXT,
                            },
                            {
                                "type": "input_image",
                                "image_url": result.image.to_data_url(),
                                "detail": "low",
                            },
                        ],
                    }
                )
                self._own_command(sent, delegation)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log_stage_failure("Could not return the result of %s to the backend: %s", name, exc)
        finally:
            if delegation is not None:
                delegation.running_calls = max(0, delegation.running_calls - 1)
                with contextlib.suppress(Exception):
                    await self._maybe_continue(delegation)

    async def _execute(self, name: str, arguments: dict[str, Any]) -> ActionResult:
        """Runs an action from the registry (the same definition MCP uses)."""
        ctx = ActionContext(
            camera=self._camera,
            avatar=self._hub,
            gallery_dir=str(self._settings.gallery_dir),
            gallery_upload_dir=self._settings.gallery_upload_dir,
            last_frame=self._last_frame,
            extra={"trivia": self._trivia, "moves": self._moves},
        )
        if self._registry is None:
            result = ActionResult(text="Error: no actions are available.")
        else:
            result = await self._registry.execute(name, arguments, ctx)
        logger.info("Action %s(%s) -> %s", name, arguments, result.text)
        if name == "show_image" and result.text.startswith("Showing"):
            self._schedule_image_auto_hide()
        elif name == "hide_image":
            self._cancel_image_auto_hide()
        if ctx.last_frame is not None:
            self._last_frame = ctx.last_frame
        return result

    async def _maybe_continue(self, delegation: _Delegation) -> None:
        """Asks the backend to go on once it has all the results."""
        if not delegation.response_done or delegation.running_calls > 0:
            return
        if delegation.calls_in_response == 0:
            self._finish_delegation(delegation)
            return
        delegation.rounds += 1
        if delegation.rounds > max(1, self._live.backend_max_tool_rounds):
            logger.warning(
                "The backend went over %d rounds of actions; it is not asked to go on",
                self._live.backend_max_tool_rounds,
            )
            self._finish_delegation(delegation)
            return
        delegation.calls_in_response = 0
        delegation.response_done = False
        client = self._client
        if client is not None:
            self._own_command(await client.create_response(), delegation)

    def _own_command(self, event_id: str, delegation: _Delegation | None) -> None:
        if delegation is not None:
            self._command_owner[event_id] = delegation.id

    def _on_command_error(self, event: dict[str, Any]) -> None:
        """If the error answers a command of a delegated task, the task is given up.

        Without this the task would wait for a final event that never comes and
        the avatar would stay in ``thinking`` until ``DELEGATION_TIMEOUT_S``.
        """
        error = event.get("error")
        client_event_id = error.get("client_event_id") if isinstance(error, dict) else None
        client_event_id = client_event_id or event.get("client_event_id")
        if not isinstance(client_event_id, str):
            return
        owner = self._command_owner.pop(client_event_id, None)
        delegation = self._delegations.get(owner) if owner is not None else None
        if delegation is not None:
            logger.warning("The backend rejected a command of task %s; closing it", owner)
            self._finish_delegation(delegation)

    async def _on_handoff_error(self, event: dict[str, Any]) -> None:
        """GPT-Live did not get the result of a delegated task (``Responses handoff incomplete``).

        It happens when the backend does not finish its response (for example, if
        it runs out of tokens while searching the web). The API sends no final
        event for that task and GPT-Live does not find out: Sonnia kept thinking
        until ``DELEGATION_TIMEOUT_S``. The task is closed and GPT-Live is asked
        to tell the user.
        """
        if "handoff" not in self.last_error.lower():
            return
        error = event.get("error")
        ids = [
            event.get("delegation_id"),
            error.get("delegation_id") if isinstance(error, dict) else None,
        ]
        delegation_id = next((i for i in ids if isinstance(i, str)), self._last_delegation_id)
        delegation = self._delegations.get(delegation_id) if delegation_id else None
        logger.warning(
            "The delegated task %s got no result: %s",
            delegation.id if delegation is not None else "(no open task)",
            json.dumps(event, ensure_ascii=False)[:500],
        )
        if delegation is not None:
            self._finish_delegation(delegation)
        await self.speak(DELEGATION_FAILED_TEXT)

    def _finish_delegation(self, delegation: _Delegation) -> None:
        self._delegations.pop(delegation.id, None)
        if self._last_delegation_id == delegation.id:
            self._last_delegation_id = None
        for event_id in [k for k, v in self._command_owner.items() if v == delegation.id]:
            del self._command_owner[event_id]
        text = " ".join("".join(delegation.text).split())
        calls = delegation.calls_total
        logger.info(
            "Backend (%s, %.1f s, %s): %s",
            delegation.id,
            time.monotonic() - delegation.created_at,
            f"{calls} {'action' if calls == 1 else 'actions'}" if calls else "no actions",
            text[:300] or "(no text)",
        )
        # GPT-Live will now say the result: its voice is awaited in ``thinking``.
        self._expect_response_until = time.monotonic() + RESPONSE_WAIT_S

    def _on_usage(self, event: dict[str, Any]) -> None:
        window = event.get("context_window")
        ratio = window.get("usage_ratio") if isinstance(window, dict) else None
        usage = event.get("usage")
        seconds = usage.get("seconds") if isinstance(usage, dict) else None
        if isinstance(seconds, int | float):
            self._usage_session_s = float(seconds)
        if isinstance(ratio, int | float):
            self._context_ratio = float(ratio)
        if (
            isinstance(ratio, int | float)
            and ratio >= self._live.context_restart_ratio
            and not self._context_full
        ):
            logger.info("GPT-Live context at %.0f %%: the session will be renewed", ratio * 100)
            self._context_full = True
        logger.debug("GPT-Live usage: %s s of voice, context %s", seconds, ratio)

    # -- interruption --------------------------------------------------------

    async def interrupt(self, *, tell_model: bool = True) -> None:
        """Silences Sonnia right away (the avatar client drops whatever it has queued)."""
        await self._on_interrupt(tell_model=tell_model)

    async def _on_interrupt(self, *, tell_model: bool = True) -> None:
        """Interruption from the avatar client: the voice stops and the model is asked to listen."""
        self._touch()
        was_audible = self._audible
        await self._hub.broadcast_json(p.msg_stop_speaking("interrupted"))
        segment, self._segment = self._segment, None
        if segment is not None:
            # The rest of that answer is dropped until the next silence.
            self._discard_audio = True
            self._last_closed_uid = segment.uid
        # The avatar client emptied its queue: there is nothing left to play.
        self._playback_done_id = max(self._playback_done_id, self._utterance_counter)
        self._last_closed_deadline = 0.0
        self._playback_end_at = time.monotonic()
        self._clip_mute_until = min(self._clip_mute_until, self._playback_end_at + CLIP_ECHO_TAIL_S)
        self._pending_assistant = []
        client = self._client
        if tell_model and was_audible and client is not None:
            with contextlib.suppress(Exception):
                await client.append_instructions(INTERRUPT_TEXT)
        self._audible = False
        self._settle_after = 0.0
        self._expect_response_until = 0.0
        await self._set_state(AssistantState.IDLE)

    # -- periodic loop -------------------------------------------------------

    async def _tick_loop(self) -> None:
        while True:
            await asyncio.sleep(self._tick)
            try:
                await self._tick_once(time.monotonic())
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error in the GPT-Live engine loop")

    async def _tick_once(self, now: float) -> None:
        gap = self._live.segment_gap_ms / 1000.0
        if self._segment is not None and now - self._last_voice_at >= gap:
            await self._close_segment(now)
        if self._discard_audio and now - self._last_voice_at >= gap:
            self._discard_audio = False

        audible = self._segment is not None or (
            self._playback_done_id < self._last_closed_uid and now < self._last_closed_deadline
        )
        if self._audible and not audible:
            self._settle_after = now + SPEECH_HOLD_S
        self._audible = audible

        if (
            self._user_turn_open
            and now - self._last_input_at >= self._live.user_turn_gap_ms / 1000.0
        ):
            await self._finish_user_turn(now)

        for delegation in list(self._delegations.values()):
            if now - delegation.created_at > DELEGATION_TIMEOUT_S:
                logger.warning("The delegated task %s did not finish; forgetting it", delegation.id)
                self._delegations.pop(delegation.id, None)

        await self._update_activity(now)
        await self._update_busy()

        if not audible and now >= self._settle_after:
            await self._set_state(self._rest_state(now))

        if self._trivia is not None:
            await self._trivia.tick(now)

        if self._state is not AssistantState.IDLE:
            self._maybe_look(turn_start=False)

        if self._is_idle(now) and self._client is not None and not self._restarting:
            await self._maybe_renew_session(now)
            if not self._restarting:
                await self._between_turns()
                await self._maybe_showcase(now)

    async def _update_activity(self, now: float) -> None:
        """Tells the avatar client if Sonnia is searching the web or a task is slow (scene effects)."""
        if any(d.searches for d in self._delegations.values()):
            activity = "search"
        elif any(now - d.created_at >= SLOW_TASK_S for d in self._delegations.values()):
            activity = "think"
        else:
            activity = "none"
        if activity == self._activity:
            return
        self._activity = activity
        logger.debug("Activity for the avatar client: %s", activity)
        await self._hub.broadcast_json(p.msg_activity(activity))

    async def _update_busy(self) -> None:
        """The waiting indicator of the delegated tasks (``sonia.busy``): one key per task.

        "Thinking…" from the moment GPT-Live delegates (not only after ``SLOW_TASK_S``,
        like ``activity``) until the task ends, fails, is cancelled or is forgotten
        (``DELEGATION_TIMEOUT_S``), and "Searching the web…" while it searches.
        "Thinking…" waits ``THINK_DELAY_S`` (0.3 s) in case the task ends right away;
        the search shows at once. Called by the tick (every 50 ms) and where the
        task is born.

        The ``thinking`` state (GPT-Live preparing its answer) does not turn it on,
        on purpose: it is inferred from the transcript and also fires with background
        voices that GPT-Live decides not to answer, so the indicator would show with
        nobody waiting for anything.
        """
        wanted: dict[str, tuple[BusyKind, str]] = {}
        now = time.monotonic()
        for delegation in self._delegations.values():
            if now - delegation.created_at >= THINK_DELAY_S:
                wanted[f"{BUSY_PREFIX}think:{delegation.id}"] = ("think", TEXT_THINK)
            if delegation.searches:
                wanted[f"{BUSY_PREFIX}search:{delegation.id}"] = ("search", TEXT_SEARCH)
        board = self._busy_board
        shown = board.keys
        for key in shown:
            if key.startswith(BUSY_PREFIX) and key not in wanted:
                await board.clear(key)
        for key, (kind, text) in wanted.items():
            if key not in shown:
                await board.set(key, kind, text)

    async def _on_client_hello(self, msg: dict[str, Any]) -> None:
        """An avatar client that connects (or reconnects) sees the wait in progress, if any."""
        if self._busy_board.current() is not None:
            await self._hub.broadcast_json(self._busy_board.message())

    def _rest_state(self, now: float) -> AssistantState:
        """Avatar state when Sonnia is not speaking."""
        if self._user_turn_open:
            return AssistantState.LISTENING
        if self._delegations or now < self._expect_response_until:
            return AssistantState.THINKING
        return AssistantState.IDLE

    def _is_idle(self, now: float) -> bool:
        return (
            self._state is AssistantState.IDLE
            and not self._audible
            and self._segment is None
            and not self._delegations
            and not self._user_turn_open
            and now >= self._expect_response_until
        )

    # -- session renewal -----------------------------------------------------

    async def _maybe_renew_session(self, now: float) -> None:
        """Opens a clean session at a quiet moment when it is due."""
        reason = ""
        limit = self._settings.idle_reset_seconds
        playing = self._playing()
        if (
            limit > 0
            and not playing
            and self._session_conversation
            and now - self._last_activity >= limit
        ):
            reason = f"{limit:.0f} s without activity"
        elif self._context_full:
            reason = "context almost full"
        else:
            expires = self._client.expires_at if self._client is not None else None
            aged = now - self._session_started_at > HEALTHY_SESSION_S
            if aged and expires is not None and expires - time.time() < EXPIRY_MARGIN_S:
                reason = "the session is about to expire"
        if reason:
            await self.restart_session(reason)

    async def restart_session(self, reason: str = "requested from the panel") -> bool:
        """Closes the current session to open a clean one (forgets the conversation)."""
        if self._client is None or self._restarting:
            return False
        logger.info("Opening a new GPT-Live session (%s)", reason)
        self._restarting = True
        self._last_frame = None
        self._cancel_image_auto_hide()
        await self._hub.hide_image()
        client = self._client
        if client is not None:
            # The session loop sees the close and reconnects right away.
            self._spawn(client.close(), "live-renew")
        return True

    # -- idle animation ------------------------------------------------------

    async def _maybe_showcase(self, now: float) -> None:
        """An idle bit if Sonnia has been alone long enough.

        If the line is in the voice cache it plays as is (no spending and nothing
        added to the conversation); if not, GPT-Live is asked to say it.
        """
        if self._showcase is None or not self._showcase_enabled or now < self._next_showcase_at:
            return
        if self._playing():
            return
        if now < self._ambient_expected_until:
            return
        bit = self._showcase.next_bit()
        show = self._settings.showcase
        low = max(5.0, show.interval_min_seconds)
        high = max(low, show.interval_max_seconds)
        self._next_showcase_at = now + self._showcase.rng.uniform(low, high)
        client = self._client
        if bit is None or client is None:
            return
        if bit.moment:
            # While it is being prepared (photo and description) no other bit comes out.
            self._ambient_expected_until = now + MOMENT_PREP_S
            self._spawn(self._request_moment(client, bit.attention), "showcase")
            return
        recorded = self._voice_cache.get(bit.text) if self._voice_cache is not None else None
        if recorded is not None:
            self._spawn(self.play_clip(recorded, bit.text, attention=bit.attention), "showcase")
            return
        if bit.attention:
            await self._hub.broadcast_json(p.msg_attention(bit.attention))
        self._ambient_expected_until = now + AMBIENT_WAIT_S
        # In the background: the 50 ms loop cannot sit waiting on the network.
        self._spawn(self._request_showcase(client, bit.text), "showcase")

    async def _request_showcase(self, client: LiveClient, text: str) -> None:
        try:
            await client.append_commentary(showcase_prompt(text))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not request the idle bit: %s", exc)
            self._ambient_expected_until = 0.0
            return
        logger.info("Idle bit requested: %s", text)

    async def _request_moment(self, client: LiveClient, attention: str | None) -> None:
        """An idle moment: GPT-Live improvises an invitation from what is happening now."""
        focus = await self._moment_focus()
        if client is not self._client or not self._is_idle(time.monotonic()):
            # Someone started talking while it was being prepared: no longer the time.
            self._ambient_expected_until = 0.0
            return
        if attention:
            await self._hub.broadcast_json(p.msg_attention(attention))
        self._ambient_expected_until = time.monotonic() + AMBIENT_WAIT_S
        try:
            await client.append_commentary(moment_prompt(focus))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not request the idle moment: %s", exc)
            self._ambient_expected_until = 0.0
            return
        logger.info("Idle moment requested: %s", focus)

    async def _moment_focus(self) -> str:
        """What the moment draws on: the camera and a specific invitation, taking turns."""
        options: list[str] = []
        if (
            self._settings.showcase.moment_camera
            and self._camera is not None
            and self._narrator is not None
            and self._policy.enabled
        ):
            options.append("camera")
        options.append("invitation")
        kind = options[self._moment_turn % len(options)]
        self._moment_turn += 1
        if kind == "camera":
            text = await self._moment_scene()
            if text:
                return moment_focus("camera", text)
        return moment_focus("invitation")

    async def _moment_scene(self) -> str:
        """What the camera sees now, for a moment (empty if it failed). The photo is not kept."""
        assert self._camera is not None and self._narrator is not None
        try:
            frame = await asyncio.wait_for(self._camera.capture(), timeout=CAPTURE_TIMEOUT_S)
            if frame is None:
                return ""
            return await self._narrator.describe(frame)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - without a photo the moment uses something else
            logger.debug("Idle moment without camera: %s", exc)
            return ""

    # -- camera --------------------------------------------------------------

    def _maybe_look(self, *, turn_start: bool) -> None:
        """Describes the camera in the background if the policy asks for it."""
        if self._camera is None or self._narrator is None or not self._policy.enabled:
            return
        if self._vision_task is not None and not self._vision_task.done():
            return
        now = time.monotonic()
        if now - self._last_vision_at < self._live.vision_min_interval_seconds:
            return
        wanted = (
            turn_start and self._policy.should_capture_on_turn_start()
        ) or self._policy.should_capture_periodic(now)
        if not wanted:
            return
        self._last_vision_at = now
        self._vision_task = asyncio.create_task(self._describe_scene(), name="sonia-live-vision")

    async def _describe_scene(self) -> None:
        assert self._camera is not None and self._narrator is not None
        started = time.monotonic()
        try:
            frame = await asyncio.wait_for(self._camera.capture(), timeout=CAPTURE_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not capture from the camera: %s", exc)
            self._camera_ok = False
            return
        self._policy.note_captured()
        self._camera_ok = frame is not None
        if frame is None:
            return
        self._last_frame = frame
        self._policy.maybe_save_debug(frame)
        try:
            text = await self._narrator.describe(frame)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log_stage_failure("Could not describe the camera: %s", exc)
            return
        client = self._client
        if not text or client is None:
            return
        try:
            await client.append_thinking(f"{CAMERA_NOTE_PREFIX} {text}")
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not pass the camera note: %s", exc)
            return
        logger.info("Camera described in %.1f s", time.monotonic() - started)
        logger.debug("Camera: %s", text)

    # -- on-screen image -----------------------------------------------------

    def _schedule_image_auto_hide(self) -> None:
        self._cancel_image_auto_hide()
        seconds = self._settings.image_auto_hide_seconds
        if seconds <= 0:
            return
        self._image_hide_task = asyncio.create_task(
            self._auto_hide_image(seconds), name="sonia-image-auto-hide"
        )

    def _cancel_image_auto_hide(self) -> None:
        task, self._image_hide_task = self._image_hide_task, None
        if task is not None and not task.done():
            task.cancel()

    async def _auto_hide_image(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
        logger.info("Image hidden automatically after %.0f s", seconds)
        self._image_hide_task = None
        await self._hub.hide_image()

    # -- panel controls ------------------------------------------------------

    async def set_active(self, active: bool) -> None:
        """Turns GPT-Live on or off. When off there is no session, so it does not spend."""
        if active == self._active:
            return
        self._active = active
        if active:
            logger.info("GPT-Live on: opening a session")
            self._next_showcase_at = time.monotonic() + max(
                0.0, self._settings.showcase.first_delay_seconds
            )
            self._active_event.set()
            return
        logger.info("GPT-Live off: closing the session to stop spending")
        self._active_event.clear()
        if self._trivia is not None:
            await self._trivia.on_session_lost()
        await self.interrupt(tell_model=False)
        if self._vision_task is not None and not self._vision_task.done():
            self._vision_task.cancel()
        client = self._client
        if client is not None:
            self._restarting = True
            self._spawn(client.close(), "live-off")

    async def play_clip(self, pcm: bytes, text: str, *, attention: str | None = None) -> bool:
        """Plays a recorded line as ``ambient`` voice (without changing state).

        It does not talk over GPT-Live: if Sonnia is already speaking, it does
        nothing and returns ``False``. While it plays (and ``CLIP_ECHO_TAIL_S``
        after) the microphone sends silence to GPT-Live: GPT-Live did not say the
        line and, if it heard it through the speakers, it would answer it as if a
        user had said it.
        """
        if self._audible or self._segment is not None:
            return False
        hub = self._hub
        if attention:
            await hub.broadcast_json(p.msg_attention(attention))
            # A dance starts with a crossfade; the voice comes in a little later.
            await asyncio.sleep(0.6 if attention == "dance" else 0.25)
            if self._audible or self._segment is not None:
                return False
        if not pcm:
            return True
        self._utterance_counter += 1
        uid = self._utterance_counter
        now = time.monotonic()
        seconds = len(pcm) / 2 / self._rate
        self._audible = True
        self._last_closed_uid = uid
        self._playback_end_at = max(self._playback_end_at, now) + seconds
        self._last_closed_deadline = self._playback_end_at + PLAYBACK_GRACE_S
        self._clip_uid = uid
        self._clip_mute_until = self._playback_end_at + CLIP_ECHO_TAIL_S
        await hub.broadcast_json(p.msg_speech_start(uid, text, ambient=True))
        await hub.broadcast_json(p.msg_transcript("assistant", text, True))
        chunk = max(2, self._rate // 10 * 2)  # 100 ms
        for start in range(0, len(pcm), chunk):
            await hub.send_audio(
                uid, AudioChunk(pcm=pcm[start : start + chunk], sample_rate=self._rate)
            )
        await hub.send_audio(uid, AudioChunk(pcm=b"", sample_rate=self._rate, is_last=True))
        await hub.broadcast_json(p.msg_speech_end(uid))
        logger.info("Sonnia (recorded, %d, %.2f s): %s", uid, seconds, text)
        return True

    async def announce(self, text: str) -> bool:
        """Asks GPT-Live to say an announcement out loud. Needs a session."""
        client = self._client
        text = text.strip()
        if client is None or not text:
            return False
        await client.append_commentary(ANNOUNCE_TEMPLATE.format(text=text))
        self._touch()
        self._expect_response_until = time.monotonic() + RESPONSE_WAIT_S
        logger.info("Announcement requested from the panel: %s", text)
        return True

    async def speak(self, prompt: str) -> bool:
        """Asks GPT-Live to say something now (``session.commentary.append``)."""
        client = self._client
        if client is None:
            return False
        try:
            await client.append_commentary(prompt)
        except Exception as exc:  # noqa: BLE001 - the session reconnects on its own
            _log_stage_failure("Could not ask GPT-Live to speak: %s", exc)
            return False
        self._touch()
        self._expect_response_until = time.monotonic() + RESPONSE_WAIT_S
        return True

    async def instruct(self, text: str) -> bool:
        """Adds an instruction to the session without making her speak."""
        client = self._client
        if client is None:
            return False
        try:
            await client.append_instructions(text)
        except Exception as exc:  # noqa: BLE001
            _log_stage_failure("Could not pass an instruction to GPT-Live: %s", exc)
            return False
        return True

    def quiet_for(self) -> float:
        """Seconds Sonnia has been quiet, by what the avatar client has left to play (0 if speaking)."""
        if self._segment is not None:
            return 0.0
        return max(0.0, time.monotonic() - self._playback_end_at)

    def touch(self) -> None:
        """There is activity: delays the idle animation and the new session due to inactivity."""
        self._touch()

    async def _between_turns(self) -> None:
        """What is passed to the session only in quiet moments: the gallery changes.

        Never while someone is talking: an append right when GPT-Live decides whether
        to delegate can change what it does (a note at the start of an answer
        coincided with a trivia answer that was not recorded).
        """
        if self._client is None:
            return
        await self._gallery_note()

    async def _gallery_loop(self, interval: float) -> None:
        """Checks the gallery every ``interval`` s to tell the session what changes.

        The operators add or remove images in ``assets/gallery`` while Sonnia is
        running: this way she knows them without a restart. The directory is read
        in a thread so as not to slow down the loop (the microphone runs in real time).
        """
        gallery = Gallery(self._settings.gallery_dir, self._settings.gallery_upload_dir)
        while True:
            await asyncio.sleep(interval)
            try:
                await self._check_gallery(gallery)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Could not check the gallery")

    async def _check_gallery(self, gallery: Gallery) -> None:
        """Compares the gallery with the one the session knows and leaves the note ready."""
        known = self._session_gallery
        if self._client is None or known is None:
            return  # no session: the next one already brings the list in its instructions
        ids = await asyncio.to_thread(gallery.ids)
        if self._session_gallery is not known or ids == self._gallery_seen:
            return  # another session opened in the meantime, or nothing new
        self._gallery_seen = ids
        added = [i for i in ids if i not in known]
        removed = [i for i in known if i not in ids]
        logger.info(
            "The gallery changed (added: %s; removed: %s)",
            ", ".join(added) or "none",
            ", ".join(removed) or "none",
        )
        if ids == known:
            self._pending_gallery = None  # back to what the session knows
            return
        note = gallery_note(added, removed, ids, max_chars=APPEND_MAX_CHARS)
        self._pending_gallery = (note, ids)

    async def _gallery_note(self) -> None:
        """Silent ``[Gallery]`` note with what changed (through ``thinking``: she does not speak)."""
        client = self._client
        if client is None or self._pending_gallery is None:
            return
        note, ids = self._pending_gallery
        self._pending_gallery = None
        try:
            await client.append_thinking(note)
        except Exception as exc:  # noqa: BLE001 - the session reconnects on its own
            logger.debug("Could not pass the gallery change to GPT-Live: %s", exc)
            if self._pending_gallery is None:
                self._pending_gallery = (note, ids)  # retried at the next quiet moment
            return
        self._session_gallery = ids
        logger.info("Gallery note: %s", note)

    async def set_notes(self, text: str) -> None:
        """Notes of the day: they go into the session now and into the instructions of the next ones."""
        text = text.strip()
        if text == self._notes:
            return
        self._notes = text
        client = self._client
        if client is not None:
            content = NOTES_TEMPLATE.format(text=text) if text else NOTES_CLEARED_TEXT
            with contextlib.suppress(Exception):
                await client.append_instructions(content)
        logger.info("Notes of the day updated (%d characters)", len(text))

    @property
    def notes(self) -> str:
        return self._notes

    def set_mic_muted(self, muted: bool) -> None:
        self._mic_manual_mute = muted
        logger.info("Microphone %s from the panel", "muted" if muted else "unmuted")

    @property
    def mic_muted(self) -> bool:
        return self._mic_manual_mute

    def set_gate(self, threshold: float) -> None:
        self._live.gate_rms = max(0.0, float(threshold))
        self._mic.set_threshold(self._live.gate_rms)

    def set_showcase_enabled(self, enabled: bool) -> None:
        self._showcase_enabled = enabled
        if enabled:
            self._next_showcase_at = time.monotonic() + max(
                0.0, self._settings.showcase.first_delay_seconds
            )

    @property
    def showcase_enabled(self) -> bool:
        return self._showcase_enabled

    def snapshot(self) -> dict[str, Any]:
        """What the panel needs to know about the engine, as JSON types."""
        now = time.monotonic()
        client = self._client
        expires = client.expires_at if client is not None else None
        uptime = now - self._session_started_at if self._session_started_at else 0.0
        current = max(self._usage_session_s, uptime) if client is not None else 0.0
        return {
            "active": self._active,
            "connected": client is not None,
            "session_id": client.session_id if client is not None else "",
            "uptime_s": round(uptime, 1),
            "expires_in_s": round(expires - time.time(), 1) if expires is not None else None,
            "context_ratio": self._context_ratio,
            "state": str(self._state),
            "speaking": self._audible,
            "delegations": len(self._delegations),
            "usage_s": round(self._usage_closed_s + current, 1),
            "mic_level": round(self._mic_level, 4),
            "mic_age_s": round(now - self._last_mic_at, 1) if self._last_mic_at else None,
            "mic_sound_age_s": (
                round(now - self._last_sound_at, 1) if self._last_sound_at else None
            ),
            "mic_muted": self._mic_manual_mute,
            "mic_gate": self._live.gate_rms,
            #: Why GPT-Live did not hear the last microphone block (empty if it did).
            "mic_reason": self._mic.reason,
            "camera_enabled": self._camera is not None and self._policy.enabled,
            "camera_ok": self._camera_ok,
            "last_error": self.last_error,
            "trivia": self._trivia.snapshot() if self._trivia is not None else None,
        }

    # -- utilities -----------------------------------------------------------

    async def _set_state(self, state: AssistantState) -> None:
        if state is self._state:
            return
        previous, self._state = self._state, state
        logger.info("State: %s -> %s", previous, state)
        await self._hub.broadcast_json(p.msg_state(state))

    def _touch(self) -> None:
        self._last_activity = time.monotonic()
        if self._showcase is not None:
            self._next_showcase_at = max(
                self._next_showcase_at,
                self._last_activity + self._settings.showcase.first_delay_seconds,
            )

    def _spawn(self, coro: Coroutine[Any, Any, Any], name: str) -> None:
        """Starts a background task with a strong reference and its errors to the log."""
        task = asyncio.create_task(coro, name=f"sonia-live-{name}")
        self._tasks.add(task)
        task.add_done_callback(self._task_done)

    def _task_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("Task %s failed: %r", task.get_name(), task.exception())


#: Sound tags GPT-Live puts in the transcript ("[laugh]", "[sigh]").
#: They can arrive split between two turns ("[sigh" in one and "]" in the next).
_TAG = re.compile(r"\[[^\[\]]*\]")
_TAG_TAIL = re.compile(r"\[[^\[\]]*$")
_TAG_HEAD = re.compile(r"^[^\[\]]*\]")


#: How her name is written: "Sonnia", with a double n, although it is said "Sonia".
#: The transcript brings what is heard; the subtitles and the panel, what is read.
WRITTEN_NAME = "Sonnia"
_SPOKEN_NAME = re.compile(r"\bson[ií]a\b", re.IGNORECASE)


def _written_name(match: re.Match[str]) -> str:
    word = match.group(0)
    if word.isupper():
        return WRITTEN_NAME.upper()
    return WRITTEN_NAME if word[0].isupper() else WRITTEN_NAME.lower()


def clean_transcript(text: str) -> str:
    """Readable text of a transcript: no sound tags or extra spaces, and with
    Sonnia's name spelled right."""
    text = _SPOKEN_NAME.sub(_written_name, text)
    text = _TAG.sub(" ", text)
    text = _TAG_TAIL.sub(" ", text)
    if "[" not in text:
        # A stray "]" at the start is the tail of a tag from the previous turn.
        head = _TAG_HEAD.match(text)
        if head is not None and len(head.group(0).strip()) <= 12:
            text = text[head.end() :]
    return " ".join(text.split())


def _pcm16_rms(pcm: bytes) -> float:
    import numpy as np

    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    return float(np.sqrt(np.mean(samples * samples))) if len(samples) else 0.0


def _forward_camera_frame(on_frame: Callable[..., Any], msg: dict[str, Any]) -> None:
    data = msg.get("data_base64")
    if isinstance(data, str) and data:
        on_frame(str(msg.get("mime") or "image/jpeg"), data)
