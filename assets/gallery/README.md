# Galería de imágenes

Cada archivo `.png`, `.jpg` o `.jpeg` que pongas directamente en esta carpeta es una imagen que Sonia puede mostrar en el panel de su escena con la acción `show_image`, usando como `image_id` el nombre del archivo sin extensión.

Por ejemplo, `logo-sonnet.png` se muestra pidiendo el id `logo-sonnet`. El id especial `camera` no es un archivo de esta carpeta: se refiere a la última captura tomada con la cámara.

## Recomendaciones al añadir imágenes

- Solo PNG y JPEG. Unity decodifica el panel con `ImageConversion.LoadImage`, que no entiende WebP: un `.webp` aquí se ignora, y si no se ignorara Sonia diría en voz alta que muestra una imagen que en la pantalla no aparece. Convierte a PNG antes de copiarla.
- Nombres de archivo en `kebab-case`, sin espacios ni tildes (por ejemplo `arquitectura-sonia.png`, no `Arquitectura Sonia.png`).
- Ancho máximo recomendado: 1920 px. Imágenes más grandes solo añaden peso y tiempo de carga sin mejorar lo que se ve en pantalla.
- Un solo archivo por id: si hay `logo-sonnet.png` y `logo-sonnet.jpg` a la vez, `server/sonia/actions/gallery.py` resuelve solo uno de los dos (por orden de extensión), así que evita duplicados con el mismo nombre.
- No subir imágenes con datos personales identificables de visitantes reales: esta carpeta es contenido preparado de antemano, no un lugar donde guardar capturas de cámara (ver `docs/decisiones/004-vision-por-capturas.md`).

## Imágenes sugeridas para el stand

Pendientes de añadir antes del evento:

- `logo-sonnet` — logo de Sonnet Code.
- `servicios-sonnet` — resumen visual de los servicios de Sonnet Code.
- `oficinas` — foto de las oficinas de Sonnet Code.
- `equipo` — foto del equipo.
- `arquitectura-sonia` — diagrama de la arquitectura de Sonia (ver `docs/arquitectura.md` para el contenido técnico de referencia).
- `devfest` — imagen relacionada con DevFest Santo Domingo 2026.

Cuando añadas una imagen de terceros (no producida por el equipo), regístrala en `docs/licencias.md`.
