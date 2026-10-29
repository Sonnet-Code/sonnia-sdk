"""Orchestrator paths: the repository, ``SONIA_HOME`` and the variables files."""

from __future__ import annotations

from pathlib import Path

import pytest

from sonia import paths


def test_in_the_repo_everything_hangs_from_the_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SONIA_HOME", raising=False)
    assert paths.home() == paths.REPO_ROOT
    assert (paths.REPO_ROOT / "server" / "sonia" / "paths.py").is_file()


def test_sonia_home_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SONIA_HOME", str(tmp_path))
    assert paths.home() == tmp_path


def test_overrides_win_over_the_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SONIA_HOME", str(tmp_path))
    assert paths.env_files() == [tmp_path / "overrides.env", paths.REPO_ROOT / ".env"]


def test_overrides_win_when_loading(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from sonia import config

    home = tmp_path / "home"
    home.mkdir()
    (home / "overrides.env").write_text("LIVE_VOICE=cedar\n", encoding="utf-8")
    bundled = tmp_path / "bundled.env"
    bundled.write_text("LIVE_VOICE=marin\nLIVE_MODEL=gpt-live-test\n", encoding="utf-8")
    monkeypatch.setattr(config, "env_files", lambda: [home / "overrides.env", bundled])
    monkeypatch.chdir(tmp_path)
    # load_dotenv writes to os.environ: this way monkeypatch restores it afterwards.
    for name in ("LIVE_VOICE", "LIVE_MODEL"):
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    settings = config.load_settings()
    assert settings.live.voice == "cedar"
    assert settings.live.model == "gpt-live-test"
