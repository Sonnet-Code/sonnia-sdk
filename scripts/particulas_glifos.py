"""Genera las texturas de glifos de las partículas del escenario (StageParticles).

Salen en unity/Assets/Resources/Particles y las carga StageParticles en Play:

- matrix-glyphs.png: 64 glifos blancos (8 x 8 celdas de 64 px) para la lluvia
  estilo Matrix que sale cuando Sonnia busca en internet:
  katakana de media anchura en espejo, como en la película, cifras y unos
  cuantos símbolos. Cada glifo lleva un brillo suave alrededor, para que se vea
  luminoso aunque el bloom esté apagado.
- trivia-glyphs.png: 8 símbolos blancos (4 x 2 celdas de 128 px) para la
  trivia: en la fila de arriba «?», estrella, «!» y otra «?» más fina (los que
  flotan despacio: la mitad son interrogaciones); en la de abajo destello,
  punto, estrella pequeña y «+» (los destellos y la explosión del acierto). El
  color lo pone Unity.

El RGB es blanco en toda la imagen y el glifo va en el alfa: las partículas son
aditivas y el tinte de cada una decide el color.

Uso, desde la raíz del repo (solo en macOS: usa las fuentes del sistema para el
katakana; Manrope y Geist Mono vienen en el repo):

    uv run --with pillow --with numpy python scripts/particulas_glifos.py
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "unity" / "Assets" / "Resources" / "Particles"
FONTS = ROOT / "unity" / "Assets" / "Resources" / "Stage" / "Fonts"

#: Katakana de media anchura (46), en espejo como en la película.
KATAKANA = "ｦｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜﾝ"
DIGITS = "0123456789"
SYMBOLS = "日ΦЖΞZ=*+"

#: Fuentes por orden de preferencia: la primera que tenga el glifo.
KANA_FONTS = [
    Path("/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"),
    Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
    Path("/Library/Fonts/Arial Unicode.ttf"),
]
LATIN_FONTS = [FONTS / "GeistMono-Medium.ttf", *KANA_FONTS]

MATRIX_CELL = 64
MATRIX_GRID = 8
TRIVIA_CELL = 128


def _font(paths: list[Path], size: int, char: str) -> ImageFont.FreeTypeFont:
    """La primera fuente de la lista que dibuja ``char`` (no la caja de «no existe»)."""
    for path in paths:
        if not path.exists():
            continue
        font = ImageFont.truetype(str(path), size)
        if font.getmask(char).getbbox() is not None and _has_glyph(font, char):
            return font
    raise SystemExit(f"Ninguna fuente tiene «{char}»: {', '.join(str(p) for p in paths)}")


def _has_glyph(font: ImageFont.FreeTypeFont, char: str) -> bool:
    """Distingue el glifo de verdad del recuadro de relleno (``.notdef``)."""
    notdef = font.getmask("\U0010fffd").getbbox()
    mask = font.getmask(char)
    return mask.getbbox() is not None and (notdef is None or mask.getbbox() != notdef or char == " ")


def _centered(char: str, font: ImageFont.FreeTypeFont, cell: int, fill: float) -> Image.Image:
    """El glifo en blanco sobre negro, centrado y escalado a ``fill`` de la celda."""
    big = cell * 4
    canvas = Image.new("L", (big, big), 0)
    draw = ImageDraw.Draw(canvas)
    draw.text((big // 2, big // 2), char, font=font, fill=255, anchor="mm")
    box = canvas.getbbox()
    if box is None:
        raise SystemExit(f"«{char}» sale vacío")
    glyph = canvas.crop(box)
    target = cell * fill
    scale = target / max(glyph.width, glyph.height)
    size = (max(1, round(glyph.width * scale)), max(1, round(glyph.height * scale)))
    glyph = glyph.resize(size, Image.LANCZOS)
    out = Image.new("L", (cell, cell), 0)
    out.paste(glyph, ((cell - size[0]) // 2, (cell - size[1]) // 2))
    return out


def _glow(alpha: Image.Image, radius: float, strength: float) -> Image.Image:
    """Suma al alfa un halo difuminado del propio glifo."""
    blurred = np.asarray(alpha.filter(ImageFilter.GaussianBlur(radius)), dtype=np.float32)
    sharp = np.asarray(alpha, dtype=np.float32)
    mixed = np.maximum(sharp, np.minimum(255.0, blurred * strength))
    return Image.fromarray(mixed.astype(np.uint8), "L")


def _rgba(alpha: Image.Image) -> Image.Image:
    white = Image.new("L", alpha.size, 255)
    return Image.merge("RGBA", (white, white, white, alpha))


def matrix_atlas() -> Image.Image:
    chars = KATAKANA + DIGITS + SYMBOLS
    assert len(chars) == MATRIX_GRID * MATRIX_GRID, len(chars)
    atlas = Image.new("L", (MATRIX_CELL * MATRIX_GRID, MATRIX_CELL * MATRIX_GRID), 0)
    for index, char in enumerate(chars):
        fonts = KANA_FONTS if char in KATAKANA or char in "日ΦЖΞ" else LATIN_FONTS
        font = _font(fonts, MATRIX_CELL * 2, char)
        glyph = _centered(char, font, MATRIX_CELL, 0.74)
        if char in KATAKANA:
            glyph = glyph.transpose(Image.FLIP_LEFT_RIGHT)
        glyph = _glow(glyph, MATRIX_CELL * 0.07, 0.55)
        # La fila 0 del atlas es la de arriba de la imagen, como la lee Unity
        # (la animación de hoja empieza arriba a la izquierda).
        x = (index % MATRIX_GRID) * MATRIX_CELL
        y = (index // MATRIX_GRID) * MATRIX_CELL
        atlas.paste(glyph, (x, y))
    return _rgba(atlas)


def _star(cell: int, points: int, outer: float, inner: float) -> Image.Image:
    big = cell * 4
    canvas = Image.new("L", (big, big), 0)
    c = big / 2
    vertices = []
    for i in range(points * 2):
        r = (outer if i % 2 == 0 else inner) * big / 2
        a = -math.pi / 2 + i * math.pi / points
        vertices.append((c + r * math.cos(a), c + r * math.sin(a)))
    ImageDraw.Draw(canvas).polygon(vertices, fill=255)
    return canvas.resize((cell, cell), Image.LANCZOS)


def _sparkle(cell: int) -> Image.Image:
    """Destello de cuatro puntas con los lados curvos hacia dentro."""
    big = cell * 4
    c = big / 2
    yy, xx = np.mgrid[0:big, 0:big].astype(np.float32)
    dx = np.abs(xx - c) / (big * 0.46)
    dy = np.abs(yy - c) / (big * 0.46)
    # Astroide: |x|^(2/3) + |y|^(2/3) <= 1, con el borde suave.
    value = dx ** (2 / 3) + dy ** (2 / 3)
    alpha = np.clip((1.0 - value) * 6.0, 0.0, 1.0) * 255
    return Image.fromarray(alpha.astype(np.uint8), "L").resize((cell, cell), Image.LANCZOS)


def _dot(cell: int) -> Image.Image:
    yy, xx = np.mgrid[0:cell, 0:cell].astype(np.float32)
    c = (cell - 1) / 2
    d = np.sqrt((xx - c) ** 2 + (yy - c) ** 2) / (cell * 0.42)
    alpha = np.clip(1.0 - d, 0.0, 1.0) ** 1.6 * 255
    return Image.fromarray(alpha.astype(np.uint8), "L")


def _plus(cell: int) -> Image.Image:
    big = cell * 4
    canvas = Image.new("L", (big, big), 0)
    draw = ImageDraw.Draw(canvas)
    arm, thick = big * 0.36, big * 0.11
    c = big / 2
    draw.rounded_rectangle((c - arm, c - thick, c + arm, c + thick), radius=thick, fill=255)
    draw.rounded_rectangle((c - thick, c - arm, c + thick, c + arm), radius=thick, fill=255)
    return canvas.resize((cell, cell), Image.LANCZOS)


def trivia_atlas() -> Image.Image:
    bold = [FONTS / "Manrope-ExtraBold.ttf"]
    semibold = [FONTS / "Manrope-SemiBold.ttf"]
    cells = [
        _centered("?", _font(bold, TRIVIA_CELL * 2, "?"), TRIVIA_CELL, 0.78),
        _star(TRIVIA_CELL, 5, 0.86, 0.38),
        _centered("!", _font(bold, TRIVIA_CELL * 2, "!"), TRIVIA_CELL, 0.74),
        _centered("?", _font(semibold, TRIVIA_CELL * 2, "?"), TRIVIA_CELL, 0.7),
        _sparkle(TRIVIA_CELL),
        _dot(TRIVIA_CELL),
        _star(TRIVIA_CELL, 5, 0.62, 0.27),
        _plus(TRIVIA_CELL),
    ]
    atlas = Image.new("L", (TRIVIA_CELL * 4, TRIVIA_CELL * 2), 0)
    for index, cell in enumerate(cells):
        cell = _glow(cell, TRIVIA_CELL * 0.05, 0.5)
        atlas.paste(cell, ((index % 4) * TRIVIA_CELL, (index // 4) * TRIVIA_CELL))
    return _rgba(atlas)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    matrix_atlas().save(OUT / "matrix-glyphs.png", optimize=True)
    trivia_atlas().save(OUT / "trivia-glyphs.png", optimize=True)
    print(f"Glifos en {OUT.relative_to(ROOT)}: matrix-glyphs.png, trivia-glyphs.png")


if __name__ == "__main__":
    main()
