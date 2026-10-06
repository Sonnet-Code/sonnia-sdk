# CLAUDE.md

Guía para trabajar en este repositorio con Claude Code.

## Qué es este proyecto

Sonia (se escribe **Sonnia**, con doble n como Sonnet Code; se pronuncia «Sonia») es un asistente de IA por voz en tiempo real con avatar 3D, similar a los avatares de Grok. Conversa voz a voz con GPT-Live de OpenAI, ve a través de una cámara (capturas puntuales que describe un modelo con visión, nunca vídeo) y puede mostrar imágenes dentro de su escena 3D. Se construye para el stand de Sonnet Code en DevFest Santo Domingo 2026 (9 y 10 de octubre de 2026). El público serán visitantes de un evento de desarrolladores, así que la demo tiene que ser robusta y rápida.

Sonia **no corre en local**: la voz y la conversación van por la API de OpenAI y necesitan internet. En el equipo del stand corren el orquestador (micrófono, cámara, acciones, panel local) y el avatar de Unity. Sonia no tiene por qué correr en el Mac de desarrollo; el equipo del stand está por decidir (el mini PC GMKtec EVO-X2 AI con Windows 11, otro portátil o el Mac), así que el orquestador y la build de Unity deben funcionar en macOS y en Windows. Guía de instalación en `docs/stand.md`.

## Principios que no se negocian

1. **Voz a voz con GPT-Live.** Hay un solo motor (ADR 007): GPT-Live (`gpt-live-1`) por WebSocket oye el micrófono de forma continua, gestiona él solo los turnos y las interrupciones (es full duplex: se le puede interrumpir hablando) y habla con su propia voz. Las acciones las ejecuta el backend de la API Responses en el que delega (`LIVE_BACKEND_MODEL`). El motor en cascada anterior (detector de voz, reconocedor, modelo de texto y TTS) y el silenciado manual del micrófono mientras hablaba Sonia se borraron el 4 de octubre de 2026: no se reintroducen. Única excepción: mientras suena una frase grabada (`LiveEngine.play_clip`: saludos, avisos y números del stand sacados de `cache/voice`) y `CLIP_ECHO_TAIL_S` después, el micrófono manda silencio a GPT-Live, porque esa frase no la dijo él y, si la oyera, la contestaría. Modelos y voz se cambian por variables de entorno, sin tocar código.
2. **Latencia primero.** Todo es streaming: el micrófono va a GPT-Live a tiempo real y su voz llega a Unity según se genera. Meta: menos de dos segundos entre que el usuario termina de hablar y Sonia empieza a responder. La descripción de la cámara corre en paralelo y no frena la respuesta. Cualquier cambio que añada latencia perceptible necesita justificación.
3. **Demo de stand, no producto.** Prioriza que funcione de forma fiable durante ocho horas seguidas sobre la elegancia arquitectónica. Reconexión con espera creciente, sesiones renovadas antes de caducar, timeouts y degradación controlada valen más que abstracciones. Nada de lo que pase en una sesión de GPT-Live, la cámara, el micrófono o Unity tumba el proceso. Sin internet Sonia no conversa: el plan B es el modo "Solo saludos" del panel, que reproduce frases ya grabadas sin red ni gasto.
4. **Gasto bajo control.** GPT-Live cuesta 0,05 USD por minuto de sesión abierta (unos 3 USD por hora), más los tokens del backend y del modelo de visión. En "Solo saludos" y "Fuera" no se abre sesión. **Ningún test ni script automático llama a APIs reales**; solo gastan `sonia check`, `sonia say` y el uso manual (`sonia run`, `sonia chat`, el panel).
5. **Pantalla vertical.** La demo se muestra en un monitor colocado en vertical, relación 9:16 (1080x1920). Toda la escena de Unity, los subtítulos, el panel de imágenes y la build se diseñan para ese encuadre.
6. **Nombre: se escribe «Sonnia», se dice «Sonia»** (decisión de Jean del 6 de octubre de 2026, para que coincida con Sonnet Code). Todo lo que se lee (pantalla, subtítulos, panel, nombre de la app) dice «Sonnia»: `clean_transcript` lo corrige en los subtítulos. Lo hablado y lo que leen los modelos (persona, conocimiento, frases grabadas de `assets/showcase`, cuya caché de voz va por texto) sigue con «Sonia». Los identificadores, rutas (`SONIA_HOME`) y cabeceras (`X-Sonia-*`) no cambian.
7. **Sonia es del staff.** Se presenta como asistente virtual y parte del staff del DevFest, creada por Sonnet Code. El avatar lleva la camiseta del staff del DevFest Santo Domingo 2026 (azul royal, lockup oficial, STAFF y los patrocinadores 2026 con Sonnet Code el más visible), horneada sobre su prenda de Genies al cargarse (`GeniesStaffShirt`, diseño en `scripts/camiseta_staff/genera.py`, ver `docs/unity.md`, «Camiseta de staff»), y la pantalla muestra el logo de Sonnet Code. La persona vive en `server/sonia/persona.py` (y las reglas propias de GPT-Live en `server/sonia/live/prompts.py`); los datos del evento, del GDG, de la biblioteca, de Sonnet Code y de cómo funciona Sonia en `assets/knowledge/*.md` (editables sin tocar código). Si le preguntan cómo funciona, dice la verdad: GPT-Live de OpenAI en la nube, nada de "100 % local".
8. **Feedback visual obligatorio.** Ningún cambio en la escena, el avatar, las animaciones, el lip-sync o el HUD se da por hecho sin verlo: se renderiza la cámara principal a 1080x1920 (render a `RenderTexture` desde un `RunCommand` del MCP o el menú **Sonia > Captura vertical 9:16**), en modo edición y en Play, y quien hace el cambio revisa la imagen (no hace falta enseñársela al usuario salvo que la pida). La herramienta `Unity_Camera_Capture` renderiza en 16:9 y no sirve para juzgar el encuadre. Al verificar el lip-sync se capturan varios frames mientras Sonia habla para ver la boca abierta. Los bounds de los renderers no sirven para encuadrar (accesorios los deforman): se usan los huesos del Humanoid. En modo edición, al posar el avatar con un `PlayableGraph` y renderizar en el mismo `RunCommand`, la malla va una pose por detrás de los huesos: poner `forceMatrixRecalculationPerRender = true` en el `SkinnedMeshRenderer` durante la captura. Si el editor no tiene el foco, el bucle de juego no avanza en Play: para probar sin nadie delante se conduce a mano con `EditorApplication.Step()` en un bucle (un frame síncrono por llamada, `deltaTime` fijo de 0,02 s) y se capturan frames en los instantes que interesen. Ojo: si el editor está en Play sin pausar, la primera llamada a `Step()` solo pide la pausa y el resto de llamadas de ese mismo `RunCommand` no avanzan nada; hay que pausar en un comando (`EditorApplication.isPaused = true` o un `Step()` suelto) y conducir los frames en el siguiente. Los avisos `JobTempAlloc has allocations...` que aparecen al usar `Step()` son ruido del editor, no errores nuestros. Para una conversación completa sin micrófono: `sonia run --no-mic` + `SoniaClient.SendTextInput` (o `scripts/ws_probe.py`); abre una sesión de GPT-Live y gasta, así que se cierra en cuanto estén las capturas. Para ver la boca con voz real sin gastar: modo "Solo saludos" con la caché de voces ya grabada (`cache/voice`) y la acción `greet` del panel local, que reproduce una frase grabada al momento (va como frase `ambient`: mueve boca, cejas y ojos sin pasar a `speaking`).
9. **Sin ánimo de lucro y de uso personal.** No hay uso comercial, así que de momento no se gestionan licencias de assets (avatar, animaciones, imágenes). `docs/licencias.md` queda como registro opcional por si algún día cambia el uso.

## Claves y secretos

Las claves (`OPENAI_API_KEY`, que usan GPT-Live y el modelo de visión salvo que `LIVE_API_KEY` o `LLM_API_KEY` den otra, y `PANEL_CLOUD_TOKEN`) viven en `.env`, ignorado por git. **Nunca leas ni imprimas `.env`** ni otros archivos con claves (los antiguos `kimi.txt` y `aistudio.txt`, también ignorados, o `~/.config/sonia/panel-secrets.env`). Los secretos del Worker del panel se ponen con `npx wrangler secret put` en `cloud/panel/`.

## Stack

- **Orquestador:** Python 3.12, gestionado con `uv`. Formateo y lint con `ruff`. Tipado con anotaciones y `mypy` en modo estricto donde sea razonable.
- **Voz y conversación:** GPT-Live (`LIVE_MODEL`, por defecto `gpt-live-1`) por WebSocket crudo contra `wss://api.openai.com/v1/live/sessions`, sin SDK (`server/sonia/live`). PCM 16 bit mono a `LIVE_SAMPLE_RATE` (24 000 o 16 000 Hz) en los dos sentidos. Comportamientos comprobados con la API real: manda audio sin parar a ritmo real (trozos de 100 ms), también cuando calla (silencio digital), así que las frases hacia Unity se cortan por nivel de voz; `session.instructions.append` no la hace hablar y `session.commentary.append` sí (por eso los textos escritos, los avisos del panel y la grabación de frases fijas van por `commentary`); la transcripción del visitante trae marcas como "[laugh]" que se limpian; la sesión dura hasta 120 minutos y el motor la renueva antes, igual que tras `IDLE_RESET_SECONDS` sin nadie o si se llena el contexto.
- **Acciones del modelo:** GPT-Live las delega en un backend de la API Responses (`LIVE_BACKEND_MODEL`, por defecto `gpt-6-luna`) con las herramientas generadas de `server/sonia/actions`.
- **Visión:** cámara USB leída con OpenCV (o la webcam de Unity con `VISION_SOURCE=unity`). En el modo reunión (`sonia reunion`, `docs/reunion.md`) los ojos son la ventana de la videollamada: una fuente de OBS fuera del lienzo que se pide por obs-websocket (`VISION_SOURCE=obs`, `server/sonia/vision/obs.py`) o, de plan B, la pantalla (`VISION_SOURCE=screen`). Solo capturas puntuales, reducidas. GPT-Live no acepta imágenes: un modelo con visión compatible con la API de OpenAI (`LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`; por defecto `gpt-6-luna` en la propia OpenAI, y para otros servidores `LLM_MAX_TOKENS_PARAM=max_tokens`) describe la foto y la descripción entra en la sesión como nota silenciosa `[Cámara] ...` (`session.thinking.append`), solo si está activada la foto automática; por defecto la cámara solo se usa con `look`, que manda la foto al backend. Nunca streaming de vídeo.
- **Panel de control:** web para el personal del stand, alojado en Cloudflare (`https://sonia.sonnetcode.com`, Worker `sonia-panel` con Durable Object, código en `cloud/panel/`). Cada Sonia se conecta hacia fuera con `PANEL_CLOUD_TOKEN`; el orquestador sirve además un panel local de respaldo en `http://127.0.0.1:8780`. Modos Conversando, Solo saludos y Fuera. Detalle en `docs/panel.md`.
- **Avatar:** Unity 6000.6.0f1 (proyecto en `unity/`, plantilla URP, solo Input System nuevo: `UnityEngine.Input` lanza excepción), C#, assets gratuitos. Avatar actual: `unity/Assets/Avatar/Babe.glb` (Ready Player Me, glTFast, blendshapes Oculus + ARKit de 0 a 1; los VRM van de 0 a 100 y `LipSyncController.BlendShapeScale` lo resuelve). Animación sin Animator Controller: `MotionPlayer` (Playables API, fundidos por código, capa de torso con máscara) + `AvatarChoreographer` (idle con variaciones y gestos de atención, escuchar con asentimientos, pensar, hablar encadenando clips sin bucle, saludo, caminar para el modo Fuera) sobre el asset `SoniaMotionSet` que genera el menú **Sonia > Crear set de animaciones** a partir de `SoniaAnimations.cs`; clips de la biblioteca de Ready Player Me (`Assets/Animations/RPM`, licencia solo para avatares RPM; para hablar solo se usan estos, femeninos y masculinos) y de Mixamo para bailes, pensar y gestos (sus clips de habla ponían los dedos en garra y hundían las manos en las caderas de Babe). Los límites musculares del rig generado se dejan en los de Unity: reducirlos reescala los clips y cierra las manos abiertas (ver `docs/unity.md`, "Manos y dedos"); tras tocar `SoniaHumanoidRig`, **Sonia > Regenerar Avatar Humanoid**. Lip-sync por fonemas en tiempo real con uLipSync (MIT, paquete UPM por git) vía `PhonemeLipSyncBridge` sobre el audio que llega; el orquestador ya no manda `visemes` ni `envelope` (Unity los sigue entendiendo como respaldo). Ojos por `EyeGazeController` (sacadas, vistazos, ganancia 0,65 para que no parezca bizca); cabeza y parpadeo en `AvatarStateController`. Iluminación de tres puntos, halo, motas y Volume ACES con **Sonia > Iluminación de estudio**. Los huesos de los ojos se dejan fuera del rig humanoide a propósito. Los VRM (Yae, Snb) siguen funcionando: `Vrm10Instance` en `LateUpdate` (orden 11000) y los controladores de cara en 12000-12500. La pantalla es el diseño F («Navy en vivo», `StageScreen`, montado por código en Play): fondo navy de la marca, logo arriba a la izquierda, QR a sonnetcode.com arriba a la derecha, invitación a hablar abajo en un bocadillo de Sonia cuando nadie conversa y subtítulos grandes tipo karaoke; Sonia de cintura para arriba al conversar y de rodillas para arriba en reposo (`docs/unity.md`, "Pantalla del stand"); los controles de desarrollo (botones, caja de texto, etiquetas de estado, F1, F2) solo salen arrancando la app con `-dev-ui` o, en el editor, con **Sonia > Controles de desarrollo en pantalla**. Esc abre siempre el menú de opciones: calidad gráfica (Alta, Media, Baja y Personalizada) y el editor de personaje de Sonia (`Assets/Scripts/Sonia/Graphics`, ver `docs/unity.md`, "Build para el stand").
- **Unity MCP:** el paquete `com.unity.ai.assistant` expone un servidor MCP del editor de Unity. Está registrado en Claude Code como `unity-mcp` (relay en `~/.unity/relay`). Requiere el editor abierto y aprobar la conexión en Edit > Project Settings > AI > Unity MCP Server. Úsalo para leer la consola (errores de compilación), inspeccionar la escena y ejecutar el menú Sonia > Crear escena base.
- **Comunicación:** WebSocket local entre orquestador y Unity. Mensajes JSON para eventos y binario para audio PCM.

## Estructura

```
server/        Orquestador Python. live (motor GPT-Live), actions, vision, llm (cliente del
               modelo de visión), audio (micrófono), ws (Unity), panel, showcase, persona.
unity/         Proyecto Unity. Scripts en unity/Assets/Scripts.
cloud/panel/   Panel de control en Cloudflare (Worker + Durable Object).
assets/        gallery (imágenes que Sonia puede mostrar), knowledge (base de conocimiento),
               showcase (frases, cantos y saludos fijos).
scripts/       Modo kiosco, checks del stand, sonda del WebSocket, herramientas del avatar.
docs/          Arquitectura, protocolo, panel, guía del stand, Unity y decisiones (ADR).
```

## Animación de stand

`server/sonia/showcase.py`: cuando Sonia lleva `SHOWCASE_FIRST_DELAY_SECONDS` en idle sin nadie, cada `SHOWCASE_INTERVAL_MIN/MAX_SECONDS` dice una frase de `assets/showcase/frases.md` (a veces con un gesto de cuarta pared) o baila con un canto de `assets/showcase/cantos.md`. Si la frase está en la caché de voces (`cache/voice`, grabada una vez con la voz de GPT-Live) se reproduce tal cual sin gastar; si no, se le pide a GPT-Live por `session.commentary.append`. Va como `speech_start` con `ambient: true` sin cambiar de estado (Unity mueve boca, cejas y ojos y sigue bailando) y con un mensaje `attention` previo. Cualquier voz o turno lo corta. El modo "Solo saludos" del panel usa además `assets/showcase/saludos.md`.

## Acciones del modelo

Definidas una sola vez en `server/sonia/actions`; de ese registro salen las herramientas del backend Responses en el que delega GPT-Live.

| Acción | Qué hace |
|---|---|
| `look` | Toma una captura fresca de la cámara y se la manda al backend como imagen. |
| `show_image` | Muestra una imagen en el panel de la escena de Unity. Acepta un id de la galería local o `camera` para la última captura. Opcionalmente un pie de texto. |
| `hide_image` | Retira el panel de imágenes. |
| `play_animation` | Baila o hace un gesto (saludar, paz, pulgares arriba...) cuando se lo piden: busca el clip en el catálogo que manda Unity y lo lanza entero (`whole`), aunque Sonia hable mientras tanto (`server/sonia/actions/moves.py`). |
| `start_trivia`, `trivia_answer`, `restart_trivia`, `stop_trivia` | Modo trivia (`docs/trivia.md`): empezar, registrar la letra que eligió el visitante, empezar otra desde cero y terminar. El orquestador guarda la clave y la pantalla; GPT-Live entiende la respuesta y lee el guion que devuelve cada acción. |

Por defecto Sonia solo mira cuando GPT-Live lo decide, con la acción `look` (decisión de Jean del 5 de octubre de 2026): no hay foto automática. Se puede activar que el motor tome una captura cuando alguien empieza a hablar (`VISION_ON_TURN_START=true`) o cada cierto tiempo (`VISION_INTERVAL_SECONDS`), y el modelo de visión la describe para GPT-Live como nota `[Cámara]`; las instrucciones de GPT-Live cambian solas según el modo (`camera_mode` en `server/sonia/live/prompts.py`). Esa política vive en `server/sonia/vision` y se controla con esas dos variables y `LIVE_VISION_MIN_INTERVAL_SECONDS`. Si `LLM_SUPPORTS_VISION=false` o `VISION_SOURCE=none`, la capa de visión se desactiva entera y `look` deja de anunciarse.

`show_image` en Unity: Sonia señala con el índice (gesto congelado en la capa de torso) y la imagen sale fija en la franja alta de la pantalla cuando la mano llega arriba; la cámara se echa un poco atrás. El orquestador la retira sola a los `IMAGE_AUTO_HIDE_SECONDS` (30).

Al añadir una acción nueva: definirla en `server/sonia/actions`, escribir su handler, añadir el mensaje correspondiente al protocolo WebSocket si afecta a Unity, e implementar el lado de Unity en el mismo commit.

## Protocolo entre orquestador y Unity

Documentado en `docs/protocolo.md`. En resumen:

- El orquestador envía estados `listening`, `thinking`, `speaking`, `idle`, deducidos de lo que llega de GPT-Live (la API no emite eventos de turno).
- El audio viaja en chunks PCM 16 bit mono de unos 100 ms a la tasa que anuncia `hello` (`LIVE_SAMPLE_RATE`). Cada tramo de voz de Sonia separado por un silencio de `LIVE_SEGMENT_GAP_MS` es una frase (`speech_start`, frames binarios, `speech_end`).
- Lo que dicen el visitante y Sonia llega como `transcript` (parcial y final) para los subtítulos.
- No se envían `visemes` ni `envelope`: el lip-sync sale de los fonemas del audio en Unity.
- El orquestador envía `show_image` con la imagen en base64, más el pie de texto opcional, y `hide_image` para retirarla. Unity decide cómo integrarlo con el avatar (panel, giro de cabeza, gesto). También `attention`, `presence` (modo Fuera), `stage_mode` (si Sonia puede conversar: la invitación a hablar) y `set_volume`.
- Las interrupciones por voz las gestiona GPT-Live solo. Unity envía `interrupt` desde los controles de desarrollo (botón "Interrumpir") y el orquestador corta la voz con `stop_speaking`, igual que con "Callar a Sonia" en el panel. `text_input` se le pasa a GPT-Live como texto escrito.

Si cambias el protocolo, actualiza ambos lados y el documento en el mismo commit.

## Convenciones

- Idioma del código y los comentarios: español para comentarios y documentación, inglés para identificadores (nombres de variables, funciones, clases).
- Commits cortos en español, en imperativo: "Añade el modo Fuera al panel".
- Configuración solo por variables de entorno y `.env` (plantilla comentada en `.env.example`). Nunca hardcodear rutas, puertos ni claves.
- No se suben al repo claves, builds de Unity, logs ni la caché (`cache/`: voces grabadas, estado del panel, id de la instancia).
- Las capturas de cámara no se guardan en disco salvo en modo debug explícito (`VISION_DEBUG_SAVE_FRAMES`). Es una demo pública con visitantes reales: nada de persistir imágenes de personas.
- Los assets de Unity de terceros pueden anotarse en `docs/licencias.md`, pero no es obligatorio: el proyecto es sin ánimo de lucro y de uso personal.

## Comandos

Todo desde `server/`. Usa `--no-sync` para no tocar el lockfile en cada ejecución.

```bash
uv sync --group dev --extra audio --extra camera --extra panel   # entorno de desarrollo
uv run --no-sync sonia check       # micrófono, cámara, GPT-Live (abre y cierra una sesión), modelo de visión, galería
uv run --no-sync sonia chat        # escribir a GPT-Live por consola (--speak para oírla)
uv run --no-sync sonia say "Hola"  # GPT-Live lee el texto con su voz (--out para guardar un WAV)
uv run --no-sync sonia run         # demo completa (--no-mic: sin micrófono, solo text_input)
uv run --no-sync sonia reunion     # Sonia en una videollamada: prepara OBS y arranca como run (docs/reunion.md)
uv run --no-sync ruff check sonia tests && uv run --no-sync ruff format sonia tests
uv run --no-sync mypy sonia
uv run --no-sync pytest -q         # sin hardware, sin red, sin APIs reales
```

`check`, `chat`, `say`, `run` y `reunion` hablan con la API de OpenAI y gastan. Los tests usan `httpx.MockTransport`, un GPT-Live falso inyectado, servidores WebSocket falsos y audio sintético. Las dependencias opcionales (sounddevice, cv2, starlette, uvicorn, jwt) se importan de forma perezosa dentro de funciones para que el paquete importe sin ellas.

## Cosas que no hay que hacer

- No reintroducir el motor en cascada (detector de voz, reconocedor, modelo de texto, TTS) ni silenciar a mano el micrófono mientras habla GPT-Live (la única excepción, las frases grabadas de `cache/voice`, está en el principio 1).
- No llamar a APIs reales (GPT-Live, el backend Responses, el modelo de visión) desde tests, scripts o comprobaciones automáticas. Solo `sonia check`, `sonia say` y el uso manual y consciente.
- No leer ni imprimir `.env` ni archivos de claves.
- No mandar imágenes a GPT-Live: no las acepta. La cámara le llega como texto; la foto solo va al modelo de visión y, con `look`, al backend.
- No bloquear el bucle `asyncio` con llamadas síncronas (red, cámara, disco): el micrófono tiene que llegar a GPT-Live a tiempo real.
- No enviar vídeo continuo ni capturas en cada frame a ningún modelo. Solo fotos puntuales, reducidas, cuando aporten.
- No guardar en disco capturas de la cámara fuera del modo debug.
- No implementar una acción sin su lado de Unity cuando le afecta: registro, handler, protocolo y Unity en el mismo commit.
- No subir claves, builds de Unity ni la caché al repositorio.
- No añadir funcionalidades que no aporten a la demo del stand sin discutirlo antes.

## Contexto del evento

- Evento: DevFest Santo Domingo 2026, organizado por GDG Santo Domingo.
- Fecha: 9 y 10 de octubre de 2026.
- Lugar: Biblioteca Nacional Pedro Henríquez Ureña, Santo Domingo, República Dominicana.
- Stand: Sonnet Code (https://www.sonnetcode.com/es).
- Sonia debe poder presentarse, explicar qué es Sonnet Code brevemente si se lo preguntan y mantener una conversación casual en español con acento y registro naturales para el Caribe.
- Debe usar la cámara con naturalidad: saludar a quien se acerca, notar si hay varias personas, comentar algo que le enseñen. Sin describir a la gente de forma invasiva ni hacer comentarios sobre aspecto físico.
- Debe apoyarse en el panel de imágenes cuando ayude a explicar algo, por ejemplo mostrar el logo o un diagrama de Sonnet Code, y retirarlo cuando cambie de tema.
