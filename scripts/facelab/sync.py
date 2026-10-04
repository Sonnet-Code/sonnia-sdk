"""Laboratorio de cara (ver docs/cara-y-lipsync.md). Dependencias: uv run --with numpy --with scipy --with pillow --with matplotlib python ..."""
import os, sys, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze import load_frames, load_audio, envelope
from pathlib import Path
out = Path(sys.argv[1])
rows = load_frames(out)
t = np.array([r["time"] for r in rows])
data, rate = load_audio(out)
fps = 1 / (t[1] - t[0])
# envolvente del audio oído a la misma resolución que los fotogramas (ventana centrada)
env = envelope(data, rate, t - 0.5 / fps, window=1 / fps)
db = 20 * np.log10(env + 1e-6)
lvl = np.clip((db + 50) / 30, 0, 1)
mo = np.array([float(r["mouthOpen"]) for r in rows])
# solo el tramo con voz
mask = t > 4.0
a = lvl[mask] - lvl[mask].mean(); b = mo[mask] - mo[mask].mean()
best = None
for lag in range(-12, 13):
    if lag >= 0:
        c = np.corrcoef(a[:len(a) - lag], b[lag:])[0, 1]
    else:
        c = np.corrcoef(a[-lag:], b[:len(b) + lag])[0, 1]
    print(f"lag {lag:+3d} fr ({lag / fps * 1000:+6.1f} ms): r={c:.3f}")
    if best is None or c > best[1]:
        best = (lag, c)
print("mejor: boca", "después" if best[0] > 0 else "antes", f"del audio en {abs(best[0]) / fps * 1000:.0f} ms (r={best[1]:.3f})")
