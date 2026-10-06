# Pendientes tras la demo al equipo (6 de octubre de 2026)

Lo que salió de la demo de Sonnia al equipo por Google Meet, más lo que ya estaba
abierto. Faltan tres días para el DevFest (9 y 10 de octubre). Orden: primero lo
que rompe la demo, luego lo que la mejora y al final lo que no es código. Al
terminar algo, marca su casilla y apunta la fecha. El histórico está en `ROADMAP.md`.

Leyenda: 🐞 bug · ✨ mejora · 📦 build o reparto · 🗒️ decisión o tarea fuera del código.

## 1. Bugs

- [x] 🐞 **La trivia marca como incorrectas algunas respuestas correctas.** En la demo, alguien dijo la opción correcta y Sonnia la dio por mala. **Hecho (6 de octubre): la causa era que la partida pasaba sola a la siguiente pregunta a los 4 s mientras Sonnia ya la leía; una respuesta en ese hueco se perdía y la cuenta se desfasaba. Ahora la siguiente solo sale con `trivia_next`.**
  - Dónde mirar:
    - GPT-Live entiende la respuesta y delega `trivia_answer` con una letra (`server/sonia/actions/trivia.py`).
    - El orquestador la compara con la clave en `TriviaGame.answer` (`server/sonia/trivia/game.py`).
    - Las opciones se barajan en cada partida: la letra tiene que ser la de la pantalla.
  - Sospechas, por orden:
    1. GPT-Live pasa la letra de la pregunta anterior: la respuesta llega cuando ya cambió de pregunta.
    2. Confunde la opción leída con su letra.
    3. Se registra «no lo sé» en vez de la letra.
  - [ ] Buscar en el registro de la demo (`orquestador-*.log` o la salida de `sonia reunion`) las líneas de `trivia_answer`, con la pregunta, la letra recibida y la clave.
  - [ ] Reproducirlo con un test sin red.
  - [ ] Que el guion «PARA SONIA:» repita cada letra con el texto de su opción, para que GPT-Live no tenga que deducirla.
  - [ ] Partida de prueba: aciertan las 5 respuestas dichas de varias formas («la B», «la segunda», el texto de la opción).

- [x] 🐞 **La trivia se quedó congelada en la pregunta 5 y nunca terminó.** En la demo, la pantalla de la trivia se quedó en la quinta pregunta y Sonnia no llegó a cerrar la partida (sin veredicto final ni pantalla de victoria o derrota). **Hecho (6 de octubre): misma causa; además, la última respuesta siempre cierra la partida y hay un test de partida entera.**
  - [ ] Ver en el registro qué pasó tras la respuesta a la 5: si llegó `trivia_answer`, qué devolvió y si se mandó a Unity el mensaje de fin.
  - [ ] Que la última respuesta cierre siempre la partida, aunque GPT-Live no delegue nada más, y que la pantalla no se quede colgada si se pierde un mensaje.
  - [ ] Test que juegue una partida entera hasta el final.

- [x] 🐞 **No hay app para el Mac antiguo (anterior a M1).** `Sonnia.app` y su orquestador congelado son solo arm64 (comprobado con `file`). **Hecho (6 de octubre): BLOQUEADO: todas las librerías nativas de Genies para macOS son solo arm64 (`lipo -archs`), así que en un Mac Intel no carga el avatar. Esa persona puede usar la build de Windows en un PC.**
  - [ ] Compilar la app de Unity para macOS como Universal o x64 (arquitectura de macOS en `PlayerSettings` de Standalone).
  - [ ] Congelar el orquestador para x86_64: en un Mac Intel o con un workflow en el runner `macos-13` de GitHub (Intel), como el de Windows.
  - [ ] Confirmar que las librerías nativas de Genies traen x86_64 (`lipo -info` sobre las `.dylib` del SDK).
  - [ ] Probarla en ese Mac: arranca, carga a Sonnia y conversa.

## 2. Trivia

- [x] ✨ **Preguntar antes de pasar a la siguiente.** Hoy pasa sola tras el veredicto. **Hecho (6 de octubre): Sonnia explica la respuesta, pregunta si siguen y espera; la siguiente sale con `trivia_next` (o el botón del panel).**
  - [ ] Que la acción no devuelva ya la siguiente pregunta en el guion: Sonnia da el veredicto y el dato, y pregunta «¿lista para la siguiente?» o «¿seguimos?».
  - [ ] Acción «siguiente pregunta» que GPT-Live delega cuando el visitante dice que sí. Si dice que no, se termina la trivia.
- [ ] ✨ **Banco de unas 300 preguntas, sin repetir.** Hoy hay 20 en `assets/trivia/preguntas.md` y se sacan 5 al azar por partida.
  - [ ] Recordar las ya hechas (en `cache/`, por equipo) y no repetirlas hasta agotar el banco.
  - [ ] Escribir las preguntas: base de conocimiento, tecnología, Google, DevFest y Sonnet Code.
  - [ ] 🗒️ Revisarlas a mano antes del evento, como pide el aviso del propio archivo.
- [x] ✨ **Niveles fácil, intermedio y difícil.** **Hecho (6 de octubre): el visitante elige el nivel (Sonnia lo pregunta); las 20 preguntas actuales van repartidas 7/7/6; el nivel sale en la pantalla.**
  - [ ] Nivel en el formato del archivo, por ejemplo `## [difícil] ¿…?`.
  - [ ] 🗒️ Decidir cómo se juega: el visitante elige el nivel, o la partida sube de nivel.
  - [ ] Mostrar el nivel en la pantalla de la trivia.
- [x] ✨ **Premios por nivel:** stickers o pines por participar, gorras por las difíciles. **Hecho (6 de octubre): por jugar «un sticker o un pin de Sonnet Code» y por ganar en difícil «una gorra de Sonnet Code» (`TRIVIA_PRIZE_*`, cambiables); Sonnia lo anuncia y sale en la pantalla final.**
  - [ ] 🗒️ Qué premios hay y cuántos.
  - [ ] Sonnia anuncia el premio al acabar según el resultado, y la pantalla de victoria lo muestra.
- [x] ✨ **Respuestas de «así no funciona la trivia»**, en broma: pedir la respuesta, contestar dos veces, cambiarla tras el veredicto, saltarse preguntas. **Hecho (6 de octubre): en las reglas de la trivia.**
  - [ ] En las reglas de la trivia de GPT-Live. Ojo: `instructions.append` corta a 1200 caracteres y hay un test que lo vigila.

## 3. Sonnia

- [ ] ✨ **Más gestos con las manos al hablar.** Hoy apenas mueve las manos: el set de Genies no tiene clips de hablar.
  - [ ] Buscar o hacer clips de hablar con manos abiertas y sin atravesar el cuerpo, y pasarlos por **Sonia > Comprobar animaciones (en Play)**.
  - [ ] Que `AvatarChoreographer` los encadene mientras habla.
  - [ ] Verificarlo con capturas 9:16 por fotogramas.
- [ ] ✨ **Bailes y animaciones por voz.** Hoy solo desde el panel (`_act_animation` en `server/sonia/panel/control.py`).
  - [ ] Acción del backend, por ejemplo `play_animation`, con la lista de animaciones que manda Unity, para «¡baila!» o «saluda». Registro, handler, protocolo y Unity en el mismo commit (`CLAUDE.md`).
- [x] ✨ **El staff de Sonnet Code en sus instrucciones:** Bryan (desarrollo), Mariel y Angie (diseño y marketing); Carlos no estará disponible. **Hecho (6 de octubre): equipo de sonnetcode.com/es/about más Elieser Grullon (ciberseguridad) y Mariel Cruz (publicidad), con a quién mandar a cada visitante.**
  - [ ] 🗒️ Confirmar apellidos y cargos exactos.
  - [ ] Archivo nuevo `assets/knowledge/08-equipo-sonnet-code.md`: quién es quién en el stand y a quién mandar a la gente según lo que pregunten.
- [ ] ✨ **Su propia descripción física:** avatar de Genies, camiseta azul del staff con el lockup del DevFest Santo Domingo, STAFF y Sonnet Code; asistente virtual. Va en `server/sonia/persona.py`.
- [ ] ✨ **Camiseta igual a la oficial.**
  - [ ] 🗒️ Foto de la camiseta real de staff de este año (Delia o Mariel).
  - [ ] Ajustar color, estampa y patrocinadores en `scripts/camiseta_staff/genera.py` (docs/unity.md, «Camiseta de staff»).
  - [ ] 🗒️ Mientras tanto, elegir variante (azul, negra o blanca) y dejarla en `GeniesStaffShirt.DefaultVariant`.

## 4. Builds y reparto 📦

- [ ] **Recompilar todo tras los arreglos de arriba.** Las de `unity/Build/` son anteriores al arreglo de la manga y solo llevan la camiseta azul.
  - [ ] macOS (Apple Silicon).
  - [ ] Windows: antes, el orquestador congelado con `gh workflow run orquestador-windows.yml` y descargar el artefacto (docs/unity.md, «Build de Windows»).
  - [ ] Mac Intel (ver bugs).
  - [ ] Rehacer los zips de `unity/Build/`.

## Hecho el 6 de octubre

- [x] Agenda real del DevFest (devfest.gdgsantodomingo.org/schedule) en la base de conocimiento; fuera la de prueba.
- [x] Builds de prueba para el equipo sin cámara ni micrófono en el panel (`PANEL_CAMERA_STREAM=false`): `unity/Build/Sonnia-pruebas-macOS.zip` y `Sonnia-pruebas-Windows.zip`.
- [x] Nombre escrito «Sonnia» (hablado sigue siendo «Sonia»).
- [x] Panel con varias Sonias a la vez, sin necesidad de nombres.
- [x] Build de Windows desde el Mac y orquestador de Windows por GitHub Actions.
- [x] Modo reunión (`sonia reunion`): Sonnia ve la reunión por OBS y tiene instrucciones de Google Meet.
- [x] Demo al equipo por Google Meet.
- [x] Camiseta de staff en azul, negra y blanca, horneada sobre la prenda de Genies, sin el trozo en la manga.
