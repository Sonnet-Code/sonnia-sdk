"""Imágenes subidas a la galería desde el panel: validación, ids, las dos carpetas y su paso
por el panel, ``show_image`` y la nota ``[Galería]``.

Sin red ni clave: imágenes sintéticas hechas aquí, GPT-Live falso de ``test_live`` y el
panel local de verdad en un puerto libre.
"""

from __future__ import annotations

import base64
import random
import re
import struct
import zlib
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from sonia.actions.builtin import show_image
from sonia.actions.gallery import (
    UPLOAD_MAX_BYTES,
    Gallery,
    GalleryError,
    image_info,
    upload_slug,
)
from sonia.config import Settings
from sonia.types import ActionContext
from tests.test_actions import FakeAvatar
from tests.test_live import make_rig
from tests.test_panel import make_panel_rig, running_panel

LAS_0731 = datetime(2026, 10, 10, 7, 31)


def png(width: int = 32, height: int = 24, *, noise: bool = False) -> bytes:
    """Un PNG de verdad (gris, o con ruido para que no se comprima), hecho a mano."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    rng = random.Random(7)
    rows = b"".join(
        b"\x00" + (rng.randbytes(width) if noise else b"\x80" * width) for _ in range(height)
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def jpeg(width: int = 64, height: int = 32) -> bytes:
    """La cabecera de un JPEG (SOI, APP0, SOF0, SOS y EOI): lo que lee la validación."""
    app0 = b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof0 = b"\xff\xc0\x00\x11\x08" + struct.pack(">HH", height, width)
    sof0 += b"\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    sos = b"\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00" + b"\x00" * 16
    return b"\xff\xd8" + app0 + sof0 + sos + b"\xff\xd9"


def heic() -> bytes:
    return b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + b"\x00" * 64


def galleries(tmp_path: Path) -> tuple[Path, Path, Gallery]:
    app = tmp_path / "app"
    uploads = tmp_path / "subidas"
    app.mkdir()
    return app, uploads, Gallery(app, uploads)


# ---------------------------------------------------------------------------
# Validación y nombre
# ---------------------------------------------------------------------------


def test_acepta_png_y_jpeg_por_su_contenido() -> None:
    assert image_info(png(32, 24)) == (".png", 32, 24)
    assert image_info(jpeg(64, 32)) == (".jpg", 64, 32)


@pytest.mark.parametrize(
    ("data", "motivo"),
    [
        (heic(), "Usa una foto JPG o PNG"),
        (b"GIF89a" + b"\x00" * 40, "Usa una foto JPG o PNG"),
        (b"", "Usa una foto JPG o PNG"),
        (b"\xff\xd8\xff\xe0" + b"\x00" * 50, "dañada"),
        (b"\x89PNG\r\n\x1a\n" + b"basura" * 10, "dañada"),
        (b"\xff\xd8\xff\xda\x00\x08" + b"\x00" * 20, "dañada"),
        (png(8, 8), "de 16 a 4096"),
        (png(5000, 20), "de 16 a 4096"),
        (jpeg(20, 4100), "de 16 a 4096"),
        (png() + b"\x00" * (UPLOAD_MAX_BYTES + 1), "pesa demasiado"),
    ],
)
def test_rechaza_lo_que_no_es_una_imagen_valida(data: bytes, motivo: str) -> None:
    with pytest.raises(GalleryError, match=motivo):
        image_info(data)


@pytest.mark.parametrize(
    ("nombre", "slug"),
    [
        ("Logo GDG.png", "logo-gdg"),
        ("Café Ñandú.JPG", "cafe-nandu"),
        ("IMG_4521.heic", "img-4521"),
        ("charla.de.ia", "charla-de-ia"),
        ("../../etc/passwd", "passwd"),
        ("C:\\fotos\\stand.jpeg", "stand"),
        ("../", ""),
        ("", ""),
        ("   ", ""),
        ("!!!¿?", ""),
        ("..png", ""),
        ("a" * 80 + ".png", "a" * 40),
    ],
)
def test_el_nombre_se_sanea(nombre: str, slug: str) -> None:
    assert upload_slug(nombre) == slug


# ---------------------------------------------------------------------------
# Las dos carpetas
# ---------------------------------------------------------------------------


def test_sube_con_id_legible_y_sin_colisiones(tmp_path: Path) -> None:
    app, uploads, gallery = galleries(tmp_path)
    (app / "logo-gdg-0731-2.png").write_bytes(png())

    assert gallery.add_upload("Logo GDG.png", png(), now=LAS_0731) == "logo-gdg-0731"
    assert (uploads / "logo-gdg-0731.png").read_bytes() == png()
    # El mismo nombre en el mismo minuto no pisa la anterior; tampoco la de la app.
    assert gallery.add_upload("logo gdg", jpeg(), now=LAS_0731) == "logo-gdg-0731-3"
    assert (uploads / "logo-gdg-0731-3.jpg").read_bytes() == jpeg()
    assert gallery.uploads() == ["logo-gdg-0731", "logo-gdg-0731-3"]
    # Sin temporales a medias en la carpeta.
    assert sorted(p.name for p in uploads.iterdir()) == ["logo-gdg-0731-3.jpg", "logo-gdg-0731.png"]


@pytest.mark.parametrize("nombre", ["../", "", "!!!"])
def test_un_nombre_sin_letras_ni_numeros_no_se_sube(tmp_path: Path, nombre: str) -> None:
    _, uploads, gallery = galleries(tmp_path)
    with pytest.raises(GalleryError, match="nombre"):
        gallery.add_upload(nombre, png(), now=LAS_0731)
    assert not uploads.exists() or list(uploads.iterdir()) == []


def test_sin_carpeta_de_subidas_no_se_sube(tmp_path: Path) -> None:
    gallery = Gallery(tmp_path, "")
    assert gallery.upload_dir is None
    with pytest.raises(GalleryError, match="dónde guardar"):
        gallery.add_upload("logo", png(), now=LAS_0731)


def test_ve_las_dos_carpetas_y_con_el_mismo_id_gana_la_app(tmp_path: Path) -> None:
    app, uploads, gallery = galleries(tmp_path)
    uploads.mkdir()
    (app / "oficinas.png").write_bytes(b"de-la-app")
    (uploads / "oficinas.jpg").write_bytes(b"subida-tapada")
    (uploads / "stand-0731.jpg").write_bytes(b"subida")
    (uploads / ".stand-0731-ab12.part").write_bytes(b"a-medias")

    assert gallery.ids() == ["oficinas", "stand-0731"]
    assert gallery.uploads() == ["stand-0731"]
    assert gallery.load("oficinas") == (b"de-la-app", "image/png")
    assert gallery.load("stand-0731") == (b"subida", "image/jpeg")
    assert gallery.resolve("../app/oficinas") is None
    # La de la app sola, como antes.
    assert Gallery(app).ids() == ["oficinas"]


def test_solo_se_quitan_las_subidas(tmp_path: Path) -> None:
    app, uploads, gallery = galleries(tmp_path)
    (app / "oficinas.png").write_bytes(png())
    image_id = gallery.add_upload("stand", png(), now=LAS_0731)

    assert gallery.remove_upload("oficinas") is False
    assert (app / "oficinas.png").exists()
    assert gallery.remove_upload("no-existe") is False
    assert gallery.remove_upload("../app/oficinas") is False
    assert gallery.remove_upload(image_id) is True
    assert gallery.ids() == ["oficinas"]
    assert list(uploads.iterdir()) == []


# ---------------------------------------------------------------------------
# show_image y el vigilante del motor
# ---------------------------------------------------------------------------


async def test_show_image_encuentra_una_subida(tmp_path: Path) -> None:
    _, uploads, gallery = galleries(tmp_path)
    image_id = gallery.add_upload("Logo GDG", jpeg(), now=LAS_0731)
    avatar = FakeAvatar()
    ctx = ActionContext(
        camera=None,
        avatar=avatar,
        gallery_dir=str(tmp_path / "app"),
        gallery_upload_dir=str(uploads),
    )
    result = await show_image(ctx, {"image_id": image_id})
    assert result.text == f"Mostrando la imagen '{image_id}'."
    assert avatar.shown[0]["data"] == jpeg() and avatar.shown[0]["mime"] == "image/jpeg"


async def test_el_vigilante_cuenta_las_subidas_en_la_nota_de_galeria(tmp_path: Path) -> None:
    async with make_rig(tmp_path, gallery_watch=0.05) as rig:
        conn = await rig.conn()
        settings: Settings = rig.engine._settings
        gallery = Gallery(settings.gallery_dir, settings.gallery_upload_dir)
        image_id = gallery.add_upload("Logo GDG", png(), now=LAS_0731)
        await conn.wait_type("session.thinking.append")
        note = conn.of_type("session.thinking.append")[0]["content"]
        assert note.startswith(f"[Galería] El equipo ha añadido a tu galería: {image_id}.")
        assert conn.of_type("response.create") == []


def test_las_subidas_van_a_cache_gallery_y_no_a_assets(tmp_path: Path) -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.gallery_upload_dir == str(tmp_path / "gallery-uploads")  # conftest
    defaults = Settings.model_fields["gallery_upload_dir"].default
    assert Path(defaults).parts[-2:] == ("cache", "gallery")
    assert not Path(defaults).is_relative_to(Path(settings.assets_dir))


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------


async def test_el_panel_sube_lista_y_quita_imagenes(tmp_path: Path) -> None:
    (tmp_path / "gallery").mkdir(exist_ok=True)
    (tmp_path / "gallery" / "oficinas.png").write_bytes(png())
    async with make_panel_rig(tmp_path) as rig:
        control = rig.control
        assert "gallery_upload" in control.capabilities
        await control._refresh_gallery()
        assert control.status()["gallery"] == {"ids": ["oficinas"], "uploads": []}

        data = base64.b64encode(jpeg()).decode()
        ok, message = await control.act(
            "add_gallery_image", {"name": "Logo GDG.jpg", "data_base64": data}
        )
        assert ok, message
        image_id = message.removeprefix("Imagen añadida: ")
        assert image_id.startswith("logo-gdg-") and len(image_id) == len("logo-gdg-0000")
        # El estado ya la trae, marcada como subida (sin esperar al siguiente repaso).
        listing = control.status()["gallery"]
        assert listing == {"ids": sorted(["oficinas", image_id]), "uploads": [image_id]}

        # Con prefijo data: también vale (es lo que da un lector del navegador).
        ok, _ = await control.act(
            "add_gallery_image",
            {
                "name": "stand",
                "data_base64": "data:image/png;base64," + base64.b64encode(png()).decode(),
            },
        )
        assert ok

        for params, motivo in [
            ({"name": "foto", "data_base64": base64.b64encode(heic()).decode()}, "JPG o PNG"),
            ({"name": "foto", "data_base64": "esto no es base64!"}, "dañada"),
            ({"name": "foto", "data_base64": ""}, "Elige una imagen"),
            ({"name": "foto"}, "Elige una imagen"),
            ({"name": "foto", "data_base64": "A" * 600_000}, "pesa demasiado"),
            ({"name": "../", "data_base64": data}, "nombre"),
        ]:
            ok, message = await control.act("add_gallery_image", params)
            assert not ok and motivo in message, (params.get("name"), message)

        ok, message = await control.act("remove_gallery_image", {"id": "oficinas"})
        assert not ok and "solo se quitan" in message
        ok, message = await control.act("remove_gallery_image", {"id": image_id})
        assert ok and message == f"Imagen quitada: {image_id}"
        assert image_id not in control.status()["gallery"]["ids"]
        assert (tmp_path / "gallery" / "oficinas.png").exists()


async def test_el_panel_local_acepta_la_subida_y_la_sirve(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig, running_panel(rig) as (host, _):
        await rig.conn()
        # Una imagen de ~250 KB (~330 KB en base64) cabe en la petición del panel local.
        big = png(500, 500, noise=True)
        assert 240 * 1024 < len(big) < UPLOAD_MAX_BYTES
        body = {
            "action": "add_gallery_image",
            "name": "Mapa del stand.png",
            "data_base64": base64.b64encode(big).decode(),
        }
        async with httpx.AsyncClient(base_url=f"http://{host}") as http:
            response = await http.post("/api/action", json=body, headers={"X-Sonia-Panel": "1"})
            assert response.status_code == 200, response.text
            image_id = response.json()["message"].removeprefix("Imagen añadida: ")
            gallery = (await http.get("/api/gallery")).json()["images"]
            assert {"id": image_id, "url": f"/api/gallery/{image_id}", "upload": True} in gallery
            served = await http.get(f"/api/gallery/{image_id}")
            assert served.status_code == 200 and served.content == big
            assert served.headers["content-type"] == "image/png"
            # Y Sonia la puede enseñar desde el panel.
            show = {"action": "show_image", "image_id": image_id}
            response = await http.post("/api/action", json=show, headers={"X-Sonia-Panel": "1"})
            assert response.json()["ok"] is True


def test_los_controles_de_subir_se_apagan_en_las_apps_que_no_lo_anuncian() -> None:
    # Las Sonnias ya instaladas no conocen ``add_gallery_image``: su panel deja el botón
    # desactivado con el aviso, como con los demás ``data-cap``.
    from sonia.panel.server import STATIC_DIR

    page = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    script = (STATIC_DIR / "panel.js").read_text(encoding="utf-8")
    for element in ("gallery-add-btn", "gallery-file", "gallery-upload-name", "gallery-upload-btn"):
        assert re.search(rf'id="{element}"[^>]*data-cap="gallery_upload"', page), element
    assert 'data-cap-note="gallery_upload"' in page
    assert re.search(r'id="gallery-file"[^>]*accept="image/\*"', page)
    # La «×» solo en las subidas, con su capacidad, y las acciones con sus parámetros.
    assert '"data-cap": "gallery_upload"' in script
    assert 'sendAction("remove_gallery_image", { id }' in script
    assert '"add_gallery_image",\n      { name, data_base64: data }' in script
    for element in (
        "gallery-upload",
        "gallery-upload-preview",
        "gallery-upload-cancel",
        "gallery-upload-state",
    ):
        assert f'id="{element}"' in page, element
