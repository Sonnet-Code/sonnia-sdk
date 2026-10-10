"""Cambio en caliente del modelo de poses (``n`` o ``s``) sin red ni modelos de verdad.

Los archivos de los modelos son archivos dispersos del tamaño exacto (no ocupan disco) y
los modelos son falsos: cada uno dice de qué variante es por cuántas personas ve.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from sonia.vision import models as models_module
from sonia.vision.contracts import Person
from sonia.vision.models import POSE_MODELS, GameModelError
from sonia.vision.poses import YoloPoseDetector
from tests.test_vision_poses import FakeStream, someone

#: Personas que «ve» cada variante: así se sabe con qué modelo salió cada detección.
PEOPLE = {"n": 1, "s": 2}


def make_files(folder: Path, *variants: str) -> None:
    """Archivos de modelo del tamaño exacto, dispersos (no ocupan disco)."""
    folder.mkdir(parents=True, exist_ok=True)
    for variant in variants:
        with (folder / POSE_MODELS[variant].name).open("wb") as handle:
            handle.truncate(POSE_MODELS[variant].size)


def variant_of(path: Path) -> str:
    return next(v for v, model in POSE_MODELS.items() if model.name == path.name)


class TaggedModel:
    def __init__(self, variant: str) -> None:
        self.variant = variant

    def detect(self, frame_bgr: np.ndarray) -> tuple[Person, ...]:
        return tuple(someone(0.2 + 0.3 * i) for i in range(PEOPLE[self.variant]))


class Opener:
    """Carga modelos falsos; los de ``slow`` esperan a ``gate`` y los de ``broken`` fallan."""

    def __init__(self, *, slow: set[str] | None = None, broken: set[str] | None = None) -> None:
        self.slow = slow or set()
        self.broken = broken or set()
        self.gate = threading.Event()
        self.opened: list[str] = []

    def __call__(self, path: Path) -> TaggedModel:
        variant = variant_of(path)
        self.opened.append(variant)
        if variant in self.slow:
            assert self.gate.wait(5.0)
        if variant in self.broken:
            raise RuntimeError("modelo roto")
        return TaggedModel(variant)


async def wait_for(condition: Callable[[], bool], limit_s: float = 3.0) -> None:
    deadline = time.monotonic() + limit_s
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("no se cumplió a tiempo")
        await asyncio.sleep(0.01)


def people_now(detector: YoloPoseDetector) -> int | None:
    frame = detector.latest()
    return None if frame is None else len(frame.people)


async def test_cambia_de_modelo_en_caliente_con_una_partida_en_marcha(tmp_path: Path) -> None:
    make_files(tmp_path, "n", "s")
    opener = Opener(slow={"s"})
    detector = YoloPoseDetector(FakeStream(), tmp_path, opener=opener, download=False)
    assert detector.variant == "n"
    assert await detector.acquire("poses", fps=50)
    await wait_for(lambda: people_now(detector) == PEOPLE["n"])

    detector.set_variant("s")
    assert detector.requested == "s"
    # Mientras se carga el nuevo, se sigue detectando con el viejo.
    await asyncio.sleep(0.15)
    assert detector.variant == "n"
    assert people_now(detector) == PEOPLE["n"]

    opener.gate.set()
    await wait_for(lambda: detector.variant == "s")
    await wait_for(lambda: people_now(detector) == PEOPLE["s"])
    await detector.release("poses")
    assert opener.opened == ["n", "s"]


async def test_pedir_el_que_ya_esta_o_el_que_se_carga_no_hace_nada(tmp_path: Path) -> None:
    make_files(tmp_path, "n", "s")
    opener = Opener(slow={"s"})
    detector = YoloPoseDetector(FakeStream(), tmp_path, opener=opener, download=False)
    assert await asyncio.to_thread(detector.preload)
    detector.set_variant("n")
    detector.set_variant("s")
    detector.set_variant("S ")
    await asyncio.sleep(0.05)
    opener.gate.set()
    await wait_for(lambda: detector.variant == "s")
    await asyncio.sleep(0.05)
    assert opener.opened == ["n", "s"]


async def test_la_ultima_peticion_manda(tmp_path: Path) -> None:
    make_files(tmp_path, "n", "s")
    opener = Opener(slow={"s"})
    detector = YoloPoseDetector(FakeStream(), tmp_path, opener=opener, download=False)
    assert await asyncio.to_thread(detector.preload)
    detector.set_variant("s")
    await wait_for(lambda: "s" in opener.opened)  # cargando
    detector.set_variant("n")  # vuelta al que hay antes de que acabe
    assert detector.requested == "n"
    opener.gate.set()
    await asyncio.sleep(0.2)
    assert detector.variant == "n"
    # Y se puede volver a pedir.
    detector.set_variant("s")
    await wait_for(lambda: detector.variant == "s")


async def test_si_falta_el_modelo_se_baja_al_pedirlo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_files(tmp_path, "n")
    asked: list[list[str]] = []

    def fake_download(folder: Path, wanted: Any = None, **_: Any) -> list[str]:
        names = [model.name for model in wanted]
        asked.append(names)
        make_files(folder, "s")
        return names

    monkeypatch.setattr(models_module, "download_game_models", fake_download)
    detector = YoloPoseDetector(FakeStream(), tmp_path, opener=Opener())
    assert await asyncio.to_thread(detector.preload)
    detector.set_variant("s")
    await wait_for(lambda: detector.variant == "s")
    assert asked == [[POSE_MODELS["s"].name]]


async def test_sin_red_se_queda_el_viejo_y_se_puede_reintentar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    make_files(tmp_path, "n")
    calls: list[int] = []

    def no_network(folder: Path, wanted: Any = None, **_: Any) -> list[str]:
        calls.append(1)
        raise GameModelError("sin red")

    monkeypatch.setattr(models_module, "download_game_models", no_network)
    detector = YoloPoseDetector(FakeStream(), tmp_path, opener=Opener())
    assert await asyncio.to_thread(detector.preload)
    with caplog.at_level(logging.WARNING, logger="sonia.vision.poses"):
        detector.set_variant("s")
        await wait_for(lambda: detector.requested == "n")
    assert detector.variant == "n"
    assert "se sigue con «n»" in caplog.text
    detector.set_variant("s")  # otra petición lo reintenta
    await wait_for(lambda: len(calls) == 2)
    await wait_for(lambda: detector.requested == "n")


async def test_si_el_nuevo_no_carga_se_queda_el_viejo(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    make_files(tmp_path, "n", "s")
    detector = YoloPoseDetector(FakeStream(), tmp_path, opener=Opener(broken={"s"}), download=False)
    assert await detector.acquire("poses", fps=50)
    with caplog.at_level(logging.WARNING, logger="sonia.vision.poses"):
        detector.set_variant("s")
        await wait_for(lambda: detector.requested == "n")
    assert detector.variant == "n"
    await wait_for(lambda: people_now(detector) == PEOPLE["n"])
    assert "no carga" in caplog.text
    await detector.release("poses")


async def test_sin_descargas_y_sin_el_archivo_se_queda_el_viejo(tmp_path: Path) -> None:
    make_files(tmp_path, "n")
    detector = YoloPoseDetector(FakeStream(), tmp_path, opener=Opener(), download=False)
    assert await asyncio.to_thread(detector.preload)
    detector.set_variant("s")
    await wait_for(lambda: detector.requested == "n")
    assert detector.variant == "n"


async def test_pedido_antes_de_cargar_nada_carga_ese(tmp_path: Path) -> None:
    make_files(tmp_path, "n", "s")
    opener = Opener()
    detector = YoloPoseDetector(FakeStream(), tmp_path, opener=opener, download=False)
    detector.set_variant("s")
    assert detector.variant == "s"  # la que se cargará
    assert await detector.acquire("poses", fps=50)
    await wait_for(lambda: people_now(detector) == PEOPLE["s"])
    await detector.release("poses")
    assert opener.opened == ["s"]


async def test_sin_el_archivo_pedido_se_usa_el_otro(tmp_path: Path) -> None:
    make_files(tmp_path, "s")
    detector = YoloPoseDetector(FakeStream(), tmp_path, variant="n", opener=Opener())
    assert detector.available
    assert await asyncio.to_thread(detector.preload)
    assert detector.variant == "s"


async def test_una_variante_que_no_existe_se_ignora(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    make_files(tmp_path, "n")
    detector = YoloPoseDetector(FakeStream(), tmp_path, opener=Opener(), download=False)
    with caplog.at_level(logging.WARNING, logger="sonia.vision.poses"):
        detector.set_variant("xl")
    assert (detector.variant, detector.requested) == ("n", "n")
    assert "desconocido" in caplog.text
