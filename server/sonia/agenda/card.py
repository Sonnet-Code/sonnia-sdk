"""The card of one talk (``show_talk``): which talk a request means and what the card says.

The code picks the talk and writes the card in ``LANGUAGE``; the avatar client only lays it
out (``show_talk`` in ``docs/protocol.md``).
"""

from __future__ import annotations

from datetime import datetime, tzinfo
from typing import Any

from sonia.agenda.model import Agenda, Talk
from sonia.language import Language
from sonia.ws import protocol as p

__all__ = ["CARD_MAX_TAGS", "choose_talk", "talk_card", "talk_status"]

#: Most tags written on a card: more do not fit in one line.
CARD_MAX_TAGS = 4
#: Most other matches told back to the model.
_MAX_OTHERS = 4


def talk_status(agenda: Agenda, talk: Talk, moment: datetime) -> str:
    """``now``, ``next`` (the next to start), ``later`` or ``over``: the card's badge."""
    if talk.running_at(moment):
        return "now"
    if talk.finish <= moment:
        return "over"
    if talk in agenda.upcoming(moment, limit=1):
        return "next"
    return "later"


def choose_talk(agenda: Agenda, query: str, moment: datetime) -> tuple[Talk | None, list[Talk]]:
    """The talk ``query`` means (an id, or words of its title, speakers, room, track or tags)
    and the other matches. With several, the one on now wins, then the next to start, then
    the last one that ended."""
    query = query.strip()
    if not query:
        return None, []
    by_id = agenda.by_id().get(query)
    if by_id is not None:
        return by_id, []
    found = agenda.find(query, limit=len(agenda))
    if not found:
        return None, []
    running = [t for t in found if t.running_at(moment)]
    coming = [t for t in found if t.start > moment]
    chosen = running[0] if running else coming[0] if coming else found[-1]
    others = [t for t in found if t is not chosen][:_MAX_OTHERS]
    return chosen, others


def talk_card(
    agenda: Agenda, talk: Talk, tz: tzinfo, language: Language, moment: datetime
) -> dict[str, Any]:
    """The ``show_talk`` message for ``talk``, written in ``language``."""
    start = talk.start.astimezone(tz)
    finish = talk.finish.astimezone(tz)
    when = f"{language.date(start.date())} · {start:%H:%M}–{finish:%H:%M}"
    if finish.date() != start.date():
        when = f"{language.date(start.date())} {start:%H:%M} – {language.date(finish.date())} "
        when += f"{finish:%H:%M}"
    return p.msg_show_talk(
        talk.id,
        talk.title,
        status=talk_status(agenda, talk, moment),
        when=when,
        speakers=talk.speakers,
        place=" · ".join(part for part in (talk.room, talk.track) if part),
        tags=talk.tags[:CARD_MAX_TAGS],
    )
