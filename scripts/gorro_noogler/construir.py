"""Gorro Noogler a partir del «HAT - Propeller Silly Hat» de Dekogon (Blender sin interfaz).

Uso, desde la raíz del repo (antes, texto.py):
    blender -b --python scripts/gorro_noogler/construir.py

1. Une las mallas, pasa a metros y deja el origen en el centro de la boca (el
   borde de abajo de la copa), con la copa hacia +Z y la visera hacia -Y.
2. Texturas: recolorea los gajos como la gorra Noogler (gajo amarillo delante,
   azul a la izquierda de quien mira, rojo a la derecha), cuña a cuña del disco
   UV para que cada color acabe en su costura, también los parches que tapan
   huecos de la copa; borra la costura del centro delantero y proyecta de frente
   el texto «Noogler» con un relieve de bordado en el normal map. Pasa las
   texturas a URP (normal OpenGL y metálico/suavidad).
3. Separa la hélice (palas y buje) en un objeto aparte con el eje en su +Z local.
4. Si encajar.py ya midió la gorra oficial (trabajo/gorra_oficial_borde.json),
   estira la parte baja de la copa hasta su borde.
5. Exporta a SALIDA el FBX, las texturas y NooglerCap.json (medidas de la boca,
   puntos de agarre y eje de la hélice), y a TRABAJO las vistas previas y las
   nubes de puntos con las que encajar.py coloca el gorro sobre la gorra oficial.
"""

import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bmesh  # noqa: E402
import bpy  # noqa: E402
import numpy as np  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402
from rutas import GLTF, IMAGENES, SALIDA, TRABAJO, read_json, write_json  # noqa: E402

os.makedirs(SALIDA, exist_ok=True)


def load_hat():
    """Importa el gorro, lo une en un objeto y lo deja en metros, Z arriba y visera hacia -Y."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=GLTF)
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    for o in meshes:
        o.parent = None
        o.matrix_world = Matrix.Identity(4)
    bpy.ops.object.select_all(action="DESELECT")
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.object.join()
    hat = bpy.context.view_layer.objects.active
    hat.name = "NooglerCap"
    # Datos crudos del glTF (ya en Z arriba de Blender por el importador): el eje
    # largo es Z. Rotación de -90° en X: la copa queda arriba (+Z) y la visera en -Y.
    rot = Matrix.Rotation(math.radians(-90.0), 4, "X")
    hat.data.transform(Matrix.Scale(0.01, 4) @ rot)
    for o in [o for o in bpy.context.scene.objects if o.type != "MESH"]:
        bpy.data.objects.remove(o, do_unlink=True)
    return hat


def islands(obj):
    """Lista de islas: cada una, conjunto de índices de cara."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    seen = set()
    result = []
    for f in bm.faces:
        if f.index in seen:
            continue
        stack = [f]
        seen.add(f.index)
        isl = []
        while stack:
            cur = stack.pop()
            isl.append(cur.index)
            for e in cur.edges:
                for g in e.link_faces:
                    if g.index not in seen:
                        seen.add(g.index)
                        stack.append(g)
        result.append(isl)
    bm.free()
    return sorted(result, key=len, reverse=True)


# Colores de la gorra Noogler (sRGB 0..1).
YELLOW = np.array([248, 205, 28]) / 255.0
GRIP_HEIGHT = 0.025  # metros sobre la boca a los que las manos cogen la copa
TEXT_WIDTH = 0.096  # metros, ancho del texto en el gajo delantero
TEXT_HEIGHT_FRACTION = 0.30  # altura del centro del texto en el gajo delantero (0 abajo, 1 arriba)
# El texto se proyecta como lo ve la cámara con la gorra puesta: desde delante y
# por encima de su eje (la gorra va inclinada hacia delante y la cámara de la
# trivia está alta). Proyectado solo desde el frente, los extremos, que quedan
# más atrás en la copa, se verían más altos que el centro y el texto saldría
# combado hacia abajo.
TEXT_VIEW_PITCH_DEG = 20.0
TEXT_ARCH = 0.006  # metros que bajan los extremos respecto al centro: arco hacia arriba
SEAM_HALF_PX = 7  # media anchura, en píxeles de la textura, de la costura central que se borra
BUMP_STRENGTH = 2.2  # relieve del bordado en el normal map


def crown_patches(obj):
    """Caras sueltas que tapan huecos de la copa (parches del modelo original).

    Son islas de una o dos caras cuyo UV cae en huecos del disco de la copa: si no
    se recolorean con ella salen como triangulitos del color viejo del gajo, y si
    se quitan, la copa queda con agujeros. El disco tiene el centro en el UV del
    botón (el vértice de la copa más cercano a lo más bajo de la hélice).
    """
    mesh = obj.data
    parts = islands(obj)
    uv_data = mesh.uv_layers.active.data
    co = np.array([v.co[:] for v in mesh.vertices])
    centers = [np.mean([mesh.polygons[f].center[:] for f in faces], axis=0) for faces in parts]
    prop_faces = [f for faces, c in zip(parts, centers, strict=True) if c[2] > 0.01 for f in faces]
    stem_base = co[np.unique([v for f in prop_faces for v in mesh.polygons[f].vertices])][
        :, 2
    ].argmin()
    stem_base = co[np.unique([v for f in prop_faces for v in mesh.polygons[f].vertices])][stem_base]
    crown_loops = [li for f in parts[0] for li in mesh.polygons[f].loop_indices]
    button = min(
        crown_loops, key=lambda li: np.linalg.norm(co[mesh.loops[li].vertex_index] - stem_base)
    )
    center = np.array(uv_data[button].uv[:])
    radius = max(np.linalg.norm(np.array(uv_data[li].uv[:]) - center) for li in crown_loops)
    patches = []
    for faces, c in zip(parts[1:], centers[1:], strict=True):
        if len(faces) > 2 or c[2] > 0.01:
            continue
        uv = np.mean(
            [uv_data[li].uv[:] for f in faces for li in mesh.polygons[f].loop_indices], axis=0
        )
        if np.linalg.norm(uv - center) < 0.97 * radius:
            patches.extend(faces)
    return patches


hat = load_hat()
me = hat.data
isl = islands(hat)
patches = crown_patches(hat)
print("PARCHES de la copa", len(patches))
verts = np.array([v.co[:] for v in me.vertices])

# --- Clasificación de piezas ------------------------------------------------
face_center = np.array([p.center[:] for p in me.polygons])
# La copa exterior, con los parches que tapan sus huecos.
crown = isl[0] + patches
part_of = np.zeros(len(me.polygons), dtype=int)  # 0 cuerpo, 1 hélice
propeller_islands = []
for faces in isl:
    centroid = face_center[faces].mean(axis=0)
    if centroid[2] > 0.01:
        propeller_islands.append(faces)
        part_of[faces] = 1
print("PIEZAS", len(isl), "de la hélice", len(propeller_islands))

# --- Boca de la copa: lazo del borde de abajo ---------------------------------
# No es plano (más alto delante y detrás que en los lados, con la muesca del
# ajuste detrás): se usa su centroide como origen y se exportan las referencias
# para encajarlo en Unity con la gorra oficial de Genies medida igual.
bm = bmesh.new()
bm.from_mesh(me)
crown_set = set(crown)
adj = {}
for e in bm.edges:
    linked = [f for f in e.link_faces if f.index in crown_set]
    if len(linked) == 1:
        a, b = e.verts[0].index, e.verts[1].index
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
bm.free()
seen = set()
loops = []
for start_v in adj:
    if start_v in seen:
        continue
    stack = [start_v]
    comp = []
    seen.add(start_v)
    while stack:
        cur = stack.pop()
        comp.append(cur)
        for n in adj[cur]:
            if n not in seen:
                seen.add(n)
                stack.append(n)
    loops.append(comp)
ring_idx = max(loops, key=len)
ring_pts = verts[ring_idx]
center = ring_pts.mean(axis=0)
print("BOCA centro", center.round(4), "puntos", len(ring_idx))
me.transform(Matrix.Translation(Vector(-center)))
me.update()
verts = np.array([v.co[:] for v in me.vertices])
ring_pts = verts[ring_idx]
face_center = np.array([p.center[:] for p in me.polygons])
body = verts[np.unique(np.concatenate([list(me.polygons[f].vertices) for f in crown]))]
apex = body[body[:, 2].argmax()]
print(
    "COPA x",
    body[:, 0].min().round(4),
    body[:, 0].max().round(4),
    "y",
    body[:, 1].min().round(4),
    body[:, 1].max().round(4),
    "z",
    body[:, 2].min().round(4),
    body[:, 2].max().round(4),
    "coronilla",
    apex.round(4),
)

# Muestras de la superficie (antes de separar la hélice, que renumera las caras):
# la copa exterior y la cara de arriba de la visera, con sus normales, para
# encajar el gorro por ICP con la gorra oficial de Genies.
me.calc_loop_triangles()
crown_set = set(crown)
tri_poly = np.array([tri.polygon_index for tri in me.loop_triangles])
tri_pts = np.array([[me.vertices[vi].co[:] for vi in tri.vertices] for tri in me.loop_triangles])
tri_nrm = np.array([tri.normal[:] for tri in me.loop_triangles])
tri_area = 0.5 * np.linalg.norm(
    np.cross(tri_pts[:, 1] - tri_pts[:, 0], tri_pts[:, 2] - tri_pts[:, 0]), axis=1
)


def sample_surface(face_ids, count, seed):
    """Puntos al azar sobre unas caras (según su área) y la normal de cada uno."""
    sel = np.nonzero(np.isin(tri_poly, list(face_ids)))[0]
    gen = np.random.default_rng(seed)
    picks = sel[gen.choice(len(sel), size=count, p=tri_area[sel] / tri_area[sel].sum())]
    a = np.sqrt(gen.random(count))[:, None]
    b = gen.random(count)[:, None]
    pts = (1 - a) * tri_pts[picks, 0] + a * (1 - b) * tri_pts[picks, 1] + a * b * tri_pts[picks, 2]
    return pts, tri_nrm[picks]


samples, sample_normals = sample_surface(crown_set, 2500, 7)

# Agarre: un punto en cada costado de la copa, a GRIP_HEIGHT sobre la boca y por
# fuera, con la normal de la tela. Las manos apoyan ahí la palma (TriviaHat).
grip_points = []
grip_normals = []
for sign in (1.0, -1.0):
    side = (np.abs(samples[:, 2] - GRIP_HEIGHT) < 0.006) & (samples[:, 0] * sign > 0)
    point = samples[side][np.argmax(samples[side, 0] * sign)]
    close = side & (np.linalg.norm(samples - point, axis=1) < 0.015)
    normal_mean = sample_normals[close].mean(axis=0)
    grip_points.append(point)
    grip_normals.append(normal_mean / np.linalg.norm(normal_mean))
print(
    "AGARRE",
    [p.round(4).tolist() for p in grip_points],
    [n.round(3).tolist() for n in grip_normals],
)
# Visera: la isla grande de delante que mira hacia arriba (con el canto del ala, la media es baja).
brim_top = None
for faces in isl[1:]:
    if part_of[faces[0]] == 1 or len(faces) < 30:
        continue
    cen = face_center[faces].mean(axis=0)
    nz = np.array([me.polygons[f].normal.z for f in faces]).mean()
    if cen[1] < -0.08 and nz > 0.05 and (brim_top is None or len(faces) > len(brim_top)):
        brim_top = faces
brim_samples, brim_normals = sample_surface(set(brim_top), 800, 11)
# Malla entera sin la hélice (para probar el ICP con una «gorra oficial» sintética).
body_tris = np.nonzero(np.isin(tri_poly, np.nonzero(part_of == 0)[0]))[0]


# --- Texturas originales ----------------------------------------------------
def load(name, non_color=False):
    img = bpy.data.images.load(os.path.join(IMAGENES, name))
    if non_color:
        img.colorspace_settings.name = "Non-Color"
    w, h = img.size
    return np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)


albedo = load("TX_M_Propeller_01a_MAT_albedo.tga.png")
normal = load("TX_M_Propeller_01a_MAT_directx_normal.png", non_color=True)
mr = load("TX_M_Propeller_01a_MAT_metalness.png", non_color=True)
H, W = albedo.shape[:2]

# --- Mapa de posiciones de la copa exterior (UV -> 3D) -----------------------
uv_layer = me.uv_layers.active.data
me.calc_loop_triangles()
pos_map = np.full((H, W, 3), np.nan, dtype=np.float32)
nrm_map = np.zeros((H, W, 3), dtype=np.float32)
for tri in me.loop_triangles:
    if tri.polygon_index not in crown_set:
        continue
    uv = np.array([uv_layer[li].uv[:] for li in tri.loops]) * [W, H]
    p = np.array([me.vertices[vi].co[:] for vi in tri.vertices])
    n = np.array(tri.normal[:])
    x0, y0 = uv[0]
    x1, y1 = uv[1]
    x2, y2 = uv[2]
    d = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
    if abs(d) < 1e-9:
        continue
    xa = max(0, int(math.floor(uv[:, 0].min())))
    xb = min(W - 1, int(math.ceil(uv[:, 0].max())))
    ya = max(0, int(math.floor(uv[:, 1].min())))
    yb = min(H - 1, int(math.ceil(uv[:, 1].max())))
    if xb < xa or yb < ya:
        continue
    xs, ys = np.meshgrid(np.arange(xa, xb + 1) + 0.5, np.arange(ya, yb + 1) + 0.5)
    l0 = ((y1 - y2) * (xs - x2) + (x2 - x1) * (ys - y2)) / d
    l1 = ((y2 - y0) * (xs - x2) + (x0 - x2) * (ys - y2)) / d
    l2 = 1.0 - l0 - l1
    inside = (l0 >= -0.02) & (l1 >= -0.02) & (l2 >= -0.02)
    if not inside.any():
        continue
    val = l0[..., None] * p[0] + l1[..., None] * p[1] + l2[..., None] * p[2]
    rows = (ys[inside] - 0.5).astype(int)
    cols = (xs[inside] - 0.5).astype(int)
    pos_map[rows, cols] = val[inside]
    nrm_map[rows, cols] = n

covered = ~np.isnan(pos_map[..., 0])
# Margen de unos píxeles alrededor de las islas UV (el muestreo de la GPU los pisa).
for _ in range(6):
    grow = covered.copy()
    src = pos_map.copy()
    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        shifted = np.roll(np.roll(covered, dy, axis=0), dx, axis=1)
        shifted_pos = np.roll(np.roll(src, dy, axis=0), dx, axis=1)
        shifted_n = np.roll(np.roll(nrm_map, dy, axis=0), dx, axis=1)
        take = shifted & ~grow
        pos_map[take] = shifted_pos[take]
        nrm_map[take] = shifted_n[take]
        grow |= take
    covered = grow
print("PIXELES de la copa", int(covered.sum()))

px = pos_map[..., 0]
py = pos_map[..., 1]
pz = pos_map[..., 2]
az = np.degrees(np.arctan2(px, -py))  # 0 delante, + hacia +X (derecha de quien mira)


# --- Gajos: cuñas del disco UV de la copa ------------------------------------------
# En el UV la copa exterior es un disco con el botón en el centro, y las costuras
# son radios rectos: cada gajo es una cuña. Se recolorea cuña a cuña para que cada
# color acabe justo en su costura (por azimut 3D no: el botón va adelantado y las
# costuras no siguen el azimut, así que quedaban picos del color de al lado).
def hsv(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    s = np.where(mx > 1e-6, (mx - mn) / np.maximum(mx, 1e-6), 0)
    return mx, s


rgb = albedo[..., :3]
value, sat = hsv(rgb)
fabric = covered & (sat > 0.35) & (value > 0.15)


def color_class(c):
    r, g, b = c[..., 0], c[..., 1], c[..., 2]
    cls = np.full(r.shape, -1)
    cls[(r > 0.5) & (g > 0.35) & (b < 0.35)] = 0  # amarillo
    cls[(cls < 0) & (b > r) & (b > g)] = 1  # azul
    cls[(cls < 0) & (r > g) & (r > b)] = 2  # rojo
    cls[(cls < 0) & (g > r) & (g > b)] = 3  # verde
    return cls


cls = color_class(rgb)
names = ["amarillo", "azul", "rojo", "verde"]

# Centro del disco: el botón, donde se apoya la hélice (el vértice de la copa más
# cercano a lo más bajo de la hélice; el más alto de la copa no lo es).
prop_pts = verts[
    np.unique(
        np.concatenate(
            [list(me.polygons[f].vertices) for faces in propeller_islands for f in faces]
        )
    )
]
stem_base = prop_pts[prop_pts[:, 2].argmin()]
crown_loops = [li for f in crown for li in me.polygons[f].loop_indices]
button_loop = min(
    crown_loops,
    key=lambda li: np.linalg.norm(
        np.array(me.vertices[me.loops[li].vertex_index].co[:]) - stem_base
    ),
)
uv_center = np.array(uv_layer[button_loop].uv[:]) * [W, H]
print("BOTÓN en el UV", (uv_center / [W, H]).round(4).tolist())
grid_y, grid_x = np.mgrid[0:H, 0:W]
du = grid_x + 0.5 - uv_center[0]
dv = grid_y + 0.5 - uv_center[1]
uv_radius = np.hypot(du, dv)
uv_angle = np.degrees(np.arctan2(dv, du))  # -180..180

# Color mayoritario cada medio grado, lejos del botón y del borde del disco.
STEP = 0.5
NBINS = int(360 / STEP)
disc = float(np.percentile(uv_radius[covered], 98))
band = fabric & (cls >= 0) & (uv_radius > 0.2 * disc) & (uv_radius < 0.92 * disc)
counts = np.zeros((NBINS, 4))
np.add.at(counts, (((uv_angle[band] + 180) / STEP).astype(int) % NBINS, cls[band]), 1)
# Moda en una ventana de 2,5° para que las puntadas de las costuras no partan gajos.
smooth = sum(np.roll(counts, k, axis=0) for k in range(-2, 3))
majority = smooth.argmax(axis=1)
runs = []
for i in range(NBINS):
    if runs and runs[-1][2] == majority[i]:
        runs[-1][1] = i + 1
    else:
        runs.append([i, i + 1, int(majority[i])])
if len(runs) > 1 and runs[0][2] == runs[-1][2]:
    runs[0][0] = runs[-1][0] - NBINS
    runs.pop()
# Tramos de menos de 10° son ruido: al vecino.
runs = [r for r in runs if (r[1] - r[0]) * STEP >= 10]
# Cada borde, a mitad entre el final de un gajo y el principio del siguiente
# (en bins, módulo la vuelta entera).
bounds = []
for i, (_a, b, _c) in enumerate(runs):
    nxt = runs[(i + 1) % len(runs)][0]
    if nxt < b - NBINS / 2:
        nxt += NBINS
    bounds.append(((b + nxt) / 2) % NBINS)
wedges = [[bounds[i - 1], bounds[i], c] for i, (a, b, c) in enumerate(runs)]
print(
    "GAJOS",
    len(wedges),
    [(round(a * STEP - 180, 1), round(b * STEP - 180, 1), names[c]) for a, b, c in wedges],
)


def wedge_mask(a, b):
    """Píxeles de la copa entre dos bordes (en bins; si a > b, la cuña cruza los ±180°)."""
    k = (uv_angle + 180) / STEP
    inside = (k >= a) & (k < b) if a < b else (k >= a) | (k < b)
    return covered & inside


# Color nuevo de cada gajo según dónde cae en 3D (azimut: 0 delante, + hacia +X,
# la derecha de quien mira): los dos de delante amarillos, el de la izquierda de
# quien mira azul, el de la derecha rojo, y detrás verde (derecha) y rojo (izquierda).
plan = []
for a, b, c in wedges:
    m = wedge_mask(a, b) & (pz > 0.02) & np.isfinite(az)
    rad = np.radians(az[m])
    center = math.degrees(math.atan2(np.sin(rad).mean(), np.cos(rad).mean()))
    plan.append([a, b, c, center])
order = sorted(range(len(plan)), key=lambda i: abs(plan[i][3]))
for rank, i in enumerate(order):
    center = plan[i][3]
    if rank < 2:
        plan[i].append("amarillo")
    elif rank < 4:
        plan[i].append("rojo" if center > 0 else "azul")
    else:
        plan[i].append("verde" if center > 0 else "rojo")
for _a, _b, c, center, name in plan:
    print("GAJO", names[c], "azimut", round(center, 1), "->", name)

panel_mean = {}
for c in range(4):
    sel = fabric & (cls == c)
    panel_mean[c] = rgb[sel].mean(axis=0)
TARGETS = {
    "amarillo": YELLOW,
    "azul": panel_mean[1],
    "rojo": panel_mean[2],
    "verde": panel_mean[3],
}


def luma(c):
    return c[..., 0] * 0.299 + c[..., 1] * 0.587 + c[..., 2] * 0.114


# Cada gajo entero (también las puntadas) al color nuevo, conservando la luz de
# la tela respecto al color medio que tenía ese gajo.
new_rgb = rgb.copy()
for a, b, c, _center, name in plan:
    m = wedge_mask(a, b)
    own = m & fabric & (cls == c)
    base = luma(rgb[own].mean(axis=0)) if own.any() else luma(panel_mean[c])
    factor = np.clip(luma(rgb[m]) / max(base, 1e-3), 0.0, 1.6)
    # Se suaviza la variación: al pasar un gajo oscuro a amarillo la tela salía moteada.
    factor = 1.0 + (factor - 1.0) * (0.45 if name == "amarillo" else 0.8)
    new_rgb[m] = np.clip(TARGETS[name][None, :] * factor[:, None], 0, 1)

# --- Borrar la costura del centro delantero -----------------------------------
# Es el radio entre los dos gajos amarillos: se tapa copiando la tela de al lado,
# en perpendicular a la costura.
front = [p for p in plan if p[4] == "amarillo"]
seam_bins = front[0][1] if abs(front[0][1] - front[1][0]) < 1e-6 else front[1][1]
seam_angle = math.radians(seam_bins * STEP - 180)
print("COSTURA delantera en el UV a", round(math.degrees(seam_angle), 1), "grados")
ux, uy = math.cos(seam_angle), math.sin(seam_angle)
along = du * ux + dv * uy
across = -du * uy + dv * ux
seam = covered & (along > 6) & (np.abs(across) < SEAM_HALF_PX)
rows, cols = np.nonzero(seam)
side = np.where(across[rows, cols] >= 0, 1.0, -1.0)
shift = 2 * SEAM_HALF_PX + 2
src_x = np.clip((cols + 0.5 - uy * side * shift).astype(int), 0, W - 1)
src_y = np.clip((rows + 0.5 + ux * side * shift).astype(int), 0, H - 1)
ok = covered[src_y, src_x] & ~seam[src_y, src_x]
new_rgb[rows[ok], cols[ok]] = new_rgb[src_y[ok], src_x[ok]]
normal[rows[ok], cols[ok]] = normal[src_y[ok], src_x[ok]]

# --- Texto «Noogler» proyectado de frente --------------------------------------
text_img = bpy.data.images.load(os.path.join(TRABAJO, "noogler_text.png"))
tw, th = text_img.size
text = np.array(text_img.pixels[:], dtype=np.float32).reshape(th, tw, 4)
front_band = covered & (np.abs(az) < 6)
# Altura vista desde delante y por encima: lo que está más atrás se ve más alto.
view_pitch = math.radians(TEXT_VIEW_PITCH_DEG)
pv = pz * math.cos(view_pitch) + py * math.sin(view_pitch)
zf_min = float(np.nanmin(pv[front_band]))
zf_max = float(np.nanmax(pv[front_band]))
text_h = TEXT_WIDTH * th / tw
text_cz = zf_min + TEXT_HEIGHT_FRACTION * (zf_max - zf_min)
print(
    "FRENTE alto visto",
    round(zf_min, 4),
    round(zf_max, 4),
    "texto centro",
    round(text_cz, 4),
    "alto",
    round(text_h, 4),
)
facing = covered & (nrm_map[..., 1] < -0.25)  # caras que miran hacia delante (-Y)
if TEXT_ARCH > 0:
    # Las letras siguen un arco de circunferencia con el centro por debajo: la
    # posición a lo largo del texto es la longitud de arco y la altura, la
    # distancia al centro.
    arch_r = ((TEXT_WIDTH / 2) ** 2 + TEXT_ARCH**2) / (2 * TEXT_ARCH)
    rel_v = pv - (text_cz - arch_r)
    tu = (np.arctan2(px, rel_v) * arch_r / TEXT_WIDTH) + 0.5
    tv = ((np.hypot(px, rel_v) - arch_r) / text_h) + 0.5
else:
    tu = (px / TEXT_WIDTH) + 0.5
    tv = ((pv - text_cz) / text_h) + 0.5
inside = facing & (tu >= 0) & (tu < 1) & (tv >= 0) & (tv < 1)
ri, ci = np.nonzero(inside)
sx = np.clip((tu[ri, ci] * tw).astype(int), 0, tw - 1)
sy = np.clip((tv[ri, ci] * th).astype(int), 0, th - 1)
sample = text[sy, sx]
alpha = sample[:, 3:4]
new_rgb[ri, ci] = new_rgb[ri, ci] * (1 - alpha) + sample[:, :3] * alpha
height = np.zeros((H, W), dtype=np.float32)
height[ri, ci] = alpha[:, 0]


# Relieve de bordado: altura suavizada del texto -> normal en espacio tangente.
def box_blur(a, r):
    k = 2 * r + 1
    pad = np.pad(a, r, mode="edge")
    c = np.cumsum(np.cumsum(pad, axis=0), axis=1)
    c = np.pad(c, ((1, 0), (1, 0)))
    return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)


height = box_blur(box_blur(height, 2), 2)
gy, gx = np.gradient(height)

# Normal map: de DirectX a OpenGL (verde invertido) y relieve del texto.
nx = normal[..., 0] * 2 - 1
ny = -(normal[..., 1] * 2 - 1)
nz = normal[..., 2] * 2 - 1
nx = nx - gx * BUMP_STRENGTH
ny = ny - gy * BUMP_STRENGTH
length = np.sqrt(nx * nx + ny * ny + nz * nz) + 1e-6
normal_out = np.stack(
    [nx / length * 0.5 + 0.5, ny / length * 0.5 + 0.5, nz / length * 0.5 + 0.5, np.ones_like(nx)],
    axis=-1,
)

# Metálico (azul) y rugosidad (verde) de glTF -> URP: R metálico, A suavidad.
metal = mr[..., 2]
rough = mr[..., 1]
ms_out = np.stack([metal, np.zeros_like(metal), np.zeros_like(metal), 1.0 - rough], axis=-1)
albedo_out = np.concatenate([new_rgb, np.ones((H, W, 1), dtype=np.float32)], axis=-1)


def save(name, data, size=None, non_color=False, jpeg=False):
    h, w = data.shape[:2]
    img = bpy.data.images.new(name, w, h, alpha=True)
    if non_color:
        img.colorspace_settings.name = "Non-Color"
    img.pixels = data.astype(np.float32).ravel()
    if size and size != w:
        img.scale(size, size)
    path = os.path.join(SALIDA, name + (".jpg" if jpeg else ".png"))
    img.filepath_raw = path
    img.file_format = "JPEG" if jpeg else "PNG"
    img.save(quality=90) if jpeg else img.save()
    return img


# El color en JPG (2048, el texto se lee bien y pesa menos de 1 MB); los mapas de datos en PNG.
img_albedo = save("NooglerCap_Albedo", albedo_out, jpeg=True)
img_normal = save("NooglerCap_Normal", normal_out, size=1024, non_color=True)
save("NooglerCap_MetallicSmoothness", ms_out, size=1024, non_color=True)

# --- Hélice como objeto aparte --------------------------------------------------
blade_pts = []
for faces in propeller_islands:
    vs = verts[np.unique(np.concatenate([list(me.polygons[f].vertices) for f in faces]))]
    if (vs.max(axis=0) - vs.min(axis=0)).max() > 0.03:
        blade_pts.append(vs)
blade_pts = np.concatenate(blade_pts)
axis_center = blade_pts.mean(axis=0)
_, _, vt = np.linalg.svd(blade_pts - axis_center)
axis = vt[2] if vt[2][2] > 0 else -vt[2]
# Giran las palas y lo que está pegado al buje; las cuentas del eje se quedan.
rotating = []
for faces in propeller_islands:
    vs = verts[np.unique(np.concatenate([list(me.polygons[f].vertices) for f in faces]))]
    big = (vs.max(axis=0) - vs.min(axis=0)).max() > 0.03
    near = np.linalg.norm(vs.mean(axis=0) - axis_center) < 0.009
    if big or near:
        rotating.extend(faces)
prop_faces = np.array(sorted(set(rotating)))
print(
    "EJE hélice", axis.round(3), "centro", axis_center.round(4), "caras que giran", len(prop_faces)
)

bpy.ops.object.select_all(action="DESELECT")
hat.select_set(True)
bpy.context.view_layer.objects.active = hat
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="DESELECT")
bpy.ops.object.mode_set(mode="OBJECT")
for f in prop_faces:
    me.polygons[f].select = True
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.separate(type="SELECTED")
bpy.ops.object.mode_set(mode="OBJECT")
prop = [o for o in bpy.context.scene.objects if o.type == "MESH" and o != hat][0]
prop.name = "Propeller"
# Origen en el eje, con el +Z local a lo largo del eje.
z = Vector(axis)
x = Vector((1, 0, 0)) - z * z.x
x.normalize()
y = z.cross(x)
basis = Matrix(((x.x, y.x, z.x, 0), (x.y, y.y, z.y, 0), (x.z, y.z, z.z, 0), (0, 0, 0, 1)))
pivot = Matrix.Translation(Vector(axis_center)) @ basis
prop.data.transform(pivot.inverted())
prop.matrix_world = pivot
prop.parent = hat
prop.matrix_parent_inverse = hat.matrix_world.inverted()

# --- Borde bajado como la gorra oficial ---------------------------------------------
# encajar.py deja en trabajo/gorra_oficial_borde.json cuánto baja la gorra oficial
# por debajo de esta copa en cada dirección (lados y nuca): ahí Genies deja el pelo
# aplastado. Se estira hacia abajo la parte baja de la copa (y lo que cuelga de
# ella: forro, tira y visera), sin tocar nada por encima de RIM_TOP. Las muestras
# para encajar.py ya salieron antes, de la copa sin estirar.
RIM_FILE = os.path.join(TRABAJO, "gorra_oficial_borde.json")
RIM_TOP = 0.055  # metros sobre la boca a partir de los que la copa no se toca


def rim_shift(points):
    """Cuánto baja cada punto (0 si no hay medida de la gorra oficial)."""
    points = np.asarray(points, dtype=float).reshape(-1, 3)
    if not os.path.exists(RIM_FILE):
        return np.zeros(len(points))
    rim = read_json(RIM_FILE)
    a = np.degrees(np.arctan2(points[:, 0], -points[:, 1]))
    extend = np.interp(a, rim["azimuth"], rim["extend"], period=360)
    u = np.clip((RIM_TOP - points[:, 2]) / RIM_TOP, 0, 1)
    return extend * u * u * (3 - 2 * u)


co = np.zeros(len(me.vertices) * 3)
me.vertices.foreach_get("co", co)
co = co.reshape(-1, 3)
drop = rim_shift(co)
co[:, 2] -= drop
me.vertices.foreach_set("co", co.ravel())
me.update()
grip_points = [p - np.array([0.0, 0.0, rim_shift(p)[0]]) for p in grip_points]
print(
    "BORDE",
    "sin medida de la gorra oficial"
    if not drop.any()
    else f"bajado hasta {drop.max() * 1000:.1f} mm",
)

# --- Material para las vistas previas ---------------------------------------------
mat = bpy.data.materials.new("NooglerCap")
mat.use_nodes = True
bsdf = mat.node_tree.nodes["Principled BSDF"]
tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
tex.image = img_albedo
mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
for o in (hat, prop):
    o.data.materials.clear()
    o.data.materials.append(mat)

scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "STUDIO"
scene.display.shading.color_type = "TEXTURE"
scene.render.resolution_x = 700
scene.render.resolution_y = 700
cam_data = bpy.data.cameras.new("cam")
cam_data.type = "ORTHO"
cam_data.ortho_scale = 0.36
cam = bpy.data.objects.new("cam", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam
target = Vector((0, -0.03, 0.04))
for name, d in {
    "frente": (0, -1, 0.15),
    "tresc": (0.8, -1, 0.35),
    "lado": (1, 0, 0.1),
    "atras": (0, 1, 0.3),
}.items():
    direction = Vector(d).normalized()
    cam.location = target + direction * 1.0
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = os.path.join(TRABAJO, f"preview_{name}.png")
    bpy.ops.render.render(write_still=True)

# --- Exportar FBX ------------------------------------------------------------------
for o in (hat, prop):
    o.data.materials.clear()
bpy.ops.object.select_all(action="DESELECT")
hat.select_set(True)
prop.select_set(True)
bpy.ops.export_scene.fbx(
    filepath=os.path.join(SALIDA, "NooglerCap.fbx"),
    use_selection=True,
    object_types={"MESH"},
    apply_scale_options="FBX_SCALE_UNITS",
    axis_forward="-Z",
    axis_up="Y",
    mesh_smooth_type="FACE",
    use_tspace=True,
    path_mode="STRIP",
    embed_textures=False,
    add_leaf_bones=False,
)
meta = {
    "opening_center": [0, 0, 0],
    "apex": apex.tolist(),
    "opening_width": float(ring_pts[:, 0].max() - ring_pts[:, 0].min()),
    "opening_depth": float(ring_pts[:, 1].max() - ring_pts[:, 1].min()),
    "crown_height": float(body[:, 2].max()),
    "crown_width": float(body[:, 0].max() - body[:, 0].min()),
    "crown_depth": float(body[:, 1].max() - body[:, 1].min()),
    "propeller_axis_center": axis_center.tolist(),
    "propeller_axis": axis.tolist(),
    # Listas planas (x, y, z de cada mano): JsonUtility de Unity no lee listas de listas.
    "grip_points": np.concatenate(grip_points).tolist(),
    "grip_normals": np.concatenate(grip_normals).tolist(),
}
write_json(os.path.join(SALIDA, "NooglerCap.json"), meta, indent=2)
# Nubes de puntos para el ICP en ejes de Unity: (x, y, z) = (-x, z, -y) de Blender.


def to_unity(a):
    a = np.asarray(a)
    return np.stack([-a[..., 0], a[..., 2], -a[..., 1]], axis=-1)


write_json(
    os.path.join(TRABAJO, "fit_source.json"),
    {
        "crown": {
            "points": to_unity(samples).round(6).tolist(),
            "normals": to_unity(sample_normals).round(5).tolist(),
        },
        "brim": {
            "points": to_unity(brim_samples).round(6).tolist(),
            "normals": to_unity(brim_normals).round(5).tolist(),
        },
    },
)
body_v = to_unity(tri_pts[body_tris].reshape(-1, 3))
body_n = to_unity(np.repeat(tri_nrm[body_tris], 3, axis=0))
write_json(
    os.path.join(TRABAJO, "body_mesh.json"),
    {
        "vertices": body_v.round(6).tolist(),
        "normals": body_n.round(5).tolist(),
        "triangles": np.arange(len(body_v)).tolist(),
    },
)
print("META", json.dumps(meta))
print(
    "MUESTRAS copa",
    len(samples),
    "visera",
    len(brim_samples),
    "triángulos del cuerpo",
    len(body_tris),
)
