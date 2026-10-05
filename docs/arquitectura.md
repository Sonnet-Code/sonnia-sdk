# Arquitectura del orquestador

El orquestador es un paquete Python (`server/sonia`) que corre como un único proceso `asyncio`. Hay un solo motor de voz: GPT-Live de OpenAI (ADR 007), que oye el micrófono y habla con su propia voz por un único WebSocket. El orquestador no reconoce voz ni sintetiza nada: le manda el micrófono, traduce su voz al protocolo de Unity, ejecuta las acciones que delega, le da ojos describiendo la cámara y sirve el panel de control.

```
micrófono ─► audio.capture ─► live.engine ──session.input_audio.append──► GPT-Live (OpenAI)
            (24 kHz, continuo)   ▲  │  ▲                                     │ voz, transcripción,
                                 │  │  │ thinking.append "[Cámara] ..."      │ delegación
cámara ─► vision.camera ─► live.vision  │                                     ▼
         (el modelo de LLM_* describe   └◄── response.event (function_call) ── backend Responses
          la foto)                         actions.registry ── function_call_output ──► (gpt-6-luna)
                                    │
                                    ├──► ws.hub ──► Unity (state, transcript, speech_start, PCM, show_image...)
                                    └──► panel ──► panel local (127.0.0.1:8780) y panel de Cloudflare
```

Lo que se envía a OpenAI: el audio del micrófono de forma continua (con la puerta de ruido, silencio por debajo de `LIVE_GATE_RMS`), los textos escritos y avisos, las notas de la cámara en texto y, solo con la acción `look`, la foto al backend. La foto que describe el modelo de visión va a `LLM_BASE_URL`. Nada se guarda en disco salvo la caché de voces (`cache/voice`) y el estado del panel (`cache/panel_state.json`).

## Comportamiento de la API comprobado

Comprobado con la API real el 4 de octubre de 2026; el motor depende de ello:

- **Audio continuo.** GPT-Live manda su voz a ritmo real en trozos de 100 ms y no para cuando calla: manda silencio digital. Por eso las frases hacia Unity se cortan por nivel de voz (`OUTPUT_VOICE_RMS` en `engine.py`) y no por huecos en el envío; el silencio de los extremos de cada frase no se manda a Unity.
- **`commentary` sí, `instructions` no.** `session.instructions.append` añade contexto pero no la hace hablar; `session.commentary.append` sí. Por eso los textos escritos (`text_input`, `sonia chat`, "Preguntar" del panel), los avisos del panel, los números del stand y la grabación de frases fijas van por `commentary`. Las instrucciones (`instructions.append`) se usan para lo que no debe provocar respuesta, como los avisos del día o tras una interrupción.
- **Transcripción con marcas.** La transcripción del visitante trae marcas de sonido como "[laugh]" o "[sigh]"; se limpian antes de mandarla a Unity, al panel y al log.
- **Sesión de hasta 120 minutos.** El motor abre otra sesión en el siguiente momento de calma antes de que caduque, igual que tras `IDLE_RESET_SECONDS` sin nadie (un visitante nuevo no arrastra la conversación del anterior) o si el contexto pasa de `LIVE_CONTEXT_RESTART_RATIO`.
- **Full duplex.** El micrófono va siempre a GPT-Live, también mientras habla: si el visitante habla, GPT-Live deja de hablar por sí mismo y le escucha. No hay detector de voz propio. La única excepción son las frases grabadas de `cache/voice` (`LiveEngine.play_clip`: saludos, avisos y números del stand): mientras suenan, y `CLIP_ECHO_TAIL_S` después, el micrófono manda silencio, porque esa voz no la generó GPT-Live y, si la oyera por los altavoces, la contestaría como si se la hubiera dicho un visitante.

## Módulos

### `sonia/live`

- `client.py`: `LiveClient`, WebSocket crudo contra `wss://api.openai.com/v1/live/sessions` (sin SDK). `start()` manda `session.start` y espera `session.started`; `events()` entrega los eventos del servidor; `append_audio`, `append_instructions`, `append_thinking`, `append_commentary`, `create_item` y `create_response` son los comandos; `expires_at` dice cuándo caduca la sesión; `close()` hace el cierre ordenado.
- `prompts.py`: `build_session_config()` construye el `session` de `session.start`: modelo, voz, `audio.format`, instrucciones de la voz (la persona de `persona.py` más las reglas de este modo, la base de conocimiento de `assets/knowledge`, los avisos del día y `describe_live_stack()`, que le dice a Sonia la verdad sobre cómo funciona) y la delegación en el backend Responses con las herramientas de `ActionRegistry.to_responses_tools()`.
- `engine.py`: `LiveEngine`. Reenvía el micrófono (con la puerta de ruido), convierte la voz de GPT-Live en frases para Unity (`speech_start`, frames binarios, `speech_end`, cerradas por un silencio de `LIVE_SEGMENT_GAP_MS`), reenvía las transcripciones como `transcript`, deduce los estados del avatar, ejecuta las acciones delegadas y devuelve sus resultados (`function_call_output`, la foto de `look` como `input_image`, `response.create`), describe la cámara al empezar cada turno, atiende `text_input` e `interrupt`, lanza la animación de stand, reconecta con espera creciente y renueva la sesión (caducidad, inactividad, contexto lleno). Expone a `panel` lo que necesita: activar o apagar la sesión según el modo, reproducir una frase grabada, avisos, puerta de ruido, silenciar el micro, reiniciar.
- `vision.py`: `VisionNarrator`, una petición al modelo de visión de `LLM_*` que describe la foto en una o dos frases sin rasgos personales.
- `audio.py`: conversión a PCM, nivel RMS, puerta de ruido (`LIVE_GATE_RMS`, con `LIVE_GATE_HOLD_MS` de cola) y silencio a tiempo real cuando no hay micrófono.
- `oneshot.py`: sesiones cortas para `sonia check` (abrir y cerrar) y `sonia say` (leer un texto con la voz de GPT-Live, por `commentary`).
- `voicecache.py`: `VoiceCache`, frases fijas (saludos, frases y cantos de `assets/showcase`) leídas una vez por GPT-Live y guardadas en WAV en `cache/voice`. La clave combina voz, tasa y texto: al cambiar de voz se regraban solas.

### `sonia/audio`

- `capture.py`: `MicCapture` abre el dispositivo (`AUDIO_INPUT_DEVICE`) con `sounddevice.InputStream` a `LIVE_SAMPLE_RATE` mono float32 y expone `async def blocks() -> AsyncIterator[AudioArray]` con bloques de `AUDIO_BLOCK_MS`. El callback de sounddevice corre en otro hilo: se pasa al bucle asyncio con `loop.call_soon_threadsafe` y una `asyncio.Queue` acotada (si se llena, se descartan bloques viejos y se registra un aviso). `blocks()` vigila el hueco entre bloques y lanza `MicStalled` si PortAudio deja de entregar audio (micro USB desconectado, cambio de dispositivo por defecto): sin eso la corrutina se quedaría esperando para siempre y Sonia se volvería sorda en silencio. Quien la consume (`_live_mic_loop` en `cli.py`) reabre el micrófono tras unos segundos, indefinidamente, y mientras tanto manda silencio para que la sesión siga viva.

### `sonia/llm`

Cliente mínimo del modelo con visión que describe la cámara (`VisionNarrator`).

- `client.py`: `LLMClient` habla con `POST {LLM_BASE_URL}/chat/completions` usando `httpx.AsyncClient`, en streaming (SSE). Envía `reasoning_effort` solo si está configurado y el tope de tokens con el nombre de `LLM_MAX_TOKENS_PARAM` (`max_completion_tokens` para la API de OpenAI). Reintenta una vez ante errores de red, nunca ante un timeout. `LLM_REQUEST_TIMEOUT` acota el hueco entre dos trozos del stream. Un chunk `{"error": ...}` dentro del stream se convierte en `LLMError`. Sin tool calling: solo texto e imagen de entrada y texto de salida. Sin SDK de OpenAI.
- `messages.py`: `system`, `user_text` y `user_with_image(text, frame)`; la imagen va como `{"type": "image_url", "image_url": {"url": "data:..."}}`.

### `sonia/actions`

- `registry.py`: `ActionRegistry` con `register(spec)`, `get(name)`, `to_responses_tools()` (las herramientas del backend Responses) y `async execute(name, args, ctx) -> ActionResult`, que valida argumentos contra el JSON Schema de forma básica (campos requeridos y tipos primitivos) y captura excepciones devolviendo un `ActionResult` con el error en texto.
- `builtin.py`: `look`, `show_image`, `hide_image`, y `build_default_registry(include_look=...)`.
  - `look`: captura con `ctx.camera`; guarda en `ctx.last_frame`; devuelve `ActionResult(text="Captura tomada.", image=frame)`.
  - `show_image(image_id: str, caption?: str)`: `image_id` es un nombre de archivo sin extensión de `assets/gallery` (png/jpg) o `camera` para `ctx.last_frame`. Llama a `ctx.avatar.show_image(...)`. El motor la retira sola a los `IMAGE_AUTO_HIDE_SECONDS`.
  - `hide_image()`.
- `gallery.py`: lista los ids disponibles y carga una imagen por id de forma segura (sin path traversal).

### `sonia/vision`

- `camera.py`: `OpenCVCamera(CameraSource)` abre `cv2.VideoCapture(index)` de forma perezosa y lee, redimensiona y codifica JPEG dentro del mismo `asyncio.to_thread`. Ningún fallo es definitivo: una apertura fallida se reintenta pasado un cooldown, y unas lecturas sin frame seguidas (o una lectura colgada, que se abandona por timeout) sueltan el dispositivo para abrir otro. `UnityCamera(CameraSource)` guarda el último `camera_frame` recibido por WS y, en `capture()`, envía `request_frame` y espera hasta 500 ms a que llegue uno nuevo; si no llega, devuelve el último que tenga siempre que no pase de `max_age`, y si no hay clientes conectados ni se molesta en pedirlo. `NullCamera` devuelve `None`. `build_camera(settings, ...)` elige según `VISION_SOURCE`.
- `policy.py`: `VisionPolicy` decide si se describe la cámara al empezar un turno (`VISION_ON_TURN_START`, apagado por defecto: Sonia solo mira con `look`) o cada cierto tiempo (`VISION_INTERVAL_SECONDS`), y se apaga entera si `LLM_SUPPORTS_VISION=false` o `VISION_SOURCE=none`. Entre dos descripciones pasan al menos `LIVE_VISION_MIN_INTERVAL_SECONDS`. Si `VISION_DEBUG_SAVE_FRAMES`, guarda en `debug_dir` (nunca en el stand).

### `sonia/ws`

- `protocol.py`: constantes, `encode_audio_frame(utterance_id, pcm, is_last) -> bytes`, `decode_audio_frame`, y funciones `msg_*` que construyen cada JSON del protocolo. Es la única fuente de verdad de los nombres de mensajes (`docs/protocolo.md`).
- `hub.py`: `Hub` es el servidor `websockets`. Mantiene el conjunto de clientes, hace `broadcast(text|bytes)`, envía `hello` al conectar seguido de los mensajes fijos (`presence`, `set_volume`), y despacha los mensajes entrantes a callbacks registrados (`on("interrupt", cb)`, etc.). Implementa `AvatarLink` (`show_image`, `hide_image`). Nunca lanza si no hay clientes: la demo debe seguir aunque Unity se reinicie. Cada envío tiene un timeout corto: un cliente que deja de leer se descarta en vez de bloquear el bucle. El `max_size` entrante se sube a 16 MiB para que quepa un `camera_frame` de una webcam grande, y el keepalive es corto para detectar pronto a un Unity congelado.

### `sonia/panel`

Panel de control para el personal del stand (`docs/panel.md`).

- `control.py`: `StandControl`, la capa entre el panel y el motor: modos (Conversando, Solo saludos, Fuera), acciones, estado en lenguaje llano y persistencia en `cache/panel_state.json`. En "Solo saludos" y "Fuera" la sesión de GPT-Live queda cerrada y no se gasta.
- `server.py`: panel local (Starlette con uvicorn) en `PANEL_HOST:PANEL_PORT`, `http://127.0.0.1:8780` por defecto.
- `cloud.py`: conexión saliente con el panel de Cloudflare (`PANEL_CLOUD_URL` con `PANEL_CLOUD_TOKEN`), con reconexión de espera creciente.
- `events.py`, `logs.py`, `identity.py`: reparto de lo que pasa (mensajes a Unity y registro) a cada panel, últimas líneas del registro, e id estable de esta Sonia en `cache/instance_id`.

### `sonia/showcase.py`, `sonia/persona.py`

- `showcase.py`: la animación de stand. Cuando Sonia lleva `SHOWCASE_FIRST_DELAY_SECONDS` sin nadie, cada `SHOWCASE_INTERVAL_MIN/MAX_SECONDS` elige una frase de `assets/showcase/frases.md` (a veces con gesto) o un canto de `cantos.md` con baile. El motor la reproduce desde la caché de voces si está grabada o se la pide a GPT-Live por `commentary`.
- `persona.py`: el system prompt de Sonia (staff del DevFest, creada por Sonnet Code) y la carga de `assets/knowledge/*.md`.

### `sonia/cli.py`

Subcomandos con `argparse`:

- `sonia run`: demo completa. Abre el micrófono a `LIVE_SAMPLE_RATE` y arranca `LiveEngine`, el servidor WebSocket hacia Unity y el panel. Con `--no-mic` manda silencio y solo atiende `text_input`.
- `sonia chat`: pasa cada línea de la consola a GPT-Live como texto escrito e imprime lo que dice. Con `--speak` reproduce su voz localmente. También levanta el WebSocket, así que Unity puede estar conectado.
- `sonia say "texto"`: GPT-Live lee el texto con `LIVE_VOICE` (o lo guarda a WAV con `--out`).
- `sonia check`: comprueba el micrófono, la cámara, una sesión de GPT-Live (abrir y cerrar), el modelo de visión (si hay cámara) y la galería. Imprime una tabla con OK/FALLO.

`check`, `chat`, `say` y `run` usan la API de OpenAI y gastan.

## Pruebas

Los tests no necesitan hardware y jamás llaman a APIs reales. GPT-Live se sustituye por un servidor falso inyectado en el `connect` del `LiveClient`; el modelo de visión, por `httpx.MockTransport` con respuestas SSE simuladas; el audio, por arrays sintéticos; Unity, por un cliente `websockets` de prueba conectado al `Hub`.

## Latencia

No hay etapas que sumar: GPT-Live decide cuándo contestar y empieza a hablar en streaming, y su voz llega a Unity a ritmo real según se genera. Las acciones añaden la ida y vuelta al backend Responses; mientras, GPT-Live suele decir algo breve ("mira, te lo enseño"). La descripción de la cámara va en paralelo: si llega tarde, Sonia contesta igual sin esperarla.
