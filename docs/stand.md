# Guía operativa del stand

Guía práctica para el día del evento (DevFest Santo Domingo 2026, 9 y 10 de
octubre, Biblioteca Nacional Pedro Henríquez Ureña). Pensada para que
cualquiera del equipo de Sonnet Code pueda montar, arrancar y mantener vivo
el stand sin depender de quien escribió el código.

## Material necesario

- Portátil con GPU dedicada (es el componente que más memoria consume; ver
  `docs/arquitectura.md`).
- Micrófono direccional o de solapa (mejor que el micrófono integrado del
  portátil: capta menos ruido ambiente y menos eco del altavoz).
- Altavoz externo.
- Pantalla externa para el avatar.
- Cámara USB.
- Regleta con varias tomas.
- Cinta adhesiva (para fijar cables y evitar tropiezos).

## Montaje físico

- **Cámara**: a la altura de los ojos de una persona de pie, apuntando al
  lugar exacto donde se va a colocar el visitante. Si queda muy baja o muy
  alta, Sonia "mira" mal y el encuadre de las capturas queda raro.
- **Altavoz**: lo más alejado posible del micrófono, y preferiblemente no
  apuntando directo hacia él. Cuanto más eco del altavoz capte el micrófono,
  más probable es un falso `barge_in` (que Sonia se corte a sí misma
  creyendo que la interrumpieron). Si el espacio es reducido, prioriza
  separación y ángulo sobre volumen.
- **Distancia recomendada** entre el visitante y el micrófono/cámara: entre
  0.5 y 1.5 metros. Más cerca, el micrófono se satura; más lejos, cae la
  calidad de la transcripción y el encuadre de la cámara pierde al
  visitante.
- Cinta para fijar el cable del micrófono y de la cámara: son los que más
  se enganchan cuando pasa gente.

## Checklist de arranque

### Con GPT-Live (`VOICE_ENGINE=live`, el modo por defecto)

No hay servidor de LLM ni de TTS que levantar: la voz y la conversación las
pone GPT-Live de OpenAI (ADR 007). Hace falta internet estable todo el día.

1. `.env` con `LIVE_API_KEY`, `AUDIO_BARGE_IN=false` (con altavoces abiertos
   GPT-Live se oiría a sí mismo) y, si hay cámara, `LLM_*` apuntando a un
   modelo con visión.
2. `scripts/check_stand.sh`: abre y cierra una sesión de GPT-Live y prueba
   el modelo de visión. Todo en OK antes de seguir.
3. `uv run sonia say "Hola, soy Sonia"` desde `server/` para oír la voz
   (`LIVE_VOICE`) por el altavoz del stand.
4. `uv run sonia run` desde `server/` (o `scripts/kiosk.sh`).
5. Abrir el build de Unity y confirmar en el HUD (`F1`) la conexión y los
   estados.

### Con el motor anterior (`VOICE_ENGINE=pipeline`)

Desde la raíz del repositorio, en este orden:

1. `scripts/check_stand.sh` — corre primero, con todo lo demás apagado. Si
   falla el endpoint del LLM es normal si aún no lo has levantado (paso 2).
2. Servidor del LLM: `scripts/run_llm_server.sh` (backend según lo que esté
   configurado ese día; ver `BACKEND` en el propio script) o confirmar que
   el endpoint provisional en la nube de `.env` responde.
3. Servidor de TTS, solo si `TTS_BACKEND=http`: `scripts/run_tts_server.sh`.
   Si `TTS_BACKEND=omnivoice` (el modo por defecto), no hace falta este
   paso: el propio orquestador carga el modelo.
4. `scripts/check_stand.sh` otra vez, ahora con el LLM (y el TTS si aplica)
   ya arriba. Todo debe salir en OK antes de seguir.
5. `uv run sonia run` desde `server/` (o `scripts/kiosk.sh` si vas a dejar
   el stand desatendido durante horas, ver más abajo).
6. Abrir el build de Unity (o el proyecto en el editor y darle a Play). Ver
   `docs/unity.md` para el detalle de cómo generar y abrir el build.
7. Confirmar el HUD de depuración de Unity (tecla `F1`) para ver de un
   vistazo el estado de la conexión WebSocket y el estado de Sonia
   (`idle`/`listening`/`thinking`/`speaking`) antes de dejar pasar al
   primer visitante.

Para dejar el stand corriendo sin supervisión constante, usa
`scripts/kiosk.sh` en vez del paso 5 suelto: reinicia el orquestador solo si
se cae y deja logs con fecha en `logs/`.

## Si algo falla

| Síntoma | Acción |
|---|---|
| GPT-Live: `sonia check` falla con HTTP 401 o 403 | La clave (`LIVE_API_KEY`) no es válida o el proyecto de OpenAI no tiene acceso a `gpt-live-1`. |
| GPT-Live: el log repite `Sesión de GPT-Live caída` | Sin internet o la API está caída: el motor reintenta solo con espera creciente. Si no vuelve, cambia a `VOICE_ENGINE=pipeline` y reinicia. |
| GPT-Live: contesta a las conversaciones del pasillo | Sube la puerta de ruido `LIVE_GATE_RMS` (por debajo de ese nivel se manda silencio). Los turnos dejan su nivel en el log (`Usuario (nivel X)`): la voz de fondo debe quedar por debajo del umbral y una persona a un metro del micro, por encima. |
| GPT-Live: el log repite `El micrófono falló` al arrancar | El micrófono no acepta 24 kHz (pasa con algunos drivers de Windows). `LIVE_SAMPLE_RATE=16000` abre el micro a 16 kHz y la voz de Sonia también baja a 16 kHz. |
| GPT-Live: se interrumpe sola o se contesta a sí misma | Eco del altavoz en el micrófono: `AUDIO_BARGE_IN=false` (el micro manda silencio mientras habla Sonia y `LIVE_ECHO_TAIL_MS` después). |
| `scripts/check_stand.sh` falla en el endpoint del LLM | Revisa que el servidor del LLM esté arriba (paso 2) y que `LLM_BASE_URL` en `.env` apunte al puerto correcto. |
| Sonia no reacciona a la voz / se queda en `listening` | Revisa el micrófono seleccionado (`AUDIO_INPUT_DEVICE`) y que no esté silenciado por el sistema operativo. Si se desconectó el micro, el orquestador lo reabre solo cada pocos segundos: busca en el log `El micrófono falló`. Prueba `uv run sonia chat` para descartar que el problema sea el pipeline de audio. |
| Sonia responde a conversaciones ajenas o se le cancela la respuesta sin que nadie le hable | El micrófono oye voces de fondo y el VAD abre turnos con ellas. `AUDIO_MIN_TURN_RMS` (0,03) descarta los turnos cuya voz no llegue a ese nivel medio; el log dice `Habla descartada por nivel bajo (X < Y)` y, en los turnos aceptados, `Usuario (nivel X)`. Calibrar en el stand: las voces de fondo deben quedar por debajo y una persona a un metro del micro claramente por encima. |
| Sonia se corta a sí misma hablando (falso barge-in) | Eco del altavoz en el micrófono. Mientras suena Sonia, el detector solo interrumpe con voz sostenida (`AUDIO_BARGE_IN_MIN_SPEECH_MS`, 400 ms) y `AUDIO_BARGE_IN_OVER_ECHO` veces (2,5, unos 8 dB) por encima del nivel de eco que mide; el log dice `Barge-in confirmado: voz X frente a eco Y` o `Habla descartada como eco`. Si aun así se corta, sube `AUDIO_BARGE_IN_OVER_ECHO` a 3 o 4, fija un suelo absoluto `AUDIO_BARGE_IN_MIN_RMS` con los niveles del log, o desactiva `AUDIO_BARGE_IN` temporalmente. |
| Respuestas muy lentas (varios segundos) | El modelo del LLM puede ser demasiado grande para el hardware disponible. Cambia a un modelo más pequeño o baja `LLM_REASONING_EFFORT`/`LLM_MAX_TOKENS`. |
| No hay voz o la voz se corta | Revisa que el proceso de TTS no se haya quedado sin memoria de vídeo. Si usas `TTS_BACKEND=http`, comprueba que `scripts/run_tts_server.sh` sigue vivo. |
| El avatar no se mueve pero se oye audio | Revisa la conexión WebSocket en el HUD de Unity (`F1`). Reinicia Unity: el orquestador sigue funcionando aunque Unity se caiga y se reconecta solo. |
| La cámara no captura nada | Revisa `VISION_CAMERA_INDEX` (si hay varias cámaras USB conectadas, puede que Sonia esté leyendo la equivocada) y que ningún otro programa tenga la cámara abierta. Si se desconectó y se volvió a conectar, el orquestador reintenta abrirla solo cada 30 s: no hace falta reiniciar. |
| Se muestra una imagen equivocada o no se muestra ninguna | Comprueba que el id pedido existe en `assets/gallery` (nombre de archivo sin extensión) con `scripts/check_stand.sh`. |
| El orquestador se cae solo repetidamente | Revisa el log más reciente en `logs/` (si usas `scripts/kiosk.sh`) para ver la traza del error antes de seguir probando a ciegas. |

## Ajustes rápidos por variable de entorno

Todos van en `.env` y requieren reiniciar `sonia run` (o esperan al próximo
reinicio automático si usas `scripts/kiosk.sh`):

- **Ambiente ruidoso (mucha gente hablando alrededor)**: sube
  `AUDIO_VAD_THRESHOLD` (por ejemplo de `0.5` a `0.6` u `0.7`) para que el
  VAD sea más exigente antes de considerar que alguien está hablando.
- **Desactivar la interrupción por voz** (si el eco del altavoz sigue
  disparando falsos positivos incluso ajustando el umbral):
  `AUDIO_BARGE_IN=false`. Sonia dejará de cortarse a sí misma, pero tampoco
  reaccionará si el visitante intenta interrumpirla hablando.
- **Bajar el modelo de reconocimiento de voz** si la máquina va justa de
  recursos y la transcripción tarda: `STT_MODEL=small` en vez de un modelo
  mayor (o `tiny` si hace falta más margen todavía). Recuerda correr
  `scripts/download_models.sh` de nuevo si cambias el tamaño.
- **Cambiar de modelo de lenguaje**: `LLM_BASE_URL`, `LLM_MODEL` y
  `LLM_API_KEY` apuntan a cualquier servidor compatible con OpenAI. Cambiar
  de modelo es cambiar estas tres variables y reiniciar; ningún código
  depende de un modelo concreto.

## Reinicio por inactividad

El orquestador reinicia la conversación (no el proceso) tras
`idle_reset_seconds` sin actividad, para que un visitante nuevo no arrastre
el contexto del anterior. Por defecto son 120 segundos; ajústalo con
`IDLE_RESET_SECONDS` en `.env` si el flujo de gente en el stand es muy denso
o muy espaciado. Esto es un reinicio de conversación, no de proceso: si lo
que falla es el proceso completo, usa `scripts/kiosk.sh` en vez de confiar
en este mecanismo.

## Cierre del stand

- Ctrl+C en la terminal de `scripts/kiosk.sh` (o de `sonia run`): para el
  orquestador de forma limpia, sin dejar procesos colgados.
- Cierra Unity.
- Si usaste `scripts/run_llm_server.sh` o `scripts/run_tts_server.sh` en
  terminales aparte, ciérralas también (Ctrl+C).
- Revisa `logs/` por si algún reinicio automático durante el día apunta a
  un problema que valga la pena arreglar antes del día siguiente del
  evento.
- Nada de lo anterior persiste capturas de cámara en disco (ver
  `docs/decisiones/004-vision-por-capturas.md`); no hace falta borrar nada
  por privacidad al cerrar.

## El equipo del stand

Sonia no tiene por qué correr en el Mac donde se desarrolla. El equipo del stand está por decidir: el mini PC GMKtec EVO-X2 AI (Windows 11 Pro), otro portátil o el propio Mac. Todo lo de esta guía vale para macOS, Windows y Linux.

- Colocarlo sobre la mesa, con el logo visible y sin tapar la ventilación.
- Conectar por cable lo que se pueda (pantalla, cámara, micrófono, altavoz y **red**). Con GPT-Live (`VOICE_ENGINE=live`, el modo por defecto) Sonia necesita internet para conversar: sin red, el plan B es pasarla a "Solo saludos" desde el panel local de ese equipo (`http://127.0.0.1:8780`), que funciona con frases ya grabadas.
- El cartel "Aquí vive Sonia. Todo corre en local, sin nube." solo vale con el motor local (`VOICE_ENGINE=pipeline`); con GPT-Live no es cierto. Está entre las decisiones pendientes de `ROADMAP.md`.

### Instalar Sonia en el equipo del stand

1. Python 3.12 con `uv` y la build de Unity para ese sistema (`docs/unity.md`; la de macOS está en `unity/Build/macOS/Sonia.app`, la de Windows hay que compilarla).
2. Clonar el repo (privado, org Sonnet-Code) y, desde `server/`: `uv sync --extra audio --extra camera --extra mcp --extra panel`.
3. `.env` a partir de `.env.example`, con las claves pasadas a mano (nunca por git): `LIVE_API_KEY`, el modelo de visión en `LLM_*`, `AUDIO_INPUT_DEVICE`, `AUDIO_BARGE_IN=false`, `PANEL_CLOUD_TOKEN` (para que salga en el panel de `sonia.sonnetcode.com`) y un nombre reconocible en `PANEL_INSTANCE_NAME` (por ejemplo "Mini PC del stand").
4. Nada más de red: Sonia se conecta sola hacia fuera al panel de Cloudflare; no hay que abrir puertos ni instalar túneles. Si otro equipo (el Mac de desarrollo, por ejemplo) también tiene `PANEL_CLOUD_TOKEN` y está corriendo, el panel mostrará dos Sonias y avisará: hay que dejar solo una.
5. `uv run sonia check` y `uv run sonia say "Hola, soy Sonia"` por el altavoz del stand.
6. `uv run sonia run`. A los 20 segundos graba solas las frases del modo saludos en `cache/voice` de ese equipo (o con "Preparar voces" en el panel). Cada equipo tiene su caché y su estado del panel (`cache/`).
7. Abrir la app de Unity y comprobar en `https://sonia.sonnetcode.com` (desde un móvil, con la contraseña del panel) que sale esta Sonia y solo esta. Sin internet queda el panel local en `http://127.0.0.1:8780` de ese equipo.

## Pantalla vertical (9:16)

El monitor del stand va colocado en vertical (retrato), relación 9:16, por ejemplo 1080x1920. Antes del evento:

- En macOS/Windows, girar la pantalla en los ajustes del sistema (rotación 90°) y comprobar que el escritorio se ve en vertical.
- La build de Unity está configurada a 1080x1920 en pantalla completa. Si el monitor tiene otra resolución 9:16 (por ejemplo 1440x2560), la escena escala sola.
- Colocar la cámara USB encima del monitor, centrada, para que Sonia "mire" a la misma altura que el visitante.
