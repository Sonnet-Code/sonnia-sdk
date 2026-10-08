# Galería de imágenes

Cada archivo `.png`, `.jpg` o `.jpeg` que pongas directamente en esta carpeta es una imagen que Sonia puede mostrar en el panel de su escena con la acción `show_image`, usando como `image_id` el nombre del archivo sin extensión.

Por ejemplo, `oficinas.png` se muestra pidiendo el id `oficinas`.

## Recomendaciones al añadir imágenes

- Solo PNG y JPEG. Unity decodifica el panel con `ImageConversion.LoadImage`, que no entiende WebP: un `.webp` aquí se ignora, y si no se ignorara Sonia diría en voz alta que muestra una imagen que en la pantalla no aparece. Convierte a PNG antes de copiarla.
- Nombres de archivo en `kebab-case`, sin espacios ni tildes (por ejemplo `arquitectura-sonia.png`, no `Arquitectura Sonia.png`).
- Ancho máximo recomendado: 1920 px. Imágenes más grandes solo añaden peso y tiempo de carga sin mejorar lo que se ve en pantalla.
- Un solo archivo por id: si hay `oficinas.png` y `oficinas.jpg` a la vez, `server/sonia/actions/gallery.py` resuelve solo uno de los dos (por orden de extensión), así que evita duplicados con el mismo nombre.
- No subir imágenes con datos personales identificables de visitantes reales: esta carpeta es contenido preparado de antemano, no un lugar donde guardar capturas de cámara (ver `docs/decisiones/004-vision-por-capturas.md`).

## Vacía por defecto

La carpeta no trae imágenes: las añade el equipo del stand el día del evento con las que considere. Sonia no tiene que enseñar el logo de Sonnet Code (ya sale en su pantalla) y, con la galería vacía, no enseña ninguna imagen: las fotos de la cámara no salen nunca en pantalla.

No hace falta reiniciar Sonia al añadir o quitar imágenes:

- El orquestador mira la carpeta cada `GALLERY_WATCH_SECONDS` (5 s) y, en el siguiente momento de calma de la conversación, le pasa a GPT-Live una nota silenciosa `[Galería]` con lo que se añadió o quitó y la lista nueva. No la dice en voz alta: enseña las imágenes cuando vienen a cuento. Las sesiones nuevas ya traen la lista en sus instrucciones.
- El panel local las ve al momento.
- El panel en la nube recibe la lista solo al conectarse la Sonia: para verlas allí hay que reiniciarla. Las miniaturas solo salen allí después de volver a desplegar el Worker (`cloud/panel/`); sin miniatura, el botón de cada imagen funciona igual.

Cuando añadas una imagen de terceros (no producida por el equipo), regístrala en `docs/licencias.md`.
