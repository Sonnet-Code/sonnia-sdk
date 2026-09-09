"""TTS falso: genera un tono (o silencio) proporcional al texto.

Sirve para probar el pipeline completo (orquestador, visemas, WebSocket, Unity)
sin cargar modelos ni depender de un servidor externo.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncIterator

import numpy as np

from ..types import AudioChunk
from .base import DEFAULT_CHUNK_MS, chunk_pcm, float_to_pcm16

__all__ = ["MockTTS"]

#: Frecuencia del tono generado, en hercios. Grave para que no moleste.
TONE_HZ = 220.0

#: Duración de las rampas de entrada y salida del tono, en milisegundos.
_FADE_MS = 30.0


class MockTTS:
    """Implementa :class:`~sonia.types.TextToSpeech` sin ningún modelo."""

    def __init__(
        self,
        sample_rate: int = 24_000,
        ms_per_char: float = 60.0,
        tone: bool = False,
        chunk_ms: int = DEFAULT_CHUNK_MS,
    ) -> None:
        self._sample_rate = sample_rate
        self._ms_per_char = ms_per_char
        self._tone = tone
        self._chunk_ms = chunk_ms
        #: Textos sintetizados, en orden. Útil para asertos en los tests.
        self.calls: list[str] = []

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def duration_for(self, text: str) -> float:
        """Duración en segundos que tendría la síntesis de ``text``."""
        return len(text.strip()) * self._ms_per_char / 1000.0

    async def warmup(self) -> None:
        """No hay nada que calentar; existe para tener la misma API que los reales."""
        return None

    async def synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        self.calls.append(text)
        pcm = float_to_pcm16(self._render(text))
        for chunk in chunk_pcm(pcm, self._sample_rate, self._chunk_ms):
            yield chunk
            # Se cede el control para imitar el streaming de un TTS real.
            await asyncio.sleep(0)

    def _render(self, text: str) -> np.ndarray:
        """Construye la onda: tono de 220 Hz con envolvente suave, o silencio."""
        n_samples = int(self.duration_for(text) * self._sample_rate)
        if n_samples <= 0:
            return np.zeros(0, dtype=np.float32)
        if not self._tone:
            return np.zeros(n_samples, dtype=np.float32)

        t = np.arange(n_samples, dtype=np.float32) / self._sample_rate
        wave = np.sin(2.0 * math.pi * TONE_HZ * t, dtype=np.float32) * 0.3
        return np.asarray(wave * self._envelope(n_samples), dtype=np.float32)

    def _envelope(self, n_samples: int) -> np.ndarray:
        """Rampas de coseno alzado al principio y al final, para evitar clics."""
        env = np.ones(n_samples, dtype=np.float32)
        fade = min(int(self._sample_rate * _FADE_MS / 1000.0), n_samples // 2)
        if fade <= 0:
            return env
        ramp = 0.5 * (1.0 - np.cos(np.linspace(0.0, math.pi, fade, dtype=np.float32)))
        env[:fade] = ramp
        env[n_samples - fade :] = ramp[::-1]
        return env
