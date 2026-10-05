"""Gorro Noogler a partir del «HAT - Propeller Silly Hat» de Dekogon (Blender sin interfaz).

Uso, desde la raíz del repo (antes, texto.py):
    blender -b --python scripts/gorro_noogler/construir.py

1. Une las mallas, pasa a metros y deja el origen en el centro de la boca (el
   borde de abajo de la copa), con la copa hacia +Z y la visera hacia -Y.
2. Texturas: recolorea los gajos como la gorra Noogler (gajo amarillo delante,
   azul a la izquierda de quien mira, rojo a la derecha), borra la costura del
   centro delantero y proyecta de frente el texto «Noogler» con un relieve de
   bordado en el normal map. Pasa las texturas a URP (normal OpenGL y
   metálico/suavidad).
3. Separa la hélice (palas y buje) en un objeto aparte con el eje en su +Z local.
4. Exporta a SALIDA el FBX, las texturas y NooglerCap.json (medidas de la boca y
   eje de la hélice), y a TRABAJO las vistas previas y las nubes de puntos con
   las que encajar.py coloca el gorro sobre la gorra oficial de Genies.
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
from rutas import GLTF, IMAGENES, SALIDA, TRABAJO, write_json  # noqa: E402

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
TEXT_WIDTH = 0.096  # metros, ancho del texto en el gajo delantero
TEXT_HEIGHT_FRACTION = 0.30  # altura del centro del texto en el gajo delantero (0 abajo, 1 arriba)
SEAM_HALF_DEG = 2.6  # media anchura de la costura central que se borra
BUMP_STRENGTH = 2.2  # relieve del bordado en el normal map

hat = load_hat()
me = hat.data
isl = islands(hat)
verts = np.array([v.co[:] for v in me.vertices])

# --- Clasificación de piezas ------------------------------------------------
face_center = np.array([p.center[:] for p in me.polygons])
crown = isl[0]
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


# --- Gajos originales por azimut (color mayoritario cada 2°) -----------------
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
bins = {}
mask_band = fabric & (pz > 0.02)
for a, c in zip(az[mask_band].ravel(), cls[mask_band].ravel(), strict=True):
    if c < 0:
        continue
    k = int(math.floor((a + 180) / 2))
    bins.setdefault(k, np.zeros(4))
    bins[k][c] += 1
majority = {k: int(v.argmax()) for k, v in bins.items()}
runs = []
for k in sorted(majority):
    if runs and runs[-1][2] == majority[k] and runs[-1][1] == k - 1:
        runs[-1][1] = k
    else:
        runs.append([k, k, majority[k]])
for a, b, c in runs:
    print("GAJO", names[c], a * 2 - 180, "..", b * 2 - 178)

# Nuevo color de cada gajo original según su azimut central, como la gorra
# Noogler: amarillo delante, azul a la izquierda de quien mira, rojo a la derecha
# y detrás rojo y verde.
panel_mean = {}
for c in range(4):
    sel = fabric & (cls == c)
    panel_mean[c] = rgb[sel].mean(axis=0)
print("MEDIAS", {names[c]: (panel_mean[c] * 255).round() for c in range(4)})
TARGETS = {
    "amarillo": YELLOW,
    "azul": panel_mean[1],
    "rojo": panel_mean[2],
    "verde": panel_mean[3],
}
# Tramos continuos (el último puede seguir por el principio, -180).
spans = [[a * 2 - 180, b * 2 - 178, c] for a, b, c in runs]
if len(spans) > 1 and spans[0][2] == spans[-1][2] and spans[0][0] <= -178 and spans[-1][1] >= 178:
    first = spans.pop(0)
    spans[-1][1] = first[1] + 360
plan = []
for a, b, c in spans:
    mid = ((a + b) / 2 + 180) % 360 - 180
    if abs(mid) <= 60:
        name = "amarillo"
    elif 60 < mid <= 132:
        name = "rojo"
    elif -132 <= mid < -60:
        name = "azul"
    elif mid > 132:
        name = "verde"
    else:
        name = "rojo"
    plan.append((a, b, name))
    print("NUEVO", names[c], a, "..", b, "->", name)


def luma(c):
    return c[..., 0] * 0.299 + c[..., 1] * 0.587 + c[..., 2] * 0.114


new_rgb = rgb.copy()
orig_mean = np.zeros_like(rgb)
for c in range(4):
    orig_mean[cls == c] = panel_mean[c]
for a, b, name in plan:
    az_wrapped = np.where(az < a, az + 360, az)
    sel = fabric & (cls >= 0) & (az_wrapped >= a) & (az_wrapped < b)
    factor = np.clip(luma(rgb[sel]) / np.maximum(luma(orig_mean[sel]), 1e-3), 0.0, 1.6)
    # Se suaviza la variación: al pasar un gajo oscuro a amarillo la tela salía moteada.
    factor = 1.0 + (factor - 1.0) * (0.45 if name == "amarillo" else 0.8)
    new_rgb[sel] = np.clip(TARGETS[name][None, :] * factor[:, None], 0, 1)

# Costura del centro delantero: el borde entre los dos gajos de delante.
front_edges = [b for a, b, name in plan if name == "amarillo" and -40 < b < 40]
SEAM_AZ = front_edges[0] if front_edges else 0.0
print("COSTURA delantera en", SEAM_AZ)

# --- Borrar la costura del centro delantero -----------------------------------
# Disco UV de la copa: centro en el UV del vértice más alto de la copa (el botón).
crown_loops = [li for f in crown for li in me.polygons[f].loop_indices]
top_loop = max(crown_loops, key=lambda li: me.vertices[me.loops[li].vertex_index].co.z)
uv_center = np.array(uv_layer[top_loop].uv[:]) * [W, H]
rows, cols = np.nonzero(covered & (np.abs(az - SEAM_AZ) < SEAM_HALF_DEG))
for r, c in zip(rows, cols, strict=True):
    v = np.array([c + 0.5, r + 0.5]) - uv_center
    radius = np.linalg.norm(v)
    if radius < 4:
        continue
    t = np.array([-v[1], v[0]]) / radius
    step = radius * math.radians(SEAM_HALF_DEG * 2.2)
    for sign in (1, -1):
        sx, sy = (np.array([c + 0.5, r + 0.5]) + sign * t * step).astype(int)
        if (
            0 <= sx < W
            and 0 <= sy < H
            and covered[sy, sx]
            and abs(az[sy, sx] - SEAM_AZ) >= SEAM_HALF_DEG
        ):
            new_rgb[r, c] = new_rgb[sy, sx]
            normal[r, c] = normal[sy, sx]
            break

# --- Texto «Noogler» proyectado de frente --------------------------------------
text_img = bpy.data.images.load(os.path.join(TRABAJO, "noogler_text.png"))
tw, th = text_img.size
text = np.array(text_img.pixels[:], dtype=np.float32).reshape(th, tw, 4)
front_band = covered & (np.abs(az) < 6)
zf_min = float(np.nanmin(pz[front_band]))
zf_max = float(np.nanmax(pz[front_band]))
text_h = TEXT_WIDTH * th / tw
text_cz = zf_min + TEXT_HEIGHT_FRACTION * (zf_max - zf_min)
print(
    "FRENTE z",
    round(zf_min, 4),
    round(zf_max, 4),
    "texto centro z",
    round(text_cz, 4),
    "alto",
    round(text_h, 4),
)
facing = covered & (nrm_map[..., 1] < -0.25)  # caras que miran hacia delante (-Y)
tu = (px / TEXT_WIDTH) + 0.5
tv = ((pz - text_cz) / text_h) + 0.5
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
