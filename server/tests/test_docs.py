"""The guides only name settings that exist and only link to files that exist."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from sonia.config_doc import collect
from sonia.paths import REPO_ROOT

GUIDES = sorted(
    [
        *(REPO_ROOT / "docs").glob("*.md"),
        REPO_ROOT / "README.md",
        REPO_ROOT / "CONTRIBUTING.md",
        *(REPO_ROOT / "assets").glob("*/README.md"),
    ]
)

#: Upper-case names in code spans that are not environment variables.
NOT_SETTINGS = {
    "LIVE_RULES",  # sonia/live/prompts.py
    "SYSTEM_PROMPT",  # sonia/persona.py
    "WRITTEN_NAME",  # sonia/live/engine.py
    "SONIA_HOME",  # sonia/paths.py, read before the settings
    "SONIA_WRITE_SNAPSHOTS",  # tests/prompt_snapshots.py
}

_CODE_SPAN = re.compile(r"`([^`\n]+)`")
_ENV_NAME = re.compile(r"(?<![A-Za-z0-9_.])([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)(?![A-Za-z0-9_*(])")
_LINK = re.compile(r"\]\(([^)\s]+)\)")


def _variables() -> set[str]:
    return {name for section in collect() for s in section.settings for name in s.variables}


def _ids(paths: list[Path]) -> list[str]:
    return [str(path.relative_to(REPO_ROOT)) for path in paths]


def _prose(path: Path) -> str:
    """The text of a guide without its fenced code blocks (examples, not references)."""
    return re.sub(r"^```.*?^```", "", path.read_text(encoding="utf-8"), flags=re.M | re.S)


def test_the_guides_are_found() -> None:
    names = {path.name for path in GUIDES}
    assert {"setup.md", "customization.md", "architecture.md", "README.md"} <= names


@pytest.mark.parametrize("guide", GUIDES, ids=_ids(GUIDES))
def test_every_named_setting_exists(guide: Path) -> None:
    known = _variables()
    named = {name for span in _CODE_SPAN.findall(_prose(guide)) for name in _ENV_NAME.findall(span)}
    unknown = sorted(named - known - NOT_SETTINGS)
    assert unknown == [], f"{guide.name} names settings Sonnia does not read: {unknown}"


@pytest.mark.parametrize("guide", GUIDES, ids=_ids(GUIDES))
def test_every_relative_link_resolves(guide: Path) -> None:
    broken = []
    for target in _LINK.findall(_prose(guide)):
        if re.match(r"[a-z]+:", target) or target.startswith("#"):
            continue
        if not (guide.parent / target.split("#", 1)[0]).exists():
            broken.append(target)
    assert broken == [], f"{guide.name} links to files that do not exist: {broken}"


def test_the_customization_guide_names_real_files() -> None:
    text = (REPO_ROOT / "docs" / "customization.md").read_text(encoding="utf-8")
    examples = {"assets/knowledge/10-museum.md", "assets/knowledge/10-shop.md"}
    paths = {
        span.rstrip("/").split("*", 1)[0].rstrip("/")
        for span in _CODE_SPAN.findall(text)
        if re.fullmatch(r"(assets|server|unity|docs)/[\w./*-]*", span)
    }
    missing = sorted(p for p in paths - examples if not (REPO_ROOT / p).exists())
    assert missing == [], f"docs/customization.md names paths that do not exist: {missing}"
