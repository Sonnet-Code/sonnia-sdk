"""Sonnia's control from the panel: modes, actions and status in plain language.

It is the layer between the web panel and the engine. It knows which mode Sonnia
is in (conversation, greeter or away), applies it to the engine and to the avatar
client, saves what the operator changes so it survives a restart, and turns the
technical status into sentences anyone can understand ("Sonnia's screen is not
connected: open the avatar app").
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import json
import logging
import math
import random
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypeGuard

from sonia.actions.gallery import UPLOAD_MAX_BYTES, Gallery, GalleryError
from sonia.actions.registry import ActionRegistry
from sonia.clock import resolve_timezone
from sonia.config import Settings
from sonia.showcase import ATTENTION_DANCE, ATTENTION_FOURTH_WALL, load_lines
from sonia.types import ActionContext
from sonia.ws import protocol as p

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sonia.live.engine import LiveEngine
    from sonia.live.voicecache import VoiceCache
    from sonia.ws.hub import Hub

__all__ = [
    "DEFAULT_AWAY_MESSAGE",
    "MODES",
    "SETTINGS",
    "TUNING_LIMITS",
    "PanelControl",
    "PanelState",
    "default_tuning",
    "merge_tuning",
]

logger = logging.getLogger(__name__)

Mode = Literal["conversation", "greeter", "away"]
MODES: tuple[Mode, ...] = ("conversation", "greeter", "away")

DEFAULT_AWAY_MESSAGE = "Back in a few minutes"

#: Built-in GPT-Live voices offered in the panel.
VOICES = ["marin", "cedar", "coral", "sage", "shimmer", "ballad", "verse", "alloy", "ash", "echo"]

GESTURES = ("greeting", "dance", "fourth_wall", "soft")

#: Everything the panel can do with the engine.
CAPABILITIES = [
    "modes",
    "say",
    "ask",
    "stop",
    "mute",
    "restart",
    "images",
    "gestures",
    "animations",
    "animation_toggles",
    "subtitles",
    "debug",
    "greet",
    "showcase",
    "volume",
    "mic_gate",
    "voice",
    "notes",
    "voice_cache",
    "tuning",
    "avatar",
    #: Log lines carry ``logger`` and ``tags`` (the Developer log filters).
    "log_tags",
    #: Upload images to the gallery and remove the uploaded ones (``add_gallery_image``,
    #: ``remove_gallery_image``); the status carries ``gallery`` with the current ids.
    "gallery_upload",
]

#: Settings the operator changes from the panel (saved in ``PANEL_STATE_FILE``). The
#: mode, the debug mode and the usage are saved too, but not through ``_set_setting``.
SETTINGS: tuple[str, ...] = (
    "away_message",
    "notes",
    "volume",
    "mic_gate",
    "voice",
    "showcase",
    "subtitles",
    "disabled_animations",
    "tuning",
    "avatar",
)

#: Developer settings: group -> value -> (minimum, maximum, default). The mouth and the
#: idle motion are multipliers of what the client scene ships with (1 = as authored) and
#: the camera offsets over its base framing (meters and degrees) plus a zoom that
#: narrows or widens the field of view.
TUNING_LIMITS: dict[str, dict[str, tuple[float, float, float]]] = {
    "mouth": {
        "open": (0.0, 2.0, 1.0),  # vowel and jaw opening
        "jaw": (0.0, 3.0, 1.0),  # extra jaw on stressed syllables
        "closure": (0.0, 1.5, 1.0),  # lip closure on p, b, m
        "speed": (0.5, 2.0, 1.0),  # how fast the mouth moves
    },
    "camera": {
        "height": (-0.5, 0.5, 0.0),  # meters, + goes up
        "distance": (-0.6, 1.0, 0.0),  # meters, + moves away
        "side": (-0.4, 0.4, 0.0),  # meters, + to the right of the screen
        "zoom": (0.5, 2.0, 1.0),  # >1 gets closer (narrower field of view)
        "tilt": (-15.0, 15.0, 0.0),  # degrees, + looks further down
    },
    "idle": {
        "breath": (0.0, 2.0, 1.0),  # breathing (chest, shoulders and head)
        "accents": (0.0, 2.0, 1.0),  # body accents on stressed syllables
        "speed": (0.5, 1.5, 1.0),  # pace of breathing and idle motion
    },
}

#: Maximum length of today's notes.
NOTES_MAX_LEN = 1_000

#: Maximum length of the "Away" sign.
AWAY_MESSAGE_MAX_LEN = 140

#: First greeting after entering greeter mode.
GREETER_FIRST_DELAY_S = 4.0

#: Before recording the fixed lines at startup the session is given some breathing room.
VOICE_WARMUP_DELAY_S = 20.0

#: Without microphone blocks for this long, it is considered down.
MIC_STALE_S = 3.0

#: Without any sound (not even background noise) for this long, the microphone hears nothing.
MIC_DEAF_S = 30.0

#: How often today's usage is saved.
USAGE_SAVE_S = 30.0

#: How often the gallery is read again for the status (``gallery``): images can also be
#: dropped into the folders by hand.
GALLERY_REFRESH_S = 5.0

#: Maximum length of ``data_base64`` (the uploaded image, with some margin).
UPLOAD_MAX_BASE64 = (UPLOAD_MAX_BYTES // 3 + 2) * 4 + 64


def default_tuning() -> dict[str, dict[str, float]]:
    """Untouched Developer settings: mouth, camera and motion as the scene ships them."""
    return {
        group: {name: limits[2] for name, limits in values.items()}
        for group, values in TUNING_LIMITS.items()
    }


def merge_tuning(*sources: Any) -> dict[str, dict[str, float]]:
    """Complete Developer settings starting from the defaults.

    Each source (group -> value -> number) is merged over the previous one,
    clamped to ``TUNING_LIMITS``. Anything unknown or malformed is ignored, so it
    works the same for what is saved on disk and for the partial changes of a
    panel slider.
    """
    result = default_tuning()
    for source in sources:
        if not isinstance(source, dict):
            continue
        for group, values in source.items():
            limits = TUNING_LIMITS.get(group)
            if limits is None or not isinstance(values, dict):
                continue
            for name, value in values.items():
                bounds = limits.get(name)
                if bounds is None or not _is_number(value) or not math.isfinite(value):
                    continue
                result[group][name] = round(max(bounds[0], min(bounds[1], float(value))), 4)
    return result


@dataclass
class PanelState:
    """What the operator changes from the panel, saved on disk."""

    mode: Mode = "conversation"
    away_message: str = DEFAULT_AWAY_MESSAGE
    notes: str = ""
    volume: float = 1.0
    mic_gate: float | None = None
    voice: str | None = None
    showcase: bool | None = None
    #: Subtitles on the avatar's screen.
    subtitles: bool = True
    #: Clips Sonnia does not use on her own (the "Animations" block).
    disabled_animations: list[str] = field(default_factory=list)
    #: Developer settings: mouth, camera and idle motion (see ``TUNING_LIMITS``).
    tuning: dict[str, dict[str, float]] = field(default_factory=default_tuning)
    #: Genies avatar definition (a JSON string); ``None``: the character the client ships.
    avatar: str | None = None
    #: Debug mode: Sonnia stays still (no realtime model and nothing automatic) for visual tests.
    debug: bool = False
    #: Today's usage: realtime session seconds accumulated on ``usage_date`` (survives
    #: orchestrator restarts).
    usage_date: str = ""
    usage_seconds: float = 0.0

    @classmethod
    def load(cls, path: Path) -> PanelState:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError) as exc:
            logger.warning("Could not read the panel state (%s); starting from scratch", exc)
            return cls()
        state = cls()
        if not isinstance(raw, dict):
            return state
        if raw.get("mode") in MODES:
            state.mode = raw["mode"]
        for name in SETTINGS:
            if name not in raw:
                continue
            with contextlib.suppress(ValueError):
                setattr(state, name, _normalize_setting(name, raw[name]))
        if isinstance(raw.get("usage_date"), str):
            state.usage_date = raw["usage_date"]
        if _is_number(raw.get("usage_seconds")):
            state.usage_seconds = float(raw["usage_seconds"])
        if isinstance(raw.get("debug"), bool):
            state.debug = raw["debug"]
        return state

    def save(self, path: Path) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
        except OSError as exc:
            logger.warning("Could not save the panel state: %s", exc)


@dataclass(frozen=True)
class _GreeterBit:
    text: str
    gesture: str | None


@dataclass
class _Material:
    """Fixed lines: greetings, idle lines and chants."""

    greetings: list[str] = field(default_factory=list)
    phrases: list[str] = field(default_factory=list)
    songs: list[str] = field(default_factory=list)

    @classmethod
    def from_dir(cls, directory: Path) -> _Material:
        return cls(
            greetings=load_lines(directory / "greetings.md"),
            phrases=load_lines(directory / "lines.md"),
            songs=load_lines(directory / "chants.md"),
        )

    def all_texts(self) -> list[str]:
        return [*self.greetings, *self.phrases, *self.songs]


class PanelControl:
    """Panel state and actions over the GPT-Live engine."""

    def __init__(
        self,
        settings: Settings,
        *,
        hub: Hub,
        registry: ActionRegistry | None,
        engine: LiveEngine,
        voice_cache: VoiceCache | None = None,
        material: _Material | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._settings = settings
        self._hub = hub
        self._registry = registry
        self._engine = engine
        self._voice_cache = voice_cache
        self._material = material or _Material.from_dir(settings.showcase_dir)
        self._rng = rng or random.Random()
        self._state_path = Path(settings.panel.state_file)
        self.state = PanelState.load(self._state_path)
        # What this machine has in its .env: a setting set to None (never touched from
        # the panel) goes back to this.
        self._default_voice = settings.live.voice
        self._default_gate = settings.live.gate_rms
        self._default_showcase = engine.showcase_enabled
        self._tasks: set[asyncio.Task[Any]] = set()
        self._loop_task: asyncio.Task[None] | None = None
        self._next_greet_at = 0.0
        self._last_greeting: str | None = None
        self._image: dict[str, Any] | None = None
        #: Clips the client says it has (``animations`` message on connect).
        self._animations: list[dict[str, str]] = []
        #: Catalog clip playing now on the client (``animation_playing``).
        self._current_animation: str | None = None
        #: Session seconds of earlier runs on the same day.
        self._usage_base = 0.0
        self._last_usage_save = time.monotonic()
        self._roll_usage_day(engine_seconds=0.0)
        #: Gallery ids for the status (uploads start with ``upload-``). They are read in
        #: a thread (``_refresh_gallery``): ``status()`` does not touch the disk.
        self._gallery_listing: dict[str, list[str]] | None = None
        self._gallery_checked_at = 0.0
        #: Uploads are written one at a time (the free id is chosen before writing).
        self._gallery_lock = asyncio.Lock()
        self._tz = resolve_timezone(settings.timezone)
        hub.add_listener(self._watch_outgoing)
        hub.on(p.MSG_ANIMATIONS, self._on_animations)
        hub.on(p.MSG_ANIMATION_PLAYING, self._on_animation_playing)

    # -- lifecycle --------------------------------------------------------------

    @property
    def capabilities(self) -> list[str]:
        caps = list(CAPABILITIES)
        if self._engine.trivia is not None:
            caps.append("trivia")
        return caps

    async def start(self) -> None:
        """Applies what was saved and starts the greeter loop. Before ``engine.run()``."""
        state = self.state
        engine = self._engine
        if state.voice in VOICES:
            self._settings.live.voice = state.voice
        if state.mic_gate is not None:
            engine.set_gate(state.mic_gate)
        if state.showcase is not None:
            engine.set_showcase_enabled(state.showcase)
        if state.notes:
            await engine.set_notes(state.notes)
        await self._hub.set_sticky("volume", p.msg_set_volume(state.volume))
        await self._hub.set_sticky("subtitles", p.msg_set_subtitles(state.subtitles))
        await self._hub.set_sticky(
            "disabled_animations", p.msg_set_disabled_animations(state.disabled_animations)
        )
        await self._hub.set_sticky("debug", p.msg_set_debug(state.debug))
        await self._hub.set_sticky("tuning", p.msg_set_tuning(state.tuning))
        await self._hub.set_sticky("avatar", p.msg_set_avatar(state.avatar))
        await self._apply_mode(state.mode)
        if state.debug:
            logger.info("The panel left Sonnia in debug mode: still and without GPT-Live")
        elif state.mode != "conversation":
            logger.info("The panel left Sonnia in %s mode: GPT-Live is not opened", state.mode)
        self._loop_task = asyncio.create_task(self._loop(), name="sonia-panel-loop")
        self._spawn(self._refresh_gallery(), "gallery")
        if self._voice_cache is not None and self._settings.live.api_key and not state.debug:
            self._spawn(self._prepare_voices(delay=VOICE_WARMUP_DELAY_S), "voice-warmup")

    async def stop(self) -> None:
        self._save_usage()
        tasks = [t for t in [self._loop_task, *self._tasks] if t is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # -- modes ------------------------------------------------------------------

    @property
    def mode(self) -> Mode:
        return self.state.mode

    async def set_mode(self, mode: Mode) -> None:
        if mode == self.state.mode:
            return
        logger.info("Panel: mode %s -> %s", self.state.mode, mode)
        self.state.mode = mode
        self._save()
        await self._apply_mode(mode)

    async def _apply_mode(self, mode: Mode) -> None:
        hub = self._hub
        if mode == "away":
            await self._set_live(False)
            await hub.hide_image()
            await hub.set_sticky("presence", p.msg_presence(False, self._away_message))
            return
        await hub.set_sticky("presence", p.msg_presence(True, self._away_message))
        if mode == "conversation":
            # In debug mode GPT-Live is not opened.
            await self._set_live(not self.state.debug)
        else:
            await self._set_live(False)
            self._next_greet_at = time.monotonic() + GREETER_FIRST_DELAY_S

    async def _set_live(self, active: bool) -> None:
        """Turns GPT-Live on or off and tells the screen (the invitation to talk)."""
        await self._engine.set_active(active)
        await self._hub.set_sticky("stage_mode", p.msg_stage_mode(self.state.mode, active))

    @property
    def _away_message(self) -> str:
        return self.state.away_message.strip() or DEFAULT_AWAY_MESSAGE

    # -- greeter loop -----------------------------------------------------------

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            try:
                if time.monotonic() - self._last_usage_save >= USAGE_SAVE_S:
                    self._save_usage()
                if time.monotonic() - self._gallery_checked_at >= GALLERY_REFRESH_S:
                    await self._refresh_gallery()
                if (
                    self.state.mode == "greeter"
                    and not self.state.debug
                    and time.monotonic() >= self._next_greet_at
                ):
                    self._schedule_next_greeting()
                    await self.greet()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error in greeter mode")

    def _schedule_next_greeting(self) -> None:
        panel = self._settings.panel
        low = max(5.0, panel.greeter_interval_min_seconds)
        high = max(low, panel.greeter_interval_max_seconds)
        self._next_greet_at = time.monotonic() + self._rng.uniform(low, high)

    def _next_bit(self, kind: str | None = None) -> _GreeterBit | None:
        material = self._material
        roll = self._rng.random()
        if kind == "greeting" or (kind is None and roll < 0.6 and material.greetings):
            pool, gesture = material.greetings, "greeting"
        elif kind is None and roll < 0.85 and material.phrases:
            pool, gesture = material.phrases, ATTENTION_FOURTH_WALL
        elif material.songs:
            pool, gesture = material.songs, ATTENTION_DANCE
        else:
            pool, gesture = material.greetings or material.phrases, "greeting"
        if not pool:
            return None
        candidates = [t for t in pool if t != self._last_greeting] or pool
        text = self._rng.choice(candidates)
        self._last_greeting = text
        return _GreeterBit(text, gesture)

    async def greet(self, kind: str | None = None) -> tuple[bool, str]:
        """A greeting with a recorded line (or only the gesture if it is not recorded yet)."""
        if self.state.mode == "away":
            return False, "Sonnia is away. Bring her back so she can greet."
        bit = self._next_bit(kind)
        if bit is None:
            await self._hub.broadcast_json(p.msg_attention("greeting"))
            return True, "Sonnia waves."
        pcm = self._voice_cache.get(bit.text) if self._voice_cache is not None else None
        if pcm is None:
            if bit.gesture:
                await self._hub.broadcast_json(p.msg_attention(bit.gesture))
            return (
                True,
                'Sonnia greets with a gesture (the line is not recorded yet: use "Prepare voices").',
            )
        played = await self._engine.play_clip(pcm, bit.text, attention=bit.gesture)
        if not played:
            return False, "Sonnia is talking right now; try again in a moment."
        return True, f'Sonnia says: "{bit.text}"'

    # -- recorded voices --------------------------------------------------------

    async def _prepare_voices(self, delay: float = 0.0) -> int:
        if self._voice_cache is None:
            return 0
        if delay:
            await asyncio.sleep(delay)
        return await self._voice_cache.prepare(self._voice_texts())

    def _voice_texts(self) -> list[str]:
        """The fixed lines that are recorded: greetings, idle lines and chants."""
        return self._material.all_texts()

    def _voice_cache_status(self) -> dict[str, Any]:
        cache = self._voice_cache
        texts = self._voice_texts()
        if cache is None:
            return {"ready": 0, "total": len(texts), "busy": False, "error": ""}
        return {
            "ready": cache.count_ready(texts),
            "total": len(set(t.strip() for t in texts if t.strip())),
            "busy": cache.busy,
            "error": cache.last_error,
        }

    # -- actions ----------------------------------------------------------------

    async def act(self, action: str, params: dict[str, Any]) -> tuple[bool, str]:
        """Runs a panel action. Never raises: failures come back as text."""
        handler = getattr(self, f"_act_{action}", None)
        if handler is None:
            return False, f"Unknown action: {action}"
        try:
            result: tuple[bool, str] = await handler(params)
        except _BadRequest as exc:
            return False, str(exc)
        except Exception as exc:
            logger.exception("The panel action %s failed", action)
            return False, f"It did not work: {exc}"
        logger.info("Panel: %s %s -> %s", action, _summary(params), result[1])
        return result

    def _need_present(self) -> None:
        if self.state.mode == "away":
            raise _BadRequest("Sonnia is away. Bring her back first.")

    async def _act_set_mode(self, params: dict[str, Any]) -> tuple[bool, str]:
        mode = params.get("mode")
        if mode not in MODES:
            raise _BadRequest("Invalid mode.")
        await self.set_mode(mode)
        return True, {
            "conversation": "Sonnia is back to conversation.",
            "greeter": "Sonnia only greets: she does not converse or spend.",
            "away": "Sonnia leaves the screen and puts up the sign.",
        }[mode]

    async def _act_set_away_message(self, params: dict[str, Any]) -> tuple[bool, str]:
        text = _text(params, "text", max_len=AWAY_MESSAGE_MAX_LEN)
        await self._set_setting("away_message", text or DEFAULT_AWAY_MESSAGE)
        return True, "Sign updated."

    async def _act_say(self, params: dict[str, Any]) -> tuple[bool, str]:
        text = _text(params, "text", max_len=400, required=True)
        self._need_present()
        if self.state.mode == "conversation":
            if not await self._engine.announce(text):
                raise _BadRequest("Sonnia is not connected right now; try again in a few seconds.")
            return True, "Sonnia will say it in a moment."
        # Greeter only: it is recorded with her voice (a short session) and played.
        if self._voice_cache is None or not self._settings.live.api_key:
            raise _BadRequest("The line cannot be recorded: the GPT-Live key is missing.")
        self._spawn(self._record_and_play(text), "panel-say")
        return True, "Recording the announcement with her voice; she will say it in a few seconds."

    async def _record_and_play(self, text: str) -> None:
        assert self._voice_cache is not None
        pcm = self._voice_cache.get(text)
        if pcm is None:
            try:
                pcm = await self._voice_cache.record(text)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not record the announcement: %s", exc)
                return
        if self.state.mode != "away":
            await self._engine.play_clip(pcm, text, attention="soft")

    async def _act_ask(self, params: dict[str, Any]) -> tuple[bool, str]:
        text = _text(params, "text", max_len=400, required=True)
        if self.state.mode != "conversation":
            raise _BadRequest('Sonnia is not conversing. Switch her to "Conversing" first.')
        await self._engine.submit_text(text)
        return True, "Sent. Sonnia will answer out loud."

    async def _act_stop(self, params: dict[str, Any]) -> tuple[bool, str]:
        await self._engine.interrupt()
        return True, "Sonnia goes quiet."

    async def _act_mute(self, params: dict[str, Any]) -> tuple[bool, str]:
        muted = _flag(params, "muted")
        self._engine.set_mic_muted(muted)
        return True, "Microphone muted: Sonnia does not hear." if muted else "Microphone on."

    async def _act_restart(self, params: dict[str, Any]) -> tuple[bool, str]:
        if self.state.mode != "conversation":
            raise _BadRequest("Sonnia is not conversing; there is no conversation to restart.")
        if not await self._engine.restart_session("requested from the panel"):
            raise _BadRequest("Already connecting; wait a few seconds.")
        return True, "New conversation: Sonnia forgets what was said and starts from scratch."

    async def _act_show_image(self, params: dict[str, Any]) -> tuple[bool, str]:
        self._need_present()
        image_id = _text(params, "image_id", max_len=120, required=True)
        caption = _text(params, "caption", max_len=120) or None
        if self._registry is None or "show_image" not in self._registry:
            raise _BadRequest("There is no action to show images.")
        ctx = ActionContext(
            camera=None,
            avatar=self._hub,
            gallery_dir=str(self._settings.gallery_dir),
            gallery_upload_dir=self._settings.gallery_upload_dir,
            extra={"trivia": self._engine.trivia},
        )
        args: dict[str, Any] = {"image_id": image_id}
        if caption:
            args["caption"] = caption
        result = await self._registry.execute("show_image", args, ctx)
        return result.text.startswith("Showing"), result.text

    async def _act_hide_image(self, params: dict[str, Any]) -> tuple[bool, str]:
        await self._hub.hide_image()
        return True, "Image hidden."

    async def _act_add_gallery_image(self, params: dict[str, Any]) -> tuple[bool, str]:
        """The "Add image" button: saves it in the uploads folder (``GALLERY_UPLOAD_DIR``).

        The panel already sends it downscaled (1280 px, a JPEG of ~220 KB or a small
        PNG). Here it is checked again by its content and written in a thread; the
        gallery watcher tells GPT-Live about it with the ``[Gallery]`` note.
        """
        name = _text(params, "name", max_len=120)
        raw = params.get("data_base64")
        if not isinstance(raw, str) or not raw.strip():
            raise _BadRequest("Pick an image first.")
        if len(raw) > UPLOAD_MAX_BASE64:
            raise _BadRequest(f"The image is too big (at most {UPLOAD_MAX_BYTES // 1024} KB).")
        if raw.startswith("data:"):
            raw = raw.partition(",")[2]
        try:
            data = base64.b64decode(raw.strip(), validate=True)
        except (binascii.Error, ValueError):
            raise _BadRequest("The image arrived damaged: pick it again.") from None
        gallery = self.gallery()
        async with self._gallery_lock:
            try:
                image_id = await asyncio.to_thread(
                    gallery.add_upload, name, data, now=datetime.now(self._tz)
                )
            except GalleryError as exc:
                raise _BadRequest(str(exc)) from None
            except OSError as exc:
                logger.warning("Could not save the uploaded image: %s", exc)
                raise _BadRequest("The image could not be saved on this computer.") from None
        await self._refresh_gallery()
        return True, f"Image added: {image_id}"

    async def _act_remove_gallery_image(self, params: dict[str, Any]) -> tuple[bool, str]:
        """The "×" of an uploaded image. The images in ``assets/gallery`` are not removed here."""
        image_id = _text(params, "id", max_len=120)
        if not image_id:
            raise _BadRequest("Say which image to remove.")
        gallery = self.gallery()
        async with self._gallery_lock:
            try:
                removed = await asyncio.to_thread(gallery.remove_upload, image_id)
            except OSError as exc:
                logger.warning("Could not remove the uploaded image %s: %s", image_id, exc)
                raise _BadRequest("The image could not be deleted on this computer.") from None
        if not removed:
            raise _BadRequest(
                "That image cannot be removed: only the ones uploaded from the panel can."
            )
        await self._refresh_gallery()
        return True, f"Image removed: {image_id}"

    async def _act_gesture(self, params: dict[str, Any]) -> tuple[bool, str]:
        self._need_present()
        category = params.get("category")
        if category not in GESTURES:
            raise _BadRequest("Invalid gesture.")
        await self._hub.broadcast_json(p.msg_attention(str(category)))
        return True, "Done."

    async def _act_animation(self, params: dict[str, Any]) -> tuple[bool, str]:
        self._need_present()
        clip = _text(params, "clip", max_len=80, required=True)
        if self._hub.client_count == 0:
            raise _BadRequest("Sonnia's screen is not connected.")
        if not self._animations:
            raise _BadRequest(
                "The avatar app has not sent its list of animations: update it or open it again."
            )
        if clip not in {a["clip"] for a in self._animations}:
            raise _BadRequest("That animation is not in the avatar app.")
        await self._hub.broadcast_json(p.msg_play_animation(clip))
        return True, f'Sonnia does "{clip}".'

    async def _act_set_animation_enabled(self, params: dict[str, Any]) -> tuple[bool, str]:
        clip = _text(params, "clip", max_len=80, required=True)
        enabled = _flag(params, "enabled")
        known = {a["clip"] for a in self._animations}
        if known and clip not in known:
            raise _BadRequest("That animation is not in the avatar app.")
        disabled = set(self.state.disabled_animations)
        if enabled:
            disabled.discard(clip)
        else:
            disabled.add(clip)
        await self._set_setting("disabled_animations", sorted(disabled))
        return True, (
            f'Sonnia uses "{clip}" on her own again.'
            if enabled
            else f'Sonnia will no longer do "{clip}" on her own (its button still works).'
        )

    async def _act_set_avatar(self, params: dict[str, Any]) -> tuple[bool, str]:
        """A Genies avatar definition (JSON string), or ``None``/empty for the default one."""
        raw = params.get("definition")
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            if self.state.avatar is None:
                return True, "Sonnia already has the default avatar."
            await self._set_setting("avatar", None)
            return True, "Sonnia goes back to the default avatar."
        definition = p.parse_avatar_definition(raw)
        if definition is None:
            raise _BadRequest(
                "That is not a valid avatar definition (a JSON with JsonVersion and "
                "equippedAssetIds)."
            )
        await self._set_setting("avatar", definition)
        return True, "Avatar saved. The avatar client loads it now (with the Genies Avatar SDK)."

    async def _act_trivia_start(self, params: dict[str, Any]) -> tuple[bool, str]:
        """The "Start trivia" button: the same game a user asks for by voice."""
        trivia = self._engine.trivia
        if trivia is None:
            raise _BadRequest("The trivia is disabled (TRIVIA_ENABLED).")
        self._need_present()
        if self.state.mode != "conversation":
            raise _BadRequest('The trivia needs Sonnia conversing: switch her to "Conversing".')
        if self.state.debug:
            raise _BadRequest("In debug mode Sonnia does not converse: turn it off first.")
        if self._hub.client_count == 0:
            raise _BadRequest("Sonnia's screen is not connected.")
        ok, message = await trivia.start("panel", _level(params))
        if not ok:
            raise _BadRequest(message)
        return True, message

    async def _act_trivia_restart(self, params: dict[str, Any]) -> tuple[bool, str]:
        """The "Restart trivia" button: a new game from the first question."""
        trivia = self._engine.trivia
        if trivia is None:
            raise _BadRequest("The trivia is disabled (TRIVIA_ENABLED).")
        self._need_present()
        if self.state.mode != "conversation":
            raise _BadRequest('The trivia needs Sonnia conversing: switch her to "Conversing".')
        if self._hub.client_count == 0:
            raise _BadRequest("Sonnia's screen is not connected.")
        ok, message = await trivia.restart("panel", _level(params))
        if not ok:
            raise _BadRequest(message)
        return True, "Trivia restarted from the first question."

    async def _act_trivia_next(self, params: dict[str, Any]) -> tuple[bool, str]:
        """The "Next question" button: the one the user asks for after seeing the result."""
        trivia = self._engine.trivia
        if trivia is None or not trivia.active:
            raise _BadRequest("There is no trivia running.")
        ok, message = await trivia.next("panel")
        if not ok:
            raise _BadRequest(message)
        return True, message

    async def _act_trivia_stop(self, params: dict[str, Any]) -> tuple[bool, str]:
        trivia = self._engine.trivia
        if trivia is None or not trivia.active:
            return True, "There is no trivia running."
        await trivia.stop("panel")
        return True, "Trivia ended."

    async def _act_trivia_answer(self, params: dict[str, Any]) -> tuple[bool, str]:
        """The A, B and C buttons (and "Doesn't know"): the operator answers for the user."""
        trivia = self._engine.trivia
        if trivia is None or not trivia.active:
            raise _BadRequest("There is no trivia running.")
        option = params.get("option")
        choices = {"A": 0, "B": 1, "C": 2, "pass": -1}
        if option not in choices:
            raise _BadRequest("Invalid answer: A, B, C or pass.")
        ok, message = await trivia.answer(choices[str(option)], "panel")
        if not ok:
            raise _BadRequest(message)
        return True, message

    async def _act_greet(self, params: dict[str, Any]) -> tuple[bool, str]:
        self._need_present()
        return await self.greet("greeting")

    async def _act_showcase(self, params: dict[str, Any]) -> tuple[bool, str]:
        enabled = _flag(params, "enabled")
        await self._set_setting("showcase", enabled)
        return True, (
            "Sonnia will say lines and dance on her own when nobody is around."
            if enabled
            else "Sonnia will no longer say lines or dance on her own."
        )

    async def _act_set_debug(self, params: dict[str, Any]) -> tuple[bool, str]:
        enabled = _flag(params, "enabled")
        if enabled == self.state.debug:
            return True, "Debug mode on." if enabled else "Debug mode off."
        self.state.debug = enabled
        self._save()
        await self._hub.set_sticky("debug", p.msg_set_debug(enabled))
        if enabled:
            logger.info("Panel: debug mode on; GPT-Live off and Sonnia still")
            await self._set_live(False)
            return True, (
                "Debug mode: Sonnia stays still and disconnected from the voice model. "
                "The panel buttons keep working."
            )
        logger.info("Panel: debug mode off; back to %s mode", self.state.mode)
        await self._apply_mode(self.state.mode)
        return True, "Debug mode off: Sonnia goes back to her normal mode."

    async def _act_set_subtitles(self, params: dict[str, Any]) -> tuple[bool, str]:
        enabled = _flag(params, "enabled")
        await self._set_setting("subtitles", enabled)
        return True, (
            "Subtitles visible on the screen."
            if enabled
            else "Subtitles hidden: what is said does not appear on the screen."
        )

    async def _act_set_volume(self, params: dict[str, Any]) -> tuple[bool, str]:
        value = _number(params, "value", 0.0, 1.5)
        await self._set_setting("volume", value)
        return True, f"Volume at {value * 100:.0f} %."

    async def _act_set_mic_gate(self, params: dict[str, Any]) -> tuple[bool, str]:
        value = _number(params, "value", 0.0, 0.2)
        await self._set_setting("mic_gate", value)
        if value <= 0:
            return True, "Noise gate off: Sonnia hears everything."
        return True, "Noise gate adjusted."

    async def _act_set_voice(self, params: dict[str, Any]) -> tuple[bool, str]:
        voice = params.get("voice")
        if voice not in VOICES:
            raise _BadRequest("Invalid voice.")
        if voice == self._settings.live.voice:
            return True, "That voice is already set."
        await self._set_setting("voice", str(voice))
        return True, f"Voice changed to {voice}. The conversation starts again."

    async def _act_set_notes(self, params: dict[str, Any]) -> tuple[bool, str]:
        text = _text(params, "text", max_len=NOTES_MAX_LEN)
        await self._set_setting("notes", text)
        return True, "Notes saved. Sonnia already knows them." if text else "Notes cleared."

    async def _act_set_tuning(self, params: dict[str, Any]) -> tuple[bool, str]:
        changes = {group: params[group] for group in TUNING_LIMITS if group in params}
        if not changes or not all(isinstance(values, dict) for values in changes.values()):
            raise _BadRequest("The mouth, camera or motion values are missing.")
        await self._set_setting("tuning", merge_tuning(self.state.tuning, changes))
        return True, "Setting applied."

    async def _act_reset_tuning(self, params: dict[str, Any]) -> tuple[bool, str]:
        part = params.get("part", "all")
        if part not in (*TUNING_LIMITS, "all"):
            raise _BadRequest("What should be reset: the mouth, the camera, the motion or all?")
        defaults = default_tuning()
        if part == "all":
            tuning = defaults
        else:
            tuning = merge_tuning(self.state.tuning, {part: defaults[part]})
        await self._set_setting("tuning", tuning)
        return True, {
            "mouth": "Mouth as the scene ships it.",
            "camera": "Camera back to its usual framing.",
            "idle": "Idle motion as the scene ships it.",
            "all": "Mouth, camera and motion as the scene ships them.",
        }[str(part)]

    async def _act_prepare_voices(self, params: dict[str, Any]) -> tuple[bool, str]:
        if self._voice_cache is None:
            raise _BadRequest("There is no voice cache.")
        if not self._settings.live.api_key:
            raise _BadRequest("The GPT-Live key is missing to record the lines.")
        if self._voice_cache.busy:
            return True, "They are already being recorded."
        missing = self._voice_cache.missing(self._voice_texts())
        if not missing:
            return True, "All the lines are already recorded."
        self._spawn(self._prepare_voices(), "voice-prepare")
        return True, f"Recording {len(missing)} lines; it takes a few seconds per line."

    # -- settings ---------------------------------------------------------------

    async def _set_setting(self, key: str, value: Any) -> None:
        """A setting changed from the panel: it is applied and saved."""
        if _same(getattr(self.state, key), value):
            return
        await self._apply_setting(key, value)
        self._save()

    async def _apply_setting(self, key: str, value: Any) -> None:
        """Applies an already validated setting to the state, the engine and the client."""
        state = self.state
        engine = self._engine
        hub = self._hub
        if key == "away_message":
            state.away_message = value
            if state.mode == "away":
                await hub.set_sticky("presence", p.msg_presence(False, self._away_message))
        elif key == "notes":
            await engine.set_notes(value)
            state.notes = value
        elif key == "volume":
            state.volume = value
            await hub.set_sticky("volume", p.msg_set_volume(value))
        elif key == "mic_gate":
            state.mic_gate = value
            engine.set_gate(self._default_gate if value is None else value)
        elif key == "voice":
            state.voice = value
            voice = self._default_voice if value is None else value
            if voice != self._settings.live.voice:
                self._settings.live.voice = voice
                await engine.restart_session(f"voice changed to {voice}")
                if self._voice_cache is not None and self._settings.live.api_key:
                    self._spawn(self._prepare_voices(delay=5.0), "voice-change")
        elif key == "showcase":
            state.showcase = value
            engine.set_showcase_enabled(self._default_showcase if value is None else value)
        elif key == "subtitles":
            state.subtitles = value
            await hub.set_sticky("subtitles", p.msg_set_subtitles(value))
        elif key == "disabled_animations":
            state.disabled_animations = value
            await hub.set_sticky("disabled_animations", p.msg_set_disabled_animations(value))
        elif key == "tuning":
            state.tuning = value
            await hub.set_sticky("tuning", p.msg_set_tuning(value))
        elif key == "avatar":
            state.avatar = value
            await hub.set_sticky("avatar", p.msg_set_avatar(value))
        else:  # pragma: no cover - SETTINGS and this go together
            raise ValueError(f"Unknown setting: {key}")

    # -- status -----------------------------------------------------------------

    def _watch_outgoing(self, msg: dict[str, Any]) -> None:
        kind = msg.get("type")
        if kind == p.MSG_SHOW_IMAGE:
            self._image = {"id": msg.get("image_id"), "caption": msg.get("caption")}
        elif kind == p.MSG_HIDE_IMAGE:
            self._image = None

    def _on_animations(self, msg: dict[str, Any]) -> None:
        self._animations = p.parse_animations(msg)
        logger.info("The avatar client has %d animations for the panel", len(self._animations))

    def _on_animation_playing(self, msg: dict[str, Any]) -> None:
        self._current_animation = p.parse_animation_playing(msg)

    def status(self) -> dict[str, Any]:
        """The ``GET /api/status`` snapshot."""
        settings = self._settings
        engine = self._engine
        snap = engine.snapshot()
        usage_s = self.usage_today()
        return {
            "mode": self.state.mode,
            "away_message": self._away_message,
            "state": snap.get("state") or "idle",
            "health": self._health(snap),
            "session": {
                "id": snap.get("session_id") or None,
                "uptime_s": snap.get("uptime_s"),
                "expires_in_s": snap.get("expires_in_s"),
                "context_ratio": snap.get("context_ratio"),
            },
            "usage": {
                "live_seconds": round(usage_s, 1),
                "cost_usd": round(usage_s / 60.0 * settings.panel.live_price_per_minute, 2),
            },
            "image": self._image,
            # Current gallery ids. Uploads (with an "×") start with ``upload-``. ``None``
            # until the first read.
            "gallery": self._gallery_listing,
            "animations": self._animations,
            "current_animation": self._current_animation if self._hub.client_count else None,
            "disabled_animations": self.state.disabled_animations,
            "subtitles": self.state.subtitles,
            "debug": self.state.debug,
            "showcase": {"enabled": engine.showcase_enabled},
            "voice": settings.live.voice,
            "voices": VOICES,
            "volume": self.state.volume,
            "mic_gate": snap.get("mic_gate", 0.0),
            "notes": engine.notes,
            "voice_cache": self._voice_cache_status(),
            "tuning": self.state.tuning,
            "avatar": {"custom": self.state.avatar is not None},
            "trivia": snap.get("trivia") or {"available": False, "active": False},
            "last_error": snap.get("last_error") or None,
            "capabilities": self.capabilities,
        }

    def _health(self, snap: dict[str, Any]) -> dict[str, dict[str, Any]]:
        mode = self.state.mode
        screen = (
            _health(True, "Screen connected")
            if self._hub.client_count > 0
            else _health(
                False,
                "Sonnia's screen is not connected",
                "Open the avatar app on this computer (or close it and open it again).",
            )
        )
        if self.state.debug:
            internet = _health(None, "Debug mode: she does not converse, so there is no cost")
        elif mode != "conversation":
            internet = _health(None, "Not conversing now, so there is no cost")
        elif snap.get("connected"):
            internet = _health(True, "Conversation connected")
        elif not self._settings.live.api_key:
            internet = _health(
                False, "The GPT-Live key is missing", "Set LIVE_API_KEY or OPENAI_API_KEY."
            )
        else:
            internet = _health(
                False,
                "Connecting to GPT-Live…",
                "If it does not connect within a minute, check the internet connection or "
                'switch to "Greeter only" meanwhile.',
            )

        level = float(snap.get("mic_level") or 0.0)
        mic_age = snap.get("mic_age_s")
        sound_age = snap.get("mic_sound_age_s")
        if mode != "conversation" or self.state.debug:
            mic = _health(None, "Not used in this mode")
        elif snap.get("mic_muted"):
            mic = _health(
                False,
                "Microphone muted from the panel",
                'Press "Unmute microphone" so Sonnia can hear again.',
            )
        elif mic_age is None or mic_age > MIC_STALE_S:
            mic = _health(
                False,
                "The microphone sends no audio",
                "Check that it is plugged in; Sonnia retries on her own every few seconds.",
            )
        elif sound_age is None or sound_age > MIC_DEAF_S:
            mic = _health(
                False,
                "The microphone picks up nothing",
                "It may be muted with its own button or unplugged.",
            )
        else:
            mic = _health(True, "Microphone receives sound")
        mic["level"] = level
        mic["muted"] = bool(snap.get("mic_muted"))

        if not snap.get("camera_enabled"):
            camera = _health(None, "Camera disabled")
        elif snap.get("camera_ok") is False:
            camera = _health(
                False,
                "The camera does not respond",
                "Check the USB cable. Sonnia keeps conversing, but without seeing.",
            )
        else:
            camera = _health(True, "Camera ready")
        return {"internet": internet, "screen": screen, "mic": mic, "camera": camera}

    # -- today's usage ----------------------------------------------------------

    def _engine_usage(self) -> float:
        return float(self._engine.snapshot().get("usage_s") or 0.0)

    def _roll_usage_day(self, engine_seconds: float) -> None:
        """When the day changes the counter starts from zero."""
        today = time.strftime("%Y-%m-%d")
        if self.state.usage_date == today:
            self._usage_base = self.state.usage_seconds
            return
        self.state.usage_date = today
        self.state.usage_seconds = 0.0
        # What the engine already had from yesterday does not count for today.
        self._usage_base = -engine_seconds

    def usage_today(self) -> float:
        engine_seconds = self._engine_usage()
        if self.state.usage_date != time.strftime("%Y-%m-%d"):
            self._roll_usage_day(engine_seconds)
        return max(0.0, self._usage_base + engine_seconds)

    def _save_usage(self) -> None:
        self._last_usage_save = time.monotonic()
        self.state.usage_seconds = round(self.usage_today(), 1)
        self._save()

    # -- helpers ----------------------------------------------------------------

    def _save(self) -> None:
        self.state.save(self._state_path)

    def _spawn(self, coro: Any, name: str) -> None:
        task = asyncio.create_task(coro, name=f"sonia-panel-{name}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def gallery(self) -> Gallery:
        return Gallery(self._settings.gallery_dir, self._settings.gallery_upload_dir)

    async def _refresh_gallery(self) -> None:
        """Reads the gallery again for the status, in a thread. Never raises."""
        self._gallery_checked_at = time.monotonic()
        gallery = self.gallery()
        try:
            ids = await asyncio.to_thread(gallery.ids)
        except Exception:  # noqa: BLE001 - without the new list the previous one stays
            logger.exception("Could not read the gallery")
            return
        self._gallery_listing = {"ids": ids}


class _BadRequest(Exception):
    """A panel request that cannot be served (the text goes to the operator)."""


def _health(ok: bool | None, label: str, hint: str = "") -> dict[str, Any]:
    return {"ok": ok, "label": label, "hint": hint if ok is False else ""}


def _text(params: dict[str, Any], name: str, *, max_len: int, required: bool = False) -> str:
    value = params.get(name, "")
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise _BadRequest(f'"{name}" must be text.')
    value = value.strip()
    if required and not value:
        raise _BadRequest("Write something first.")
    if len(value) > max_len:
        raise _BadRequest(f"Too long (at most {max_len} characters).")
    return value


def _flag(params: dict[str, Any], name: str) -> bool:
    value = params.get(name)
    if not isinstance(value, bool):
        raise _BadRequest(f'"{name}" must be yes or no.')
    return value


def _number(params: dict[str, Any], name: str, low: float, high: float) -> float:
    value = params.get(name)
    if not _is_number(value) or not math.isfinite(value):
        raise _BadRequest(f'"{name}" must be a number.')
    return max(low, min(high, float(value)))


def _is_number(value: Any) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _same(a: Any, b: Any) -> bool:
    """Same setting? Compares as JSON (``1`` and ``1.0`` count as equal)."""
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True) or a == b


def _normalize_setting(key: str, value: Any) -> Any:
    """Validates a setting read from the state file. ``ValueError`` if it is not valid."""
    if key == "away_message":
        if not isinstance(value, str):
            raise ValueError(key)
        return value.strip()[:AWAY_MESSAGE_MAX_LEN] or DEFAULT_AWAY_MESSAGE
    if key == "notes":
        if not isinstance(value, str):
            raise ValueError(key)
        return value.strip()[:NOTES_MAX_LEN]
    if key in ("volume", "mic_gate"):
        if value is None and key == "mic_gate":
            return None
        if not _is_number(value) or not math.isfinite(value):
            raise ValueError(key)
        return max(0.0, min(1.5 if key == "volume" else 0.2, float(value)))
    if key == "voice":
        if value is None or value in VOICES:
            return value
        raise ValueError(key)
    if key == "showcase":
        if value is None or isinstance(value, bool):
            return value
        raise ValueError(key)
    if key == "subtitles":
        if isinstance(value, bool):
            return value
        raise ValueError(key)
    if key == "disabled_animations":
        if not isinstance(value, list):
            raise ValueError(key)
        return sorted({c for c in value if isinstance(c, str) and c})
    if key == "tuning":
        if not isinstance(value, dict):
            raise ValueError(key)
        return merge_tuning(value)
    if key == "avatar":
        if value is None:
            return None
        definition = p.parse_avatar_definition(value)
        if definition is None:
            raise ValueError(key)
        return definition
    raise ValueError(key)


def _summary(params: dict[str, Any]) -> str:
    """Parameters for the log, without long texts."""
    if not params:
        return ""
    with contextlib.suppress(Exception):
        return json.dumps(
            {
                k: (v[:40] + "…" if isinstance(v, str) and len(v) > 40 else v)
                for k, v in params.items()
            },
            ensure_ascii=False,
        )
    return ""


def _level(params: dict[str, Any]) -> str | None:
    """Trivia level requested from the panel (easy, medium or hard), or ``None``."""
    from sonia.trivia import normalize_level

    value = params.get("level")
    return normalize_level(value) if isinstance(value, str) else None
