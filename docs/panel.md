# Panel de control de Sonia

Panel web para que el personal del stand (no necesariamente técnico) controle a Sonia en vivo. Vive en **Cloudflare** (`https://sonia.sonnetcode.com`, Worker `sonia-panel` con un Durable Object, código en `cloud/panel/`) y cada Sonia, esté en el equipo que esté, se conecta a él hacia fuera por WebSocket: no hace falta abrir puertos ni túneles en el equipo del stand. Así el panel ve **todas** las Sonias conectadas: puede haber varias a la vez en sitios distintos (en el stand solo habrá una) y se elige cuál se controla, cambiando de una a otra cuando haga falta (ver «Varias Sonias»).

El orquestador sigue sirviendo el mismo panel en `http://127.0.0.1:8780/` como respaldo local: funciona sin internet (por ejemplo, para pasar a "Solo saludos" si cae la red) y solo ve a la Sonia de ese equipo.

## Modos de Sonia

| Modo | Qué hace | Gasta |
|---|---|---|
| `conversation` (Conversando) | GPT-Live abierto: oye, conversa, usa la cámara y las acciones. | Sesión de GPT-Live (0,05 USD/min) y modelo de visión. |
| `greeter` (Solo saludos) | Sin conversación: no oye ni mira. Cada cierto tiempo saluda, hace un gesto o baila diciendo una frase grabada con su voz. | Nada: las frases salen de la caché de voces (`cache/voice`). |
| `away` (Fuera) | Se va de la pantalla caminando y deja un letrero ("Me fui a ver una charla, regreso en un momento"). | Nada. |

## Dónde se guardan los ajustes

Los ajustes son de Sonia, no de un equipo: el texto del letrero, los avisos del día, el volumen, la sensibilidad del micrófono, la voz, la animación de stand, los subtítulos, las animaciones que no usa por su cuenta, los de «Developer» (boca, cámara y movimiento en reposo) y los personajes guardados en el editor (el de Sonia y el de Jean del Modo Jean) se guardan **en la nube** y valen para todas las Sonias (`SHARED_SETTINGS` en `server/sonia/panel/control.py`). Da igual desde dónde se cambien, el panel de Cloudflare o el local (`http://127.0.0.1:8780`): el orquestador los aplica al momento y los sube a la nube, que los reparte a las demás Sonias conectadas.

Cada orquestador guarda además una copia en `cache/panel_state.json`, así que sin internet arranca con lo último que supo y lo que se cambie desde el panel local queda apuntado como pendiente (`pending_settings`) hasta que la nube lo confirma al volver la conexión. Si con la red caída se cambia algo aquí y otra Sonia cambia lo mismo, gana el último cambio que llega a la nube.

El modo (Conversando, Solo saludos, Fuera), el modo debug y el gasto del día son de cada Sonia y no viajan a la nube: con varias Sonias encendidas, cada una sigue en su modo y desde el panel de Cloudflare se elige cuál se controla (ver «Varias Sonias»). Esos se guardan solo en `cache/panel_state.json` y se recuperan si el orquestador se reinicia (un reinicio estando "Fuera" no la trae de vuelta).

El estado lo dice en `settings_sync`, y el panel lo muestra arriba de «Avanzado» y de «Developer»: guardado en la nube, guardando, sin conexión (con lo que falta por subir) o sin nube configurada (falta `PANEL_CLOUD_TOKEN`).

La caché de voces guarda cada frase fija (saludos, frases y cantos del stand) leída una vez por GPT-Live con la voz configurada. Se rellena sola en segundo plano cuando hay clave y Sonia está en `conversation`, o con el botón "Preparar voces". Las frases del modo saludos están en `assets/showcase/saludos.md`.

## Ver cámara

«Ver cámara», en «Acciones rápidas», abre un visor con la cámara del stand en directo y sus estadísticas (fps, kbit/s, tamaño y calidad, ida y vuelta). No hay micro ni secuencia: es solo para ver qué pasa en el stand.

Con `PANEL_CAMERA_STREAM=false` la Sonia no manda ni la cámara ni el micrófono al panel: sin «Ver cámara» ni Modo Jean. Lo llevan las builds de prueba que se reparten al equipo (`build.env`, ver `docs/unity.md`, «Builds de prueba»), para que nadie del panel vea ni oiga a quien la prueba en casa.

Con `TRIAL_LIMIT_MINUTES` (las builds de prueba llevan 300), la Sonia tiene ese tiempo de conversación en total, sumando todos sus arranques. Al acabarse:
- se queda en «Fuera» con el letrero «La prueba de Sonnia ha terminado» y no vuelve a abrir GPT-Live;
- el panel rechaza devolverla a otro modo.

- Va por la sala de vídeo de Cloudflare (`/api/guest` con `role=watch`, la misma del Modo Jean), así que solo funciona desde el panel de la nube. En el local lo dice y no muestra nada.
- El visor pide la sala con la acción `watch_camera` y la renueva cada 10 s mientras está abierto (`keepalive`, que no llena el registro).
- El orquestador (`RoomSupervisor`, `server/sonia/guest/room.py`) la cierra sola cuando no queda nadie mirando durante 25 s, o 3 s después de pulsar «Cerrar».
- No cierra GPT-Live, no anuncia nada y no manda nada a Unity.
- El micro del stand no sale. Con el Modo Jean activo, el visor solo se suma a la sala y la sala le sigue negando el micro: el audio va solo al modal de Jean.
- La cámara es la misma de la visión de Sonia: con `VISION_SOURCE=opencv`, el mismo `OpenCVCamera` (un solo dispositivo abierto; las capturas se turnan y leen y codifican en un hilo, fuera del bucle). Con la visión apagada, la sala abre la cámara por su cuenta y la suelta al cerrarse; con `VISION_SOURCE=unity`, usa la de Unity.
- Mientras alguien mira, la cabecera del panel muestra «Cámara en directo: N mirando» (en el móvil, el icono de la cámara y N) y la fila de la cámara de «¿Funciona todo?» lo repite.

## Mensajes nuevos del protocolo con Unity

Se suman a `docs/protocolo.md` (versión 1, sin romper nada: Unity ignora tipos desconocidos).

### `presence` (orquestador → Unity)

```json
{"type": "presence", "present": false, "message": "Me fui a ver una charla, regreso en un momento"}
```

- `present: false`: Unity corta la voz y la boca, retira el panel de imagen, Sonia se gira hacia un lado de la pantalla y sale caminando hasta quedar fuera de cuadro; al salir aparece el letrero con `message`.
- `present: true`: se retira el letrero, Sonia entra caminando desde el mismo lado hasta su sitio, se gira hacia la cámara y vuelve al idle.
- Es un mensaje "fijo": el orquestador lo repite justo después de `hello` a cada cliente que se conecta. Si Unity arranca o se reconecta estando fuera, aplica el estado sin animación (Sonia ya fuera y letrero visible).
- Un `presence` con el mismo `present` y otro `message` solo cambia el texto del letrero.

### `set_volume` (orquestador → Unity)

```json
{"type": "set_volume", "value": 0.8}
```

Volumen de la voz de Sonia, de 0 a 1,5 (1 = normal). También es fijo: se repite tras `hello`.

### `attention` con `category: "greeting"`

Además de `dance`, `fourth_wall` y `soft`, `greeting` hace el saludo con la mano (`motionSet.greeting`).

### `animations` (Unity → orquestador) y `play_animation` (orquestador → Unity)

Unity manda al recibir `hello` la lista de clips que se pueden lanzar uno a uno (`AnimationCatalog.cs`: todo lo de una sola vez del set, sin los bucles base ni el caminar). El orquestador la publica en `animations` del estado y el bloque «Animaciones» de Avanzado (plegado de entrada, porque son muchas) pinta un botón por clip, agrupados (saludo, bailes, hacia el público, gestos suaves, al hablar, en reposo, pensando, escuchando). Cada botón manda la acción `animation` y el orquestador la pasa a Unity como `play_animation`. Unity avisa con `animation_playing` de qué clip suena (también los que Sonia hace sola) y el panel pinta ese botón en azul. La casilla «La usa» de cada ficha manda `set_animation_enabled`; las desmarcadas viajan a Unity en el mensaje fijo `set_disabled_animations` y Sonia deja de hacerlas por su cuenta, aunque su botón las sigue lanzando. Forma de los mensajes en `docs/protocolo.md`.

### `set_subtitles` y `set_debug` (orquestador → Unity)

«Preguntar como visitante», «Conversación nueva» y «Animación de stand» están en la parte principal del panel, no en «Avanzado» (8 de octubre de 2026).

Interruptores de Avanzado, guardados en `cache/panel_state.json` y repetidos tras `hello` como el volumen. «Subtítulos» oculta en la pantalla lo que dicen el visitante y Sonia. «Modo debug» deja a Sonia quieta para pruebas visuales: el orquestador cierra GPT-Live (aunque el modo sea «Conversando»), no saluda solo en «Solo saludos» y no graba voces al arrancar; Unity se queda sin gestos, bailes ni variaciones automáticas. Los botones del panel (animaciones, saludar, imágenes) siguen funcionando, y la cabecera del panel avisa mientras está activo.

Mientras suena una frase grabada (saludos, avisos y números del stand de la caché de voces), el micrófono manda silencio a GPT-Live hasta que termina más `CLIP_ECHO_TAIL_S`: la frase no la dijo él y, si la oyera por los altavoces, la contestaría.

### Developer y `set_tuning` (orquestador → Unity)

Sección plegada debajo de «Avanzado» para ajustar a ojo, con Sonia en pantalla:

- **Boca**: apertura (vocales y mandíbula), mandíbula en las sílabas fuertes, cierre de labios en p, b y m, y rapidez. Son multiplicadores de lo que trae la escena (100 % = tal cual). Para verlo sin gastar, «Saludar ahora» reproduce una frase grabada.
- **Cámara**: zoom, altura, distancia, lateral e inclinación sobre el encuadre de siempre (el plano medio de Sonia hablando). El plano de imagen se mueve con él; los de cuerpo entero (bailes y modo Fuera) no.
- **Movimiento en reposo**: respiración, acentos del cuerpo al hablar y ritmo del reposo (respiración y vaivén). Multiplicadores de lo que trae la escena (100 % = tal cual); respiración y acentos de 0 a 200 %, ritmo de 50 a 150 %.

Cada deslizador se aplica en directo mientras se arrastra (como mucho cada 150 ms) y cada sección tiene su botón de restablecer. Los valores van a Unity en el mensaje fijo `set_tuning` (forma en `docs/protocolo.md`) y se guardan en la nube como el resto de ajustes.

**Registro**: las últimas 500 líneas del registro del orquestador de la Sonia elegida, con su hora, su nivel y el módulo que las escribe, lo más nuevo abajo. Sirve para depurar lo que no se ve en la pantalla, por ejemplo si GPT-Live dice «ahí va el baile» pero no lo delega. Filtros:
- **Delegaciones y acciones**: cada «GPT-Live delega» (con lo que traiga la delegación además de sus ids), cada acción con sus argumentos y su resultado (también los argumentos rotos), y el cierre de cada tarea del backend con cuántas acciones pidió (o «sin acciones») y lo que respondió. Si Sonia dice que hace algo y aquí no sale «GPT-Live delega», no lo delegó.
- **Gestos**: lo que elige o descarta el director de gestos en cada frase.
- **Agenda y reloj**: la agenda y la hora que se le pasan a Sonia.
- **Errores y avisos**: todo lo que va con nivel de aviso o de error.

«Copiar lo que se ve» copia las líneas del filtro elegido. Las etiquetas las pone el orquestador (`log_tags()` en `server/sonia/panel/logs.py`) según el módulo y la plantilla de cada línea, no por lo que diga el visitante. Una Sonia sin actualizar no las manda (no tiene la capacidad `log_tags`): el panel las adivina por el texto y lo avisa. El registro de «Avanzado» sigue igual, sin filtros.

**Personaje**: «Editar personaje» pasa la pantalla de Sonia a la escena de editar personaje de Genies (`open_avatar_editor`). Se edita allí, en el equipo del stand y con el ratón; el panel no edita el avatar. Mientras la escena está abierta Sonia no conversa (GPT-Live cerrado) y el panel lo dice. Al pulsar Guardar en el editor, Unity manda la definición (`avatar_saved`), el orquestador la guarda en la nube como ajuste compartido (`avatar`) y todas las Sonias la reciben en el mensaje fijo `set_avatar`. «Cerrar sin guardar» sale del editor y «Volver al personaje de la app» borra el aspecto guardado.

«Editar personaje de Jean» abre el mismo editor para el avatar de Jean del Modo Jean (`open_avatar_editor` con `target` `guest`, también desde el modal del Modo Jean). Parte del aspecto actual de Jean (su avatar de prueba si no hay ninguno guardado) y, al guardar, el orquestador lo guarda en el ajuste compartido `guest_avatar` y lo reparte en el mensaje fijo `set_guest_avatar`, sin tocar a Sonia. «Volver al avatar de prueba de Jean» lo borra. Con el Modo Jean en marcha no se abre el editor, y con el editor abierto no se activa el Modo Jean.

**Modo Jean**: «Abrir Modo Jean» abre un modal para que Jean (CTO de Sonnet Code) entre en el stand desde lejos como invitado sorpresa (diseño completo en `docs/modo-jean.md`). Desde el modal:
- activa y termina el modo (`set_guest_mode`);
- ve la cámara del stand y oye su micro;
- habla por su micro, abierto o pulsando para hablar;
- lanza los gestos de su avatar (`guest_animation`);
- pasa la pantalla de Sonia al editor de su personaje, con el modo apagado.

Lo monta `static/jean.js` (con `jean.css` y el AudioWorklet `jean-worklet.js`). La media va por la sala `/api/guest` del panel de Cloudflare, así que la cámara y el micro solo funcionan desde la nube. En el panel local se puede probar la entrada y los gestos. Mientras el modo está activo:
- GPT-Live está cerrada;
- el modo saludos no saluda solo;
- no se puede cambiar el modo de Sonia;
- Sonia no dice ni hace nada desde el panel («Que Sonia diga…», «Saludar ahora», gestos y animaciones): ha dejado su sitio al invitado. Las imágenes sí se pueden mostrar.

## API HTTP del panel

Todo bajo el mismo origen que la página. Respuestas JSON en UTF-8.

### `GET /api/status`

Instantánea completa. La misma forma llega por el WebSocket cada medio segundo.

```json
{
  "engine": "live",
  "mode": "conversation",
  "away_message": "Me fui a ver una charla, regreso en un momento",
  "state": "idle",
  "health": {
    "internet": {"ok": true, "label": "GPT-Live conectada", "hint": ""},
    "screen": {"ok": true, "label": "Pantalla conectada", "hint": ""},
    "mic": {"ok": true, "label": "Micrófono recibe sonido", "hint": "", "level": 0.03, "muted": false},
    "camera": {"ok": true, "label": "Cámara lista", "hint": ""}
  },
  "session": {"id": "sess_123", "uptime_s": 312.0, "expires_in_s": 3100.0, "context_ratio": 0.21},
  "usage": {"live_seconds": 1840.0, "cost_usd": 1.53},
  "image": null,
  "animations": [{"clip": "Greeting", "group": "greeting"}, {"clip": "Dance_HipHop", "group": "dance"}],
  "current_animation": "Dance_HipHop",
  "disabled_animations": ["Dance_Gangnam"],
  "subtitles": true,
  "debug": false,
  "showcase": {"enabled": true},
  "voice": "marin",
  "voices": ["marin", "cedar", "coral", "sage", "shimmer"],
  "volume": 1.0,
  "mic_gate": 0.0,
  "mic_presence": {"enabled": true, "ready": true, "watching": true, "status": "hace poco", "idle_s": 95.0,
                   "hold_s": 600.0, "near_gate_scale": 0.5},
  "notes": "La charla de IA se movió a la sala B.",
  "voice_cache": {"ready": 18, "total": 25, "busy": false},
  "tuning": {
    "mouth": {"open": 1.0, "jaw": 1.0, "closure": 1.0, "speed": 1.0},
    "camera": {"height": 0.0, "distance": 0.0, "side": 0.0, "zoom": 1.0, "tilt": 0.0},
    "idle": {"breath": 1.0, "accents": 1.0, "speed": 1.0}
  },
  "avatar": {"custom": true, "editor_open": false, "editor_target": "sonia"},
  "guest_avatar": {"custom": false},
  "guest": {"available": true, "phase": "off", "name": "Jean", "unity_phase": null, "intro_ready": true,
            "link": {"connected": false, "viewers": 0, "listeners": 0, "video": {"fps": 0.0, "kbps": 0, "rtt_ms": null, "step": 1, "width": 640, "quality": 65, "lost": 0},
                     "guest_level": 0.0, "guest_frames": 0, "dropped_audio": 0, "stand_muted": false}},
  "camera_watch": {"available": true, "active": false, "open": false, "connected": false, "viewers": 0, "live": false,
                   "video": {"fps": 0.0, "kbps": 0, "rtt_ms": null, "step": 1, "width": 640, "quality": 65, "lost": 0}},
  "gesture_director": {"enabled": true, "character": "Sage", "catalog": 162, "requests": 41, "gestures": 17, "fallbacks": 1,
                       "none": 19, "unknown": 0, "vetoed": 2, "late": 3, "failures": 1, "avg_latency_s": 0.82, "last": "noBigDeal"},
  "settings_sync": {"cloud": "online", "synced": true, "pending": [], "rev": 42},
  "last_error": null,
  "capabilities": ["modes", "say", "ask", "stop", "mute", "restart", "images", "gestures", "animations", "animation_toggles", "subtitles", "debug", "greet", "showcase", "volume", "mic_gate", "voice", "notes", "voice_cache", "tuning", "cloud_settings", "avatar_editor", "guest_avatar_editor", "guest_mode", "camera_watch"]
}
```

- `health.*.ok` es `true`, `false` o `null` (no aplica, por ejemplo la cámara desactivada o GPT-Live en modo saludos). `label` es una frase corta para el operador y `hint`, si no está bien, qué hacer.
- `capabilities` dice qué controles funcionan; la página desactiva los que no estén en la lista y muestra una nota junto a ellos.
- `image` es `null` o `{"id": "oficinas", "caption": "..."}`; `last_error` es `null` o un texto.
- `animations` es la lista que mandó Unity al conectar (vacía si la app de Unity es anterior a este mensaje o aún no se ha conectado). `current_animation` es el clip que suena según `animation_playing` (`null` si ninguno o sin pantalla) y `disabled_animations`, los que Sonia no usa por su cuenta.
- `health.mic.level` es el nivel RMS del micrófono (0 a 1, con decaimiento rápido), la misma escala que `mic_gate`. Llega con el estado cada medio segundo.
- `mic_presence` es la parte de la cámara de la puerta del micro (`null` si esta Sonnia no tiene cámara USB; entonces tampoco está la capacidad `mic_presence`). Arranca con `enabled` según `LIVE_PRESENCE_GATE` (apagada por defecto) o lo último que se eligió en el panel. `status`: `alguien` (una cara cerca en los últimos 10 s: la raya del ruido baja a `near_gate_scale`), `hace poco` (sin nadie desde hace `idle_s`, pero menos de `hold_s`), `nadie` (GPT-Live no oye el micro hasta que llega alguien), `sin caras aún` (la cámara no ha visto ninguna cara desde que arrancó: no cuenta), `sin imagen` (con `watching` en `false`, porque no hay sesión; si no, la cámara no da imagen: no cuenta) o `apagada`. `ready` es `false` mientras falta el modelo YuNet. Con `nadie`, `health.mic.label` lo dice.
- `usage` es el gasto del día (desde medianoche, sumando los reinicios del orquestador): segundos de sesión de GPT-Live y su coste aproximado con `PANEL_LIVE_PRICE_PER_MINUTE`.
- `voice_cache` trae también `error` (texto del último fallo al grabar, o vacío).
- `tuning` son los ajustes de «Developer» (forma de `set_tuning`).
- `avatar`: `custom`, si hay un personaje guardado desde el editor (si no, el de la app); `editor_open`, si la pantalla está ahora en la escena de editar personaje, y `editor_target`, de quién es el que se edita (`sonia` o `guest`, el de Jean; con el editor cerrado, el último que se abrió).
- `guest_avatar`: `custom`, si Jean tiene un personaje guardado desde el editor (si no, su avatar de prueba).
- `guest` (Modo Jean):
  - `available`: si esta Sonia tiene nube; sin ella no hay Modo Jean, y tampoco aparece `guest_mode` en `capabilities`.
  - `phase`: `off`, `intro`, `entering`, `live` o `leaving`.
  - `unity_phase`: la última que contó Unity.
  - `intro_ready`: si la frase con la que Sonia lo presenta ya está grabada.
  - `link`: estado de la sala; quién mira (`viewers`) y quién oye el micro del stand (`listeners`, el modal de Jean); los fps, kbit/s, RTT y escalón de calidad del vídeo, el nivel de la voz de Jean, los bloques perdidos y si el micro del stand le llega en silencio porque suena su propia voz (`stand_muted`).
- `camera_watch` («Ver cámara»):
  - `available`: si hay nube y cámara; sin eso no aparece `camera_watch` en `capabilities`.
  - `active`: si alguien pidió ver la cámara y aún no se ha soltado.
  - `open` y `connected`: si la sala está abierta y conectada (también por el Modo Jean).
  - `viewers`: cuántos navegadores miran.
  - `live`: si la cámara sale ahora del stand (sala conectada y alguien mirando).
  - `video`: las estadísticas del vídeo.
- `trivia` (modo trivia, ver `docs/trivia.md`): `available`, si hay preguntas suficientes en `assets/trivia/preguntas.md` (si la trivia está apagada con `TRIVIA_ENABLED=false`, no aparece `trivia` en `capabilities`); `active`; `phase` (`off`, `asking` esperando respuesta o `revealing` con el resultado en pantalla); `number` y `total`; `threshold`, los aciertos para ganar; `score`, y la pregunta en curso con sus tres `options`.
- `gesture_director` (gestos al hablar, ver `docs/gestos.md`): `null` si está apagado (`GESTURES_ENABLED=false` o sin clave para su modelo). Si no, contadores desde que arrancó el orquestador: `catalog`, cuántos gestos mandó Unity; `requests`, peticiones al modelo; `gestures`, gestos mandados a Unity (de ellos, `fallbacks` de relleno); `none`, frases en las que eligió no gesticular (incluidos `unknown`, respuestas que no eran un gesto, y `vetoed`, gestos que tiró la regla de frecuencia); `late`, gestos que llegaban tarde; `failures`, fallos o esperas agotadas del modelo; `avg_latency_s`, lo que tarda de media, y `last`, el último gesto. Solo informativo: la página aún no lo muestra.
- `settings_sync`: `cloud` es `off` (sin `PANEL_CLOUD_TOKEN`), `offline` u `online`; `synced`, si ya llegaron los ajustes de la nube en esta conexión; `pending`, los ajustes cambiados aquí que la nube aún no ha confirmado, y `rev`, la última revisión de la nube aplicada.

### `GET /api/gallery`

```json
{"images": [{"id": "oficinas", "url": "/api/gallery/oficinas"}]}
```

`GET /api/gallery/{id}` devuelve la imagen (para las miniaturas).

### `POST /api/action`

Cabeceras obligatorias: `Content-Type: application/json` y `X-Sonia-Panel: 1` (sin ella se responde 403; evita que otra web dispare acciones). Cuerpo `{"action": "...", ...parámetros}`. Respuesta `{"ok": true, "message": "texto para el operador"}` o `{"ok": false, "message": "..."}` con 400.

| `action` | Parámetros | Qué hace |
|---|---|---|
| `set_mode` | `mode`: `conversation`, `greeter`, `away` | Cambia de modo. |
| `set_away_message` | `text` | Texto del letrero de "Fuera". |
| `say` | `text` | Sonia lo dice en voz alta (aviso, anuncio). |
| `ask` | `text` | Como si un visitante se lo hubiera escrito: Sonia responde. |
| `stop` | | Callar a Sonia ya. |
| `mute` | `muted`: bool | Silenciar o reactivar el micrófono. |
| `restart` | | Empezar una conversación nueva (nueva sesión, olvida lo hablado). |
| `show_image` | `image_id`, `caption` opcional | Muestra una imagen de la galería. |
| `hide_image` | | Retira la imagen. |
| `gesture` | `category`: `greeting`, `dance`, `fourth_wall`, `soft` | Gesto en el avatar. |
| `animation` | `clip`: un nombre de `animations` | Reproduce ese clip una vez, en cualquier estado (no estando "Fuera"). |
| `set_animation_enabled` | `clip`, `enabled`: bool | Que Sonia use o no ese clip por su cuenta. |
| `set_subtitles` | `enabled`: bool | Subtítulos en pantalla sí o no. |
| `set_debug` | `enabled`: bool | Modo debug: Sonia quieta, sin GPT-Live ni nada automático. |
| `greet` | | Saludo con frase grabada ahora mismo (modos `conversation` y `greeter`). |
| `showcase` | `enabled`: bool | Animación de stand (frases, bailes y momentos solos) sí o no. |
| `set_volume` | `value`: 0 a 1,5 | Volumen de la voz. |
| `set_mic_gate` | `value`: 0 a 0,2 | Puerta de ruido: por debajo de este nivel GPT-Live no oye el micro (le llega un ruido muy suave). |
| `set_mic_presence` | `enabled`: bool | «Oír solo con alguien delante»: la parte de la cámara de la puerta del micro, apagada por defecto (necesita la capacidad `mic_presence`). Se guarda en este equipo y manda sobre `LIVE_PRESENCE_GATE`. |
| `set_voice` | `voice` | Cambia la voz; reinicia la conversación. |
| `set_notes` | `text` | Avisos del día que Sonia debe conocer; se le pasan al momento. |
| `set_tuning` | `mouth`, `camera` y/o `idle`: valores sueltos de `tuning` | Ajustes de «Developer»; se mezclan con los que hay y se recortan a sus límites. Un `tuning` guardado sin `idle` lo recibe con sus valores por defecto. |
| `reset_tuning` | `part`: `mouth`, `camera`, `idle` o `all` | Vuelve esa parte de «Developer» a como viene de la escena. |
| `open_avatar_editor` | `target` opcional: `sonia` (por defecto) o `guest` | La pantalla de Sonia pasa a la escena de editar personaje (no estando "Fuera" ni con el Modo Jean en marcha); con `guest`, el de Jean. |
| `close_avatar_editor` | | Sale del editor de personaje sin guardar. |
| `reset_avatar` | `target` opcional | Borra el personaje guardado: todas las Sonias vuelven al de la app. Con `target` `guest`, Jean vuelve a su avatar de prueba. |
| `set_guest_mode` | `active`: bool | Modo Jean: Sonia presenta a Jean y le deja el sitio, o él se despide y vuelve ella. Necesita la nube y la pantalla conectada. |
| `watch_camera` | `active`: bool; `keepalive` opcional | «Ver cámara»: abre la sala solo con vídeo (o la renueva) y, con `false`, la deja cerrarse en cuanto no quede nadie mirando. No toca GPT-Live, Unity ni el micro. |
| `guest_animation` | `clip` | Un gesto del avatar de Jean (con el invitado en el stand). |
| `prepare_voices` | | Graba las frases que falten en la caché de voces. |
| `trivia_start` | | Empieza una trivia (la misma partida que pide un visitante por voz). Solo en «Conversando», con la pantalla conectada y sin Modo Jean, editor ni modo debug. |
| `trivia_restart` | | Reinicia la trivia: una partida nueva desde la primera pregunta (corta la que haya). |
| `trivia_answer` | `option`: `A`, `B`, `C` o `pass` | Contesta por el visitante (si con el ruido Sonia no le entiende); `pass` es «no lo sabe». |
| `trivia_stop` | | Termina la trivia en curso. |

### `WS /api/events`

El servidor manda objetos JSON:

- `{"type": "status", "status": {...}}`: la instantánea de `/api/status`, cada medio segundo.
- `{"type": "message", "message": {...}}`: cada mensaje que el orquestador manda a Unity (`state`, `transcript`, `speech_start`, `show_image` sin `data_base64`, `hide_image`, `presence`, `attention`, `error`...), con un campo `time` (`HH:MM:SS`) añadido. Sirve para la conversación en vivo. Las frases grabadas del modo saludos llegan como `transcript` de `assistant` y `speech_start` con `ambient: true`.
- `{"type": "log", "level": "INFO", "time": "12:03:04", "logger": "live.engine", "tags": ["actions"], "text": "..."}`: líneas del registro. `logger` es el módulo sin el `sonia.` del principio y `tags`, las etiquetas de los filtros de «Developer» (`actions`, `gestures`, `agenda`); las Sonias antiguas no los mandan.

Al conectar llega primero un `{"type": "history", "messages": [...], "logs": [...]}` con lo último (conversación y registro) para pintar la página sin esperar.

## Seguridad del panel local

- El panel local escucha solo en `127.0.0.1` (`PANEL_HOST`, `PANEL_PORT=8780`).
- Las peticiones que llegan por Cloudflare (traen `Cf-Connecting-Ip`) necesitan un JWT de Cloudflare Access válido en `Cf-Access-Jwt-Assertion`: firma con las claves de `https://<PANEL_ACCESS_TEAM_DOMAIN>/cdn-cgi/access/certs`, `aud` igual a `PANEL_ACCESS_AUD` y sin caducar. Sin esas dos variables, todo acceso remoto se rechaza.
- Las acciones exigen la cabecera `X-Sonia-Panel: 1` y el WebSocket comprueba que `Origin` sea el propio panel.
- El panel local muestra lo que dicen los visitantes (transcripción). No muestra la cámara: el directo de «Ver cámara» y del Modo Jean solo va por el panel de Cloudflare, con su acceso.
- La cámara del stand solo sale mientras alguien la mira: el orquestador abre la sala de vídeo cuando se la piden y la cierra sola cuando no queda nadie. Los fotogramas van de la cámara a la sala y de ahí al navegador, que los pinta y los descarta; no se guardan en disco ni en la nube.

## Panel en Cloudflare (`cloud/panel/`)

```
navegador ──HTTPS/WS──► Worker sonia-panel ──► Durable Object "control" ◄──WS (saliente)── Sonia (equipo A)
 (operador)              (login, estáticos)      (estado de cada Sonia,  ◄──WS (saliente)── Sonia (equipo B, otro sitio)
                                                  reparte acciones)
```

### Conexión de cada Sonia (agente)

- El orquestador abre `wss://sonia.sonnetcode.com/agent` (`PANEL_CLOUD_URL`) con las cabeceras `Authorization: Bearer <PANEL_CLOUD_TOKEN>`, `X-Sonia-Instance: <id>` y `X-Sonia-Name: <nombre>`. El Worker compara el token con su secreto `AGENT_TOKEN` (comparación de tiempo constante) y pasa la conexión al Durable Object. Sin `PANEL_CLOUD_TOKEN` el orquestador no se conecta.
- `id`: `<nombre del equipo>-<6 hex>`, guardado en `cache/instance_id` (dos equipos nunca comparten id aunque se copie la carpeta: incluye el nombre del equipo). `nombre`: `PANEL_INSTANCE_NAME` (opcional, nadie tiene por qué ponerlo) o el nombre del equipo. Si dos Sonias salen con el mismo nombre, el panel añade el final de su id para distinguirlas («MacBook-Pro · d7b4c5»).
- Reconecta sola con espera creciente (1 a 30 s).

Mensajes **agente → Durable Object**:

| `type` | Campos | Cuándo |
|---|---|---|
| `hello` | `instance` (`id`, `name`, `host`, `engine`, `version`), `status`, `history` (`messages`, `logs`), `gallery` (lista de ids), `settings` (`values`: todos los ajustes compartidos; `pending`: los cambiados aquí sin confirmar; `seq`: número del último cambio) | Al conectar y como respuesta a `sync`. |
| `settings` | `changes` (ajustes cambiados aquí, con su valor), `seq` | Cuando un panel cambia un ajuste compartido (se juntan los de 0,4 s). |
| `status` | `status` (la instantánea de `GET /api/status`) | Cada 0,5 s si alguien mira esa Sonia (`viewers` > 0); si no, cada 15 s. |
| `message` | `message` (lo mismo que el panel local manda en `{"type": "message"}`, con `time`) | Al momento. |
| `log` | `level`, `time`, `text` | Al momento. |
| `result` | `request_id`, `ok`, `message` | Respuesta a cada `action`. |

Mensajes **Durable Object → agente**:

| `type` | Campos | Qué hace el agente |
|---|---|---|
| `action` | `request_id`, `action`, `params` | `StandControl.act(action, params)` y responde con `result`. |
| `viewers` | `count` | Ajusta la frecuencia de `status`. |
| `sync` | | Vuelve a mandar `hello` (el Durable Object pudo hibernar y perder el historial en memoria). |
| `settings` | `settings` (todos los ajustes de la nube), `rev`, `ack` (último `seq` de esa Sonia que ya incluyen) | Los aplica sin pisar lo cambiado aquí después de `ack` (aún en camino). |

#### Ajustes compartidos

El Durable Object guarda un único documento de ajustes (clave `settings` de su almacenamiento, con `rev`, `updated_at` y `updated_by`):

- Al recibir un `hello` con `settings`, si aún no hay documento, esa Sonia lo siembra con todos sus `values`; si ya lo hay, solo se mezclan sus `pending` (lo que cambió sin conexión). Siempre se le contesta con `settings`.
- Al recibir `settings` con `changes`, los mezcla, sube `rev` y lo guarda (una escritura) si algo cambió de verdad; contesta a esa Sonia con su `ack` y reparte el documento a las demás conectadas.
- Una Sonia anterior a esto (su `hello` sin `settings`) ni siembra ni recibe ajustes.
- Tope de 256 KB en JSON.

### API del navegador en Cloudflare

Es la misma API del panel local con un parámetro `instance` (el `id` de la Sonia). Si falta, se usa la primera conectada.

- `GET /api/instances` → `{"instances": [...], "conflicts": {"connected": ["id1", "id2"], "conversing": ["id1", "id2"]}}`. Cada instancia: `id`, `name`, `host`, `connected`, `last_seen` (ms desde 1970), `mode`, `state`, `engine`, `healthy` (bool), `issues` (frases de lo que falla), `cost_usd`. Incluye las desconectadas vistas en las últimas 2 horas.
- `GET /api/status?instance=<id>` → la instantánea de esa Sonia más `"instance": {...}`. 404 si no se conoce.
- `GET /api/gallery?instance=<id>` → `{"images": [{"id", "url"}]}`: ids que mandó esa Sonia; las imágenes se sirven desde los estáticos del Worker (`/gallery/<archivo>`, copiadas de `assets/gallery` al desplegar). Un id sin archivo en Cloudflare sale sin miniatura.
- `POST /api/action` con `{"instance": "<id>", "action": ..., ...}` y la cabecera `X-Sonia-Panel: 1` → `{"ok", "message"}`. 503 si esa Sonia no está conectada, 504 si no contesta en 15 s.
- `WS /api/events?instance=<id>` → igual que el local (`history`, `status`, `message`, `log` de esa Sonia) más `{"type": "instances", ...}` (misma forma que `GET /api/instances`) al conectar y cada vez que cambia la lista o el modo de alguna. El navegador puede mandar `{"type": "select", "instance": "<id>"}` para cambiar de Sonia sin reconectar.
- `WS /api/guest?instance=<id>` → sala de vídeo de esa Sonia (Durable Object `GuestRoom`, uno por Sonia), para el Modo Jean y para «Ver cámara». Recibe:
  - la cámara del stand en JPEG;
  - el micro del stand en PCM a 16 kHz (solo el modal del Modo Jean);
  - `stats`;
  - `agent` {`connected`}.

  El modal del Modo Jean manda la voz de Jean en PCM a 24 kHz y un `ack` por fotograma. Con `role=watch` («Ver cámara») el navegador solo ve: no recibe el micro del stand y lo que mande en binario se descarta (los `ack` sí pasan). La sala avisa a la Sonia con `viewers` {`count`, `listeners`}: cuántos miran y cuántos oyen el micro. Formato de los frames en `docs/modo-jean.md`. La Sonia entra a la misma sala por `/guest/agent` con `AGENT_TOKEN`, solo mientras el Modo Jean o «Ver cámara» la necesitan. La sala no guarda nada.

El panel local implementa lo mismo con una sola instancia (`/api/instances` devuelve la de ese equipo y el parámetro `instance` se ignora).

### Varias Sonias

Puede haber varias Sonias a la vez en sitios distintos (por ejemplo, la del stand y otra en la oficina); no es un error. Cada una tiene su id, su modo, su sesión de GPT-Live y su gasto; los ajustes compartidos valen para todas.

- Con dos o más conectadas, el panel muestra arriba «¿Qué Sonia estás controlando?» con todas (nombre, equipo, modo y si está bien). Se toca una para controlarla y todo lo de abajo se aplica solo a esa; se cambia de una a otra en cualquier momento. Cada navegador recuerda la última que eligió (`localStorage`).
- Si dos o más están en "Conversando", debajo sale una nota informativa (no una alarma): cada una gasta por su cuenta (unos 3 USD por hora) y, si dos están en la misma sala, se contestarían entre ellas. Lleva un botón para dejar solo la elegida conversando y mandar las demás a "Fuera".
- `conflicts` de `/api/instances` sigue con el mismo nombre por compatibilidad: `conversing` es lo que usa esa nota; `connected` ya no se muestra.
- Una Sonia desconectada sale en gris con "desconectada hace X min" y sus controles deshabilitados.

### Acceso

- `/agent` y `/guest/agent`: solo con `AGENT_TOKEN`.
- Todo lo demás (página, estáticos, API, WebSocket): un JWT de Cloudflare Access válido (`Cf-Access-Jwt-Assertion` o la cookie `CF_Authorization`, firmado con las claves de `https://<ACCESS_TEAM_DOMAIN>/cdn-cgi/access/certs`, `aud` = `ACCESS_AUD`) si esas variables están puestas, **o** la sesión de la contraseña del panel (`PANEL_PASSWORD`): `GET /login` muestra un formulario, `POST /login` comprueba la contraseña y deja una cookie `sonia_session` (HttpOnly, Secure, SameSite=Strict, 12 h, firmada con HMAC). Sin sesión: las páginas redirigen a `/login` y la API responde 401. Si no hay ni Access ni contraseña configurados, nadie entra.
- Cuando se cree la aplicación de Access para `sonia.sonnetcode.com`, la ruta `/agent` necesita una política **Bypass** (o un service token) para que las Sonias sigan conectando.
- Las mismas cabeceras de seguridad que el panel local (CSP sin scripts en línea, `frame-ancestors 'none'`...).

### Secretos y despliegue

- Secretos del Worker (`wrangler secret put` en `cloud/panel/`): `AGENT_TOKEN`, `PANEL_PASSWORD` y, cuando exista Access, `ACCESS_TEAM_DOMAIN` y `ACCESS_AUD`.
- En el `.env` de cada equipo con Sonia: `PANEL_CLOUD_TOKEN` (el mismo valor que `AGENT_TOKEN`) y, si se quiere, `PANEL_INSTANCE_NAME`.
- Despliegue: `cd cloud/panel && npm install && npm run deploy` (copia los estáticos del panel y la galería a `public/` y ejecuta `wrangler deploy`). El dominio `sonia.sonnetcode.com` es un Custom Domain del Worker.
- Plan free de Workers: el Durable Object usa SQLite y la API de hibernación; con el estado cada 15 s cuando nadie mira, el consumo queda muy por debajo de los límites gratuitos.
