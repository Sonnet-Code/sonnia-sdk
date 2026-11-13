"""The event schedule: talks from a JSON or iCalendar file or URL (``AGENDA_SOURCE``).

See ``docs/agenda.md``. :class:`AgendaBook` loads and refreshes it, works out what
changed and what is about to start, and writes it out for the models; the
``check_agenda`` action (:mod:`sonia.actions.agenda`) reads it again on demand.
"""

from sonia.agenda.book import AgendaBook, AgendaChanges, describe_changes
from sonia.agenda.model import Agenda, Talk, describe_talk
from sonia.agenda.sources import AgendaFormatError, parse_agenda, parse_ics, parse_json

__all__ = [
    "Agenda",
    "AgendaBook",
    "AgendaChanges",
    "AgendaFormatError",
    "Talk",
    "describe_changes",
    "describe_talk",
    "parse_agenda",
    "parse_ics",
    "parse_json",
]
