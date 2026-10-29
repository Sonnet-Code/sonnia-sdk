# Orchestrator ↔ avatar client protocol

Version 1 (draft). One local WebSocket, `ws://127.0.0.1:8765/` by default. The orchestrator is the server; the Unity avatar (or any other client, such as a test console) connects as a client. Several clients may be connected at once and all of them receive the same messages.

There are two kinds of frames:

- **Text**: JSON with a mandatory `type` field. Everything that is not audio goes here.
- **Binary**: PCM audio with a fixed 12-byte header. Orchestrator to client only.

Utterance ids (`utterance_id`) are increasing integers within a session.

On the other side of the orchestrator sits a speech-to-speech model that listens to the microphone and speaks with its own voice. This protocol knows nothing about it: the orchestrator turns the model's voice into utterances, states and transcripts for the client.

## Orchestrator → client

### `hello`

First message after connecting. It announces the audio format that will follow (`LIVE_SAMPLE_RATE`, 24000 by default). The "sticky" messages (`presence`, `set_volume`, ...) are re-sent right after it.

```json
{"type": "hello", "version": 1, "sample_rate": 24000, "channels": 1, "format": "pcm_s16le"}
```

### `state`

Assistant state change. The client uses it to drive animation.

```json
{"type": "state", "state": "idle"}
```

Values: `idle`, `listening`, `thinking`, `speaking`. The realtime model does not emit turn events, so the orchestrator infers them: `listening` while the user's transcript is arriving, `thinking` after the user's turn or while the backend runs an action, `speaking` with the first audio of the assistant, `idle` once the client has finished playing.

### `activity`

What the assistant is doing behind the scenes, for scene effects: `search` while the backend searches the web, `think` when a delegated task takes longer than a few seconds, and `none` otherwise. Sent only on change. Clients that do not know it ignore it.

```json
{"type": "activity", "activity": "search"}
```

### `busy`

On-screen waiting indicator: a large pill with animated dots while the assistant waits for something the user cannot see. It carries the whole state: with `on: true` the client shows `text` (or replaces it), with `on: false` it hides it. Clients should keep it visible for at least 0.6 s so it does not flicker. Only the highest-priority wait is sent (`kind`: `search` above `think`), and it is re-sent to a client that reconnects while one is active.

```json
{"type": "busy", "on": true, "kind": "think", "text": "Thinking…"}
{"type": "busy", "on": false}
```

### `transcript`

Text of what the user (`user`) or the assistant (`assistant`) says, for subtitles and the control panel. `final` is `false` while the text is still growing; each message carries the accumulated text, not just the new part.

```json
{"type": "transcript", "role": "user", "text": "hi sonnia", "final": true}
```

Sound tags from the model's transcription (such as `[laugh]`) are removed before sending.

### `speech_start`

An assistant utterance begins. Binary frames with that `utterance_id` will follow. An utterance is a continuous stretch of voice; it closes after `LIVE_SEGMENT_GAP_MS` (800 ms) of silence. `text` may be empty: the transcript lags slightly behind the audio and is completed through `transcript`.

```json
{"type": "speech_start", "utterance_id": 7, "text": "Hi, how are you?"}
```

With `"ambient": true` it is an idle line (something the assistant says on its own when nobody is around, usually played from the voice cache). The state does not change and the client only moves the mouth, brows and eyes without interrupting the current dance or gesture.

### `speech_end`

No more audio for that utterance. The client answers with `playback_done` once it has played everything it has queued.

```json
{"type": "speech_end", "utterance_id": 7}
```

### `stop_speaking`

Interruption. The client immediately drops all queued audio and stops moving the mouth. Sent when the client sends `interrupt` or when the operator mutes the assistant from the panel. Barge-in by voice needs nothing: the realtime model stops sending audio by itself.

```json
{"type": "stop_speaking", "reason": "interrupted"}
```

### `show_image` and `hide_image`

Show an image in the scene's image panel (the `show_image` action or a panel button). `data_base64` carries the whole image. If nobody hides it, the orchestrator sends `hide_image` after `IMAGE_AUTO_HIDE_SECONDS`.

```json
{"type": "show_image", "image_id": "diagram", "source": "gallery", "mime": "image/png", "data_base64": "...", "caption": "How it works"}
{"type": "hide_image"}
```

### `attention`

Asks the avatar for an attention gesture: `dance`, `fourth_wall` (point, wave, tap the screen), `soft` or `greeting`. `clip` optionally names a specific clip. Honored in `idle` (`greeting` also while listening).

```json
{"type": "attention", "category": "dance"}
```

### `play_animation`

Plays a specific clip from the catalog the client sent with `animations`. Unlike `attention`, it is honored in any state: the clip plays once and the animation system then returns to whatever it was doing. With `whole: true` the clip plays to the end even if the assistant starts speaking. Unknown names are ignored with a console warning.

```json
{"type": "play_animation", "clip": "QuickAction_vibe", "whole": true}
```

### `presence`

The assistant is on screen (`present: true`) or away (`false`): she walks off and leaves a sign with `message`. Sticky: re-sent after `hello`, and then applied without animation.

```json
{"type": "presence", "present": false, "message": "Back in a few minutes"}
```

### `stage_mode`

Operating mode (`conversation`, `greeter` or `away`) and whether the assistant can hold a conversation right now (`talk`). Sticky. The screen only shows the "come and talk to me" invitation with `talk: true`.

```json
{"type": "stage_mode", "mode": "greeter", "talk": false}
```

### `devices`

Answer to `list_devices` (and after each `set_device`): the microphones of the machine running the orchestrator, the configured one, the camera index in use and where snapshots come from.

```json
{"type": "devices", "microphones": [{"name": "Built-in Microphone", "default": true}], "microphone": "", "default_microphone": "Built-in Microphone", "camera": 0, "camera_source": "opencv"}
```

### Sticky settings

All of these are re-sent after `hello` and whenever they change:

| Message | Payload | Meaning |
|---|---|---|
| `set_volume` | `value` (0 to 1.5, 1 is normal) | Voice volume. |
| `set_subtitles` | `enabled` | Show or hide subtitles; `transcript` keeps arriving either way. |
| `set_disabled_animations` | `clips` | Clips the avatar must not use on its own (`play_animation` still plays them). |
| `set_debug` | `enabled` | Debug mode: only base loops, no idle variations or attention gestures. |
| `set_tuning` | `mouth`, `camera`, `idle` | Multipliers for lip-sync, camera framing and idle motion (1 = as authored). |
| `set_avatar` | `definition` | Genies avatar definition as a JSON string, or `null` for the default character. Ignored when the Genies SDK is not installed. |

### Trivia: `trivia_start`, `trivia_question`, `trivia_answer`, `trivia_end`

The realtime model hosts the trivia and the orchestrator keeps the answer key: the screen is the source of truth. While a game is running, `trivia_start` and the current question are sticky.

```json
{"type": "trivia_start", "total": 5, "threshold": 3, "level": "medium"}
{"type": "trivia_question", "number": 2, "total": 5, "question": "What does HTTP stand for?", "options": ["HyperText Transfer Protocol", "High Transfer Text Process", "Hosted Text Transport Protocol"], "score": 1}
{"type": "trivia_answer", "number": 2, "chosen": 0, "correct": 0, "is_correct": true, "score": 2}
{"type": "trivia_end", "score": 4, "total": 5, "won": true, "reason": "finished"}
```

- `chosen` is the index picked (0 to 2) or -1 if the player did not know; `correct` is the right index.
- `reason` is `finished` (show the final screen) or `cancelled` (clear everything without fanfare).

### `request_frame`

Only with `VISION_SOURCE=unity`. The client answers with a `camera_frame` as soon as possible.

### `error`

```json
{"type": "error", "message": "human readable description"}
```

## Binary audio frames

12-byte little-endian header followed by mono PCM s16le (the model's voice as it arrives, not resampled):

| Offset | Size | Field | Value |
|---|---|---|---|
| 0 | 4 | magic | `SNIA` (ASCII bytes) |
| 4 | 4 | utterance_id | uint32 |
| 8 | 4 | flags | uint32. Bit 0: last chunk of the utterance. |
| 12 | n | pcm | int16 LE mono samples at the rate announced in `hello` |

Chunks are about 100 ms long and arrive in real time. The client queues them in a ring buffer and plays them without waiting for the whole utterance. The last chunk (bit 0 set) may be empty.

## Client → orchestrator

### `client_hello`

Optional. Identifies the client and what it supports. Sent on every connection.

```json
{"type": "client_hello", "client": "unity", "version": "1.0.0", "features": []}
```

### `interrupt`

Interrupt the assistant through a non-voice channel (for example a developer button). The orchestrator discards the rest of the current answer, tells the model the user interrupted and sends `stop_speaking`.

```json
{"type": "interrupt"}
```

### `playback_done`

The client finished playing the last utterance it received. The orchestrator switches to `idle` after the `playback_done` of the last utterance (or after a timeout based on the audio duration).

```json
{"type": "playback_done", "utterance_id": 7}
```

### `text_input`

Typed input instead of voice, useful for testing without a microphone. It is handed to the model as text the user typed, and the assistant answers out loud.

```json
{"type": "text_input", "text": "What can you do?"}
```

### `camera_frame`

With `VISION_SOURCE=unity`, the client sends snapshots from its webcam when asked with `request_frame`. The orchestrator keeps only the latest one in memory.

```json
{"type": "camera_frame", "mime": "image/jpeg", "data_base64": "..."}
```

### `list_devices` and `set_device`

`list_devices` asks for the microphones and current choices (answered with `devices`); `set_device` picks a microphone (`kind: microphone`, `value`: its name, or empty for the system default) or a camera (`kind: camera`, `value`: its index). The choice is applied immediately and stored on that machine.

```json
{"type": "list_devices"}
{"type": "set_device", "kind": "camera", "value": 1}
```

### `animations` and `animation_playing`

On `hello`, the client sends the catalog of one-shot clips that can be triggered with `play_animation`. `group` is one of `greeting`, `dance`, `fourth_wall`, `soft`, `talking`, `idle_variation`, `thinking`, `nod` or `present`. Whenever the playing one-shot clip changes, the client sends `animation_playing` (`clip` or `null`).

```json
{"type": "animations", "animations": [{"clip": "Wave", "group": "greeting"}]}
{"type": "animation_playing", "clip": "Wave"}
```

## A typical turn

```
Client                                 Orchestrator                      Realtime model
  |                                        |===== continuous microphone ===>|
  |<--- transcript(user, partial) ---------|<--- user transcription --------|
  |<--- state: listening ------------------|
  |<--- transcript(user, final) -----------|   (user pauses)
  |<--- state: thinking -------------------|
  |<--- speech_start(1) -------------------|<--- first audio with voice ----|
  |<--- state: speaking -------------------|
  |<--- [binary 1] x N --------------------|<--- real-time audio (100 ms) --|
  |<--- transcript(assistant, final) ------|   (800 ms of silence)
  |<--- speech_end(1) ---------------------|
  |<--- show_image ------------------------|<--- action delegated to backend
  |---- playback_done(1) ----------------->|
  |<--- state: idle -----------------------|
```

## Rules

- The client must never block waiting for a specific message. Any message can arrive at any time.
- Messages with an unknown `type` are ignored in both directions.
- When the protocol changes, update this document, the orchestrator's protocol module and the Unity `Protocol.cs` in the same commit.
