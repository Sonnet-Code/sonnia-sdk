"""Tests for the action registry, the built-in actions and the gallery."""

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
# Test doubles
# ---------------------------------------------------------------------------


def make_frame(data: bytes = b"jpeg-bytes") -> Frame:
    return Frame(data=data, mime="image/jpeg", width=4, height=3, captured_at=time.monotonic())


@dataclass
class FakeCamera:
    """Fake camera: returns the queued frames, or ``None``."""

    frames: list[Frame | None] = field(default_factory=list)
    calls: int = 0

    async def capture(self) -> Frame | None:
        self.calls += 1
        if not self.frames:
            return None
        return self.frames.pop(0)


@dataclass
class FakeAvatar:
    """Fake avatar: records the calls the actions make to it."""

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
    gallery_dir: Path | str = "/does/not/exist",
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
    description="Test action.",
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


def test_validate_accepts_valid_arguments() -> None:
    cleaned = validate_arguments(
        PING.parameters,
        {"text": "hello", "count": 3, "ratio": 1, "loud": True, "mode": "b"},
    )
    assert cleaned == {"text": "hello", "count": 3, "ratio": 1.0, "loud": True, "mode": "b"}


def test_validate_ignores_unknown_arguments() -> None:
    cleaned = validate_arguments(PING.parameters, {"text": "hello", "made_up": 42})
    assert cleaned == {"text": "hello"}


def test_validate_requires_required_arguments() -> None:
    with pytest.raises(ValidationError, match="text"):
        validate_arguments(PING.parameters, {"count": 1})


@pytest.mark.parametrize(
    "arguments",
    [
        {"text": 3},
        {"text": "ok", "count": "three"},
        {"text": "ok", "count": True},  # bool is not a JSON integer
        {"text": "ok", "loud": "yes"},
        {"text": "ok", "ratio": "1.5"},
        {"text": "ok", "mode": "z"},  # outside the enum
    ],
)
def test_validate_rejects_wrong_types_and_enum(arguments: dict[str, Any]) -> None:
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


def test_to_responses_tools_exact_shape() -> None:
    registry = ActionRegistry()
    registry.register(PING)
    assert registry.to_responses_tools() == [
        {
            "type": "function",
            "name": "ping",
            "description": "Test action.",
            "parameters": PING.parameters,
        }
    ]


async def test_execute_calls_handler_with_cleaned_arguments() -> None:
    registry = ActionRegistry()
    registry.register(PING)
    result = await registry.execute("ping", {"text": "hello", "junk": 1}, make_ctx())
    assert result.text == "pong:[('text', 'hello')]"


async def test_execute_unknown_action_does_not_raise() -> None:
    registry = ActionRegistry()
    registry.register(PING)
    result = await registry.execute("unknown", {}, make_ctx())
    assert result.text.startswith("Error:")
    assert "unknown" in result.text
    assert "does not exist" in result.text
    assert "Available: ping" in result.text


async def test_execute_invalid_arguments_do_not_raise() -> None:
    registry = ActionRegistry()
    registry.register(PING)
    result = await registry.execute("ping", {"count": 1}, make_ctx())
    assert result.text.startswith("Error:")
    assert "text" in result.text


async def test_execute_catches_handler_exceptions() -> None:
    async def explode(ctx: ActionContext, arguments: dict[str, Any]) -> ActionResult:
        raise RuntimeError("boom")

    registry = ActionRegistry()
    registry.register(
        ActionSpec(
            name="explode",
            description="",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=explode,
        )
    )
    result = await registry.execute("explode", None, make_ctx())
    assert result.text.startswith("Error:")
    assert "boom" in result.text


def test_build_default_registry() -> None:
    registry = build_default_registry()
    assert registry.names() == ["look", "show_image", "hide_image", "play_animation"]
    without_look = build_default_registry(include_look=False)
    assert without_look.names() == ["show_image", "hide_image", "play_animation"]
    assert registry.get("look") is LOOK
    assert registry.get("show_image") is SHOW_IMAGE
    assert registry.get("hide_image") is HIDE_IMAGE


# ---------------------------------------------------------------------------
# Gallery
# ---------------------------------------------------------------------------


@pytest.fixture
def gallery_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "gallery"
    directory.mkdir()
    (directory / "logo-team.png").write_bytes(b"\x89PNG-fake")
    (directory / "diagram.jpg").write_bytes(b"\xff\xd8-fake")
    (directory / "notes.txt").write_text("not an image")
    (tmp_path / "secret.png").write_bytes(b"secret")
    return directory


def test_gallery_ids_sorted_and_images_only(gallery_dir: Path) -> None:
    assert Gallery(gallery_dir).ids() == ["diagram", "logo-team"]


def test_gallery_ids_missing_directory(tmp_path: Path) -> None:
    assert Gallery(tmp_path / "nothing").ids() == []


def test_gallery_load_returns_bytes_and_mime(gallery_dir: Path) -> None:
    gallery = Gallery(gallery_dir)
    assert gallery.load("logo-team") == (b"\x89PNG-fake", "image/png")
    assert gallery.load("diagram") == (b"\xff\xd8-fake", "image/jpeg")


def test_gallery_load_missing_id(gallery_dir: Path) -> None:
    assert Gallery(gallery_dir).load("missing") is None
    assert Gallery(gallery_dir).load("notes") is None


@pytest.mark.parametrize(
    "image_id",
    [
        "../secret",
        "..\\secret",
        "subdir/logo-team",
        "/etc/passwd",
        "..",
        ".",
        "",
        "   ",
    ],
)
def test_gallery_rejects_path_traversal(gallery_dir: Path, image_id: str) -> None:
    assert Gallery(gallery_dir).load(image_id) is None
    assert Gallery(gallery_dir).resolve(image_id) is None


def test_gallery_symlink_outside_the_directory(gallery_dir: Path, tmp_path: Path) -> None:
    (gallery_dir / "leak.png").symlink_to(tmp_path / "secret.png")
    gallery = Gallery(gallery_dir)
    assert gallery.load("leak") is None
    # Nor is an id that cannot be loaded announced to the model.
    assert "leak" not in gallery.ids()


def test_gallery_ignores_webp_because_unity_cannot_decode_it(gallery_dir: Path) -> None:
    """Unity uses ``ImageConversion.LoadImage``: PNG and JPEG only.

    Announcing a ``.webp`` would make Sonnia say out loud that she is showing an
    image that never shows up on screen.
    """
    (gallery_dir / "modern.webp").write_bytes(b"RIFF----WEBP")
    gallery = Gallery(gallery_dir)
    assert "modern" not in gallery.ids()
    assert gallery.load("modern") is None


def test_gallery_accepts_uppercase_extensions(gallery_dir: Path) -> None:
    (gallery_dir / "POSTER.PNG").write_bytes(b"\x89PNG-upper")
    gallery = Gallery(gallery_dir)
    assert "POSTER" in gallery.ids()
    assert gallery.load("POSTER") == (b"\x89PNG-upper", "image/png")


# ---------------------------------------------------------------------------
# look
# ---------------------------------------------------------------------------


async def test_look_without_camera() -> None:
    registry = build_default_registry()
    result = await registry.execute("look", {}, make_ctx())
    assert result.text == "There is no camera available."
    assert result.image is None


async def test_look_returns_the_image_and_stores_it_in_the_context() -> None:
    frame = make_frame()
    ctx = make_ctx(camera=FakeCamera(frames=[frame]))
    result = await build_default_registry().execute("look", {}, ctx)
    assert result.text == "Snapshot taken."
    assert result.image is frame
    assert ctx.last_frame is frame


async def test_look_when_the_camera_returns_no_frame() -> None:
    ctx = make_ctx(camera=FakeCamera(frames=[None]))
    result = await build_default_registry().execute("look", {}, ctx)
    assert result.image is None
    assert "could not" in result.text


# ---------------------------------------------------------------------------
# show_image / hide_image
# ---------------------------------------------------------------------------


async def test_show_image_from_the_gallery(gallery_dir: Path) -> None:
    avatar = FakeAvatar()
    ctx = make_ctx(avatar=avatar, gallery_dir=gallery_dir)
    result = await build_default_registry().execute(
        "show_image", {"image_id": "logo-team", "caption": "Our team"}, ctx
    )
    assert result.text == "Showing the image 'logo-team'."
    assert avatar.shown == [
        {
            "image_id": "logo-team",
            "source": "gallery",
            "mime": "image/png",
            "data": b"\x89PNG-fake",
            "caption": "Our team",
        }
    ]


async def test_show_image_without_caption(gallery_dir: Path) -> None:
    avatar = FakeAvatar()
    ctx = make_ctx(avatar=avatar, gallery_dir=gallery_dir)
    await build_default_registry().execute("show_image", {"image_id": "diagram"}, ctx)
    assert avatar.shown[0]["caption"] is None


async def test_show_image_missing_id(gallery_dir: Path) -> None:
    avatar = FakeAvatar()
    ctx = make_ctx(avatar=avatar, gallery_dir=gallery_dir)
    result = await build_default_registry().execute("show_image", {"image_id": "missing"}, ctx)
    assert "There is no image 'missing'" in result.text
    assert "logo-team" in result.text
    assert avatar.shown == []


async def test_show_image_without_avatar(gallery_dir: Path) -> None:
    ctx = make_ctx(gallery_dir=gallery_dir)
    result = await build_default_registry().execute("show_image", {"image_id": "diagram"}, ctx)
    assert result.text == "The avatar is not connected."


async def test_show_image_never_shows_the_camera(gallery_dir: Path) -> None:
    """Camera photos never go on screen: ``camera`` is just another id that does not exist."""
    avatar = FakeAvatar()
    camera = FakeCamera(frames=[make_frame(b"photo")])
    ctx = make_ctx(
        camera=camera, avatar=avatar, gallery_dir=gallery_dir, last_frame=make_frame(b"old")
    )
    result = await build_default_registry().execute("show_image", {"image_id": "camera"}, ctx)
    assert "There is no image 'camera'" in result.text
    assert camera.calls == 0
    assert avatar.shown == []


async def test_show_image_with_trivia_on_screen_shows_nothing(
    gallery_dir: Path,
) -> None:
    """The top strip belongs to the trivia: the image would not be seen and Sonnia would
    point at nothing. The answer tells her to explain it with words."""
    from types import SimpleNamespace

    registry = build_default_registry()
    avatar = FakeAvatar()
    ctx = ActionContext(
        camera=None,
        avatar=avatar,
        gallery_dir=str(gallery_dir),
        extra={"trivia": SimpleNamespace(active=True)},
    )
    result = await registry.execute("show_image", {"image_id": "diagram"}, ctx)
    assert avatar.shown == [] and "trivia" in result.text and "with words" in result.text
    # With nothing on screen, it is shown.
    ctx = ActionContext(
        camera=None,
        avatar=avatar,
        gallery_dir=str(gallery_dir),
        extra={"trivia": None},
    )
    result = await registry.execute("show_image", {"image_id": "diagram"}, ctx)
    assert len(avatar.shown) == 1 and result.text == "Showing the image 'diagram'."


async def test_show_image_without_image_id_is_an_error() -> None:
    ctx = make_ctx(avatar=FakeAvatar())
    result = await build_default_registry().execute("show_image", {}, ctx)
    assert result.text.startswith("Error:")


async def test_hide_image() -> None:
    avatar = FakeAvatar()
    ctx = make_ctx(avatar=avatar)
    result = await build_default_registry().execute("hide_image", {}, ctx)
    assert avatar.hidden == 1
    assert "hidden" in result.text


async def test_hide_image_without_avatar() -> None:
    result = await build_default_registry().execute("hide_image", {}, make_ctx())
    assert result.text == "The avatar is not connected."
