"""The protocol's JSON Schema (``docs/protocol.schema.json``) as a test helper.

``conftest.py`` uses :func:`check_server_message` to validate every message the
orchestrator builds anywhere in the test suite, so the schema, the document and
the code cannot drift apart without a test failing.
"""

from __future__ import annotations

import json
from functools import cache
from typing import Any

from jsonschema import Draft202012Validator

from sonia.paths import REPO_ROOT

SCHEMA_PATH = REPO_ROOT / "docs" / "protocol.schema.json"


@cache
def schema() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return loaded


def _refs(group: str) -> list[str]:
    return [ref["$ref"].rsplit("/", 1)[1] for ref in schema()["$defs"][group]["oneOf"]]


@cache
def server_types() -> frozenset[str]:
    """Message types the orchestrator sends to the client."""
    return frozenset(_refs("serverMessage"))


@cache
def client_types() -> frozenset[str]:
    """Message types the client sends to the orchestrator."""
    return frozenset(_refs("clientMessage"))


@cache
def validator(name: str = "") -> Draft202012Validator:
    """Validator for one ``$defs`` entry (a message type), or for any message."""
    root = schema()
    target = {"$ref": f"#/$defs/{name}"} if name else {"oneOf": root["oneOf"]}
    return Draft202012Validator({**target, "$defs": root["$defs"]})


def problems(msg: Any, name: str = "") -> list[str]:
    """Every reason ``msg`` does not match the schema (empty: it matches).

    Without ``name`` the message is checked against its own type when the schema knows
    it (clearer errors than the root's "not valid under any of the given schemas").
    """
    kind = msg.get("type") if isinstance(msg, dict) else None
    if not name and kind in server_types() | client_types():
        name = str(kind)
    return [
        f"{'/'.join(map(str, error.absolute_path)) or '(message)'}: {error.message}"
        for error in validator(name).iter_errors(msg)
    ]


def check_server_message(msg: Any) -> None:
    """Fails if ``msg`` is not a valid orchestrator → client message."""
    kind = msg.get("type") if isinstance(msg, dict) else None
    assert kind in server_types(), f"not an orchestrator → client message type: {msg!r:.200}"
    found = problems(msg, str(kind))
    assert not found, f"{kind} does not match docs/protocol.schema.json: {found} in {msg!r:.300}"
