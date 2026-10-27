"""Cliente del renderizador de Sonnia Video contra una app de Unity falsa (``MockTransport``)."""

from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from sonia.video.errors import VideoError
from sonia.video.renderer import (
    Cancelled,
    Progress,
    RendererClient,
    app_executable,
    find_app,
    port,
    run_job,
    wait_ready,
)
from tests.video_fakes import CATALOG, FakeRenderer


def job(**fields: Any) -> dict[str, Any]:
    base = {"id": "prueba-1", "kind": "video", "fps": 30, "duration_s": 2.0, "output_dir": "/x"}
    base.update(fields)
    return base


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_estado_catalogo_y_cierre() -> None:
    fake = FakeRenderer()
    client = RendererClient(8795, transport=fake.transport)
    status = client.status()
    assert status is not None and status["avatar"] == "ready"
    assert client.catalog() == CATALOG
    assert client.quit() is True
    assert fake.quit
    assert client.status() is None  # ya no contesta


def test_catalogo_sin_avatar() -> None:
    client = RendererClient(8795, transport=FakeRenderer(avatar="loading").transport)
    with pytest.raises(VideoError, match="aún no tiene el avatar"):
        client.catalog()


def test_sin_app_abierta_no_hay_estado() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no", request=request)

    assert RendererClient(8795, transport=httpx.MockTransport(refuse)).status() is None


def test_espera_al_avatar_con_progreso() -> None:
    fake = FakeRenderer(avatar="loading")
    clock = Clock()
    stream = io.StringIO()
    calls = {"n": 0}

    def sleep(seconds: float) -> None:
        calls["n"] += 1
        clock.sleep(seconds)
        if calls["n"] == 3:
            fake.avatar = "ready"

    status = wait_ready(
        RendererClient(8795, transport=fake.transport),
        progress=Progress(stream, every_s=0),
        sleep=sleep,
        clock=clock,
    )
    assert status["avatar"] == "ready"
    assert "Cargando el avatar de Sonnia… 0:00" in stream.getvalue()


def test_espera_al_avatar_con_tope_y_app_caida(tmp_path: Path) -> None:
    clock = Clock()
    with pytest.raises(VideoError, match="El avatar de Genies no cargó en 0:05"):
        wait_ready(
            RendererClient(8795, transport=FakeRenderer(avatar="loading").transport),
            timeout_s=5,
            sleep=clock.sleep,
            clock=clock,
        )

    class Dead:
        def poll(self) -> int:
            return 1

    fake = FakeRenderer()
    fake.alive = False
    with pytest.raises(VideoError, match="se cerró al arrancar. Registro: .*unity.log"):
        wait_ready(
            RendererClient(8795, transport=fake.transport),
            process=Dead(),  # type: ignore[arg-type]
            log_file=tmp_path / "unity.log",
            sleep=clock.sleep,
            clock=clock,
        )


def test_trabajo_con_progreso_en_una_linea() -> None:
    fake = FakeRenderer(polls=3)
    clock = Clock()
    stream = io.StringIO()
    done = run_job(
        RendererClient(8795, transport=fake.transport),
        job(),
        progress=Progress(stream, every_s=0),
        sleep=clock.sleep,
        clock=clock,
    )
    assert done["state"] == "done"
    assert fake.jobs[0]["id"] == "prueba-1"
    text = stream.getvalue()
    assert "Renderizando cuadro 10/60 · 20,0 cuadros/s · quedan 0:02" in text


def test_trabajo_ocupado_fallido_y_rechazado() -> None:
    fake = FakeRenderer(polls=100)
    client = RendererClient(8795, transport=fake.transport)
    client.submit(job(id="otro"))
    with pytest.raises(VideoError, match="ocupado con otro trabajo"):
        client.submit(job())
    clock = Clock()
    with pytest.raises(VideoError, match="El renderizador falló: sin memoria"):
        run_job(
            RendererClient(8795, transport=FakeRenderer(fail="sin memoria").transport),
            job(),
            sleep=clock.sleep,
            clock=clock,
        )
    bad = httpx.MockTransport(lambda r: httpx.Response(400, text="falta width"))
    with pytest.raises(VideoError, match="rechazó el trabajo \\(400\\): falta width"):
        RendererClient(8795, transport=bad).submit(job())


def test_ctrl_c_cancela_en_la_app() -> None:
    fake = FakeRenderer(polls=100)
    calls = {"n": 0}

    def sleep(seconds: float) -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise KeyboardInterrupt

    with pytest.raises(Cancelled):
        run_job(RendererClient(8795, transport=fake.transport), job(), sleep=sleep)
    assert fake.cancelled


def test_la_app_deja_de_contestar() -> None:
    fake = FakeRenderer(polls=100)
    client = RendererClient(8795, transport=fake.transport)
    clock = Clock()
    original = clock.sleep

    def sleep(seconds: float) -> None:
        fake.alive = False
        original(seconds)

    with pytest.raises(VideoError, match="dejó de contestar"):
        run_job(client, job(), sleep=sleep, clock=clock)


def test_donde_esta_la_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    app = tmp_path / "Sonnia Video.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    exe = app / "Contents" / "MacOS" / "Sonnia Video"
    exe.write_text("#!/bin/sh\n")
    monkeypatch.setenv("SONNIA_VIDEO_APP", str(app))
    assert find_app() == app
    assert app_executable(app) == exe
    monkeypatch.setenv("SONNIA_VIDEO_APP", str(tmp_path / "nada.app"))
    with pytest.raises(VideoError, match="(?s)No encuentro «Sonnia Video».*SONNIA_VIDEO_APP"):
        find_app()
    with pytest.raises(VideoError):
        app_executable(tmp_path)


def test_app_congelada_dentro_de_la_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    app = tmp_path / "Sonnia Video.app"
    frozen_exe = app / "Contents" / "Resources" / "sonnia-video" / "sonnia-video"
    frozen_exe.parent.mkdir(parents=True)
    frozen_exe.write_text("")
    monkeypatch.delenv("SONNIA_VIDEO_APP")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(frozen_exe))
    assert find_app() == app


def test_puerto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SONNIA_VIDEO_PORT")
    assert port() == 8795
    monkeypatch.setenv("SONNIA_VIDEO_PORT", "9000")
    assert port() == 9000
    monkeypatch.setenv("SONNIA_VIDEO_PORT", "x")
    with pytest.raises(VideoError):
        port()


def test_orden_de_arranque_sin_ventana(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from sonia.video.renderer import launch_args

    exe = tmp_path / "Sonnia Video"
    log = tmp_path / "unity.log"
    assert launch_args(exe, 8795, log) == [
        str(exe),
        "-batchmode",
        "-sonnia-video",
        "-sonnia-video-port",
        "8795",
        "-logFile",
        str(log),
    ]
    plain = launch_args(exe, 9000, log, outfit="plain", idle_min=10)
    assert plain[1] == "-batchmode"
    assert plain[plain.index("-sonnia-video-idle-min") + 1] == "10"
    assert "-sin-camiseta-staff" in plain
    assert plain[-2:] == ["-logFile", str(log)]


class FakeProcess:
    def __init__(self) -> None:
        self.alive = True

    def poll(self) -> int | None:
        return None if self.alive else 0


def test_otra_camiseta_cierra_y_vuelve_a_abrir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sonia.video import renderer

    fake = FakeRenderer(outfit="staff")
    launched: list[str] = []

    def launch(app: Path, listen_port: int, log_file: Path, *, outfit: str = "staff") -> Any:
        launched.append(outfit)
        fake.alive, fake.outfit = True, outfit
        return FakeProcess()

    monkeypatch.setattr(renderer, "launch", launch)
    monkeypatch.setattr(renderer, "_LAUNCHED", {})
    client = RendererClient(8795, transport=fake.transport)
    app = tmp_path / "Sonnia Video.app"
    # La misma camiseta (o cualquiera): no se toca.
    assert renderer.ensure_started(client, tmp_path / "u.log", app=app, outfit="staff") is None
    assert renderer.ensure_started(client, tmp_path / "u.log", app=app) is None
    # La lisa: cierra la abierta, espera a que no conteste y la abre con -sin-camiseta-staff.
    process = renderer.ensure_started(
        client, tmp_path / "u.log", app=app, outfit="plain", sleep=lambda s: None
    )
    assert process is not None and fake.quit and launched == ["plain"]
    assert client.status()["outfit"] == "plain"  # type: ignore[index]


def test_no_lanza_otra_mientras_arranca(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from sonia.video import renderer

    fake = FakeRenderer()
    fake.alive = False  # arrancando: aún no contesta
    started: list[FakeProcess] = []

    def launch(app: Path, listen_port: int, log_file: Path, *, outfit: str = "staff") -> Any:
        started.append(FakeProcess())
        return started[-1]

    monkeypatch.setattr(renderer, "launch", launch)
    monkeypatch.setattr(renderer, "_LAUNCHED", {})
    client = RendererClient(8795, transport=fake.transport)
    first = renderer.ensure_started(client, tmp_path / "u.log", app=tmp_path)
    again = renderer.ensure_started(client, tmp_path / "u.log", app=tmp_path)
    assert first is again and len(started) == 1
    started[0].alive = False  # se cayó: ahora sí se lanza otra
    renderer.ensure_started(client, tmp_path / "u.log", app=tmp_path)
    assert len(started) == 2


def test_otra_camiseta_con_trabajo_en_curso(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sonia.video import renderer

    fake = FakeRenderer(polls=100)
    client = RendererClient(8795, transport=fake.transport)
    client.submit(job())
    with pytest.raises(VideoError, match="otra camiseta y está ocupado"):
        renderer.ensure_started(client, tmp_path / "u.log", app=tmp_path, outfit="plain")


def test_relanza_una_vez_si_el_avatar_no_llega(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Genies a veces se queda a medias en el primer arranque: se relanza la app una vez."""
    from sonia.video import renderer
    from sonia.video.pipeline import Pipeline
    from sonia.video.voice import VoiceCache, VoiceMaker

    fake = FakeRenderer(avatar="loading")
    launched: list[str] = []

    def launch(app: Path, listen_port: int, log_file: Path, *, outfit: str = "staff") -> Any:
        launched.append(outfit)
        fake.alive, fake.avatar = True, "ready"
        return FakeProcess()

    monkeypatch.setattr(renderer, "launch", launch)
    monkeypatch.setattr(renderer, "_LAUNCHED", {})
    pipeline = Pipeline(
        client=RendererClient(8795, transport=fake.transport),
        voice=VoiceMaker(VoiceCache(tmp_path / "cache")),
        ffmpeg="ffmpeg",
        progress=Progress(io.StringIO(), every_s=0),
        app=tmp_path / "Sonnia Video.app",
        stall_restart_s=0.0,
    )
    status = pipeline.ready()
    assert status["avatar"] == "ready"
    assert fake.quit and launched == ["staff"]
