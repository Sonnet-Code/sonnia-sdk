"""Síntesis de voz local en proceso con OmniVoice (k2-fsa/OmniVoice).

Suposiciones sobre la API del paquete ``omnivoice``, tomadas de su README
(el paquete es muy pesado y no está instalado en el entorno de desarrollo, por
eso se importa de forma perezosa y se puede inyectar un modelo falso):

- ``from omnivoice import OmniVoice`` expone la clase principal.
- ``OmniVoice.from_pretrained(repo_id, device_map=..., dtype=...)`` descarga y
  carga los pesos. ``device_map`` es una cadena (``"cuda"``, ``"mps"``,
  ``"cpu"``) y ``dtype`` un ``torch.dtype``. En CUDA se usa ``float16``; en MPS
  y CPU hay que quedarse en ``float32`` porque el half no está bien soportado.
- ``model.generate(...)`` sintetiza y devuelve una **lista** de ``np.ndarray``
  mono de forma ``(T,)`` en float, a 24 kHz. Acepta:
  - ``text``: el texto a hablar.
  - ``instruct``: descripción en lenguaje natural de la voz (*voice design*).
  - ``ref_audio`` y ``ref_text``: alternativa al anterior, clonación por audio
    de referencia y su transcripción (``ref_text`` puede ser ``None``).
  - ``num_step``: pasos de difusión (menos pasos, menos latencia).
  - ``speed``: factor de velocidad del habla.
- La llamada es síncrona y bloqueante, así que va en ``asyncio.to_thread``, y no
  es reentrante: se serializa con dos cerrojos. El ``asyncio.Lock`` mantiene el
  orden de las frases, pero se suelta en cuanto se cancela el turno aunque el
  hilo siga dentro de ``generate`` (a un hilo no se le puede cancelar). Por eso
  hay además un ``threading.Lock`` que se toma **dentro** del hilo: la síntesis
  nueva espera ahí a que termine la huérfana en vez de entrar en paralelo.

Si la API real difiere, el único punto a tocar es :meth:`OmniVoiceTTS._generate`.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import AsyncIterator, Callable
from typing import Any

import numpy as np

from ..config import TTSSettings
from ..types import AudioChunk
from .base import DEFAULT_CHUNK_MS, chunk_pcm, float_to_pcm16, resample

__all__ = ["OmniVoiceTTS"]

log = logging.getLogger(__name__)

#: Identificador del repo de pesos en Hugging Face.
MODEL_ID = "k2-fsa/OmniVoice"

#: Tasa de muestreo nativa de OmniVoice.
MODEL_SAMPLE_RATE = 24_000

#: Frase corta para el warmup (compila kernels y llena cachés).
WARMUP_TEXT = "Hola."


class OmniVoiceTTS:
    """Motor de TTS en proceso. Implementa :class:`~sonia.types.TextToSpeech`."""

    def __init__(
        self,
        settings: TTSSettings,
        *,
        model_factory: Callable[[], Any] | None = None,
        chunk_ms: int = DEFAULT_CHUNK_MS,
    ) -> None:
        self._settings = settings
        #: Fábrica del modelo. En producción es ``None`` y se usa la carga real;
        #: los tests inyectan aquí un modelo falso para no depender del paquete.
        self._model_factory = model_factory
        self._chunk_ms = chunk_ms
        self._model: Any | None = None
        #: Ordena las frases en el bucle de eventos.
        self._lock = asyncio.Lock()
        #: Serializa de verdad las llamadas al modelo, dentro de los hilos: el
        #: asyncio.Lock se libera al cancelar aunque el hilo siga generando.
        self._thread_lock = threading.Lock()
        #: Evita que dos turnos simultáneos carguen el modelo dos veces.
        self._load_lock = asyncio.Lock()

    @property
    def sample_rate(self) -> int:
        return self._settings.sample_rate

    # -- carga del modelo ---------------------------------------------------

    def resolve_device(self) -> str:
        """Decide el dispositivo: lo configurado, o auto (cuda > mps > cpu)."""
        configured = (self._settings.device or "auto").strip().lower()
        if configured and configured != "auto":
            return configured
        try:
            import torch
        except ImportError:  # pragma: no cover - depende del entorno
            return "cpu"
        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    def _load_model(self) -> Any:
        """Carga bloqueante del modelo. Se llama siempre desde un hilo."""
        if self._model_factory is not None:
            return self._model_factory()

        import torch
        from omnivoice import OmniVoice

        device = self.resolve_device()
        # En MPS y CPU el float16 da resultados inestables o ni siquiera está
        # implementado para algunas operaciones, así que solo se usa en CUDA.
        dtype = torch.float16 if device == "cuda" else torch.float32
        log.info("Cargando OmniVoice en %s (%s)", device, dtype)
        return OmniVoice.from_pretrained(MODEL_ID, device_map=device, dtype=dtype)

    async def ensure_loaded(self) -> Any:
        """Carga el modelo la primera vez, en un hilo, sin bloquear el bucle."""
        if self._model is not None:
            return self._model
        async with self._load_lock:
            if self._model is None:
                self._model = await asyncio.to_thread(self._load_model)
        return self._model

    # -- síntesis -----------------------------------------------------------

    def _generate_kwargs(self, text: str) -> dict[str, Any]:
        """Argumentos de ``model.generate`` según el modo de voz configurado."""
        settings = self._settings
        kwargs: dict[str, Any] = {
            "text": text,
            "num_step": settings.num_step,
            "speed": settings.speed,
        }
        if settings.ref_audio:
            # La clonación por audio de referencia tiene prioridad.
            kwargs["ref_audio"] = settings.ref_audio
            kwargs["ref_text"] = settings.ref_text or None
        else:
            kwargs["instruct"] = settings.voice_instruct
        return kwargs

    def _run_generate(self, model: Any, text: str) -> Any:
        # Corre en un hilo del executor. El cerrojo evita que una generación
        # huérfana (turno cancelado) coincida con la siguiente sobre un modelo
        # que no es reentrante.
        with self._thread_lock:
            return model.generate(**self._generate_kwargs(text))

    async def _generate_pcm(self, text: str) -> bytes:
        """Sintetiza ``text`` y devuelve PCM s16le a ``self.sample_rate``."""
        model = await self.ensure_loaded()
        async with self._lock:
            raw = await asyncio.to_thread(self._run_generate, model, text)
        audio = _as_mono_float(raw)
        if audio.size == 0:
            return b""
        if self.sample_rate != MODEL_SAMPLE_RATE:
            audio = resample(audio, MODEL_SAMPLE_RATE, self.sample_rate)
        return float_to_pcm16(audio)

    async def synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        """Sintetiza y emite chunks de ``chunk_ms`` milisegundos."""
        pcm = await self._generate_pcm(text)
        for chunk in chunk_pcm(pcm, self.sample_rate, self._chunk_ms):
            yield chunk
            # Se cede el control entre chunks para no monopolizar el bucle.
            await asyncio.sleep(0)

    async def warmup(self) -> None:
        """Carga el modelo y sintetiza una frase corta para calentarlo."""
        try:
            await self._generate_pcm(WARMUP_TEXT)
        except Exception:  # pragma: no cover - el warmup nunca debe tumbar la demo
            log.exception("Falló el warmup de OmniVoice")


def _as_mono_float(raw: Any) -> np.ndarray:
    """Normaliza la salida del modelo a un único array mono float32.

    OmniVoice devuelve una lista de arrays ``(T,)`` (un elemento por segmento);
    se concatenan en el orden en que llegan. También se acepta un array suelto.
    """
    if raw is None:
        return np.zeros(0, dtype=np.float32)
    if isinstance(raw, (list, tuple)):
        pieces = [np.asarray(item, dtype=np.float32).reshape(-1) for item in raw]
        pieces = [piece for piece in pieces if piece.size]
        if not pieces:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(pieces)
    return np.asarray(raw, dtype=np.float32).reshape(-1)
