#!/usr/bin/env python3
"""Cirugía sobre GLB de Ready Player Me, sin Blender.

Todos los avatares de RPM comparten esqueleto, topología de cabeza y anillo de
cuello (comprobado: 0,00 mm de desviación entre modelos), así que las piezas se
intercambian entre ficheros sin retocar nada.

    injerto_glb.py cabeza  cuerpo.glb cabeza.glb salida.glb
        Pone la cabeza, el pelo, los ojos y los dientes del segundo avatar
        sobre el cuerpo vestido del primero. Conserva los 67 blendshapes.

    injerto_glb.py prenda  receptor.glb donante.glb Wolf3D_Outfit_Top salida.glb
        Quita el top del receptor (una exportación de atlas) y le injerta la
        prenda del donante. Ojo: RPM borra la geometría oculta bajo la ropa, así
        que si la prenda nueva cubre más o menos que la vieja quedan huecos.

Las dependencias son numpy y nada más. Los blendshapes se copian byte a byte,
sin recodificar, así que no engordan ni pierden precisión.
"""
import json, struct, sys
import numpy as np

COMP={5120:'i1',5121:'u1',5122:'i2',5123:'u2',5125:'u4',5126:'f4'}
NC={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4,'MAT4':16}
def read(p):
    d=open(p,'rb').read(); off=12; js=bn=None
    while off+8<=len(d):
        cl,ct=struct.unpack('<II',d[off:off+8]); ch=d[off+8:off+8+cl]
        if ct==0x4E4F534A: js=json.loads(ch.decode('utf-8','replace'))
        elif ct==0x004E4942: bn=ch
        off+=8+cl
        if off%4: off+=4-off%4
    return js,bn
def acc(js,bn,i):
    a=js['accessors'][i]; n=NC[a['type']]; dt=np.dtype('<'+COMP[a['componentType']])
    bv=js['bufferViews'][a['bufferView']]
    start=bv.get('byteOffset',0)+a.get('byteOffset',0)
    stride=bv.get('byteStride') or n*dt.itemsize
    raw=np.frombuffer(bn,np.uint8,count=stride*a['count'],offset=start).reshape(a['count'],stride)[:,:n*dt.itemsize].copy()
    return raw.view(dt).reshape(a['count'],n)
def partes(path):
    js,bn=read(path); out=[]
    for m in js['meshes']:
        tn=(m.get('extras',{}) or {}).get('targetNames',[]) or []
        for pr in m['primitives']:
            pos=acc(js,bn,pr['attributes']['POSITION']).astype(np.float64)
            idx=acc(js,bn,pr['indices']).astype(np.int64).ravel()
            # componentes conexas por union-find sobre las aristas
            n=len(pos); par=np.arange(n)
            def find(x):
                while par[x]!=x: par[x]=par[par[x]]; x=par[x]
                return x
            tri=idx.reshape(-1,3)
            for a_,b_ in ((0,1),(1,2),(2,0)):
                for u,v in zip(tri[:,a_],tri[:,b_]):
                    ru,rv=find(u),find(v)
                    if ru!=rv: par[ru]=rv
            roots=np.array([find(i) for i in range(n)])
            for r in np.unique(roots):
                sel=roots==r
                if sel.sum()<20: continue
                tsel=sel[tri[:,0]]
                out.append({'mesh':m.get('name',''),'verts':int(sel.sum()),'tris':int(tsel.sum()),
                            'bbox':(pos[sel].min(0).round(3).tolist(),pos[sel].max(0).round(3).tolist()),
                            'pos':pos[sel],'tri':tri[tsel],'sel':sel,'targetNames':tn,'prim':pr,'js':js,'bn':bn})
    return out
def borde_cuello(p):
    """Vertices del borde abierto mas alto (el cuello)."""
    tri=p['tri']; remap={v:i for i,v in enumerate(np.nonzero(p['sel'])[0])}
    from collections import Counter
    c=Counter()
    for a_,b_ in ((0,1),(1,2),(2,0)):
        for u,v in zip(tri[:,a_],tri[:,b_]):
            c[(min(u,v),max(u,v))]+=1
    borde=[e for e,k in c.items() if k==1]
    if not borde: return None
    vs=sorted({v for e in borde for v in e})
    P=np.array([p['pos'][remap[v]] for v in vs])
    return P


Y_CUELLO = 1.52          # por encima de esto están la cabeza, el pelo, los ojos y los dientes
FUERA = ('EyeLeft', 'EyeRight', 'Wolf3D_Head', 'Wolf3D_Teeth', 'Wolf3D_Hair')

def copia_pose(js, ca_js, result_log):
    """Copia la pose de reposo del esqueleto del donante al receptor.

    Los avatares de RPM se exportan en T-pose o en A-pose segun como se pidieran.
    Las matrices de bind son las mismas, pero el rig Humanoid que genera Unity se
    construye a partir de la pose de los nodos: si el cuerpo esta en A-pose y los
    clips estan hechos para la T-pose, el retargeting pliega los brazos dentro del
    torso. Igualar la pose a la del donante lo arregla.
    """
    donante = {n.get('name'): n for n in ca_js['nodes'] if n.get('name')}
    cambiados = 0
    for n in js['nodes']:
        d = donante.get(n.get('name'))
        if d is None or 'mesh' in n or 'mesh' in d:
            continue
        antes = (n.get('translation'), n.get('rotation'), n.get('scale'))
        for k in ('translation', 'rotation', 'scale', 'matrix'):
            n.pop(k, None)
            if k in d:
                n[k] = list(d[k])
        if (n.get('translation'), n.get('rotation'), n.get('scale')) != antes:
            cambiados += 1
    result_log("  pose de reposo igualada a la del donante: %d huesos" % cambiados)


def injerto_cabeza(cuerpo_path, cabeza_path, out_path):
    cu_js, cu_bn = read(cuerpo_path)
    ca_js, ca_bn = read(cabeza_path)

    js = json.loads(json.dumps(cu_js))
    copia_pose(js, ca_js, result_log=lambda m: print(m))
    blob = bytearray(cu_bn)

    def add_view(data, target=None):
        while len(blob) % 4:
            blob.append(0)
        off = len(blob)
        blob.extend(data)
        bv = {'buffer': 0, 'byteOffset': off, 'byteLength': len(data)}
        if target:
            bv['target'] = target
        js['bufferViews'].append(bv)
        return len(js['bufferViews']) - 1

    vistas = {}

    def copia_vista(i):
        if i not in vistas:
            bv = ca_js['bufferViews'][i]
            o = bv.get('byteOffset', 0)
            nueva = add_view(ca_bn[o:o + bv['byteLength']], bv.get('target'))
            if 'byteStride' in bv:
                js['bufferViews'][nueva]['byteStride'] = bv['byteStride']
            vistas[i] = nueva
        return vistas[i]

    def copia_acc(i):
        """Copia un accessor del donante byte a byte, incluido el modo disperso."""
        a = json.loads(json.dumps(ca_js['accessors'][i]))
        if 'bufferView' in a:
            a['bufferView'] = copia_vista(a['bufferView'])
        sp = a.get('sparse')
        if sp:
            sp['indices']['bufferView'] = copia_vista(sp['indices']['bufferView'])
            sp['values']['bufferView'] = copia_vista(sp['values']['bufferView'])
        js['accessors'].append(a)
        return len(js['accessors']) - 1

    # 1. Fuera la cabeza del cuerpo receptor. Hay dos casos: multi-malla (cada
    #    pieza es una malla con nombre) y atlas de malla unica (todo junto, y
    #    entonces solo se recortan los triangulos por encima del cuello).
    quitar = {i for i, m in enumerate(cu_js['meshes']) if m.get('name') in FUERA}
    if quitar:
        for n in js['nodes']:
            if 'children' in n:
                n['children'] = [c for c in n['children'] if cu_js['nodes'][c].get('mesh') not in quitar]
        for s in js['scenes']:
            s['nodes'] = [c for c in s['nodes'] if cu_js['nodes'][c].get('mesh') not in quitar]
        print(f"  retiradas del cuerpo: {[cu_js['meshes'][i].get('name') for i in sorted(quitar)]}")
    else:
        cpr = js['meshes'][0]['primitives'][0]
        ctri = acc(cu_js, cu_bn, cpr['indices']).astype(np.int64).ravel().reshape(-1, 3)
        cfuera = np.zeros(len(acc(cu_js, cu_bn, cpr['attributes']['POSITION'])), dtype=bool)
        quitados = 0
        for pz in partes(cuerpo_path):
            if pz['bbox'][1][1] >= Y_CUELLO:
                cfuera[np.nonzero(pz['sel'])[0]] = True
                quitados += pz['tris']
        ckeep = ~cfuera[ctri].any(axis=1)
        ctri_new = ctri[ckeep].astype(np.uint32)
        print(f"  cuerpo de atlas: recortada la cabeza, {quitados} triángulos fuera "
              f"({len(ctri)} → {len(ctri_new)})")
        cpr['_indices_recortados'] = ctri_new      # se escribe abajo, con el resto

    cpr0 = js['meshes'][0]['primitives'][0]
    if '_indices_recortados' in cpr0:
        datos = cpr0.pop('_indices_recortados')
        bvc = add_view(datos.ravel().tobytes(), 34963)
        js['accessors'].append({'bufferView': bvc, 'componentType': 5125,
                                'count': int(datos.size), 'type': 'SCALAR'})
        cpr0['indices'] = len(js['accessors']) - 1

    # 2. De la cabeza donante, solo los triangulos por encima del cuello
    pr = ca_js['meshes'][0]['primitives'][0]
    pos = acc(ca_js, ca_bn, pr['attributes']['POSITION']).astype(np.float64)
    dentro = np.zeros(len(pos), dtype=bool)
    piezas = 0
    for p in partes(cabeza_path):
        if p['bbox'][1][1] >= Y_CUELLO:
            dentro[np.nonzero(p['sel'])[0]] = True
            piezas += p['tris']
    tri = acc(ca_js, ca_bn, pr['indices']).astype(np.int64).ravel().reshape(-1, 3)
    keep = dentro[tri].all(axis=1)
    tri_new = tri[keep].astype(np.uint32)
    print(f"  piezas de cabeza conservadas: {piezas} triángulos ({keep.sum()} tras filtrar)")

    # 3. Copiar atributos, blendshapes, material y texturas del donante
    attrs = {k: copia_acc(v) for k, v in pr['attributes'].items()}
    targets = [{k: copia_acc(v) for k, v in t.items()} for t in pr.get('targets', [])]

    def copia_textura(ti):
        t = ca_js['textures'][ti]
        img = ca_js['images'][t['source']]
        bv = ca_js['bufferViews'][img['bufferView']]
        o = bv.get('byteOffset', 0)
        nv = add_view(ca_bn[o:o + bv['byteLength']])
        js.setdefault('images', []).append(
            {'name': img.get('name', 'cabeza'), 'mimeType': img.get('mimeType', 'image/png'), 'bufferView': nv})
        nt = {'source': len(js['images']) - 1}
        if 'sampler' in t:
            js.setdefault('samplers', []).append(dict(ca_js['samplers'][t['sampler']]))
            nt['sampler'] = len(js['samplers']) - 1
        js.setdefault('textures', []).append(nt)
        return len(js['textures']) - 1

    mat = json.loads(json.dumps(ca_js['materials'][pr['material']]))
    pbr = mat.get('pbrMetallicRoughness', {})
    for slot in ('baseColorTexture', 'metallicRoughnessTexture'):
        if slot in pbr:
            pbr[slot] = {**pbr[slot], 'index': copia_textura(pbr[slot]['index'])}
    for slot in ('normalTexture', 'occlusionTexture', 'emissiveTexture'):
        if slot in mat:
            mat[slot] = {**mat[slot], 'index': copia_textura(mat[slot]['index'])}
    js['materials'].append(mat)
    for e in ca_js.get('extensionsUsed', []):
        if e not in js.setdefault('extensionsUsed', []):
            js['extensionsUsed'].append(e)

    idx_acc = len(js['accessors'])
    js['bufferViews'].append({'buffer': 0, 'byteOffset': 0, 'byteLength': 0})   # marcador, se rellena abajo
    js['bufferViews'].pop()
    bv_idx = add_view(tri_new.ravel().tobytes(), 34963)
    js['accessors'].append({'bufferView': bv_idx, 'componentType': 5125,
                            'count': int(tri_new.size), 'type': 'SCALAR'})

    nueva_malla = {'name': 'Sonia_Cabeza',
                   'primitives': [{'attributes': attrs, 'indices': idx_acc,
                                   'material': len(js['materials']) - 1,
                                   **({'targets': targets} if targets else {})}]}
    tn = (ca_js['meshes'][0].get('extras', {}) or {}).get('targetNames')
    if tn:
        nueva_malla['extras'] = {'targetNames': tn}
    js['meshes'].append(nueva_malla)

    # nodo, colgado del mismo padre que las mallas del cuerpo
    ref = next(i for i, n in enumerate(cu_js['nodes']) if n.get('mesh') is not None and n.get('mesh') not in quitar)
    padre = next((i for i, n in enumerate(cu_js['nodes']) if ref in n.get('children', [])), None)
    js['nodes'].append({'name': 'Sonia_Cabeza', 'mesh': len(js['meshes']) - 1,
                        'skin': cu_js['nodes'][ref].get('skin')})
    nuevo = len(js['nodes']) - 1
    if padre is None:
        js['scenes'][js.get('scene', 0)]['nodes'].append(nuevo)
    else:
        js['nodes'][padre]['children'].append(nuevo)

    js['buffers'][0]['byteLength'] = len(blob)
    jb = json.dumps(js, separators=(',', ':')).encode()
    jb += b' ' * ((4 - len(jb) % 4) % 4)
    blob.extend(b'\0' * ((4 - len(blob) % 4) % 4))
    total = 12 + 8 + len(jb) + 8 + len(blob)
    with open(out_path, 'wb') as f:
        f.write(struct.pack('<III', 0x46546C67, 2, total))
        f.write(struct.pack('<II', len(jb), 0x4E4F534A)); f.write(jb)
        f.write(struct.pack('<II', len(blob), 0x004E4942)); f.write(blob)
    print(f"  escrito {out_path} ({total/1048576:.1f} MB), {len(tn or [])} blendshapes")

def injerto_prenda(rx_path, dn_path, malla, out_path):
    rx, dn = Glb(rx_path), Glb(dn_path)

    # 1. Las piezas del receptor cuyo UV cae en el cuadrante de la prenda
    pr = rx.js['meshes'][0]['primitives'][0]
    uv = rx.acc(pr['attributes']['TEXCOORD_0']).astype(np.float64)
    fuera = np.zeros(len(uv), dtype=bool)
    quitadas = 0
    for p in partes(rx_path):
        idx = np.nonzero(p['sel'])[0]
        m = uv[idx].mean(axis=0)
        if m[0] > 0.5 and m[1] > 0.5:
            fuera[idx] = True
            quitadas += p['tris']
    print(f"  piezas del top del receptor: {quitadas} triángulos, {int(fuera.sum())} vértices")

    tri = rx.acc(pr['indices']).astype(np.int64).ravel().reshape(-1, 3)
    keep = ~fuera[tri].any(axis=1)
    tri_new = tri[keep].astype(np.uint32)
    print(f"  índices: {len(tri)} → {len(tri_new)} triángulos")

    # 2. La prenda del donante
    mi = next(i for i, m in enumerate(dn.js['meshes']) if m.get('name') == malla)
    dpr = dn.js['meshes'][mi]['primitives'][0]
    P = dn.acc(dpr['attributes']['POSITION']).astype(np.float32)
    N = dn.acc(dpr['attributes']['NORMAL']).astype(np.float32)
    UV = dn.acc(dpr['attributes']['TEXCOORD_0']).astype(np.float32)
    J = dn.acc(dpr['attributes']['JOINTS_0']).astype(np.uint16)
    W = dn.acc(dpr['attributes']['WEIGHTS_0']).astype(np.float32)
    I = dn.acc(dpr['indices']).astype(np.uint32).ravel()
    print(f"  prenda '{malla}': {len(I)//3} triángulos, {len(P)} vértices")

    # 3. Reconstruir el GLB del receptor con datos nuevos al final del BIN
    js = json.loads(json.dumps(rx.js))
    pr = js['meshes'][0]['primitives'][0]   # ojo: hay que tocar la copia, no el original
    blob = bytearray(rx.bn)

    def add_view(data: bytes, target=None):
        while len(blob) % 4:
            blob.append(0)
        off = len(blob)
        blob.extend(data)
        bv = {'buffer': 0, 'byteOffset': off, 'byteLength': len(data)}
        if target:
            bv['target'] = target
        js['bufferViews'].append(bv)
        return len(js['bufferViews']) - 1

    def add_acc(arr, tipo, ctype, target=None, minmax=False):
        bv = add_view(arr.tobytes(), target)
        a = {'bufferView': bv, 'componentType': ctype, 'count': len(arr), 'type': tipo}
        if minmax:
            a['min'] = arr.min(axis=0).tolist()
            a['max'] = arr.max(axis=0).tolist()
        js['accessors'].append(a)
        return len(js['accessors']) - 1

    # índices recortados del receptor
    pr['indices'] = add_acc(tri_new.ravel().reshape(-1, 1), 'SCALAR', 5125, 34963)

    # texturas y material de la prenda
    def copia_textura(tex_idx):
        t = dn.js['textures'][tex_idx]
        img = dn.js['images'][t['source']]
        bv = add_view(dn.raw_bufferview(img['bufferView']))
        js.setdefault('images', []).append(
            {'name': img.get('name', 'prenda'), 'mimeType': img.get('mimeType', 'image/png'), 'bufferView': bv})
        src = len(js['images']) - 1
        nt = {'source': src}
        if 'sampler' in t:
            s = dn.js['samplers'][t['sampler']]
            js.setdefault('samplers', []).append(dict(s))
            nt['sampler'] = len(js['samplers']) - 1
        js.setdefault('textures', []).append(nt)
        return len(js['textures']) - 1

    mat = json.loads(json.dumps(dn.js['materials'][dpr['material']]))
    pbr = mat.get('pbrMetallicRoughness', {})
    for slot in ('baseColorTexture', 'metallicRoughnessTexture'):
        if slot in pbr:
            pbr[slot] = {**pbr[slot], 'index': copia_textura(pbr[slot]['index'])}
    for slot in ('normalTexture', 'occlusionTexture', 'emissiveTexture'):
        if slot in mat:
            mat[slot] = {**mat[slot], 'index': copia_textura(mat[slot]['index'])}
    js['materials'].append(mat)
    mat_idx = len(js['materials']) - 1
    for e in dn.js.get('extensionsUsed', []):
        if e not in js.setdefault('extensionsUsed', []):
            js['extensionsUsed'].append(e)

    prim = {
        'attributes': {
            'POSITION': add_acc(P, 'VEC3', 5126, 34962, minmax=True),
            'NORMAL': add_acc(N, 'VEC3', 5126, 34962),
            'TEXCOORD_0': add_acc(UV, 'VEC2', 5126, 34962),
            'JOINTS_0': add_acc(J, 'VEC4', 5123, 34962),
            'WEIGHTS_0': add_acc(W, 'VEC4', 5126, 34962),
        },
        'indices': add_acc(I.reshape(-1, 1), 'SCALAR', 5125, 34963),
        'material': mat_idx,
    }
    js['meshes'].append({'name': malla, 'primitives': [prim]})
    mesh_idx = len(js['meshes']) - 1

    nodo_avatar = next(i for i, n in enumerate(js['nodes']) if n.get('mesh') == 0)
    js['nodes'].append({'name': malla, 'mesh': mesh_idx, 'skin': js['nodes'][nodo_avatar]['skin']})
    nuevo = len(js['nodes']) - 1
    padre = next((i for i, n in enumerate(js['nodes']) if nodo_avatar in n.get('children', [])), None)
    if padre is None:
        js['scenes'][js.get('scene', 0)]['nodes'].append(nuevo)
    else:
        js['nodes'][padre]['children'].append(nuevo)

    js['buffers'][0]['byteLength'] = len(blob)
    jb = json.dumps(js, separators=(',', ':')).encode()
    jb += b' ' * ((4 - len(jb) % 4) % 4)
    blob.extend(b'\0' * ((4 - len(blob) % 4) % 4))
    total = 12 + 8 + len(jb) + 8 + len(blob)
    with open(out_path, 'wb') as f:
        f.write(struct.pack('<III', 0x46546C67, 2, total))
        f.write(struct.pack('<II', len(jb), 0x4E4F534A)); f.write(jb)
        f.write(struct.pack('<II', len(blob), 0x004E4942)); f.write(blob)
    print(f"  escrito {out_path} ({total/1048576:.1f} MB)")

if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1] not in ('cabeza', 'prenda'):
        print(__doc__)
        raise SystemExit(1)
    if sys.argv[1] == 'cabeza':
        injerto_cabeza(*sys.argv[2:5])
    else:
        injerto_prenda(*sys.argv[2:6])
