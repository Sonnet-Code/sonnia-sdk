"""Wordle de tecnología (``wordle``): adivinar una palabra tech de 5 letras en 6 intentos, gritando palabras.

Lo explica ``docs/juegos/wordle.md``; el plan, ``docs/plan-juegos.md`` (5.5). Reparto, como en
la trivia:

- **El orquestador guarda la palabra y la pantalla.** Elige una del banco
  (``assets/games/wordle/palabras.md``, editable desde el panel) sin repetir hasta agotarlas
  y GPT-Live **no la conoce** hasta que termina la partida: no puede revelarla ni corregirla.
- **GPT-Live entiende y conduce.** El grupo grita palabras; GPT-Live elige la que se oye, la
  escribe bien y delega un intento (``wordle_guess``). Nada de parsers de lo que dice el
  visitante. Vale cualquier palabra de cinco letras, sin diccionario: es más divertido y evita
  discusiones.
- **El orquestador colorea.** Con la regla del Wordle de verdad, también con letras repetidas
  (:func:`sonia.games.wordle.logic.score_guess`), manda el tablero entero a Unity y le
  devuelve a GPT-Live un resumen corto («la L y la U están, pero en otro sitio»).
- **La pista** sale tras ``GAME_WORDLE_HINT_AFTER`` intentos fallidos. Si aciertan hay confeti;
  si se acaban los intentos, sale la palabra.

Una palabra que no vale (no tiene cinco letras, lleva símbolos o ya la probaron) no gasta
intento: sacude la fila y GPT-Live recibe un guion que lo dice. Ninguna jugada lanza: fuera
de turno devuelve un guion que reconduce.

Eventos de la pantalla (``docs/protocolo.md``): ``start`` (la rejilla vacía), ``guess`` (un
intento, con el tablero entero y el estado de las letras, fijo) e ``invalid`` (una sacudida,
suelto); el final lo manda el manager (``end``) tras :meth:`GameHost.finish`.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, ClassVar

from sonia.actions.games import game_action
from sonia.games.banks import GameBank
from sonia.games.base import Game, GameError, GameHost, StopReason
from sonia.games.wordle.bank import WORDS, pick_word
from sonia.games.wordle.logic import (
    GRAY,
    GREEN,
    NOT_A_WORD,
    WORD_LENGTH,
    WordCheck,
    check_word,
    describe_marks,
    score_guess,
    used_letters,
)
from sonia.types import ActionSpec

__all__ = ["WordleGame"]

logger = logging.getLogger(__name__)

#: Filas del tablero: lo que se pide en ``GAME_WORDLE_ROWS`` se queda entre estos topes (Unity
#: reparte la altura de la rejilla entre las filas).
MIN_ROWS = 3
MAX_ROWS = 8

#: A partir de cuántas letras verdes se les dice que van muy cerca.
CLOSE_GREENS = 3

#: Tope de caracteres de lo que dijo el grupo cuando se repite en un guion.
ECHO_MAX = 20

RULES_TEXT = """\
JUEGO EN MARCHA: Wordle de tecnología. Hay una palabra secreta de tecnología de {cols} letras y el grupo tiene {rows} intentos. El tablero está en tu pantalla y tú NO conoces la palabra.
- Cuando digan una palabra de {cols} letras (o la deletreen), sea de tecnología o no, escríbela bien y delega enseguida «wordle: intento PIZZA». Si dicen otra cosa o no se entiende, pregunta. Lo que hablan entre ellos no es un intento: si no está claro que te lo dicen a ti, pregunta antes. Si gritan varias a la vez, vale cualquiera de las que oigas bien; si dudas, pregunta.
- Con el resultado, cuenta en una frase corta qué letras están bien colocadas, cuáles en otro sitio y cuáles no están, y anímales a decir otra. Di solo lo que diga el resultado.
- Nunca digas si una palabra acierta ni qué letras tiene la secreta sin delegar el intento. {hint_rule}
- Si quieren dejarlo, delega terminarlo.
- En la pantalla nada cambia si no lo delegas: nunca digas «ya la puse» sin haberlo delegado."""

HINT_RULE = "La pista sale sola tras {hint_after} intentos; si la piden antes, que sigan probando."
NO_HINT_RULE = "No hay pistas: si la piden, que sigan probando."

START_TEXT = (
    "El Wordle de tecnología está en tu pantalla: hay una palabra secreta de tecnología de {cols} "
    "letras y el grupo tiene {rows} intentos. No la conoces. Explícalo en dos frases con energía "
    "(que griten palabras de {cols} letras y tú las vas poniendo en el tablero) y pídeles la "
    "primera."
)

RESUME_TEXT = (
    "Ya están jugando al Wordle: llevan {used} de {rows} intentos{tried}.{hint} Sigue con la "
    "partida donde iba y pídeles otra palabra."
)

GUESS_TEXT = (
    "Intento {number} de {rows}, «{word}»: {summary}. {left}{extra} Cuéntalo en una frase corta, "
    "con ánimo, y pídeles otra palabra."
)
ALL_GRAY_TEXT = " No ha salido ninguna letra, pero así descartan {n} de golpe."
CLOSE_TEXT = " ¡Van muy cerca!"
HINT_TEXT = " Ha salido la pista en la pantalla: léela tal cual, «{hint}»."

WON_TEXT = (
    "¡LO HAN ADIVINADO en el intento {number} de {rows}! La palabra era {word} (para que la "
    "cuentes: {hint}). Celébralo a lo grande y felicítales."
)
LOST_TEXT = (
    "Se acabaron los {rows} intentos y no lo adivinaron: la palabra era {word} (para que la "
    "cuentes: {hint}). Díselo con cariño y buen humor, que ha estado reñido, y anímales a una "
    "revancha."
)
#: Sonia no sabe qué premios hay: a quien gana lo manda con el equipo del stand.
WIN_CONTACT_TEXT = (
    " Diles que pasen a hablar con {contact} aquí en el stand. No sabes qué premios hay: no "
    "prometas ninguno y, si preguntan, que se lo cuenten ellos."
)
BACK_TO_TALK_TEXT = (
    " Si quieren otra partida, que te lo pidan y la empiezas. Luego sigue conversando con "
    "normalidad."
)

INVALID_TEXT = {
    "empty": "No me ha llegado ninguna palabra. Pídeles que digan una de {cols} letras.",
    "length": "«{said}» no sirve: tiene {count}, y tienen que ser {cols}.",
    "chars": (
        "«{said}» no sirve: tiene que ser una palabra de {cols} letras, sin números ni símbolos."
    ),
}
REPEATED_TEXT = "«{word}» ya la probaron antes."
INVALID_TAIL = (
    " No cuenta como intento: llevan {used} de {rows}. Díselo con humor y pídeles otra palabra."
)

#: Lo que se lee en la pantalla cuando la fila se sacude (en un rótulo de una sola línea: de
#: 25 caracteres como mucho).
INVALID_MESSAGES = {
    "empty": "No se entendió la palabra",
    "length": "Tienen que ser {cols} letras",
    "chars": "Solo letras, sin números",
    "repeated": "Esa ya la probaron",
}

OVER_TEXT = "La partida de Wordle ya ha terminado. Si quieren otra, delega empezarla de nuevo."

#: Empujón si el grupo habló en plena partida y GPT-Live no delegó nada.
NUDGE_TEXT = (
    "WORDLE: el grupo acaba de hablarte y no has delegado nada. Si te han dicho una palabra de "
    "{cols} letras, delégala ya como intento (decirlo no basta: el tablero solo cambia si "
    "delegas) y luego cuéntalo; si querían dejarlo, delega terminarlo. Si solo charlaban, no "
    "digas nada."
)


@dataclass(frozen=True, slots=True)
class Guess:
    """Un intento puesto en el tablero: sus letras y su color."""

    letters: str
    marks: str


def _echo(raw: object) -> str:
    """Lo que dijo el grupo, para repetirlo en un guion: solo letras y cifras, con tope."""
    text = "".join(char for char in str(raw or "") if char.isalnum())
    return text[:ECHO_MAX] + ("…" if len(text) > ECHO_MAX else "")


def _letters(count: int) -> str:
    return f"{count} letra" if count == 1 else f"{count} letras"


class WordleGame(Game):
    """Adivinar una palabra tech de 5 letras en 6 intentos, gritando palabras (plan, 5.5)."""

    id: ClassVar[str] = "wordle"
    title: ClassVar[str] = "Wordle de tecnología"
    spoken: ClassVar[str] = "el Wordle de tecnología"
    needs: ClassVar[frozenset[str]] = frozenset()
    settings_key: ClassVar[str] = "wordle"

    def __init__(self, host: GameHost) -> None:
        super().__init__(host)
        # Una jugada a la vez: dos intentos que llegan juntos no pueden pisarse las filas.
        self._lock = asyncio.Lock()
        # Palabra -> número de la partida en que salió. Sobrevive a ``start`` para no repetir
        # hasta agotar el banco.
        self._recent: dict[str, int] = {}
        self._matches = 0
        self._reset()

    def _reset(self) -> None:
        self._word = ""
        self._hint = ""
        self._rows = 6
        self._hint_after = 4
        self._guesses: list[Guess] = []
        self._hint_shown = False
        self._over = False

    # -- lo que declara el juego ----------------------------------------------

    @classmethod
    def banks(cls) -> list[GameBank[Any]]:
        return [WORDS]

    @classmethod
    def actions(cls) -> list[ActionSpec]:
        return [
            game_action(
                cls,
                name="wordle_guess",
                description=(
                    "Pone en el tablero del Wordle de tecnología la palabra de 5 letras que ha "
                    "dicho el grupo y devuelve qué letras están bien colocadas, cuáles en otro "
                    "sitio y cuáles no están, y cómo contarlo. Sonia te dice la palabra ya "
                    "escrita («el grupo prueba PIZZA»); si no te la dice, no la inventes: "
                    "contesta que falta."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "palabra": {
                            "type": "string",
                            "description": (
                                "La palabra del grupo, escrita bien y de corrido (si la deletrean, "
                                f"con las letras juntas). Si no dijeron ninguna, {NOT_A_WORD}."
                            ),
                        }
                    },
                    "required": ["palabra"],
                },
                play=WordleGame.guess,
            )
        ]

    # Sin ``phrases()``: ninguna jugada tiene un tiempo exacto, así que no hay frases grabadas.

    # -- ciclo de vida --------------------------------------------------------

    async def start(self, source: str, options: dict[str, Any]) -> str:
        words = await self.host.load_bank(WORDS)
        if not words:
            raise GameError("No hay palabras en el banco del Wordle.")
        self._reset()
        block = self.host.settings.games.wordle
        self._rows = max(MIN_ROWS, min(MAX_ROWS, int(block.rows)))
        self._hint_after = int(block.hint_after)
        picked = pick_word(words, self.host.rng, self._recent)
        self._matches += 1
        self._recent[picked.word] = self._matches
        self._word, self._hint = picked.word, picked.hint
        logger.info(
            "Wordle: partida %d con %d palabras en el banco; la palabra es %s",
            self._matches,
            len(words),
            self._word,
        )
        await self.host.send(
            "start", {"rows": self._rows, "cols": WORD_LENGTH, "hint_after": self._hint_after}
        )
        await self.host.instruct(self._rules())
        return START_TEXT.format(cols=WORD_LENGTH, rows=self._rows)

    def _rules(self) -> str:
        has_hint = 1 <= self._hint_after < self._rows
        hint_rule = HINT_RULE.format(hint_after=self._hint_after) if has_hint else NO_HINT_RULE
        return RULES_TEXT.format(cols=WORD_LENGTH, rows=self._rows, hint_rule=hint_rule)

    async def resume(self) -> str:
        tried = f" ({', '.join(g.letters for g in self._guesses)})" if self._guesses else ""
        hint = f" La pista de la pantalla dice: «{self._hint}»." if self._hint_shown else ""
        return RESUME_TEXT.format(used=len(self._guesses), rows=self._rows, tried=tried, hint=hint)

    async def stop(self, reason: StopReason) -> None:
        # Nada que soltar: sin cámara ni tareas. La palabra se queda hasta el próximo ``start``.
        self._over = True

    def nudge(self) -> str | None:
        return NUDGE_TEXT.format(cols=WORD_LENGTH)

    def snapshot(self) -> dict[str, Any]:
        return {
            "word": self._word,
            "hint": self._hint,
            "rows": self._rows,
            "attempts": len(self._guesses),
            "guesses": [guess.letters for guess in self._guesses],
            "hint_shown": self._hint_shown,
            "over": self._over,
        }

    # -- la jugada -------------------------------------------------------------

    async def guess(self, arguments: dict[str, Any]) -> str:
        """``wordle_guess``: pone la palabra del grupo en el tablero y cuenta qué salió."""
        async with self._lock:
            if self._over or not self._word:
                return OVER_TEXT
            raw = arguments.get("palabra")
            checked = check_word(raw)
            if not checked.ok:
                return await self._invalid(checked, raw)
            if checked.word in {guess.letters for guess in self._guesses}:
                return await self._repeated(checked.word)
            return await self._place(checked.word)

    async def _invalid(self, checked: WordCheck, raw: object) -> str:
        await self._shake(checked.shown, checked.reason)
        text = INVALID_TEXT.get(checked.reason, INVALID_TEXT["chars"]).format(
            said=_echo(raw), count=_letters(len(checked.word)), cols=WORD_LENGTH
        )
        return text + INVALID_TAIL.format(used=len(self._guesses), rows=self._rows)

    async def _repeated(self, word: str) -> str:
        await self._shake(word, "repeated")
        text = REPEATED_TEXT.format(word=word)
        return text + INVALID_TAIL.format(used=len(self._guesses), rows=self._rows)

    async def _shake(self, letters: str, reason: str) -> None:
        """La fila se sacude con lo que se entendió (suelto: no queda fijo)."""
        message = INVALID_MESSAGES.get(reason, INVALID_MESSAGES["chars"])
        await self.host.send(
            "invalid",
            {"letters": letters, "reason": reason, "message": message.format(cols=WORD_LENGTH)},
            sticky=False,
        )

    async def _place(self, word: str) -> str:
        marks = score_guess(word, self._word)
        self._guesses.append(Guess(word, marks))
        number = len(self._guesses)
        won = marks == GREEN * WORD_LENGTH
        lost = not won and number >= self._rows
        hint_now = not won and not lost and not self._hint_shown and 1 <= self._hint_after <= number
        if hint_now:
            self._hint_shown = True
        result = "win" if won else "lose" if lost else ""
        # Ganar o perder cierra la partida aquí mismo: ningún intento más puede entrar.
        self._over = bool(result)
        logger.info("Wordle: intento %d/%d %s -> %s", number, self._rows, word, marks)
        await self.host.send("guess", self._state(result))
        if won:
            await self.host.finish("win", {"word": self._word, "attempts": number})
            text = WON_TEXT.format(number=number, rows=self._rows, word=self._word, hint=self._hint)
            return self._ending(text, win=True)
        if lost:
            await self.host.finish("lose", {"word": self._word, "attempts": number})
            text = LOST_TEXT.format(rows=self._rows, word=self._word, hint=self._hint)
            return self._ending(text, win=False)
        return GUESS_TEXT.format(
            number=number,
            rows=self._rows,
            word=word,
            summary=describe_marks(word, marks),
            left=self._left_text(),
            extra=self._extra(word, marks, hint_now),
        )

    def _left_text(self) -> str:
        left = self._rows - len(self._guesses)
        return "Queda un solo intento." if left == 1 else f"Quedan {left} intentos."

    def _extra(self, word: str, marks: str, hint_now: bool) -> str:
        extra = ""
        if all(mark == GRAY for mark in marks):
            extra += ALL_GRAY_TEXT.format(n=_letters(len(set(word))))
        elif marks.count(GREEN) >= CLOSE_GREENS:
            extra += CLOSE_TEXT
        if hint_now:
            extra += HINT_TEXT.format(hint=self._hint)
        return extra

    def _ending(self, text: str, *, win: bool) -> str:
        contact = self.host.settings.trivia.win_contact.strip()
        if win and contact:
            text += WIN_CONTACT_TEXT.format(contact=contact)
        return text + BACK_TO_TALK_TEXT

    def _state(self, result: str) -> dict[str, Any]:
        """El tablero entero y el estado de las letras: lo que Unity pinta y repite al reconectar."""
        last = self._guesses[-1]
        return {
            "row": len(self._guesses) - 1,
            "letters": last.letters,
            "marks": last.marks,
            "board": [{"letters": g.letters, "marks": g.marks} for g in self._guesses],
            "used": used_letters([(g.letters, g.marks) for g in self._guesses]),
            "hint": self._hint if self._hint_shown or result == "lose" else "",
            "result": result,
            "word": self._word if result else "",
        }
