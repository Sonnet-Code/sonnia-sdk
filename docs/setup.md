# Setup guide

This guide takes a machine from nothing to Sonnia running on a portrait screen, on macOS or Windows. It assumes one computer runs both halves: the orchestrator (Python) and the avatar client (Unity). For what each half does, see the [architecture guide](architecture.md); every setting named here is in the [configuration reference](configuration.md).

## What you need

- **A computer** with macOS or Windows 10/11. The orchestrator is light; the avatar client wants a GPU that runs Unity's URP comfortably at 1080x1920.
- **A microphone.** A USB or desk microphone pointed at the person in front of the screen works better than a laptop's built-in one in a noisy room.
- **A camera** (optional). Any USB webcam. Without one, set `VISION_SOURCE=none` and the `look` action is simply not offered.
- **A monitor in portrait**, 9:16 (1080x1920). A landscape monitor works for development; the framing is designed for portrait.
- **Speakers.**
- **Internet and an OpenAI API key** for real conversations. Not needed for the offline demo.
- **Unity 6000.6.0f1** to open the client or build it into an app.

## 1. Install the orchestrator

The orchestrator is managed with [uv](https://docs.astral.sh/uv/), which also downloads the right Python (3.12 or 3.13) for you.

**macOS** (Terminal):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh     # or: brew install uv
git clone <this repository> sonnia-sdk
cd sonnia-sdk/server
uv sync --extra audio --extra camera --extra panel
```

**Windows** (PowerShell, with [Git for Windows](https://git-scm.com/download/win) installed):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
git clone <this repository> sonnia-sdk
cd sonnia-sdk\server
uv sync --extra audio --extra camera --extra panel
```

The extras are optional pieces: `audio` (microphone and speaker), `camera` (USB camera through OpenCV) and `panel` (the local control panel). Leave out the ones you do not need. Add `--group dev` to run the tests and the linters.

## 2. Try it offline first

Without a key, without network and without cost:

```bash
uv run sonia demo
```

Then open the client (step 4) and press Play. The demo drives the avatar with a synthetic voice, subtitles, the waiting indicator, an image, a dance and a trivia round, and answers typed text with a canned line. `--volume 0` keeps it silent, `--once` plays the show once and exits. If the avatar moves and its mouth follows the voice, the client and the WebSocket are working.

## 3. Add your key and check the machine

```bash
cp ../.env.example ../.env        # Windows: copy ..\.env.example ..\.env
```

Open `.env` and set `OPENAI_API_KEY`. Never commit this file. Then:

```bash
uv run sonia check
```

It checks the microphone, the camera, the realtime model (it opens and closes a short session, so it costs a fraction of a cent), the vision model and the gallery, one line each: `OK`, `WARN` (Sonnia runs with less) or `FAIL` (fix it first). When everything is `OK`:

```bash
uv run sonia run
```

`uv run sonia run --no-mic` starts without a microphone: type to her from the client's development controls instead.

## 4. The avatar client

Open `unity/` with Unity 6000.6.0f1 and let it resolve the packages (uLipSync comes from its git repository). Set the Game view to 1080x1920 and press Play. The client connects to `ws://127.0.0.1:8765` and keeps reconnecting on its own, so the order in which you start the two halves does not matter.

To build an app, use Unity's Build Profiles for macOS or Windows; **Sonnia > Configure 9:16 Build** sets the player resolution. The orchestrator is not packaged inside the app: run it next to it.

Command-line options of the client (the editor or a built app):

| Option | What it does |
|---|---|
| `-sonia-ws ws://127.0.0.1:<port>` | Connect to another address; match it with `WS_PORT`. |
| `-dev-ui` | Show the development controls: connection and state labels, a text box to type to Sonnia, an "Interrupt" button, F1 (HUD) and F2 (tuning panel). |
| `-quality high\|medium\|low\|custom` | Start with that graphics preset instead of the saved one. |
| `-capture-dir <folder> [-capture-every <seconds>]` | Save a numbered screenshot every few seconds (5 by default), to check a build without anyone watching. |

**Esc** always opens the options menu: graphics quality, microphone, camera, display and particles.

## 5. Devices

**Microphone.** By default the system's input device. To pick another one, choose it in the client's options menu (Esc) or set `AUDIO_INPUT_DEVICE` to its index or part of its name. To list them:

```bash
uv run python -c "import sounddevice; print(sounddevice.query_devices())"
```

**Camera.** `VISION_CAMERA_INDEX` (0 is the first one), or the options menu. Some webcams open at 640x480 on Windows even when they do 1080p; `VISION_CAPTURE_WIDTH` and `VISION_CAPTURE_HEIGHT` ask for more. With `VISION_SOURCE=unity` the client sends snapshots from its own webcam instead, and `VISION_SOURCE=none` turns the camera off.

What you choose in the options menu is saved on that machine (`DEVICES_FILE`) and wins over `.env`.

**Permissions.**

- macOS asks the first time a program opens the microphone or the camera. The permission belongs to the app that started the orchestrator (Terminal, iTerm, your editor...): if you denied it, enable it in System Settings > Privacy & Security > Microphone (and Camera) and restart that app. A denied microphone does not fail: it records silence, and Sonnia never hears anyone.
- Windows: Settings > Privacy & security > Microphone (and Camera) > "Let desktop apps access your microphone" must be on.

## 6. Portrait screens

- Rotate the display in the operating system, not in Unity: on macOS, System Settings > Displays > Rotation 90°; on Windows, Settings > System > Display > Display orientation > Portrait.
- Run the client full screen at 1080x1920. A different 9:16 resolution scales cleanly; another aspect ratio crops the framing.
- In the editor, set the Game view to 1080x1920. **Sonnia > Vertical 9:16 Capture** renders the main camera at that size: the editor's own capture tools render 16:9 and are no good for judging the framing.

## 7. Running it all day

Sonnia is meant to run unattended for a whole day. A few habits help:

- **Keep the machine awake.** On macOS, run `caffeinate -dis` in a terminal while she runs (or turn sleep off in Energy settings). On Windows, set the power plan's screen and sleep timeouts to "Never".
- **Silence the operating system.** Turn on Do Not Disturb (macOS) or Focus (Windows) so no notification covers the screen, and turn off automatic updates during the event.
- **Wired network if possible.** The conversation streams audio both ways in real time.
- **Use the control panel** at `http://127.0.0.1:8780`. Its modes decide what she does and what it costs:
  - *Conversation*: she listens and talks. The realtime model costs about 0.05 USD per minute of open session, plus the tokens of the backend and the vision model.
  - *Greeter*: she only says recorded greetings every so often. A line not yet in the voice cache is recorded once with a short session; after that it plays for free.
  - *Away*: she walks off and leaves a sign. Nothing runs.
- After `IDLE_RESET_SECONDS` without anyone talking, the conversation restarts, so the next visitor does not inherit the last one's context.
- The orchestrator survives a lost network, a closed client or a broken camera and recovers on its own; see "Staying up for a whole day" in the [architecture guide](architecture.md).

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| The avatar idles but never talks. | The orchestrator is not running, or listens on another port: compare `WS_PORT` with the client's `-sonia-ws`. With `-dev-ui` the connection label says whether the client is connected. |
| The orchestrator exits because its WebSocket port is busy. | Another orchestrator (or `sonia demo`) is still running. Stop it, or use another `WS_PORT` and `-sonia-ws`. |
| She never hears anyone. | Microphone permission (see above), the wrong input device, or the microphone muted from the panel. `sonia check` shows the input device it will open. |
| She answers conversations around her. | Point the microphone at the visitor and away from the aisle. As a last resort `LIVE_GATE_RMS` sends silence below a level; it is off by default because a badly set gate also cuts the visitor. |
| The camera check fails. | Another app holds the camera, the index is wrong, or the permission is missing. Try `VISION_CAMERA_INDEX=1`, or `VISION_SOURCE=unity`. |
| No sound, but subtitles appear. | The volume in the panel is at 0 (or `sonia demo` runs with `--volume 0`), or the operating system plays to another output device. |
| The avatar is cut off or too small. | The screen or Game view is not 9:16. |
| The Windows build closes at once with the Genies Avatar SDK. | Install the Microsoft Visual C++ runtime. |
| `sonia check` fails on the realtime model. | Check `OPENAI_API_KEY`, that the account has access to `LIVE_MODEL`, and the network. |

Still stuck? Open an issue with the output of `uv run sonia check` (it never prints your keys) and the last lines of the orchestrator's log.
