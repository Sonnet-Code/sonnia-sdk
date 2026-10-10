# Wordle de tecnología (`wordle`)

> Lo hizo A6. Plan: `docs/plan-juegos.md`, sección 5.5. Contrato y cómo se hace un juego: `docs/juegos.md`; lado de Unity de los cimientos y capturas: `docs/juegos-unity.md`. El banco de palabras es un **borrador pendiente de revisión de Jean**.

## Qué es

Una palabra de tecnología de 5 letras y seis intentos para el grupo entero. Los visitantes gritan palabras, Sonnia elige la que oye, la pone en el tablero y las fichas se voltean con los colores del Wordle de verdad: verde (en su sitio), amarilla (está, pero en otro sitio) y gris (no está). Tras cuatro intentos fallidos sale una pista en la pantalla. Si aciertan hay confeti y baile; si se acaban los intentos, sale la palabra con su pista.

Es un juego sin cámara (`needs` vacío) y de grupo: pueden jugar a la vez todos los que quepan delante de la pantalla, sin turnos. Vale **cualquier palabra de 5 letras**, sea de tecnología o no y exista o no: no hay diccionario, que es más divertido y evita discusiones.

## Cómo se juega

1. **Empezar.** El visitante dice «¿jugamos al Wordle?» y GPT-Live delega `start_game(wordle)` (o el equipo pulsa el botón del panel). El orquestador elige una palabra del banco que no haya salido, manda `start` (la rejilla vacía), le pasa a GPT-Live las reglas con `instruct` (menos de 1200 caracteres, sin la palabra) y le devuelve el guion de arranque: que explique el juego en dos frases y pida la primera palabra.
2. **Cada intento.** El grupo grita una palabra; GPT-Live la escribe bien (si la deletrean, junta las letras) y delega `wordle_guess(palabra)`. El orquestador la normaliza, la colorea y manda `guess` con el tablero entero; a GPT-Live le devuelve un resumen corto («bien colocadas (verdes): L (primera) y X (quinta); en otro sitio (amarillas): I; no están (grises): N y U. Quedan 4 intentos») para que anime al grupo.
3. **La pista.** Tras `GAME_WORDLE_HINT_AFTER` (4) intentos fallidos, la pista del banco sale en la tarjeta de la derecha y el guion del intento le pide a Sonnia que la lea.
4. **El final.** Si aciertan, confeti, la fila baila y el guion manda al grupo a hablar con `TRIVIA_WIN_CONTACT` (Brian o Mariel): Sonnia no sabe qué premios hay ni los promete. Si se acaban los intentos, sale la palabra con su pista y el guion los anima a una revancha. En los dos casos el resultado se queda en pantalla hasta que Sonnia termina de contarlo (`GAMES_RESULT_SECONDS` y `GAMES_FINAL_WAIT_SECONDS`), el manager manda `end` y le dice a GPT-Live que vuelva a conversar. Si piden otra partida, `start_game` cierra la que enseña el resultado y empieza la nueva.

## Quién hace qué

| Quién | Qué hace |
|---|---|
| GPT-Live | Explica el juego, **oye y entiende** al grupo (varias voces, deletreos, «la ka-efe-ka»), escribe la palabra bien y delega el intento. Si no está claro que se la dicen a ella o gritan varias a la vez, pregunta. Cuenta el resultado con ánimo y lee la pista. **No sabe la palabra** hasta que termina la partida: no puede revelarla ni corregir los colores. |
| Backend Responses | Llama a `start_game`, `wordle_guess` y `stop_game` con lo que le da GPT-Live. Si no le llega la palabra, no la inventa. |
| Orquestador | Guarda la palabra y la pista, elige sin repetir hasta agotar el banco, valida y normaliza cada intento, lo colorea con la regla del Wordle de verdad y escribe el guion de cada paso. Lleva la pantalla (`start`, `guess`, `invalid`) y el final (`finish`). Una jugada a la vez (un candado), así que dos intentos que llegan juntos no se pisan las filas. |
| Unity | Pinta: la rejilla, el volteo, la sacudida, la pista, las letras usadas y el confeti (`WordleController`). No manda nada al orquestador. |

## Acciones de GPT-Live

| Acción | Cuándo la usa | Qué devuelve |
|---|---|---|
| `start_game` (`juego`: `wordle`) | El visitante quiere jugar al Wordle. | El guion de arranque (con `PARA SONIA:`). Si ya hay una partida del Wordle, cómo va (intentos, palabras probadas y la pista si ya salió). |
| `wordle_guess` (`palabra`) | El grupo dice una palabra de 5 letras. | El resumen del intento con los intentos que quedan; si sale la pista, que la lea; si aciertan o pierden, el guion final. Con `no_lo_dijo` (no se entendió ninguna), que pida una. |
| `stop_game` | Quieren dejarlo. | Con la partida en marcha, antes de cerrar se enseña la palabra con su pista y el resultado le dice a Sonia cuál era para que la diga («Lo dejan aquí: la palabra era REACT…»). La pantalla recibe el último estado con `stopped: true` (no es un intento nuevo: no se vuelve a voltear ninguna fila; con ningún intento hecho, `row: -1` y el tablero vacío). Termina con `end` (`lose` y `stopped: true`) y vuelve la conversación. «Terminar juego» en el panel hace lo mismo y Sonia lo cuenta en cuanto calla. |

Los guiones de `wordle_guess` por caso:

| Caso | Guion | Pantalla |
|---|---|---|
| Palabra válida | «Intento 2 de 6, «LINUX»: bien colocadas…; quedan 4 intentos. Cuéntalo en una frase corta, con ánimo, y pídeles otra palabra.» Con todas grises dice que descartan esas letras de golpe; con tres verdes o más, que van muy cerca. | `guess` |
| Pista (el intento 4) | Lo mismo y «ha salido la pista en la pantalla: léela tal cual, «…»». | `guess` con `hint` |
| Último intento fallido | La palabra y su pista, con cariño y una revancha. | `guess` con `result: lose` |
| Acierto | «¡LO HAN ADIVINADO en el intento N de 6!», la palabra con su pista, y que pasen a hablar con el equipo (sin premios). | `guess` con `result: win` |
| No tiene 5 letras, lleva cifras o símbolos, o no se entendió | Qué pasó, que **no cuenta como intento** y cuántos llevan, y que pida otra. | `invalid` (suelto) |
| Ya probada | ««LINUX» ya la probaron antes», sin gastar intento. | `invalid` |
| Fuera de turno | El manager contesta: «no hay ninguna partida…» o «la partida ya ha terminado…». Dentro del juego, tras ganar o perder, también: nunca una excepción. | nada |

Lo que dijo el grupo se repite en el guion solo con letras y cifras y 20 caracteres como mucho: una frase pensada para colarle instrucciones a Sonnia no llega a su contexto.

## Reglas del color con letras repetidas

`score_guess` (`server/sonia/games/wordle/logic.py`) hace dos pasadas, como el Wordle de verdad: primero las verdes, que se retiran de la palabra secreta, y luego, de izquierda a derecha, cada letra que no es verde es amarilla si a la palabra aún le queda una de esas sin repartir, y gris si no. Casos que prueban `tests/games/test_wordle_logica.py` (contra una segunda formulación de la regla, con **todos** los pares posibles de dos y tres letras):

| Intento | Palabra | Marcas | Por qué |
|---|---|---|---|
| `SPEED` | `ABIDE` | `xxyxy` | Una sola E en la palabra: la primera es amarilla, la segunda gris. |
| `EERIE` | `REACT` | `xgyxx` | La E de la segunda posición está en su sitio: es la verde, y la E de antes se queda gris (sin la pasada de verdes saldría amarilla). |
| `OVOID` | `ABOUT` | `xxgxx` | Lo mismo con la O. |
| `LLAMA` | `SCALA` | `yxgxg` | Una L en la palabra: solo la primera sale amarilla. Las dos A están, y en su sitio. |
| `LLAMA` | `CHILL` | `yyxxx` | Dos L en la palabra: las dos amarillas. |
| `BOBBY` | `ABBEY` | `yxgxg` | El ejemplo de los manuales. |

El resumen para GPT-Live avisa cuando una ficha gris es de una letra que sí está («Ojo: de la L solo hay una en la palabra»), para que Sonnia no diga que la letra no existe.

## Pantalla

Todo va en la tarjeta de la franja alta (la de la trivia): la rejilla a la izquierda y, a la derecha, la pista arriba y las letras debajo. La cámara pasa sola al plano de panel para que Sonnia quede debajo (`GameHud`). Los subtítulos de abajo quedan libres. Los eventos están en `docs/protocolo.md` («Eventos de cada juego», `wordle`): `start`, `guess` e `invalid`; Unity no manda ninguno.

- **Rejilla** de `rows`×5 (6×5): fichas de 88 px con borde y esquinas redondeadas. Al llegar un `guess`, las letras entran en la fila (un latido), las fichas se voltean una a una (`GameAnim.Flip`, 0,5 s con 0,2 s entre fichas) y cambian al color de su marca a medio giro: verde, amarillo y gris azulado.
- **Sacudida.** Con `invalid`, la primera fila libre enseña lo que se entendió con el borde en rojo, se sacude (`GameAnim.Shake`) y un rótulo rojo dice por qué (`Hud.ShowBanner`). Se limpia sola al cabo de 1,4 s y no gasta fila.
- **Pista.** Candada al empezar (un signo de pregunta y «sale tras 4 intentos», que va contando los que faltan). Al llegar `hint` sale con un rebote y destellos. Al terminar, la tarjeta enseña «la palabra era» con la palabra en fichas (verdes si acertaron) y su pista.
- **Letras.** Las 26 letras en cuatro filas, cada una en su mejor color (verde antes que amarillo antes que gris; las que no han salido, en azul). Es el teclado del Wordle, algo más que «una fila con las letras usadas» del plan: así se ve también lo que falta por probar.
- **Lo dejan a medias** (`stopped`). La cabecera dice «LO DEJAMOS AQUÍ» (no «SIN INTENTOS»: no se agotaron) y la tarjeta de la derecha enseña «la palabra era» con su pista; la fila ya pintada no se vuelve a voltear y las que la pantalla no hubiera visto (se conectó justo entonces) salen ya puestas. No sale la tarjeta de resultado: el tablero se queda unos segundos con la palabra y se retira. Sonnia hace el gesto amable de la derrota.
- **Final.** Al acertar, la fila baila (un salto con latido, de ficha en ficha), llueve confeti (`Hud.Celebrate`) y Sonnia lo celebra (`QuickAction_vibe`, alegría). Al perder, `emotions-0049-traitsKind`. Con el `end` sale la tarjeta de resultado de los juegos («¡GANARON! KAFKA · 3 DE 6» o «¡CASI! ERA KAFKA») unos 3,5 s.
- **Reconexión.** El último `guess` lleva el tablero entero (`board`) y las letras usadas (`used`): una Unity que se reconecta o arranca a mitad pinta ya puestas las filas que no había visto y solo voltea la última.
- **Sin tirones.** La rejilla (unos 250 objetos de interfaz) se monta la primera vez y se reutiliza mientras no cambien las filas ni la pista; cada partida solo la deja como nueva.
- Con menos o más filas (3 a 8), las fichas se encogen para que la rejilla no pase de 578 px de alto.

## En el panel

La tarjeta «Juegos» enseña «Jugando a Wordle de tecnología · 1:15 · Intento 3 de 6» (el `summary` de `snapshot()`: «6 intentos» al empezar, «Intento N de 6» mientras se juega, «Acertaron en N de 6», «Sin intentos (6 de 6)» o «Lo dejaron (N de 6)» al terminar). El estado del panel **no lleva la palabra ni la pista**: se ve delante de los visitantes, y sin `summary` el panel enseñaría los datos del estado tal cual. Los bancos se editan en «Bancos de los juegos» (`wordle_palabras`), y el interruptor del juego (`games_off`) lo apaga en todas las Sonnias sin reinstalar.

## Bancos

| Banco | Archivo | Entradas | Mínimo |
|---|---|---|---|
| `wordle_palabras` (Palabras del Wordle) | `assets/games/wordle/palabras.md` | 65 | 10 |

Formato (también al principio del archivo): cada palabra es un encabezado `## PALABRA` (5 letras, sin tildes; la Ñ cuenta como N) y una línea `> pista` debajo (como mucho 160 caracteres y sin decir la palabra). Las entradas mal formadas (no tienen 5 letras, repetidas, sin pista, con la pista demasiado larga o que dice la palabra) se saltan con un aviso en el registro y en el panel al guardar. Con menos de 10 válidas, el banco ni se guarda desde el panel ni se juega; si el de la nube no llega, sigue el de la app. Se edita desde el panel («Bancos de los juegos») y manda desde la próxima partida, sin instalar nada.

Las 65 palabras son términos técnicos tal como se dicen en el sector (lenguajes y herramientas como LINUX, REACT, SWIFT, KAFKA, REDIS, FLASK, SCALA o JULIA; conceptos como CLOUD, PIXEL, TOKEN o CACHE; el mundo Google y la IA como GMAIL, COLAB, GEMMA o LLAMA; palabras del código como CLASS, STATE o WHILE). Ninguna nombra las marcas con las que está hecha Sonia (lo vigila un test). **Pendiente de que Jean las revise.**

Sin repetir: el juego recuerda qué palabra salió en cada partida y elige entre las que nunca han salido o hace más que salieron, así que no repite ninguna hasta agotar el banco (65 partidas seguidas con el de la app).

## Frases grabadas

Ninguna. Ninguna jugada tiene un tiempo exacto, así que no hay `say_fixed` ni `phrases()`: lo que dice Sonnia sale siempre de GPT-Live.

## Ajustes (`GAME_WORDLE_*`)

| Ajuste | Por defecto | Qué hace |
|---|---|---|
| `GAME_WORDLE_ENABLED` | `true` | El juego se ofrece (además de estar encendido en `games/registry.py` y de que el equipo no lo apague desde el panel). |
| `GAME_WORDLE_ROWS` | `6` | Intentos. Entre 3 y 8 (Unity reparte la altura). |
| `GAME_WORDLE_HINT_AFTER` | `4` | La pista sale tras estos intentos fallidos. `0` o más que las filas: sin pista (las reglas se lo dicen a GPT-Live). |
| `GAME_WORDLE_ABANDON_SECONDS` | `90` | Sin voz ni actividad del grupo durante esto, la partida se cancela. Manda sobre `GAMES_ABANDON_SECONDS` (60). |

Los comunes (`GAMES_*`): `GAMES_NUDGE_SECONDS` (3), `GAMES_RESULT_SECONDS` (4) y `GAMES_FINAL_WAIT_SECONDS` (20).

## Robustez

- **El empujón.** Si el grupo habla y en 3 s no se delega nada, con Sonnia callada, se le pasa por `commentary` que, si dijeron una palabra, la delegue ya (decirlo no basta: el tablero solo cambia si delegas); si solo charlaban, que no diga nada. Las reglas ya le avisan: «en la pantalla nada cambia si no lo delegas».
- **Una jugada a la vez.** Dos `wordle_guess` que llegan juntos se hacen uno tras otro (probado con una pantalla lenta).
- **Fuera de turno.** Sin partida, con el resultado ya en pantalla o tras ganar o perder, el guion lo dice: nunca hay excepción. Los argumentos raros (`None`, un número, sin `palabra`) se tratan como «no se entendió ninguna palabra».
- **Abandono, sesión caída y Unity.** Como dice el contrato (`docs/juegos.md`): la partida se cancela, Unity retira la pantalla y GPT-Live vuelve a conversar. Una Unity que no anuncia el juego no lo ofrece.
- **Reconexión de Unity.** Se repiten el `start` y el último `guess`, con el tablero entero.

## Pruebas y capturas

- `uv run --no-sync pytest -q tests/games/test_wordle.py tests/games/test_wordle_logica.py tests/games/test_wordle_motor.py` (sin red, sin Unity y sin cámara; el último pasa por el motor de verdad con un GPT-Live falso: herramientas, reglas por `instructions.append`, guiones con `PARA SONIA:` y los mensajes de pantalla): las reglas con letras repetidas (contra una segunda formulación y con todos los pares de dos y tres letras), la normalización, el banco (el de la app y el mal formado), el flujo entero (empezar, jugar, pista, ganar, perder, cancelar, abandonar y reconectar), una cancelación a mitad de un intento, las jugadas fuera de turno, 40 partidas con palabras al azar (letras, tildes, cifras, signos y tipos raros: nunca lanza y el tablero queda coherente), el tope de 1200 caracteres, que ningún texto nombre el stack ni lleve la palabra antes del final, y que la secuencia del orquestador falso sea la que manda el juego de verdad.
- Ver la pantalla sin Sonnia: `uv run --no-sync python ../scripts/juegos_demo.py --juego wordle --puerto 87xx` (desde `server/`) y Unity apuntada a él con `-sonia-ws ws://127.0.0.1:87xx`. Las capturas 9:16 en batch: `scripts/juegos_capturas.sh --juego wordle --puerto 87xx --clon <el compartido> --salida <carpeta>` (receta en `docs/juegos-unity.md`).
- **Verificado en Unity** (Play en batch, 9 de octubre de 2026, 20 capturas 9:16 revisadas, que sigue `server/sonia/games/wordle/demo.py`): la rejilla vacía con la pista candada y las letras sin usar; un intento a medio volteo y terminado con la cuenta atrás de la pista; una palabra que no vale (corta) y otra repetida, con el borde rojo y el rótulo; la pista tras el cuarto intento; el acierto con la fila bailando, el confeti y la palabra con su pista; la tarjeta de resultado «¡GANARON!»; la derrota con la palabra, su pista y letras repetidas (CHECK y MERGE contra CACHE) y su resultado; una partida de ocho filas sin pista; tres intentos que llegan casi a la vez; una pantalla que se conecta a mitad con el tablero entero y la pista más larga que admite el banco (160 caracteres, que cabe); y los tres finales al dejarlo: con tres intentos hechos (medio segundo después la fila no se está volteando otra vez, el rótulo dice «LO DEJAMOS AQUÍ» y sale la palabra con su pista, sin tarjeta de resultado), sin ningún intento (tablero vacío y la palabra) y con una pantalla que se conecta justo entonces (las tres filas salen ya puestas). La tarjeta acaba hacia los 922 px y la coronilla de Sonnia queda hacia los 1060 px: no le tapa la cabeza en ningún estado.

## Pendiente

- **Probar con la API real** (lo decide Jean): que GPT-Live delegue cada palabra (también con varias voces y deletreadas), que no diga el resultado sin delegar y que el empujón no la haga hablar de más. Las pruebas automáticas usan un GPT-Live falso.
- **Que Jean revise el banco** (`assets/games/wordle/palabras.md`): es un borrador.
- **Rendirse.** Si el grupo lo deja antes de agotar los intentos (`stop_game` o «Terminar juego»), se enseña la palabra y Sonia la dice (`WordleGame.stop_requested`, el gancho de los cimientos), sin acción nueva para el backend.
