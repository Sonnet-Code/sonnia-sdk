"""La sala de Cloudflare del stand: quién la necesita y qué media lleva.

La usan dos cosas:

- El Modo Jean (``hold_guest`` y ``release_guest``): vídeo, micro del stand
  hacia la sala (``LiveEngine.add_mic_listener``) y voz de Jean hacia Unity.
- «Ver cámara» (``watch`` y ``unwatch``): solo vídeo. No toca GPT-Live, no
  anuncia nada y no manda nada a Unity. Se suelta sola cuando no queda ningún
  navegador en la sala durante ``WATCH_GRACE_S``. Si alguien pulsó «Cerrar»,
  el margen es ``WATCH_CLOSE_GRACE_S``. El modal la renueva mientras está
  abierto (``WATCH_KEEPALIVE_S`` en ``static/room.js``).

``RoomSupervisor`` mantiene ``GuestLink`` abierto mientras alguno de los dos la
necesite y lo cierra en cuanto ninguno la necesita. Si el enlace usaba una
cámara propia (con la visión de Sonia apagada), entonces la suelta. El vídeo
solo sale con alguien mirando (``GuestLink`` mira los ``viewers`` de la sala) y
no se guarda nada.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - solo para tipado
    from sonia.guest.link import GuestLink
    from sonia.live.engine import LiveEngine

__all__ = ["WATCH_CLOSE_GRACE_S", "WATCH_GRACE_S", "RoomSupervisor"]

logger = logging.getLogger(__name__)

#: Sin nadie mirando, «Ver cámara» se suelta pasado esto (el modal la renueva
#: mientras está abierto, así que solo cuenta cuando se cierra o se cae).
WATCH_GRACE_S = 25.0
#: Lo mismo cuando alguien pulsó «Cerrar»: casi al momento.
WATCH_CLOSE_GRACE_S = 3.0
#: Cada cuánto se mira si queda alguien.
WATCH_TICK_S = 1.0


class RoomSupervisor:
    """Abre la sala mientras la necesiten el Modo Jean o «Ver cámara»."""

    def __init__(
        self,
        link: GuestLink,
        engine: LiveEngine,
        *,
        camera_available: bool = True,
        release_camera: Callable[[], Awaitable[None]] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._link = link
        self._engine = engine
        self._camera_available = camera_available
        self._release_camera = release_camera
        self._clock = clock
        self._task: asyncio.Task[None] | None = None
        #: Enlace que se está cerrando: uno nuevo espera a que termine.
        self._stopping: asyncio.Task[None] | None = None
        self._watchdog: asyncio.Task[None] | None = None
        self._guest = False
        self._watching = False
        self._closing = False
        self._deadline = 0.0

    @property
    def link(self) -> GuestLink:
        return self._link

    @property
    def available(self) -> bool:
        """Hay nube: la sala se puede abrir."""
        return self._link.enabled

    @property
    def can_watch(self) -> bool:
        """Hay nube y una cámara con la que llenar la sala."""
        return self.available and self._camera_available

    @property
    def watching(self) -> bool:
        return self._watching

    @property
    def is_open(self) -> bool:
        return self._task is not None and not self._task.done()

    def watch_status(self) -> dict[str, Any]:
        """``camera_watch`` del estado del panel (forma en ``docs/panel.md``)."""
        link = self._link
        stats = link.stats()
        return {
            "available": self.can_watch,
            "active": self._watching,
            "open": self.is_open,
            "connected": link.connected,
            "viewers": link.viewers,
            "live": bool(link.connected and link.viewers > 0),
            "video": stats.get("video"),
        }

    # -- Modo Jean ---------------------------------------------------------------

    def hold_guest(self) -> None:
        """El Modo Jean empieza: sala abierta con el micro del stand y la voz de Jean."""
        if not self._guest:
            self._guest = True
            self._link.set_guest_media(True)
            self._engine.add_mic_listener(self._link.push_mic)
        self._ensure_open()

    async def release_guest(self) -> None:
        """El Modo Jean termina: fuera el audio; la sala sigue si alguien la mira."""
        if self._guest:
            self._guest = False
            self._engine.remove_mic_listener(self._link.push_mic)
            self._link.set_guest_media(False)
        await self._close_if_unused()

    # -- «Ver cámara» ------------------------------------------------------------

    def watch(self) -> bool:
        """Alguien quiere ver la cámara (o lo renueva). Devuelve si acaba de empezar."""
        started = not self._watching
        self._watching = True
        self._closing = False
        self._deadline = max(self._deadline, self._clock() + WATCH_GRACE_S)
        if started:
            logger.info("Ver cámara: se abre la sala solo con vídeo")
        self._ensure_open()
        if self._watchdog is None or self._watchdog.done():
            self._watchdog = asyncio.create_task(self._watch_loop(), name="camera-watch")
        return started

    def unwatch(self) -> None:
        """Alguien pulsó «Cerrar»: la sala se cierra en cuanto no quede nadie mirando."""
        if not self._watching:
            return
        self._closing = True
        self._deadline = self._clock() + WATCH_CLOSE_GRACE_S

    async def _watch_loop(self) -> None:
        try:
            while self._watching:
                await asyncio.sleep(WATCH_TICK_S)
                now = self._clock()
                if self._link.viewers > 0:
                    grace = WATCH_CLOSE_GRACE_S if self._closing else WATCH_GRACE_S
                    self._deadline = max(self._deadline, now + grace)
                    continue
                if now >= self._deadline:
                    self._watching = False
                    self._closing = False
                    logger.info("Ver cámara: ya no mira nadie; se cierra la sala")
                    await self._close_if_unused()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - un fallo aquí no puede dejar la cámara saliendo
            logger.exception("Ver cámara: fallo vigilando la sala; se cierra")
            self._watching = False
            await self._close_if_unused()

    # -- sala ----------------------------------------------------------------------

    def _ensure_open(self) -> None:
        if self.is_open:
            return
        self._task = asyncio.create_task(self._run_after(self._stopping), name="guest-link")

    async def _run_after(self, previous: asyncio.Task[None] | None) -> None:
        # El enlace es uno solo: si el anterior aún se está cerrando, se espera.
        if previous is not None:
            await asyncio.gather(previous, return_exceptions=True)
        await self._link.run()

    async def _close_if_unused(self) -> None:
        if self._guest or self._watching:
            return
        task = self._task
        self._task = None
        if task is not None:
            self._stopping = task
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if self._stopping is task:
                self._stopping = None
            logger.info("Sala de vídeo cerrada: la cámara ya no sale del stand")
        # Mientras se cerraba pudo volver a hacer falta: entonces la cámara sigue.
        if self._release_camera is not None and not (self._guest or self._watching):
            with contextlib.suppress(Exception):
                await self._release_camera()

    async def close(self) -> None:
        """Al apagar el orquestador: todo fuera."""
        self._watching = False
        watchdog = self._watchdog
        self._watchdog = None
        if watchdog is not None and not watchdog.done():
            watchdog.cancel()
            await asyncio.gather(watchdog, return_exceptions=True)
        if self._guest:
            self._guest = False
            self._engine.remove_mic_listener(self._link.push_mic)
            self._link.set_guest_media(False)
        await self._close_if_unused()
