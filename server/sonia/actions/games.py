"""Acciones de los juegos: ``start_game``, ``stop_game`` y las jugadas de cada juego.

Las delega GPT-Live (``docs/juegos.md``):

- ``start_game(juego, sigue_a_sonnet_code)``: en cuanto el visitante quiere jugar.
  ``juego`` es un enum fijo con los juegos encendidos al arrancar (las herramientas del
  backend se fijan al abrir cada sesión) más :data:`~sonia.games.base.NOT_SAID` si no dijo
  a cuál. Lo que se puede jugar en ese momento (Unity, cámara, el panel, otra partida, la
  trivia) se comprueba al llamar, y si no se puede, el resultado propone los que sí. Si
  no ha dicho ya que sigue a Sonnet Code, el juego se prepara y el guion pide
  preguntárselo antes (como la trivia; ``GameManager``, «Seguir a Sonnet Code»).
- ``stop_game()``: termina el que haya.
- Las jugadas de cada juego (``wordle_guess``...), creadas con :func:`game_action`: el
  handler recibe la partida en marcha, si es la suya.

El motor deja el :class:`~sonia.games.manager.GameManager` en ``ctx.extra["games"]``.
Los guiones van marcados con :data:`~sonia.games.base.SCRIPT_PREFIX` para que el
backend se los pase enteros a Sonia.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Any

from sonia.games.base import NOT_SAID, SCRIPT_PREFIX, Game
from sonia.types import ActionContext, ActionResult, ActionSpec

if TYPE_CHECKING:
    from sonia.games.manager import GameManager

__all__ = [
    "NO_GAMES",
    "STOP_GAME",
    "StartGame",
    "build_start_game",
    "game_action",
    "game_actions",
    "start_game",
    "stop_game",
]

logger = logging.getLogger(__name__)

NO_GAMES = "Los juegos no están disponibles ahora mismo."

_NO_ARGS: dict[str, Any] = {"type": "object", "properties": {}, "required": []}

#: El parámetro ``sigue_a_sonnet_code`` de ``start_game``, igual que el de ``start_trivia``.
FOLLOW_ARG_TEXT = (
    "true solo si el visitante ya ha dicho que sigue a Sonnet Code en Instagram y LinkedIn. "
    "Si no lo ha dicho, no lo pongas."
)


def games_of(ctx: ActionContext) -> GameManager | None:
    """El manager de los juegos del contexto (``ctx.extra["games"]``), o ``None``."""
    from sonia.games.manager import GameManager

    manager = ctx.extra.get("games")
    return manager if isinstance(manager, GameManager) else None


async def start_game(ctx: ActionContext, arguments: dict[str, Any]) -> ActionResult:
    """Empieza un juego en la pantalla y devuelve cómo arrancarlo (sus reglas van aparte).

    Como la trivia, el juego empieza ya aunque no se sepa si sigue a Sonnet Code: el guion
    pide preguntarlo antes y la pantalla espera a que Sonia arranque. Con «aún no empieza,
    vuelve a delegar» GPT-Live no volvía a delegar si el visitante le contestaba mientras
    hablaba (pruebas de la trivia con la API real del 8 de octubre de 2026).
    """
    manager = games_of(ctx)
    if manager is None:
        return ActionResult(text=NO_GAMES)
    juego = arguments["juego"]
    if juego == NOT_SAID:
        return ActionResult(text=f"{SCRIPT_PREFIX} {manager.choose_text()}")
    ok, script = await manager.start(
        juego, "voice", ask_follow=arguments.get("sigue_a_sonnet_code") is not True
    )
    if not ok:
        return ActionResult(text=f"No se pudo empezar el juego: {script}")
    return ActionResult(text=f"{SCRIPT_PREFIX} {script}")


async def stop_game(ctx: ActionContext, arguments: dict[str, Any]) -> ActionResult:
    """Termina el juego en marcha."""
    manager = games_of(ctx)
    if manager is None:
        return ActionResult(text=NO_GAMES)
    ok, message = await manager.stop("voice")
    if not ok:
        return ActionResult(text=message)
    if manager.phase == "finishing":
        # El juego cerró él mismo enseñando su final (``Game.stop_requested``): el mensaje es
        # su guion para Sonia (la palabra del Wordle, por ejemplo).
        return ActionResult(text=f"{SCRIPT_PREFIX} {message}")
    return ActionResult(
        text="Juego terminado. Sonia lo dice en una frase corta y sigue conversando con normalidad."
    )


class StartGame:
    """El handler de ``start_game``: sabe qué juegos lleva su enum.

    Así la línea de juegos de las instrucciones (``live/prompts.py``) sale de la misma
    acción que ve el backend, con el nombre de cada juego para GPT-Live.
    """

    def __init__(self, games: Sequence[type[Game]]) -> None:
        self.games: tuple[type[Game], ...] = tuple(games)

    async def __call__(self, ctx: ActionContext, arguments: dict[str, Any]) -> ActionResult:
        return await start_game(ctx, arguments)


def build_start_game(games: Sequence[type[Game]]) -> ActionSpec:
    """``start_game`` con el enum de los juegos encendidos al arrancar."""
    listed = "; ".join(f"{g.id} ({g.spoken})" for g in games)
    return ActionSpec(
        name="start_game",
        description=(
            "Empieza en tu pantalla uno de los juegos del stand y devuelve cómo arrancarlo; sus "
            "reglas le llegan a Sonia aparte. Úsala en cuanto el visitante quiera jugar a uno, "
            f"sin preguntarle nada antes. Juegos: {listed}. Si no dijo a cuál, {NOT_SAID}."
        ),
        parameters={
            "type": "object",
            "properties": {
                "juego": {
                    "type": "string",
                    "enum": [NOT_SAID, *(g.id for g in games)],
                    "description": f"El juego que quiere el visitante, o {NOT_SAID} si no lo dijo.",
                },
                "sigue_a_sonnet_code": {
                    "type": "boolean",
                    "description": FOLLOW_ARG_TEXT,
                },
            },
            "required": ["juego"],
        },
        handler=StartGame(games),
    )


STOP_GAME = ActionSpec(
    name="stop_game",
    description=(
        "Termina el juego que esté en marcha en tu pantalla cuando el visitante ya no quiere "
        "seguir jugando."
    ),
    parameters=_NO_ARGS,
    handler=stop_game,
)


def game_action[G: Game](
    game_cls: type[G],
    *,
    name: str,
    description: str,
    parameters: dict[str, Any],
    play: Callable[[G, dict[str, Any]], Awaitable[str]],
) -> ActionSpec:
    """Una jugada delegada de ``game_cls`` (para :meth:`sonia.games.base.Game.actions`).

    ``play(partida, argumentos)`` recibe la partida en marcha (solo si es de ``game_cls``
    y aún se juega) y los argumentos ya validados contra ``parameters``, y devuelve el
    guion para Sonia (sale con :data:`SCRIPT_PREFIX`). Si la jugada no toca, lanza
    :class:`~sonia.games.base.GameError` con lo que Sonia tiene que saber. Nunca llega
    una jugada a un juego que no está en pantalla: el manager contesta por él.

    Esquema estricto: todos los parámetros en ``required`` y en cada enum un valor de
    :data:`~sonia.games.base.NOT_SAID_VALUES` («no lo dijo»).
    """

    async def handler(ctx: ActionContext, arguments: dict[str, Any]) -> ActionResult:
        manager = games_of(ctx)
        if manager is None:
            return ActionResult(text=NO_GAMES)
        return await manager.play(game_cls, play, arguments)

    return ActionSpec(name=name, description=description, parameters=parameters, handler=handler)


def game_actions(games: Sequence[type[Game]]) -> list[ActionSpec]:
    """``start_game``, ``stop_game`` y las jugadas de ``games`` (vacío si no hay juegos).

    Un juego cuyas jugadas no se pueden crear (``actions()`` lanza) se queda fuera, también
    del enum de ``start_game``: un juego roto no tumba el arranque ni se ofrece.
    """
    usable: list[type[Game]] = []
    plays: list[ActionSpec] = []
    for game in games:
        try:
            specs = list(game.actions())
        except Exception:  # noqa: BLE001 - un juego roto no tumba el arranque
            logger.exception("Las jugadas de %s no se pudieron crear: se deja fuera", game.id)
            continue
        usable.append(game)
        plays.extend(specs)
    if not usable:
        return []
    return [build_start_game(usable), STOP_GAME, *plays]
