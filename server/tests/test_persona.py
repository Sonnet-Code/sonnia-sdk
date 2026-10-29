"""Tests of the persona and of the editable knowledge base."""

from __future__ import annotations

from pathlib import Path

from sonia.persona import SYSTEM_PROMPT, host_of, is_local_host, load_knowledge


def test_load_knowledge_concatenates_in_order_and_ignores_the_readme(tmp_path: Path) -> None:
    (tmp_path / "02-b.md").write_text("Second\n", encoding="utf-8")
    (tmp_path / "01-a.md").write_text("First\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("Must not go in", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("Neither", encoding="utf-8")

    text = load_knowledge(tmp_path)

    assert text == "First\n\nSecond"


def test_several_knowledge_folders_go_one_after_another(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "01.md").write_text("A", encoding="utf-8")
    (tmp_path / "b" / "01.md").write_text("B", encoding="utf-8")
    assert load_knowledge([tmp_path / "a", tmp_path / "b"]) == "A\n\nB"


def test_load_knowledge_without_folder_returns_empty(tmp_path: Path) -> None:
    assert load_knowledge(tmp_path / "missing") == ""


def test_the_repository_knowledge_base_exists_and_fits_in_the_prompt() -> None:
    """The real assets/knowledge folder loads and does not blow up in size."""
    text = load_knowledge()
    assert "Sonia" in text
    assert len(text.split()) < 1500, "the knowledge base counts as tokens on every turn"


def test_the_persona_gives_safe_compliments() -> None:
    assert "compliment" in SYSTEM_PROMPT
    assert "never about the body" in SYSTEM_PROMPT


def test_the_persona_speaks_english_by_default_and_follows_the_user() -> None:
    assert "Speak English by default" in SYSTEM_PROMPT
    assert "answer in that language" in SYSTEM_PROMPT


def test_the_persona_does_not_claim_to_run_locally() -> None:
    assert "do not say you run locally" in SYSTEM_PROMPT


def test_host_of_and_is_local_host() -> None:
    assert host_of("https://API.openai.com/v1") == "api.openai.com"
    assert host_of("not a url") == ""
    assert is_local_host("localhost")
    assert is_local_host("192.168.1.20")
    assert is_local_host("sonia.local")
    assert not is_local_host("api.openai.com")
