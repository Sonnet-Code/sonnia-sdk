"""Tests of the on-screen waiting indicator (``sonia.busy``), without a client or network."""

from __future__ import annotations

from typing import Any

import pytest

from sonia.busy import TEXT_SEARCH, TEXT_THINK, BusyBoard
from sonia.ws import protocol as p


class Sent:
    """What the board sends to the client."""

    def __init__(self) -> None:
        self.msgs: list[dict[str, Any]] = []

    async def __call__(self, msg: dict[str, Any]) -> None:
        self.msgs.append(msg)


def on(kind: str, text: str) -> dict[str, Any]:
    return p.msg_busy(True, kind, text)


OFF = p.msg_busy(False)


async def test_sends_the_highest_priority_wait() -> None:
    sent = Sent()
    board = BusyBoard(sent)
    await board.set("live:search:a", "search", TEXT_SEARCH)
    # A lower-priority one that arrives later does not cover the visible one.
    await board.set("live:think:a", "think", TEXT_THINK)
    assert board.current() == ("search", TEXT_SEARCH)
    assert sent.msgs == [on("search", TEXT_SEARCH)]
    # When the search ends, the next one in priority.
    await board.clear("live:search:a")
    assert sent.msgs[-1] == on("think", TEXT_THINK)
    await board.clear("live:think:a")
    assert sent.msgs[-1] == OFF
    assert board.current() is None and board.keys == ()


async def test_among_equals_the_most_recent_is_shown() -> None:
    sent = Sent()
    board = BusyBoard(sent)
    await board.set("live:think:a", "think", "Thinking A…")
    await board.set("live:think:b", "think", "Thinking B…")
    assert board.current() == ("think", "Thinking B…")
    # Setting a key again makes it the most recent (and changes the text).
    await board.set("live:think:a", "think", "Thinking A…")
    assert board.current() == ("think", "Thinking A…")
    await board.clear("live:think:a")
    assert board.current() == ("think", "Thinking B…")
    assert [m.get("text") for m in sent.msgs] == [
        "Thinking A…",
        "Thinking B…",
        "Thinking A…",
        "Thinking B…",
    ]


async def test_does_not_repeat_what_is_already_shown() -> None:
    sent = Sent()
    board = BusyBoard(sent)
    await board.set("live:think:a", "think", TEXT_THINK)
    await board.set("live:think:b", "think", TEXT_THINK)
    await board.clear("live:think:a")
    await board.clear("was-not-there")
    assert sent.msgs == [on("think", TEXT_THINK)]
    await board.clear("live:think:b")
    await board.clear("live:think:b")
    assert sent.msgs == [on("think", TEXT_THINK), OFF]


async def test_clear_prefix_turns_off_a_group() -> None:
    sent = Sent()
    board = BusyBoard(sent)
    await board.set("other:think:a", "think", TEXT_THINK)
    await board.set("live:think:a", "think", TEXT_THINK)
    await board.set("live:search:a", "search", TEXT_SEARCH)
    await board.clear_prefix("live:")
    assert board.keys == ("other:think:a",)
    assert sent.msgs[-1] == on("think", TEXT_THINK)
    # A prefix without keys sends nothing.
    count = len(sent.msgs)
    await board.clear_prefix("missing:")
    assert len(sent.msgs) == count
    # With "", all of them.
    await board.clear_prefix("")
    assert board.keys == () and sent.msgs[-1] == OFF


async def test_message_repeats_it_on_reconnect() -> None:
    board = BusyBoard()
    assert board.message() == OFF
    await board.set("live:search:a", "search", TEXT_SEARCH)
    assert board.message() == on("search", TEXT_SEARCH)


async def test_a_send_failure_breaks_nothing(caplog: pytest.LogCaptureFixture) -> None:
    calls: list[dict[str, Any]] = []

    async def broken(msg: dict[str, Any]) -> None:
        calls.append(msg)
        raise ConnectionError("the client went away")

    board = BusyBoard(broken)
    await board.set("live:think:a", "think", TEXT_THINK)
    assert board.current() == ("think", TEXT_THINK)
    assert "Could not send" in caplog.text
    # It keeps counting and, with another destination, sends the next change.
    sent = Sent()
    board.bind(sent)
    await board.clear("live:think:a")
    assert len(calls) == 1 and sent.msgs == [OFF]


async def test_without_destination_it_only_keeps_count() -> None:
    board = BusyBoard()
    await board.set("live:think:a", "think", TEXT_THINK)
    assert board.keys == ("live:think:a",)
    await board.clear("live:think:a")
    assert board.current() is None


def test_unknown_kind_is_rejected() -> None:
    with pytest.raises(ValueError):
        p.msg_busy(True, "loading", "…")
