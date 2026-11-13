"""Settings common to all tests: no network and no touching the machine's cache."""

from __future__ import annotations

import functools
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _separate_devices(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A test's microphone and camera choice does not touch the machine's."""
    monkeypatch.setenv("DEVICES_FILE", str(tmp_path / "devices.json"))


@pytest.fixture(autouse=True)
def _separate_gallery_uploads(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Images a test uploads to the gallery do not go to the machine's ``cache/gallery``."""
    monkeypatch.setenv("GALLERY_UPLOAD_DIR", str(tmp_path / "gallery-uploads"))


@pytest.fixture(autouse=True)
def _built_in_prompts() -> Iterator[None]:
    """Texts a test edits from the prompt editor do not reach the next test."""
    from sonia.prompt_book import BOOK, use_knowledge_dirs

    yield
    BOOK.load({})
    use_knowledge_dirs(None)


@pytest.fixture(autouse=True)
def _protocol_contract(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every message the orchestrator builds or sends must match docs/protocol.schema.json.

    The ``msg_*`` builders and ``dumps`` (what the hub puts on the wire) are wrapped for
    the whole suite, so any test that exercises a feature also checks its messages
    against the protocol. A test that builds a broken message on purpose opts out with
    ``@pytest.mark.protocol_unchecked``.
    """
    if request.node.get_closest_marker("protocol_unchecked"):
        return
    from sonia.ws import protocol as p
    from tests.protocol_contract import check_server_message

    def checked(build: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
        @functools.wraps(build)
        def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
            msg = build(*args, **kwargs)
            check_server_message(msg)
            return msg

        return wrapper

    for name in dir(p):
        if name.startswith("msg_"):
            monkeypatch.setattr(p, name, checked(getattr(p, name)))

    original_dumps = p.dumps

    def dumps(msg: dict[str, Any]) -> str:
        check_server_message(msg)
        return original_dumps(msg)

    monkeypatch.setattr(p, "dumps", dumps)
