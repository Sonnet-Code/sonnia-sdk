"""The prompt editor: the registry of texts, its checks, where the edited texts are used
and the panel actions that save them. No network: the panel runs against the fake
GPT-Live of ``test_live``."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from sonia.actions import build_default_registry
from sonia.live.prompts import (
    BACKEND_PROMPT,
    LIVE_RULES,
    build_backend_instructions,
    build_live_instructions,
)
from sonia.live.vision import NARRATOR_PROMPT, VisionNarrator
from sonia.panel.control import PanelState
from sonia.persona import SYSTEM_PROMPT
from sonia.prompt_book import (
    BOOK,
    LIVE_RULE_FIELDS,
    PROMPT_MAX_LEN,
    PromptBook,
    PromptSpec,
    placeholders,
    use_knowledge_dirs,
)
from sonia.types import Frame
from tests.test_live import FakeVisionLLM, make_settings
from tests.test_panel import make_panel_rig, running_panel


def _book() -> PromptBook:
    book = PromptBook()
    book.register(PromptSpec(id="plain", title="Plain", default=lambda: "Say {hi} as is."))
    book.register(
        PromptSpec(
            id="rules",
            title="Rules",
            default=lambda: "Tools:\n{tools}\n{extra}",
            fields=("tools", "extra"),
            required=("tools",),
            template=True,
        )
    )
    return book


# -- the registry ------------------------------------------------------------


def test_every_text_the_models_get_is_registered() -> None:
    assert BOOK.ids() == ("persona", "knowledge", "live_rules", "backend_rules", "vision")
    assert BOOK.default("persona") == SYSTEM_PROMPT
    assert BOOK.default("live_rules") == LIVE_RULES
    assert BOOK.default("backend_rules") == BACKEND_PROMPT
    assert BOOK.default("vision") == NARRATOR_PROMPT


def test_the_voice_rule_placeholders_are_the_ones_the_code_fills() -> None:
    assert tuple(placeholders(LIVE_RULES)[0]) == LIVE_RULE_FIELDS


def test_every_built_in_text_passes_its_own_check(tmp_path: Path) -> None:
    (tmp_path / "10-place.md").write_text("The talks are on the first floor.", encoding="utf-8")
    use_knowledge_dirs([tmp_path])
    for prompt_id in BOOK.ids():
        assert BOOK.validate(prompt_id, BOOK.default(prompt_id)) == [], prompt_id
    assert BOOK.default("knowledge") == "The talks are on the first floor."


def test_a_bad_spec_is_refused() -> None:
    book = PromptBook()
    with pytest.raises(ValueError, match="invalid prompt id"):
        book.register(PromptSpec(id="Bad id", title="", default=str))
    with pytest.raises(ValueError, match="only a template"):
        book.register(PromptSpec(id="x", title="", default=str, fields=("a",)))
    with pytest.raises(ValueError, match="required"):
        book.register(PromptSpec(id="x", title="", default=str, template=True, required=("a",)))


# -- checks ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("Tools: {tools} {weather}", "does not fill in {weather}"),
        ("Tools: {tools} {", "not a valid template"),
        ('Tools: {tools} {"a": 1}', "is not a placeholder"),
        ("Tools: {tools} {0}", "is not a placeholder"),
        ("Tools: {tools} {tools.name}", "is not a placeholder"),
        ("Tools: {tools:>10}", "cannot carry a format"),
        ("No tools here: {extra}", "must keep {tools}"),
        ("   ", "empty"),
        ("{tools}" + "x" * PROMPT_MAX_LEN, "too long"),
    ],
    # Short ids: pytest puts the id in an environment variable, and Windows caps those.
    ids=lambda value: value[:24] if isinstance(value, str) else None,
)
def test_a_template_that_would_not_fill_is_refused(text: str, problem: str) -> None:
    problems = _book().validate("rules", text)
    assert any(problem in p for p in problems), problems


def test_a_template_may_drop_optional_placeholders_and_escape_braces() -> None:
    assert _book().validate("rules", 'Only {tools}. JSON: {{"ok": true}}') == []


def test_a_plain_text_keeps_its_braces() -> None:
    book = _book()
    assert book.validate("plain", 'Answer with {"seen": true} and {anything}.') == []
    assert book.validate("missing", "text") == ["There is no prompt 'missing'."]


def test_set_reset_and_load() -> None:
    book = _book()
    assert book.set("rules", "Only {tools}") == []
    assert book.text("rules") == "Only {tools}"
    assert book.edits() == {"rules": "Only {tools}"}
    assert book.set("rules", "Nothing") != []  # refused: nothing changes
    assert book.text("rules") == "Only {tools}"
    assert book.reset("rules") is True
    assert book.reset("rules") is False
    assert book.text("rules") == "Tools:\n{tools}\n{extra}"

    warnings = book.load({"rules": "No placeholder", "plain": "Hi", "gone": "x", "bad": 3})
    assert len(warnings) == 1 and warnings[0].startswith("rules:")
    assert book.override("rules") is None  # ignored, but kept for the editor
    assert book.text("plain") == "Hi"
    assert book.edits() == {"rules": "No placeholder", "plain": "Hi", "gone": "x"}
    entry = {e["id"]: e for e in book.catalog()}["rules"]
    assert entry["edited"] and entry["ignored"] and entry["text"] == "No placeholder"


# -- where the edited texts go -----------------------------------------------


def test_the_session_uses_the_edited_texts(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    registry = build_default_registry(include_look=False)
    (tmp_path / "10-place.md").write_text("Files say: room A.", encoding="utf-8")
    before = build_live_instructions(
        settings, registry=registry, gallery_ids=[], knowledge_dir=tmp_path
    )
    assert "room A" in before

    assert BOOK.set("persona", "You are Ada, a museum guide.") == []
    assert BOOK.set("knowledge", "The museum closes at six.") == []
    assert BOOK.set("live_rules", "RULES. Tools:\n{capabilities}") == []
    assert BOOK.set("backend_rules", "You run Ada's tools.") == []
    live = build_live_instructions(
        settings, registry=registry, gallery_ids=[], knowledge_dir=tmp_path
    )
    assert live.startswith("You are Ada, a museum guide.\n\nRULES. Tools:\n- ")
    assert "closes at six" in live and "room A" not in live
    assert SYSTEM_PROMPT.strip() not in live  # the edited one, never both

    backend = build_backend_instructions(gallery_ids=[], knowledge_dir=tmp_path)
    assert backend.startswith("You run Ada's tools.")
    assert "closes at six" in backend and "room A" not in backend


def test_rules_that_do_not_format_fall_back_to_the_built_in_ones(tmp_path: Path) -> None:
    # The editor never saves these; the safety net still keeps the session alive.
    BOOK._valid["live_rules"] = "{weather}"
    live = build_live_instructions(
        make_settings(tmp_path), registry=None, gallery_ids=[], knowledge_dir=tmp_path
    )
    assert "HOW YOU WORK" in live


async def test_the_vision_model_gets_the_edited_prompt() -> None:
    llm = FakeVisionLLM()
    assert BOOK.set("vision", "Count the people. Nothing else.") == []
    await VisionNarrator(llm).describe(Frame(data=b"x"))
    assert llm.requests[0][0] == {"role": "system", "content": "Count the people. Nothing else."}


# -- the panel ---------------------------------------------------------------


def _saved_prompts(state_file: str) -> object:
    return json.loads(Path(state_file).read_text(encoding="utf-8"))["prompts"]


async def test_the_panel_checks_saves_and_resets_a_prompt(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        await rig.conn()
        assert "prompts" in rig.control.capabilities

        ok, message = await rig.control.act(
            "check_prompt", {"id": "live_rules", "text": "Tools: {tools}"}
        )
        assert not ok and "{tools}" in message
        ok, message = await rig.control.act(
            "set_prompt", {"id": "live_rules", "text": "Tools: {tools}"}
        )
        assert not ok and BOOK.override("live_rules") is None

        ok, message = await rig.control.act(
            "set_prompt", {"id": "persona", "text": "You are Ada, a museum guide."}
        )
        assert ok and "next conversation" in message
        assert _saved_prompts(rig.settings.panel.state_file) == {
            "persona": "You are Ada, a museum guide."
        }

        # No restart of the orchestrator: the next conversation uses it.
        await rig.control.act("restart", {})
        conn2 = await rig.conn(2)
        assert conn2.start["session"]["instructions"].startswith("You are Ada, a museum guide.")

        ok, message = await rig.control.act("reset_prompt", {"id": "persona"})
        assert ok and "built-in" in message
        assert BOOK.override("persona") is None
        assert _saved_prompts(rig.settings.panel.state_file) == {}
        ok, message = await rig.control.act("reset_prompt", {"id": "persona"})
        assert ok and "already" in message


async def test_saving_the_built_in_text_is_a_reset(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        await rig.control.act("set_prompt", {"id": "vision", "text": "Count the people."})
        assert BOOK.override("vision") is not None
        ok, message = await rig.control.act(
            "set_prompt", {"id": "vision", "text": f"\n{NARRATOR_PROMPT}\n"}
        )
        assert ok and "built-in" in message and "next photo" in message
        assert BOOK.override("vision") is None


async def test_bad_requests_are_explained(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        assert await rig.control.act("set_prompt", {"id": "nope", "text": "x"}) == (
            False,
            "Unknown prompt.",
        )
        ok, message = await rig.control.act("set_prompt", {"id": "persona", "text": "  "})
        assert not ok and "Write something" in message


async def test_saved_texts_are_used_from_the_first_conversation(tmp_path: Path) -> None:
    state = PanelState(prompts={"backend_rules": "You run Ada's tools.", "live_rules": "{broken"})
    async with make_panel_rig(tmp_path, state=state) as rig:
        conn = await rig.conn()
        session = conn.start["session"]
        assert session["delegation"]["responses"]["instructions"].startswith("You run Ada's tools.")
        assert "HOW YOU WORK" in session["instructions"]  # the broken one is ignored
        entry = {e["id"]: e for e in rig.control.prompts()}["live_rules"]
        assert entry["ignored"] and entry["text"] == "{broken"


async def test_the_server_lists_the_prompts(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig, running_panel(rig) as (host, _):
        await rig.control.act("set_prompt", {"id": "vision", "text": "Count the people."})
        async with httpx.AsyncClient(base_url=f"http://{host}") as http:
            response = await http.get("/api/prompts")
    assert response.headers["cache-control"] == "no-store"
    prompts = {entry["id"]: entry for entry in response.json()["prompts"]}
    assert list(prompts) == list(BOOK.ids())
    vision = prompts["vision"]
    assert vision["edited"] and vision["text"] == "Count the people."
    assert vision["default"] == NARRATOR_PROMPT and vision["applies"] == "request"
    assert prompts["live_rules"]["fields"] == list(LIVE_RULE_FIELDS)
    assert prompts["live_rules"]["required"] == ["capabilities"]
