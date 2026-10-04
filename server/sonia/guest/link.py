"""Conexión del Modo Jean con la sala de Cloudflare (``GuestRoom``).

Mientras el Modo Jean está activo, el orquestador abre un segundo WebSocket
(aparte del de ``CloudLink``) hacia ``/guest/agent``, con el mismo token:

- Sube la cámara del stand (JPEG) al ritmo que marca ``VideoRateController``:
  ventana de fotogramas sin confirmar y escalones de tamaño y calidad según la
  red. Si el búfer de envío se llena, se salta vídeo antes que audio.
- Sube el micro del stand a 16 kHz en bloques de 100 ms, sin acumular más de
  300 ms de retraso (lo viejo se tira).
- Baja la voz de Jean y la pasa a Unity como frames ``SNGU``, cortada en
  rachas por ``GuestSpeechSegmenter``.
- Cada segundo manda las estadísticas (fps, kbit/s, RTT...) que pinta el modal.

Solo manda vídeo y audio si hay alguien mirando (``viewers``). Nada de esto
puede tumbar a Sonia: cualquier fallo se registra y se reconecta con espera
creciente.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

from sonia.config import PanelSettings
from sonia.guest.media import (
    KIND_GUEST_AUDIO,
    KIND_STAND_AUDIO,
    KIND_VIDEO,
    STAND_AUDIO_RATE,
    GuestSpeechSegmenter,
    LinearResampler,
    StandAudioPacker,
    VideoRateController,
    decode_room_frame,
    encode_room_frame,
    pcm16_to_float,
)
from sonia.guest.media import (
    STAND_AUDIO_MAX_PENDING as _MAX_PENDING_AUDIO,
)
from sonia.panel.identity import InstanceIdentity
from sonia.types import AudioArray
from sonia.ws.protocol import encode_guest_audio_frame

__all__ = ["FrameGrabber", "GuestAudioSink", "GuestLink", "guest_url"]

logger = logging.getLogger(__name__)

#: ``(width, quality) -> JPEG`` o ``None`` si la cámara no dio imagen.
FrameGrabber = Callable[[int, int], Awaitable[bytes | None]]

#: ``(url, cabeceras) -> conexión``; los tests inyectan uno contra un servidor falso.
GuestConnect = Callable[[str, dict[str, str]], Awaitable[Any]]

RECONNECT_MIN_S = 0.5
RECONNECT_MAX_S = 10.0
#: Una conexión que aguantó esto reinicia la espera entre reintentos.
HEALTHY_CONNECTION_S = 30.0
#: Con más de esto en el búfer de envío se salta el vídeo (el audio manda).
VIDEO_SKIP_BUFFER_BYTES = 256 * 1024
STATS_INTERVAL_S = 1.0
_MAX_SIZE = 4 * 1024 * 1024


class GuestAudioSink(Protocol):
    """Lo que hace falta del hub de Unity: mandar frames binarios."""

    async def broadcast_bytes(self, data: bytes) -> None: ...


def guest_url(cloud_url: str) -> str:
    """``wss://host/agent`` → ``wss://host/guest/agent`` (misma máquina, mismo token)."""
    parts = urlsplit(cloud_url)
    path = parts.path.rsplit("/", 1)[0] if parts.path.endswith("/agent") else parts.path.rstrip("/")
    return urlunsplit((parts.scheme, parts.netloc, f"{path}/guest/agent", "", ""))


class GuestLink:
    """WebSocket del Modo Jean: cámara y micro del stand hacia Jean, su voz hacia Unity."""

    def __init__(
        self,
        settings: PanelSettings,
        identity: InstanceIdentity,
        *,
        sink: GuestAudioSink,
        unity_rate: int,
        mic_rate: int,
        grab: FrameGrabber | None = None,
        connect: GuestConnect | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._identity = identity
        self._sink = sink
        self._unity_rate = unity_rate
        self._mic_rate = mic_rate
        self._grab = grab
        self._connect = connect or _default_connect
        self._clock = clock
        self._ws: Any = None
        self._viewers = 0
        self._video = VideoRateController(clock=clock)
        self._video_wake = asyncio.Event()
        self._audio_wake = asyncio.Event()
        self._packer = StandAudioPacker(mic_rate)
        self._pending_audio: deque[bytes] = deque(maxlen=_MAX_PENDING_AUDIO)
        self._segmenter = GuestSpeechSegmenter(rate=unity_rate)
        self._guest_resampler: LinearResampler | None = None
        self._video_seq = 0
        self._audio_seq = 0
        self._guest_frames = 0
        self._dropped_audio = 0
        self._send_lock = asyncio.Lock()
        self.connected = False

    @property
    def enabled(self) -> bool:
        return bool(self._settings.cloud_url and self._settings.cloud_token)

    @property
    def viewers(self) -> int:
        return self._viewers

    def stats(self) -> dict[str, Any]:
        """Lo que el panel enseña del enlace (forma de ``guest.link`` en ``docs/modo-jean.md``)."""
        return {
            "connected": self.connected,
            "viewers": self._viewers,
            "video": self._video.stats.as_dict(),
            "guest_level": round(self._segmenter.level, 4),
            "guest_frames": self._guest_frames,
            "dropped_audio": self._dropped_audio,
        }

    # -- micro del stand ---------------------------------------------------------

    def push_mic(self, block: AudioArray) -> None:
        """Un bloque del micro del stand (lo llama el motor con cada bloque)."""
        if not self.connected or self._viewers <= 0:
            return
        for chunk in self._packer.push(block):
            if len(self._pending_audio) == self._pending_audio.maxlen:
                self._dropped_audio += 1
            self._pending_audio.append(chunk)
        if self._pending_audio:
            self._audio_wake.set()

    # -- bucle -------------------------------------------------------------------

    async def run(self) -> None:
        """Conecta y reconecta hasta que se cancela."""
        if not self.enabled:
            logger.warning("Modo Jean sin nube: falta PANEL_CLOUD_URL o PANEL_CLOUD_TOKEN")
            return
        url = guest_url(self._settings.cloud_url)
        delay = RECONNECT_MIN_S
        while True:
            started = self._clock()
            try:
                ws = await self._connect(url, self._headers())
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - sin sala, Sonia sigue
                logger.warning("Modo Jean: no se pudo conectar con la sala: %s", exc)
            else:
                try:
                    await self._session(ws)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Modo Jean: se cortó la sala: %s", exc)
                finally:
                    await self._end_session()
                    with contextlib.suppress(Exception):
                        await ws.close()
            if self._clock() - started > HEALTHY_CONNECTION_S:
                delay = RECONNECT_MIN_S
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX_S)

    def _headers(self) -> dict[str, str]:
        from urllib.parse import quote

        return {
            "Authorization": f"Bearer {self._settings.cloud_token}",
            "X-Sonia-Instance": self._identity.id,
            "X-Sonia-Name": quote(self._identity.name[:80], safe=" "),
        }

    async def _session(self, ws: Any) -> None:
        self._ws = ws
        self.connected = True
        self._video.reset()
        logger.info("Modo Jean: conectada a la sala de Cloudflare")
        tasks = [
            asyncio.create_task(self._read(ws), name="guest-read"),
            asyncio.create_task(self._video_loop(ws), name="guest-video"),
            asyncio.create_task(self._audio_loop(ws), name="guest-audio"),
            asyncio.create_task(self._stats_loop(ws), name="guest-stats"),
        ]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()  # el lector acaba al cerrarse; los demás, solo por error
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _end_session(self) -> None:
        self.connected = False
        self._ws = None
        self._viewers = 0
        self._pending_audio.clear()
        self._video.reset()
        # Una racha a medias de Jean se cierra para que Unity no se quede esperando.
        for frame in self._segmenter.close_if_stale(now=float("inf")):
            with contextlib.suppress(Exception):
                await self._sink.broadcast_bytes(encode_guest_audio_frame(*frame))

    async def _send(self, ws: Any, data: bytes | str) -> None:
        async with self._send_lock:
            await ws.send(data)

    def _buffered(self, ws: Any) -> int:
        transport = getattr(ws, "transport", None)
        if transport is None:
            return 0
        with contextlib.suppress(Exception):
            return int(transport.get_write_buffer_size())
        return 0

    # -- entrada: voz de Jean y confirmaciones ----------------------------------

    async def _read(self, ws: Any) -> None:
        from websockets.exceptions import ConnectionClosed

        try:
            async for raw in ws:
                if isinstance(raw, bytes | bytearray):
                    await self._on_binary(bytes(raw))
                elif isinstance(raw, str):
                    self._on_text(raw)
        except ConnectionClosed:
            return

    async def _on_binary(self, data: bytes) -> None:
        try:
            frame = decode_room_frame(data)
        except ValueError:
            return
        if frame.kind != KIND_GUEST_AUDIO or not frame.payload:
            return
        pcm = frame.payload
        if frame.rate and frame.rate != self._unity_rate:
            resampler = self._guest_resampler
            if resampler is None or resampler.src_rate != frame.rate:
                resampler = LinearResampler(frame.rate, self._unity_rate)
                self._guest_resampler = resampler
            samples = resampler.process(pcm16_to_float(pcm))
            pcm = (samples.clip(-1.0, 1.0) * 32767.0).astype("<i2").tobytes()
        self._guest_frames += 1
        for utterance_id, chunk, is_last in self._segmenter.push(pcm, now=self._clock()):
            await self._sink.broadcast_bytes(encode_guest_audio_frame(utterance_id, chunk, is_last))

    def _on_text(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        if not isinstance(msg, dict):
            return
        kind = msg.get("type")
        if kind == "ack":
            seq = msg.get("seq")
            if isinstance(seq, int) and not isinstance(seq, bool):
                self._video.on_ack(seq)
                self._video_wake.set()
        elif kind == "viewers":
            count = msg.get("count")
            if isinstance(count, int) and not isinstance(count, bool):
                previous = self._viewers
                self._viewers = max(0, count)
                if self._viewers == 0:
                    self._video.reset()
                    self._pending_audio.clear()
                elif previous == 0:
                    logger.info("Modo Jean: alguien mira la cámara del stand")
                self._video_wake.set()

    # -- salida: vídeo, micro del stand y estadísticas ---------------------------

    async def _video_loop(self, ws: Any) -> None:
        while True:
            if self._grab is None or self._viewers <= 0:
                await self._wait(self._video_wake, seconds=1.0)
                continue
            if not self._video.can_send():
                await self._wait(self._video_wake, seconds=0.02)
                continue
            if self._buffered(ws) > VIDEO_SKIP_BUFFER_BYTES:
                # La red no da abasto: primero el audio.
                await asyncio.sleep(0.05)
                continue
            step = self._video.step
            try:
                jpeg = await self._grab(step.width, step.quality)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - una captura fallida no corta el vídeo
                logger.exception("Modo Jean: fallo capturando la cámara")
                jpeg = None
            if not jpeg:
                await asyncio.sleep(0.5)
                continue
            self._video_seq += 1
            seq = self._video_seq
            await self._send(ws, encode_room_frame(KIND_VIDEO, seq, self._now_ms(), jpeg))
            self._video.on_sent(seq, len(jpeg))

    async def _audio_loop(self, ws: Any) -> None:
        while True:
            await self._audio_wake.wait()
            self._audio_wake.clear()
            while self._pending_audio:
                chunk = self._pending_audio.popleft()
                self._audio_seq += 1
                frame = encode_room_frame(
                    KIND_STAND_AUDIO, self._audio_seq, self._now_ms(), chunk, rate=STAND_AUDIO_RATE
                )
                await self._send(ws, frame)

    async def _stats_loop(self, ws: Any) -> None:
        while True:
            await asyncio.sleep(STATS_INTERVAL_S)
            self._video.tick()
            for frame in self._segmenter.close_if_stale(now=self._clock()):
                await self._sink.broadcast_bytes(encode_guest_audio_frame(*frame))
            if self._viewers > 0:
                await self._send(ws, json.dumps({"type": "stats", **self.stats()}))

    async def _wait(self, event: asyncio.Event, *, seconds: float) -> None:
        """Espera a ``event`` como mucho ``seconds`` y lo deja bajado."""
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(seconds):
                await event.wait()
        event.clear()

    def _now_ms(self) -> int:
        return int(self._clock() * 1000) & 0xFFFFFFFF


async def _default_connect(url: str, headers: dict[str, str]) -> Any:
    from websockets.asyncio.client import connect

    return await connect(
        url,
        additional_headers=headers,
        max_size=_MAX_SIZE,
        open_timeout=15,
        ping_interval=20,
        ping_timeout=20,
        compression=None,
    )
