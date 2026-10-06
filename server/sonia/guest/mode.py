"""Modo Jean: la secuencia del invitado sorpresa y su enlace de media.

Fases: ``off → intro → entering → live → leaving → off``.

1. ``intro``: GPT-Live se cierra (lo hace ``StandControl`` al ver el modo activo),
   la sala de Cloudflare se abre con audio (``RoomSupervisor.hold_guest``) para
   que Jean ya vea y oiga el stand, y Sonnia dice una frase grabada de
   ``assets/showcase/invitado.md`` (sin gastar).
2. ``entering``: Unity recibe ``guest_mode`` {``phase``: ``enter``}: entra el
   avatar de Jean, se dan la mano y Sonnia sale. Unity avisa con
   ``guest_state`` {``phase``: ``live``}.
3. ``live``: la voz de Jean suena en el stand con su avatar.
4. ``leaving``: ``guest_mode`` {``phase``: ``leave``}; Unity despide a Jean,
   trae a Sonnia y avisa con ``guest_state`` {``phase``: ``off``}.

Nada se queda colgado: si Unity no contesta (app antigua o cerrada), cada paso
sigue igual pasado su tiempo límite. ``guest_mode`` es un mensaje fijo, así que
una pantalla que se conecta a mitad se pone al día sin animación.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Literal

from sonia.ws import protocol as p

if TYPE_CHECKING:  # pragma: no cover - solo para tipado
    from sonia.guest.room import RoomSupervisor
    from sonia.live.engine import LiveEngine
    from sonia.live.voicecache import VoiceCache
    from sonia.ws.hub import Hub

__all__ = ["GuestMode", "GuestPhase"]

logger = logging.getLogger(__name__)

GuestPhase = Literal["off", "intro", "entering", "live", "leaving"]

#: Respiro tras la frase de Sonnia antes de que entre el invitado.
INTRO_TAIL_S = 0.4
#: Lo que se espera a que Unity confirme la entrada (caminar, mano, salida de Sonnia).
ENTER_TIMEOUT_S = 25.0
#: Y la salida.
LEAVE_TIMEOUT_S = 20.0


class GuestMode:
    """Invitado sorpresa (Jean) en el stand: secuencia, media y estado para el panel."""

    def __init__(
        self,
        *,
        hub: Hub,
        engine: LiveEngine,
        room: RoomSupervisor,
        voice_cache: VoiceCache | None,
        intro_lines: list[str],
        unity_rate: int,
        on_change: Callable[[], Awaitable[None]],
        name: str = "Jean",
        rng: random.Random | None = None,
    ) -> None:
        self._hub = hub
        self._engine = engine
        self._room = room
        self._voice_cache = voice_cache
        self._intro_lines = intro_lines
        self._unity_rate = unity_rate
        self._on_change = on_change
        self._name = name
        self._rng = rng or random.Random()
        self._phase: GuestPhase = "off"
        self._unity_phase: str | None = None
        self._unity_live = asyncio.Event()
        self._unity_off = asyncio.Event()
        self._sequence: asyncio.Task[None] | None = None

    @property
    def phase(self) -> GuestPhase:
        return self._phase

    @property
    def active(self) -> bool:
        return self._phase != "off"

    @property
    def available(self) -> bool:
        return self._room.available

    def status(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "phase": self._phase,
            "name": self._name,
            "unity_phase": self._unity_phase,
            "intro_ready": self._intro_clip() is not None,
            "link": self._room.link.stats(),
        }

    # -- control ------------------------------------------------------------------

    async def start(self) -> tuple[bool, str]:
        if self._phase != "off":
            return True, "El Modo Jean ya está en marcha."
        if not self._room.available:
            return (
                False,
                "Esta Sonnia no está conectada a la nube: el Modo Jean necesita PANEL_CLOUD_TOKEN.",
            )
        self._phase = "intro"
        logger.info("Modo Jean: empieza (invitado %s)", self._name)
        await self._on_change()
        self._room.hold_guest()
        self._sequence = asyncio.create_task(self._enter(), name="guest-enter")
        return True, f"Sonnia presenta a {self._name}: en unos segundos el stand te oye."

    async def stop(self) -> tuple[bool, str]:
        if self._phase == "off":
            return True, "El Modo Jean no estaba activo."
        if self._phase == "leaving":
            return True, f"{self._name} ya se está despidiendo."
        await self._cancel_sequence()
        self._phase = "leaving"
        self._sequence = asyncio.create_task(self._leave(), name="guest-leave")
        return True, f"{self._name} se despide y vuelve Sonia."

    def on_unity_state(self, phase: str) -> None:
        """``guest_state`` de Unity: cuándo el invitado ya está o ya se fue."""
        self._unity_phase = phase
        if phase == "live":
            self._unity_live.set()
        elif phase == "off":
            self._unity_off.set()

    async def close(self) -> None:
        """Al apagar el orquestador: corta la secuencia y el audio sin esperar a Unity."""
        await self._cancel_sequence()
        await self._room.release_guest()

    # -- secuencia ----------------------------------------------------------------

    async def _enter(self) -> None:
        try:
            clip = self._intro_clip()
            if clip is None:
                logger.warning(
                    "Modo Jean: la frase de entrada no está grabada (usa «Preparar voces»); "
                    "entra sin anunciarlo"
                )
            else:
                text, pcm = clip
                if await self._engine.play_clip(pcm, text, attention="fourth_wall"):
                    await asyncio.sleep(len(pcm) / 2 / self._unity_rate + INTRO_TAIL_S)
            self._phase = "entering"
            self._unity_live.clear()
            await self._hub.set_sticky(
                "guest", p.msg_guest_mode("enter", self._name, self._unity_rate)
            )
            try:
                async with asyncio.timeout(ENTER_TIMEOUT_S):
                    await self._unity_live.wait()
            except TimeoutError:
                logger.warning("Modo Jean: Unity no confirmó la entrada; el invitado habla igual")
            self._phase = "live"
            logger.info("Modo Jean: %s en directo", self._name)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Modo Jean: fallo en la entrada; se sigue en directo")
            self._phase = "live"

    async def _leave(self) -> None:
        try:
            self._unity_off.clear()
            await self._hub.set_sticky(
                "guest", p.msg_guest_mode("leave", self._name, self._unity_rate)
            )
            try:
                async with asyncio.timeout(LEAVE_TIMEOUT_S):
                    await self._unity_off.wait()
            except TimeoutError:
                logger.warning("Modo Jean: Unity no confirmó la salida; Sonnia vuelve igual")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Modo Jean: fallo en la salida")
        finally:
            await self._room.release_guest()
            self._phase = "off"
            logger.info("Modo Jean: terminado")
            with contextlib.suppress(Exception):
                await self._on_change()

    async def _cancel_sequence(self) -> None:
        task = self._sequence
        self._sequence = None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def _intro_clip(self) -> tuple[str, bytes] | None:
        cache = self._voice_cache
        if cache is None:
            return None
        ready = [(text, pcm) for text in self._intro_lines if (pcm := cache.get(text)) is not None]
        return self._rng.choice(ready) if ready else None
