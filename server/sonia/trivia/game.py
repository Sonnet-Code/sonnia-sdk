"""A trivia game: the realtime model hosts it and the orchestrator keeps the screen and the key.

A game is ``TRIVIA_QUESTIONS`` random questions from the bank, with three options
shown on the avatar's screen. It makes the most of the realtime model:

- **It understands the answer.** The user answers however they like ("B",
  "Kotlin", "the second one", "two thousand twelve", "A... no, C") and the
  realtime model, which knows its own voice and the conversation, decides what
  was chosen and records it with the ``trivia_answer`` action. If it is not
  clear, it asks.
- **It reads and reacts.** The result of each action (``start_trivia``,
  ``trivia_answer``, ``trivia_next``) brings the script: the question (only the
  question: the options are on screen), the verdict with its explanation or the
  end. The realtime model tells it in its own words.
- **It keeps the pace.** After the verdict, Sonnia asks whether to move on to
  the next one and the game waits: nothing advances on its own. When the user
  says yes, the realtime model delegates ``trivia_next``. That way an answer
  never lands on a question that is not on screen yet. After the last one, the
  final screen comes when Sonnia finishes telling the result.
- **It does not know the answer ahead of time.** Only the orchestrator has the
  key: the screen rules and Sonnia cannot reveal or correct it.

The panel or the ``start_trivia`` action (by voice) start it and both go through
:meth:`TriviaGame.start`, so the game is the same whoever starts it. By voice, the
script comes back as the action result; from the panel (starting or answering
with the A, B and C buttons) it is passed to the realtime model with
``session.commentary.append``, which makes it speak.

Nothing that happens here takes the engine down: failures go to the log and, if
the realtime session drops, the game is cancelled.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time
from collections.abc import Coroutine
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from sonia.config import TriviaSettings
from sonia.trivia.bank import (
    DEFAULT_LEVEL,
    OPTION_LETTERS,
    TriviaBank,
    TriviaQuestion,
    normalize_level,
)
from sonia.ws import protocol as p

__all__ = ["PASS", "TriviaGame", "TriviaHost", "TriviaPhase", "TriviaScreen"]

logger = logging.getLogger(__name__)

#: The user does not know the answer (counts as wrong and the right one is told).
PASS = -1

#: Keys of the sticky hub messages: the client gets them again when it reconnects.
STICKY_START = "trivia_start"
STICKY_QUESTION = "trivia_question"

#: Maximum wait for Sonnia to go quiet before reading what the panel starts.
PANEL_WAIT_S = 3.0

RULES_TEXT = """\
TRIVIA MODE ON: {total} questions, {level} level, three options each (A, B, C) on your screen. Winning takes {threshold} correct answers.
- Read only the question, never the options: they are on screen. You know them to tell which letter the player picks.
- When they give their option, however they say it, turn it into its letter and delegate right away "trivia: answer B"; if they do not know, "trivia: does not know". People talking to each other is not an answer: if unsure they are answering you, ask.
- You do not know the right answer: never say if it is correct or which one it was before delegating; wait for the result.
- With the result, react and explain in one or two sentences why it is right. Then ask if they want the next question and wait: only when they say yes, delegate "trivia: next question".
- If they ask for the answer, answer twice, want to change theirs after the result or skip one, tell them with humor that the trivia does not work that way.
- To stop playing, delegate ending it; for a new game from scratch, restarting it.
- The screen only changes if you delegate: never say "done" or "stopped" without delegating."""

OFF_TEXT = (
    "The trivia is over and there are no more questions on your screen: go back to talking "
    "normally."
)

INTRO_TEXT = "The trivia is on your screen, {level} level."
LEVEL_TEXT = (
    "If they ask for another level (easy, medium or hard), delegate restarting it with that level."
)
KICKOFF_TEXT = (
    "{lead} with energy: say in one sentence that there are {total} questions and that they "
    "win with {threshold} correct answers."
)

QUESTION_TEXT = (
    '{lead} question {number} of {total} and read only the question, as is: "{question}". '
    "Do not read the options, they are already on the screen (for you: A: {a}; B: {b}; C: {c})."
)

#: The options of each question, straight to the realtime model: the backend summarized
#: the script, dropped them, and Sonnia did not know which letter an answer was.
OPTIONS_TEXT = (
    'TRIVIA, question {number} of {total}: "{question}". Options on the screen, so you know '
    "which letter the player picks, whether they say the letter or the answer (do not read "
    "them): A: {a}; B: {b}; C: {c}."
)

REMIND_TEXT = (
    "TRIVIA: there is no answer recorded for question {number}. If the player already gave "
    'you their option, delegate "trivia: answer" with its letter now, without saying whether '
    "it is correct. If not, encourage them in a few words and, if needed, repeat the question, "
    "without reading the options (they are on the screen)."
)

#: A nudge if the player spoke mid-game and the realtime model delegated nothing: sometimes
#: it said "I'll end it" or "I'll mark it" without delegating. It decides.
NUDGE_TEXT = (
    "TRIVIA: the player just spoke to you and you have not delegated anything. If they asked "
    "to stop playing, for a new game from scratch or for the next question, or gave you their "
    "option, delegate it right now (saying it is not enough: the screen only changes if you "
    "delegate) and then say it in a few words. If they were just chatting, say nothing."
)

#: Seconds after the player's turn without any delegation before the nudge.
NUDGE_S = 3.0

CORRECT_TEXT = 'They picked {letter}, "{option}": it is CORRECT. Celebrate it.'
WRONG_TEXT = (
    'They picked {letter}, "{option}": it is NOT correct; the right one was '
    '{right_letter}, "{right_option}". Tell them kindly.'
)
PASS_TEXT = (
    'They do not know. The right one was {right_letter}, "{right_option}". Tell them kindly.'
)
EXPLAIN_TEXT = "Explain in one or two sentences why it is the right one."
FACT_TEXT = "Use this fact: {fact}"
ASK_NEXT_TEXT = (
    "Then ask whether they want to move on to the next question and wait: when they say yes, "
    'delegate "trivia: next question"; if they do not want to go on, delegate ending the trivia.'
)
WON_TEXT = (
    "That ends the trivia: they got {score} of {total} right and HAVE WON. Congratulate them "
    "big time."
)
LOST_TEXT = (
    "That ends the trivia: they got {score} of {total} right and fell short of the "
    "{threshold} needed. Kindly encourage them to try again."
)
#: Sonnia does not know about prizes: she sends winners to the people who run her.
WIN_CONTACT_TEXT = (
    "Tell them to go and talk to {contact}. You do not know about any prizes: do not promise "
    "any and, if they ask, let {contact} tell them."
)
BACK_TO_TALK_TEXT = "Then keep talking normally."

#: An answer that arrives with the result still on screen (nobody asked for the next one).
WAITING_NEXT_TEXT = (
    "Question {number} is already answered and its result is still on screen. If the player "
    'wants to go on, delegate "trivia: next question" and let them answer the new one.'
)

#: What the realtime model is told when the answer comes from the panel.
PANEL_ANSWER_TEXT = "TRIVIA (answer recorded by the operator): "

CANCEL_TEXT = {
    "panel": (
        "TRIVIA: the operator has ended the trivia. Say it in one short sentence and keep "
        "talking normally."
    ),
    "abandoned": (
        "TRIVIA: the player no longer answers and the trivia is cancelled. Say in one short "
        "sentence that the trivia will have to wait for another time."
    ),
}


class TriviaPhase(StrEnum):
    OFF = "off"
    #: Question on screen, waiting for the answer.
    ASKING = "asking"
    #: Result on screen, waiting for the next one to be requested (or, after the last, the end).
    REVEALING = "revealing"


class TriviaHost(Protocol):
    """What the game uses from the realtime engine."""

    @property
    def connected(self) -> bool: ...

    def quiet_for(self) -> float:
        """Seconds Sonnia has been quiet (0 while she speaks)."""
        ...

    async def speak(self, prompt: str) -> bool:
        """Asks the realtime model to say something (``session.commentary.append``)."""
        ...

    async def instruct(self, text: str) -> bool:
        """Adds an instruction without making it speak (``session.instructions.append``)."""
        ...

    async def wait_idle(self, limit_s: float | None = None) -> bool: ...

    def touch(self) -> None:
        """There is activity: no idle animation and no new session for inactivity."""
        ...


class TriviaScreen(Protocol):
    """What the game uses from the avatar client hub."""

    async def broadcast_json(self, msg: dict[str, Any]) -> None: ...
    async def set_sticky(self, key: str, msg: dict[str, Any]) -> None: ...
    def clear_sticky(self, key: str) -> None: ...
    async def hide_image(self) -> None: ...


class TriviaGame:
    """One trivia game at a time, over the engine's realtime session."""

    def __init__(
        self,
        settings: TriviaSettings,
        bank_file: Path,
        *,
        host: TriviaHost,
        screen: TriviaScreen,
        rng: random.Random | None = None,
    ) -> None:
        self._settings = settings
        self._bank_file = bank_file
        self._host = host
        self._screen = screen
        self._rng = rng or random.Random()
        self._bank = TriviaBank.from_file(bank_file)
        #: Question -> game in which it last came up: no repeats until the level runs out.
        self._asked: dict[str, int] = {}
        self._phase = TriviaPhase.OFF
        self._game = 0
        self._questions: list[TriviaQuestion] = []
        self._index = -1
        self._score = 0
        self._level = DEFAULT_LEVEL
        #: The last question is already answered: only the end is left.
        self._final = False
        self._asked_at = 0.0
        self._reminded = False
        #: Last time the player was heard (or answered).
        self._last_user_at = 0.0
        #: When the :data:`NUDGE_TEXT` nudge is due (0: not due) and the last delegation.
        self._nudge_at = 0.0
        self._delegated_at = float("-inf")
        self._tasks: set[asyncio.Task[Any]] = set()

    # -- state --------------------------------------------------------------

    @property
    def available(self) -> bool:
        """Are there enough questions for a game?"""
        return self._settings.enabled and len(self._bank) >= self._total

    @property
    def active(self) -> bool:
        return self._phase is not TriviaPhase.OFF

    @property
    def phase(self) -> TriviaPhase:
        return self._phase

    @property
    def questions_per_game(self) -> int:
        """Questions in a game: a bank needs at least these."""
        return self._total

    @property
    def _total(self) -> int:
        return max(1, self._settings.questions)

    @property
    def _threshold(self) -> int:
        return max(1, min(self._settings.win_threshold, self._total))

    @property
    def _current(self) -> TriviaQuestion | None:
        if 0 <= self._index < len(self._questions):
            return self._questions[self._index]
        return None

    def snapshot(self) -> dict[str, Any]:
        """For the panel: where the game is at."""
        question = self._current if self.active else None
        return {
            "available": self.available,
            "bank": len(self._bank),
            "bank_levels": self._bank.levels(),
            "active": self.active,
            "phase": str(self._phase),
            "number": self._index + 1 if question is not None else 0,
            "level": self._level if self.active else "",
            "total": self._total,
            "threshold": self._threshold,
            "score": self._score,
            "question": question.text if question is not None else "",
            "options": list(question.options) if question is not None else [],
        }

    def _draw(self) -> list[TriviaQuestion]:
        """The questions of the game, starting with the ones that have not come up for longest."""
        questions = self._bank.draw(self._total, self._rng, self._level, recent=self._asked)
        for question in questions:
            self._asked[question.text] = self._game
        return questions

    # -- start and end ------------------------------------------------------

    async def start(self, source: str, level: str | None = None) -> tuple[bool, str]:
        """Starts a game. Never raises.

        With ``source="voice"`` (``start_trivia`` action) it returns the script for
        the realtime model to say as the action result. With ``panel`` the game
        passes it to the realtime model as soon as it is quiet and returns a text
        for the operator.
        """
        if not self._settings.enabled:
            return False, "The trivia is disabled (TRIVIA_ENABLED=false)."
        if self.active:
            return False, "A trivia game is already running."
        if not self._host.connected:
            return False, "Sonnia is not connected to the realtime model right now."
        # The file is read again: it can be edited without restarting.
        bank = TriviaBank.from_file(self._bank_file)
        if len(bank) >= self._total:
            self._bank = bank
        if len(self._bank) < self._total:
            return False, (
                f"Not enough questions: there are {len(self._bank)} and {self._total} are needed."
            )
        self._game += 1
        self._level = (
            normalize_level(level) or normalize_level(self._settings.default_level) or DEFAULT_LEVEL
        )
        self._questions = self._draw()
        self._score = 0
        self._final = False
        self._last_user_at = time.monotonic()
        logger.info("Trivia started (%s): %d questions, %s level", source, self._total, self._level)
        self._host.touch()
        await self._screen.hide_image()
        await self._screen.set_sticky(
            STICKY_START, p.msg_trivia_start(self._total, self._threshold, self._level)
        )
        await self._host.instruct(
            RULES_TEXT.format(total=self._total, threshold=self._threshold, level=self._level)
        )
        await self._ask(0)
        script = " ".join(
            [
                INTRO_TEXT.format(level=self._level),
                LEVEL_TEXT,
                self._kickoff_text("Start"),
                self._question_text(0, lead="Then say"),
            ]
        )
        if source == "voice":
            return True, script
        self._spawn(self._speak_when_quiet(self._game, "TRIVIA: " + script), "trivia-intro")
        return True, (
            f"Trivia started, {self._level} level: {self._total} questions, win with "
            f"{self._threshold}."
        )

    async def restart(self, source: str, level: str | None = None) -> tuple[bool, str]:
        """Starts a new game, cutting the running one without a goodbye.

        If no question has been answered yet (they ask for another level at the
        start), only the questions change: the game goes on.
        """
        if self.active and self._index == 0 and self._phase is TriviaPhase.ASKING:
            return await self._change_level(source, level)
        if self.active:
            logger.info("Trivia restarted (%s) at %d of %d", source, self._score, self._index + 1)
            level = level or self._level
            await self._end(won=False, reason="cancelled")
        ok, script = await self.start(source, level)
        if ok and source == "voice":
            script = "New trivia from scratch. " + script
        return ok, script

    async def _change_level(self, source: str, level: str | None) -> tuple[bool, str]:
        """Other questions of level ``level`` before answering the first one."""
        self._level = normalize_level(level) or self._level
        self._questions = self._draw()
        logger.info("Trivia: %s level before the first question (%s)", self._level, source)
        self._host.touch()
        await self._screen.set_sticky(
            STICKY_START, p.msg_trivia_start(self._total, self._threshold, self._level)
        )
        await self._ask(0)
        script = (
            f"The trivia is now {self._level} level and the first question is a different one. "
            + self._kickoff_text("Start")
            + " "
            + self._question_text(0, lead="Then say")
        )
        if source == "voice":
            return True, script
        self._spawn(self._speak_when_quiet(self._game, "TRIVIA: " + script), "trivia-level")
        return True, f"Trivia at {self._level} level: other questions from the first one."

    async def resume(self) -> str:
        """The script when starting the trivia is requested with the game already running."""
        question = self._current
        if not self.active or question is None:
            return OFF_TEXT
        if self._phase is TriviaPhase.REVEALING:
            if self._final:
                return "That was the last question: the trivia is already over, wrap it up."
            return self._waiting_next_text()
        text = "The trivia is already running on your screen, no need to start it. "
        if self._index > 0:
            return text + self._question_text(self._index, lead="If you have not read it, read")
        text += self._kickoff_text("Start")
        return text + " " + self._question_text(0, lead="Then say")

    async def stop(self, reason: str) -> tuple[bool, str]:
        """Cancels the game. ``reason``: ``panel``, ``voice``, ``abandoned``, ``session``..."""
        if not self.active:
            return False, "There is no trivia running."
        logger.info("Trivia cancelled (%s) at %d of %d", reason, self._score, self._index + 1)
        await self._end(won=False, reason="cancelled")
        if self._host.connected and reason != "session":
            text = CANCEL_TEXT.get(reason)
            with contextlib.suppress(Exception):
                await self._host.instruct(OFF_TEXT)
                if text:
                    await self._host.speak(text)
        return True, "Trivia ended."

    async def _end(self, *, won: bool, reason: str) -> None:
        self._phase = TriviaPhase.OFF
        self._cancel_tasks()
        self._screen.clear_sticky(STICKY_START)
        self._screen.clear_sticky(STICKY_QUESTION)
        await self._screen.broadcast_json(
            p.msg_trivia_end(self._score, self._total, won=won, reason=reason)
        )

    async def _ask(self, index: int) -> None:
        """Puts question ``index`` on screen."""
        self._index = index
        question = self._questions[index]
        self._phase = TriviaPhase.ASKING
        self._asked_at = time.monotonic()
        self._reminded = False
        await self._screen.set_sticky(
            STICKY_QUESTION,
            p.msg_trivia_question(
                index + 1, self._total, question.text, list(question.options), self._score
            ),
        )
        a, b, c = question.options
        with contextlib.suppress(Exception):
            await self._host.instruct(
                OPTIONS_TEXT.format(
                    number=index + 1, total=self._total, question=question.text, a=a, b=b, c=c
                )
            )

    def _question_text(self, index: int, *, lead: str) -> str:
        question = self._questions[index]
        a, b, c = question.options
        return QUESTION_TEXT.format(
            lead=lead,
            number=index + 1,
            total=self._total,
            question=question.text,
            a=a,
            b=b,
            c=c,
        )

    def _kickoff_text(self, lead: str) -> str:
        """Start by saying how many questions there are and how many answers win."""
        return KICKOFF_TEXT.format(lead=lead, total=self._total, threshold=self._threshold)

    def _waiting_next_text(self) -> str:
        """An answer or a request to start while the result is still on screen."""
        return WAITING_NEXT_TEXT.format(number=self._index + 1)

    async def _speak_when_quiet(self, game: int, prompt: str) -> None:
        await self._host.wait_idle(PANEL_WAIT_S)
        if game == self._game and self.active:
            await self._host.speak(prompt)

    # -- answers ------------------------------------------------------------

    def on_user_text(self, now: float) -> None:
        """The player is heard: they are still there (so the game is not abandoned)."""
        if self.active:
            self._last_user_at = max(self._last_user_at, now)

    def on_user_turn_end(self, now: float, started_at: float) -> None:
        """A player turn ended (it started at ``started_at``): if nothing is delegated, a nudge.

        The realtime model usually delegates before the end of the transcript
        arrives: anything delegated since they started speaking already counts.
        """
        if self.active and self._delegated_at < started_at - 0.5:
            self._nudge_at = now + NUDGE_S

    def on_delegation(self, now: float) -> None:
        """The realtime model delegated something: no nudge needed."""
        self._delegated_at = now
        self._nudge_at = 0.0

    async def answer(self, choice: int, source: str) -> tuple[bool, str]:
        """Records the answer (0, 1, 2 or :data:`PASS`). Never raises.

        With ``source="voice"`` (``trivia_answer`` action) it returns the script for
        the realtime model: the verdict, a fact and what comes next. With ``panel``
        the game passes it to the realtime model and returns a text for the operator.
        """
        question = self._current
        if self._phase is not TriviaPhase.ASKING or question is None:
            if self._phase is TriviaPhase.REVEALING:
                if self._final:
                    return (
                        False,
                        "That was the last question: the trivia is already over, wrap it up.",
                    )
                return False, self._waiting_next_text()
            return False, "There is no trivia question waiting for an answer."
        if choice not in (0, 1, 2, PASS):
            return False, "Invalid answer: A, B, C or that they do not know."
        self._phase = TriviaPhase.REVEALING
        self._last_user_at = time.monotonic()
        right = choice == question.correct
        if right:
            self._score += 1
        number = self._index + 1
        last = number >= self._total
        won = self._score >= self._threshold
        logger.info(
            "Trivia %d/%d (%s): %s -> %s (%d correct)",
            number,
            self._total,
            source,
            OPTION_LETTERS[choice] if choice >= 0 else "does not know",
            "correct" if right else f"wrong, it was {OPTION_LETTERS[question.correct]}",
            self._score,
        )
        self._host.touch()
        await self._screen.broadcast_json(
            p.msg_trivia_answer(number, choice, question.correct, right, self._score)
        )
        parts = [self._result_text(question, choice)]
        if last:
            self._final = True
            template = WON_TEXT if won else LOST_TEXT
            parts.append(
                template.format(score=self._score, total=self._total, threshold=self._threshold)
            )
            contact = self._settings.win_contact.strip()
            if won and contact:
                parts.append(WIN_CONTACT_TEXT.format(contact=contact))
            parts.append(BACK_TO_TALK_TEXT)
            self._spawn(self._finish_when_told(self._game, won), "trivia-final")
        else:
            parts.append(ASK_NEXT_TEXT)
        script = " ".join(parts)
        if source == "voice":
            return True, script
        await self._host.speak(PANEL_ANSWER_TEXT + script)
        letter = OPTION_LETTERS[choice] if choice >= 0 else '"I don\'t know"'
        return True, f"Answer {letter}: {'correct' if right else 'wrong'}."

    async def next(self, source: str) -> tuple[bool, str]:
        """The next question, when the player asks for it. Never raises.

        With ``voice`` (``trivia_next`` action) it returns the script; with ``panel``
        it passes it to the realtime model as soon as it is quiet.
        """
        question = self._current
        if not self.active or question is None:
            return False, "There is no trivia running."
        if self._phase is TriviaPhase.ASKING:
            return False, (
                f"Question {self._index + 1} is still waiting for an answer: "
                f'"{question.text}". Let them answer first.'
            )
        if self._final:
            return False, "That was the last question: the trivia is already over."
        self._last_user_at = time.monotonic()
        self._host.touch()
        await self._ask(self._index + 1)
        logger.info("Trivia: question %d of %d (%s)", self._index + 1, self._total, source)
        script = self._question_text(self._index, lead="Go on with")
        if source == "voice":
            return True, script
        self._spawn(self._speak_when_quiet(self._game, "TRIVIA: " + script), "trivia-next")
        return True, f"Question {self._index + 1} of {self._total} on screen."

    async def _finish_when_told(self, game: int, won: bool) -> None:
        """After the last answer, the final screen when Sonnia finishes telling it.

        The result stays at least ``reveal_seconds``; then it waits for Sonnia to
        speak and go quiet again (at most ``final_wait_seconds``), so the win or
        lose screen does not step on her explanation.
        """
        loop = asyncio.get_running_loop()
        settings = self._settings
        await asyncio.sleep(max(0.0, settings.reveal_seconds))
        deadline = loop.time() + max(0.0, settings.final_wait_seconds)
        spoke = False
        while loop.time() < deadline and game == self._game:
            quiet = self._host.quiet_for()
            spoke = spoke or quiet < 0.5
            if spoke and quiet >= 1.5:
                break
            await asyncio.sleep(0.25)
        if game != self._game or self._phase is not TriviaPhase.REVEALING:
            return
        logger.info(
            "Trivia over: %d of %d (%s)", self._score, self._total, "won" if won else "lost"
        )
        await self._end(won=won, reason="finished")
        with contextlib.suppress(Exception):
            await self._host.instruct(OFF_TEXT)

    def _result_text(self, question: TriviaQuestion, choice: int) -> str:
        right_letter = OPTION_LETTERS[question.correct]
        right_option = question.options[question.correct]
        if choice == PASS:
            verdict = PASS_TEXT.format(right_letter=right_letter, right_option=right_option)
        elif choice == question.correct:
            verdict = CORRECT_TEXT.format(letter=right_letter, option=right_option)
        else:
            verdict = WRONG_TEXT.format(
                letter=OPTION_LETTERS[choice],
                option=question.options[choice],
                right_letter=right_letter,
                right_option=right_option,
            )
        parts = [verdict, EXPLAIN_TEXT]
        if question.fact:
            parts.append(FACT_TEXT.format(fact=question.fact))
        return " ".join(parts)

    # -- loop ---------------------------------------------------------------

    async def tick(self, now: float) -> None:
        """Called by the engine loop: remind the question and give up on an abandoned game."""
        if self._phase is TriviaPhase.OFF or self._final:
            self._nudge_at = 0.0
            return
        settings = self._settings
        quiet = self._host.quiet_for()
        if self._nudge_at and now >= self._nudge_at and quiet >= 0.5:
            # It already answered without delegating: let it decide. It goes through
            # commentary because a silent instruction does not open a turn.
            self._nudge_at = 0.0
            logger.info("Trivia: the player spoke and nothing was delegated; reminding it")
            self._spawn(self._host.speak(NUDGE_TEXT), "trivia-nudge")
        if now - self._last_user_at >= settings.abandon_seconds and quiet >= 1.0:
            await self.stop("abandoned")
            return
        if self._phase is not TriviaPhase.ASKING:
            return
        silent_for = min(now - self._last_user_at, quiet)
        if (
            not self._reminded
            and silent_for >= settings.remind_seconds
            and now - self._asked_at >= settings.remind_seconds
        ):
            self._reminded = True
            remind = REMIND_TEXT.format(number=self._index + 1, total=self._total)
            self._spawn(self._host.speak(remind), "trivia-remind")

    async def on_session_lost(self) -> None:
        """The realtime session dropped or was renewed: the game cannot go on."""
        if self.active:
            await self.stop("session")

    # -- helpers ------------------------------------------------------------

    def _spawn(self, coro: Coroutine[Any, Any, Any], name: str) -> None:
        task = asyncio.create_task(coro, name=f"sonia-{name}")
        self._tasks.add(task)
        task.add_done_callback(self._task_done)

    def _task_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("Trivia task %s failed: %r", task.get_name(), task.exception())

    def _cancel_tasks(self) -> None:
        current = asyncio.current_task()
        for task in list(self._tasks):
            if task is not current and not task.done():
                task.cancel()
