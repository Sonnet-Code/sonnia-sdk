"""Síntesis de voz con el motor del sistema operativo: bajo consumo y sin red.

- macOS: ``say`` (voces en español integradas: Paulina, Mónica...). Exporta WAV
  directamente a la tasa pedida.
- Windows: ``System.Speech`` a través de PowerShell (voces SAPI instaladas;
  en español suelen venir "Helena", "Sabina" o "Laura" según el idioma del
  sistema). Exporta WAV a 22 050 Hz y aquí se remuestrea.
- Linux: ``espeak-ng`` si está instalado.

Es la voz "de respaldo" para ensayar sin GPU y sin gastar cuota en la nube:
suena a sintetizador clásico, pero llega en unos 100 a 300 ms por frase y no
consume casi nada. El motor definitivo del stand sigue siendo OmniVoice.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

from ..config import TTSSettings
from ..types import AudioChunk
from .base import DEFAULT_CHUNK_MS, TTSError, chunk_pcm, resample_pcm, wav_to_pcm

log = logging.getLogger(__name__)

#: Voces preferidas por plataforma, en orden. Se usa la primera que exista.
PREFERRED_VOICES_MACOS = ("Paulina", "Mónica", "Monica")
PREFERRED_VOICES_WINDOWS = ("Sabina", "Helena", "Laura", "Paulina")

_POWERSHELL_SCRIPT = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voice = $env:SONIA_TTS_VOICE
if ($voice) {
  try { $s.SelectVoice($voice) } catch { }
} else {
  foreach ($v in $s.GetInstalledVoices()) {
    if ($v.VoiceInfo.Culture.Name -like 'es-*') { $s.SelectVoice($v.VoiceInfo.Name); break }
  }
}
$rate = [int]$env:SONIA_TTS_RATE
if ($rate -ne 0) { $s.Rate = $rate }
$s.SetOutputToWaveFile($env:SONIA_TTS_OUT)
$text = [System.IO.File]::ReadAllText($env:SONIA_TTS_IN, [System.Text.Encoding]::UTF8)
$s.Speak($text)
$s.Dispose()
"""


def _read_if_exists(path: Path) -> bytes:
    return path.read_bytes() if path.is_file() else b""


class SystemTTS:
    """Motor de voz del sistema operativo detrás de la interfaz ``TextToSpeech``."""

    def __init__(self, settings: TTSSettings, *, chunk_ms: int = DEFAULT_CHUNK_MS) -> None:
        self._settings = settings
        self._chunk_ms = max(1, chunk_ms)
        self._lock = asyncio.Lock()
        self._voice: str | None = settings.system_voice.strip() or None
        self._platform = sys.platform
        self._resolved_voice: str | None = None

    @property
    def sample_rate(self) -> int:
        return self._settings.sample_rate

    @property
    def voice(self) -> str:
        """Voz que se está usando (resuelta en el primer uso)."""
        return self._resolved_voice or self._voice or "(por defecto)"

    @staticmethod
    def is_available() -> bool:
        if sys.platform == "darwin":
            return shutil.which("say") is not None
        if sys.platform.startswith("win"):
            return shutil.which("powershell") is not None or shutil.which("pwsh") is not None
        return shutil.which("espeak-ng") is not None or shutil.which("espeak") is not None

    async def warmup(self) -> None:
        async for _ in self.synthesize("Hola."):
            pass

    async def close(self) -> None:  # simetría con los demás motores
        return None

    async def synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        text = text.strip()
        if not text:
            yield AudioChunk(pcm=b"", sample_rate=self.sample_rate, is_last=True)
            return
        async with self._lock:
            pcm, rate = await self._render(text)
        if rate != self.sample_rate:
            pcm = resample_pcm(pcm, rate, self.sample_rate)
        for chunk in chunk_pcm(pcm, self.sample_rate, self._chunk_ms):
            yield chunk
            await asyncio.sleep(0)

    # -- por plataforma --------------------------------------------------

    async def _render(self, text: str) -> tuple[bytes, int]:
        with tempfile.TemporaryDirectory(prefix="sonia-tts-") as tmp:
            out = Path(tmp) / "out.wav"
            if self._platform == "darwin":
                await self._render_macos(text, out)
            elif self._platform.startswith("win"):
                await self._render_windows(text, out, Path(tmp) / "in.txt")
            else:
                await self._render_linux(text, out)
            data = await asyncio.to_thread(_read_if_exists, out)
            if len(data) < 64:
                raise TTSError("El motor de voz del sistema no produjo audio.")
            return wav_to_pcm(data)

    async def _run(
        self, args: list[str], *, stdin: bytes | None = None, env: dict[str, str] | None = None
    ) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except FileNotFoundError as exc:
            raise TTSError(f"No se encontró el motor de voz del sistema ({args[0]}).") from exc
        try:
            _, err = await asyncio.wait_for(proc.communicate(stdin), timeout=30.0)
        except TimeoutError as exc:
            proc.kill()
            raise TTSError("El motor de voz del sistema tardó más de 30 s.") from exc
        if proc.returncode != 0:
            detail = err.decode("utf-8", "replace").strip()
            raise TTSError(f"{args[0]} devolvió {proc.returncode}: {detail[:200]}")

    async def _macos_voice(self) -> str | None:
        if self._resolved_voice is not None:
            return self._resolved_voice
        if self._voice:
            self._resolved_voice = self._voice
            return self._voice
        try:
            proc = await asyncio.create_subprocess_exec(
                "say", "-v", "?", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        except (OSError, TimeoutError):
            return None
        listing = out.decode("utf-8", "replace")
        names = [line.split("  ")[0].strip() for line in listing.splitlines() if line.strip()]
        for candidate in PREFERRED_VOICES_MACOS:
            if candidate in names:
                self._resolved_voice = candidate
                return candidate
        for line in listing.splitlines():
            if " es_" in line:
                self._resolved_voice = line.split("  ")[0].strip()
                return self._resolved_voice
        return None

    async def _render_macos(self, text: str, out: Path) -> None:
        args = ["say", "-o", str(out), f"--data-format=LEI16@{self.sample_rate}", "-f", "-"]
        voice = await self._macos_voice()
        if voice:
            args[1:1] = ["-v", voice]
        if self._settings.system_rate > 0:
            args[1:1] = ["-r", str(self._settings.system_rate)]
        await self._run(args, stdin=text.encode("utf-8"))

    async def _render_windows(self, text: str, out: Path, text_file: Path) -> None:
        await asyncio.to_thread(text_file.write_text, text, encoding="utf-8")
        shell = shutil.which("pwsh") or shutil.which("powershell") or "powershell"
        env = dict(os.environ)
        env["SONIA_TTS_OUT"] = str(out)
        env["SONIA_TTS_IN"] = str(text_file)
        env["SONIA_TTS_VOICE"] = self._voice or ""
        # System.Speech usa una escala de -10 a 10; system_rate son palabras por minuto.
        rate = 0
        if self._settings.system_rate > 0:
            rate = max(-10, min(10, round((self._settings.system_rate - 175) / 17.5)))
        env["SONIA_TTS_RATE"] = str(rate)
        await self._run(
            [shell, "-NoProfile", "-NonInteractive", "-Command", _POWERSHELL_SCRIPT], env=env
        )
        self._resolved_voice = self._voice or "es-* (SAPI)"

    async def _render_linux(self, text: str, out: Path) -> None:
        binary = shutil.which("espeak-ng") or shutil.which("espeak") or "espeak-ng"
        args = [binary, "-v", self._voice or "es", "-w", str(out)]
        if self._settings.system_rate > 0:
            args += ["-s", str(self._settings.system_rate)]
        args += ["--stdin"]
        await self._run(args, stdin=text.encode("utf-8"))
        self._resolved_voice = self._voice or "es"
