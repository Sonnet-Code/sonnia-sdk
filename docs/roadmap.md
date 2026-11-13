# Roadmap

Sonnia SDK grows in small, self-contained releases. Every step below keeps the offline test suite green, adds no third-party assets that cannot be redistributed and never needs a paid API call to be verified.

Status legend: ✅ done · 🚧 in progress · ⏳ planned

## 0.1 · Public release ✅

- ✅ MIT license, architecture overview and the [WebSocket protocol](protocol.md)
- ✅ Python orchestrator: realtime voice engine, actions (`look`, `show_image`, `hide_image`, `play_animation`), camera snapshots, local control panel, idle lines, trivia mode
- ✅ Unity client: avatar, lip-sync, animation, vertical stage, image panel, subtitles, trivia screen, optional Genies integration
- ✅ `.env.example` and a sample knowledge base

## 0.2 · A project people can contribute to ✅

1. ✅ **Continuous integration.** GitHub Actions running `ruff`, `ruff format --check`, `mypy` and `pytest` on Linux, macOS and Windows, plus a secret scan. No network access to model APIs.
2. ✅ **Contributor files.** `CONTRIBUTING.md`, `SECURITY.md`, code of conduct, issue and pull request templates, `.editorconfig` and a changelog.
3. ✅ **Configuration reference.** `docs/configuration.md` generated from the settings model, with a test that fails when a setting is added without being documented.
4. ✅ **Architecture guide.** `docs/architecture.md`: processes, threads and asyncio tasks, the life of an utterance, session renewal, degradation paths and where each concern lives in the code.

## 0.3 · Run it without an API key ✅

5. ✅ **Offline demo orchestrator.** `sonia demo`: drives the Unity client with synthetic speech-like audio, scripted subtitles, state changes, images and a trivia round, so the avatar can be tried, developed and screenshotted with no account and no cost.
6. ✅ **Protocol schema and contract tests.** A JSON Schema for every message in `docs/protocol.md`, validated against what the orchestrator actually sends in the test suite.
7. ✅ **Setup guide.** `docs/setup.md`: step-by-step install on macOS and Windows, devices, portrait screens, kiosk tips and troubleshooting.

## 0.4 · Make her yours 🚧

8. ✅ **Customization guide.** `docs/customization.md`: persona, knowledge base, idle lines, trivia bank, gallery, voice and models, with examples for a museum guide and a shop assistant.
9. ✅ **Writing actions.** `docs/actions.md` and a worked example action with its Unity side, showing the registry, handler, protocol message and tests.
10. ✅ **Prompt editor in the local panel.** Every text the models receive (persona, knowledge, voice-model rules, backend, vision) editable and validated from the panel, stored locally and applied without a restart.
11. ⏳ **Language setting.** One setting to choose the language Sonnia speaks and writes, with the prompts and screen texts written once and the answer language passed to the models.

## 0.5 · More to do at the stand

12. ⏳ **Event schedule.** A generic agenda module: load talks from a JSON or iCalendar file or URL, refresh it, tell the voice model what is on now and next, and the `check_agenda` and `show_talk` actions with their Unity card.
13. ⏳ **Games framework.** A `GameManager` with one game at a time, editable banks and panel controls, shipped with camera-free games: a word-guessing game and a "guess what I'm thinking" game.
14. ⏳ **Gesture director.** Optional: a light text model picks a gesture from the clips the Unity client announces while Sonnia speaks, with frequency rules applied in code.

## 0.6 · Ship it

15. ⏳ **Player build scripts.** Editor build entry points and shell scripts for macOS and Windows players, checked in batch mode, with the orchestrator started next to the player.
16. ⏳ **Away mode without sliding.** A proper exit for the default avatar when there is no walk cycle: a wave and a fade instead of sliding off screen.
17. ⏳ **Releases.** Tagged versions with a changelog entry and the orchestrator published as a wheel.

## Needs a human

These are known gaps that cannot be closed by the maintainers' automation alone:

- A full conversation against the real speech-to-speech model since the public release (it costs money and needs someone to talk to her).
- Testing on real kiosk hardware for a whole day.
