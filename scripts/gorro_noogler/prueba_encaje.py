"""Prueba de encajar.py con una gorra «oficial» sintética: la malla entera del
gorro (copa, forro, visera y tira, sin la hélice) deformada, girada, escalada y
con ruido, en un espacio de cabeza con ejes arbitrarios. Compara con la verdad.

Uso: uv run --no-project --with numpy --with scipy --with matplotlib \
         python scripts/gorro_noogler/prueba_encaje.py [cabeceo alabeo guiñada [ancho alto fondo]]
Con la forma exacta (1 1 1) el giro sale a menos de 0,2° y la posición a 0,1 mm.
"""

import math
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rutas import AQUI, TRABAJO, read_json, write_json  # noqa: E402

pitch, roll, yaw = (float(v) for v in (sys.argv[1:4] if len(sys.argv) > 3 else (-9, 2, 0)))
# Ancho, alto y fondo de la copa distintos (por defecto 1, 0,95 y 1,05).
stretch = (
    np.array([float(v) for v in sys.argv[4:7]])
    if len(sys.argv) > 6
    else np.array([1.0, 0.95, 1.05])
)
noise = 0.0007

body = read_json(os.path.join(TRABAJO, "body_mesh.json"))
v = np.array(body["vertices"]) * stretch
n = np.array(body["normals"]) / stretch
n /= np.linalg.norm(n, axis=1, keepdims=True)


def rot(axis, deg):
    axis = np.asarray(axis, float) / np.linalg.norm(axis)
    k = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    a = math.radians(deg)
    return np.eye(3) + math.sin(a) * k + (1 - math.cos(a)) * k @ k


# Ejes del avatar vistos desde un hueso de cabeza girado como los de Genies.
head = rot([0.3, 1, 0.2], 97) @ rot([1, 0, 0], -90)
up = head @ np.array([0, 1.0, 0])
fwd = head @ np.array([0, 0, 1.0])
right = np.cross(up, fwd)
basis = np.column_stack([right, up, fwd])
r_true = basis @ rot([0, 1, 0], yaw) @ rot([1, 0, 0], pitch) @ rot([0, 0, 1], roll)
s_true = 1.42
t_true = basis @ np.array([0.004, 0.128, 0.021])
rng = np.random.default_rng(1)
pts = s_true * v @ r_true.T + t_true + rng.normal(0, noise, v.shape)
write_json(
    os.path.join(TRABAJO, "gorra_prueba.json"),
    {
        "vertices": pts.tolist(),
        "normals": (n @ r_true.T).tolist(),
        "triangles": body["triangles"],
        "up": up.tolist(),
        "forward": fwd.tolist(),
        "head_scale": 1.0,
    },
)
print(
    f"VERDAD cabeceo {pitch} alabeo {roll} guiñada {yaw} escala {s_true} (copa deformada {stretch.tolist()})",
    flush=True,
)
result = os.path.join(TRABAJO, "gorra_prueba_fit.json")
subprocess.run(
    [
        sys.executable,
        os.path.join(AQUI, "encajar.py"),
        os.path.join(TRABAJO, "gorra_prueba.json"),
        result,
    ],
    check=True,
)
fit = read_json(result)
x, y, z, w = fit["rotation"]
r_fit = np.array(
    [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]
)
angle = math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(r_fit @ r_true.T) - 1) / 2))))
print(
    f"ERROR: giro {angle:.2f}°, escala {fit['scale']:.4f} (verdad {s_true}), "
    f"posición {np.linalg.norm(np.array(fit['position']) - t_true) * 1000:.1f} mm"
)
