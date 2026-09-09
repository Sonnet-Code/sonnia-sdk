"""TTS contra un servidor HTTP compatible con ``POST /audio/speech``.

Sirve para hablar con un OmniVoice (o cualquier otro motor) que corra en otro
proceso o en otra máquina de la red local del stand, sin cargar torch dentro del
orquestador. Sigue siendo 100 % local: la URL la decide la configuración.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ..config import TTSSettings
from ..types import AudioChunk
from .base import DEFAULT_CHUNK_MS, chunk_pcm, resample_pcm, wav_to_pcm

__all__ = ["HTTPTTS"]

log = logging.getLogger(__name__)


class HTTPTTS:
    """Implementa :class:`~sonia.types.TextToSpeech` sobre HTTP."""

    def __init__(
        self,
        settings: TTSSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        chunk_ms: int = DEFAULT_CHUNK_MS,
        timeout: float = 60.0,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._chunk_ms = chunk_ms
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    @property
    def sample_rate(self) -> int:
        return self._settings.sample_rate

    @property
    def url(self) -> str:
        return f"{self._settings.base_url.rstrip('/')}/audio/speech"

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                transport=self._transport,
                timeout=self._timeout,
                headers={"Authorization": f"Bearer {self._settings.api_key}"},
            )
        return self._client

    def _payload(self, text: str) -> dict[str, Any]:
        settings = self._settings
        return {
            "model": settings.http_model,
            "input": text,
            "voice": settings.voice_instruct,
            "response_format": "wav",
            "speed": settings.speed,
        }

    async def _fetch_pcm(self, text: str) -> bytes:
        """Pide el audio al servidor y devuelve PCM s16le a ``self.sample_rate``."""
        response = await self._ensure_client().post(self.url, json=self._payload(text))
        response.raise_for_status()
        data = response.content
        if not data:
            return b""

        content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
        if content_type in ("audio/pcm", "audio/l16", "audio/x-pcm"):
            # PCM crudo: el servidor no dice la tasa, se asume la configurada.
            pcm, src_rate = data, self.sample_rate
        else:
            pcm, src_rate = wav_to_pcm(data)

        return resample_pcm(pcm, src_rate, self.sample_rate)

    async def synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        pcm = await self._fetch_pcm(text)
        for chunk in chunk_pcm(pcm, self.sample_rate, self._chunk_ms):
            yield chunk

    async def warmup(self) -> None:
        """Comprueba que el servidor responde. Nunca lanza: la demo debe seguir."""
        try:
            await self._fetch_pcm("Hola.")
        except Exception:  # pragma: no cover - depende del servidor
            log.exception("Falló el warmup del TTS HTTP en %s", self.url)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
