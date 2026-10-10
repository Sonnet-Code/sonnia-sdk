# Búsqueda relámpago (`busqueda`)

Plan: `docs/plan-juegos.md`, sección 5.6. Contrato y cómo se hace un juego: `docs/juegos.md`. Visión (la cámara, la vista en vivo y el juez): `docs/juegos-vision.md`. Pantalla en Unity: `docs/juegos-unity.md`.

## Qué es

«¡El primero que me enseñe algo azul!». Sonnia pide un objeto, el grupo corre a enseñarlo a la cámara y el stand comprueba si lo trae. Se juegan `GAME_BUSQUEDA_ROUNDS` rondas (3) de `GAME_BUSQUEDA_ROUND_SECONDS` (25 s). La imagen de la cámara sale en la franja alta, encima de Sonnia, para que sepan dónde enseñar el objeto («En vivo · no se graba»).

Manda fotos fuera del equipo: una foto reducida cada `GAME_BUSQUEDA_CHECK_SECONDS` (2,5 s) al juez, con una pregunta cerrada y un tope de `GAME_BUSQUEDA_MAX_CHECKS` (10) por ronda. El juez es Gemini con `GAMES_JUDGE=gemini` (el de por defecto desde el 10 de octubre de 2026) y el modelo de visión de Sonia (`LLM_*`) con `GAMES_JUDGE=local` o sin `GEMINI_API_KEY` (`docs/juegos-vision.md`, «Juez de Gemini»). Nunca se guarda una imagen ni se describe a nadie: el juez solo dice si se ve el objeto y cuál es.

Necesita (`needs`): la cámara USB, la vista en vivo en la Unity (`camera_preview`) y un juez (Gemini o el modelo de visión).

## Cómo se juega

1. **Empezar.** GPT-Live delega `start_game(busqueda)` (o el equipo pulsa «Búsqueda relámpago» en el panel). El orquestador reserva la cámara, enciende la vista en vivo (sin dibujo encima), manda `start` y la ronda 1 lista (`round`), pasa las reglas por `instruct` (menos de 1200 caracteres) y devuelve el guion: explicar el juego en una frase y anunciar el objeto.
2. **Ronda lista.** La pantalla enseña el objeto, el color y el tiempo entero parado («PREPÁRENSE…»). El orquestador sigue la transcripción de Sonia (`on_assistant_text`, solo para sincronizar la pantalla): cuando dice el objeto y calla un segundo, suena el **«¡Ya!»** grabado y arranca el contador (`go`). Si no la oye decirlo, da la salida al tope de espera (14 s la primera ronda, 9 s las demás).
3. **Miradas.** Cada 2,5 s una foto al juez con la pregunta del objeto (`VisionJudge.ask`). Las miradas **no se solapan**: si una tarda, la siguiente espera a que acabe y sale enseguida. Cada mirada manda a la pantalla un `checking` (el barrido de «mirando») y, solo mientras la foto está en juicio, la pastilla de espera «Mirando lo que enseñas…» (`busy`, tipo `judge`), que se apaga en cuanto el juez contesta, falla o se acaba el plazo. Tope de 10 por ronda, contando las de `busqueda_check`; si el tope va justo (muchas delegaciones o un `MAX_CHECKS` bajo), la siguiente mirada se retrasa para repartir las que quedan por lo que queda de ronda, así el final también se mira.
4. **¡Encontrado!** En cuanto el modelo ve el objeto: `found` (¡Encontrado!, confeti y lo que vio la cámara), suena el **«¡Lo veo!»** grabado y Sonia lo celebra en una frase **describiendo el objeto, nunca a la persona** (ver «Lo que dice el modelo»).
5. **Se acaba el tiempo.** `timeout` (¡Tiempo!), suena el **«¡Tiempo!»** grabado y Sonia lo dice con humor, sin culpar a nadie.
6. **Siguiente.** Cuando Sonia termina de contar el resultado, sale la ronda siguiente (otro `round` y otro anuncio). Tras la última ronda, `finish`: gana si encuentran la mitad o más (2 de 3) y se queda en pantalla hasta que Sonia termina de contarlo; la vista en vivo se retira 3 s después de la última ronda. A quien gana se le manda con `TRIVIA_WIN_CONTACT` (Brian o Mariel); Sonia no sabe de premios.

Nada de lo que oye el visitante se interpreta. Si alguien grita «¡aquí!», GPT-Live delega `busqueda_check` y se mira al momento (dentro del tope), pero el juego no depende de eso: las miradas del reloj ya lo verían.

### Cuando algo falla

- **El juez no contesta** (sin foto, plazo, error): esa mirada cuenta contra el tope pero no pasa nada. Con Gemini, si falla (error, 429, plazo de 4 s o JSON roto), la misma pregunta va al modelo de visión de Sonia (`LLM_*`, luna) con una foto nueva y lo que queda de los 8 s (`FallbackJudge`); sin foto o pasado el tope no se repite, y el tope cuenta preguntas, no llamadas. Si en una ronda no contesta **ninguna**, Sonia no dice «nadie lo enseñó» sino que la cámara no contestó (`timeout` con `silent: true`). Con dos rondas seguidas así, se cancela el juego con una disculpa corta.
- **Una mirada tarda más que la ronda:** la foto que va en el aire al acabar el tiempo aún cuenta durante 3 s; si no llega, la ronda se pierde y la respuesta tardía se ignora.
- **Se cae GPT-Live, cambia el modo o se reconecta Unity:** como dice el contrato (`docs/juegos.md`). Cada mensaje de ronda (`round`, `go`, `found`, `timeout`) lleva el estado completo, así que el último que se repite tras `hello` repinta toda la pantalla.
- **Abandono:** `GAMES_ABANDON_SECONDS` (60 s) sin voz ni actividad (que el modelo vea el objeto cuenta como actividad). Se cancela y suelta la cámara.

## Quién hace qué

| Quién | Qué hace |
|---|---|
| GPT-Live | Anuncia cada ronda con ganas, celebra o lamenta el resultado en una frase y calla durante la ronda. Si oye «¡aquí!» o «¡ya lo tengo!», delega `busqueda_check` antes de decir nada. No ve nada: no dice que lo ve hasta que el sistema se lo cuenta. No usa `look` en este juego. |
| Backend Responses | Llama a `start_game`, `busqueda_check` y `stop_game`, y pasa entero el guion `PARA SONIA:`. |
| Orquestador | Elige los objetos, lleva las rondas y el contador, da la salida, pregunta a la cámara cada 2,5 s con tope, no deja que se solapen las miradas, filtra lo que dice el modelo, registra las fotos y cuenta el resultado. |
| Juez (Gemini o el modelo de visión) | Mira cada foto y contesta si se ve el objeto y cuál es, en JSON (`JUDGE_PROMPT`), sin describir a nadie. |
| Unity | Muestra la vista en vivo, la tarjeta con el objeto y el contador, el barrido de «mirando», la pastilla de espera, «¡Encontrado!» y el final. No manda nada al orquestador. |

## Acciones de GPT-Live

| Acción | Cuándo la usa | Qué devuelve |
|---|---|---|
| `start_game` (`juego`: `busqueda`) | El visitante quiere jugar. | El guion de arranque: explicar el juego en una frase y anunciar la ronda 1 (con el objeto). |
| `busqueda_check` (sin argumentos) | Alguien grita «¡aquí!» o «¡ya lo tengo!» o le enseña algo. | Mira ya la cámara. Si se ve: el guion para celebrarlo (o el final, si era la última ronda). Si no: que lo acerque, bien a la vista y quieto. Antes de la salida: que espere al «¡Ya!». Ronda ya contada: que no repita nada. Sin miradas: que solo queda esperar. |
| `stop_game` | Ya no quiere seguir. | El juego se cancela. |

`busqueda_check` nunca falla: fuera de turno devuelve un guion que reconduce. Si hay una mirada del reloj en el aire, espera a que acabe (hasta 4 s); si esa mirada ve el objeto, la delegación ya no repite nada.

## Estado para el panel

`snapshot()` lleva `summary` (una línea para la tarjeta «Juegos»: «Ronda 2 de 3: algo azul · 1 encontrada»; vacía sin partida), `phase` (`ready`, `running`, `between`, `done`), `round`, `rounds`, `object`, `objects` (los de la partida), `found`, `results` (`found`, `timeout` o `silent` por ronda), `seconds_left`, `checks` (fotos de la ronda) y `photos` (de la partida).

## Control a mano (panel)

Por si falla la voz o la cámara, con la ronda en marcha el equipo tiene en el panel (`panel_controls`, `panel_control`; «Reiniciar» y «Terminar» los pone el manager para todos):

- **«¡Lo encontró!»**: gana la ronda como un `busqueda_check` que lo ve (pantalla, «¡Lo veo!» y el guion de siempre para Sonia, que se le pasa en cuanto calla).
- **«Saltar objeto»**: cierra la ronda sin encontrarlo («¡Tiempo!» y un guion propio, `SKIP_TEXT`), y nunca cuenta como ronda en la que la cámara no contestó.

Antes de la salida o con la ronda ya contada no hay controles y dan `GameError`. Tests en `server/tests/games/test_controles_camara.py`.

## Pantalla

Sus eventos están en `docs/protocolo.md` («Eventos de cada juego», `busqueda`). Unity (`Games/Busqueda/BusquedaController.cs`, sobre `GameHud`):

- **Vista en vivo** (la pone `CameraPreviewPanel`): arriba, en 16:9, con «En vivo · no se graba». Encima, en su `Overlay`: el barrido de «mirando» (una línea con halo que baja, esquinas de enfoque y «MIRANDO…») en cada `checking`, y un marco verde al encontrar o rojo al acabarse el tiempo.
- **Tarjeta** (debajo de la vista, la coloca `GameHud`): título de colores, «RONDA 1 DE 3» y un punto por ronda (blanco la actual, verde encontrada, rojo perdida). Dentro: un cuadro con el color del objeto y un «?», el objeto en grande y el contador circular a la derecha. Al encontrarlo, el cuadro pasa a un visto, sale «¡Encontrado!» y lo que vio la cámara; al acabar el tiempo, una cruz y «¡Tiempo!».
- **Final:** la tarjeta de resultado común (`¡PLENO!` con 3 de 3, `¡BUEN OJO!` con la mitad o más, `¡CASI!` si no) con el marcador «2 de 3».
- **Sonnia:** `actions-highFive_actionSuccess` y alegría al encontrarlo, `actions-highFive_actionFail` y pena al acabarse el tiempo, y los clips de ganar o perder de la trivia al final.
- «Sonnia» en pantalla; lo que llega del orquestador pasa por `GameUi.Plain`.

## Cámara

- `host.stream.acquire` y `host.preview.start` (sin overlay) al empezar; el manager los suelta al terminar aunque se olvide. La vista en vivo se retira 3 s después de la última ronda, para que no acompañe a la tarjeta final.
- **Una foto por mirada**, reducida (640 px de ancho) y fresca, al juez, con una pregunta cerrada. Nunca a GPT-Live, nunca a disco. El juez (`ModelJudge`, `docs/juegos-vision.md`) lleva su propio tope por ronda (`start_round(max_checks)`, que el juego llama al abrir cada ronda) además del contador del juego.
- **Qué juez:** lo monta `build_game_vision` según `GAMES_JUDGE`. Con `gemini` (por defecto), `ModelJudge` con un cliente de Gemini (`gemini-3.1-flash-lite`, el del director de gestos, con `GEMINI_API_KEY`); con `local` o sin esa clave, `ModelJudge` con el modelo de visión de Sonia (`LLM_*`), como antes. El prompt (`JUDGE_PROMPT`) y el tope son los mismos; el plazo de Gemini es `GAMES_JUDGE_TIMEOUT_SECONDS` (4 s) y, si falla, la misma pregunta va a luna con una foto nueva y lo que queda de los 8 s (`FallbackJudge`, `sonia/vision/judge.py`). Es por si la clave de Gemini tiene topes por minuto o por día, que no sabemos, y los gestos ya la usan todo el día. En el banco de pruebas del 10 de octubre de 2026 Gemini acertó 25 de 25 fotos de la búsqueda (el modelo de visión, 24 de 25), con 1,25 s de mediana y unos 1.350 tokens de entrada por foto.
- **Qué le pregunta:** la del objeto (`objetos.md`), cerrada y sin hablar de personas; sin pregunta propia, «En la foto, ¿se ve <objeto> bien a la vista, en una mano o frente a la cámara? No cuentan la ropa ni el fondo.». El prompt del juez ya prohíbe describir personas y dice que lo que alguien lleva puesto o colgado (la ropa, las gafas, el pelo, las gorras, el gafete o la credencial con su cordón) no cuenta mientras siga puesto o colgando, y sí si lo sostiene con la mano y lo enseña a la cámara (10 de octubre de 2026: con «algo azul», Gemini daba por buenos los cordones azules de las acreditaciones, que en el stand lleva todo el mundo. Con el cambio, los cordones colgados ya no cuentan, ni para «algo azul» ni para «la credencial del DevFest», cuya pregunta pide ahora enseñarla con la mano; 24 de 25 en el banco de pruebas, el fallo es una foto dudosa de globos con luz morada).
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

**Hay que grabarlas** («Preparar voces» en el panel, o la grabación automática) antes de jugar: sin la frase grabada, cada una sale por `commentary` y GPT-Live la dice con ~1,5 s de retraso (y a veces la siguiente ronda se adelanta un poco a su reacción). Con las voces preparadas, suenan al instante y sin gastar.

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
- `server/tests/games/test_busqueda_motor.py`: una ronda por voz dentro del motor de verdad (un GPT-Live falso, un `Hub` y una Unity de mentira): `start_game` y `busqueda_check` delegados por el backend, la salida cuando Sonia termina de decir el objeto (su transcripción y su audio), la celebración y el anuncio de la ronda siguiente por `commentary` y `stop_game`.
- `server/tests/games/test_busqueda_azar.py`: 40 partidas al azar con semilla contra el `GameManager` (un juez y una Sonia caprichosos, delegaciones a destiempo, sesión caída): nunca cuelgan, nunca hay dos miradas a la vez, cada ronda se cuenta una vez, no sale ningún error al registro y la cámara y la pantalla acaban sueltas con un solo `end`.
- `server/tests/games/test_busqueda_juez.py`: el juego con el juez de verdad (`ModelJudge`) sobre un servidor HTTP falso (`httpx.MockTransport`, nunca el modelo de verdad): la cuenta de fotos y su tope por ronda, la pregunta que llega al modelo, lo que vuelve en JSON por `clean_what`, el servidor caído y la cámara sin foto.
- `server/tests/games/test_busqueda_demo.py`: la secuencia del orquestador falso manda lo mismo que el juego.
- `server/tests/games/test_busqueda_aviso.py`: la pastilla de espera (`busy`, `judge`) se enciende solo mientras hay una foto en juicio y se apaga al contestar, sin respuesta o si el juez falla; si el aviso falla, la mirada sigue.
- Ningún test llama a la API real ni usa la cámara de nadie.
- Capturas 9:16 de cada estado con el orquestador falso (`server/sonia/games/busqueda/demo.py`; la vista en vivo sale de una foto pública si se da `BUSQUEDA_DEMO_FOTO`, o de una imagen sintética):

  ```bash
  BUSQUEDA_DEMO_FOTO=<foto pública> SONIA_UNITY_LOCKS=$SP/unity-locks \
    scripts/juegos_capturas.sh --juego busqueda --puerto 8797 --salida <carpeta>
  ```

  **Revisadas el 10 de octubre de 2026** (13 capturas, con una foto pública de Wikimedia Commons como vista en vivo): la ronda lista, el contador, la cámara mirando (barrido, esquinas y «MIRANDO…»), ¡encontrado! con confeti y después, una ronda sin color (cuadro neutro), ¡tiempo!, un nombre largo en dos líneas, ¡encontrado! con un objeto largo, el final con 2 de 3 (¡BUEN OJO!), el tiempo con la cámara sin contestar («NO PUDE MIRAR BIEN»), el final con 0 de 3 (¡CASI!) y la pantalla repintada tras reconectar solo con el `start` y un `go` de la ronda 2 (los puntos de las rondas anteriores se reconstruyen). En todas, la franja alta acaba en 1108 px y la coronilla de Sonnia queda hacia 1200 px: no le tapa la cara. Con el resultado final, la vista en vivo se aparta y la tarjeta sube. No se guardaron las imágenes (`capturas.txt` de cada pasada, en el scratchpad de la sesión).

## Pendiente

- Probarla con la API real: que GPT-Live delegue `start_game` a la primera, que anuncie el objeto antes de la salida, que delegue `busqueda_check` con el barullo y que no se invente que lo ve. Y medir el coste de las fotos y lo que tarda cada mirada con Gemini y la cámara del stand (en el banco de pruebas, con fotos públicas, 1,25 s de mediana).
- Que Jean revise el banco de objetos.
