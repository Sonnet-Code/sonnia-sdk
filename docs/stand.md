# Guía operativa del stand

Guía práctica para el día del evento (DevFest Santo Domingo 2026, 9 y 10 de
octubre, Biblioteca Nacional Pedro Henríquez Ureña). Pensada para que
cualquiera del equipo de Sonnet Code pueda montar, arrancar y mantener vivo
el stand sin depender de quien escribió el código.

Sonia conversa con GPT-Live de OpenAI (ADR 007): la voz y la conversación van
por internet. En el equipo del stand corren el orquestador (micrófono, cámara,
acciones, panel local) y el avatar de Unity. El día a día se maneja desde el
panel de control (`docs/panel.md`).

## Material necesario

- El equipo del stand (ver "El equipo del stand" más abajo). No necesita GPU
  dedicada: los modelos corren en la nube y el equipo solo mueve Unity y el
  orquestador.
- **Internet estable**, mejor por cable. Sin red Sonia no conversa.
- Micrófono direccional o de solapa (mejor que el micrófono integrado del
  portátil: capta menos ruido ambiente y menos eco del altavoz).
- Altavoz externo.
- Pantalla externa para el avatar, en vertical.
- Cámara USB.
- Regleta con varias tomas.
- Cinta adhesiva (para fijar cables y evitar tropiezos).

## Montaje físico

- **Cámara**: a la altura de los ojos de una persona de pie, apuntando al
  lugar exacto donde se va a colocar el visitante. Si queda muy baja o muy
  alta, Sonia "mira" mal y el encuadre de las capturas queda raro.
- **Altavoz**: lo más alejado posible del micrófono, y preferiblemente no
  apuntando directo hacia él. GPT-Live oye el micrófono todo el rato, también
  mientras habla Sonia (así se la puede interrumpir hablando): cuanto más de
  su propia voz le llegue por el micro, más probable es que se corte sola o
  se conteste a sí misma. Si el espacio es reducido, prioriza separación y
  ángulo sobre volumen.
- **Distancia recomendada** entre el visitante y el micrófono/cámara: entre
  0.5 y 1.5 metros. Más cerca, el micrófono se satura; más lejos, GPT-Live
  entiende peor y el encuadre de la cámara pierde al visitante.
- Cinta para fijar el cable del micrófono y de la cámara: son los que más
  se enganchan cuando pasa gente.

## Checklist de arranque

No hay servidores de modelos que levantar: la voz y la conversación las pone
GPT-Live. Desde la raíz del repositorio:

1. `.env` con `OPENAI_API_KEY` (la usan GPT-Live y el modelo de visión) y
   `PANEL_CLOUD_TOKEN` (ver "Instalar Sonia en el equipo del stand").
2. `scripts/check_stand.sh`: corre `sonia check` (micrófono, cámara, abre y
   cierra una sesión de GPT-Live, modelo de visión, galería) y comprueba que
   el puerto del WebSocket está libre. Todo en OK antes de seguir; un AVISO
   en el modelo de visión solo deja a Sonia sin ojos.
3. `uv run sonia say "Hola, soy Sonia"` desde `server/` para oír la voz
   (`LIVE_VOICE`) por el altavoz del stand.
4. `scripts/kiosk.sh` (o `uv run sonia run` desde `server/` si vas a estar
   delante): reinicia el orquestador solo si se cae y deja logs con fecha en
   `logs/`.
5. Abrir la build de Unity (o el proyecto en el editor y darle a Play). Ver
   `docs/unity.md` para el detalle de cómo generar y abrir la build.
6. En el panel (`https://sonia.sonnetcode.com` desde el móvil, o
   `http://127.0.0.1:8780` en el propio equipo), comprobar en "¿Funciona
   todo?" que GPT-Live, la pantalla, el micrófono y la cámara salen bien y que
   solo hay una Sonia conectada. La pantalla del stand ya no muestra estados
   ni botones; si hace falta verlos, arrancar la app con `-dev-ui` (HUD con
   F1).
7. Hablarle desde donde se pondrá el visitante, mirar en el log el nivel de
   tu voz (`Usuario (nivel X)`) y calibrar la puerta de ruido (ver "Voces del
   pasillo" más abajo).

## Si algo falla

| Síntoma | Acción |
|---|---|
| `sonia check` falla en GPT-Live con HTTP 401 o 403 | La clave (`OPENAI_API_KEY` o `LIVE_API_KEY`) no es válida o el proyecto de OpenAI no tiene acceso a `gpt-live-1`. |
| El log repite `Sesión de GPT-Live caída` | Sin internet o la API está caída: el motor reintenta solo con espera creciente. Si no vuelve, pasa a Sonia a "Solo saludos" desde el panel local (`http://127.0.0.1:8780`): sigue saludando con frases grabadas, sin red ni gasto. |
| Contesta a las conversaciones del pasillo | Sube la puerta de ruido: el control "Ruido del pasillo" del panel o `LIVE_GATE_RMS` en `.env` (por debajo de ese nivel el micro manda silencio). Ver "Voces del pasillo". |
| Se corta sola o se contesta a sí misma | Le llega su propia voz por el micrófono. Separa más el altavoz del micro y que no lo apunte, baja el volumen (panel) o usa un micrófono más direccional. Subir un poco la puerta de ruido también ayuda si el eco llega flojo. |
| No se la puede interrumpir hablando | La puerta de ruido está demasiado alta para una voz normal a un metro: bájala. GPT-Live se calla solo cuando oye al visitante. |
| El log repite `El micrófono falló` al arrancar | El micrófono no acepta 24 kHz (pasa con algunos drivers de Windows). `LIVE_SAMPLE_RATE=16000` abre el micro a 16 kHz y la voz de Sonia también baja a 16 kHz. |
| Sonia no reacciona a la voz | Revisa el micrófono seleccionado (`AUDIO_INPUT_DEVICE`), que no esté silenciado por el sistema operativo ni desde el panel, y el medidor del panel. Si se desconectó el micro, el orquestador lo reabre solo cada pocos segundos: busca en el log `El micrófono falló`. `uv run sonia chat` descarta que el problema sea la sesión. |
| No ve a nadie / `scripts/check_stand.sh` avisa del modelo de visión | Revisa la clave (`LLM_API_KEY` u `OPENAI_API_KEY`) y, si no es la API de OpenAI, `LLM_BASE_URL`, `LLM_MODEL` y `LLM_MAX_TOKENS_PARAM=max_tokens`. Sonia sigue conversando sin ojos mientras tanto. |
| La cámara no captura nada | Revisa `VISION_CAMERA_INDEX` (si hay varias cámaras USB conectadas, puede que Sonia esté leyendo la equivocada) y que ningún otro programa tenga la cámara abierta. Si se desconectó y se volvió a conectar, el orquestador reintenta abrirla solo cada 30 s: no hace falta reiniciar. |
| El avatar no se mueve pero se oye audio | Mira "Pantalla conectada" en el panel. Reinicia Unity: el orquestador sigue funcionando aunque Unity se caiga y se reconecta solo. |
| Se muestra una imagen equivocada o no se muestra ninguna | Comprueba que el id pedido existe en `assets/gallery` (nombre de archivo sin extensión) con `scripts/check_stand.sh`. |
| El panel avisa de dos Sonias | Otro equipo (el Mac de desarrollo, por ejemplo) tiene `PANEL_CLOUD_TOKEN` y está corriendo. Deja solo la del stand: el botón del aviso manda las demás a "Fuera", y luego se paran en ese equipo. |
| El orquestador se cae solo repetidamente | Revisa el log más reciente en `logs/` (si usas `scripts/kiosk.sh`) para ver la traza del error antes de seguir probando a ciegas. |

## Voces del pasillo y puerta de ruido

GPT-Live decide él solo cuándo le hablan, y oye todo lo que llega al
micrófono. En un pasillo lleno puede contestar a conversaciones ajenas. La
puerta de ruido lo evita: por debajo de un nivel, el micrófono manda silencio.

1. Arranca a Sonia y háblale desde donde se pondrá el visitante, a un metro.
2. Cada turno deja su nivel en el log: `Usuario (nivel 0.081): ...`. El
   medidor de "Ruido del pasillo" del panel muestra lo mismo en directo
   (misma escala, de 0 a 1).
3. Fija el umbral entre las voces de fondo (que deben quedar por debajo) y tu
   voz a un metro (claramente por encima). Con el control del panel se
   aplica al momento y se guarda en `cache/panel_state.json` (manda sobre
   `LIVE_GATE_RMS` del `.env` en los siguientes arranques); con `LIVE_GATE_RMS`
   hay que reiniciar.
4. Comprueba que se la puede interrumpir hablando mientras contesta: si no se
   calla, el umbral está demasiado alto.

## Ajustes rápidos por variable de entorno

Todos van en `.env` y requieren reiniciar `sonia run` (o esperan al próximo
reinicio automático si usas `scripts/kiosk.sh`):

- **Puerta de ruido**: `LIVE_GATE_RMS` (0 = apagada). Ver arriba.
- **Voz**: `LIVE_VOICE` (marin, cedar, coral, sage, shimmer...). También se
  cambia desde el panel; al cambiarla, las frases grabadas se regraban solas.
- **Micrófono que no abre a 24 kHz**: `LIVE_SAMPLE_RATE=16000`.
- **Acciones más rápidas**: `LIVE_BACKEND_SERVICE_TIER=priority` (más caro).
- **Modelo de visión**: `LLM_BASE_URL`, `LLM_MODEL` y `LLM_API_KEY` apuntan a
  cualquier servidor compatible con la API de OpenAI que acepte imágenes.
  `LLM_SUPPORTS_VISION=false` apaga la cámara.

## Reinicio por inactividad

Tras `IDLE_RESET_SECONDS` sin nadie (120 por defecto) el motor abre una
sesión nueva de GPT-Live, para que un visitante nuevo no arrastre el
contexto del anterior; la base de conocimiento (`assets/knowledge`) se relee
en ese momento. También renueva la sesión antes de que caduque (duran hasta
120 minutos) o si se llena el contexto, siempre en un momento de calma. Es un
reinicio de conversación, no de proceso: si lo que falla es el proceso
completo, usa `scripts/kiosk.sh`.

## Gasto

GPT-Live cuesta 0,05 USD por minuto de sesión abierta (unos 3 USD por hora en
"Conversando"), más el backend de acciones y el modelo de visión. El panel
muestra el gasto del día. En "Solo saludos" y "Fuera" no se abre sesión y no
se gasta nada: úsalos en las pausas largas y al cerrar.

## Cierre del stand

- Pasar a Sonia a "Fuera" o "Solo saludos" desde el panel (deja de gastar).
- Ctrl+C en la terminal de `scripts/kiosk.sh` (o de `sonia run`): para el
  orquestador de forma limpia, sin dejar procesos colgados.
- Cierra Unity.
- Revisa `logs/` por si algún reinicio automático durante el día apunta a
  un problema que valga la pena arreglar antes del día siguiente del
  evento.
- Nada de lo anterior persiste capturas de cámara en disco (ver
  `docs/decisiones/004-vision-por-capturas.md`); no hace falta borrar nada
  por privacidad al cerrar.

## El equipo del stand

Sonia no tiene por qué correr en el Mac donde se desarrolla. El equipo del stand está por decidir: el mini PC GMKtec EVO-X2 AI (Windows 11 Pro), otro portátil o el propio Mac. Todo lo de esta guía vale para macOS y Windows.

- Colocarlo sobre la mesa sin tapar la ventilación.
- Conectar por cable lo que se pueda (pantalla, cámara, micrófono, altavoz y **red**). Sonia necesita internet para conversar: sin red, el plan B es pasarla a "Solo saludos" desde el panel local de ese equipo (`http://127.0.0.1:8780`), que funciona con frases ya grabadas.
- Nada de carteles de "todo corre en local": Sonia usa GPT-Live de OpenAI en la nube, y si le preguntan lo dice.

### Instalar Sonia en el equipo del stand

1. Python 3.12 con `uv` y la build de Unity para ese sistema (`docs/unity.md`; la de macOS está en `unity/Build/macOS/Sonia.app`, la de Windows hay que compilarla).
2. Clonar el repo (privado, org Sonnet-Code) y, desde `server/`: `uv sync --extra audio --extra camera --extra panel`.
3. `.env` a partir de `.env.example`, con las claves pasadas a mano (nunca por git): `OPENAI_API_KEY`, `AUDIO_INPUT_DEVICE`, `PANEL_CLOUD_TOKEN` (para que salga en el panel de `sonia.sonnetcode.com`) y un nombre reconocible en `PANEL_INSTANCE_NAME` (por ejemplo "Mini PC del stand").
4. Nada más de red: Sonia se conecta sola hacia fuera al panel de Cloudflare; no hay que abrir puertos ni instalar túneles. Si otro equipo (el Mac de desarrollo, por ejemplo) también tiene `PANEL_CLOUD_TOKEN` y está corriendo, el panel mostrará dos Sonias y avisará: hay que dejar solo una.
5. `uv run sonia check` y `uv run sonia say "Hola, soy Sonia"` por el altavoz del stand.
6. `uv run sonia run`. A los 20 segundos graba solas las frases del modo saludos en `cache/voice` de ese equipo (o con "Preparar voces" en el panel). Cada equipo tiene su caché y su estado del panel (`cache/`).
7. Abrir la app de Unity y comprobar en `https://sonia.sonnetcode.com` (desde un móvil, con la contraseña del panel) que sale esta Sonia y solo esta. Sin internet queda el panel local en `http://127.0.0.1:8780` de ese equipo.

## Pantalla vertical (9:16)

El monitor del stand va colocado en vertical (retrato), relación 9:16, por ejemplo 1080x1920. Antes del evento:

- En macOS/Windows, girar la pantalla en los ajustes del sistema (rotación 90°) y comprobar que el escritorio se ve en vertical.
- La build de Unity está configurada a 1080x1920 en pantalla completa. Si el monitor tiene otra resolución 9:16 (por ejemplo 1440x2560), la escena escala sola.
- En pantalla solo se ven Sonia, el logo y los subtítulos. Los controles de desarrollo salen arrancando la app con `-dev-ui`.
- Si el equipo va justo (FPS por debajo de 60 o ventiladores a tope), Esc en la ventana de Sonia abre el menú de calidad gráfica: probar Media y luego Baja, mirando los FPS que marca arriba. Se queda guardado en ese equipo; también se puede arrancar con `-quality media` o `-quality baja`.
- Colocar la cámara USB encima del monitor, centrada, para que Sonia "mire" a la misma altura que el visitante.
