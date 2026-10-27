"""Voz con ElevenLabs: ``text-to-speech/{voice_id}/with-timestamps`` en PCM de 24 kHz.

Comprobado en su documentación el 27-oct-2026: la respuesta trae ``audio_base64`` y
``alignment`` (``characters``, ``character_start_times_seconds``,
``character_end_times_seconds``) sobre el texto enviado, de donde salen los tiempos de
cada palabra sin transcribir nada. Las voces se listan con ``GET /v2/voices``
(``search``, ``page_size`` hasta 100, ``next_page_token``) y la clave va en ``xi-api-key``.

Modelo por defecto: ``eleven_v4``, el de más calidad y multilingüe según su lista de
modelos. La documentación no dice si acepta tiempos y ajustes de voz, así que si lo
rechaza (4xx) se repite una vez con ``eleven_multilingual_v2``, que sí, y se avisa.
"""

from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from sonia.video.align import TimedWord, words_from_characters
from sonia.video.audio import SAMPLE_RATE, Samples, pcm16_to_float
from sonia.video.errors import VideoError
from sonia.video.http import HttpError, request_json

__all__ = [
    "CHAR_LIMITS",
    "DEFAULT_MODEL",
    "FALLBACK_MODEL",
    "ElevenLabsClient",
    "ElevenTake",
    "ElevenVoice",
    "looks_like_voice_id",
]

logger = logging.getLogger(__name__)

BASE_URL = "https://api.elevenlabs.io"
DEFAULT_MODEL = "eleven_v4"
FALLBACK_MODEL = "eleven_multilingual_v2"
OUTPUT_FORMAT = f"pcm_{SAMPLE_RATE}"

#: Caracteres por petición de cada modelo (su documentación, 27-oct-2026).
CHAR_LIMITS = {
    "eleven_v4": 10_000,
    "eleven_v3": 5_000,
    "eleven_multilingual_v2": 10_000,
    "eleven_flash_v2_5": 40_000,
    "eleven_flash_v2": 30_000,
}

#: Páginas de voces que se miran como mucho (100 por página).
MAX_VOICE_PAGES = 10

_VOICE_ID_RE = re.compile(r"^[A-Za-z0-9]{20}$")


def looks_like_voice_id(text: str) -> bool:
    """¿Es un ``voice_id`` (20 letras y cifras) y no un nombre?"""
    return bool(_VOICE_ID_RE.match(text.strip()))


@dataclass(frozen=True, slots=True)
class ElevenVoice:
    voice_id: str
    name: str
    category: str = ""
    description: str = ""
    labels: dict[str, str] = field(default_factory=dict)

    @property
    def summary(self) -> str:
        parts = [v for v in (self.labels.get("accent"), self.labels.get("gender")) if v]
        parts += [v for k, v in sorted(self.labels.items()) if k not in {"accent", "gender"} and v]
        if self.category:
            parts.append(self.category)
        return ", ".join(parts)


@dataclass(frozen=True, slots=True)
class ElevenTake:
    """Una toma de ElevenLabs: el audio, sus palabras con tiempo y el modelo que la hizo."""

    samples: Samples
    rate: int
    words: list[TimedWord]
    model: str


def _voice(item: dict[str, Any]) -> ElevenVoice | None:
    voice_id = item.get("voice_id")
    if not isinstance(voice_id, str) or not voice_id:
        return None
    labels = item.get("labels")
    return ElevenVoice(
        voice_id=voice_id,
        name=str(item.get("name") or voice_id),
        category=str(item.get("category") or ""),
        description=str(item.get("description") or ""),
        labels={str(k): str(v) for k, v in labels.items()} if isinstance(labels, dict) else {},
    )


class ElevenLabsClient:
    """Cliente mínimo de ElevenLabs: voces y voz con tiempos."""

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
            headers={"xi-api-key": key, "Content-Type": "application/json"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> ElevenLabsClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def voices(self, search: str = "") -> list[ElevenVoice]:
        """Las voces de la cuenta (las de la biblioteca guardadas, las propias y las de serie)."""
        out: list[ElevenVoice] = []
        token: str | None = None
        for _ in range(MAX_VOICE_PAGES):
            params: dict[str, Any] = {"page_size": 100}
            if search:
                params["search"] = search
            if token:
                params["next_page_token"] = token
            data = await request_json(
                self._client,
                "GET",
                "/v2/voices",
                what="La lista de voces de ElevenLabs",
                params=params,
                backoff_s=self._backoff_s,
            )
            for item in data.get("voices") or []:
                voice = _voice(item) if isinstance(item, dict) else None
                if voice is not None:
                    out.append(voice)
            token = data.get("next_page_token") if data.get("has_more") else None
            if not token:
                break
        return out

    async def resolve_voice(self, name: str) -> ElevenVoice:
        """La voz con ese id o ese nombre (sin mirar mayúsculas; vale el principio del nombre)."""
        name = name.strip()
        if not name:
            raise VideoError(
                'Falta la voz de ElevenLabs: pon voz = "..." en [voz] (nombre o voice_id; '
                "lista con sonnia-video voces elevenlabs)."
            )
        if looks_like_voice_id(name):
            return ElevenVoice(voice_id=name, name=name)
        found = await self.voices(search=name)
        lowered = name.lower()
        exact = [v for v in found if v.name.lower() == lowered]
        start = [v for v in found if v.name.lower().startswith(lowered)]
        if exact or start:
            return (exact or start)[0]
        if len(found) == 1:
            return found[0]
        hint = ", ".join(v.name for v in found[:6])
        raise VideoError(
            f"No encuentro la voz «{name}» en ElevenLabs"
            + (f"; se parecen: {hint}" if hint else "")
            + ". Lista: sonnia-video voces elevenlabs"
        )

    async def synthesize(
        self,
        text: str,
        *,
        voice_id: str,
        model: str = DEFAULT_MODEL,
        voice_settings: dict[str, float] | None = None,
        language: str = "",
    ) -> ElevenTake:
        """La toma de ``text`` con sus palabras con tiempo.

        Si ``eleven_v4`` no se acepta (4xx), vuelve a pedirla con ``eleven_multilingual_v2``.
        """
        limit = CHAR_LIMITS.get(model)
        if limit is not None and len(text) > limit:
            raise VideoError(
                f"El guion tiene {len(text)} caracteres y {model} acepta {limit} por toma: "
                "acórtalo o divídelo en dos vídeos."
            )
        try:
            return await self._synthesize(text, voice_id, model, voice_settings, language)
        except HttpError as exc:
            if model != DEFAULT_MODEL or exc.status not in {400, 404, 422}:
                raise
            logger.warning(
                "ElevenLabs no aceptó %s (%s); repito con %s", model, exc, FALLBACK_MODEL
            )
            # multilingual_v2 no acepta language_code.
            return await self._synthesize(text, voice_id, FALLBACK_MODEL, voice_settings, "")

    async def _synthesize(
        self,
        text: str,
        voice_id: str,
        model: str,
        voice_settings: dict[str, float] | None,
        language: str,
    ) -> ElevenTake:
        body: dict[str, Any] = {"text": text, "model_id": model}
        if voice_settings:
            body["voice_settings"] = voice_settings
        if language:
            body["language_code"] = language
        data = await request_json(
            self._client,
            "POST",
            f"/v1/text-to-speech/{voice_id}/with-timestamps",
            what="La voz de ElevenLabs",
            params={"output_format": OUTPUT_FORMAT},
            json=body,
            backoff_s=self._backoff_s,
        )
        audio = data.get("audio_base64")
        if not isinstance(audio, str) or not audio:
            raise VideoError("ElevenLabs no devolvió audio.")
        samples = pcm16_to_float(base64.b64decode(audio))
        words: list[TimedWord] = []
        alignment = data.get("alignment") or data.get("normalized_alignment")
        if isinstance(alignment, dict):
            words = words_from_characters(
                [str(c) for c in alignment.get("characters") or []],
                [float(t) for t in alignment.get("character_start_times_seconds") or []],
                [float(t) for t in alignment.get("character_end_times_seconds") or []],
            )
        return ElevenTake(samples=samples, rate=SAMPLE_RATE, words=words, model=model)
