# Modo trivia

Sonia hace una trivia de preguntas sobre el DevFest, el GDG, la biblioteca, Sonnet Code y tecnología. Por defecto son 5 preguntas de tres opciones (A, B y C), que salen en la pantalla vertical, y se gana con 3 aciertos. Sonia se pone la gorra Noogler al empezar y se la quita al terminar.

## Cómo se lanza

Las dos vías entran por el mismo `TriviaGame.start` (`server/sonia/trivia/game.py`), así que la partida es la misma la lance quien la lance.

- **Por voz.** El visitante dice «¿jugamos a la trivia?» y GPT-Live delega `start_trivia` en el backend.
- **Desde el panel.** En el local y en sonia.sonnetcode.com: botón «Empezar trivia» de la tarjeta «Trivia».

Solo funciona en «Conversando» y con la pantalla conectada. No funciona con el Modo Jean, el editor de personaje ni el modo debug.

## Quién hace qué

GPT-Live lleva la conversación de la trivia y el orquestador guarda la clave de respuestas y la pantalla.

| Quién | Qué hace |
|---|---|
| GPT-Live | Pregunta el nivel (fácil, intermedio o difícil) y si ya sigue a Sonnet Code en Instagram y LinkedIn, sin comprobarlo. Lee solo cada pregunta: las opciones están en la pantalla y no las lee. Explica cada respuesta y pregunta si pasa a la siguiente; cuando el visitante dice que sí, delega `trivia_next`. Entiende lo que contesta el visitante («la B», «Kotlin», «la segunda», «dos mil doce», «la A… no, la C»), lo pasa a su letra y delega `trivia_answer`. Reacciona al resultado. Si alguien no sabe qué preguntar, puede proponer la trivia. |
| Backend Responses | Llama a las acciones `start_trivia`, `trivia_answer`, `trivia_next`, `restart_trivia` y `stop_trivia` con la letra que le da GPT-Live. Si no le llega la letra, no la adivina. |
| Orquestador | Saca 5 preguntas al azar del banco, del nivel elegido (y, si no llegan, del más cercano), y baraja las opciones. Guarda la clave y cuenta los aciertos. Manda la pantalla a Unity (`trivia_*`, ver `docs/protocolo.md`) y escribe el guion de cada paso: la pregunta, el veredicto con su explicación y un dato, o el final con el premio. Nada avanza solo: la siguiente pregunta sale con `trivia_next`. |
| Unity | Muestra la tarjeta, el acierto o el fallo, el confeti, el marcador y la pantalla final. Hace el gorro y las reacciones de Sonia (`TriviaController`, `TriviaHat`). |

GPT-Live no conoce la respuesta correcta hasta que el resultado de `trivia_answer` se la dice, así que no puede revelarla antes de tiempo. La que vale siempre es la de la pantalla.

El guion vuelve a GPT-Live por dos caminos:

- **Por voz:** como resultado de la acción, marcado con `PARA SONIA:` para que el backend lo pase entero (`BACKEND_PROMPT`).
- **Desde el panel** (empezar, contestar con los botones A, B y C o reiniciar): con `session.commentary.append`, que es lo que la hace hablar.

Al empezar, las reglas de la trivia entran en la sesión con `session.instructions.append`. Al terminar, otra instrucción le dice que vuelva a conversar con normalidad.

## Acciones de GPT-Live

| Acción | Cuándo la usa | Qué devuelve |
|---|---|---|
| `start_trivia` (`nivel` opcional) | El visitante quiere jugar. | El guion de arranque con la pregunta 1 (para leer solo la pregunta). |
| `trivia_answer` (`option`: `A`, `B`, `C` o `no_lo_sabe`) | El visitante elige. | El veredicto con su explicación y, si no era la última, que pregunte si pasa a la siguiente; en la última, el final y el premio. Si llega con el resultado aún en pantalla, se le dice que primero pida la siguiente. |
| `trivia_next` | El visitante pide la siguiente. | La siguiente pregunta en pantalla y su guion. |
| `restart_trivia` (`nivel` opcional) | El visitante quiere empezar otra desde cero. | Corta la partida en curso, si la hay, y devuelve la pregunta 1 de una nueva. |
| `stop_trivia` | El visitante ya no quiere jugar. | La partida se cancela. |

## Mientras dura la partida

- **Recordatorio:** sin respuesta durante `TRIVIA_REMIND_SECONDS` (25 s), Sonia anima una vez y, si hace falta, repite la pregunta (nunca las opciones).
- **Abandono:** sin oír al visitante durante `TRIVIA_ABANDON_SECONDS` (60 s), la partida se cancela; el visitante se ha ido.
- **Ritmo:** lo lleva el visitante. El resultado se queda en pantalla hasta que pide la siguiente (`trivia_next`). Antes, con un temporizador, una respuesta dada mientras se veía el resultado se perdía y la cuenta se desfasaba: así se explican las respuestas buenas marcadas como malas y la partida que se quedó en la pregunta 5 en la demo del 6 de octubre. Tras la última, la pantalla final sale cuando Sonia termina de contar el resultado: al menos `TRIVIA_REVEAL_SECONDS` (4 s) y como mucho `TRIVIA_FINAL_WAIT_SECONDS` (20 s).
- **Niveles y premios:** el nivel lo elige el visitante (`TRIVIA_DEFAULT_LEVEL`, intermedio, si no). Por jugar se lleva `TRIVIA_PRIZE_PARTICIPATION` (un sticker o un pin) y por ganar en difícil, `TRIVIA_PRIZE_HARD_WIN` (una gorra); Sonia lo anuncia y la pantalla final lo muestra. El panel tiene el nivel al lado de «Empezar trivia» y un botón «Siguiente pregunta».
- **Pausas:** no hay animación de stand, ni renovación de la sesión por inactividad, ni saludo automático con la mano.
- **Cancelación:** la partida se cancela si cambia el modo, si se cae o se renueva la sesión de GPT-Live, o con «Terminar trivia» o «Reiniciar» en el panel.
- **Reconexión:** si Unity se reconecta a mitad de partida, el orquestador le repite `trivia_start` y la pregunta en curso.

## Preguntas

El banco está en `assets/trivia/preguntas.md` y se edita sin tocar código. El formato está explicado al principio del archivo. El orquestador lo relee al empezar cada partida. Las preguntas mal formadas se saltan con un aviso, y si no hay suficientes la trivia no se ofrece.

**Jean debe revisar las preguntas antes del evento.**

## Pantalla y animación

La tarjeta va en la franja alta, la misma del panel de imágenes, y la cámara pasa al plano de panel un poco más atrás para que Sonia y el gorro quepan debajo (`TriviaController.panelShotExtra`). Las reacciones de Sonia son clips oficiales de Genies (GeniesIRL, Apache-2.0):

| Momento | Clip |
|---|---|
| Acierto | `actions-highFive_actionSuccess` |
| Fallo | `actions-highFive_actionFail` |
| Ganar | `QuickAction_vibe` |
| Perder | `emotions-0049-traitsKind` |

Los clips van en el set con «Sonia > Crear set de animaciones» (`SoniaAnimations.TriviaClips`) y suenan enteros aunque Sonia pase a pensar o a hablar (`AvatarChoreographer.PlayReaction`).

## El gorro Noogler

Sonia se pone la gorra Noogler, la de hélice que Google da a quien acaba de entrar: gajo amarillo delante con «Noogler» bordado en los colores de Google, azul a un lado, rojo al otro y una hélice arriba que gira, y más deprisa al acertar y al ganar. Sonia se la pone y se la quita con las dos manos (IK de brazos en `TriviaHat`), porque Genies no trae ninguna animación de ponerse un gorro. Para cogerla se inclina hacia delante (dobla la columna sobre la animación que suene) y la recoge abajo, delante de los muslos, donde la cámara no la ve: se inclina lo justo para eso, entre 20° y 70°. La sube con las palmas apoyadas por fuera de los costados de la copa (puntos de agarre del prefab), sin atravesarla. Quitársela es el mismo gesto al revés: la levanta recta, la baja en arco, se inclina y la deja abajo, fuera de cuadro.

Va como una prenda oficial de Genies:

- **Sitio y tamaño medidos.** Se encajó (ICP de semejanza) sobre la gorra oficial que llevaba Sonia, `WardrobeGear/recRecBCofFMJ5Hox`, en el espacio del hueso de la cabeza, que es donde va pegada esa gorra: escala 1,26, unos 5° hacia delante y 4,6 mm de error medio entre las dos copas. El resultado (`NooglerCap_fit.json`) lo guarda el prefab en `TriviaCapRig`. Por los lados y la nuca la gorra oficial baja más que la Noogler, así que la parte baja de la copa se estira hasta su borde (hasta 2 cm, `gorra_oficial_borde.json`) para tapar el pelo que Genies deja aplastado. Una vez puesta no se bambolea.
- **Gorra oficial.** Genies (NAF) junta cuerpo, pelo, ropa y gorro en un solo renderer (`Default`) con una submalla por material. Mientras Sonia lleva la Noogler, la submalla de la gorra oficial se apaga con un material sin pasadas de render. `TriviaHat.FindHatParts` la encuentra sola: es la ropa que queda entera por encima del hueso de la cabeza y pasa de la coronilla, así que vale para cualquier gorra.
- **Pelo.** NAF solo aplasta el pelo cuando el avatar lleva una gorra oficial, y lo hornea en la malla: no hay blendshape que mover en tiempo real. Así que cada vez que se pone un avatar de Sonia, `GeniesHatHair` monta a escondidas (muy por debajo del suelo) una gemela con la misma definición más la gorra de referencia, la del encaje (`GeniesHatHair.ReferenceHat`), copia de ella la forma del pelo y la suelta. Con las piezas ya en caché tarda unas décimas de segundo. `HatHair` compara las dos mallas vértice a vértice (misma topología, UV y esqueleto) y saca una copia de la malla de Sonia con un blendshape más, `sonia_hat_hair`. `TriviaHat` pone esa copia mientras Sonia lleva la Noogler: la gorra llega unos centímetros por encima de su sitio y baja recta mientras el blendshape sube, así que la copa tapa la coronilla antes de que el pelo se recoja y no lo atraviesa; al quitársela, al revés. Sin gorro, Sonia lleva su malla de siempre. Vale para cualquier pelo de Genies, porque el aplastado lo hace Genies, y al cambiar de avatar se vuelve a sacar. Genies aplasta recogiendo el pelo en un aro bajo la línea de la gorra, así que bajo la copa la coronilla queda calva: solo se ve por la abertura trasera de la Noogler, y se deja así: en la trivia Sonia nunca da la espalda (decisión de Jean). Si Sonia ya lleva una gorra oficial, su pelo ya va aplastado y no se monta la gemela. Si la gemela falla por la red, se reintenta al ponerse la gorra; si no casa, la gorra se pone sin aplastar el pelo y queda un aviso en el registro. Con avatares que traen el blendshape (`hair_geo_blendShape...hat`, como el doble del editor), `TriviaHat` lo activa.

El modelo es «HAT - Propeller Silly Hat - PBR Game Ready», de Dekogon (Sketchfab), recoloreado en Blender. Para regenerarlo con `scripts/gorro_noogler`, desde la raíz del repo:

1. Descomprimir el zip de Sketchfab en `scripts/gorro_noogler/fuente/`.
2. `uv run --no-project --with pillow python scripts/gorro_noogler/texto.py`: el texto bordado. Usa la fuente Avenir Next de macOS.
3. `blender -b --python scripts/gorro_noogler/construir.py`: deja el FBX, las texturas y las medidas en `unity/Assets/Sonia/Trivia/NooglerCap/`, y las vistas previas en `scripts/gorro_noogler/trabajo/`.
4. Solo si cambia la cabeza de Sonia: en Play y con una gorra oficial puesta, **Sonia > Medir gorra oficial (gorro Noogler)**. Después, `uv run --no-project --with numpy --with scipy --with matplotlib python scripts/gorro_noogler/encajar.py` (revisar `trabajo/gorra_oficial_encaje.png`) y otra vez `construir.py`, que estira el borde de la copa con lo medido. `prueba_encaje.py` comprueba el ajuste con una gorra sintética.
5. Fuera de Play, **Sonia > Crear gorro Noogler** monta el prefab en `Assets/Sonia/Trivia/Resources/Trivia/NooglerCap.prefab`.

Sin el prefab, `TriviaHat` vuelve al gorro de fiesta de franjas generado por código. Las prendas del catálogo de Genies se descartaron para la trivia: equiparlas descarga y reconstruye el avatar en mitad de la partida.

## Pendiente

- Si Sonia lleva una gorra oficial, al ponerse y quitarse la Noogler se ven las dos a la vez durante 2 o 3 frames.
- Retoques visuales: tamaños, colores, la pantalla de derrota y el encuadre fino.
- Probarlo con la API real: cómo pasa el backend el guion `PARA SONIA:` y lo que tarda la delegación de `trivia_answer`. Las pruebas automáticas usan un GPT-Live falso.
