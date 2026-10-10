# Juegos del stand: cimientos y cómo se hace un juego

Los seis juegos nuevos de Sonnia (plan aprobado en `docs/plan-juegos.md`) comparten unos cimientos en el orquestador: un contrato por juego, un manager que lleva uno a la vez sobre el motor GPT-Live, las acciones comunes, los bancos editables desde el backoffice, el sobre `game` del protocolo y unas versiones falsas para probarlo todo sin red. Este documento es el contrato: léelo antes de escribir un juego. Lo de Unity (`GameRouter`, `GameHud`, la vista en vivo y la receta de capturas en batch) está en `docs/juegos-unity.md`.

La trivia es el modelo (`docs/trivia.md`): todo lo que aquí se repite sale de lo aprendido con ella.

## Qué hay

| Archivo | Qué lleva |
|---|---|
| `server/sonia/games/base.py` | `Game` (la clase base, con los ganchos vacíos), `GameHost` (lo que el juego puede usar), `GameError` y las constantes (`SCRIPT_PREFIX`, `INSTRUCT_MAX_CHARS`, `NOT_SAID`...). |
| `server/sonia/games/banks.py` | `GameBank` y `BankParse` (bancos editables), `markdown_sections` para leerlos. |
| `server/sonia/games/manager.py` | `GameManager`: registro, exclusividad (también con la trivia), ciclo de vida, pausas, abandono, reconexión de Unity, bancos y estado para el panel. |
| `server/sonia/games/host.py` | `ManagedGameHost`: el `GameHost` de cada juego sobre el manager y el motor. |
| `server/sonia/games/registry.py` | La lista de juegos, una línea por juego, con `on=False` hasta que su agente lo termine. |
| `server/sonia/games/demo.py` | El orquestador falso de las pantallas (`serve_demo`) y los pasos de sus secuencias; `scripts/juegos_demo.py` lo lanza. |
| `server/sonia/games/<paquete>/` | Un paquete por juego: `ruleta`, `poses`, `akinator`, `ppt` (id `piedra_papel_tijera`), `wordle` y `busqueda`. |
| `server/sonia/actions/games.py` | `start_game`, `stop_game` y `game_action` (las jugadas de cada juego). |
| `server/sonia/vision/contracts.py` | Los contratos de visión (`CameraStream`, `PreviewStreamer`, `PoseDetector`, `HandDetector`, `VisionJudge`, `GameVision`), que implementa el agente de visión. |
| `server/sonia/config.py` | `GamesSettings` (`GAMES_*`) con un bloque por juego (`GAME_<X>_*`), en `settings.games.<bloque>`. |
| `server/tests/games/fakes.py` | `FakeGameHost`, `FakeVision`, `FakeEngine`, `FakeScreen`, `make_game` y `make_manager`. |
| `server/tests/games/test_ejemplo.py` | La plantilla de los tests de un juego. |
| `server/tests/games/test_contratos.py` | Lo que tiene que cumplir todo juego del registro (se aplica solo al tuyo). |
| `server/tests/games/test_manager.py`, `test_motor.py`, `test_juegos_demo.py`, `test_trivia_juegos.py` | Los tests de los cimientos: el manager, el motor con un GPT-Live falso, el orquestador falso y lo que la trivia añade. |

## Reglas comunes

Resumen de la sección 3 del plan; son obligatorias.

1. **Una sola delegación para empezar.** GPT-Live delega `start_game(juego)` y a partir de ahí el orquestador lleva el juego. Lo que GPT-Live tiene que **saber** va por `host.instruct` (`session.instructions.append`, no la hace hablar); lo que tiene que **decir ya**, por `host.speak` (`session.commentary.append`) o como resultado de la acción. Las jugadas que exigen entender al visitante van por una acción del juego, una por jugada, con el mínimo de delegaciones posible.
2. **Nada de parsers de lo que dice el visitante.** GPT-Live lo entiende y lo delega. El juego sí puede seguir lo que dice Sonia (`on_assistant_text`) para sincronizar la pantalla.
3. **Un juego cada vez**, nunca con la trivia, solo en «Conversando», con Unity conectada y si esa Unity anuncia el juego (`client_hello.games`). Lo comprueba el manager.
4. **Tiempos exactos con frases grabadas** (`host.say_fixed`): suenan de la caché de voces, sin gastar y con el micro callado. Declara esas frases en `phrases()` para que se graben. Los contadores los lleva el orquestador y los pinta Unity.
5. **Cámara**: solo la USB, todo en este equipo y en hilos, sin guardar ninguna imagen ni dato de nadie y sin reconocer a nadie. La vista en vivo solo durante los juegos que la usan.
6. **Sin premios**: a quien gana se le manda con `settings.trivia.win_contact` (Brian o Mariel).
7. **Nombre**: en pantalla, «Sonnia» (`title`, textos de `data`); en lo que lee o dice GPT-Live y en las frases grabadas, «Sonia» (`spoken`, `instruct`, `speak`, guiones). Nada de lo que lee GPT-Live nombra el stack: ni GPT-Live, OpenAI, Unity, Genies, YOLO, OpenCV ni MediaPipe. `FakeGameHost` y `FakeEngine` fallan si lo haces.
8. **Instrucciones cortas**: cada `instruct` como mucho 1200 caracteres (el manager corta y los falsos fallan). Las reglas del juego entran al empezar; al terminar, el manager le dice que vuelva a conversar con normalidad. El prompt base solo lleva una línea con la lista de juegos.
9. **Bancos editables desde el backoffice** (abajo). Los que escribas, marcados «pendiente de revisión de Jean».
10. **Pruebas sin APIs reales ni la cámara de nadie.** Solo fotos o vídeos públicos, en tu scratchpad, o imágenes sintéticas.

## El contrato de un juego (`Game`)

Una subclase de `sonia.games.base.Game` que sobreescribe solo lo suyo. Hay **una instancia por juego** durante toda la vida del motor: `start` empieza de cero (reinicia todo tu estado). La crea el manager con su `GameHost` en `self.host`.

```python
class WordleGame(Game):
    id: ClassVar[str] = "wordle"                      # protocolo, start_game, client_hello
    title: ClassVar[str] = "Wordle de tecnología"     # en pantalla («Sonnia»)
    spoken: ClassVar[str] = "el Wordle de tecnología" # para GPT-Live y el panel («Sonia»)
    needs: ClassVar[frozenset[str]] = frozenset()     # camera, preview, poses, hands, vision_llm
    settings_key: ClassVar[str] = "wordle"            # settings.games.wordle (GAME_WORDLE_*)
```

| Método | Cuándo | Qué hace |
|---|---|---|
| `actions()` (clase) | Al arrancar | Sus jugadas delegadas, creadas con `game_action` (abajo). |
| `banks()` (clase) | Al arrancar y en el panel | Sus bancos (`GameBank`). |
| `phrases()` | «Preparar voces» y la grabación automática (en un hilo) | Las frases fijas que dice con `say_fixed`. Puede leer bancos con `host.read_bank`. |
| `unavailable_reason()` | Antes de empezar y en el panel | Por qué no se puede jugar (`None`: se puede). Solo lo propio: lo común ya lo mira el manager. Barata. |
| `start(source, options)` | `start_game` o el panel | Reinicia el estado, carga los bancos (`await host.load_bank(...)`), manda `start` y la primera pantalla, pasa las reglas con `instruct` y devuelve el guion de arranque. Si no se puede, `GameError("motivo")`. |
| `resume()` | GPT-Live vuelve a delegar empezar el mismo juego | El guion para seguir donde iba. |
| `stop_requested(source)` | Le piden terminar con la partida en marcha (`voice`: `stop_game`; `panel`: «Terminar juego») | Opcional. Por defecto `None`: se cancela. Si quiere cerrar enseñando su final (el Wordle enseña la palabra), lo enseña, llama a `host.finish(...)` y devuelve el guion para Sonia: el manager no cancela, sigue el final normal y le pasa el guion a GPT-Live (por voz, como resultado de `stop_game`; desde el panel, por `speak` en cuanto calla). |
| `stop(reason)` | Siempre, una vez, al terminar la partida | Suelta lo suyo. No hables aquí. `reason`: `finished`, `voice`, `panel`, `abandoned`, `session`, `unity`, `replaced`, `error` o `shutdown`. |
| `tick(now)` | Cada 50 ms mientras se juega | Contadores, rondas, comprobaciones. Nada bloqueante. |
| `on_assistant_text(text, final)` | Mientras habla Sonia | `text` es lo acumulado de la frase en curso; con `final=True`, la frase entera, una vez. |
| `on_user_text(now)` | Llega transcripción del visitante | Sin texto: no se parsea al visitante. |
| `on_user_turn_end(now, started_at)` | Termina un turno del visitante | |
| `on_delegation(now)` | GPT-Live delega algo | |
| `on_unity_event(event, data)` | Un `game_event` de su pantalla | Por ejemplo `wheel_stopped`. |
| `nudge()` | Tras un turno del visitante sin delegación (después de `on_user_turn_end`, así que puede depender del turno) | El empujón o `None` para no empujar (por defecto). Va por `commentary`, que la hace hablar: escríbelo como una **orden corta** («WORDLE: si el grupo dijo una palabra, delega ya el intento; si pidió parar o se despidió, delega terminar el juego.»), sin frases que pueda repetir; el manager añade al final que, si no, siga sin decir nada y que es una nota interna (`NUDGE_TAIL`). En las pruebas con Unity, los empujones que sonaban a frase los leía en voz alta. Úsalo si cada turno del visitante debería ser una jugada, y siempre para parar («si pidió parar o se despidió, delega terminar el juego»). |
| `snapshot()` | Estado del panel | En qué va la partida, en tipos JSON. |

Los ganchos que fallan van al registro y no tumban nada; si `tick` falla 20 veces seguidas, la partida se cancela.

## Lo que el juego puede usar (`GameHost`)

`self.host` es lo único que el juego toca: nunca el motor ni el hub. Nada lanza; sin sesión o sin pantalla, devuelve `False` o no hace nada. Un juego que ya no está en pantalla no puede hablar ni mandar nada (una tarea rezagada no pinta encima del siguiente).

| Qué | Para qué |
|---|---|
| `settings` | Toda la configuración: lo tuyo en `settings.games.<bloque>`; también `settings.trivia.win_contact`. |
| `rng`, `now()`, `sleep(s)` | Azar y reloj del juego. En los tests, con semilla y un reloj que se adelanta a mano (`sleep` no espera de verdad). Usa siempre estos, no `random` ni `time` directamente. |
| `connected` | ¿Hay sesión de GPT-Live? |
| `speak(prompt)` | Que Sonia diga algo ya (`commentary`). Lo dice con sus palabras. |
| `instruct(text)` | Que lo sepa sin hablar (`instructions.append`), como mucho 1200 caracteres. |
| `say_fixed(text)` | Una frase exacta en el tiempo: grabada si está en `cache/voice`; si no, por `commentary` pidiéndole que la diga tal cual. `False` si Sonia ya hablaba o no hay sesión. |
| `wait_idle(limit_s)`, `quiet_for()` | Esperar a que nadie hable / cuánto lleva Sonia callada. |
| `touch()` | Hay actividad: llámala si ves gente con la cámara aunque nadie hable, para que la partida no se dé por abandonada. |
| `send(event, data, sticky=True)` | Un mensaje de tu pantalla (abajo). |
| `play_animation(clip)` | Una animación o gesto de Sonia, entero (`whole=True`). |
| `finish(result, data)` | El juego terminó: `win`, `lose` o `cancel` (abajo). |
| `stream`, `preview`, `poses`, `hands`, `judge`, `referee` | La visión (`sonia/vision/contracts.py`). Pide y suelta a tu nombre (`self.id`). `referee` es el juez de las rondas de cámara (Gemini; abajo). |
| `set_busy(kind, text)` | La pastilla de espera de la pantalla (`sonia/busy.py`): `text` la enciende y `None` la apaga. Para lo que el visitante espera sin ver nada, como el juez mirando la foto de la ronda (`judge`) o la cámara arrancando (`camera`). Se apagan solas al terminar la partida. |
| `spawn(coro, name)` | Una tarea en segundo plano que se cancela sola al terminar la partida. |
| `load_bank(bank)` / `read_bank(bank)` | Las entradas del banco en uso (en un hilo / síncrona). |
| `draw_trivia(nivel)` | Una pregunta del banco de la trivia en uso (`TriviaQuestion`: `text`, `options`, `correct`, `fact`, `level`), con las opciones barajadas y sin repetir hasta agotar el nivel (`TriviaGame.draw_one`). `None` si la trivia está apagada. Para la trivia relámpago de la ruleta. |

### Hablar con GPT-Live

- **Al empezar**: las reglas por `instruct` (≤ 1200) y el guion de arranque como retorno de `start`. Por voz, el guion vuelve como resultado de `start_game` con la marca `PARA SONIA:` (el backend lo pasa entero); desde el panel, el manager se lo pasa por `speak` en cuanto Sonia calla.
- **En cada jugada**: lo que devuelve tu función `play` es el guion (sale con `PARA SONIA:`); un `GameError` sale tal cual, sin la marca.
- **Por su cuenta** (un contador que acaba, la cámara que ve algo): `speak` con lo que tiene que decir. Una frase exacta en el tiempo, `say_fixed`.
- **Una frase grabada no la oye GPT-Live**: suena desde la caché, fuera de su conversación, y el micro le manda silencio mientras tanto (si no, la contestaría). Si tiene que saber que ya se dijo («¡Simón dice: brazos arriba!»), cuéntaselo con `instruct`. Va a la pantalla como frase `ambient` (boca, cejas y ojos, sin pasar a hablar) y con subtítulo. `say_fixed` devuelve `False` si Sonia ya estaba hablando: espera antes con `wait_idle` si el momento importa.
- GPT-Live **no sabe la solución** hasta que se la das (como la trivia): así no puede revelarla.
- **No le dejes decir que algo ha pasado sin delegarlo.** Si la pantalla solo cambia con una jugada delegada, díselo en las reglas («en la pantalla nada cambia si no lo delegas»).

### Las jugadas (`game_action`)

```python
from sonia.actions.games import game_action

class WordleGame(Game):
    @classmethod
    def actions(cls) -> list[ActionSpec]:
        return [
            game_action(
                cls,
                name="wordle_guess",                  # prefijo del juego (o de su bloque)
                description="Registra la palabra que dice el grupo en el Wordle...",
                parameters={
                    "type": "object",
                    "properties": {"palabra": {"type": "string", "description": "..."}},
                    "required": ["palabra"],          # todos obligatorios
                },
                play=WordleGame.guess,                # async (partida, argumentos) -> guion
            )
        ]
```

- El handler recibe la partida en marcha, solo si es de su clase y aún se juega; si no, el manager contesta por él («no hay ninguna partida…», «ya ha terminado…»). Los argumentos llegan validados contra el esquema.
- **Esquemas estrictos**: todos los parámetros en `required` y en cada enum un valor de «no lo dijo» de `NOT_SAID_VALUES` (`no_lo_dijo`, `no_lo_sabe`, `se_rinden`, `sin_elegir`). Lección de la trivia: un nivel opcional, el backend lo rellenaba siempre con «fácil». Lo comprueba `test_contratos.py`.
- La descripción la lee el backend: corta, en español, sin marcas del stack y diciendo qué devuelve.
- Las herramientas del backend se fijan al abrir cada sesión: las jugadas de los juegos encendidos están siempre; la disponibilidad se mira al llamar.

### `start_game` y `stop_game`

- `start_game(juego)`: `juego` es un enum fijo con los juegos encendidos al arrancar (registro y ajustes) más `no_lo_dijo`. Con `no_lo_dijo`, el guion le pide preguntar a cuál, con la lista de los que se pueden jugar ahora. Si el juego no se puede (apagado en el panel, Unity vieja, sin cámara, banco vacío…), el resultado dice por qué y propone los que sí. Si ya hay otro juego en marcha, dice cuál y que hay que terminarlo antes; si es el mismo, `resume()`. Si hay una trivia, igual.
- `stop_game()`: termina el que haya (`stop("voice")`). Si el juego tiene `stop_requested` y cierra enseñando su final, el resultado es su guion (con `PARA SONIA:`); si no, se cancela.
- Sin ningún juego encendido no se registra ninguna de las dos ni sale la línea de juegos en el prompt.

## La pantalla (`send` y `finish`)

El sobre común del protocolo (`docs/protocolo.md`, «Juegos: `game`»):

```json
{"type": "game", "game": "wordle", "event": "guess", "seq": 7, "data": {"row": 2, "letters": "LINUX", "marks": "gyxxg"}}
```

- `host.send(event, data)` pone `type`, `game` y `seq` (sube en cada mensaje).
- **`start` va siempre el primero** y siempre con `data.title`: mándalo tú en `start()` con lo que necesite tu pantalla (`title` se añade si falta) o sale solo con el título antes de tu primer mensaje.
- **Fijos**: el `start` y el último mensaje con `sticky=True` se repiten tras `hello` si Unity se reconecta, en ese orden. Solo se guarda el último, así que manda **estados completos** (por ejemplo, el tablero entero) y `sticky=False` para los efectos sueltos (un confeti, una sacudida).
- **`end` no se manda a mano.** `host.finish(result, data)`:
  - `win` o `lose`: el resultado se queda en pantalla al menos `GAMES_RESULT_SECONDS` y hasta que Sonia termina de contarlo (como mucho `GAMES_FINAL_WAIT_SECONDS`); luego `stop("finished")`, `end` con `data` y `result`, y la instrucción de volver a conversar. Mientras tanto las jugadas ya no llegan al juego y un `start_game` nuevo cierra este al momento.
  - `cancel`: igual, sin esperar.
  - Devuelve enseguida: llámala y devuelve tu guion final (el de la victoria o la derrota).
- Si el juego se cancela por fuera (panel, abandono, sesión), el manager manda `end` con `cancel`.
- Los `game_event` de tu pantalla te llegan en `on_unity_event`.
- Documenta tus eventos en tu tabla de `docs/protocolo.md` («Eventos de cada juego»).

## Cámara y visión

Los contratos están en `server/sonia/vision/contracts.py` y los implementa `server/sonia/vision` (stream, vista en vivo, poses, manos y juez, con sus dibujos en `overlay.py`): detalle, modelos y medidas en `docs/juegos-vision.md`. Sin cámara USB (`VISION_SOURCE` distinto de `opencv`), sin los modelos o sin una Unity que anuncie `camera_preview`, `build_game_vision` da esa pieza «no disponible» y los juegos de cámara no se ofrecen. Tus tests usan `FakeVision`.

Medido el 10 de octubre de 2026 en el Mac (M1 Pro, con la máquina cargada) con fotos públicas de Commons:
- Poses: `s` unos 60 ms por detección (310 ms de CPU) y `n` unos 30 ms (120 ms de CPU). De frente detecta a casi todos (18 de 20 en dos filas, 5 de 5) y ninguna persona en salas vacías; pierde a quien solo asoma la cabeza.
- Manos: 12 de 13 manos con gesto bien leídas (piedra, papel y tijera); falla con una mano pegada a la cámara.
- Todo junto (poses a 8 por segundo, vista en vivo y manos): unos 3 núcleos con `s` y 1,4 con `n`. En el Mac no se puede limitar a menos núcleos. Por eso el modelo por defecto es `n` (`GAME_POSES_MODEL=n`).
- El ajuste compartido `games_pose_model` del panel («Modelo de poses: ligero (n) o preciso (s)», `data-cap="game_pose_model"`) manda sobre `GAME_POSES_MODEL`, sin reiniciar: `GameManager.set_pose_model` (`None` vuelve al de `GAME_POSES_MODEL`), `snapshot()["pose_model"]` y `normalize_pose_model` (en `sonia.games`). El cambio es en caliente y atómico, también con una partida en marcha (`docs/juegos-vision.md`, «Modelos»).
- Igual el juez de las rondas de cámara: el ajuste compartido `games_judge` («Juez de las rondas de cámara: Gemini o local», `data-cap="game_judge"`) manda sobre `GAMES_JUDGE`, al momento: `GameManager.set_judge`, `snapshot()["judge"]` y `normalize_games_judge` (`docs/juegos-vision.md`, «Juez de Gemini»).

- Declara lo que necesitas en `needs`: el manager no ofrece el juego si falta (cámara USB, la Unity sin `camera_preview`, detectores o el modelo de visión).
- Pide y suelta a tu nombre: `await host.stream.acquire(self.id)`, `await host.poses.acquire(self.id, fps)`, `await host.preview.start(self.id, overlay=...)`. Al terminar la partida el manager suelta `preview`, `poses` y `stream` a tu nombre, aunque se te olvide.
- Coordenadas de 0 a 1 sobre la imagen **sin espejo**; el espejo es solo de la vista en vivo. El `Overlay` dibuja sobre el frame BGR y sabe si va en espejo (`x` → `1 - x`).
- Todo lo pesado (detectar, dibujar, codificar) va en hilos: lo hace la visión. En tu `tick`, usa `poses.latest()`.
- Nunca se guarda una imagen ni un dato de nadie. Solo salen fotos reducidas hacia un modelo de visión: las de `VisionJudge` en la búsqueda relámpago (con tope por ronda) y una por ronda de `GameReferee` en Simón dice y en piedra, papel o tijera. Con `GAMES_JUDGE=gemini` (por defecto) las dos van a Gemini; nunca describen personas.

### El juez de las rondas: Gemini

Desde el 10 de octubre de 2026 (Jean: «es una mac m3 pro que habrá. mejor usemos gemini») el veredicto de las rondas de cámara lo da `gemini-3.1-flash-lite`, el modelo de los gestos, por su endpoint compatible con OpenAI, con razonamiento `minimal`, fotos de 640 px y JPEG q75 (`server/sonia/vision/referee.py`; `GAMES_JUDGE=gemini`). La detección local sigue a lo suyo (vista en vivo, esqueletos, elegir el momento de la foto) y decide si Gemini no contesta en `GAMES_JUDGE_TIMEOUT_SECONDS` (4 s), falla o no hay `GEMINI_API_KEY`. Con `GAMES_JUDGE=local`, todo como antes.

- Simón dice: una foto por ronda (también las trampa) y Gemini cuenta personas y quién hace cada pose.
- Piedra, papel o tijera: la lectura local elige el momento (la muestra estable o, si no la hay, la última) y Gemini dice el gesto de la mano que enseña la persona más cercana.
- Búsqueda: la misma pregunta cerrada de siempre (`JUDGE_PROMPT`) a Gemini, con el plazo del juez; si falla (un 429 de la clave, que también usan los gestos, o el plazo), la misma pregunta va al modelo de visión de `LLM_*` con lo que queda de los 8 s (`FallbackJudge`). Sin clave de Gemini, el modelo de visión, como antes.
- Mientras el juez mira, la pastilla de espera («Mirando las poses…», «Mirando tu mano…», «Mirando lo que enseñas…»).

Banco de pruebas del 10 de octubre de 2026, con la API real y 80 fotos públicas de Commons etiquetadas a mano (unas 165 llamadas):

| | Gemini | Local `s` | Local `n` |
|---|---|---|---|
| Pose de una persona | 22/22 | 21/22 | 17/22 |
| Cuántos la hacen en un grupo (±1) | 10/11 | 9/11 | 9/11 |
| Piedra, papel o tijera | 18/18 | 15/18 | 14/18 |
| Fotos sin gesto (sin inventar ninguno) | 3/3 | 1/3 | 1/3 |
| Búsqueda | 25/25 | — | — |

- Tiempos de Gemini: mediana 1,25 s, p90 1,7 s y máximo 2,8 s, sin errores. La detección local tarda 33 ms (`n`) y 65 ms (`s`); luna, el juez anterior de la búsqueda, 1,39 s y 24 de 25.
- La misma foto cinco veces da lo mismo. Gasta unos 1.350 tokens de entrada por foto, sea cual sea el ancho (`detail` no cambia nada): unos 0,0004 USD.
- Fallos vistos: tres personas con los dos brazos arriba contadas como `un_brazo`, y en multitudes de más de 60 personas se inventa las cifras.

## Bancos editables desde el backoffice

Como el banco de la trivia en la nube (`docs/panel.md`):

- El de la app va en `assets/games/<id del juego>/<archivo>.md`, con el formato explicado al principio del archivo en un comentario HTML (`<!-- ... -->`, se ignora al leerlo).
- Se declara en `banks()`:

  ```python
  ADIVINANZAS = GameBank(
      id="ruleta_adivinanzas",          # <juego>_<banco>, único: clave en game_banks
      title="Adivinanzas de la ruleta", # lo que ve el equipo en el panel
      file="adivinanzas.md",            # en assets/games/ruleta/
      parse=parse_riddles,              # texto -> BankParse(entradas, avisos); nunca lanza
      min_entries=10,                   # con menos, ni se guarda ni se juega
  )
  ```

- **El analizador** devuelve `BankParse(entries, warnings)`: las entradas válidas y un aviso legible por cada una que se salta. `markdown_sections(text)` te da `[(encabezado, líneas), ...]` de un Markdown con `## ` sin los comentarios.
- **En el panel** («Bancos de los juegos», en «Developer»): el equipo carga el banco en uso, lo edita y lo guarda en la nube (ajuste compartido `game_banks`, `{banco: texto}`, orden `set_game_bank`). Antes de guardarlo, el orquestador lo valida (`GameManager.validate_bank`): como mucho 15 000 caracteres (`BANK_MAX_CHARS`) y al menos `min_entries` válidas. «Volver al de la app» lo borra.
- **Al jugar**: `await host.load_bank(BANCO)` en cada `start`. Manda el de la nube si llega a `min_entries`; si no, el de la app. Lo mal formado se salta con un aviso en el registro.
- Escribe los primeros textos tú, marcados como borrador «pendiente de revisión de Jean».

## Ajustes

`settings.games` (`GamesSettings`, `GAMES_*`): `enabled`, `abandon_seconds` (60), `nudge_seconds` (3), `result_seconds` (4), `final_wait_seconds` (20) y `models_dir` (`cache/games/modelos`). Cada juego tiene su bloque con los valores de la sección 5 del plan (`settings.games.ruleta`, `.poses`, `.akinator`, `.ppt`, `.wordle`, `.busqueda`), todos con `enabled` y `abandon_seconds` (0 = el general). Los bloques ya están creados: **nadie más toca `config.py`**. Si cambias un valor por defecto, cámbialo solo en tu bloque de `.env.example` y dilo en tu informe.

## Cómo se hace un juego

Tus archivos (sección 7.2 del plan): `server/sonia/games/<paquete>/`, `server/tests/games/test_<juego>*.py`, `assets/games/<id>/`, `unity/Assets/Scripts/Sonia/Games/<Juego>/`, `docs/juegos/<id>.md`, tu tabla de `docs/protocolo.md` y los valores de tu bloque en `.env.example`. En lo común, **solo tu línea de `games/registry.py`**. Si te falta algo de los cimientos, pídelo en tu informe y apáñate dentro de tus archivos.

1. Rellena tu `game.py` (ya tiene `id`, `title`, `spoken`, `needs` y `settings_key`). Quita el «Aún no está listo» de `unavailable_reason`.
2. Escribe tus bancos en `assets/games/<id>/` y decláralos en `banks()`.
3. Tus jugadas con `game_action` en `actions()`, con esquemas estrictos.
4. `start()`: estado a cero, bancos, `start` y primera pantalla, reglas por `instruct` (≤ 1200), guion de arranque.
5. El juego en `tick`, en tus jugadas y en `on_unity_event`; al acabar, `finish`.
6. Tus frases fijas en `phrases()`.
7. Tests en `server/tests/games/test_<juego>.py`, a partir de `test_ejemplo.py`: el juego suelto con `make_game` y de punta a punta con `make_manager`. `test_contratos.py` ya revisa tu clase.
8. Tu secuencia del orquestador falso en `server/sonia/games/<paquete>/demo.py` (abajo) y las capturas 9:16 de cada estado.
9. Tu `docs/juegos/<id>.md` y tu tabla en `docs/protocolo.md`.
10. Cuando todo esté verificado, `on=True` en tu línea de `games/registry.py`.

Antes de cada commit: `uv run --no-sync ruff check sonia tests && uv run --no-sync ruff format sonia tests && uv run --no-sync mypy sonia && uv run --no-sync pytest -q`.

## Tests

`server/tests/games/fakes.py`:

- `make_game(MiJuego, **opciones) -> (juego, host)`: el juego suelto con un `FakeGameHost`. El host apunta `spoken`, `instructions`, `fixed` (`(frase, grabada)`), `sent` (`events(evento)`, `last(evento)`), `animations`, `finished` y `touches`; tiene `clock` (`advance`), `rng` con semilla (`seed=`), `quiet`, `connected`, `cloud_banks` (bancos «de la nube») `recorded` (frases grabadas) y `trivia_questions` (lo que dará `draw_trivia`). Los bancos de la app se leen de `assets/games/<id>/`.
- `FakeVision`: `FakeStream`, `FakePreview` (apunta `starts`/`stops` y pinta el overlay con `draw()`), `FakePoses` (frames guionizados con `person({L_WRIST: (x, y), ...})` y `pose_frame(...)`), `FakeHands` (lecturas guionizadas) y `FakeJudge` (respuestas guionizadas; apunta las preguntas). Cada uno con `available`.
- `make_manager([MiJuego], ...) -> (manager, engine, screen, clock)`: el `GameManager` con `FakeEngine`, `FakeScreen`, visión y reloj falsos, y una Unity que ya anunció tus juegos. `screen.game_msgs(evento)` y `screen.replay()` (lo que recibiría una Unity al reconectarse). Las acciones se prueban con `build_default_registry(games=[MiJuego])` y un `ActionContext` con `extra={"games": manager}`. `settle()` deja correr las tareas en segundo plano (el final).
- Todo texto para GPT-Live pasa por `check_for_live`: falla con más de 1200 caracteres en `instruct` o si nombra el stack.

## Probar la pantalla sin Sonia

`scripts/juegos_demo.py` es un orquestador falso: un servidor WebSocket en su propio puerto que habla el protocolo con Unity y reproduce paso a paso la secuencia de un juego. Al conectar manda `hello` y `set_volume` a 0 (las pruebas van en silencio), espera el `client_hello` de Unity y luego los pasos; al acabar, `dev_done`. No llama a ninguna API ni abre ninguna cámara.

```bash
uv run --no-sync python ../scripts/juegos_demo.py --juego wordle --puerto 8791
```

Unity se apunta a él con `-sonia-ws ws://127.0.0.1:8791` (receta de Unity en batch y capturas en `docs/juegos-unity.md`). `--juego ejemplo` reproduce una secuencia de ejemplo con solo la pantalla común (`start`, la vista en vivo sintética y `end`) usando el id de `--como` (por defecto, `ruleta`). Otras opciones: `--espera` (segundos esperando a Unity, 180), `--tras-captura` (lo que se deja a Unity tras pedir cada captura, 0,5 s) y `--quedarse` (no manda `dev_done`: para mirar a mano). Sale con 0 si la secuencia terminó, 1 si Unity no llegó, 2 si se fue a mitad y 3 si falló un paso.

Cada juego escribe su secuencia en `server/sonia/games/<paquete>/demo.py` con una función `steps()` (formato en `server/sonia/games/demo.py`):

| Paso | Qué hace |
|---|---|
| `GameMsg(event, data)` | Un mensaje `game` de tu juego; el orquestador falso pone `type`, `game` y `seq`. |
| `Send(msg)` | Cualquier mensaje del protocolo tal cual (`speech_start`, `transcript`, `state`...). |
| `Wait(segundos)` | Esperar (animaciones, giros, contadores). |
| `WaitEvent(evento, timeout)` | Esperar un `game_event` de Unity (`wheel_stopped`). |
| `Preview(segundos, source=..., draw=..., off=False)` | La vista en vivo **en segundo plano** (los pasos siguientes van a la vez, así puedes capturarla): `camera_preview` y unos 10 frames `SNCV` por segundo, en espejo, de una foto o un vídeo público de tu scratchpad (nunca del repo) o sintéticos; `draw(frame, en_espejo)` pinta encima como el overlay del juego; `off=True` la apaga al acabar. |
| `Capture(nombre, settle_s=1.0)` | Espera `settle_s` y pide una captura 9:16. |

### `dev_capture` y `dev_done`

Mensajes de pruebas, fuera del protocolo de producción: solo los manda el orquestador falso y solo los entiende la herramienta de capturas en batch de Unity (`docs/juegos-unity.md`). Una Unity normal los ignora.

```json
{"type": "dev_capture", "name": "wordle-2-jugada"}
{"type": "dev_done"}
```

- `dev_capture`: la herramienta guarda la cámara principal en `<carpeta de capturas>/<name>.png`, a 1080x1920. `name` solo con letras, números, `-`, `_` y `.`; lo demás se cambia por `_`.
- `dev_done`: Unity sale.
- La herramienta conecta Unity al orquestador falso cuando el avatar ya está cargado (hasta 60 s): por eso el orquestador falso espera al `client_hello`. Deja como un segundo entre un evento y su captura para que acaben las animaciones de entrada (`Capture` lo hace por defecto).

## El motor

`LiveEngine` crea el `GameManager` junto a la trivia (`engine.games`; `None` si no hay ningún juego encendido o en una videollamada), con el `BusyBoard` de la pastilla de espera (`busy_board`), y le pasa lo mismo que a ella:

- lo que dice Sonia (`on_assistant_text`: el texto acumulado de cada frase y, al cerrarla, la frase entera) y lo que dice el visitante (`on_user_text`, `on_user_turn_end`);
- las delegaciones (`on_delegation`) y el ciclo de 50 ms (`tick`);
- la sesión que se cae o se renueva, y GPT-Live apagada al cambiar de modo, de Modo Jean, de modo debug o con el editor de personaje (`on_session_lost`: la partida se cancela);
- `client_hello` y `game_event` del hub; `ctx.extra["games"]` para las acciones y `snapshot()["games"]` para el panel.

Mientras hay un juego en pantalla no hay animación de stand ni renovación de la sesión por inactividad, como con la trivia. El saludo automático con la mano lo apaga Unity (`GameHud`). La trivia no empieza con un juego en marcha ni al revés. Tampoco se enseñan imágenes: con un juego (o la trivia) en pantalla, `show_image` y `show_talk` no mandan nada a Unity y le contestan a GPT-Live que lo cuente con palabras (`screen_busy` en `actions/builtin.py`); si no, la tarjeta se quedaba detrás de la del juego y Sonnia señalaba hacia nada. La visión llega de `build_game_vision` con la cámara del motor (solo `VISION_SOURCE=opencv`), el hub (vista en vivo) y el modelo de visión (`vision_llm`, que pasa la CLI). Si un `tick` falla 20 veces seguidas, la partida se cancela (`error`).

La CLI (`build_components`) registra `start_game`, `stop_game` y las jugadas de los juegos encendidos (`enabled_games`), salvo en una videollamada. El prompt base solo gana la línea «Juegos en tu pantalla: …. Delega empezarlos y terminarlos; las reglas te llegan al empezar.», que sale de esos mismos juegos, y el recordatorio final («empezar y terminar los juegos y sus jugadas» solo pasa si lo delega).

## El panel (para F0-Panel)

El panel usa el `GameManager` del motor (`engine.games`, `None` si esta Sonnia no tiene juegos) y no toca los juegos:

| Qué | Cómo |
|---|---|
| Estado | `manager.snapshot()` (también en `engine.snapshot()["games"]`): `enabled`, `active` (id o `null`), `title`, `phase` (`off`, `playing`, `finishing`), `elapsed_s`, `state` (el `snapshot()` del juego), `games` (`[{id, title, needs, off, available, reason}]`), `games_off`, `banks` (`[{id, game, title, file, min_entries, source}]`, `source` = `cloud` o `app`), `unity_games` (o `null` si la pantalla no anunció juegos) y `preview`. |
| Capacidades | `manager.capabilities()`: `games`, `game:<id>` (solo los que anuncia la Unity conectada) y `game_banks`. Van con las demás en `data-cap`. |
| Empezar | Orden `game_start` (`game`): `await manager.start(id, "panel")` → `(ok, mensaje)`. Antes, lo mismo que la trivia: «Conversando», sin modo debug, sin editor de personaje y con la pantalla conectada. |
| Terminar | Orden `game_stop`: `await manager.stop("panel")`. Si el juego cierra enseñando su final (`Game.stop_requested`, el Wordle), el mensaje dice que enseña su final y el manager se lo pasa a GPT-Live; si no, se cancela. |
| Interruptores | Ajuste compartido `games_off` (lista de ids): normalízalo con `normalize_games_off` y aplícalo con `await manager.set_games_off(ids)` (también al arrancar, con lo guardado). Si se apaga el que está en marcha, se termina. |
| Bancos | Cargar: `await asyncio.to_thread(manager.bank_text, bank_id)` (el de la nube o el de la app). Guardar (`set_game_bank`, `bank`, `text`): `ok, mensaje = manager.validate_bank(bank_id, text)`; si vale, guarda `game_banks` con `{**actual, bank_id: text}` (o sin esa clave si `text` está vacío: «Volver al de la app») y aplica con `manager.use_cloud_banks(valor)`. Normaliza lo que llega de la nube con `normalize_game_banks`. |
| Frases grabadas | `await asyncio.to_thread(manager.fixed_phrases)` se suma a las frases de «Preparar voces», de la grabación automática y del contador de frases grabadas. |

Las Sonnias anteriores ignoran `games_off` y `game_banks`, y sus pantallas no anuncian juegos.

## Control a mano desde el panel

Jean, 10 de octubre de 2026: «Debe haber panel para controlar los juegos igual que el de la trivia por si acaso algo sale mal». Con un juego en marcha, la tarjeta «Juegos» del panel enseña «Control del juego»: botones y campos para llevar la partida a mano si falla la voz o la cámara, como A, B, C, «Siguiente», «Reiniciar» y «Terminar» de la trivia. El equipo marca lo que haría el visitante y Sonia lo cuenta como parte del juego.

El contrato:

- **`Game.panel_controls()`**: los controles que valen ahora, en orden. Un botón es `{"id": "spin", "label": "Girar"}`; un campo de texto con su botón, `{"id": "guess", "label": "Probar palabra", "kind": "text", "placeholder": "5 letras"}`. Por defecto, ninguno.
- **`Game.panel_control(control, value) -> str`**: hace lo del control reutilizando el handler de la jugada de GPT-Live (la misma pantalla y el mismo guion) y devuelve el guion para Sonia. Si no vale ahora (fuera de turno, un id que no conoce, un texto que no vale), `GameError` con un mensaje para el equipo; la partida no se toca.
- **`GameManager.snapshot()["controls"]`**: los del juego (solo con la partida en `playing`) más «Reiniciar» (`restart`) y «Terminar» (`stop`), que pone el manager para todos; `[]` sin juego en pantalla.
- **`await GameManager.panel_control(control, value) -> (ok, mensaje)`**: `restart` termina el juego y empieza otra partida del mismo, `stop` lo termina como «Terminar juego». El resto va al juego, y su guion le llega a GPT-Live por `commentary` en cuanto calla, con `PANEL_CONTROL_TEXT` delante (que lo cuente como parte del juego, sin hablar del panel). Nunca lanza.
- **Orden del panel `game_control`** (`control` y `value`, este opcional y de hasta 200 caracteres, `GAME_CONTROL_VALUE_MAX_LEN`): pide lo mismo que `game_start` («Conversando», sin modo debug, sin editor de personaje, sin Modo Jean y con la pantalla conectada), salvo `stop`, que vale siempre.
- **Capacidad `game_controls`**: el panel solo pinta «Control del juego» en las Sonnias que la anuncian. A las anteriores les deja el botón «Terminar juego» de siempre y una nota.

El panel pinta tal cual la lista y solo la rehace si cambia, para no borrar lo que se está escribiendo. Antes de «Reiniciar» y «Terminar» pide confirmación.

| Juego | Momento de la partida | Controles (`id` · botón) | Qué hacen |
|---|---|---|---|
| Ruleta | Girando | ninguno | — |
| | Trivia relámpago | `A`, `B`, `C` · la letra y su opción; `pass` · «No lo sabe» | `ruleta_answer` con la letra o `se_rinden`. |
| | Adivinanza | `right` · «Acertó», `wrong` · «Falló», `pass` · «Se rinde» | `ruleta_answer`. «Falló» gasta un intento y saca la pista; el reto sigue hasta el tercer fallo. |
| | Explica en 20 s | `right` · «Bien (nota 8)», `wrong` · «Flojo (nota 4)», `pass` · «Se rinde» | `ruleta_score` con nota 8 (supera el reto) o 4; `pass`, `ruleta_answer` con `se_rinden`. |
| | Futuro de la IA | `predict` · «Poner su predicción» (campo), `pass` · «Se rinde» | `ruleta_prediccion` con el texto y una probabilidad al azar de 30 a 85. |
| | Sonnet Code: pregunta | `right` · «Acertó», `wrong` · «Falló», `pass` · «Se rinde» | `ruleta_answer`. |
| | Sonnet Code: reto de stand | `right` · «Lo hizo», `wrong` · «No lo hizo», `pass` · «Se rinde» | `ruleta_answer`. |
| | Cualquier reto en curso | `spin` · «Cambiar de reto» (el último) | `ruleta_spin`: salta el reto y gira. |
| | Resultado en pantalla | `spin` · «Girar» | `ruleta_spin`: otra vuelta. |
| Akinator dev | Esperando a que piense en algo | `ready` · «Ya lo pensó» | Cuenta como el aviso del visitante: desde ahí cuentan las preguntas de Sonia. |
| | Pregunta en curso | `yes` · «Sí», `no` · «No», `dont_know` · «No sé» | No hay jugada (las preguntas no se delegan): cuentan como una respuesta corta del visitante y el guion se la dice a Sonia. |
| | Sonia arriesga una respuesta | `right` · «Acertó», `wrong` · «Falló» | `akinator_result` con sí o no: gana Sonia, o sigue preguntando o se rinde. |
| | Sonia se rinde y pregunta qué era | `answer` · «Decir qué era» (campo) | `akinator_result` con no y lo que era: gana el visitante. |
| Wordle | Jugando | `guess` · «Probar palabra» (campo, «5 letras»), `reveal` · «Ver la palabra» | `guess` es `wordle_guess`; si lo escrito no vale, `GameError` sin gastar intento ni sacudir la fila delante de los visitantes. `reveal` es `stop_requested`: enseña la palabra con su pista y termina. |
| Simón dice, piedra, papel o tijera y búsqueda relámpago | — | pendiente | Mientras, «Reiniciar» y «Terminar». |

Tests: `tests/test_panel_game_controls.py` (la orden y el panel, con un juego de mentira) y `tests/games/test_<juego>_panel.py` (cada juego: el control hace lo mismo que la jugada de GPT-Live, fuera de turno da `GameError` y la lista cambia según la fase).
