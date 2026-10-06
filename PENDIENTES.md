# Pendientes tras la demo al equipo (6 de octubre de 2026)

Lo que salió de la demo de Sonnia al equipo por Google Meet, más lo que ya estaba
abierto. Faltan tres días para el DevFest (9 y 10 de octubre). Orden: primero lo
que rompe la demo, luego lo que la mejora y al final lo que no es código. Al
terminar algo, marca su casilla y apunta la fecha. El histórico está en `ROADMAP.md`.

Leyenda: 🐞 bug · ✨ mejora · 📦 build o reparto · 🗒️ decisión o tarea fuera del código.

## 1. Bugs

- [x] 🐞 **La trivia marca como incorrectas algunas respuestas correctas.** En la demo, alguien dijo la opción correcta y Sonnia la dio por mala. **Hecho (6 de octubre). Causa real, sacada del registro de la demo:**
  - Pregunta 1: no fue un fallo. La visitante dijo después que la había contestado mal a propósito.
  - Pregunta 4: nadie eligió nada. GPT-Live registró una «B» a partir de la charla del equipo («lo que dijo Alexander… pasa al otro de una vez»).
  - Arreglo: en las reglas, «lo que hablan entre ellos no es una respuesta: si no está claro que te contesta a ti, pregunta antes». Además, la siguiente pregunta ya no sale sola a los 4 s.
  - [x] Buscar en el registro de la demo (`orquestador-*.log` o la salida de `sonia reunion`) las líneas de `trivia_answer`, con la pregunta, la letra recibida y la clave. **Hecho: es lo de arriba. Las 4 respuestas llegaron bien; ninguna se perdió.**
  - [x] Reproducirlo con un test sin red. **Lo que falla es el criterio de GPT-Live, que un test no puede reproducir. Los tests comprueban que las reglas y el recordatorio llevan los dos arreglos.**
  - [x] Que el guion «PARA SONIA:» repita cada letra con el texto de su opción, para que GPT-Live no tenga que deducirla. **Hecho: va como «(para ti: A: …; B: …; C: …)».**
  - [ ] 🗒️ Partida de prueba con GPT-Live de verdad (gasta): que acierten las 5 respuestas dichas de varias formas («la B», «la segunda», el texto de la opción).

- [x] 🐞 **La trivia se quedó congelada en la pregunta 5 y nunca terminó.** **Hecho (6 de octubre). Causa real, sacada del registro de la demo:**
  - La visitante dijo «La C, Sonnia». Sonnia contestó ella sola, «Era la C, la Plaza de la Cultura», sin delegar la respuesta, así que la pantalla se quedó en la 5 hasta que se canceló desde el panel.
  - Arreglo:
    - En las reglas: «nunca digas si acierta ni cuál era sin delegar la respuesta».
    - El recordatorio de una pregunta sin respuesta le pide ahora registrar la opción si el visitante ya la dijo, en vez de volver a preguntar.
  - [x] Ver en el registro qué pasó tras la respuesta a la 5: si llegó `trivia_answer`, qué devolvió y si se mandó a Unity el mensaje de fin. **Hecho: no llegó ningún `trivia_answer` (lo de arriba).**
  - [x] Que la última respuesta cierre siempre la partida, aunque GPT-Live no delegue nada más, y que la pantalla no se quede colgada si se pierde un mensaje. **Hecho:**
    - La última respuesta cierra la partida, y la pantalla final espera a que Sonnia termine de hablar, con un tope.
    - Los mensajes de la trivia son fijos: Unity los recibe otra vez al reconectar.
    - El recordatorio cubre la respuesta que no se registró.
  - [x] Test que juegue una partida entera hasta el final. **Hecho: `test_partida_ganada_por_voz` y, con GPT-Live falso, `test_trivia_por_voz_de_principio_a_fin`.**

- [x] 🐞 **No hay app para el Mac antiguo (anterior a M1).** `Sonnia.app` y su orquestador congelado son solo arm64 (comprobado con `file`). **Bloqueado (6 de octubre): todas las librerías nativas de Genies para macOS son solo arm64, así que en un Mac Intel no carga el avatar. Esa persona puede usar la build de Windows en un PC.**
  - [x] Confirmar que las librerías nativas de Genies traen x86_64 (`lipo -info` sobre las `.dylib` del SDK). **Hecho: no lo traen; solo arm64.**
  - No aplican, por el bloqueo: compilar la app para Universal o x64, congelar el orquestador para x86_64 y probarla en ese Mac.

## 2. Trivia

- [x] ✨ **Preguntar antes de pasar a la siguiente.** Hoy pasa sola tras el veredicto. **Hecho (6 de octubre): Sonnia explica la respuesta, pregunta si siguen y espera; la siguiente sale con `trivia_next` (o el botón del panel).**
  - [x] Que la acción no devuelva ya la siguiente pregunta en el guion: Sonnia da el veredicto y el dato, y pregunta «¿lista para la siguiente?» o «¿seguimos?».
  - [x] Acción «siguiente pregunta» que GPT-Live delega cuando el visitante dice que sí. Si dice que no, se termina la trivia. **Hecho: `trivia_next`; si no quiere seguir, el guion le pide terminarla (`stop_trivia`).**
- [ ] ✨ **Banco de unas 300 preguntas, sin repetir.** Hoy hay 20 en `assets/trivia/preguntas.md` y se sacan 5 al azar por partida. **Para después, por decisión de Jean.**
  - [ ] Recordar las ya hechas (en `cache/`, por equipo) y no repetirlas hasta agotar el banco.
  - [ ] Escribir las preguntas: base de conocimiento, tecnología, Google, DevFest y Sonnet Code.
  - [ ] 🗒️ Revisarlas a mano antes del evento, como pide el aviso del propio archivo.
- [x] ✨ **Niveles fácil, intermedio y difícil.** **Hecho (6 de octubre): el visitante elige el nivel (Sonnia lo pregunta); las 20 preguntas actuales van repartidas 7/7/6; el nivel sale en la pantalla.**
  - [x] Nivel en el formato del archivo, por ejemplo `## [difícil] ¿…?`.
  - [x] 🗒️ Decidir cómo se juega: el visitante elige el nivel, o la partida sube de nivel. **Queda que lo elige el visitante; si prefieres que suba solo, se cambia.**
  - [x] Mostrar el nivel en la pantalla de la trivia. **Hecho: «PREGUNTA 2 DE 5 · DIFÍCIL».**
- [x] ✨ **Premios por nivel:** stickers o pines por participar, gorras por las difíciles. **Hecho (6 de octubre): por jugar «un sticker o un pin de Sonnet Code» y por ganar en difícil «una gorra de Sonnet Code» (`TRIVIA_PRIZE_*`, cambiables); Sonnia lo anuncia y sale en la pantalla final.**
  - [ ] 🗒️ Qué premios hay y cuántos. **Los textos de ahora son provisionales.**
  - [x] Sonnia anuncia el premio al acabar según el resultado, y la pantalla de victoria lo muestra.
- [x] ✨ **Respuestas de «así no funciona la trivia»**, en broma: pedir la respuesta, contestar dos veces, cambiarla tras el veredicto, saltarse preguntas. **Hecho (6 de octubre): en las reglas de la trivia.**
  - [x] En las reglas de la trivia de GPT-Live. Ojo: `instructions.append` corta a 1200 caracteres y hay un test que lo vigila. **Las reglas ocupan 1018 caracteres.**

## 3. Sonnia

- [ ] ✨ **Más gestos con las manos al hablar.** Hoy apenas mueve las manos: el set de Genies no tiene clips de hablar. **En pausa (6 de octubre), por decisión de Jean: se retoma después.**
  - Respaldo ya activo (5fdd48f): gestos de manos por código en `AvatarStateController` (`handGestures`). Al empezar algunas frases, las manos suben delante del cuerpo, abiertas y con golpes en los acentos. Verificado en silencio con capturas 9:16 en la app compilada.
  - Los gestos de verdad del chat de Genies están a medias: `docs/informe-gestos-genies.md` (12 de 48 capturados y el horneado con las piernas rotas). Los datos están en `cache/gestos-genies/`.
  - [ ] Buscar o hacer clips de hablar con manos abiertas y sin atravesar el cuerpo, y pasarlos por **Sonia > Comprobar animaciones (en Play)**.
  - [ ] Que `AvatarChoreographer` los encadene mientras habla.
  - [ ] Verificarlo con capturas 9:16 por fotogramas.
- [x] ✨ **Bailes y animaciones por voz.** Hoy solo desde el panel (`_act_animation` en `server/sonia/panel/control.py`). **Hecho (6 de octubre): acción `play_animation` (`server/sonia/actions/moves.py`) con bailar, saludar, paz, saludo militar, pulgares arriba, celebrar, lamentarse y pensar; busca el clip en el catálogo de Unity y lo lanza entero (`whole`) aunque Sonnia hable. Visto en la app compilada, en silencio: el baile suena entero mientras habla. Falta probarlo con GPT-Live de verdad.**
  - [x] Acción del backend, por ejemplo `play_animation`, con la lista de animaciones que manda Unity, para «¡baila!» o «saluda». Registro, handler, protocolo y Unity en el mismo commit (`CLAUDE.md`).
- [x] ✨ **El staff de Sonnet Code en sus instrucciones:** Bryan (desarrollo), Mariel y Angie (diseño y marketing); Carlos no estará disponible. **Hecho (6 de octubre): equipo de sonnetcode.com/es/about más Elieser Grullon (ciberseguridad) y Mariel Cruz (publicidad), con a quién mandar a cada visitante.**
  - [x] 🗒️ Confirmar apellidos y cargos exactos. **Hecho (6 de octubre): copiados de sonnetcode.com/es/about; Mariel Cruz no sale en la página y queda como encargada de publicidad.**
  - [x] Archivo nuevo `assets/knowledge/08-equipo-sonnet-code.md`: quién es quién en el stand y a quién mandar a la gente según lo que pregunten. **Hecho dentro de `04-sonnet-code.md` (el `08` es la agenda): equipo y a quién mandar a cada visitante según lo que pregunte.**
- [x] ✨ **Su propia descripción física:** **Hecho (6 de octubre), en `server/sonia/persona.py`; sin el color de la camiseta, porque la variante se elige al arrancar la app.** avatar de Genies, camiseta azul del staff con el lockup del DevFest Santo Domingo, STAFF y Sonnet Code; asistente virtual. Va en `server/sonia/persona.py`.
- [ ] ✨ **Camiseta igual a la oficial.**
  - [ ] 🗒️ Foto de la camiseta real de staff de este año (Delia o Mariel).
  - [ ] Ajustar color, estampa y patrocinadores en `scripts/camiseta_staff/genera.py` (docs/unity.md, «Camiseta de staff»).
  - [ ] 🗒️ Mientras tanto, elegir variante (azul, negra o blanca) y dejarla en `GeniesStaffShirt.DefaultVariant`.

## 4. Builds y reparto 📦

- [x] **Recompilar todo tras los arreglos de arriba.** **Hecho (6 de octubre, 22:06): stand y pruebas, macOS y Windows, con los orquestadores congelados de nuevo. Llevan los bailes por voz, la descripción física, los gestos por código, la trivia con los arreglos del registro de la demo, la agenda y los cargos reales y el último avatar guardado.**
  - [x] macOS (Apple Silicon): `unity/Build/Sonnia-macOS.zip` y `Sonnia-pruebas-macOS.zip`. Probada en silencio con el orquestador falso.
  - [x] Windows: `unity/Build/Sonnia-Windows.zip` y `Sonnia-pruebas-Windows.zip`, con el orquestador del workflow `orquestador-windows.yml`. Sin probar en un PC de verdad.
  - [x] Mac Intel: no se puede (ver bugs).
  - [x] Rehacer los zips de `unity/Build/`. Las de pruebas llevan `build.env` con `PANEL_CAMERA_STREAM=false` y `TRIAL_LIMIT_MINUTES=60`: una hora de conversación en total y después se quedan fuera con el letrero «La prueba de Sonnia ha terminado».
  - [x] Instrucciones para el equipo: `docs/pruebas-equipo.md` y, para mandarlas con los zips, `unity/Build/Instrucciones-pruebas-Sonnia.docx`.
  - [ ] 🗒️ Probar la build de Windows en un PC con Windows (Jean o el equipo).
  - [ ] 🗒️ Repartir las de pruebas por un canal privado: llevan la clave de OpenAI en el `.env`.

## Hecho el 6 de octubre

- [x] Agenda real del DevFest (devfest.gdgsantodomingo.org/schedule) en la base de conocimiento; fuera la de prueba.
- [x] Builds de prueba para el equipo sin cámara ni micrófono en el panel (`PANEL_CAMERA_STREAM=false`): `unity/Build/Sonnia-pruebas-macOS.zip` y `Sonnia-pruebas-Windows.zip`.
- [x] Nombre escrito «Sonnia» (hablado sigue siendo «Sonia»).
- [x] Panel con varias Sonias a la vez, sin necesidad de nombres.
- [x] Build de Windows desde el Mac y orquestador de Windows por GitHub Actions.
- [x] Modo reunión (`sonia reunion`): Sonnia ve la reunión por OBS y tiene instrucciones de Google Meet.
- [x] Demo al equipo por Google Meet.
- [x] Camiseta de staff en azul, negra y blanca, horneada sobre la prenda de Genies, sin el trozo en la manga.
