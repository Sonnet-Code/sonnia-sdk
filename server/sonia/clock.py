"""The local date and time, in English and ready to be read out loud.

Sonnia may be somewhere else than the time zone of the computer that runs her:
the time always comes from ``TIMEZONE`` (an IANA name such as ``Europe/Madrid``),
or from the system when it is empty.

Windows does not ship the time zone database :mod:`zoneinfo` uses (install the
``tzdata`` package to get it); a zone that cannot be resolved falls back to the
system time with a warning.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone, tzinfo

__all__ = [
    "Clock",
    "clock_for",
    "place_of",
    "resolve_timezone",
    "spoken_date",
    "spoken_hour",
    "spoken_now",
    "spoken_time",
]

logger = logging.getLogger(__name__)

#: Returns the current time with a time zone (injectable in tests).
Clock = Callable[[], datetime]

#: Zones that can be resolved without the database.
_FIXED_OFFSETS = {
    "utc": timedelta(0),
    "etc/utc": timedelta(0),
}

_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def resolve_timezone(name: str) -> tzinfo:
    """The ``name`` zone (IANA, such as ``Europe/Madrid``). Never raises."""
    name = name.strip()
    if not name:
        return _system_timezone()
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 - misspelled zone or no database (Windows)
        offset = _FIXED_OFFSETS.get(name.lower())
        if offset is not None:
            return timezone(offset, name)
        logger.warning("Unknown time zone %r: using the system one", name)
        return _system_timezone()


def _system_timezone() -> tzinfo:
    return datetime.now().astimezone().tzinfo or UTC


def clock_for(tz: tzinfo) -> Clock:
    """A clock that gives the current time in ``tz``."""
    return lambda: datetime.now(tz)


def place_of(timezone_name: str) -> str:
    """The place of an IANA zone, to say it: ``America/New_York`` -> ``New York``."""
    tail = timezone_name.strip().rsplit("/", 1)[-1]
    return tail.replace("_", " ")


def spoken_date(moment: datetime) -> str:
    """``Wednesday, May 7, 2025``."""
    weekday = _WEEKDAYS[moment.weekday()]
    return f"{weekday}, {_MONTHS[moment.month - 1]} {moment.day}, {moment.year}"


def spoken_time(moment: datetime) -> str:
    """``19:05 (7:05 in the evening)``: the 24-hour time and how it is said."""
    return f"{moment.hour:02d}:{moment.minute:02d} ({spoken_hour(moment)})"


def spoken_hour(moment: datetime) -> str:
    """``7:05 in the evening``: the time as it is said."""
    hour = moment.hour
    twelve = hour % 12 or 12
    if hour < 6:
        part = "at night"
    elif hour < 12:
        part = "in the morning"
    elif hour == 12:
        part = "at noon"
    elif hour < 18:
        part = "in the afternoon"
    else:
        part = "in the evening"
    return f"{twelve}:{moment.minute:02d} {part}"


def spoken_now(moment: datetime, place: str = "") -> str:
    """``Wednesday, May 7, 2025, 19:05 (7:05 in the evening), New York time``."""
    text = f"{spoken_date(moment)}, {spoken_time(moment)}"
    return f"{text}, {place} time" if place else text
