# Piedra, papel o tijera (`piedra_papel_tijera`)

> Plan: `docs/plan-juegos.md`, sección 5.4. Contrato y cómo se hace un juego: `docs/juegos.md`.
> Código: `server/sonia/games/ppt/` (orquestador) y `unity/Assets/Scripts/Sonia/Games/Ppt/` (pantalla).

## Qué es

Uno contra Sonnia, de uno en uno (decisión de Jean). La cámara del stand lee la mano del jugador y
Sonnia saca la suya con el avatar. Se juega al mejor de `GAME_PPT_ROUNDS` (3: gana quien llega a 2),
con el marcador «Sonnia 1 - 2 Tú» en pantalla y la vista en vivo encima de Sonnia para que el
jugador sepa dónde poner la mano.

## Cómo se juega

1. El visitante pide jugar y GPT-Live delega `start_game(piedra_papel_tijera)`: es la única
   delegación de toda la partida. Se encienden la cámara, las poses y la vista en vivo, y Sonia
   explica en una o dos frases dónde ponerse: a un paso, con la mano delante del pecho, y que la
   enseñe en el «¡ya!».
2. Cada tirada va sola:
   1. Se espera a que haya un jugador delante y a que nadie hable. Sin nadie 5 s, el rótulo
      «¡Ponte delante de la cámara!» y Sonia lo pide; sin nadie 30 s, se deja para otro momento.
   2. El orquestador elige la jugada de Sonnia **antes** de mirar.
   3. Sonnia sube el puño (`ready`) y, 0,8 s después, suena la frase grabada «¡Piedra, papel o
      tijera… ya!» (`countdown` justo antes). Unity agita el puño tres veces al ritmo de la frase y
      en el «ya» abre la mano con su jugada (`go`).
   4. El orquestador lee la mano del jugador desde 0,25 s después del «ya» (lo que se tarda en
      reaccionar) durante `GAME_PPT_READ_SECONDS` y se queda con la lectura estable.
   5. Las dos jugadas en grande y el marcador (`result`), y Sonia reacciona en una frase.
      - Empate: se repite la ronda, sin contar.
      - Sin lectura: «¡no te vi la mano!» (o «no te la entendí») y se repite la ronda
        (`GAME_PPT_RETRIES`, una vez). Si tampoco, la ronda no cuenta para nadie. Dos rondas
        seguidas sin ver la mano: Sonia se disculpa y la partida se cancela.
3. Al llegar uno a la mitad más una de las rondas, el resultado final (`final`) y `finish`. Si gana
   el visitante, Sonia le manda con el equipo del stand (`TRIVIA_WIN_CONTACT`, Brian o Mariel); si
   gana ella, le anima a pedir la revancha. Hay un tope de 4 tiradas por ronda (empates y rondas
   nulas incluidos): si se llega, gana quien vaya delante o queda en empate.
4. Si el visitante quiere parar, GPT-Live delega `stop_game`.

## Quién hace qué

| Quién | Qué hace |
|---|---|
| GPT-Live | Explica el juego al empezar, reacciona a cada resultado que le pasa el juego y delega `start_game` y `stop_game`. No elige ni ve jugadas: las reglas le prohíben decir la cuenta o inventarse resultados. |
| Backend Responses | Ejecuta `start_game` y `stop_game` y le pasa a Sonia el guion de arranque. |
| Orquestador | Lleva la partida entera (`PptGame`): elige la jugada de Sonnia, lanza la frase grabada, mide dónde cae el «ya», elige al jugador, lee su mano, decide la tirada, lleva el marcador y le pasa a GPT-Live cada resultado por `speak`. |
| Unity | La tarjeta con el marcador y las jugadas en grande, la vista en vivo y la mano de Sonnia (`PptController` y `SoniaHandPoser`). |

## Acciones de GPT-Live

| Acción | Cuándo la usa | Qué devuelve |
|---|---|---|
| `start_game` (`juego`: `piedra_papel_tijera`) | El visitante quiere jugar. | El guion de arranque: explicar dónde ponerse y callar. Las reglas le llegan por `instruct`. |
| `stop_game` | Ya no quiere seguir. | El juego se cancela. |

No hay jugadas delegadas: la jugada del visitante no se entiende por voz, la lee la cámara. Así cada
ronda no depende de que GPT-Live delegue a tiempo. Lo que tiene que decir le llega por `speak`
(`commentary`): «sacaste tijera y el jugador piedra: gana el jugador; marcador...».

## Pantalla

Sus eventos están en `docs/protocolo.md` («Eventos de cada juego», `piedra_papel_tijera`). En
resumen: `start`, `round` (empieza o se repite una tirada), `ready` (Sonnia sube el puño),
`countdown` (empieza la frase: `go_s` dice cuántos segundos después del principio del audio cae el
«ya»), `go` (el «ya»), `abort` (la cuenta no llegó a sonar), `result`, `final` y `hint`. Fijos
(se repiten si Unity se reconecta): `start`, `round`, `result` y `final`; lo demás es pasajero.

**Sincronía de la cuenta.** Lo que más se nota es que Sonnia saque la mano a la vez que dice «ya»:
si la saca tarde, parece que hace trampa. Por eso:

- El orquestador mide la frase grabada una vez por partida (`phrase_go_seconds`: la caché de voces
  con la voz y la tasa de ahora y `logic.ya_onset`, que busca el principio de la última palabra en
  la envolvente de la voz) y manda `go_s` en `countdown`.
- Unity agita el puño tres veces y saca la mano siguiendo el audio de la frase
  (`AudioStreamPlayer.CurrentUtteranceId` y `CurrentUtteranceTime`) y, si no puede, desde que llegó
  `countdown` más 0,12 s.
- Si la frase no está grabada, la dice GPT-Live en directo: entonces `go_s` va a `null`, el «ya»
  sale de la transcripción de Sonia (`logic.says_ya`, que sigue lo que dice ella, nunca al
  visitante) o, como mucho, a los 5 s, y Unity saca la mano con `go`.

## Cámara

Todo en el equipo del stand, en hilos y sin guardar nada (`docs/juegos-vision.md`):

- **Quién juega** (`logic.pick_player`): la persona más cercana y centrada, la de cuerpo más grande
  (área de su caja, rebajada hasta la mitad si está en el borde). Para no saltar entre dos personas
  parecidas, se sigue con la de antes mientras su caja solape y no haya otra claramente más grande;
  si otra se pone delante, pasa a jugar ella y la partida sigue. No se reconoce a nadie.
- **Qué mano cuenta** (`logic.read_sample`): la levantada delante del cuerpo. Una mano que cuelga
  por debajo de las caderas no se está enseñando (una mano relajada con los dedos estirados se lee
  como papel). De las levantadas, la más alta; si hay dos a la misma altura con jugadas distintas,
  esa muestra no vale.
- **Lectura estable** (`logic.settle`): durante la lectura se toma una muestra cada 0,08 s (poses
  sobre ese mismo frame con `poses.detect` y las manos con `hands.read`, para que persona y mano
  sean del mismo instante). Vale el último tramo de dos lecturas iguales seguidas sin contar huecos:
  el puño que se agita antes del «ya» se lee piedra y manda lo que viene después. Si al acabar no
  hay tramo estable, o la última lectura lo contradice, se alarga hasta 0,6 s más.
- **Vista en vivo** (`overlay.py`, con numpy): en espejo, con esquinas amarillas alrededor del
  jugador (los demás no se marcan) y, durante la lectura y el resultado, una caja alrededor de la
  mano que juega: verde si se entendió, roja si no.

## Bancos

No tiene: las jugadas son tres y las frases las dice GPT-Live con sus palabras.

| Banco | Archivo | Entradas | Mínimo |
|---|---|---|---|
| — | — | — | — |

## Frases grabadas

- «¡Piedra, papel o tijera… ya!» (`PHRASE`, con los puntos suspensivos de verdad): se graba con
  «Preparar voces» y la grabación automática (`phrases()`). Grabada, suena al momento, sin gastar y
  con el micro callado mientras suena; sin grabar, se le pide a GPT-Live que la diga tal cual.

## Ajustes (`GAME_PPT_*`)

| Ajuste | Por defecto | Qué hace |
|---|---|---|
| `ENABLED` | `true` | Encendido. |
| `ROUNDS` | 3 | Al mejor de estas rondas (gana quien llega a `ROUNDS // 2 + 1`). |
| `READ_SECONDS` | 0.8 | Lectura de la mano tras el «ya» (se alarga hasta 0,6 s si no es estable). |
| `FPS` | 8 | Detecciones de poses por segundo mientras se juega (para seguir al jugador). |
| `RETRIES` | 1 | Veces que se repite una ronda si no se ve la mano. |
| `ABANDON_SECONDS` | 0 | 0: `GAMES_ABANDON_SECONDS`. Mientras se ve al jugador, la partida no se abandona. |

Tiempos fijos en `game.py`: `READY_LEAD_S` (0,8), `AUDIO_LAG_S` (0,12), `REACTION_S` (0,25),
`GO_TIMEOUT_S` (5), `HINT_AFTER_S` (5) y `NO_PLAYER_CANCEL_S` (30).

## Unity

`PptController` (sobre `GameControllerBase` y `GameHud`) y `SoniaHandPoser`, en `Games/Ppt/`.

**Pantalla.** La vista en vivo arriba (la manda el orquestador, con el jugador resaltado) y, debajo,
la tarjeta común:

- En la cabecera, «AL MEJOR DE 3 · RONDA 2» (y «· OTRA VEZ» si se repite).
- El marcador «SONNIA 1 – 2 TÚ», que late al sumar.
- Una fila con las dos jugadas en grande: la de Sonnia a la izquierda y la del visitante a la
  derecha, con «contra» en medio («PIEDRA contra TIJERA»). La ganadora sale en verde con brillo y
  la perdedora apagada; en un empate, las dos en ámbar; sin lectura, «¿?» en rojo.
- Durante la cuenta esa fila enseña «PIEDRA», «PAPEL», «TIJERA» y «¡YA!» al ritmo de los golpes del
  puño.
- El rótulo de la tarjeta dice el resultado de la ronda («¡GANAS TÚ!», «¡GANA SONNIA!»,
  «¡EMPATE!», «¡NO TE VI LA MANO!» o «¡NO TE ENTENDÍ LA MANO!»), con confeti si gana el visitante, y
  la cara de Sonnia reacciona (alegría si gana ella, sorpresa si pierde).
- El final, con `Hud.ShowResult` 1,5 s después del último resultado: «¡GANASTE!» con «Pasa a ver a
  Brian o Mariel del equipo», «¡GANA SONNIA!» o «¡EMPATE!», y el marcador.

**La mano de Sonnia (`SoniaHandPoser`).**

- El brazo derecho delante del pecho con IK de dos huesos (como `TriviaHat`), la palma hacia el
  público y los dedos hacia arriba: es como mejor se lee la jugada en la pantalla vertical (con los
  dedos hacia la cámara, el papel se vería de canto). La cara queda libre.
- `ready` sube el puño. `countdown` lo agita: baja en cada tiempo de la frase (tres golpes, cada uno
  rápido hacia abajo y más lento hacia arriba, inclinando el puño como un martillo) y en el cuarto,
  el «¡ya!», la mano se abre en su forma en 0,13 s y empuja un poco hacia el público.
- El «¡ya!» sale del audio de la frase que está sonando (`AudioStreamPlayer.GetPlaybackPosition`:
  la primera voz nueva tras `countdown`, menos el adelanto del lip-sync), así que la mano se abre a
  la vez que la voz. Sin audio, cuenta desde que llega el mensaje más 0,12 s; sin `go_s`, agita en
  bucle hasta `go`. Si llega `go` y en 0,4 s no se ha abierto, se abre. Al cambiar de reloj se funde
  la diferencia para que el puño no salte.
- Tras el resultado la mano se queda enseñando su jugada 2,4 s y baja sola con un fundido (y como
  mucho a los 9 s con el brazo arriba, por si se pierde un mensaje). Al cerrarse la pantalla, baja.
- Los dedos van con los músculos del humanoide: al enganchar el avatar se calcula con
  `HumanPoseHandler` la rotación local de cada falange de la mano derecha para cada forma, y cada
  fotograma solo se mezclan esas rotaciones con las de la animación (no se toca el resto del
  cuerpo). Con los límites de Unity el puño se queda en garra, así que los dedos cerrados se doblan
  1,9 veces lo del músculo y el pulgar 1,4, cruzado por delante de los dedos como en ✊. Los valores
  están en el inspector de `SoniaHandPoser` y salieron de una galería de variantes renderizadas con
  el avatar de Sonnia.
- Corre en `LateUpdate` con orden 12650, después de la cara, los ojos y el gorro de la trivia; si el
  avatar cambia, se vuelve a enganchar.
- **Plan B**: `PptController.SoniaHandEnabled = false` quita la mano y la jugada de Sonnia sale
  solo en la tarjeta (por si en algún avatar los dedos no quedaran bien).

**Cómo se validó la mano** (10 de octubre de 2026, Unity en batch sobre un clon, con el avatar de
Genies de Sonnia y su camiseta de staff): un laboratorio de paso fijo (30 fps) subió el puño, contó y
enseñó cada forma con capturas de cerca de cada dos fotogramas, de lado y desde arriba, además del
plano 9:16. Así salieron dos fallos que una captura suelta no habría enseñado: durante la cuenta los
dedos ya tenían la forma final (se veía el papel antes del «ya») y el puño se quedaba en garra. Los
músculos del puño y de la tijera salieron de una galería de 16 variantes (pulgar y cierre).

## Pruebas y capturas

- `server/tests/games/test_ppt.py`, sin red ni cámara:
  - quién juega (la más grande y centrada, las dudosas y lejanas fuera, sin saltos entre dos
    parecidas, otra persona delante), qué mano cuenta (la levantada, dos manos, sin caderas a la
    vista), la lectura estable (estable, cambiante, sin mano, cambio tardío, huecos), quién gana
    (las nueve combinaciones), el «ya» de la transcripción y el de la frase grabada (con voz
    sintética y con la caché de voces), y la vista en vivo (con y sin espejo);
  - partidas enteras con `FakeGameHost`: ganar, perder, empates, sin mano (repetir y ronda nula),
    mano que no se entiende, lectura cambiante, dos rondas sin mano, la cuenta que no suena, el
    «ya» medido, el de la transcripción y el del tope, sin nadie delante, otra persona delante,
    parar a media partida, sin cámara, sin vista en vivo, las reglas (≤ 1200 caracteres y sin
    marcas del stack) y la frase declarada;
  - de punta a punta con `GameManager`: `start_game`, la partida, `end` con su resultado,
    `stop_game` y lo que vuelve a pintar una Unity que se reconecta.
- Orquestador falso: `server/sonia/games/ppt/demo.py`, con una captura por estado
  (`ppt-1-empezar`, `ppt-2-cuenta`, `ppt-3-ya`, `ppt-4-acierto`, `ppt-5-fallo`, `ppt-6-sin-mano`,
  `ppt-7-final`):

  ```bash
  cd server && uv run --no-sync python ../scripts/juegos_demo.py --juego piedra_papel_tijera --puerto 8795
  ```

## Pendiente

- Probar la lectura de manos con la cámara del stand y gente de verdad (los tiempos de la lectura y
  de la reacción salen de lo razonable, no de medidas).
- Capturas 9:16 de cada estado y la mano de Sonnia validada por fotogramas.
- Una partida con la API real (con permiso de Jean) para ver que GPT-Live no dice la cuenta por su
  cuenta ni se inventa resultados.
