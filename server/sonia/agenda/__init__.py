"""Agenda del DevFest en vivo: se lee de su web y el código detecta los cambios.

- :mod:`sonia.agenda.source`: saca las sesiones de la página de la agenda.
- :mod:`sonia.agenda.schedule`: los datos, el texto para Sonia, los cambios
  entre dos versiones y qué hay ahora.
- :mod:`sonia.agenda.book`: la agenda actual, su caché y la consulta periódica.

Ver docs/agenda.md.
"""

from __future__ import annotations

from sonia.agenda.book import AgendaBook, AgendaUpdate
from sonia.agenda.schedule import (
    Room,
    Schedule,
    Talk,
    diff_agenda,
    happening,
    render_agenda,
    starting_soon,
    today_now_and_next,
)
from sonia.agenda.source import AgendaError, parse_schedule_page, schedule_from_rows

__all__ = [
    "AgendaBook",
    "AgendaError",
    "AgendaUpdate",
    "Room",
    "Schedule",
    "Talk",
    "diff_agenda",
    "happening",
    "parse_schedule_page",
    "render_agenda",
    "schedule_from_rows",
    "starting_soon",
    "today_now_and_next",
]
