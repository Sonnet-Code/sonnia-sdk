"""Laboratorio de cara (ver docs/cara-y-lipsync.md). Dependencias: uv run --with numpy --with scipy --with pillow --with matplotlib python ..."""
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
out = Path(sys.argv[1])
crop = tuple(int(v) for v in sys.argv[2].split(",")) if len(sys.argv) > 2 else None
cols = int(sys.argv[3]) if len(sys.argv) > 3 else 6
scale = float(sys.argv[4]) if len(sys.argv) > 4 else 0.6
filt = sys.argv[5] if len(sys.argv) > 5 else ""
name = sys.argv[6] if len(sys.argv) > 6 else "gallery_sheet.jpg"
last = {}
order = []
for line in open(out / "frames.tsv", encoding="utf-8").read().splitlines()[1:]:
    p = line.split("\t")
    f, label = int(p[0]), p[2]
    if not label.startswith("shape"):
        continue
    if label not in last:
        order.append(label)
    last[label] = f
font = ImageFont.load_default(size=15)
tiles = []
for label in order:
    if filt and not any(k in label for k in filt.split("|")):
        continue
    f = last[label]
    path = out / "closeup" / f"{f:05d}.jpg"
    if not path.exists():
        path = out / "closeup" / f"{f-1:05d}.jpg"
    im = Image.open(path).convert("RGB")
    if crop:
        x, y, w, h = crop
        im = im.crop((x, y, x + w, y + h))
    im = im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
    c = Image.new("RGB", (im.width, im.height + 20), (15, 15, 15))
    c.paste(im, (0, 20))
    ImageDraw.Draw(c).text((3, 2), label.replace("shape:", "")[:48] or "neutro", fill=(255, 255, 0), font=font)
    tiles.append(c)
w, h = tiles[0].size
rows = (len(tiles) + cols - 1) // cols
sheet = Image.new("RGB", (w * cols, h * rows))
for i, t in enumerate(tiles):
    sheet.paste(t, ((i % cols) * w, (i // cols) * h))
sheet.save(out / name, quality=90)
print(out / name, sheet.size, len(tiles))
