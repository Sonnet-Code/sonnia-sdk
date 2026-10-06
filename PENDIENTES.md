# Pendientes tras la demo al equipo (6 de octubre de 2026)

Lo que salió de la demo de Sonnia al equipo por Google Meet, más lo que ya estaba
abierto. Faltan tres días para el DevFest (9 y 10 de octubre). Orden: primero lo
que rompe la demo, luego lo que la mejora y al final lo que no es código. El resto
del histórico está en `ROADMAP.md`.

Leyenda: 🐞 bug · ✨ mejora · 📦 build o reparto · 🗒️ decisión o tarea fuera del código.

## 1. Bugs

### 🐞 La trivia marca como incorrectas algunas respuestas correctas
- **Qué pasó:** en la demo, alguien dijo la opción correcta y Sonnia la dio por mala.
- **Dónde mirar:**
  - GPT-Live entiende la respuesta y delega `trivia_answer` con una letra (`server/sonia/actions/trivia.py`).
  - El orquestador la compara con la clave en `TriviaGame.answer` (`server/sonia/trivia/game.py`).
  - Las opciones se barajan en cada partida, así que la letra que dice el visitante tiene que ser la de la pantalla, no la del archivo.
- **Sospechas, por orden:**
  1. GPT-Live pasa la letra de una pregunta anterior: la respuesta llega cuando ya cambió de pregunta.
  2. GPT-Live confunde la opción leída con su letra, porque las opciones barajadas no coinciden con el orden en que las leyó.
  3. Se registra «no lo sé» en vez de la letra.
- **Cómo:**
  - Buscar en el registro de la demo (`orquestador-*.log` del equipo donde corrió, o la salida de `sonia reunion`) las líneas de `trivia_answer` con la pregunta, la letra recibida y la clave.
  - Reproducirlo con un test sin red.
  - Hacer que el guion «PARA SONIA:» de cada pregunta repita la letra con el texto de cada opción, para que GPT-Live no tenga que deducirla.
- **Hecho cuando:** un test cubre el caso y en una partida de prueba aciertan las 5 respuestas dichas de varias formas («la B», «la segunda», el texto de la opción).

### 🐞 No hay app para el Mac antiguo (anterior a M1)
- **Qué pasa:** `Sonnia.app` y su orquestador congelado son solo arm64 (comprobado con `file`), así que no arrancan en un Mac Intel.
- **Cómo:**
  - **Unity:** compilar macOS como Universal o x64 (`PlayerSettings` de Standalone, arquitectura de macOS).
  - **Orquestador:** congelarlo para x86_64, ya sea en un Mac Intel o en el runner `macos-13` de GitHub Actions (Intel), con un workflow como el de Windows.
  - **Genies:** confirmar que sus librerías nativas de macOS traen x86_64 (`lipo -info` sobre las `.dylib` del SDK).
- **Hecho cuando:** la app arranca en ese Mac, carga a Sonnia y conversa.

## 2. Trivia

### ✨ Preguntar antes de pasar a la siguiente
- Hoy pasa sola a la siguiente pregunta tras el veredicto.
- Tiene que dar el veredicto y el dato, y preguntar «¿lista para la siguiente?» o «¿seguimos?». La siguiente sale cuando el visitante dice que sí. Si dice que no, se termina la trivia.
- **Cómo:** que la acción no devuelva ya la siguiente pregunta en el guion. GPT-Live pregunta y delega una acción «siguiente pregunta» cuando el visitante acepta. Va en la línea de dejar a GPT-Live interpretar, no un parser.

### ✨ Banco de unas 300 preguntas, sin repetir
- Hoy hay 20 en `assets/trivia/preguntas.md` y se sacan 5 al azar en cada partida.
- **Rotar sin repetir:** recordar las ya hechas (en `cache/`, por equipo) y no volver a sacarlas hasta agotar el banco.
- **Escribir las preguntas:** de la base de conocimiento, tecnología, Google, DevFest y Sonnet Code. Hay que revisarlas a mano, como pide el aviso del propio archivo.

### ✨ Niveles fácil, intermedio y difícil
- Añadir el nivel a cada pregunta en el formato del archivo, por ejemplo `## [difícil] ¿…?`.
- Elegir cómo se juega: el visitante elige el nivel, o la partida sube de nivel.
- Mostrar el nivel en la pantalla de la trivia.

### ✨ Premios por nivel
- Stickers o pines por participar y gorras por las difíciles.
- Sonnia anuncia el premio al acabar según el resultado, y la pantalla de victoria lo muestra.
- Falta saber qué premios hay y cuántos (🗒️ equipo).

### ✨ Respuestas de «así no funciona la trivia»
- Para cuando alguien hace trampa o pide la respuesta, contesta dos veces, cambia la respuesta tras el veredicto o intenta saltarse preguntas.
- Van en las reglas de la trivia de GPT-Live, con tono de broma.
- Las reglas se mandan por `instructions.append`, que corta a 1200 caracteres, y hay un test que lo vigila.

## 3. Sonnia

### ✨ Más gestos con las manos al hablar
- Hoy apenas mueve las manos mientras habla. El set de animaciones de Genies no tiene clips de hablar (ver la memoria de la migración y `docs/unity.md`).
- **Cómo:**
  - Buscar o hacer clips de hablar validados, con manos abiertas y sin atravesar el cuerpo (**Sonia > Comprobar animaciones (en Play)**).
  - Que `AvatarChoreographer` los encadene mientras habla.
  - Verificarlo con capturas 9:16 por fotogramas.

### ✨ Bailes y animaciones por voz
- Hoy solo se lanzan desde el panel (`_act_animation` en `server/sonia/panel/control.py`).
- **Cómo:** una acción del backend, por ejemplo `play_animation`, con la lista de animaciones que manda Unity, para que GPT-Live la delegue cuando le piden «¡baila!» o «saluda». Según `CLAUDE.md` van registro, handler, protocolo y Unity en el mismo commit.

### ✨ Instrucciones: el staff de Sonnet Code y su propia descripción
- **Staff:** Bryan (desarrollo), Mariel y Angie (diseño y marketing). Carlos no estará disponible.
  - Va en un archivo nuevo de `assets/knowledge/`, por ejemplo `08-equipo-sonnet-code.md`.
  - Contenido: quién es quién en el stand y a quién mandar a la gente según lo que pregunten.
- **Cómo es ella:** avatar de Genies, camiseta azul del staff con el lockup del DevFest Santo Domingo, STAFF y Sonnet Code, sin dejar de ser asistente virtual. Va en `server/sonia/persona.py`.
- 🗒️ Confirmar apellidos y cargos exactos antes de escribirlos.

### ✨ Camiseta: igualarla a la oficial
- Delia o Mariel mandan la foto de la camiseta real de staff de este año.
- Ajustar color, estampa y patrocinadores en `scripts/camiseta_staff/genera.py` (docs/unity.md, «Camiseta de staff»).
- 🗒️ Mientras tanto, elegir variante, azul, negra o blanca, y dejarla por defecto en `GeniesStaffShirt.DefaultVariant`.

## 4. Builds y reparto 📦

- **Recompilar todo tras los arreglos de arriba.** La de macOS y la de Windows de `unity/Build/` son anteriores al arreglo de la manga de la camiseta y solo llevan la azul.
  - Windows: el orquestador congelado sale del workflow de GitHub (`gh workflow run orquestador-windows.yml` y descargar el artefacto). Ver docs/unity.md, «Build de Windows».
- **A quién:**
  - Mac (Apple Silicon): Mariel y Bryan.
  - Windows: Lizeth.
  - Mac Intel: ver el bug de arriba.
- **Cómo repartir:** el zip de `unity/Build/`, nunca por git, porque lleva la clave en el `.env`. Mejor por un enlace privado y que caduque.
- **El acceso al panel** (dirección y contraseña) se manda aparte y no se escribe en ningún archivo del repo.
- **Probar la app de Windows en un Windows de verdad**, porque nunca se ha hecho:
  - que Genies cargue a Sonnia con Vulkan;
  - que el micrófono abra a 24 kHz (si no, `LIVE_SAMPLE_RATE=16000`);
  - cámara y panel.

## 5. Antes y durante el evento

- **Ensayo en un sitio ruidoso.**
  - Probarla en un lugar público con ruido parecido al del pasillo.
  - Calibrar «Ruido del pasillo» en el panel (`LIVE_GATE_RMS`) y ver si se contesta sola o se corta.
  - Si molesta, mirar primero el micrófono (direccional o de diadema) y dónde van los altavoces (`docs/stand.md`).
- **Reiniciar el contexto entre bloques:**
  - Al empezar cada día y entre mañana, almuerzo y tarde, con «Reiniciar conversación» en el panel.
  - En el stand ya se reinicia sola tras 2 minutos sin nadie (`IDLE_RESET_SECONDS`).
  - ✨ Opcional: reinicios a horas fijas.
- **Coste:** en «Conversando» son unos 3 USD por hora (unos 30 USD los dos días). Pasarla a «Solo saludos» o «Fuera» cuando no haga falta.
- **Subtítulos:** dejarlos activados en el stand, por el ruido.

## 6. QR y redes

- ✨ **El QR del stand** (`StageScreen`, hoy a sonnetcode.com/es) debe llevar a una página con la web, Instagram y LinkedIn.
  - Puede ser una página de sonnetcode.com o una ruta del Worker de Cloudflare.
  - 🗒️ El «sigue las dos cuentas antes de jugar» no se puede comprobar solo: o lo verifica el staff, o Sonnia lo pide de palabra antes de la trivia.
- 🗒️ **Redes (Mariel):** publicaciones de esta semana sobre el DevFest y grabar a gente hablando con Sonnia para reels y TikTok.

## 7. Fuera de este evento

- Panel autoservicio para configurar avatar, personalidad y base de conocimiento (Sonnia como producto para cualquier evento).
- Varios avatares por equipo, uno por especialidad.
- Una voz en español nativo cuando GPT-Live la tenga: hoy suena con acento no nativo y es una limitación del modelo.
- Dirección visual en manos de Mariel: diseño 2D y 3D, pantalla y avatar.

## Hecho en esta sesión (6 de octubre)

- Nombre escrito «Sonnia» (hablado sigue siendo «Sonia»).
- Panel con varias Sonias a la vez, sin necesidad de nombres.
- Build de Windows desde el Mac y orquestador de Windows por GitHub Actions.
- Modo reunión (`sonia reunion`): Sonnia ve la reunión por OBS, tiene instrucciones de Google Meet y una agenda de prueba en `assets/knowledge-prueba`.
- Camiseta de staff en azul, negra y blanca, horneada sobre la prenda de Genies, sin el trozo en la manga.
