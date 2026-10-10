# Akinator dev (`akinator`)

Plan: `docs/plan-juegos.md`, sección 5.3. Contrato de los juegos: `docs/juegos.md`. Pantalla de Unity y capturas: `docs/juegos-unity.md`. Eventos: `docs/protocolo.md`, «akinator».

> **Estado (10 de octubre de 2026):** el orquestador y la pantalla están hechos y probados con un GPT-Live falso (también dentro del `LiveEngine` real) y con el orquestador falso en Unity, con capturas 9:16 revisadas de cada estado. No se ha probado con la API real (decisión de Jean): ver «Pendiente».

## Qué es

El visitante piensa en algo del mundo tech (un lenguaje, una herramienta, una empresa, un producto de Google, un personaje de la informática...) sin decirlo, y Sonnia lo adivina con preguntas de sí o no, como mucho `GAME_AKINATOR_MAX_QUESTIONS` (20). Los temas que valen están en un banco que se edita desde el panel (`akinator_temas`): por defecto, el mundo tech; ahí se pueden añadir, por ejemplo, cosas dominicanas.

No usa la cámara ni el modelo de visión, y no hay parser de lo que dice el visitante: GPT-Live entiende «sí», «no», «no sé» y «a veces» y conduce la partida.

## Cómo se juega

1. **Empezar.** `start_game(akinator)`, por voz o desde el panel. Sale la tarjeta «Piensa en algo… y no lo digas» con la bola de cristal y los 20 puntos de progreso vacíos (uno por pregunta). Los temas del banco no salen en la tarjeta (a 2 o 3 m no se leían y Sonnia los dice), pero sí entran en las reglas y en lo que le pide decir al empezar. Las reglas entran en GPT-Live por `instruct` (menos de 1200 caracteres, con los temas del banco) y el guion de arranque le dice que explique el juego en dos frases, espere a que el visitante avise y no pregunte nada todavía.
2. **Preguntas.** Cuando el visitante avisa, GPT-Live hace sus preguntas: una cada vez, solo de sí o no, **sin delegar** (una delegación por pregunta la haría lentísima). El orquestador cuenta las preguntas en la transcripción de Sonnia y pinta «PREGUNTA 7 DE 20», los puntos y la pregunta en curso. No cuenta ni la apertura ni lo que no es una pregunta del juego («¿verdad?», «¿listo?», «¿cómo dices?»).
3. **Adivinar.** Cuando lo tiene claro (no antes de la quinta pregunta) delega `akinator_guess(respuesta)`: sale la tarjeta grande «¿Es… Kotlin?» y Sonnia se lo pregunta.
4. **Veredicto.** Cuando el visitante dice si acertó, o qué era, GPT-Live delega `akinator_result(acierto, respuesta_real)`:
   - **Acierta:** confeti, «¡Lo sabía!» y Sonnia presume.
   - **Falla y el visitante dice qué era:** «¡Me ganaste!» con lo que era. A quien le gana se le manda con el equipo del stand (`TRIVIA_WIN_CONTACT`, Brian o Mariel), sin premios.
   - **Falla y no dice qué era:** si quedan preguntas y no ha fallado ya tres veces, rótulo «¡No era Kotlin!» y sigue preguntando donde iba; si no, se rinde: «Me rindo… ¿Qué era?», y cuando el visitante lo dice, `akinator_result` otra vez con lo que era.
5. **Límite.** Si llega a la pregunta 20 sin saberlo arriesga su mejor idea o se rinde y pregunta qué era. El orquestador la ayuda en silencio: a la pregunta 15 le avisa de que le quedan cinco y al contar la 20 le dice que es la última (`instruct`, no habla). Si aun así sigue preguntando, un empujón la recoloca.
6. **Después** de un resultado, la partida se queda en pantalla al menos `GAMES_RESULT_SECONDS` y hasta que Sonnia termina de contarlo; luego el manager le dice a GPT-Live que vuelva a conversar con normalidad. Si el visitante pide otra, `start_game` cierra el resultado y empieza de nuevo.

## Quién hace qué

| Quién | Qué hace |
|---|---|
| GPT-Live | Explica el juego, espera el aviso del visitante y hace las preguntas de sí o no, una cada vez y sin delegar. Acepta «sí», «no», «no sé», «a veces» y «probablemente». No repite preguntas, no arriesga antes de la quinta y, si llega a la última sin saberlo, se rinde o arriesga. Delega `akinator_guess` cuando lo tiene claro y `akinator_result` cuando el visitante dice si acertó (o qué era). Reacciona al resultado. |
| Backend Responses | Llama a `akinator_guess` y `akinator_result` con lo que le da GPT-Live. Si no le llega la respuesta, no la adivina. |
| Orquestador | Cuenta las preguntas de Sonnia en su transcripción (solo para la pantalla), lleva la fase, saca la tarjeta de la respuesta, registra el veredicto y manda el estado entero a Unity en cada evento. Avisa en silencio de que quedan pocas preguntas y empuja si GPT-Live no delega el veredicto. |
| Unity | La tarjeta con la bola de cristal, la pregunta, los puntos de progreso, la adivinanza grande, el rótulo del fallo y el resultado (`AkinatorController`). Sonnia piensa con la mano en la barbilla (`touchBeard`) cuando el avatar pasa a «pensando». |

## Acciones de GPT-Live

| Acción | Cuándo la usa | Qué devuelve |
|---|---|---|
| `start_game` (`juego`: `akinator`) | El visitante quiere jugar. | El guion de arranque con los temas del banco (marcado `PARA SONIA:`). Con la partida ya en marcha, cómo seguir. |
| `akinator_guess` (`respuesta`) | Tiene claro qué pensó el visitante. | Cómo preguntárselo («¿Es… X?»). Antes de la quinta pregunta la rechaza una vez («todavía es pronto»); no deja repetir una respuesta que ya falló. |
| `akinator_result` (`acierto`: `si`, `no` o `no_lo_dijo`; `respuesta_real`) | El visitante dice si acertó, o qué era. | El guion de la reacción. `respuesta_real` es lo que era (si acertó, su respuesta; `no_lo_dijo` si no lo dijo). Sin respuesta pendiente, un «no» no hace nada («las preguntas de sí o no no se delegan»). |
| `stop_game` | Ya no quiere seguir. | La partida se cancela. |

Los esquemas son estrictos (todos los parámetros obligatorios, y `no_lo_dijo` en el enum). Si el visitante dice qué era sin decir si acertó, el orquestador lo decide comparando con la respuesta pendiente.

## Reglas para GPT-Live

Entran por `instruct` al empezar (`server/sonia/games/akinator/prompts.py`, `RULES_TEXT`): preguntas de sí o no, una cada vez y sin delegar; acepta «no sé» y «a veces»; no repite; empieza por lo general y afina; los temas que valen (con dos ejemplos de cada uno mientras quepan); no arriesga antes de la pregunta `GAME_AKINATOR_MIN_QUESTIONS`; cómo delegar la respuesta y el resultado; y que la pantalla no cambia si no delega. Como mucho 1200 caracteres: con un banco largo los temas llevan menos ejemplos (y al final solo el nombre). Los temas y ejemplos con marcas del stack (Unity, Windows, GPT...) salen en la pantalla pero no entran en las reglas.

Dos avisos silenciosos más (`instruct`): «llevas 15 de 20» y «la que acabas de hacer es la última». Y los empujones (`GAMES_NUDGE_SECONDS`, solo cuando el visitante habla y no se delega nada): si el visitante ya avisó y Sonnia aún no ha hecho su primera pregunta, «hazla ahora»; con la respuesta en pantalla, «delega el veredicto»; tras rendirse, «delega lo que era»; con las 20 preguntas hechas, «no puedes hacer más: arriesga o ríndete». Mientras pregunta no hay empujón: preguntar sin delegar es lo normal. El manager evalúa el empujón cuando vence, así que si Sonnia ya estaba preguntando no se dice nada.

## El contador de preguntas

`server/sonia/games/akinator/questions.py`. Lo cuenta el orquestador solo para la pantalla y para avisar de que se acaban; no tiene que ser exacto. El motor llama a `on_assistant_text` con el texto acumulado de la frase en curso por cada trozo y, al cerrarla, con la frase entera (`final`); por eso:

- Una pregunta existe cuando llega su «?». Mientras se dice («¿Es un lenguaje de progr») no hay nada que contar.
- Es idempotente: cada pregunta se cuenta una vez por su texto normalizado (sin mayúsculas, tildes ni signos). El mismo texto creciendo, la frase final repitiéndolo o Sonnia repitiendo la pregunta no suben la cuenta.
- Cuenta una por frase: si trae dos preguntas, vale la última y la primera se sustituye en la pantalla sin subir la cuenta.
- No cuenta lo que no es del juego: una sola palabra («¿verdad?», «¿listo?») y frases hechas («¿cómo dices?», «¿me oyes?»), ni la pregunta con la que se rinde («¿qué era?»), que cambia la pantalla a «Me rindo…».
- No cuenta nada hasta que el visitante habla por primera vez tras el arranque (`READY_GRACE_S` de margen para la transcripción tardía de su petición): así un «¿listo?» de la apertura no es la pregunta 1. La apertura no lleva ninguna pregunta.
- No depende de que llegue el cierre de la frase: la frase siguiente se reconoce porque su texto no continúa el anterior.
- Aguanta que el «?» llegue tarde: el motor corta las frases por el silencio del audio y el texto no va pegado a él, así que una pregunta puede quedar abierta al final de una frase («¿Es un lenguaje de programación») y su «?» abrir la siguiente. Se juntan.

Si se descuenta una pregunta (dos en la misma frase) o se cuenta de más (una aclaración que parece pregunta), la pantalla va una arriba o abajo y el juego sigue igual.

## Panel

La tarjeta «Juegos» del panel enseña el `summary` del `snapshot()` del juego: «Esperando a que piense en algo», «Pregunta 7 de 20», «Pregunta 7 de 20 · arriesga: Kotlin», «Se rinde: pregunta qué era», «Acertó: Kotlin» o «Perdió: era Rust». El resto del `snapshot()` (`phase`, `asked`, `max`, `question`, `guess`, `missed`) sirve para depurar. El banco de temas se edita en «Bancos de los juegos».

## Pantalla

Sus eventos están en `docs/protocolo.md` («Eventos de cada juego», `akinator`). Todos llevan el estado entero (fase, preguntas, pregunta en curso, respuesta, fallos), así que el último fijo repinta la pantalla si Unity se reconecta.

La tarjeta de la franja alta es compacta, para que Sonnia siga grande debajo (acaba hacia donde la de la trivia): a la izquierda la bola de cristal (esfera con brillo, arcos de colores que giran, destellos que orbitan y un «?» que flota, sobre un soporte dorado); a la derecha la pregunta o lo que toque; debajo, un punto por pregunta en los colores de Google (el último late) y una línea de ayuda de 30 px, para que se lea a 2 o 3 m.

| Fase | Se ve |
|---|---|
| `waiting` | «PIENSA EN ALGO… Y NO LO DIGAS», «20 PREGUNTAS DE SÍ O NO» en la cabecera, los puntos vacíos y «CUANDO LO TENGAS, AVÍSALE A SONNIA». |
| `asking` | La pregunta en curso, «PREGUNTA 7 DE 20» en la cabecera, los puntos y «RESPONDE: SÍ · NO · NO SÉ · A VECES». |
| `guessing` | «¿ES…» y la respuesta en grande, en dorado, con destellos y el halo de la bola en amarillo. |
| `miss` | Rótulo rojo «¡NO ERA KOTLIN!» unos segundos y vuelve a la pregunta. |
| `giving_up` | «ME RINDO… ¿QUÉ ERA?» con la bola apagada. |
| `revealed` | La tarjeta de resultado: «¡LO SABÍA!» con confeti y la respuesta, o «¡ME GANASTE!» con «ERA: …». |

Sonnia reacciona con los clips de la trivia (`QuickAction_vibe` al ganar, `emotions-0049-traitsKind` al perder, `actions-highFive_actionFail` al fallar) y piensa con la mano en la barbilla mientras el avatar está pensando.

## Bancos

| Banco | Archivo | Entradas | Mínimo |
|---|---|---|---|
| `akinator_temas` («Temas del Akinator dev») | `assets/games/akinator/temas.md` | 8 temas | 3 |

Formato (explicado al principio del archivo): `## Nombre del tema` y debajo, en una o varias líneas, ejemplos separados por comas (opcionales; a Sonnia solo se le pasan los primeros de cada tema, así que van primero los más conocidos). El nombre lo dice Sonnia al explicar el juego (corto: menos de 30 letras); la tarjeta no los pinta. Como mucho 15 000 caracteres en la nube; un tema mal formado (sin nombre, repetido, con un nombre de más de 60 caracteres) se salta con un aviso en el registro y en el panel.

**Borrador pendiente de revisión de Jean.** Los temas y los ejemplos los escribió el agente del juego.

## Frases grabadas

Ninguna: el Akinator no tiene tiempos exactos, así que todo lo dice GPT-Live con sus palabras (`Game.phrases()` devuelve la lista vacía).

## Ajustes (`GAME_AKINATOR_*`)

| Ajuste | Por defecto | Qué hace |
|---|---|---|
| `ENABLED` | `true` | Si se ofrece (además de su línea de `games/registry.py`, `GAMES_ENABLED` y el interruptor del panel). |
| `MAX_QUESTIONS` | 20 | Preguntas de sí o no como mucho (mínimo 5). Son los puntos de la pantalla. |
| `MIN_QUESTIONS` | 5 | No arriesga antes de esta pregunta (el orquestador rechaza una vez una respuesta anterior). |
| `ABANDON_SECONDS` | 60 | Sin voz del visitante durante esto, la partida se cancela. |

Constantes del juego (en `game.py`): tres respuestas fallidas como mucho antes de rendirse (`MAX_GUESSES`), aunque queden preguntas.

## Pruebas y capturas

- `server/tests/games/test_akinator.py`: el banco (bien y mal formado, mínimo, tope, el de la nube), las reglas (1200 caracteres, sin marcas del stack, con un banco enorme), el flujo entero (empezar, contar, arriesgar, acertar, fallar, rendirse, tres fallos), las jugadas fuera de turno, los empujones (también el de arranque), la reconexión de Unity, el abandono y la sesión perdida, con el `GameHost` falso y con el `GameManager` de punta a punta. Además una partida **dentro del `LiveEngine` real** (con un GPT-Live falso por WebSocket y un `Hub` de verdad): Sonnia habla en trozos con audio, el motor corta las frases por silencio y el contador sale bien con parciales, finales, una pregunta repetida y la apertura sin contar.
- `server/tests/games/test_akinator_preguntas.py`: el contador con transcripciones parciales y finales como las que da el motor (`clean_transcript`), el «?» que llega tarde y una prueba aleatoria (300 transcripciones inventadas: nunca lanza ni baja).
- `server/sonia/games/akinator/demo.py`: la secuencia del orquestador falso (`scripts/juegos_demo.py --juego akinator`), con una captura 9:16 por estado: una partida que Sonnia gana, otra que pierde, otra con otro máximo de preguntas y otra con pocos temas y una respuesta larguísima (textos largos):

  ```bash
  SONIA_UNITY_LOCKS=$SP/unity-locks scripts/juegos_capturas.sh --juego akinator --puerto 8794 --salida $SP/akinator/capturas
  ```

- **Capturas revisadas** (10 de octubre de 2026, Unity en batch sobre el clon compartido, 1080x1920 en Play): empezar (`waiting`), pregunta corta, larga (cinco líneas) y última; Sonnia pensando con la mano en la barbilla (dos fotogramas); adivinanza entrando y ya puesta, con un nombre corto, uno de dos líneas y uno de 58 caracteres; rótulo «¡No era Java!»; resultado con confeti y con una respuesta larga; «me rindo»; «¡me ganaste!»; el máximo de 12 preguntas; pocos temas; y la pantalla cerrada tras cada final. Con `capturas.txt` sin avisos: lo de la franja alta acaba en el píxel 716 y la coronilla de Sonnia queda hacia el 850 (hacia el 800 con el resultado).
- Lo que se arregló al verlas: el halo de la bola (un disco plano pisaba el texto: ahora es un degradado suave), el rótulo de fallo tapaba la línea de ayuda (ahora la oculta mientras sale), los destellos de la adivinanza caían sobre el título, la bola al rendirse y los nombres largos en el rótulo y en el resultado (se recortan con «…»). El último ajuste (recortar a 15 caracteres el nombre del rótulo de fallo para que quepa en la tarjeta) no se volvió a capturar.

## Pendiente

- **Probarlo con la API real** (lo decide Jean; no se ha hecho): que GPT-Live pregunte sin delegar y a buen ritmo, que espere el aviso del visitante antes de la primera pregunta, que delegue `akinator_guess` y `akinator_result` a la primera, que no diga que acertó sin delegarlo y que respete el límite. Lo más delicado es el contador: depende de cómo escriba GPT-Live sus preguntas en la transcripción (con «¿» y «?»).
- Los temas y ejemplos del banco los revisa Jean.
- Si el ritmo de las preguntas se nota lento en el stand, se puede quitar el gesto de pensar (`ponderWhileThinking` en `AkinatorController`) o acortar las reglas.
