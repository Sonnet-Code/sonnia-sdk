# Plan: juegos nuevos del stand

> **Estado:** plan aprobado (10 de octubre de 2026, 01:55 en España / 19:55 del viernes 9 en Santo
> Domingo). Jean contestó las decisiones (sección 2) y el objetivo es **mañana, sábado 10**, último
> día del DevFest: la primera charla es a las 9:00 en Santo Domingo y la app nueva tiene que estar
> lista para instalarla hacia las 7:00 (calendario en la sección 9). Lo que no esté verificado a la
> hora de corte sale apagado.

## 1. Qué se va a hacer

Seis juegos para variar de la trivia. Entre todos cubren lo que la trivia no hace: que juegue un
grupo entero, que la gente se mueva y que se use la cámara.

| Juego | id | En una frase | Cámara | Dificultad |
|---|---|---|---|---|
| La ruleta de Sonnia | `ruleta` | Una ruleta en pantalla elige uno de cinco retos. | No | Media |
| Simón dice con poses | `poses` | Órdenes con nombre de meme dev; la cámara cuenta quién hace la pose, con la imagen en vivo encima de Sonnia. | Sí, en el equipo | Alta |
| Akinator dev | `akinator` | El visitante piensa en algo tech y Sonnia lo adivina con preguntas de sí o no. | No | Baja |
| Piedra, papel o tijera | `piedra_papel_tijera` | Uno contra Sonnia: la cámara lee la mano del jugador y ella saca la suya con el avatar. | Sí, en el equipo | Alta |
| Wordle de tecnología | `wordle` | Adivinar una palabra tech de 5 letras en 6 intentos, gritando palabras. | No | Media |
| Búsqueda relámpago | `busqueda` | «¡El primero que me enseñe algo azul!»: la cámara comprueba quién lo trae. | Sí, con el modelo de visión | Media |

Se reutiliza lo que ya hay:
- **La trivia como modelo:** `server/sonia/trivia`, `TriviaController` y `docs/trivia.md`.
- **Mensajes y voz:** `show_image`, `play_animation`, la caché de voces, los subtítulos y el panel.
- **Contenido:** el banco de la trivia.
- **Visión:** `look` y el modelo de visión, la cámara USB con OpenCV y la prueba de viabilidad de poses (sección 6).

## 2. Decisiones de Jean (10 de octubre de 2026)

- Se hacen los seis juegos.
- La ruleta lleva estos cinco retos:
  - Trivia relámpago.
  - Adivinanza geek.
  - Explica una tecnología en 20 segundos.
  - Predice el futuro de la IA.
  - Reto sorpresa de Sonnet Code.
- En el juego de poses, la imagen en vivo de la cámara sale en la franja alta, **encima de Sonnia**,
  para que la gente sepa dónde ponerse.
  - Es una excepción a la regla del 8 de octubre (las fotos de la cámara no se enseñan nunca en pantalla).
  - Vale solo en directo y mientras dura el juego.
  - La imagen nunca se guarda ni va a ningún modelo de la nube.
- Antes de programar, este plan.

Respuestas de Jean a las preguntas del plan:
- **Para mañana**, también los juegos de cámara («mañana sí habrá cámara»).
- **Vista en vivo** también en piedra, papel o tijera y en la búsqueda relámpago.
- **La ruleta** lleva solo los cinco retos.
- **Contenido editable desde el backoffice** (el panel de la nube), igual que el banco de la trivia:
  - los retos de Sonnet Code;
  - los demás bancos (adivinanzas, tecnologías, palabras del Wordle, objetos de la búsqueda, poses);
  - los temas del Akinator: por defecto, el mundo tech.

  Los primeros textos los escriben los agentes y se cambian desde el panel sin instalar nada.
- **Piedra, papel o tijera**, uno a la vez.
- **La búsqueda relámpago** puede gastar su tope de fotos al modelo de visión.
- **Sin premios**, como en la trivia: a quien gana se le manda con Brian o Mariel.

## 3. Reglas comunes a todos los juegos

Salen de lo aprendido con la trivia (`docs/trivia.md`) y de `CLAUDE.md`.

1. **Una sola delegación para empezar.** GPT-Live delega `start_game` y a partir de ahí el
   orquestador lleva el juego. Le pasa a GPT-Live dos cosas por dos vías distintas:
   - Lo que tiene que saber, por `session.instructions.append`. No la hace hablar.
   - Lo que tiene que decir ya, por `session.commentary.append`. Esta sí la hace hablar.

   Las jugadas que exigen entender al visitante (una palabra del Wordle, la respuesta a una
   adivinanza) sí van por una acción delegada, una por jugada. Nunca se depende de que el backend
   pase un guion entero: lo importante va directo a GPT-Live. Con la trivia se vio que, si el
   visitante contesta mientras Sonia aún habla, GPT-Live no vuelve a delegar: cada paso tiene que
   necesitar las menos delegaciones posibles.
2. **El orquestador guarda la clave y la pantalla; GPT-Live entiende y conduce.**
   - Nada de parsers de lo que dice el visitante (preferencia de Jean): GPT-Live lo interpreta y lo delega.
   - El orquestador sí puede seguir la transcripción de Sonia para sincronizar la pantalla, como ya hace la trivia.
3. **Un juego cada vez.**
   - No convive con la trivia, el Modo Jean, el editor de personaje, el modo debug ni el modo reunión.
   - Solo funciona en «Conversando», con Unity conectada y si esa Unity anuncia el juego (`client_hello.games`).
   - Mientras dura, se pausan como en la trivia: la animación de stand, la renovación de la sesión por inactividad y el saludo automático.
   - Se cancela si:
     - se cae o se renueva la sesión;
     - cambia el modo;
     - se termina desde el panel;
     - o por abandono: nadie habla ni hay nadie delante durante `GAMES_ABANDON_SECONDS`.
4. **Tiempos exactos.**
   - Las frases fijas con tiempo exacto («¡Simón dice…!», «¡Piedra, papel o tijera… ya!») van grabadas en la caché de voces (`LiveEngine.play_clip`). Así no gastan y el micro calla mientras suenan.
   - Si una frase no está grabada, va por `commentary` con el texto exacto.
   - Los contadores los lleva el orquestador y los pinta Unity.
5. **Cámara.**
   - Solo la cámara USB (`VISION_SOURCE=opencv`).
   - Las poses y las manos se detectan en el equipo del stand, en hilos, sin bloquear el bucle de audio.
   - Nunca se guarda una imagen ni un dato de nadie, y no se reconoce a nadie.
   - La vista en vivo sale solo durante los juegos que la usan, en espejo y con el rótulo «En vivo · no se graba».
   - El modelo de visión de la nube solo lo usa la búsqueda relámpago, con fotos reducidas, espaciadas y con un tope por ronda.
6. **Sin premios.** Como en la trivia, Sonnia no sabe qué premios hay: a quien gana lo manda con `TRIVIA_WIN_CONTACT` (Brian o Mariel).
7. **Nombre.**
   - En pantalla pone «Sonnia».
   - En lo que oye o lee GPT-Live y en las frases grabadas, «Sonia».
   - Lo que lee GPT-Live no nombra ninguna marca del stack, tampoco YOLO, OpenCV ni MediaPipe (lo vigila `test_sonia_no_conoce_las_marcas_de_su_stack`).
8. **Instrucciones cortas.**
   - El prompt base gana una sola línea con la lista de juegos.
   - Las reglas de cada juego entran al empezar por `instructions.append`, con un máximo de 1200 caracteres (hay test).
   - Al terminar, otra instrucción le dice que vuelva a conversar con normalidad.
   - Motivo: el 7 de octubre las instrucciones llegaron a 36 000 caracteres y GPT-Live dejó de delegar.
9. **Bancos editables desde el backoffice** (decisión de Jean). Funcionan como el banco de la trivia en la nube (`trivia_bank`, `docs/panel.md`):
   - El contenido de la app (palabras, adivinanzas, tecnologías, retos, objetos, poses, temas del Akinator) va en `assets/games/<juego>/*.md`, con el formato explicado al principio de cada archivo.
   - Cada banco se puede editar desde el panel y se guarda en la nube como ajuste compartido. Llega a todas las Sonnias sin instalar nada y manda sobre el archivo de la app. «Volver al de la app» lo borra.
   - Se relee al empezar cada partida y se valida: lo mal formado se salta con un aviso, y un banco sin entradas suficientes no se guarda.
   - Cada banco tiene un tope de 15 000 caracteres, para no pasar de los 256 KB de ajustes del Durable Object, donde el de la trivia ya ocupa hasta 100 000.
   - Los primeros textos los escriben los agentes, y el equipo los cambia desde el panel cuando quiera.
10. **Pruebas.**
    - Ningún test llama a APIs reales.
    - Cada pantalla se verifica con capturas 9:16 en Play (principio 8 de `CLAUDE.md`).
    - Las pruebas de Sonnia van en silencio (`set_volume` a 0).
11. **Compatibilidad con las apps ya instaladas.**
    - Unity anuncia los juegos que sabe pintar y el orquestador solo ofrece esos.
    - Una Unity vieja ignora los mensajes nuevos.
    - Los botones del panel llevan `data-cap`.

## 4. Fase 0: los cimientos compartidos

Los hace un solo agente antes que nadie, para que después cada agente trabaje en sus propios archivos.
Al acabar esta fase:
- Todo compila y los tests pasan.
- Cada juego existe como esqueleto apagado.
- Hay un orquestador falso para probar las pantallas.

### 4.1 Orquestador: `server/sonia/games/`

| Archivo | Qué lleva |
|---|---|
| `base.py` | El contrato de un juego (`Game`) y lo que puede usar (`GameHost`). |
| `manager.py` | `GameManager`: registro de juegos, exclusividad, ciclo de vida, pausas, abandono, reconexión de Unity y estado para el panel. |
| `host.py` | `GameHost` sobre el motor: hablar, instruir, frases grabadas, pantalla, animaciones, cámara, vista en vivo y visión. |
| `registry.py` | La lista de juegos, una línea por juego. Viene con todas puestas y apagadas, para que cada agente solo toque la suya. |
| `vision.py` | Las interfaces de visión (`CameraStream`, `PreviewStreamer`, `PoseDetector`, `HandDetector`, `VisionJudge`) con versiones falsas para los tests. Las reales las hace el agente de visión (sección 6). |
| `<juego>/` | Un paquete por juego, en esqueleto: `game.py`, `actions.py`... |

El contrato es orientativo: el agente de la fase 0 lo fija y lo documenta.

```python
class Game(Protocol):
    id: ClassVar[str]                  # "wordle"
    title: ClassVar[str]               # en pantalla: "Wordle de tecnología"
    spoken: ClassVar[str]              # para GPT-Live: "el Wordle de tecnología"
    needs: ClassVar[frozenset[str]]    # {"camera", "preview", "poses", "hands", "vision_llm"}

    def actions(self) -> list[ActionSpec]: ...         # jugadas propias (además de start y stop)
    def banks(self) -> list[GameBank]: ...             # bancos editables desde el backoffice
    def unavailable_reason(self) -> str | None: ...    # None: se puede jugar
    async def start(self, source: str, options: dict[str, Any]) -> str: ...  # guion de arranque
    async def stop(self, reason: str) -> None: ...
    async def tick(self, now: float) -> None: ...
    # Ganchos; por defecto no hacen nada.
    async def on_assistant_text(self, text: str, final: bool) -> None: ...
    def on_user_text(self, now: float) -> None: ...
    def on_user_turn_end(self, now: float, started_at: float) -> None: ...
    def on_delegation(self, now: float) -> None: ...
    async def on_unity_event(self, event: str, data: dict[str, Any]) -> None: ...
    def snapshot(self) -> dict[str, Any]: ...          # para el panel


class GameHost(Protocol):
    async def speak(self, prompt: str) -> bool: ...      # commentary: la hace hablar
    async def instruct(self, text: str) -> bool: ...     # instructions.append: lo sabe, no habla
    async def say_fixed(self, text: str) -> bool: ...    # frase grabada si la hay; si no, commentary
    async def wait_idle(self, limit_s: float | None = None) -> bool: ...
    def quiet_for(self) -> float: ...
    def touch(self) -> None: ...
    async def send(self, game: str, event: str, data: dict[str, Any], *, sticky: bool = True) -> None: ...
    async def play_animation(self, clip: str) -> None: ...   # siempre con whole=True
    preview: PreviewStreamer    # start(overlay=...) y stop()
    poses: PoseDetector
    hands: HandDetector
    judge: VisionJudge
    rng: random.Random
```

**Acciones** (`server/sonia/actions/games.py`):
- `start_game(juego)`.
  - `juego` es obligatorio: un enum con los juegos disponibles en ese momento.
  - Devuelve el guion de arranque.
  - Si ya hay otro juego o la trivia en marcha, dice cuál es y cómo seguir.
- `stop_game()` termina el que haya.
- Cada juego registra sus jugadas con `Game.actions()` (`wordle_guess`, `akinator_guess`...).
  - Los esquemas son estrictos: parámetros obligatorios.
  - Cada enum lleva un valor para «no lo dijo». Lección de la trivia: un nivel opcional, el backend lo rellenaba siempre con «fácil».

**Motor** (`server/sonia/live/engine.py`):
- Un `GameManager` junto a la trivia, al que se llama en los mismos puntos donde hoy se llama a `self._trivia` (buscar `_trivia`):
  - la transcripción de Sonia y la del visitante;
  - el fin de turno y las delegaciones;
  - `tick` y la sesión perdida;
  - la pausa de la animación de stand y de la renovación por inactividad;
  - `ctx.extra` y el estado del panel.
- Los `game_event` que manda Unity van al juego activo.

**Trivia.** Dos cambios mínimos, que solo añaden:
- No arranca si hay un juego en marcha.
- `TriviaGame.draw_one(level)` saca una pregunta del banco en uso (el de la nube, si lo hay) y respeta el «sin repetir». La usa la trivia relámpago de la ruleta.

**Prompts** (`server/sonia/live/prompts.py`):
- Una sola línea en las herramientas del backend y en la política de delegación: «Juegos: ruleta, Simón dice con poses, Akinator, piedra, papel o tijera, Wordle de tecnología y búsqueda relámpago. Delega empezarlos y terminarlos; las reglas te llegan al empezar».
- Ninguna regla de juego va en el prompt base.

**Ajustes** (`server/sonia/config.py` y `.env.example`):
- `GamesSettings`: `GAMES_ENABLED`, `GAMES_ABANDON_SECONDS` y `GAMES_MODELS_DIR`.
- Un bloque por juego con los valores por defecto de la sección 5. Prefijos: `GAME_RULETA_`, `GAME_POSES_`, `GAME_AKINATOR_`, `GAME_PPT_`, `GAME_WORDLE_` y `GAME_BUSQUEDA_`.
- Todos los bloques los crea la fase 0, para que nadie más toque `config.py`. Cada agente solo cambia valores de su bloque.

**Frases grabadas.** Un registro de las frases fijas de los juegos, para que entren en `cache/voice` con «Preparar voces» y con la grabación automática. La build ya empaqueta esa caché.

**Panel y backoffice** (`server/sonia/panel/`; el de la nube copia estos estáticos con `cloud/panel/scripts/build.mjs`):
- Una tarjeta «Juegos» con:
  - un botón por juego;
  - «Terminar juego» y el estado del juego en marcha.
- Un interruptor por juego, guardado en la nube como ajuste compartido (`games_off`, la lista de los apagados). Si un juego falla en el stand, el equipo lo apaga desde el móvil sin reinstalar.
- «Bancos de los juegos», como «Banco de preguntas» de la trivia:
  - Se elige el banco, se carga el que está en uso, se edita y se guarda.
  - Se guarda en la nube, en el ajuste compartido `game_banks` (`{banco: texto}`), con la orden `set_game_bank` (`bank`, `text`). El orquestador lo valida con el analizador del juego antes de guardarlo.
  - «Volver al de la app» borra la versión de la nube.
  - Los bancos los declara cada juego (`Game.banks()`: id, título, archivo de la app, analizador y mínimo de entradas). La fase 0 deja el mecanismo y cada agente declara los suyos.
- Órdenes `game_start` y `game_stop`.
- Capacidades `games`, `game:<id>` y `game_banks`, según lo que anuncie Unity. Las Sonnias anteriores ignoran los ajustes nuevos.

### 4.2 Protocolo

Se actualizan los tres a la vez: `docs/protocolo.md`, `server/sonia/ws/protocol.py` y `Protocol.cs`.

**Del orquestador a Unity, un sobre común.** Unity lo reparte por `game` y cada controlador lee su `data`:

```json
{"type": "game", "game": "wordle", "event": "guess", "seq": 7, "data": {"row": 2, "letters": "LINUX", "marks": "gyxxg"}}
```

- Hay dos eventos comunes:
  - `start` monta la pantalla del juego y pide el plano de panel.
  - `end` da el resultado y retira la pantalla. `data.result` vale `win`, `lose` o `cancel`.
- Los demás eventos son propios de cada juego (sección 5).
- El último estado va como mensaje fijo (`hub.set_sticky("game", …)`), para repetirlo si Unity se reconecta. `end` lo borra.

**De Unity al orquestador:**

```json
{"type": "game_event", "game": "ruleta", "event": "wheel_stopped", "data": {"segment": 3}}
{"type": "client_hello", "client": "unity", "version": "…", "games": ["ruleta", "wordle"], "features": ["camera_preview"]}
```

**Vista en vivo de la cámara.** Un mensaje la enciende y la apaga:

```json
{"type": "camera_preview", "on": true, "mirror": true}
```

- La imagen va en frames binarios con marca propia, como la voz del invitado (`SNGU`): `SNCV` + `seq` (uint32) + ancho y alto (uint16) + flags (uint8) + JPEG.
- Unos 10 por segundo, a 640x360.
- El orquestador dibuja los esqueletos y las marcas sobre la imagen antes de codificarla: así van sincronizados y se dibujan en un solo sitio.
- Unity muestra el último frame que llega. Lo retira con `on: false` o si pasan 2 s sin imagen.

### 4.3 Unity: `unity/Assets/Scripts/Sonia/Games/`

El código va en el ensamblado `Sonia` (`Sonia.asmdef`).

| Archivo | Qué lleva |
|---|---|
| `GameRouter.cs` | Recibe `game` y `camera_preview` de `SoniaClient` y los reparte. Manda `game_event` y registra los controladores. |
| `IGameController.cs` | El contrato de un controlador: `Id`, `OnEvent(evento, json)`, `OnEnd` e `IsActive`. |
| `GameHud.cs` | Lo común de pantalla, construido por código en el Canvas del HUD (`SoniaHUD`), como la trivia. Detalle debajo de la tabla. |
| `CameraPreviewPanel.cs` | La vista en vivo en la franja alta, encima de Sonnia: textura reutilizada (`Texture2D.LoadImage`), aspecto 16:9, esquinas redondeadas y el rótulo «En vivo · no se graba». |
| `<Juego>/` | Una carpeta por juego, en esqueleto. |

`GameHud` lleva:
- la tarjeta de la franja alta, el título, el contador circular y el rótulo del resultado;
- el confeti y los destellos, copiados de los de la trivia sin tocar `TriviaController`;
- la petición del plano de panel (`CameraFramingController.PanelRequestOffset`);
- el aviso a `StageScreen` para que aparte el QR y la invitación.

Cambios en el código que ya hay:
- `SoniaClient` y `Protocol.cs` entienden el sobre `game` y los frames `SNCV`. Unity le pasa el JSON crudo de `data` al controlador, que lo deserializa con sus propias clases, dentro de su carpeta.
- `client_hello` anuncia los juegos registrados.
- `SoniaClient` acepta `-sonia-ws ws://127.0.0.1:<puerto>`, para que cada agente pruebe con su orquestador falso en su propio puerto (hoy la URL solo se cambia en la escena).

### 4.4 Herramientas y documentación

- **`scripts/juegos_demo.py`:** un orquestador falso (servidor WebSocket en un puerto propio) que manda a Unity la secuencia de un juego paso a paso (`--juego wordle`).
  - Para la vista en vivo usa frames de fotos o vídeos públicos, nunca la cámara de Jean.
  - Arranca con `set_volume` a 0.
- **Versiones falsas para los tests:**
  - un `GameHost` que apunta lo que se dijo y lo que se mandó;
  - detectores que devuelven personas y manos inventadas.
- **Documentación:**
  - `docs/juegos.md`: los cimientos, las reglas comunes y cómo añadir un juego;
  - `docs/juegos/<juego>.md`: vacíos, con sus apartados, para que cada agente rellene el suyo.

## 5. Los juegos

### 5.1 La ruleta de Sonnia (`ruleta`)

**Qué es.** Una ruleta de cinco casillas gira en la franja alta y cae en un reto. Al terminarlo, Sonnia ofrece otra vuelta.

**Flujo.**
1. Se lanza con `start_game(ruleta)`, por voz o desde el panel.
   - El orquestador elige la casilla con los pesos de `GAME_RULETA_WEIGHTS`, sin repetir la anterior.
   - Manda `spin` con la casilla de destino.
   - Unity gira, frena y avisa con `wheel_stopped`.
2. Con la ruleta parada, el orquestador pasa a GPT-Live las reglas del reto (`instruct`) y le pide que lo anuncie (`speak`).
3. Se juega el reto (tabla de abajo). Al terminar:
   - salen el resultado y la reacción de Sonnia, y ella pregunta «¿otra vuelta?»;
   - si quieren otra, `ruleta_spin`;
   - si no, `stop_game`.

**Los cinco retos.**

| Casilla | Cómo se juega | Jugadas delegadas | Pantalla |
|---|---|---|---|
| Trivia relámpago | Una pregunta de tres opciones del banco de la trivia (`draw_one`), sin gorra ni el requisito de seguir a Sonnet Code. GPT-Live no sabe la buena hasta el resultado. | `ruleta_answer(opcion)`: `A`, `B`, `C` o `no_lo_sabe` | Tarjeta con las opciones y un contador de `GAME_RULETA_QUIZ_SECONDS` (solo visual). Acierto o fallo, con confeti. |
| Adivinanza geek | Una adivinanza de `adivinanzas.md` (texto, respuesta, variantes válidas y pista). GPT-Live recibe la respuesta para juzgar respuestas libres y no la dice. La pista sale a los `GAME_RULETA_HINT_SECONDS`. | `ruleta_answer(resultado)`: `acierto`, `fallo` o `se_rinden` | La adivinanza, la pista cuando toca y la solución al final. |
| Explica en 20 segundos | Una tecnología al azar de `tecnologias.md`. El tiempo arranca cuando el visitante empieza a hablar, o a los 5 s. Al acabar, GPT-Live le pone nota del 1 al 10, con humor. | `ruleta_score(nota)` | La tecnología en grande con un contador circular, «¡Tiempo!» y la nota con estrellas. |
| Predice el futuro de la IA | El visitante hace su predicción y Sonnia la resume con una «probabilidad» puesta con gracia. | `ruleta_prediccion(prediccion, probabilidad)`: hasta 120 caracteres y de 0 a 100 | Tarjeta con la predicción y una barra de probabilidad. |
| Reto sorpresa de Sonnet Code | Un reto de `retos-sonnet-code.md`: una pregunta sobre Sonnet Code (respuesta en el banco) o un reto de stand (seguir a Sonnet Code y enseñar el móvil, chocar los cinco con Brian o Mariel, una foto con Sonnia etiquetando a @sonnetcode). Se cree al visitante, como en la trivia. | `ruleta_answer(resultado)` | El reto y el resultado. |

**Unity** (`Games/Ruleta/`):
- La ruleta: cinco casillas con icono y texto en los colores de Google, un puntero y un giro con frenada y «clics» visuales.
- Las cinco tarjetas de los retos.
- Las reacciones de Sonnia, con los clips que ya usa la trivia.

**Ajustes** (`GAME_RULETA_`):

| Ajuste | Por defecto |
|---|---|
| `ENABLED` | activado |
| `WEIGHTS` | `1,1,1,1,1` |
| `QUIZ_SECONDS` | 20 |
| `HINT_SECONDS` | 30 |
| `EXPLAIN_SECONDS` | 20 |
| `ABANDON_SECONDS` | 60 |

**Bancos** (`assets/games/ruleta/`). Los tres se editan desde el backoffice:

| Archivo | Cuántas | Nota |
|---|---|---|
| `adivinanzas.md` | unas 30 | — |
| `tecnologias.md` | unas 40 | — |
| `retos-sonnet-code.md` | unos 12 | Solo con datos de `assets/knowledge/04-sonnet-code.md`. |

### 5.2 Simón dice con poses (`poses`)

**Qué es.**
- Sonnia da órdenes con nombre de meme dev y la pose dicha en claro: «¡Simón dice: pasaron todos los tests, brazos arriba!».
- La cámara cuenta cuántos hacen la pose.
- Algunas rondas son trampa: la orden sale sin «Simón dice».
- El resultado es colectivo («¡7 de 9!»): nunca se elimina a nadie.

**Vista en vivo (decisión de Jean).**
- Al empezar, la imagen de la cámara sale arriba de Sonnia, en espejo.
- Encima van dibujados los esqueletos de quienes juegan: en verde si hacen la pose, en gris si no.
- Sirve para que la gente sepa dónde ponerse y para pedir el paso atrás.

**Flujo.**
1. Se lanza con `start_game(poses)` y se enciende la vista en vivo.
2. Colocación:
   - El orquestador mira a cuántos ve y si se les ven los brazos.
   - Si hay gente demasiado cerca (hombros sin muñecas, o cuerpos que se salen por arriba), le pide a Sonnia que les pida un paso atrás, hasta unos 2 m.
3. Se juegan `GAME_POSES_ROUNDS` rondas. De ellas, `GAME_POSES_TRICKS` son trampa, y nunca la primera. En cada ronda:
   1. Sonnia demuestra la pose (ver Unity) y sale su pictograma.
   2. Suena la orden como frase grabada, exacta en el tiempo y en si dice «Simón dice». Si no está grabada, va por `commentary` con el texto exacto.
   3. Se abre una ventana de `GAME_POSES_WINDOW_SECONDS` tras la orden. De todos los frames de la ventana, cuenta el mejor recuento.
   4. Resultado: las marcas en la vista en vivo y «7 de 9». A GPT-Live le llegan los números por `speak` para que reaccione en una frase; en las trampas, «¡cayeron 4!».
4. Al final, el total de la partida y una celebración.

**Poses.** Van en `assets/games/poses/poses.md`, con su id, la frase con el meme, una instrucción clara y la demostración. Desde el backoffice se cambian las frases y la instrucción y se activan o desactivan poses. Las reglas de detección van en el código: una pose nueva necesita su regla.

| id | Orden | Pose | Cómo se detecta |
|---|---|---|---|
| `brazos_arriba` | «¡Pasaron todos los tests!» | Los dos brazos arriba. | Las muñecas (o los codos, si no se ven) por encima de la cabeza. |
| `un_brazo` | «Subiendo a producción» | Un brazo arriba. | Una muñeca por encima de la cabeza y la otra no. |
| `pose_t` | «Pose T, la del avatar sin animar» | Brazos en cruz. | Los brazos estirados, a menos de 35° de la horizontal. |
| `manos_cabeza` | «Deploy un viernes» | Manos a la cabeza. | Las dos muñecas junto a la cabeza. |
| `biceps` | «Compiló a la primera» | Sacar bíceps. | Los codos a la altura de los hombros y las muñecas por encima de los codos. |
| `barbilla` | «Revisando el PR» | Mano en la barbilla. | Una muñeca junto a la nariz, por debajo de ella. |

**Detección.**
- `PoseDetector` (agente de visión) da personas con 17 puntos normalizados.
- El juego se queda solo con quien juega: una altura mínima en la imagen (`GAME_POSES_MIN_PERSON`).
- Aplica reglas permisivas: si falta la muñeca, cuenta el codo, y se miden ángulos, no posiciones absolutas.
- Por qué el veredicto es colectivo y generoso: según la prueba de viabilidad (sección 6), en grupos de frente detecta a casi todos, pero en una multitud apretada con los brazos arriba los brazos se cruzan y cuenta de menos.

**Unity** (`Games/Poses/`):
- La vista en vivo, grande, en la franja alta.
- El pictograma de la pose (un monigote blanco) en una esquina, el rótulo de la orden y el contador «7 de 9».
- Sonnia demuestra cada pose:
  - Lo ideal es una pose sostenida por código sobre el humanoide (valores de músculos, como el gorro de la trivia mueve los brazos), para que salga exacta.
  - Si no, clips de Sage que se le parezcan (`facepalmTinashe02`, `touchBeard`, `armsOnHips`) y la celebración de la trivia para «brazos arriba».

**Ajustes** (`GAME_POSES_`):

| Ajuste | Por defecto |
|---|---|
| `ENABLED` | activado |
| `ROUNDS` | 6 |
| `TRICKS` | 1 |
| `WINDOW_SECONDS` | 1.8 |
| `MIN_PERSON` | 0.25 (fracción de la altura de la imagen) |
| `FPS` | 8 (detecciones por segundo) |
| `MODEL` | `s` |

### 5.3 Akinator dev (`akinator`)

**Qué es.**
- El visitante piensa en algo del mundo tech: un lenguaje, una herramienta, una empresa, un producto de Google o un personaje de la informática.
- Sonnia lo adivina con preguntas de sí o no, como mucho `GAME_AKINATOR_MAX_QUESTIONS`.
- Los temas que valen están en `assets/games/akinator/temas.md` y se editan desde el backoffice. Por defecto, el mundo tech; ahí se pueden añadir, por ejemplo, cosas dominicanas.

**Flujo.**
1. Se lanza con `start_game(akinator)`.
   - Sale la tarjeta «Piensa en algo… y no lo digas».
   - Las reglas llegan a GPT-Live por `instruct`:
     - preguntas de sí o no, de una en una;
     - acepta «no sé» y «a veces»;
     - no intenta adivinar antes de la quinta pregunta;
     - si no lo saca en 20, pide la respuesta.
2. GPT-Live pregunta sin delegar: una delegación por pregunta lo haría lentísimo. El orquestador cuenta las preguntas de Sonnia en su transcripción (las que acaban en «?»), solo para el contador de pantalla.
3. Cuando lo tiene claro, delega `akinator_guess(respuesta)` y sale una tarjeta grande: «¿Es… Kotlin?».
4. El visitante confirma con `akinator_result(acierto, respuesta_real)`.
   - Si acierta: confeti y Sonnia presume.
   - Si falla: «¡me ganaste!» con lo que era. Puede seguir preguntando hasta llegar a 20.

**Unity** (`Games/Akinator/`):
- Una tarjeta con motivo de bola de cristal y 20 puntos de progreso.
- La adivinanza final y el resultado.
- Mientras piensa, gestos de pensar (`touchBeard`).

**Ajustes** (`GAME_AKINATOR_`):

| Ajuste | Por defecto |
|---|---|
| `ENABLED` | activado |
| `MAX_QUESTIONS` | 20 |
| `ABANDON_SECONDS` | 60 |

### 5.4 Piedra, papel o tijera (`piedra_papel_tijera`)

**Qué es.** Uno contra Sonnia, de uno en uno (decisión de Jean). Ella saca la mano con el avatar y la cámara lee la del jugador. Se juega al mejor de `GAME_PPT_ROUNDS`, con un marcador «Sonnia 1 - 2 Tú».

**Quién juega.** La persona más cercana a la cámara y más centrada, la de cuerpo más grande en la imagen. En la vista en vivo sale resaltada y los demás no cuentan. Si cambia de persona a mitad de partida, el juego sigue: es el que tiene la mano delante.

**Flujo.**
1. Se lanza con `start_game(piedra_papel_tijera)`. Se enciende la vista en vivo para que el jugador sepa dónde poner la mano: delante del cuerpo, a la altura del pecho.
2. En cada ronda:
   1. El orquestador elige la jugada de Sonnia **antes** de mirar.
   2. Suena la frase grabada «¡Piedra, papel o tijera… ya!» y Sonnia agita el puño al ritmo.
   3. En el «ya», Unity pone su mano.
   4. El orquestador lee la mano del jugador durante `GAME_PPT_READ_SECONDS` y se queda con la lectura estable.
3. Resultado:
   - La jugada de cada uno en grande («Piedra contra tijera») y el marcador.
   - GPT-Live reacciona.
   - Si no ve la mano o no la entiende, lo dice («¡no te vi la mano!») y repite la ronda una vez.
4. Al final, quién gana la partida. Si gana el visitante, se le manda con Brian o Mariel, como en la trivia.

**Detección** (`HandDetector`, del agente de visión):
- Las muñecas del `PoseDetector` dicen dónde mirar; se recorta alrededor de cada una.
- Un modelo de 21 puntos de la mano (a comprobar: los de MediaPipe del OpenCV Zoo) dice qué dedos están estirados:

  | Dedos estirados | Lectura |
  |---|---|
  | Ninguno, o solo el pulgar | piedra |
  | Índice y corazón | tijera |
  | Cuatro o cinco | papel |
  | Cualquier otra cosa | sin lectura |

- Solo se leen las manos del jugador (las dos muñecas de la persona elegida). Vale la que esté levantada delante del cuerpo.

**Unity** (`Games/Ppt/`, `SoniaHandPoser`):
- El brazo derecho al frente, con IK como `TriviaHat`.
- El puño se agita tres veces y la mano termina con su forma, moviendo los dedos con los músculos del humanoide.
- Es la parte más delicada. Jean es muy exigente con manos y dedos (`docs/unity.md`, «Manos y dedos»), así que se valida por fotogramas, no con una captura suelta.

**Ajustes** (`GAME_PPT_`):

| Ajuste | Por defecto |
|---|---|
| `ENABLED` | activado |
| `ROUNDS` | 3 (al mejor de tres) |
| `READ_SECONDS` | 0.8 |

### 5.5 Wordle de tecnología (`wordle`)

**Qué es.** Una palabra tech de 5 letras en 6 intentos. El grupo grita palabras y GPT-Live elige una, la escribe bien y la delega.

**Flujo.**
1. Se lanza con `start_game(wordle)`. El orquestador elige una palabra de `palabras.md`: 5 letras, sin tildes y con una pista cada una. GPT-Live no la sabe.
2. Cada intento es un `wordle_guess(palabra)`.
   - El orquestador acepta cualquier palabra de 5 letras, sin diccionario: es más divertido y evita discusiones.
   - Colorea las letras con la regla del Wordle real, también con letras repetidas, y manda `guess`.
   - A GPT-Live le devuelve un resumen corto («la L y la U están, pero en otro sitio») para que anime al grupo.
3. Tras `GAME_WORDLE_HINT_AFTER` intentos sale la pista del banco. Si aciertan, confeti; si no, sale la palabra.

**Unity** (`Games/Wordle/`):
- Una rejilla de 6×5 con volteo de fichas y los colores clásicos.
- Una sacudida si la palabra no vale.
- Una fila con las letras usadas.
- Confeti al acertar.

**Ajustes** (`GAME_WORDLE_`):

| Ajuste | Por defecto |
|---|---|
| `ENABLED` | activado |
| `ROWS` | 6 |
| `HINT_AFTER` | 4 |
| `ABANDON_SECONDS` | 90 |

**Banco** (`assets/games/wordle/palabras.md`, editable desde el backoffice): unas 60 palabras fáciles de pronunciar, cada una con su pista. Por ejemplo: LINUX, REACT, SWIFT, KAFKA, REDIS, CLOUD, PIXEL, FLASK, SCALA o JULIA. Son términos técnicos tal como se dicen en el sector, de 5 letras y sin tildes.

### 5.6 Búsqueda relámpago (`busqueda`)

**Qué es.** «¡El primero que me enseñe algo azul!». La cámara comprueba quién lo trae. Se juegan `GAME_BUSQUEDA_ROUNDS` rondas.

**Flujo.**
1. Se lanza con `start_game(busqueda)` y se enciende la vista en vivo, para que sepan dónde enseñar el objeto.
2. En cada ronda sale un objeto al azar de `objetos.md`, con su tarjeta y un contador de `GAME_BUSQUEDA_ROUND_SECONDS`.
3. Comprobación:
   - Cada `GAME_BUSQUEDA_CHECK_SECONDS` va una foto reducida al modelo de visión (`VisionJudge`).
   - Lleva una pregunta cerrada y la respuesta vuelve en JSON: `{"visto": true, "objeto": "botella azul"}`.
   - Hay un tope de `GAME_BUSQUEDA_MAX_CHECKS` fotos por ronda.
   - Si alguien grita «¡aquí!», GPT-Live delega `busqueda_check()` y se mira al momento.
4. En cuanto aparece: «¡Lo veo!» y confeti. Sonnia lo celebra describiendo el objeto, nunca a la persona.

**Objetos** (`assets/games/busqueda/objetos.md`, editable desde el backoffice).
- Cosas que la gente lleva en un evento: algo azul, algo rojo, la credencial del DevFest, una botella, unas llaves, un bolígrafo, un cable USB-C, un sticker, algo con el logo de Google…
- Nada que obligue a hablar de la persona: ni gafas ni ropa.

**Unity** (`Games/Busqueda/`): la vista en vivo, la tarjeta con el objeto y el contador, y «¡Encontrado!».

**Ajustes** (`GAME_BUSQUEDA_`):

| Ajuste | Por defecto |
|---|---|
| `ENABLED` | activado |
| `ROUNDS` | 3 |
| `ROUND_SECONDS` | 25 |
| `CHECK_SECONDS` | 2.5 |
| `MAX_CHECKS` | 10 |

**Coste.** Unas 10 fotos por ronda al modelo de visión, aprobado por Jean. Se mide en la primera prueba real.

## 6. Visión (agente A1)

Implementa las interfaces de `server/sonia/games/vision.py`.

- **`CameraStream`.**
  - Lee la cámara USB sin parar, en un hilo, mientras algún juego la pide, y guarda el último frame.
  - Mientras está activa, `OpenCVCamera.capture()` coge el frame del stream en vez de leer el dispositivo. Así nunca hay dos lecturas a la vez de `look`, las caras, la presencia y el juego.
- **`PreviewStreamer`.**
  - Frames en espejo a 640x360, JPEG de calidad ~60 y unos 10 por segundo, enviados por `SNCV`.
  - Admite una función de dibujo opcional (esqueletos, manos, marcas).
  - Codifica en un hilo.
- **`PoseDetector`.**
  - Usa YOLOv8-pose en ONNX con `cv2.dnn` de OpenCV 5, sin dependencias nuevas.
  - Modelos de Hugging Face, ambos de `onnx/model.onnx`:

    | Variante | Repositorio | Tamaño | SHA256 |
    |---|---|---|---|
    | `s` | `Xenova/yolov8s-pose` | 47 MB | `5c92815cc509a9ccb6a817f4c2816de800092964319ad179a2751eda6df35d83` |
    | `n` | `Xenova/yolov8n-pose` | 13 MB | `04f6d2416266f2aba6c5ba8b26de33ed9eba3279f972ac02e33f9f1366547586` |

  - Se fija la revisión, se guarda en `cache/games/modelos` y se empaqueta en la app, como los modelos de caras.
  - Entrada de 640 con letterbox, ÷255 y en RGB. Salida `[1, 56, 8400]`, con NMS.
  - Los hilos de OpenCV van limitados para dejar CPU a Unity.
- **`HandDetector`.** Recorta alrededor de las muñecas que da el `PoseDetector`, saca los 21 puntos de la mano y clasifica en piedra, papel o tijera.
- **`VisionJudge`.**
  - Le hace una pregunta cerrada sobre una foto al modelo de visión que ya usa Sonia (`server/sonia/llm`).
  - Pide JSON estricto, prohíbe describir personas y lleva tope de llamadas.
- **CPU del equipo del stand.** Hay que medirla en Windows con Unity en marcha. Si no llega, el modelo `n` o menos detecciones por segundo.

**Prueba de viabilidad del 10 de octubre.** Se hizo en el scratchpad de esa sesión, no en el repo, con fotos públicas de Wikimedia Commons.
- `cv2.dnn` de OpenCV 5.0.0 carga los dos modelos.
- En el Mac tardan unos 30 ms (`n`) y 70 ms (`s`) por foto.
- Con `s`, en fotos de frente:
  - 27 de unas 30 personas en una foto de grupo;
  - 11 de 13 en una de dos filas.
- Falla con:
  - gente pegada a la cámara (solo se ven caras);
  - filas de atrás tapadas;
  - brazos arriba que se cruzan: 4 de 9 en una foto de saltos.

## 7. Reparto en agentes

### 7.1 Fases

Para llegar a mañana, la fase 0 se parte en dos agentes que trabajan a la vez, y la visión arranca con ellos.

| Fase | Quién | Qué | Rama | Depende de |
|---|---|---|---|---|
| 0 | F0-Py «Cimientos del orquestador» (Opus) | 4.1, el lado Python de 4.2 y 4.4 | `juegos/f0-py` | — |
| 0 | F0-Unity «Cimientos de Unity» (Opus) | El lado Unity de 4.2 y 4.3, con capturas del `GameHud` y de la vista en vivo | `juegos/f0-unity` | — |
| 0 | A1 «Visión» (Opus) | Sección 6 | `juegos/vision` | — (implementa las interfaces tal como las describe este plan) |
| 1 | A2 «Ruleta» (Opus) | 5.1 | `juegos/ruleta` | `juegos/base` |
| 1 | A3 «Poses» (Opus) | 5.2, con detectores falsos hasta que llegue A1 | `juegos/poses` | `juegos/base`, y A1 para la prueba final |
| 1 | A4 «Akinator» (Sonnet) | 5.3 | `juegos/akinator` | `juegos/base` |
| 1 | A5 «Piedra, papel o tijera» (Opus) | 5.4 | `juegos/ppt` | `juegos/base`, y A1 para la prueba final |
| 1 | A6 «Wordle» (Sonnet) | 5.5 | `juegos/wordle` | `juegos/base` |
| 1 | A7 «Búsqueda» (Sonnet) | 5.6 | `juegos/busqueda` | `juegos/base`, y A1 (`VisionJudge`, vista en vivo) |
| 2 | La sesión principal (+ I «Integración», Opus, si hace falta) | Fusión en `juegos/integracion`, pruebas completas, verificación en el editor real y en la app | — | Fase 1 |
| 3 | R «Revisión» (Fable) | Revisión de todo el cambio antes de las builds | — | Fase 2 |

**Contratos primero.**
- En cuanto los tengan, F0-Py y F0-Unity hacen un primer commit solo con los contratos:
  - las clases e interfaces de 4.1 y 4.3;
  - el registro con los seis juegos apagados y los esqueletos de cada juego;
  - los mensajes del protocolo;
  - los bloques de ajustes.
- La sesión principal junta esos dos commits en `juegos/base` y lanza A2-A7 desde ahí.
- F0-Py y F0-Unity siguen con el resto. Lo que añadan llega a los agentes de juegos con `git merge juegos/base`, cuando la sesión principal vuelva a juntarlo.

**Reparto entre F0-Py y A1:**
- F0-Py escribe en `server/sonia/games/vision.py` las interfaces y los falsos, y en `protocol.py` el empaquetado de los frames `SNCV` (`encode_preview_frame`).
- A1 escribe las implementaciones en archivos propios (`server/sonia/vision/stream.py`, `poses.py`, `hands.py` y `judge.py`) y el cambio de `OpenCVCamera` en `camera.py`.

**Orden de fusión,** de menos a más riesgo: `juegos/base` (F0-Py + F0-Unity) → A1 → A6 → A4 → A2 → A7 → A3 → A5.

### 7.2 Reglas para los agentes de la fase 1

- **Aislados.** Cada uno trabaja en su worktree (`isolation: "worktree"`):
  - Lo primero, su rama desde la base: `git switch -c juegos/<id> juegos/base`.
  - Luego su propio entorno: `cd server && uv sync --group dev --extra audio --extra camera --extra panel`.
- **Solo tocan sus archivos:**
  - `server/sonia/games/<juego>/`
  - `server/tests/games/test_<juego>*.py`
  - `assets/games/<juego>/`
  - `unity/Assets/Scripts/Sonia/Games/<Juego>/`
  - `docs/juegos/<juego>.md`
  - su sección de `docs/protocolo.md`
  - los valores de su bloque en `.env.example`

  En los archivos comunes solo cambian su línea de `games/registry.py`. Si necesitan algo de los cimientos, lo piden; no lo cambian ellos.
- **Unity sin el editor compartido.** Ver el apéndice. Nunca se guarda un `.cs` con un Unity en Play.
- **Hecho quiere decir:**
  - `ruff check`, `ruff format`, `mypy` y `pytest -q` en verde, y el C# compila;
  - capturas 9:16 revisadas de cada estado de su pantalla (empezar, jugada, acierto, fallo y final);
  - escritos su `docs/juegos/<juego>.md` y su sección de `docs/protocolo.md`;
  - el banco en borrador, marcado «pendiente de revisión de Jean»;
  - un commit en su rama, en español y en imperativo.
- **Prohibido:**
  - llamar a APIs reales (GPT-Live, el backend, el modelo de visión);
  - usar la cámara de Jean;
  - leer `.env`;
  - hacer push, desplegar el panel o compilar builds.

### 7.3 Encargos

La base de todos los encargos es la misma:
1. Leer `CLAUDE.md`, `docs/trivia.md` y de este plan las secciones 3, 4 y la suya.
2. Hacer su sección.
3. Seguir las reglas de 7.2.

Lo propio de cada uno:

| Agente | Encargo |
|---|---|
| A1 «Visión» | La sección 6, con tests de personas y manos inventadas y una prueba de rendimiento con fotos públicas, fuera del repo. |
| A2 «Ruleta» | Los cinco retos, la ruleta y las tarjetas en Unity, y los tres bancos. |
| A3 «Poses» | Las reglas, con tests de puntos inventados para cada pose (y que no salte con la gente en reposo). El flujo de rondas y trampas, la vista en vivo con los esqueletos y la demostración de Sonnia. |
| A4 «Akinator» | Las reglas para GPT-Live, el contador a partir de la transcripción de Sonnia, la adivinanza final y el resultado. |
| A5 «Piedra, papel o tijera» | La clasificación de manos con tests inventados, las rondas y `SoniaHandPoser` validado por fotogramas. |
| A6 «Wordle» | La lógica (con letras repetidas como el Wordle real), el banco y la rejilla. |
| A7 «Búsqueda» | Las rondas, las comprobaciones con tope, `busqueda_check`, el prompt cerrado del `VisionJudge` (sin hablar de personas) y el banco. |

## 8. Pruebas

- **Automáticas, sin red ni hardware:**
  - la lógica de cada juego con un `GameHost` falso y detectores falsos;
  - las acciones y sus esquemas;
  - que no se pise con la trivia;
  - el abandono, la reconexión de Unity y la sesión perdida;
  - la longitud de cada `instructions.append` (1200 caracteres como mucho);
  - que ningún texto para GPT-Live nombre el stack.
- **Pantalla:** capturas 9:16 de cada estado con el orquestador falso, en edición y en Play (principio 8).
- **Visión:**
  - Rendimiento y aciertos con fotos públicas, como la prueba del 10 de octubre; nunca con la cámara de Jean.
  - En el equipo del stand, la CPU con Unity en marcha.
- **Con la API real.** Gasta, así que solo con permiso de Jean.
  - Voz sintetizada como micrófono, empujada a ritmo real con `push_mic`.
  - El banco de pruebas de la trivia está en un scratchpad, no en el repo: hay que rehacerlo.
  - De 3 a 5 partidas por juego, para comprobar que:
    - delega `start_game` a la primera;
    - delega cada jugada;
    - delega `stop_game` cuando la cortan;
    - no se inventa resultados.

## 9. Despliegue y calendario

- **Builds.** Todos los juegos necesitan una Unity nueva: build de macOS y de Windows, la de Windows compilada desde el Mac.
- **Orquestador de Windows.** El congelado se puede parchear sin volver a congelarlo (`scripts/parchea_orquestador_windows.py`), porque no hay dependencias nuevas.
- **Panel de la nube.** Se despliega aparte (`cloud/panel`), desde un worktree limpio.
- **Publicar por partes.** Cada juego tiene su `GAME_<X>_ENABLED` y solo se ofrece si Unity lo anuncia: se puede publicar solo con los que estén listos.
- **Calendario para mañana, sábado 10.** Primero la hora de Santo Domingo, entre paréntesis la de España. La primera charla es a las 9:00 (15:00).

  | Hora | Hito |
  |---|---|
  | 20:00 (02:00) | Plan commiteado. Arrancan F0-Py, F0-Unity y A1. |
  | ~22:00 (04:00) | Contratos en `juegos/base`. Arrancan A2-A7. |
  | ~02:00 (08:00) | Juegos terminados en sus ramas, con tests y capturas. |
  | 02:00-05:00 (08:00-11:00) | Fusión en orden, verificación en el editor, revisión de Fable y pruebas con la API real (si Jean da permiso). |
  | **05:00 (11:00)** | **Hora de corte.** Lo que no esté verificado sale apagado en `games_off`, y se enciende desde el backoffice si se termina luego sin cambiar Unity. |
  | 05:00-06:30 (11:00-12:30) | Builds de macOS y Windows, orquestador de Windows parcheado y panel de la nube desplegado. |
  | ~07:00 (13:00) | App lista para instalar en el stand antes de abrir. |

- **Si algo se tuerce,** la app que ya hay en el stand (1.0.195) sigue igual: la nueva solo se instala si sale verificada.

## 10. Riesgos

| Riesgo | Cómo se reduce |
|---|---|
| GPT-Live deja de delegar con más herramientas e instrucciones (pasó el 7 de octubre). | Una sola línea en el prompt base, reglas al empezar, una sola delegación para arrancar y pruebas reales antes de publicar. |
| Con el barullo, GPT-Live coge mal la palabra o la respuesta. | Son juegos de fiesta: vale cualquiera de las que se oyen, y si duda, pregunta. |
| La CPU del equipo del stand con Unity, la detección y la vista en vivo a la vez. | Medirla; si no llega, el modelo `n`, menos detecciones por segundo y hilos limitados. |
| Dos lecturas de la cámara a la vez (caras, presencia y juego). | Un `CameraStream` único. |
| Gente pegada a la cámara o tapándose. | Vista en vivo, aviso de paso atrás y veredicto colectivo. |
| La imagen de la cámara en pantalla en un evento público. | Solo durante los juegos, en directo, con «no se graba» y nada en disco. |
| Las manos de Sonnia salen mal en piedra, papel o tijera. | Validación por fotogramas. Si no queda bien, el juego sale sin ese detalle o se aplaza. |
| El coste del modelo de visión en la búsqueda. | Tope por ronda y medirlo. |
| El repo se comparte con otras sesiones. | Worktrees, fusiones en orden y commits solo de lo propio (`git commit -- rutas`). |
| Las apps ya instaladas en el stand. | `client_hello.games`, `data-cap` y mensajes desconocidos que se ignoran. |

## 11. Decisiones

Las diez preguntas del plan quedaron contestadas el 10 de octubre (sección 2). Quedan pendientes:

1. **Pruebas con la API real.** Unas partidas por juego con voz sintetizada como micrófono. Cuestan unos dólares en sesiones de GPT-Live. Sin ellas, la delegación solo se prueba con el GPT-Live falso.
2. **Cómo llega la app al stand.** Jean decide quién la instala y por dónde se la pasa.
3. **Despliegue del panel de la nube** con los interruptores y los bancos de los juegos. Es necesario para editar desde el backoffice; se hace al final, junto con las builds.

## Apéndice: Unity sin el editor compartido

Solo hay un editor y lo pueden estar usando otras sesiones. Los agentes de la fase 1 trabajan sin él.

- **Compilar.** Con el Roslyn que trae Unity:
  - El compilador: `…/Unity.app/Contents/Resources/Scripting/NetCoreRuntime/dotnet` con `…/Scripting/DotNetSdk/sdk/8.0.318/Roslyn/bincore/csc.dll`.
  - Opciones: `-nostdlib`.
  - Referencias:
    - `…/Scripting/UnityReferenceAssemblies/unity-4.8-api` (con sus `Facades`);
    - `…/Scripting/Managed/UnityEngine/*.dll`;
    - `unity/Library/ScriptAssemblies/*.dll` del repo principal.
  - Con netstandard falla `ReadOnlySpan`.
  - Así se comprueba el ensamblado `Sonia` sin tocar el editor.
- **Ver en Play.**
  1. Clonar el proyecto con APFS: `cp -cR unity <scratchpad>/<juego>/unity`. Es instantáneo, no ocupa disco y no toca el editor de nadie.
  2. Copiar al clon los `.cs` del worktree.
  3. Correr Unity en modo batch con el puente MCP desactivado (`UNITY_MCP_DISABLE_BATCH=1`, como en `docs/cara-y-lipsync.md`) y un script temporal que:
     - entra en Play;
     - apunta `SoniaClient` a su orquestador falso con `-sonia-ws`;
     - renderiza la cámara principal a un RenderTexture de 1080x1920 con `SoniaCapture.Render`;
     - guarda los PNG fuera de `unity/Temp` y sale con `EditorApplication.Exit`.
  4. Los Canvas superpuestos se pasan a ScreenSpaceCamera para que salgan en la captura.
  5. No llamar a `AssetDatabase.SaveAssets()` después de Play: reescribe `QualitySettings.asset`.
- **Como mucho dos Unity en batch a la vez,** por memoria y CPU. El turno se coge con un candado: crear una carpeta (`mkdir`) en el scratchpad de la sesión principal y borrarla al terminar.
- **Al fusionar a `main`,** Unity genera los `.meta` de los archivos nuevos y se commitean con el juego.
