"""Talks and the agenda that holds them, with what Sonnia needs to read out loud.

Every time is timezone-aware (``TIMEZONE``): the sources turn naive times into that zone
before a :class:`Talk` is built.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, tzinfo

from sonia.clock import spoken_date, spoken_hour

__all__ = [
    "DEFAULT_TALK_MINUTES",
    "Agenda",
    "Talk",
    "describe_talk",
    "talk_id",
]

#: Length assumed for a talk without an end time.
DEFAULT_TALK_MINUTES = 30


def talk_id(title: str, start: datetime) -> str:
    """A stable id for a talk without one: its title and start, as a slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48] or "talk"
    return f"{start.strftime('%Y%m%dT%H%M')}-{slug}"


@dataclass(frozen=True, slots=True)
class Talk:
    """One item of the agenda: a talk, a workshop, a break."""

    id: str
    title: str
    #: Timezone-aware.
    start: datetime
    #: Timezone-aware, or ``None`` (then :data:`DEFAULT_TALK_MINUTES` is assumed).
    end: datetime | None = None
    speakers: tuple[str, ...] = ()
    room: str = ""
    track: str = ""
    description: str = ""
    tags: tuple[str, ...] = ()

    @property
    def finish(self) -> datetime:
        return self.end or self.start + timedelta(minutes=DEFAULT_TALK_MINUTES)

    def running_at(self, moment: datetime) -> bool:
        return self.start <= moment < self.finish

    def matches(self, query: str) -> bool:
        """Every word of ``query`` is in its title, speakers, room, track or tags."""
        haystack = " ".join(
            [self.title, self.room, self.track, *self.speakers, *self.tags]
        ).casefold()
        return all(word in haystack for word in query.casefold().split())

    def to_json(self) -> dict[str, object]:
        """The agenda JSON format (``docs/agenda.md``), so a copy can be read back."""
        out: dict[str, object] = {
            "id": self.id,
            "title": self.title,
            "start": self.start.isoformat(),
        }
        if self.end is not None:
            out["end"] = self.end.isoformat()
        for key, value in (
            ("speakers", list(self.speakers)),
            ("room", self.room),
            ("track", self.track),
            ("description", self.description),
            ("tags", list(self.tags)),
        ):
            if value:
                out[key] = value
        return out


def _joined(names: Sequence[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + f" and {names[-1]}"


def describe_talk(talk: Talk, tz: tzinfo, *, with_day: bool = False) -> str:
    """``"Intro to Rust" by Ada and Lin, 10:00 to 10:45 (10:00 in the morning), Room 2``."""
    start = talk.start.astimezone(tz)
    finish = talk.finish.astimezone(tz)
    parts = [f'"{talk.title}"']
    if talk.speakers:
        parts[0] += f" by {_joined(talk.speakers)}"
    when = f"{start:%H:%M} to {finish:%H:%M} ({spoken_hour(start)})"
    if with_day:
        when = f"{spoken_date(start)}, {when}"
    parts.append(when)
    if talk.room:
        parts.append(talk.room)
    if talk.track:
        parts.append(f"{talk.track} track")
    return ", ".join(parts)


@dataclass(frozen=True, slots=True)
class Agenda:
    """The talks, sorted by start."""

    talks: tuple[Talk, ...] = field(default_factory=tuple)

    @classmethod
    def of(cls, talks: Iterable[Talk]) -> Agenda:
        unique: dict[str, Talk] = {}
        for talk in talks:
            unique[talk.id] = talk
        return cls(tuple(sorted(unique.values(), key=lambda t: (t.start, t.title))))

    def __len__(self) -> int:
        return len(self.talks)

    def by_id(self) -> dict[str, Talk]:
        return {talk.id: talk for talk in self.talks}

    def days(self, tz: tzinfo) -> list[date]:
        return sorted({talk.start.astimezone(tz).date() for talk in self.talks})

    def on(self, day: date, tz: tzinfo) -> list[Talk]:
        return [t for t in self.talks if t.start.astimezone(tz).date() == day]

    def now(self, moment: datetime) -> list[Talk]:
        return [t for t in self.talks if t.running_at(moment)]

    def upcoming(self, moment: datetime, limit: int = 3) -> list[Talk]:
        """The next talks to start (all those that start together count as one)."""
        later = [t for t in self.talks if t.start > moment]
        if not later:
            return []
        starts = sorted({t.start for t in later})[:limit]
        return [t for t in later if t.start in starts]

    def find(self, query: str, limit: int = 5) -> list[Talk]:
        query = query.strip()
        if not query:
            return []
        return [t for t in self.talks if t.matches(query)][:limit]
