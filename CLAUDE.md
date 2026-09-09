# CLAUDE.md

Guía para trabajar en este repositorio con Claude Code.

## Qué es este proyecto

Sonia es un asistente de IA por voz en tiempo real con avatar 3D, similar a los avatares de Grok, que corre completamente en local. Ve a través de una cámara (capturas puntuales, no vídeo) y puede mostrar imágenes dentro de su escena 3D. Se construye para el stand de Sonnet Code en DevFest Santo Domingo 2026 (9 y 10 de octubre de 2026). El público serán visitantes de un evento de desarrolladores, así que la demo tiene que ser robusta, rápida y funcionar sin conexión a internet.

## Principios que no se negocian

1. **Todo corre local.** Ningún componente puede depender de una API en la nube. No añadas SDKs de OpenAI, Anthropic, Google, ElevenLabs ni similares como dependencia de ejecución. Si un módulo necesita red para funcionar, está mal diseñado. Excepción temporal documentada en "Estado provisional": mientras no haya GPU, el LLM y el TTS apuntan a APIs en la nube a través de las mismas interfaces que usarán los modelos locales.
2. **Agnóstico al modelo.** El orquestador habla con un endpoint compatible con OpenAI configurado por variables de entorno (`LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`). Kimi K3 es el modelo por defecto, pero ningún archivo de código debe mencionarlo por nombre. Nada de prompts, parsers ni ajustes específicos de un modelo. La visión y las acciones usan los formatos estándar de la API (contenido de imagen en `image_url` y tool calling), y deben degradar limpiamente si el modelo configurado no soporta imágenes o herramientas.
3. **Latencia primero.** Todo el pipeline es streaming. Meta: menos de dos segundos entre que el usuario termina de hablar y Sonia empieza a responder. Cualquier cambio que añada latencia perceptible necesita justificación.
4. **Demo de stand, no producto.** Prioriza que funcione de forma fiable durante ocho horas seguidas sobre la elegancia arquitectónica. Reinicios automáticos, timeouts y degradación controlada valen más que abstracciones.
5. **Pantalla vertical.** La demo se muestra en un monitor colocado en vertical, relación 9:16 (1080x1920). Toda la escena de Unity, el HUD, el panel de imágenes y la build se diseñan para ese encuadre.
6. **Sonia es del staff.** Se presenta como asistente virtual y parte del staff del DevFest, creada por Sonnet Code. El avatar lleva la camiseta del staff del DevFest y la pantalla muestra el logo de Sonnet Code. La persona vive en `server/sonia/persona.py`; los datos del evento, del GDG, de la biblioteca y de Sonnet Code en `assets/knowledge/*.md` (editables sin tocar código).
7. **Feedback visual obligatorio.** Ningún cambio en la escena, el avatar, las animaciones, el lip-sync o el HUD se da por hecho sin verlo: se renderiza la cámara principal a 1080x1920 (render a `RenderTexture` desde un `RunCommand` del MCP o el menú `Sonia/Render 9:16`), en modo edición y en Play, y quien hace el cambio revisa la imagen (no hace falta enseñársela al usuario salvo que la pida). La herramienta `Unity_Camera_Capture` renderiza en 16:9 y no sirve para juzgar el encuadre. Al verificar el lip-sync se capturan varios frames durante `speaking` para ver la boca abierta. Los bounds de los renderers no sirven para encuadrar (accesorios los deforman): se usan los huesos del Humanoid. En modo edición, al posar el avatar con un `PlayableGraph` y renderizar en el mismo `RunCommand`, la malla va una pose por detrás de los huesos: poner `forceMatrixRecalculationPerRender = true` en el `SkinnedMeshRenderer` durante la captura. Si el editor no tiene el foco, el bucle de juego no avanza en Play: para probar sin nadie delante se conduce a mano con `EditorApplication.Step()` en un bucle (un frame síncrono por llamada, `deltaTime` fijo de 0,02 s) y se capturan frames en los instantes que interesen. Ojo: si el editor está en Play sin pausar, la primera llamada a `Step()` solo pide la pausa y el resto de llamadas de ese mismo `RunCommand` no avanzan nada; hay que pausar en un comando (`EditorApplication.isPaused = true` o un `Step()` suelto) y conducir los frames en el siguiente. Los avisos `JobTempAlloc has allocations...` que aparecen al usar `Step()` son ruido del editor, no errores nuestros; el orquestador en modo ensayo (`scripts/fake_llm_server.py` + `TTS_BACKEND=system` + `sonia run --no-mic` + `SoniaClient.SendTextInput`) da una conversación completa sin nube; `TTS_BACKEND=mock` produce silencio y es solo para tests.
8. **Sin ánimo de lucro y de uso personal.** No hay uso comercial, así que de momento no se gestionan licencias de assets (avatar, animaciones, imágenes). `docs/licencias.md` queda como registro opcional por si algún día cambia el uso.

## Estado provisional (septiembre de 2026)

El equipo definitivo del stand será un mini PC **GMKtec EVO-X2 AI** (AMD Ryzen AI Max+ 395, Radeon 8060S integrada, 128 GB de memoria unificada LPDDR5X, 2 TB SSD, Wi-Fi 7, Windows 11 Pro). Implicaciones: el orquestador debe correr en Windows; el LLM local irá servido con llama.cpp (backend Vulkan o ROCm) aprovechando la memoria unificada; OmniVoice y faster-whisper deben validarse en esa GPU AMD (por confirmar: ROCm en Windows o CPU). Sonia debe presumir de correr 100 % en local en esa máquina, que estará a la vista en el stand.

Todavía no ha llegado ese hardware. Hasta que llegue:

- **LLM:** la API de Kimi en la nube (`LLM_BASE_URL=https://api.moonshot.ai/v1`, modelo `kimi-k3`) a través del mismo cliente compatible con OpenAI. La cuenta tiene pocos tokens: **ningún test ni script automático llama a la API real**; solo `sonia check` (tres peticiones mínimas de 5 tokens) y el uso manual. La clave vive en `.env` y `kimi.txt`, ambos ignorados por git. Nunca los leas ni los imprimas.
- **TTS:** `TTS_BACKEND=gemini` usa la API Live de Gemini (free tier) como voz provisional (`server/sonia/tts/gemini.py`, ADR 006). Se retira cuando OmniVoice pueda correr en local. Requiere `TTS_GEMINI_API_KEY` en `.env`.
- **STT y VAD** sí corren en local (faster-whisper en CPU y Silero VAD).

## Stack

- **Orquestador:** Python 3.12, gestionado con `uv`. Formateo y lint con `ruff`. Tipado con anotaciones y `mypy` en modo estricto donde sea razonable.
- **Detección de voz:** Silero VAD.
- **Reconocimiento de voz:** faster-whisper, español.
- **Modelo de lenguaje:** cualquier servidor con API compatible con OpenAI (llama.cpp, vLLM, Ollama). Por defecto Kimi K3, que es multimodal.
- **Visión:** cámara USB leída con OpenCV. Solo capturas puntuales, reducidas antes de enviarlas al modelo. Nunca streaming de vídeo al LLM.
- **Acciones del modelo:** tool calling estándar de OpenAI como vía principal. Las mismas acciones se exponen también como servidor MCP local (`server/mcp`) para modelos o servidores sin tool calling nativo. Una única definición de acciones alimenta ambas vías.
- **Síntesis de voz:** OmniVoice, detrás de una interfaz `TextToSpeech` sustituible.
- **Avatar:** Unity 6000.6.0f1 (proyecto en `unity/`, plantilla URP, solo Input System nuevo: `UnityEngine.Input` lanza excepción), C#, assets gratuitos. Avatar actual: `unity/Assets/Avatar/Babe.glb` (Ready Player Me, glTFast, blendshapes Oculus + ARKit de 0 a 1; los VRM van de 0 a 100 y `LipSyncController.BlendShapeScale` lo resuelve). Animación sin Animator Controller: `MotionPlayer` (Playables API, fundidos por código, capa de torso con máscara) + `AvatarChoreographer` (idle con variaciones y gestos de atención, escuchar con asentimientos, pensar, hablar encadenando clips sin bucle, saludo) sobre el asset `SoniaMotionSet` que genera el menú **Sonia > Crear set de animaciones** a partir de `SoniaAnimations.cs`; clips de la biblioteca de Ready Player Me (`Assets/Animations/RPM`, licencia solo para avatares RPM; para hablar solo se usan estos, femeninos y masculinos) y de Mixamo para bailes, pensar y gestos (sus clips de habla ponían los dedos en garra y hundían las manos en las caderas de Babe). Los límites musculares del rig generado se dejan en los de Unity: reducirlos reescala los clips y cierra las manos abiertas (ver `docs/unity.md`, "Manos y dedos"); tras tocar `SoniaHumanoidRig`, **Sonia > Regenerar Avatar Humanoid**. Lip-sync por visemas del orquestador cuando llegan y, si no, por fonemas en tiempo real con uLipSync (MIT, paquete UPM por git) vía `PhonemeLipSyncBridge`; ojos por `EyeGazeController` (sacadas, vistazos, ganancia 0,65 para que no parezca bizca); cabeza y parpadeo en `AvatarStateController`. Iluminación de tres puntos, halo, motas y Volume ACES con **Sonia > Iluminación de estudio**. Los huesos de los ojos se dejan fuera del rig humanoide a propósito. Los VRM (Yae, Snb) siguen funcionando: `Vrm10Instance` en `LateUpdate` (orden 11000) y los controladores de cara en 12000-12500.
- **Unity MCP:** el paquete `com.unity.ai.assistant` expone un servidor MCP. Está registrado en Claude Code como `unity-mcp` (relay en `~/.unity/relay`). Requiere el editor abierto y aprobar la conexión en Edit > Project Settings > AI > Unity MCP Server. Úsalo para leer la consola (errores de compilación), inspeccionar la escena y ejecutar el menú Sonia/Crear escena base.
- **Comunicación:** WebSocket local entre orquestador y Unity. Mensajes JSON para eventos y binario para audio PCM.

## Estructura

```
server/     Orquestador Python. Un módulo por etapa: vad, stt, vision, llm, actions, tts, ws, mcp.
unity/      Proyecto Unity. Scripts en unity/Assets/Scripts.
assets/     Galería local de imágenes que Sonia puede mostrar (logos, diagramas, material del stand).
scripts/    Arranque de servicios locales, descarga de modelos, checks del stand.
docs/       Decisiones de diseño (ADR cortos), protocolo WebSocket, licencias de assets.
```

## Animación de stand

`server/sonia/showcase.py`: cuando el orquestador lleva `SHOWCASE_FIRST_DELAY_SECONDS` en idle sin nadie, cada `SHOWCASE_INTERVAL_MIN/MAX_SECONDS` dice una frase de `assets/showcase/frases.md` (a veces con un gesto de cuarta pared) o baila con un canto de `assets/showcase/cantos.md`. Va como `speech_start` con `ambient: true` sin cambiar de estado (Unity mueve boca, cejas y ojos y sigue bailando) y con un mensaje `attention` previo. Sin LLM: son textos fijos. Cualquier voz o turno lo corta con `stop_speaking`.

## Acciones del modelo

Definidas una sola vez en `server/actions` y expuestas por tool calling y por MCP.

| Acción | Qué hace |
|---|---|
| `look` | Toma una captura fresca de la cámara y la devuelve al modelo como imagen. |
| `show_image` | Muestra una imagen en el panel de la escena de Unity. Acepta un id de la galería local o `camera` para la última captura. Opcionalmente un pie de texto. |
| `hide_image` | Retira el panel de imágenes. |

Además de la acción `look`, el orquestador adjunta automáticamente una captura al turno cuando detecta que alguien empieza a hablar, y opcionalmente cada cierto tiempo mientras hay presencia. Esa política vive en `server/vision` y se controla por variables de entorno (`VISION_ON_TURN_START`, `VISION_INTERVAL_SECONDS`). Si `LLM_SUPPORTS_VISION=false`, la capa de visión se desactiva entera y `look` deja de anunciarse al modelo.

Al añadir una acción nueva: definirla en `server/actions`, escribir su handler, añadir el mensaje correspondiente al protocolo WebSocket si afecta a Unity, e implementar el lado de Unity en el mismo commit.

## Protocolo entre orquestador y Unity

Documentado en `docs/protocolo.md` cuando exista. Mientras tanto, la idea:

- El orquestador envía eventos de estado: `listening`, `thinking`, `speaking`, `idle`.
- El audio viaja en chunks PCM 16 bit mono con la tasa de muestreo que produzca OmniVoice.
- Junto a cada chunk van los visemas con su timestamp para el lip-sync.
- El orquestador envía `show_image` con la imagen en base64 o una ruta de la galería, más el pie de texto opcional, y `hide_image` para retirarla. Unity decide cómo integrarlo con el avatar (panel, giro de cabeza, gesto).
- Unity envía `interrupt` cuando detecta que el usuario ha empezado a hablar mientras Sonia habla. El orquestador cancela la generación y la síntesis en curso.

Si cambias el protocolo, actualiza ambos lados y el documento en el mismo commit.

## Convenciones

- Idioma del código y los comentarios: español para comentarios y documentación, inglés para identificadores (nombres de variables, funciones, clases).
- Commits cortos en español, en imperativo: "Añade interrupción por VAD".
- Configuración solo por variables de entorno y `.env`. Nunca hardcodear rutas de modelos, puertos ni claves.
- Los modelos pesados (pesos de LLM, STT, TTS) no se suben al repo. Van en `.gitignore` y se descargan con `scripts/`.
- Las capturas de cámara no se guardan en disco salvo en modo debug explícito. Es una demo pública con visitantes reales: nada de persistir imágenes de personas.
- Los assets de Unity de terceros pueden anotarse en `docs/licencias.md`, pero no es obligatorio: el proyecto es sin ánimo de lucro y de uso personal.

## Comandos

Todo desde `server/`. Usa `--no-sync` para no tocar el lockfile en cada ejecución.

```bash
uv sync --group dev --extra audio --extra stt --extra camera --extra mcp   # entorno de desarrollo (sin omnivoice)
uv sync --extra all                                                       # demo completa (incluye omnivoice, pesado)
uv run --no-sync sonia check       # micrófono, VAD, STT, cámara, LLM (3 peticiones mínimas), TTS, galería
uv run --no-sync sonia chat        # conversar por texto sin micrófono ni cámara
uv run --no-sync sonia say "Hola"  # probar el TTS
uv run --no-sync sonia run         # demo completa
uv run --no-sync ruff check sonia tests && uv run --no-sync ruff format sonia tests
uv run --no-sync mypy sonia
uv run --no-sync pytest -q         # sin hardware, sin modelos, sin red
```

Los tests usan `httpx.MockTransport`, servidores WebSocket falsos y audio sintético. Las dependencias pesadas (torch, omnivoice, faster_whisper, silero_vad, cv2, sounddevice, mcp) se importan de forma perezosa dentro de funciones para que el paquete importe sin ellas.

## Cosas que no hay que hacer

- No introducir dependencias de red en tiempo de ejecución (salvo los backends provisionales ya documentados).
- No llamar a la API de Kimi ni a la de Gemini desde tests, scripts o comprobaciones automáticas. Solo de forma manual y consciente.
- No acoplar el código a Kimi K3 ni a ningún modelo concreto.
- No bloquear el hilo de audio con llamadas síncronas al LLM o al TTS.
- No enviar vídeo continuo ni capturas en cada frame al modelo. Solo fotos puntuales, reducidas, cuando aporten.
- No guardar en disco capturas de la cámara fuera del modo debug.
- No implementar una acción solo en tool calling o solo en MCP. Siempre ambas desde la misma definición.
- No subir pesos de modelos ni builds de Unity al repositorio.
- No añadir funcionalidades que no aporten a la demo del stand sin discutirlo antes.

## Contexto del evento

- Evento: DevFest Santo Domingo 2026, organizado por GDG Santo Domingo.
- Fecha: 9 y 10 de octubre de 2026.
- Lugar: Biblioteca Nacional Pedro Henríquez Ureña, Santo Domingo, República Dominicana.
- Stand: Sonnet Code (https://www.sonnetcode.com/es).
- Sonia debe poder presentarse, explicar qué es Sonnet Code brevemente si se lo preguntan y mantener una conversación casual en español con acento y registro naturales para el Caribe.
- Debe usar la cámara con naturalidad: saludar a quien se acerca, notar si hay varias personas, comentar algo que le enseñen. Sin describir a la gente de forma invasiva ni hacer comentarios sobre aspecto físico.
- Debe apoyarse en el panel de imágenes cuando ayude a explicar algo, por ejemplo mostrar el logo o un diagrama de Sonnet Code, y retirarlo cuando cambie de tema.
