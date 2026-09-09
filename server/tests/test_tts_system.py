"""Backend de voz del sistema operativo (say / SAPI / espeak-ng)."""

from __future__ import annotations

import sys

import pytest

from sonia.config import Settings, TTSSettings
from sonia.tts import SystemTTS, build_tts


def test_build_tts_system() -> None:
    engine = build_tts(TTSSettings(backend="system", sample_rate=24_000))
    assert isinstance(engine, SystemTTS)
    assert engine.sample_rate == 24_000
    assert isinstance(build_tts(Settings(tts=TTSSettings(backend="system"))), SystemTTS)


async def test_texto_vacio_produce_un_chunk_vacio() -> None:
    engine = SystemTTS(TTSSettings(backend="system"))
    chunks = [chunk async for chunk in engine.synthesize("   ")]
    assert len(chunks) == 1 and chunks[0].is_last and chunks[0].pcm == b""


@pytest.mark.skipif(
    sys.platform != "darwin" or not SystemTTS.is_available(), reason="requiere say de macOS"
)
async def test_say_de_macos_sintetiza_en_espanol() -> None:
    engine = SystemTTS(TTSSettings(backend="system", sample_rate=24_000))
    chunks = [chunk async for chunk in engine.synthesize("Hola, soy Sonia.")]
    assert chunks and chunks[-1].is_last
    total = sum(len(c.pcm) for c in chunks) / 2 / 24_000
    assert 0.5 < total < 6.0, f"duración inesperada: {total:.2f} s"
    assert all(c.sample_rate == 24_000 for c in chunks)
    assert engine.voice in ("Paulina", "Mónica", "Monica") or engine.voice.startswith("es")
