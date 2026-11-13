"""The event schedule (``sonia.agenda``, ``check_agenda``): reading JSON and iCalendar,
what changed, what is about to start and what the models are told. No network: URLs go
through ``httpx.MockTransport``."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

import sonia.live.engine as engine_module
from sonia import cli
from sonia.actions import build_default_registry
from sonia.actions.agenda import NO_AGENDA
from sonia.agenda import (
    Agenda,
    AgendaBook,
    AgendaFormatError,
    describe_changes,
    describe_talk,
    parse_agenda,
    parse_ics,
    parse_json,
)
from sonia.config import AgendaSettings
from sonia.live.prompts import build_backend_instructions, build_live_instructions
from sonia.paths import BUNDLE_ROOT
from sonia.types import ActionContext
from tests.test_live import make_rig, make_settings

TZ = timezone(timedelta(hours=-4), "event")
EXAMPLES = BUNDLE_ROOT / "assets" / "agenda"


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=TZ)


class FixedClock:
    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment


def _book(source: Path | str, moment: datetime, cache: Path | None = None) -> AgendaBook:
    return AgendaBook(source=str(source), tz=TZ, clock=FixedClock(moment), cache_file=cache)


def _write(path: Path, talks: list[dict[str, object]]) -> Path:
    path.write_text(json.dumps({"talks": talks}), encoding="utf-8")
    return path


# -- reading -------------------------------------------------------------------


def test_the_json_example() -> None:
    agenda = parse_json((EXAMPLES / "example.json").read_text(encoding="utf-8"), TZ)
    assert len(agenda) == 6
    rust = agenda.by_id()["rust-intro"]
    assert rust.start == at(20, 9, 45) and rust.end == at(20, 10, 30)
    assert rust.speakers == ("Ada Byron",) and rust.room == "Room 2"
    assert describe_talk(agenda.by_id()["voice-agents"], TZ) == (
        '"Building voice agents" by Lin Chen and Sam Ortiz, 09:45 to 10:30 '
        "(9:45 in the morning), Main hall, AI track"
    )


def test_the_ics_example_matches_the_json_one() -> None:
    ics = parse_agenda((EXAMPLES / "example.ics").read_text(encoding="utf-8"), TZ)
    json_agenda = parse_json((EXAMPLES / "example.json").read_text(encoding="utf-8"), TZ)
    # Sorted by start, then title; the all-day event is left out.
    assert [t.id for t in ics.talks] == ["welcome", "voice-agents", "rust-intro"]
    for talk in ics.talks:
        same = json_agenda.by_id()[talk.id]
        assert (talk.title, talk.start, talk.end, talk.room) == (
            same.title,
            same.start,
            same.end,
            same.room,
        )
    assert ics.by_id()["voice-agents"].speakers == ("Lin Chen", "Sam Ortiz")
    assert (
        ics.by_id()["rust-intro"].description == "A first look at ownership, borrowing and cargo."
    )
    assert ics.by_id()["rust-intro"].tags == ("rust", "systems")


def test_ics_zones_folding_organizers_and_cancelled_events() -> None:
    text = "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "BEGIN:VEVENT",
            "SUMMARY:A very long title that the export",
            "  folded in two",
            "DTSTART:20261120T140000Z",
            'ORGANIZER;CN="Grace Park":mailto:grace@example.com',
            "END:VEVENT",
            "BEGIN:VEVENT",
            "SUMMARY:Gone",
            "STATUS:CANCELLED",
            "DTSTART:20261120T150000Z",
            "END:VEVENT",
            "BEGIN:VEVENT",
            "SUMMARY:Elsewhere",
            "DTSTART;TZID=UTC:20261120T160000",
            "END:VEVENT",
            "END:VCALENDAR",
        ]
    )
    agenda = parse_ics(text, TZ)
    first, second = agenda.talks
    assert first.title == "A very long title that the export folded in two"
    assert first.start == datetime(2026, 11, 20, 14, tzinfo=UTC) and first.end is None
    assert first.finish == first.start + timedelta(minutes=30)
    assert first.speakers == ("Grace Park",)
    assert second.title == "Elsewhere" and second.start.utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("not an agenda", "not JSON"),
        ('{"talks": {}}', "list of talks"),
        ('[{"start": "2026-11-20T09:00"}]', "title"),
        ('[{"title": "X", "start": "tomorrow"}]', "ISO"),
        ('[{"title": "X"}]', "start"),
    ],
)
def test_a_bad_json_agenda_is_explained(text: str, problem: str) -> None:
    with pytest.raises(AgendaFormatError, match=problem):
        parse_agenda(text, TZ)


def test_now_next_and_search() -> None:
    agenda = parse_json((EXAMPLES / "example.json").read_text(encoding="utf-8"), TZ)
    assert [t.id for t in agenda.now(at(20, 10))] == ["voice-agents", "rust-intro"]
    # The two talks at 9:45 count as one start, then the break.
    assert [t.id for t in agenda.upcoming(at(20, 9, 10), limit=2)] == [
        "voice-agents",
        "rust-intro",
        "coffee",
    ]
    assert [t.id for t in agenda.find("ada")] == ["rust-intro", "keynote-day2"]
    assert [t.id for t in agenda.find("room 2 testing")] == ["testing"]
    assert agenda.find("  ") == []
    assert Agenda.of([]).upcoming(at(20, 9)) == []


# -- the book ------------------------------------------------------------------


async def test_the_book_reads_tells_and_notices(tmp_path: Path) -> None:
    book = _book(EXAMPLES / "example.json", at(20, 9, 40))
    await book.start()
    assert book.ready and len(book.agenda) == 6

    section = book.section()
    assert section.startswith("Today:\n- ")
    assert "Intro to Rust" in section and "Closing keynote" not in section
    assert "also has talks on Saturday, November 21, 2026" in section

    status = book.status(query="rust")
    assert status.startswith("It is 09:40 (9:40 in the morning), Friday, November 20, 2026.")
    assert 'Talks about "rust":' in status
    assert "Nothing is on right now." in status  # the welcome ended at 9:30
    assert "Next: " in status and "Building voice agents" in status
    book.clock = FixedClock(at(20, 9, 10))
    assert 'On now: "Welcome and opening"' in book.status()

    notices = book.notices(at(20, 9, 40), 10)
    assert notices == [
        'Starting in 5 minutes: "Building voice agents" by Lin Chen and Sam Ortiz, '
        "09:45 to 10:30 (9:45 in the morning), Main hall, AI track.",
        'Starting in 5 minutes: "Intro to Rust" by Ada Byron, 09:45 to 10:30 '
        "(9:45 in the morning), Room 2, Languages track.",
    ]
    assert book.notices(at(20, 9, 42), 10) == []  # once per talk
    assert book.notices(at(20, 9, 42), 0) == []


async def test_the_section_on_other_days(tmp_path: Path) -> None:
    book = _book(EXAMPLES / "example.json", at(19, 18))
    await book.start()
    assert book.section().startswith("Next talks, on Friday, November 20, 2026:")
    book.clock = FixedClock(at(22, 9))
    assert book.section() == "There are no more talks on the agenda: the event is over."
    assert "There are no more talks on the agenda." in book.status()


async def test_a_refresh_tells_what_changed_and_a_failure_keeps_the_agenda(
    tmp_path: Path,
) -> None:
    source = _write(
        tmp_path / "agenda.json",
        [
            {"id": "a", "title": "Rust", "start": "2026-11-20T10:00", "room": "Room 1"},
            {"id": "b", "title": "Go", "start": "2026-11-20T11:00"},
        ],
    )
    book = _book(source, at(20, 9))
    await book.start()
    _write(
        source,
        [
            {"id": "a", "title": "Rust", "start": "2026-11-20T10:30", "room": "Room 3"},
            {"id": "c", "title": "Zig", "start": "2026-11-20T12:00"},
        ],
    )
    changes = await book.refresh()
    assert changes is not None
    assert [t.id for t in changes.added] == ["c"]
    assert [t.id for t in changes.removed] == ["b"]
    assert [after.id for _, after in changes.moved] == ["a"]
    text = describe_changes(changes, TZ)
    assert '- "Rust": now 10:30 to 11:00; now in Room 3.' in text
    assert '- Cancelled: "Go"' in text and '- New: "Zig"' in text

    assert await book.refresh() == changes.__class__()  # nothing new: no changes
    source.write_text("broken", encoding="utf-8")
    assert await book.refresh() is None
    assert [t.id for t in book.agenda.talks] == ["a", "c"]


async def test_without_the_source_the_saved_copy_is_used(tmp_path: Path) -> None:
    cache = tmp_path / "cache" / "agenda.json"
    await _book(EXAMPLES / "example.json", at(20, 9), cache).start()
    assert cache.is_file()

    offline = _book(tmp_path / "missing.json", at(20, 9), cache)
    await offline.start()
    assert offline.ready and len(offline.agenda) == 6

    nothing = _book(tmp_path / "missing.json", at(20, 9))
    await nothing.start()
    assert not nothing.ready and nothing.section() == ""
    assert "could not be read" in nothing.status()


async def test_an_agenda_from_a_url() -> None:
    body = (EXAMPLES / "example.ics").read_bytes()
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path.endswith("missing.ics"):
            return httpx.Response(404)
        return httpx.Response(200, content=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        book = AgendaBook(
            source="https://events.example/agenda.ics",
            tz=TZ,
            clock=FixedClock(at(20, 9)),
            http=http,
        )
        await book.start()
        assert len(book.agenda) == 3
        book.source = "https://events.example/missing.ics"
        assert await book.refresh() is None
    assert seen == ["https://events.example/agenda.ics", "https://events.example/missing.ics"]


# -- the action and the prompts ------------------------------------------------


async def test_check_agenda(tmp_path: Path) -> None:
    registry = build_default_registry(include_agenda=True)
    ctx = ActionContext(camera=None, avatar=None, gallery_dir=str(tmp_path))
    assert (await registry.execute("check_agenda", {}, ctx)).text == NO_AGENDA

    source = _write(
        tmp_path / "a.json", [{"id": "a", "title": "Rust", "start": "2026-11-20T10:00"}]
    )
    book = _book(source, at(20, 9, 55))
    await book.start()
    ctx.extra["agenda"] = book
    _write(source, [{"id": "a", "title": "Rust", "start": "2026-11-20T10:15"}])
    text = (await registry.execute("check_agenda", {"query": "rust"}, ctx)).text
    assert text.startswith('The agenda changed:\n- "Rust": now 10:15 to 10:45.')
    assert 'Talks about "rust":' in text and "Next: " in text


def test_it_is_only_offered_with_an_agenda(tmp_path: Path) -> None:
    assert "check_agenda" not in build_default_registry()
    settings = make_settings(tmp_path)
    with_agenda = build_default_registry(include_look=False, include_agenda=True)
    live = build_live_instructions(
        settings, registry=with_agenda, gallery_ids=[], agenda="Today:\n- Rust at 10"
    )
    assert "- Agenda: read the event schedule again" in live
    assert "You are asked about the schedule and the AGENDA section does not answer it" in live
    assert "AGENDA (the event schedule" in live and "Today:\n- Rust at 10" in live
    without = build_live_instructions(
        settings, registry=build_default_registry(include_look=False), gallery_ids=[]
    )
    assert "AGENDA" not in without and "check_agenda" not in without
    backend = build_backend_instructions(gallery_ids=[], agenda="Today:\n- Rust at 10")
    assert "AGENDA (when the conversation started; check_agenda reads it again):" in backend


@pytest.mark.parametrize("source", ["", "agenda.json"])
async def test_the_setting_decides_the_components(tmp_path: Path, source: str) -> None:
    settings = make_settings(tmp_path)
    settings.agenda = AgendaSettings(
        source=str(tmp_path / source) if source else "", cache_file=str(tmp_path / "c.json")
    )
    components = cli.build_components(settings, with_camera=False)
    try:
        assert ("check_agenda" in components.registry) is bool(source)
        assert (components.agenda is not None) is bool(source)
    finally:
        await components.close()


# -- the engine ----------------------------------------------------------------


async def test_the_session_knows_the_agenda_and_hears_what_is_about_to_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine_module, "AGENDA_TICK_S", 0.05)
    clock = FixedClock(at(20, 9, 30))
    book = AgendaBook(source=str(EXAMPLES / "example.json"), tz=TZ, clock=clock)
    async with make_rig(
        tmp_path,
        agenda=book,
        clock=clock,
        agenda_settings=AgendaSettings(notice_minutes=0),
    ) as rig:
        conn = await rig.conn()
        session = conn.start["session"]
        assert "AGENDA (the event schedule" in session["instructions"]
        assert '"Intro to Rust" by Ada Byron' in session["instructions"]
        assert "Intro to Rust" in session["delegation"]["responses"]["instructions"]
        tools = session["delegation"]["responses"]["tools"]
        assert "check_agenda" in [t.get("name") for t in tools]

        rig.settings.agenda = AgendaSettings(notice_minutes=20)
        await conn.wait_type("session.thinking.append")
        note = conn.of_type("session.thinking.append")[0]["content"]
        assert note.startswith('[Agenda] Starting in 15 minutes: "Building voice agents"')
        assert '"Intro to Rust"' in note
        assert conn.of_type("session.commentary.append") == []
