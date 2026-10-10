# Búsqueda relámpago (`busqueda`)

Plan: `docs/plan-juegos.md`, sección 5.6. Contrato y cómo se hace un juego: `docs/juegos.md`. Visión (la cámara, la vista en vivo y el juez): `docs/juegos-vision.md`. Pantalla en Unity: `docs/juegos-unity.md`.

## Qué es

«¡El primero que me enseñe algo azul!». Sonnia pide un objeto, el grupo corre a enseñarlo a la cámara y el stand comprueba si lo trae. Se juegan `GAME_BUSQUEDA_ROUNDS` rondas (3) de `GAME_BUSQUEDA_ROUND_SECONDS` (25 s). La imagen de la cámara sale en la franja alta, encima de Sonnia, para que sepan dónde enseñar el objeto («En vivo · no se graba»).

Es el único juego que manda una foto fuera del equipo: una foto reducida cada `GAME_BUSQUEDA_CHECK_SECONDS` (2,5 s) al modelo de visión, con una pregunta cerrada y un tope de `GAME_BUSQUEDA_MAX_CHECKS` (10) por ronda. Nunca se guarda una imagen ni se describe a nadie: el modelo solo dice si se ve el objeto y cuál es.

Necesita (`needs`): la cámara USB, la vista en vivo en la Unity (`camera_preview`) y el modelo de visión.

## Cómo se juega

1. **Empezar.** GPT-Live delega `start_game(busqueda)` (o el equipo pulsa «Búsqueda relámpago» en el panel). El orquestador reserva la cámara, enciende la vista en vivo (sin dibujo encima), manda `start` y la ronda 1 lista (`round`), pasa las reglas por `instruct` (menos de 1200 caracteres) y devuelve el guion: explicar el juego en una frase y anunciar el objeto.
2. **Ronda lista.** La pantalla enseña el objeto, el color y el tiempo entero parado («PREPÁRENSE…»). El orquestador sigue la transcripción de Sonia (`on_assistant_text`, solo para sincronizar la pantalla): cuando dice el objeto y calla un segundo, suena el **«¡Ya!»** grabado y arranca el contador (`go`). Si no la oye decirlo, da la salida al tope de espera (14 s la primera ronda, 9 s las demás).
3. **Miradas.** Cada 2,5 s una foto al modelo de visión con la pregunta del objeto (`VisionJudge.ask`). Las miradas **no se solapan**: si una tarda, la siguiente espera a que acabe y sale enseguida. Cada mirada manda a la pantalla un `checking` (el barrido de «mirando»). Tope de 10 por ronda, contando las de `busqueda_check`.
4. **¡Encontrado!** En cuanto el modelo ve el objeto: `found` (¡Encontrado!, confeti y lo que vio la cámara), suena el **«¡Lo veo!»** grabado y Sonia lo celebra en una frase **describiendo el objeto, nunca a la persona** (ver «Lo que dice el modelo»).
5. **Se acaba el tiempo.** `timeout` (¡Tiempo!), suena el **«¡Tiempo!»** grabado y Sonia lo dice con humor, sin culpar a nadie.
6. **Siguiente.** Cuando Sonia termina de contar el resultado, sale la ronda siguiente (otro `round` y otro anuncio). Tras la última ronda, `finish`: gana si encuentran la mitad o más (2 de 3) y se queda en pantalla hasta que Sonia termina de contarlo; la vista en vivo se retira 3 s después de la última ronda. A quien gana se le manda con `TRIVIA_WIN_CONTACT` (Brian o Mariel); Sonia no sabe de premios.

Nada de lo que oye el visitante se interpreta. Si alguien grita «¡aquí!», GPT-Live delega `busqueda_check` y se mira al momento (dentro del tope), pero el juego no depende de eso: las miradas del reloj ya lo verían.

### Cuando algo falla

- **El modelo no contesta** (sin foto, plazo de 8 s, error): esa mirada cuenta contra el tope pero no pasa nada. Si en una ronda no contesta **ninguna**, Sonia no dice «nadie lo enseñó» sino que no ha podido mirar bien (`timeout` con `silent: true`). Con dos rondas seguidas así, se cancela el juego con una disculpa corta.
- **Una mirada tarda más que la ronda:** la foto que va en el aire al acabar el tiempo aún cuenta durante 3 s; si no llega, la ronda se pierde y la respuesta tardía se ignora.
- **Se cae GPT-Live, cambia el modo o se reconecta Unity:** como dice el contrato (`docs/juegos.md`). Cada mensaje de ronda (`round`, `go`, `found`, `timeout`) lleva el estado completo, así que el último que se repite tras `hello` repinta toda la pantalla.
- **Abandono:** `GAMES_ABANDON_SECONDS` (60 s) sin voz ni actividad (ver a alguien enseñar el objeto cuenta como actividad). Se cancela y suelta la cámara.

## Quién hace qué

| Quién | Qué hace |
|---|---|
| GPT-Live | Anuncia cada ronda con ganas, celebra o lamenta el resultado en una frase y calla durante la ronda. Si oye «¡aquí!» o «¡ya lo tengo!», delega `busqueda_check` antes de decir nada. No ve nada: no dice que lo ve hasta que el sistema se lo cuenta. No usa `look` en este juego. |
| Backend Responses | Llama a `start_game`, `busqueda_check` y `stop_game`, y pasa entero el guion `PARA SONIA:`. |
| Orquestador | Elige los objetos, lleva las rondas y el contador, da la salida, pregunta a la cámara cada 2,5 s con tope, no deja que se solapen las miradas, filtra lo que dice el modelo, registra las fotos y cuenta el resultado. |
| Unity | Muestra la vista en vivo, la tarjeta con el objeto y el contador, el barrido de «mirando», «¡Encontrado!» y el final. No manda nada al orquestador. |

## Acciones de GPT-Live

| Acción | Cuándo la usa | Qué devuelve |
|---|---|---|
| `start_game` (`juego`: `busqueda`) | El visitante quiere jugar. | El guion de arranque: explicar el juego en una frase y anunciar la ronda 1 (con el objeto). |
| `busqueda_check` (sin argumentos) | Alguien grita «¡aquí!» o «¡ya lo tengo!» o le enseña algo. | Mira ya la cámara. Si se ve: el guion para celebrarlo (o el final, si era la última ronda). Si no: que lo acerque, bien a la vista y quieto. Antes de la salida: que espere al «¡Ya!». Ronda ya contada: que no repita nada. Sin miradas: que solo queda esperar. |
| `stop_game` | Ya no quiere seguir. | El juego se cancela. |

`busqueda_check` nunca falla: fuera de turno devuelve un guion que reconduce. Si hay una mirada del reloj en el aire, espera a que acabe (hasta 4 s); si esa mirada ve el objeto, la delegación ya no repite nada.

## Pantalla

Sus eventos están en `docs/protocolo.md` («Eventos de cada juego», `busqueda`). Unity (`Games/Busqueda/BusquedaController.cs`, sobre `GameHud`):

- **Vista en vivo** (la pone `CameraPreviewPanel`): arriba, en 16:9, con «En vivo · no se graba». Encima, en su `Overlay`: el barrido de «mirando» (una línea con halo que baja, esquinas de enfoque y «MIRANDO…») en cada `checking`, y un marco verde al encontrar o rojo al acabarse el tiempo.
- **Tarjeta** (debajo de la vista, la coloca `GameHud`): título de colores, «RONDA 1 DE 3» y un punto por ronda (blanco la actual, verde encontrada, rojo perdida). Dentro: un cuadro con el color del objeto y un «?», el objeto en grande y el contador circular a la derecha. Al encontrarlo, el cuadro pasa a un visto, sale «¡Encontrado!» y lo que vio la cámara; al acabar el tiempo, una cruz y «¡Tiempo!».
- **Final:** la tarjeta de resultado común (`¡PLENO!` con 3 de 3, `¡BUEN OJO!` con la mitad o más, `¡CASI!` si no) con el marcador «2 de 3».
- **Sonnia:** `actions-highFive_actionSuccess` y alegría al encontrarlo, `actions-highFive_actionFail` y pena al acabarse el tiempo, y los clips de ganar o perder de la trivia al final.
- «Sonnia» en pantalla; lo que llega del orquestador pasa por `GameUi.Plain`.

## Cámara

- `host.stream.acquire` y `host.preview.start` (sin overlay) al empezar; el manager los suelta al terminar aunque se olvide. La vista en vivo se retira 3 s después de la última ronda, para que no acompañe a la tarjeta final.
- **Una foto por mirada**, reducida (640 px de ancho) y fresca, al modelo de visión que ya usa Sonia, con una pregunta cerrada. Nunca a GPT-Live, nunca a disco. El juez (`ModelJudge`, `docs/juegos-vision.md`) lleva su propio tope por ronda (`start_round(max_checks)`, que el juego llama al abrir cada ronda) además del contador del juego.
- **Qué le pregunta:** la del objeto (`objetos.md`), cerrada y sin hablar de personas; sin pregunta propia, «En la foto, ¿se ve <objeto> bien a la vista, en una mano o frente a la cámara? No cuentan la ropa ni el fondo.». El prompt del juez ya prohíbe describir personas y dice que la ropa, las gafas o el pelo no cuentan.
- **Coste.** Hasta 9 o 10 fotos por ronda si nadie lo trae (2,5 s en 25 s), menos si lo encuentran antes; el tope de 10 las acota. Cada ronda y la partida entera dejan una línea en el registro, por ejemplo: `Búsqueda: ronda 1/3 «algo azul»: encontrado. 5 fotos al modelo de visión (4 periódicas, 1 por busqueda_check; 5 con respuesta). Partida: 5 fotos, 1 de 3 encontrados` y, al terminar, `Búsqueda terminada (finished): 2 de 3 rondas encontradas, 14 fotos al modelo de visión (14 con respuesta) en 96 s`. Se mide en la primera prueba real.

### Lo que dice el modelo (`JudgeAnswer.what`)

El único texto que sale del modelo de visión hacia Sonia y la pantalla. `clean_what` lo deja pasar solo si es una frase corta de objeto («botella azul»): hasta 40 caracteres y 6 palabras, letras, cifras y poca puntuación, sin palabras de personas (persona, hombre, cara, pelo, camiseta, gafas...), sin acciones («sosteniendo...») ni «en la mano de alguien». Si no cumple, se usa el objeto que se pidió. Así a Sonia solo le llega «en la cámara se ve «botella azul»» o ««algo azul»», nunca algo de quien lo trae.

## Bancos

| Banco | Archivo | Entradas | Mínimo |
|---|---|---|---|
| `busqueda_objetos` («Objetos de la búsqueda relámpago») | `assets/games/busqueda/objetos.md` | 26 | 6 |

**Borrador pendiente de revisión de Jean.** Se edita desde el panel (banco compartido en la nube, `game_banks`) y manda sobre el archivo de la app; «Volver al de la app» lo borra. Se relee al empezar cada partida.

Formato (explicado también al principio del archivo): una sección `## objeto` por objeto, con su artículo, tal como lo dice Sonia («algo azul», «unas llaves», «la credencial del DevFest»). Líneas opcionales: `> pregunta cerrada para la cámara` (sin ella se usa la genérica) y `color: azul` (azul, rojo, amarillo, verde, naranja, morado, rosa, blanco, negro o gris: el color de la tarjeta). El analizador (`bank.py:parse_objects`) se salta con un aviso lo que no encaja:

- nombre de menos de 3 o más de 48 letras, repetido, o que **hable de la persona** (ropa, gafas, cuerpo...): «Nada que obligue a hablar de la persona»;
- una pregunta que no sea cerrada (sin «?»), muy corta o larga, o que hable de personas no tira el objeto: se usa la genérica y se avisa;
- un color desconocido: se avisa y la tarjeta sale sin color.

Los objetos de una partida salen al azar, sin repetirse dentro de ella, y entre partidas primero los que hace más tiempo que no salen (no se repite ninguno hasta agotar el banco).

## Frases grabadas

Con tiempo exacto, por `say_fixed` (de `cache/voice` si están grabadas; si no, por `commentary` pidiendo que las diga tal cual). Las tres se graban con «Preparar voces»:

- «¡Ya!» — la salida de cada ronda.
- «¡Lo veo!» — al ver el objeto, antes de que Sonia lo celebre con sus palabras.
- «¡Tiempo!» — al acabarse el tiempo.

## Ajustes (`GAME_BUSQUEDA_*`)

| Ajuste | Por defecto | Qué hace |
|---|---|---|
| `ENABLED` | `true` | Si el juego se ofrece (además de `GAMES_ENABLED`, la lista de `games/registry.py` y el interruptor del panel). |
| `ROUNDS` | 3 | Rondas por partida (como mucho tantas como objetos del banco). |
| `ROUND_SECONDS` | 25 | Duración de cada ronda. |
| `CHECK_SECONDS` | 2.5 | Cada cuánto va una foto al modelo de visión. |
| `MAX_CHECKS` | 10 | Tope de fotos por ronda (también el del juez). |
| `ABANDON_SECONDS` | 0 | 0 = `GAMES_ABANDON_SECONDS` (60 s). |

## Pruebas y capturas

- `server/tests/games/test_busqueda.py` (juego suelto con un juez falso guionizado y de punta a punta con el `GameManager`): empezar con la vista en vivo y las reglas, la salida con el «¡Ya!», la cadencia y el tope de miradas, que no se solapen, encontrarlo a la primera o a la quinta o nunca, el juez sin respuesta (y la cancelación a las dos rondas mudas), la foto en el aire al acabar el tiempo, `busqueda_check` (antes de la salida, sin verlo, sin respuesta, viéndolo, sin miradas, ronda contada y con una mirada en el aire), ganar, perder, el pleno y la última ronda por delegación, la reconexión de Unity, la sesión perdida, el abandono y el coste en el registro.
- `server/tests/games/test_busqueda_banco.py`: el banco de la app, lo bien y mal formado, el mínimo de entradas, que nada hable de personas, `clean_what` y que nada de lo que lee GPT-Live nombre el stack ni lleve más de 1200 caracteres.
- `server/tests/games/test_busqueda_demo.py`: la secuencia del orquestador falso manda lo mismo que el juego.
- Ningún test llama a la API real ni usa la cámara de nadie.
- Capturas 9:16 de cada estado con el orquestador falso (`server/sonia/games/busqueda/demo.py`; la vista en vivo sale de una foto pública si se da `BUSQUEDA_DEMO_FOTO`, o de una imagen sintética):

  ```bash
  BUSQUEDA_DEMO_FOTO=<foto pública> SONIA_UNITY_LOCKS=$SP/unity-locks \
    scripts/juegos_capturas.sh --juego busqueda --puerto 8797 --salida <carpeta>
  ```

## Pendiente

- Probarla con la API real: que GPT-Live delegue `start_game` a la primera, que anuncie el objeto antes de la salida, que delegue `busqueda_check` con el barullo y que no se invente que lo ve. Y medir el coste de las fotos y lo que tarda cada mirada con el modelo de verdad.
- Que Jean revise el banco de objetos.
