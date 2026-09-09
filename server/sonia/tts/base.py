"""Protocolo de síntesis de voz y utilidades de audio compartidas.

Aquí vive todo lo que no depende del motor concreto: conversión entre float y
PCM s16le, troceado en chunks, remuestreo lineal y un parser mínimo de WAV.
Ninguna de estas funciones necesita dependencias fuera de numpy.
"""

from __future__ import annotations

import contextlib
import struct
from collections.abc import AsyncIterator

import numpy as np

from ..types import AudioArray, AudioChunk, TextToSpeech

__all__ = [
    "TextToSpeech",
    "aclosing",
    "chunk_pcm",
    "float_to_pcm16",
    "pcm16_to_float",
    "resample",
    "resample_pcm",
    "wav_to_pcm",
]

#: Tamaño por defecto de los chunks que se envían al avatar, en milisegundos.
DEFAULT_CHUNK_MS = 100

#: Formatos de WAV que aceptamos en la cabecera ``fmt ``.
_WAVE_FORMAT_PCM = 0x0001
_WAVE_FORMAT_EXTENSIBLE = 0xFFFE


class TTSError(RuntimeError):
    """Fallo de síntesis con un mensaje legible para el operador del stand."""


@contextlib.asynccontextmanager
async def aclosing[T](source: AsyncIterator[T]) -> AsyncIterator[AsyncIterator[T]]:
    """``contextlib.aclosing`` para iteradores tipados como ``AsyncIterator``.

    Al cancelar un turno, el generador del TTS se queda suspendido en su
    ``yield`` y su limpieza se aplaza hasta que pase el recolector. Eso deja
    cerrojos tomados y sesiones a medio consumir justo cuando empieza la frase
    siguiente, así que aquí se cierra de forma determinista.
    """
    try:
        yield source
    finally:
        close = getattr(source, "aclose", None)
        if close is not None:
            await close()


def float_to_pcm16(audio: np.ndarray) -> bytes:
    """Convierte audio float en [-1, 1] a PCM s16le mono.

    Las muestras fuera de rango se recortan (clipping) en lugar de dar la
    vuelta, que es lo que pasaría al castear un float grande a int16.
    """
    if audio.size == 0:
        return b""
    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    samples = np.clip(samples, -1.0, 1.0)
    return (samples * 32767.0).astype("<i2").tobytes()


def pcm16_to_float(pcm: bytes) -> AudioArray:
    """Inversa de :func:`float_to_pcm16`: PCM s16le mono a float32 en [-1, 1]."""
    if not pcm:
        return np.zeros(0, dtype=np.float32)
    # Se ignora un byte suelto al final (audio truncado por un servidor).
    usable = len(pcm) - (len(pcm) % 2)
    samples = np.frombuffer(pcm[:usable], dtype="<i2").astype(np.float32)
    return np.asarray(samples / 32768.0, dtype=np.float32)


def chunk_pcm(pcm: bytes, sample_rate: int, chunk_ms: int = DEFAULT_CHUNK_MS) -> list[AudioChunk]:
    """Trocea PCM s16le en chunks de ``chunk_ms`` milisegundos.

    El último chunk lleva ``is_last=True``. Si ``pcm`` está vacío se devuelve un
    único chunk vacío marcado como último, para que el consumidor siempre reciba
    el final de la frase.
    """
    if sample_rate <= 0:
        raise ValueError("sample_rate debe ser positivo")
    if chunk_ms <= 0:
        raise ValueError("chunk_ms debe ser positivo")

    if not pcm:
        return [AudioChunk(pcm=b"", sample_rate=sample_rate, is_last=True)]

    # Bytes por chunk, siempre múltiplo de 2 (una muestra int16).
    samples_per_chunk = max(1, (sample_rate * chunk_ms) // 1000)
    size = samples_per_chunk * 2

    chunks: list[AudioChunk] = []
    for start in range(0, len(pcm), size):
        piece = pcm[start : start + size]
        chunks.append(AudioChunk(pcm=piece, sample_rate=sample_rate, is_last=False))
    chunks[-1].is_last = True
    return chunks


def resample(audio: np.ndarray, src_rate: int, dst_rate: int) -> AudioArray:
    """Remuestrea audio mono float con interpolación lineal.

    No es un remuestreo de alta calidad (no hay filtro anti-aliasing), pero para
    voz y para saltos pequeños (22 050 a 24 000, por ejemplo) es suficiente y no
    añade dependencias ni latencia.
    """
    if src_rate <= 0 or dst_rate <= 0:
        raise ValueError("las tasas de muestreo deben ser positivas")

    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    if src_rate == dst_rate or samples.size == 0:
        return samples

    n_out = int(round(samples.size * dst_rate / src_rate))
    if n_out <= 0:
        return np.zeros(0, dtype=np.float32)

    src_positions = np.arange(n_out, dtype=np.float64) * (src_rate / dst_rate)
    src_index = np.arange(samples.size, dtype=np.float64)
    out = np.interp(src_positions, src_index, samples.astype(np.float64))
    return np.asarray(out, dtype=np.float32)


def resample_pcm(pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Igual que :func:`resample` pero de PCM s16le a PCM s16le."""
    if src_rate == dst_rate or not pcm:
        return pcm
    return float_to_pcm16(resample(pcm16_to_float(pcm), src_rate, dst_rate))


def wav_to_pcm(data: bytes) -> tuple[bytes, int]:
    """Extrae el PCM s16le mono y la tasa de muestreo de un WAV en memoria.

    Solo acepta WAV PCM de 16 bits (el formato que devuelven los servidores de
    TTS compatibles con ``/audio/speech``). Si el audio es multicanal se mezcla a
    mono promediando los canales. Se implementa a mano para no arrastrar
    dependencias: ``soundfile`` es opcional y ``wave`` no acepta bytes sueltos
    sin envolverlos.
    """
    if len(data) < 12 or data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("los datos no son un WAV RIFF válido")

    channels = 0
    sample_rate = 0
    bits_per_sample = 0
    audio_format = 0
    payload: bytes | None = None

    pos = 12
    while pos + 8 <= len(data):
        chunk_id = data[pos : pos + 4]
        (chunk_size,) = struct.unpack_from("<I", data, pos + 4)
        body_start = pos + 8
        body_end = body_start + chunk_size
        if chunk_size == 0 or body_end > len(data):
            # Cabecera de tamaño desconocido (streaming): se toma el resto.
            body_end = len(data)
        body = data[body_start:body_end]

        if chunk_id == b"fmt " and len(body) >= 16:
            audio_format, channels, sample_rate, _byte_rate, _align, bits_per_sample = (
                struct.unpack_from("<HHIIHH", body)
            )
        elif chunk_id == b"data":
            payload = body
            break

        # Los chunks RIFF van alineados a 2 bytes.
        pos = body_end + (chunk_size & 1)

    if payload is None or sample_rate <= 0 or channels <= 0:
        raise ValueError("el WAV no tiene cabecera 'fmt ' o datos 'data'")
    if audio_format not in (_WAVE_FORMAT_PCM, _WAVE_FORMAT_EXTENSIBLE):
        raise ValueError(f"formato de WAV no soportado: {audio_format}")
    if bits_per_sample != 16:
        raise ValueError(f"solo se soporta WAV de 16 bits, no de {bits_per_sample}")

    if channels == 1:
        usable = len(payload) - (len(payload) % 2)
        return payload[:usable], sample_rate

    frame_bytes = 2 * channels
    usable = len(payload) - (len(payload) % frame_bytes)
    samples = np.frombuffer(payload[:usable], dtype="<i2").reshape(-1, channels)
    # Se promedia en int32 para no desbordar al sumar los canales.
    mono = np.round(samples.astype(np.int32).mean(axis=1)).astype("<i2")
    return mono.tobytes(), sample_rate
