"""Caché de frases fijas leídas una vez por GPT-Live.

El modo "Solo saludos" y la animación de stand dicen frases fijas (saludos,
frases y cantos de ``assets/showcase``). En vez de abrir una sesión de GPT-Live
cada vez, cada frase se lee una sola vez con la voz configurada, se guarda en
WAV y luego se reproduce desde disco: misma voz que en la conversación y coste
cero mientras Sonia solo saluda.

La clave de cada archivo combina voz, tasa y texto: al cambiar de voz las
frases se vuelven a grabar solas.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import wave
from collections.abc import Iterable
from pathlib import Path

from sonia.config import LiveSettings
from sonia.live.client import WsConnect
from sonia.live.oneshot import max_reading_seconds, speak_text

__all__ = ["VoiceCache"]

logger = logging.getLogger(__name__)

#: Frases más cortas que esto se dan por fallidas (GPT-Live no dijo nada).
_MIN_SECONDS = 0.3

#: Fallos seguidos tras los que se deja de grabar.
_MAX_FAILURES = 2

#: Margen por la cola de silencio que se deja al final de cada grabación.
_TAIL_SLACK_S = 0.3


class VoiceCache:
    """Frases fijas en WAV dentro de ``directory``."""

    def __init__(
        self, directory: str | Path, settings: LiveSettings, *, connect: WsConnect | None = None
    ) -> None:
        self._dir = Path(directory)
        self._settings = settings
        self._connect = connect
        self._lock = asyncio.Lock()
        self.busy = False
        self.last_error = ""

    @property
    def directory(self) -> Path:
        return self._dir

    def path_for(self, text: str) -> Path:
        settings = self._settings
        key = f"{settings.voice}\n{settings.sample_rate}\n{text.strip()}"
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
        return self._dir / settings.voice / f"{digest}.wav"

    def has(self, text: str) -> bool:
        return self._usable(text)

    def get(self, text: str) -> bytes | None:
        """PCM s16le mono de la frase, o ``None`` si no está grabada (o no sirve)."""
        if not self._usable(text):
            return None
        path = self.path_for(text)
        try:
            with wave.open(str(path), "rb") as wav:
                return wav.readframes(wav.getnframes())
        except (OSError, wave.Error, EOFError):
            logger.warning("Frase grabada ilegible: %s", path)
            return None

    def _usable(self, text: str) -> bool:
        """¿Hay una grabación de la frase con el formato y la duración esperados?

        Una grabación más larga de lo que puede durar el texto es que GPT-Live
        añadió algo de su cosecha (pasó: inventó una charla tras un saludo). Se
        borra para que "Preparar voces" la vuelva a grabar.
        """
        path = self.path_for(text)
        if not path.is_file():
            return False
        try:
            with wave.open(str(path), "rb") as wav:
                if (
                    wav.getnchannels() != 1
                    or wav.getsampwidth() != 2
                    or wav.getframerate() != self._settings.sample_rate
                ):
                    return False
                seconds = wav.getnframes() / wav.getframerate()
        except (OSError, wave.Error, EOFError):
            logger.warning("Frase grabada ilegible: %s", path)
            return False
        if seconds > max_reading_seconds(text) + _TAIL_SLACK_S:
            logger.warning(
                "Frase grabada demasiado larga (%.1f s) para %r: se descarta y se volverá a grabar",
                seconds,
                text[:60],
            )
            with contextlib.suppress(OSError):
                path.unlink()
            return False
        return True

    def count_ready(self, texts: Iterable[str]) -> int:
        return sum(1 for text in texts if self.has(text))

    def missing(self, texts: Iterable[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for text in texts:
            text = text.strip()
            if text and text not in seen and not self.has(text):
                seen.add(text)
                out.append(text)
        return out

    async def record(self, text: str) -> bytes:
        """Graba una frase con GPT-Live (abre una sesión corta) y la guarda."""
        pcm = await speak_text(self._settings, text, connect=self._connect)
        if len(pcm) / 2 / self._settings.sample_rate < _MIN_SECONDS:
            raise RuntimeError("GPT-Live no devolvió voz para la frase")
        path = self.path_for(text)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with wave.open(str(tmp), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self._settings.sample_rate)
            wav.writeframes(pcm)
        tmp.replace(path)
        return pcm

    async def prepare(self, texts: Iterable[str]) -> int:
        """Graba las frases que falten, de una en una. Devuelve cuántas grabó.

        Sin clave no hace nada. Un fallo suelto no para las demás; dos seguidos
        (clave mala, sin red) sí.
        """
        if not self._settings.api_key and self._connect is None:
            self.last_error = "Falta LIVE_API_KEY para grabar las frases."
            return 0
        async with self._lock:
            pending = self.missing(texts)
            if not pending:
                return 0
            self.busy = True
            self.last_error = ""
            done = 0
            try:
                logger.info(
                    "Grabando %d frases fijas con la voz %s", len(pending), self._settings.voice
                )
                failures = 0
                for text in pending:
                    try:
                        await self.record(text)
                        done += 1
                        failures = 0
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001 - se sigue con las demás
                        self.last_error = str(exc)
                        failures += 1
                        logger.warning("No se pudo grabar la frase %r: %s", text[:60], exc)
                        if failures >= _MAX_FAILURES:
                            # Clave mala o sin red: no tiene sentido insistir frase a frase.
                            logger.warning("Se deja de grabar tras %d fallos seguidos", failures)
                            break
                logger.info("Frases fijas grabadas: %d de %d", done, len(pending))
            finally:
                self.busy = False
            return done

    def clear_partial(self) -> None:
        """Borra temporales de una grabación interrumpida."""
        for tmp in self._dir.glob("*/*.tmp"):
            with contextlib.suppress(OSError):
                tmp.unlink()
