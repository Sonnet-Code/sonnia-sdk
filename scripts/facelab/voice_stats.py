"""Laboratorio de cara (ver docs/cara-y-lipsync.md). Dependencias: uv run --with numpy --with scipy --with pillow --with matplotlib python ..."""
import sys, wave, numpy as np
from scipy import signal
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
path = sys.argv[1]; title = sys.argv[2] if len(sys.argv) > 2 else ""
w = wave.open(path); sr = w.getframerate()
x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
hop = int(sr * 0.005)
def band(lo, hi):
    sos = signal.butter(2, [lo, hi], btype="band", fs=sr, output="sos")
    return signal.sosfilt(sos, x)
bands = {"low 100-500": band(100, 500), "mid 500-1500": band(500, 1500), "high 1500-3500": band(1500, 3500), "sib 4000-10000": band(4000, min(10000, sr/2-100))}
n = len(x) // hop
def db(sig):
    e = np.array([np.sqrt(np.mean(sig[i*hop:(i+1)*hop]**2)) for i in range(n)])
    return 20*np.log10(e + 1e-7)
tot = db(x)
print("rms dB percentiles (voz > -50):", np.percentile(tot[tot > -50], [5, 25, 50, 75, 95, 99]).round(1))
t = np.arange(n) * hop / sr
fig, axes = plt.subplots(3, 1, figsize=(24, 11), sharex=True)
f, tt, S = signal.spectrogram(x, fs=sr, nperseg=512, noverlap=512-hop, scaling="spectrum")
axes[0].pcolormesh(tt, f, 10*np.log10(S + 1e-12), shading="auto", vmin=-110, vmax=-30, cmap="magma")
axes[0].set_ylim(0, 5000); axes[0].set_title(title, loc="left")
axes[1].plot(t, tot, "k", lw=0.8, label="total")
for k, v in bands.items():
    axes[1].plot(t, db(v), lw=0.7, label=k)
axes[1].set_ylim(-80, -5); axes[1].legend(ncol=5, fontsize=8); axes[1].grid(alpha=.3)
sib = db(bands["sib 4000-10000"]); low = db(bands["low 100-500"]); mid = db(bands["mid 500-1500"]); hi = db(bands["high 1500-3500"])
axes[2].plot(t, sib - np.maximum(low, mid), lw=0.7, label="sib - max(low,mid)")
axes[2].plot(t, low - mid, lw=0.7, label="low - mid")
axes[2].plot(t, hi - mid, lw=0.7, label="high - mid")
axes[2].axhline(0, color="gray", lw=0.5); axes[2].set_ylim(-40, 30); axes[2].legend(fontsize=8); axes[2].grid(alpha=.3)
axes[2].set_xticks(np.arange(0, t[-1], 0.1), minor=True); axes[2].grid(which="minor", alpha=.15)
plt.tight_layout(); out = path.split("/")[-1].replace(".wav", "_stats.png"); plt.savefig(out, dpi=62); print(out)
