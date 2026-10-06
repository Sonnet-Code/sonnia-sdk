# Pendientes tras la demo al equipo (6 de octubre de 2026)

Lo que salió de la demo de Sonnia al equipo por Google Meet, más lo que ya estaba
abierto. Faltan tres días para el DevFest (9 y 10 de octubre). Orden: primero lo
que rompe la demo, luego lo que la mejora y al final lo que no es código. Al
terminar algo, marca su casilla y apunta la fecha. El histórico está en `ROADMAP.md`.

Leyenda: 🐞 bug · ✨ mejora · 📦 build o reparto · 🗒️ decisión o tarea fuera del código.

## 1. Bugs

- [ ] 🐞 **La trivia marca como incorrectas algunas respuestas correctas.** En la demo, alguien dijo la opción correcta y Sonnia la dio por mala.
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

- [ ] 🐞 **No hay app para el Mac antiguo (anterior a M1).** `Sonnia.app` y su orquestador congelado son solo arm64 (comprobado con `file`).
  - [ ] Compilar la app de Unity para macOS como Universal o x64 (arquitectura de macOS en `PlayerSettings` de Standalone).
  - [ ] Congelar el orquestador para x86_64: en un Mac Intel o con un workflow en el runner `macos-13` de GitHub (Intel), como el de Windows.
  - [ ] Confirmar que las librerías nativas de Genies traen x86_64 (`lipo -info` sobre las `.dylib` del SDK).
  - [ ] Probarla en ese Mac: arranca, carga a Sonnia y conversa.

## 2. Trivia

- [ ] ✨ **Preguntar antes de pasar a la siguiente.** Hoy pasa sola tras el veredicto.
  - [ ] Que la acción no devuelva ya la siguiente pregunta en el guion: Sonnia da el veredicto y el dato, y pregunta «¿lista para la siguiente?» o «¿seguimos?».
  - [ ] Acción «siguiente pregunta» que GPT-Live delega cuando el visitante dice que sí. Si dice que no, se termina la trivia.
- [ ] ✨ **Banco de unas 300 preguntas, sin repetir.** Hoy hay 20 en `assets/trivia/preguntas.md` y se sacan 5 al azar por partida.
  - [ ] Recordar las ya hechas (en `cache/`, por equipo) y no repetirlas hasta agotar el banco.
  - [ ] Escribir las preguntas: base de conocimiento, tecnología, Google, DevFest y Sonnet Code.
  - [ ] 🗒️ Revisarlas a mano antes del evento, como pide el aviso del propio archivo.
- [ ] ✨ **Niveles fácil, intermedio y difícil.**
  - [ ] Nivel en el formato del archivo, por ejemplo `## [difícil] ¿…?`.
  - [ ] 🗒️ Decidir cómo se juega: el visitante elige el nivel, o la partida sube de nivel.
  - [ ] Mostrar el nivel en la pantalla de la trivia.
- [ ] ✨ **Premios por nivel:** stickers o pines por participar, gorras por las difíciles.
  - [ ] 🗒️ Qué premios hay y cuántos.
  - [ ] Sonnia anuncia el premio al acabar según el resultado, y la pantalla de victoria lo muestra.
- [ ] ✨ **Respuestas de «así no funciona la trivia»**, en broma: pedir la respuesta, contestar dos veces, cambiarla tras el veredicto, saltarse preguntas.
  - [ ] En las reglas de la trivia de GPT-Live. Ojo: `instructions.append` corta a 1200 caracteres y hay un test que lo vigila.

## 3. Sonnia

- [ ] ✨ **Más gestos con las manos al hablar.** Hoy apenas mueve las manos: el set de Genies no tiene clips de hablar.
  - [ ] Buscar o hacer clips de hablar con manos abiertas y sin atravesar el cuerpo, y pasarlos por **Sonia > Comprobar animaciones (en Play)**.
  - [ ] Que `AvatarChoreographer` los encadene mientras habla.
  - [ ] Verificarlo con capturas 9:16 por fotogramas.
- [ ] ✨ **Bailes y animaciones por voz.** Hoy solo desde el panel (`_act_animation` en `server/sonia/panel/control.py`).
  - [ ] Acción del backend, por ejemplo `play_animation`, con la lista de animaciones que manda Unity, para «¡baila!» o «saluda». Registro, handler, protocolo y Unity en el mismo commit (`CLAUDE.md`).
- [ ] ✨ **El staff de Sonnet Code en sus instrucciones:** Bryan (desarrollo), Mariel y Angie (diseño y marketing); Carlos no estará disponible.
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
- [ ] **Repartir** por un enlace privado que caduque, nunca por git, porque llevan la clave en el `.env`:
  - [ ] Mac: Mariel y Bryan.
  - [ ] Windows: Lizeth.
  - [ ] Mac Intel: quien lo use.
  - [ ] 🗒️ Mandar aparte la dirección y la contraseña del panel. No se escriben en ningún archivo del repo.
- [ ] **Probar la app de Windows en un Windows de verdad.** Nunca se ha hecho.
  - [ ] Genies carga a Sonnia con Vulkan.
  - [ ] El micrófono abre a 24 kHz (si no, `LIVE_SAMPLE_RATE=16000`).
  - [ ] Cámara y panel.

## 5. Antes y durante el evento

- [ ] **Ensayo en un sitio ruidoso**, con ruido parecido al del pasillo.
  - [ ] Calibrar «Ruido del pasillo» en el panel (`LIVE_GATE_RMS`).
  - [ ] Ver si se contesta sola o se corta. Si molesta, mirar primero el micrófono (direccional o de diadema) y dónde van los altavoces (`docs/stand.md`).
- [ ] **Reiniciar el contexto** al empezar cada día y entre bloques (mañana, almuerzo, tarde) con «Reiniciar conversación» en el panel. En el stand ya se reinicia sola tras 2 minutos sin nadie (`IDLE_RESET_SECONDS`).
  - [ ] ✨ Opcional: reinicios a horas fijas.
- [ ] **Coste:** en «Conversando» son unos 3 USD por hora (unos 30 USD los dos días). Pasarla a «Solo saludos» o «Fuera» cuando no haga falta.
- [ ] **Subtítulos activados** en el stand, por el ruido.

## 6. QR y redes

- [ ] ✨ **QR del stand** (`StageScreen`, hoy a sonnetcode.com/es) a una página con la web, Instagram y LinkedIn.
  - [ ] 🗒️ Dónde va la página: sonnetcode.com o una ruta del Worker de Cloudflare.
  - [ ] 🗒️ «Seguir las dos cuentas antes de jugar» no se puede comprobar solo: o lo verifica el staff, o Sonnia lo pide de palabra antes de la trivia.
- [ ] 🗒️ **Redes (Mariel):** publicaciones de esta semana sobre el DevFest.
- [ ] 🗒️ **Grabar a gente hablando con Sonnia** para reels y TikTok.

## 7. Fuera de este evento

- [ ] Panel autoservicio para configurar avatar, personalidad y base de conocimiento (Sonnia como producto para cualquier evento).
- [ ] Varios avatares por equipo, uno por especialidad.
- [ ] Voz en español nativo cuando GPT-Live la tenga. Hoy suena con acento no nativo: es una limitación del modelo.
- [ ] Dirección visual en manos de Mariel: diseño 2D y 3D, pantalla y avatar.

## Hecho el 6 de octubre

- [x] Nombre escrito «Sonnia» (hablado sigue siendo «Sonia»).
- [x] Panel con varias Sonias a la vez, sin necesidad de nombres.
- [x] Build de Windows desde el Mac y orquestador de Windows por GitHub Actions.
- [x] Modo reunión (`sonia reunion`): Sonnia ve la reunión por OBS, tiene instrucciones de Google Meet y una agenda de prueba en `assets/knowledge-prueba`.
- [x] Demo al equipo por Google Meet.
- [x] Camiseta de staff en azul, negra y blanca, horneada sobre la prenda de Genies, sin el trozo en la manga.
