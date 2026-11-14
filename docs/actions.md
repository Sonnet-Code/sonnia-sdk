# Writing actions

An action is something Sonnia does besides talking: look through the camera, show an image, dance, run the trivia. This guide explains how actions work and walks through `show_emotion`, a small action that ships as the worked example: it puts joy, sadness or surprise on her face, and it touches every layer an action can touch, from the tool definition to the Unity client. For the bigger picture, see the [architecture guide](architecture.md).

## How an action runs

1. The voice model hears the visitor ("make a surprised face!") and delegates a task to the backend, a Responses API model (`LIVE_BACKEND_MODEL`). The voice model cannot call tools itself: its instructions only list what the backend can do.
2. The backend has the registry's actions as tools. It calls `show_emotion` with `{"emotion": "surprise"}`.
3. The engine asks the registry to run it. The registry checks the arguments against the action's JSON Schema and calls its handler with an `ActionContext`.
4. The handler does the work (here, it sends a `show_emotion` message to the avatar client) and returns an `ActionResult`.
5. The result text goes back to the backend, which answers the voice model, which says something out loud.

Everything an action needs lives in four places:

| Layer | Where |
|---|---|
| Definition and handler | `server/sonia/actions/` (`emotion.py` for the example) |
| Registration | `build_default_registry` in `server/sonia/actions/builtin.py`, called from `build_components` in `server/sonia/cli.py` |
| What the voice model is told | `server/sonia/live/prompts.py` |
| The avatar side, if the avatar reacts | `server/sonia/ws/protocol.py`, `docs/protocol.md`, `docs/protocol.schema.json` and `unity/Assets/Scripts/Sonia` |

## 1. Define it

An action is an `ActionSpec` (`server/sonia/types.py`): a name, a description for the backend, a JSON Schema for the arguments and an async handler.

```python
SHOW_EMOTION = ActionSpec(
    name="show_emotion",
    description=(
        "Show an emotion on your avatar's face for a few seconds: joy, sadness or surprise. "
        "Use it when the user asks you to make a face, or to react to good news, a sad "
        "story or a surprising fact."
    ),
    parameters={
        "type": "object",
        "properties": {
            "emotion": {"type": "string", "enum": ["joy", "sad", "surprise"], "description": "..."},
            "seconds": {"type": "number", "description": "..."},
        },
        "required": ["emotion"],
    },
    handler=show_emotion,
)
```

- **The description is a prompt.** The backend decides from it when to call the action, so say what it does and when to use it.
- **The schema is enforced.** Before the handler runs, the registry checks required arguments, primitive types and `enum` values, and turns a failure into an error the model reads. Unknown arguments are dropped silently: models invent them. Use `enum` whenever the values are a fixed list; the handler then never sees anything else.

## 2. Write the handler

```python
async def show_emotion(ctx: ActionContext, arguments: dict[str, Any]) -> ActionResult:
    if ctx.avatar is None:
        return ActionResult(text=NO_AVATAR)
    emotion: str = arguments["emotion"]
    seconds = float(arguments.get("seconds") or DEFAULT_SECONDS)
    seconds = min(max(seconds, 0.5), p.EMOTION_MAX_SECONDS)
    await ctx.avatar.show_emotion(emotion, seconds)
    return ActionResult(text=f"Done: your face shows {emotion} on screen. Keep talking naturally.")
```

The rules every handler follows:

- **Never raise for an expected problem.** Return the problem as text ("The avatar is not connected.") so the model can say something sensible. The registry still catches anything unexpected and returns it as an error, but that is the safety net, not the plan.
- **The result is read by a model.** Keep it short and say what happened and what she should do next. A result starting with `FOR SONIA:` is passed through whole: the trivia uses it for the question she must read.
- **Never block the event loop.** The microphone streams to the model from the same loop. Use `await` for I/O and `asyncio.to_thread` for anything slow and synchronous (disk, image processing), and put a timeout on anything that can hang, like `look` does with the camera.
- **Clamp what the model gives you.** Numbers come from a model: bound them.

`ActionContext` gives the handler:

| Field | What it is |
|---|---|
| `avatar` | The link to the avatar client (`AvatarLink`, implemented by the WebSocket hub), or `None` in tests and tools without a client. |
| `camera` | The camera source, or `None` when there is none. `await ctx.camera.capture()` returns a `Frame`. |
| `last_frame` | The most recent snapshot, if any. |
| `gallery_dir`, `gallery_upload_dir` | The image folders. |
| `extra` | Engine objects some actions need: `extra["trivia"]` (the trivia game), `extra["moves"]` (the animation catalog), `extra["agenda"]` (the `AgendaBook`, when there is an agenda) and `extra["language"]` (the `Language` of `LANGUAGE`, for anything written on the screen). |

An `ActionResult` can also carry an `image`: `look` returns the snapshot that way, and the engine shows it to the backend.

## 3. Register it

`build_default_registry` decides which actions exist. The example is behind a flag:

```python
def build_default_registry(*, include_look=True, include_trivia=False, include_emotion=False):
    ...
    if include_emotion:
        registry.register(SHOW_EMOTION)
```

and `build_components` in `server/sonia/cli.py` passes `include_emotion=settings.show_emotion_enabled`. If your action needs a setting, add a field with a `#:` comment to `server/sonia/config.py`, regenerate the [configuration reference](configuration.md) from `server/` with `uv run python -m sonia.config_doc > ../docs/configuration.md` and add the variable to `.env.example`. The tests fail if any of those three disagree.

Leave an action out of the registry when it cannot work (no camera, no question bank): an action that is not registered is not offered to the backend and is not mentioned to the voice model.

## 4. Tell the voice model

The voice model does not see the tools, only its instructions, so `server/sonia/live/prompts.py` tells it what the backend can do and when to delegate. Each piece is added only when the action is registered:

- `_CAPABILITIES["show_emotion"]`: one line in the list of backend tools.
- `_EMOTION_WHEN`: when to delegate it, inserted through the `{emotion_when}` placeholder of `LIVE_RULES`.
- `_BACKEND_DOES["show_emotion"]`: added to the reminder at the very end of the instructions ("these only happen if you delegate them"). Without it, the voice model tends to say "here I go!" and delegate nothing.

The texts sent to the models are covered by snapshot tests. If your change alters the default instructions, the suite shows the diff; review it and rewrite the snapshots from `server/` with `SONIA_WRITE_SNAPSHOTS=1 uv run pytest -q tests/test_prompts_live.py tests/test_prompts_trivia.py`. An action that is off by default, like the example, leaves the snapshots untouched.

## 5. The avatar side

If the avatar reacts, the action needs a protocol message, and the [protocol](protocol.md) changes in the same commit on both sides.

**Orchestrator.** In `server/sonia/ws/protocol.py`, a `MSG_` constant and a `msg_` builder; nothing builds protocol dictionaries by hand:

```python
MSG_SHOW_EMOTION = "show_emotion"

def msg_show_emotion(emotion: str, seconds: float = 3.0) -> dict[str, Any]:
    if emotion not in EMOTIONS:
        raise ValueError(f"unknown emotion {emotion!r}; expected one of {EMOTIONS}")
    held = min(max(float(seconds), 0.5), EMOTION_MAX_SECONDS)
    return {"type": MSG_SHOW_EMOTION, "emotion": emotion, "seconds": round(held, 2)}
```

Then a `show_emotion` method on `AvatarLink` (`server/sonia/types.py`) and on the hub (`server/sonia/ws/hub.py`), which sends it with `broadcast_json`. If a client that connects later must see it too (something that stays on screen), send it with `set_sticky` instead.

**Contract.** Describe the message in `docs/protocol.md` with a JSON example and add it to `docs/protocol.schema.json`, under `$defs` and in `serverMessage`. The suite validates every message the orchestrator builds against the schema and checks that the document, the schema and the Unity client agree on the message names.

**Unity client.** Three files in `unity/Assets/Scripts/Sonia`:

1. `Protocol.cs`: the name in `MessageTypes`, above the "From Unity to the orchestrator" line, and a message class.

   ```csharp
   public const string ShowEmotion = "show_emotion";

   [Serializable]
   public class ShowEmotionMessage
   {
       [JsonProperty("emotion")] public string Emotion;
       [JsonProperty("seconds")] public float Seconds = 3f;
   }
   ```

2. `SoniaClient.cs`: an `OnShowEmotion` event, a `case MessageTypes.ShowEmotion` that deserializes it, and the block that raises the event.
3. A handler. `SoniaBootstrap` wires the client to the scene, so it subscribes in `OnEnable`, unsubscribes in `OnDisable`, and calls the component that does the work, here `FacialExpressionController.ShowEmotion`:

   ```csharp
   private void HandleShowEmotion(ShowEmotionMessage message)
   {
       FacialExpressionController face = GetComponentInChildren<FacialExpressionController>(true);
       if (face == null || message == null)
       {
           return;
       }
       // "joy", "sad" or "surprise" to FacialExpressionController.Emotion, then:
       face.ShowEmotion(emotion, Mathf.Clamp(message.Seconds, 0.5f, 10f));
   }
   ```

A client that does not know a message type ignores it, so an older build keeps working with a newer orchestrator. Any visual change on the client must be checked on screen at 1080x1920 before it is called done; `sonia demo` is the quickest way, and the demo shows a surprised face after its web search.

## 6. Test it

`server/tests/test_emotion.py` is the template, one test per layer, all offline:

- the protocol builder, including what it rejects and clamps;
- the handler through `registry.execute`, with a fake `AvatarLink` that records calls;
- a made-up argument that never reaches the avatar, and the text the model gets without an avatar;
- the registry and the instructions, with and without the action;
- the setting, through `cli.build_components`;
- a real WebSocket client connected to a `Hub`, which receives the message.

Tests never call real APIs. Add the builder to `BUILDS` in `server/tests/test_protocol_schema.py`; a test fails until every builder is listed there.

## Checklist

- [ ] `ActionSpec` with a description that says when to use it and a schema with `enum` where it can.
- [ ] A handler that returns problems as text, clamps numbers and never blocks the loop.
- [ ] Registered in `build_default_registry`, behind a setting if it is optional or costs money.
- [ ] Capability, when-to-delegate rule and reminder in `prompts.py`; snapshots reviewed.
- [ ] If the avatar reacts: builder, `AvatarLink` and hub method, `docs/protocol.md`, the schema, `Protocol.cs`, `SoniaClient.cs` and a handler, all in the same commit.
- [ ] Tests for every layer, and `uv run pytest -q` green.
- [ ] Checked on screen with `sonia demo` or `sonia run`.

## Try the example

```bash
SHOW_EMOTION_ENABLED=true uv run sonia run
```

Then ask her to make a surprised face. Each emotion is a task for the backend, so it costs a few tokens and adds a short delay; that is why it is off by default.
