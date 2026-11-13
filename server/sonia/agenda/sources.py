"""Reading an agenda: JSON or iCalendar, from a file or a URL.

The JSON format (``docs/agenda.md``) is a list of talks, or ``{"talks": [...]}``:

    {"talks": [{"title": "Intro to Rust", "start": "2026-11-20T10:00",
                "end": "2026-11-20T10:45", "speakers": ["Ada"], "room": "Room 2"}]}

Times without a zone are in ``TIMEZONE``. iCalendar (``.ics``, what most calendar and
event tools export) is read with its ``VEVENT``\\s: ``SUMMARY``, ``DTSTART``, ``DTEND``,
``LOCATION``, ``DESCRIPTION``, ``CATEGORIES``, ``UID`` and the speakers from
``X-SPEAKER`` or the ``ORGANIZER``'s ``CN``. All-day events are left out: they are not
talks.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import UTC, datetime, tzinfo
from pathlib import Path
from typing import Any

import httpx

from sonia.agenda.model import Agenda, Talk, talk_id
from sonia.clock import resolve_timezone

__all__ = [
    "AgendaFormatError",
    "fetch_text",
    "is_url",
    "parse_agenda",
    "parse_ics",
    "parse_json",
]

logger = logging.getLogger(__name__)

#: Most bytes read from a source: an agenda is small; this stops a wrong URL.
MAX_BYTES = 2_000_000


class AgendaFormatError(ValueError):
    """A source that is neither an agenda JSON nor an iCalendar."""


def is_url(source: str) -> bool:
    return source.strip().lower().startswith(("http://", "https://"))


def _read_file(source: str) -> str:
    data = Path(source).expanduser().read_bytes()
    return data[:MAX_BYTES].decode("utf-8-sig", errors="replace")


async def fetch_text(
    source: str, *, client: httpx.AsyncClient | None = None, wait_s: float = 10.0
) -> str:
    """The text of a file or an http(s) URL, waiting at most ``wait_s`` for a URL.
    Raises ``OSError`` or ``httpx.HTTPError``."""
    source = source.strip()
    if not is_url(source):
        return await asyncio.to_thread(_read_file, source)
    own = client is None
    http = client or httpx.AsyncClient(timeout=wait_s, follow_redirects=True)
    try:
        response = await http.get(source, timeout=wait_s)
        response.raise_for_status()
        return response.content[:MAX_BYTES].decode(response.encoding or "utf-8", errors="replace")
    finally:
        if own:
            await http.aclose()


def parse_agenda(text: str, tz: tzinfo) -> Agenda:
    """An agenda from JSON or iCalendar text, told apart by its content."""
    if text.lstrip("﻿ \r\n\t").upper().startswith("BEGIN:VCALENDAR"):
        return parse_ics(text, tz)
    return parse_json(text, tz)


# -- JSON --------------------------------------------------------------------


def _when(value: Any, tz: tzinfo, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise AgendaFormatError(f'"{field}" must be a date and time such as "2026-11-20T10:00"')
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise AgendaFormatError(f'"{field}": {value!r} is not an ISO date and time') from exc
    return moment.replace(tzinfo=tz) if moment.tzinfo is None else moment


def _strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def parse_json(text: str, tz: tzinfo) -> Agenda:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise AgendaFormatError(f"not JSON nor iCalendar ({exc})") from exc
    items = data.get("talks") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise AgendaFormatError('expected a list of talks or {"talks": [...]}')
    talks: list[Talk] = []
    for number, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise AgendaFormatError(f"talk {number}: expected an object")
        title = _text(item.get("title"))
        if not title:
            raise AgendaFormatError(f'talk {number}: "title" is missing')
        start = _when(item.get("start"), tz, "start")
        end = _when(item["end"], tz, "end") if item.get("end") else None
        if end is not None and end <= start:
            end = None
        talks.append(
            Talk(
                id=_text(item.get("id")) or talk_id(title, start),
                title=title,
                start=start,
                end=end,
                speakers=_strings(item.get("speakers") or item.get("speaker")),
                room=_text(item.get("room") or item.get("location")),
                track=_text(item.get("track")),
                description=_text(item.get("description")),
                tags=_strings(item.get("tags")),
            )
        )
    return Agenda.of(talks)


# -- iCalendar ---------------------------------------------------------------

_ICS_TIME = re.compile(r"^(\d{8})(?:T(\d{4})(\d{2})?)?(Z)?$")


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif raw:
            lines.append(raw)
    return lines


def _unescape(value: str) -> str:
    out: list[str] = []
    chars = iter(value)
    for char in chars:
        if char == "\\":
            following = next(chars, "")
            out.append("\n" if following in ("n", "N") else following)
        else:
            out.append(char)
    return "".join(out).strip()


def _split_property(line: str) -> tuple[str, dict[str, str], str]:
    head, _, value = line.partition(":")
    name, *raw_params = head.split(";")
    params: dict[str, str] = {}
    for param in raw_params:
        key, _, val = param.partition("=")
        params[key.upper()] = val.strip('"')
    return name.upper(), params, value


def _ics_time(value: str, params: dict[str, str], tz: tzinfo) -> datetime | None:
    """A DTSTART or DTEND; ``None`` for a date without a time (all day)."""
    match = _ICS_TIME.match(value.strip())
    if match is None:
        raise AgendaFormatError(f"{value!r} is not an iCalendar date")
    day, hhmm, seconds, utc = match.groups()
    if hhmm is None or params.get("VALUE", "").upper() == "DATE":
        return None
    moment = datetime.strptime(day + hhmm + (seconds or "00"), "%Y%m%d%H%M%S")
    if utc:
        return moment.replace(tzinfo=UTC)
    zone = resolve_timezone(params["TZID"]) if params.get("TZID") else tz
    return moment.replace(tzinfo=zone)


def parse_ics(text: str, tz: tzinfo) -> Agenda:
    talks: list[Talk] = []
    event: dict[str, tuple[dict[str, str], str]] | None = None
    for line in _unfold(text):
        name, params, value = _split_property(line)
        if name == "BEGIN" and value.upper() == "VEVENT":
            event = {}
        elif name == "END" and value.upper() == "VEVENT":
            if event is not None:
                talk = _ics_talk(event, tz)
                if talk is not None:
                    talks.append(talk)
            event = None
        elif event is not None and name not in event:
            event[name] = (params, value)
    return Agenda.of(talks)


def _ics_talk(event: dict[str, tuple[dict[str, str], str]], tz: tzinfo) -> Talk | None:
    title = _unescape(event.get("SUMMARY", ({}, ""))[1])
    if not title or "DTSTART" not in event:
        return None
    if event.get("STATUS", ({}, ""))[1].strip().upper() == "CANCELLED":
        return None
    start = _ics_time(event["DTSTART"][1], event["DTSTART"][0], tz)
    if start is None:
        return None  # all day: not a talk
    end = _ics_time(event["DTEND"][1], event["DTEND"][0], tz) if "DTEND" in event else None
    if end is not None and end <= start:
        end = None
    speakers = _strings(_unescape(event.get("X-SPEAKER", ({}, ""))[1]))
    if not speakers and "ORGANIZER" in event:
        name = event["ORGANIZER"][0].get("CN", "").strip()
        speakers = (name,) if name else ()
    return Talk(
        id=_unescape(event.get("UID", ({}, ""))[1]) or talk_id(title, start),
        title=title,
        start=start,
        end=end,
        speakers=speakers,
        room=_unescape(event.get("LOCATION", ({}, ""))[1]),
        description=_unescape(event.get("DESCRIPTION", ({}, ""))[1]),
        tags=_strings(_unescape(event.get("CATEGORIES", ({}, ""))[1])),
    )
