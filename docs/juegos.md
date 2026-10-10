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
| `server/sonia/games/demo.py` | Los pasos de las secuencias del orquestador falso (`scripts/juegos_demo.py`). |
| `server/sonia/games/<paquete>/` | Un paquete por juego: `ruleta`, `poses`, `akinator`, `ppt` (id `piedra_papel_tijera`), `wordle` y `busqueda`. |
| `server/sonia/actions/games.py` | `start_game`, `stop_game` y `game_action` (las jugadas de cada juego). |
| `server/sonia/vision/contracts.py` | Los contratos de visión (`CameraStream`, `PreviewStreamer`, `PoseDetector`, `HandDetector`, `VisionJudge`, `GameVision`), que implementa el agente de visión. |
| `server/sonia/config.py` | `GamesSettings` (`GAMES_*`) con un bloque por juego (`GAME_<X>_*`), en `settings.games.<bloque>`. |
| `server/tests/games/fakes.py` | `FakeGameHost`, `FakeVision`, `FakeEngine`, `FakeScreen`, `make_game` y `make_manager`. |
| `server/tests/games/test_ejemplo.py` | La plantilla de los tests de un juego. |
| `server/tests/games/test_contratos.py` | Lo que tiene que cumplir todo juego del registro (se aplica solo al tuyo). |

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
| `stop(reason)` | Siempre, una vez, al terminar la partida | Suelta lo suyo. No hables aquí. `reason`: `finished`, `voice`, `panel`, `abandoned`, `session`, `unity`, `replaced`, `error` o `shutdown`. |
| `tick(now)` | Cada 50 ms mientras se juega | Contadores, rondas, comprobaciones. Nada bloqueante. |
| `on_assistant_text(text, final)` | Mientras habla Sonia | `text` es lo acumulado de la frase en curso; con `final=True`, la frase entera, una vez. |
| `on_user_text(now)` | Llega transcripción del visitante | Sin texto: no se parsea al visitante. |
| `on_user_turn_end(now, started_at)` | Termina un turno del visitante | |
| `on_delegation(now)` | GPT-Live delega algo | |
| `on_unity_event(event, data)` | Un `game_event` de su pantalla | Por ejemplo `wheel_stopped`. |
| `nudge()` | Tras un turno del visitante sin delegación | El texto del empujón (como el de la trivia) o `None` para no empujar (por defecto). Úsalo si cada turno del visitante debería ser una jugada. |
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
| `stream`, `preview`, `poses`, `hands`, `judge` | La visión (`sonia/vision/contracts.py`). Pide y suelta a tu nombre (`self.id`). |
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
- `stop_game()`: termina el que haya (`stop("voice")`).
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

Los contratos están en `server/sonia/vision/contracts.py` y los implementa el agente de visión (A1); mientras no estén, `build_game_vision` da todo «no disponible» y los juegos de cámara no se ofrecen. Tus tests usan `FakeVision`.

- Declara lo que necesitas en `needs`: el manager no ofrece el juego si falta (cámara USB, la Unity sin `camera_preview`, detectores o el modelo de visión).
- Pide y suelta a tu nombre: `await host.stream.acquire(self.id)`, `await host.poses.acquire(self.id, fps)`, `await host.preview.start(self.id, overlay=...)`. Al terminar la partida el manager suelta `preview`, `poses` y `stream` a tu nombre, aunque se te olvide.
- Coordenadas de 0 a 1 sobre la imagen **sin espejo**; el espejo es solo de la vista en vivo. El `Overlay` dibuja sobre el frame BGR y sabe si va en espejo (`x` → `1 - x`).
- Todo lo pesado (detectar, dibujar, codificar) va en hilos: lo hace la visión. En tu `tick`, usa `poses.latest()`.
- Nunca se guarda una imagen ni un dato de nadie. `VisionJudge` (solo la búsqueda relámpago) manda una foto reducida al modelo de visión con un tope por ronda y nunca describe personas.

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
- **En el panel**: el equipo carga el banco en uso, lo edita y lo guarda en la nube (ajuste compartido `game_banks`, `{banco: texto}`, orden `set_game_bank`). Antes de guardarlo, el orquestador lo valida (`GameManager.validate_bank`): como mucho 15 000 caracteres (`BANK_MAX_CHARS`) y al menos `min_entries` válidas. «Volver al de la app» lo borra.
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

- `make_game(MiJuego, **opciones) -> (juego, host)`: el juego suelto con un `FakeGameHost`. El host apunta `spoken`, `instructions`, `fixed` (`(frase, grabada)`), `sent` (`events(evento)`, `last(evento)`), `animations`, `finished` y `touches`; tiene `clock` (`advance`), `rng` con semilla (`seed=`), `quiet`, `connected`, `cloud_banks` (bancos «de la nube») y `recorded` (frases grabadas). Los bancos de la app se leen de `assets/games/<id>/`.
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

`LiveEngine` crea el `GameManager` junto a la trivia (`engine.games`; `None` si no hay ningún juego encendido o en una videollamada) y le pasa lo mismo que a ella:

- lo que dice Sonia (`on_assistant_text`: el texto acumulado de cada frase y, al cerrarla, la frase entera) y lo que dice el visitante (`on_user_text`, `on_user_turn_end`);
- las delegaciones (`on_delegation`) y el ciclo de 50 ms (`tick`);
- la sesión que se cae o se renueva, y GPT-Live apagada al cambiar de modo, de Modo Jean, de modo debug o con el editor de personaje (`on_session_lost`: la partida se cancela);
- `client_hello` y `game_event` del hub; `ctx.extra["games"]` para las acciones y `snapshot()["games"]` para el panel.

Mientras hay un juego en pantalla no hay animación de stand ni renovación de la sesión por inactividad, como con la trivia. El saludo automático con la mano lo apaga Unity (`GameHud`). La trivia no empieza con un juego en marcha ni al revés. La visión llega de `build_game_vision` con la cámara del motor (solo `VISION_SOURCE=opencv`), el hub (vista en vivo) y el modelo de visión (`vision_llm`, que pasa la CLI). Si un `tick` falla 20 veces seguidas, la partida se cancela (`error`).

La CLI (`build_components`) registra `start_game`, `stop_game` y las jugadas de los juegos encendidos (`enabled_games`), salvo en una videollamada. El prompt base solo gana la línea «Juegos en tu pantalla: …. Delega empezarlos y terminarlos; las reglas te llegan al empezar.», que sale de esos mismos juegos, y el recordatorio final («empezar y terminar los juegos y sus jugadas» solo pasa si lo delega).

## El panel (para F0-Panel)

El panel usa el `GameManager` del motor (`engine.games`, `None` si esta Sonnia no tiene juegos) y no toca los juegos:

| Qué | Cómo |
|---|---|
| Estado | `manager.snapshot()` (también en `engine.snapshot()["games"]`): `enabled`, `active` (id o `null`), `title`, `phase` (`off`, `playing`, `finishing`), `elapsed_s`, `state` (el `snapshot()` del juego), `games` (`[{id, title, needs, off, available, reason}]`), `games_off`, `banks` (`[{id, game, title, file, min_entries, source}]`, `source` = `cloud` o `app`), `unity_games` (o `null` si la pantalla no anunció juegos) y `preview`. |
| Capacidades | `manager.capabilities()`: `games`, `game:<id>` (solo los que anuncia la Unity conectada) y `game_banks`. Van con las demás en `data-cap`. |
| Empezar | Orden `game_start` (`game`): `await manager.start(id, "panel")` → `(ok, mensaje)`. Antes, lo mismo que la trivia: «Conversando», sin modo debug, sin editor de personaje y con la pantalla conectada. |
| Terminar | Orden `game_stop`: `await manager.stop("panel")`. |
| Interruptores | Ajuste compartido `games_off` (lista de ids): normalízalo con `normalize_games_off` y aplícalo con `await manager.set_games_off(ids)` (también al arrancar, con lo guardado). Si se apaga el que está en marcha, se termina. |
| Bancos | Cargar: `await asyncio.to_thread(manager.bank_text, bank_id)` (el de la nube o el de la app). Guardar (`set_game_bank`, `bank`, `text`): `ok, mensaje = manager.validate_bank(bank_id, text)`; si vale, guarda `game_banks` con `{**actual, bank_id: text}` (o sin esa clave si `text` está vacío: «Volver al de la app») y aplica con `manager.use_cloud_banks(valor)`. Normaliza lo que llega de la nube con `normalize_game_banks`. |
| Frases grabadas | `await asyncio.to_thread(manager.fixed_phrases)` se suma a las frases de «Preparar voces», de la grabación automática y del contador de frases grabadas. |

Las Sonnias anteriores ignoran `games_off` y `game_banks`, y sus pantallas no anuncian juegos.
