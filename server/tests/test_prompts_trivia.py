"""The trivia texts for the realtime model, as snapshots.

``snapshots/prompts_trivia.json`` holds everything the realtime model gets in several
games (instructions, ``commentary`` and the action scripts): changing a text is always
deliberate and reviewed in the diff. No network and no real GPT-Live: a fake engine
and screen that record everything in order.
"""

from __future__ import annotations

import asyncio
import random
from pathlib import Path
from typing import Any

from sonia.actions import build_default_registry
from sonia.config import TriviaSettings
from sonia.live.client import APPEND_MAX_CHARS
from sonia.trivia import PASS, TriviaGame
from sonia.trivia.game import NUDGE_S
from sonia.types import ActionContext
from tests.prompt_snapshots import assert_snapshot

#: Its own bank (not the repository one, which can change): four questions, one with a
#: fact and one per level, so the games of the snapshots do not change with the bank.
BANK = """\
## [easy] Which language is used to style web pages?
- [x] CSS
- [ ] SQL
- [ ] Bash
> CSS stands for Cascading Style Sheets.

## Which protocol do web browsers use to load pages?
- [ ] FTP
- [x] HTTP
- [ ] SMTP

## [hard] In which year was the first version of Python released?
- [ ] 1985
- [x] 1991
- [ ] 2000
> Guido van Rossum published it in February 1991.

## What does the "I" in AI stand for?
- [ ] Internet
- [ ] Interface
- [x] Intelligence
"""


class LogHost:
    """The realtime engine as the game sees it: it records everything it gets, in order."""

    def __init__(self, log: list[list[Any]]) -> None:
        self.log = log
        self.connected = True
        self.quiet = 10.0

    def quiet_for(self) -> float:
        return self.quiet

    async def speak(self, prompt: str) -> bool:
        self.log.append(["speak", prompt])
        return True

    async def instruct(self, text: str) -> bool:
        self.log.append(["instruct", text])
        return True

    async def wait_idle(self, limit_s: float | None = None) -> bool:
        return True

    def touch(self) -> None:
        pass


class NullScreen:
    """The avatar client screen: what it gets does not matter here."""

    async def broadcast_json(self, msg: dict[str, Any]) -> None:
        pass

    async def set_sticky(self, key: str, msg: dict[str, Any]) -> None:
        pass

    def clear_sticky(self, key: str) -> None:
        pass

    async def hide_image(self) -> None:
        pass


def make_game(
    tmp_path: Path, *, questions: int = 3, threshold: int = 2, **overrides: Any
) -> tuple[TriviaGame, LogHost, list[list[Any]]]:
    bank = tmp_path / "questions.md"
    bank.write_text(BANK, encoding="utf-8")
    values: dict[str, Any] = {
        "reveal_seconds": 0.0,
        "final_wait_seconds": 0.0,
        "win_contact": "the people at the front desk",
        **overrides,
    }
    settings = TriviaSettings(questions=questions, win_threshold=threshold, **values)
    log: list[list[Any]] = []
    host = LogHost(log)
    game = TriviaGame(settings, bank, host=host, screen=NullScreen(), rng=random.Random(7))
    return game, host, log


async def settle() -> None:
    """Lets the game tasks run (``reveal_seconds`` is 0)."""
    for _ in range(5):
        await asyncio.sleep(0)


def right(game: TriviaGame) -> int:
    question = game._current
    assert question is not None
    return question.correct


def wrong(game: TriviaGame) -> int:
    return (right(game) + 1) % 3


async def call(log: list[list[Any]], name: str, result: Any) -> None:
    """Records what a game call returns (a script or a text for the operator)."""
    if isinstance(result, tuple):
        log.append([name, *result])
    else:
        log.append([name, result])


async def flow_wins_with_contact(tmp_path: Path) -> list[list[Any]]:
    game, _, log = make_game(tmp_path)
    await call(log, "start", await game.start("voice", "easy"))
    await call(log, "answer", await game.answer(right(game), "voice"))
    await call(log, "next", await game.next("voice"))
    await call(log, "answer", await game.answer(wrong(game), "voice"))
    await call(log, "next", await game.next("voice"))
    await call(log, "answer", await game.answer(right(game), "voice"))
    # The last one answered and before the final screen.
    await call(log, "resume", await game.resume())
    await call(log, "answer", await game.answer(0, "voice"))
    await call(log, "next", await game.next("voice"))
    await settle()
    await call(log, "resume", await game.resume())
    return log


async def flow_loses(tmp_path: Path) -> list[list[Any]]:
    game, _, log = make_game(tmp_path)
    await call(log, "start", await game.start("voice"))
    await call(log, "next", await game.next("voice"))
    await call(log, "answer", await game.answer(PASS, "voice"))
    await call(log, "answer", await game.answer(0, "voice"))
    await call(log, "resume", await game.resume())
    await call(log, "next", await game.next("voice"))
    await call(log, "resume", await game.resume())
    await call(log, "answer", await game.answer(wrong(game), "voice"))
    await call(log, "next", await game.next("voice"))
    await call(log, "answer", await game.answer(right(game), "voice"))
    await settle()
    return log


async def flow_wins_without_contact(tmp_path: Path) -> list[list[Any]]:
    game, _, log = make_game(tmp_path, questions=1, threshold=1, win_contact="")
    await call(log, "start", await game.start("voice", "hard"))
    await call(log, "answer", await game.answer(right(game), "voice"))
    await settle()
    return log


async def flow_change_level(tmp_path: Path) -> list[list[Any]]:
    game, _, log = make_game(tmp_path)
    await call(log, "start", await game.start("voice", "easy"))
    # Another level before answering.
    await call(log, "restart", await game.restart("voice", "hard"))
    await call(log, "resume", await game.resume())
    await call(log, "restart", await game.restart("voice", "medium"))
    await call(log, "answer", await game.answer(right(game), "voice"))
    # Once one is answered, restarting is a new game from scratch.
    await call(log, "restart", await game.restart("voice"))
    await call(log, "stop", await game.stop("voice"))
    await call(log, "resume", await game.resume())
    return log


async def flow_panel(tmp_path: Path) -> list[list[Any]]:
    game, _, log = make_game(tmp_path)
    await call(log, "start", await game.start("panel", "easy"))
    await settle()
    await call(log, "restart", await game.restart("panel", "hard"))
    await settle()
    await call(log, "answer", await game.answer(wrong(game), "panel"))
    await call(log, "next", await game.next("panel"))
    await settle()
    await call(log, "answer", await game.answer(PASS, "panel"))
    await call(log, "restart", await game.restart("panel"))
    await settle()
    await call(log, "stop", await game.stop("panel"))
    return log


async def flow_ticks(tmp_path: Path) -> list[list[Any]]:
    game, host, log = make_game(tmp_path, remind_seconds=20.0, abandon_seconds=60.0)
    await call(log, "start", await game.start("voice"))
    host.quiet = 1000.0
    start = game._asked_at
    await game.tick(start + 21)  # reminds the question
    await settle()
    game.on_user_turn_end(start + 22, start + 21)  # spoke and nothing was delegated
    await game.tick(start + 22 + NUDGE_S + 1)
    await settle()
    await game.tick(start + 70)  # gone: game abandoned
    await settle()
    return log


async def flow_actions(tmp_path: Path) -> list[list[Any]]:
    """What the backend gets as the result of each action (with ``FOR SONIA:``)."""
    game, _, log = make_game(tmp_path)
    registry = build_default_registry(include_look=False, include_trivia=True)
    ctx = ActionContext(camera=None, avatar=None, gallery_dir="", extra={"trivia": game})

    async def run(name: str, arguments: dict[str, Any]) -> None:
        result = await registry.execute(name, arguments, ctx)
        log.append([name, result.text])

    await run("start_trivia", {"level": "not_chosen"})
    await run("start_trivia", {"level": "not_chosen"})
    await run("trivia_answer", {"option": "ABC"[right(game)]})
    await run("trivia_next", {})
    await run("trivia_answer", {"option": "dont_know"})
    await run("restart_trivia", {"level": "hard"})
    await run("stop_trivia", {})
    await run("start_trivia", {"level": "easy"})
    await run("trivia_answer", {"option": "ABC"[wrong(game)]})
    await run("stop_trivia", {})
    await settle()
    return log


async def all_flows(tmp_path: Path) -> dict[str, list[list[Any]]]:
    flows = {
        "wins_with_contact": flow_wins_with_contact,
        "loses": flow_loses,
        "wins_without_contact": flow_wins_without_contact,
        "change_level": flow_change_level,
        "panel": flow_panel,
        "ticks": flow_ticks,
        "actions": flow_actions,
    }
    out: dict[str, list[list[Any]]] = {}
    for name, flow in flows.items():
        folder = tmp_path / name
        folder.mkdir()
        out[name] = await flow(folder)
    return out


async def test_what_the_realtime_model_gets_matches_the_snapshot(tmp_path: Path) -> None:
    assert_snapshot("prompts_trivia", await all_flows(tmp_path))


async def test_instructions_fit_in_an_append(tmp_path: Path) -> None:
    flows = await all_flows(tmp_path)
    for log in flows.values():
        for entry in log:
            if entry[0] in ("instruct", "speak"):
                assert len(entry[1]) <= APPEND_MAX_CHARS, entry[1][:80]
