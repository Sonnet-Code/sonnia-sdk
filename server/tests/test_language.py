"""The ``LANGUAGE`` setting: the language files, what the models are told and the screen
texts the orchestrator uses and sends to the avatar client. No network."""

from __future__ import annotations

import json
import logging
import random
import re
from datetime import date
from pathlib import Path

import pytest

import sonia.live.engine as engine_module
from sonia.config import Settings
from sonia.demo import DemoContent, DemoDirector
from sonia.language import (
    BUNDLED_LANGUAGES_DIR,
    DEFAULT_LANGUAGE,
    available_languages,
    describe_languages,
    load_language,
    read_dates,
    read_language_file,
    text_placeholders,
)
from sonia.live.prompts import build_backend_instructions, build_live_instructions
from sonia.panel.control import DEFAULT_AWAY_MESSAGE, PanelState
from sonia.paths import BUNDLE_ROOT, REPO_ROOT
from sonia.ws import protocol as p
from tests.test_demo import FakeLink
from tests.test_live import _busy, _delegation_created, make_rig, make_settings
from tests.test_panel import make_panel_rig

SCREEN_TEXTS_CS = REPO_ROOT / "unity" / "Assets" / "Scripts" / "Sonia" / "ScreenTexts.cs"


def _english() -> dict[str, str]:
    return read_language_file(BUNDLED_LANGUAGES_DIR / "en.json")[2]


def _write(folder: Path, code: str, data: object) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{code}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


# -- the files ---------------------------------------------------------------


def test_the_bundled_languages() -> None:
    assert list(available_languages()) == ["de", "en", "es", "fr", "pt"]
    assert "es (Español)" in describe_languages()


@pytest.mark.parametrize("code", sorted(available_languages()))
def test_every_bundled_file_has_every_text_with_its_placeholders(code: str) -> None:
    name, native, texts = read_language_file(BUNDLED_LANGUAGES_DIR / f"{code}.json")
    assert name.isascii() and native
    english = _english()
    assert texts.keys() == english.keys()
    for key, text in texts.items():
        assert text_placeholders(text) == text_placeholders(english[key]), key
    # Loading it changes nothing: nothing was missing.
    assert dict(load_language(code).texts) == texts


def test_the_unity_client_has_the_english_texts_built_in() -> None:
    source = SCREEN_TEXTS_CS.read_text(encoding="utf-8")
    names = dict(re.findall(r'public const string (\w+) = "(\w+)";', source))
    built_in: dict[str, str] = {}
    for name, suffix, value in re.findall(
        r'\[(\w+)(?: \+ "(\w+)")?\] = "((?:[^"\\]|\\.)*)"', source
    ):
        built_in[names[name] + suffix] = value.replace("\\n", "\n")
    assert built_in == _english()


def test_the_documented_languages_are_the_bundled_ones() -> None:
    doc = (REPO_ROOT / "docs" / "configuration.md").read_text(encoding="utf-8")
    assert "``LANGUAGE``" in doc or "`LANGUAGE`" in doc
    for code in available_languages():
        assert f"``{code}``" in doc or f"`{code}`" in doc, code


# -- loading -----------------------------------------------------------------


def test_a_language_and_its_texts() -> None:
    spanish = load_language("es")
    assert (spanish.code, spanish.name, spanish.native_name) == ("es", "Spanish", "Español")
    assert spanish.text("trivia_counter", number=2, total=5) == "PREGUNTA 2 DE 5"
    assert spanish.text("nope") == ""
    assert load_language("").code == DEFAULT_LANGUAGE


def test_an_unknown_language_falls_back_to_english(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        language = load_language("xx")
    assert language.code == "en" and language.name == "English"
    assert "LANGUAGE=xx" in caplog.text


def test_a_file_in_the_assets_folder_wins_and_gaps_are_english(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _write(
        tmp_path / "languages",
        "es",
        {
            "name": "Spanish",
            "texts": {
                "invitation": "¡Hola, ven!",
                "trivia_counter": "PREGUNTA {number}",  # lost {total}: not used
                "made_up": "ignored by the client",
            },
        },
    )
    with caplog.at_level(logging.WARNING):
        language = load_language("es", tmp_path)
    assert language.text("invitation") == "¡Hola, ven!"
    assert language.native_name == "Spanish"
    english = _english()
    assert language.text("trivia_counter") == english["trivia_counter"]
    assert language.text("you") == english["you"]
    assert "made_up" not in language.texts
    assert "trivia_counter" in caplog.text


def test_a_new_language_can_be_added_without_code(tmp_path: Path) -> None:
    texts = dict(_english(), invitation="Avvicinati e chiedimi\nquello che vuoi!")
    _write(
        tmp_path / "languages", "it", {"name": "Italian", "native_name": "Italiano", "texts": texts}
    )
    assert "it" in available_languages(tmp_path)
    assert load_language("it", tmp_path).name == "Italian"


@pytest.mark.parametrize(
    "content",
    ["not json", "[]", '{"texts": {}}', '{"name": "Spanish", "texts": []}'],
)
def test_a_broken_file_falls_back_to_english(tmp_path: Path, content: str) -> None:
    (tmp_path / "languages").mkdir()
    (tmp_path / "languages" / "es.json").write_text(content, encoding="utf-8")
    assert load_language("es", tmp_path).code == "en"


def test_the_setting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGUAGE", "fr")
    settings = Settings(_env_file=None, assets_dir=str(tmp_path))  # type: ignore[call-arg]
    assert settings.language == "fr"
    assert settings.load_language().text("you") == "TOI"
    assert BUNDLE_ROOT / "assets" / "languages" == BUNDLED_LANGUAGES_DIR


# -- the models --------------------------------------------------------------


def test_the_models_are_told_the_default_language(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, language="es")
    live = build_live_instructions(settings, registry=None, gallery_ids=[])
    assert "Speak Spanish by default; if someone speaks to you in another language" in live
    assert "English" not in live
    backend = build_backend_instructions(gallery_ids=[], language="Spanish")
    assert "\n\nDefault language: Spanish.\n\n" in backend


async def test_the_session_carries_the_language_to_both_models(tmp_path: Path) -> None:
    async with make_rig(tmp_path, language="de") as rig:
        conn = await rig.conn()
        session = conn.start["session"]
        assert "Speak German by default" in session["instructions"]
        backend = session["delegation"]["responses"]["instructions"]
        assert "Default language: German." in backend


# -- the screen --------------------------------------------------------------


async def test_the_client_gets_the_screen_texts_and_a_waiting_pill_in_the_language(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine_module, "THINK_DELAY_S", 0.0)
    async with make_rig(tmp_path, language="es") as rig:
        assert rig.rec.of_type("screen_texts") == [
            p.msg_screen_texts("es", load_language("es").texts)
        ]
        assert rig.hub.sticky("screen_texts") == rig.rec.of_type("screen_texts")[0]
        conn = await rig.conn()
        await conn.send(_delegation_created())
        await rig.rec.wait_for(lambda _: _busy(rig) == ["Pensando…"])


async def test_the_default_away_sign_is_in_the_language(tmp_path: Path) -> None:
    # The English default saved by an older version counts as "never changed".
    state = PanelState(mode="away", away_message=DEFAULT_AWAY_MESSAGE)
    async with make_panel_rig(tmp_path, state=state, language="pt") as rig:
        await rig.rec.wait_type("presence")
        assert rig.rec.of_type("presence")[-1]["message"] == "Volto em alguns minutos"
        ok, _ = await rig.control.act("set_away_message", {"text": "No almoço"})
        assert ok
        await rig.rec.wait_type("presence", count=2)
        assert rig.rec.of_type("presence")[-1]["message"] == "No almoço"


async def test_the_offline_demo_uses_the_screen_texts() -> None:
    link = FakeLink()
    content = DemoContent.load(BUNDLE_ROOT / "assets", random.Random(1))
    await DemoDirector(link, content, time_scale=0, seed=1, language=load_language("fr")).run(
        loops=1
    )
    texts = {m["text"] for m in link.messages if m["type"] == p.MSG_BUSY and m["on"]}
    assert texts == {"Je réfléchis…", "Recherche sur le web…"}


def test_each_language_writes_a_day(tmp_path: Path) -> None:
    friday = date(2026, 11, 20)
    assert load_language("en").date(friday) == "Friday 20 November"
    assert load_language("es").date(friday) == "viernes 20 de noviembre"
    assert load_language("fr").date(friday) == "vendredi 20 novembre"
    assert load_language("pt").date(friday) == "sexta-feira, 20 de novembro"
    assert load_language("de").date(friday) == "Freitag, 20. November"
    # A file without dates, or with wrong ones, writes days in English.
    languages = tmp_path / "languages"
    languages.mkdir()
    (languages / "it.json").write_text(
        json.dumps({"name": "Italian", "texts": {"you": "TU"}}), encoding="utf-8"
    )
    (languages / "nl.json").write_text(
        json.dumps(
            {
                "name": "Dutch",
                "texts": {},
                "dates": {"format": "{day} {month}", "weekdays": [], "months": []},
            }
        ),
        encoding="utf-8",
    )
    assert load_language("it", tmp_path).date(friday) == "Friday 20 November"
    assert load_language("nl", tmp_path).date(friday) == "Friday 20 November"
    assert read_dates(languages / "nl.json") is None
