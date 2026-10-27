"""Línea de órdenes de Sonnia Video (sin red: el renderizador no está y las APIs son falsas)."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from sonia.video import cli
from sonia.video.pipeline import Pipeline
from sonia.video.script import EXAMPLE
from tests.test_video_pipeline import FFMPEG, FakeLLM, make_pipeline, make_script


@pytest.fixture(autouse=True)
def _sin_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ningún test carga el ``.env`` del repo (tiene claves de verdad)."""
    monkeypatch.setattr(cli, "load_env", lambda: [])


def test_ejemplo(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["ejemplo"]) == 0
    out = capsys.readouterr().out
    assert out == EXAMPLE
    tomllib.loads(out)


def test_ayuda(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([]) == 0
    assert "render" in capsys.readouterr().out
    with pytest.raises(SystemExit) as info:
        cli.main(["render", "--help"])
    assert info.value.code == 0
    text = capsys.readouterr().out
    for flag in (
        "--voz",
        "--formato",
        "--calidad",
        "--reel",
        "--forzar",
        "--emocion",
        "--luz",
        "--fondo",
        "--encuadre",
        "--sin-gestos",
    ):
        assert flag in text


def test_estado_y_cerrar_sin_renderizador(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["estado"]) == 0
    assert "no está abierto" in capsys.readouterr().out
    assert cli.main(["cerrar"]) == 0
    assert "no estaba abierto" in capsys.readouterr().out


def test_errores_con_mensaje_y_codigo(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["render", str(tmp_path / "no.toml")]) == 1
    assert "error: No existe el guion" in capsys.readouterr().err
    bad = tmp_path / "malo.toml"
    bad.write_text('[[frase]]\ntexto = "Hola."\n[escena]\nluz = "neón"\n', encoding="utf-8")
    assert cli.main(["render", str(bad)]) == 1
    assert "escena → luz" in capsys.readouterr().err


def test_voces(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    assert cli.main(["voces"]) == 0
    out = capsys.readouterr().out
    assert "es-es-techagent-5" in out and "es-419-commercial-6" in out
    assert "ELEVENLABS_API_KEY" in out
    assert cli.main(["voces", "elevenlabs"]) == 1
    assert "Falta ELEVENLABS_API_KEY" in capsys.readouterr().err


@pytest.mark.skipif(FFMPEG is None, reason="sin ffmpeg en este equipo")
def test_decir_con_flags(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "falsa")
    # El texto partido en frases es el mismo guion que usa el Gemini falso.
    script = make_script(frase=[{"texto": "¡Hola! Soy Sonia."}, {"texto": "Adiós."}])
    pipeline, fake, _, _ = make_pipeline(tmp_path, script, llm=FakeLLM('{"gestos": []}'))
    monkeypatch.setattr(Pipeline, "default", classmethod(lambda cls, progress=None: pipeline))
    code = cli.main(
        [
            "decir",
            "¡Hola! Soy Sonia. Adiós.",
            "--out",
            str(tmp_path / "salida"),
            "--formato",
            "64x112",
            "--calidad",
            "borrador",
            "--luz",
            "fria",
            "--sin-gestos",
            "--titulo",
            "saludo",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0, out
    assert f"Listo: {tmp_path / 'salida' / 'saludo.mp4'}" in out
    assert "Subtítulos:" in out and "Gestos: ninguno" in out
    job = fake.jobs[0]
    assert job["scene"]["lighting"]["preset"] == "cool"
    assert (job["width"], job["height"]) == (64, 112)


@pytest.mark.skipif(FFMPEG is None, reason="sin ffmpeg en este equipo")
def test_foto_y_reel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "falsa")
    script = make_script(frase=[{"texto": "¡Hola! Soy Sonia."}, {"texto": "Adiós."}])
    pipeline, fake, _, _ = make_pipeline(tmp_path, script, llm=FakeLLM('{"gestos": []}'))
    monkeypatch.setattr(Pipeline, "default", classmethod(lambda cls, progress=None: pipeline))
    code = cli.main(
        [
            "foto",
            "--gesto",
            "waveCalm",
            "--rafaga",
            "2",
            "--fondo",
            "transparente",
            "--formato",
            "4k-vertical",
            "--out",
            str(tmp_path / "fotos"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0, out
    assert out.count("Foto: ") == 2
    assert fake.jobs[-1]["scene"]["background"]["mode"] == "transparent"
    reel = tmp_path / "reel"
    reel.mkdir()
    (reel / "reel.config.js").write_text("export default {};\n", encoding="utf-8")
    code = cli.main(
        [
            "decir",
            "¡Hola! Soy Sonia. Adiós.",
            "--reel",
            str(reel),
            "--formato",
            "64x112",
            "--calidad",
            "borrador",
            "--sin-gestos",
            "--out",
            str(tmp_path / "salida"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0, out
    assert f"Paquete para reels: {reel / 'assets' / 'sonnia'}" in out
    assert "Para el reel:" in out and "secuencia(C, root" in out
    assert cli.main(["decir", "Hola.", "--reel", str(reel)]) == 1
    assert "--forzar" in capsys.readouterr().err
