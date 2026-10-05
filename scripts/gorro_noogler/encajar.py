"""Encaja el gorro Noogler sobre la gorra oficial de Genies.

Uso, desde la raíz del repo (después de construir.py y de medir la gorra en Unity):
    uv run --no-project --with numpy --with scipy --with matplotlib \
        python scripts/gorro_noogler/encajar.py [gorra_oficial.json] [salida.json]

Entrada (por defecto trabajo/gorra_oficial.json, la escribe "Sonia > Medir gorra
oficial" en Play): la gorra oficial horneada, en el espacio del hueso de la cabeza:
  {"vertices": [[x, y, z], ...], "normals": [...], "triangles": [i, j, k, ...] (opcional),
   "up": [...], "forward": [...] (del avatar, vistos desde el hueso), "head_scale": s}
Fuente: trabajo/fit_source.json (sale de construir.py): copa exterior y visera del
gorro Noogler en el espacio del prefab (x derecha, y arriba, z delante; origen en la boca).

1. Se queda con la cara exterior de la gorra oficial (fuera el forro y lo de debajo
   de la visera) y encaja el gorro entero (copa y visera) con un ICP de semejanza
   (giro, escala y traslación) con pares en los dos sentidos y recorte de los
   peores, desde varios cabeceos y guiñadas de partida.
2. Con ese encaje, la visera oficial es lo que queda más cerca de la visera del
   Noogler que de su copa.
3. Afina copa contra copa, punto a punto y luego punto a plano: la copa es lo que
   tiene que coincidir con la cabeza (y con el pelo deformado bajo la gorra).
Escribe NooglerCap_fit.json junto al FBX (posición, giro y escala del prefab en el
espacio de la cabeza; lo lee "Sonia > Crear gorro Noogler") y
trabajo/gorra_oficial_encaje.png (las dos gorras superpuestas de lado, de frente
y desde arriba) para revisarlo.
"""

import math
import os
import sys

import numpy as np
from scipy.spatial import cKDTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rutas import SALIDA, TRABAJO, read_json, write_json  # noqa: E402

OFFICIAL = sys.argv[1] if len(sys.argv) > 1 else os.path.join(TRABAJO, "gorra_oficial.json")
OUT_JSON = sys.argv[2] if len(sys.argv) > 2 else os.path.join(SALIDA, "NooglerCap_fit.json")
OUT_PNG = os.path.join(TRABAJO, os.path.splitext(os.path.basename(OFFICIAL))[0] + "_encaje.png")
TRIM = 0.9  # fracción de pares que se queda en cada sentido
SAMPLES = 6000  # puntos sobre la superficie de la gorra oficial


def normalize(v):
    v = np.asarray(v, dtype=float)
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


# --- Datos -----------------------------------------------------------------------
source = read_json(os.path.join(TRABAJO, "fit_source.json"))
crown_src = np.array(source["crown"]["points"])
crown_src_n = normalize(source["crown"]["normals"])
brim_src = np.array(source["brim"]["points"])
brim_src_n = normalize(source["brim"]["normals"])

official = read_json(OFFICIAL)
verts = np.array(official["vertices"], dtype=float)
vnorm = normalize(official["normals"])
tris = official.get("triangles")
if tris:
    tri = np.array(tris, dtype=int).reshape(-1, 3)
    a, b, c = verts[tri[:, 0]], verts[tri[:, 1]], verts[tri[:, 2]]
    cross = np.cross(b - a, c - a)
    area = 0.5 * np.linalg.norm(cross, axis=1)
    ok = area > 1e-12
    tri, a, b, c, cross, area = tri[ok], a[ok], b[ok], c[ok], cross[ok], area[ok]
    # Normal de cada triángulo orientada como las de sus vértices (el sentido del
    # producto vectorial depende del orden de los vértices).
    fn = cross / (2 * area[:, None])
    vn = vnorm[tri].sum(axis=1)
    fn *= np.where((fn * vn).sum(axis=1) < 0, -1.0, 1.0)[:, None]
    rng = np.random.default_rng(5)
    pick = rng.choice(len(tri), size=SAMPLES, p=area / area.sum())
    r1 = np.sqrt(rng.random(SAMPLES))[:, None]
    r2 = rng.random(SAMPLES)[:, None]
    tgt_all = (1 - r1) * a[pick] + r1 * (1 - r2) * b[pick] + r1 * r2 * c[pick]
    tgt_all_n = fn[pick]
else:
    tgt_all, tgt_all_n = verts, vnorm

# Ejes del avatar en el espacio de la cabeza (Unity: derecha = arriba x delante).
up = normalize(official["up"])
fwd = np.asarray(official["forward"], dtype=float)
fwd = normalize(fwd - up * fwd.dot(up))
right = np.cross(up, fwd)
if np.linalg.det(np.array([right, up, fwd])) < 0:
    right = -right
BASIS = np.column_stack([right, up, fwd])  # prefab (x, y, z) -> cabeza, sin giro relativo


def to_avatar(p):
    """Coordenadas del avatar (derecha, arriba, delante) de puntos del espacio de la cabeza."""
    return np.asarray(p) @ BASIS


# --- Gorra oficial: cara exterior ---------------------------------------------------
P = to_avatar(tgt_all)
Nv = to_avatar(tgt_all_n)
y_min, y_max = np.percentile(P[:, 1], [1, 99])
height = y_max - y_min
upper = P[:, 1] > y_min + 0.6 * height  # lo alto de la copa
center = np.array([np.median(P[upper, 0]), y_min + 0.1 * height, np.median(P[upper, 2])])
outward = ((P - center) * Nv).sum(axis=1) > 0
tgt_out = tgt_all[outward]
tgt_out_n = tgt_all_n[outward]
print(f"GORRA OFICIAL: {len(tgt_all)} puntos, cara exterior {len(tgt_out)}")


# --- ICP -------------------------------------------------------------------------------
def umeyama(src, dst):
    """s, R, t que minimizan |dst - (s R src + t)|^2."""
    ms, md = src.mean(axis=0), dst.mean(axis=0)
    ds, dd = src - ms, dst - md
    u, d, vt = np.linalg.svd(dd.T @ ds / len(src))
    sign = np.eye(3)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        sign[2, 2] = -1
    r = u @ sign @ vt
    s = np.trace(np.diag(d) @ sign) / ((ds**2).sum() / len(src))
    return s, r, md - s * r @ ms


def rotation(axis, deg):
    axis = normalize(axis)
    k = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    a = math.radians(deg)
    return np.eye(3) + math.sin(a) * k + (1 - math.cos(a)) * k @ k


def rotvec(w):
    angle = np.linalg.norm(w)
    return np.eye(3) if angle < 1e-12 else rotation(w / angle, math.degrees(angle))


class Icp:
    """ICP de semejanza con pares en los dos sentidos, recortados (TRIM)."""

    def __init__(self, src, src_n, tgt, tgt_n):
        self.src, self.src_n, self.tgt, self.tgt_n = src, src_n, tgt, tgt_n
        self.tree = cKDTree(tgt)

    def pairs(self, s, r, t):
        cur = s * self.src @ r.T + t
        d1, i1 = self.tree.query(cur)
        d2, i2 = cKDTree(cur).query(self.tgt)
        k1 = d1 <= np.quantile(d1, TRIM)
        k2 = d2 <= np.quantile(d2, TRIM)
        score = math.sqrt(0.5 * (np.mean(d1[k1] ** 2) + np.mean(d2[k2] ** 2)))
        return cur, (k1, i1, d1), (k2, i2, d2), score

    def point(self, s, r, t, iters=80):
        for _ in range(iters):
            _, (k1, i1, _), (k2, i2, _), _ = self.pairs(s, r, t)
            src = np.vstack([self.src[k1], self.src[i2[k2]]])
            dst = np.vstack([self.tgt[i1[k1]], self.tgt[k2]])
            s2, r2, t2 = umeyama(src, dst)
            moved = abs(s2 - s) + np.abs(r2 - r).max() + np.abs(t2 - t).max()
            s, r, t = s2, r2, t2
            if moved < 1e-7:
                break
        return s, r, t

    def plane(self, s, r, t, iters=40):
        """Afinado punto a plano (Gauss-Newton de la semejanza linealizada)."""
        for _ in range(iters):
            cur, (k1, i1, _), (k2, i2, _), _ = self.pairs(s, r, t)
            cur_n = self.src_n @ r.T
            q = np.vstack([cur[k1], cur[i2[k2]]])
            y = np.vstack([self.tgt[i1[k1]], self.tgt[k2]])
            n = np.vstack([self.tgt_n[i1[k1]], cur_n[i2[k2]]])
            c = q.mean(axis=0)
            a = q - c
            res = ((q - y) * n).sum(axis=1)
            jac = np.hstack([np.cross(a, n), (a * n).sum(axis=1)[:, None], n])
            x = np.linalg.lstsq(jac, -res, rcond=None)[0]
            rw = rotvec(x[:3])
            sig = x[3]
            s, r, t = s * (1 + sig), rw @ r, (1 + sig) * rw @ (t - c) + c + x[4:]
            if np.abs(x).max() < 1e-7:
                break
        return s, r, t


def start(src, tgt, pitch, yaw):
    """Arranque: ejes del avatar con un cabeceo y una guiñada, ancho igualado y el
    gorro encima (centrado de lado, la coronilla y la nuca a la altura de la oficial)."""
    r = BASIS @ rotation([0, 1, 0], yaw) @ rotation([1, 0, 0], pitch)
    tp = to_avatar(tgt)
    s = np.ptp(np.percentile(tp[:, 0], [2, 98])) / np.ptp(np.percentile(src[:, 0], [2, 98]))
    q = to_avatar(s * src @ r.T)
    shift = np.array(
        [
            np.median(tp[:, 0]) - np.median(q[:, 0]),
            np.percentile(tp[:, 1], 99) - np.percentile(q[:, 1], 99),
            np.percentile(tp[:, 2], 1) - np.percentile(q[:, 2], 1),
        ]
    )
    return s, r, BASIS @ shift


# Paso 1: gorro entero (copa y visera) contra la cara exterior de la oficial.
full = Icp(
    np.vstack([crown_src, brim_src]), np.vstack([crown_src_n, brim_src_n]), tgt_out, tgt_out_n
)
results = []
for pitch in np.arange(-30, 31, 7.5):
    for yaw in (-10, 0, 10):
        s, r, t = full.point(*start(full.src, tgt_out, pitch, yaw))
        results.append((full.pairs(s, r, t)[3], pitch, yaw, s, r, t))
results.sort(key=lambda x: x[0])
for score, pitch, yaw, *_ in results[:4]:
    print(f"  arranque cabeceo {pitch:+.1f} guiñada {yaw:+d}: {score * 1000:.2f} mm")
_, _, _, s, r, t = results[0]

# Paso 2: la visera oficial, lo que queda más cerca de la visera del Noogler que de su copa.
dc, _ = cKDTree(s * crown_src @ r.T + t).query(tgt_out)
db, _ = cKDTree(s * brim_src @ r.T + t).query(tgt_out)
official_brim = db < dc
tgt = tgt_out[~official_brim]
tgt_n = tgt_out_n[~official_brim]
tgt_brim = tgt_out[official_brim]
print(f"  copa oficial {len(tgt)} puntos, visera {len(tgt_brim)}")

# Paso 3: copa contra copa.
crown = Icp(crown_src, crown_src_n, tgt, tgt_n)
s, r, t = crown.plane(*crown.point(s, r, t))
cur, (k1, _, d1), (k2, _, d2), score = crown.pairs(s, r, t)


# --- Resultado ---------------------------------------------------------------------
def quat_from_matrix(m):
    tr = m[0, 0] + m[1, 1] + m[2, 2]
    if tr > 0:
        q = 0.5 / math.sqrt(tr + 1.0)
        return np.array(
            [(m[2, 1] - m[1, 2]) * q, (m[0, 2] - m[2, 0]) * q, (m[1, 0] - m[0, 1]) * q, 0.25 / q]
        )
    i = int(np.argmax([m[0, 0], m[1, 1], m[2, 2]]))
    j, k = (i + 1) % 3, (i + 2) % 3
    sq = math.sqrt(m[i, i] - m[j, j] - m[k, k] + 1.0) * 2
    q = np.zeros(4)
    q[i] = 0.25 * sq
    q[3] = (m[k, j] - m[j, k]) / sq
    q[j] = (m[j, i] + m[i, j]) / sq
    q[k] = (m[k, i] + m[i, k]) / sq
    return q


def unity_euler(m):
    """Euler de Unity (Quaternion.Euler: z, luego x, luego y) en grados."""
    x = math.degrees(math.asin(max(-1.0, min(1.0, -m[1, 2]))))
    y = math.degrees(math.atan2(m[0, 2], m[2, 2]))
    z = math.degrees(math.atan2(m[1, 0], m[1, 1]))
    return [x, y, z]


relative = unity_euler(BASIS.T @ r)
offset = to_avatar(t)
head_scale = float(official.get("head_scale", 1.0))
both = np.concatenate([d1[k1], d2[k2]])
print(
    f"AJUSTE: error medio {both.mean() * 1000:.2f} mm, mediana {np.median(both) * 1000:.2f} mm, "
    f"p90 {np.percentile(both, 90) * 1000:.2f} mm (sin recortar: {np.concatenate([d1, d2]).mean() * 1000:.2f} mm)"
)
print(f"  escala {s:.4f} (en el mundo {s * head_scale:.4f})")
print(
    f"  boca respecto a la cabeza (derecha, arriba, delante del avatar): {(offset * 1000).round(1).tolist()} mm"
)
print(
    f"  giro respecto al avatar: cabeceo {relative[0]:+.2f}°, guiñada {relative[1]:+.2f}°, alabeo {relative[2]:+.2f}°"
)

# Visera: cuánto se separa la del Noogler de la oficial con este encaje (solo informativo).
brim_fit = s * brim_src @ r.T + t
if len(tgt_brim) > 20:
    db, _ = cKDTree(tgt_brim).query(brim_fit)
    print(
        f"  visera: distancia media a la oficial {db.mean() * 1000:.1f} mm (mediana {np.median(db) * 1000:.1f})"
    )

write_json(
    OUT_JSON,
    {
        "position": t.tolist(),
        "rotation": quat_from_matrix(r).tolist(),
        "euler": unity_euler(r),
        "scale": float(s),
        "head_scale": head_scale,
        "relative_euler": relative,
        "offset_avatar": offset.tolist(),
        "error_mm": float(both.mean() * 1000),
    },
    indent=2,
)

# --- Vistas de comprobación -------------------------------------------------------------
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

views = [
    ("De lado (delante a la derecha)", 2, 1),
    ("De frente", 0, 1),
    ("Desde arriba (delante arriba)", 0, 2),
]
fig, axes = plt.subplots(1, 3, figsize=(15, 5.4))
other = to_avatar(tgt_all[~outward])
for ax, (title, i, j) in zip(axes, views, strict=True):
    ax.scatter(other[:, i], other[:, j], s=1, c="#cccccc", label="oficial: descartado")
    tp = to_avatar(tgt)
    ax.scatter(tp[:, i], tp[:, j], s=1, c="#555555", label="oficial: copa")
    bp = to_avatar(tgt_brim)
    ax.scatter(bp[:, i], bp[:, j], s=1, c="#6fa8dc", label="oficial: visera")
    cp = to_avatar(cur)
    ax.scatter(cp[:, i], cp[:, j], s=1, c="#e53935", alpha=0.6, label="Noogler: copa")
    fp = to_avatar(brim_fit)
    ax.scatter(fp[:, i], fp[:, j], s=1, c="#fb8c00", alpha=0.6, label="Noogler: visera")
    ax.set_title(title)
    ax.set_aspect("equal")
axes[0].legend(markerscale=6, fontsize=8, loc="lower left")
fig.tight_layout()
fig.savefig(OUT_PNG, dpi=90)
print("VISTAS", OUT_PNG)
