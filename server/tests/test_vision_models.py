"""Descarga de los modelos de los juegos sin red (``httpx.MockTransport``)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from sonia.paths import SEEDED
from sonia.vision.models import (
    HAND_LANDMARKS,
    PALM_DETECTOR,
    POSE_MODELS,
    GameModel,
    GameModelError,
    download_game_models,
    game_models,
    games_models_dir,
    model_present,
)

DATA = b"modelo de mentira"
FAKE = GameModel(
    "falso.onnx", "https://modelos.invalid/falso.onnx", hashlib.sha256(DATA).hexdigest(), len(DATA)
)


def client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler)


def test_baja_el_modelo_y_no_lo_vuelve_a_bajar(tmp_path: Path) -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(200, content=DATA)

    folder = tmp_path / "modelos"
    with client(httpx.MockTransport(handler)) as http:
        assert download_game_models(folder, (FAKE,), client=http) == ["falso.onnx"]
        assert download_game_models(folder, (FAKE,), client=http) == []
    assert requests == [FAKE.url]
    assert (folder / "falso.onnx").read_bytes() == DATA
    assert model_present(folder, FAKE)
    assert not list(folder.glob("*.part"))


def test_rechaza_una_descarga_con_otra_huella(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"otra cosa"))
    with client(transport) as http, pytest.raises(GameModelError, match="huella"):
        download_game_models(tmp_path, (FAKE,), client=http)
    assert not (tmp_path / "falso.onnx").exists()


def test_sin_red_o_con_error_lo_dice(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(404))
    with client(transport) as http, pytest.raises(GameModelError, match="falso.onnx"):
        download_game_models(tmp_path, (FAKE,), client=http)


def test_un_archivo_a_medias_no_cuenta(tmp_path: Path) -> None:
    (tmp_path / "falso.onnx").write_bytes(DATA[:5])
    assert not model_present(tmp_path, FAKE)
    assert not model_present(tmp_path / "no-existe", FAKE)


def test_los_modelos_son_los_del_plan_con_revision_fijada() -> None:
    # docs/plan-juegos.md, sección 6.
    assert POSE_MODELS["s"].sha256 == (
        "5c92815cc509a9ccb6a817f4c2816de800092964319ad179a2751eda6df35d83"
    )
    assert POSE_MODELS["n"].sha256 == (
        "04f6d2416266f2aba6c5ba8b26de33ed9eba3279f972ac02e33f9f1366547586"
    )
    for model in (*POSE_MODELS.values(), HAND_LANDMARKS, PALM_DETECTOR):
        assert "/resolve/main/" not in model.url  # revisión fijada, no la rama
        assert model.url.startswith("https://huggingface.co/")
        assert len(model.sha256) == 64
    assert game_models("n") == (POSE_MODELS["n"], PALM_DETECTOR, HAND_LANDMARKS)
    assert game_models("zzz")[0] is POSE_MODELS["s"]


def test_la_carpeta_sale_de_los_ajustes_o_de_la_cache(tmp_path: Path) -> None:
    settings = SimpleNamespace(games=SimpleNamespace(models_dir=str(tmp_path / "m")))
    assert games_models_dir(settings) == tmp_path / "m"
    assert games_models_dir(SimpleNamespace()).parts[-3:] == ("cache", "games", "modelos")


def test_la_app_lleva_los_modelos_de_los_juegos() -> None:
    assert "cache/games/modelos" in SEEDED
