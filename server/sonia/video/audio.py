"""Audio de la voz: WAV, niveles y tramos con voz (todo con numpy, sin dependencias nuevas).

Las tomas van en ``float32`` mono de −1 a 1 a ``SAMPLE_RATE`` (24 kHz, la de Gemini, la
de ElevenLabs con ``pcm_24000`` y la que se le anuncia a Unity).
"""

from __future__ import annotations

import io
import wave
from pathlib import Path

import numpy as np
import numpy.typing as npt

from sonia.video.errors import VideoError

__all__ = [
    "SAMPLE_RATE",
    "Samples",
    "frame_envelope",
    "limit",
    "pcm16_bytes",
    "pcm16_to_float",
    "quietest_point",
    "read_wav",
    "read_wav_bytes",
    "resample",
    "speech_level",
    "to_unity_level",
    "unity_gain",
    "voiced_runs",
    "voiced_threshold",
    "window_rms",
    "write_wav",
]

Samples = npt.NDArray[np.float32]

SAMPLE_RATE = 24000

#: Nivel de la voz de GPT-Live en Unity: RMS mediano de las ventanas de 20 ms con voz.
#: Con la voz más fuerte (Gemini sale unas 2,7 veces por encima) la boca va siempre abierta.
UNITY_SPEECH_RMS = 0.059

#: Ventana del nivel de la voz.
LEVEL_WINDOW_S = 0.02

#: Techo del limitador (por debajo de 1 para no recortar al pasar a 16 bits).
LIMIT_CEILING = 0.97

#: Una ventana con voz está a menos de esto por debajo del percentil 95 (en amplitud: −20 dB).
VOICED_RELATIVE = 0.1
#: Por debajo de esto nunca es voz (−54 dBFS).
VOICED_FLOOR = 0.002


def pcm16_to_float(data: bytes) -> Samples:
    """PCM 16 bit little-endian → ``float32`` de −1 a 1."""
    usable = len(data) - len(data) % 2
    return (np.frombuffer(data[:usable], dtype="<i2").astype(np.float32) / 32768.0).astype(
        np.float32
    )


def pcm16_bytes(samples: Samples) -> bytes:
    """``float32`` → PCM 16 bit little-endian (recortando a ±1)."""
    clipped = np.clip(samples, -1.0, 32767.0 / 32768.0)
    return (clipped * 32768.0).round().astype("<i2").tobytes()


def _from_wave(reader: wave.Wave_read) -> tuple[Samples, int]:
    channels = reader.getnchannels()
    width = reader.getsampwidth()
    rate = reader.getframerate()
    raw = reader.readframes(reader.getnframes())
    if width == 2:
        data = np.frombuffer(raw[: len(raw) - len(raw) % 2], dtype="<i2").astype(np.float32)
        data /= 32768.0
    elif width == 4:
        data = np.frombuffer(raw[: len(raw) - len(raw) % 4], dtype="<i4").astype(np.float64)
        data = (data / 2147483648.0).astype(np.float32)
    elif width == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise VideoError(f"WAV de {8 * width} bits no soportado: conviértelo a 16 bits")
    if channels > 1:
        data = data[: len(data) - len(data) % channels].reshape(-1, channels).mean(axis=1)
    return data.astype(np.float32), rate


def read_wav_bytes(data: bytes) -> tuple[Samples, int]:
    """Un WAV PCM en memoria → muestras mono y su tasa."""
    try:
        with wave.open(io.BytesIO(data), "rb") as reader:
            return _from_wave(reader)
    except (wave.Error, EOFError) as exc:
        raise VideoError(f"El audio no es un WAV PCM válido: {exc}") from None


def read_wav(path: Path) -> tuple[Samples, int]:
    """Un WAV PCM del disco → muestras mono y su tasa."""
    try:
        with wave.open(str(path), "rb") as reader:
            return _from_wave(reader)
    except (wave.Error, EOFError) as exc:
        raise VideoError(f"{path} no es un WAV PCM válido: {exc}") from None
    except OSError as exc:
        raise VideoError(f"No se pudo leer {path}: {exc}") from None


def write_wav(path: Path, samples: Samples, rate: int = SAMPLE_RATE) -> Path:
    """Escribe un WAV PCM 16 bit mono."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(pcm16_bytes(samples))
    return path


def resample(samples: Samples, rate: int, target: int = SAMPLE_RATE) -> Samples:
    """Cambia la tasa por interpolación lineal (solo para tomas que no vengan a 24 kHz)."""
    if rate == target or not len(samples):
        return samples.astype(np.float32)
    count = max(1, round(len(samples) * target / rate))
    source = np.arange(len(samples), dtype=np.float64) / rate
    times = np.arange(count, dtype=np.float64) / target
    return np.interp(times, source, samples).astype(np.float32)


def window_rms(samples: Samples, rate: int, window_s: float = LEVEL_WINDOW_S) -> Samples:
    """RMS de ventanas seguidas de ``window_s`` (la última, incompleta, se descarta)."""
    size = max(1, round(rate * window_s))
    count = len(samples) // size
    if count == 0:
        return np.zeros(0, dtype=np.float32)
    blocks = samples[: count * size].astype(np.float64).reshape(count, size)
    return np.sqrt(np.mean(blocks * blocks, axis=1)).astype(np.float32)


def voiced_threshold(rms: Samples) -> float:
    """El RMS a partir del cual una ventana tiene voz."""
    if not len(rms):
        return VOICED_FLOOR
    return max(VOICED_FLOOR, float(np.percentile(rms, 95)) * VOICED_RELATIVE)


def speech_level(samples: Samples, rate: int) -> float:
    """RMS mediano de las ventanas de 20 ms con voz (0 si no hay voz)."""
    rms = window_rms(samples, rate)
    voiced = rms[rms > voiced_threshold(rms)]
    return float(np.median(voiced)) if len(voiced) else 0.0


def limit(samples: Samples, rate: int, ceiling: float = LIMIT_CEILING) -> Samples:
    """Limitador sin recortes: baja la ganancia alrededor de cada pico que pasa del techo.

    Por bloques de 5 ms: cada bloque pide la ganancia que deja su pico en el techo; se
    extiende un bloque hacia atrás (ataque) y ocho hacia delante (relajación) y se
    interpola entre los centros de los bloques. Como cada muestra queda entre ganancias
    que ya cubren su bloque, ninguna pasa del techo.
    """
    if not len(samples):
        return samples
    block = max(1, round(rate * 0.005))
    count = -(-len(samples) // block)
    padded = np.zeros(count * block, dtype=np.float32)
    padded[: len(samples)] = np.abs(samples)
    peaks = padded.reshape(count, block).max(axis=1)
    if float(peaks.max()) <= ceiling:
        return samples.astype(np.float32)
    gains = np.minimum(1.0, ceiling / np.maximum(peaks, 1e-9))
    spread = gains.copy()
    for shift in range(-1, 9):
        # spread[i] = mínimo de gains[i - 8 .. i + 1]: un bloque antes del pico y ocho después.
        shifted = np.roll(gains, shift)
        if shift < 0:
            shifted[shift:] = 1.0
        elif shift > 0:
            shifted[:shift] = 1.0
        spread = np.minimum(spread, shifted)
    centers = (np.arange(count) + 0.5) * block
    per_sample = np.interp(np.arange(len(samples)), centers, spread)
    limited = samples * per_sample.astype(np.float32)
    return np.clip(limited, -ceiling, ceiling).astype(np.float32)


def to_unity_level(samples: Samples, rate: int, gain: float) -> Samples:
    """La voz con la ganancia de Unity y el limitador."""
    return limit((samples * np.float32(gain)).astype(np.float32), rate)


def unity_gain(samples: Samples, rate: int, target: float = UNITY_SPEECH_RMS) -> float:
    """La ganancia que deja la voz al nivel de GPT-Live (1 si no hay voz)."""
    level = speech_level(samples, rate)
    return target / level if level > 0 else 1.0


def voiced_runs(
    samples: Samples,
    rate: int,
    *,
    min_gap_s: float = 0.12,
    min_run_s: float = 0.04,
    threshold: float | None = None,
) -> list[tuple[float, float]]:
    """Tramos con voz (inicio y fin en segundos), uniendo los huecos de menos de ``min_gap_s``."""
    window = 0.01
    rms = window_rms(samples, rate, window)
    if not len(rms):
        return []
    level = voiced_threshold(rms) if threshold is None else threshold
    voiced = rms > level
    runs: list[tuple[float, float]] = []
    start: int | None = None
    for i, on in enumerate(voiced):
        if on and start is None:
            start = i
        elif not on and start is not None:
            runs.append((start * window, i * window))
            start = None
    if start is not None:
        runs.append((start * window, len(voiced) * window))
    merged: list[tuple[float, float]] = []
    for run in runs:
        if merged and run[0] - merged[-1][1] < min_gap_s:
            merged[-1] = (merged[-1][0], run[1])
        else:
            merged.append(run)
    return [r for r in merged if r[1] - r[0] >= min_run_s]


def quietest_point(samples: Samples, rate: int, start: float, end: float) -> float:
    """Dónde cortar entre ``start`` y ``end`` (segundos): el medio del silencio más largo, o
    el punto más bajo si no hay silencio."""
    if end - start < 0.02:
        return (start + end) / 2
    window = 0.01
    first = max(0, int(start * rate))
    last = min(len(samples), int(end * rate))
    rms = window_rms(samples[first:last], rate, window)
    if not len(rms):
        return (start + end) / 2
    level = voiced_threshold(window_rms(samples, rate, window))
    silent = rms <= level
    best: tuple[int, int] | None = None
    run_start: int | None = None
    for i, quiet in enumerate([*silent.tolist(), False]):
        if quiet and run_start is None:
            run_start = i
        elif not quiet and run_start is not None:
            if best is None or i - run_start > best[1] - best[0]:
                best = (run_start, i)
            run_start = None
    middle = (best[0] + best[1]) / 2 if best is not None else float(np.argmin(rms)) + 0.5
    return first / rate + middle * window


def frame_envelope(samples: Samples, rate: int, fps: float, frames: int) -> Samples:
    """RMS de la voz en cada cuadro del vídeo (``samples`` empieza en el cuadro 0)."""
    out = np.zeros(frames, dtype=np.float32)
    for i in range(frames):
        a = int(round(i * rate / fps))
        b = int(round((i + 1) * rate / fps))
        chunk = samples[a:b]
        if len(chunk):
            out[i] = float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))
    return out
