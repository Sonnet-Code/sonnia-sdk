"""Sesiones cortas de GPT-Live para ``sonia check`` y ``sonia say``.

Cada una abre una sesión, hace lo mínimo y la cierra. Se cobran por segundo de
sesión, así que duran lo justo: unos segundos.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import time
from dataclasses import dataclass
from typing import Any

from sonia.config import LiveSettings
from sonia.live.audio import silence_blocks
from sonia.live.client import LiveClient, LiveError, WsConnect, describe_error

__all__ = ["ProbeResult", "probe_session", "speak_text"]

#: Instrucciones de la sesión de lectura de ``sonia say``.
SAY_INSTRUCTIONS = (
    "Eres una voz de lectura en español. Cada texto que te llegue para decir en voz alta, "
    "dilo exactamente como está escrito, sin añadir, quitar ni comentar nada, y después "
    "quédate en silencio. No saludes ni hables por tu cuenta."
)

SAY_REQUEST = "{text}"

#: Silencio tras la última voz con el que se da la lectura por terminada.
SAY_END_GAP_S = 1.5

#: Nivel RMS (0..1) a partir del cual un trozo es voz (GPT-Live manda silencio digital, 0).
VOICE_RMS = 0.003

#: Silencio que se deja al final de la grabación para que no suene cortada.
_TAIL_S = 0.15

#: Bloques de silencio que mantienen viva la línea de tiempo de la sesión.
_SILENCE_BLOCK_MS = 40


@dataclass(slots=True)
class ProbeResult:
    session_id: str
    elapsed_s: float
    voice: str
    expires_in_s: float | None


def _session(settings: LiveSettings, instructions: str) -> dict[str, Any]:
    return {
        "model": settings.model,
        "instructions": instructions,
        "audio": {
            "format": {"type": "audio/pcm", "rate": int(settings.sample_rate)},
            "output": {"voice": settings.voice},
        },
    }


async def probe_session(settings: LiveSettings, *, connect: WsConnect | None = None) -> ProbeResult:
    """Abre y cierra una sesión: comprueba clave, acceso al modelo y voz."""
    client = LiveClient(settings, connect=connect)
    started = time.monotonic()
    try:
        session = await client.start(_session(settings, "Responde en español."))
        elapsed = time.monotonic() - started
    finally:
        await client.close()
    audio = session.get("audio")
    output = audio.get("output") if isinstance(audio, dict) else None
    voice = output.get("voice") if isinstance(output, dict) else None
    expires = client.expires_at
    return ProbeResult(
        session_id=client.session_id,
        elapsed_s=elapsed,
        voice=str(voice or settings.voice),
        expires_in_s=(expires - time.time()) if expires is not None else None,
    )


async def speak_text(
    settings: LiveSettings,
    text: str,
    *,
    connect: WsConnect | None = None,
    timeout_s: float = 30.0,
) -> bytes:
    """Hace que GPT-Live lea ``text`` y devuelve el PCM s16le mono de su voz.

    GPT-Live manda audio sin parar (también silencio), así que la lectura
    empieza con el primer trozo con voz y termina tras ``SAY_END_GAP_S`` sin
    voz. El silencio de antes y de después se recorta.
    """
    client = LiveClient(settings, connect=connect)
    await client.start(_session(settings, SAY_INSTRUCTIONS))
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def feed_silence() -> None:
        with contextlib.suppress(Exception):
            async for block in silence_blocks(settings.sample_rate, _SILENCE_BLOCK_MS):
                await client.append_audio(bytes(len(block) * 2))

    async def read() -> None:
        # Un lector aparte: cancelar una espera nunca cierra el flujo de eventos.
        with contextlib.suppress(Exception):
            async for event in client.events():
                await queue.put(event)
        await queue.put(None)

    tasks = [
        asyncio.create_task(feed_silence(), name="sonia-say-silence"),
        asyncio.create_task(read(), name="sonia-say-read"),
    ]
    chunks: list[bytes] = []
    last_voice_index = -1
    try:
        # ``commentary`` es lo que la hace hablar (``instructions`` no).
        await client.append_commentary(SAY_REQUEST.format(text=text))
        deadline = time.monotonic() + timeout_s
        last_voice: float | None = None
        while True:
            now = time.monotonic()
            if now >= deadline or (last_voice is not None and now - last_voice >= SAY_END_GAP_S):
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=0.2)
            except TimeoutError:
                continue
            if event is None:
                break
            kind = event.get("type")
            if kind == "session.output_audio.delta":
                data = event.get("delta")
                if not isinstance(data, str) or not data:
                    continue
                with contextlib.suppress(binascii.Error, ValueError):
                    pcm = base64.b64decode(data)
                    if len(pcm) % 2:
                        pcm = pcm[:-1]
                    if _rms(pcm) >= VOICE_RMS:
                        if last_voice is None:
                            chunks.clear()  # fuera el silencio de antes
                        last_voice = time.monotonic()
                        chunks.append(pcm)
                        last_voice_index = len(chunks) - 1
                    elif last_voice is not None:
                        chunks.append(pcm)
            elif kind == "error":
                raise LiveError(describe_error(event))
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await client.close()
    # Fuera el silencio de después, salvo una cola corta para que no suene cortado.
    kept = chunks[: last_voice_index + 1] if last_voice_index >= 0 else []
    tail = b"".join(chunks[last_voice_index + 1 :])[: int(settings.sample_rate * _TAIL_S) * 2]
    return b"".join(kept) + tail


def _rms(pcm: bytes) -> float:
    import numpy as np

    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    return float(np.sqrt(np.mean(samples * samples))) if len(samples) else 0.0
