"""Cine la camiseta de un avatar RPM contrayendo su geometria hacia el torso.

RPM borra la piel que la ropa tapa, asi que los vertices de la prenda SON la
tela: se pueden acercar al eje del cuerpo sin descubrir nada. La camiseta viene
partida en piezas sueltas (cuello, dos mangas, delantero y espalda), asi que se
localiza por componentes conexas y no por pesos de skinning, que en el atlas
mezclan tela y piel.

El factor de contraccion va por altura: 1.0 en los hombros (si se movieran se
abriria la costura con el cuello y las sisas), minimo en la cintura, y algo mas
suelto en el bajo para que abrace la cadera en vez de terminar en punta.

Uso: cenir_prenda.py entrada.glb salida.glb [cintura] [busto] [bajo] [manga]
"""
import json, os, struct, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from injerto_glb import read, acc, partes

def escribe(js, bn, out):
    j = json.dumps(js, separators=(',', ':')).encode()
    j += b' ' * (-len(j) % 4)
    b = bytes(bn) + b'\0' * (-len(bn) % 4)
    with open(out, 'wb') as f:
        f.write(b'glTF' + struct.pack('<II', 2, 12 + 8 + len(j) + 8 + len(b)))
        f.write(struct.pack('<II', len(j), 0x4E4F534A) + j)
        f.write(struct.pack('<II', len(b), 0x004E4942) + b)

def sobrescribe(js, bn, acc_i, V):
    a = js['accessors'][acc_i]
    bv = js['bufferViews'][a['bufferView']]
    off = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
    stride = bv.get('byteStride') or 12
    raw = V.astype('<f4').tobytes()
    for i in range(len(V)):
        bn[off + i * stride: off + i * stride + 12] = raw[i * 12:(i + 1) * 12]
    a['min'] = V.min(0).tolist()
    a['max'] = V.max(0).tolist()

def main(entrada, salida, k_cint=0.80, k_busto=0.95, k_bajo=0.86, k_manga=0.88):
    ps = partes(entrada)
    js, bn = ps[0]['js'], bytearray(ps[0]['bn'])
    # el cuerpo es la primitiva mas poblada que no sea la cabeza injertada
    cuerpo_prim = max((p for p in ps if p['mesh'] != 'Sonia_Cabeza'),
                      key=lambda p: p['verts'])['prim']
    # la camiseta: piezas del cuerpo que llegan al pecho y no bajan de la cadera
    prenda, sel_total, piezas = cuerpo_prim, None, []
    for p in ps:
        if p['prim'] is not cuerpo_prim:
            continue
        lo, hi = p['bbox']
        if hi[1] >= 1.25 and lo[1] >= 0.95 and max(abs(lo[0]), abs(hi[0])) <= 0.30:
            sel_total = p['sel'].copy() if sel_total is None else (sel_total | p['sel'])
            piezas.append(p)
            print("  pieza: %d verts  y %.3f..%.3f  x %.3f..%.3f" % (p['verts'], lo[1], hi[1], lo[0], hi[0]))
    if sel_total is None:
        raise SystemExit("no se ha encontrado la camiseta")

    P = acc(js, bn, prenda['attributes']['POSITION']).astype(np.float64)
    idx = np.nonzero(sel_total)[0]
    Pt = P[idx]
    y_bajo, y_alto = Pt[:, 1].min(), Pt[:, 1].max()
    print("  camiseta: %d vertices, y %.3f..%.3f" % (len(idx), y_bajo, y_alto))

    # eje del torso por altura (mediana de x y z en cada franja)
    franjas = np.linspace(y_bajo, y_alto, 20)
    cen = (franjas[:-1] + franjas[1:]) / 2
    eje = []
    for a, b in zip(franjas[:-1], franjas[1:]):
        s = (Pt[:, 1] >= a) & (Pt[:, 1] < b)
        eje.append([np.median(Pt[s, 0]), np.median(Pt[s, 2])] if s.sum() > 4 else [np.nan, np.nan])
    eje = np.array(eje)
    for c in (0, 1):
        m = ~np.isnan(eje[:, c])
        eje[:, c] = np.interp(cen, cen[m], eje[m, c])

    # perfil por altura normalizada: bajo(0) - cintura(0.2) - busto(0.65) - hombro(1)
    t_ref = np.array([0.00, 0.20, 0.65, 0.88, 1.00])
    f_ref = np.array([k_bajo, k_cint, k_busto, 0.995, 1.0])

    # las mangas cuelgan de los hombros: van aparte, no por altura
    mangas = np.zeros(len(P), bool)
    for p in piezas:
        lo, hi = p['bbox']
        if abs((lo[0] + hi[0]) / 2) > 0.12:
            mangas |= p['sel']
    cuerpo = sel_total & ~mangas
    ic = np.nonzero(cuerpo)[0]

    Q = P.copy()
    y = P[ic, 1]
    t = np.clip((y - y_bajo) / (y_alto - y_bajo), 0, 1)
    f = np.interp(t, t_ref, f_ref)
    cx = np.interp(y, cen, eje[:, 0])
    cz = np.interp(y, cen, eje[:, 1])
    Q[ic, 0] = cx + (P[ic, 0] - cx) * f
    Q[ic, 2] = cz + (P[ic, 2] - cz) * f

    for lado in (-1, 1):
        s = mangas & ((P[:, 0] * lado) > 0)
        if s.sum() < 10:
            continue
        i2 = np.nonzero(s)[0]
        Pb = P[i2]
        c = Pb.mean(0)
        u = np.linalg.svd(Pb - c, full_matrices=False)[2][0]
        d = (Pb - c) @ u
        if np.dot(u, [lado, 0, 0]) < 0:
            u, d = -u, -d
        tt = (d - d.min()) / (d.max() - d.min() + 1e-9)   # 0 sisa, 1 borde
        proy = c + np.outer(d, u)
        g = 1.0 - (1.0 - k_manga) * tt
        Q[i2] = proy + (Pb - proy) * g[:, None]
        print("  manga %s: %d vertices" % ('izq' if lado < 0 else 'der', s.sum()))

    # tope: donde la camiseta cae sobre el pantalon, no puede meterse dentro
    bajo = None
    for p in ps:
        if p['prim'] is not cuerpo_prim:
            continue
        lo, hi = p['bbox']
        if lo[1] < 0.6 and hi[1] > y_bajo and p['verts'] > 400:
            bajo = p['sel'].copy() if bajo is None else (bajo | p['sel'])
    if bajo is not None:
        Pb = P[bajo]
        solape = (Pb[:, 1] >= y_bajo - 0.02) & (Pb[:, 1] <= y_bajo + 0.15)
        if solape.sum() > 20:
            Pb = Pb[solape]
            def radio(V, ys):
                cx = np.interp(V[:, 1], cen, eje[:, 0])
                cz = np.interp(V[:, 1], cen, eje[:, 1])
                dx, dz = V[:, 0] - cx, V[:, 2] - cz
                return np.hypot(dx, dz), np.arctan2(dz, dx)
            rb, ab = radio(Pb, None)
            # rejilla de radio del pantalon por altura y angulo
            ny, na = 6, 16
            ys = np.linspace(y_bajo - 0.02, y_bajo + 0.15, ny + 1)
            rej = np.zeros((ny, na))
            for iy in range(ny):
                sy = (Pb[:, 1] >= ys[iy]) & (Pb[:, 1] < ys[iy + 1])
                for ia in range(na):
                    a0 = -np.pi + 2 * np.pi * ia / na
                    sa = sy & (ab >= a0) & (ab < a0 + 2 * np.pi / na)
                    rej[iy, ia] = rb[sa].max() if sa.sum() else 0.0
            # rellenar huecos con el maximo de la franja
            for iy in range(ny):
                m = rej[iy] > 0
                if m.any():
                    rej[iy][~m] = rej[iy][m].max()
            Qc = Q[ic]
            rq, aq = radio(Qc, None)
            iy = np.clip(np.searchsorted(ys, Qc[:, 1]) - 1, 0, ny - 1)
            ia = np.clip(((aq + np.pi) / (2 * np.pi) * na).astype(int), 0, na - 1)
            minimo = rej[iy, ia] + 0.005
            dentro = (Qc[:, 1] <= y_bajo + 0.15) & (rq < minimo) & (rej[iy, ia] > 0)
            if dentro.any():
                cx = np.interp(Qc[:, 1], cen, eje[:, 0])
                cz = np.interp(Qc[:, 1], cen, eje[:, 1])
                esc = np.where(dentro, minimo / np.maximum(rq, 1e-6), 1.0)
                Q[ic, 0] = cx + (Qc[:, 0] - cx) * esc
                Q[ic, 2] = cz + (Qc[:, 2] - cz) * esc
                print("  tope sobre el pantalon: %d vertices corregidos" % dentro.sum())

    print("  desplazamiento maximo: %.1f mm" % (np.abs(Q - P).max() * 1000))
    sobrescribe(js, bn, prenda['attributes']['POSITION'], Q)

    # normales rehechas solo donde se ha movido la geometria: las de la piel y
    # el resto de la ropa son las que horneo RPM y se conservan tal cual
    N = acc(js, bn, prenda['attributes']['NORMAL']).astype(np.float64).copy()
    I = acc(js, bn, prenda['indices']).astype(np.int64).ravel().reshape(-1, 3)
    Nn = np.zeros_like(Q)
    fn = np.cross(Q[I[:, 1]] - Q[I[:, 0]], Q[I[:, 2]] - Q[I[:, 0]])
    for k in range(3):
        np.add.at(Nn, I[:, k], fn)
    ln = np.linalg.norm(Nn, axis=1, keepdims=True)
    Nn = np.where(ln > 1e-12, Nn / np.maximum(ln, 1e-12), np.array([0.0, 0.0, 1.0]))
    N[sel_total] = Nn[sel_total]
    sobrescribe(js, bn, prenda['attributes']['NORMAL'], N)
    js['accessors'][prenda['attributes']['NORMAL']].pop('min', None)
    js['accessors'][prenda['attributes']['NORMAL']].pop('max', None)

    escribe(js, bn, salida)
    print("  escrito %s (%.1f MB)" % (salida, len(bn) / 1e6))

if __name__ == '__main__':
    a = sys.argv
    main(a[1], a[2], *[float(x) for x in a[3:7]])
