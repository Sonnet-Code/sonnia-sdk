"""Estampa un logo en el pecho separando esos triangulos en un material propio.

El atlas de algunos avatares de RPM mapea la misma zona de textura a dos partes
distintas de la prenda con escalas diferentes, asi que pintar el atlas saca el
logo duplicado. La salida limpia es sacar los triangulos del pecho a una malla
aparte con su propio material: la textura de esa malla es una copia del atlas
con el logo pintado, y el resto del cuerpo sigue usando el atlas original, sin
logo. Como las UV no cambian, no hay costura: el parche pinta exactamente lo
mismo que antes salvo el logo.

Uso: parche_logo.py modelo.glb logo.png salida.glb u0 u1 v0 v1 [ancho_px]
     (u0..v1 = rectangulo del atlas donde vive el pecho, en pixeles)
"""
import io, json, struct, sys
import numpy as np
from PIL import Image
import injerto_glb as T  # read() y acc() del lector de GLB


def main(glb, logo_path, salida, x0, x1, y0, y1, ancho_logo=110):
    js, bn = T.read(glb)
    pr = js['meshes'][0]['primitives'][0]
    pos = T.acc(js, bn, pr['attributes']['POSITION']).astype(np.float64)
    nor = T.acc(js, bn, pr['attributes']['NORMAL']).astype(np.float64)
    uv = T.acc(js, bn, pr['attributes']['TEXCOORD_0']).astype(np.float64)
    tri = T.acc(js, bn, pr['indices']).astype(np.int64).ravel().reshape(-1, 3)

    src = js['textures'][js['materials'][pr['material']]['pbrMetallicRoughness']['baseColorTexture']['index']]['source']
    img = js['images'][src]
    bvi = js['bufferViews'][img['bufferView']]
    off = bvi.get('byteOffset', 0)
    tex = Image.open(io.BytesIO(bn[off:off + bvi['byteLength']])).convert("RGBA")
    W, H = tex.size

    # triangulos cuyo centro de UV cae en el rectangulo del pecho
    cuv = uv[tri].mean(axis=1)
    cn = nor[tri].mean(axis=1)
    sel = ((cuv[:, 0] * W > x0) & (cuv[:, 0] * W < x1)
           & (cuv[:, 1] * H > y0) & (cuv[:, 1] * H < y1))
    print("  triángulos con UV en el rectángulo del pecho: %d" % sel.sum())
    if sel.sum() < 10:
        raise SystemExit("pocos triángulos")
    # de esos, los que miran al frente (hacia -Z o +Z, el lado con mas triangulos)
    frente = -1.0 if (cn[sel][:, 2] < 0).sum() >= (cn[sel][:, 2] > 0).sum() else 1.0
    sel &= (cn[:, 2] * frente > 0.2)
    print("  y mirando hacia Z%+d: %d" % (frente, sel.sum()))

    ptri = tri[sel]
    usados = np.unique(ptri)
    remap = {int(v): i for i, v in enumerate(usados)}
    ptri_local = np.vectorize(remap.get)(ptri).astype(np.uint32)
    print("  el parche usa %d vértices" % len(usados))

    # textura del parche: copia del atlas con el logo encima
    logo = Image.open(logo_path).convert("RGBA")
    logo = logo.crop(logo.getchannel("A").getbbox())
    logo = logo.resize((ancho_logo, round(ancho_logo * logo.height / logo.width)), Image.LANCZOS)
    U = uv[usados]
    cx = int(round(U[:, 0].mean() * W))
    cy = int(round(U[:, 1].mean() * H))
    parche = tex.copy()
    parche.alpha_composite(logo, (cx - logo.width // 2, cy - logo.height // 2))
    print("  logo %dx%d centrado en el píxel (%d,%d)" % (logo.width, logo.height, cx, cy))
    buf = io.BytesIO(); parche.convert("RGB").save(buf, "PNG", optimize=True)
    datos_tex = buf.getvalue()

    blob = bytearray(bn)

    def add_view(data, target=None):
        while len(blob) % 4:
            blob.append(0)
        bv = {'buffer': 0, 'byteOffset': len(blob), 'byteLength': len(data)}
        if target:
            bv['target'] = target
        blob.extend(data)
        js['bufferViews'].append(bv)
        return len(js['bufferViews']) - 1

    def add_acc(arr, tipo, ctype, target=None, minmax=False):
        a = {'bufferView': add_view(arr.tobytes(), target), 'componentType': ctype,
             'count': len(arr), 'type': tipo}
        if minmax:
            a['min'] = arr.min(axis=0).tolist(); a['max'] = arr.max(axis=0).tolist()
        js['accessors'].append(a)
        return len(js['accessors']) - 1

    # quitar del original los triangulos que se lleva el parche
    resto = tri[~sel].astype(np.uint32)
    pr['indices'] = add_acc(resto.ravel().reshape(-1, 1), 'SCALAR', 5125, 34963)
    print("  índices del cuerpo: %d -> %d triángulos" % (len(tri), len(resto)))

    # imagen y material del parche
    js.setdefault('images', []).append({'name': 'CAMISETA_LOGO', 'mimeType': 'image/png',
                                        'bufferView': add_view(datos_tex)})
    tex_orig = js['textures'][js['materials'][pr['material']]['pbrMetallicRoughness']['baseColorTexture']['index']]
    nueva_tex = {'source': len(js['images']) - 1}
    if 'sampler' in tex_orig:
        nueva_tex['sampler'] = tex_orig['sampler']
    js['textures'].append(nueva_tex)
    # material minimo: copiar el original con sus extensiones hace que glTFast
    # falle y pinte el parche de magenta
    orig = js['materials'][pr['material']]
    pbr_orig = orig.get('pbrMetallicRoughness', {})
    mat = {'name': 'CamisetaLogo',
           'pbrMetallicRoughness': {
               'baseColorTexture': {'index': len(js['textures']) - 1},
               'baseColorFactor': pbr_orig.get('baseColorFactor', [1, 1, 1, 1]),
               'metallicFactor': pbr_orig.get('metallicFactor', 0.0),
               'roughnessFactor': pbr_orig.get('roughnessFactor', 0.8)}}
    # sin mapa de normales ni de metallic-roughness: la malla del parche no lleva
    # tangentes y glTFast no puede compilar esa variante, asi que Unity lo pinta
    # de magenta. Con solo color base se ve igual en una zona plana como el pecho.
    js['materials'].append(mat)

    P = pos[usados].astype(np.float32)
    N = nor[usados].astype(np.float32)
    UVp = uv[usados].astype(np.float32)
    J = T.acc(js, bn, pr['attributes']['JOINTS_0']).astype(np.uint16)[usados]
    Wg = T.acc(js, bn, pr['attributes']['WEIGHTS_0']).astype(np.float32)[usados]
    prim = {'attributes': {
                'POSITION': add_acc(P, 'VEC3', 5126, 34962, minmax=True),
                'NORMAL': add_acc(N, 'VEC3', 5126, 34962),
                'TEXCOORD_0': add_acc(UVp, 'VEC2', 5126, 34962),
                'JOINTS_0': add_acc(J, 'VEC4', 5123, 34962),
                'WEIGHTS_0': add_acc(Wg, 'VEC4', 5126, 34962)},
            'indices': add_acc(ptri_local.ravel().reshape(-1, 1), 'SCALAR', 5125, 34963),
            'material': len(js['materials']) - 1}
    js['meshes'].append({'name': 'Camiseta_Logo', 'primitives': [prim]})

    nodo_cuerpo = next(i for i, n in enumerate(js['nodes']) if n.get('mesh') == 0)
    js['nodes'].append({'name': 'Camiseta_Logo', 'mesh': len(js['meshes']) - 1,
                        'skin': js['nodes'][nodo_cuerpo].get('skin')})
    nuevo = len(js['nodes']) - 1
    padre = next((i for i, n in enumerate(js['nodes']) if nodo_cuerpo in n.get('children', [])), None)
    if padre is None:
        js['scenes'][js.get('scene', 0)]['nodes'].append(nuevo)
    else:
        js['nodes'][padre]['children'].append(nuevo)

    js['buffers'][0]['byteLength'] = len(blob)
    jb = json.dumps(js, separators=(',', ':')).encode(); jb += b' ' * ((4 - len(jb) % 4) % 4)
    blob.extend(b'\0' * ((4 - len(blob) % 4) % 4))
    total = 12 + 8 + len(jb) + 8 + len(blob)
    with open(salida, 'wb') as f:
        f.write(struct.pack('<III', 0x46546C67, 2, total))
        f.write(struct.pack('<II', len(jb), 0x4E4F534A)); f.write(jb)
        f.write(struct.pack('<II', len(blob), 0x004E4942)); f.write(blob)
    print("  escrito %s (%.1f MB)" % (salida, total / 1048576))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3],
         float(sys.argv[4]), float(sys.argv[5]), float(sys.argv[6]), float(sys.argv[7]),
         int(sys.argv[8]) if len(sys.argv) > 8 else 110)
