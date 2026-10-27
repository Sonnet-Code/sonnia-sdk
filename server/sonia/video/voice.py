"""La toma de voz del guion entero y los tiempos de cada palabra, con caché en disco.

Una sola toma para todo el guion (suena más natural que frases sueltas). La caché va
por el hash de lo que decide el audio (motor, voz, modelo, estilo, ajustes y texto):
repetir un vídeo cambiando la luz o el encuadre no vuelve a pagar la voz. Las
transcripciones también se guardan, por el hash del audio.

Tiempos por palabra, de mejor a peor:

1. ElevenLabs: su alineación por caracteres.
2. Gemini (y el motor ``archivo``): ``gemini-3.5-transcribe`` alineado con el guion.
3. Respaldo local: las palabras repartidas por los tramos con voz (``align.distribute``).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from sonia.video import elevenlabs as eleven
from sonia.video import gemini
from sonia.video.align import TimedWord, align_words, distribute, fill_gaps
from sonia.video.audio import (
    SAMPLE_RATE,
    Samples,
    pcm16_to_float,
    read_wav,
    resample,
    write_wav,
)
from sonia.video.errors import VideoError
from sonia.video.home import ELEVENLABS_KEY, GEMINI_KEY, require_key
from sonia.video.script import PhraseText, Script, tts_text

__all__ = ["Take", "VoiceCache", "VoiceMaker", "decode_audio"]

logger = logging.getLogger(__name__)

#: Por debajo de esta fracción de palabras casadas, la transcripción no vale (¿otro texto?).
MIN_MATCHED = 0.5


@dataclass(slots=True)
class Take:
    """La voz del guion: audio a 24 kHz y el inicio y el fin de cada palabra dicha."""

    samples: Samples
    rate: int
    #: Uno por palabra dicha del guion, en orden (``PhraseText.spoken_words`` seguidas).
    words: list[tuple[float, float]]
    engine: str
    voice: str
    model: str
    #: De dónde salen los tiempos: ``elevenlabs``, ``transcripcion`` o ``local``.
    timing: str
    #: El audio salió de la caché (no se pagó).
    cached: bool = False

    @property
    def duration(self) -> float:
        return len(self.samples) / self.rate if self.rate else 0.0


def _digest(parts: dict[str, Any]) -> str:
    raw = json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _audio_digest(samples: Samples) -> str:
    return hashlib.sha256(np.ascontiguousarray(samples).tobytes()).hexdigest()[:32]


class VoiceCache:
    """Tomas y transcripciones ya pagadas, en ``<home>/cache``."""

    def __init__(self, root: Path) -> None:
        self.audio_dir = root / "voz"
        self.words_dir = root / "tiempos"

    def load_take(self, key: str) -> tuple[Samples, int, dict[str, Any]] | None:
        wav = self.audio_dir / f"{key}.wav"
        meta_path = self.audio_dir / f"{key}.json"
        if not wav.is_file() or not meta_path.is_file():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            samples, rate = read_wav(wav)
        except (OSError, ValueError, VideoError):
            logger.warning("Toma de la caché ilegible (%s); se vuelve a pedir", key)
            return None
        return samples, rate, meta if isinstance(meta, dict) else {}

    def save_take(self, key: str, samples: Samples, rate: int, meta: dict[str, Any]) -> None:
        write_wav(self.audio_dir / f"{key}.wav", samples, rate)
        (self.audio_dir / f"{key}.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    def load_words(self, key: str) -> list[TimedWord] | None:
        path = self.words_dir / f"{key}.json"
        if not path.is_file():
            return None
        try:
            items = json.loads(path.read_text(encoding="utf-8"))
            return [TimedWord(str(w["text"]), float(w["start"]), float(w["end"])) for w in items]
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def save_words(self, key: str, words: Sequence[TimedWord]) -> None:
        self.words_dir.mkdir(parents=True, exist_ok=True)
        (self.words_dir / f"{key}.json").write_text(
            json.dumps(
                [{"text": w.text, "start": w.start, "end": w.end} for w in words],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


def decode_audio(path: Path, ffmpeg: str | None) -> Samples:
    """Un WAV o MP3 → mono a 24 kHz (con ffmpeg; sin él, solo WAV PCM)."""
    if ffmpeg:
        try:
            result = subprocess.run(
                [ffmpeg, "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SAMPLE_RATE)]
                + ["-f", "s16le", "-"],
                capture_output=True,
                check=False,
                timeout=300,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise VideoError(f"ffmpeg no pudo leer {path.name}: {exc}") from None
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip()[-400:]
            raise VideoError(f"ffmpeg no pudo leer {path.name}: {detail}")
        return pcm16_to_float(result.stdout)
    if path.suffix.lower() != ".wav":
        raise VideoError(f"Para leer {path.name} hace falta ffmpeg (o pásalo a WAV).")
    samples, rate = read_wav(path)
    return resample(samples, rate)


class VoiceMaker:
    """Hace (o saca de la caché) la toma de un guion. Las claves se piden al necesitarlas."""

    def __init__(
        self,
        cache: VoiceCache,
        *,
        ffmpeg: str | None = None,
        gemini_transport: httpx.AsyncBaseTransport | None = None,
        eleven_transport: httpx.AsyncBaseTransport | None = None,
        backoff_s: float = 2.0,
    ) -> None:
        self._cache = cache
        self._ffmpeg = ffmpeg
        self._gemini_transport = gemini_transport
        self._eleven_transport = eleven_transport
        self._backoff_s = backoff_s

    def gemini_client(self) -> gemini.GeminiClient:
        key = require_key(GEMINI_KEY, "la voz y la transcripción de Gemini")
        return gemini.GeminiClient(key, transport=self._gemini_transport, backoff_s=self._backoff_s)

    def eleven_client(self) -> eleven.ElevenLabsClient:
        key = require_key(ELEVENLABS_KEY, "la voz de ElevenLabs")
        return eleven.ElevenLabsClient(
            key, transport=self._eleven_transport, backoff_s=self._backoff_s
        )

    # -- la toma -------------------------------------------------------------------

    async def take(self, script: Script, phrases: Sequence[PhraseText]) -> Take:
        """La toma del guion con los tiempos de cada palabra dicha."""
        text = tts_text(list(phrases))
        engine = script.voice.engine
        heard: list[TimedWord] | None = None
        timing = "elevenlabs"
        if engine == "gemini":
            samples, voice, model, cached = await self._gemini_take(script, text)
        elif engine == "elevenlabs":
            samples, voice, model, cached, heard = await self._eleven_take(script, text)
        else:
            samples = decode_audio(Path(script.voice.file), self._ffmpeg)
            if not len(samples):
                raise VideoError(f"El audio {script.voice.file} está vacío.")
            voice, model, cached = Path(script.voice.file).name, "", True
        words = [w for p in phrases for w in p.spoken_words]
        duration = len(samples) / SAMPLE_RATE
        times: list[tuple[float, float]] | None = None
        if heard:
            times = self._match(words, heard, duration)
        if times is None:
            heard = await self._transcribe(samples, script.voice.language)
            if heard:
                times = self._match(words, heard, duration)
                timing = "transcripcion"
        if times is None:
            logger.warning(
                "Sin tiempos por palabra fiables: reparto las palabras por la energía de la voz"
            )
            times = distribute([p.spoken_words for p in phrases], samples, SAMPLE_RATE)
            timing = "local"
        return Take(
            samples=samples,
            rate=SAMPLE_RATE,
            words=times,
            engine=engine,
            voice=voice,
            model=model,
            timing=timing,
            cached=cached,
        )

    @staticmethod
    def _match(
        words: Sequence[str], heard: Sequence[TimedWord], duration: float
    ) -> list[tuple[float, float]] | None:
        aligned = align_words(words, heard)
        matched = sum(1 for t in aligned if t is not None)
        if not words or matched / len(words) < MIN_MATCHED:
            logger.warning(
                "Los tiempos casan con %d de %d palabras del guion: no valen", matched, len(words)
            )
            return None
        return fill_gaps(aligned, words, end=duration)

    async def _gemini_take(self, script: Script, text: str) -> tuple[Samples, str, str, bool]:
        voice = script.voice.voice.strip() or gemini.DEFAULT_VOICE
        model = script.voice.model.strip() or gemini.TTS_MODEL
        style = gemini.style_for(script.voice.style)
        key = _digest(
            {"engine": "gemini", "voice": voice, "model": model, "style": style, "text": text}
        )
        hit = self._cache.load_take(key)
        if hit is not None:
            logger.info("Voz de la caché (%s, %s): no se paga otra vez", voice, model)
            return resample(hit[0], hit[1]), voice, model, True
        logger.info("Pidiendo la voz a Gemini (%s, %s, %d caracteres)", voice, model, len(text))
        async with self.gemini_client() as client:
            samples, rate = await client.synthesize(text, voice=voice, model=model, style=style)
        samples = resample(samples, rate)
        if not len(samples):
            raise VideoError("Gemini devolvió un audio vacío.")
        self._cache.save_take(
            key, samples, SAMPLE_RATE, {"engine": "gemini", "voice": voice, "model": model}
        )
        return samples, voice, model, False

    async def _eleven_take(
        self, script: Script, text: str
    ) -> tuple[Samples, str, str, bool, list[TimedWord]]:
        options = script.voice
        model = options.model.strip() or eleven.DEFAULT_MODEL
        settings: dict[str, float] = {}
        for name, value in (
            ("stability", options.stability),
            ("similarity_boost", options.similarity),
            ("style", options.style if isinstance(options.style, float) else None),
            ("speed", options.speed),
        ):
            if value is not None:
                settings[name] = float(value)
        key = _digest(
            {
                "engine": "elevenlabs",
                "voice": options.voice.strip(),
                "model": model,
                "settings": settings,
                "language": options.language,
                "text": text,
            }
        )
        hit = self._cache.load_take(key)
        if hit is not None:
            samples, rate, meta = hit
            heard = [
                TimedWord(str(w["text"]), float(w["start"]), float(w["end"]))
                for w in meta.get("words") or []
            ]
            logger.info("Voz de la caché (ElevenLabs): no se paga otra vez")
            return (
                resample(samples, rate),
                str(meta.get("voice") or options.voice),
                str(meta.get("model") or model),
                True,
                heard,
            )
        async with self.eleven_client() as client:
            voice = await client.resolve_voice(options.voice)
            logger.info(
                "Pidiendo la voz a ElevenLabs (%s, %s, %d caracteres)", voice.name, model, len(text)
            )
            take = await client.synthesize(
                text,
                voice_id=voice.voice_id,
                model=model,
                voice_settings=settings or None,
                language=options.language.strip(),
            )
        if not len(take.samples):
            raise VideoError("ElevenLabs devolvió un audio vacío.")
        self._cache.save_take(
            key,
            take.samples,
            take.rate,
            {
                "engine": "elevenlabs",
                "voice": voice.name,
                "voice_id": voice.voice_id,
                "model": take.model,
                "words": [{"text": w.text, "start": w.start, "end": w.end} for w in take.words],
            },
        )
        return resample(take.samples, take.rate), voice.name, take.model, False, take.words

    async def _transcribe(self, samples: Samples, language: str) -> list[TimedWord] | None:
        """Las palabras de la toma según Gemini (de la caché si ya se transcribió)."""
        languages = (language.strip() or gemini.TRANSCRIBE_LANGUAGE,)
        key = _digest(
            {"audio": _audio_digest(samples), "model": gemini.TRANSCRIBE_MODEL, "lang": languages}
        )
        cached = self._cache.load_words(key)
        if cached:
            return cached
        if not os.environ.get(GEMINI_KEY, "").strip():
            logger.warning("Sin %s no hay transcripción para los tiempos por palabra", GEMINI_KEY)
            return None
        try:
            async with self.gemini_client() as client:
                words = await client.transcribe(samples, SAMPLE_RATE, languages=languages)
        except VideoError as exc:
            logger.warning("La transcripción falló: %s", exc)
            return None
        self._cache.save_words(key, words)
        return words
