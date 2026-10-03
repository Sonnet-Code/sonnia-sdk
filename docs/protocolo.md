# Protocolo entre el orquestador y Unity

Versión 1. Un WebSocket local, por defecto en `ws://127.0.0.1:8765/`. El orquestador es el servidor; Unity (o cualquier otro cliente, por ejemplo la consola de pruebas) es el cliente. Puede haber varios clientes conectados a la vez; todos reciben lo mismo.

Hay dos tipos de frames:

- **Texto**: JSON con un campo `type` obligatorio. Todo lo que no es audio va aquí.
- **Binario**: audio PCM con una cabecera fija de 12 bytes. Solo del orquestador hacia Unity.

Los tiempos (`t`) van en segundos y son relativos al inicio de la frase (`speech_start`) a la que pertenecen. Los identificadores de frase (`utterance_id`) son enteros crecientes dentro de la sesión.

## Del orquestador a Unity

### `hello`

Primer mensaje tras conectar. Anuncia el formato del audio que vendrá.

```json
{"type": "hello", "version": 1, "sample_rate": 24000, "channels": 1, "format": "pcm_s16le"}
```

### `state`

Cambio de estado del asistente. Unity lo usa para disparar animaciones.

```json
{"type": "state", "state": "idle"}
```

Valores: `idle`, `listening`, `thinking`, `speaking`.

### `transcript`

Texto de lo que dijo el usuario o de lo que va a decir Sonia. Útil para subtítulos y depuración. `final` es `false` mientras el texto sigue creciendo.

```json
{"type": "transcript", "role": "user", "text": "hola sonia", "final": true}
```

### `speech_start`

Empieza una frase sintetizada. A partir de aquí llegarán frames binarios con ese `utterance_id`.

```json
{"type": "speech_start", "utterance_id": 7, "text": "Hola, ¿cómo estás?"}
```

Con `"ambient": true` es una frase de la **animación de stand** (lo que Sonia
dice sola cuando lleva un rato sin nadie, o lo que "canta" mientras baila): el
estado no cambia, sigue en `idle`, y Unity solo mueve la boca, las cejas y los
ojos sin interrumpir el baile ni el gesto en curso.

```json
{"type": "speech_start", "utterance_id": 8, "text": "¡Lalalá, esto es DevFest!", "ambient": true}
```

### `visemes`

Visemas de la frase, con su instante de inicio relativo a `speech_start`. Se calculan sobre la duración total del audio, así que llegan siempre **después** de los frames binarios de esa frase, en cuanto termina de sintetizarse: normalmente cuando Unity apenas ha empezado a reproducirla, pero nunca antes del primer frame. Hoy son una **estimación por texto** (grafema a visema, repartida uniformemente en la duración): Unity los usa solo como respaldo cuando no puede analizar fonemas en tiempo real sobre el audio, porque tomarlos como fuente principal desincronizaba la boca en la cola de cada frase. Si algún día el TTS entrega tiempos reales por fonema, este mensaje es el sitio para mandarlos. Los ids son los del conjunto Oculus (compatible con Ready Player Me): `sil`, `PP`, `FF`, `TH`, `DD`, `kk`, `CH`, `SS`, `nn`, `RR`, `aa`, `E`, `ih`, `oh`, `ou`.

```json
{"type": "visemes", "utterance_id": 7, "frames": [{"t": 0.00, "v": "oh", "w": 1.0}, {"t": 0.12, "v": "aa", "w": 1.0}]}
```

### `envelope`

Envolvente de amplitud de la frase, un valor entre 0 y 1 cada `interval_ms`. Sirve como lip-sync de respaldo si el avatar no tiene blendshapes de visemas. Llega junto a `visemes`, con las mismas garantías de orden.

```json
{"type": "envelope", "utterance_id": 7, "interval_ms": 20, "values": [0.0, 0.31, 0.62]}
```

### `speech_end`

No habrá más audio de esa frase. Unity responde con `playback_done` cuando termine de reproducir lo que tenga en cola.

```json
{"type": "speech_end", "utterance_id": 7}
```

### `stop_speaking`

Interrupción. Unity descarta inmediatamente todo el audio en cola y deja de mover la boca.

```json
{"type": "stop_speaking", "reason": "interrupted"}
```

### `show_image`

Mostrar una imagen en el panel de la escena. `data_base64` lleva la imagen completa. `source` indica de dónde viene: `gallery` o `camera`.

```json
{"type": "show_image", "image_id": "logo-sonnet", "source": "gallery", "mime": "image/png", "data_base64": "...", "caption": "Sonnet Code"}
```

### `hide_image`

```json
{"type": "hide_image"}
```

### `attention`

Pide al avatar un gesto de atención: `dance` (baile), `fourth_wall` (señalar,
saludar, tocar la pantalla) o `soft` (gesto suave). `clip` es opcional y nombra
un clip concreto del set. Solo se atiende en `idle`. La animación de stand lo
envía justo antes de una frase `ambient` para que Sonia cante mientras baila.

```json
{"type": "attention", "category": "dance"}
```

### `error`

```json
{"type": "error", "message": "descripción legible"}
```

## Frames binarios (audio)

Cabecera de 12 bytes, little endian, seguida del PCM s16le mono:

| Offset | Tamaño | Campo | Valor |
|---|---|---|---|
| 0 | 4 | magic | `SNIA` (bytes ASCII) |
| 4 | 4 | utterance_id | uint32 |
| 8 | 4 | flags | uint32. Bit 0: último chunk de la frase. |
| 12 | n | pcm | muestras int16 LE, mono, a la tasa anunciada en `hello` |

Los chunks son de unos 100 ms. Unity los encola en un buffer circular y los reproduce sin esperar a que llegue la frase completa.

## De Unity al orquestador

### `client_hello`

Opcional. Identifica al cliente.

```json
{"type": "client_hello", "client": "unity", "version": "0.1.0"}
```

### `interrupt`

El usuario ha interrumpido (por ejemplo tocando la pantalla). El orquestador cancela la generación y la síntesis en curso, y envía `stop_speaking`. La interrupción por voz la detecta el propio orquestador con el VAD; Unity no tiene que hacer nada para eso.

```json
{"type": "interrupt"}
```

### `playback_done`

Unity terminó de reproducir la última frase que recibió (`speech_end` ya llegó y el buffer está vacío). El orquestador pasa a `idle` cuando ha recibido `playback_done` de la última frase del turno.

```json
{"type": "playback_done", "utterance_id": 7}
```

### `text_input`

Entrada de texto en lugar de voz. Sirve para probar sin micrófono. Se procesa exactamente igual que un turno hablado.

```json
{"type": "text_input", "text": "¿Qué es Sonnet Code?"}
```

### `camera_frame`

Si `VISION_SOURCE=unity`, Unity envía capturas de su `WebCamTexture` cuando el orquestador se las pide con `request_frame` o de forma periódica. El orquestador se queda con la última.

```json
{"type": "camera_frame", "mime": "image/jpeg", "data_base64": "..."}
```

### `request_frame` (orquestador → Unity)

Solo cuando `VISION_SOURCE=unity`. Unity responde con un `camera_frame` lo antes posible.

```json
{"type": "request_frame"}
```

## Secuencia típica de un turno

```
Unity                                  Orquestador
  |<--- state: listening ------------------|   (VAD detecta voz; captura de cámara)
  |<--- state: thinking -------------------|   (fin de voz; STT; petición al modelo)
  |<--- transcript(user, final) -----------|
  |<--- speech_start(1) -------------------|   (primera frase lista)
  |<--- state: speaking -------------------|
  |<--- [binario 1] x N -------------------|
  |<--- visemes(1) / envelope(1) ----------|
  |<--- speech_end(1) ---------------------|
  |<--- speech_start(2) ... ---------------|   (mientras el modelo sigue generando)
  |---- playback_done(1) ----------------->|
  |<--- show_image ------------------------|   (si el modelo llamó a show_image)
  |---- playback_done(2) ----------------->|
  |<--- state: idle -----------------------|
```

Si el usuario habla en mitad de la respuesta y `AUDIO_BARGE_IN=true`:

```
  |<--- stop_speaking(interrupted) --------|
  |<--- state: listening ------------------|
```

## Con el motor GPT-Live

Con `VOICE_ENGINE=live` (ADR 007) el protocolo es el mismo, con estas diferencias de uso:

- `hello` anuncia `LIVE_SAMPLE_RATE` (24000 por defecto).
- Cada tramo de voz de GPT-Live separado por un silencio de `LIVE_SEGMENT_GAP_MS` es una frase. `speech_start` puede llegar con `text` vacío, porque la transcripción va un poco por detrás del audio.
- El texto de Sonia viaja como `transcript` de `assistant` con `final: false`, creciendo a la vez que suena la voz, y un último `final: true` justo antes de `speech_end`. El HUD pinta los trozos según llegan; el motor anterior nunca manda `final: false` para Sonia.
- Lo que dice el visitante llega igual: `transcript` de `user` con `final: false` mientras habla y `final: true` al cerrar su turno.
- No se envían `visemes` ni `envelope`: el lip-sync sale de los fonemas del audio (uLipSync).
- `stop_speaking` solo se envía cuando Unity manda `interrupt`: GPT-Live deja de hablar por sí mismo cuando le interrumpen por voz.
- Los estados se deducen: `listening` mientras llega transcripción del visitante, `thinking` tras su turno o mientras el backend ejecuta una acción, `speaking` con el primer audio de Sonia, `idle` después.

## Reglas

- Unity nunca debe bloquearse esperando un mensaje concreto. Cualquier mensaje puede llegar en cualquier momento.
- Mensajes con `type` desconocido se ignoran en ambos sentidos.
- Si cambia el protocolo, se actualiza este documento, `server/sonia/ws/protocol.py` y `unity/Assets/Scripts/Sonia/Protocol.cs` en el mismo commit.
