# Sonnia's knowledge base

Every `*.md` file in this folder (except this `README.md`) is appended, in alphabetical order, to the session instructions of the voice model and of the backend agent. It is how you tell Sonnia what she knows without touching code.

## Rules

- Only verified facts. If something is not confirmed yet, write it as "to be confirmed" so she says so instead of making it up.
- Short, concrete sentences. Everything here counts as tokens on every turn, so keep the whole folder under roughly 1500 words.
- Numeric prefixes (`01-`, `02-`, `10-`...) control the order in which the files are added.
- The files are re-read whenever a new session opens: after `IDLE_RESET_SECONDS` without anyone talking to her, or with "Restart conversation" in the control panel. You can edit them while she is running and the next session picks up the changes.
- For last-minute facts that do not deserve a file (a room change, a lost badge, a closing time), use "Today's notes" in the control panel instead.

## Make it yours

The two files that ship here describe Sonnia herself: who she is (`01-about-sonia.md`) and how she works (`02-how-sonia-works.md`). To use her at your own kiosk, event, shop or museum, add files with what visitors will ask about, for example:

- `10-my-venue.md`: what the place is, opening hours, where things are.
- `11-my-event.md`: what is happening today and who is behind it.
- `12-faq.md`: the questions people ask most, with their answers.

Write them as notes for the model ("The museum opens at 10 a.m.", "Restrooms are next to the entrance"), not as a script to read aloud. You can also rewrite `01-about-sonia.md` to change her personality or what she says about herself.

`KNOWLEDGE_EXTRA_DIR` can point to an extra folder of `*.md` files that is read after this one. It is handy to keep your own facts outside the repository, or to switch between several events without editing these files.

## "Sonia" or "Sonnia"

Her name is written **Sonnia** (double n) on screen, but the speech model would mispronounce that spelling. So in every text the voice model reads or speaks (these knowledge files, and the idle lines, chants and greetings in `assets/showcase`) write it **Sonia**. The orchestrator rewrites "Sonia" to "Sonnia" in the subtitles automatically.
