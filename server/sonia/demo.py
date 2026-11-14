"""Offline demo: drives the avatar client with no API key, no network and no cost.

``sonia demo`` starts the same WebSocket hub as ``sonia run`` but, instead of a
voice model, a scripted director plays a short show on a loop: idle lines, a
conversation with subtitles, the waiting indicator, a web search, an image on the
panel, the card of a talk of the example agenda, a dance and a trivia round. Her voice is synthetic: harmonics shaped like
vowels, so the client's lip-sync moves the mouth as with real speech. It is not
meant to sound like a person, only to exercise everything the client draws.

It is for trying the avatar, developing the client and taking screenshots. What
someone types in the client (``text_input``) gets a canned answer and the
client's "interrupt" cuts her off, as in the real thing.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import random
import struct
import zlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, timedelta
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from sonia.agenda import Agenda, AgendaFormatError, parse_json
from sonia.agenda.card import talk_card
from sonia.language import Language, load_language
from sonia.showcase import load_lines
from sonia.trivia.bank import TriviaBank, TriviaQuestion
from sonia.types import AssistantState, AudioChunk
from sonia.ws import protocol as p

logger = logging.getLogger(__name__)

#: Length of each binary audio frame, as GPT-Live sends them.
CHUNK_S = 0.1

#: Vowel formants (F1, F2, F3 in Hz) the synthetic voice cycles through.
_VOWELS: tuple[tuple[float, float, float], ...] = (
    (800.0, 1200.0, 2500.0),  # a
    (450.0, 2000.0, 2600.0),  # e
    (300.0, 2300.0, 3000.0),  # i
    (480.0, 900.0, 2400.0),  # o
    (330.0, 850.0, 2300.0),  # u
)

#: Questions used when the trivia bank is missing or empty.
_FALLBACK_QUESTIONS = (
    TriviaQuestion(
        "What does CPU stand for?",
        ("Central Processing Unit", "Computer Power Unit", "Core Program Utility"),
        0,
    ),
    TriviaQuestion("Which language is known for its indentation rules?", ("C", "Python", "Go"), 1),
    TriviaQuestion("What does HTTP mostly carry?", ("Electricity", "Hypertext", "Hardware"), 1),
)

#: Canned answer for whatever is typed in the client.
TYPED_REPLY = (
    "I'm running the offline demo, so I can't really understand you yet. "
    "Add an API key and start sonia run to have a real conversation."
)


class DemoLink(Protocol):
    """What the director needs from the hub (the real one or a fake in tests)."""

    @property
    def client_count(self) -> int: ...

    @property
    def sample_rate(self) -> int: ...

    async def broadcast_json(self, msg: dict[str, Any]) -> None: ...

    async def send_audio(self, utterance_id: int, chunk: AudioChunk) -> None: ...

    async def set_sticky(self, key: str, msg: dict[str, Any]) -> None:
        """Pins ``msg`` for clients that connect later and broadcasts it now."""

    def clear_sticky(self, key: str) -> None: ...


# ---------------------------------------------------------------------------
# Synthetic voice
# ---------------------------------------------------------------------------


def synth_speech(text: str, sample_rate: int, *, seed: int = 0) -> bytes:
    """Speech-like PCM s16le for ``text``: one vowel-shaped syllable every ~0.2 s.

    The length follows the text (about 14 characters per second), punctuation
    adds short pauses and the pitch falls gently over each phrase. Deterministic
    for the same ``text`` and ``seed``.
    """
    rng = random.Random(f"{seed}:{text}")
    words = text.split() or ["..."]
    pieces: list[np.ndarray] = []
    f0_start = 215.0 + rng.uniform(-10, 10)
    total_syllables = max(1, sum(max(1, round(len(w) / 3)) for w in words))
    index = 0
    for word in words:
        for _ in range(max(1, round(len(word) / 3))):
            progress = index / total_syllables
            f0 = f0_start * (1.0 - 0.18 * progress) + rng.uniform(-8, 8)
            duration = rng.uniform(0.15, 0.24)
            pieces.append(_syllable(sample_rate, duration, f0, rng.choice(_VOWELS), rng))
            index += 1
        gap = 0.05
        if word[-1] in ",;:":
            gap = 0.18
        elif word[-1] in ".!?":
            gap = 0.32
        pieces.append(np.zeros(int(sample_rate * gap), dtype=np.float32))
    signal = np.concatenate(pieces)
    peak = float(np.max(np.abs(signal))) or 1.0
    pcm = np.clip(signal / peak * 0.3 * 32767, -32768, 32767).astype("<i2")
    return pcm.tobytes()


def _syllable(
    sample_rate: int,
    duration: float,
    f0: float,
    formants: tuple[float, float, float],
    rng: random.Random,
) -> np.ndarray:
    n = max(1, int(sample_rate * duration))
    t = np.arange(n, dtype=np.float64) / sample_rate
    vibrato = 1.0 + 0.01 * np.sin(2 * math.pi * 5.0 * t)
    phase = 2 * math.pi * np.cumsum(f0 * vibrato) / sample_rate
    voice = np.zeros(n, dtype=np.float64)
    nyquist = sample_rate / 2
    for k in range(1, int(min(4000.0, nyquist * 0.9) // f0) + 1):
        frequency = k * f0
        gain = sum(1.0 / (1.0 + ((frequency - f) / (60.0 + 0.06 * f)) ** 2) for f in formants)
        voice += gain / k**0.5 * np.sin(k * phase)
    # Raised-cosine envelope: each syllable swells and fades like a spoken one.
    envelope = np.sin(np.linspace(0.0, math.pi, n)) ** 0.8
    voice *= envelope
    # A short burst of noise at the start, like a consonant.
    burst = min(n, int(sample_rate * 0.03))
    noise_rng = np.random.default_rng(rng.randrange(2**32))
    voice[:burst] += noise_rng.normal(0.0, 0.15, burst) * np.linspace(1.0, 0.0, burst)
    return voice.astype(np.float32)


# ---------------------------------------------------------------------------
# Demo picture
# ---------------------------------------------------------------------------


def demo_picture(width: int = 960, height: int = 640) -> bytes:
    """A PNG drawn in code (a gradient with soft circles), for an empty gallery."""
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    u, v = x / width, y / height
    red = 40 + 120 * u
    green = 60 + 90 * v
    blue = 160 + 80 * (1 - u)
    for cx, cy, radius, tint in (
        (0.3, 0.4, 0.22, (255, 200, 90)),
        (0.7, 0.65, 0.18, (120, 230, 200)),
    ):
        distance = np.sqrt(((u - cx) * width / height) ** 2 + (v - cy) ** 2)
        alpha = np.clip(1.0 - distance / radius, 0.0, 1.0) ** 1.5
        red = red * (1 - alpha) + tint[0] * alpha
        green = green * (1 - alpha) + tint[1] * alpha
        blue = blue * (1 - alpha) + tint[2] * alpha
    rgb = np.stack([red, green, blue], axis=-1).clip(0, 255).astype(np.uint8)
    return _png(rgb)


def _png(rgb: np.ndarray) -> bytes:
    height, width, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[row].tobytes() for row in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def gallery_picture(gallery_dir: Path, rng: random.Random) -> tuple[str, bytes, str]:
    """``(image_id, data, mime)``: a random image of the gallery, or the drawn one."""
    from sonia.actions.gallery import Gallery

    gallery = Gallery(gallery_dir)
    ids = gallery.ids()
    if ids:
        image_id = rng.choice(ids)
        loaded = gallery.load(image_id)
        if loaded is not None:
            return image_id, loaded[0], loaded[1]
    return "demo", demo_picture(), "image/png"


# ---------------------------------------------------------------------------
# Director
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DemoContent:
    """What the show says and shows. Built from the assets with :meth:`load`."""

    idle_lines: tuple[str, ...]
    questions: tuple[TriviaQuestion, ...]
    picture: tuple[str, bytes, str]
    #: The example agenda (``assets/agenda/example.json``) for the talk card, if there is one.
    agenda: Agenda | None = None

    @classmethod
    def load(cls, assets_dir: Path, rng: random.Random) -> DemoContent:
        lines = tuple(load_lines(assets_dir / "showcase" / "lines.md")) or (
            "Hi there! Come closer and say hello.",
        )
        bank = TriviaBank.from_file(assets_dir / "trivia" / "questions.md")
        questions = tuple(bank.draw(3, rng)) if len(bank) >= 3 else _FALLBACK_QUESTIONS
        return cls(
            lines,
            questions,
            gallery_picture(assets_dir / "gallery", rng),
            _example_agenda(assets_dir),
        )


def _example_agenda(assets_dir: Path) -> Agenda | None:
    try:
        text = (assets_dir / "agenda" / "example.json").read_text(encoding="utf-8")
        agenda = parse_json(text, UTC)
    except (OSError, AgendaFormatError):
        return None
    return agenda if agenda.talks else None


class DemoDirector:
    """Plays the scripted show to whatever client is connected.

    ``time_scale`` multiplies every wait: 1 is real time, 0 runs the whole show
    at once (tests).
    """

    def __init__(
        self,
        link: DemoLink,
        content: DemoContent,
        *,
        time_scale: float = 1.0,
        seed: int | None = None,
        language: Language | None = None,
    ) -> None:
        self._link = link
        #: Only the screen texts change with ``LANGUAGE``: the scripted lines are English.
        self._language = language or load_language("en")
        self._content = content
        self._scale = max(0.0, time_scale)
        self._rng = random.Random(seed)
        self._uid = 0
        self._cut = asyncio.Event()
        self._typed: asyncio.Queue[str] = asyncio.Queue()

    # -- inputs from the client --------------------------------------------

    def on_text_input(self, msg: dict[str, Any]) -> None:
        text = str(msg.get("text", "")).strip()
        if text:
            self._typed.put_nowait(text[:200])

    def on_interrupt(self, _msg: dict[str, Any]) -> None:
        self._cut.set()

    # -- show ---------------------------------------------------------------

    async def run(self, *, loops: int | None = None) -> None:
        """Plays the show ``loops`` times (forever with ``None``)."""
        await self._link.set_sticky("stage_mode", p.msg_stage_mode("conversation", True))
        played = 0
        while loops is None or played < loops:
            await self._wait_for_client()
            for scene in self._scenes():
                await self._answer_typed()
                await scene()
            played += 1

    def _scenes(self) -> list[Callable[[], Awaitable[None]]]:
        return [
            self._scene_idle_line,
            self._scene_greeting,
            self._scene_search,
            self._scene_picture,
            self._scene_talk,
            self._scene_dance,
            self._scene_trivia,
        ]

    async def _scene_idle_line(self) -> None:
        await self._state(AssistantState.IDLE)
        await self._pause(2.0)
        await self._link.broadcast_json(p.msg_attention("soft"))
        await self._pause(0.25)
        await self._say(self._rng.choice(self._content.idle_lines), ambient=True)
        await self._pause(3.0)

    async def _scene_greeting(self) -> None:
        await self._user_says("Hi Sonnia! What can you do?")
        await self._think(0.6)
        await self._say(
            "Hi! I can chat with you, look through my camera when you ask, "
            "show pictures, look things up and host a trivia game."
        )
        await self._listen_after()

    async def _scene_search(self) -> None:
        await self._user_says("Can you look up something on the web for me?")
        await self._think(0.4)
        await self._say("Sure, give me a second.")
        await self._busy("search", self._language.text("searching"), 3.0, activity="search")
        # The show_emotion action (docs/actions.md), so the client's side can be seen offline.
        await self._link.broadcast_json(p.msg_show_emotion("surprise", 2.5))
        await self._say("Here's what I found. In the real thing, this is a live web search.")
        await self._listen_after()

    async def _scene_picture(self) -> None:
        await self._user_says("Show me a picture.")
        await self._busy("think", self._language.text("thinking"), 1.2, activity="think")
        image_id, data, mime = self._content.picture
        await self._link.broadcast_json(
            p.msg_show_image(image_id, "gallery", mime, data, caption="From the gallery")
        )
        await self._say("Here's one from my gallery. Add your own images to assets/gallery.")
        await self._pause(4.0)
        await self._link.broadcast_json(p.msg_hide_image())
        await self._listen_after()

    async def _scene_talk(self) -> None:
        agenda = self._content.agenda
        if agenda is None:
            return
        talk = agenda.by_id().get("voice-agents") or agenda.talks[0]
        await self._user_says(f'When is "{talk.title}"?')
        await self._busy("think", self._language.text("thinking"), 0.8, activity="think")
        # As if it were a quarter of an hour before: the card says it is up next.
        moment = talk.start - timedelta(minutes=15)
        await self._link.broadcast_json(talk_card(agenda, talk, UTC, self._language, moment))
        await self._say("Here's its card. With your own agenda in AGENDA_SOURCE, this is live.")
        await self._pause(4.0)
        await self._link.broadcast_json(p.msg_hide_image())
        await self._listen_after()

    async def _scene_dance(self) -> None:
        await self._user_says("Can you dance?")
        await self._think(0.4)
        await self._link.broadcast_json(p.msg_attention("dance"))
        await self._pause(0.6)
        await self._say("Watch this!")
        await self._pause(5.0)
        await self._listen_after()

    async def _scene_trivia(self) -> None:
        questions = self._content.questions
        total = len(questions)
        threshold = max(1, total - 1)
        await self._user_says("Let's play trivia!")
        await self._think(0.5)
        start = p.msg_trivia_start(total, threshold, "easy")
        await self._link.set_sticky("trivia", start)
        await self._say(f"Great! {total} questions, get {threshold} right to win.")
        score = 0
        for number, question in enumerate(questions, start=1):
            await self._link.broadcast_json(
                p.msg_trivia_question(number, total, question.text, list(question.options), score)
            )
            await self._say(question.text)
            await self._pause(1.5)
            # The player gets every answer right but the last one.
            chosen = question.correct if number < total else (question.correct + 1) % 3
            await self._user_says("ABC"[chosen])
            correct = chosen == question.correct
            score += int(correct)
            await self._link.broadcast_json(
                p.msg_trivia_answer(number, chosen, question.correct, correct, score)
            )
            await self._say(
                "That's right!"
                if correct
                else f"Not quite, it was {question.options[question.correct]}."
            )
        won = score >= threshold
        await self._link.broadcast_json(p.msg_trivia_end(score, total, won=won, reason="finished"))
        self._link.clear_sticky("trivia")
        await self._say(f"You got {score} out of {total}. {'You win!' if won else 'So close!'}")
        await self._listen_after()

    # -- building blocks ------------------------------------------------------

    async def _answer_typed(self) -> None:
        while not self._typed.empty():
            text = self._typed.get_nowait()
            await self._link.broadcast_json(p.msg_transcript("user", text, True))
            await self._think(0.5)
            await self._say(TYPED_REPLY)
            await self._listen_after()

    async def _user_says(self, text: str) -> None:
        await self._state(AssistantState.LISTENING)
        words = text.split()
        for count in range(1, len(words) + 1):
            await self._link.broadcast_json(
                p.msg_transcript("user", " ".join(words[:count]), False)
            )
            await self._pause(0.25)
        await self._link.broadcast_json(p.msg_transcript("user", text, True))

    async def _think(self, seconds: float) -> None:
        await self._state(AssistantState.THINKING)
        await self._pause(seconds)

    async def _busy(self, kind: str, text: str, seconds: float, *, activity: str) -> None:
        await self._state(AssistantState.THINKING)
        await self._link.broadcast_json(p.msg_activity(activity))
        await self._link.set_sticky("busy", p.msg_busy(True, kind, text))
        await self._pause(seconds)
        self._link.clear_sticky("busy")
        await self._link.broadcast_json(p.msg_busy(False))
        await self._link.broadcast_json(p.msg_activity("none"))

    async def _listen_after(self) -> None:
        await self._state(AssistantState.LISTENING)
        await self._pause(1.5)
        await self._state(AssistantState.IDLE)
        await self._pause(1.5)

    async def _say(self, text: str, *, ambient: bool = False) -> None:
        """One utterance: ``speech_start``, audio at real time, ``speech_end``."""
        link = self._link
        rate = link.sample_rate
        pcm = await asyncio.to_thread(synth_speech, text, rate)
        self._uid += 1
        uid = self._uid
        self._cut.clear()
        await link.broadcast_json(p.msg_speech_start(uid, text, ambient=ambient))
        if not ambient:
            await self._state(AssistantState.SPEAKING)
        await link.broadcast_json(p.msg_transcript("assistant", text, False))
        step = max(2, int(rate * CHUNK_S) * 2)
        for start in range(0, len(pcm), step):
            if self._cut.is_set():
                await link.broadcast_json(p.msg_stop_speaking())
                break
            await link.send_audio(uid, AudioChunk(pcm=pcm[start : start + step], sample_rate=rate))
            await self._pause(CHUNK_S)
        await link.send_audio(uid, AudioChunk(pcm=b"", sample_rate=rate, is_last=True))
        await link.broadcast_json(p.msg_transcript("assistant", text, True))
        await link.broadcast_json(p.msg_speech_end(uid))

    async def _state(self, state: AssistantState) -> None:
        await self._link.broadcast_json(p.msg_state(state))

    async def _pause(self, seconds: float) -> None:
        await asyncio.sleep(seconds * self._scale)

    async def _wait_for_client(self) -> None:
        if self._link.client_count:
            return
        logger.info("Waiting for the avatar client to connect…")
        while not self._link.client_count:  # noqa: ASYNC110 - the hub has no connect event
            await asyncio.sleep(0.2)
        # Give it a moment to load the scene after ``hello``.
        await self._pause(1.0)


async def run_demo(
    *,
    host: str,
    port: int,
    sample_rate: int,
    assets_dir: Path,
    volume: float,
    loops: int | None = None,
    language: Language | None = None,
) -> int:
    """``sonia demo``: the hub plus the director, until Ctrl+C or ``loops`` shows."""
    from sonia.config import WSSettings
    from sonia.ws.hub import Hub

    hub = Hub(WSSettings(host=host, port=port), sample_rate)
    content = await asyncio.to_thread(DemoContent.load, assets_dir, random.Random())
    screen = language or load_language("en")
    director = DemoDirector(hub, content, language=screen)
    hub.on(p.MSG_TEXT_INPUT, director.on_text_input)
    hub.on(p.MSG_INTERRUPT, director.on_interrupt)
    await hub.set_sticky("volume", p.msg_set_volume(volume))
    await hub.set_sticky("screen_texts", p.msg_screen_texts(screen.code, screen.texts))
    async with hub:
        logger.info(
            "Offline demo on ws://%s:%d/ (no API key, no network). Ctrl+C to stop.",
            host,
            hub.port,
        )
        with contextlib.suppress(asyncio.CancelledError):
            await director.run(loops=loops)
    return 0
