"""Tests del registro de acciones, las acciones integradas y la galería."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from sonia.actions.builtin import HIDE_IMAGE, LOOK, SHOW_IMAGE, build_default_registry
from sonia.actions.gallery import Gallery
from sonia.actions.registry import ActionRegistry, ValidationError, validate_arguments
from sonia.types import ActionContext, ActionResult, ActionSpec, Frame

# ---------------------------------------------------------------------------
# Dobles de prueba
# ---------------------------------------------------------------------------


def make_frame(data: bytes = b"jpeg-bytes") -> Frame:
    return Frame(data=data, mime="image/jpeg", width=4, height=3, captured_at=time.monotonic())


@dataclass
class FakeCamera:
    """Cámara falsa: devuelve los frames de la cola, o ``None``."""

    frames: list[Frame | None] = field(default_factory=list)
    calls: int = 0

    async def capture(self) -> Frame | None:
        self.calls += 1
        if not self.frames:
            return None
        return self.frames.pop(0)


@dataclass
class FakeAvatar:
    """Avatar falso: apunta las llamadas que le hacen las acciones."""

    shown: list[dict[str, Any]] = field(default_factory=list)
    hidden: int = 0

    async def show_image(
        self, *, image_id: str, source: str, mime: str, data: bytes, caption: str | None
    ) -> None:
        self.shown.append(
            {
                "image_id": image_id,
                "source": source,
                "mime": mime,
                "data": data,
                "caption": caption,
            }
        )

    async def hide_image(self) -> None:
        self.hidden += 1


def make_ctx(
    *,
    camera: FakeCamera | None = None,
    avatar: FakeAvatar | None = None,
    gallery_dir: Path | str = "/no/existe",
    last_frame: Frame | None = None,
) -> ActionContext:
    return ActionContext(
        camera=camera,
        avatar=avatar,
        gallery_dir=str(gallery_dir),
        last_frame=last_frame,
    )


async def _ping_handler(ctx: ActionContext, arguments: dict[str, Any]) -> ActionResult:
    return ActionResult(text=f"pong:{sorted(arguments.items())}")


PING = ActionSpec(
    name="ping",
    description="Acción de prueba.",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "count": {"type": "integer"},
            "ratio": {"type": "number"},
            "loud": {"type": "boolean"},
            "mode": {"type": "string", "enum": ["a", "b"]},
        },
        "required": ["text"],
    },
    handler=_ping_handler,
)


# ---------------------------------------------------------------------------
# validate_arguments
# ---------------------------------------------------------------------------


def test_validate_acepta_argumentos_correctos() -> None:
    cleaned = validate_arguments(
        PING.parameters,
        {"text": "hola", "count": 3, "ratio": 1, "loud": True, "mode": "b"},
    )
    assert cleaned == {"text": "hola", "count": 3, "ratio": 1.0, "loud": True, "mode": "b"}


def test_validate_ignora_argumentos_desconocidos() -> None:
    cleaned = validate_arguments(PING.parameters, {"text": "hola", "inventado": 42})
    assert cleaned == {"text": "hola"}


def test_validate_exige_los_requeridos() -> None:
    with pytest.raises(ValidationError, match="text"):
        validate_arguments(PING.parameters, {"count": 1})


@pytest.mark.parametrize(
    "arguments",
    [
        {"text": 3},
        {"text": "ok", "count": "tres"},
        {"text": "ok", "count": True},  # bool no es un entero JSON
        {"text": "ok", "loud": "sí"},
        {"text": "ok", "ratio": "1.5"},
        {"text": "ok", "mode": "z"},  # fuera del enum
    ],
)
def test_validate_rechaza_tipos_y_enum(arguments: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        validate_arguments(PING.parameters, arguments)


# ---------------------------------------------------------------------------
# ActionRegistry
# ---------------------------------------------------------------------------


def test_registry_register_get_names() -> None:
    registry = ActionRegistry()
    registry.register(PING)
    assert registry.names() == ["ping"]
    assert registry.get("ping") is PING
    assert registry.get("nope") is None
    assert "ping" in registry
    assert len(registry) == 1


def test_to_openai_tools_forma_exacta() -> None:
    registry = ActionRegistry()
    registry.register(PING)
    assert registry.to_openai_tools() == [
        {
            "type": "function",
            "function": {
                "name": "ping",
                "description": "Acción de prueba.",
                "parameters": PING.parameters,
            },
        }
    ]


def test_to_mcp_tools_forma_exacta() -> None:
    registry = ActionRegistry()
    registry.register(PING)
    assert registry.to_mcp_tools() == [
        {
            "name": "ping",
            "description": "Acción de prueba.",
            "inputSchema": PING.parameters,
        }
    ]


async def test_execute_llama_al_handler_con_argumentos_limpios() -> None:
    registry = ActionRegistry()
    registry.register(PING)
    result = await registry.execute("ping", {"text": "hola", "basura": 1}, make_ctx())
    assert result.text == "pong:[('text', 'hola')]"


async def test_execute_accion_desconocida_no_lanza() -> None:
    registry = ActionRegistry()
    registry.register(PING)
    result = await registry.execute("desconocida", {}, make_ctx())
    assert result.text.startswith("Error:")
    assert "desconocida" in result.text


async def test_execute_argumentos_invalidos_no_lanza() -> None:
    registry = ActionRegistry()
    registry.register(PING)
    result = await registry.execute("ping", {"count": 1}, make_ctx())
    assert result.text.startswith("Error:")
    assert "text" in result.text


async def test_execute_captura_excepciones_del_handler() -> None:
    async def explota(ctx: ActionContext, arguments: dict[str, Any]) -> ActionResult:
        raise RuntimeError("boom")

    registry = ActionRegistry()
    registry.register(
        ActionSpec(
            name="explota",
            description="",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=explota,
        )
    )
    result = await registry.execute("explota", None, make_ctx())
    assert result.text.startswith("Error:")
    assert "boom" in result.text


def test_build_default_registry() -> None:
    registry = build_default_registry()
    assert registry.names() == ["look", "show_image", "hide_image"]
    sin_look = build_default_registry(include_look=False)
    assert sin_look.names() == ["show_image", "hide_image"]
    assert registry.get("look") is LOOK
    assert registry.get("show_image") is SHOW_IMAGE
    assert registry.get("hide_image") is HIDE_IMAGE


# ---------------------------------------------------------------------------
# Galería
# ---------------------------------------------------------------------------


@pytest.fixture
def gallery_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "gallery"
    directory.mkdir()
    (directory / "logo-sonnet.png").write_bytes(b"\x89PNG-fake")
    (directory / "diagrama.jpg").write_bytes(b"\xff\xd8-fake")
    (directory / "notas.txt").write_text("no es una imagen")
    (tmp_path / "secreto.png").write_bytes(b"secreto")
    return directory


def test_gallery_ids_ordenados_y_solo_imagenes(gallery_dir: Path) -> None:
    assert Gallery(gallery_dir).ids() == ["diagrama", "logo-sonnet"]


def test_gallery_ids_directorio_inexistente(tmp_path: Path) -> None:
    assert Gallery(tmp_path / "nada").ids() == []


def test_gallery_load_devuelve_bytes_y_mime(gallery_dir: Path) -> None:
    gallery = Gallery(gallery_dir)
    assert gallery.load("logo-sonnet") == (b"\x89PNG-fake", "image/png")
    assert gallery.load("diagrama") == (b"\xff\xd8-fake", "image/jpeg")


def test_gallery_load_id_inexistente(gallery_dir: Path) -> None:
    assert Gallery(gallery_dir).load("no-existe") is None
    assert Gallery(gallery_dir).load("notas") is None


@pytest.mark.parametrize(
    "image_id",
    [
        "../secreto",
        "..\\secreto",
        "subdir/logo-sonnet",
        "/etc/passwd",
        "..",
        ".",
        "",
        "   ",
    ],
)
def test_gallery_rechaza_path_traversal(gallery_dir: Path, image_id: str) -> None:
    assert Gallery(gallery_dir).load(image_id) is None
    assert Gallery(gallery_dir).resolve(image_id) is None


def test_gallery_symlink_fuera_del_directorio(gallery_dir: Path, tmp_path: Path) -> None:
    (gallery_dir / "fuga.png").symlink_to(tmp_path / "secreto.png")
    gallery = Gallery(gallery_dir)
    assert gallery.load("fuga") is None
    # Tampoco se le anuncia al modelo un id que no va a poder cargar.
    assert "fuga" not in gallery.ids()


def test_gallery_ignora_webp_porque_unity_no_lo_decodifica(gallery_dir: Path) -> None:
    """Unity usa ``ImageConversion.LoadImage``: solo PNG y JPEG.

    Anunciar un ``.webp`` haría que Sonia dijese en voz alta que muestra una
    imagen que en la pantalla no aparece nunca.
    """
    (gallery_dir / "moderna.webp").write_bytes(b"RIFF----WEBP")
    gallery = Gallery(gallery_dir)
    assert "moderna" not in gallery.ids()
    assert gallery.load("moderna") is None


def test_gallery_acepta_extensiones_en_mayusculas(gallery_dir: Path) -> None:
    (gallery_dir / "CARTEL.PNG").write_bytes(b"\x89PNG-mayus")
    gallery = Gallery(gallery_dir)
    assert "CARTEL" in gallery.ids()
    assert gallery.load("CARTEL") == (b"\x89PNG-mayus", "image/png")


# ---------------------------------------------------------------------------
# look
# ---------------------------------------------------------------------------


async def test_look_sin_camara() -> None:
    registry = build_default_registry()
    result = await registry.execute("look", {}, make_ctx())
    assert result.text == "No hay cámara disponible."
    assert result.image is None


async def test_look_devuelve_la_imagen_y_la_guarda_en_el_contexto() -> None:
    frame = make_frame()
    ctx = make_ctx(camera=FakeCamera(frames=[frame]))
    result = await build_default_registry().execute("look", {}, ctx)
    assert result.text == "Captura tomada."
    assert result.image is frame
    assert ctx.last_frame is frame


async def test_look_cuando_la_camara_no_devuelve_frame() -> None:
    ctx = make_ctx(camera=FakeCamera(frames=[None]))
    result = await build_default_registry().execute("look", {}, ctx)
    assert result.image is None
    assert "No pude" in result.text


# ---------------------------------------------------------------------------
# show_image / hide_image
# ---------------------------------------------------------------------------


async def test_show_image_desde_la_galeria(gallery_dir: Path) -> None:
    avatar = FakeAvatar()
    ctx = make_ctx(avatar=avatar, gallery_dir=gallery_dir)
    result = await build_default_registry().execute(
        "show_image", {"image_id": "logo-sonnet", "caption": "Sonnet Code"}, ctx
    )
    assert result.text == "Mostrando la imagen 'logo-sonnet'."
    assert avatar.shown == [
        {
            "image_id": "logo-sonnet",
            "source": "gallery",
            "mime": "image/png",
            "data": b"\x89PNG-fake",
            "caption": "Sonnet Code",
        }
    ]


async def test_show_image_sin_caption(gallery_dir: Path) -> None:
    avatar = FakeAvatar()
    ctx = make_ctx(avatar=avatar, gallery_dir=gallery_dir)
    await build_default_registry().execute("show_image", {"image_id": "diagrama"}, ctx)
    assert avatar.shown[0]["caption"] is None


async def test_show_image_id_inexistente(gallery_dir: Path) -> None:
    avatar = FakeAvatar()
    ctx = make_ctx(avatar=avatar, gallery_dir=gallery_dir)
    result = await build_default_registry().execute("show_image", {"image_id": "nada"}, ctx)
    assert "No existe la imagen 'nada'" in result.text
    assert "logo-sonnet" in result.text
    assert avatar.shown == []


async def test_show_image_sin_avatar(gallery_dir: Path) -> None:
    ctx = make_ctx(gallery_dir=gallery_dir)
    result = await build_default_registry().execute("show_image", {"image_id": "diagrama"}, ctx)
    assert result.text == "El avatar no está conectado."


async def test_show_image_camera_usa_last_frame() -> None:
    frame = make_frame(b"foto")
    avatar = FakeAvatar()
    camera = FakeCamera()
    ctx = make_ctx(camera=camera, avatar=avatar, last_frame=frame)
    result = await build_default_registry().execute("show_image", {"image_id": "camera"}, ctx)
    assert "cámara" in result.text
    assert camera.calls == 0  # ya había una captura: no se pide otra
    assert avatar.shown[0]["source"] == "camera"
    assert avatar.shown[0]["data"] == b"foto"


async def test_show_image_camera_captura_si_no_hay_last_frame() -> None:
    frame = make_frame(b"nueva")
    avatar = FakeAvatar()
    camera = FakeCamera(frames=[frame])
    ctx = make_ctx(camera=camera, avatar=avatar)
    await build_default_registry().execute("show_image", {"image_id": "camera"}, ctx)
    assert camera.calls == 1
    assert ctx.last_frame is frame
    assert avatar.shown[0]["data"] == b"nueva"


async def test_show_image_camera_sin_ninguna_captura() -> None:
    avatar = FakeAvatar()
    ctx = make_ctx(avatar=avatar)
    result = await build_default_registry().execute("show_image", {"image_id": "camera"}, ctx)
    assert "No hay ninguna captura" in result.text
    assert avatar.shown == []


async def test_show_image_sin_image_id_es_error() -> None:
    ctx = make_ctx(avatar=FakeAvatar())
    result = await build_default_registry().execute("show_image", {}, ctx)
    assert result.text.startswith("Error:")


async def test_hide_image() -> None:
    avatar = FakeAvatar()
    ctx = make_ctx(avatar=avatar)
    result = await build_default_registry().execute("hide_image", {}, ctx)
    assert avatar.hidden == 1
    assert "retirado" in result.text


async def test_hide_image_sin_avatar() -> None:
    result = await build_default_registry().execute("hide_image", {}, make_ctx())
    assert result.text == "El avatar no está conectado."
