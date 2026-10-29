"""Trivia actions: ``start_trivia``, ``trivia_answer``, ``trivia_next``, ``restart_trivia`` and ``stop_trivia``.

The realtime model delegates them: when the user wants to play ("shall we play
the trivia?"), when they pick an option (however they say it: the realtime model
understands what was chosen and passes the letter), when they want a new game
from scratch and when they want to stop playing. They go through the same
:class:`sonia.trivia.TriviaGame` as the panel buttons, so the game is the same
whoever starts it. The engine leaves the game in ``ctx.extra["trivia"]``.

The result of ``start_trivia``, ``trivia_answer`` and ``trivia_next`` is Sonnia's
script (the current question, or the verdict with its explanation): it is marked
with :data:`SCRIPT_PREFIX` so the backend passes it on whole. The next question
only comes with ``trivia_next``, when the user asks for it.
"""

from __future__ import annotations

from typing import Any

from sonia.trivia import LEVELS, PASS, TriviaGame
from sonia.types import ActionContext, ActionResult, ActionSpec

NO_TRIVIA = "The trivia is not available right now."

#: Mark of the script the backend must pass on to Sonnia whole (``BACKEND_PROMPT``).
SCRIPT_PREFIX = "FOR SONIA:"

#: Option letter -> index (``dont_know`` counts as wrong and the right one is told).
ANSWER_CHOICES = {"A": 0, "B": 1, "C": 2, "dont_know": PASS}

_NO_ARGS: dict[str, Any] = {"type": "object", "properties": {}, "required": []}

#: Level of ``start_trivia`` when the user has not chosen one: ``TRIVIA_DEFAULT_LEVEL``.
#: With an optional level, the backend picked "easy" even if nobody had said so.
NO_LEVEL = "not_chosen"

_START_ARGS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "level": {
            "type": "string",
            "enum": [NO_LEVEL, *LEVELS],
            "description": f"Level the user chose, or {NO_LEVEL} if they have not said one.",
        },
    },
    "required": ["level"],
}

_LEVEL_ARGS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "level": {
            "type": "string",
            "enum": list(LEVELS),
            "description": "Level the user chose. If they did not choose one, leave it out.",
        }
    },
    "required": [],
}


def _game(ctx: ActionContext) -> TriviaGame | None:
    game = ctx.extra.get("trivia")
    return game if isinstance(game, TriviaGame) else None


async def start_trivia(ctx: ActionContext, arguments: dict[str, Any]) -> ActionResult:
    """Starts a trivia game on the screen, with the first question.

    The realtime model delegates it as soon as the user wants to play, without
    asking anything first: with the procedure in its own prompt it started playing
    on its own with made-up questions.
    """
    game = _game(ctx)
    if game is None:
        return ActionResult(text=NO_TRIVIA)
    if game.active:
        return ActionResult(text=f"{SCRIPT_PREFIX} {await game.resume()}")
    level = arguments.get("level")
    ok, script = await game.start("voice", None if level == NO_LEVEL else level)
    if not ok:
        return ActionResult(text=f"Could not start the trivia: {script}")
    return ActionResult(text=f"{SCRIPT_PREFIX} {script}")


async def restart_trivia(ctx: ActionContext, arguments: dict[str, Any]) -> ActionResult:
    """Starts a new game from scratch (cuts the running one)."""
    game = _game(ctx)
    if game is None:
        return ActionResult(text=NO_TRIVIA)
    ok, script = await game.restart("voice", arguments.get("level"))
    if not ok:
        return ActionResult(text=f"Could not restart the trivia: {script}")
    return ActionResult(text=f"{SCRIPT_PREFIX} {script}")


async def trivia_answer(ctx: ActionContext, arguments: dict[str, Any]) -> ActionResult:
    """Records the option the user chose and returns the result."""
    game = _game(ctx)
    if game is None:
        return ActionResult(text=NO_TRIVIA)
    ok, script = await game.answer(ANSWER_CHOICES[arguments["option"]], "voice")
    if not ok:
        return ActionResult(text=script)
    return ActionResult(text=f"{SCRIPT_PREFIX} {script}")


async def trivia_next(ctx: ActionContext, arguments: dict[str, Any]) -> ActionResult:
    """Puts up the next question when the user asks for it."""
    game = _game(ctx)
    if game is None:
        return ActionResult(text=NO_TRIVIA)
    ok, script = await game.next("voice")
    if not ok:
        return ActionResult(text=script)
    return ActionResult(text=f"{SCRIPT_PREFIX} {script}")


async def stop_trivia(ctx: ActionContext, arguments: dict[str, Any]) -> ActionResult:
    """Ends the running trivia game."""
    game = _game(ctx)
    if game is None:
        return ActionResult(text=NO_TRIVIA)
    ok, message = await game.stop("voice")
    if not ok:
        return ActionResult(text=message)
    return ActionResult(
        text="Trivia ended. Sonia says so in one short sentence and keeps talking normally."
    )


START_TRIVIA = ActionSpec(
    name="start_trivia",
    description=(
        "Starts a tech trivia game with three options per question on your screen and "
        "returns how to kick it off. Use it as soon as the user wants to play, even if you "
        "do not know their level yet."
    ),
    parameters=_START_ARGS,
    handler=start_trivia,
)

TRIVIA_ANSWER = ActionSpec(
    name="trivia_answer",
    description=(
        "Records in the trivia the letter the user chose and returns whether it is correct "
        'and how to explain it. Sonia tells you the letter ("the user answers B"); if she '
        "does not say it, do not guess it: reply that the letter is missing."
    ),
    parameters={
        "type": "object",
        "properties": {
            "option": {
                "type": "string",
                "enum": list(ANSWER_CHOICES),
                "description": "Letter of the chosen option (the one Sonia says), or dont_know.",
            }
        },
        "required": ["option"],
    },
    handler=trivia_answer,
)

TRIVIA_NEXT = ActionSpec(
    name="trivia_next",
    description=(
        "Puts the next trivia question on your screen and returns how to read it. Use it "
        'only when the user says they want the next one ("trivia: next question").'
    ),
    parameters=_NO_ARGS,
    handler=trivia_next,
)

RESTART_TRIVIA = ActionSpec(
    name="restart_trivia",
    description=(
        "Restarts the trivia: a new game from the first question, cutting the running one. "
        "Use it when the user wants to start over or play again."
    ),
    parameters=_LEVEL_ARGS,
    handler=restart_trivia,
)

STOP_TRIVIA = ActionSpec(
    name="stop_trivia",
    description="Ends the running trivia when the user does not want to keep playing.",
    parameters=_NO_ARGS,
    handler=stop_trivia,
)
