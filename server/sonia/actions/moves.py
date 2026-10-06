"""Acción ``play_animation``: bailes y gestos que se le piden a Sonia de viva voz.

GPT-Live la delega cuando el visitante le pide que baile, salude, haga la señal
de paz... El backend elige un movimiento de una lista fija de nombres en
español (:data:`MOVES`) y aquí se busca el clip en el catálogo que manda Unity
al conectarse (mensaje ``animations``, el mismo que usa el panel), así que solo
suena lo que tiene la app. Va a Unity como ``play_animation`` con
``whole: true``: el clip suena entero aunque Sonia hable mientras tanto (si no,
el «¡allá voy!» lo cortaría al pasar a ``speaking``).

El motor deja el catálogo en ``ctx.extra["moves"]``.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sonia.types import ActionContext, ActionResult, ActionSpec
from sonia.ws import protocol as p

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Move:
    """Un movimiento que se puede pedir: qué clips del catálogo de Unity lo hacen."""

    #: Qué es, para el backend.
    description: str
    #: Grupos del catálogo cuyos clips valen todos (``dance``, ``greeting``...).
    groups: tuple[str, ...] = ()
    #: Clips concretos, por nombre.
    clips: tuple[str, ...] = ()


#: Movimientos que se pueden pedir de viva voz. Si la app de Unity no tiene
#: ninguno de sus clips, ese movimiento no está disponible.
MOVES: dict[str, Move] = {
    "bailar": Move("un baile corto", groups=("dance",)),
    "saludar": Move("saludar con la mano", groups=("greeting",), clips=("WaveGeneric",)),
    "paz": Move("la señal de paz con los dedos", clips=("Peace",)),
    "saludo_militar": Move("un saludo militar", clips=("QuickAction_salute",)),
    "pulgares_arriba": Move("los dos pulgares arriba", clips=("QuickAction_twoThumbsUp",)),
    "celebrar": Move("celebrar con alegría", clips=("actions-highFive_actionSuccess",)),
    "lamentarse": Move("un gesto de «casi, qué pena»", clips=("actions-highFive_actionFail",)),
    "pensar": Move("ponerse pensativa", groups=("thinking",)),
}

NO_MOVES = (
    "Ahora mismo no puedes moverte a petición (la app del avatar no está conectada). "
    "Dilo con gracia y sigue conversando."
)

#: Manda un mensaje JSON a Unity (``hub.broadcast_json``).
SendJson = Callable[[dict[str, Any]], Awaitable[None]]


class MoveCatalog:
    """Clips de la app de Unity que se pueden lanzar, por movimiento."""

    def __init__(self, send: SendJson, *, rng: random.Random | None = None) -> None:
        self._send = send
        self._rng = rng or random.Random()
        self._clips: list[dict[str, str]] = []

    def update(self, msg: dict[str, Any]) -> None:
        """Catálogo nuevo (mensaje ``animations`` de Unity)."""
        self._clips = p.parse_animations(msg)

    def clips_for(self, move: str) -> list[str]:
        """Clips del catálogo que hacen ``move`` (vacío si no lo tiene la app)."""
        spec = MOVES.get(move)
        if spec is None:
            return []
        return [
            item["clip"]
            for item in self._clips
            if item["group"] in spec.groups or item["clip"] in spec.clips
        ]

    def available(self) -> list[str]:
        """Movimientos que la app puede hacer ahora mismo."""
        return [name for name in MOVES if self.clips_for(name)]

    async def play(self, move: str) -> str | None:
        """Lanza un clip al azar de ``move`` y devuelve su nombre (``None`` si no hay)."""
        clips = self.clips_for(move)
        if not clips:
            return None
        clip = self._rng.choice(clips)
        await self._send(p.msg_play_animation(clip, whole=True))
        return clip


async def play_animation(ctx: ActionContext, arguments: dict[str, Any]) -> ActionResult:
    """Hace el movimiento que pidió el visitante."""
    catalog = ctx.extra.get("moves")
    if not isinstance(catalog, MoveCatalog):
        return ActionResult(text=NO_MOVES)
    move = arguments["movimiento"]
    clip = await catalog.play(move)
    if clip is None:
        available = catalog.available()
        if not available:
            return ActionResult(text=NO_MOVES)
        return ActionResult(
            text=(
                f"Ese movimiento ({move}) no lo tienes. Puedes hacer: "
                f"{', '.join(available)}. Ofrécele otro con gracia."
            )
        )
    logger.info("Movimiento por voz: %s -> %s", move, clip)
    return ActionResult(
        text=f"Hecho: Sonia está haciendo «{move}» en pantalla. Que lo acompañe con una frase corta."
    )


PLAY_ANIMATION = ActionSpec(
    name="play_animation",
    description=(
        "Haz un movimiento con tu avatar en la pantalla. Úsala cuando el visitante te pida "
        "que bailes, saludes o hagas un gesto."
    ),
    parameters={
        "type": "object",
        "properties": {
            "movimiento": {
                "type": "string",
                "enum": list(MOVES),
                "description": "Qué hacer: "
                + "; ".join(f"{name}: {move.description}" for name, move in MOVES.items())
                + ".",
            }
        },
        "required": ["movimiento"],
    },
    handler=play_animation,
)
