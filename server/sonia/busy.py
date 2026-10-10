"""Aviso de espera en pantalla (``busy``): «la gente es bruta y se desespera» (Jean, 10-oct-2026).

Mientras Sonia espera algo que el visitante no ve (una tarea delegada en el backend, una
búsqueda en internet, el juez de un juego mirando la foto, la cámara que arranca), Unity
enseña una pastilla con puntos animados. Varias esperas pueden coincidir; cada una se
apunta con su clave y Unity solo ve la de más prioridad (``BUSY_KINDS``, en orden), con su
texto. Cuando no queda ninguna, ``busy`` con ``on: false``.

Unity la saca al momento y la sostiene al menos un poco para que no parpadee; este lado solo
manda el estado al cambiar (y entero: :meth:`BusyBoard.message` sirve para repetirlo a una
Unity que se reconecta).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from sonia.ws import protocol as p

__all__ = [
    "TEXT_CAMERA",
    "TEXT_GAME",
    "TEXT_HAND",
    "TEXT_LOOK",
    "TEXT_POSES",
    "TEXT_SEARCH",
    "TEXT_THINK",
    "BusyBoard",
    "BusyKind",
]

logger = logging.getLogger(__name__)

#: Tipos de espera, de más a menos prioridad (``protocol.BUSY_KINDS``).
BusyKind = Literal["judge", "camera", "game", "search", "think"]

# Textos de la pastilla: cortos, para leerse a 2-3 m.
TEXT_THINK = "Pensando…"
TEXT_SEARCH = "Buscando en internet…"
TEXT_GAME = "Preparando el juego…"
TEXT_CAMERA = "Encendiendo la cámara…"
TEXT_POSES = "Mirando las poses…"
TEXT_HAND = "Mirando tu mano…"
TEXT_LOOK = "Mirando lo que enseñas…"

SendJson = Callable[[dict[str, Any]], Awaitable[None]]


class BusyBoard:
    """Las esperas en marcha, por clave; manda ``busy`` a Unity cuando cambia la que se ve.

    Sin ``send_json`` (tests, o antes de conectar con Unity) solo lleva la cuenta. Nunca
    lanza: un fallo al mandar se apunta en el registro y la espera queda apuntada igual.
    """

    def __init__(self, send_json: SendJson | None = None) -> None:
        self._send = send_json
        #: clave → (tipo, texto), en el orden en que llegaron.
        self._waits: dict[str, tuple[BusyKind, str]] = {}
        self._shown: dict[str, Any] = p.msg_busy(False)

    def bind(self, send_json: SendJson | None) -> None:
        """Cambia hacia dónde se manda (el ``Hub`` del motor)."""
        self._send = send_json

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(self._waits)

    def current(self) -> tuple[BusyKind, str] | None:
        """La espera que se ve: la de más prioridad y, entre iguales, la más reciente."""
        best: tuple[BusyKind, str] | None = None
        best_rank = len(p.BUSY_KINDS)
        for kind, text in self._waits.values():
            rank = p.BUSY_KINDS.index(kind)
            if rank <= best_rank:
                best, best_rank = (kind, text), rank
        return best

    def message(self) -> dict[str, Any]:
        """El ``busy`` que toca ahora (para una Unity que se acaba de conectar)."""
        shown = self.current()
        return p.msg_busy(False) if shown is None else p.msg_busy(True, shown[0], shown[1])

    async def set(self, key: str, kind: BusyKind, text: str) -> None:
        """Empieza (o cambia) la espera ``key``."""
        self._waits.pop(key, None)
        self._waits[key] = (kind, text)
        await self._publish()

    async def clear(self, key: str) -> None:
        """Termina la espera ``key`` (si no estaba, nada)."""
        if self._waits.pop(key, None) is not None:
            await self._publish()

    async def clear_prefix(self, prefix: str) -> None:
        """Termina todas las esperas cuya clave empieza por ``prefix`` (las de un juego)."""
        gone = [key for key in self._waits if key.startswith(prefix)]
        for key in gone:
            del self._waits[key]
        if gone:
            await self._publish()

    async def _publish(self) -> None:
        message = self.message()
        if message == self._shown:
            return
        self._shown = message
        logger.debug("Aviso de espera: %s", message)
        if self._send is None:
            return
        try:
            await self._send(message)
        except Exception:  # noqa: BLE001 - sin aviso, Sonia sigue
            logger.warning("No se pudo mandar el aviso de espera a Unity", exc_info=True)
