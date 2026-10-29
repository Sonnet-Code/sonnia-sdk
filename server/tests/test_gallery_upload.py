"""Images uploaded to the gallery from the panel: validation, ids, both folders and their way
through the panel, ``show_image`` and the ``[Gallery]`` note.

No network or key: synthetic images made here, the fake GPT-Live from ``test_live`` and the
real local panel on a free port.
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
    UPLOAD_PREFIX,
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

AT_0731 = datetime(2025, 1, 15, 7, 31)


def png(width: int = 32, height: int = 24, *, noise: bool = False) -> bytes:
    """A real PNG (gray, or noisy so it does not compress), made by hand."""

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
    """A JPEG header (SOI, APP0, SOF0, SOS and EOI): what the validation reads."""
    app0 = b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof0 = b"\xff\xc0\x00\x11\x08" + struct.pack(">HH", height, width)
    sof0 += b"\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    sos = b"\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00" + b"\x00" * 16
    return b"\xff\xd8" + app0 + sof0 + sos + b"\xff\xd9"


def heic() -> bytes:
    return b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + b"\x00" * 64


def galleries(tmp_path: Path) -> tuple[Path, Path, Gallery]:
    app = tmp_path / "app"
    uploads = tmp_path / "uploads"
    app.mkdir()
    return app, uploads, Gallery(app, uploads)


# ---------------------------------------------------------------------------
# Validation and name
# ---------------------------------------------------------------------------


def test_accepts_png_and_jpeg_by_their_content() -> None:
    assert image_info(png(32, 24)) == (".png", 32, 24)
    assert image_info(jpeg(64, 32)) == (".jpg", 64, 32)


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (heic(), "Use a JPG or PNG picture"),
        (b"GIF89a" + b"\x00" * 40, "Use a JPG or PNG picture"),
        (b"", "Use a JPG or PNG picture"),
        (b"\xff\xd8\xff\xe0" + b"\x00" * 50, "damaged"),
        (b"\x89PNG\r\n\x1a\n" + b"garbage" * 10, "damaged"),
        (b"\xff\xd8\xff\xda\x00\x08" + b"\x00" * 20, "damaged"),
        (png(8, 8), "from 16 to 4096"),
        (png(5000, 20), "from 16 to 4096"),
        (jpeg(20, 4100), "from 16 to 4096"),
        (png() + b"\x00" * (UPLOAD_MAX_BYTES + 1), "too big"),
    ],
)
def test_rejects_anything_that_is_not_a_valid_image(data: bytes, reason: str) -> None:
    with pytest.raises(GalleryError, match=reason):
        image_info(data)


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("Team Logo.png", "team-logo"),
        # Accented letters lose their accents (this sample is non-ASCII on purpose).
        ("Crème Brûlée.JPG", "creme-brulee"),
        ("IMG_4521.heic", "img-4521"),
        ("talk.on.ai", "talk-on-ai"),
        ("../../etc/passwd", "passwd"),
        ("C:\\photos\\poster.jpeg", "poster"),
        ("../", ""),
        ("", ""),
        ("   ", ""),
        ("!!!©?", ""),
        ("..png", ""),
        ("a" * 80 + ".png", "a" * 40),
    ],
)
def test_the_name_is_sanitized(name: str, slug: str) -> None:
    assert upload_slug(name) == slug


# ---------------------------------------------------------------------------
# Both folders
# ---------------------------------------------------------------------------


def test_upload_gets_a_readable_id_without_collisions(tmp_path: Path) -> None:
    app, uploads, gallery = galleries(tmp_path)
    (app / "upload-team-logo-0731-2.png").write_bytes(png())

    # The id starts with "upload-": that is how the panel knows it can be removed.
    assert UPLOAD_PREFIX == "upload-"
    assert gallery.add_upload("Team Logo.png", png(), now=AT_0731) == "upload-team-logo-0731"
    assert (uploads / "upload-team-logo-0731.png").read_bytes() == png()
    # The same name in the same minute does not overwrite the previous one, nor the app's.
    assert gallery.add_upload("team logo", jpeg(), now=AT_0731) == "upload-team-logo-0731-3"
    assert (uploads / "upload-team-logo-0731-3.jpg").read_bytes() == jpeg()
    # No half-written temporary files left in the folder.
    assert sorted(p.name for p in uploads.iterdir()) == [
        "upload-team-logo-0731-3.jpg",
        "upload-team-logo-0731.png",
    ]
    assert gallery.ids() == [
        "upload-team-logo-0731",
        "upload-team-logo-0731-2",
        "upload-team-logo-0731-3",
    ]


@pytest.mark.parametrize("name", ["../", "", "!!!"])
def test_a_name_without_letters_or_digits_is_not_uploaded(tmp_path: Path, name: str) -> None:
    _, uploads, gallery = galleries(tmp_path)
    with pytest.raises(GalleryError, match="name"):
        gallery.add_upload(name, png(), now=AT_0731)
    assert not uploads.exists() or list(uploads.iterdir()) == []


def test_without_an_upload_folder_nothing_is_uploaded(tmp_path: Path) -> None:
    gallery = Gallery(tmp_path, "")
    assert gallery.upload_dir is None
    with pytest.raises(GalleryError, match="nowhere to save"):
        gallery.add_upload("logo", png(), now=AT_0731)


def test_sees_both_folders_and_the_app_wins_on_the_same_id(tmp_path: Path) -> None:
    app, uploads, gallery = galleries(tmp_path)
    uploads.mkdir()
    (app / "offices.png").write_bytes(b"from-the-app")
    (uploads / "offices.jpg").write_bytes(b"upload-hidden")
    (uploads / "upload-poster-0731.jpg").write_bytes(b"uploaded")
    (uploads / ".upload-poster-0731-ab12.part").write_bytes(b"half-written")

    assert gallery.ids() == ["offices", "upload-poster-0731"]
    assert gallery.load("offices") == (b"from-the-app", "image/png")
    assert gallery.load("upload-poster-0731") == (b"uploaded", "image/jpeg")
    assert gallery.resolve("../app/offices") is None
    # The app folder alone, as before.
    assert Gallery(app).ids() == ["offices"]


def test_only_uploads_can_be_removed(tmp_path: Path) -> None:
    app, uploads, gallery = galleries(tmp_path)
    (app / "offices.png").write_bytes(png())
    # With the prefix but from the app: left alone.
    (app / "upload-from-the-app.png").write_bytes(png())
    image_id = gallery.add_upload("poster", png(), now=AT_0731)
    # In the upload folder but without the prefix (dropped there by hand): left alone too.
    (uploads / "by-hand.png").write_bytes(png())

    assert gallery.remove_upload("offices") is False
    assert gallery.remove_upload("upload-from-the-app") is False
    assert gallery.remove_upload("by-hand") is False
    assert gallery.remove_upload("upload-missing") is False
    assert gallery.remove_upload("upload-../app/offices") is False
    assert gallery.remove_upload("../app/offices") is False
    assert (app / "offices.png").exists() and (app / "upload-from-the-app.png").exists()
    assert gallery.remove_upload(image_id) is True
    assert gallery.ids() == ["by-hand", "offices", "upload-from-the-app"]
    assert [p.name for p in uploads.iterdir()] == ["by-hand.png"]


# ---------------------------------------------------------------------------
# show_image and the engine's watcher
# ---------------------------------------------------------------------------


async def test_show_image_finds_an_upload(tmp_path: Path) -> None:
    _, uploads, gallery = galleries(tmp_path)
    image_id = gallery.add_upload("Team Logo", jpeg(), now=AT_0731)
    avatar = FakeAvatar()
    ctx = ActionContext(
        camera=None,
        avatar=avatar,
        gallery_dir=str(tmp_path / "app"),
        gallery_upload_dir=str(uploads),
    )
    result = await show_image(ctx, {"image_id": image_id})
    assert result.text == f"Showing the image '{image_id}'."
    assert avatar.shown[0]["data"] == jpeg() and avatar.shown[0]["mime"] == "image/jpeg"


async def test_the_watcher_reports_uploads_in_the_gallery_note(tmp_path: Path) -> None:
    async with make_rig(tmp_path, gallery_watch=0.05) as rig:
        conn = await rig.conn()
        settings: Settings = rig.engine._settings
        gallery = Gallery(settings.gallery_dir, settings.gallery_upload_dir)
        image_id = gallery.add_upload("Team Logo", png(), now=AT_0731)
        await conn.wait_type("session.thinking.append")
        note = conn.of_type("session.thinking.append")[0]["content"]
        assert note.startswith(f"[Gallery] New images were added to your gallery: {image_id}.")
        assert conn.of_type("response.create") == []


def test_uploads_go_to_cache_gallery_and_not_to_assets(tmp_path: Path) -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.gallery_upload_dir == str(tmp_path / "gallery-uploads")  # conftest
    defaults = Settings.model_fields["gallery_upload_dir"].default
    assert Path(defaults).parts[-2:] == ("cache", "gallery")
    assert not Path(defaults).is_relative_to(Path(settings.assets_dir))


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------


async def test_the_panel_uploads_lists_and_removes_images(tmp_path: Path) -> None:
    (tmp_path / "gallery").mkdir(exist_ok=True)
    (tmp_path / "gallery" / "offices.png").write_bytes(png())
    async with make_panel_rig(tmp_path) as rig:
        control = rig.control
        assert "gallery_upload" in control.capabilities
        await control._refresh_gallery()
        assert control.status()["gallery"] == {"ids": ["offices"]}

        data = base64.b64encode(jpeg()).decode()
        ok, message = await control.act(
            "add_gallery_image", {"name": "Team Logo.jpg", "data_base64": data}
        )
        assert ok, message
        image_id = message.removeprefix("Image added: ")
        assert image_id.startswith("upload-team-logo-")
        assert len(image_id) == len("upload-team-logo-0000")
        # The status already includes it, without waiting for the next scan.
        assert control.status()["gallery"] == {"ids": sorted(["offices", image_id])}

        # A data: prefix is accepted too (it is what a browser file reader gives).
        ok, _ = await control.act(
            "add_gallery_image",
            {
                "name": "poster",
                "data_base64": "data:image/png;base64," + base64.b64encode(png()).decode(),
            },
        )
        assert ok

        for params, reason in [
            ({"name": "photo", "data_base64": base64.b64encode(heic()).decode()}, "JPG or PNG"),
            ({"name": "photo", "data_base64": "this is not base64!"}, "damaged"),
            ({"name": "photo", "data_base64": ""}, "Pick an image"),
            ({"name": "photo"}, "Pick an image"),
            ({"name": "photo", "data_base64": "A" * 600_000}, "too big"),
            ({"name": "../", "data_base64": data}, "name with letters"),
        ]:
            ok, message = await control.act("add_gallery_image", params)
            assert not ok and reason in message, (params.get("name"), message)

        ok, message = await control.act("remove_gallery_image", {"id": "offices"})
        assert not ok and "only the ones uploaded" in message
        ok, message = await control.act("remove_gallery_image", {"id": image_id})
        assert ok and message == f"Image removed: {image_id}"
        assert image_id not in control.status()["gallery"]["ids"]
        assert (tmp_path / "gallery" / "offices.png").exists()


async def test_the_local_panel_accepts_the_upload_and_serves_it(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig, running_panel(rig) as (host, _):
        await rig.conn()
        # A ~250 KB image (~330 KB in base64) fits in a local panel request.
        big = png(500, 500, noise=True)
        assert 240 * 1024 < len(big) < UPLOAD_MAX_BYTES
        body = {
            "action": "add_gallery_image",
            "name": "Venue Map.png",
            "data_base64": base64.b64encode(big).decode(),
        }
        async with httpx.AsyncClient(base_url=f"http://{host}") as http:
            response = await http.post("/api/action", json=body, headers={"X-Sonia-Panel": "1"})
            assert response.status_code == 200, response.text
            image_id = response.json()["message"].removeprefix("Image added: ")
            gallery = (await http.get("/api/gallery")).json()["images"]
            assert image_id.startswith(UPLOAD_PREFIX)
            assert {"id": image_id, "url": f"/api/gallery/{image_id}"} in gallery
            served = await http.get(f"/api/gallery/{image_id}")
            assert served.status_code == 200 and served.content == big
            assert served.headers["content-type"] == "image/png"
            # And Sonnia can show it from the panel.
            show = {"action": "show_image", "image_id": image_id}
            response = await http.post("/api/action", json=show, headers={"X-Sonia-Panel": "1"})
            assert response.json()["ok"] is True


def test_upload_controls_are_disabled_in_apps_that_do_not_announce_it() -> None:
    # Older apps do not know ``add_gallery_image``: the panel leaves the button disabled
    # with the notice, as with every other ``data-cap``.
    from sonia.panel.server import STATIC_DIR

    page = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    script = (STATIC_DIR / "panel.js").read_text(encoding="utf-8")
    for element in ("gallery-add-btn", "gallery-file", "gallery-upload-name", "gallery-upload-btn"):
        assert re.search(rf'id="{element}"[^>]*data-cap="gallery_upload"', page), element
    assert 'data-cap-note="gallery_upload"' in page
    assert re.search(r'id="gallery-file"[^>]*accept="image/\*"', page)
    # The remove button only on uploads, by their id prefix (the same as the orchestrator's),
    # with its capability, and the actions with their parameters.
    assert f'const UPLOAD_PREFIX = "{UPLOAD_PREFIX}";' in script
    assert "upload: id.startsWith(UPLOAD_PREFIX)" in script
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
