# Panel de control de Sonia

Panel web para que el personal del stand (no necesariamente técnico) controle a Sonia en vivo. Lo sirve el propio orquestador en `http://127.0.0.1:8780/` y se publica en internet en `https://sonia.sonnetcode.com` con un Cloudflare Tunnel protegido por Cloudflare Access (solo correos `@sonnetcode.com`). Ver "Publicación en internet" al final.

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
  "showcase": {"enabled": true},
  "voice": "marin",
  "voices": ["marin", "cedar", "coral", "sage", "shimmer"],
  "barge_in": false,
  "volume": 1.0,
  "mic_gate": 0.0,
  "notes": "La charla de IA se movió a la sala B.",
  "voice_cache": {"ready": 18, "total": 25, "busy": false},
  "last_error": null,
  "capabilities": ["modes", "say", "ask", "stop", "mute", "restart", "images", "gestures", "greet", "showcase", "volume", "mic_gate", "barge_in", "voice", "notes", "voice_cache"]
}
```

- `health.*.ok` es `true`, `false` o `null` (no aplica, por ejemplo la cámara desactivada o GPT-Live en modo saludos). `label` es una frase corta para el operador y `hint`, si no está bien, qué hacer.
- `capabilities` dice qué controles funcionan con el motor actual: con `VOICE_ENGINE=pipeline` solo hay `ask`, `stop`, `images`, `gestures` y `volume`.
- `image` es `null` o `{"id": "logo-sonnet", "caption": "..."}`; `last_error` es `null` o un texto.
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
| `greet` | | Saludo con frase grabada ahora mismo (modos `conversation` y `greeter`). |
| `showcase` | `enabled`: bool | Animación de stand (frases y bailes solos) sí o no. |
| `set_volume` | `value`: 0 a 1,5 | Volumen de la voz. |
| `set_mic_gate` | `value`: 0 a 0,2 | Puerta de ruido: por debajo de este nivel el micrófono manda silencio. |
| `set_barge_in` | `enabled`: bool | Dejar que la interrumpan hablando (solo con auriculares o cancelación de eco). |
| `set_voice` | `voice` | Cambia la voz; reinicia la conversación. |
| `set_notes` | `text` | Avisos del día que Sonia debe conocer; se le pasan al momento. |
| `prepare_voices` | | Graba las frases que falten en la caché de voces. |

### `WS /api/events`

El servidor manda objetos JSON:

- `{"type": "status", "status": {...}}`: la instantánea de `/api/status`, cada medio segundo.
- `{"type": "message", "message": {...}}`: cada mensaje que el orquestador manda a Unity (`state`, `transcript`, `speech_start`, `show_image` sin `data_base64`, `hide_image`, `presence`, `attention`, `error`...), con un campo `time` (`HH:MM:SS`) añadido. Sirve para la conversación en vivo. Las frases grabadas del modo saludos llegan como `transcript` de `assistant` y `speech_start` con `ambient: true`.
- `{"type": "log", "level": "INFO", "time": "12:03:04", "text": "..."}`: líneas del registro.

Al conectar llega primero un `{"type": "history", "messages": [...], "logs": [...]}` con lo último (conversación y registro) para pintar la página sin esperar.

## Seguridad

- El panel escucha solo en `127.0.0.1` (`PANEL_HOST`, `PANEL_PORT=8780`).
- Las peticiones que llegan por Cloudflare (traen `Cf-Connecting-Ip`) necesitan un JWT de Cloudflare Access válido en `Cf-Access-Jwt-Assertion`: firma con las claves de `https://<PANEL_ACCESS_TEAM_DOMAIN>/cdn-cgi/access/certs`, `aud` igual a `PANEL_ACCESS_AUD` y sin caducar. Sin esas dos variables, todo acceso remoto se rechaza.
- Las acciones exigen la cabecera `X-Sonia-Panel: 1` y el WebSocket comprueba que `Origin` sea el propio panel.
- El panel muestra lo que dicen los visitantes (transcripción). No muestra la cámara.

## Publicación en internet

Estado a 3 de octubre de 2026:

- **Hecho.** Cloudflare Tunnel `sonia-panel`, gestionado desde el dashboard (cuenta SONNET CODE), con el ingress `sonia.sonnetcode.com` → `http://localhost:8780` y el resto en 404. Registro DNS `sonia` (CNAME al túnel, con proxy). El token del conector está en `~/.cloudflared/sonia-panel.token` (fuera del repo, permisos 600) en el Mac de Jean.
- **Pendiente.** La aplicación de Cloudflare Access. Hasta que exista, `https://sonia.sonnetcode.com` responde "Acceso no autorizado" (el panel rechaza todo lo que llega por Cloudflare sin un JWT de Access válido) y el panel solo se usa en local.

Para terminar Access (dashboard de Cloudflare → Zero Trust, equipo `sonnetcode`):

1. Access → Applications → Add an application → **Self-hosted**.
2. Nombre "Panel de Sonia", dominio `sonia.sonnetcode.com`, duración de sesión 24 h.
3. Política "Staff de Sonnet Code": acción **Allow**, regla **Include → Emails ending in → `@sonnetcode.com`**. Métodos de login: One-time PIN (código por correo) y, si se quiere, Google (ya configurado para el CMS de la web).
4. Guardar y copiar el **Application Audience (AUD) Tag**.
5. En el `.env` del equipo del stand: `PANEL_ACCESS_TEAM_DOMAIN=sonnetcode.cloudflareaccess.com` y `PANEL_ACCESS_AUD=<el AUD>`, y reiniciar `sonia run`.

Alternativa: dar a Claude un token de API con "Access: Apps and Policies → Edit" (por ejemplo, ampliando el de `haymesa`) y lo hace por API. Los tokens existentes (sesión de wrangler y `haymesa`) no tienen ese permiso; el DNS se creó con el certificado de origen de `cloudflared` de `piku-steamdeck`.

### Arrancar el túnel

```bash
scripts/panel_tunnel.sh      # en el equipo donde corre `sonia run`; se reinicia solo si se cae
```

Para el equipo del stand: instala `cloudflared` y copia `~/.cloudflared/sonia-panel.token`. Solo debe haber un equipo con el conector corriendo a la vez (si hay dos, Cloudflare reparte las visitas entre ellos).
