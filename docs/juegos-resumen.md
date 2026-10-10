# Juegos del stand: estado para Jean (10 de octubre de 2026)

Resumen del trabajo de la noche del 9 al 10 de octubre: la sesión principal fue «sonia-af» y coordinó «sonia-e6». El plan está en `docs/plan-juegos.md` y el detalle técnico en `docs/juegos.md`, `docs/juegos-unity.md`, `docs/juegos-vision.md` y `docs/juegos/<juego>.md`.

## Entrega

- **App para el stand: 1.0.391**, compilada desde `main` en `b31a357` («Fusiona los juegos nuevos del stand»).
  - `Sonnia-macOS-1.0.391.zip`: SHA-256 `6f22c4c25fddeeffd4330a4841dee21fd1b2e5b7e0cb2473f65a4dbfe97e2ccf`.
  - `Sonnia-Windows-x64-1.0.391.zip`: SHA-256 `cb10eab07b5ef55db1ce65dcd6c579bfb4eac5de7fcdcc4b8f12b011895b6500`.
  - Están en `~/Documents/git/sonia/unity/Build/` y en `~/Documents/git/sonia-entrega/1.0.391/`, con su `LEEME.txt`.
- **Reserva 1.0.389:** el mismo código, sin los `.meta` (de `88e8e6d`), en `~/Documents/git/sonia-reserva/1.0.389/` y también en `unity/Build/`.
- **Reserva anterior a los juegos:** la 1.0.199, en `~/Documents/git/sonia-reserva/1.0.199/`.
- **Panel de la nube:** desplegado con los controles de los juegos, versión del Worker `33c2771a-9388-4e1a-9d6e-52bdfc6d2f1a`. Para volver a la anterior: `cd cloud/panel && npx wrangler rollback b52595a5-c9e3-4bd7-b8b8-0c165016aaa0`. Las apps 1.0.195 y 1.0.199 siguen funcionando con él: sus controles de juegos salen desactivados (se probó con dos Sonnias, una vieja y otra nueva, conectadas a la vez a un Worker local).

## Qué hay

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

## Pruebas hechas

- **Automáticas:** 1420 tests sin red. El C# se compiló para el editor, macOS y Windows.
- **Pantallas:** capturas 9:16 de cada estado de cada juego, con Unity en batch, revisadas.
- **Con la API real:** voz sintetizada como micrófono, barullo e interrupciones.
  - Fueron unos 50 minutos de GPT-Live con todo; en total, unos 4 USD de los 6 aprobados.
  - Lo que falló se corrigió y se volvió a probar: las despedidas que no terminaban el juego, el Akinator jugado sin delegar, las palabras del Wordle gritadas mientras Sonia habla, el empujón leído en voz alta, el giro de la ruleta anunciado sin delegar y la orden de poses adelantada.
- **De punta a punta con Unity real:** GPT-Live real, la visión real sobre fotos públicas y el juez real en la búsqueda.
- **Las apps 1.0.389 y 1.0.391**, sacadas del zip en este Mac: los seis juegos anunciados y un Wordle completo desde el panel local con GPT-Live real.

## Sin probar

- La app de Windows en un PC de verdad.
- Los juegos de cámara con la cámara del stand y gente real: aquí solo se usaron fotos públicas.

Si algo falla en el stand, se apaga ese juego desde el panel.

## Defectos conocidos (no bloquean)

- **Piedra, papel o tijera:** la pastilla de subtítulos del visitante («TÚ …») tapa a veces la mano de Sonnia en el resultado. El marcador ya dice qué sacó cada uno.
- **Akinator:** una pregunta partida sin «¿» en su primera mitad puede salir cortada en pantalla; el contador cuenta bien.
- **Ruleta:** cada vuelta añade sus reglas a la sesión (~1 KB). En el stand serán pocas vueltas.
- **Unity** se anuncia como «unity 0.1.0» en `client_hello` (cosmético).

## Para revisar (Jean)

- **Bancos en borrador,** editables desde el panel sin reinstalar:
  - `assets/games/ruleta/`: adivinanzas, tecnologías y retos de Sonnet Code;
  - `assets/games/wordle/palabras.md`: tiene muchas palabras en inglés, que cuestan a un grupo que grita en español;
  - `assets/games/akinator/temas.md`;
  - `assets/games/busqueda/objetos.md`;
  - `assets/games/poses/poses.md`.
- **Modelo de poses:** `n` por defecto. Para Simón dice, el agente de poses recomienda `s` si el equipo del stand va sobrado.
