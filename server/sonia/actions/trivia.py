"""Acciones de la trivia: ``start_trivia``, ``trivia_answer``, ``trivia_next``, ``restart_trivia`` y ``stop_trivia``.

Las delega GPT-Live: cuando el visitante quiere jugar («¿jugamos a la
trivia?»), cuando elige una opción (la diga como la diga: GPT-Live entiende qué
ha elegido y pasa la letra), cuando quiere empezar otra desde cero y cuando
quiere dejar de jugar. Entran por el mismo
:class:`sonia.trivia.TriviaGame` que los botones del panel, así que la partida
es la misma la lance quien la lance. El motor deja la partida en
``ctx.extra["trivia"]``.

El resultado de ``start_trivia``, ``trivia_answer`` y ``trivia_next`` es el guion
para Sonia (la pregunta que toca, o el veredicto con su explicación): va marcado
con :data:`SCRIPT_PREFIX` para que el backend se lo pase entero. La siguiente
pregunta solo sale con ``trivia_next``, cuando el visitante la pide.
"""

from __future__ import annotations

from typing import Any

from sonia.trivia import LEVELS, PASS, TriviaGame
from sonia.types import ActionContext, ActionResult, ActionSpec

NO_TRIVIA = "La trivia no está disponible ahora mismo."

#: Marca del guion que el backend tiene que pasarle a Sonia entero (``BACKEND_PROMPT``).
SCRIPT_PREFIX = "PARA SONIA:"

#: Letra de la opción -> índice (``no_lo_sabe`` cuenta como fallo y se dice la buena).
ANSWER_CHOICES = {"A": 0, "B": 1, "C": 2, "no_lo_sabe": PASS}

_NO_ARGS: dict[str, Any] = {"type": "object", "properties": {}, "required": []}

#: Lo que le falta saber a Sonia antes de abrir la trivia (``start_trivia``).
FOLLOW_TEXT = (
    "Aún no empieza: para jugar hay que seguir a Sonnet Code en Instagram y LinkedIn "
    "(@sonnetcode). Pregúntale si ya las sigue; si no, que escanee el QR de la pantalla y las "
    "siga (no puedes comprobarlo: créele)."
)
LEVEL_TEXT = " Pregúntale también qué nivel quiere: fácil, intermedio o difícil."
ONLY_LEVEL_TEXT = "Aún no empieza: pregúntale qué nivel quiere: fácil, intermedio o difícil."
THEN_START_TEXT = (
    " Cuando te conteste, vuelve a delegar empezar la trivia con lo que te diga (si le da igual "
    "el nivel, intermedio). No digas ninguna pregunta todavía: salen del backend."
)

_START_ARGS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "nivel": {
            "type": "string",
            "enum": [],
            "description": "Nivel que eligió el visitante. Si no lo ha dicho, no lo pongas.",
        },
        "sigue_a_sonnet_code": {
            "type": "boolean",
            "description": (
                "true solo si el visitante ya ha dicho que sigue a Sonnet Code en Instagram y "
                "LinkedIn. Si no lo ha dicho, no lo pongas."
            ),
        },
    },
    "required": [],
}

_LEVEL_ARGS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "nivel": {
            "type": "string",
            "enum": list(LEVELS),
            "description": "Nivel que eligió el visitante. Si no eligió, no lo pongas.",
        }
    },
    "required": [],
}
_START_ARGS["properties"]["nivel"]["enum"] = list(LEVELS)


def _game(ctx: ActionContext) -> TriviaGame | None:
    game = ctx.extra.get("trivia")
    return game if isinstance(game, TriviaGame) else None


async def start_trivia(ctx: ActionContext, arguments: dict[str, Any]) -> ActionResult:
    """Empieza una partida de trivia en la pantalla, o dice qué falta preguntar antes.

    GPT-Live la delega en cuanto el visitante quiere jugar, sin preguntar nada
    antes: el requisito (seguir a Sonnet Code) y el nivel los pide este guion.
    Con el procedimiento en el prompt de GPT-Live, se ponía a jugar por su
    cuenta con preguntas inventadas (registro del 7 de octubre de 2026).
    """
    game = _game(ctx)
    if game is None:
        return ActionResult(text=NO_TRIVIA)
    level = arguments.get("nivel")
    if not game.active and arguments.get("sigue_a_sonnet_code") is not True:
        missing = FOLLOW_TEXT + ("" if level else LEVEL_TEXT)
        return ActionResult(text=f"{SCRIPT_PREFIX} {missing}{THEN_START_TEXT}")
    if not game.active and not level:
        return ActionResult(text=f"{SCRIPT_PREFIX} {ONLY_LEVEL_TEXT}{THEN_START_TEXT}")
    ok, script = await game.start("voice", level)
    if not ok:
        return ActionResult(text=f"No se pudo empezar la trivia: {script}")
    return ActionResult(text=f"{SCRIPT_PREFIX} {script}")


async def restart_trivia(ctx: ActionContext, arguments: dict[str, Any]) -> ActionResult:
    """Empieza una partida nueva desde cero (corta la que haya en marcha)."""
    game = _game(ctx)
    if game is None:
        return ActionResult(text=NO_TRIVIA)
    ok, script = await game.restart("voice", arguments.get("nivel"))
    if not ok:
        return ActionResult(text=f"No se pudo reiniciar la trivia: {script}")
    return ActionResult(text=f"{SCRIPT_PREFIX} Trivia nueva desde cero. {script}")


async def trivia_answer(ctx: ActionContext, arguments: dict[str, Any]) -> ActionResult:
    """Registra la opción que eligió el visitante y devuelve el resultado."""
    game = _game(ctx)
    if game is None:
        return ActionResult(text=NO_TRIVIA)
    ok, script = await game.answer(ANSWER_CHOICES[arguments["option"]], "voice")
    if not ok:
        return ActionResult(text=script)
    return ActionResult(text=f"{SCRIPT_PREFIX} {script}")


async def trivia_next(ctx: ActionContext, arguments: dict[str, Any]) -> ActionResult:
    """Pone la siguiente pregunta cuando el visitante la pide."""
    game = _game(ctx)
    if game is None:
        return ActionResult(text=NO_TRIVIA)
    ok, script = await game.next("voice")
    if not ok:
        return ActionResult(text=script)
    return ActionResult(text=f"{SCRIPT_PREFIX} {script}")


async def stop_trivia(ctx: ActionContext, arguments: dict[str, Any]) -> ActionResult:
    """Termina la partida de trivia en curso."""
    game = _game(ctx)
    if game is None:
        return ActionResult(text=NO_TRIVIA)
    ok, message = await game.stop("voice")
    if not ok:
        return ActionResult(text=message)
    return ActionResult(
        text="Trivia terminada. Sonia lo dice en una frase corta y sigue conversando con normalidad."
    )


START_TRIVIA = ActionSpec(
    name="start_trivia",
    description=(
        "Empieza una trivia de preguntas sobre el DevFest y la tecnología, con tres opciones "
        "en tu pantalla. Úsala en cuanto el visitante quiera jugar, aunque aún no sepas su "
        "nivel ni si sigue a Sonnet Code: si falta algo, devuelve qué preguntarle."
    ),
    parameters=_START_ARGS,
    handler=start_trivia,
)

TRIVIA_ANSWER = ActionSpec(
    name="trivia_answer",
    description=(
        "Registra en la trivia la letra que ha elegido el visitante y devuelve si acierta y "
        "cómo explicarlo. Sonia te dice la letra («el visitante responde B»); si no la dice, no "
        "la adivines: contesta que falta la letra."
    ),
    parameters={
        "type": "object",
        "properties": {
            "option": {
                "type": "string",
                "enum": list(ANSWER_CHOICES),
                "description": "Letra de la opción elegida (la que dice Sonia), o no_lo_sabe.",
            }
        },
        "required": ["option"],
    },
    handler=trivia_answer,
)

TRIVIA_NEXT = ActionSpec(
    name="trivia_next",
    description=(
        "Pone en la pantalla la siguiente pregunta de la trivia y devuelve cómo leerla. Úsala "
        "solo cuando el visitante diga que quiere la siguiente («trivia: siguiente pregunta»)."
    ),
    parameters=_NO_ARGS,
    handler=trivia_next,
)

RESTART_TRIVIA = ActionSpec(
    name="restart_trivia",
    description=(
        "Reinicia la trivia: empieza una partida nueva desde la primera pregunta, cortando la "
        "que haya en marcha. Úsala cuando el visitante quiera volver a empezar o jugar otra."
    ),
    parameters=_LEVEL_ARGS,
    handler=restart_trivia,
)

STOP_TRIVIA = ActionSpec(
    name="stop_trivia",
    description="Termina la trivia en curso cuando el visitante ya no quiere seguir jugando.",
    parameters=_NO_ARGS,
    handler=stop_trivia,
)
