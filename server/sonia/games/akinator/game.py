"""Akinator dev (``akinator``): el visitante piensa en algo tech y Sonia lo adivina con preguntas de sí o no.

Plan: ``docs/plan-juegos.md``, 5.3. Detalle: ``docs/juegos/akinator.md``.

**Quién hace qué.** GPT-Live lleva toda la conversación: hace las preguntas de sí o no
**sin delegar** (una delegación por pregunta lo haría lentísimo) y entiende lo que contesta
el visitante («sí», «no sé», «a veces»). El orquestador no entiende al visitante: solo

- cuenta las preguntas de Sonia en su transcripción (:mod:`~sonia.games.akinator.questions`)
  para los 20 puntos de la pantalla y para avisarle de que se queda sin preguntas;
- saca la tarjeta grande «¿Es… Kotlin?» cuando ella arriesga una respuesta
  (``akinator_guess``);
- registra cómo acaba (``akinator_result``): si acierta, confeti y presume; si falla, «¡me
  ganaste!» con lo que era, o sigue preguntando si le quedan preguntas.

**La pantalla.** Todos los eventos de Unity llevan el estado entero (fase, preguntas,
pregunta en curso, respuesta arriesgada y fallos), así que el último fijo basta para
repintarla si Unity se reconecta. Los eventos solo dicen qué acaba de pasar para animarlo
(``docs/protocolo.md``, «akinator»).

**Fases.** ``waiting`` (la tarjeta pide pensar en algo y espera el aviso del visitante) →
``asking`` (preguntas, con el contador) → ``guessing`` (hay una respuesta suya en pantalla
esperando el veredicto) ↔ ``asking`` (falló y le quedan preguntas) → ``giving_up`` (se
rinde y pregunta qué era) → ``revealed`` (resultado). La cuenta de preguntas no empieza
hasta que el visitante habla por primera vez tras el arranque: así un «¿listo?» de la
apertura no cuenta como la primera.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Sequence
from typing import Any, ClassVar, Literal

from sonia.actions.games import game_action
from sonia.games.akinator.bank import THEMES, Theme, normalize, theme_names
from sonia.games.akinator.prompts import (
    EARLY_GUESS_SCRIPT,
    FEW_LEFT_TEXT,
    GIVEUP_NUDGE,
    GIVEUP_REASON_MISS,
    GIVEUP_SCRIPT,
    GUESS_NUDGE,
    GUESS_SCRIPT,
    LAST_QUESTION_TEXT,
    LIMIT_NUDGE,
    LOSE_CONTACT_TEXT,
    LOSE_SCRIPT,
    MISS_SCRIPT,
    NO_ANSWER_SCRIPT,
    NO_GUESS_SCRIPT,
    NOT_CLEAR_SCRIPT,
    REPEATED_GUESS_SCRIPT,
    RESUME_GUESS,
    RESUME_SCRIPT,
    START_NUDGE,
    WIN_SCRIPT,
    build_rules,
    build_start_script,
)
from sonia.games.akinator.questions import QuestionCounter, extract_questions, is_giving_up
from sonia.games.banks import GameBank
from sonia.games.base import NOT_SAID, NOT_SAID_VALUES, Game, GameError, GameHost
from sonia.types import ActionSpec

__all__ = ["AkinatorGame", "Phase", "clean_answer", "screen_state", "screen_text"]

logger = logging.getLogger(__name__)

#: En qué va la partida (ver el módulo).
Phase = Literal["waiting", "asking", "guessing", "giving_up", "revealed"]

#: Intentos fallidos tras los que Sonia se rinde y pregunta qué era, aunque le queden preguntas.
MAX_GUESSES = 3

#: Con menos preguntas máximas no hay juego.
MIN_MAX_QUESTIONS = 5

#: Hasta que pasa esto desde el arranque, lo que se oye no es el aviso del visitante: puede
#: ser la transcripción tardía de su petición («jugamos al Akinator»).
READY_GRACE_S = 1.0

#: Largo máximo de lo que se enseña en la tarjeta.
QUESTION_CHARS = 120
ANSWER_CHARS = 60

_SPOKEN_NAME = re.compile(r"\bson[ií]a\b", re.IGNORECASE)
_TAGS = re.compile(r"<[^<>]*>")
_STRIP = " «»\"'“”‘’.,;:!¡¿?\n\t"


def screen_text(text: str) -> str:
    """Un texto para la pantalla: «Sonnia» con doble n (en lo hablado es «Sonia»)."""

    def written(match: re.Match[str]) -> str:
        word = match.group(0)
        if word.isupper():
            return "SONNIA"
        return "Sonnia" if word[0].isupper() else "sonnia"

    return _SPOKEN_NAME.sub(written, text)


def clean_answer(value: object) -> str:
    """La respuesta que llega del backend, lista para la pantalla (vacía si no dijo ninguna)."""
    if not isinstance(value, str):
        return ""
    text = " ".join(_TAGS.sub(" ", value).replace("<", " ").replace(">", " ").split())
    text = text.strip(_STRIP)
    if not text or text.lower().replace(" ", "_") in NOT_SAID_VALUES:
        return ""
    return screen_text(text)[:ANSWER_CHARS].rstrip()


def screen_state(
    *,
    phase: Phase,
    asked: int,
    max_questions: int,
    question: str = "",
    guess: str = "",
    missed: Sequence[str] = (),
    outcome: str = "",
    answer: str = "",
) -> dict[str, Any]:
    """El estado entero de la pantalla: el ``data`` de cada evento (menos ``start`` y ``end``).

    También lo usa ``demo.py``, para que el orquestador falso mande exactamente lo mismo.
    """
    return {
        "phase": phase,
        "asked": max(0, min(asked, max_questions)),
        "max": max_questions,
        "question": screen_text(question)[:QUESTION_CHARS],
        "guess": guess,
        "missed": list(missed),
        "outcome": outcome,
        "answer": answer,
    }


class AkinatorGame(Game):
    """El visitante piensa en algo del mundo tech y Sonia lo adivina con preguntas de sí o no."""

    id: ClassVar[str] = "akinator"
    title: ClassVar[str] = "Akinator dev"
    spoken: ClassVar[str] = "el Akinator dev"
    needs: ClassVar[frozenset[str]] = frozenset()
    settings_key: ClassVar[str] = "akinator"

    def __init__(self, host: GameHost) -> None:
        super().__init__(host)
        #: Los eventos de la pantalla salen en el orden en que cambia el estado.
        self._lock = asyncio.Lock()
        self._reset()

    def _reset(self) -> None:
        self._phase: Phase = "waiting"
        self._themes: list[Theme] = []
        self._max = 20
        self._min = 5
        self._started_at = 0.0
        self._ready = False
        self._counter = QuestionCounter()
        self._guess = ""
        self._misses: list[str] = []
        self._early_refused = False
        self._warned_few = False
        self._warned_last = False
        self._outcome = ""
        self._answer = ""

    # -- lo que declara el juego ----------------------------------------------

    @classmethod
    def banks(cls) -> list[GameBank[Any]]:
        return [THEMES]

    @classmethod
    def actions(cls) -> list[ActionSpec]:
        return [
            game_action(
                cls,
                name="akinator_guess",
                description=(
                    "Registra la respuesta que Sonia arriesga en el Akinator dev (por ejemplo "
                    "«Kotlin») y la saca en la pantalla como «¿Es… Kotlin?». Úsala cuando Sonia "
                    "tenga claro qué ha pensado el visitante, nunca antes de la pregunta 5. "
                    "Devuelve cómo preguntárselo."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "respuesta": {
                            "type": "string",
                            "description": (
                                "Lo que Sonia cree que pensó el visitante: solo el nombre "
                                "(por ejemplo «Kotlin» o «Linus Torvalds»)."
                            ),
                        }
                    },
                    "required": ["respuesta"],
                },
                play=AkinatorGame.guess,
            ),
            game_action(
                cls,
                name="akinator_result",
                description=(
                    "Registra cómo acaba el Akinator dev: si Sonia acertó, según el visitante, y "
                    "qué era en realidad. Úsala cuando el visitante confirme o niegue la "
                    "respuesta de Sonia, o cuando diga qué había pensado. Devuelve cómo "
                    "reaccionar."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "acierto": {
                            "type": "string",
                            "enum": ["si", "no", NOT_SAID],
                            "description": (
                                "«si» si el visitante dice que Sonia acertó, «no» si dice que "
                                f"falló, {NOT_SAID} si no dejó claro cuál de las dos."
                            ),
                        },
                        "respuesta_real": {
                            "type": "string",
                            "description": (
                                "Lo que había pensado el visitante: solo el nombre. Si Sonia "
                                f"acertó, su propia respuesta. Si no lo dijo, {NOT_SAID}."
                            ),
                        },
                    },
                    "required": ["acierto", "respuesta_real"],
                },
                play=AkinatorGame.result,
            ),
        ]

    # -- ciclo de vida --------------------------------------------------------

    async def start(self, source: str, options: dict[str, Any]) -> str:
        self._reset()
        settings = self.host.settings.games.akinator
        self._max = max(MIN_MAX_QUESTIONS, int(settings.max_questions))
        self._min = min(max(1, int(settings.min_questions)), self._max)
        themes = await self.host.load_bank(THEMES)
        if not themes:
            raise GameError(
                "El banco de temas del Akinator dev está vacío, así que no se puede jugar ahora."
            )
        self._themes = themes
        self._started_at = self.host.now()
        async with self._lock:
            await self.host.send("start", {"max": self._max, "themes": theme_names(themes)})
            await self._emit("waiting")
        await self.host.instruct(build_rules(self._max, self._min, themes))
        return build_start_script(themes)

    async def resume(self) -> str:
        guess = ""
        if self._phase == "guessing" and self._guess:
            guess = RESUME_GUESS.format(answer=self._guess)
        return RESUME_SCRIPT.format(asked=self._asked, max=self._max, guess=guess)

    # -- el estado ------------------------------------------------------------

    @property
    def _asked(self) -> int:
        """Preguntas de Sonia contadas, sin pasar del máximo (lo que pinta la pantalla)."""
        return min(self._counter.count, self._max)

    def _state(self) -> dict[str, Any]:
        """El estado entero de la pantalla (cada evento lo lleva)."""
        return screen_state(
            phase=self._phase,
            asked=self._counter.count,
            max_questions=self._max,
            question=self._counter.text,
            guess=self._guess,
            missed=self._misses,
            outcome=self._outcome,
            answer=self._answer,
        )

    async def _emit(self, event: str) -> None:
        await self.host.send(event, self._state())

    def snapshot(self) -> dict[str, Any]:
        return {
            "summary": self._summary(),
            "phase": self._phase,
            "asked": self._asked,
            "max": self._max,
            "question": self._counter.text,
            "guess": self._guess,
            "missed": list(self._misses),
            "ready": self._ready,
        }

    def _summary(self) -> str:
        """Una línea para la tarjeta «Juegos» del panel (``summary`` del ``snapshot``)."""
        if self._phase == "waiting":
            return "Esperando a que piense en algo"
        if self._phase == "guessing":
            return f"Pregunta {self._asked} de {self._max} · arriesga: {self._guess}"
        if self._phase == "giving_up":
            return "Se rinde: pregunta qué era"
        if self._phase == "revealed":
            if self._outcome == "sonnia":
                return f"Acertó: {self._answer}"
            return f"Perdió: era {self._answer}" if self._answer else "Perdió"
        return f"Pregunta {self._asked} de {self._max}"

    # -- lo que dice Sonia y lo que dice el visitante ---------------------------

    async def on_assistant_text(self, text: str, final: bool) -> None:
        if not self._counting():
            if final:
                self._counter.end_sentence()
            return
        async with self._lock:
            if not self._counting():
                if final:
                    self._counter.end_sentence()
                return
            questions = extract_questions(text)
            if questions and is_giving_up(questions[-1]):
                # «¿Qué era?»: se rinde. No es una pregunta del juego, pero la pantalla cambia.
                if final:
                    self._counter.end_sentence()
                self._phase = "giving_up"
                logger.info("Akinator: Sonia se rinde y pregunta qué era")
                await self._emit("giveup")
                return
            update = self._counter.feed(text, final=final)
            if update is None:
                return
            self._phase = "asking"
            await self._emit("question")
            if update.is_new:
                logger.info("Akinator: pregunta %d de %d: %s", self._asked, self._max, update.text)
                self._remind(update.count)

    def _counting(self) -> bool:
        return self._ready and self._phase in ("waiting", "asking")

    def _remind(self, count: int) -> None:
        """Avisos silenciosos a Sonia cuando se acaban las preguntas (no hablan: ``instruct``)."""
        if count >= self._max and not self._warned_last:
            self._warned_last = True
            text = LAST_QUESTION_TEXT.format(max=self._max)
            self.host.spawn(self.host.instruct(text), "ultima-pregunta")
        elif self._max >= 10 and count == self._max - 5 and not self._warned_few:
            self._warned_few = True
            text = FEW_LEFT_TEXT.format(asked=count, max=self._max)
            self.host.spawn(self.host.instruct(text), "quedan-pocas")

    def on_user_text(self, now: float) -> None:
        if not self._ready and now - self._started_at >= READY_GRACE_S:
            self._ready = True

    def nudge(self) -> str | None:
        if self._phase == "waiting" and self._ready and self._counter.count == 0:
            # El visitante ya habló y Sonia no ha empezado a preguntar.
            return START_NUDGE
        if self._phase == "guessing":
            return GUESS_NUDGE
        if self._phase == "giving_up":
            return GIVEUP_NUDGE
        if self._phase in ("waiting", "asking") and self._counter.count >= self._max:
            return LIMIT_NUDGE.format(max=self._max)
        return None

    # -- las jugadas ------------------------------------------------------------

    async def guess(self, arguments: dict[str, Any]) -> str:
        """``akinator_guess``: Sonia arriesga una respuesta y sale la tarjeta «¿Es… X?»."""
        answer = clean_answer(arguments.get("respuesta"))
        if not answer:
            raise GameError(
                "No me dijiste qué quieres adivinar. Pásame tu respuesta, por ejemplo «Kotlin»."
            )
        async with self._lock:
            if self._phase == "revealed":
                raise GameError(
                    "La partida ya terminó. Si quieren otra, delega empezarla de nuevo."
                )
            if self._counter.count < self._min and not self._early_refused:
                # Una sola vez: si insiste (o la cuenta se quedó corta), se deja pasar.
                self._early_refused = True
                raise GameError(EARLY_GUESS_SCRIPT.format(asked=self._counter.count, min=self._min))
            key = normalize(answer)
            if any(normalize(missed) == key for missed in self._misses):
                raise GameError(REPEATED_GUESS_SCRIPT.format(answer=answer))
            if self._phase == "guessing" and normalize(self._guess) == key:
                # La misma otra vez (GPT-Live la delegó dos veces): ya está en la pantalla.
                return GUESS_SCRIPT.format(answer=self._guess)
            if self._phase == "guessing" and self._guess:
                # Arriesga otra sin resolver la anterior: la anterior no era.
                self._misses.append(self._guess)
            self._guess = answer
            self._phase = "guessing"
            logger.info("Akinator: arriesga «%s» tras %d preguntas", answer, self._asked)
            await self._emit("guess")
        return GUESS_SCRIPT.format(answer=answer)

    async def result(self, arguments: dict[str, Any]) -> str:
        """``akinator_result``: cómo acaba, según el visitante, y qué era."""
        verdict = str(arguments.get("acierto") or NOT_SAID)
        real = clean_answer(arguments.get("respuesta_real"))
        async with self._lock:
            if self._phase == "revealed":
                raise GameError(
                    "La partida ya terminó. Si quieren otra, delega empezarla de nuevo."
                )
            pending = self._guess if self._phase == "guessing" else ""
            if verdict == "si" and self._phase == "giving_up":
                # Se rindió y preguntó qué era: lo que conteste el visitante no es un acierto.
                verdict = "no"
            if verdict == "si":
                answer = pending or real
                if not answer:
                    raise GameError(NO_ANSWER_SCRIPT)
                return await self._reveal("win", answer)
            if verdict == "no":
                return await self._miss(pending, real)
            # No quedó claro: con lo que era se puede decidir; si no, que se lo pregunte.
            if pending and real:
                if normalize(pending) == normalize(real):
                    return await self._reveal("win", pending)
                return await self._miss(pending, real)
            if real:
                return await self._miss(pending, real)
            if pending:
                return NOT_CLEAR_SCRIPT
            return NO_GUESS_SCRIPT

    async def _miss(self, pending: str, real: str) -> str:
        """Sonia falló: si el visitante dijo qué era, ganó; si no, sigue o se rinde."""
        if pending:
            self._misses.append(pending)
            self._guess = ""
        if real:
            return await self._reveal("lose", real)
        if not pending:
            if self._phase == "giving_up":
                return GIVEUP_SCRIPT.format(reason="")
            return NO_GUESS_SCRIPT
        left = self._max - self._asked
        logger.info(
            "Akinator: «%s» no era (fallos: %d, preguntas que quedan: %d)",
            pending,
            len(self._misses),
            left,
        )
        if left > 0 and len(self._misses) < MAX_GUESSES:
            self._phase = "asking"
            await self._emit("miss")
            return MISS_SCRIPT.format(answer=pending, left=left)
        self._phase = "giving_up"
        await self._emit("giveup")
        return GIVEUP_SCRIPT.format(reason=GIVEUP_REASON_MISS.format(answer=pending))

    async def _reveal(self, result: Literal["win", "lose"], answer: str) -> str:
        """El resultado final: la pantalla lo enseña ya y ``finish`` cierra la partida después."""
        won = result == "win"
        self._phase = "revealed"
        self._guess = ""
        self._answer = answer
        self._outcome = "sonnia" if won else "visitor"
        await self._emit("reveal")
        asked = self._asked
        tries = len(self._misses) + (1 if won else 0)
        logger.info(
            "Akinator: %s (era «%s», %d preguntas, %d intentos)",
            "acierta" if won else "pierde",
            answer,
            asked,
            tries,
        )
        await self.host.finish(
            result,
            {"outcome": self._outcome, "answer": answer, "asked": asked, "tries": tries},
        )
        if won:
            return WIN_SCRIPT.format(answer=answer, asked=asked)
        contact = self.host.settings.trivia.win_contact.strip()
        return LOSE_SCRIPT.format(
            answer=answer, contact=LOSE_CONTACT_TEXT.format(contact=contact) if contact else ""
        )
