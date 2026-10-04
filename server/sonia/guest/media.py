"""Media del Modo Jean: frames de la sala, bitrate adaptable y voz del invitado.

Todo lo de aquí es puro (sin red ni hardware) para poder probarlo a fondo:

- El formato binario de la sala de Cloudflare (``GuestRoom``), por la que viajan
  la cámara y el micro del stand hacia Jean y la voz de Jean hacia el stand.
- ``VideoRateController``: decide cuándo mandar un fotograma y con qué tamaño y
  calidad. Ventana de fotogramas sin confirmar (como TCP): si la red se atasca
  bajan los fps solos y la imagen nunca se queda vieja; además baja o sube de
  escalón según el RTT y los atascos. Es lo que mantiene estable el vídeo
  "ajustando el bitrate".
- ``LinearResampler``: remuestreo con estado, sin chasquidos entre bloques.
- ``GuestSpeechSegmenter``: corta la voz de Jean en rachas para Unity, con un
  pequeño colchón al empezar cada una para absorber los saltos de la red.

Formato y decisiones en ``docs/modo-jean.md``.
"""

from __future__ import annotations

import math
import struct
import time
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from sonia.types import AudioArray

__all__ = [
    "KIND_GUEST_AUDIO",
    "KIND_STAND_AUDIO",
    "KIND_VIDEO",
    "STAND_AUDIO_RATE",
    "VIDEO_STEPS",
    "GuestSpeechSegmenter",
    "LinearResampler",
    "RoomFrame",
    "StandAudioPacker",
    "VideoRateController",
    "VideoStep",
    "decode_room_frame",
    "encode_room_frame",
    "pcm16_to_float",
]

# ---------------------------------------------------------------------------
# Frames de la sala (orquestador ↔ Durable Object ↔ navegador de Jean)
# ---------------------------------------------------------------------------

ROOM_MAGIC = b"SG"
ROOM_VERSION = 1
#: Cabecera de 16 bytes: marca, versión, tipo, número, hora de envío (ms), tasa, reservado.
ROOM_HEADER = struct.Struct("<2sBBIIHH")

#: Fotograma JPEG de la cámara del stand.
KIND_VIDEO = 1
#: PCM s16le mono del micro del stand (hacia Jean).
KIND_STAND_AUDIO = 2
#: PCM s16le mono del micro de Jean (hacia el stand).
KIND_GUEST_AUDIO = 3

_KINDS = (KIND_VIDEO, KIND_STAND_AUDIO, KIND_GUEST_AUDIO)


@dataclass(frozen=True, slots=True)
class RoomFrame:
    kind: int
    seq: int
    #: Hora de envío en ms del reloj de quien lo manda (vuelve tal cual en el ``ack``).
    t_ms: int
    #: Tasa de muestreo del audio en Hz (0 en el vídeo).
    rate: int
    payload: bytes


def encode_room_frame(kind: int, seq: int, t_ms: int, payload: bytes, rate: int = 0) -> bytes:
    if kind not in _KINDS:
        raise ValueError(f"tipo de frame desconocido: {kind}")
    header = ROOM_HEADER.pack(
        ROOM_MAGIC,
        ROOM_VERSION,
        kind,
        seq & 0xFFFFFFFF,
        t_ms & 0xFFFFFFFF,
        max(0, min(0xFFFF, rate)),
        0,
    )
    return header + payload


def decode_room_frame(data: bytes) -> RoomFrame:
    """Deshace ``encode_room_frame``. ``ValueError`` si no es un frame de la sala."""
    if len(data) < ROOM_HEADER.size:
        raise ValueError(f"frame demasiado corto: {len(data)} bytes")
    magic, version, kind, seq, t_ms, rate, _ = ROOM_HEADER.unpack_from(data)
    if magic != ROOM_MAGIC or version != ROOM_VERSION or kind not in _KINDS:
        raise ValueError("no es un frame de la sala del Modo Jean")
    return RoomFrame(kind, seq, t_ms, rate, bytes(data[ROOM_HEADER.size :]))


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------


def pcm16_to_float(pcm: bytes) -> AudioArray:
    """PCM s16le a float32 en [-1, 1] (ignora un byte suelto al final)."""
    usable = len(pcm) - (len(pcm) % 2)
    samples = np.frombuffer(pcm[:usable], dtype="<i2").astype(np.float32)
    return samples / 32768.0


class LinearResampler:
    """Remuestreo lineal con estado: los bloques encadenan sin saltos de fase.

    Para bajar de tasa pasa antes un filtro paso bajo de tres coeficientes, que
    quita lo peor del aliasing; para voz de control (lo que oye Jean del stand)
    es suficiente y no añade latencia.
    """

    def __init__(self, src_rate: int, dst_rate: int) -> None:
        if src_rate <= 0 or dst_rate <= 0:
            raise ValueError("las tasas tienen que ser positivas")
        self.src_rate = src_rate
        self.dst_rate = dst_rate
        self._step = src_rate / dst_rate
        #: Índice (fraccionario) de la siguiente muestra de salida en el bloque actual.
        self._t = 0.0
        self._prev = 0.0
        self._lowpass = dst_rate < src_rate
        self._fir_prev = np.zeros(2, dtype=np.float32)

    def process(self, block: AudioArray) -> AudioArray:
        samples = np.asarray(block, dtype=np.float32)
        n = len(samples)
        if n == 0:
            return np.zeros(0, dtype=np.float32)
        if self.src_rate == self.dst_rate:
            return samples.copy()
        if self._lowpass:
            padded = np.concatenate([self._fir_prev, samples])
            filtered = 0.25 * padded[:-2] + 0.5 * padded[1:-1] + 0.25 * padded[2:]
            self._fir_prev = padded[-2:].copy()
            samples = filtered.astype(np.float32)
        x = np.empty(n + 1, dtype=np.float32)
        x[0] = self._prev
        x[1:] = samples
        count = 0 if self._t > n - 1 else math.floor((n - 1 - self._t) / self._step) + 1
        positions = self._t + self._step * np.arange(count)
        out: AudioArray = np.asarray(
            np.interp(positions + 1.0, np.arange(n + 1), x), dtype=np.float32
        )
        self._t = self._t + self._step * count - n
        self._prev = float(samples[-1])
        return out


# ---------------------------------------------------------------------------
# Vídeo: bitrate adaptable
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VideoStep:
    width: int
    quality: int


#: Escalones de mayor a menor calidad. Se arranca en el segundo (640x360 q65).
VIDEO_STEPS: tuple[VideoStep, ...] = (
    VideoStep(854, 70),
    VideoStep(640, 65),
    VideoStep(640, 50),
    VideoStep(480, 50),
    VideoStep(320, 45),
)
START_STEP = 1

#: Fotogramas sin confirmar como mucho: con 2, la imagen nunca va más de dos por detrás.
VIDEO_WINDOW = 2
VIDEO_MAX_FPS = 12.0
#: Un fotograma sin ``ack`` en este tiempo se da por perdido.
VIDEO_ACK_TIMEOUT_S = 2.0
#: Por encima de este RTT (ms) se baja un escalón.
RTT_BAD_MS = 700.0
#: Por debajo, y sin atascos, se sube tras unos segundos buenos.
RTT_GOOD_MS = 350.0
GOOD_SECONDS_TO_STEP_UP = 3


@dataclass(slots=True)
class _InFlight:
    sent_at: float
    size: int


@dataclass(slots=True)
class VideoStats:
    fps: float = 0.0
    kbps: float = 0.0
    rtt_ms: float | None = None
    step: int = START_STEP
    width: int = VIDEO_STEPS[START_STEP].width
    quality: int = VIDEO_STEPS[START_STEP].quality
    lost: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "fps": round(self.fps, 1),
            "kbps": round(self.kbps),
            "rtt_ms": None if self.rtt_ms is None else round(self.rtt_ms),
            "step": self.step,
            "width": self.width,
            "quality": self.quality,
            "lost": self.lost,
        }


class VideoRateController:
    """Ventana de fotogramas y escalones de calidad según lo que aguanta la red."""

    def __init__(
        self,
        *,
        window: int = VIDEO_WINDOW,
        max_fps: float = VIDEO_MAX_FPS,
        clock: object = time.monotonic,
    ) -> None:
        self._window = max(1, window)
        self._interval = 1.0 / max(0.5, max_fps)
        self._clock = clock
        self._step = START_STEP
        self._in_flight: dict[int, _InFlight] = {}
        self._last_sent = -1e9
        self._rtt_ms: float | None = None
        # Contadores del segundo en curso.
        self._rtt_sum = 0.0
        self._rtt_count = 0
        self._acked_frames = 0
        self._acked_bytes = 0
        self._lost = 0
        self._blocked = 0
        self._chances = 0
        self._good_seconds = 0
        self._last_tick = self._now()
        self.stats = VideoStats()

    def _now(self) -> float:
        clock = self._clock
        return float(clock())  # type: ignore[operator]

    @property
    def step(self) -> VideoStep:
        return VIDEO_STEPS[self._step]

    @property
    def in_flight(self) -> int:
        return len(self._in_flight)

    def can_send(self, now: float | None = None) -> bool:
        """¿Toca mandar un fotograma ya? Cuenta los atascos de la ventana."""
        now = self._now() if now is None else now
        if now - self._last_sent < self._interval:
            return False
        self._chances += 1
        if len(self._in_flight) >= self._window:
            self._blocked += 1
            return False
        return True

    def on_sent(self, seq: int, size: int, now: float | None = None) -> None:
        now = self._now() if now is None else now
        self._last_sent = now
        self._in_flight[seq] = _InFlight(now, size)

    def on_ack(self, seq: int, now: float | None = None) -> None:
        now = self._now() if now is None else now
        frame = self._in_flight.pop(seq, None)
        if frame is None:
            return
        rtt = (now - frame.sent_at) * 1000.0
        self._rtt_ms = rtt if self._rtt_ms is None else 0.8 * self._rtt_ms + 0.2 * rtt
        self._rtt_sum += rtt
        self._rtt_count += 1
        self._acked_frames += 1
        self._acked_bytes += frame.size

    def reset(self) -> None:
        """Sin nadie mirando (o tras reconectar): se olvida lo pendiente."""
        self._in_flight.clear()
        self._rtt_ms = None
        self._good_seconds = 0

    def tick(self, now: float | None = None) -> VideoStats:
        """Una vez por segundo: estadísticas y, si toca, cambio de escalón."""
        now = self._now() if now is None else now
        elapsed = max(1e-3, now - self._last_tick)
        self._last_tick = now
        for seq, frame in list(self._in_flight.items()):
            if now - frame.sent_at > VIDEO_ACK_TIMEOUT_S:
                del self._in_flight[seq]
                self._lost += 1

        fps = self._acked_frames / elapsed
        blocked_ratio = self._blocked / self._chances if self._chances else 0.0
        # Se decide con el RTT del último segundo, que reacciona ya; la media
        # móvil solo suaviza lo que se enseña.
        rtt = self._rtt_sum / self._rtt_count if self._rtt_count else None
        if (
            self._lost > 0
            or (rtt is not None and rtt > RTT_BAD_MS)
            or (blocked_ratio > 0.5 and fps < 5)
        ):
            self._step = min(len(VIDEO_STEPS) - 1, self._step + 1)
            self._good_seconds = 0
        elif (
            rtt is not None and rtt < RTT_GOOD_MS and blocked_ratio < 0.1 and self._acked_frames > 0
        ):
            self._good_seconds += 1
            if self._good_seconds >= GOOD_SECONDS_TO_STEP_UP:
                self._step = max(0, self._step - 1)
                self._good_seconds = 0
        else:
            self._good_seconds = 0

        step = VIDEO_STEPS[self._step]
        self.stats = VideoStats(
            fps=fps,
            kbps=self._acked_bytes * 8 / 1000.0 / elapsed,
            rtt_ms=self._rtt_ms,
            step=self._step,
            width=step.width,
            quality=step.quality,
            lost=self.stats.lost + self._lost,
        )
        self._rtt_sum = 0.0
        self._rtt_count = 0
        self._acked_frames = 0
        self._acked_bytes = 0
        self._lost = 0
        self._blocked = 0
        self._chances = 0
        return self.stats


# ---------------------------------------------------------------------------
# Voz de Jean: rachas para Unity
# ---------------------------------------------------------------------------

#: Por debajo de este RMS un bloque cuenta como silencio (el navegador ya
#: suprime el ruido de fondo, así que el silencio llega casi a cero).
VOICE_THRESHOLD = 0.008
#: Colchón al empezar una racha: absorbe los saltos de la red sin cortes.
PREBUFFER_MS = 150
#: Silencio que cierra una racha.
SILENCE_MS = 500


@dataclass(slots=True)
class GuestSpeechSegmenter:
    """Convierte el audio continuo de Jean en rachas (``utterance``) para Unity.

    ``push`` devuelve los frames que hay que mandar ya: ``(utterance_id, pcm,
    is_last)``. Una racha empieza con la primera voz y junta ``PREBUFFER_MS``
    antes de soltar nada; las pausas cortas van dentro; ``SILENCE_MS`` seguidos
    de silencio (o ``close_if_stale`` si deja de llegar audio) la cierran con un
    frame vacío marcado como último.
    """

    rate: int
    threshold: float = VOICE_THRESHOLD
    prebuffer_ms: int = PREBUFFER_MS
    silence_ms: int = SILENCE_MS
    utterance_id: int = 0
    _talking: bool = False
    _buffer: list[bytes] = field(default_factory=list)
    _buffered_ms: float = 0.0
    _silent_ms: float = 0.0
    _last_audio_at: float = 0.0
    level: float = 0.0
    #: Cuándo llegó la última voz (no silencio) de Jean, en el reloj de ``push``.
    last_voiced_at: float = float("-inf")

    @property
    def talking(self) -> bool:
        """Cierto con una racha abierta (o empezando a juntar su colchón)."""
        return self._talking or bool(self._buffer)

    def push(self, pcm: bytes, now: float | None = None) -> list[tuple[int, bytes, bool]]:
        now = time.monotonic() if now is None else now
        self._last_audio_at = now
        samples = pcm16_to_float(pcm)
        if len(samples) == 0:
            return []
        level = float(np.sqrt(np.mean(samples * samples)))
        self.level = level
        duration_ms = len(samples) * 1000.0 / self.rate
        voiced = level >= self.threshold
        if voiced:
            self.last_voiced_at = now
        out: list[tuple[int, bytes, bool]] = []
        if not self._talking:
            if not voiced and not self._buffer:
                return out
            if not self._buffer:
                self.utterance_id += 1
                self._silent_ms = 0.0
            self._buffer.append(pcm)
            self._buffered_ms += duration_ms
            if self._buffered_ms >= self.prebuffer_ms:
                self._talking = True
                out.extend((self.utterance_id, chunk, False) for chunk in self._buffer)
                self._buffer.clear()
                self._buffered_ms = 0.0
            return out
        out.append((self.utterance_id, pcm, False))
        self._silent_ms = 0.0 if voiced else self._silent_ms + duration_ms
        if self._silent_ms >= self.silence_ms:
            out.append(self._close())
        return out

    def close_if_stale(self, now: float | None = None) -> list[tuple[int, bytes, bool]]:
        """Si dejó de llegar audio en mitad de una racha, la cierra."""
        now = time.monotonic() if now is None else now
        if not (self._talking or self._buffer):
            return []
        if now - self._last_audio_at < self.silence_ms / 1000.0:
            return []
        out: list[tuple[int, bytes, bool]] = []
        if self._buffer:
            out.extend((self.utterance_id, chunk, False) for chunk in self._buffer)
        out.append(self._close())
        return out

    def _close(self) -> tuple[int, bytes, bool]:
        self._talking = False
        self._buffer.clear()
        self._buffered_ms = 0.0
        self._silent_ms = 0.0
        return (self.utterance_id, b"", True)


# ---------------------------------------------------------------------------
# Micro del stand hacia Jean
# ---------------------------------------------------------------------------

#: Tasa del audio del stand hacia Jean: voz de control, 256 kbit/s en PCM.
STAND_AUDIO_RATE = 16_000
#: Bloques de 100 ms: pocos mensajes al Durable Object y latencia aceptable.
STAND_AUDIO_BLOCK_MS = 100
#: Bloques pendientes de enviar como mucho: con más, se tira el más viejo (300 ms).
STAND_AUDIO_MAX_PENDING = 3


class StandAudioPacker:
    """Junta el micro del stand en bloques de 100 ms a 16 kHz."""

    def __init__(self, src_rate: int) -> None:
        self._resampler = LinearResampler(src_rate, STAND_AUDIO_RATE)
        self._pending: deque[AudioArray] = deque()
        self._pending_samples = 0
        self._block = STAND_AUDIO_RATE * STAND_AUDIO_BLOCK_MS // 1000

    def push(self, block: AudioArray) -> list[bytes]:
        """Devuelve los bloques PCM s16le listos para enviar."""
        resampled = self._resampler.process(block)
        if len(resampled):
            self._pending.append(resampled)
            self._pending_samples += len(resampled)
        out: list[bytes] = []
        while self._pending_samples >= self._block:
            out.append(_pcm16(self._take(self._block)))
        return out

    def _take(self, count: int) -> AudioArray:
        parts: list[AudioArray] = []
        needed = count
        while needed > 0 and self._pending:
            head = self._pending[0]
            if len(head) <= needed:
                parts.append(head)
                self._pending.popleft()
                needed -= len(head)
            else:
                parts.append(head[:needed])
                self._pending[0] = head[needed:]
                needed = 0
        self._pending_samples -= count - needed
        return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)


def _pcm16(samples: AudioArray) -> bytes:
    clipped = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    return (clipped * 32767.0).astype("<i2").tobytes()
