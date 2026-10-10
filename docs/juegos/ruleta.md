# La ruleta de Sonnia (`ruleta`)

> Plan: `docs/plan-juegos.md`, sección 5.1. Contrato y cómo se hace un juego: `docs/juegos.md`; pantalla común de Unity: `docs/juegos-unity.md`. Código: `server/sonia/games/ruleta/` y `unity/Assets/Scripts/Sonia/Games/Ruleta/`.

## Qué es

Una ruleta de cinco casillas gira en la franja alta de la pantalla y cae en un reto: trivia relámpago, adivinanza geek, explica una tecnología en 20 segundos, predice el futuro de la IA o reto sorpresa de Sonnet Code. Al terminar cada reto, Sonnia enseña el resultado, reacciona y ofrece otra vuelta. La partida no termina sola: dura hasta que el visitante no quiere más (`stop_game`), el equipo la termina desde el panel o nadie juega durante `GAME_RULETA_ABANDON_SECONDS`.

## Cómo se juega

1. **El giro.** `start_game(ruleta)`, por voz o desde el panel. El orquestador elige la casilla con los pesos de `GAME_RULETA_WEIGHTS`, sin repetir la anterior (salvo que solo quede una), prepara ya su reto (saca la pregunta, la adivinanza...) y manda `spin` con la casilla de destino. Unity gira unos 4,6 s, frena y contesta `wheel_stopped`. Si Unity no contesta en 7,6 s, el orquestador sigue solo: nunca se queda esperando. Una casilla sin contenido (banco vacío, trivia apagada) no sale.
2. **El reto.** Con la ruleta parada: la tarjeta del reto a la pantalla (`challenge`), sus reglas a GPT-Live (`instruct`, 1200 caracteres como mucho) y, en cuanto Sonia calla (como mucho 6 s), que lo anuncie (`speak`). Los contadores cuentan desde que termina de anunciarlo: la primera vez que se la oye hablar y luego lleva 0,8 s callada (si no se la oye, a los 15 s).
3. **El resultado.** Las jugadas delegadas lo ponen en pantalla (`result`) y devuelven la reacción y la pregunta de otra vuelta: si quieren, `ruleta_spin`; si no, `stop_game`. Con un reto a medias, `ruleta_spin` lo salta y gira otra vez.

| Casilla | Cómo se juega | Jugada | Pantalla |
|---|---|---|---|
| Trivia relámpago | Una pregunta de tres opciones del banco de la trivia en uso (`GameHost.draw_trivia`, el nivel de `TRIVIA_DEFAULT_LEVEL` y el «sin repetir» de la trivia), sin gorra ni el requisito de seguir a Sonnet Code. GPT-Live recibe la pregunta y las opciones para saber qué letra elige el visitante, pero no la buena: la sabe con el resultado. Pasado el contador (solo visual) y sin respuesta, un recordatorio. | `ruleta_answer`: `A`, `B`, `C` o `se_rinden` | La pregunta, las opciones A, B y C y el contador de `GAME_RULETA_QUIZ_SECONDS` en la esquina; la buena en verde, la elegida en rojo y confeti si acierta. |
| Adivinanza geek | Una de `adivinanzas.md`. GPT-Live recibe la respuesta y las variantes para juzgar lo que contesten, con la orden de no decirla. Tres intentos: con el primer fallo sale la pista (si no había salido ya a los `GAME_RULETA_HINT_SECONDS`) y al tercero, la solución. | `ruleta_answer`: `acierto`, `fallo` o `se_rinden` | La adivinanza, los intentos, la pista cuando toca y, al final, la solución en verde, rojo o azul. |
| Explica en 20 segundos | Una tecnología de `tecnologias.md` (GPT-Live recibe además la nota de qué es). El tiempo (`GAME_RULETA_EXPLAIN_SECONDS`) arranca con la primera transcripción del visitante tras el anuncio, o a los 5 s. Al acabar suena «¡Tiempo!» (grabado) y se le pide la nota del 1 al 10 con humor. Puede ponerla antes si el visitante dice que ha terminado. | `ruleta_score(nota)`, o `ruleta_answer(se_rinden)` | La tecnología en grande con el contador circular en el centro, «¡Tiempo!» y la nota con estrellas (media estrella por punto). |
| Predice el futuro de la IA | El visitante predice y Sonia la resume (120 caracteres como mucho) con una «probabilidad» puesta con gracia. | `ruleta_prediccion(prediccion, probabilidad)`, o `ruleta_answer(se_rinden)` | La pregunta y una bola de cristal; luego la predicción y la barra de probabilidad, que se llena. |
| Reto sorpresa de Sonnet Code | Uno de `retos-sonnet-code.md`: un reto de stand que se le cree, como en la trivia (seguir a Sonnet Code, chocar los cinco con el equipo...). Sin preguntas sobre Sonnet Code desde el 10-oct-2026; si alguien añade una `[pregunta]` al banco, va con dos intentos y GPT-Live recibe la respuesta para juzgar. | `ruleta_answer`: `acierto`, `fallo` o `se_rinden` | La pregunta o el reto, y la solución o «¡Reto cumplido!». |

Cuenta como **reto superado** acertar (trivia, adivinanza, Sonnet Code) o sacar un 7 o más explicando. Al tercero de una partida, Sonia le dice al visitante que pase a saludar a `TRIVIA_WIN_CONTACT` (Brian o Mariel), sin prometer premios (no sabe de ninguno). La cabecera de la tarjeta enseña la vuelta («VUELTA 3») y los retos superados con una estrella.

## Quién hace qué

| Quién | Qué hace |
|---|---|
| GPT-Live | Anuncia el reto que le llega al parar la ruleta, con emoción y sin adivinarlo antes. Entiende lo que contesta el visitante y lo delega: la letra en la trivia relámpago; acierto o fallo en la adivinanza y en las preguntas de Sonnet Code (juzga con la respuesta que tiene, sin decirla); la nota de la explicación; la predicción resumida con su probabilidad. Reacciona al resultado y pregunta si quieren otra vuelta. |
| Backend Responses | Llama a `start_game`, `ruleta_spin`, `ruleta_answer`, `ruleta_score`, `ruleta_prediccion` y `stop_game` con lo que le pasa GPT-Live, y le devuelve el guion (`PARA SONIA:`). |
| Orquestador | Elige la casilla, prepara el reto, guarda la clave de la trivia relámpago, lleva los contadores (pista, tiempo para explicar, recordatorio) y manda la pantalla. Reglas por `instruct`, anuncios por `speak`, «¡Tiempo!» con `say_fixed` y el guion de cada jugada como resultado. Nada de parsers de lo que dice el visitante: solo mira cuándo empieza a hablar para arrancar el tiempo de explicar. |
| Unity | La ruleta (casillas con icono y texto en los colores de Google, lengüeta que hace clic en cada clavija, giro con frenada), las cinco tarjetas, los rótulos, el confeti y las reacciones de Sonnia con los clips de la trivia (`RuletaController`). |

Reglas para GPT-Live (al empezar): la ruleta la gira la pantalla y no adivina el reto; cada respuesta se delega y en la pantalla nada cambia sin delegar; lo que hablan entre ellos no es una respuesta; tras cada reto, otra vuelta o terminar; sin premios. Al terminar, el manager le dice que vuelva a conversar con normalidad.

**Empujones** (`nudge`): si el visitante habla en pleno reto o tras el resultado y en `GAMES_NUDGE_SECONDS` no se delegó nada, se le recuerda con una orden corta que delegue (la respuesta sin decir si acierta, otra vuelta o terminar); mientras gira, solo terminar. Despedirse («ya está, gracias», «hasta luego») cuenta como terminar: en las pruebas con la API real Sonnia contestaba «¡De nada!» y el juego seguía. Mientras explica una tecnología, no. Los guiones tras cada jugada piden una frase corta, para que calle antes (interrumpirla mientras lee un resultado es donde más fallaba), y en las adivinanzas y preguntas con la respuesta en la mano se le repite que no diga si acierta sin delegarlo.

## Acciones de GPT-Live

Todas con esquemas estrictos (todos los parámetros obligatorios; el enum con «no lo dijo»).

| Acción | Cuándo la usa | Qué devuelve |
|---|---|---|
| `start_game` (`juego`: `ruleta`) | El visitante quiere jugar a la ruleta. | Que la ruleta ya gira y que no adivine el reto: se lo dirá al parar. |
| `ruleta_spin` (sin parámetros) | Quieren otra vuelta, u otro reto (salta el que haya). | Qué decir mientras gira. Con la ruleta girando, que espere. |
| `ruleta_answer` (`respuesta`: `A`, `B`, `C`, `acierto`, `fallo`, `se_rinden` o `no_lo_dijo`) | El visitante contesta al reto o se rinde. | El resultado (con la buena o la solución si toca), la reacción y la pregunta de otra vuelta. Un fallo con intentos por delante: ánimo (y la pista con el primero de la adivinanza). Un valor que no vale para el reto en juego (una letra en la adivinanza, `acierto` en la trivia) o `no_lo_dijo`: qué delegar en su lugar. |
| `ruleta_score` (`nota`: entero del 1 al 10) | Termina de explicar la tecnología (o suena «¡Tiempo!»). | La nota en pantalla y que la comente con humor. Fuera de rango se ajusta. |
| `ruleta_prediccion` (`prediccion`: 120 caracteres como mucho; `probabilidad`: entero de 0 a 100) | El visitante dice su predicción. | La predicción en pantalla con su barra y que la comente. Vacía: que se la pida. |
| `stop_game` | Ya no quieren seguir. | El juego se cancela (`end` con `cancel`). |

Cualquier jugada fuera de turno (con la ruleta girando, con el resultado ya en pantalla, la nota en la trivia...) devuelve un texto que reconduce, nunca un fallo.

## Pantalla

Sus eventos están en `docs/protocolo.md` («Eventos de cada juego», `ruleta`). Todos los estados son completos y fijos: tras reconectar, Unity repinta la ruleta parada en su casilla y la tarjeta tal como iba.

- **La ruleta** (`RuletaWheel`): 680 px en la tarjeta común (el 78 % de su ancho, para leer las casillas a 2-3 m), casillas en azul, rojo, amarillo y verde de Google y la de Sonnet Code en blanco, con icono por dentro (rayo, «?», micrófono, bola de cristal y estrella, pintados por código en `RuletaIcons`) y texto en dos líneas por fuera, donde la casilla es más ancha (hasta 38 px). Las casillas de la mitad de abajo giran 180° su texto y su icono, también mientras gira, para que siempre se lean de pie. Mientras se ve la ruleta la tarjeta crece (el contenido pasa de 540 a 732 px) y la cámara se aleja un poco; con el reto vuelve a 540 px, cuando la ruleta ya se fundió. El giro: un pequeño impulso atrás y al menos cuatro vueltas con frenada de cuarto grado hasta la casilla del orquestador, con un desvío al azar dentro de ella. La lengüeta (un triángulo rojo y blanco) salta en cada clavija («clics» visuales) y las clavijas destellan. Al parar, la casilla brilla, las demás se apagan un poco y Sonnia se sorprende; la tarjeta del reto sale 1,1 s después.
- **Las tarjetas** (`RuletaCard`), 540 px de alto como la ruleta para que la tarjeta no salte (la franja alta acaba hacia los 884 px y la coronilla de Sonnia queda hacia los 1020): una píldora con el icono y el nombre del reto en el color de su casilla y debajo lo de cada reto (tabla de arriba). El contador circular es el del HUD: en la esquina en la trivia relámpago y en el centro (200 px) al explicar; con el «¡Tiempo!» se pone a cero. Hasta que sale la pista de la adivinanza, su hueco dice «La pista sale en un ratito».
- **Reacciones de Sonnia** (los clips de la trivia): acierto `actions-highFive_actionSuccess` (o `QuickAction_twoThumbsUp`), fallo `actions-highFive_actionFail`, se rinden `emotions-0049-traitsKind` (o `Peace`), nota de 7 o más `QuickAction_vibe`, nota media y predicción `QuickAction_twoThumbsUp`. Más una emoción en la cara (alegría, pena o sorpresa).
- Rótulos sobre el borde de la tarjeta: «¡Correcto!», «¡Uy! Era la B», «¡Acertaste!», «¡Casi!», «¡No es eso!» (un fallo con intentos, 2,5 s), «¡Tiempo!», «¡Nota 8!», «¡Lo veremos!», «¡Genial!» (reto de stand cumplido), «¡Otra vez será!».

## Bancos

Los tres se editan desde el backoffice («Bancos de los juegos»). Borradores **pendientes de revisión de Jean**, con el formato explicado al principio de cada archivo. En pantalla se escribe «Sonnia» y a GPT-Live le llega «Sonia», escriba el equipo lo que escriba.

| Banco | Archivo | Entradas | Mínimo |
|---|---|---|---|
| `ruleta_adivinanzas` (Adivinanzas de la ruleta) | `assets/games/ruleta/adivinanzas.md` | 35: `## adivinanza`, `- Respuesta:`, `- También vale:` (opcional) y `- Pista:` | 10 |
| `ruleta_tecnologias` (Tecnologías de la ruleta) | `assets/games/ruleta/tecnologias.md` | 44: `## nombre` y, opcional, `> de qué va` (para Sonia, no sale en pantalla) | 10 |
| `ruleta_retos_sonnet_code` (Retos sorpresa de Sonnet Code) | `assets/games/ruleta/retos-sonnet-code.md` | 5, solo `## [reto] ...` (sin preguntas sobre Sonnet Code: nadie se las sabe, decisión de Jean del 10-oct-2026; el formato admite también `## [pregunta] ...` con `- Respuesta:`); `{contacto}` es `TRIVIA_WIN_CONTACT` | 5 |

Los retos de Sonnet Code solo usan datos de `assets/knowledge/04-sonnet-code.md`. Topes de longitud (para la tarjeta y para que las reglas de cada reto no pasen de 1200 caracteres): adivinanza 200, respuesta 60, variantes 140, pista 140, tecnología 32, su nota 200, reto 160. Lo que no encaja se salta con un aviso. Ninguna entrada se repite hasta agotar su banco (lo recuerda mientras no se reinicia el orquestador); las preguntas de la trivia relámpago comparten el «sin repetir» de la trivia.

## Frases grabadas

- «¡Tiempo!», al acabar el tiempo de explicar (`say_fixed`). Si no está grabada o Sonia hablaba, se le pide que lo diga ella con la nota.

## Ajustes (`GAME_RULETA_*`)

| Ajuste | Por defecto | Qué hace |
|---|---|---|
| `ENABLED` | `true` | Ofrecer la ruleta. |
| `WEIGHTS` | `1,1,1,1,1` | Pesos de las casillas, en orden: trivia relámpago, adivinanza, explica, futuro de la IA y reto de Sonnet Code. 0 la quita. Si no se entiende (otro número de pesos, negativos, todo ceros), pesos iguales. |
| `QUIZ_SECONDS` | 20 | Contador (solo visual) de la trivia relámpago; pasado, un recordatorio si no hay respuesta. |
| `HINT_SECONDS` | 30 | La pista de la adivinanza sale a estos segundos del anuncio. |
| `EXPLAIN_SECONDS` | 20 | Tiempo para explicar la tecnología (también en el texto de la casilla). |
| `ABANDON_SECONDS` | 60 | Sin voz ni jugadas durante esto, la partida se cancela. |

Constantes del código (`game.py`): el giro dura 4,6 s y se espera 3 s más a `wheel_stopped`; el anuncio espera como mucho 6 s a que Sonia calle; el tiempo de explicar arranca solo a los 5 s; tres intentos en la adivinanza y dos en las preguntas de Sonnet Code; tres retos superados para mandar con el equipo.

## Pruebas y capturas

- `server/tests/games/test_ruleta.py` (sin red ni APIs): los bancos (la app entera y sin avisos, lo mal formado, los topes, que nada nombre el stack), los pesos y el «sin repetir la anterior», cada reto con sus contadores (anuncio, pista, recordatorio, tiempo de explicar por voz o solo, «¡Tiempo!» grabado o dicho), acierto, fallo y rendirse, las jugadas fuera de turno, los empujones, el tope de 1200 caracteres con las entradas más largas, «Sonnia» en pantalla y «Sonia» para GPT-Live, los esquemas y, con el `GameManager`, la partida por voz, la reconexión, Unity que no contesta, el abandono, la sesión perdida y la trivia en marcha.
- Secuencia del orquestador falso: `server/sonia/games/ruleta/demo.py` (22 capturas: la ruleta quieta, cuatro fotogramas del giro y la parada, cada tarjeta, la pista, el contador, «¡Tiempo!», la nota con estrellas, la barra, los aciertos y fallos y el cierre):

  ```bash
  SONIA_UNITY_LOCKS=$SP/unity-locks scripts/juegos_capturas.sh --juego ruleta --puerto 8742 \
    --salida <scratchpad>/capturas --clon <clon compartido>
  ```

## Pendiente

- Revisión de Jean de los tres bancos (borradores).
- Probarla con la API real (decisión de Jean): que GPT-Live delegue cada jugada, que no adivine el reto mientras gira, que no diga la solución de la adivinanza y cómo pone la nota y la probabilidad.
