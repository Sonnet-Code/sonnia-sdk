"""Partida de trivia: GPT-Live la conduce y el orquestador lleva la pantalla y la clave.

Una partida son ``TRIVIA_QUESTIONS`` preguntas al azar del banco, con tres
opciones que salen en la pantalla de Unity. Se aprovecha GPT-Live al máximo:

- **Entiende la respuesta.** El visitante contesta como quiera («la B»,
  «Kotlin», «la segunda», «dos mil doce», «la A… no, la C») y GPT-Live,
  que conoce su propia voz y la conversación, decide qué ha elegido y lo
  registra con la acción ``trivia_answer``. Si no está claro, pregunta.
- **Lee y reacciona.** El resultado de cada acción (``start_trivia``,
  ``trivia_answer``, ``trivia_next``) trae el guion: la pregunta (solo la
  pregunta: las opciones están en pantalla), el veredicto con su explicación o
  el final. GPT-Live lo cuenta con sus palabras.
- **Lleva el ritmo.** Tras el veredicto, Sonia pregunta si pasan a la
  siguiente y la partida espera: nada avanza solo. Cuando el visitante dice que
  sí, GPT-Live delega ``trivia_next``. Así una respuesta nunca llega a una
  pregunta que aún no está en pantalla. Tras la última, la pantalla final sale
  cuando Sonia termina de contar el resultado.
- **No sabe la respuesta antes de tiempo.** La clave solo la tiene el
  orquestador: la pantalla manda y Sonia no puede revelarla ni corregirla.

La lanza el panel o la acción ``start_trivia`` (por voz) y las dos entran por
:meth:`TriviaGame.start`, así que la partida es la misma la lance quien la
lance. Por voz, el guion vuelve como resultado de la acción; desde el panel
(arrancar o contestar con los botones A, B y C) se le pasa a GPT-Live con
``session.commentary.append``, que la hace hablar.

Nada de lo que pase aquí tumba el motor: los fallos van al registro y, si la
sesión de GPT-Live se cae, la partida se cancela.
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

#: El visitante no sabe la respuesta (cuenta como fallo y se le dice la buena).
PASS = -1

#: Claves de los mensajes fijos del hub: Unity los recibe otra vez al reconectar.
STICKY_START = "trivia_start"
STICKY_QUESTION = "trivia_question"

#: Tope de espera a que Sonia calle antes de leer lo que se arranca desde el panel.
PANEL_WAIT_S = 3.0

RULES_TEXT = """\
MODO TRIVIA EN MARCHA: {total} preguntas de nivel {level}, cada una con tres opciones (A, B y C) en tu pantalla. Gana con {threshold} aciertos.
- Lee solo la pregunta, nunca las opciones: se ven en la pantalla. Tú las conoces para saber qué letra elige.
- Cuando te diga su opción, la diga como la diga, pásala a su letra y delega enseguida «trivia: responde B»; si no lo sabe, «trivia: no lo sabe». Lo que hablan entre ellos no es una respuesta: si no está claro que te contesta a ti, pregunta antes.
- No sabes la buena: nunca digas si acierta ni cuál era sin delegar la respuesta; espera al resultado.
- Con el resultado, reacciona y explica en una o dos frases por qué es la buena. Luego pregunta si quiere la siguiente y espera: solo cuando diga que sí, delega «trivia: siguiente pregunta».
- Si pide la respuesta, contesta dos veces, quiere cambiar la suya tras el resultado o saltarse una, dile con humor que así no funciona la trivia.
- Si quiere dejar de jugar, delega terminarla; si quiere otra desde cero, reiniciarla.
- En la pantalla nada cambia si no lo delegas: nunca digas «ya está», «la marco» o «la detengo» sin haberlo delegado."""

OFF_TEXT = (
    "La trivia ha terminado y ya no hay preguntas en tu pantalla: vuelve a conversar con "
    "normalidad."
)

INTRO_TEXT = (
    "La trivia está en tu pantalla, nivel {level}. Arranca con energía: di en una frase que son "
    "{total} preguntas y que con {threshold} aciertos gana. "
)

QUESTION_TEXT = (
    "{lead} la pregunta {number} de {total} y lee solo la pregunta, tal cual: «{question}». "
    "No leas las opciones, ya están en la pantalla (para ti: A: {a}; B: {b}; C: {c})."
)

REMIND_TEXT = (
    "TRIVIA: no hay ninguna respuesta registrada para la pregunta {number}. Si el visitante ya "
    "te dijo su opción, delega ahora «trivia: responde» con su letra, sin decir si acierta. Si "
    "no, anímale en pocas palabras y, si hace falta, repite la pregunta, sin leer las opciones "
    "(están en la pantalla)."
)

CORRECT_TEXT = "Ha elegido la {letter}, «{option}»: es CORRECTA. Celébralo."
WRONG_TEXT = (
    "Ha elegido la {letter}, «{option}»: NO es correcta; la buena era la {right_letter}, "
    "«{right_option}». Díselo con cariño."
)
PASS_TEXT = "No lo sabe. La buena era la {right_letter}, «{right_option}». Díselo con cariño."
EXPLAIN_TEXT = " Explica en una o dos frases por qué es la buena."
FACT_TEXT = " Apóyate en este dato: {fact}"
ASK_NEXT_TEXT = (
    " Luego pregúntale si quiere pasar a la siguiente pregunta y espera: cuando diga que sí, "
    "delega «trivia: siguiente pregunta»; si no quiere seguir, delega terminar la trivia."
)
WON_TEXT = (
    " Con esto termina la trivia: ha acertado {score} de {total} y HA GANADO. Felicítale a lo "
    "grande."
)
LOST_TEXT = (
    " Con esto termina la trivia: ha acertado {score} de {total} y le faltaron aciertos para "
    "los {threshold}. Anímale con cariño a intentarlo otra vez."
)
PRIZE_TEXT = " Dile que pase por el staff del stand a recoger {prize}."
BACK_TO_TALK_TEXT = " Luego sigue conversando con normalidad."

#: Respuesta que llega con el resultado aún en pantalla (no se pidió la siguiente).
WAITING_NEXT_TEXT = (
    "La pregunta {number} ya está contestada y su resultado sigue en pantalla. Si el visitante "
    "quiere seguir, delega «trivia: siguiente pregunta» y que conteste a la nueva."
)

#: Lo que se le dice a GPT-Live cuando la respuesta llega por el panel.
PANEL_ANSWER_TEXT = "TRIVIA (respuesta registrada por el equipo del stand): "

CANCEL_TEXT = {
    "panel": (
        "TRIVIA: el equipo del stand ha terminado la trivia. Dilo en una frase corta y sigue "
        "conversando con normalidad."
    ),
    "abandoned": (
        "TRIVIA: el visitante ya no contesta y la trivia se cancela. Di en una frase corta que "
        "la trivia queda para otro momento."
    ),
}


class TriviaPhase(StrEnum):
    OFF = "off"
    #: Pregunta en pantalla, esperando la respuesta.
    ASKING = "asking"
    #: Resultado en pantalla, esperando a que pidan la siguiente (o, en la última, el final).
    REVEALING = "revealing"


class TriviaHost(Protocol):
    """Lo que la partida usa del motor GPT-Live."""

    @property
    def connected(self) -> bool: ...

    def quiet_for(self) -> float:
        """Segundos que Sonia lleva callada (0 mientras habla)."""
        ...

    async def speak(self, prompt: str) -> bool:
        """Le pide a GPT-Live que diga algo (``session.commentary.append``)."""
        ...

    async def instruct(self, text: str) -> bool:
        """Le añade una instrucción sin hacerla hablar (``session.instructions.append``)."""
        ...

    async def wait_idle(self, limit_s: float | None = None) -> bool: ...

    def touch(self) -> None:
        """Hay actividad: ni animación de stand ni sesión nueva por inactividad."""
        ...


class TriviaScreen(Protocol):
    """Lo que la partida usa del hub de Unity."""

    async def broadcast_json(self, msg: dict[str, Any]) -> None: ...
    async def set_sticky(self, key: str, msg: dict[str, Any]) -> None: ...
    def clear_sticky(self, key: str) -> None: ...
    async def hide_image(self) -> None: ...


class TriviaGame:
    """Una partida de trivia a la vez, sobre la sesión de GPT-Live del motor."""

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
        self._phase = TriviaPhase.OFF
        self._game = 0
        self._questions: list[TriviaQuestion] = []
        self._index = -1
        self._score = 0
        self._level = DEFAULT_LEVEL
        #: La última pregunta ya está contestada: solo falta el final.
        self._final = False
        self._asked_at = 0.0
        self._reminded = False
        #: Última vez que se oyó al visitante (o se contestó).
        self._last_user_at = 0.0
        self._tasks: set[asyncio.Task[Any]] = set()

    # -- estado -------------------------------------------------------------

    @property
    def available(self) -> bool:
        """¿Hay preguntas para una partida?"""
        return self._settings.enabled and len(self._bank) >= self._total

    @property
    def active(self) -> bool:
        return self._phase is not TriviaPhase.OFF

    @property
    def phase(self) -> TriviaPhase:
        return self._phase

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
        """Para el panel: en qué va la partida."""
        question = self._current if self.active else None
        return {
            "available": self.available,
            "bank": len(self._bank),
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

    # -- arranque y final ---------------------------------------------------

    async def start(self, source: str, level: str | None = None) -> tuple[bool, str]:
        """Empieza una partida. Nunca lanza.

        Con ``source="voice"`` (acción ``start_trivia``) devuelve el guion para
        que GPT-Live lo diga como resultado de la acción. Con ``panel`` se lo
        pasa la partida a GPT-Live en cuanto calla y devuelve un texto para el
        personal del stand.
        """
        if not self._settings.enabled:
            return False, "La trivia está desactivada (TRIVIA_ENABLED=false)."
        if self.active:
            return False, "Ya hay una trivia en marcha."
        if not self._host.connected:
            return False, "Sonnia no está conectada a GPT-Live ahora mismo."
        # Se relee el banco: se puede editar durante el evento sin reiniciar.
        bank = TriviaBank.from_file(self._bank_file)
        if len(bank) >= self._total:
            self._bank = bank
        if len(self._bank) < self._total:
            return False, (
                f"No hay preguntas suficientes: hay {len(self._bank)} y hacen falta {self._total}."
            )
        self._game += 1
        self._level = (
            normalize_level(level) or normalize_level(self._settings.default_level) or DEFAULT_LEVEL
        )
        self._questions = self._bank.draw(self._total, self._rng, self._level)
        self._score = 0
        self._final = False
        self._last_user_at = time.monotonic()
        logger.info(
            "Trivia en marcha (%s): %d preguntas, nivel %s", source, self._total, self._level
        )
        self._host.touch()
        await self._screen.hide_image()
        await self._screen.set_sticky(
            STICKY_START, p.msg_trivia_start(self._total, self._threshold, self._level)
        )
        await self._host.instruct(
            RULES_TEXT.format(total=self._total, threshold=self._threshold, level=self._level)
        )
        await self._ask(0)
        script = INTRO_TEXT.format(total=self._total, threshold=self._threshold, level=self._level)
        script += self._question_text(0, lead="Después di")
        if source == "voice":
            return True, script
        self._spawn(self._speak_when_quiet(self._game, "TRIVIA: " + script), "trivia-intro")
        return True, (
            f"Trivia en marcha, nivel {self._level}: {self._total} preguntas, gana con "
            f"{self._threshold}."
        )

    async def restart(self, source: str, level: str | None = None) -> tuple[bool, str]:
        """Empieza una partida nueva, cortando sin despedida la que haya en marcha."""
        if self.active:
            logger.info("Trivia reiniciada (%s) con %d de %d", source, self._score, self._index + 1)
            level = level or self._level
            await self._end(won=False, reason="cancelled")
        return await self.start(source, level)

    async def stop(self, reason: str) -> tuple[bool, str]:
        """Cancela la partida. ``reason``: ``panel``, ``voice``, ``abandoned``, ``session``..."""
        if not self.active:
            return False, "No hay ninguna trivia en marcha."
        logger.info("Trivia cancelada (%s) con %d de %d", reason, self._score, self._index + 1)
        await self._end(won=False, reason="cancelled")
        if self._host.connected and reason != "session":
            text = CANCEL_TEXT.get(reason)
            with contextlib.suppress(Exception):
                await self._host.instruct(OFF_TEXT)
                if text:
                    await self._host.speak(text)
        return True, "Trivia terminada."

    async def _end(self, *, won: bool, reason: str, prize: str = "") -> None:
        self._phase = TriviaPhase.OFF
        self._cancel_tasks()
        self._screen.clear_sticky(STICKY_START)
        self._screen.clear_sticky(STICKY_QUESTION)
        await self._screen.broadcast_json(
            p.msg_trivia_end(self._score, self._total, won=won, reason=reason, prize=prize)
        )

    def _prize(self, won: bool) -> str:
        """Lo que se lleva: la gorra si gana en difícil; si no, el premio por participar."""
        settings = self._settings
        if won and self._level == "difícil" and settings.prize_hard_win.strip():
            return settings.prize_hard_win.strip()
        return settings.prize_participation.strip()

    async def _ask(self, index: int) -> None:
        """Pone la pregunta ``index`` en pantalla."""
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

    def _question_text(self, index: int, *, lead: str) -> str:
        question = self._questions[index]
        a, b, c = question.options
        return QUESTION_TEXT.format(
            lead=lead, number=index + 1, total=self._total, question=question.text, a=a, b=b, c=c
        )

    async def _speak_when_quiet(self, game: int, prompt: str) -> None:
        await self._host.wait_idle(PANEL_WAIT_S)
        if game == self._game and self.active:
            await self._host.speak(prompt)

    # -- respuestas ---------------------------------------------------------

    def on_user_text(self, now: float) -> None:
        """Se oye al visitante: sigue ahí (para no dar la partida por abandonada)."""
        if self.active:
            self._last_user_at = now

    async def answer(self, choice: int, source: str) -> tuple[bool, str]:
        """Registra la respuesta (0, 1, 2 o :data:`PASS`). Nunca lanza.

        Con ``source="voice"`` (acción ``trivia_answer``) devuelve el guion
        para GPT-Live: el veredicto, un dato y lo siguiente. Con ``panel`` se
        lo pasa la partida a GPT-Live y devuelve un texto para el personal.
        """
        question = self._current
        if self._phase is not TriviaPhase.ASKING or question is None:
            if self._phase is TriviaPhase.REVEALING:
                if self._final:
                    return False, "Era la última pregunta: la trivia ya terminó, despídela."
                return False, WAITING_NEXT_TEXT.format(number=self._index + 1)
            return False, "No hay ninguna pregunta de trivia esperando respuesta."
        if choice not in (0, 1, 2, PASS):
            return False, "Respuesta no válida: A, B, C o que no lo sabe."
        self._phase = TriviaPhase.REVEALING
        self._last_user_at = time.monotonic()
        right = choice == question.correct
        if right:
            self._score += 1
        number = self._index + 1
        last = number >= self._total
        won = self._score >= self._threshold
        logger.info(
            "Trivia %d/%d (%s): %s -> %s (%d aciertos)",
            number,
            self._total,
            source,
            OPTION_LETTERS[choice] if choice >= 0 else "no lo sabe",
            "acierto" if right else f"fallo, era la {OPTION_LETTERS[question.correct]}",
            self._score,
        )
        self._host.touch()
        await self._screen.broadcast_json(
            p.msg_trivia_answer(number, choice, question.correct, right, self._score)
        )
        script = self._result_text(question, choice)
        if last:
            self._final = True
            template = WON_TEXT if won else LOST_TEXT
            script += template.format(
                score=self._score, total=self._total, threshold=self._threshold
            )
            prize = self._prize(won)
            if prize:
                script += PRIZE_TEXT.format(prize=prize)
            script += BACK_TO_TALK_TEXT
            self._spawn(self._finish_when_told(self._game, won, prize), "trivia-final")
        else:
            script += ASK_NEXT_TEXT
        if source == "voice":
            return True, script
        await self._host.speak(PANEL_ANSWER_TEXT + script)
        letter = OPTION_LETTERS[choice] if choice >= 0 else "«no lo sé»"
        return True, f"Respuesta {letter}: {'acierto' if right else 'fallo'}."

    async def next(self, source: str) -> tuple[bool, str]:
        """La siguiente pregunta, cuando el visitante la pide. Nunca lanza.

        Con ``voice`` (acción ``trivia_next``) devuelve el guion; con ``panel``
        se lo pasa a GPT-Live en cuanto calla.
        """
        question = self._current
        if not self.active or question is None:
            return False, "No hay ninguna trivia en marcha."
        if self._phase is TriviaPhase.ASKING:
            return False, (
                f"La pregunta {self._index + 1} aún espera respuesta: «{question.text}». "
                "Que conteste primero."
            )
        if self._final:
            return False, "Esa era la última pregunta: la trivia ya terminó."
        self._last_user_at = time.monotonic()
        self._host.touch()
        await self._ask(self._index + 1)
        logger.info("Trivia: pregunta %d de %d (%s)", self._index + 1, self._total, source)
        script = self._question_text(self._index, lead="Vamos con")
        if source == "voice":
            return True, script
        self._spawn(self._speak_when_quiet(self._game, "TRIVIA: " + script), "trivia-next")
        return True, f"Pregunta {self._index + 1} de {self._total} en pantalla."

    async def _finish_when_told(self, game: int, won: bool, prize: str) -> None:
        """Tras la última respuesta, la pantalla final cuando Sonia termina de contarlo.

        El resultado se queda al menos ``reveal_seconds``; luego se espera a que
        Sonia hable y vuelva a callar (con tope ``final_wait_seconds``), así la
        pantalla de victoria o derrota no le pisa la explicación.
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
            "Trivia terminada: %d de %d (%s)", self._score, self._total, "gana" if won else "pierde"
        )
        await self._end(won=won, reason="finished", prize=prize)
        with contextlib.suppress(Exception):
            await self._host.instruct(OFF_TEXT)

    def _result_text(self, question: TriviaQuestion, choice: int) -> str:
        right_letter = OPTION_LETTERS[question.correct]
        right_option = question.options[question.correct]
        if choice == PASS:
            text = PASS_TEXT.format(right_letter=right_letter, right_option=right_option)
        elif choice == question.correct:
            text = CORRECT_TEXT.format(letter=right_letter, option=right_option)
        else:
            text = WRONG_TEXT.format(
                letter=OPTION_LETTERS[choice],
                option=question.options[choice],
                right_letter=right_letter,
                right_option=right_option,
            )
        text += EXPLAIN_TEXT
        if question.fact:
            text += FACT_TEXT.format(fact=question.fact)
        return text

    # -- ciclo --------------------------------------------------------------

    async def tick(self, now: float) -> None:
        """Lo llama el ciclo del motor: recordar la pregunta y dar la partida por abandonada."""
        if self._phase is TriviaPhase.OFF or self._final:
            return
        settings = self._settings
        quiet = self._host.quiet_for()
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
            self._spawn(
                self._host.speak(REMIND_TEXT.format(number=self._index + 1)), "trivia-remind"
            )

    async def on_session_lost(self) -> None:
        """Se cayó o se renovó la sesión de GPT-Live: la partida no puede seguir."""
        if self.active:
            await self.stop("session")

    # -- utilidades ---------------------------------------------------------

    def _spawn(self, coro: Coroutine[Any, Any, Any], name: str) -> None:
        task = asyncio.create_task(coro, name=f"sonia-{name}")
        self._tasks.add(task)
        task.add_done_callback(self._task_done)

    def _task_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("La tarea %s de la trivia falló: %r", task.get_name(), task.exception())

    def _cancel_tasks(self) -> None:
        current = asyncio.current_task()
        for task in list(self._tasks):
            if task is not current and not task.done():
                task.cancel()
