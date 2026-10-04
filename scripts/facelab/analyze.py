"""Análisis de una pasada del laboratorio de cara.

Uso:
  analyze.py OUT plot                  -> curvas de blendshapes vs. audio (plot.png)
  analyze.py OUT sheet A B STEP [crop] -> hoja de contactos de primeros planos (sheet_A_B.jpg)
     crop = x,y,w,h en píxeles del primer plano (por defecto la cara entera)
"""

import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def load_frames(out: Path):
    rows = []
    with open(out / "frames.tsv", encoding="utf-8") as f:
        header = f.readline().rstrip("\n").split("\t")
        for line in f:
            parts = line.rstrip("\n").split("\t")
            row = dict(zip(header, parts))
            shapes = {}
            for item in row.get("shapes", "").split():
                if "=" in item:
                    k, v = item.split("=")
                    shapes[k] = float(v)
            row["shapes"] = shapes
            row["frame"] = int(row["frame"])
            row["time"] = float(row["time"])
            rows.append(row)
    return rows


def load_audio(out: Path):
    with wave.open(str(out / "heard.wav")) as w:
        rate = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    return data, rate


def envelope(data, rate, times, window=1 / 60):
    env = []
    for t in times:
        a = int(t * rate)
        b = int((t + window) * rate)
        seg = data[a:b]
        env.append(float(np.sqrt(np.mean(seg**2))) if len(seg) else 0.0)
    return np.array(env)


def plot(out: Path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = load_frames(out)
    t = np.array([r["time"] for r in rows])
    data, rate = load_audio(out)
    env = envelope(data, rate, t)
    groups = {
        "boca (visemas)": ["viseme_aa", "viseme_E", "viseme_I", "viseme_O", "viseme_U", "viseme_nn", "viseme_PP", "viseme_FF", "viseme_SS", "viseme_CH", "viseme_DD", "viseme_kk", "viseme_RR", "viseme_TH", "viseme_sil"],
        "boca (ARKit)": ["jawOpen", "mouthClose", "mouthFunnel", "mouthPucker", "mouthSmileLeft", "mouthStretchLeft", "mouthPressLeft", "mouthLowerDownLeft", "mouthUpperUpLeft", "mouthRollLower", "mouthShrugUpper"],
        "cejas y ojos": ["browInnerUp", "browOuterUpLeft", "browDownLeft", "eyeSquintLeft", "eyeWideLeft", "cheekSquintLeft", "eyeBlinkLeft", "noseSneerLeft"],
    }
    fig, axes = plt.subplots(len(groups) + 2, 1, figsize=(22, 16), sharex=True)
    axes[0].plot(t, env / max(env.max(), 1e-6), color="k", lw=0.8, label="audio oído (RMS)")
    vol = np.array([float(r["vol"]) if r["vol"] not in ("-", "") else 0 for r in rows])
    mo = np.array([float(r["mouthOpen"]) if r["mouthOpen"] not in ("-", "") else 0 for r in rows])
    axes[0].plot(t, vol, color="tab:orange", lw=0.8, label="volumen puente")
    axes[0].plot(t, mo, color="tab:blue", lw=0.8, label="MouthOpen")
    axes[0].legend(loc="upper right")
    for ax, (title, names) in zip(axes[1:], groups.items()):
        for name in names:
            y = np.array([r["shapes"].get(name, 0.0) for r in rows])
            if y.max() > 0.01:
                ax.plot(t, y, lw=0.9, label=name)
        ax.set_title(title, loc="left", fontsize=9)
        ax.legend(loc="upper right", fontsize=7, ncol=4)
        ax.set_ylim(0, 1)
    hp = np.array([float(r["headPitch"]) if r["headPitch"] != "-" else 0 for r in rows])
    hy = np.array([float(r["headYaw"]) if r["headYaw"] != "-" else 0 for r in rows])
    el = [r["eyeL"].split(",") for r in rows]
    ex = np.array([float(e[0]) if len(e) == 2 else 0 for e in el])
    ey = np.array([float(e[1]) if len(e) == 2 else 0 for e in el])
    axes[-1].plot(t, hp, label="cabeza pitch")
    axes[-1].plot(t, hy, label="cabeza yaw")
    axes[-1].plot(t, ex, label="ojo izq x")
    axes[-1].plot(t, ey, label="ojo izq y")
    axes[-1].legend(loc="upper right", fontsize=7)
    # cambios de etiqueta
    last = None
    for r in rows:
        if r["label"] != last:
            for ax in axes:
                ax.axvline(r["time"], color="gray", lw=0.5, ls="--")
            axes[0].text(r["time"], 1.02, r["label"], fontsize=7, rotation=0)
            last = r["label"]
    plt.tight_layout()
    fig.savefig(out / "plot.png", dpi=70)
    print(out / "plot.png")


def sheet(out: Path, a: int, b: int, step: int, crop=None, cols=8, scale=1.0, tag="closeup"):
    rows = {r["frame"]: r for r in load_frames(out)}
    frames = list(range(a, b + 1, step))
    tiles = []
    font = ImageFont.load_default(size=14)
    for f in frames:
        path = out / tag / f"{f:05d}.jpg"
        if not path.exists():
            continue
        im = Image.open(path).convert("RGB")
        if crop:
            x, y, w, h = crop
            im = im.crop((x, y, x + w, y + h))
        if scale != 1.0:
            im = im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
        r = rows.get(f)
        canvas = Image.new("RGB", (im.width, im.height + 34), (20, 20, 20))
        canvas.paste(im, (0, 34))
        d = ImageDraw.Draw(canvas)
        if r:
            sh = r["shapes"]
            vis = sorted(((k[7:], v) for k, v in sh.items() if k.startswith("viseme_")), key=lambda kv: -kv[1])[:2]
            vtxt = " ".join(f"{k}{v:.2f}" for k, v in vis)
            d.text((3, 1), f"{f} t{r['time']:.2f} {r['state'][:4]} {r['phoneme']}", fill=(255, 255, 0), font=font)
            d.text((3, 17), f"{vtxt} jaw{sh.get('jawOpen', 0):.2f} sm{sh.get('mouthSmileLeft', 0):.2f}", fill=(180, 255, 180), font=font)
        tiles.append(canvas)
    if not tiles:
        print("sin fotogramas")
        return
    w, h = tiles[0].size
    rows_n = (len(tiles) + cols - 1) // cols
    sheet_im = Image.new("RGB", (w * cols, h * rows_n), (0, 0, 0))
    for i, tile in enumerate(tiles):
        sheet_im.paste(tile, ((i % cols) * w, (i // cols) * h))
    name = out / f"sheet_{tag}_{a}_{b}_{step}.jpg"
    sheet_im.save(name, quality=90)
    print(name, sheet_im.size)


if __name__ == "__main__":
    out = Path(sys.argv[1])
    cmd = sys.argv[2]
    if cmd == "plot":
        plot(out)
    elif cmd == "sheet":
        a, b, step = int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
        crop = tuple(int(v) for v in sys.argv[6].split(",")) if len(sys.argv) > 6 and sys.argv[6] != "-" else None
        cols = int(sys.argv[7]) if len(sys.argv) > 7 else 8
        scale = float(sys.argv[8]) if len(sys.argv) > 8 else 1.0
        tag = sys.argv[9] if len(sys.argv) > 9 else "closeup"
        sheet(out, a, b, step, crop, cols, scale, tag)
