"""Imagen RGBA del texto «Noogler» bordado: cada letra en su color de Google con un canto más oscuro.

Uso (macOS, por la fuente Avenir Next):
    uv run --no-project --with pillow python scripts/gorro_noogler/texto.py
Escribe trabajo/noogler_text.png, que proyecta construir.py en el gajo delantero.
"""

import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rutas import TRABAJO  # noqa: E402

FONT = "/System/Library/Fonts/Avenir Next.ttc"
SIZE = 520
TEXT = "Noogler"
# Como en la gorra original: N azul, o roja, o amarilla, g azul, l verde, e roja, r verde.
COLORS = [
    (66, 133, 244),
    (234, 67, 53),
    (238, 152, 0),  # ámbar: sobre el gajo amarillo, el amarillo de Google no se ve
    (66, 133, 244),
    (52, 168, 83),
    (234, 67, 53),
    (52, 168, 83),
]

font = ImageFont.truetype(FONT, SIZE, index=5)  # Medium
pad = 60
widths = [font.getlength(ch) for ch in TEXT]
kerning = font.getlength(TEXT) - sum(widths)
width = int(font.getlength(TEXT) + pad * 2)
ascent, descent = font.getmetrics()
height = int(ascent + descent + pad * 2)

image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
mask = Image.new("L", (width, height), 0)
x = pad
for ch, color, w in zip(TEXT, COLORS, widths, strict=True):
    layer = Image.new("L", (width, height), 0)
    ImageDraw.Draw(layer).text((x, pad), ch, font=font, fill=255)
    # Canto del bordado: la letra un poco más gruesa en un tono más oscuro debajo.
    edge = layer.filter(ImageFilter.MaxFilter(9))
    dark = tuple(int(c * 0.55) for c in color)
    image.paste(Image.new("RGBA", (width, height), dark + (255,)), (0, 0), edge)
    image.paste(Image.new("RGBA", (width, height), color + (255,)), (0, 0), layer)
    mask.paste(255, (0, 0), edge)
    x += w + kerning / max(1, len(TEXT) - 1)

image = image.crop(mask.getbbox())
image.save(os.path.join(TRABAJO, "noogler_text.png"))
print("TEXTO", image.size, "aspecto", round(image.size[0] / image.size[1], 3))
