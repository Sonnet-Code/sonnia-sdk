"""The configuration reference (docs/configuration.md) is generated from the code."""

from __future__ import annotations

import re

from sonia.config_doc import collect, default_path, render
from sonia.paths import REPO_ROOT


def _all_variables() -> set[str]:
    return {name for section in collect() for s in section.settings for name in s.variables}


def test_the_committed_reference_matches_the_settings_model() -> None:
    committed = default_path().read_text(encoding="utf-8")
    assert committed == render(), (
        "docs/configuration.md is out of date. Regenerate it from server/ with "
        "`uv run --no-sync python -m sonia.config_doc > ../docs/configuration.md`."
    )


def test_every_setting_has_a_description() -> None:
    missing = [
        s.variables[0] for section in collect() for s in section.settings if not s.description
    ]
    assert missing == [], f"add a `#:` comment above these fields in sonia/config.py: {missing}"


def test_env_example_only_names_real_settings() -> None:
    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    named = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", example, re.MULTILINE))
    unknown = sorted(named - _all_variables())
    assert unknown == [], f".env.example names variables Sonnia does not read: {unknown}"


def test_paths_do_not_leak_the_machine_that_generated_the_reference() -> None:
    text = render()
    assert str(REPO_ROOT) not in text
    assert "<SONIA_HOME>/cache/" in text
