"""Rutas del orquestador en el repo y dentro de la app empaquetada."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from sonia import paths


def test_en_el_repo_todo_cuelga_del_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SONIA_HOME", raising=False)
    assert not paths.frozen()
    assert paths.home() == paths.REPO_ROOT
    assert (paths.REPO_ROOT / "server" / "sonia" / "paths.py").is_file()


def test_sonia_home_manda(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SONIA_HOME", str(tmp_path))
    assert paths.home() == tmp_path


def test_congelado_sin_sonia_home_usa_la_carpeta_del_usuario(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SONIA_HOME", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert paths.frozen()
    assert paths.home() == paths.user_data_dir()
    # Los assets van con el programa, en la carpeta de PyInstaller.
    assert paths._bundle_root() == tmp_path


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("darwin", Path("Library/Application Support/Sonia")),
        ("linux", Path(".local/share/sonia")),
    ],
)
def test_carpeta_del_usuario(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, platform: str, expected: Path
) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert paths.user_data_dir() == tmp_path / expected


def test_carpeta_del_usuario_en_windows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert paths.user_data_dir() == tmp_path / "Sonia"


def test_el_backoffice_manda_sobre_el_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SONIA_HOME", str(tmp_path))
    assert paths.env_files() == [tmp_path / "overrides.env", paths.REPO_ROOT / ".env"]


def test_en_la_app_el_env_va_junto_al_ejecutable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exe = tmp_path / "orquestador" / "sonia-orquestador"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setenv("SONIA_HOME", str(tmp_path / "home"))
    assert paths.env_files() == [
        tmp_path / "home" / "overrides.env",
        exe.parent / "build.env",
        exe.parent / ".env",
    ]


def test_el_build_env_de_las_pruebas_apaga_la_camara_del_panel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sonia import config

    folder = tmp_path / "orquestador"
    folder.mkdir()
    (folder / "build.env").write_text("PANEL_CAMERA_STREAM=false\n", encoding="utf-8")
    (folder / ".env").write_text("PANEL_CAMERA_STREAM=true\n", encoding="utf-8")
    home = tmp_path / "home"
    monkeypatch.setattr(
        config, "env_files", lambda: [home / "overrides.env", folder / "build.env", folder / ".env"]
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PANEL_CAMERA_STREAM", "")
    monkeypatch.delenv("PANEL_CAMERA_STREAM")
    assert config.load_settings().panel.camera_stream is False


def test_overrides_manda_al_cargar(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from sonia import config

    home = tmp_path / "home"
    home.mkdir()
    (home / "overrides.env").write_text("LIVE_VOICE=cedar\n", encoding="utf-8")
    bundled = tmp_path / "bundled.env"
    bundled.write_text("LIVE_VOICE=marin\nLIVE_MODEL=gpt-live-prueba\n", encoding="utf-8")
    monkeypatch.setattr(config, "env_files", lambda: [home / "overrides.env", bundled])
    monkeypatch.chdir(tmp_path)
    # load_dotenv escribe en os.environ: así monkeypatch lo deja como estaba al acabar.
    for name in ("LIVE_VOICE", "LIVE_MODEL"):
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    settings = config.load_settings()
    assert settings.live.voice == "cedar"
    assert settings.live.model == "gpt-live-prueba"


def test_la_app_siembra_las_frases_grabadas_sin_pisar_nada(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    home = tmp_path / "home"
    (bundle / "cache" / "voice" / "marin").mkdir(parents=True)
    (bundle / "cache" / "voice" / "marin" / "a.wav").write_bytes(b"empaquetada")
    (bundle / "cache" / "voice" / "marin" / "b.wav").write_bytes(b"empaquetada")
    (home / "cache" / "voice" / "marin").mkdir(parents=True)
    (home / "cache" / "voice" / "marin" / "b.wav").write_bytes(b"de este equipo")

    assert paths.seed_home(bundle, home) == 1
    assert (home / "cache" / "voice" / "marin" / "a.wav").read_bytes() == b"empaquetada"
    assert (home / "cache" / "voice" / "marin" / "b.wav").read_bytes() == b"de este equipo"
    # La segunda vez ya no hay nada que copiar.
    assert paths.seed_home(bundle, home) == 0


def test_fuera_de_la_app_no_siembra_nada(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SONIA_HOME", str(tmp_path))
    assert not paths.frozen()
    assert paths.seed_home() == 0
    assert not (tmp_path / "cache").exists()


def test_la_app_sin_frases_empaquetadas_no_siembra(tmp_path: Path) -> None:
    assert paths.seed_home(tmp_path / "bundle", tmp_path / "home") == 0
