"""``check_agenda`` action: reads the event schedule again and tells what is on.

The instructions already carry today's talks (``AGENDA`` section) and silent
``[Agenda]`` notes arrive before each talk and when the schedule changes. This action
is for what may have changed since, for another day or for a talk by name: it reads
the source again and returns, worked out in code, what changed, what is on now and
next and the talks that match the question.
"""

from __future__ import annotations

from typing import Any

from sonia.agenda import AgendaBook, describe_changes
from sonia.types import ActionContext, ActionResult, ActionSpec

__all__ = ["CHECK_AGENDA", "NO_AGENDA"]

NO_AGENDA = "There is no agenda loaded: say you do not have the schedule."


async def check_agenda(ctx: ActionContext, arguments: dict[str, Any]) -> ActionResult:
    book = ctx.extra.get("agenda")
    if not isinstance(book, AgendaBook):
        return ActionResult(text=NO_AGENDA)
    changes = await book.refresh()
    parts = []
    if changes:
        parts.append("The agenda changed:\n" + describe_changes(changes, book.tz))
    elif changes is None and book.ready:
        parts.append("The agenda could not be read again; this is the last copy.")
    query = str(arguments.get("query") or "")[:120]
    parts.append(book.status(query=query))
    return ActionResult(text="\n".join(parts))


CHECK_AGENDA = ActionSpec(
    name="check_agenda",
    description=(
        "Read the event agenda again: the current time, what is on now and next, the "
        "latest changes and, with a query, the talks about a topic, a speaker or a room. "
        "Use it when the user asks about the schedule and the agenda you have may be out "
        "of date, is about another day, or does not say."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Optional: words to look for in titles, speakers, rooms and tags "
                    '("Rust", "Ada Lovelace", "Room 2"). Empty for what is on now and next.'
                ),
            },
        },
        "required": [],
    },
    handler=check_agenda,
)
