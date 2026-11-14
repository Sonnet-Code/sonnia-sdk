"""``check_agenda`` and ``show_talk``: the event schedule, read again or shown on screen.

The instructions already carry today's talks (``AGENDA`` section) and silent
``[Agenda]`` notes arrive before each talk and when the schedule changes. This action
is for what may have changed since, for another day or for a talk by name: it reads
the source again and returns, worked out in code, what changed, what is on now and
next and the talks that match the question. ``show_talk`` puts the card of one talk where
images go (:mod:`sonia.agenda.card`).
"""

from __future__ import annotations

from typing import Any

from sonia.actions.builtin import NO_AVATAR, screen_busy
from sonia.agenda import AgendaBook, describe_changes, describe_talk
from sonia.agenda.card import choose_talk, talk_card
from sonia.language import DEFAULT_LANGUAGE, Language, load_language
from sonia.types import ActionContext, ActionResult, ActionSpec

__all__ = ["CHECK_AGENDA", "NO_AGENDA", "SHOW_TALK"]

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


async def show_talk(ctx: ActionContext, arguments: dict[str, Any]) -> ActionResult:
    book = ctx.extra.get("agenda")
    if not isinstance(book, AgendaBook):
        return ActionResult(text=NO_AGENDA)
    if ctx.avatar is None:
        return ActionResult(text=NO_AVATAR)
    busy = screen_busy(ctx, "the talk card")
    if busy:
        return ActionResult(text=busy)
    if not book.ready:
        return ActionResult(text="The agenda could not be read: say you cannot show it right now.")
    query = str(arguments.get("talk") or "")[:120].strip()
    moment = book.clock().astimezone(book.tz)
    talk, others = choose_talk(book.agenda, query, moment)
    if talk is None:
        return ActionResult(
            text=f'Nothing on the agenda matches "{query}": nothing is shown. '
            "Check the agenda or ask which talk they mean."
        )
    language = ctx.extra.get("language")
    if not isinstance(language, Language):
        language = load_language(DEFAULT_LANGUAGE)
    await ctx.avatar.show_talk(talk_card(book.agenda, talk, book.tz, language, moment))
    text = f"Showing the card of {describe_talk(talk, book.tz, with_day=True)}."
    if others:
        text += " Other talks also match: " + "; ".join(
            describe_talk(t, book.tz, with_day=True) for t in others
        )
        text += "."
    return ActionResult(text=text)


SHOW_TALK = ActionSpec(
    name="show_talk",
    description=(
        "Show on your screen the card of one talk of the agenda: its title, speakers, day, "
        "time and room. Use it when someone asks about a specific talk, where or when it is."
    ),
    parameters={
        "type": "object",
        "properties": {
            "talk": {
                "type": "string",
                "description": (
                    "Words of the talk's title, a speaker or a topic "
                    '("Rust", "Ada Lovelace"). With several matches, the one on now or the '
                    "next to start is shown."
                ),
            },
        },
        "required": ["talk"],
    },
    handler=show_talk,
)
