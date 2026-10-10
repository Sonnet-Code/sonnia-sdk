# Simón dice con poses (`poses`)

> Plan: `docs/plan-juegos.md`, sección 5.2. Contrato y cómo se hace un juego: `docs/juegos.md`.
> Visión: `docs/juegos-vision.md`. Unity: `docs/juegos-unity.md`.

## Qué es

Sonnia da órdenes con nombre de meme dev y la pose dicha en claro: «¡Simón dice: pasaron todos los tests, brazos arriba!». La cámara del stand cuenta cuántos hacen la pose (con `GAMES_JUDGE=gemini`, el de por defecto, el veredicto de cada ronda lo da Gemini con una foto) y la imagen en vivo sale encima de Sonnia, en espejo, con los esqueletos de quienes juegan. Algunas rondas son trampa: la orden sale sin «Simón dice» y quien hace la pose cae. El resultado es del grupo («¡7 de 9!», «¡cayeron 4!»): nunca se elimina a nadie.

## Cómo se juega

1. **Empezar.** El visitante pide jugar y GPT-Live delega `start_game(poses)` (o el equipo pulsa el botón del panel). El orquestador enciende el detector de poses y la vista en vivo, le pasa a GPT-Live las reglas (`instruct`) y le devuelve el guion de arranque: Sonia explica el juego en dos o tres frases (a unos dos metros, la pose solo con «Simón dice», cuántas rondas, nadie queda eliminado).
2. **Colocación.** Mientras Sonia explica, el orquestador mira a cuántos ve y si se les ven los brazos. Si alguien está demasiado cerca (hombros muy anchos en la imagen, hombros sin ninguna muñeca, la cabeza pegada al borde de arriba o solo la cara), Sonia le pide un paso atrás, hasta unos 2 m (como mucho una vez cada 12 s); si no ve a nadie en 4 s, pide que se pongan delante (una vez). La primera ronda empieza cuando Sonia ha terminado de explicar y hay alguien colocado durante 0,8 s, o como mucho a los 20 s (40 s si Sonia no calla).
3. **Rondas** (`GAME_POSES_ROUNDS`, 6). `GAME_POSES_TRICKS` (1) son trampa, nunca la primera. Las poses salen barajadas del banco y, si hay menos que rondas, se repiten sin salir la misma dos veces seguidas. En cada ronda:
   1. Espera a que Sonia calle (y, hasta 4 s más, a que nadie hable: en un stand con barullo la sesión casi nunca está en calma).
   2. **Orden** (eventos `round` y `command`): suena como frase grabada (`say_fixed`), exacta en el tiempo y en si dice «Simón dice». Si no está grabada, GPT-Live la dice tal cual por `commentary`. Si Sonia estaba hablando, se espera a que calle y se reintenta (tres veces). Hasta que suena, la pantalla no cambia: con la frase salen el pictograma de la pose, la demostración de Sonnia (que la sostiene hasta el resultado) y el rótulo de la orden; si no llega a sonar, salen igual y la ronda sigue. (Antes la demostración se adelantaba 1,4 s a la orden y, si Sonia alargaba la explicación, la orden salía en pantalla segundos antes de sonar.)
   3. **Ventana** (evento `window`): cuando termina de sonar la orden se abre una ventana de `GAME_POSES_WINDOW_SECONDS` (1,8 s). De todos sus frames cuenta el mejor recuento local: cuántos hacen la pose y cuántos juegan. Mientras cuenta, guarda en memoria la foto de la cámara de ese mejor recuento.
   4. **Juez** (con `GAMES_JUDGE=gemini`, ver «Cámara»): al cerrarse la ventana, esa foto va a Gemini con «Mirando las poses…» en pantalla, mientras la vista en vivo sigue con los esqueletos. Tarda 1,25 s de mediana y como mucho `GAMES_JUDGE_TIMEOUT_SECONDS` (4 s). Si su veredicto trae la pose, el resultado es el suyo; si no, el recuento local.
   5. **Resultado** (evento `result`): «7 de 9» (o, en la trampa, «¡cayeron 4!»), con el número final (el del juez o el local), y a GPT-Live le llegan esos números por `speak` para que reaccione en una frase muy corta. Se espera a que termine de reaccionar.
4. **Final** (evento `final`): el total del grupo («hicieron bien 38 de 50 jugadas»: la pose con «Simón dice» y quedarse quieto en las trampas) y cuántos cayeron en las trampas. Sonia lo celebra y, si alguien pregunta por premios, le manda con `TRIVIA_WIN_CONTACT` (Brian o Mariel) sin prometer nada. La partida termina con `win` y el resultado se queda en pantalla hasta que Sonia termina de contarlo. Nunca termina en `lose`: el resultado es del grupo y siempre se celebra.
5. **Sin nadie.** Dos rondas seguidas sin ver a nadie (con el número final: si el juez dice que no hay nadie, cuenta como ronda vacía) y el juego se acaba (`cancel`) con una frase. Si nadie habla ni hay nadie delante durante `GAMES_ABANDON_SECONDS` (60 s), el manager la da por abandonada; mientras la cámara vea gente jugando, el juego avisa de que sigue (`touch`) aunque nadie hable.

Una partida de seis rondas dura unos 80 s (unos 8 s más con el juez de Gemini).

## Quién hace qué

| Quién | Qué hace |
|---|---|
| GPT-Live | Delega `start_game(poses)` en cuanto el visitante quiere jugar. Explica el juego con el guion de arranque, reacciona en una frase a cada resultado que le llega, pide el paso atrás cuando se lo dicen y celebra el final. No dice las órdenes ni se inventa números. Si quieren dejar de jugar, delega `stop_game`. |
| Backend Responses | Llama a `start_game` y `stop_game`. Este juego no tiene jugadas propias: todo lo demás lo lleva el orquestador con la cámara. |
| Orquestador | Elige las rondas y las trampas, manda la pantalla, hace sonar las órdenes, cuenta con la cámara en cada ventana (`rules.py`), pide el veredicto de cada ronda al juez de Gemini con una foto (`GAMES_JUDGE=gemini`), dibuja los esqueletos en la vista en vivo (`overlay.py`), le pasa los resultados a GPT-Live y lleva la colocación. Código en `server/sonia/games/poses/`. |
| Gemini (juez) | Con `GAMES_JUDGE=gemini`, mira la foto de cada ronda y dice cuántas personas juegan y cuántas hacen cada pose (`docs/juegos-vision.md`, «Juez de Gemini»). No sabe nada del juego ni de nadie. |
| Unity | Pinta la vista en vivo grande, el pictograma, la orden, el contador de la ventana, el resultado y el final, y hace que Sonnia demuestre cada pose (`unity/Assets/Scripts/Sonia/Games/Poses/`). |

## Acciones de GPT-Live

| Acción | Cuándo la usa | Qué devuelve |
|---|---|---|
| `start_game` (`juego`: `poses`) | El visitante quiere jugar. | El guion de arranque: explicar el juego en dos o tres frases y callar (las órdenes empiezan solas). Con la partida ya en marcha, por qué ronda va. Sin cámara, sin detector o con la pantalla de una versión anterior, por qué no se puede y qué otros juegos hay. |
| `stop_game` | Ya no quiere seguir. | El juego se cancela. |

No hay jugadas delegadas: nada de lo que dice el visitante cambia el juego, así que no hay nada que entender ni que delegar (menos herramientas para GPT-Live). Lo que tiene que saber va por `instruct` (las reglas, menos de 1200 caracteres) y lo que tiene que decir ya, por `speak` (la colocación, cada resultado y el final).

## Control a mano (panel)

Por si falla la voz o la cámara, el equipo lleva la partida desde el panel (`panel_controls`, `panel_control`; «Reiniciar» y «Terminar» los pone el manager para todos):

| Control | Cuándo | Qué hace |
|---|---|---|
| «Lo hicieron» / «No lo hicieron» | Con una ronda en curso (orden, ventana o el juez mirando) | El veredicto de esa ronda: todos o ninguno de los que juegan (al menos uno). Manda sobre el juez y lo local; con él puesto, el juez ni mira. |
| «Lo hicieron» / «No lo hicieron» | Con el resultado en pantalla | Corrige esa ronda: la pantalla, los totales y el guion para que Sonia lo cuente («Corrige el resultado de la ronda 2: …»). |
| «Siguiente orden» | En la colocación, con una ronda en curso o con su resultado | Salta: la colocación empieza ya; la ronda en curso no cuenta; con el resultado, no se espera a que Sonia termine de reaccionar. Sin guion para Sonia: la siguiente orden suena sola. |

Fuera de esas fases, `GameError` con el motivo para el equipo. Se saltan las esperas con una marca que miran los bucles, nunca cancelando la tarea: así una orden grabada que esté sonando termina entera (con su `speech_end`). Tests en `server/tests/games/test_controles_camara.py`.

## Pantalla

Sus eventos están en `docs/protocolo.md` («Eventos de cada juego», `poses`). Todos son fijos y llevan el estado completo, así que una Unity que se reconecta lo pinta todo con el último.

Todo lo monta `PosesController` (`unity/Assets/Scripts/Sonia/Games/Poses/`) por código, en la capa del juego; la tarjeta común no se enseña hasta el final.

- **Cabecera fina** arriba: el título con las letras en los colores de Google y, a la derecha, «COLÓCATE» o «RONDA 2 DE 6».
- **Vista en vivo** grande justo debajo (960x540), con «En vivo · no se graba». Si se retira y vuelve, se recoloca; sin imagen, «Esperando la cámara…». La cámara de la escena usa el plano de panel automático, con sitio reservado para que se vean las manos de Sonnia arriba.
- **Encima de la imagen:**
  - el pictograma de la pose (un monigote blanco, `PosesPictogram`) arriba a la derecha, con su instrucción;
  - el rótulo de abajo, como uno de televisión: «¡Atentos a Sonnia!» mientras demuestra, y la orden tal cual sonó, con «Simón dice» en amarillo cuando lo dijo;
  - el contador circular de la ventana a la izquierda;
  - el resultado en el centro: «7 de 9» (con destellos si la hicieron todos), «¡Cayeron 4!» con «Era trampa: sin «Simón dice»», o «¡Nadie cayó!»;
  - al colocarse, cuántos juegan («3 JUGANDO», «NO VEO A NADIE») y el aviso del orquestador en amarillo («Un paso atrás: a unos 2 m»).
- **Final**: lo del juego se funde y sale arriba la tarjeta común del resultado, dorada y con confeti: «¡QUÉ EQUIPO!», «38 de 50», «poses bien hechas · 3 cayeron en la trampa».
- **Demostración de Sonnia** (`PosesDemo`): sostiene la pose de `round` a `result` con IK de dos huesos por brazo hacia objetivos medidos cada frame sobre su propio cuerpo (hombros, largo del brazo, y la cabeza y la barbilla medidas una vez en la malla, con el pelo). El codo dobla por su bisagra y la mano se orienta entera, con cada falange apuntada: abierta y relajada (nunca en garra), puño con el pulgar recogido en el bíceps y puño suelto bajo la barbilla. Entra en 0,5 s y sale en 0,45 s, con el camino de la mano abombado para no atravesar el cuerpo ni la cabeza. Corre en `LateUpdate` muy tarde (orden 12650), después del Animator, los gestos de Genies, la cabeza y los ojos, así que gana a cualquier clip que suene y pone las manos en la cabeza ya girada. En la pose T la cámara se aleja un poco mientras dura, para que entren las dos manos. Si el banco trae en `demo` el nombre de un clip, la enseña con ese clip; con `ninguna`, sin demostración. Validada por fotogramas (entrada, sostenida y salida, con primeros planos de las manos) en las seis poses.

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
- **Juez de Gemini** (`GAMES_JUDGE=gemini`, `docs/juegos-vision.md`). Una sola foto por ronda, también en las trampas: la del mejor recuento local de la ventana (entre las de mejor recuento, la más reciente; si lo local no vio a nadie haciéndola, eso deja la última de la ventana), cogida con `host.stream.latest()` mientras se cuenta y guardada solo en memoria. Mientras el juez mira, la vista en vivo sigue con los esqueletos y sale la pastilla «Mirando las poses…» (`busy`, tipo `judge`), que se apaga al llegar el veredicto.
  - **Con veredicto que trae la pose:** cuántos la hacen es la cuenta del juez (sin pasar de sus `personas`). Cuántos juegan sale de lo local si vio a alguien (la gente cerca, con `GAME_POSES_MIN_PERSON`), nunca menos que los que hicieron la pose: Gemini cuenta a toda persona visible, también a la gente de paso del fondo, y daba «2 de 40». Si lo local no vio a nadie, las `personas` del juez con un tope de 10 (`MAX_JUDGED_PLAYERS`).
  - **Sin veredicto** (no contesta en `GAMES_JUDGE_TIMEOUT_SECONDS`, falla, el JSON no cuadra o no trae la pose): el recuento local de la ventana, como antes.
  - **Sin juez** (`GAMES_JUDGE=local` o sin `GEMINI_API_KEY`): ni foto ni aviso; decide lo local.
  - En el banco de pruebas Gemini acertó la pose de una persona en 22 de 22 fotos (lo local, 21 con `s` y 17 con `n`) y cuántos la hacen en un grupo (±1) en 10 de 11 (9 y 9). Su fallo conocido: contó a tres personas con los dos brazos arriba como `un_brazo`.
- **Nada se guarda**: ni imágenes, ni puntos, ni recuentos de nadie, y no se reconoce a nadie. Lo único que sale del equipo, con `GAMES_JUDGE=gemini`, es la foto reducida de cada ronda hacia Gemini, que no se guarda. La vista en vivo solo existe mientras dura la partida.

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
- **De punta a punta con la visión de verdad** (10 de octubre de 2026, en el scratchpad): el `GameManager` con el motor y la pantalla falsos, pero con el detector (`YoloPoseDetector`) y la vista en vivo (`LivePreview`) de verdad sobre una «cámara» que siempre da una foto pública. La partida va sola de la colocación al final (`end` con `win`), cuenta a los cinco que juegan, manda unos 10 frames `SNCV` por segundo y los esqueletos caen encima de cada persona en la imagen en espejo.
- Capturas 9:16 con el orquestador falso (`server/sonia/games/poses/demo.py`: colocación, ronda con demostración, orden, ventana, acierto, fallo, trampa, las demás demostraciones, final y cierre), con una vista en vivo sintética: una sala dibujada con monigotes y los esqueletos de verdad encima.

  ```bash
  SONIA_UNITY_LOCKS=$SP/unity-locks scripts/juegos_capturas.sh --juego poses --puerto 8793 --salida <scratchpad>/capturas
  ```

  Pasada del 10 de octubre de 2026: las 17 capturas revisadas, sin ningún aviso de que lo de arriba tape la cabeza de Sonnia. Las seis demostraciones se validaron además por fotogramas (entrada, sostenida y salida, con primeros planos de las manos y el cuerpo) con una secuencia propia en el scratchpad.

## Pendiente

- Probarlo con la API real (gasta: lo decide Jean): que delegue `start_game` a la primera, que reaccione en una frase a cada resultado sin inventar números y que no diga las órdenes ella. Y el juez de Gemini con la cámara del stand y gente de verdad (lo hace la sesión principal): cuánto tarda cada veredicto y si cuenta a la gente de paso del fondo.
- Medir los umbrales con gente de verdad delante de la cámara del stand (se han probado con monigotes inventados y con fotos públicas, nunca con la cámara de nadie).
- Pose T: en los primeros ~0,3 s de la entrada las manos de Sonnia rozan el borde de la pantalla mientras la cámara aún se aleja (ya sostenida, quedan dentro con margen), y durante esa ronda Sonnia sale algo más pequeña.
- El banco, pendiente de revisión de Jean.
