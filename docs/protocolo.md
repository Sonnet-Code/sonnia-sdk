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

### `activity`

Qué hace Sonia por detrás, para los efectos de la escena: `search` mientras el backend busca en internet (`web_search`), `think` si una tarea delegada en el backend lleva más de `SLOW_TASK_S` (5 s; las normales tardan unos 3,4 s) y `none` cuando no pasa nada de eso. Se manda solo al cambiar, también mientras Sonia habla (si dice «déjame buscarlo» mientras el backend sigue). Con `search` Unity enseña la lluvia estilo Matrix (`StageParticles`, al menos 2,5 s) salvo durante la trivia; con `think` no hay efecto de partículas: mientras está en `thinking`, Sonia se lleva la mano a la barbilla (`AvatarChoreographer`, el gesto `touchBeard` de Sage sostenido) y la baja al acabar la tarea o al cambiar de estado. No es fijo: no se repite tras `hello`. Una Unity que no lo conoce lo ignora.

```json
{"type": "activity", "activity": "search"}
```

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

Mostrar una imagen en el panel de la escena (acción `show_image` del backend o botón del panel). `data_base64` lleva la imagen completa. `source` indica de dónde viene: `gallery` o `agenda` (la tarjeta de una charla que dibuja el orquestador con la acción `show_talk`; Unity la trata como cualquier imagen). Si nadie la retira, el orquestador manda `hide_image` a los `IMAGE_AUTO_HIDE_SECONDS`.

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

Reproduce un clip concreto del catálogo que Unity mandó con `animations`: lo mandan los botones de «Animaciones» del bloque Avanzado del panel y la acción `play_animation` que GPT-Live delega cuando le piden a Sonia que baile o haga un gesto (`server/sonia/actions/moves.py`). A diferencia de `attention`, se atiende en cualquier estado: el clip suena una vez sobre el cuerpo y el coreógrafo vuelve después a lo que tocaba (reposo, escuchar, pensar o los gestos al hablar). Con Sonia fuera de pantalla no hace nada. Un nombre que no esté en el set se ignora con un aviso en la consola.

Sin `whole` (el panel), pasar a pensar o a hablar corta el clip. Con `whole: true` (los movimientos por voz) suena entero aunque Sonia hable mientras tanto, como las reacciones de la trivia (`AvatarChoreographer.PlayReaction`); si no, el «¡allá voy!» de Sonia lo cortaría.

```json
{"type": "play_animation", "clip": "QuickAction_vibe", "whole": true}
```

### `gesture`

Un gesto de hablar del catálogo que Unity mandó con `gesture_catalog`, elegido por el director de gestos del orquestador (`server/sonia/gestures`, ver `docs/gestos.md`) para acompañar una frase de Sonia. `name` es el nombre tal cual vino en el catálogo.

- `utterance_id` es el de la frase (`speech_start`) que acompaña. Unity lo reproduce enseguida si esa frase sigue sonando y lo descarta si ya terminó.
- `utterance_id: null` es «para la próxima frase»: Unity lo guarda hasta 4 s y lo lanza con el siguiente `speech_start` no ambiental. Es el gesto de apertura, elegido con lo que dijo el visitante mientras GPT-Live prepara la respuesta.
- Las frases `ambient` (animación de stand, «Solo saludos») nunca llevan gesto.
- Unity corta el gesto con un fundido al salir de `speaking` o con `stop_speaking`. Un gesto largo puede seguir entre frases del mismo turno.
- El orquestador ya aplica el ritmo (como mucho uno por frase, ninguno antes de que acabe el núcleo del anterior, ver `docs/gestos.md`): Unity no tiene que filtrar nada más.

```json
{"type": "gesture", "name": "noBigDeal", "utterance_id": 12}
```

### `presence`

Sonia está en pantalla (`present: true`) o se ha ido (`false`): sale caminando y deja un letrero con `message`. Lo manda el panel de control al cambiar al modo "Fuera" o volver. Es un mensaje fijo: el orquestador lo repite justo después de `hello` a cada cliente nuevo, y entonces Unity lo aplica sin animación. Ver `docs/panel.md`.

```json
{"type": "presence", "present": false, "message": "Me fui a ver una charla, regreso en un momento"}
```

### `stage_mode`

Modo del stand (`conversation`, `greeter` o `away`) y si Sonia puede conversar ahora (`talk`, GPT-Live encendida). Fijo: se repite tras `hello` y cada vez que GPT-Live se enciende o se apaga (cambio de modo, modo debug, editor de personaje, Modo Jean). La pantalla solo enseña la invitación a hablar («Acércate y pregúntame lo que quieras») con `talk: true`: en «Solo saludos», «Fuera» o en modo debug Sonia no contestaría. Una Unity que no lo conoce lo ignora; sin él, la pantalla da por hecho que sí puede conversar.

```json
{"type": "stage_mode", "mode": "greeter", "talk": false}
```

### `devices`

Respuesta a `list_devices` (y tras cada `set_device`), para el menú de opciones de Unity («Micrófono, cámara y pantalla»): los micrófonos del equipo donde corre el orquestador, el configurado (`microphone`; vacío es el del sistema, que se llama `default_microphone`; puede ser solo parte del nombre, como en el `.env`), el índice de la cámara que usa el orquestador y de dónde saca las fotos (`camera_source`). Las cámaras no van: las lista Unity (`WebCamTexture.devices`), en el mismo orden en que las abre OpenCV.

```json
{"type": "devices", "microphones": [{"name": "MacBook Pro Microphone", "default": true}], "microphone": "", "default_microphone": "MacBook Pro Microphone", "camera": 0, "camera_source": "opencv"}
```

### `set_volume`

Volumen de la voz de Sonia, de 0 a 1,5 (1 es el normal). También fijo: se repite tras `hello`.

```json
{"type": "set_volume", "value": 0.8}
```

### `set_subtitles`

Subtítulos en pantalla sí o no (interruptor del panel). Fijo: se repite tras `hello`. Apagados, Unity borra los que hubiera y no pinta ni lo que dice el visitante ni lo que dice Sonia; `transcript` sigue llegando igual.

```json
{"type": "set_subtitles", "enabled": false}
```

### `set_disabled_animations`

Clips que Sonia no debe usar por su cuenta (casillas «La usa» del panel). Fijo: se repite tras `hello`. Unity da al coreógrafo una copia del set sin esos clips; con `play_animation` siguen sonando. Desactivar el saludo apaga también el saludo automático y el de `attention` con `greeting`.

```json
{"type": "set_disabled_animations", "clips": ["Dance_Gangnam", "Dismissive"]}
```

### `set_debug`

Modo debug del panel. Fijo: se repite tras `hello`. Activo, el coreógrafo se queda sin gestos de atención, bailes, variaciones de reposo y de pensar ni asentimientos: solo los bucles base, los gestos al hablar, el caminar y el de presentar imagen. Lo que se lanza con `play_animation` suena igual. El orquestador, además, cierra GPT-Live y no saluda solo.

```json
{"type": "set_debug", "enabled": true}
```

### `set_tuning`

Ajustes de la sección «Developer» del panel. Fijo: se repite tras `hello` y cada vez que cambian (también desde otra Sonia, porque se guardan en la nube). Siempre llegan completos.

```json
{"type": "set_tuning",
 "mouth": {"open": 1.2, "jaw": 1.0, "closure": 1.0, "speed": 1.0},
 "camera": {"height": 0.05, "distance": 0.1, "side": 0.0, "zoom": 1.1, "tilt": 2.0},
 "idle": {"breath": 1.0, "accents": 0.8, "speed": 1.0}}
```

- `mouth` multiplica lo que trae la escena en `LipSyncController` (1 = tal cual): `open` la apertura de vocales y mandíbula, `jaw` la mandíbula extra de las sílabas fuertes (`jawBoost`), `closure` el cierre de labios en p, b y m (`closureWeight`) y `speed` la rapidez de la boca (`mouthSpeed` y `closureSpeed`).
- `camera` mueve el plano base de `CameraFramingController`: `height`, `distance` (positivo se aleja) y `side` (positivo, a la derecha de la pantalla) en metros; `zoom` divide la tangente del campo de visión (más de 1 acerca) y `tilt` inclina en grados (positivo mira más abajo). El plano de panel se mueve con el base; los de cuerpo entero (bailes y modo Fuera) no.
- `idle` multiplica el movimiento en reposo de `AvatarStateController.SetIdleTuning` (1 = tal cual): `breath` la respiración (pecho, hombros y cabeza), `accents` los acentos del cuerpo en las sílabas fuertes al hablar y `speed` el ritmo de la respiración y del bucle de reposo (`AvatarChoreographer.SetLoopSpeed`). Un orquestador anterior no lo manda y Unity lo deja en 1.

### `set_avatar`

Aspecto de Sonia. Fijo: se repite tras `hello` y cada vez que cambia (se guarda en la nube y vale para todas las Sonias). `definition` es la definición del avatar de Genies en texto JSON (la que guarda el editor de personaje) o `null` para el personaje que trae la app (`Assets/Sonia/Avatar/SoniaGeniesAvatar.json`). Si no es el que ya tiene puesto, Unity carga el nuevo con el SDK y lo engancha.

```json
{"type": "set_avatar", "definition": "{\"JsonVersion\": \"2-0-0\", \"equippedAssetIds\": [...], ...}"}
```

### `set_guest_avatar`

Aspecto del invitado del Modo Jean, igual que `set_avatar` pero para su avatar: fijo, se repite tras `hello` y cada vez que cambia (ajuste compartido `guest_avatar` en la nube). `null` es el avatar de prueba que trae la app (`Assets/Sonia/Avatar/JeanGeniesAvatar.json`). Unity lo carga con el SDK en su propio cargador y recuerda el último aparte del de Sonia.

```json
{"type": "set_guest_avatar", "definition": "{\"JsonVersion\": \"2-0-0\", \"equippedAssetIds\": [...], ...}"}
```

### `open_avatar_editor` y `close_avatar_editor`

Botones de «Developer» en el panel (y del modal del Modo Jean). `open_avatar_editor` pasa la pantalla de Sonia a la escena de editar personaje y `close_avatar_editor` sale de ella sin guardar. Unity contesta con `avatar_editor`.

`target` dice de quién es el personaje: `sonia` (por defecto, también si falta) o `guest`, el avatar de Jean del Modo Jean. El editor parte del aspecto actual de ese personaje y contesta con el mismo `target` en `avatar_editor` y `avatar_saved`.

```json
{"type": "open_avatar_editor", "target": "guest"}
```

### `guest_mode`

Modo Jean (`docs/modo-jean.md`): un invitado (Jean, CTO de Sonnet Code) entra en el stand y habla desde lejos con su avatar. Fijo: se repite tras `hello`; si llega nada más conectar, Unity lo aplica sin animación (invitado ya en su sitio o ya fuera).

```json
{"type": "guest_mode", "phase": "enter", "name": "Jean", "sample_rate": 24000}
```

- `enter`:
  1. Entra el avatar del invitado caminando.
  2. Sonia y él se dan la mano.
  3. Sonia sale caminando, sin letrero.
  4. El invitado queda en el centro con el plano medio.
- `leave`: el invitado se despide y sale, y Sonia vuelve.
- La voz del invitado llega en frames binarios `SNGU` (ver "Frames binarios") a `sample_rate`. Su avatar la reproduce con su propio lip-sync, cabeza, cejas y gestos.
- Unity responde con `guest_state` en cada cambio de fase.

### `guest_animation`

Un clip de una sola vez en el avatar del invitado (los mismos del catálogo de `animations`). Lo lanza Jean desde el modal del Modo Jean.

```json
{"type": "guest_animation", "clip": "WaveGeneric"}
```

### Trivia: `trivia_start`, `trivia_question`, `trivia_answer` y `trivia_end`

Modo trivia (`docs/trivia.md`). Lo conduce GPT-Live y el orquestador guarda la clave: la pantalla manda. Mientras dura la partida, `trivia_start` y la pregunta en curso son fijos y se repiten tras `hello`, así que una Unity que se reconecta vuelve a pintar la partida. Al terminar dejan de repetirse.

`trivia_start` abre la partida: Sonia se pone el gorro de fiesta, la escena pasa al tema de la trivia y sale el marcador a cero. `threshold` son los aciertos que hacen falta para ganar y `level` el nivel (fácil, intermedio o difícil), que sale en el contador. La pregunta siguiente solo llega cuando el visitante la pide (acción `trivia_next`). `trivia_end` no lleva premio: Sonia no sabe cuáles hay y a quien gana lo manda con el equipo del stand.

```json
{"type": "trivia_start", "total": 5, "threshold": 3, "level": "intermedio"}
```

`trivia_question` muestra una pregunta (`number` empieza en 1) con sus tres opciones, A, B y C en ese orden, y los aciertos que lleva. La tarjeta va en la mitad de la pantalla, sin tapar los subtítulos de abajo.

```json
{"type": "trivia_question", "number": 2, "total": 5, "question": "¿Qué significan las siglas GDG?", "options": ["Global Digital Generation", "Google Design Guild", "Google Developer Groups"], "score": 1}
```

`trivia_answer` es el resultado de esa pregunta, en cuanto se registra la respuesta. `chosen` es el índice elegido (0 a 2), o -1 si el visitante no la sabía; `correct` es el índice de la buena.
- Acierto: la opción se pone en verde, sale confeti y Sonia lo celebra.
- Fallo: la opción elegida se pone en roja, la buena en verde, y Sonia reacciona con pena.

La siguiente `trivia_question` llega `TRIVIA_REVEAL_SECONDS` después.

```json
{"type": "trivia_answer", "number": 2, "chosen": 0, "correct": 2, "is_correct": false, "score": 1}
```

`trivia_end` cierra la partida.
- `reason: "finished"`: pantalla final. Con `won` hay victoria con confeti grande y baile; sin él, una tarjeta de ánimo.
- `reason: "cancelled"`: el personal la terminó, el visitante se fue o se cayó la sesión. Todo se retira sin fanfarria.

En los dos casos Unity quita el gorro y el tema al acabar.

```json
{"type": "trivia_end", "score": 4, "total": 5, "won": true, "reason": "finished"}
```

### `camera_preview`

Enciende o apaga la vista en vivo de la cámara en la franja alta, encima de Sonia, durante los juegos que la usan (`docs/plan-juegos.md`): poses, piedra, papel o tijera y búsqueda relámpago. Es la única excepción a que las imágenes de la cámara no salgan en pantalla. Solo se muestra en directo y nunca se guarda. La imagen llega en frames binarios `SNCV` (abajo). Con `on: false`, o si pasan 2 s sin frames, Unity la retira. Solo se manda a una Unity que anuncia `camera_preview` en `client_hello.features`.

```json
{"type": "camera_preview", "on": true, "mirror": true}
```

### Juegos: `game`

Los juegos del stand (`docs/juegos.md`) mandan su pantalla en un sobre común. Unity lo reparte por `game` al controlador de ese juego, que lee su `data` con sus propias clases.

```json
{"type": "game", "game": "wordle", "event": "guess", "seq": 7, "data": {"row": 2, "letters": "LINUX", "marks": "gyxxg"}}
```

- `game`: el id del juego (`ruleta`, `poses`, `akinator`, `piedra_papel_tijera`, `wordle`, `busqueda`). Ids y eventos: minúsculas, cifras y `_`, empezando por letra (`^[a-z][a-z0-9_]{0,39}$`).
- `seq`: sube en cada mensaje de juego del orquestador, de cualquier juego. Vuelve a empezar si se reinicia el orquestador. Unity ignora un `game` con un `seq` que ya vio en la partida en marcha.
- `data`: lo de cada evento (tablas de abajo). Nunca falta: como poco, `{}`.

Dos eventos son comunes a todos los juegos:

- `start` monta la pantalla común del juego (la tarjeta de la franja alta, el plano de panel, aparta el QR y la invitación) y abre una partida. Siempre lleva `data.title`, el título en pantalla (con «Sonnia»), y lo que añada cada juego. Es siempre el primer mensaje de la partida. Un `start` con un `seq` nuevo abre partida nueva: si había otra en pantalla, se retira.
- `end` retira la pantalla. `data.result` vale `win`, `lose` o `cancel`, más lo que añada el juego. Si el juego ya enseñó su resultado con sus eventos, Unity solo hace el fundido de salida; si no y es `win` o `lose`, saca unos segundos una tarjeta de resultado genérica; con `cancel`, fuera al momento.

Mientras dura la partida, el orquestador guarda dos mensajes fijos que se repiten tras `hello`, en este orden: el `start` de la partida y el último estado del juego, los dos con su `seq` original. Así una Unity que se reconecta vuelve a montar la pantalla y una que solo perdió la conexión no repinta nada. Los efectos sueltos (un confeti) no quedan fijos. `end` no es fijo y borra los dos. Si tras un `hello` no llega en 2,5 s el `game` del juego que Unity tenía en pantalla, Unity lo da por cancelado y lo retira (como la trivia).

Unity solo recibe juegos que anunció en `client_hello.games`; los mensajes de un juego que no conoce los ignora.

#### Eventos de cada juego

Cada agente apunta los de su juego en su tabla (además de `start` y `end`). En la columna «Fijo», «sí» si el orquestador lo guarda como último estado.

##### `ruleta` (La ruleta de Sonnia, `docs/juegos/ruleta.md`)

Las casillas van siempre en este orden (`segment` es su índice): `0` trivia relámpago, `1` adivinanza geek, `2` explica en 20 segundos, `3` predice el futuro de la IA y `4` reto sorpresa de Sonnet Code. `spin` es el número de la vuelta en la partida (1, 2...). Los textos ya vienen con «Sonnia».

| Evento | Sentido | `data` | Fijo | Qué hace |
|---|---|---|---|---|
| `start` | → Unity | `title`, `segments`: `[{id, label, title, icon, off}]` (`id`: `trivia`, `adivinanza`, `explica`, `futuro` o `sonnet`; `label`, el texto de la casilla, «Trivia relámpago»; `title`, el de la tarjeta del reto, «TRIVIA RELÁMPAGO»; `icon`: `bolt`, `riddle`, `mic`, `crystal` o `star`; `off`: sin reto en esta partida, apagada) | sí (el de la partida) | Monta la ruleta quieta en la tarjeta común. |
| `spin` | → Unity | `spin`, `segment` (la casilla de destino), `duration_s` (4,6), `wins` (retos superados) | sí | Gira y frena hasta `segment`; al parar, `wheel_stopped`. Repetido con el mismo `spin` (reconexión), se ignora. |
| `wheel_stopped` | → orquestador | `spin`, `segment` | — | La ruleta paró. Si no llega en `duration_s` + 3 s, el orquestador sigue solo; uno de otra vuelta o tarde se ignora, y la casilla la manda el orquestador. |
| `challenge` | → Unity | `spin`, `segment`, `kind` (el `id` de la casilla), `title`, `prompt` (la pregunta, la adivinanza, la tecnología, la pregunta del futuro o el reto), `wins`; según el reto: `options` (las tres de la trivia), `tries` y `misses` (intentos y fallos), `hint` (la pista, vacía hasta que sale), `task` (Sonnet Code: reto de stand y no pregunta), `timer` (`{seconds, running}`: el contador empieza a correr con `running`) y `time_up` (explica: se acabó el tiempo) | sí | La tarjeta del reto. Mientras se juega llega otra vez con lo que cambia (la pista, un fallo, el contador, el «¡Tiempo!»). Si llega con la ruleta aún girando, la ruleta para ya en `segment`; si llega de una vuelta que Unity no vio girar, la pinta con la ruleta ya parada. |
| `result` | → Unity | lo de `challenge` sin `timer`, más `outcome` (`win`, `lose`, `pass`: se rindieron, o `done`: la nota y la predicción) y lo de cada reto: `chosen` y `correct` (trivia; `chosen` -1 si no lo sabía), `answer` (la solución de la adivinanza y de la pregunta de Sonnet Code), `score` (la nota, 1 a 10) o `prediction` y `probability` (0 a 100) | sí | El resultado en la tarjeta, el rótulo, el confeti y la reacción de Sonnia. Se queda hasta el siguiente `spin` o el `end`. |

`end` llega con `cancel` (la ruleta no termina sola: `stop_game`, el panel o el abandono) y la pantalla se retira al momento.

##### `poses` (Simón dice con poses, `docs/juegos/poses.md`)

| Evento | Sentido | `data` | Fijo | Qué hace |
|---|---|---|---|---|

##### `akinator` (Akinator dev, `docs/juegos/akinator.md`)

| Evento | Sentido | `data` | Fijo | Qué hace |
|---|---|---|---|---|

##### `piedra_papel_tijera` (Piedra, papel o tijera, `docs/juegos/piedra_papel_tijera.md`)

| Evento | Sentido | `data` | Fijo | Qué hace |
|---|---|---|---|---|

##### `wordle` (Wordle de tecnología, `docs/juegos/wordle.md`)

| Evento | Sentido | `data` | Fijo | Qué hace |
|---|---|---|---|---|
| `start` | orquestador → Unity | `{"title": "Wordle de tecnología", "rows": 6, "cols": 5, "hint_after": 4}` | sí | Monta la rejilla vacía de `rows`×`cols` (3 a 8 filas), la pista candada («sale tras `hint_after` intentos»; sin pista si `hint_after` es 0 o no cabe) y las 26 letras sin usar. |
| `guess` | orquestador → Unity | `{"row": 2, "letters": "LINUX", "marks": "gyxxg", "board": [{"letters": "CLOUD", "marks": "xyyxx"}, ...], "used": {"g": "LX", "y": "IO", "x": "CDNU"}, "hint": "", "result": "", "word": ""}` | sí | Un intento: las letras entran en la fila `row` (desde 0), las fichas se voltean con sus `marks` (`g` verde, `y` amarilla, `x` gris) y sale la pista si viene en `hint`. Lleva el **estado completo**: `board` con todas las filas hasta esta (para repintar tras reconectar, sin animar las ya vistas) y `used` con cada letra en su mejor color. `result` vale `win` o `lose` en el último intento y vacío mientras se juega; entonces `word` trae la palabra (y, al perder, `hint` trae siempre la pista); con `win`, confeti. Si lo terminan por voz o desde el panel con algún intento hecho, se repite el último intento (misma fila) con `result: lose`, `word` y `hint`: la misma pantalla de la derrota. |
| `invalid` | orquestador → Unity | `{"letters": "WEB", "reason": "length", "message": "Tienen que ser 5 letras"}` | no | La palabra no vale y no gasta intento: la primera fila libre se sacude con lo que se entendió (`letters`, hasta cinco letras, puede venir vacío) y un rótulo de una línea dice `message` (de 25 caracteres como mucho). `reason`: `length`, `chars`, `empty` o `repeated`. |
| `end` | orquestador → Unity | `{"word": "KAFKA", "attempts": 3, "result": "win"}` | no | El final común (lo manda el manager tras `finish`): Unity enseña su tarjeta de resultado con la palabra y los intentos y se retira. `result`: `win` o `lose` (o `cancel`, sin más datos). |

Unity no manda ningún `game_event` en este juego. Una Unity sin el controlador ignora todo esto.

##### `busqueda` (Búsqueda relámpago, `docs/juegos/busqueda.md`)

| Evento | Sentido | `data` | Fijo | Qué hace |
|---|---|---|---|---|

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

La voz del invitado del Modo Jean usa la misma cabecera con el magic `SNGU`, a la `sample_rate` de `guest_mode`. Llega en rachas: una racha es una frase, que se corta tras 500 ms de silencio y lleva unos 150 ms de colchón al empezar. Los bloques son de 60 ms. Unity la manda al reproductor del invitado, no al de Sonia. Las versiones que no la conocen la ignoran porque la marca no coincide.

## Frames binarios de la vista en vivo (`SNCV`)

Cabecera de 16 bytes, little endian, seguida de un JPEG entero. Llegan unos 10 por segundo, a 640x360, mientras `camera_preview` está encendida.

| Offset | Tamaño | Campo | Valor |
|---|---|---|---|
| 0 | 4 | magic | `SNCV` (bytes ASCII) |
| 4 | 4 | seq | uint32, sube en cada frame |
| 8 | 2 | ancho | uint16, píxeles del JPEG |
| 10 | 2 | alto | uint16 |
| 12 | 4 | flags | uint32. Bit 0: la imagen ya va en espejo. |
| 16 | n | jpeg | la imagen, con los esqueletos y las marcas del juego ya dibujados encima |

Unity muestra siempre el último frame y descarta los que lleguen con un `seq` menor. Las versiones que no lo conocen lo ignoran porque la marca no coincide.

## De Unity al orquestador

### `client_hello`

Opcional. Identifica al cliente y dice lo que sabe hacer. Unity lo manda cada vez que se conecta.

```json
{"type": "client_hello", "client": "unity", "version": "1.0.200", "games": ["ruleta", "wordle"], "features": ["camera_preview"]}
```

- `games`: los juegos cuya pantalla sabe pintar (sus controladores registrados). El orquestador solo ofrece esos. Sin `games` (una Unity anterior a los juegos), ninguno. Si se conecta una Unity que no anuncia el juego en marcha, el orquestador lo cancela.
- `features`: lo que sabe hacer además. Hoy, `camera_preview` (la vista en vivo, frames `SNCV`): sin ella no se manda `camera_preview` ni se ofrecen los juegos que la necesitan.

### `game_event`

Lo que pasa en la pantalla de un juego y le importa al orquestador (la ruleta se paró, una animación terminó). Va al juego en marcha si es el suyo; si no, se ignora. `data` puede faltar (equivale a `{}`). Los eventos de cada juego están en su tabla, arriba («Eventos de cada juego», sentido Unity → orquestador).

```json
{"type": "game_event", "game": "ruleta", "event": "wheel_stopped", "data": {"segment": 3}}
```

### `interrupt`

Interrumpir a Sonia por una vía que no es la voz: hoy, el botón "Interrumpir" de los controles de desarrollo (`-dev-ui`). El orquestador tira el resto de la respuesta en curso, le dice a GPT-Live que el visitante la ha interrumpido y envía `stop_speaking`. La interrupción por voz la gestiona GPT-Live solo (es full duplex): Unity no tiene que hacer nada para eso.

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

### `list_devices` y `set_device`

Desde el menú de opciones de Unity: `list_devices` pide los micrófonos y lo elegido (llega `devices`); `set_device` elige micrófono (`kind: microphone`, `value`: el nombre, o vacío para el del sistema) o cámara (`kind: camera`, `value`: el índice). El orquestador lo aplica al momento (reabre el micrófono; la siguiente foto ya sale de la cámara nueva) y lo guarda en ese equipo (`DEVICES_FILE`, por defecto `cache/devices.json`), que manda sobre `AUDIO_INPUT_DEVICE` y `VISION_CAMERA_INDEX` del `.env`.

```json
{"type": "list_devices"}
{"type": "set_device", "kind": "microphone", "value": "Yeti"}
{"type": "set_device", "kind": "camera", "value": 1}
```

### `animations`

Unity lo envía al recibir `hello`: el catálogo de clips que el panel puede lanzar uno a uno con `play_animation` (`AnimationCatalog.cs`). Son los clips de una sola vez del `SoniaMotionSet` en uso, sin repetir nombre; los bucles base y el ciclo de caminar se quedan fuera. `group` es `greeting`, `dance`, `fourth_wall`, `soft`, `talking`, `idle_variation`, `thinking`, `nod` o `present`. El orquestador lo guarda tal cual (hasta 200 entradas, nombres de hasta 80 caracteres) y lo publica en el estado del panel.

```json
{"type": "animations", "animations": [{"clip": "Greeting", "group": "greeting"}, {"clip": "Dance_HipHop", "group": "dance"}]}
```

### `gesture_catalog`

Unity lo envía al recibir `hello`, junto a `animations`: los gestos de hablar de Genies que puede reproducir (los de Sage), cada uno con la ficha que Genies le da a su LLM (`llmMetadata`). El orquestador lo usa para el director de gestos (`docs/gestos.md`) y lo reemplaza entero en cada reconexión. Sin este mensaje, el director no pide nada.

- `character`: de quién son los gestos. `transition_s`: fundido de entrada de Unity hacia cada gesto, en segundos.
- Por gesto: `name` (único, hasta 80 caracteres); `lists`, las listas de Genies (`Utility_NoImpact` marca los de relleno neutro); `duration`, `core_start` y `core_stop` en segundos del clip (el núcleo: antes de `core_stop` no empieza otro gesto); `critical_beat` y `min_duration` (pueden ser `null`); `held`; `frequency` (`Standard`, `Uncommon` o `Rare`); `timing` (`Instant`, `Short` o `Long`); `impact` (`NoImpact`, `LowImpact`, `HighImpact` o vacío); `intensity` (1 a 4); `special`; `description`, la descripción física; `intents`; `intent_description`, las reglas «USE: ... DO NOT USE: ...» (o vacío), y `tags`.
- El orquestador es tolerante: un campo que falta toma su valor por defecto, los números pueden llegar como texto, una frecuencia desconocida cuenta como `Standard` y los nombres repetidos se ignoran (hasta 400 gestos).

```json
{"type": "gesture_catalog", "character": "Sage", "transition_s": 0.8,
 "gestures": [{"name": "noBigDeal", "lists": ["Sage(IDset)"], "duration": 3.63,
   "core_start": 0.4, "core_stop": 2.1, "critical_beat": 1.0, "held": false, "min_duration": 1.5,
   "frequency": "Standard", "timing": "Short", "impact": "LowImpact", "intensity": 2, "special": false,
   "description": "Raises right hand ...", "intents": ["To Dismiss"],
   "intent_description": "USE: ...\nDO NOT USE: ...", "tags": ["descriptor:Neutral", "personality:Poised"]}]}
```

### `animation_playing`

Qué clip de una sola vez suena ahora en el avatar (capa de cuerpo, luego torso y luego brazo), o `null` si solo suena un bucle base. Unity lo manda cuando cambia y otra vez tras cada `hello`; el panel resalta ese botón de «Animaciones», también cuando Sonia lo hace por su cuenta.

```json
{"type": "animation_playing", "clip": "Dance_Jazz"}
```

### `avatar_editor`

La escena de editar personaje se abrió (`open: true`) o se cerró (`open: false`, se guardara o no). Mientras está abierta el orquestador no abre GPT-Live; al cerrarse, Sonia vuelve a su modo. `target` repite el de `open_avatar_editor` (sin él, `sonia`).

```json
{"type": "avatar_editor", "open": true, "target": "sonia"}
```

### `avatar_saved`

Se pulsó Guardar en el editor de personaje. `definition` es la definición del avatar de Genies en texto JSON (un objeto, hasta 64 KB, con alguna pieza en `equippedAssetIds`). El orquestador la valida, la guarda en la nube como ajuste compartido y la reparte: con `target` `sonia` (o sin `target`) es el ajuste `avatar` y va en `set_avatar`; con `guest` es `guest_avatar` y va en `set_guest_avatar`, sin tocar a Sonia.

```json
{"type": "avatar_saved", "definition": "{\"JsonVersion\": \"2-0-0\", ...}", "target": "guest"}
```

### `guest_state`

Fase del Modo Jean en la pantalla: `entering` (entrando), `live` (el invitado ya está y habla), `leaving` (despidiéndose) y `off` (Sonia de vuelta). El orquestador espera `live` como mucho 25 s y `off` como mucho 20 s. Si no llegan, sigue igual: una app antigua no deja el modo colgado.

```json
{"type": "guest_state", "phase": "live"}
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
  |<--- state: listening ------------------|   (solo con VISION_ON_TURN_START=true, en paralelo:
  |                                        |    foto → modelo de visión → nota "[Cámara] ...")
  |<--- transcript(user, final) -----------|   (pausa del visitante)
  |<--- state: thinking -------------------|
  |<--- gesture(null) ---------------------|   (apertura: el director de gestos, con lo que dijo el visitante)
  |<--- speech_start(1) -------------------|<--- primer audio con voz de Sonia
  |<--- state: speaking -------------------|
  |<--- [binario 1] x N -------------------|<--- audio a ritmo real (100 ms)
  |<--- transcript(assistant, parcial) ----|<--- transcripción de Sonia
  |<--- transcript(assistant, final) ------|   (800 ms de silencio en su voz)
  |<--- speech_end(1) ---------------------|
  |<--- show_image ------------------------|<--- acción delegada en el backend Responses
  |<--- speech_start(2) ... ---------------|   (siguiente tramo de voz)
  |<--- gesture(2) ------------------------|   (el gesto de esa frase, si el director elige uno)
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
