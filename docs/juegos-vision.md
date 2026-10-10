# Visión de los juegos

La parte de visión de los juegos nuevos del stand (`docs/plan-juegos.md`, sección 6): la cámara en
vivo, la vista en vivo encima de Sonnia, las poses, las manos de piedra, papel o tijera y el juez de
la búsqueda relámpago. Código en `server/sonia/vision`; los juegos lo usan a través de `GameHost`
(`sonia.games`) con las interfaces de `sonia/vision/contracts.py`.

Todo corre en el equipo del stand y en memoria: **nunca se guarda una imagen ni un dato de nadie y
no se reconoce a nadie** (solo dónde están hombros, codos, muñecas y dedos). Lo único que sale del
equipo es la foto reducida que el juez manda al modelo de visión, y solo en la búsqueda relámpago.

## Qué hay

| Pieza | Archivo | Qué hace |
|---|---|---|
| `CameraStream` | `stream.py` (`OpenCVCameraStream`) | Lee la cámara USB en un hilo mientras algún dueño la pida y guarda solo el último frame. |
| `PreviewStreamer` | `stream.py` (`LivePreview`) | La vista en vivo: frames `SNCV` a Unity, en espejo, 640x360, JPEG de calidad 60, 10 por segundo, con el dibujo del juego encima. |
| `PoseDetector` | `poses.py` (`YoloPoseDetector`) | Personas con sus 17 puntos (YOLOv8-pose en ONNX con `cv2.dnn`), en continuo o suelta. |
| `HandDetector` | `hands.py` (`MediaPipeHandDetector`) | Las manos de una persona: 21 puntos y piedra, papel, tijera o sin lectura. |
| `VisionJudge` | `judge.py` (`ModelJudge`) | Pregunta cerrada al modelo de visión sobre una foto fresca, con respuesta en JSON. |
| Dibujos | `overlay.py` | Esqueletos (verde o gris), manos, cajas, marcas ✓ y ✗ y etiquetas para la vista en vivo. |
| Modelos | `models.py` | Descarga con revisión fijada y SHA-256, y carga con el motor clásico de `cv2.dnn`. |
| Montaje | `games.py` (`build_game_vision`) | Monta todo con `VISION_SOURCE=opencv`; si algo falta, esa pieza dice que no está disponible. |

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
- **Juez.** Foto de 640 px de ancho y calidad 75, prompt que prohíbe describir a las personas (la
  ropa, las gafas o el pelo no cuentan como objeto), respuesta `{"visto": bool, "objeto": str}`,
  plazo de 8 s y tope por ronda (`start_round`). Pasado el tope, `ask` devuelve `None` sin llamar.

## Modelos

| Modelo | Para qué | Origen (revisión fijada) | Tamaño | Licencia |
|---|---|---|---|---|
| `yolov8s-pose.onnx` | Poses (por defecto, `GAME_POSES_MODEL=s`) | `Xenova/yolov8s-pose` `9dd2818` | 47 MB | AGPL-3.0 (Ultralytics) |
| `yolov8n-pose.onnx` | Poses, ligero (`GAME_POSES_MODEL=n`) | `Xenova/yolov8n-pose` `da42240` | 13 MB | AGPL-3.0 (Ultralytics) |
| `palm_detection_mediapipe_2023feb.onnx` | Palmas (piedra, papel o tijera) | `opencv/palm_detection_mediapipe` `233e619` | 4 MB | Apache 2.0 |
| `handpose_estimation_mediapipe_2023feb.onnx` | 21 puntos de la mano | `opencv/handpose_estimation_mediapipe` `4b2a0b4` | 4 MB | Apache 2.0 |

Todos de Hugging Face, con la revisión en la URL y comprobados por SHA-256 (`models.py`).

- **Bajarlos:** `uv run --no-sync python -m sonia.vision.models` (desde `server/`) los baja a
  `GAMES_MODELS_DIR` (`cache/games/modelos`). Solo baja lo que falte o no cuadre.
- **En la app:** `scripts/build_orquestador.sh` los baja si faltan y los mete en el orquestador
  congelado; la app los copia a su carpeta de datos al arrancar (`sonia.paths.SEEDED`, igual que
  los modelos de caras, también con `sonia caras`). `scripts/parchea_orquestador_windows.py` los
  añade a un orquestador de Windows ya congelado si este equipo los tiene en `cache/games/modelos`.
- **Si faltan al arrancar,** el motor los baja en un hilo y, hasta que llegan, los juegos de cámara
  no se ofrecen. Con los modelos ya en su sitio, ese hilo los carga y los calienta con una
  detección en vacío, para que la primera ronda no pague la carga (unos 200 ms).

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
- **Recomendación:** `s` en el EVO-X2 si la medida con Unity sale bien; **`n` si el equipo del
  stand es el Mac o un portátil** (`GAME_POSES_MODEL=n`): cuesta la mitad de CPU y de frente detecta
  casi lo mismo. Bajar `GAME_POSES_FPS` (por ejemplo a 5) también reparte menos carga.
