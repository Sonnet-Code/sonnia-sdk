# Arquitectura del orquestador

El orquestador es un paquete Python (`server/sonia`) que corre como un único proceso `asyncio`. Cada etapa vive en su módulo y se comunica con las demás únicamente a través de los tipos de `sonia/types.py` y la configuración de `sonia/config.py`.

Hay dos motores de voz, elegidos con `VOICE_ENGINE`:

- `live` (por defecto, ADR 007): GPT-Live de OpenAI oye y habla por un único WebSocket; ver [Motor GPT-Live](#motor-gpt-live).
- `pipeline`: el motor en cascada que describe el diagrama de abajo (VAD, STT, LLM, TTS). Se conserva como respaldo.

Los dos hablan con Unity por el mismo protocolo (`sonia/ws`) y usan las mismas acciones (`sonia/actions`), cámara (`sonia/vision`) y persona (`sonia/persona.py`).

### Motor pipeline

```
micrófono ─► audio.capture ─► audio.vad ─► Utterance
                                              │
cámara ─► vision.camera ─► Frame ──────────┐  │
                                           ▼  ▼
                                    orchestrator (máquina de estados)
                                     │   │        │
                            stt ◄────┘   │        └────► ws.hub ──► Unity
                            llm.client ◄─┘  ◄─► actions.registry
                                │
                          sentence splitter ─► tts ─► visemes ─► ws.hub
```

## Módulos

### `sonia/audio`

- `capture.py`: `MicCapture` abre el dispositivo con `sounddevice.InputStream` a 16 kHz mono float32 y expone `async def blocks() -> AsyncIterator[AudioArray]` con bloques de `AUDIO_BLOCK_MS`. El callback de sounddevice corre en otro hilo: se pasa al bucle asyncio con `loop.call_soon_threadsafe` y una `asyncio.Queue` acotada (si se llena, se descartan bloques viejos y se registra un aviso). `blocks()` vigila el hueco entre bloques y lanza `MicStalled` si PortAudio deja de entregar audio (micro USB desconectado, cambio de dispositivo por defecto): sin eso la corrutina se quedaría esperando para siempre y Sonia se volvería sorda en silencio. Quien la consume (`_mic_loop` en `cli.py`) reabre el micrófono tras unos segundos, indefinidamente.
- `vad.py`: `VoiceActivityDetector` envuelve Silero VAD (`silero_vad.load_silero_vad`, `VADIterator` o llamada directa al modelo por bloque de 512 muestras). `TurnDetector` consume bloques y produce `Utterance`s completas aplicando `min_speech_ms`, `end_silence_ms`, `pre_roll_ms` y `max_utterance_s`. Emite también eventos `speech_started` (para capturar la cámara) antes de que el turno termine, y `BargeIn` cuando, mientras suena Sonia, la voz es sostenida (`barge_in_min_speech_ms`) y supera `barge_in_over_echo` veces el nivel de eco que mide (media móvil del RMS de los bloques con voz). Un turno abierto mientras suena Sonia que no se confirma se descarta: era su propio eco en el micrófono. `set_speaking(bool)` lo llama el orquestador con el primer chunk de audio de cada respuesta (no al cambiar de estado) y al dejar de sonar. Debe poder probarse con audio sintético y con un VAD falso inyectado.

### `sonia/stt`

- `base.py`: reexporta el protocolo `SpeechToText`.
- `faster_whisper.py`: `FasterWhisperSTT` carga el modelo una vez (lazy, en un hilo con `asyncio.to_thread`) y transcribe con `language`, `beam_size`, `vad_filter=False` (el VAD ya lo hicimos). Devuelve texto limpio.
- `mock.py`: `MockSTT` devuelve un texto fijo o una cola de textos, para tests y para `sonia chat`.

### `sonia/llm`

- `client.py`: `LLMClient` habla con `POST {base_url}/chat/completions` usando `httpx.AsyncClient`, siempre en streaming (SSE). `async def stream(messages, tools=None) -> AsyncIterator[LLMEvent]`. Acumula deltas de `tool_calls` por `index`, ignora `reasoning_content` para el texto hablado pero lo conserva y lo devuelve en `ToolCallsEvent`/`TurnDone`. Envía `reasoning_effort` solo si está configurado. Reintenta una vez ante errores de red, nunca ante un timeout. `LLM_REQUEST_TIMEOUT` acota el hueco entre dos trozos del stream y, multiplicado por un factor, el turno entero: un servidor que acepta la conexión y luego enmudece no puede dejar a Sonia en `thinking` sin fin. Un chunk `{"error": ...}` dentro del stream (vLLM, llama.cpp y varios proxies lo mandan con HTTP 200) se convierte en `LLMError` en vez de descartarse. Se cancela limpiamente al cancelar la tarea (cerrar la respuesta). Sin SDK de OpenAI.
- `messages.py`: helpers para construir mensajes: `user_text(text)`, `user_with_image(text, frame)`, `assistant_tool_calls(calls, content, reasoning_content)`, `tool_result(call_id, text)`. Cuando el modelo soporta visión, la imagen va como `{"type": "image_url", "image_url": {"url": "data:..."}}`.
- `conversation.py`: `Conversation` guarda el historial acotado a `history_turns` turnos, quita las imágenes de los turnos antiguos (solo se conserva la imagen del turno actual para no disparar el prefill) y expone `messages()` con el system prompt delante.
- `prompt_tools.py`: modo `prompt` de tool calling para servidores sin soporte nativo: genera la descripción de acciones para el system prompt y parsea bloques `<action>{"name": ..., "arguments": {...}}</action>` del texto. El texto fuera de los bloques se habla; los bloques se ejecutan.

### `sonia/actions`

- `registry.py`: `ActionRegistry` con `register(spec)`, `get(name)`, `to_openai_tools()` (lista de `{"type": "function", "function": {...}}`) y `async execute(name, args, ctx) -> ActionResult` que valida argumentos contra el JSON Schema de forma básica (campos requeridos y tipos primitivos) y captura excepciones devolviendo un `ActionResult` con el error en texto.
- `builtin.py`: `look`, `show_image`, `hide_image`, y `build_default_registry(ctx_factory)`.
  - `look`: captura con `ctx.camera`; guarda en `ctx.last_frame`; devuelve `ActionResult(text="Captura tomada.", image=frame)`.
  - `show_image(image_id: str, caption?: str)`: `image_id` es un nombre de archivo sin extensión de `assets/gallery` (png/jpg) o `camera` para `ctx.last_frame`. Llama a `ctx.avatar.show_image(...)`.
  - `hide_image()`.
- `gallery.py`: lista los ids disponibles y carga una imagen por id de forma segura (sin path traversal).

### `sonia/vision`

- `camera.py`: `OpenCVCamera(CameraSource)` abre `cv2.VideoCapture(index)` de forma perezosa y lee, redimensiona y codifica JPEG dentro del mismo `asyncio.to_thread`. Ningún fallo es definitivo: una apertura fallida se reintenta pasado un cooldown, y unas lecturas sin frame seguidas (o una lectura colgada, que se abandona por timeout) sueltan el dispositivo para abrir otro. `UnityCamera(CameraSource)` guarda el último `camera_frame` recibido por WS y, en `capture()`, envía `request_frame` y espera hasta 500 ms a que llegue uno nuevo; si no llega, devuelve el último que tenga siempre que no pase de `max_age`, y si no hay clientes conectados ni se molesta en pedirlo. `NullCamera` devuelve `None`. `build_camera(settings, hub)` elige según `VISION_SOURCE`.
- `policy.py`: `VisionPolicy` decide si se adjunta captura al turno (`on_turn_start`, `interval_seconds`, `supports_vision`). Si `debug_save_frames`, guarda en `debug_dir`.

### `sonia/tts`

- `base.py`: protocolo `TextToSpeech` y utilidades `float_to_pcm16`, `chunk_pcm(pcm, sample_rate, chunk_ms)`.
- `omnivoice.py`: `OmniVoiceTTS` carga `OmniVoice.from_pretrained("k2-fsa/OmniVoice", device_map=..., dtype=...)` en un hilo la primera vez (`device` auto: cuda > mps > cpu; en mps/cpu usar float32). `synthesize(text)` llama a `model.generate(text=..., instruct=... o ref_audio/ref_text, num_step, speed)` en `asyncio.to_thread`, convierte el `np.ndarray` a PCM y lo trocea en chunks. Si el modelo devuelve lista, se concatena.
- `http.py`: `HTTPTTS` llama a `POST {base_url}/audio/speech` con `{"model", "input", "voice", "response_format": "pcm" o "wav", "speed"}` y trocea la respuesta (si es wav, quita la cabecera y respeta su tasa de muestreo).
- `mock.py`: `MockTTS` genera un tono o silencio con una duración proporcional al texto (unos 60 ms por carácter) para probar todo el pipeline sin modelos.
- `factory.py`: `build_tts(settings)`.

### `sonia/visemes.py`

`visemes_for(text, duration) -> list[VisemeFrame]`: heurística grafema → visema para español (vocales a/e/i/o/u → `aa`/`E`/`ih`/`oh`/`ou`; p/b/m → `PP`; f/v → `FF`; d/t → `DD`; k/c/g/q/j → `kk`; ch/ñ/y/ll → `CH`; s/z/c(e,i)/x → `SS`; n/l → `nn`; r/rr → `RR`; espacios/puntuación → `sil`). Reparte los visemas uniformemente por sílabas aproximadas en la duración real del audio. `envelope_for(pcm, sample_rate, interval_ms) -> list[float]`: RMS normalizado por ventana.

### `sonia/sentences.py`

`SentenceSplitter`: recibe deltas de texto y devuelve frases completas en cuanto se cierran (`.`, `!`, `?`, `;`, `:` seguidos de espacio o fin, y también `,` si el fragmento acumulado supera unos 60 caracteres). Trata abreviaturas comunes y números decimales. `flush()` devuelve lo que quede. Las frases van sin markdown ni emojis (se limpian aquí).

### `sonia/ws`

- `protocol.py`: constantes, `encode_audio_frame(utterance_id, pcm, is_last) -> bytes`, `decode_audio_frame`, y funciones `msg_*` que construyen cada JSON del protocolo. Es la única fuente de verdad de los nombres de mensajes.
- `hub.py`: `Hub` es el servidor `websockets`. Mantiene el conjunto de clientes, hace `broadcast(text|bytes)`, envía `hello` al conectar, y despacha los mensajes entrantes a callbacks registrados (`on("interrupt", cb)`, etc.). Implementa `AvatarLink` (`show_image`, `hide_image`). Nunca lanza si no hay clientes: la demo debe seguir aunque Unity se reinicie. Cada envío tiene un timeout corto: un cliente que deja de leer se descarta en vez de bloquear el bucle del orquestador. El `max_size` entrante se sube a 16 MiB para que quepa un `camera_frame` de una webcam grande, y el keepalive es corto para detectar pronto a un Unity congelado.

### `sonia/mcp/server.py`

Servidor MCP (transporte streamable HTTP, en proceso, puerto `MCP_PORT`) que expone cada `ActionSpec` del registro como tool MCP. Importa `mcp` de forma perezosa: si el extra no está instalado y `MCP_ENABLED=false`, no pasa nada. Comprobar la API real de la versión instalada de `mcp` antes de escribir el código.

### `sonia/orchestrator.py`

Máquina de estados asincrónica. Dependencias inyectadas por constructor: `settings`, `turns` (async iterador de eventos del `TurnDetector` o de `text_input`), `stt`, `llm`, `tts`, `camera`, `vision_policy`, `registry`, `hub`. Métodos principales:

- `run()`: bucle principal. Espera un evento de turno. En `speech_started`: si está `idle` pasa a `listening` y captura la cámara según la política; mientras suena Sonia se ignora (puede ser su eco). En `barge_in`: si está `speaking` y `barge_in` está activo, cancela el turno en curso (`stop_speaking`) y pasa a `listening`. En `utterance`: `thinking`, STT, y lanza `handle_user_text(text, frame)`. Entre frases, el freno de audio (`_pace`) toma como inicio de reproducción el primer chunk enviado, no el final de la síntesis: con un TTS a tiempo real la diferencia son segundos de hueco. A partir de la segunda frase el troceador no corta hasta 80 caracteres (`SENTENCE_MIN_CHARS`), porque cada corte es una petición al TTS y un hueco.
- `handle_user_text(text, frame)`: añade el mensaje al historial, hace hasta `max_tool_rounds` rondas con el LLM. Los `TextDelta` van al `SentenceSplitter`; cada frase completa se encola para síntesis. Las `ToolCallsEvent` se ejecutan en orden con el registro, se añaden los mensajes `assistant`/`tool` al historial (y un mensaje de usuario con la imagen si la acción devolvió una) y se vuelve a llamar al modelo.
- Síntesis: una tarea consumidora toma frases de una cola, las sintetiza y emite `speech_start`, frames binarios, `visemes`, `envelope`, `speech_end`. Dentro de una frase no se frena el envío: así los visemas, que necesitan la duración total, llegan nada más terminar de sintetizarse y no cuando ya casi se acabó de reproducir. El freno (`MAX_AUDIO_LEAD_S`) se aplica entre frases. La primera frase marca `speaking`. El estado vuelve a `idle` cuando la cola está vacía, el modelo terminó y Unity envió `playback_done` de la última frase (o pasado un timeout igual a la duración del audio más un margen, por si Unity no responde).
- Cancelación: todo el turno corre bajo una `asyncio.TaskGroup`/tareas que se cancelan juntas. Al cancelar, vaciar la cola de frases y enviar `stop_speaking`.
- `text_input` desde el WS entra por el mismo camino que un `Utterance` transcrito.
- Reinicio del historial tras `idle_reset_seconds` sin actividad.

### `sonia/cli.py`

Subcomandos con `argparse`:

- `sonia run`: demo completa.
- `sonia chat`: sin micrófono ni cámara: lee texto de la consola, lo pasa por el orquestador con `MockSTT` y muestra las frases que se sintetizan. Con `--speak` reproduce el audio localmente con sounddevice.
- `sonia say "texto"`: sintetiza y reproduce (o guarda a wav con `--out`).
- `sonia check`: comprueba dispositivos de audio, Silero VAD, el modelo de STT (que el extra esté instalado y los pesos descargados), cámara, endpoint del LLM (una petición mínima de 5 tokens), sus capacidades tal como se usan en cada turno (una petición con imagen y otra con `tools`, de 5 tokens cada una), TTS y galería. Imprime una tabla con OK/FALLO.
- `sonia mcp`: arranca solo el servidor MCP con las acciones (útil para probar con otros clientes).

Con `VOICE_ENGINE=live`, `run` abre el micrófono a `LIVE_SAMPLE_RATE` y arranca `LiveEngine` (con `--no-mic` manda silencio y solo atiende `text_input`); `chat` pasa cada línea a GPT-Live como texto escrito e imprime lo que dice; `say` hace que GPT-Live lea el texto con `LIVE_VOICE`; y `check` comprueba micrófono, cámara, una sesión de GPT-Live (abrir y cerrar), el modelo de visión (si hay cámara) y la galería.

## Motor GPT-Live

```
micrófono ─► audio.capture (24 kHz) ─► live.engine ──session.input_audio.append──► GPT-Live
                                          ▲  │                                     │ voz, transcripción,
cámara ─► vision.camera ─► live.vision ───┘  │ thinking.append "[Cámara] ..."      │ delegación
           (modelo LLM_* describe la foto)   │                                     ▼
                                             └◄── response.event (function_call) ── backend Responses
                                    actions.registry ──► function_call_output ──►  (gpt-6-luna)
                                             │
                                             └──► ws.hub ──► Unity (speech_start, PCM, transcript, state)
```

### `sonia/live`

- `client.py`: `LiveClient`, WebSocket crudo contra `wss://api.openai.com/v1/live/sessions` (sin SDK). `start()` manda `session.start` y espera `session.started`; `events()` entrega los eventos del servidor; `append_audio`, `append_instructions`, `append_thinking`, `append_commentary`, `create_item` y `create_response` son los comandos; `close()` hace el cierre ordenado.
- `prompts.py`: `build_session_config()` construye el `session` de `session.start`: modelo, voz, `audio.format`, instrucciones de la voz (la persona de `persona.py` más las reglas de este modo, el conocimiento y `describe_live_stack()`) y la delegación en el backend Responses con las herramientas de `ActionRegistry.to_responses_tools()`.
- `engine.py`: `LiveEngine`, la pieza que sustituye al orquestador. Reenvía el micrófono (silencio mientras suena Sonia sin barge-in o con la puerta de ruido cerrada), convierte la voz de GPT-Live en frases para Unity, deduce los estados, ejecuta las acciones delegadas y devuelve sus resultados (`function_call_output`, la foto de `look` como `input_image`, `response.create`), describe la cámara al empezar cada turno, atiende `text_input` e `interrupt`, pide los números del stand con `session.commentary.append`, reconecta con espera creciente y abre una sesión limpia tras `IDLE_RESET_SECONDS` sin nadie, si el contexto se llena o si la sesión va a caducar.
- `vision.py`: `VisionNarrator`, una petición al modelo de visión de `LLM_*` que describe la foto en una o dos frases sin rasgos personales.
- `audio.py`: conversión a PCM, puerta de ruido (`LIVE_GATE_RMS`) y silencio a tiempo real cuando no hay micrófono.
- `oneshot.py`: sesiones cortas para `sonia check` (abrir y cerrar) y `sonia say` (leer un texto con la voz de GPT-Live).

## Pruebas

Los tests no necesitan modelos ni hardware y jamás llaman a APIs reales. Para el LLM se usa `httpx.MockTransport` con respuestas SSE simuladas (texto, tool calls fragmentadas por chunks, `reasoning_content`). Para audio, arrays sintéticos. Para el VAD, un detector falso inyectado. Para Unity, un cliente `websockets` de prueba conectado al `Hub`.

## Latencia

Con GPT-Live no hay etapas que sumar: el propio modelo decide cuándo contestar y empieza a hablar en streaming. Las acciones añaden la ida y vuelta al backend Responses; mientras, GPT-Live suele decir algo breve ("mira, te lo enseño").

Con el motor pipeline, objetivo: menos de dos segundos entre el fin del habla y el primer audio de Sonia. Contribuciones esperadas: fin de silencio 600 ms, STT `small` 300 a 500 ms, primera frase del modelo 300 a 800 ms, TTS de la primera frase 200 a 400 ms. Por eso la primera frase se corta corto (la coma cuenta como corte si ya hay más de 60 caracteres) y el TTS usa `num_step=16`.
