"""Montaje de la visión de los juegos (``build_game_vision``) sin cámara ni modelos de verdad."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import pytest

from sonia.config import Settings
from sonia.vision import models as models_module
from sonia.vision.camera import OpenCVCamera, UnityCamera
from sonia.vision.games import NoJudge, build_game_vision
from sonia.vision.hands import MediaPipeHandDetector
from sonia.vision.judge import ModelJudge
from sonia.vision.poses import YoloPoseDetector
from sonia.vision.stream import LivePreview, OpenCVCameraStream


@pytest.fixture(autouse=True)
def _sin_modelos_del_equipo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Nunca los modelos de verdad de ``cache/games/modelos``: una carpeta vacía."""
    monkeypatch.setattr(models_module, "games_models_dir", lambda settings=None: tmp_path)


def make_settings(tmp_path: Path, source: str = "opencv") -> Settings:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    settings.vision.source = source  # type: ignore[assignment]
    games = getattr(settings, "games", None)
    if games is not None:
        games.models_dir = str(tmp_path / "modelos")
    return settings


async def nothing(_: Any) -> None:
    return None


def build(settings: Settings, camera: Any, **options: Any) -> Any:
    return build_game_vision(
        settings=settings,
        camera=camera,
        send_json=nothing,
        send_bytes=nothing,
        preview_supported=lambda: True,
        vision_llm=options.pop("vision_llm", None),
        download_models=options.pop("download_models", False),
    )


async def test_con_la_camara_usb_monta_la_vision_de_verdad(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = make_settings(tmp_path)
    camera = OpenCVCamera(settings.vision)
    vision = build(settings, camera)
    assert isinstance(vision.stream, OpenCVCameraStream)
    assert isinstance(vision.preview, LivePreview)
    assert isinstance(vision.poses, YoloPoseDetector)
    assert isinstance(vision.hands, MediaPipeHandDetector)
    # Sin modelos en la carpeta, ni poses ni manos; sin modelo de visión, sin juez.
    assert not vision.poses.available
    assert not vision.hands.available
    assert isinstance(vision.judge, NoJudge)
    assert not vision.stream.active
    await vision.close()


async def test_con_el_modelo_de_vision_hay_juez(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    vision = build(settings, OpenCVCamera(settings.vision), vision_llm=object())
    assert isinstance(vision.judge, ModelJudge)
    assert vision.judge.available
    settings.llm.supports_vision = False
    vision = build(settings, OpenCVCamera(settings.vision), vision_llm=object())
    assert isinstance(vision.judge, NoJudge)


@pytest.mark.parametrize("source", ["unity", "obs", "screen", "none"])
async def test_sin_camara_usb_no_hay_vision_de_juegos(tmp_path: Path, source: str) -> None:
    settings = make_settings(tmp_path, source)
    vision = build(settings, UnityCamera(), vision_llm=object())
    assert not vision.poses.available
    assert not vision.hands.available
    assert not vision.judge.available
    assert await vision.stream.acquire("prueba") is False


async def test_con_otra_camara_aunque_diga_opencv_tampoco(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    vision = build(settings, None)
    assert await vision.preview.start("prueba") is False


async def test_si_faltan_los_modelos_se_bajan_en_un_hilo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[Path, tuple[str, ...]]] = []
    done = threading.Event()

    def fake_download(folder: Path, models: Any = None, **_: Any) -> list[str]:
        calls.append((folder, tuple(model.name for model in models)))
        done.set()
        return []

    monkeypatch.setattr(models_module, "download_game_models", fake_download)
    settings = make_settings(tmp_path)
    build(settings, OpenCVCamera(settings.vision), download_models=True)
    assert await asyncio.to_thread(done.wait, 2.0)
    assert calls[0][0] == tmp_path
    assert calls[0][1][0].startswith("yolov8")


def test_si_algo_falla_al_montar_no_lanza(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sonia.vision import stream as stream_module

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("roto")

    monkeypatch.setattr(stream_module, "OpenCVCameraStream", broken)
    settings = make_settings(tmp_path)
    vision = build(settings, OpenCVCamera(settings.vision))
    assert not vision.poses.available


async def test_la_vista_solo_sale_si_la_unity_conectada_la_anuncia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Con el ``GameManager`` de los cimientos: ``preview_supported`` sale de ``client_hello``."""
    from sonia.games.manager import GameManager
    from sonia.ws import protocol as p
    from tests.games.fakes import FakeEngine, FakeScreen, game_settings
    from tests.test_vision_stream import FakeVideo, wait_for

    settings = game_settings()
    settings.vision.source = "opencv"
    manager = GameManager(
        settings, engine=FakeEngine(), screen=FakeScreen(), games=[], camera_ready=lambda: True
    )
    camera = OpenCVCamera(settings.vision)
    device = FakeVideo()
    monkeypatch.setattr(camera, "_open_sync", lambda: device)
    frames: list[bytes] = []
    messages: list[dict[str, Any]] = []

    async def send_json(msg: dict[str, Any]) -> None:
        messages.append(msg)

    async def send_bytes(data: bytes) -> None:
        frames.append(data)

    vision = build_game_vision(
        settings=settings,
        camera=camera,
        send_json=send_json,
        send_bytes=send_bytes,
        preview_supported=manager.preview_supported,
        vision_llm=None,
        download_models=False,
    )

    def hello(features: list[str]) -> dict[str, Any]:
        return {"type": "client_hello", "client": "unity", "games": [], "features": features}

    # Una Unity anterior a los juegos no la sabe pintar: no se manda nada.
    await manager.on_client_hello(hello([]))
    assert await vision.preview.start("poses") is False
    await manager.on_client_hello(hello([p.FEATURE_CAMERA_PREVIEW]))
    assert await vision.preview.start("poses")
    await wait_for(lambda: len(frames) >= 2)
    assert p.decode_preview_frame(frames[0])[1:4] == (640, 360, True)
    assert messages[0] == p.msg_camera_preview(True)
    # Lo que sueltan los cimientos al terminar la partida, a nombre del juego.
    for release in (vision.preview.stop, vision.poses.release, vision.stream.release):
        await release("poses")
    assert not vision.stream.active
    assert messages[-1] == p.msg_camera_preview(False)
    await vision.close()
