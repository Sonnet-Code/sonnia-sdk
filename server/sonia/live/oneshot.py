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
    "Eres una voz de lectura en español. Cuando se te indique un texto, dilo en voz alta "
    "exactamente como está escrito, sin añadir ni quitar nada, y después quédate en silencio."
)

SAY_REQUEST = "Di en voz alta exactamente este texto, sin añadir nada: «{text}»"

#: Silencio tras la última voz con el que se da la lectura por terminada.
SAY_END_GAP_S = 1.5

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
    """Hace que GPT-Live lea ``text`` y devuelve el PCM s16le mono de su voz."""
    client = LiveClient(settings, connect=connect)
    await client.start(_session(settings, SAY_INSTRUCTIONS))
    pcm = bytearray()

    async def feed_silence() -> None:
        with contextlib.suppress(Exception):
            async for block in silence_blocks(settings.sample_rate, _SILENCE_BLOCK_MS):
                await client.append_audio(bytes(len(block) * 2))

    feeder = asyncio.create_task(feed_silence(), name="sonia-say-silence")
    events = client.events()
    try:
        await client.append_instructions(SAY_REQUEST.format(text=text))
        deadline = time.monotonic() + timeout_s
        last_audio: float | None = None
        while True:
            now = time.monotonic()
            if now >= deadline:
                break
            wait = deadline - now
            if last_audio is not None:
                wait = min(wait, last_audio + SAY_END_GAP_S - now)
                if wait <= 0:
                    break
            try:
                event = await asyncio.wait_for(anext(events), timeout=wait)
            except TimeoutError:
                continue
            except StopAsyncIteration:
                break
            kind = event.get("type")
            if kind == "session.output_audio.delta":
                data = event.get("delta")
                if isinstance(data, str) and data:
                    with contextlib.suppress(binascii.Error, ValueError):
                        pcm += base64.b64decode(data)
                        last_audio = time.monotonic()
            elif kind == "error":
                raise LiveError(describe_error(event))
    finally:
        feeder.cancel()
        await asyncio.gather(feeder, return_exceptions=True)
        with contextlib.suppress(Exception):
            await events.aclose()
        await client.close()
    if len(pcm) % 2:
        del pcm[-1]
    return bytes(pcm)
