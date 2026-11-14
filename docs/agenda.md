# Event schedule

At an event, the question visitors ask most is "what's on next?". With an agenda, Sonnia knows the talks of the day, hears a few minutes before each one starts, learns about changes on her own and can read the schedule again when she is asked something it does not cover. All of it is optional: without `AGENDA_SOURCE` nothing changes.

## Try it

```bash
AGENDA_SOURCE=../assets/agenda/example.json TIMEZONE=America/New_York uv run sonia run
```

The example is a two-day event on November 20 and 21, 2026; ask her "what's on after the coffee break?" or "when does Ada speak?". A relative path is read from the folder you run `sonia` in (`server/` above).

## Where it comes from

`AGENDA_SOURCE` is a file path or an http(s) URL, in one of two formats:

- **iCalendar** (`.ics`), what most calendar and event tools export. Each `VEVENT` is a talk: `SUMMARY` is the title, `DTSTART` and `DTEND` the times, `LOCATION` the room, `DESCRIPTION`, `CATEGORIES` (tags) and `UID` (the id that tells changes apart). Speakers come from `X-SPEAKER` (several separated by commas) or from the `CN` of the `ORGANIZER`. All-day and cancelled events are left out. See [`assets/agenda/example.ics`](../assets/agenda/example.ics).
- **JSON**, a list of talks or `{"talks": [...]}`, as in [`assets/agenda/example.json`](../assets/agenda/example.json):

  ```json
  {"talks": [
    {"id": "rust-intro", "title": "Intro to Rust", "start": "2026-11-20T09:45", "end": "2026-11-20T10:30",
     "speakers": ["Ada Byron"], "room": "Room 2", "track": "Languages", "tags": ["rust"]}
  ]}
  ```

  Only `title` and `start` are required. Without `end`, a talk lasts 30 minutes. Without `id`, one is made from the title and the start, so renaming a talk then reads as one cancelled and one new.

Times without a zone are in `TIMEZONE` (the zone Sonnia uses for the date and time she knows); times with a zone (`Z`, `+02:00`, a `TZID`) are converted to it.

## What Sonnia gets

| When | What | How |
|---|---|---|
| Every new conversation | Today's talks, or those of the next day with talks, and the other days with talks | The `AGENDA` section of her instructions and of the backend's |
| `AGENDA_NOTICE_MINUTES` before a talk (10) | "Starting in 10 minutes: ..." | A silent `[Agenda]` note, once per talk |
| Every `AGENDA_REFRESH_MINUTES` (30) | What changed: moved, cancelled or new talks | A silent `[Agenda]` note, worked out in code |
| When she is asked something the section does not answer | The current time, what is on now and next, the latest changes and the talks that match a topic, a speaker or a room | The `check_agenda` action, delegated to the backend |
| When she is asked about one talk | Its card on the screen | The `show_talk` action, delegated to the backend |

Silent notes go through `session.thinking.append`: they never make her speak, and they only reach an open conversation, in a quiet moment between turns. The changes and the notices are worked out by the code, not by the model, so they do not depend on it comparing two lists correctly.

## The talk card

`show_talk` puts the card of one talk where images go: a badge (on now, up next, later or already over), the title, the speakers, the day and times, the room and track and up to four tags. The talk is picked in code from the words the model sends (a title, a speaker, a topic or an id): with several matches, the one on now wins, then the next to start, then the last one that ended, and the model is told the other matches. The card is written in `LANGUAGE`, with the day as the language file writes it (its `dates` block: "Friday 20 November", "viernes 20 de noviembre"), and reaches the avatar client in the `show_talk` message of the [protocol](protocol.md). Like an image, Sonnia points up while it comes in, `hide_image` removes it and it goes away on its own after `IMAGE_AUTO_HIDE_SECONDS`; it is not shown over the trivia.

## Without network

Every good read is saved to `AGENDA_CACHE_FILE` (`cache/agenda.json`). If the source cannot be read at startup, that copy is used; if a later refresh fails, the agenda in use stays. Point `AGENDA_SOURCE` at a local file to run with no network at all.

## Settings

| Setting | Default | What it does |
|---|---|---|
| `AGENDA_SOURCE` | empty | File or URL of the agenda; empty turns the feature off |
| `AGENDA_REFRESH_MINUTES` | 30 | How often it is read again (0: only at startup and with `check_agenda`) |
| `AGENDA_NOTICE_MINUTES` | 10 | Notice before each talk (0: none) |
| `AGENDA_CACHE_FILE` | `cache/agenda.json` | The saved copy |
| `AGENDA_TIMEOUT_SECONDS` | 10 | Wait for the source |

The full reference is in [configuration](configuration.md).

## In the code

- `server/sonia/agenda/sources.py` reads JSON and iCalendar; `model.py` has `Talk` and `Agenda` and how a talk is told; `book.py` (`AgendaBook`) keeps the agenda, refreshes it, compares it and writes the texts.
- `server/sonia/actions/agenda.py` is `check_agenda` and `show_talk`; `server/sonia/agenda/card.py` picks the talk and writes its card.
- `unity/Assets/Scripts/Sonia/TalkCardController.cs` draws the card on the HUD; `SoniaBootstrap` shares the top strip and the pointing gesture between it and the image panel.
- `server/sonia/live/engine.py` loads it at startup and runs the refresh and notice loop (`_agenda_loop`); `server/sonia/live/prompts.py` has the `AGENDA` section, the capabilities and the `{agenda_when}` rules.
- `server/tests/test_agenda.py` covers all of it offline; URLs go through `httpx.MockTransport`.
