"""Audio de entrada hacia GPT-Live: PCM, puerta de ruido y silencio.

GPT-Live es un modelo full duplex: espera un flujo continuo de micrófono a
tiempo real, también mientras habla. Cuando no hay nada que mandar (sin
micrófono, micro silenciado mientras suena Sonia, puerta de ruido cerrada) se
envía silencio del mismo tamaño en lugar de cortar el flujo, para que la línea
de tiempo de la sesión no se detenga.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

import numpy as np

from sonia.types import AudioArray

__all__ = ["NoiseGate", "pcm16_from_float", "rms", "silence_blocks"]


def pcm16_from_float(block: AudioArray) -> bytes:
    """Float32 en [-1, 1] a PCM s16le mono."""
    clipped = np.clip(np.asarray(block, dtype=np.float32), -1.0, 1.0)
    return (clipped * 32767.0).astype("<i2").tobytes()


def rms(block: AudioArray) -> float:
    """Nivel RMS de un bloque float32 (0..1)."""
    if len(block) == 0:
        return 0.0
    samples = np.asarray(block, dtype=np.float32)
    return float(np.sqrt(np.mean(samples * samples)))


class NoiseGate:
    """Deja pasar el micrófono solo cuando alguien habla cerca.

    Se abre en cuanto un bloque supera ``threshold`` y se cierra tras
    ``hold_ms`` sin ninguno por encima: así no corta las pausas entre
    palabras. Con ``threshold`` 0 está siempre abierta. No guarda audio previo
    a la apertura: perder unos milisegundos del arranque de la primera sílaba
    no afecta a un modelo de voz, y meter audio atrasado desplazaría la línea
    de tiempo de la sesión.
    """

    def __init__(self, threshold: float, hold_ms: int) -> None:
        self._threshold = max(0.0, threshold)
        self._hold_s = max(0, hold_ms) / 1000.0
        self._open_until = 0.0

    @property
    def enabled(self) -> bool:
        return self._threshold > 0.0

    def admit(self, level: float, now: float | None = None) -> bool:
        """¿Pasa el bloque con este nivel RMS?"""
        if not self.enabled:
            return True
        now = time.monotonic() if now is None else now
        if level >= self._threshold:
            self._open_until = now + self._hold_s
            return True
        return now < self._open_until


async def silence_blocks(sample_rate: int, block_ms: int) -> AsyncIterator[AudioArray]:
    """Bloques de silencio a ritmo de tiempo real, para cuando no hay micrófono.

    Se programa contra el reloj (no con ``sleep`` fijo) para que los retrasos
    del bucle no se acumulen y el flujo no se quede por detrás del tiempo real.
    """
    samples = max(1, sample_rate * block_ms // 1000)
    period = samples / sample_rate
    block: AudioArray = np.zeros(samples, dtype=np.float32)
    next_at = time.monotonic()
    while True:
        yield block
        next_at += period
        delay = next_at - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        elif delay < -1.0:
            # El bucle estuvo bloqueado: no se recupera el tiempo perdido a
            # ráfagas, se vuelve a sincronizar con el reloj.
            next_at = time.monotonic()
