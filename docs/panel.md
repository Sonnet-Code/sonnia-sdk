# Panel de control de Sonia

Panel web para que el personal del stand (no necesariamente técnico) controle a Sonia en vivo. Vive en **Cloudflare** (`https://sonia.sonnetcode.com`, Worker `sonia-panel` con un Durable Object, código en `cloud/panel/`) y cada Sonia, esté en el equipo que esté, se conecta a él hacia fuera por WebSocket: no hace falta abrir puertos ni túneles en el equipo del stand. Así el panel ve **todas** las Sonias conectadas y avisa si hay más de una (lo normal es una sola; dos conversando a la vez es pagar doble y que se pisen).

El orquestador sigue sirviendo el mismo panel en `http://127.0.0.1:8780/` como respaldo local: funciona sin internet (por ejemplo, para pasar a "Solo saludos" si cae la red) y solo ve a la Sonia de ese equipo.

## Modos de Sonia

| Modo | Qué hace | Gasta |
|---|---|---|
| `conversation` (Conversando) | GPT-Live abierto: oye, conversa, usa la cámara y las acciones. | Sesión de GPT-Live (0,05 USD/min) y modelo de visión. |
| `greeter` (Solo saludos) | Sin conversación: no oye ni mira. Cada cierto tiempo saluda, hace un gesto o baila diciendo una frase grabada con su voz. | Nada: las frases salen de la caché de voces (`cache/voice`). |
| `away` (Fuera) | Se va de la pantalla caminando y deja un letrero ("Me fui a ver una charla, regreso en un momento"). | Nada. |

El modo, el texto del letrero, los avisos del día, el volumen, la sensibilidad del micrófono, la voz y la animación de stand se guardan en `cache/panel_state.json` y se recuperan si el orquestador se reinicia (un reinicio estando "Fuera" no la trae de vuelta).

La caché de voces guarda cada frase fija (saludos, frases y cantos del stand) leída una vez por GPT-Live con la voz configurada. Se rellena sola en segundo plano cuando hay clave y Sonia está en `conversation`, o con el botón "Preparar voces". Las frases del modo saludos están en `assets/showcase/saludos.md`.

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

Unity manda al recibir `hello` la lista de clips que se pueden lanzar uno a uno (`AnimationCatalog.cs`: todo lo de una sola vez del set, sin los bucles base ni el caminar). El orquestador la publica en `animations` del estado y el bloque «Animaciones» de Avanzado pinta un botón por clip, agrupados (saludo, bailes, hacia el público, gestos suaves, al hablar, en reposo, pensando, escuchando). Cada botón manda la acción `animation` y el orquestador la pasa a Unity como `play_animation`. Forma de los mensajes en `docs/protocolo.md`.

Mientras suena una frase grabada (saludos, avisos y números del stand de la caché de voces), el micrófono manda silencio a GPT-Live hasta que termina más `CLIP_ECHO_TAIL_S`: la frase no la dijo él y, si la oyera por los altavoces, la contestaría.

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
  "showcase": {"enabled": true},
  "voice": "marin",
  "voices": ["marin", "cedar", "coral", "sage", "shimmer"],
  "volume": 1.0,
  "mic_gate": 0.0,
  "notes": "La charla de IA se movió a la sala B.",
  "voice_cache": {"ready": 18, "total": 25, "busy": false},
  "last_error": null,
  "capabilities": ["modes", "say", "ask", "stop", "mute", "restart", "images", "gestures", "animations", "greet", "showcase", "volume", "mic_gate", "voice", "notes", "voice_cache"]
}
```

- `health.*.ok` es `true`, `false` o `null` (no aplica, por ejemplo la cámara desactivada o GPT-Live en modo saludos). `label` es una frase corta para el operador y `hint`, si no está bien, qué hacer.
- `capabilities` dice qué controles funcionan; la página desactiva los que no estén en la lista y muestra una nota junto a ellos.
- `image` es `null` o `{"id": "logo-sonnet", "caption": "..."}`; `last_error` es `null` o un texto.
- `animations` es la lista que mandó Unity al conectar (vacía si la app de Unity es anterior a este mensaje o aún no se ha conectado).
- `health.mic.level` es el nivel RMS del micrófono (0 a 1, con decaimiento rápido), la misma escala que `mic_gate`. Llega con el estado cada medio segundo.
- `usage` es el gasto del día (desde medianoche, sumando los reinicios del orquestador): segundos de sesión de GPT-Live y su coste aproximado con `PANEL_LIVE_PRICE_PER_MINUTE`.
- `voice_cache` trae también `error` (texto del último fallo al grabar, o vacío).

### `GET /api/gallery`

```json
{"images": [{"id": "logo-sonnet", "url": "/api/gallery/logo-sonnet"}]}
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
| `greet` | | Saludo con frase grabada ahora mismo (modos `conversation` y `greeter`). |
| `showcase` | `enabled`: bool | Animación de stand (frases y bailes solos) sí o no. |
| `set_volume` | `value`: 0 a 1,5 | Volumen de la voz. |
| `set_mic_gate` | `value`: 0 a 0,2 | Puerta de ruido: por debajo de este nivel el micrófono manda silencio. |
| `set_voice` | `voice` | Cambia la voz; reinicia la conversación. |
| `set_notes` | `text` | Avisos del día que Sonia debe conocer; se le pasan al momento. |
| `prepare_voices` | | Graba las frases que falten en la caché de voces. |

### `WS /api/events`

El servidor manda objetos JSON:

- `{"type": "status", "status": {...}}`: la instantánea de `/api/status`, cada medio segundo.
- `{"type": "message", "message": {...}}`: cada mensaje que el orquestador manda a Unity (`state`, `transcript`, `speech_start`, `show_image` sin `data_base64`, `hide_image`, `presence`, `attention`, `error`...), con un campo `time` (`HH:MM:SS`) añadido. Sirve para la conversación en vivo. Las frases grabadas del modo saludos llegan como `transcript` de `assistant` y `speech_start` con `ambient: true`.
- `{"type": "log", "level": "INFO", "time": "12:03:04", "text": "..."}`: líneas del registro.

Al conectar llega primero un `{"type": "history", "messages": [...], "logs": [...]}` con lo último (conversación y registro) para pintar la página sin esperar.

## Seguridad del panel local

- El panel local escucha solo en `127.0.0.1` (`PANEL_HOST`, `PANEL_PORT=8780`).
- Las peticiones que llegan por Cloudflare (traen `Cf-Connecting-Ip`) necesitan un JWT de Cloudflare Access válido en `Cf-Access-Jwt-Assertion`: firma con las claves de `https://<PANEL_ACCESS_TEAM_DOMAIN>/cdn-cgi/access/certs`, `aud` igual a `PANEL_ACCESS_AUD` y sin caducar. Sin esas dos variables, todo acceso remoto se rechaza.
- Las acciones exigen la cabecera `X-Sonia-Panel: 1` y el WebSocket comprueba que `Origin` sea el propio panel.
- El panel muestra lo que dicen los visitantes (transcripción). No muestra la cámara.

## Panel en Cloudflare (`cloud/panel/`)

```
navegador ──HTTPS/WS──► Worker sonia-panel ──► Durable Object "control" ◄──WS (saliente)── Sonia (equipo A)
 (operador)              (login, estáticos)      (estado de cada Sonia,  ◄──WS (saliente)── Sonia (equipo B, duplicado)
                                                  reparte acciones)
```

### Conexión de cada Sonia (agente)

- El orquestador abre `wss://sonia.sonnetcode.com/agent` (`PANEL_CLOUD_URL`) con las cabeceras `Authorization: Bearer <PANEL_CLOUD_TOKEN>`, `X-Sonia-Instance: <id>` y `X-Sonia-Name: <nombre>`. El Worker compara el token con su secreto `AGENT_TOKEN` (comparación de tiempo constante) y pasa la conexión al Durable Object. Sin `PANEL_CLOUD_TOKEN` el orquestador no se conecta.
- `id`: `<nombre del equipo>-<6 hex>`, guardado en `cache/instance_id` (dos equipos nunca comparten id aunque se copie la carpeta: incluye el nombre del equipo). `nombre`: `PANEL_INSTANCE_NAME` o el nombre del equipo.
- Reconecta sola con espera creciente (1 a 30 s).

Mensajes **agente → Durable Object**:

| `type` | Campos | Cuándo |
|---|---|---|
| `hello` | `instance` (`id`, `name`, `host`, `engine`, `version`), `status`, `history` (`messages`, `logs`), `gallery` (lista de ids) | Al conectar y como respuesta a `sync`. |
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

### API del navegador en Cloudflare

Es la misma API del panel local con un parámetro `instance` (el `id` de la Sonia). Si falta, se usa la primera conectada.

- `GET /api/instances` → `{"instances": [...], "conflicts": {"connected": ["id1", "id2"], "conversing": ["id1", "id2"]}}`. Cada instancia: `id`, `name`, `host`, `connected`, `last_seen` (ms desde 1970), `mode`, `state`, `engine`, `healthy` (bool), `issues` (frases de lo que falla), `cost_usd`. Incluye las desconectadas vistas en las últimas 2 horas.
- `GET /api/status?instance=<id>` → la instantánea de esa Sonia más `"instance": {...}`. 404 si no se conoce.
- `GET /api/gallery?instance=<id>` → `{"images": [{"id", "url"}]}`: ids que mandó esa Sonia; las imágenes se sirven desde los estáticos del Worker (`/gallery/<archivo>`, copiadas de `assets/gallery` al desplegar). Un id sin archivo en Cloudflare sale sin miniatura.
- `POST /api/action` con `{"instance": "<id>", "action": ..., ...}` y la cabecera `X-Sonia-Panel: 1` → `{"ok", "message"}`. 503 si esa Sonia no está conectada, 504 si no contesta en 15 s.
- `WS /api/events?instance=<id>` → igual que el local (`history`, `status`, `message`, `log` de esa Sonia) más `{"type": "instances", ...}` (misma forma que `GET /api/instances`) al conectar y cada vez que cambia la lista o el modo de alguna. El navegador puede mandar `{"type": "select", "instance": "<id>"}` para cambiar de Sonia sin reconectar.

El panel local implementa lo mismo con una sola instancia (`/api/instances` devuelve la de ese equipo y el parámetro `instance` se ignora).

### Duplicados

- Con dos o más Sonias conectadas, el panel muestra arriba una barra para elegir cuál se controla (con su modo y si está bien) y un aviso: "Hay 2 Sonias conectadas; normalmente solo debe haber una".
- Si dos o más están en "Conversando", el aviso es rojo ("se paga doble y pueden responder a la vez") con un botón para dejar solo la elegida y mandar las demás a "Fuera".
- Una Sonia desconectada sale en gris con "desconectada hace X min" y sus controles deshabilitados.

### Acceso

- `/agent`: solo con `AGENT_TOKEN`.
- Todo lo demás (página, estáticos, API, WebSocket): un JWT de Cloudflare Access válido (`Cf-Access-Jwt-Assertion` o la cookie `CF_Authorization`, firmado con las claves de `https://<ACCESS_TEAM_DOMAIN>/cdn-cgi/access/certs`, `aud` = `ACCESS_AUD`) si esas variables están puestas, **o** la sesión de la contraseña del panel (`PANEL_PASSWORD`): `GET /login` muestra un formulario, `POST /login` comprueba la contraseña y deja una cookie `sonia_session` (HttpOnly, Secure, SameSite=Strict, 12 h, firmada con HMAC). Sin sesión: las páginas redirigen a `/login` y la API responde 401. Si no hay ni Access ni contraseña configurados, nadie entra.
- Cuando se cree la aplicación de Access para `sonia.sonnetcode.com`, la ruta `/agent` necesita una política **Bypass** (o un service token) para que las Sonias sigan conectando.
- Las mismas cabeceras de seguridad que el panel local (CSP sin scripts en línea, `frame-ancestors 'none'`...).

### Secretos y despliegue

- Secretos del Worker (`wrangler secret put` en `cloud/panel/`): `AGENT_TOKEN`, `PANEL_PASSWORD` y, cuando exista Access, `ACCESS_TEAM_DOMAIN` y `ACCESS_AUD`.
- En el `.env` de cada equipo con Sonia: `PANEL_CLOUD_TOKEN` (el mismo valor que `AGENT_TOKEN`) y, si se quiere, `PANEL_INSTANCE_NAME`.
- Despliegue: `cd cloud/panel && npm install && npm run deploy` (copia los estáticos del panel y la galería a `public/` y ejecuta `wrangler deploy`). El dominio `sonia.sonnetcode.com` es un Custom Domain del Worker.
- Plan free de Workers: el Durable Object usa SQLite y la API de hibernación; con el estado cada 15 s cuando nadie mira, el consumo queda muy por debajo de los límites gratuitos.
