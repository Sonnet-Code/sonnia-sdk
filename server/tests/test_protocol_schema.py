"""Contract tests: docs/protocol.schema.json, docs/protocol.md, the code and the Unity client agree."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from sonia.paths import REPO_ROOT
from sonia.ws import protocol as p
from tests.protocol_contract import (
    SCHEMA_PATH,
    client_types,
    problems,
    schema,
    server_types,
)

DOC = REPO_ROOT / "docs" / "protocol.md"
UNITY_PROTOCOL = REPO_ROOT / "unity" / "Assets" / "Scripts" / "Sonia" / "Protocol.cs"


def test_the_schema_is_valid_json_schema() -> None:
    Draft202012Validator.check_schema(schema())
    assert SCHEMA_PATH.read_text(encoding="utf-8").endswith("}\n")


def test_every_message_type_is_in_the_schema_once() -> None:
    constants = {getattr(p, name) for name in dir(p) if name.startswith("MSG_")}
    assert not server_types() & client_types()
    assert server_types() | client_types() == constants
    # Whatever the orchestrator sends has a builder; what it receives does not.
    builders = {name.removeprefix("msg_") for name in dir(p) if name.startswith("msg_")}
    assert server_types() == builders


def test_the_unity_client_knows_the_same_messages() -> None:
    source = UNITY_PROTOCOL.read_text(encoding="utf-8")
    block = source.split("class MessageTypes", 1)[1].split("\n    }", 1)[0]
    incoming, outgoing = block.split("// From Unity to the orchestrator.", 1)
    names = re.compile(r'const string \w+ = "(\w+)";')
    assert set(names.findall(incoming)) == server_types()
    assert set(names.findall(outgoing)) == client_types()


def _doc_examples() -> list[dict[str, Any]]:
    text = DOC.read_text(encoding="utf-8")
    blocks = re.findall(r"```json\n(.*?)```", text, re.DOTALL)
    # Payloads are abbreviated as "..." in the document: an empty payload stands in.
    lines = [line for block in blocks for line in block.splitlines() if line.strip()]
    return [json.loads(line.replace('"..."', '""')) for line in lines]


def test_every_example_in_the_document_matches_the_schema() -> None:
    examples = _doc_examples()
    assert len(examples) >= 30
    for example in examples:
        assert problems(example) == [], example


def test_the_document_covers_every_message() -> None:
    text = DOC.read_text(encoding="utf-8")
    missing = sorted(t for t in server_types() | client_types() if f"`{t}`" not in text)
    assert missing == []


# -- builders --------------------------------------------------------------

#: At least one call per builder, with the optional variants.
BUILDS: list[tuple[str, Callable[[], dict[str, Any]]]] = [
    ("hello", lambda: p.msg_hello(16_000)),
    ("state", lambda: p.msg_state("thinking")),
    ("transcript", lambda: p.msg_transcript("user", "hi", final=False)),
    ("speech_start", lambda: p.msg_speech_start(0, "")),
    ("speech_start ambient", lambda: p.msg_speech_start(3, "Hello", ambient=True)),
    ("attention", lambda: p.msg_attention("fourth_wall")),
    ("attention clip", lambda: p.msg_attention("dance", "Dance_1")),
    ("play_animation", lambda: p.msg_play_animation("Wave")),
    ("play_animation whole", lambda: p.msg_play_animation("Wave", whole=True)),
    ("show_emotion", lambda: p.msg_show_emotion("surprise", 3)),
    ("show_emotion clamped", lambda: p.msg_show_emotion("joy", 60)),
    ("speech_end", lambda: p.msg_speech_end(3)),
    ("stop_speaking", lambda: p.msg_stop_speaking()),
    ("show_image", lambda: p.msg_show_image("logo", "gallery", "image/png", b"\x89PNG")),
    ("show_image caption", lambda: p.msg_show_image("a", "gallery", "image/jpeg", b"", "Hi")),
    ("show_talk", lambda: p.msg_show_talk("t1", "Intro", status="now", when="Friday 20 November")),
    (
        "show_talk full",
        lambda: p.msg_show_talk(
            "t2", "Rust", status="later", when="x", speakers=["Ada"], place="Room 2", tags=["a"]
        ),
    ),
    ("hide_image", p.msg_hide_image),
    ("error", lambda: p.msg_error("oops")),
    ("presence", lambda: p.msg_presence(False, "Back soon")),
    ("stage_mode", lambda: p.msg_stage_mode("away", False)),
    ("screen_texts", lambda: p.msg_screen_texts("es", {"you": "TÚ", "invitation": "¡Hola!"})),
    (
        "devices",
        lambda: p.msg_devices(
            microphones=[{"name": "Mic", "default": True}],
            microphone="",
            default_microphone="Mic",
            camera=0,
            camera_source="opencv",
        ),
    ),
    ("set_volume", lambda: p.msg_set_volume(9)),
    ("set_subtitles", lambda: p.msg_set_subtitles(True)),
    ("set_disabled_animations", lambda: p.msg_set_disabled_animations(["b", "a", "b"])),
    ("set_debug", lambda: p.msg_set_debug(False)),
    ("set_tuning empty", lambda: p.msg_set_tuning({})),
    (
        "set_tuning",
        lambda: p.msg_set_tuning(
            {
                "mouth": {"open": 1.2, "jaw": 1, "closure": 1, "speed": 1},
                "camera": {"height": 0.1, "distance": 0, "side": 0, "zoom": 1.1, "tilt": -2},
                "idle": {"breath": 1, "accents": 0.5, "speed": 1},
            }
        ),
    ),
    ("set_avatar default", lambda: p.msg_set_avatar(None)),
    ("set_avatar", lambda: p.msg_set_avatar('{"JsonVersion": "1"}')),
    ("trivia_start", lambda: p.msg_trivia_start(5, 3, "easy")),
    ("trivia_question", lambda: p.msg_trivia_question(1, 5, "Q?", ["a", "b", "c"], 0)),
    ("trivia_answer", lambda: p.msg_trivia_answer(1, -1, 2, False, 0)),
    ("trivia_end", lambda: p.msg_trivia_end(0, 5, won=False, reason="cancelled")),
    ("activity", lambda: p.msg_activity("search")),
    ("busy on", lambda: p.msg_busy(True, "think", "Thinking…")),
    ("busy off", lambda: p.msg_busy(False)),
    ("request_frame", p.msg_request_frame),
]


@pytest.mark.parametrize("build", [b for _, b in BUILDS], ids=[name for name, _ in BUILDS])
def test_builders_produce_valid_messages(build: Callable[[], dict[str, Any]]) -> None:
    msg = build()
    assert problems(msg, msg["type"]) == []


def test_every_builder_is_exercised_here() -> None:
    built = {name.split()[0] for name, _ in BUILDS}
    assert built == server_types()


def test_the_suite_checks_what_the_orchestrator_builds() -> None:
    # conftest wraps the builders: an off-protocol message fails wherever it is made.
    with pytest.raises(AssertionError, match="state does not match"):
        p.msg_state("dancing")


# -- the schema rejects what the protocol does not allow ---------------------


@pytest.mark.parametrize(
    "msg",
    [
        {"type": "state", "state": "idle", "extra": 1},
        {"type": "state"},
        {"type": "busy", "on": True, "kind": "think"},
        {"type": "busy", "on": False, "kind": "think", "text": ""},
        {"type": "speech_start", "utterance_id": -1, "text": ""},
        {"type": "speech_start", "utterance_id": 1, "text": "", "ambient": False},
        {
            "type": "trivia_question",
            "number": 1,
            "total": 3,
            "question": "?",
            "options": ["a", "b"],
            "score": 0,
        },
        {
            "type": "trivia_answer",
            "number": 1,
            "chosen": 3,
            "correct": 0,
            "is_correct": False,
            "score": 0,
        },
        {"type": "set_volume", "value": 2},
        {"type": "set_tuning", "mouth": {"smile": 1}, "camera": {}, "idle": {}},
        {
            "type": "show_image",
            "image_id": "x",
            "source": "camera",
            "mime": "image/png",
            "data_base64": "",
            "caption": None,
        },
        {
            "type": "show_talk",
            "talk_id": "t",
            "title": "T",
            "status": "soon",
            "when": "",
            "speakers": [],
            "place": "",
            "tags": [],
        },
        {
            "type": "show_talk",
            "talk_id": "t",
            "title": "",
            "status": "now",
            "when": "",
            "speakers": [],
            "place": "",
            "tags": [],
        },
        {"type": "set_device", "kind": "camera", "value": "1"},
        {"type": "animations", "animations": [{"clip": "Wave", "group": "party"}]},
        {"type": "nope"},
        {"state": "idle"},
    ],
)
def test_the_schema_rejects_off_protocol_messages(msg: dict[str, Any]) -> None:
    assert problems(msg) != []


@pytest.mark.parametrize(
    "msg",
    [
        {"type": "client_hello"},
        {"type": "client_hello", "client": "unity", "version": "1.0.0", "features": ["camera"]},
        {"type": "set_device", "kind": "microphone", "value": ""},
        {"type": "animation_playing", "clip": None},
        {"type": "playback_done", "utterance_id": 0},
    ],
)
def test_the_schema_accepts_client_messages(msg: dict[str, Any]) -> None:
    assert problems(msg) == []
