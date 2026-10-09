"""Pone el código y los assets del repo en un orquestador de Windows ya congelado, desde un Mac.

PyInstaller no congela para Windows desde macOS y el workflow de GitHub Actions
(``orquestador-windows.yml``) no siempre se puede lanzar. Pero el ejecutable de Windows
guarda el código de Python como bytecode de 3.12, que es el mismo en cualquier sistema.
Este script, sobre la carpeta ``sonia-orquestador`` de una build anterior de Windows:

1. Rehace ``sonia-orquestador.exe`` copiando sin tocar todas sus entradas (cargador,
   módulos de terceros) y cambiando en ``PYZ.pyz`` solo los módulos ``sonia.*`` por los
   del repo, compilados aquí con las rutas de Windows (``sonia\\trivia\\game.py``) como
   haría PyInstaller allí. Después recalcula la suma de verificación PE (el exe no lleva
   firma Authenticode).
2. Copia los ``assets/`` y los estáticos del panel que cambiaron (archivos sueltos en
   ``_internal``, los mismos que mete ``scripts/build_orquestador.sh``).

Vale mientras no cambien las dependencias de terceros: si se añade un paquete, hay que
congelar en Windows. Se ejecuta con el Python del orquestador (3.12), desde ``server/``:

    uv run --no-sync python ../scripts/parchea_orquestador_windows.py \\
        ../unity/Build/orquestador/Windows/sonia-orquestador

Con ``--sin-cambios`` rehace el exe sin sustituir nada y no copia datos: tiene que salir
idéntico salvo un byte de ``marshal`` en el índice del PYZ y la suma PE (comprobado con la
1.0.195; con el código de 61e7ce3 sale byte a byte el orquestador de la 1.0.197).
``--probar`` lo deja en ``sonia-orquestador.parcheado.exe`` sin tocar el original.
"""

from __future__ import annotations

import argparse
import filecmp
import importlib.util
import marshal
import shutil
import struct
import sys
import zlib
from array import array
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SERVER = REPO / "server"
# Mismas carpetas que --add-data en scripts/build_orquestador.sh (origen, destino en _internal).
DATA_DIRS = [
    *(
        (REPO / "assets" / name, Path("assets") / name)
        for name in ("knowledge", "gallery", "showcase", "trivia", "agenda", "faces", "fonts")
    ),
    (SERVER / "sonia" / "panel" / "static", Path("sonia") / "panel" / "static"),
]

COOKIE_MAGIC = b"MEI\014\013\012\013\016"
COOKIE_FORMAT = "!8sIIII64s"
COOKIE_LEN = struct.calcsize(COOKIE_FORMAT)
TOC_ENTRY_FORMAT = "!IIIIBc"
TOC_ENTRY_LEN = struct.calcsize(TOC_ENTRY_FORMAT)
PYZ_HEADER_LEN = 12 + 5
PYZ_ITEM_MODULE = 0
PYZ_ITEM_PKG = 1
ZLIB_LEVEL = 6


def read_exe(data: bytes) -> tuple[bytes, list[list], int, bytes]:
    """Cargador, entradas del CArchive de PyInstaller, versión de Python y nombre de su DLL."""
    pos = data.rfind(COOKIE_MAGIC)
    if pos < 0 or pos + COOKIE_LEN != len(data):
        raise SystemExit("no es un ejecutable de PyInstaller (la cookie no está al final)")
    _, arch_len, toc_off, toc_len, pyvers, pylib = struct.unpack(
        COOKIE_FORMAT, data[pos : pos + COOKIE_LEN]
    )
    start = len(data) - arch_len
    arch = data[start:]
    entries = []
    p = toc_off
    while p < toc_off + toc_len:
        elen, doff, clen, dlen, compress, typecode = struct.unpack(
            TOC_ENTRY_FORMAT, arch[p : p + TOC_ENTRY_LEN]
        )
        name = arch[p + TOC_ENTRY_LEN : p + elen].rstrip(b"\0").decode("utf-8")
        entries.append([name, dlen, compress, typecode, arch[doff : doff + clen]])
        p += elen
    return data[:start], entries, pyvers, pylib


def serialize_toc(toc: list[tuple]) -> bytes:
    out = []
    for offset, clen, dlen, compress, typecode, name in toc:
        raw = name.encode("utf-8")
        name_len = len(raw) + 1
        entry_len = TOC_ENTRY_LEN + name_len
        if entry_len % 16:
            name_len += 16 - entry_len % 16
        out.append(
            struct.pack(
                TOC_ENTRY_FORMAT + f"{name_len}s",
                TOC_ENTRY_LEN + name_len,
                offset,
                clen,
                dlen,
                compress,
                typecode,
                raw,
            )
        )
    return b"".join(out)


def write_archive(entries: list[list], pyvers: int, pylib: bytes) -> bytes:
    out = bytearray()
    toc = []
    for name, dlen, compress, typecode, blob in entries:
        toc.append((len(out), len(blob), dlen, compress, typecode, name))
        out += blob
    toc_off = len(out)
    toc_data = serialize_toc(toc)
    out += toc_data
    arch_len = toc_off + len(toc_data) + COOKIE_LEN
    out += struct.pack(COOKIE_FORMAT, COOKIE_MAGIC, arch_len, toc_off, len(toc_data), pyvers, pylib)
    return bytes(out)


def read_pyz(blob: bytes) -> tuple[bytes, list[list]]:
    if blob[:4] != b"PYZ\0":
        raise SystemExit("PYZ.pyz sin la cabecera esperada")
    (toc_off,) = struct.unpack("!i", blob[8:12])
    toc = marshal.loads(blob[toc_off:])
    items = [[name, typecode, blob[off : off + length]] for name, (typecode, off, length) in toc]
    return blob[4:8], items


def write_pyz(pymagic: bytes, items: list[list]) -> bytes:
    out = bytearray(b"\0" * PYZ_HEADER_LEN)
    toc = []
    for name, typecode, data in items:
        toc.append((name, (typecode, len(out), len(data))))
        out += data
    toc_off = len(out)
    out += marshal.dumps(toc)
    out[0:4] = b"PYZ\0"
    out[4:8] = pymagic
    out[8:12] = struct.pack("!i", toc_off)
    return bytes(out)


def sonia_modules() -> dict[str, tuple[int, object]]:
    """Módulo -> (tipo, código) de todo ``server/sonia``, con rutas de Windows."""
    modules = {}
    for path in sorted((SERVER / "sonia").rglob("*.py")):
        rel = path.relative_to(SERVER)
        parts = list(rel.with_suffix("").parts)
        if parts[-1] == "__init__":
            name, typecode = ".".join(parts[:-1]), PYZ_ITEM_PKG
        else:
            name, typecode = ".".join(parts), PYZ_ITEM_MODULE
        filename = "\\".join(rel.parts)
        code = compile(path.read_text(encoding="utf-8"), filename, "exec", dont_inherit=True)
        modules[name] = (typecode, code)
    return modules


def patch_pyz(items: list[list]) -> None:
    modules = sonia_modules()
    same, changed, added = 0, [], []
    index = {item[0]: item for item in items}
    for name, (typecode, code) in modules.items():
        data = zlib.compress(marshal.dumps(code), ZLIB_LEVEL)
        old = index.get(name)
        if old is None:
            items.append([name, typecode, data])
            added.append(name)
            continue
        if old[1] != typecode:
            raise SystemExit(f"{name}: era de tipo {old[1]} y ahora {typecode}")
        if old[2] == data or marshal.loads(zlib.decompress(old[2])) == code:
            same += 1
            continue
        old[2] = data
        changed.append(name)
    stale = [
        item[0]
        for item in items
        if (item[0] == "sonia" or item[0].startswith("sonia.")) and item[0] not in modules
    ]
    print(
        f"sonia: {same} iguales, {len(changed)} cambiados, {len(added)} nuevos, {len(stale)} sin fuente"
    )
    for name in changed:
        print("  cambiado:", name)
    for name in added:
        print(
            "  nuevo (si importa algo de terceros que no estaba, hay que congelar en Windows):",
            name,
        )
    for name in stale:
        print("  sin fuente en el repo (se deja):", name)


def pe_checksum_offset(data: bytes) -> int:
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe : pe + 4] != b"PE\0\0":
        raise SystemExit("el ejecutable no tiene cabecera PE")
    # Firma (4) + cabecera COFF (20) + 64 bytes de la cabecera opcional hasta CheckSum.
    return pe + 4 + 20 + 64


def pe_checksum(data: bytes) -> int:
    """La suma de verificación PE de Windows (la de ``CheckSumMappedFile``)."""
    field = pe_checksum_offset(data)
    words = array("H", data[:field] + b"\0\0\0\0" + data[field + 4 :] + b"\0" * (len(data) % 2))
    if sys.byteorder == "big":
        words.byteswap()
    total = sum(words)
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return total + len(data)


def with_checksum(data: bytes) -> bytes:
    field = pe_checksum_offset(data)
    return data[:field] + struct.pack("<I", pe_checksum(data)) + data[field + 4 :]


def patch_exe(exe: Path, target: Path, *, unchanged: bool) -> None:
    original = exe.read_bytes()
    stored = struct.unpack_from("<I", original, pe_checksum_offset(original))[0]
    if stored and stored != pe_checksum(original):
        print(f"aviso: la suma PE del original no cuadra ({stored:#x}); se escribe la buena")
    boot, entries, pyvers, pylib = read_exe(original)
    if pyvers != sys.version_info[0] * 100 + sys.version_info[1]:
        raise SystemExit(f"el exe es de Python {pyvers // 100}.{pyvers % 100}: ejecútalo con ese")
    pyz_entry = next(e for e in entries if e[0] == "PYZ.pyz")
    if pyz_entry[2]:
        raise SystemExit("PYZ.pyz va comprimido entero: formato no previsto")
    pymagic, items = read_pyz(pyz_entry[4])
    if pymagic != importlib.util.MAGIC_NUMBER:
        raise SystemExit("el bytecode del exe es de otra versión de Python")
    if not unchanged:
        patch_pyz(items)
    pyz_entry[4] = write_pyz(pymagic, items)
    pyz_entry[1] = len(pyz_entry[4])
    result = with_checksum(boot + write_archive(entries, pyvers, pylib))
    if result == original:
        print("el exe ya estaba al día")
        return
    differing = (
        sum(a != b for a, b in zip(result, original, strict=True))
        if len(result) == len(original)
        else None
    )
    target.write_bytes(result)
    detail = f", {differing} bytes distintos" if differing is not None else ""
    print(f"escrito {target.name}: {len(result)} bytes (antes {len(original)}{detail})")


def same_text(a: Path, b: Path) -> bool:
    """Iguales, o solo cambian los saltos de línea: el runner de Windows los saca con CRLF."""
    if filecmp.cmp(a, b, shallow=False):
        return True
    return a.read_bytes().replace(b"\r\n", b"\n") == b.read_bytes().replace(b"\r\n", b"\n")


def sync_data(internal: Path) -> None:
    copied = []
    for source, dest in DATA_DIRS:
        for path in sorted(source.rglob("*")):
            if not path.is_file() or path.name == ".DS_Store" or "__pycache__" in path.parts:
                continue
            target = internal / dest / path.relative_to(source)
            if target.is_file() and same_text(path, target):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            copied.append(target.relative_to(internal))
        extra = (
            [
                p.relative_to(internal)
                for p in sorted((internal / dest).rglob("*"))
                if p.is_file() and not (source / p.relative_to(internal / dest)).exists()
            ]
            if (internal / dest).is_dir()
            else []
        )
        for path in extra:
            print("  solo en la app (se deja):", path)
    print(f"datos: {len(copied)} archivos copiados")
    for path in copied:
        print("  copiado:", path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "folder", type=Path, help="carpeta sonia-orquestador de la build de Windows"
    )
    parser.add_argument(
        "--sin-cambios", action="store_true", help="rehace el exe sin sustituir nada"
    )
    parser.add_argument(
        "--probar", action="store_true", help="escribe el exe al lado y no toca nada más"
    )
    args = parser.parse_args()
    exe = args.folder / "sonia-orquestador.exe"
    if not exe.is_file():
        raise SystemExit(f"no está {exe}")
    target = exe.with_suffix(".parcheado.exe") if args.probar or args.sin_cambios else exe
    patch_exe(exe, target, unchanged=args.sin_cambios)
    if not (args.probar or args.sin_cambios):
        sync_data(args.folder / "_internal")


if __name__ == "__main__":
    main()
