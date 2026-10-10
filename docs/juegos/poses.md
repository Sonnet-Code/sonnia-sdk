# Simón dice con poses (`poses`)

> Plan: `docs/plan-juegos.md`, sección 5.2. Contrato y cómo se hace un juego: `docs/juegos.md`.
> Visión: `docs/juegos-vision.md`. Unity: `docs/juegos-unity.md`.

## Qué es

Sonnia da órdenes con nombre de meme dev y la pose dicha en claro: «¡Simón dice: pasaron todos los tests, brazos arriba!». La cámara del stand cuenta cuántos hacen la pose y la imagen en vivo sale encima de Sonnia, en espejo, con los esqueletos de quienes juegan. Algunas rondas son trampa: la orden sale sin «Simón dice» y quien hace la pose cae. El resultado es del grupo («¡7 de 9!», «¡cayeron 4!»): nunca se elimina a nadie.

## Cómo se juega

1. **Empezar.** El visitante pide jugar y GPT-Live delega `start_game(poses)` (o el equipo pulsa el botón del panel). El orquestador enciende el detector de poses y la vista en vivo, le pasa a GPT-Live las reglas (`instruct`) y le devuelve el guion de arranque: Sonia explica el juego en dos o tres frases (a unos dos metros, la pose solo con «Simón dice», cuántas rondas, nadie queda eliminado).
2. **Colocación.** Mientras Sonia explica, el orquestador mira a cuántos ve y si se les ven los brazos. Si alguien está demasiado cerca (hombros muy anchos en la imagen, hombros sin ninguna muñeca, la cabeza pegada al borde de arriba o solo la cara), Sonia le pide un paso atrás, hasta unos 2 m (como mucho una vez cada 12 s); si no ve a nadie en 4 s, pide que se pongan delante (una vez). La primera ronda empieza cuando Sonia ha terminado de explicar y hay alguien colocado durante 0,8 s, o como mucho a los 20 s (40 s si Sonia no calla).
3. **Rondas** (`GAME_POSES_ROUNDS`, 6). `GAME_POSES_TRICKS` (1) son trampa, nunca la primera. Las poses salen barajadas del banco y, si hay menos que rondas, se repiten sin salir la misma dos veces seguidas. En cada ronda:
   1. Espera a que Sonia calle (y, hasta 4 s más, a que nadie hable: en un stand con barullo la sesión casi nunca está en calma).
   2. **Demostración**: Unity saca el pictograma de la pose y Sonnia la hace y la sostiene (evento `round`).
   3. **Orden** a los 1,4 s (evento `command`): suena como frase grabada (`say_fixed`), exacta en el tiempo y en si dice «Simón dice». Si no está grabada, GPT-Live la dice tal cual por `commentary`. Si Sonia estaba hablando, se espera a que calle y se reintenta (tres veces).
   4. **Ventana** (evento `window`): cuando termina de sonar la orden se abre una ventana de `GAME_POSES_WINDOW_SECONDS` (1,8 s). De todos sus frames cuenta el mejor recuento: cuántos hacen la pose y cuántos juegan.
   5. **Resultado** (evento `result`): «7 de 9» (o, en la trampa, «¡cayeron 4!»), y a GPT-Live le llegan los números por `speak` para que reaccione en una frase muy corta. Se espera a que termine de reaccionar.
4. **Final** (evento `final`): el total del grupo («hicieron bien 38 de 50 jugadas»: la pose con «Simón dice» y quedarse quieto en las trampas) y cuántos cayeron en las trampas. Sonia lo celebra y, si alguien pregunta por premios, le manda con `TRIVIA_WIN_CONTACT` (Brian o Mariel) sin prometer nada. La partida termina con `win` y el resultado se queda en pantalla hasta que Sonia termina de contarlo.
5. **Sin nadie.** Dos rondas seguidas sin ver a nadie y el juego se acaba (`cancel`) con una frase. Si nadie habla ni hay nadie delante durante `GAMES_ABANDON_SECONDS` (60 s), el manager la da por abandonada; mientras la cámara vea gente jugando, el juego avisa de que sigue (`touch`) aunque nadie hable.

Una partida de seis rondas dura unos 80 s.

## Quién hace qué

| Quién | Qué hace |
|---|---|
| GPT-Live | Delega `start_game(poses)` en cuanto el visitante quiere jugar. Explica el juego con el guion de arranque, reacciona en una frase a cada resultado que le llega, pide el paso atrás cuando se lo dicen y celebra el final. No dice las órdenes ni se inventa números. Si quieren dejar de jugar, delega `stop_game`. |
| Backend Responses | Llama a `start_game` y `stop_game`. Este juego no tiene jugadas propias: todo lo demás lo lleva el orquestador con la cámara. |
| Orquestador | Elige las rondas y las trampas, manda la pantalla, hace sonar las órdenes, cuenta con la cámara en cada ventana (`rules.py`), dibuja los esqueletos en la vista en vivo (`overlay.py`), le pasa los resultados a GPT-Live y lleva la colocación. Código en `server/sonia/games/poses/`. |
| Unity | Pinta la vista en vivo grande, el pictograma, la orden, el contador de la ventana, el resultado y el final, y hace que Sonnia demuestre cada pose (`unity/Assets/Scripts/Sonia/Games/Poses/`). |

## Acciones de GPT-Live

| Acción | Cuándo la usa | Qué devuelve |
|---|---|---|
| `start_game` (`juego`: `poses`) | El visitante quiere jugar. | El guion de arranque: explicar el juego en dos o tres frases y callar (las órdenes empiezan solas). Con la partida ya en marcha, por qué ronda va. Sin cámara, sin detector o con la pantalla de una versión anterior, por qué no se puede y qué otros juegos hay. |
| `stop_game` | Ya no quiere seguir. | El juego se cancela. |

No hay jugadas delegadas: nada de lo que dice el visitante cambia el juego, así que no hay nada que entender ni que delegar (menos herramientas para GPT-Live). Lo que tiene que saber va por `instruct` (las reglas, menos de 1200 caracteres) y lo que tiene que decir ya, por `speak` (la colocación, cada resultado y el final).

## Pantalla

Sus eventos están en `docs/protocolo.md` («Eventos de cada juego», `poses`). Todos son fijos y llevan el estado completo, así que una Unity que se reconecta lo pinta todo con el último.

- **Vista en vivo** grande, justo debajo de la cabecera de la tarjeta («SIMÓN DICE CON POSES» y «RONDA 2 DE 6»), con «En vivo · no se graba». La cámara pasa a un plano de panel más alejado para que Sonnia quepa debajo con los brazos levantados.
- **Encima de la vista**, en la capa del juego: el pictograma de la pose (un monigote blanco) arriba a la derecha con su instrucción; el rótulo de la orden abajo, como un rótulo de televisión, con «Simón dice» resaltado cuando lo dijo; el contador circular de la ventana; el resultado en el centro («7 de 9», «¡Cayeron 4!» o «¡Nadie cayó!»); y, al colocarse, cuántos juegan y el aviso («Un paso atrás: a unos 2 m»).
- **Final**: la tarjeta de resultado con el total del grupo y celebración.
- **Demostración de Sonnia**: cada pose sostenida por código sobre el humanoide desde `round` hasta `result`, con entrada y salida suaves (`PosesDemo`). Si el banco trae en `demo` el nombre de un clip, la enseña con ese clip; con `ninguna`, sin demostración.

## Cámara

- **Detector.** El de la visión de los juegos (`PoseDetector`, YOLOv8-pose, `docs/juegos-vision.md`), en continuo a `GAME_POSES_FPS` (8) detecciones por segundo mientras dura la partida. El juego mira la última detección cada 0,1 s (0,05 s en la ventana) y cuenta cada frame una vez.
- **Quién juega.** Las personas con los dos hombros a la vista cuya caja ocupa al menos `GAME_POSES_MIN_PERSON` (0,25) del alto de la imagen: la gente del fondo o de paso no cuenta. Quien está demasiado cerca sigue jugando si se le puede medir, pero sale en amarillo para que se aparte.
- **Reglas** (`server/sonia/games/poses/rules.py`). Todo se mide relativo a cada cuerpo: las coordenadas pasan a píxeles (para que los ángulos valgan igual en los dos ejes) y las distancias van en anchos de hombros (`S`) desde sus hombros, su nariz o su cabeza, nunca en posiciones absolutas. Permisivas: si falta la muñeca, cuenta el codo (salvo en la barbilla, donde el codo solo no dice nada); en las poses de dos brazos, un brazo que no se ve no cuenta en contra (en un grupo apretado se tapan), pero alguno tiene que verse.

  | id | Orden | Pose | Cómo se detecta |
  |---|---|---|---|
  | `brazos_arriba` | «¡Pasaron todos los tests!» | Los dos brazos arriba. | Cada muñeca al menos 0,45 S por encima de la nariz con el codo al menos 0,25 S por encima del hombro (sin muñeca, el codo por encima de la nariz). Vale en V y con los puños en alto y los codos doblados. |
  | `un_brazo` | «Subiendo a producción» | Un brazo arriba. | Un brazo arriba (como el de arriba) y el otro no. |
  | `pose_t` | «Pose T, la del avatar sin animar» | Brazos en cruz. | Cada brazo hacia fuera, a menos de 35° de la horizontal, estirado (la muñeca a más de 0,85 S del hombro y el codo a más de 130°). |
  | `manos_cabeza` | «Deploy un viernes» | Manos a la cabeza. | Cada muñeca a menos de 0,85 S del centro de la cabeza, ni por debajo de la barbilla ni a más de 0,6 S por encima de la nariz (los brazos estirados hacia arriba no cuentan); sin muñeca, el codo levantado por encima del hombro sin llegar a lo de brazos arriba. |
  | `biceps` | «Compiló a la primera» | Sacar bíceps. | Cada codo a la altura del hombro (±0,45 S) y abierto hacia fuera, con la muñeca por encima del codo y el antebrazo más vertical que horizontal. |
  | `barbilla` | «Revisando el PR» | Mano en la barbilla. | Una muñeca por debajo de la nariz, como mucho 0,2 S bajo la línea de los hombros, cerca del centro de la cara y con el codo por debajo. |

  En reposo no salta ninguna: brazos caídos, cruzados, en los bolsillos, en jarras o el móvil en la mano a la altura del pecho o de la cintura (hay tests). Sí pueden contar de más: con las manos en las mejillas cuenta como barbilla y como manos a la cabeza, y quien levanta el móvil a la cara para hacer una foto puede contar como barbilla. Es lo buscado: un juego de fiesta, colectivo y generoso.
- **Vista en vivo.** Encima de la imagen (en espejo) van los esqueletos de quienes juegan, con los dibujos de `sonia/vision/overlay.py`: en gris mientras se demuestra la pose y suena la orden; en la ventana y el resultado, en verde con ✓ quien hace la pose y en gris quien no; en las trampas, en rojo con ✗ quien cae; en amarillo quien está demasiado cerca. Los dibuja el hilo de la vista en vivo; el juego solo cambia la lista entera de esqueletos.
- **Nada se guarda** ni sale del equipo: ni imágenes, ni puntos, ni recuentos de nadie, y no se reconoce a nadie. La vista en vivo solo existe mientras dura la partida.

## Bancos

| Banco | Archivo | Entradas | Mínimo |
|---|---|---|---|
| `poses_poses` («Poses de «Simón dice»») | `assets/games/poses/poses.md` | 6 poses | 3 activas |

Formato (explicado al principio del archivo): `## <id>` (uno de los seis de la tabla de arriba: una pose nueva necesita su regla en el código) y debajo `- orden:` (el meme, sin «Simón dice», hasta 60 caracteres), `- pose:` (la instrucción clara, en minúsculas, hasta 32), `- demo:` (opcional: vacío, la pose por código; el nombre de un clip, ese clip; `ninguna`, sin demostración) y `- activa:` (`sí` por defecto, `no` la deja fuera). Desde el panel («Bancos de los juegos») se cambian las frases y las instrucciones y se activan o desactivan poses sin instalar nada. Es un borrador **pendiente de revisión de Jean**.

## Frases grabadas

Las órdenes de todas las poses activas, con y sin «Simón dice» (doce con el banco de la app): «¡Simón dice: pasaron todos los tests, brazos arriba!» y «¡Pasaron todos los tests, brazos arriba!», etcétera (`PosesGame.phrases`). Entran en «Preparar voces» y en la grabación automática. Si se cambia una frase del banco, hay que volver a prepararlas: mientras tanto, GPT-Live la dice en directo y la ventana se abre algo más tarde.

## Ajustes (`GAME_POSES_*`)

| Ajuste | Por defecto | Qué hace |
|---|---|---|
| `ENABLED` | `true` | Con `false` no se ofrece. |
| `ROUNDS` | 6 | Rondas por partida. |
| `TRICKS` | 1 | De ellas, trampas (nunca la primera). |
| `WINDOW_SECONDS` | 1.8 | Ventana tras la orden en la que se cuenta (el mejor frame). |
| `MIN_PERSON` | 0.25 | Alto mínimo de una persona en la imagen (fracción) para jugar. |
| `FPS` | 8 | Detecciones por segundo mientras se juega. |
| `MODEL` | `n` | Modelo de poses: `n` (ligero) o `s` (más preciso, el doble de CPU). El panel lo cambia en caliente (`docs/juegos-vision.md`). |
| `ABANDON_SECONDS` | 0 | Sin voz ni nadie delante durante esto, se cancela (0: `GAMES_ABANDON_SECONDS`). |

Los tiempos internos (colocación, espera a que calle, demostración, reintentos) son constantes documentadas al principio de `server/sonia/games/poses/game.py`.

## Pruebas y capturas

- `server/tests/games/test_poses_rules.py`: cada pose con monigotes inventados (`puppets.py`), que no salte con las demás ni en reposo, que dé igual el lado y el sitio de la imagen, el codo cuando falta la muñeca, el brazo que no se ve, quién juega y la colocación.
- `server/tests/games/test_poses.py`: el banco (bien y mal formado, mínimo, frases grabadas), el plan de rondas (la trampa nunca primero, sin repetir seguida), la partida entera con una multitud falsa (acierto, trampa, sin nadie, alguien demasiado cerca, la cámara que falla), los textos para GPT-Live (sin marcas del stack, las reglas por debajo de 1200 caracteres), los esqueletos de la vista en vivo (colores y espejo) y de punta a punta con el `GameManager`: por voz, con las órdenes grabadas, `stop_game` a mitad, abandono, reconexión de Unity y la secuencia del orquestador falso.
- **Con detecciones de verdad** (10 de octubre de 2026): el detector de poses (`s`) sobre fotos públicas de Wikimedia Commons (las de `docs/juegos-vision.md` y otras siete: guerrero II de yoga, doble bíceps, un chico pensando con la mano en la barbilla, un hombre pensando, niños con las manos arriba, la foto de grupo de Wikimania 2023 con las manos arriba y un dibujo de un hombre con las manos en la cabeza), en el scratchpad de esa sesión y nunca en el repo:
  - Grupos de frente en reposo (cuatro fotos, unas 55 personas que juegan): ninguna pose de más.
  - Saltando en la playa (seis personas de espaldas): las dos con los brazos arriba, las tres con uno y la de las manos en la cabeza, como en la foto.
  - Brazos arriba (también con los puños en alto y los codos doblados), pose T, doble bíceps y las dos manos en la barbilla: bien.
  - Cuentan de más: quien habla con un micro o enseña la palma delante de la cara sale como barbilla (es lo esperado: la mano junto a la cara).
  - En las multitudes muy apretadas el detector solo ve la primera fila (ya lo dice la prueba de la visión) y en un dibujo cortado por arriba no hay nada que medir.
  - Ajustes que salieron de aquí: el codo de brazos arriba basta con 0,25 S por encima del hombro (con 0,4 se perdían los puños en alto), las manos a la cabeza no pasan de 0,6 S sobre la nariz (los brazos estirados junto a la cabeza contaban), la muñeca del bíceps basta con 0,15 S sobre el codo (el detector la pone a media altura del antebrazo) y el torso y las orejas dan la escala solo con los hombros muy de perfil (con el torso largo, la escala salía inflada y los brazos arriba no llegaban).
  - **`s` frente a `n`**: con el modelo ligero (`n`, el de por defecto) los grupos en reposo siguen sin poses de más y brazos arriba, un brazo, manos a la cabeza, pose T y barbilla salen igual en las fotos de cuerpo entero, pero en los primeros planos pone peor las muñecas: se pierden el doble bíceps, una barbilla y los puños en alto del remero. Si la CPU del equipo del stand lo permite, mejor `s` para este juego (el panel cambia el modelo en caliente).
- Capturas 9:16 con el orquestador falso (`server/sonia/games/poses/demo.py`: colocación, ronda con demostración, orden, ventana, acierto, fallo, trampa, las demás demostraciones, final y cierre), con una vista en vivo sintética: una sala dibujada con monigotes y los esqueletos de verdad encima.

  ```bash
  SONIA_UNITY_LOCKS=$SP/unity-locks scripts/juegos_capturas.sh --juego poses --puerto 8793 --salida <scratchpad>/capturas
  ```

## Pendiente

- Probarlo con la API real (gasta: lo decide Jean): que delegue `start_game` a la primera, que reaccione en una frase a cada resultado sin inventar números y que no diga las órdenes ella.
- Medir los umbrales con gente de verdad delante de la cámara del stand (solo se han probado con monigotes inventados).
- El banco, pendiente de revisión de Jean.
