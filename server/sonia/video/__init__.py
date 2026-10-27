"""Sonnia Video: vídeos de Sonnia para redes sociales sin abrir Unity (``docs/video.md``).

``sonnia-video`` lee un guion (TOML), genera la voz con Gemini o ElevenLabs (o toma
un audio grabado), saca los tiempos de cada palabra, elige los gestos con el modelo
de gestos del stand y le pasa al renderizador («Sonnia Video.app», una build de Unity)
una línea de tiempo con los mismos mensajes que manda el orquestador en el stand.
Unity renderiza a paso fijo y codifica el vídeo mudo con ffmpeg; aquí se le pone la
voz original, colocada donde sonó en Unity y a −14 LUFS, y se escriben los subtítulos.

Piezas:

- ``script``: el guion, sus opciones y la regla del nombre («Sonnia» escrito, «Sonia» dicho).
- ``voice`` (con ``gemini``, ``elevenlabs`` y ``align``): una sola toma de voz para todo el
  guion, sus tiempos por palabra y la caché en disco.
- ``plan``: frases, cortes, niveles para Unity y la línea de tiempo del trabajo.
- ``gestures``: los gestos de cada frase con una sola petición al modelo de gestos.
- ``renderer``: lanzar la app de Unity, mandarle el trabajo y seguir su progreso.
- ``ffmpeg`` y ``srt``: la mezcla final, la comprobación de la sincronía y los subtítulos.
- ``pipeline``: el recorrido entero, que usa la línea de órdenes (``cli``).
"""

from __future__ import annotations

from sonia.video.errors import VideoError

__all__ = ["VideoError"]
