# Juegos del stand: estado para Jean (10 de octubre de 2026, madrugada)

Resumen del trabajo de la noche del 9 al 10 de octubre (sesión principal «sonia-af», coordinada por «sonia-e6»).

## Hecho (rama `juegos/base`, en el worktree `~/Documents/git/sonia-juegos`; aún no está en `main`)

- **Cimientos:** `GameManager`, acciones `start_game`/`stop_game`, protocolo `game`/`game_event`/`camera_preview`/SNCV, `GameHud` y vista en vivo en Unity, panel (tarjeta «Juegos», interruptores `games_off`, bancos `game_banks`, modelo de poses `games_pose_model`), visión (stream, YOLOv8-pose `n` por defecto, manos, juez). Detalle en `docs/juegos.md`, `docs/juegos-unity.md` y `docs/juegos-vision.md`.
- **Los seis juegos encendidos y verificados con capturas 9:16:** ruleta, Wordle, Akinator, búsqueda relámpago, Simón dice con poses y piedra, papel o tijera (la mano de Sonnia validada por fotogramas; plan B: `PptController.SoniaHandEnabled = false`).
- **Pruebas:** 1365 tests sin red; C# compilado para editor, macOS y Windows; capturas en Unity por juego; pruebas con la API real (voz sintetizada, ~50 min de GPT-Live en total) y de punta a punta con Unity real. Sus fallos (despedidas, Akinator jugado sin delegar, Wordle con palabras gritadas, empujón leído en voz alta, orden de poses adelantada) están corregidos.
- **Ensayo de builds 1.0.359** (no entregado): las dos apps compilan y la de macOS se probó con un Wordle real. Zips de ensayo en `~/Documents/git/sonia-build/unity/Build/`.
- **Frases fijas** de los seis juegos grabadas en `cache/voice` de la copia principal.
- **Reserva:** la 1.0.199 está guardada en `~/Documents/git/sonia-reserva/1.0.199/`.

## Falta

1. Fusionar `juegos/base` en `main` (lo coordina sonia-e6).
2. Builds finales desde `~/Documents/git/sonia-build` con el commit de `main` (receta probada: ver el informe del agente de builds).
3. Desplegar el panel de la nube (`cd cloud/panel && npm run deploy`, desde un worktree limpio de `main`). Probado en local con una Sonnia 1.0.199 y una nueva.

## Defectos conocidos (no bloquean)

- **Piedra, papel o tijera:** la pastilla de subtítulos del visitante («TÚ …») tapa a veces la mano de Sonnia en el resultado; el marcador ya dice qué sacó cada uno.
- **Akinator:** una pregunta partida sin «¿» en su primera mitad puede salir cortada en pantalla (el contador cuenta bien).
- **Unity** se anuncia como «unity 0.1.0» en `client_hello` (cosmético).
- **Ruleta:** cada vuelta añade sus reglas a la sesión (~1 KB); en el stand serán pocas vueltas.

## Para revisar (Jean)

- **Bancos en borrador:** `assets/games/ruleta/` (adivinanzas, tecnologías, retos de Sonnet Code), `assets/games/wordle/palabras.md`, `assets/games/akinator/temas.md`, `assets/games/busqueda/objetos.md`, `assets/games/poses/poses.md`. Se pueden cambiar desde el panel sin reinstalar.
- **Si un juego falla en el stand:** apagarlo desde el panel (interruptor de la tarjeta «Juegos»).
- **Modelo de poses:** `n` por defecto; `s` desde el panel si el equipo va sobrado.
