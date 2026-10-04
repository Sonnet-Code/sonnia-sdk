# Protocolo entre el orquestador y Unity

Versión 1. Un WebSocket local, por defecto en `ws://127.0.0.1:8765/`. El orquestador es el servidor; Unity (o cualquier otro cliente, por ejemplo la consola de pruebas) es el cliente. Puede haber varios clientes conectados a la vez; todos reciben lo mismo.

Hay dos tipos de frames:

- **Texto**: JSON con un campo `type` obligatorio. Todo lo que no es audio va aquí.
- **Binario**: audio PCM con una cabecera fija de 12 bytes. Solo del orquestador hacia Unity.

Los identificadores de frase (`utterance_id`) son enteros crecientes dentro de la sesión.

Al otro lado del orquestador está GPT-Live de OpenAI (ADR 007), que oye el micrófono y habla con su propia voz. Este protocolo no sabe nada de eso: el orquestador traduce la voz de GPT-Live a frases, estados y transcripciones para Unity.

## Del orquestador a Unity

### `hello`

Primer mensaje tras conectar. Anuncia el formato del audio que vendrá: la tasa es `LIVE_SAMPLE_RATE` (24000 por defecto, 16000 si el micrófono no abre a 24 kHz). Justo después llegan los mensajes fijos (`presence`, `set_volume`).

```json
{"type": "hello", "version": 1, "sample_rate": 24000, "channels": 1, "format": "pcm_s16le"}
```

### `state`

Cambio de estado del asistente. Unity lo usa para disparar animaciones.

```json
{"type": "state", "state": "idle"}
```

Valores: `idle`, `listening`, `thinking`, `speaking`. GPT-Live no emite eventos de turno, así que el orquestador los deduce: `listening` mientras llega transcripción del visitante, `thinking` tras su turno o mientras el backend ejecuta una acción, `speaking` con el primer audio de Sonia, `idle` cuando Unity termina de reproducir.

### `transcript`

Texto de lo que dice el visitante (`user`) o Sonia (`assistant`), para los subtítulos y el panel. `final` es `false` mientras el texto sigue creciendo; cada mensaje trae el texto acumulado, no solo lo nuevo.

```json
{"type": "transcript", "role": "user", "text": "hola sonia", "final": true}
```

- `user`: llega con `final: false` mientras el visitante habla y con `final: true` al cerrar su turno. Las marcas de sonido de la transcripción de GPT-Live ("[laugh]", "[sigh]") se quitan antes de enviarlo.
- `assistant`: crece a la vez que suena la voz de Sonia y termina con un `final: true` justo antes de `speech_end` de esa frase.

### `speech_start`

Empieza una frase de Sonia. A partir de aquí llegarán frames binarios con ese `utterance_id`. Una frase es un tramo continuo de voz de GPT-Live: se cierra cuando lleva `LIVE_SEGMENT_GAP_MS` (800 ms) en silencio. Como GPT-Live manda audio sin parar, también cuando calla (silencio digital), el orquestador corta por nivel de voz y no manda a Unity el silencio de los extremos. `text` puede llegar vacío: la transcripción de Sonia va un poco por detrás de su audio y se completa con `transcript`.

```json
{"type": "speech_start", "utterance_id": 7, "text": "Hola, ¿cómo estás?"}
```

Con `"ambient": true` es una frase de la **animación de stand** o del modo
"Solo saludos" (lo que Sonia dice sola cuando lleva un rato sin nadie, o lo
que "canta" mientras baila, normalmente reproducido desde la caché de voces):
el estado no cambia, sigue en `idle`, y Unity solo mueve la boca, las cejas y
los ojos sin interrumpir el baile ni el gesto en curso.

```json
{"type": "speech_start", "utterance_id": 8, "text": "¡Lalalá, esto es DevFest!", "ambient": true}
```

### `visemes` y `envelope` (no se envían)

El orquestador ya no los manda: el lip-sync sale de los fonemas del audio, que Unity analiza en tiempo real con uLipSync. Unity los sigue entendiendo como respaldo por si algún día vuelven (visemas Oculus con su instante `t` en segundos relativo a `speech_start`, o una envolvente de amplitud de 0 a 1 cada `interval_ms`):

```json
{"type": "visemes", "utterance_id": 7, "frames": [{"t": 0.00, "v": "oh", "w": 1.0}, {"t": 0.12, "v": "aa", "w": 1.0}]}
{"type": "envelope", "utterance_id": 7, "interval_ms": 20, "values": [0.0, 0.31, 0.62]}
```

Ids de visema (conjunto Oculus, compatible con Ready Player Me): `sil`, `PP`, `FF`, `TH`, `DD`, `kk`, `CH`, `SS`, `nn`, `RR`, `aa`, `E`, `ih`, `oh`, `ou`.

### `speech_end`

No habrá más audio de esa frase. Unity responde con `playback_done` cuando termine de reproducir lo que tenga en cola.

```json
{"type": "speech_end", "utterance_id": 7}
```

### `stop_speaking`

Interrupción. Unity descarta inmediatamente todo el audio en cola y deja de mover la boca. Se envía cuando Unity manda `interrupt` o cuando el personal pulsa "Callar a Sonia" en el panel. Cuando el visitante la interrumpe hablando no hace falta: GPT-Live deja de mandar voz por sí mismo, y como la manda a ritmo real Unity apenas tiene nada en cola.

```json
{"type": "stop_speaking", "reason": "interrupted"}
```

### `show_image`

Mostrar una imagen en el panel de la escena (acción `show_image` del backend o botón del panel). `data_base64` lleva la imagen completa. `source` indica de dónde viene: `gallery` o `camera`. Si nadie la retira, el orquestador manda `hide_image` a los `IMAGE_AUTO_HIDE_SECONDS`.

```json
{"type": "show_image", "image_id": "logo-sonnet", "source": "gallery", "mime": "image/png", "data_base64": "...", "caption": "Sonnet Code"}
```

### `hide_image`

```json
{"type": "hide_image"}
```

### `attention`

Pide al avatar un gesto de atención: `dance` (baile), `fourth_wall` (señalar,
saludar, tocar la pantalla), `soft` (gesto suave) o `greeting` (saludo con la mano). `clip` es opcional y nombra
un clip concreto del set. Se atiende en `idle`; `greeting` también mientras escucha. La animación de stand lo
envía justo antes de una frase `ambient` para que Sonia cante mientras baila.

```json
{"type": "attention", "category": "dance"}
```

### `play_animation`

Reproduce un clip concreto del catálogo que Unity mandó con `animations` (botones de «Animaciones» en el bloque Avanzado del panel). A diferencia de `attention`, se atiende en cualquier estado: el clip suena una vez sobre el cuerpo y el coreógrafo vuelve después a lo que tocaba (reposo, escuchar, pensar o los gestos al hablar). Con Sonia fuera de pantalla no hace nada. Un nombre que no esté en el set se ignora con un aviso en la consola.

```json
{"type": "play_animation", "clip": "Dance_HipHop"}
```

### `presence`

Sonia está en pantalla (`present: true`) o se ha ido (`false`): sale caminando y deja un letrero con `message`. Lo manda el panel de control al cambiar al modo "Fuera" o volver. Es un mensaje fijo: el orquestador lo repite justo después de `hello` a cada cliente nuevo, y entonces Unity lo aplica sin animación. Ver `docs/panel.md`.

```json
{"type": "presence", "present": false, "message": "Me fui a ver una charla, regreso en un momento"}
```

### `set_volume`

Volumen de la voz de Sonia, de 0 a 1,5 (1 es el normal). También fijo: se repite tras `hello`.

```json
{"type": "set_volume", "value": 0.8}
```

### `error`

```json
{"type": "error", "message": "descripción legible"}
```

## Frames binarios (audio)

Cabecera de 12 bytes, little endian, seguida del PCM s16le mono (la voz de GPT-Live tal cual llega, sin remuestrear):

| Offset | Tamaño | Campo | Valor |
|---|---|---|---|
| 0 | 4 | magic | `SNIA` (bytes ASCII) |
| 4 | 4 | utterance_id | uint32 |
| 8 | 4 | flags | uint32. Bit 0: último chunk de la frase. |
| 12 | n | pcm | muestras int16 LE, mono, a la tasa anunciada en `hello` |

Los chunks son de unos 100 ms y llegan a ritmo real. Unity los encola en un buffer circular y los reproduce sin esperar a que llegue la frase completa. El último chunk de una frase (bit 0 de `flags`) puede ir vacío.

## De Unity al orquestador

### `client_hello`

Opcional. Identifica al cliente.

```json
{"type": "client_hello", "client": "unity", "version": "0.1.0"}
```

### `interrupt`

Interrumpir a Sonia por una vía que no es la voz: hoy, el botón "Interrumpir" o la tecla Escape de los controles de desarrollo (`-dev-ui`). El orquestador tira el resto de la respuesta en curso, le dice a GPT-Live que el visitante la ha interrumpido y envía `stop_speaking`. La interrupción por voz la gestiona GPT-Live solo (es full duplex): Unity no tiene que hacer nada para eso.

```json
{"type": "interrupt"}
```

### `playback_done`

Unity terminó de reproducir la última frase que recibió (`speech_end` ya llegó y el buffer está vacío). El orquestador pasa a `idle` cuando ha recibido `playback_done` de la última frase (o pasado un margen sobre la duración del audio, por si Unity no responde).

```json
{"type": "playback_done", "utterance_id": 7}
```

### `text_input`

Entrada de texto en lugar de voz. Sirve para probar sin micrófono (`sonia run --no-mic`, la caja de texto de los controles de desarrollo, `scripts/ws_probe.py`). Se le pasa a GPT-Live como un texto que el visitante ha escrito en la pantalla (`session.commentary.append`, que es lo que la hace hablar) y Sonia responde en voz alta igual que a un turno hablado.

```json
{"type": "text_input", "text": "¿Qué es Sonnet Code?"}
```

### `camera_frame`

Si `VISION_SOURCE=unity`, Unity envía capturas de su `WebCamTexture` cuando el orquestador se las pide con `request_frame` o de forma periódica. El orquestador se queda con la última.

```json
{"type": "camera_frame", "mime": "image/jpeg", "data_base64": "..."}
```

### `animations`

Unity lo envía al recibir `hello`: el catálogo de clips que el panel puede lanzar uno a uno con `play_animation` (`AnimationCatalog.cs`). Son los clips de una sola vez del `SoniaMotionSet` en uso, sin repetir nombre; los bucles base y el ciclo de caminar se quedan fuera. `group` es `greeting`, `dance`, `fourth_wall`, `soft`, `talking`, `idle_variation`, `thinking`, `nod` o `present`. El orquestador lo guarda tal cual (hasta 200 entradas, nombres de hasta 80 caracteres) y lo publica en el estado del panel.

```json
{"type": "animations", "animations": [{"clip": "Greeting", "group": "greeting"}, {"clip": "Dance_HipHop", "group": "dance"}]}
```

### `request_frame` (orquestador → Unity)

Solo cuando `VISION_SOURCE=unity`. Unity responde con un `camera_frame` lo antes posible.

```json
{"type": "request_frame"}
```

## Secuencia típica de un turno

```
Unity                                  Orquestador                       GPT-Live
  |                                        |==== micrófono continuo =======>|  (también mientras habla Sonia)
  |<--- transcript(user, parcial) ---------|<--- transcripción del visitante |
  |<--- state: listening ------------------|   (y en paralelo: foto de la cámara → modelo de visión
  |                                        |    → nota "[Cámara] ..." a GPT-Live)
  |<--- transcript(user, final) -----------|   (pausa del visitante)
  |<--- state: thinking -------------------|
  |<--- speech_start(1) -------------------|<--- primer audio con voz de Sonia
  |<--- state: speaking -------------------|
  |<--- [binario 1] x N -------------------|<--- audio a ritmo real (100 ms)
  |<--- transcript(assistant, parcial) ----|<--- transcripción de Sonia
  |<--- transcript(assistant, final) ------|   (800 ms de silencio en su voz)
  |<--- speech_end(1) ---------------------|
  |<--- show_image ------------------------|<--- acción delegada en el backend Responses
  |<--- speech_start(2) ... ---------------|   (siguiente tramo de voz)
  |---- playback_done(1) ----------------->|
  |---- playback_done(2) ----------------->|
  |<--- state: idle -----------------------|
```

Si el visitante habla mientras Sonia contesta, GPT-Live se calla solo: la frase en curso se cierra como cualquier otra y, en cuanto deja de sonar, el estado vuelve a `listening`. Si Unity manda `interrupt` (o el panel "Callar a Sonia"):

```
  |---- interrupt ------------------------>|
  |<--- stop_speaking(interrupted) --------|
```

## Reglas

- Unity nunca debe bloquearse esperando un mensaje concreto. Cualquier mensaje puede llegar en cualquier momento.
- Mensajes con `type` desconocido se ignoran en ambos sentidos.
- Si cambia el protocolo, se actualiza este documento, `server/sonia/ws/protocol.py` y `unity/Assets/Scripts/Sonia/Protocol.cs` en el mismo commit.
