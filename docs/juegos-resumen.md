# Juegos del stand: estado para Jean (10 de octubre de 2026)

## Entrega de la mañana: 1.0.460 (la que va al stand)

Encargos de Jean de las 05:05 a las 05:30, en Santo Domingo. Los coordinó «sonia-e6» y los hizo «sonia-af».

- **App para el stand: 1.0.460**, solo macOS (el equipo es un Mac M3 Pro). Compilada desde `main` en `1f083b5`.
  - `Sonnia-macOS-1.0.460.zip`: SHA-256 `2468ccf398cd4c56e036ff1d80212d8edd3fecb86726d8c6c45bc71ac9f2c77c`.
  - Está en `~/Documents/git/sonia-entrega/1.0.460/`, con su `LEEME.txt`, y en `~/Documents/git/sonia/unity/Build/`.
  - Reserva: la 1.0.391 de anoche (abajo).
- **Panel de la nube:** desplegado el 10 de octubre a las ~06:38 con «Añadir imagen», «Control del juego» y el selector del juez. Versión del Worker `0f699541-55ad-4f7e-a215-9a598325e141`. Para volver a la de anoche: `cd cloud/panel && npx wrangler rollback 33c2771a-9388-4e1a-9d6e-52bdfc6d2f1a`. Las apps viejas ven esos controles desactivados, con su aviso.

### Qué trae

- **Gemini juzga los juegos de cámara** (`GAMES_JUDGE=gemini`). Manda una foto reducida por ronda de Simón dice y de piedra, papel o tijera, y las miradas de la búsqueda.
  - Si no contesta en 4 s, decide la detección local; en la búsqueda, el modelo de visión de siempre.
  - **Se cambia en caliente desde el panel**, en «Juez de las rondas de cámara» de la tarjeta Juegos, en todas las Sonnias y sin tocar archivos. Es la red de seguridad si Gemini va lento o falla.
  - En Simón dice, cuántos juegan lo dice la detección local, porque Gemini también cuenta a la gente de paso del fondo.
- **Aviso de espera:** una pastilla arriba, sin tapar a Sonnia, con estos textos:
  - «Pensando…», con cualquier tarea delegada que dure más de 0,3 s.
  - «Buscando en internet…».
  - «Preparando el juego…».
  - «Encendiendo la cámara…».
  - «Mirando las poses…», «Mirando tu mano…» y «Mirando lo que enseñas…», mientras juzga Gemini.
- **«Control del juego» en el panel**, para llevar cada juego a mano si falla la voz o la cámara. Todos tienen «Reiniciar» y «Terminar», con confirmación.

  | Juego | Botones |
  |---|---|
  | Ruleta | Girar, Acertó/Falló, las letras de la trivia… |
  | Akinator | Sí/No/No sé, Acertó/Falló |
  | Wordle | Probar palabra, Ver la palabra |
  | Simón dice | Lo hicieron/No lo hicieron, Siguiente orden |
  | Piedra, papel o tijera | Piedra/Papel/Tijera, Otra ronda |
  | Búsqueda | ¡Lo encontró!, Saltar objeto |

- **«Añadir imagen» en «Mostrar una imagen»** (también desde el móvil).
  - El navegador la reduce y Sonnia la guarda en su carpeta de datos, con el id `subida-<nombre>-<hora>`.
  - La «×» solo quita las subidas.
- **Ruleta sin preguntas sobre Sonnet Code:** solo retos (lo hizo sonia-e6 en `main`).
- **Búsqueda:** lo que se lleva colgado, como el gafete del evento o su cordón azul, no cuenta salvo que se levante y se enseñe a la cámara. Con «algo azul», Gemini daba por buenos los cordones de las acreditaciones.

### Pruebas hechas

- **Tests:** 1635 sin red. El C# se compiló para el editor, macOS y Windows.
- **Pastilla:** capturas 9:16 revisadas, en reposo, conversando y en los juegos, con su entrada y su salida.
- **Con la API real**, unos 10 min de GPT-Live y unas 110 llamadas a Gemini (≈0,55 USD), con Unity de verdad y fotos públicas como cámara:
  - **Simón dice:** 5 de 6 rondas bien. La que falla es una foto difícil, de espaldas y saltando.
  - **Piedra, papel o tijera:** Gemini lee bien las manos que la detección local no veía o leía mal, como la tijera.
  - **Búsqueda:** encuentra el objeto, no se deja engañar por el señuelo y corta a tiempo.
  - **Banco de pruebas de sonia-e6:** 80 fotos, con números en `docs/juegos.md` y `docs/juegos-vision.md`.
- **Panel de la nube:** probado antes de desplegar con un Worker local y dos Sonnias a la vez, la de hoy y la de `main` de anoche. Sin errores de JS:
  - la subida de una imagen pasa por la nube;
  - las apps viejas ven los controles nuevos desactivados.
- **La app 1.0.460 sacada del zip:** se abrió con su orquestador y su firma es válida. Se probaron un Wordle llevado con «Control del juego», subir y quitar una imagen y cambiar el juez.

### A tener en cuenta en el stand

- **Si Gemini va lento o falla,** «Juez de las rondas de cámara» → «Local».
- **Piedra, papel o tijera:** si alguien saca la mano muy tarde o la tapa, puede que se juzgue el puño de la cuenta. El equipo lo corrige con los botones «Piedra/Papel/Tijera».
- **La pastilla «Pensando…» sale a menudo** porque sale en cada tarea delegada: es lo que se pidió.
- **Sin probar:** la cámara del stand con gente de verdad, y el panel en un móvil de verdad (se emuló uno de 430 px).
- **Va aparte, en la 2.ª versión de media mañana** (rama `prompts/base`): el editor de todos los prompts de Sonnia en Developer, con prioridad de la nube.

---

## Entrega de la noche: 1.0.391 (ahora de reserva)


Resumen del trabajo de la noche del 9 al 10 de octubre: la sesión principal fue «sonia-af» y coordinó «sonia-e6». El plan está en `docs/plan-juegos.md` y el detalle técnico en `docs/juegos.md`, `docs/juegos-unity.md`, `docs/juegos-vision.md` y `docs/juegos/<juego>.md`.

### Entrega

- **App para el stand: 1.0.391**, compilada desde `main` en `b31a357` («Fusiona los juegos nuevos del stand»).
  - `Sonnia-macOS-1.0.391.zip`: SHA-256 `6f22c4c25fddeeffd4330a4841dee21fd1b2e5b7e0cb2473f65a4dbfe97e2ccf`.
  - `Sonnia-Windows-x64-1.0.391.zip`: SHA-256 `cb10eab07b5ef55db1ce65dcd6c579bfb4eac5de7fcdcc4b8f12b011895b6500`.
  - Están en `~/Documents/git/sonia/unity/Build/` y en `~/Documents/git/sonia-entrega/1.0.391/`, con su `LEEME.txt`.
- **Reserva 1.0.389:** el mismo código, sin los `.meta` (de `88e8e6d`), en `~/Documents/git/sonia-reserva/1.0.389/` y también en `unity/Build/`.
- **Reserva anterior a los juegos:** la 1.0.199, en `~/Documents/git/sonia-reserva/1.0.199/`.
- **Panel de la nube:** desplegado con los controles de los juegos, versión del Worker `33c2771a-9388-4e1a-9d6e-52bdfc6d2f1a`. Para volver a la anterior: `cd cloud/panel && npx wrangler rollback b52595a5-c9e3-4bd7-b8b8-0c165016aaa0`. Las apps 1.0.195 y 1.0.199 siguen funcionando con él: sus controles de juegos salen desactivados (se probó con dos Sonnias, una vieja y otra nueva, conectadas a la vez a un Worker local).

### Qué hay

- **Seis juegos**, uno cada vez y nunca a la vez que la trivia. Son la ruleta de Sonnia (cinco retos), el Wordle de tecnología, el Akinator dev, la búsqueda relámpago, Simón dice con poses y piedra, papel o tijera (con la mano de Sonnia hecha por código y validada por fotogramas).
  - GPT-Live delega empezarlos (`start_game`) y el orquestador lleva el resto.
  - Terminar un Wordle a medias enseña la palabra.
- **Panel** (tarjeta «Juegos»):
  - un botón por juego y «Terminar juego»;
  - un interruptor por juego para apagarlo desde el móvil si falla, sin reinstalar;
  - los bancos editables;
  - el modelo de poses, `n` por defecto y `s` si el equipo va sobrado.
- **Cámara**, solo en poses, piedra, papel o tijera y búsqueda:
  - imagen en vivo encima de Sonnia, en espejo, con «En vivo · no se graba»;
  - detección en el propio equipo, sin guardar nada;
  - la búsqueda manda fotos reducidas al modelo de visión, con un tope por ronda.
- **Frases fijas** de los seis juegos (16), grabadas y dentro de la app.

### Pruebas hechas

- **Automáticas:** 1420 tests sin red. El C# se compiló para el editor, macOS y Windows.
- **Pantallas:** capturas 9:16 de cada estado de cada juego, con Unity en batch, revisadas.
- **Con la API real:** voz sintetizada como micrófono, barullo e interrupciones.
  - Fueron unos 50 minutos de GPT-Live con todo; en total, unos 4 USD de los 6 aprobados.
  - Lo que falló se corrigió y se volvió a probar: las despedidas que no terminaban el juego, el Akinator jugado sin delegar, las palabras del Wordle gritadas mientras Sonia habla, el empujón leído en voz alta, el giro de la ruleta anunciado sin delegar y la orden de poses adelantada.
- **De punta a punta con Unity real:** GPT-Live real, la visión real sobre fotos públicas y el juez real en la búsqueda.
- **Las apps 1.0.389 y 1.0.391**, sacadas del zip en este Mac: los seis juegos anunciados y un Wordle completo desde el panel local con GPT-Live real.

### Sin probar

- La app de Windows en un PC de verdad.
- Los juegos de cámara con la cámara del stand y gente real: aquí solo se usaron fotos públicas.

Si algo falla en el stand, se apaga ese juego desde el panel.

### Defectos conocidos (no bloquean)

- **Piedra, papel o tijera:** la pastilla de subtítulos del visitante («TÚ …») tapa a veces la mano de Sonnia en el resultado. El marcador ya dice qué sacó cada uno.
- **Akinator:** una pregunta partida sin «¿» en su primera mitad puede salir cortada en pantalla; el contador cuenta bien.
- **Ruleta:** cada vuelta añade sus reglas a la sesión (~1 KB). En el stand serán pocas vueltas.
- **Unity** se anuncia como «unity 0.1.0» en `client_hello` (cosmético).

### Para revisar (Jean)

- **Bancos en borrador,** editables desde el panel sin reinstalar:
  - `assets/games/ruleta/`: adivinanzas, tecnologías y retos de Sonnet Code;
  - `assets/games/wordle/palabras.md`: tiene muchas palabras en inglés, que cuestan a un grupo que grita en español;
  - `assets/games/akinator/temas.md`;
  - `assets/games/busqueda/objetos.md`;
  - `assets/games/poses/poses.md`.
- **Modelo de poses:** `n` por defecto. Para Simón dice, el agente de poses recomienda `s` si el equipo del stand va sobrado.
