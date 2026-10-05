"""Convierte un LUT .cube (3D) en la tira 2D que espera el Color Lookup de URP.

URP (ApplyLut2D) lee una tira de N bloques de NxN: el azul elige el bloque, el
rojo avanza a la derecha dentro del bloque y el verde hacia arriba (fila 0 de
Unity = abajo = última fila del PNG). N tiene que ser el "Grading LUT size" del
pipeline (32 en PC_RPAsset), así que el LUT de 25 de Genies se remuestrea con
interpolación trilineal, la misma que hace three.js al leer su textura 3D.

Uso: python lut_to_unity.py entrada.cube salida.png [N]
"""

import sys
import zlib
import struct
from pathlib import Path

import numpy as np


def read_cube(path: Path) -> np.ndarray:
    size = None
    dmin = np.zeros(3)
    dmax = np.ones(3)
    rows = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key = line.split()[0].upper()
        if key == "LUT_3D_SIZE":
            size = int(line.split()[1])
        elif key == "DOMAIN_MIN":
            dmin = np.array([float(v) for v in line.split()[1:4]])
        elif key == "DOMAIN_MAX":
            dmax = np.array([float(v) for v in line.split()[1:4]])
        elif key in ("TITLE", "LUT_1D_SIZE", "LUT_3D_INPUT_RANGE"):
            if key == "LUT_1D_SIZE":
                raise SystemExit("Solo se admiten LUT 3D")
        else:
            rows.append([float(v) for v in line.split()[:3]])
    if size is None or len(rows) != size**3:
        raise SystemExit(f"LUT inválido: tamaño {size}, {len(rows)} filas")
    if not (np.allclose(dmin, 0) and np.allclose(dmax, 1)):
        raise SystemExit(f"Dominio no estándar: {dmin} {dmax}")
    # En .cube el rojo cambia más rápido, luego el verde y luego el azul: [b, g, r, canal]
    return np.array(rows, dtype=np.float64).reshape(size, size, size, 3)


def sample(lut: np.ndarray, r: np.ndarray, g: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Interpolación trilineal en coordenadas 0..1 (los extremos caen en los nodos)."""
    n = lut.shape[0]
    def split(c):
        x = np.clip(c, 0.0, 1.0) * (n - 1)
        i0 = np.clip(np.floor(x).astype(int), 0, n - 2)
        return i0, x - i0
    r0, fr = split(r)
    g0, fg = split(g)
    b0, fb = split(b)
    out = np.zeros(r.shape + (3,))
    for db in (0, 1):
        wb = fb if db else 1 - fb
        for dg in (0, 1):
            wg = fg if dg else 1 - fg
            for dr in (0, 1):
                wr = fr if dr else 1 - fr
                out += (wb * wg * wr)[..., None] * lut[b0 + db, g0 + dg, r0 + dr]
    return out


def write_png(path: Path, rgb8: np.ndarray) -> None:
    """PNG RGB de 8 bits sin dependencias (zlib + struct)."""
    h, w, _ = rgb8.shape
    raw = b"".join(b"\x00" + rgb8[y].tobytes() for y in range(h))
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    path.write_bytes(png)


def main() -> None:
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 32
    lut = read_cube(src)
    coords = np.arange(n) / (n - 1)
    # Imagen n alto x n*n ancho, en coordenadas de Unity (fila 0 = abajo).
    x = np.arange(n * n)
    r = coords[x % n]
    b = coords[x // n]
    g = coords
    R, G = np.meshgrid(r, g)          # [fila=g, columna]
    B, _ = np.meshgrid(b, g)
    strip = sample(lut, R, G, B)       # [g, x, 3]
    img = np.flipud(strip)             # PNG: la primera fila es la de arriba (g = 1)
    rgb8 = np.clip(np.round(img * 255.0), 0, 255).astype(np.uint8)
    write_png(dst, rgb8)
    # Comprobaciones: error de cuantización y diferencia con el LUT original en sus nodos.
    back = np.flipud(rgb8.astype(np.float64) / 255.0)
    print(f"{dst.name}: {n * n}x{n}, error máx. de 8 bits {np.abs(back - strip).max():.4f}")
    grays = [0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9, 1.0]
    for v in grays:
        o = sample(lut, np.array(v), np.array(v), np.array(v))
        print(f"  gris {v:.1f} -> {np.round(o, 3)}")
    for name, c in {"rojo": (1, 0, 0), "verde": (0, 1, 0), "azul": (0, 0, 1),
                    "piel": (0.85, 0.62, 0.50), "navy": (0.05, 0.08, 0.20)}.items():
        o = sample(lut, np.array(c[0]), np.array(c[1]), np.array(c[2]))
        print(f"  {name:5s} {c} -> {np.round(o, 3)}")


if __name__ == "__main__":
    main()
