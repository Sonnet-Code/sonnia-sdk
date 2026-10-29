# sonia (orchestrator)

Python package of the Sonnia orchestrator: it glues together the microphone, the OpenAI GPT-Live speech-to-speech model (`sonia/live`), the camera, the actions, the local control panel and the Unity avatar client. See the repository README for the overview and `docs/protocol.md` for the contract with the avatar client.

```bash
uv sync --extra audio --extra camera --extra panel   # full experience (add --group dev for tests and lint)
uv run sonia check       # microphone, camera, GPT-Live, vision model and gallery
uv run sonia chat        # type to GPT-Live from the console (--speak to hear it)
uv run sonia say "Hello" # hear the GPT-Live voice (--out to save a WAV)
uv run sonia run         # start everything (--no-mic: typed text only)
uv run pytest -q         # no hardware, no network, no real APIs
```

`check`, `chat`, `say` and `run` use the OpenAI API and cost money; the tests never do. Settings come from environment variables or `.env` at the repository root (see `.env.example`). The local control panel listens on `http://127.0.0.1:8780` while `sonia run` is running.

Lint and type checks:

```bash
uv run --no-sync ruff check sonia tests && uv run --no-sync ruff format --check sonia tests
uv run --no-sync mypy sonia
```
