# Modo trivia

Sonia hace una trivia de preguntas sobre el DevFest, el GDG, la biblioteca, Sonnet Code y tecnología. Por defecto son 5 preguntas de tres opciones (A, B y C), que salen en la pantalla vertical, y se gana con 3 aciertos. Sonia se pone un gorro de fiesta al empezar y se lo quita al terminar.

## Cómo se lanza

Las dos vías entran por el mismo `TriviaGame.start` (`server/sonia/trivia/game.py`), así que la partida es la misma la lance quien la lance.

- **Por voz.** El visitante dice «¿jugamos a la trivia?» y GPT-Live delega `start_trivia` en el backend.
- **Desde el panel.** En el local y en sonia.sonnetcode.com: botón «Empezar trivia» de la tarjeta «Trivia».

Solo funciona en «Conversando» y con la pantalla conectada. No funciona con el Modo Jean, el editor de personaje ni el modo debug.

## Quién hace qué

GPT-Live lleva la conversación de la trivia y el orquestador guarda la clave de respuestas y la pantalla.

| Quién | Qué hace |
|---|---|
| GPT-Live | Lee cada pregunta y sus opciones. Entiende lo que contesta el visitante («la B», «Kotlin», «la segunda», «dos mil doce», «la A… no, la C»), lo pasa a su letra y delega `trivia_answer`. Reacciona al resultado. Si alguien no sabe qué preguntar, puede proponer la trivia. |
| Backend Responses | Llama a las acciones `start_trivia`, `trivia_answer`, `restart_trivia` y `stop_trivia` con la letra que le da GPT-Live. Si no le llega la letra, no la adivina. |
| Orquestador | Saca 5 preguntas al azar del banco y baraja las opciones. Guarda la clave y cuenta los aciertos. Manda la pantalla a Unity (`trivia_*`, ver `docs/protocolo.md`) y escribe el guion de cada paso: la pregunta, el veredicto con un dato curioso, y la siguiente pregunta o el final. |
| Unity | Muestra la tarjeta, el acierto o el fallo, el confeti, el marcador y la pantalla final. Hace el gorro y las reacciones de Sonia (`TriviaController`, `TriviaHat`). |

GPT-Live no conoce la respuesta correcta hasta que el resultado de `trivia_answer` se la dice, así que no puede revelarla antes de tiempo. La que vale siempre es la de la pantalla.

El guion vuelve a GPT-Live por dos caminos:

- **Por voz:** como resultado de la acción, marcado con `PARA SONIA:` para que el backend lo pase entero (`BACKEND_PROMPT`).
- **Desde el panel** (empezar, contestar con los botones A, B y C o reiniciar): con `session.commentary.append`, que es lo que la hace hablar.

Al empezar, las reglas de la trivia entran en la sesión con `session.instructions.append`. Al terminar, otra instrucción le dice que vuelva a conversar con normalidad.

## Acciones de GPT-Live

| Acción | Cuándo la usa | Qué devuelve |
|---|---|---|
| `start_trivia` | El visitante quiere jugar. | El guion de arranque con la pregunta 1. |
| `trivia_answer` (`option`: `A`, `B`, `C` o `no_lo_sabe`) | El visitante elige. | El veredicto, un dato y la siguiente pregunta o el final. |
| `restart_trivia` | El visitante quiere empezar otra desde cero. | Corta la partida en curso, si la hay, y devuelve la pregunta 1 de una nueva. |
| `stop_trivia` | El visitante ya no quiere jugar. | La partida se cancela. |

## Mientras dura la partida

- **Recordatorio:** sin respuesta durante `TRIVIA_REMIND_SECONDS` (25 s), Sonia repite las opciones una vez.
- **Abandono:** sin oír al visitante durante `TRIVIA_ABANDON_SECONDS` (60 s), la partida se cancela; el visitante se ha ido.
- **Ritmo:** el acierto o el fallo se quedan en pantalla `TRIVIA_REVEAL_SECONDS` (4 s) antes de la siguiente pregunta.
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

El gorro (`TriviaHat`) es un cono de franjas generado por código. Sonia se lo pone y se lo quita con las dos manos, con IK de brazos. Las prendas del catálogo de Genies se descartaron: equiparlas descarga y reconstruye el avatar en mitad de la partida y ninguna es temática.

## Pendiente

- Retoques visuales: tamaños, colores, la pantalla de derrota y el encuadre fino.
- Probarlo con la API real: cómo pasa el backend el guion `PARA SONIA:` y lo que tarda la delegación de `trivia_answer`. Las pruebas automáticas usan un GPT-Live falso.
