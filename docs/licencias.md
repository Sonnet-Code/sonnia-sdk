# Licencias de assets de terceros


> **Nota (septiembre de 2026):** Sonia es un proyecto sin ánimo de lucro y de uso personal. Por decisión del equipo, de momento no se gestionan ni verifican las licencias de los assets. Esta tabla queda como registro opcional por si el uso cambia en el futuro.

Registro opcional de los modelos, voces, avatares, animaciones e imágenes de
terceros que usa Sonia. Ver también las
"Convenciones" en `CLAUDE.md`.

| Asset | Autor | Licencia | Enlace | Uso en el proyecto |
|---|---|---|---|---|
| OmniVoice (modelo de voz) | k2-fsa | Apache-2.0 según su repositorio (verificar antes de distribuir la demo fuera del stand) | https://github.com/k2-fsa/OmniVoice | Síntesis de voz (TTS) del orquestador, `server/sonia/tts/omnivoice.py` |
| faster-whisper | SYSTRAN | MIT | https://github.com/SYSTRAN/faster-whisper | Reconocimiento de voz (STT) del orquestador |
| Silero VAD | Silero Team | MIT | https://github.com/snakers4/silero-vad | Detección de actividad de voz (inicio/fin de turno del usuario) |
| Modelo/avatar 3D | _pendiente_ | _pendiente_ | _pendiente_ | Personaje de Sonia en Unity |
| Animaciones del avatar | _pendiente_ | _pendiente_ | _pendiente_ | Animaciones de escucha, pensamiento y habla |
| Imágenes de la galería (`assets/gallery`) | _pendiente_ | _pendiente_ | _pendiente_ | Panel de imágenes que Sonia muestra con `show_image` |

Al añadir una fila nueva: nombre del asset, autor u organización que lo
publica, licencia exacta (no solo "libre" o "gratis"), enlace a la fuente
original, y en qué parte del proyecto se usa. Si la licencia no queda clara
en la fuente, anota "verificar" en vez de asumir.
