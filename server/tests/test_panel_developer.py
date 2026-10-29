"""The panel page, including its "Developer" card. No browser: ``index.html`` and
``panel.js`` are read exactly as they are served."""

from __future__ import annotations

import re
from html.parser import HTMLParser

from sonia.panel.server import STATIC_DIR

PAGE = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
SCRIPT = (STATIC_DIR / "panel.js").read_text(encoding="utf-8")

#: Void elements: they do not open a nesting level.
_VOID = {"area", "br", "col", "hr", "img", "input", "link", "meta", "source", "wbr"}


class _Tree(HTMLParser):
    """For each element with an ``id``: its attributes and the ``id`` of its ancestors."""

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[tuple[str, str | None]] = []
        self.attrs: dict[str, dict[str, str | None]] = {}
        self.tags: dict[str, str] = {}
        self.parents: dict[str, list[str]] = {}
        self.ids: list[str] = []

    def _record(self, tag: str, attrs: list[tuple[str, str | None]]) -> str | None:
        values = dict(attrs)
        element_id = values.get("id")
        if element_id:
            self.ids.append(element_id)
            self.attrs[element_id] = values
            self.tags[element_id] = tag
            self.parents[element_id] = [i for _, i in self.stack if i]
        return element_id

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        element_id = self._record(tag, attrs)
        if tag not in _VOID:
            self.stack.append((tag, element_id))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._record(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return


def _tree() -> _Tree:
    tree = _Tree()
    tree.feed(PAGE)
    return tree


def _section(element_id: str) -> str:
    """The HTML of the ``<section>`` or ``<details>`` with that ``id``, up to its closing tag."""
    match = re.search(rf'<(section|details)[^>]*\sid="{element_id}"', PAGE)
    assert match, element_id
    tag = match.group(1)
    depth = 0
    for token in re.finditer(rf"<(/?){tag}\b", PAGE[match.start() :]):
        depth += -1 if token.group(1) else 1
        if depth == 0:
            return PAGE[match.start() : match.start() + token.end()]
    raise AssertionError(f"{element_id} is not closed")


def test_panel_ids_exist_and_are_unique() -> None:
    """Everything ``collectElements`` looks up by id is on the page, exactly once."""
    tree = _tree()
    duplicated = {i for i in tree.ids if tree.ids.count(i) > 1}
    assert not duplicated
    listed = re.search(r"const ids = \[(.*?)\];", SCRIPT, re.S)
    assert listed
    wanted = re.findall(r'"([a-z0-9-]+)"', listed.group(1))
    assert "avatar-input" in wanted and "gallery-upload-btn" in wanted
    assert [i for i in wanted if i not in tree.attrs] == []
