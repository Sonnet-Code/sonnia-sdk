# Visión de los juegos

La parte de visión de los juegos nuevos del stand (`docs/plan-juegos.md`, sección 6): la cámara en
vivo, la vista en vivo encima de Sonnia, las poses, las manos de piedra, papel o tijera, el juez de
la búsqueda relámpago y el juez de las rondas (Gemini, `GAMES_JUDGE`). Código en
`server/sonia/vision`; los juegos lo usan a través de `GameHost` (`sonia.games`) con las interfaces
de `sonia/vision/contracts.py`.

Todo corre en el equipo del stand y en memoria: **nunca se guarda una imagen ni un dato de nadie y
no se reconoce a nadie** (solo dónde están hombros, codos, muñecas y dedos). Lo único que sale del
equipo son fotos reducidas, sin guardarlas, hacia un modelo de visión:

- con `GAMES_JUDGE=gemini` (por defecto desde el 10 de octubre de 2026), a Gemini: una por ronda de
  Simón dice, una por tirada de piedra, papel o tijera y las de la búsqueda relámpago (con su tope
  por ronda);
- con `GAMES_JUDGE=local` (o sin `GEMINI_API_KEY`), solo las de la búsqueda relámpago, al modelo de
  visión de Sonia (`LLM_*`), como antes.

## Qué hay

| Pieza | Archivo | Qué hace |
|---|---|---|
| `CameraStream` | `stream.py` (`OpenCVCameraStream`) | Lee la cámara USB en un hilo mientras algún dueño la pida y guarda solo el último frame. |
| `PreviewStreamer` | `stream.py` (`LivePreview`) | La vista en vivo: frames `SNCV` a Unity, en espejo, 640x360, JPEG de calidad 60, 10 por segundo, con el dibujo del juego encima. |
| `PoseDetector` | `poses.py` (`YoloPoseDetector`) | Personas con sus 17 puntos (YOLOv8-pose en ONNX con `cv2.dnn`), en continuo o suelta. |
| `HandDetector` | `hands.py` (`MediaPipeHandDetector`) | Las manos de una persona: 21 puntos y piedra, papel, tijera o sin lectura. |
| `VisionJudge` | `judge.py` (`ModelJudge`, `FallbackJudge`) | Pregunta cerrada sobre una foto fresca, con respuesta en JSON (búsqueda relámpago): a Gemini con `GAMES_JUDGE=gemini` y, si falla, al modelo de visión de Sonia; solo a este con `local`. |
| `GameReferee` | `referee.py` (`GeminiReferee`) | El juez de las rondas de Simón dice y de piedra, papel o tijera: una foto por ronda a Gemini, con respuesta en JSON (`PoseVerdict`, `HandVerdict`). Sin él, `NoReferee`. |
| Dibujos | `overlay.py` | Esqueletos (verde o gris), manos, cajas, marcas ✓ y ✗ y etiquetas para la vista en vivo. |
| Modelos | `models.py` | Descarga con revisión fijada y SHA-256, y carga con el motor clásico de `cv2.dnn`. |
| Montaje | `games.py` (`build_game_vision`) | Monta todo con `VISION_SOURCE=opencv` y elige el juez (`GAMES_JUDGE`); si algo falta, esa pieza dice que no está disponible. |

Sin cámara USB (`VISION_SOURCE` distinto de `opencv`), sin los modelos o sin una Unity que anuncie
`camera_preview`, la pieza correspondiente dice que no está disponible y los juegos de cámara no se
ofrecen. Nada de eso tumba el orquestador.

## Cómo lo usan los juegos

Coordenadas siempre de 0 a 1 sobre la imagen **sin espejo**, e izquierda y derecha de las personas
son las suyas (orden COCO, `contracts.py`). El espejo es solo de la vista en vivo: los dibujos
reciben `mirrored` y pintan en `1 - x`.

```python
# Poses (Simón dice): detección continua a 8 por segundo y la vista con los esqueletos.
await host.poses.acquire("poses", fps=8)
await host.preview.start("poses")
frame = host.poses.latest()                      # PoseFrame o None si es vieja (0,5 s)
host.preview.set_overlay(skeletons(frame.people, [GREEN if ok else GREY for ok in hits]))

# Piedra, papel o tijera: las manos de la persona más grande, sobre el frame de ahora.
latest = host.stream.latest()                    # (time.monotonic(), frame BGR) o None
pose = await host.poses.detect(latest[1], latest[0])
player = max(pose.people, key=lambda p: p.box[2] * p.box[3])
readings = await host.hands.read(latest[1], player)   # las que tienen lectura primero, y la más alta

# Búsqueda relámpago: tope de fotos por ronda (lo pone el juego).
host.judge.start_round(max_checks)               # solo ModelJudge; sin tope si no se llama
answer = await host.judge.ask("¿Alguien enseña algo azul a la cámara?")   # JudgeAnswer o None

# Juez de las rondas (GAMES_JUDGE=gemini): una foto por ronda; None, decide lo local.
if host.referee.available:
    await host.set_busy("judge", TEXT_POSES)     # la pastilla de espera mientras mira
    try:
        verdict = await host.referee.poses(frame_bgr)   # PoseVerdict(people, counts) o None
    finally:
        await host.set_busy("judge", None)
```

- **Dueños.** Cada `acquire`/`start` lleva un dueño (el id del juego) y cada `release`/`stop`
  suelta el suyo; soltar dos veces no rompe nada. Los cimientos sueltan todo al terminar la
  partida. La vista y las poses piden el stream a su nombre (`vista:<dueño>`, `poses:<dueño>`).
- **Cámara compartida.** Mientras el stream lee, `OpenCVCamera.capture()` (`look`, caras, presencia,
  la sala del Modo Jean) saca sus fotos del último frame del stream: nunca hay dos lecturas a la vez.
  El dispositivo se lo presta la cámara (`lend_device`) y vuelve abierto al terminar (`end_loan`).
- **Fallos.** Si el driver se cuelga dentro de `grab()` o deja de dar imagen, el stream abandona ese
  dispositivo y abre otro (lo suelta el propio hilo colgado cuando vuelve). Si no abre, reintenta
  cada 2 s respetando la espera de la cámara.
- **Vista en vivo.** Solo se manda si `preview_supported()` (la Unity conectada anuncia
  `camera_preview`). Repite `camera_preview` encendido cada 2 s y en cuanto Unity vuelve, por si
  se reconectó. Unity la retira sola a los 2 s sin frames. El JPEG pesa unos 40 KB (unos 400 KB/s
  por el WebSocket local).
- **Manos.** Por cada muñeca visible se busca la palma en una zona alrededor de ella; con la palma
  se recorta la mano girada como la espera el modelo de 21 puntos y, si no hay palma, el giro sale
  del antebrazo. Si así no sale ninguna lectura (alguien muy cerca, sin muñecas a la vista), se
  buscan palmas en la caja de la persona. La tabla de la sección 5.4 del plan está en
  `hands.classify`.
- **Juez de la búsqueda.** Foto de 640 px de ancho y calidad 75, prompt que prohíbe describir a las
  personas (no cuenta lo que alguien lleva puesto o colgado: ropa, gafas, pelo, gorras ni el gafete del evento), respuesta
  `{"visto": bool, "objeto": str}`, plazo de 8 s y tope por ronda (`start_round`). Pasado el tope,
  `ask` devuelve `None` sin llamar. Con `GAMES_JUDGE=gemini` pregunta a Gemini y con `local`, al
  modelo de visión de Sonia (ver «Juez de Gemini»).

## Juez de Gemini (`GAMES_JUDGE`)

Encargo de Jean del 10 de octubre de 2026 («mejor usemos gemini»): las rondas de cámara las decide
Gemini con una foto, que acierta más que la detección local (ver «Banco de pruebas» abajo). La
detección local no se va: sigue a 8 por segundo para la vista en vivo, los esqueletos, la colocación,
quién juega y el momento de la foto, y es la que decide si Gemini no contesta.

| Ajuste | Por defecto | Qué hace |
|---|---|---|
| `GAMES_JUDGE` | `gemini` | `gemini`: las rondas de Simón dice y de piedra, papel o tijera y las miradas de la búsqueda las juzga Gemini. `local`: como antes, todo en el equipo y la búsqueda con el modelo de visión (`LLM_*`). |
| `GAMES_JUDGE_TIMEOUT_SECONDS` | 4 | Plazo de Gemini en Simón dice, en piedra, papel o tijera y en cada mirada de la búsqueda; en la búsqueda, si Gemini no contesta, el modelo de visión tiene lo que queda de los 8 s que espera el juego (`JUDGE_TIMEOUT_S`). |

**Qué decide en cada juego:**

- **Simón dice** (`docs/juegos/poses.md`): cuántos hacen la pose y cuántos juegan en cada ronda,
  también en las trampas, con una foto: la del mejor recuento local de la ventana.
- **Piedra, papel o tijera** (`docs/juegos/piedra_papel_tijera.md`): la jugada del visitante en cada
  tirada, con el frame que elige la lectura local.
- **Búsqueda relámpago** (`docs/juegos/busqueda.md`): si se ve el objeto en cada mirada (`ModelJudge`
  con un cliente de Gemini, el mismo `JUDGE_PROMPT`, su plazo de 8 s y el tope por ronda de siempre).

**El juez** (`server/sonia/vision/referee.py`, `GeminiReferee`, que implementa `GameReferee` de
`contracts.py`):

- **Modelo.** El cliente del director de gestos (`settings.gestures.llm_settings(settings.llm)`):
  `gemini-3.1-flash-lite` por su endpoint compatible con OpenAI, con razonamiento `minimal` y
  `max_tokens` 1024. Solo está disponible si esa configuración apunta a Gemini y tiene clave
  (`GEMINI_API_KEY`, la misma que ya usan los gestos); si no, `build_game_vision` monta `NoReferee` y
  todo sigue como con `local`.
- **La foto.** Una por ronda, reducida a 640 px de ancho y en JPEG de calidad 75, sin espejo. Se
  codifica en un hilo (`asyncio.to_thread`) y nunca se guarda.
- **Las preguntas.** Dos prompts cerrados que prohíben describir a las personas:
  - poses: cuenta las personas que se ven (al menos de medio cuerpo o con los brazos a la vista; ni
    carteles ni murales) y cuántas hacen cada pose del banco (`brazos_arriba`, `un_brazo`,
    `pose_t`, `manos_cabeza`, `biceps`, `barbilla` o `ninguna`; cada persona en una sola), con el
    mensaje «Analiza la foto.» y la respuesta `{"personas": N, "brazos_arriba": n, ...}`;
  - manos: los gestos de piedra, papel o tijera de «la mano que enseña a la cámara la persona más
    cercana», de la más visible a la menos, con el mensaje «¿Qué gestos de piedra, papel o tijera se
    ven?» y la respuesta `{"manos": ["piedra" | "papel" | "tijera", ...]}`. El primero es la jugada;
    la lista vacía, que ninguna mano hace un gesto claro.
- **La respuesta.** Parseo tolerante: vale el JSON dentro de ```` ``` ```` o con texto alrededor.
  Poses: `PoseVerdict(people, counts)`, sin negativos y sin pasar de `personas`; las claves que no
  son poses se ignoran. Manos: `HandVerdict(shapes)`; las formas desconocidas se descartan.
- **Sin veredicto (`None`).** Si no contesta en el plazo, si falla o si el JSON no es el esperado.
  Nunca lanza. Lo que tarda cada foto va al registro.
- **Al arrancar**, el registro dice qué juez se usa; al apagar, `close()` cierra su cliente HTTP.

**Vueltas a lo local:**

| Caso | Qué pasa |
|---|---|
| `GAMES_JUDGE=local` | `NoReferee`: Simón dice y piedra, papel o tijera deciden en el equipo, sin fotos ni aviso; la búsqueda, con el modelo de visión (`LLM_*`) o sin juez si no hay. |
| Sin `GEMINI_API_KEY`, o los gestos apuntan a otro servidor | Lo mismo que `local`. |
| Gemini no contesta en el plazo, falla o el JSON no cuadra | Esa ronda la decide la detección local, como antes. En la búsqueda, la misma pregunta va al modelo de visión (`LLM_*`) con una foto nueva (`FallbackJudge`): un 429 de la clave de Gemini, que también usan los gestos todo el día, no deja la búsqueda sin juez. Sin foto o con el tope de la ronda alcanzado no se repite, y el tope cuenta preguntas, no llamadas. |

**Aviso de espera.** Mientras el juez mira, la pantalla enseña la pastilla de espera (`busy` con tipo
`judge`, `docs/protocolo.md`): «Mirando las poses…», «Mirando tu mano…» o «Mirando lo que
enseñas…». El juego la enciende justo antes de mandar la foto y la apaga en cuanto contesta (o se
acaba el plazo, o falla); al terminar la partida se apagan todas las suyas. Sin juez no sale.

### Banco de pruebas (10 de octubre de 2026)

Con la API real y 80 fotos públicas etiquetadas (nunca la cámara de nadie), `gemini-3.1-flash-lite`
por su endpoint compatible con OpenAI, con razonamiento `minimal`, fotos de 640 px y JPEG de calidad
75. Los prompts y la llamada son los del juez; el banco de pruebas quedó en el scratchpad de esa
sesión, no en el repo.

| Prueba | Gemini | Local `s` | Local `n` |
|---|---|---|---|
| Pose de una persona | 22 de 22 | 21 | 17 |
| Cuántos la hacen en un grupo (±1) | 10 de 11 | 9 | 9 |
| Piedra, papel o tijera | 18 de 18 | 15 | 14 |
| Fotos sin gesto, sin inventarse ninguno | 3 de 3 | 1 | 1 |
| Búsqueda relámpago | 25 de 25 | — | — |

- **Búsqueda:** el juez anterior (`gpt-6-luna`, el modelo de visión) acertó 24 de 25.
- **Tiempos:** mediana 1,25 s, p90 1,7 s y máximo 2,8 s, sin ningún error. La detección local tarda
  33 ms con `n` y 65 ms con `s`: el juez añade algo más de un segundo por ronda, que cubre la
  pastilla de espera.
- **Constancia:** la misma foto cinco veces da lo mismo.
- **Fallos:** contó a tres personas con los dos brazos arriba como `un_brazo`, y en multitudes de más
  de 60 personas se inventa las cifras (en el stand juegan unas pocas).
- **Tokens:** unos 1.350 de entrada por foto; `detail` no cambia nada.

## Modelos

| Modelo | Para qué | Origen (revisión fijada) | Tamaño | Licencia |
|---|---|---|---|---|
| `yolov8n-pose.onnx` | Poses, ligero (por defecto, `GAME_POSES_MODEL=n`) | `Xenova/yolov8n-pose` `da42240` | 13 MB | AGPL-3.0 (Ultralytics) |
| `yolov8s-pose.onnx` | Poses, preciso (`GAME_POSES_MODEL=s`) | `Xenova/yolov8s-pose` `9dd2818` | 47 MB | AGPL-3.0 (Ultralytics) |
| `palm_detection_mediapipe_2023feb.onnx` | Palmas (piedra, papel o tijera) | `opencv/palm_detection_mediapipe` `233e619` | 4 MB | Apache 2.0 |
| `handpose_estimation_mediapipe_2023feb.onnx` | 21 puntos de la mano | `opencv/handpose_estimation_mediapipe` `4b2a0b4` | 4 MB | Apache 2.0 |

Todos de Hugging Face, con la revisión en la URL y comprobados por SHA-256 (`models.py`).

- **Bajarlos:** `uv run --no-sync python -m sonia.vision.models` (desde `server/`) baja los cuatro
  (los dos de poses y los de manos) a `GAMES_MODELS_DIR` (`cache/games/modelos`). Solo baja lo que
  falte o no cuadre.
- **En la app:** `scripts/build_orquestador.sh` los baja si faltan y los mete todos en el
  orquestador congelado; la app los copia a su carpeta de datos al arrancar (`sonia.paths.SEEDED`,
  igual que los modelos de caras, también con `sonia caras`). `scripts/parchea_orquestador_windows.py`
  los baja si faltan y los añade igual a un orquestador de Windows ya congelado.
- **Al arrancar** la app solo exige el de poses de `GAME_POSES_MODEL` y los de manos: si faltan, el
  motor los baja en un hilo y, hasta que llegan, los juegos de cámara no se ofrecen. Con los modelos
  ya en su sitio, ese hilo los carga y los calienta con una detección en vacío, para que la primera
  ronda no pague la carga (unos 200 ms). El otro de poses se baja la primera vez que se pide.
- **Cambiar de modelo sin reiniciar:** el ajuste compartido `games_pose_model` del panel («Modelo de
  poses: ligero (n) o preciso (s)») manda sobre `GAME_POSES_MODEL`; vacío, vuelve al de
  `GAME_POSES_MODEL`. El motor llama a `GameManager.set_pose_model`, que usa
  `YoloPoseDetector.set_variant`: el modelo nuevo se carga en un hilo (y se baja si no vino con la
  app) mientras se sigue detectando con el viejo, y el cambio es atómico, también con una partida
  en marcha. Si el nuevo no carga, o falta y no se puede bajar, se queda el viejo con un aviso en el
  registro. `variant` dice el que está en uso.

## Rendimiento y aciertos (10 de octubre de 2026)

Medido en el Mac de desarrollo (Apple M1 Pro, 10 núcleos, OpenCV 5.0.0), con la máquina cargada por
otros agentes (carga media de 5 a 11): las cifras pueden salir algo peores de lo normal. Con 21
fotos públicas de Wikimedia Commons (grupos de frente, brazos arriba, una persona, manos haciendo
piedra, papel y tijera, y salas vacías), nunca la cámara de nadie. Pruebas en el scratchpad de esa
sesión, no en el repo.

**Motor de `cv2.dnn`.** En OpenCV 5 el motor clásico gasta bastante menos CPU que el nuevo con estos
modelos y da las mismas salidas, así que se carga con él (`models.load_onnx`):

| Poses, por detección | Clásico (reloj / CPU) | Nuevo (reloj / CPU) | Clásico con 1 hilo |
|---|---|---|---|
| `n` | 28-31 ms / 120 ms | 31 ms / 175 ms | 90 ms |
| `s` | 58-62 ms / 310 ms | 67 ms / 510 ms | 250 ms |

**Personas detectadas** (umbral 0,35; `s` y `n`):

| Foto | Personas | `s` | `n` |
|---|---|---|---|
| Grupo de 5 de frente | 5 | 5 | 5 |
| Grupo en dos filas | 20 | 18 | 17 |
| Sala con gente al fondo (varias solo con la cabeza a la vista) | 28 | 20 | 18 |
| Grupo en dos filas, uno tapado y otro cortado | 17 | 13 | 12 |
| Una persona con los dos brazos arriba | 1 | 1 | 1 |
| Seis saltando (de espaldas) | 6 | 6 | 6 |
| Una persona de pie en un escenario (tres fotos) | 1 | 1 | 1 |
| Salas vacías (dos fotos) | 0 | 0 | 0 |

De frente detecta a casi todos y no ve personas donde no las hay. Pierde a quien solo asoma la
cabeza por detrás de otros. Con umbral 0,25 `s` saca alguna más en los grupos (23 de 28, 15 de 17).

**Manos** (las de las fotos de piedra, papel y tijera y las de las personas):
- Piedra, papel y tijera bien leídas en 12 de las 13 manos con gesto de las fotos: un puño de lado,
  un choque de puños, dos partidas reales (piedra contra tijera, y una V en alto, una V horizontal y
  un puño), tres palmas abiertas y una V de espaldas. Con los brazos arriba lee las dos manos
  abiertas como papel, y los puños en alto como piedra.
- No lee una V pegada a la cámara que ocupa media foto (ni la palma ni la persona se ven bien): es
  el caso en que el juego pide un paso atrás.
- Una mano relajada colgando con los dedos estirados se lee como papel: por eso `read` pone primero
  la mano más alta, la que se enseña delante del cuerpo.
- Unos 20-45 ms por persona (las dos muñecas), y hasta 90 ms si hay que buscar también en la caja.

**Todo junto** (prueba de punta a punta con una foto como cámara a 1920x1080: `build_game_vision`,
poses continuas a 8 por segundo, vista en vivo a 10 por segundo con esqueletos y marcas, y las
manos del jugador cuatro veces por segundo): salen 8,0 detecciones y 10,0 frames de vista por
segundo, `look` sigue funcionando desde el stream, y el proceso usa de media **unos 3 núcleos con
`s` y 1,4 con `n`**. Preparar cada frame de la vista cuesta 3-5 ms.

## CPU del equipo del stand

- **En macOS** OpenCV reparte cada detección con GCD, que no hace caso de `cv2.setNumThreads` salvo
  con 1: no se puede limitar a 4 hilos. Con `s` a 8 por segundo son unos 3 núcleos del M1 Pro
  mientras dura el juego.
- **En Windows** (las ruedas de OpenCV usan otro reparto) el límite `DNN_THREADS` (4) sí vale.
  Falta medirlo en el equipo del stand (GMKtec EVO-X2, 16 núcleos) con Unity en marcha.
- **Por defecto, `n`** (`GAME_POSES_MODEL=n`, desde el 10 de octubre de 2026): cuesta la mitad de
  CPU y de frente detecta casi lo mismo. `s` (más preciso con gente tapada) se puede poner desde el
  panel si la CPU del equipo del stand va sobrada con Unity en marcha. Bajar `GAME_POSES_FPS` (por
  ejemplo a 5) también reparte menos carga.
