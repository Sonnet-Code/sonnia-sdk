"""Detección de voz y de turnos.

`VoiceActivityDetector` envuelve Silero VAD (probabilidad de voz por bloque de
512 muestras a 16 kHz) y `TurnDetector` convierte esa señal en eventos de
turno: `SpeechStarted` en cuanto se detecta voz, y después `Utterance` (turno
completo) o `SpeechDiscarded` (ruido demasiado corto).

Las duraciones se calculan contando muestras, no con el reloj, para que el
comportamiento sea determinista y comprobable con audio sintético.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import numpy as np

from sonia.config import AudioSettings
from sonia.types import INPUT_SAMPLE_RATE, AudioArray, Utterance

_log = logging.getLogger(__name__)

#: Silero VAD solo acepta ventanas de 512 muestras a 16 kHz.
VAD_WINDOW = 512

_SAMPLES_PER_MS = INPUT_SAMPLE_RATE // 1000


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------


def resample_to_16k(audio: AudioArray, sample_rate: int) -> AudioArray:
    """Remuestrea a 16 kHz con interpolación lineal.

    Es suficiente para el VAD y el STT cuando el dispositivo no soporta la tasa
    nativa. Si ya está a 16 kHz devuelve el audio tal cual (en float32).
    """
    data = np.asarray(audio, dtype=np.float32)
    if sample_rate == INPUT_SAMPLE_RATE or data.size == 0:
        return data
    if sample_rate <= 0:
        raise ValueError("sample_rate debe ser positivo")

    target_len = int(round(data.size * INPUT_SAMPLE_RATE / sample_rate))
    if target_len <= 0:
        return np.zeros(0, dtype=np.float32)
    if data.size == 1:
        return np.full(target_len, data[0], dtype=np.float32)

    source_x = np.arange(data.size, dtype=np.float64)
    target_x = np.linspace(0.0, data.size - 1, target_len, dtype=np.float64)
    return np.interp(target_x, source_x, data).astype(np.float32)


def _ms_to_samples(ms: float) -> int:
    return int(ms * _SAMPLES_PER_MS)


# ---------------------------------------------------------------------------
# VAD
# ---------------------------------------------------------------------------


@runtime_checkable
class VadLike(Protocol):
    """Lo mínimo que necesita `TurnDetector`; permite inyectar un VAD falso."""

    def probability(self, block: AudioArray) -> float:
        """Probabilidad de voz (0..1) del bloque dado."""
        ...


class VoiceActivityDetector:
    """Silero VAD por bloques, con carga perezosa del modelo.

    Acepta bloques de cualquier tamaño: acumula las muestras y evalúa el modelo
    por ventanas de 512 muestras, guardando el resto para la llamada siguiente.
    `probability` devuelve el máximo de las ventanas evaluadas en esta llamada
    (o la última probabilidad conocida si aún no se completó ninguna ventana).
    """

    def __init__(self, sample_rate: int = INPUT_SAMPLE_RATE) -> None:
        if sample_rate != INPUT_SAMPLE_RATE:
            raise ValueError(f"El VAD solo funciona a {INPUT_SAMPLE_RATE} Hz")
        self.sample_rate = sample_rate
        self._model: Any = None
        self._torch: Any = None
        self._pending: AudioArray = np.zeros(0, dtype=np.float32)
        self._last_probability = 0.0

    def _ensure_model(self) -> tuple[Any, Any]:
        """Carga el modelo la primera vez (importación perezosa de torch)."""
        if self._model is None:
            import torch
            from silero_vad import load_silero_vad

            _log.info("Cargando Silero VAD")
            self._model = load_silero_vad()
            self._torch = torch
        return self._model, self._torch

    def warmup(self) -> None:
        """Carga el modelo por adelantado (útil antes de abrir el micrófono)."""
        self._ensure_model()

    def reset(self) -> None:
        """Reinicia el estado recurrente del modelo y el buffer pendiente."""
        self._pending = np.zeros(0, dtype=np.float32)
        self._last_probability = 0.0
        if self._model is not None:
            self._model.reset_states()

    def probability(self, block: AudioArray) -> float:
        model, torch = self._ensure_model()

        data = np.asarray(block, dtype=np.float32).reshape(-1)
        if self._pending.size:
            data = np.concatenate((self._pending, data))

        windows = data.size // VAD_WINDOW
        if windows == 0:
            self._pending = data
            return self._last_probability

        best = 0.0
        with torch.no_grad():
            for i in range(windows):
                chunk = data[i * VAD_WINDOW : (i + 1) * VAD_WINDOW]
                tensor = torch.from_numpy(np.ascontiguousarray(chunk))
                probability = float(model(tensor, self.sample_rate).item())
                best = max(best, probability)

        self._pending = data[windows * VAD_WINDOW :].copy()
        self._last_probability = best
        return best


# ---------------------------------------------------------------------------
# Eventos de turno
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SpeechStarted:
    """El usuario ha empezado a hablar (dispara cámara y barge-in)."""

    at: float  # time.monotonic()


@dataclass(slots=True)
class SpeechDiscarded:
    """El habla detectada era demasiado corta: no había turno de verdad."""

    at: float  # time.monotonic()
    duration: float = 0.0  # segundos de voz acumulados, calculados por muestras


TurnEvent = SpeechStarted | Utterance | SpeechDiscarded


# ---------------------------------------------------------------------------
# Detector de turnos
# ---------------------------------------------------------------------------


class TurnDetector:
    """Convierte bloques de audio en turnos completos del usuario.

    Reglas (todas configurables por `AudioSettings`):

    - Umbral `vad_threshold`, o `vad_threshold_while_speaking` mientras Sonia
      habla (menos falsos positivos por el eco del altavoz).
    - `pre_roll_ms` de audio anterior al disparo se conservan para no cortar la
      primera sílaba.
    - `SpeechStarted` se emite en cuanto se supera el umbral. Si al cerrar el
      turno no se alcanzó `min_speech_ms` (o `barge_in_min_speech_ms` cuando
      Sonia hablaba), se emite `SpeechDiscarded` en vez de `Utterance`.
    - `end_silence_ms` de silencio cierran el turno; `max_utterance_s` lo
      fuerza aunque el usuario siga hablando.
    """

    def __init__(self, settings: AudioSettings, vad: VadLike) -> None:
        self._settings = settings
        self._vad = vad
        self._speaking = False

        self._pre_roll_limit = _ms_to_samples(settings.pre_roll_ms)
        self._end_silence_samples = _ms_to_samples(settings.end_silence_ms)
        self._max_turn_samples = int(settings.max_utterance_s * INPUT_SAMPLE_RATE)

        self._pre_roll: deque[AudioArray] = deque()
        self._pre_roll_samples = 0

        self._active = False
        self._buffer: list[AudioArray] = []
        self._turn_samples = 0  # muestras del turno sin contar el pre-roll
        self._speech_samples = 0
        self._silence_samples = 0
        self._started_at = 0.0
        #: Mínimo de voz exigido a este turno, fijado al empezarlo.
        self._min_speech_samples = 0

    # -- estado externo --------------------------------------------------

    def set_speaking(self, speaking: bool) -> None:
        """Indica si Sonia está hablando (cambia umbral y mínimo de barge-in)."""
        self._speaking = speaking

    @property
    def speaking(self) -> bool:
        return self._speaking

    @property
    def threshold(self) -> float:
        """Umbral de voz vigente."""
        settings = self._settings
        return settings.vad_threshold_while_speaking if self._speaking else settings.vad_threshold

    @property
    def min_speech_samples(self) -> int:
        """Voz mínima exigida para dar el turno por bueno, en muestras."""
        settings = self._settings
        ms = settings.barge_in_min_speech_ms if self._speaking else settings.min_speech_ms
        return _ms_to_samples(ms)

    def reset(self) -> None:
        """Olvida el turno en curso y el pre-roll acumulado."""
        self._pre_roll.clear()
        self._pre_roll_samples = 0
        self._discard_turn()

    # -- bucle de eventos ------------------------------------------------

    async def events(self, blocks: AsyncIterator[AudioArray]) -> AsyncIterator[TurnEvent]:
        """Consume bloques de audio y produce eventos de turno."""
        async for block in blocks:
            for event in self.feed(block):
                yield event
        for event in self.flush():
            yield event

    def feed(self, block: AudioArray) -> list[TurnEvent]:
        """Procesa un bloque y devuelve los eventos que genere (0, 1 o 2)."""
        data = np.asarray(block, dtype=np.float32).reshape(-1)
        if data.size == 0:
            return []

        voiced = self._vad.probability(data) >= self.threshold
        events: list[TurnEvent] = []

        if not self._active:
            if not voiced:
                self._remember_pre_roll(data)
                return events
            events.append(self._begin_turn(data))
            return events

        self._buffer.append(data)
        self._turn_samples += data.size
        if voiced:
            self._speech_samples += data.size
            self._silence_samples = 0
        else:
            self._silence_samples += data.size

        if self._silence_samples >= self._end_silence_samples:
            events.append(self._close_turn())
        elif self._turn_samples >= self._max_turn_samples:
            _log.info("Turno cortado por max_utterance_s (%.1f s)", self._settings.max_utterance_s)
            events.append(self._close_turn())
        return events

    def flush(self) -> list[TurnEvent]:
        """Cierra el turno en curso (fin del flujo de audio)."""
        if not self._active:
            return []
        return [self._close_turn()]

    # -- interno ---------------------------------------------------------

    def _remember_pre_roll(self, block: AudioArray) -> None:
        """Guarda el bloque en el buffer circular de pre-roll."""
        if self._pre_roll_limit <= 0:
            return
        self._pre_roll.append(block)
        self._pre_roll_samples += block.size
        while (
            self._pre_roll
            and self._pre_roll_samples - self._pre_roll[0].size >= self._pre_roll_limit
        ):
            self._pre_roll_samples -= self._pre_roll.popleft().size

    def _begin_turn(self, block: AudioArray) -> SpeechStarted:
        """Arranca un turno con el pre-roll delante y emite `SpeechStarted`."""
        self._active = True
        self._buffer = list(self._pre_roll)
        self._buffer.append(block)
        self._turn_samples = block.size
        self._speech_samples = block.size
        self._silence_samples = 0
        self._min_speech_samples = self.min_speech_samples
        self._started_at = time.monotonic()
        self._pre_roll.clear()
        self._pre_roll_samples = 0
        return SpeechStarted(at=self._started_at)

    def _close_turn(self) -> TurnEvent:
        """Cierra el turno: `Utterance` si hubo voz suficiente, si no `SpeechDiscarded`."""
        audio = np.concatenate(self._buffer) if self._buffer else np.zeros(0, dtype=np.float32)
        speech_samples = self._speech_samples
        started_at = self._started_at
        enough = speech_samples >= self._min_speech_samples
        self._discard_turn()

        ended_at = time.monotonic()
        if not enough:
            duration = speech_samples / INPUT_SAMPLE_RATE
            _log.debug("Habla descartada (%.0f ms de voz)", duration * 1000)
            return SpeechDiscarded(at=ended_at, duration=duration)
        return Utterance(
            audio=audio.astype(np.float32, copy=False),
            sample_rate=INPUT_SAMPLE_RATE,
            started_at=started_at,
            ended_at=ended_at,
        )

    def _discard_turn(self) -> None:
        self._active = False
        self._buffer = []
        self._turn_samples = 0
        self._speech_samples = 0
        self._silence_samples = 0
        self._started_at = 0.0
