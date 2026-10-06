#!/usr/bin/env python3
"""Estampados de la camiseta de staff de Sonnia (DevFest Santo Domingo 2026).

Genera, para cada variante (marino, azul, negra, blanca), en
unity/Assets/Resources/StaffShirt/<variante>/:
  staff-front.png    lo de delante: el arte del DevFest Santo Domingo 2026 (el de
                     la camiseta real) y, debajo, Sonnet Code;
  staff-back.png     lo de detrás: «STAFF» grande y los patrocinadores 2026,
                     con Sonnet Code el más grande;
  staff-shirt.json   color de la camiseta y dónde va cada estampado, en metros
                     respecto al hueso del pecho del avatar (UpperChest): x hacia
                     la derecha de quien la mira, y hacia arriba.
y los .meta de Unity que falten (PNG legibles, sin comprimir). GeniesStaffShirt
(Unity) proyecta cada estampado de frente o de espaldas sobre la malla de la
camiseta y lo hornea en su textura (docs/unity.md, «Camiseta de staff»). La app
usa la variante de -camiseta <nombre> o, sin él, DefaultVariant.

Referencias (6 de octubre de 2026, ver docs/unity.md):
  - la camiseta de staff de 2026 es azul marino con la estampa en blanco (foto de
    Jean del 7 de octubre): #3A3448 es la tela de esa foto con el balance de
    blancos corregido con la tinta blanca;
  - el arte del pecho (logos/devfest-sd-2026-arte.svg, «DevFest 2026 / # →
    Santo Domingo» con fray Antón de Montesinos gritando su sermón, el mapa con
    el corazón, [*] y GDG) es el de la camiseta real, vectorizado el 7 de
    octubre; el PNG de al lado sale de él con arte.py (líneas del dibujo más
    gruesas para la pantalla);
  - las camisetas de DevFest Santo Domingo 2023 eran azul royal con la estampa en
    blanco; el lockup 2026 es el de https://devfest.gdgsantodomingo.org;
  - patrocinadores 2026 de la web oficial del evento (Platino, Oro, Plata, Aliado).
Todo se estampa en una tinta (blanca en las oscuras, casi negra en la blanca),
salvo el emblema de GDG y el corazón del arte, a color, y, en la blanca, el logo
de Sonnet Code a color. Los logos de origen están en logos/.

Uso: python3 scripts/camiseta_staff/genera.py [--preview carpeta] [variante...]
Solo necesita Pillow y la fuente Avenir Next de macOS (parecida a Google Sans).
"""

from __future__ import annotations

import argparse
import json
import math
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
LOGOS = HERE / "logos"
OUT = HERE.parents[1] / "unity" / "Assets" / "Resources" / "StaffShirt"

#: Resolución de los estampados: 40 px por centímetro de tela.
PX_PER_M = 4000

AVENIR = "/System/Library/Fonts/Avenir Next.ttc"
BOLD, DEMI, MEDIUM, HEAVY = 0, 2, 5, 8

RGB = tuple[int, int, int]


@dataclass(frozen=True)
class Variant:
    name: str
    #: Color de la tela (sRGB).
    shirt: str
    #: Tinta de los estampados y de los anillos del emblema.
    ink: RGB
    #: Logo de Sonnet Code (logos/).
    sonnet: str
    #: La tela es clara: los logos de patrocinio van en tinta oscura.
    light: bool = False


VARIANTS = {
    # Como la camiseta de staff de 2026 (azul marino, foto del 7 de octubre).
    "marino": Variant("marino", "#3A3448", (255, 255, 255), "sonnet-code-blanco-2lineas.png"),
    # Como las de DevFest Santo Domingo 2023.
    "azul": Variant("azul", "#1F5FD6", (255, 255, 255), "sonnet-code-blanco-2lineas.png"),
    "negra": Variant("negra", "#1A1A1A", (255, 255, 255), "sonnet-code-blanco-2lineas.png"),
    # Tinta #1E1E1E: el oscuro de la marca DevFest 2026 (contornos del emblema en fondo claro).
    "blanca": Variant("blanca", "#F2F2F2", (30, 30, 30), "sonnet-code-color-2lineas.png", light=True),
}


def font(index: int, size_m: float) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(AVENIR, max(8, round(size_m * PX_PER_M)), index=index)


def px(m: float) -> int:
    return round(m * PX_PER_M)


def clear(size: tuple[int, int], ink: RGB) -> Image.Image:
    """Lienzo transparente con el color de la tinta (sin halos al filtrar)."""
    return Image.new("RGBA", size, ink + (0,))


def trimmed(path: Path) -> Image.Image:
    image = Image.open(path).convert("RGBA")
    box = image.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    return image.crop(box) if box else image


def one_ink(image: Image.Image, mode: str, ink: RGB) -> Image.Image:
    """Logo en una tinta, con el alfa como cantidad de tinta.

    dark  logo pensado para fondo oscuro: lo claro es tinta y lo oscuro se queda
          en la tela (el cuadrado del Popular, los ojos del panda de Bojote);
    light logo pensado para fondo claro: la silueta es tinta y lo blanco de
          dentro se queda en la tela (las letras blancas de «academy»).
    """
    r, g, b, a = image.split()
    luma = Image.merge("RGB", (r, g, b)).convert("L")
    if mode == "dark":
        amount = luma.point(lambda v: max(0, min(255, round((v - 45) * 255 / 110))))
    else:
        amount = luma.point(lambda v: 255 if v < 200 else max(0, round((235 - v) * 255 / 35)))
    out = clear(image.size, ink)
    out.putalpha(ImageChops.multiply(a, amount))
    return out


def split_ink(image: Image.Image, left: str, right: str, ink: RGB) -> Image.Image:
    """Icono y texto con modos distintos: se parte por el primer hueco vertical
    después del 20 % del ancho (el icono del Popular, el panda de Bojote)."""
    alpha = image.getchannel("A")
    width, height = image.size
    cut = width // 3
    for x in range(width // 5, width * 3 // 5):
        if alpha.crop((x, 0, x + 1, height)).getbbox() is None:
            cut = x
            break
    out = clear(image.size, ink)
    out.alpha_composite(one_ink(image.crop((0, 0, cut, height)), left, ink), (0, 0))
    out.alpha_composite(one_ink(image.crop((cut, 0, width, height)), right, ink), (cut, 0))
    return out


def fit(image: Image.Image, width_m: float | None = None, height_m: float | None = None) -> Image.Image:
    w, h = image.size
    scale = min(px(width_m) / w if width_m else 1e9, px(height_m) / h if height_m else 1e9)
    return image.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)


def text(content: str, index: int, size_m: float, ink: RGB, tracking: float = 0.0) -> Image.Image:
    """Texto en la tinta, recortado a su caja; ``tracking`` en ems."""
    f = font(index, size_m)
    widths = [f.getlength(ch) for ch in content]
    extra = tracking * f.size
    total = round(sum(widths) + extra * (len(content) - 1)) + 4
    ascent, descent = f.getmetrics()
    image = clear((total, ascent + descent + 4), ink)
    draw = ImageDraw.Draw(image)
    x = 2.0
    for ch, w in zip(content, widths, strict=True):
        draw.text((x, 2), ch, font=f, fill=ink + (255,))
        x += w + extra
    return image.crop(image.getchannel("A").getbbox())


#: Grosor del anillo de cada píldora del emblema, en unidades del SVG.
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


def gdg_emblem(height_m: float, ring: RGB) -> Image.Image:
    """Emblema oficial de GDG (logos/gdg-emblema-color.svg, el de la web del DevFest Santo Domingo
    2026): cuatro píldoras de color con su anillo, dibujadas desde la geometría del SVG. El anillo
    va en la tinta: blanco como el oficial en fondo oscuro, oscuro como el de DevFest 2026 en claro."""
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

    image = clear(size, ring)
    for (geom, tx, ty, angle, color), outer in zip(pills, outlines, strict=True):
        ImageDraw.Draw(image).polygon(to_px(outer), fill=color)
        mask = Image.new("L", size, 0)
        draw = ImageDraw.Draw(mask)
        draw.polygon(to_px(outer), fill=255)
        draw.polygon(to_px(_pill(*geom, tx, ty, angle, inset=EMBLEM_RING)), fill=0)
        image.paste(ring + (255,), (0, 0), mask)
    return image


def lockup(width_m: float, ink: RGB) -> Image.Image:
    """Emblema GDG + «DevFest» / «Santo Domingo», como el de la web del evento 2026."""
    title = text("DevFest", DEMI, 0.050, ink)
    city = text("Santo Domingo", MEDIUM, 0.030, ink)
    gap = px(0.006)
    block_h = title.height + gap + city.height
    emblem = gdg_emblem(block_h / PX_PER_M * 0.92, ink)
    words_w = max(title.width, city.width)
    space = px(0.012)
    image = clear((emblem.width + space + words_w, max(block_h, emblem.height)), ink)
    image.alpha_composite(emblem, (0, (image.height - emblem.height) // 2))
    top = (image.height - block_h) // 2
    image.alpha_composite(title, (emblem.width + space, top))
    image.alpha_composite(city, (emblem.width + space + px(0.001), top + title.height + gap))
    return fit(image, width_m=width_m)


#: Arte del pecho: blanco y los colores de GDG sobre transparente (ver la cabecera).
ART = "devfest-sd-2026-arte.png"


def devfest_art(width_m: float, ink: RGB) -> Image.Image:
    """El arte del DevFest 2026 con lo blanco en la tinta (los colores se quedan)."""
    image = trimmed(LOGOS / ART)
    if ink != (255, 255, 255):
        pixels = image.load()
        for y in range(image.height):
            for x in range(image.width):
                r, g, b, a = pixels[x, y]
                if a and min(r, g, b) > 200:
                    pixels[x, y] = ink + (a,)
    return fit(image, width_m=width_m)


def staff_badge(height_m: float, ink: RGB) -> Image.Image:
    """«STAFF» espaciado entre dos líneas finas."""
    word = fit(text("STAFF", BOLD, height_m * 1.35, ink, tracking=0.32), height_m=height_m)
    line_w, line_h, space = px(0.022), max(2, px(0.0018)), px(0.009)
    image = clear((word.width + 2 * (line_w + space), word.height), ink)
    draw = ImageDraw.Draw(image)
    y = image.height // 2 - line_h // 2
    draw.rectangle((0, y, line_w, y + line_h), fill=ink + (255,))
    draw.rectangle((image.width - line_w, y, image.width, y + line_h), fill=ink + (255,))
    image.alpha_composite(word, (line_w + space, 0))
    return image


class Canvas:
    """Un estampado: rectángulo en metros respecto al pecho (x a la derecha de quien mira, y arriba)."""

    def __init__(self, name: str, face: str, rect: tuple[float, float, float, float], ink: RGB) -> None:
        self.name, self.face, self.rect = name, face, rect
        x0, y0, x1, y1 = rect
        self.image = clear((px(x1 - x0), px(y1 - y0)), ink)

    def place(self, item: Image.Image, cx: float, cy: float) -> None:
        x0, _, _, y1 = self.rect
        self.image.alpha_composite(item, (px(cx - x0) - item.width // 2, px(y1 - cy) - item.height // 2))

    def row(self, items: list[Image.Image], cy: float, gap_m: float) -> None:
        total = sum(i.width for i in items) + px(gap_m) * (len(items) - 1)
        x = -total / 2 / PX_PER_M
        for item in items:
            self.place(item, x + item.width / 2 / PX_PER_M, cy)
            x += (item.width + px(gap_m)) / PX_PER_M

    def describe(self) -> dict[str, object]:
        return {"texture": self.name, "face": self.face, "rect": [round(v, 4) for v in self.rect]}


#: Cómo pasar cada patrocinador a una tinta: en tela oscura y en tela clara.
#: Una tupla es icono y texto por separado (ver split_ink).
SPONSORS: dict[str, tuple[object, object]] = {
    "platinum-google.png": ("light", "light"),
    "platinum-banco-popular.png": ("dark", ("light", "dark")),
    "gold-heva.png": ("dark", "dark"),
    "gold-bojote.png": ("dark", ("light", "dark")),
    "gold-caribium-blanco.png": ("dark", "dark"),
    "gold-tt-academy.png": ("light", "light"),
    "silver-thraive.png": ("dark", "dark"),
    "silver-talento-digital.png": ("light", "light"),
    "partner-festiva.png": ("light", "light"),
}


def sponsor(name: str, variant: Variant, height_m: float, max_width_m: float) -> Image.Image:
    mode = SPONSORS[name][1 if variant.light else 0]
    image = trimmed(LOGOS / "patrocinadores" / name)
    inked = split_ink(image, *mode, variant.ink) if isinstance(mode, tuple) else one_ink(image, mode, variant.ink)
    return fit(inked, max_width_m, height_m)


def build(variant: Variant) -> list[Canvas]:
    ink = variant.ink
    sonnet = trimmed(LOGOS / variant.sonnet)

    # Delante: entre el cuello (unos 11 cm por encima del pecho) y la cintura. El
    # arte del DevFest grande, como en la camiseta real, y Sonnet Code debajo.
    front = Canvas("staff-front", "front", (-0.15, -0.16, 0.15, 0.10), ink)
    front.place(devfest_art(0.18, ink), 0.0, 0.004)
    front.place(fit(sonnet, width_m=0.077), 0.0, -0.122)

    # Detrás: STAFF grande arriba y los patrocinadores por niveles, dentro de
    # ±11 cm (más allá la espalda ya gira hacia el costado) y por encima del bajo
    # (a unos 20 cm por debajo del pecho). El pelo tapa lo de más arriba de +9 cm.
    back = Canvas("staff-back", "back", (-0.13, -0.19, 0.13, 0.10), ink)
    back.place(fit(text("STAFF", HEAVY, 0.075, ink, tracking=0.06), width_m=0.19), 0.0, 0.058)
    back.place(lockup(0.10, ink), 0.0, 0.006)
    back.place(fit(sonnet, width_m=0.12), 0.0, -0.045)
    back.row(
        [
            sponsor("platinum-google.png", variant, 0.021, 0.07),
            sponsor("platinum-banco-popular.png", variant, 0.021, 0.08),
        ],
        -0.093,
        0.024,
    )
    back.row(
        [
            sponsor("gold-heva.png", variant, 0.014, 0.045),
            sponsor("gold-bojote.png", variant, 0.016, 0.05),
            sponsor("gold-caribium-blanco.png", variant, 0.009, 0.05),
            sponsor("gold-tt-academy.png", variant, 0.016, 0.05),
        ],
        -0.127,
        0.013,
    )
    back.row(
        [
            sponsor("silver-thraive.png", variant, 0.012, 0.05),
            sponsor("silver-talento-digital.png", variant, 0.015, 0.05),
            sponsor("partner-festiva.png", variant, 0.0095, 0.05),
        ],
        -0.156,
        0.016,
    )
    return [front, back]


# ---------------------------------------------------------------------------
# .meta de Unity (solo si faltan: así no cambian los GUID)
# ---------------------------------------------------------------------------

TEXTURE_META = """fileFormatVersion: 2
guid: {guid}
TextureImporter:
  internalIDToNameTable: []
  externalObjects: {{}}
  serializedVersion: 13
  mipmaps:
    mipMapMode: 0
    enableMipMap: 0
    sRGBTexture: 1
    linearTexture: 0
  isReadable: 1
  textureFormat: 1
  maxTextureSize: 4096
  textureSettings:
    serializedVersion: 2
    filterMode: 1
    aniso: 1
    mipBias: 0
    wrapU: 1
    wrapV: 1
    wrapW: 1
  nPOTScale: 0
  lightmap: 0
  compressionQuality: 50
  alphaUsage: 1
  alphaIsTransparency: 1
  textureType: 0
  textureShape: 1
  platformSettings:
  - serializedVersion: 4
    buildTarget: DefaultTexturePlatform
    maxTextureSize: 4096
    resizeAlgorithm: 0
    textureFormat: -1
    textureCompression: 0
    compressionQuality: 50
    crunchedCompression: 0
    allowsAlphaSplitting: 0
    overridden: 0
  - serializedVersion: 4
    buildTarget: Standalone
    maxTextureSize: 4096
    resizeAlgorithm: 0
    textureFormat: -1
    textureCompression: 0
    compressionQuality: 50
    crunchedCompression: 0
    allowsAlphaSplitting: 0
    overridden: 0
  userData:
  assetBundleName:
  assetBundleVariant:
"""

FOLDER_META = """fileFormatVersion: 2
guid: {guid}
folderAsset: yes
DefaultImporter:
  externalObjects: {{}}
  userData:
  assetBundleName:
  assetBundleVariant:
"""

TEXT_META = """fileFormatVersion: 2
guid: {guid}
TextScriptImporter:
  externalObjects: {{}}
  userData:
  assetBundleName:
  assetBundleVariant:
"""


def ensure_meta(path: Path, template: str) -> None:
    meta = path.with_name(path.name + ".meta")
    if not meta.exists():
        meta.write_text(template.format(guid=uuid.uuid4().hex), encoding="utf-8")


def write_variant(variant: Variant, preview: Path | None) -> str:
    folder = OUT / variant.name
    folder.mkdir(parents=True, exist_ok=True)
    ensure_meta(OUT, FOLDER_META)
    ensure_meta(folder, FOLDER_META)
    canvases = build(variant)
    for canvas in canvases:
        path = folder / f"{canvas.name}.png"
        canvas.image.save(path, optimize=True)
        ensure_meta(path, TEXTURE_META)
        if preview:
            preview.mkdir(parents=True, exist_ok=True)
            sheet = Image.new("RGBA", canvas.image.size, variant.shirt)
            sheet.alpha_composite(canvas.image)
            sheet.convert("RGB").save(preview / f"{variant.name}-{canvas.name}.png")
    config = {"variant": variant.name, "color": variant.shirt, "prints": [c.describe() for c in canvases]}
    json_path = folder / "staff-shirt.json"
    json_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    ensure_meta(json_path, TEXT_META)
    return f"{variant.name}: " + ", ".join(f"{c.name}.png {c.image.width}x{c.image.height}" for c in canvases)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("variants", nargs="*", choices=list(VARIANTS), help="variantes (por defecto, todas)")
    parser.add_argument("--preview", type=Path, help="carpeta para vistas previas sobre la tela de cada variante")
    args = parser.parse_args()
    for name in args.variants or VARIANTS:
        print("listo", write_variant(VARIANTS[name], args.preview))


if __name__ == "__main__":
    main()
