#!/usr/bin/env python3
"""Estampados de la camiseta de staff de Sonnia (DevFest Santo Domingo 2026).

Genera en unity/Assets/Resources/StaffShirt/:
  staff-front.png    lo de delante: lockup oficial (emblema GDG + «DevFest /
                     Santo Domingo»), «STAFF» y Sonnet Code;
  staff-back.png     lo de detrás: «STAFF» grande y los patrocinadores 2026,
                     con Sonnet Code el más grande;
  staff-shirt.json   color de la camiseta y dónde va cada estampado, en metros
                     respecto al hueso del pecho del avatar (UpperChest): x hacia
                     la derecha de quien la mira, y hacia arriba.
GeniesStaffShirt (Unity) proyecta cada estampado de frente o de espaldas sobre
la malla de la camiseta y lo hornea en su textura (docs/unity.md, «Camiseta de
staff»).

Referencias (6 de octubre de 2026, ver docs/unity.md):
  - las camisetas de DevFest Santo Domingo 2023 eran azul royal con la estampa en
    blanco; el lockup 2026 es el de https://devfest.gdgsantodomingo.org;
  - patrocinadores 2026 de la web oficial del evento (Platino, Oro, Plata, Aliado).
Todo se estampa en blanco (una tinta), salvo el emblema de GDG, a color con sus
anillos blancos, como el oficial. Los logos de origen están en logos/.

Uso: python3 scripts/camiseta_staff/genera.py [--preview carpeta]
Solo necesita Pillow y la fuente Avenir Next de macOS (parecida a Google Sans).
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
LOGOS = HERE / "logos"
OUT = HERE.parents[1] / "unity" / "Assets" / "Resources" / "StaffShirt"

#: Azul royal de las camisetas de DevFest Santo Domingo (sRGB).
SHIRT_COLOR = "#1F5FD6"
INK = (255, 255, 255)
#: Resolución de los estampados: 40 px por centímetro de tela.
PX_PER_M = 4000

AVENIR = "/System/Library/Fonts/Avenir Next.ttc"
BOLD, DEMI, MEDIUM, HEAVY = 0, 2, 5, 8


def font(index: int, size_m: float) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(AVENIR, max(8, round(size_m * PX_PER_M)), index=index)


def px(m: float) -> int:
    return round(m * PX_PER_M)


def trimmed(path: Path) -> Image.Image:
    image = Image.open(path).convert("RGBA")
    box = image.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    return image.crop(box) if box else image


def one_ink(image: Image.Image, mode: str) -> Image.Image:
    """Logo en blanco, con el alfa como tinta.

    dark  logo pensado para fondo oscuro: lo claro es tinta y lo oscuro se queda
          en la tela (el cuadrado del Popular, los ojos del panda de Bojote);
    light logo pensado para fondo claro: la silueta es tinta y lo blanco de
          dentro se queda en la tela (las letras blancas de «academy»).
    """
    r, g, b, a = image.split()
    luma = Image.merge("RGB", (r, g, b)).convert("L")
    if mode == "dark":
        ink = luma.point(lambda v: max(0, min(255, round((v - 45) * 255 / 110))))
    else:
        ink = luma.point(lambda v: 255 if v < 200 else max(0, round((235 - v) * 255 / 35)))
    alpha = ImageChops.multiply(a, ink)
    out = Image.new("RGBA", image.size, INK + (0,))
    out.putalpha(alpha)
    return out


def white(image: Image.Image) -> Image.Image:
    out = Image.new("RGBA", image.size, INK + (0,))
    out.putalpha(image.getchannel("A"))
    return out


def fit(image: Image.Image, width_m: float | None = None, height_m: float | None = None) -> Image.Image:
    w, h = image.size
    scale = min(px(width_m) / w if width_m else 1e9, px(height_m) / h if height_m else 1e9)
    return image.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)


def text(content: str, index: int, size_m: float, tracking: float = 0.0) -> Image.Image:
    """Texto en blanco recortado a su caja; ``tracking`` en ems."""
    f = font(index, size_m)
    widths = [f.getlength(ch) for ch in content]
    extra = tracking * f.size
    total = round(sum(widths) + extra * (len(content) - 1)) + 4
    ascent, descent = f.getmetrics()
    image = Image.new("RGBA", (total, ascent + descent + 4), INK + (0,))
    draw = ImageDraw.Draw(image)
    x = 2.0
    for ch, w in zip(content, widths, strict=True):
        draw.text((x, 2), ch, font=f, fill=INK + (255,))
        x += w + extra
    return image.crop(image.getchannel("A").getbbox())


#: Grosor del anillo blanco de cada píldora del emblema, en unidades del SVG.
EMBLEM_RING = 6.6


def _pill(x: float, y: float, w: float, h: float, r: float, tx: float, ty: float, angle: float,
          inset: float = 0.0) -> list[tuple[float, float]]:
    """Contorno de un rectángulo redondeado del SVG con su transform (translate + rotate)."""
    x, y, w, h, r = x + inset, y + inset, w - 2 * inset, h - 2 * inset, max(0.0, r - inset)
    points = []
    for cx, cy, start in ((x + w - r, y + r, -90), (x + w - r, y + h - r, 0), (x + r, y + h - r, 90), (x + r, y + r, 180)):
        for i in range(25):
            a = math.radians(start + 90 * i / 24)
            points.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    return [(px_ * c - py_ * s + tx, px_ * s + py_ * c + ty) for px_, py_ in points]


def gdg_emblem(height_m: float) -> Image.Image:
    """Emblema oficial de GDG (logos/gdg-emblema-color.svg, el de la web del DevFest Santo Domingo
    2026): cuatro píldoras de color con su anillo blanco, dibujadas desde la geometría del SVG."""
    svg = (LOGOS / "gdg-emblema-color.svg").read_text(encoding="utf-8")
    pills = []
    for m in re.finditer(r"<rect ([^>]+)/>", svg):
        attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', m.group(1)))
        tx, ty = map(float, re.search(r"translate\(([-\d.]+)[ ,]+([-\d.]+)\)", attrs["transform"]).groups())
        angle = float(re.search(r"rotate\(([-\d.]+)\)", attrs["transform"]).group(1))
        color = re.search(r"fill:\s*(#[0-9a-fA-F]{6})", attrs["style"]).group(1)
        geom = [float(attrs[k]) for k in ("x", "y", "width", "height", "rx")]
        pills.append((geom, tx, ty, angle, color))
    outlines = [_pill(*g, tx, ty, a) for g, tx, ty, a, _ in pills]
    xs = [p[0] for o in outlines for p in o]
    ys = [p[1] for o in outlines for p in o]
    pad = 2.0
    scale = px(height_m) / (max(ys) - min(ys) + 2 * pad)
    size = (round((max(xs) - min(xs) + 2 * pad) * scale), round((max(ys) - min(ys) + 2 * pad) * scale))

    def to_px(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
        return [((x - min(xs) + pad) * scale, (y - min(ys) + pad) * scale) for x, y in points]

    image = Image.new("RGBA", size, INK + (0,))
    for (geom, tx, ty, angle, color), outer in zip(pills, outlines, strict=True):
        ImageDraw.Draw(image).polygon(to_px(outer), fill=color)
        ring = Image.new("L", size, 0)
        draw = ImageDraw.Draw(ring)
        draw.polygon(to_px(outer), fill=255)
        draw.polygon(to_px(_pill(*geom, tx, ty, angle, inset=EMBLEM_RING)), fill=0)
        image.paste(INK + (255,), (0, 0), ring)
    return image


def lockup(width_m: float) -> Image.Image:
    """Emblema GDG + «DevFest» / «Santo Domingo», como el de la web del evento 2026."""
    title = text("DevFest", DEMI, 0.050)
    city = text("Santo Domingo", MEDIUM, 0.030)
    gap = px(0.006)
    block_h = title.height + gap + city.height
    emblem = gdg_emblem(block_h / PX_PER_M * 0.92)
    words_w = max(title.width, city.width)
    space = px(0.012)
    image = Image.new("RGBA", (emblem.width + space + words_w, max(block_h, emblem.height)), INK + (0,))
    image.alpha_composite(emblem, (0, (image.height - emblem.height) // 2))
    top = (image.height - block_h) // 2
    image.alpha_composite(title, (emblem.width + space, top))
    image.alpha_composite(city, (emblem.width + space + px(0.001), top + title.height + gap))
    return fit(image, width_m=width_m)


def staff_badge(height_m: float) -> Image.Image:
    """«STAFF» espaciado entre dos líneas finas."""
    word = text("STAFF", BOLD, height_m * 1.35, tracking=0.32)
    word = fit(word, height_m=height_m)
    line_w, line_h, space = px(0.022), max(2, px(0.0018)), px(0.009)
    image = Image.new("RGBA", (word.width + 2 * (line_w + space), word.height), INK + (0,))
    draw = ImageDraw.Draw(image)
    y = image.height // 2 - line_h // 2
    draw.rectangle((0, y, line_w, y + line_h), fill=INK + (255,))
    draw.rectangle((image.width - line_w, y, image.width, y + line_h), fill=INK + (255,))
    image.alpha_composite(word, (line_w + space, 0))
    return image


class Canvas:
    """Un estampado: rectángulo en metros respecto al pecho (x a la derecha de quien mira, y arriba)."""

    def __init__(self, name: str, face: str, x0: float, y0: float, x1: float, y1: float) -> None:
        self.name, self.face = name, face
        self.rect = (x0, y0, x1, y1)
        self.image = Image.new("RGBA", (px(x1 - x0), px(y1 - y0)), INK + (0,))

    def place(self, item: Image.Image, cx: float, cy: float) -> None:
        x0, _, _, y1 = self.rect
        left = px(cx - x0) - item.width // 2
        top = px(y1 - cy) - item.height // 2
        self.image.alpha_composite(item, (left, top))

    def row(self, items: list[Image.Image], cy: float, gap_m: float) -> None:
        total = sum(i.width for i in items) + px(gap_m) * (len(items) - 1)
        x = -total / 2 / PX_PER_M
        for item in items:
            self.place(item, x + item.width / 2 / PX_PER_M, cy)
            x += (item.width + px(gap_m)) / PX_PER_M

    def describe(self) -> dict[str, object]:
        return {"texture": self.name, "face": self.face, "rect": [round(v, 4) for v in self.rect]}


def sponsor(name: str, mode: str, height_m: float, max_width_m: float) -> Image.Image:
    return fit(one_ink(trimmed(LOGOS / "patrocinadores" / name), mode), max_width_m, height_m)


def build() -> list[Canvas]:
    # Delante: entre el cuello (unos 11 cm por encima del pecho) y la cintura.
    front = Canvas("staff-front", "front", -0.15, -0.14, 0.15, 0.10)
    front.place(lockup(0.165), 0.0, 0.052)
    front.place(staff_badge(0.017), 0.0, 0.002)
    front.place(fit(trimmed(LOGOS / "sonnet-code-blanco-2lineas.png"), width_m=0.125), 0.0, -0.062)

    # Detrás: STAFF grande arriba y los patrocinadores por niveles, dentro de
    # ±11 cm (más allá la espalda ya gira hacia el costado) y por encima del bajo
    # (a unos 20 cm por debajo del pecho). El pelo tapa lo de más arriba de +9 cm.
    back = Canvas("staff-back", "back", -0.13, -0.19, 0.13, 0.10)
    back.place(fit(text("STAFF", HEAVY, 0.075, tracking=0.06), width_m=0.19), 0.0, 0.058)
    back.place(lockup(0.10), 0.0, 0.006)
    back.place(fit(trimmed(LOGOS / "sonnet-code-blanco-2lineas.png"), width_m=0.12), 0.0, -0.045)
    back.row(
        [
            sponsor("platinum-google.png", "light", 0.021, 0.07),
            sponsor("platinum-banco-popular.png", "dark", 0.021, 0.08),
        ],
        -0.093,
        0.024,
    )
    back.row(
        [
            sponsor("gold-heva.png", "dark", 0.014, 0.045),
            sponsor("gold-bojote.png", "dark", 0.016, 0.05),
            sponsor("gold-caribium-blanco.png", "dark", 0.009, 0.05),
            sponsor("gold-tt-academy.png", "light", 0.016, 0.05),
        ],
        -0.127,
        0.013,
    )
    back.row(
        [
            sponsor("silver-thraive.png", "dark", 0.012, 0.05),
            sponsor("silver-talento-digital.png", "light", 0.015, 0.05),
            sponsor("partner-festiva.png", "light", 0.0095, 0.05),
        ],
        -0.156,
        0.016,
    )
    return [front, back]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--preview", type=Path, help="carpeta para vistas previas sobre el azul de la camiseta")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    canvases = build()
    for canvas in canvases:
        canvas.image.save(OUT / f"{canvas.name}.png", optimize=True)
        if args.preview:
            args.preview.mkdir(parents=True, exist_ok=True)
            preview = Image.new("RGBA", canvas.image.size, SHIRT_COLOR)
            preview.alpha_composite(canvas.image)
            preview.convert("RGB").save(args.preview / f"{canvas.name}-preview.png")
    config = {"color": SHIRT_COLOR, "prints": [c.describe() for c in canvases]}
    (OUT / "staff-shirt.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print("listo:", ", ".join(f"{c.name}.png {c.image.width}x{c.image.height}" for c in canvases))


if __name__ == "__main__":
    main()
