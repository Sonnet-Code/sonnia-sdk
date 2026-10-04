"""Laboratorio de cara (ver docs/cara-y-lipsync.md). Dependencias: uv run --with numpy --with scipy --with pillow --with matplotlib python ..."""
import sys, wave, numpy as np
from scipy import signal
def load(path):
    w = wave.open(path); sr = w.getframerate()
    x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    return x, sr
def bands(x, sr, hop):
    def b(lo, hi):
        return signal.sosfilt(signal.butter(2, [lo, hi], btype="band", fs=sr, output="sos"), x)
    sig = {"tot": x, "low": b(100, 500), "mid": b(500, 1500), "high": b(1500, 3500), "sib": b(4000, min(10000, sr / 2 - 100))}
    n = len(x) // hop
    return {k: 20 * np.log10(np.array([np.sqrt(np.mean(v[i*hop:(i+1)*hop]**2)) for i in range(n)]) + 1e-7) for k, v in sig.items()}
def lpc_formants(frame, sr, order=12):
    frame = frame * np.hamming(len(frame))
    frame = np.append(frame[0], frame[1:] - 0.63 * frame[:-1])
    r = np.correlate(frame, frame, "full")[len(frame)-1:len(frame)+order]
    if r[0] <= 0: return None
    # Levinson
    a = np.zeros(order + 1); a[0] = 1; e = r[0]
    for i in range(1, order + 1):
        k = -(r[i] + np.dot(a[1:i], r[i-1:0:-1])) / e
        a[1:i] = a[1:i] + k * a[i-1:0:-1]
        a[i] = k; e *= (1 - k * k)
    roots = np.roots(a); roots = roots[np.imag(roots) > 0]
    f = np.angle(roots) * sr / (2 * np.pi); bw = -sr / np.pi * np.log(np.abs(roots))
    cand = sorted(fi for fi, bi in zip(f, bw) if fi > 200 and bi < 500)
    return cand[:3] if len(cand) >= 2 else None
if __name__ == "__main__":
    path = sys.argv[1]; t0 = float(sys.argv[2]); t1 = float(sys.argv[3])
    x, sr = load(path)
    hop = int(sr * 0.01)
    B = bands(x, sr, hop)
    tot = B["tot"]
    # remuestreo a 11025 para formantes
    y = signal.resample_poly(x, 11025, sr) if sr != 11025 else x
    for i in range(1, len(tot) - 1):
        t = i * hop / sr
        if t < t0 or t > t1: continue
        if tot[i] > -32 and tot[i] >= tot[i-1] and tot[i] >= tot[i+1]:
            c = int(t * 11025); fr = y[c - 138:c + 138]
            fm = lpc_formants(fr, 11025) if c > 138 else None
            fs = " ".join(f"{v:5.0f}" for v in fm) if fm else "-"
            print(f"t={t:5.2f} tot={tot[i]:6.1f} mid-low={B['mid'][i]-B['low'][i]:6.1f} high-mid={B['high'][i]-B['mid'][i]:6.1f} sib-max={B['sib'][i]-max(B['low'][i],B['mid'][i]):6.1f}  F={fs}")
