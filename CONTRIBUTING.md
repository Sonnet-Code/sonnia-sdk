# Contributing to Sonnia SDK

Thanks for your interest in Sonnia. Bug reports, documentation fixes, new actions, avatars and ideas are all welcome.

## Before you start

- Read the [README](README.md), the [roadmap](docs/roadmap.md) and the [WebSocket protocol](docs/protocol.md).
- For anything larger than a small fix, open an issue first so we can agree on the approach.
- Be kind: this project follows the [Code of Conduct](CODE_OF_CONDUCT.md).

## Development setup

### Orchestrator (Python)

You need Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
cd server
uv sync --group dev --all-extras
uv run --no-sync pytest -q
uv run --no-sync ruff check sonia tests
uv run --no-sync ruff format --check sonia tests
uv run --no-sync mypy sonia
```

The same checks run in CI on Linux, macOS and Windows. A pull request has to pass all of them.

### Unity client

Open `unity/` with Unity 6000.6.0f1 and set the Game view to 1080x1920 (portrait). See [`unity/README.md`](unity/README.md). The Genies Avatar SDK is optional and must never be committed.

## Ground rules

These keep the project usable as an unattended kiosk and safe to publish:

- **Tests never call real APIs.** No GPT-Live, no Responses backend, no vision model, no network. Use the fakes in `server/tests` (`httpx.MockTransport`, a fake realtime session, fake WebSocket servers, synthetic audio). Only the manual commands (`sonia check`, `sonia say`, `sonia chat`, `sonia run`) spend money.
- **Never block the asyncio loop.** Network, camera and disk calls go to a thread or are async: the microphone has to reach the model in real time.
- **No video to models.** Only single, downscaled snapshots, and only when they help.
- **Camera frames stay in memory.** Nothing is written to disk outside the explicit debug mode.
- **Speech to speech, one engine.** Do not add a cascaded VAD, ASR, LLM and TTS pipeline.
- **Configuration through environment variables** (documented in `.env.example`), never hardcoded paths, ports or keys.
- **Optional dependencies are imported lazily** inside functions, so the package imports without them.
- **Both sides of the protocol change together.** If a change touches a WebSocket message, update the orchestrator, the Unity client, `docs/protocol.md` and `docs/protocol.schema.json` in the same pull request. The test suite checks every message the orchestrator builds against the schema.
- **Portrait screen.** Anything visual is designed for 1080x1920 and checked with a capture at that size (menu **Sonnia > Vertical 9:16 Capture** in the editor).
- **Only redistributable assets.** Do not add models, animations, fonts, images or logos unless their license allows redistribution under this repository. Say where each new asset comes from in the pull request.
- **No secrets.** `.env` is ignored by git; never commit keys or tokens. CI scans the whole history with gitleaks.

## Adding an action

Actions are defined once in `server/sonia/actions`; the tools the voice model delegates to are generated from that registry. A new action needs its definition, its handler, tests and, if the avatar has to react, a protocol message with its Unity side, all in the same pull request.

## Style

- Code, comments, documentation and commit messages are in English.
- Python is formatted with `ruff format` and type-checked with `mypy` in strict mode.
- Commit messages are short and in the imperative mood ("Add the away mode to the panel"), with a body that explains why when it is not obvious.

## Reporting bugs

Open an issue with the template. Include your OS, Python and Unity versions, the relevant part of the orchestrator log and the steps to reproduce it. Never paste API keys.

## Security

Please do not report security problems in public issues. See [SECURITY.md](SECURITY.md).
