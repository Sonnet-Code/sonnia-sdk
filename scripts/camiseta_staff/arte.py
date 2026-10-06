"""PNG del arte del DevFest 2026 para la camiseta de Sonnia.

Parte de logos/devfest-sd-2026-arte.svg (el vector del estampado de la camiseta
real, el que se manda a imprimir) y escribe logos/devfest-sd-2026-arte.png, que
es el que usa genera.py. En la pantalla del stand el pecho de Sonnia mide unos
pocos cientos de píxeles y las líneas finas del dibujo (fray Antón de
Montesinos, el marco y el mapa) casi desaparecían, así que aquí se engruesan;
los textos de arriba y el bloque de [*] y Google Developer Groups se quedan
como en el vector, y los colores (las píldoras de GDG y el corazón) van encima,
sin tocar.

Uso, desde la raíz del repo (cairosvg necesita la librería cairo; en macOS con
Homebrew, `brew install cairo` y DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib):

    uv run --with cairosvg --with opencv-python-headless --with numpy --with pillow \\
        python scripts/camiseta_staff/arte.py
"""

from __future__ import annotations

import io
from pathlib import Path

import cairosvg
import cv2
import numpy as np
from PIL import Image

LOGOS = Path(__file__).resolve().parent / "logos"
SVG = LOGOS / "devfest-sd-2026-arte.svg"
PNG = LOGOS / "devfest-sd-2026-arte.png"

#: Ancho del PNG. En la camiseta va a 18 cm y 40 px/cm (720 px): sobra para reducir.
WIDTH = 2400
#: Cuánto crece cada lado de las líneas del dibujo, en px de WIDTH (el trazo
#: original mide unos 10 px: con 5 por lado pasa a unos 20, el doble).
THICKEN = 5
#: Lo que no se engruesa, en fracciones del arte recortado (x0, y0, x1, y1): los
#: dos renglones de texto de arriba y el bloque de [*] y Google Developer Groups.
KEEP = [(0.0, 0.0, 1.0, 0.27), (0.06, 0.845, 0.64, 1.0)]


def main() -> None:
    png = cairosvg.svg2png(url=str(SVG), output_width=WIDTH)
    image = Image.open(io.BytesIO(png)).convert("RGBA")
    image = image.crop(image.getchannel("A").getbbox())
    rgba = np.asarray(image).astype(np.float32)
    height, width = rgba.shape[:2]

    alpha = rgba[..., 3] / 255.0
    white = (rgba[..., :3].min(axis=2) > 200) * alpha
    color = alpha - white

    region = np.ones((height, width), dtype=np.float32)
    for x0, y0, x1, y1 in KEEP:
        region[round(y0 * height) : round(y1 * height), round(x0 * width) : round(x1 * width)] = 0.0
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * THICKEN + 1, 2 * THICKEN + 1))
    thick = np.maximum(white, cv2.dilate(white * region, kernel))

    # Blanco engrosado debajo y los colores encima, tal cual.
    out = np.zeros_like(rgba)
    out[..., :3] = 255.0
    out[..., 3] = thick
    paint = color[..., None]
    out[..., :3] = rgba[..., :3] * paint + out[..., :3] * (1.0 - paint)
    out[..., 3] = np.maximum(thick, color)
    out[..., 3] *= 255.0
    Image.fromarray(np.clip(np.round(out), 0, 255).astype(np.uint8), "RGBA").save(PNG, optimize=True)
    print(f"{PNG.name}: {width}x{height}, líneas del dibujo +{THICKEN} px por lado")


if __name__ == "__main__":
    main()
