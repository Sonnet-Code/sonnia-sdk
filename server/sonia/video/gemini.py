"""Voz y transcripción con Gemini por su API «interactions» (como ``media/framework/voice/gemini.mjs``
del repo de Sonnet Code, con el que se hizo el comercial del DevFest).

- Voz: ``gemini-3.8-flash-tts`` devuelve un WAV de 24 kHz; el estilo va como anotación
  ``speech_metadata`` del texto.
- Tiempos por palabra: ``gemini-3.5-transcribe`` en modo literal con
  ``timestamp_granularities: ["word"]`` (rejilla de unos 100 ms).
"""

from __future__ import annotations

import base64
import io
import re
import wave
from typing import Any

import httpx

from sonia.video.align import TimedWord
from sonia.video.audio import SAMPLE_RATE, Samples, pcm16_bytes, pcm16_to_float, read_wav_bytes
from sonia.video.errors import VideoError
from sonia.video.http import request_json

__all__ = [
    "DEFAULT_STYLE",
    "DEFAULT_VOICE",
    "GeminiClient",
    "KNOWN_VOICES",
    "NO_STYLE",
    "TRANSCRIBE_MODEL",
    "TTS_MODEL",
    "style_for",
    "wav_bytes",
]

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
TTS_MODEL = "gemini-3.8-flash-tts"
TRANSCRIBE_MODEL = "gemini-3.5-transcribe"

#: La voz que eligió Jean para el comercial del DevFest (9-oct-2026), con acento
#: latinoamericano pedido por estilo: es-es-techagent-5 sale castellana sin él.
DEFAULT_VOICE = "es-es-techagent-5"
DEFAULT_STYLE = (
    "Speak with a neutral Latin American Spanish accent, NOT Castilian Spanish: seseo (c and z "
    "always sound like s, never th), Latin American intonation and rhythm, like a young host "
    "from Mexico City or Santo Domingo. Warm, conversational and upbeat, like telling a friend "
    "who works in tech about exciting news; a smile in the voice; brisk but unhurried pace."
)
#: ``estilo = "ninguno"``: sin indicación de estilo.
NO_STYLE = "ninguno"

#: Idioma de la transcripción si el guion no dice otro.
TRANSCRIBE_LANGUAGE = "es-419"

#: Voces conocidas (la API no las lista): las del casting del repo de Sonnet Code, la del
#: comercial del DevFest y algunas globales. Cualquier otra que acepte Gemini vale igual.
KNOWN_VOICES: tuple[tuple[str, str], ...] = (
    ("es-es-techagent-5", "Tech Advisor 5; la del comercial del DevFest (con estilo latino)"),
    ("es-419-assistant-1", "25 años, muy cercana"),
    ("es-419-commercial-6", "23 años, grave, aterciopelada, sin prisa"),
    ("es-419-commercial-8", "24 años, segura y clara"),
    ("es-419-commercial-9", "28 años, objetiva, directa y útil"),
    ("es-419-podcaster-2", "25 años, locutora de radio, profesional pero cercana"),
    ("es-419-training-7", "25 años, íntima, de talk show"),
    ("Leda", "global, juvenil (no es nativa latina)"),
    ("Kore", "global, firme"),
    ("Aoede", "global, ligera"),
    ("Zephyr", "global, brillante"),
    ("Callirrhoe", "global, tranquila"),
    ("Autonoe", "global, clara"),
    ("Despina", "global, suave"),
    ("Sulafat", "global, cálida"),
    ("Puck", "global, masculina, animada"),
    ("Charon", "global, masculina, informativa"),
    ("Fenrir", "global, masculina, enérgica"),
)

_RATE_RE = re.compile(r"rate=(\d+)")


def style_for(style: str | float | None) -> str:
    """La indicación de estilo que se manda: la latina si no hay, nada con «ninguno»."""
    text = style.strip() if isinstance(style, str) else ""
    if not text:
        return DEFAULT_STYLE
    return "" if text.lower() == NO_STYLE else text


def wav_bytes(samples: Samples, rate: int) -> bytes:
    """Un WAV PCM 16 bit mono en memoria."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(pcm16_bytes(samples))
    return buffer.getvalue()


def _seconds(value: Any) -> float:
    """``"1.25s"`` (o un número) → 1.25."""
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().removesuffix("s"))
        except ValueError:
            return 0.0
    if isinstance(value, dict):
        return float(value.get("seconds", 0) or 0) + float(value.get("nanos", 0) or 0) / 1e9
    return 0.0


def _contents(data: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for step in data.get("steps") or []:
        if not isinstance(step, dict):
            continue
        for content in step.get("content") or []:
            if isinstance(content, dict):
                out.append({**content, "_step": step.get("type")})
    return out


class GeminiClient:
    """Cliente de la API «interactions» de Gemini para la voz y la transcripción."""

    def __init__(
        self,
        key: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = 300.0,
        backoff_s: float = 2.0,
    ) -> None:
        self._backoff_s = backoff_s
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            transport=transport,
            timeout=httpx.Timeout(timeout_s, connect=15.0),
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> GeminiClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def synthesize(
        self, text: str, *, voice: str, model: str = TTS_MODEL, style: str = ""
    ) -> tuple[Samples, int]:
        """La toma de ``text`` con ``voice``: muestras mono y su tasa."""
        content: dict[str, Any] = {"type": "text", "text": text}
        if style:
            content["annotations"] = [{"type": "speech_metadata", "style": style}]
        data = await request_json(
            self._client,
            "POST",
            "/interactions",
            what="La voz de Gemini",
            backoff_s=self._backoff_s,
            json={
                "model": model,
                "input": [{"type": "user_input", "content": [content]}],
                "response_format": {
                    "type": "audio",
                    "mime_type": "audio/wav",
                    "sample_rate": SAMPLE_RATE,
                },
                "generation_config": {"speech_config": [{"voice": voice}]},
                "stream": False,
            },
        )
        audio = [
            c for c in _contents(data) if c.get("type") == "audio" and c["_step"] == "model_output"
        ]
        if not audio or not isinstance(audio[-1].get("data"), str):
            raise VideoError("Gemini no devolvió audio (¿la voz o el modelo no existen?).")
        raw = base64.b64decode(audio[-1]["data"])
        if raw[:4] == b"RIFF":
            return read_wav_bytes(raw)
        mime = str(audio[-1].get("mime_type") or "")
        match = _RATE_RE.search(mime)
        return pcm16_to_float(raw), int(match.group(1)) if match else SAMPLE_RATE

    async def transcribe(
        self,
        samples: Samples,
        rate: int,
        *,
        languages: tuple[str, ...] = (TRANSCRIBE_LANGUAGE,),
        model: str = TRANSCRIBE_MODEL,
    ) -> list[TimedWord]:
        """Las palabras de la toma con su inicio y su fin (segundos)."""
        data = await request_json(
            self._client,
            "POST",
            "/interactions",
            what="La transcripción de Gemini",
            backoff_s=self._backoff_s,
            json={
                "model": model,
                "input": [
                    {
                        "type": "audio",
                        "data": base64.b64encode(wav_bytes(samples, rate)).decode("ascii"),
                        "mime_type": "audio/wav",
                    }
                ],
                "generation_config": {
                    "transcription_config": {
                        "language_codes": list(languages),
                        "mode": {"type": "verbatim", "timestamp_granularities": ["word"]},
                    }
                },
                "stream": False,
            },
        )
        words: list[TimedWord] = []
        for content in _contents(data):
            if content.get("type") != "text":
                continue
            for note in content.get("annotations") or []:
                if isinstance(note, dict) and note.get("type") == "word_info":
                    words.append(
                        TimedWord(
                            str(note.get("text") or ""),
                            _seconds(note.get("start_offset")),
                            _seconds(note.get("end_offset")),
                        )
                    )
        if not words:
            raise VideoError("La transcripción de Gemini no trajo palabras con tiempo.")
        return words
