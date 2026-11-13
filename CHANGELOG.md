# Changelog

All notable changes to Sonnia SDK are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow the releases in the [roadmap](docs/roadmap.md).

## [Unreleased]

### Added

- An event schedule (`docs/agenda.md`): talks from a JSON or iCalendar file or URL (`AGENDA_SOURCE`), today's talks in the instructions, a silent `[Agenda]` note before each talk and when the schedule changes, worked out in code, a saved copy for when the source cannot be read, and the `check_agenda` action. Example agendas in `assets/agenda`.
- A `LANGUAGE` setting: the language Sonnia speaks by default and writes on the screen, with English, Spanish, French, Portuguese and German in `assets/languages`. The prompts stay in English and are told the default language; the screen texts (the invitation, the subtitle label, the waiting pill, the away sign and the trivia card) are written once per language and reach the avatar client in the new sticky `screen_texts` message. A language can be added with a JSON file, without code.
- A prompt editor in the control panel (Developer > Prompts): the persona, the knowledge base, the voice-model rules, the backend rules and the vision prompt, checked before saving, stored in the panel state file and used from the next conversation without a restart.
- `docs/actions.md`: how an action runs and how to write one, from the tool definition and handler to the prompts, the protocol message, the Unity side and the tests, with a checklist.
- `show_emotion`, the worked example of that guide: joy, sadness or surprise on the avatar's face, with its `show_emotion` protocol message and Unity handler. Off unless `SHOW_EMOTION_ENABLED=true`; `sonia demo` shows it after its web search.
- `docs/customization.md`: the knowledge base, today's notes, the persona, idle lines, the trivia bank, the gallery, voice and models, and turning features off, with examples for a museum guide and a shop assistant. A new test checks that the guides only name real settings and link to files that exist.
- `docs/setup.md`: installing on macOS and Windows, trying the offline demo, devices and permissions, portrait screens, running all day and troubleshooting.
- `docs/protocol.schema.json`: a JSON Schema for every WebSocket message. The test suite validates every message the orchestrator builds or sends against it, and checks that the document's examples and the Unity client's message names agree with it.
- `sonia demo`: an offline, scripted show for the avatar client with a synthetic speech-like voice, subtitles, states, the waiting indicator, an image and a trivia round. No API key, no network, no cost.
- Continuous integration: lint, format check, type check and the test suite on Linux, macOS and Windows, and a gitleaks scan of the whole history.
- A public roadmap in `docs/roadmap.md`.
- `docs/architecture.md`: processes, asyncio tasks and threads, the life of a turn, delegation, and how the orchestrator survives a whole day.
- `docs/configuration.md`, a reference of every setting generated from the settings model, with tests that keep it, the field descriptions and `.env.example` in sync.
- Contributor guide, security policy, code of conduct, issue and pull request templates, `.editorconfig` and this changelog.

### Fixed

- The test suite runs on Windows: long parametrized test ids no longer overflow the environment variable pytest sets.

## [0.1.0] - 2026-10-29

First public release.

### Added

- Python orchestrator: realtime speech-to-speech engine over a raw WebSocket, delegated actions (`look`, `show_image`, `hide_image`, `play_animation`), on-demand camera snapshots described by a vision model, local control panel, idle lines and trivia mode.
- Unity client: default avatar from the Genies Avatar Starter Pack with optional Genies Avatar SDK support, phoneme lip-sync, procedural eyes, blinking and breathing, Playables-based animation, vertical 9:16 stage, image panel, subtitles and trivia screen.
- WebSocket protocol between both, documented in `docs/protocol.md`.
- MIT license, README, `.env.example` and a sample knowledge base.
