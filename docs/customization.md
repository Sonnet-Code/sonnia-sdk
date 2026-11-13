# Customization guide

Sonnia ships as a generic assistant. This guide turns her into yours: what she knows, how she speaks, what she says while nobody is around, the trivia questions, the images she can show, her voice and the models behind her. Most of it is plain files and environment variables; only the persona lives in code. Every variable named here is in the [configuration reference](configuration.md).

## Where everything lives

| What | Where | Applied |
|---|---|---|
| Facts she knows | `assets/knowledge/*.md` | At the next session |
| Last-minute facts | "Today's notes" in the control panel | At once |
| Who she is and how she speaks | `SYSTEM_PROMPT` in `server/sonia/persona.py` | On restart |
| Any text the models receive, without touching code | Developer > Prompts in the control panel | At the next session (vision: the next photo) |
| Idle lines, chants and greetings | `assets/showcase/*.md` | On restart |
| Trivia questions | `assets/trivia/questions.md` | At the next game |
| Images she can show | `assets/gallery/` or "Add image" in the panel | Within seconds |
| Voice and models | `LIVE_VOICE`, `LIVE_MODEL`, `LIVE_BACKEND_MODEL`, `LLM_*` | On restart (the voice also from the panel) |
| The language she speaks and writes | `LANGUAGE` and `assets/languages/*.json` | On restart |

A new session opens after `IDLE_RESET_SECONDS` without anyone talking to her, or with "Restart conversation" in the panel.

`ASSETS_DIR` points the orchestrator at another assets folder with the same layout (`knowledge`, `showcase`, `trivia`, `gallery`). Keep your own copy outside the repository and you can pull updates without merge conflicts, or switch between several deployments by changing one variable.

## Knowledge base

Every `*.md` file in `assets/knowledge` except `README.md` is appended, in alphabetical order, to the instructions of the voice model and of the backend. It is the only source of facts she treats as verified: what is not there she does not claim, and she may search the web for it (`LIVE_BACKEND_WEB_SEARCH`).

- Write notes for the model, not a script: "The museum opens at 10 a.m.", "Lockers are next to the entrance".
- One topic per file, with a numeric prefix for the order: `10-venue.md`, `11-collection.md`, `12-faq.md`.
- Keep the whole folder under about 1500 words: it is sent on every turn.
- Mark what is not confirmed as "to be confirmed", so she says so instead of guessing.
- `KNOWLEDGE_EXTRA_DIR` adds a second folder, read after this one.

The two files that ship (`01-about-sonia.md`, `02-how-sonia-works.md`) describe Sonnia herself. Keep them if visitors may ask how she works; rewrite them if she should present herself differently.

## The prompt editor

The panel's Developer section has a Prompts editor with every long text the models receive: the persona, the knowledge base, the voice-model rules, the backend rules and the vision prompt. Pick one, edit it and save. The edit is checked first, stored in the panel state file on this machine (`PANEL_STATE_FILE`) and used from the next conversation, or from the next photo for the vision prompt, with no restart; "Start a new conversation" applies it at once. Sonnia then uses your version instead of the built-in text, never both, until "Use the built-in text" deletes it.

- **Placeholders.** The voice-model rules are a template: the code replaces `{capabilities}`, `{language}`, `{look_when}` and the others with rules that depend on the settings and the actions. An edit may drop a placeholder (that rule is then never added) but must keep `{capabilities}`, and cannot add one the code does not fill. Write a literal brace as `{{` or `}}`. The other texts are used as written, braces included.
- **The knowledge base** in the editor starts as the files of `assets/knowledge` one after another. A saved version replaces all of them, for the voice model and the backend, until it is reset; editing the files afterwards changes nothing while it is saved.
- **After an upgrade**, a saved version that no longer passes the check (a placeholder it needs was renamed) is ignored with a warning in the log, and the editor marks it so you can fix it.
- **To keep a change**, copy it into the code or the knowledge files: the panel state is per machine.

## Today's notes

The panel's "Today's notes" box (up to 1000 characters) reaches the open session at once and wins over the knowledge base when they clash. Use it for what changes during the day: a moved talk, a closed room, a sold-out item. The notes are saved and survive a restart.

## Persona

`SYSTEM_PROMPT` in `server/sonia/persona.py` (or "Persona" in the [prompt editor](#the-prompt-editor), to try changes without a restart) says who she is, how she speaks, how she uses the camera and the images, and what she tells about herself. `server/sonia/live/prompts.py` adds the rules of real-time voice, the delegation to the backend, the knowledge base and a description of her stack generated at startup, so the persona only needs to describe her.

Good changes to make there:

- Her job: "Your job is to welcome visitors to the museum and help them find their way."
- Her tone: more formal, more playful, how long her answers are.
- What she must never do: give medical advice, quote prices, promise discounts.
- What to do when she does not know: send people to the desk, to a phone number, to a website.

The texts sent to the models are covered by snapshot tests, so after editing the persona the suite shows the diff and fails. Review it and rewrite the snapshots on purpose, from `server/`:

```bash
SONIA_WRITE_SNAPSHOTS=1 uv run pytest -q tests/test_prompts_live.py tests/test_prompts_trivia.py
```

**Language.** She speaks English by default and switches to the visitor's language. To make another language the default, change the "Speak English by default" lines in `SYSTEM_PROMPT` and in `LIVE_RULES` (`server/sonia/live/prompts.py`), and translate the knowledge base, the showcase lines and the trivia bank. The screen texts of the avatar client are in English.

**Name.** Her name is written "Sonnia" but every text the voice model reads says "Sonia", so it is pronounced right, and `clean_transcript` in `server/sonia/live/engine.py` fixes the spelling in the subtitles (`WRITTEN_NAME`). To rename her, change the persona, the knowledge base and the showcase lines, those two places in `engine.py` and `invitationSpeaker` in `StageScreen.cs`.

## Idle lines, chants and greetings

While nobody talks to her, Sonnia says something every `SHOWCASE_INTERVAL_MIN_SECONDS` to `SHOWCASE_INTERVAL_MAX_SECONDS`, after `SHOWCASE_FIRST_DELAY_SECONDS` idle:

- `assets/showcase/lines.md`: short lines that invite people to come closer.
- `assets/showcase/chants.md`: what she "sings" while she dances (`SHOWCASE_DANCE_CHANCE`).
- `assets/showcase/greetings.md`: only for the panel's "Greeter" mode, where she greets passers-by without conversing.

One line per line; lines starting with `#` are comments. Each line is recorded once with her voice and replayed from `cache/voice` at no cost; when the voice changes, they are recorded again. "Prepare voices" in the panel records the missing ones ahead of time.

Besides the fixed lines, `SHOWCASE_MOMENT_CHANCE` of the bits are improvised invitations built from what is going on (and from the camera with `SHOWCASE_MOMENT_CAMERA`). Set it to 0 to keep her to your lines only, and `SHOWCASE_ENABLED=false` to keep her quiet.

## Trivia bank

`assets/trivia/questions.md` explains its own format at the top: a `## [easy]`, `[medium]` or `[hard]` heading with the question, three options with exactly one `- [x]`, and an optional `> ` fact she adds when she reveals the answer. Each level needs at least `TRIVIA_QUESTIONS` questions (5 by default). The file is read again at the start of every game, and a malformed question is skipped with a warning.

To check a bank before going live, from `server/`:

```bash
uv run python -c "from pathlib import Path; from sonia.trivia.bank import TriviaBank; print(TriviaBank.from_file(Path('../assets/trivia/questions.md')).levels())"
```

Questions about your venue or product work better than general knowledge. Every answer must be unambiguous: she states the correct option as a fact in front of people.

`TRIVIA_WIN_THRESHOLD` sets how many correct answers win, and `TRIVIA_WIN_CONTACT` who winners are sent to ("the people at the desk"). Sonnia never promises prizes on her own. `TRIVIA_ENABLED=false` removes the game.

## Gallery

Every PNG or JPEG directly in `assets/gallery` can be shown on her screen with the file name as its id: `floor-map.png` is `floor-map`. Name the files so the id says what is in them, because the model chooses by the id. The folder is checked every `GALLERY_WATCH_SECONDS` and changes reach the open session as a silent note. From the panel, "Add image" uploads to `GALLERY_UPLOAD_DIR` without touching the assets. The gallery's own [README](../assets/gallery/README.md) has the details.

Never put photos of visitors there.

## Voice and models

| Setting | What it changes |
|---|---|
| `LIVE_VOICE` | Her voice. The panel can change it at runtime (the session restarts and the recorded lines are recorded again). |
| `LIVE_MODEL` | The speech-to-speech model that listens and speaks. |
| `LIVE_BACKEND_MODEL` | The model that runs the actions and the web searches. `LIVE_BACKEND_REASONING_EFFORT` trades speed for care. |
| `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` | The vision model that describes the camera: any server with an OpenAI-compatible Chat Completions API and image input. For servers other than OpenAI, usually `LLM_MAX_TOKENS_PARAM=max_tokens`, `LLM_IMAGE_DETAIL=off` and `LLM_REASONING_EFFORT=off`. |
| `LIVE_BACKEND_WEB_SEARCH_COUNTRY`, `LIVE_BACKEND_WEB_SEARCH_CITY` | Where she is, for local search results. |
| `TIMEZONE` | The time zone of the date and time she knows. |

`uv run sonia check` tries every model with your settings before a long day.

## Language

`LANGUAGE` sets the language Sonnia speaks by default and the one she writes on the screen. It is the name of a file in [`assets/languages`](../assets/languages): `en` (the default), `es`, `fr`, `pt` or `de`. She still answers each visitor in the language they speak to her, and goes back to the default with the next person.

```bash
LANGUAGE=es uv run sonia run
```

- **The prompts are written once, in English.** The voice model is told "Speak Spanish by default" through the `{language}` placeholder of its rules, and the backend gets a "Default language" line, so the instructions never need translating. Models read English instructions and answer in the language they are asked to.
- **The screen texts are written once per language**, in the language file: the invitation bubble, the "you" label of the subtitles, the waiting pill, the away sign and the trivia card. The orchestrator sends them to the avatar client when it starts (the `screen_texts` message of the [protocol](protocol.md)), so changing them needs no rebuild.
- **Your content stays yours to translate**: the knowledge base, the persona, the idle lines, the trivia bank and the gallery captions are used as written. A knowledge base in English works with any `LANGUAGE`; idle lines and trivia questions are read out as they are, so write them in the language you choose.

To add a language, copy `en.json` to a file named with its code (for example `it.json`), set `"name"` to the language's name in English ("Italian", which is what the models are told), translate every text and keep each `{placeholder}`. Put it in `assets/languages`, or in a `languages` folder of your `ASSETS_DIR` to add or change one without touching the program. A missing text, or one with different placeholders, falls back to English with a warning in the log; an unknown `LANGUAGE` falls back to English entirely.

## Turning features off

| To remove | Set |
|---|---|
| The camera (and the `look` action) | `VISION_SOURCE=none` |
| Web search | `LIVE_BACKEND_WEB_SEARCH=false` |
| The trivia | `TRIVIA_ENABLED=false` |
| Talking on her own while idle | `SHOWCASE_ENABLED=false` |
| Improvised invitations only | `SHOWCASE_MOMENT_CHANCE=0` |
| Images closing on their own | `IMAGE_AUTO_HIDE_SECONDS=0` |

The instructions the models receive follow these settings: an action that is off is not offered, and she is not told she can do it.

## The avatar and the screen

- With the Genies Avatar SDK installed in the client, the panel's Developer section takes a Genies avatar definition (JSON) and swaps the character at runtime. Without the SDK, the client keeps its fallback character.
- The mouth, the camera framing and the idle motion are tuned from the same Developer section, without rebuilding.
- The invitation bubble shown while nobody talks ("Come closer and ask me anything!") and the other screen texts come from the [language file](#language); `invitation` in `StageScreen.cs` overrides it for one build.
- The "Away" sign is written in the panel; until it is changed, it is the one of the language file.

## Example: a museum guide

`assets/knowledge/10-museum.md`:

```markdown
# The museum

- The City Museum is open Tuesday to Sunday, 10 a.m. to 6 p.m. Closed on Mondays.
- Entry is free on the first Sunday of every month. Otherwise tickets are sold at the main desk.
- Lockers are next to the entrance. Large bags are not allowed in the galleries.
- Ground floor: the history of the city. First floor: modern art. Second floor: temporary exhibition, to be confirmed.
- Guided tours start at the main desk at 11 a.m. and 4 p.m.
- Photos without flash are allowed everywhere except the temporary exhibition.
```

In `SYSTEM_PROMPT`, replace the job paragraph:

```text
Your job is to welcome visitors to the City Museum, tell them what they can see and help them find their way. Speak like a friendly guide: curious, warm, never academic. If someone asks about a work or a date you do not have, say so and send them to the main desk.
```

Add `floor-map.png` and `opening-hours.png` to the gallery, idle lines such as "Lost? Ask me where anything is.", and a trivia bank about the collection and the city.

## Example: a shop assistant

`assets/knowledge/10-shop.md`:

```markdown
# The shop

- Open every day from 9 a.m. to 9 p.m.
- Returns: within 30 days with the receipt, at the counter by the exit.
- Fitting rooms are at the back, on the left.
- Today's offers are in Today's notes. Never quote a price that is not written there.
- Gift wrapping is free at the counter.
```

In `SYSTEM_PROMPT`:

```text
Your job is to welcome customers, help them find what they are looking for and answer questions about the shop. Be brief and helpful. Never quote prices, stock or discounts that are not in your knowledge base or today's notes; for anything else, send people to the staff at the counter.
```

A typical note in the panel: "Today: 20% off all jackets. The north entrance is closed for cleaning until 2 p.m." Turn off what does not fit the place, for example `TRIVIA_ENABLED=false` and `SHOWCASE_DANCE_CHANCE=0`, and keep the camera only if there is a reason to look.

## Trying your changes

- `uv run sonia demo` reads `ASSETS_DIR` too: your idle lines, the trivia bank and a gallery image appear on the avatar without a key.
- `uv run pytest -q` checks the prompts (see the snapshots above) and everything else offline.
- `uv run sonia run`, with the panel open, is the real test: ask her what visitors will ask.
