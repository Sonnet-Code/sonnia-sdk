"""Sonnia settings. Everything comes from environment variables or `.env`.

No module should read `os.environ` directly: it receives a `Settings` (or the
part it needs) as a parameter. That way tests can build the configuration by
hand.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from sonia.paths import BUNDLE_ROOT, env_files, home

#: Root of `cache/` and `overrides.env` (see `sonia/paths.py`).
_HOME = home()


class LLMSettings(BaseSettings):
    """Vision model that describes the camera (the speech-to-speech model takes no images).

    Any OpenAI-compatible endpoint (Chat Completions). OpenAI's API by default;
    without ``LLM_API_KEY`` the OpenAI key is used (``OPENAI_API_KEY`` or, if
    missing, ``LIVE_API_KEY``), but only against OpenAI itself (see :attr:`key`).
    """

    model_config = SettingsConfigDict(
        env_prefix="LLM_", extra="ignore", env_ignore_empty=True, populate_by_name=True
    )

    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-6-luna"
    #: ``LLM_API_KEY``: the key of the model server.
    api_key: str = Field(default="", repr=False)
    #: OpenAI key (``OPENAI_API_KEY`` or, if missing, the realtime one,
    #: ``LIVE_API_KEY``), only used when ``base_url`` is OpenAI's API.
    openai_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("OPENAI_API_KEY", "LIVE_API_KEY"),
        repr=False,
    )
    #: If False, Sonnia does not look through the camera (no camera notes, no ``look``).
    supports_vision: bool = True
    #: Sent as ``reasoning_effort`` unless it is ``off``. An empty value cannot remove it:
    #: in ``.env`` it is the same as not setting the variable, which gives back ``none``.
    #: ``none`` because with ``low`` the default model took twice as long to describe a photo.
    reasoning_effort: str = "none"
    #: Only sent when not None (some models only accept their default value).
    temperature: float | None = None
    max_tokens: int = 400
    #: Field name used to send ``max_tokens``: OpenAI's API wants
    #: ``max_completion_tokens`` for its reasoning models; other servers, ``max_tokens``.
    max_tokens_param: Literal["max_tokens", "max_completion_tokens"] = "max_completion_tokens"
    #: ``detail`` sent with each image (low, high, auto). ``off`` does not send it:
    #: outside OpenAI the field is not documented and a strict server may reject it.
    image_detail: str = "low"
    #: Extra request body fields, as JSON in ``LLM_EXTRA_BODY``, for whatever each
    #: server needs (for example a flag that turns off a model's reasoning).
    extra_body: dict[str, Any] = Field(default_factory=dict)
    request_timeout: float = 60.0

    @property
    def key(self) -> str:
        """The key that is sent: ``LLM_API_KEY`` or, against OpenAI's API, the OpenAI one.

        With another provider and no ``LLM_API_KEY`` it is empty: the OpenAI key
        never goes to another server.
        """
        if self.api_key:
            return self.api_key
        return self.openai_api_key if is_openai_url(self.base_url) else ""


def is_openai_url(url: str) -> bool:
    """Is ``url`` OpenAI's API (``api.openai.com`` over HTTPS)?"""
    parsed = urlparse(url.strip())
    return parsed.scheme == "https" and (parsed.hostname or "") == "api.openai.com"


class AudioSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUDIO_", extra="ignore", env_ignore_empty=True)

    #: Index or name of the sounddevice input device ("" = default).
    input_device: str = ""
    #: Size of the microphone blocks sent to the realtime model, in milliseconds.
    block_ms: int = 32


class VisionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VISION_", extra="ignore", env_ignore_empty=True)

    #: opencv = capture from Python; unity = the avatar client sends frames over the WebSocket; none.
    source: Literal["opencv", "unity", "none"] = "opencv"
    camera_index: int = 0
    #: Resolution requested from the USB camera if it opens below it (many webcams open at
    #: 640x480 on Windows even though they do 1080p). If it gives no image at that size,
    #: the camera keeps its own. 0 = whatever the camera gives.
    capture_width: int = 1920
    capture_height: int = 1080
    max_width: int = 768
    jpeg_quality: int = 80
    #: Describe the camera when the user starts speaking (``[Camera]`` note).
    #: Off by default: Sonnia only looks when she decides to, with the ``look`` action.
    on_turn_start: bool = False
    #: Also attach a snapshot every N seconds even if the model did not ask (0 = never).
    interval_seconds: float = 0.0
    #: Save snapshots to disk (debugging only; never with real visitors).
    debug_save_frames: bool = False
    debug_dir: str = str(_HOME / "debug_frames")


class WSSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WS_", extra="ignore", env_ignore_empty=True)

    host: str = "127.0.0.1"
    port: int = 8765


class LiveSettings(BaseSettings):
    """Speech-to-speech engine (OpenAI GPT-Live).

    The realtime model hears the microphone and speaks with its own voice over a
    single WebSocket: it replaces voice detection, speech recognition, the text
    model and TTS. Actions are run by a Responses API backend the realtime model
    delegates to (``backend_*``).
    """

    model_config = SettingsConfigDict(
        env_prefix="LIVE_", extra="ignore", env_ignore_empty=True, populate_by_name=True
    )

    url: str = "wss://api.openai.com/v1/live/sessions"
    #: API key. If ``LIVE_API_KEY`` is missing, ``OPENAI_API_KEY`` is used.
    api_key: str = Field(
        default="", validation_alias=AliasChoices("LIVE_API_KEY", "OPENAI_API_KEY")
    )
    model: str = "gpt-live-1"
    #: Built-in voice (marin, cedar, coral, shimmer...). Fixed for the whole session.
    voice: str = "marin"
    #: PCM rate in both directions. The API accepts 16000 or 24000. It is a
    #: validated ``int`` and not a ``Literal``: from ``.env`` it arrives as text and
    #: pydantic does not convert text to an integer ``Literal``.
    sample_rate: int = 24_000
    #: Responses API model that runs the delegated tasks and the actions.
    backend_model: str = "gpt-6-luna"
    #: Backend ``reasoning.effort`` (empty = the model's default).
    backend_reasoning_effort: str = "low"
    #: Backend ``service_tier`` (empty = not sent; ``priority`` = faster).
    backend_service_tier: str = ""
    #: Token cap of each backend response, reasoning and searches included. With 400 web
    #: searches were cut short and the realtime model reported "Responses handoff
    #: incomplete"; only what it writes is billed, and its answers stay short.
    backend_max_output_tokens: int = 2000
    #: Rounds of actions allowed to the backend per delegated task.
    backend_max_tool_rounds: int = 3
    #: ``LIVE_BACKEND_WEB_SEARCH``: the backend may search the web (the Responses API
    #: ``web_search`` tool, run by OpenAI) to answer what is not in the knowledge
    #: base. Each search is billed separately.
    backend_web_search: bool = True
    #: How much web context each search reads: ``low`` (faster), ``medium`` or ``high``.
    backend_web_search_context: str = "low"
    #: Where Sonnia is, so searches give local results (ISO country code and city).
    #: Empty = not sent.
    backend_web_search_country: str = ""
    backend_web_search_city: str = ""
    #: Silence in Sonnia's voice that closes an utterance for the avatar client.
    segment_gap_ms: int = 800
    #: Silence in the user's transcript that closes their turn.
    user_turn_gap_ms: int = 1_200
    #: Noise gate: RMS level (0..1) below which silence is sent instead of the
    #: microphone. 0 turns it off. Keeps the realtime model from hearing background
    #: conversations; calibrate it on site.
    gate_rms: float = 0.0
    #: How long the gate stays open after the last voice above the threshold.
    gate_hold_ms: int = 900
    #: Very soft noise (RMS 0..1) the realtime model hears when it is not sent the
    #: microphone (closed gate, muted microphone, recorded line, ``--no-mic``). With
    #: absolute zeros it understood the user 7 to 40 s late and did not say what the
    #: backend returned until it heard something again. 0 = zeros.
    comfort_noise_rms: float = 0.003
    #: Minimum time between two camera descriptions (each one is a vision model request).
    vision_min_interval_seconds: float = 10.0
    #: Restart the session at the next quiet moment once the context passes this ratio.
    context_restart_ratio: float = 0.85
    connect_timeout: float = 15.0
    #: Waits between reconnections (they grow from the minimum to the maximum).
    reconnect_min_seconds: float = 1.0
    reconnect_max_seconds: float = 15.0

    @field_validator("sample_rate")
    @classmethod
    def _check_sample_rate(cls, value: int) -> int:
        if value not in (16_000, 24_000):
            raise ValueError("LIVE_SAMPLE_RATE must be 16000 or 24000")
        return value


class ShowcaseSettings(BaseSettings):
    """Idle animation: lines and sung dances when nobody is around."""

    model_config = SettingsConfigDict(env_prefix="SHOWCASE_", extra="ignore", env_ignore_empty=True)

    enabled: bool = True
    #: Seconds idle before the first bit.
    first_delay_seconds: float = 25.0
    #: Minimum and maximum seconds between bits.
    interval_min_seconds: float = 40.0
    interval_max_seconds: float = 90.0
    #: Probability that a bit is a sung dance instead of a line.
    dance_chance: float = 0.3
    #: Probability that a line comes with a fourth-wall gesture.
    gesture_chance: float = 0.5
    #: Of what is not a dance, the share of moments: an invitation to come closer
    #: that the realtime model improvises from what is happening now (what the camera
    #: sees or something people can try) instead of a fixed line. 0 = fixed lines only.
    moment_chance: float = 0.6
    #: Let moments also use what the camera sees (one snapshot described by the vision
    #: model every few moments; it is never stored).
    moment_camera: bool = True


class TriviaSettings(BaseSettings):
    """Trivia mode: multiple-choice questions on the avatar's screen.

    The realtime model understands what the user answers and records it with the
    ``trivia_answer`` action; the orchestrator keeps the answer key and drives the screen.
    """

    model_config = SettingsConfigDict(env_prefix="TRIVIA_", extra="ignore", env_ignore_empty=True)

    enabled: bool = True
    #: Questions per game (drawn at random from ``assets/trivia/questions.md``).
    questions: int = 5
    #: Correct answers needed to win.
    win_threshold: int = 3
    #: With no answer for this long, Sonnia repeats the question once.
    remind_seconds: float = 25.0
    #: Without hearing the user for this long, the game is cancelled (they left).
    abandon_seconds: float = 60.0
    #: After the last answer, minimum time the result stays on screen before the final screen.
    #: Between questions there is no timer: the next one comes when the user asks for it.
    reveal_seconds: float = 4.0
    #: Maximum wait for Sonnia to finish telling the final result before the final screen.
    final_wait_seconds: float = 20.0
    #: Level when the user does not choose one: easy, medium or hard.
    default_level: str = "medium"
    #: Who Sonnia sends winners to (for example "the people at the desk"); empty = nobody.
    #: Sonnia does not know about prizes: she never promises any.
    win_contact: str = ""


class PanelSettings(BaseSettings):
    """Local web control panel (``sonia/panel``)."""

    model_config = SettingsConfigDict(env_prefix="PANEL_", extra="ignore", env_ignore_empty=True)

    enabled: bool = True
    #: Local only: the panel has no authentication of its own.
    host: str = "127.0.0.1"
    port: int = 8780
    #: Where the panel state is saved (mode, notes, volume...).
    state_file: str = str(_HOME / "cache" / "panel_state.json")
    #: Cache of fixed lines recorded with the realtime model's voice.
    voice_cache_dir: str = str(_HOME / "cache" / "voice")
    #: "Greeter" mode: seconds between greetings (minimum and maximum).
    greeter_interval_min_seconds: float = 25.0
    greeter_interval_max_seconds: float = 55.0
    #: Realtime model price per session minute, to estimate the cost.
    live_price_per_minute: float = 0.05


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # In pydantic-settings the last file wins: the opposite of env_files().
        env_file=(".env", *reversed(env_files())),
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    live: LiveSettings = Field(default_factory=LiveSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    vision: VisionSettings = Field(default_factory=VisionSettings)
    ws: WSSettings = Field(default_factory=WSSettings)
    showcase: ShowcaseSettings = Field(default_factory=ShowcaseSettings)
    trivia: TriviaSettings = Field(default_factory=TriviaSettings)
    panel: PanelSettings = Field(default_factory=PanelSettings)

    assets_dir: str = str(BUNDLE_ROOT / "assets")
    log_level: str = "INFO"
    #: ``DEVICES_FILE``: microphone and camera chosen in the avatar's options menu (sonia/devices.py).
    devices_file: str = str(_HOME / "cache" / "devices.json")
    #: ``TIMEZONE``: the IANA time zone Sonnia uses for the date and time she knows
    #: (for example ``Europe/Madrid``). Empty = the system time zone.
    timezone: str = ""
    #: Restart the conversation after N seconds without activity (kiosk mode).
    idle_reset_seconds: float = 120.0
    #: Hide a shown image on its own after N seconds (0 = never). The model hides it
    #: when the topic changes, but if it forgets, the image does not stay there.
    image_auto_hide_seconds: float = 30.0
    #: ``GALLERY_WATCH_SECONDS``: how often ``assets/gallery`` is checked; what is added
    #: or removed is told to the open session with a silent ``[Gallery]`` note
    #: (0 = do not watch: the new list arrives with the next session).
    gallery_watch_seconds: float = 5.0
    #: ``GALLERY_UPLOAD_DIR``: where images uploaded from the panel are stored. Writable
    #: and outside ``assets``, which may live inside a read-only app bundle.
    gallery_upload_dir: str = str(_HOME / "cache" / "gallery")
    #: ``KNOWLEDGE_EXTRA_DIR``: another knowledge folder read after ``assets/knowledge``,
    #: for example with test data. Empty by default.
    knowledge_extra_dir: str = ""
    #: ``SONIA_PARENT_PID``: the PID of the app that launched the orchestrator (the avatar
    #: client sets it when it starts the orchestrator itself). If that app dies, the
    #: orchestrator exits on its own (``sonia/parent.py``). Empty when launched by hand.
    sonia_parent_pid: int | None = None

    @field_validator("sonia_parent_pid", mode="before")
    @classmethod
    def _check_parent_pid(cls, value: Any) -> int | None:
        # An odd value must not keep Sonnia from starting: no watching then.
        try:
            pid = int(str(value).strip())
        except (TypeError, ValueError):
            return None
        return pid if pid > 0 else None

    @property
    def gallery_dir(self) -> Path:
        return Path(self.assets_dir) / "gallery"

    @property
    def showcase_dir(self) -> Path:
        return Path(self.assets_dir) / "showcase"

    @property
    def knowledge_dir(self) -> Path:
        return Path(self.assets_dir) / "knowledge"

    @property
    def knowledge_dirs(self) -> list[Path]:
        """``assets/knowledge`` and, if set, the extra one (``KNOWLEDGE_EXTRA_DIR``)."""
        extra = [Path(self.knowledge_extra_dir)] if self.knowledge_extra_dir.strip() else []
        return [self.knowledge_dir, *extra]

    @property
    def trivia_file(self) -> Path:
        return Path(self.assets_dir) / "trivia" / "questions.md"


def load_settings() -> Settings:
    """Loads the variables (`overrides.env`, the repo `.env` and the one in the cwd) and builds the settings."""
    from dotenv import load_dotenv

    # No override: the first file that defines a variable wins.
    for candidate in (*env_files(), Path(".env")):
        if candidate.is_file():
            load_dotenv(candidate, override=False)
    return Settings()
