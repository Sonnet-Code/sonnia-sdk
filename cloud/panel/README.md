# Panel de Sonia en Cloudflare (`sonia-panel`)

Worker de Cloudflare que sirve el panel de control en `https://sonia.sonnetcode.com` y al que cada Sonia se conecta hacia fuera por WebSocket. El contrato completo (mensajes, API y acceso) está en [`docs/panel.md`](../../docs/panel.md), sección "Panel en Cloudflare".

## Organización

```
src/index.ts         Worker: rutas, API del navegador, estáticos.
src/control-room.ts  Durable Object ControlRoom (una sola instancia, "control"):
                     Sonias conectadas, historial, acciones, viewers, sync.
src/auth.ts          JWT de Cloudflare Access y sesión de la contraseña.
src/login.ts         /login y /logout (formulario sin JavaScript).
src/http.ts          Respuestas JSON y cabeceras de seguridad (CSP del panel local).
scripts/build.mjs    Copia la página (server/sonia/panel/static) y la galería
                     (assets/gallery, solo PNG y JPEG) a public/, con gallery.json.
```

`public/` se genera en cada `build`/`deploy`; no se sube al repositorio.

## Desarrollo local

```bash
cd cloud/panel
npm install
cp .dev.vars.example .dev.vars   # y rellena AGENT_TOKEN y PANEL_PASSWORD de prueba
npm run dev                      # build + wrangler dev en http://localhost:8787
npm run typecheck                # wrangler types + tsc
```

`wrangler dev` corre todo en local (Durable Object con SQLite y WebSockets incluidos). Para que una Sonia se conecte a él: `PANEL_CLOUD_URL=ws://localhost:8787/agent` y `PANEL_CLOUD_TOKEN` igual al `AGENT_TOKEN` de `.dev.vars`. En local la cookie de sesión lleva `Secure`, que los navegadores aceptan en `localhost`.

## Despliegue

Desde `cloud/panel/`, con una sesión de wrangler en la cuenta de Cloudflare de `sonnetcode.com`:

```bash
npm install
npm run deploy                           # build + wrangler deploy
npx wrangler secret put AGENT_TOKEN      # valor largo y aleatorio, p. ej. openssl rand -hex 32
npx wrangler secret put PANEL_PASSWORD   # contraseña para el personal del stand
```

- Hasta que existan los secretos nadie entra al panel y ninguna Sonia conecta: desplegar primero es seguro. Cambiar un secreto no necesita volver a desplegar.
- El dominio `sonia.sonnetcode.com` es un Custom Domain del Worker (`routes` en `wrangler.jsonc`): `wrangler deploy` crea el registro DNS y el certificado. No puede existir ya otro registro DNS con ese nombre.
- `workers_dev` y `preview_urls` están desactivados para que no haya otra URL fuera de Access.
- En el `.env` de cada equipo con Sonia: `PANEL_CLOUD_TOKEN` (el mismo valor que `AGENT_TOKEN`) y, si se quiere, `PANEL_INSTANCE_NAME`.

### Cloudflare Access (opcional)

Si se crea una aplicación de Access para `sonia.sonnetcode.com`:

1. Añade una política **Bypass** (o un service token) para la ruta `/agent`, o las Sonias no podrán conectar.
2. `npx wrangler secret put ACCESS_TEAM_DOMAIN` (`<equipo>.cloudflareaccess.com`) y `npx wrangler secret put ACCESS_AUD` (la AUD de la aplicación).

Con Access configurado, la contraseña sigue valiendo como alternativa mientras `PANEL_PASSWORD` exista; bórrala (`wrangler secret delete PANEL_PASSWORD`) si solo se quiere Access.

## Consumo en el plan free

- El Durable Object usa SQLite (obligatorio en el plan free) y la API de hibernación de WebSockets; no hay temporizadores periódicos ni alarmas.
- Sin nadie mirando, cada Sonia manda su estado cada 15 s: 5.760 mensajes al día, que cuentan como unas 290 peticiones (los mensajes de WebSocket entrantes cuentan 1 de cada 20). Mirando, cada 0,5 s: unas 8.600 peticiones al día por cada Sonia mirada sin parar.
- El objeto hiberna a los ~10 s sin mensajes. Con el estado cada 15 s pasa despierto como mucho dos tercios del tiempo; ni despierto las 24 h (10.800 GB-s) llega al límite gratuito diario de duración (13.000 GB-s).
- En el almacenamiento solo se guarda un resumen de cada Sonia: al conectar y desconectar, si cambia el modo o la salud (como mucho cada 10 s) y como mucho una vez por minuto para `last_seen`.
- Los registros (`observability`) van muestreados al 10 % para no agotar la cuota gratuita. `npx wrangler tail` ve todo en directo.
