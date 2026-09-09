"""Reconocimiento de voz local con faster-whisper.

El modelo se carga una sola vez, de forma perezosa y en un hilo aparte
(`asyncio.to_thread`), para no bloquear el bucle de eventos durante la carga ni
durante la transcripción. La librería se importa dentro de las funciones: así
`import sonia.stt.faster_whisper` funciona aunque el extra `stt` no esté
instalado.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import re
import threading
from typing import TYPE_CHECKING, Any

import numpy as np

from sonia.stt.base import INPUT_SAMPLE_RATE, AudioArray, Utterance

if TYPE_CHECKING:
    from sonia.config import STTSettings

logger = logging.getLogger(__name__)

#: Espacios repetidos que deja la concatenación de segmentos.
_WHITESPACE_RE = re.compile(r"\s+")


def resolve_device(device: str, compute_type: str) -> tuple[str, str]:
    """Decide el dispositivo y el tipo de cómputo reales.

    ``device="auto"`` usa CUDA si hay GPU NVIDIA disponible y CPU en cualquier
    otro caso. En macOS con Apple Silicon no se usa ``mps``: CTranslate2 (el
    motor de faster-whisper) no lo soporta, así que se cae a CPU con ``int8``,
    que es lo más rápido ahí.
    """
    resolved_device = device.strip().lower() or "auto"
    if resolved_device == "auto":
        resolved_device = "cuda" if _cuda_available() else "cpu"
    elif resolved_device == "mps":
        # faster-whisper no soporta mps; degradamos en lugar de fallar.
        logger.warning("faster-whisper no soporta 'mps'; se usa 'cpu'.")
        resolved_device = "cpu"

    resolved_compute = compute_type.strip().lower() or "auto"
    if resolved_compute in ("", "auto", "default"):
        resolved_compute = "float16" if resolved_device == "cuda" else "int8"
    return resolved_device, resolved_compute


def _cuda_available() -> bool:
    """¿Hay una GPU NVIDIA utilizable? Importa torch de forma perezosa."""
    if platform.system() == "Darwin":
        # No hay CUDA en macOS; nos ahorramos importar torch.
        return False
    try:
        import torch  # noqa: PLC0415
    except Exception:  # pragma: no cover - depende del entorno
        return False
    try:
        return bool(torch.cuda.is_available())
    except Exception:  # pragma: no cover - depende del entorno
        return False


def _resample(audio: AudioArray, source_rate: int, target_rate: int) -> AudioArray:
    """Remuestreo lineal simple, por si llega audio a otra tasa que no sea 16 kHz."""
    if source_rate == target_rate or audio.size == 0:
        return audio
    duration = audio.size / source_rate
    target_len = max(1, int(round(duration * target_rate)))
    source_x = np.linspace(0.0, duration, num=audio.size, endpoint=False, dtype=np.float64)
    target_x = np.linspace(0.0, duration, num=target_len, endpoint=False, dtype=np.float64)
    return np.interp(target_x, source_x, audio).astype(np.float32)


class FasterWhisperSTT:
    """`SpeechToText` sobre faster-whisper (CTranslate2), en español por defecto."""

    def __init__(self, settings: STTSettings) -> None:
        self._settings = settings
        self._model: Any | None = None
        self._lock = asyncio.Lock()
        #: Serializa las transcripciones dentro de los hilos. Al cancelar un
        #: turno en `thinking`, `asyncio.to_thread` devuelve el control pero el
        #: hilo sigue transcribiendo: sin esto, la transcripción huérfana
        #: competiría por la CPU con la del turno nuevo y duplicaría su latencia.
        self._thread_lock = threading.Lock()
        self._hotwords: str | None = None

    @property
    def settings(self) -> STTSettings:
        return self._settings

    @property
    def hotwords(self) -> str | None:
        """Nombres propios que sesgan al decodificador (glosario)."""
        return self._hotwords

    def set_hotwords(self, terms: list[str]) -> None:
        """Fija las palabras clave: nombres del glosario que Whisper suele destrozar."""
        cleaned = [term.strip() for term in terms if term and term.strip()]
        self._hotwords = ", ".join(cleaned) if cleaned else None

    @property
    def loaded(self) -> bool:
        """¿Ya está el modelo en memoria?"""
        return self._model is not None

    async def warmup(self) -> None:
        """Carga el modelo por adelantado, para no pagar la espera en el primer turno."""
        await self._ensure_model()

    async def transcribe(self, utterance: Utterance) -> str:
        """Transcribe un turno completo del usuario. Devuelve texto limpio."""
        audio = np.asarray(utterance.audio, dtype=np.float32)
        if audio.size == 0:
            return ""
        audio = _resample(audio, utterance.sample_rate, INPUT_SAMPLE_RATE)
        model = await self._ensure_model()
        return await asyncio.to_thread(self._transcribe_sync, model, audio)

    # ------------------------------------------------------------------
    # Interno
    # ------------------------------------------------------------------

    async def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        async with self._lock:
            # Otra tarea pudo cargarlo mientras esperábamos el lock.
            if self._model is None:
                self._model = await asyncio.to_thread(self._load_model)
        return self._model

    def _load_model(self) -> Any:
        """Construye el `WhisperModel`. Corre en un hilo: puede tardar segundos."""
        from faster_whisper import WhisperModel  # noqa: PLC0415

        device, compute_type = resolve_device(self._settings.device, self._settings.compute_type)
        logger.info(
            "Cargando faster-whisper model=%s device=%s compute_type=%s",
            self._settings.model,
            device,
            compute_type,
        )
        return WhisperModel(self._settings.model, device=device, compute_type=compute_type)

    def _transcribe_sync(self, model: Any, audio: AudioArray) -> str:
        with self._thread_lock:
            return self._run_transcribe(model, audio)

    def _run_transcribe(self, model: Any, audio: AudioArray) -> str:
        segments, _info = model.transcribe(
            audio,
            language=self._settings.language or None,
            beam_size=self._settings.beam_size,
            # El VAD ya se aplicó antes: aquí solo estorbaría y añadiría latencia.
            vad_filter=False,
            # Cada turno es independiente; el contexto anterior provoca bucles.
            condition_on_previous_text=False,
            # Nombres del glosario: sesgan al decodificador hacia esas grafías.
            hotwords=self._hotwords,
        )
        parts = [segment.text for segment in segments]
        return _WHITESPACE_RE.sub(" ", " ".join(parts)).strip()
