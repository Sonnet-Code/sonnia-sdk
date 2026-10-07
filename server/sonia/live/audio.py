"""Audio de entrada hacia GPT-Live: PCM, la puerta del micro y silencio.

GPT-Live es un modelo full duplex: espera un flujo continuo de micrófono a
tiempo real, también mientras habla. :class:`MicGate` decide en cada bloque si
GPT-Live oye el micro o un ruido muy suave del mismo tamaño
(:class:`ComfortNoise`), juntando todas las medidas: el micro silenciado desde
el panel, las frases grabadas, si hay alguien delante de la cámara y la puerta
de ruido. Nunca se corta el flujo, para que la línea de tiempo de la sesión no
se detenga.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Literal, Protocol

import numpy as np

from sonia.types import AudioArray

__all__ = [
    "ComfortNoise",
    "MicGate",
    "NoiseGate",
    "Reason",
    "pcm16_from_float",
    "rms",
    "silence_blocks",
]


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

    def admit(self, level: float, now: float | None = None, *, scale: float = 1.0) -> bool:
        """¿Pasa el bloque con este nivel RMS? ``scale`` < 1 baja el umbral (alguien delante)."""
        if not self.enabled:
            return True
        now = time.monotonic() if now is None else now
        if level >= self._threshold * scale:
            self._open_until = now + self._hold_s
            return True
        return now < self._open_until


class ComfortNoise:
    """Ruido muy suave que se manda a GPT-Live en lugar del micrófono.

    Con ceros absolutos GPT-Live entendía al visitante con 7 a 40 s de retraso
    y no decía el resultado de una tarea delegada hasta volver a oír algo;
    con ruido de sala, al momento (probado con la API real el 7 de octubre de
    2026). Con ``level`` 0 manda ceros.
    """

    def __init__(self, level: float, seed: int | None = None) -> None:
        self._level = max(0.0, level)
        self._rng = np.random.default_rng(seed)

    def pcm(self, samples: int) -> bytes:
        """``samples`` muestras de ruido en PCM s16le, con RMS ``level``."""
        if self._level <= 0.0:
            return bytes(samples * 2)
        noise = self._rng.standard_normal(samples).astype(np.float32) * self._level
        return pcm16_from_float(noise)


#: Por qué GPT-Live no oye un bloque del micro; vacío si lo oye.
Reason = Literal["", "panel", "frase grabada", "nadie delante", "silencio", "pasillo"]


class PresenceLike(Protocol):
    """Lo que la puerta del micro sabe de la cámara (``sonia.vision.presence.PresenceGate``)."""

    def admits(self, now: float) -> bool: ...

    def near(self, now: float) -> bool: ...


class MicGate:
    """La puerta del micro: qué oye GPT-Live en cada bloque, el micro o un ruido muy suave.

    Todas las medidas deciden juntas, en este orden; la primera que no deja
    pasar da el motivo (``reason``, que enseña el panel):

    1. ``panel``: el micro está silenciado desde el panel.
    2. ``frase grabada``: suena una frase de ``cache/voice`` (GPT-Live no la dijo
       y la contestaría).
    3. ``nadie delante``: la cámara no ha visto ninguna cara cerca ni ha habido
       conversación en ``LIVE_PRESENCE_HOLD_SECONDS`` (``sonia.vision.presence``).
    4. ``silencio``: el bloque viene vacío (``--no-mic``, micro sin permiso).
    5. ``pasillo``: no llega a la puerta de ruido (``LIVE_GATE_RMS``). Con alguien
       delante ahora mismo el umbral baja (``LIVE_PRESENCE_NEAR_GATE_SCALE``):
       quien habla bajito delante de Sonia también pasa.

    Lo que no pasa llega como :class:`ComfortNoise` (``LIVE_COMFORT_NOISE_RMS``),
    nunca como ceros. Cada medida se apaga sola: ``LIVE_GATE_RMS=0`` (o el
    control «Ruido del pasillo»), ``LIVE_PRESENCE_GATE=false`` (o el interruptor
    del panel), ``LIVE_PRESENCE_NEAR_GATE_SCALE=1`` y ``LIVE_COMFORT_NOISE_RMS=0``.
    """

    def __init__(
        self,
        *,
        threshold: float,
        hold_ms: int,
        comfort_rms: float,
        near_scale: float = 1.0,
        presence: PresenceLike | None = None,
        silence_rms: float = 0.0,
    ) -> None:
        self._hold_ms = hold_ms
        self._noise = NoiseGate(threshold, hold_ms)
        self._comfort = ComfortNoise(comfort_rms)
        self._near_scale = min(1.0, max(0.0, near_scale))
        self._presence = presence
        self._silence_rms = silence_rms
        #: Por qué no oyó GPT-Live el último bloque (vacío si lo oyó).
        self.reason: Reason = ""

    def set_threshold(self, threshold: float) -> None:
        """Cambia la puerta de ruido (control «Ruido del pasillo» del panel)."""
        self._noise = NoiseGate(threshold, self._hold_ms)

    def check(self, level: float, now: float, *, muted: bool = False, echo: bool = False) -> Reason:
        """Por qué GPT-Live no oiría un bloque con este nivel RMS (vacío: lo oye)."""
        if muted:
            return "panel"
        if echo:
            return "frase grabada"
        scale = 1.0
        presence = self._presence
        if presence is not None:
            if not presence.admits(now):
                return "nadie delante"
            if presence.near(now):
                scale = self._near_scale
        if level <= self._silence_rms:
            return "silencio"
        if not self._noise.admit(level, now, scale=scale):
            return "pasillo"
        return ""

    def pcm(
        self,
        block: AudioArray,
        level: float,
        now: float,
        *,
        muted: bool = False,
        echo: bool = False,
    ) -> bytes:
        """Lo que se manda a GPT-Live por este bloque: el micro o el ruido suave."""
        self.reason = self.check(level, now, muted=muted, echo=echo)
        if self.reason:
            return self._comfort.pcm(len(block))
        return pcm16_from_float(block)


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
