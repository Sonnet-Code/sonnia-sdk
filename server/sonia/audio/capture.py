"""Captura de micrófono con `sounddevice`, entregada al bucle asyncio en bloques.

El callback de PortAudio corre en un hilo propio y no puede bloquearse: se
limita a copiar el bloque y pasarlo al bucle con ``loop.call_soon_threadsafe``.
La cola está acotada; si el consumidor se retrasa se descartan los bloques más
viejos (mejor perder audio antiguo que acumular latencia).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator
from types import TracebackType
from typing import Any, Self

import numpy as np

from sonia.config import AudioSettings
from sonia.types import INPUT_SAMPLE_RATE, AudioArray

_log = logging.getLogger(__name__)

#: Bloques como máximo en la cola (con bloques de 32 ms son ~1.6 s de audio).
QUEUE_MAXSIZE = 50

#: Segundos mínimos entre dos avisos iguales, para no inundar el log.
_WARN_INTERVAL_S = 5.0

#: Si PortAudio deja de entregar bloques durante este tiempo, se da el
#: micrófono por muerto. Mientras el stream vive el callback sigue llegando
#: aunque haya silencio absoluto, así que un hueco de segundos solo pasa cuando
#: el dispositivo desaparece o el stream se aborta sin avisar.
DEFAULT_STALL_TIMEOUT_S = 3.0

#: Si, después de haber llegado sonido, solo llega silencio digital (todas las
#: muestras a cero exacto) durante este tiempo, el stream se da por atascado:
#: un micrófono de verdad siempre trae algo de ruido. Pasa al desenchufar y
#: volver a enchufar el micro USB: PortAudio sigue entregando bloques, pero
#: vacíos, del dispositivo que ya no existe.
DEFAULT_SILENCE_TIMEOUT_S = 5.0


class MicStalled(RuntimeError):
    """El micrófono dejó de entregar audio (o solo entrega ceros) sin cerrar el stream."""


def refresh_devices() -> None:
    """Vuelve a leer los dispositivos de audio del sistema.

    PortAudio solo los lee al iniciarse, así que un micrófono USB que se
    desenchufa y se vuelve a enchufar no aparece (o sigue apuntando al que ya no
    existe) hasta reiniciar el proceso. Solo se puede llamar sin ningún stream
    abierto. Si falla, se avisa y se sigue con la lista que había.
    """
    try:
        import sounddevice as sd

        sd._terminate()
        sd._initialize()
    except Exception as exc:  # noqa: BLE001 - depende del hardware y de PortAudio
        _log.warning("No se pudo volver a leer la lista de dispositivos de audio: %s", exc)


def list_input_devices() -> list[dict[str, Any]]:
    """Devuelve los dispositivos de entrada disponibles (para ``sonia check``).

    Cada elemento trae ``index``, ``name``, ``channels``, ``sample_rate`` y
    ``default``. Si `sounddevice` no está instalado o PortAudio falla, devuelve
    una lista vacía en vez de lanzar: la demo debe seguir arrancando.
    """
    try:
        import sounddevice as sd
    except Exception:  # pragma: no cover - depende del entorno
        _log.warning("sounddevice no está disponible: no se pueden listar micrófonos")
        return []

    try:
        devices = sd.query_devices()
        default_index = _default_input_index(sd)
    except Exception as exc:  # pragma: no cover - depende del hardware
        _log.warning("No se pudieron consultar los dispositivos de audio: %s", exc)
        return []

    result: list[dict[str, Any]] = []
    for position, device in enumerate(devices):
        if int(device.get("max_input_channels", 0)) <= 0:
            continue
        index = int(device.get("index", position))
        result.append(
            {
                "index": index,
                "name": str(device.get("name", "")),
                "channels": int(device.get("max_input_channels", 0)),
                "sample_rate": float(device.get("default_samplerate", 0.0)),
                "default": index == default_index,
            }
        )
    return result


def _default_input_index(sd: Any) -> int | None:
    """Índice del dispositivo de entrada por defecto, o ``None`` si no hay."""
    try:
        default = sd.default.device
    except Exception:  # pragma: no cover - depende del hardware
        return None
    value = default[0] if isinstance(default, list | tuple) and default else default
    try:
        index = int(value)
    except (TypeError, ValueError):
        return None
    return index if index >= 0 else None


def resolve_input_device(spec: str) -> int | None:
    """Traduce la configuración ``input_device`` a un id de sounddevice.

    Acepta un índice numérico, un fragmento del nombre del dispositivo
    (búsqueda por subcadena, sin distinguir mayúsculas) o cadena vacía para el
    dispositivo por defecto.
    """
    spec = (spec or "").strip()
    if not spec:
        return None

    try:
        return int(spec)
    except ValueError:
        pass

    import sounddevice as sd

    needle = spec.casefold()
    devices = sd.query_devices()
    for position, device in enumerate(devices):
        if int(device.get("max_input_channels", 0)) <= 0:
            continue
        if needle in str(device.get("name", "")).casefold():
            return int(device.get("index", position))

    available = ", ".join(d["name"] for d in list_input_devices()) or "ninguno"
    raise ValueError(
        f"No hay ningún micrófono cuyo nombre contenga {spec!r}. Disponibles: {available}"
    )


class MicCapture:
    """Micrófono mono float32 como flujo asíncrono de bloques.

    Por defecto a 16 kHz, la tasa del VAD y del reconocedor. El motor GPT-Live
    lo abre a la tasa de su sesión (24 kHz) para no remuestrear.

    Uso::

        async with MicCapture(settings.audio) as mic:
            async for block in mic.blocks():
                ...
    """

    def __init__(
        self,
        settings: AudioSettings,
        *,
        stall_timeout: float = DEFAULT_STALL_TIMEOUT_S,
        silence_timeout: float = DEFAULT_SILENCE_TIMEOUT_S,
        sample_rate: int = INPUT_SAMPLE_RATE,
    ) -> None:
        self._settings = settings
        self._stall_timeout = stall_timeout
        self._silence_timeout = silence_timeout
        self._sample_rate = sample_rate
        self._block_samples = max(1, settings.block_ms * sample_rate // 1000)
        self._queue: asyncio.Queue[AudioArray | None] = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stream: Any = None
        self._closed = False
        self._dropped = 0
        self._last_warning: dict[str, float] = {}

    # -- propiedades -----------------------------------------------------

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def block_samples(self) -> int:
        """Muestras por bloque (``block_ms`` a la tasa del micrófono)."""
        return self._block_samples

    @property
    def dropped_blocks(self) -> int:
        """Bloques descartados por cola llena desde que se abrió el micrófono."""
        return self._dropped

    # -- context manager -------------------------------------------------

    async def __aenter__(self) -> Self:
        import sounddevice as sd

        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
        self._closed = False
        self._dropped = 0

        device = resolve_input_device(self._settings.input_device)
        self._stream = sd.InputStream(
            samplerate=self._sample_rate,
            blocksize=self._block_samples,
            device=device,
            channels=1,
            dtype="float32",
            callback=self._on_audio,
        )
        self._stream.start()
        _log.info(
            "Micrófono abierto (dispositivo=%s, %d Hz, bloques de %d muestras)",
            "por defecto" if device is None else device,
            self._sample_rate,
            self._block_samples,
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Cierra el stream y termina el iterador de bloques."""
        self._closed = True
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception as err:  # pragma: no cover - depende del hardware
                _log.warning("Error cerrando el micrófono: %s", err)
        if self._dropped:
            _log.info("Se descartaron %d bloques de audio por cola llena", self._dropped)
        # Sentinela para desbloquear a quien esté esperando en blocks(). Si la
        # cola está llena se hace sitio descartando el bloque más viejo.
        if self._queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
        with contextlib.suppress(asyncio.QueueFull):
            self._queue.put_nowait(None)

    # -- flujo de bloques ------------------------------------------------

    async def blocks(self) -> AsyncIterator[AudioArray]:
        """Produce bloques de audio mono float32 hasta que se cierre el stream.

        Si PortAudio deja de llamar al callback (micrófono desconectado, cambio
        de dispositivo por defecto, stream abortado) no llega ninguna excepción
        por su cuenta: la corrutina se quedaría esperando para siempre y Sonia
        se volvería sorda en silencio. Por eso se vigila el hueco entre bloques
        y se lanza :class:`MicStalled`, que quien llama usa para reabrir. Lo
        mismo si, tras haber oído algo, solo llegan ceros exactos (el micro USB
        se desenchufó y se volvió a enchufar); un micro que llega mudo desde el
        principio (con su botón de silencio) no se reabre en bucle.
        """
        if self._stream is None and not self._closed:
            raise RuntimeError("MicCapture.blocks() requiere abrir el micrófono con 'async with'")
        heard = False
        silent_since: float | None = None
        while True:
            timeout = self._stall_timeout if self._stall_timeout > 0 else None
            try:
                block = await asyncio.wait_for(self._queue.get(), timeout=timeout)
            except TimeoutError:
                if self._closed:
                    break
                raise MicStalled(
                    f"el micrófono no entrega audio desde hace {self._stall_timeout:g} s "
                    f"(stream activo: {self.stream_active})"
                ) from None
            if block is None:
                break
            if self._silence_timeout > 0:
                if block.any():
                    heard = True
                    silent_since = None
                elif heard:
                    now = time.monotonic()
                    if silent_since is None:
                        silent_since = now
                    elif now - silent_since >= self._silence_timeout:
                        raise MicStalled(
                            "el micrófono solo entrega silencio digital desde hace "
                            f"{self._silence_timeout:g} s (¿se desenchufó?)"
                        )
            yield block

    @property
    def stream_active(self) -> bool:
        """¿PortAudio dice que el stream sigue vivo? (solo informativo)."""
        stream = self._stream
        if stream is None:
            return False
        try:
            return bool(stream.active)
        except Exception:  # noqa: BLE001 - depende del backend de PortAudio
            return False

    # -- interno ---------------------------------------------------------

    def _on_audio(
        self,
        indata: np.ndarray[Any, Any],
        frames: int,
        time_info: Any,
        status: Any,
    ) -> None:
        """Callback de PortAudio. Corre en el hilo de audio: nada de bloqueos."""
        if status:
            self._warn_throttled("status", "Estado del stream de audio: %s", status)
        loop = self._loop
        if loop is None or self._closed:
            return
        block: AudioArray = np.array(indata[:, 0], dtype=np.float32, copy=True)
        # Si el bucle ya se cerró, el bloque simplemente se pierde.
        with contextlib.suppress(RuntimeError):  # pragma: no cover
            loop.call_soon_threadsafe(self._push, block)

    def _push(self, block: AudioArray) -> None:
        """Encola un bloque en el bucle asyncio, descartando el más viejo si hace falta."""
        if self._closed:
            return
        if self._queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
            self._dropped += 1
            self._warn_throttled(
                "drop",
                "Cola de audio llena: se descartan bloques (%d en total). ¿Consumidor lento?",
                self._dropped,
            )
        try:
            self._queue.put_nowait(block)
        except asyncio.QueueFull:  # pragma: no cover - carrera improbable
            self._dropped += 1

    def _warn_throttled(self, key: str, message: str, *args: Any) -> None:
        """Registra un warning como mucho cada ``_WARN_INTERVAL_S`` segundos por clave."""
        now = time.monotonic()
        if now - self._last_warning.get(key, 0.0) < _WARN_INTERVAL_S:
            return
        self._last_warning[key] = now
        _log.warning(message, *args)
