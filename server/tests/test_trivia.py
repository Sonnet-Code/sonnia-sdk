"""Trivia mode: question bank, game and actions, without network or a real GPT-Live."""

from __future__ import annotations

import asyncio
import random
from pathlib import Path
from typing import Any

from sonia.actions import build_default_registry
from sonia.actions.trivia import SCRIPT_PREFIX
from sonia.config import TriviaSettings
from sonia.trivia import (
    PASS,
    TriviaBank,
    TriviaGame,
    TriviaPhase,
    count_headings,
    parse_questions,
)
from sonia.trivia.game import STICKY_QUESTION, STICKY_START
from sonia.types import ActionContext

REPO_BANK = Path(__file__).resolve().parents[2] / "assets" / "trivia" / "questions.md"

BANK = """\
<!-- A comment that is ignored.
## This is not a question
- [x] Nor is this an option
-->
# Questions

## Question one?
- [x] Right one
- [ ] Wrong one
- [ ] Worse one
> Fact of question one.

## Question two?
- [ ] Wrong two
- [x] Right two
- [ ] Worse two

## Question three?
- [ ] Wrong three
- [ ] Worse three
- [X] Right three

## Malformed question without a right one?
- [ ] One
- [ ] Two
- [ ] Three

## Malformed question with two options?
- [x] One
- [ ] Two
"""


class FakeHost:
    """The realtime engine as the game sees it."""

    def __init__(self) -> None:
        self.connected = True
        self.quiet = 10.0
        self.spoken: list[str] = []
        self.instructions: list[str] = []
        self.touches = 0

    def quiet_for(self) -> float:
        return self.quiet

    async def speak(self, prompt: str) -> bool:
        self.spoken.append(prompt)
        return True

    async def instruct(self, text: str) -> bool:
        self.instructions.append(text)
        return True

    async def wait_idle(self, limit_s: float | None = None) -> bool:
        return True

    def touch(self) -> None:
        self.touches += 1


class FakeScreen:
    """The avatar client hub as the game sees it."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.sticky: dict[str, dict[str, Any]] = {}
        self.hidden = 0

    async def broadcast_json(self, msg: dict[str, Any]) -> None:
        self.sent.append(msg)

    async def set_sticky(self, key: str, msg: dict[str, Any]) -> None:
        self.sticky[key] = msg
        self.sent.append(msg)

    def clear_sticky(self, key: str) -> None:
        self.sticky.pop(key, None)

    async def hide_image(self) -> None:
        self.hidden += 1

    def of_type(self, kind: str) -> list[dict[str, Any]]:
        return [m for m in self.sent if m["type"] == kind]


def make_game(
    tmp_path: Path, *, questions: int = 3, threshold: int = 2, **overrides: Any
) -> tuple[TriviaGame, FakeHost, FakeScreen]:
    bank = tmp_path / "questions.md"
    bank.write_text(BANK, encoding="utf-8")
    values: dict[str, Any] = {
        "reveal_seconds": 0.0,
        "final_wait_seconds": 0.0,
        "win_contact": "the front desk",
        **overrides,
    }
    settings = TriviaSettings(questions=questions, win_threshold=threshold, **values)
    host, screen = FakeHost(), FakeScreen()
    game = TriviaGame(settings, bank, host=host, screen=screen, rng=random.Random(7))
    return game, host, screen


async def settle() -> None:
    """Lets the game tasks run (``reveal_seconds`` is 0)."""
    for _ in range(5):
        await asyncio.sleep(0)


def current(screen: FakeScreen) -> dict[str, Any]:
    return screen.sticky[STICKY_QUESTION]


def correct_index(game: TriviaGame) -> int:
    question = game._current
    assert question is not None
    return question.correct


# ---------------------------------------------------------------------------
# Bank
# ---------------------------------------------------------------------------


def test_the_bank_skips_malformed_questions_and_comments() -> None:
    questions = parse_questions(BANK)
    assert [q.text for q in questions] == ["Question one?", "Question two?", "Question three?"]
    assert [q.correct for q in questions] == [0, 1, 2]
    assert questions[0].fact == "Fact of question one."
    assert questions[1].fact == ""


def test_shuffling_keeps_the_right_answer() -> None:
    question = parse_questions(BANK)[1]
    rng = random.Random(3)
    for _ in range(20):
        shuffled = question.shuffled(rng)
        assert sorted(shuffled.options) == sorted(question.options)
        assert shuffled.options[shuffled.correct] == "Right two"


def test_it_counts_malformed_questions_but_not_commented_ones() -> None:
    assert count_headings(BANK) == 5
    assert len(TriviaBank.from_text(BANK, source="test")) == 3
    assert TriviaBank.from_text(BANK, source="test").levels() == {
        "easy": 0,
        "medium": 3,
        "hard": 0,
    }


def test_the_draw_does_not_repeat_until_the_level_runs_out() -> None:
    text = (
        "".join(f"## [easy] Easy {i}?\n- [x] Yes\n- [ ] No\n- [ ] Maybe\n\n" for i in range(7))
        + "## [hard] Hard?\n- [x] Yes\n- [ ] No\n- [ ] Maybe\n"
    )
    bank = TriviaBank.from_text(text, source="test")
    rng = random.Random(3)
    recent: dict[str, int] = {}
    seen: list[set[str]] = []
    for game in range(3):
        drawn = bank.draw(3, rng, "easy", recent=recent)
        assert all(q.level == "easy" for q in drawn)
        seen.append({q.text for q in drawn})
        recent.update({q.text: game for q in drawn})
    # The first six are different and the third game brings the missing one plus two of
    # the first game, the ones that have not come up for longest.
    assert len(seen[0] | seen[1]) == 6
    missing = {f"Easy {i}?" for i in range(7)} - seen[0] - seen[1]
    assert len(missing) == 1 and missing <= seen[2]
    assert seen[2] - missing <= seen[0]


async def test_games_do_not_repeat_questions(tmp_path: Path) -> None:
    six = "".join(f"## Question {i}?\n- [x] Yes\n- [ ] No\n- [ ] Maybe\n\n" for i in range(6))
    game, _, _ = make_game(tmp_path)
    (tmp_path / "questions.md").write_text(six, encoding="utf-8")
    asked: list[str] = []
    for _ in range(2):
        ok, _ = await game.start("panel")
        assert ok
        asked += [q.text for q in game._questions]
        await game.stop("panel")
    assert len(set(asked)) == 6


def test_the_repository_bank_has_valid_short_questions() -> None:
    bank = TriviaBank.from_file(REPO_BANK)
    assert len(bank) >= 45
    assert all(count >= 5 for count in bank.levels().values())
    for question in bank.questions:
        assert len(question.options) == 3
        # They show on the vertical screen: short options.
        assert all(len(option) <= 40 for option in question.options), question.text
    assert len({q.text for q in bank.questions}) == len(bank)


def test_the_rules_fit_in_one_instruction() -> None:
    from sonia.live.client import APPEND_MAX_CHARS
    from sonia.trivia.game import RULES_TEXT

    # session.instructions.append cuts whatever goes over APPEND_MAX_CHARS.
    assert len(RULES_TEXT.format(total=10, threshold=10, level="medium")) < APPEND_MAX_CHARS
    # A letter picked up from people talking to each other, or an answer Sonnia accepted
    # without recording it, would leave the screen behind.
    assert "People talking to each other is not an answer" in RULES_TEXT
    assert "never say if it is correct or which one it was before delegating" in RULES_TEXT


def test_without_a_bank_there_is_no_trivia(tmp_path: Path) -> None:
    host, screen = FakeHost(), FakeScreen()
    game = TriviaGame(TriviaSettings(), tmp_path / "missing.md", host=host, screen=screen)
    assert not game.available
    assert len(TriviaBank.from_file(tmp_path / "missing.md")) == 0


# ---------------------------------------------------------------------------
# Game
# ---------------------------------------------------------------------------


async def answer_and_next(game: TriviaGame, choice: int) -> str:
    """Answers and, if it was not the last one, asks for the next (as GPT-Live would)."""
    ok, script = await game.answer(choice, "voice")
    assert ok, script
    if game.phase is TriviaPhase.REVEALING and not game._final:
        assert (await game.next("voice"))[0]
    await settle()
    return script


async def test_a_game_won_by_voice(tmp_path: Path) -> None:
    game, host, screen = make_game(tmp_path)
    ok, script = await game.start("voice")
    assert ok
    assert game.phase is TriviaPhase.ASKING
    assert screen.hidden == 1
    assert screen.sticky[STICKY_START] == {
        "type": "trivia_start",
        "total": 3,
        "threshold": 2,
        "level": "medium",
    }
    first = current(screen)
    assert first["number"] == 1 and first["total"] == 3 and first["score"] == 0
    assert len(first["options"]) == 3
    # The question is there to be read; the options, only so GPT-Live knows the letters.
    assert first["question"] in script and "read only the question" in script
    assert "Do not read the options" in script
    assert all(option in script for option in first["options"])
    assert "CORRECT" not in script
    # By voice nothing is asked through commentary: the script goes in the result.
    assert host.spoken == []
    assert "TRIVIA MODE ON" in host.instructions[0]
    assert "never the options" in host.instructions[0]

    for number in (1, 2, 3):
        right = correct_index(game)
        ok, script = await game.answer(right, "voice")
        assert ok and "CORRECT" in script and "Explain" in script
        answer = screen.of_type("trivia_answer")[-1]
        assert answer == {
            "type": "trivia_answer",
            "number": number,
            "chosen": right,
            "correct": right,
            "is_correct": True,
            "score": number,
        }
        if number < 3:
            # Nothing moves on its own: it asks whether they want the next one and waits.
            assert "next question" in script and "question 2" not in script
            assert "if they do not want to go on, delegate ending the trivia" in script
            await settle()
            assert game.phase is TriviaPhase.REVEALING
            assert current(screen)["number"] == number
            ok, script = await game.next("voice")
            assert ok and f"question {number + 1} of 3" in script
            assert current(screen)["number"] == number + 1
        else:
            assert "HAVE WON" in script
            # Sonnia does not know about prizes: she sends winners to the contact.
            assert "talk to the front desk" in script
            assert "prizes" in script
        await settle()

    end = screen.of_type("trivia_end")[-1]
    assert end == {
        "type": "trivia_end",
        "score": 3,
        "total": 3,
        "won": True,
        "reason": "finished",
    }
    assert not game.active
    assert screen.sticky == {}
    assert "The trivia is over" in host.instructions[-1]


async def test_the_last_answer_always_closes_the_game(tmp_path: Path) -> None:
    # The screen cannot stay on the last question.
    game, host, screen = make_game(tmp_path, questions=3)
    await game.start("voice")
    await answer_and_next(game, 0)
    await answer_and_next(game, 0)
    await answer_and_next(game, 0)
    assert not game.active
    assert screen.of_type("trivia_end")[-1]["reason"] == "finished"


async def test_the_final_screen_waits_for_sonnia_to_finish(tmp_path: Path) -> None:
    game, host, screen = make_game(tmp_path, questions=1, threshold=1, final_wait_seconds=5.0)
    await game.start("voice")
    host.quiet = 10.0
    await game.answer(correct_index(game), "voice")
    await asyncio.sleep(0.3)
    assert game.active  # she has not started telling it yet
    host.quiet = 0.0  # speaks
    await asyncio.sleep(0.3)
    assert game.active
    host.quiet = 2.0  # goes quiet
    await asyncio.sleep(0.6)
    assert not game.active
    assert screen.of_type("trivia_end")[-1]["won"] is True


async def test_the_next_one_only_when_it_is_time(tmp_path: Path) -> None:
    game, _, screen = make_game(tmp_path)
    await game.start("voice")
    ok, message = await game.next("voice")
    assert not ok and "still waiting for an answer" in message
    await game.answer(0, "voice")
    # An answer with the result on screen is not lost silently: it is explained.
    ok, message = await game.answer(1, "voice")
    assert not ok and "next question" in message
    assert len(screen.of_type("trivia_answer")) == 1
    assert (await game.next("voice"))[0]
    assert (await game.answer(1, "voice"))[0]


async def test_a_lost_game_tells_the_right_one_and_encourages(tmp_path: Path) -> None:
    game, host, screen = make_game(tmp_path)
    await game.start("voice")
    wrong = (correct_index(game) + 1) % 3
    question = game._current
    assert question is not None
    ok, script = await game.answer(wrong, "voice")
    assert ok
    assert "NOT correct" in script
    assert question.options[question.correct] in script
    answer = screen.of_type("trivia_answer")[-1]
    assert answer["is_correct"] is False and answer["chosen"] == wrong
    await game.next("voice")
    ok, script = await game.answer(PASS, "voice")
    assert ok and "They do not know" in script
    assert screen.of_type("trivia_answer")[-1]["chosen"] == -1
    await game.next("voice")
    ok, script = await game.answer(correct_index(game), "voice")
    assert "fell short" in script
    await settle()
    end = screen.of_type("trivia_end")[-1]
    assert end["won"] is False and end["score"] == 1 and end["reason"] == "finished"
    # Only winners are sent to the contact.
    assert "front desk" not in script


async def test_winning_without_a_contact_sends_nobody(tmp_path: Path) -> None:
    game, _, screen = make_game(tmp_path, win_contact="")
    ok, script = await game.start("voice", "Hard")
    assert ok and "hard level" in script
    for _ in range(3):
        last = await answer_and_next(game, correct_index(game))
    assert "HAVE WON" in last and "talk to" not in last
    assert screen.of_type("trivia_end")[-1]["won"] is True


def test_bank_levels() -> None:
    from sonia.trivia import normalize_level

    text = BANK.replace("## Question two?", "## [hard] Question two?").replace(
        "## Question three?", "## [Easy] Question three?"
    )
    questions = parse_questions(text)
    assert [q.level for q in questions] == ["medium", "hard", "easy"]
    assert questions[1].text == "Question two?"
    assert normalize_level("basic") == "easy" and normalize_level("nothing") is None
    bank = TriviaBank(questions)
    first = bank.draw(1, random.Random(1), "hard")[0]
    assert first.text == "Question two?"
    # If the level falls short, it is completed with the closest one.
    assert len(bank.draw(3, random.Random(1), "easy")) == 3


async def test_the_question_fact_goes_in_the_script(tmp_path: Path) -> None:
    game, _, _ = make_game(tmp_path)
    await game.start("voice")
    while game._current is not None and game._current.text != "Question one?":
        await answer_and_next(game, 0)
    _, script = await game.answer(0, "voice")
    assert "Fact of question one." in script


async def test_from_the_panel_it_asks_gpt_live(tmp_path: Path) -> None:
    game, host, screen = make_game(tmp_path)
    ok, message = await game.start("panel", "easy")
    assert ok and "Trivia started, easy level" in message
    await settle()
    assert len(host.spoken) == 1
    assert current(screen)["question"] in host.spoken[0]
    ok, message = await game.answer(correct_index(game), "panel")
    assert ok and "correct" in message
    assert "recorded by the operator" in host.spoken[-1]
    assert "CORRECT" in host.spoken[-1]
    ok, message = await game.next("panel")
    assert ok and "Question 2 of 3" in message
    await settle()
    assert "question 2 of 3" in host.spoken[-1]


async def test_nothing_is_recorded_without_a_question_or_with_a_bad_letter(
    tmp_path: Path,
) -> None:
    game, _, screen = make_game(tmp_path)
    ok, _ = await game.answer(0, "voice")
    assert not ok
    await game.start("voice")
    ok, _ = await game.answer(5, "voice")
    assert not ok
    assert screen.of_type("trivia_answer") == []


async def test_it_does_not_start_twice_or_without_a_session(tmp_path: Path) -> None:
    game, host, _ = make_game(tmp_path)
    assert (await game.start("voice"))[0]
    ok, message = await game.start("panel")
    assert not ok and "already running" in message
    await game.stop("panel")
    host.connected = False
    ok, message = await game.start("panel")
    assert not ok and "not connected" in message


async def test_not_enough_questions(tmp_path: Path) -> None:
    game, _, _ = make_game(tmp_path, questions=5)
    assert not game.available
    ok, message = await game.start("voice")
    assert not ok and "5 are needed" in message


async def test_restarting_starts_from_scratch(tmp_path: Path) -> None:
    game, host, screen = make_game(tmp_path)
    await game.start("voice")
    await game.answer(correct_index(game), "voice")
    ok, script = await game.restart("voice")
    assert ok and script.startswith("New trivia from scratch.") and "question 1 of 3" in script
    assert game.phase is TriviaPhase.ASKING
    assert screen.of_type("trivia_end")[-1]["reason"] == "cancelled"
    assert screen.sticky[STICKY_QUESTION]["number"] == 1
    assert screen.sticky[STICKY_QUESTION]["score"] == 0
    # Without a running game, restarting is starting.
    await game.stop("panel")
    ok, _ = await game.restart("voice")
    assert ok and game.active


async def test_another_level_before_answering_changes_the_questions_without_closing(
    tmp_path: Path,
) -> None:
    game, _, screen = make_game(tmp_path)
    await game.start("voice", "easy")
    ok, script = await game.restart("voice", "hard")
    assert ok and "hard level" in script
    assert current(screen)["question"] in script and current(screen)["number"] == 1
    # The client gets no end: the trivia screen stays.
    assert screen.of_type("trivia_end") == []
    assert screen.sticky[STICKY_START]["level"] == "hard"
    assert game.snapshot()["level"] == "hard"


async def test_cancelling_from_the_panel(tmp_path: Path) -> None:
    game, host, screen = make_game(tmp_path)
    await game.start("voice")
    ok, _ = await game.stop("panel")
    assert ok and not game.active
    end = screen.of_type("trivia_end")[-1]
    assert end["reason"] == "cancelled" and end["won"] is False
    assert screen.sticky == {}
    assert "the operator has ended the trivia" in host.spoken[-1]


async def test_if_the_session_drops_it_is_cancelled_without_speaking(tmp_path: Path) -> None:
    game, host, screen = make_game(tmp_path)
    await game.start("voice")
    host.connected = False
    await game.on_session_lost()
    assert not game.active
    assert screen.of_type("trivia_end")[-1]["reason"] == "cancelled"
    assert host.spoken == []


async def test_it_reminds_the_question_and_then_gives_up(tmp_path: Path) -> None:
    game, host, screen = make_game(tmp_path, remind_seconds=20.0, abandon_seconds=60.0)
    await game.start("voice")
    host.quiet = 1000.0  # Sonnia has been quiet for a while
    start = game._asked_at
    await game.tick(start + 10)
    assert host.spoken == []
    await game.tick(start + 21)
    await settle()
    assert len(host.spoken) == 1 and "repeat the question" in host.spoken[0]
    assert "without reading the options" in host.spoken[0]
    # If they already answered and Sonnia did not record it, the reminder asks to record it.
    assert "already gave you their option, delegate" in host.spoken[0]
    await game.tick(start + 30)
    await settle()
    assert len(host.spoken) == 1  # only once per question
    # If the player is heard, the game is not abandoned.
    game.on_user_text(start + 50)
    await game.tick(start + 61)
    assert game.active
    await game.tick(start + 111)
    assert not game.active
    assert screen.of_type("trivia_end")[-1]["reason"] == "cancelled"
    assert "another time" in host.spoken[-1]


async def test_while_sonnia_speaks_it_neither_reminds_nor_gives_up(tmp_path: Path) -> None:
    game, host, _ = make_game(tmp_path, remind_seconds=20.0, abandon_seconds=60.0)
    await game.start("voice")
    host.quiet = 0.0
    await game.tick(game._asked_at + 100)
    assert game.active and host.spoken == []


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


async def test_trivia_actions(tmp_path: Path) -> None:
    game, host, screen = make_game(tmp_path)
    registry = build_default_registry(include_look=False, include_trivia=True)
    assert registry.names() == [
        "show_image",
        "hide_image",
        "play_animation",
        "start_trivia",
        "trivia_answer",
        "trivia_next",
        "restart_trivia",
        "stop_trivia",
    ]
    ctx = ActionContext(camera=None, avatar=None, gallery_dir="", extra={"trivia": game})

    # The level is required, but it can be "not chosen": otherwise the backend made one up.
    result = await registry.execute("start_trivia", {}, ctx)
    assert result.text.startswith("Error") and not game.active

    result = await registry.execute("start_trivia", {"level": "not_chosen"}, ctx)
    assert result.text.startswith(f"{SCRIPT_PREFIX} The trivia is on your screen, medium level")
    assert current(screen)["question"] in result.text and current(screen)["number"] == 1

    # If GPT-Live delegates starting it again, the game goes on and it is told how.
    result = await registry.execute("start_trivia", {"level": "not_chosen"}, ctx)
    assert result.text.startswith(SCRIPT_PREFIX) and "already running" in result.text
    assert current(screen)["question"] in result.text

    letter = "ABC"[correct_index(game)]
    result = await registry.execute("trivia_answer", {"option": letter}, ctx)
    assert result.text.startswith(SCRIPT_PREFIX) and "CORRECT" in result.text

    result = await registry.execute("trivia_answer", {"option": "D"}, ctx)
    assert result.text.startswith("Error")

    result = await registry.execute("trivia_next", {}, ctx)
    assert result.text.startswith(SCRIPT_PREFIX) and "question 2 of 3" in result.text
    assert current(screen)["number"] == 2

    result = await registry.execute("restart_trivia", {}, ctx)
    assert result.text.startswith(SCRIPT_PREFIX) and "from scratch" in result.text
    assert current(screen)["number"] == 1

    result = await registry.execute("stop_trivia", {}, ctx)
    assert "Trivia ended" in result.text
    assert not game.active

    result = await registry.execute("start_trivia", {"level": "easy"}, ctx)
    assert result.text.startswith(f"{SCRIPT_PREFIX} The trivia is on your screen, easy level")

    without_game = ActionContext(camera=None, avatar=None, gallery_dir="")
    result = await registry.execute("start_trivia", {"level": "not_chosen"}, without_game)
    assert "not available" in result.text


def test_without_trivia_its_actions_are_not_announced() -> None:
    names = build_default_registry(include_look=False).names()
    assert "start_trivia" not in names and "trivia_answer" not in names


async def test_if_the_player_speaks_and_nothing_is_delegated_it_is_reminded(
    tmp_path: Path,
) -> None:
    from sonia.trivia.game import NUDGE_S, NUDGE_TEXT

    game, host, _ = make_game(tmp_path)
    await game.start("voice")
    host.spoken.clear()
    now = game._asked_at + 5
    # "Better cancel it": Sonnia answers without delegating.
    game.on_user_turn_end(now, now - 2)
    host.quiet = 0.0
    await game.tick(now + NUDGE_S + 1)
    assert host.spoken == []  # nothing while she speaks
    host.quiet = 1.0
    await game.tick(now + NUDGE_S + 1.5)
    await settle()
    assert host.spoken == [NUDGE_TEXT]
    await game.tick(now + NUDGE_S + 5)
    await settle()
    assert host.spoken == [NUDGE_TEXT]  # once per turn

    # If it delegates, it is not needed: after the turn or, as usual, before it ends.
    game.on_user_turn_end(now + 20, now + 18)
    game.on_delegation(now + 21)
    await game.tick(now + 20 + NUDGE_S + 1)
    await settle()
    assert host.spoken == [NUDGE_TEXT]
    game.on_delegation(now + 29)
    game.on_user_turn_end(now + 30, now + 28)
    await game.tick(now + 20 + NUDGE_S + 1)
    await settle()
    assert host.spoken == [NUDGE_TEXT]

    # Without a game, neither.
    await game.stop("voice")
    game.on_user_turn_end(now + 40, now + 38)
    await game.tick(now + 40 + NUDGE_S + 1)
    await settle()
    assert NUDGE_TEXT not in host.spoken[1:]


async def test_each_question_passes_its_options_to_gpt_live(tmp_path: Path) -> None:
    """The backend summarized the script and dropped the options: Sonnia did not know the letters."""
    game, host, screen = make_game(tmp_path)
    await game.start("voice")
    first = current(screen)
    options = [i for i in host.instructions if i.startswith("TRIVIA, question 1 of")]
    assert len(options) == 1
    assert (
        f"A: {first['options'][0]}; B: {first['options'][1]}; C: {first['options'][2]}."
        in options[0]
    )
    assert "whether they say the letter or the answer" in options[0]
    await game.answer(correct_index(game), "voice")
    await game.next("voice")
    assert any(i.startswith("TRIVIA, question 2 of") for i in host.instructions)
