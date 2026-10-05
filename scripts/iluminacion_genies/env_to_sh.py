"""Ambiente SH de Unity a partir del HDR equirectangular de Mia (three.js).

Unity guarda el ambiente (RenderSettings.ambientProbe) ya convolucionado con el
coseno y dividido entre pi: el shader evalúa directamente
  f(N) = c0 + c1·y + c2·z + c3·x + c4·xy + c5·yz + c6·(3z²−1) + c7·xz + c8·(x²−y²)
(ver SHCoefficients en com.unity.render-pipelines.core: SHAr = (c3, c1, c2, c0−c6)…)
y el difuso es albedo·f(N). Con eso:
  c_lm = (A_l/pi)·L_lm·k_lm, A0/pi = 1, A1/pi = 2/3, A2/pi = 1/4,
donde L_lm es la proyección de la radiancia en la base real ortonormal.

Conversión de ejes: three.js mira con el avatar hacia +Z y la cámara en +Z;
en Sonia el avatar mira a −Z y la cámara está en −Z. Una dirección (x, y, z)
de three.js es (x, y, −z) en Unity.

Uso (desde server/, con las dependencias de la cámara instaladas):
  OPENCV_IO_ENABLE_OPENEXR=1 uv run --no-sync python env_to_sh.py HDR.exr 0.425 0.275021
donde 0,425 = environmentIntensity 0,5 × (1 − flatness 0,15) y 0,275021 =
0,85 × (#b5b5b5 lineal / π) + 0,15.
"""

import json
import os
import sys

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

image = cv2.imread(sys.argv[1], cv2.IMREAD_UNCHANGED)
if image is None:
    raise SystemExit(f"No se pudo leer {sys.argv[1]} (¿OpenCV sin OpenEXR?)")
rgb = image[..., 2::-1].astype(np.float64)  # BGR(A) -> RGB lineal, [fila desde arriba, columna, rgb]
env_scale = float(sys.argv[2])        # environmentIntensity × (1 − flatness)
dc_add = float(sys.argv[3])           # ambiente plano + flatness, en unidades de Unity
H, W, _ = rgb.shape
v = 1.0 - (np.arange(H) + 0.5) / H    # v = 1 arriba (EXRLoader invierte las filas)
u = (np.arange(W) + 0.5) / W
lat = (v - 0.5) * np.pi               # asin(y)
phi = (u - 0.5) * 2.0 * np.pi         # atan2(z, x) de three.js
LAT, PHI = np.meshgrid(lat, phi, indexing="ij")
tx, ty, tz = np.cos(LAT) * np.cos(PHI), np.sin(LAT), np.cos(LAT) * np.sin(PHI)
x, y, z = tx, ty, -tz                 # a ejes de Unity
dA = np.cos(LAT) * (np.pi / H) * (2.0 * np.pi / W)

basis = [
    0.282095 * np.ones_like(x),
    0.488603 * y, 0.488603 * z, 0.488603 * x,
    1.092548 * x * y, 1.092548 * y * z, 0.315392 * (3 * z * z - 1), 1.092548 * x * z, 0.546274 * (x * x - y * y),
]
norm = [0.282095, 0.488603, 0.488603, 0.488603, 1.092548, 1.092548, 0.315392, 1.092548, 0.546274]
band = [1.0, 2 / 3, 2 / 3, 2 / 3, 0.25, 0.25, 0.25, 0.25, 0.25]
L = np.array([[(rgb[..., ch] * Y * dA).sum() for Y in basis] for ch in range(3)])  # [canal, 9]
coef = np.array([[band[i] * norm[i] * L[ch, i] for i in range(9)] for ch in range(3)]) * env_scale
coef[:, 0] += dc_add

def evaluate(c, n):
    n = np.asarray(n, float) / np.linalg.norm(n)
    X, Y, Z = n
    poly = [1, Y, Z, X, X * Y, Y * Z, 3 * Z * Z - 1, X * Z, X * X - Y * Y]
    return c @ np.array(poly)

def brute(n):
    n = np.asarray(n, float) / np.linalg.norm(n)
    cosw = np.clip(x * n[0] + y * n[1] + z * n[2], 0, None)
    return (rgb * (cosw * dA)[..., None]).sum((0, 1)) / np.pi * env_scale + dc_add

dirs = {"arriba": (0, 1, 0), "abajo": (0, -1, 0), "der. pantalla +X": (1, 0, 0), "izq. -X": (-1, 0, 0),
        "hacia cámara -Z": (0, 0, -1), "detrás +Z": (0, 0, 1), "cara 3/4 izq": (-0.5, 0.2, -0.85)}
for k, n in dirs.items():
    print(f"{k:18s} SH {np.round(evaluate(coef, n), 3)}  exacto {np.round(brute(n), 3)}")

def lin2srgb(c):
    c = np.clip(c, 0, None)
    return np.where(c <= 0.0031308, 12.92 * c, 1.055 * np.power(c, 1 / 2.4) - 0.055)

horizon = np.mean([evaluate(coef, (np.cos(a), 0, np.sin(a))) for a in np.linspace(0, 2 * np.pi, 16, endpoint=False)], axis=0)
tri = {"sky": evaluate(coef, (0, 1, 0)), "equator": horizon, "ground": evaluate(coef, (0, -1, 0))}
print("Trilight (lineal):", {k: np.round(c, 3).tolist() for k, c in tri.items()})
print("Trilight (sRGB para RenderSettings):", {k: np.round(lin2srgb(c), 4).tolist() for k, c in tri.items()})
out = {"coefficients": [[round(float(c), 6) for c in row] for row in coef],
       "trilight_srgb": {k: [round(float(c), 4) for c in lin2srgb(v)] for k, v in tri.items()}}
print(json.dumps(out))
