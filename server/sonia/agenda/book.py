"""The agenda Sonnia knows: loaded from ``AGENDA_SOURCE``, refreshed, compared and told.

:class:`AgendaBook` keeps the last agenda that could be read. A refresh that fails keeps
the old one; with nothing read yet it falls back to the copy saved at the last good read
(``AGENDA_CACHE_FILE``), so a stand without network still knows the schedule. The code
works out what changed and what is about to start; the models only get it written out.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, tzinfo
from pathlib import Path

import httpx

from sonia.agenda.model import Agenda, Talk, describe_talk
from sonia.agenda.sources import AgendaFormatError, fetch_text, parse_agenda, parse_json
from sonia.clock import Clock, spoken_date, spoken_hour

__all__ = ["AgendaBook", "AgendaChanges", "describe_changes"]

logger = logging.getLogger(__name__)

#: Most talks listed in the instructions for one day.
SECTION_MAX_TALKS = 40


@dataclass(frozen=True, slots=True)
class AgendaChanges:
    """What a refresh changed."""

    added: tuple[Talk, ...] = ()
    removed: tuple[Talk, ...] = ()
    #: (before, after)
    moved: tuple[tuple[Talk, Talk], ...] = ()

    def __bool__(self) -> bool:
        return bool(self.added or self.removed or self.moved)


def _diff(before: Agenda, after: Agenda) -> AgendaChanges:
    old, new = before.by_id(), after.by_id()
    added = tuple(t for i, t in new.items() if i not in old)
    removed = tuple(t for i, t in old.items() if i not in new)
    moved = tuple(
        (old[i], t)
        for i, t in new.items()
        if i in old
        and (old[i].start, old[i].finish, old[i].room, old[i].title)
        != (t.start, t.finish, t.room, t.title)
    )
    return AgendaChanges(added, removed, moved)


def describe_changes(changes: AgendaChanges, tz: tzinfo) -> str:
    """The changes in a few lines, as Sonnia would tell them."""
    lines: list[str] = []
    for before, after in changes.moved:
        what: list[str] = []
        if before.start != after.start or before.finish != after.finish:
            what.append(
                f"now {after.start.astimezone(tz):%H:%M} to {after.finish.astimezone(tz):%H:%M}"
            )
        if before.room != after.room and after.room:
            what.append(f"now in {after.room}")
        if before.title != after.title:
            what.append(f'now called "{after.title}"')
        lines.append(f'- "{before.title}": ' + ("; ".join(what) or "details changed") + ".")
    lines += [f"- Cancelled: {describe_talk(t, tz, with_day=True)}." for t in changes.removed]
    lines += [f"- New: {describe_talk(t, tz, with_day=True)}." for t in changes.added]
    return "\n".join(lines)


@dataclass
class AgendaBook:
    """The agenda in use, its refreshes and the notices of what is about to start."""

    source: str
    tz: tzinfo
    clock: Clock
    cache_file: Path | None = None
    timeout: float = 10.0
    http: httpx.AsyncClient | None = None
    agenda: Agenda = field(default_factory=Agenda)
    #: When the agenda in use was read (``None``: never).
    loaded_at: datetime | None = None
    #: Talks already announced as about to start.
    _noticed: set[str] = field(default_factory=set)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def ready(self) -> bool:
        return self.loaded_at is not None

    async def start(self) -> None:
        """First read: the source or, if it fails, the saved copy. Never raises."""
        if await self.refresh() is not None:
            return
        cached = await asyncio.to_thread(self._read_cache)
        if cached is not None:
            self.agenda = cached
            self.loaded_at = self.clock()
            logger.warning(
                "Agenda: using the saved copy (%d talks) from %s", len(cached), self.cache_file
            )

    async def refresh(self) -> AgendaChanges | None:
        """Reads the source again. The changes, or ``None`` if it could not be read (the
        agenda in use stays). Never raises."""
        async with self._lock:
            try:
                text = await fetch_text(self.source, client=self.http, wait_s=self.timeout)
                agenda = parse_agenda(text, self.tz)
            except (OSError, httpx.HTTPError, AgendaFormatError, UnicodeError) as exc:
                logger.warning("Could not read the agenda from %s: %s", self.source, exc)
                return None
            first = self.loaded_at is None
            changes = AgendaChanges() if first else _diff(self.agenda, agenda)
            self.agenda = agenda
            self.loaded_at = self.clock()
            await asyncio.to_thread(self._write_cache, agenda)
        if first:
            logger.info("Agenda: %d talks from %s", len(agenda), self.source)
        elif changes:
            logger.info("Agenda changed:\n%s", describe_changes(changes, self.tz))
        return changes

    # -- for the models ------------------------------------------------------------------

    def section(self, moment: datetime | None = None) -> str:
        """The schedule of today (or of the next day with talks), for the instructions."""
        if not self.agenda.talks:
            return ""
        moment = (moment or self.clock()).astimezone(self.tz)
        days = [d for d in self.agenda.days(self.tz) if d >= moment.date()]
        if not days:
            return "There are no more talks on the agenda: the event is over."
        day = days[0]
        talks = self.agenda.on(day, self.tz)
        title = (
            "Today"
            if day == moment.date()
            else f"Next talks, on {spoken_date(talks[0].start.astimezone(self.tz))}"
        )
        lines = [f"{title}:"]
        for talk in talks[:SECTION_MAX_TALKS]:
            lines.append(f"- {describe_talk(talk, self.tz)}")
        if len(talks) > SECTION_MAX_TALKS:
            lines.append(f"- … and {len(talks) - SECTION_MAX_TALKS} more: delegate to check them.")
        later = [d for d in days[1:]]
        if later:
            lines.append(
                "The agenda also has talks on "
                + ", ".join(
                    spoken_date(datetime(d.year, d.month, d.day, tzinfo=self.tz)) for d in later
                )
                + ": delegate to check them."
            )
        return "\n".join(lines)

    def status(self, moment: datetime | None = None, *, query: str = "") -> str:
        """What is on now and next, and the talks that match ``query``: the result of
        ``check_agenda``."""
        if not self.ready:
            return "The agenda could not be read: say you cannot check it right now."
        moment = (moment or self.clock()).astimezone(self.tz)
        lines = [f"It is {moment:%H:%M} ({spoken_hour(moment)}), {spoken_date(moment)}."]
        if query.strip():
            found = self.agenda.find(query)
            if found:
                lines.append(f'Talks about "{query.strip()}":')
                lines += [f"- {describe_talk(t, self.tz, with_day=True)}" for t in found]
            else:
                lines.append(f'Nothing on the agenda matches "{query.strip()}".')
        now = self.agenda.now(moment)
        lines.append(
            "On now: " + "; ".join(describe_talk(t, self.tz) for t in now) + "."
            if now
            else "Nothing is on right now."
        )
        upcoming = self.agenda.upcoming(moment)
        if upcoming:
            same_day = all(t.start.astimezone(self.tz).date() == moment.date() for t in upcoming)
            lines.append(
                "Next: "
                + "; ".join(describe_talk(t, self.tz, with_day=not same_day) for t in upcoming)
                + "."
            )
        else:
            lines.append("There are no more talks on the agenda.")
        return "\n".join(lines)

    def notices(self, moment: datetime | None, minutes: float) -> list[str]:
        """The talks that start within ``minutes`` and were not announced yet, written out."""
        if minutes <= 0 or not self.agenda.talks:
            return []
        moment = moment or self.clock()
        horizon = moment + timedelta(minutes=minutes)
        due = [
            t
            for t in self.agenda.talks
            if moment <= t.start <= horizon and t.id not in self._noticed
        ]
        self._noticed.update(t.id for t in due)
        return [
            f"Starting in {max(1, round((t.start - moment).total_seconds() / 60))} minutes: "
            f"{describe_talk(t, self.tz)}."
            for t in due
        ]

    # -- the saved copy ------------------------------------------------------------------

    def _write_cache(self, agenda: Agenda) -> None:
        if self.cache_file is None:
            return
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            data = {"source": self.source, "talks": [t.to_json() for t in agenda.talks]}
            tmp = self.cache_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.cache_file)
        except OSError as exc:
            logger.warning("Could not save the agenda copy to %s: %s", self.cache_file, exc)

    def _read_cache(self) -> Agenda | None:
        if self.cache_file is None or not self.cache_file.is_file():
            return None
        try:
            return parse_json(self.cache_file.read_text(encoding="utf-8"), self.tz)
        except (OSError, AgendaFormatError) as exc:
            logger.warning("The saved agenda copy %s cannot be read: %s", self.cache_file, exc)
            return None
