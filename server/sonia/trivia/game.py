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

Los textos para GPT-Live se editan desde el panel (``trivia/*``, :func:`prompt_specs`):
cada uno se pide al registro (``BOOK``) al usarlo. Los que se encadenan en un guion van sin
espacios en los bordes (la nube los recorta) y el código los une con un espacio.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import re
import time
from collections.abc import Callable, Coroutine
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from sonia.config import TriviaSettings
from sonia.prompts import BOOK, PromptSpec
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

INTRO_TEXT = "La trivia está en tu pantalla, nivel {level}."
READY_TEXT = (
    "La trivia está preparada, nivel {level}, pero aún no ha empezado ni sale en tu pantalla: "
    "sale cuando arranques."
)
LEVEL_TEXT = "Si pide otro nivel (fácil, intermedio o difícil), delega reiniciarla con ese nivel."
KICKOFF_TEXT = (
    "{lead} con energía: di en una frase que son {total} preguntas y que con {threshold} "
    "aciertos gana."
)

#: Para jugar hay que seguir a Sonnet Code, y se pide antes de empezar. La partida se prepara
#: ya (GPT-Live tiene la primera pregunta) y sale en pantalla cuando Sonia arranca: si
#: esperaba a una segunda delegación («ya las sigo»), GPT-Live se la saltaba cuando el
#: visitante contestaba mientras ella hablaba y se inventaba la pregunta (registro y pruebas
#: con la API real del 8 de octubre de 2026).
FOLLOW_TEXT = (
    "Antes de empezar, pregúntale solo si ya sigue a Sonnet Code en Instagram y LinkedIn "
    "(@sonnetcode); si no, que escanee el QR de la pantalla y las siga. No lo puedes comprobar: "
    "créele. Espera su respuesta: no digas todavía la pregunta ni cuántas son. Si no quiere "
    "seguirlas, dile con cariño que es lo único que pide la trivia y, si aun así no quiere, "
    "delega terminarla. Cuando te diga que ya las sigue (no antes),"
)

#: Margen de la primera pregunta mientras el visitante sigue a Sonnet Code con el móvil:
#: ni recordatorio ni partida abandonada por no oírle. Pasado, la trivia sale en pantalla.
FOLLOW_GRACE_S = 45.0

#: Lo que dice Sonia al arrancar (:data:`KICKOFF_TEXT`) y saca la trivia a la pantalla.
KICKOFF_WORDS = frozenset({"acierto", "aciertos"})
#: Parte de las palabras de la primera pregunta que tiene que haber dicho para sacarla.
QUESTION_HEARD_SHARE = 0.5

QUESTION_TEXT = (
    "{lead} la pregunta {number} de {total} y lee solo la pregunta, tal cual: «{question}». "
    "No leas las opciones, ya están en la pantalla (para ti: A: {a}; B: {b}; C: {c})."
)

#: Las opciones de cada pregunta, directas a GPT-Live: el backend resumía el guion y se
#: las comía, y Sonia no sabía que «Cobol» era la B (7 de octubre de 2026).
#: Delante de :data:`OPTIONS_TEXT` mientras se pregunta si sigue a Sonnet Code: con la
#: pregunta en la mano, GPT-Live la leía sin esperar el «ya las sigo» (8 de octubre de 2026).
WAIT_OPTIONS_TEXT = (
    "TRIVIA PREPARADA, AÚN SIN EMPEZAR: primero pregúntale si sigue a Sonnet Code en Instagram "
    "y LinkedIn y espera a que te diga que sí; no digas antes la pregunta ni cuántas son."
)
OPTIONS_TEXT = (
    "TRIVIA, pregunta {number} de {total}: «{question}». Opciones en la pantalla, para que "
    "sepas qué letra elige el visitante, diga la letra o la respuesta (no las leas): "
    "A: {a}; B: {b}; C: {c}."
)

REMIND_TEXT = (
    "TRIVIA: no hay ninguna respuesta registrada para la pregunta {number}. Si el visitante ya "
    "te dijo su opción, delega ahora «trivia: responde» con su letra, sin decir si acierta. Si "
    "no, anímale en pocas palabras y, si hace falta, repite la pregunta, sin leer las opciones "
    "(están en la pantalla)."
)

#: Empujón si el visitante habló en plena partida y GPT-Live no delegó nada: a veces
#: decía «la termino» o «la marco» sin delegar (7 de octubre de 2026). Lo decide ella.
NUDGE_TEXT = (
    "TRIVIA: el visitante acaba de hablarte y no has delegado nada. Si te ha pedido dejar de "
    "jugar, otra desde cero o la siguiente pregunta, o te ha dicho su opción, delégalo ahora "
    "mismo (decirlo no basta: la pantalla solo cambia si delegas) y luego dilo en pocas "
    "palabras. Si solo charlaba, no digas nada."
)

#: Segundos tras el turno del visitante sin ninguna delegación antes del empujón.
NUDGE_S = 3.0

CORRECT_TEXT = "Ha elegido la {letter}, «{option}»: es CORRECTA. Celébralo."
WRONG_TEXT = (
    "Ha elegido la {letter}, «{option}»: NO es correcta; la buena era la {right_letter}, "
    "«{right_option}». Díselo con cariño."
)
PASS_TEXT = "No lo sabe. La buena era la {right_letter}, «{right_option}». Díselo con cariño."
EXPLAIN_TEXT = "Explica en una o dos frases por qué es la buena."
FACT_TEXT = "Apóyate en este dato: {fact}"
ASK_NEXT_TEXT = (
    "Luego pregúntale si quiere pasar a la siguiente pregunta y espera: cuando diga que sí, "
    "delega «trivia: siguiente pregunta»; si no quiere seguir, delega terminar la trivia."
)
WON_TEXT = (
    "Con esto termina la trivia: ha acertado {score} de {total} y HA GANADO. Felicítale a lo "
    "grande."
)
LOST_TEXT = (
    "Con esto termina la trivia: ha acertado {score} de {total} y le faltaron aciertos para "
    "los {threshold}. Anímale con cariño a intentarlo otra vez."
)
#: Sonia no sabe qué premios hay: a quien gana lo manda con el equipo del stand.
WIN_CONTACT_TEXT = (
    "Dile que pase a hablar con {contact} aquí en el stand. No sabes qué premios hay: no "
    "prometas ninguno y, si pregunta, que se lo cuenten ellos."
)
BACK_TO_TALK_TEXT = "Luego sigue conversando con normalidad."

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
#: La pieza editable de cada texto de :data:`CANCEL_TEXT`.
CANCEL_PIECES = {"panel": "trivia/cancelada_panel", "abandoned": "trivia/cancelada_abandono"}


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
        busy: Callable[[], str | None] | None = None,
    ) -> None:
        self._settings = settings
        #: Por qué no puede empezar ahora por otra cosa (un juego en marcha), o ``None``.
        self._busy = busy
        self._bank_file = bank_file
        self._host = host
        self._screen = screen
        self._rng = rng or random.Random()
        self._bank = TriviaBank.from_file(bank_file)
        #: Banco guardado en la nube desde el panel (ajuste compartido ``trivia_bank``);
        #: ``None``: el archivo que trae la app.
        self._cloud_text: str | None = None
        #: Pregunta -> partida en que salió por última vez: no se repiten hasta agotar el nivel.
        self._asked: dict[str, int] = {}
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
        #: Cuándo toca el empujón de :data:`NUDGE_TEXT` (0: no toca) y la última delegación.
        self._nudge_at = 0.0
        self._delegated_at = float("-inf")
        #: Se le ha preguntado si sigue a Sonnet Code y aún no ha contestado a la primera:
        #: su «ya las sigo» no es una respuesta, así que no hay empujón.
        self._follow_pending = False
        #: Pantalla retenida hasta que Sonia arranca (``None``: no se retiene) y lo que ha
        #: dicho mientras tanto.
        self._held: dict[str, dict[str, Any]] | None = None
        self._heard: set[str] = set()
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
    def questions_per_game(self) -> int:
        """Preguntas de una partida: un banco necesita al menos estas."""
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
        """Para el panel: en qué va la partida."""
        question = self._current if self.active else None
        return {
            "available": self.available,
            "bank": len(self._bank),
            "bank_source": "cloud" if self._cloud_text is not None else "app",
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

    # -- banco de preguntas -------------------------------------------------

    def use_cloud_bank(self, text: str | None) -> bool:
        """Usa el banco guardado en la nube desde el panel (``None``: el de la app).

        Si no llega a las preguntas de una partida, sigue el de la app: un error al
        editarlo no puede dejar a Sonia sin trivia. La partida en marcha sigue con sus
        preguntas; el banco nuevo sale en la siguiente. Devuelve si se usa el de la nube.
        """
        if text:
            bank = TriviaBank.from_text(text, source="banco de la nube")
            if len(bank) >= self._total:
                self._cloud_text = text
                self._bank = bank
                logger.info("Trivia: banco de la nube con %d preguntas", len(bank))
                return True
            logger.warning(
                "El banco de la nube tiene %d preguntas válidas y hacen falta %d: "
                "sigue el de la app",
                len(bank),
                self._total,
            )
        self._cloud_text = None
        self._bank = TriviaBank.from_file(self._bank_file)
        return False

    def bank_text(self) -> str:
        """El banco en uso, en el formato del archivo (para editarlo en el panel). Lee disco."""
        if self._cloud_text is not None:
            return self._cloud_text
        try:
            return self._bank_file.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("No se pudo leer el banco de la trivia %s: %s", self._bank_file, exc)
            return ""

    def draw_one(self, level: str | None = None) -> TriviaQuestion | None:
        """Una pregunta suelta del banco en uso (el de la nube, si lo hay), opciones barajadas.

        Respeta el «sin repetir» de las partidas: primero las que nunca han salido y
        después las que hace más. Sin ``level``, el de ``TRIVIA_DEFAULT_LEVEL``. ``None``
        si el banco está vacío. No lee disco. La usa la trivia relámpago de la ruleta
        (``docs/juegos/ruleta.md``).
        """
        wanted = (
            normalize_level(level) or normalize_level(self._settings.default_level) or DEFAULT_LEVEL
        )
        drawn = self._bank.draw(1, self._rng, wanted, recent=self._asked)
        if not drawn:
            return None
        self._asked[drawn[0].text] = self._game
        return drawn[0]

    def _draw(self) -> list[TriviaQuestion]:
        """Las preguntas de la partida, empezando por las que hace más que no salen."""
        questions = self._bank.draw(self._total, self._rng, self._level, recent=self._asked)
        for question in questions:
            self._asked[question.text] = self._game
        return questions

    # -- arranque y final ---------------------------------------------------

    async def start(
        self, source: str, level: str | None = None, *, ask_follow: bool = False
    ) -> tuple[bool, str]:
        """Empieza una partida. Nunca lanza.

        Con ``source="voice"`` (acción ``start_trivia``) devuelve el guion para
        que GPT-Live lo diga como resultado de la acción. Con ``panel`` se lo
        pasa la partida a GPT-Live en cuanto calla y devuelve un texto para el
        personal del stand. Con ``ask_follow``, el guion pide preguntarle antes
        de la primera si sigue a Sonnet Code (:data:`FOLLOW_TEXT`).
        """
        if not self._settings.enabled:
            return False, "La trivia está desactivada (TRIVIA_ENABLED=false)."
        if self.active:
            return False, "Ya hay una trivia en marcha."
        busy = self._busy() if self._busy is not None else None
        if busy:
            return False, busy
        if not self._host.connected:
            return False, "Sonnia no está conectada a GPT-Live ahora mismo."
        # Se relee el archivo: se puede editar durante el evento sin reiniciar. El banco
        # de la nube, si lo hay, manda y llega por el panel.
        if self._cloud_text is None:
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
        self._questions = self._draw()
        self._score = 0
        self._final = False
        self._last_user_at = time.monotonic()
        logger.info(
            "Trivia en marcha (%s): %d preguntas, nivel %s", source, self._total, self._level
        )
        self._host.touch()
        # Mientras se pregunta si sigue a Sonnet Code, la pantalla espera: el QR sigue a la vista.
        self._held = {} if ask_follow else None
        self._heard = set()
        if not ask_follow:
            await self._screen.hide_image()
        await self._show(
            STICKY_START, p.msg_trivia_start(self._total, self._threshold, self._level)
        )
        await self._host.instruct(
            BOOK.render(
                "trivia/reglas",
                fallback=RULES_TEXT,
                total=self._total,
                threshold=self._threshold,
                level=self._level,
            )
        )
        self._follow_pending = ask_follow
        await self._ask(0)
        intro_id, intro = (
            ("trivia/preparada", READY_TEXT) if ask_follow else ("trivia/presentacion", INTRO_TEXT)
        )
        parts = [
            BOOK.render(
                intro_id,
                fallback=intro,
                level=self._level,
                total=self._total,
                threshold=self._threshold,
            ),
            BOOK.text("trivia/otro_nivel", LEVEL_TEXT),
        ]
        if ask_follow:
            grace = time.monotonic() + FOLLOW_GRACE_S
            self._asked_at = self._last_user_at = grace
            parts.append(BOOK.text("trivia/seguir_sonnet_code", FOLLOW_TEXT))
        parts.append(self._kickoff_text("arranca" if ask_follow else "Arranca"))
        parts.append(self._question_text(0, lead="Después di"))
        script = " ".join(parts)
        if source == "voice":
            return True, script
        self._spawn(self._speak_when_quiet(self._game, "TRIVIA: " + script), "trivia-intro")
        return True, (
            f"Trivia en marcha, nivel {self._level}: {self._total} preguntas, gana con "
            f"{self._threshold}."
        )

    async def restart(self, source: str, level: str | None = None) -> tuple[bool, str]:
        """Empieza una partida nueva, cortando sin despedida la que haya en marcha.

        Si aún no ha contestado ninguna (pide otro nivel al empezar), solo cambian
        las preguntas: la partida sigue y Sonia no se quita y se vuelve a poner la gorra.
        """
        if self.active and self._index == 0 and self._phase is TriviaPhase.ASKING:
            return await self._change_level(source, level)
        if self.active:
            logger.info("Trivia reiniciada (%s) con %d de %d", source, self._score, self._index + 1)
            level = level or self._level
            await self._end(won=False, reason="cancelled")
        ok, script = await self.start(source, level)
        if ok and source == "voice":
            script = "Trivia nueva desde cero. " + script
        return ok, script

    async def _change_level(self, source: str, level: str | None) -> tuple[bool, str]:
        """Otras preguntas del nivel ``level`` antes de contestar la primera."""
        self._level = normalize_level(level) or self._level
        self._questions = self._draw()
        logger.info("Trivia: nivel %s antes de la primera (%s)", self._level, source)
        self._host.touch()
        await self._show(
            STICKY_START, p.msg_trivia_start(self._total, self._threshold, self._level)
        )
        grace = max(self._asked_at, self._last_user_at)
        await self._ask(0)
        # Si aún sigue a Sonnet Code con el móvil, se mantiene su margen.
        self._asked_at = max(self._asked_at, grace)
        script = f"Ahora la trivia es de nivel {self._level} y la primera pregunta es otra. "
        if self._held is not None:
            script += "Sigue sin salir en tu pantalla hasta que arranques. "
        if self._follow_pending:
            script += "Si aún no te ha dicho que sigue a Sonnet Code, pregúntaselo antes. "
        script += self._kickoff_text("Arranca") + " " + self._question_text(0, lead="Después di")
        if source == "voice":
            return True, script
        self._spawn(self._speak_when_quiet(self._game, "TRIVIA: " + script), "trivia-level")
        return True, f"Trivia de nivel {self._level}: otras preguntas desde la primera."

    async def resume(self) -> str:
        """El guion si se pide empezar la trivia con la partida ya en marcha.

        Pasa si GPT-Live vuelve a delegar empezarla tras el «ya las sigo»: sin
        esto, el backend le contaba que no se pudo empezar. Si la pantalla
        esperaba a que arrancase, sale ya.
        """
        await self.show_screen()
        question = self._current
        if not self.active or question is None:
            return BOOK.text("trivia/fin", OFF_TEXT)
        if self._phase is TriviaPhase.REVEALING:
            if self._final:
                return "Era la última pregunta: la trivia ya terminó, despídela."
            return self._waiting_next_text()
        text = "La trivia ya está en marcha en tu pantalla, no hace falta empezarla. "
        if self._index > 0:
            return text + self._question_text(self._index, lead="Si no la has leído, lee")
        text += self._kickoff_text("Arranca")
        return text + " " + self._question_text(0, lead="Después di")

    async def stop(self, reason: str) -> tuple[bool, str]:
        """Cancela la partida. ``reason``: ``panel``, ``voice``, ``abandoned``, ``session``..."""
        if not self.active:
            return False, "No hay ninguna trivia en marcha."
        logger.info("Trivia cancelada (%s) con %d de %d", reason, self._score, self._index + 1)
        await self._end(won=False, reason="cancelled")
        if self._host.connected and reason != "session":
            text = CANCEL_TEXT.get(reason)
            with contextlib.suppress(Exception):
                await self._host.instruct(BOOK.text("trivia/fin", OFF_TEXT))
                if text:
                    await self._host.speak(BOOK.text(CANCEL_PIECES[reason], text))
        return True, "Trivia terminada."

    async def _end(self, *, won: bool, reason: str) -> None:
        self._phase = TriviaPhase.OFF
        self._follow_pending = False
        # Lo que no llegó a salir en pantalla se tira: Unity ignora el final sin trivia.
        self._held = None
        self._cancel_tasks()
        self._screen.clear_sticky(STICKY_START)
        self._screen.clear_sticky(STICKY_QUESTION)
        await self._screen.broadcast_json(
            p.msg_trivia_end(self._score, self._total, won=won, reason=reason)
        )

    async def _show(self, key: str, msg: dict[str, Any]) -> None:
        """Manda un mensaje fijo de la pantalla, o lo guarda si la pantalla espera."""
        if self._held is not None:
            self._held[key] = msg
            return
        await self._screen.set_sticky(key, msg)

    async def show_screen(self) -> None:
        """Saca a la pantalla la trivia retenida mientras se preguntaba lo de Sonnet Code."""
        held, self._held = self._held, None
        if held is None:
            return
        logger.info("Trivia: sale en pantalla")
        with contextlib.suppress(Exception):
            await self._screen.hide_image()
            for key in (STICKY_START, STICKY_QUESTION):
                if key in held:
                    await self._screen.set_sticky(key, held[key])

    async def on_assistant_text(self, text: str) -> None:
        """Lo que va diciendo Sonia: si arranca la trivia retenida, sale en pantalla.

        Arranca al decir cuántos aciertos hacen falta (:data:`KICKOFF_TEXT`) o al
        leer buena parte de la primera pregunta. Nunca lanza.
        """
        question = self._current
        if self._held is None or question is None:
            return
        self._heard |= _words(text)
        wanted = _words(question.text)
        said = len(wanted & self._heard)
        if self._heard & KICKOFF_WORDS or (
            said >= min(2, len(wanted)) and said >= QUESTION_HEARD_SHARE * len(wanted)
        ):
            await self.show_screen()

    async def _ask(self, index: int) -> None:
        """Pone la pregunta ``index`` en pantalla."""
        self._index = index
        question = self._questions[index]
        self._phase = TriviaPhase.ASKING
        self._asked_at = time.monotonic()
        self._reminded = False
        await self._show(
            STICKY_QUESTION,
            p.msg_trivia_question(
                index + 1, self._total, question.text, list(question.options), self._score
            ),
        )
        a, b, c = question.options
        with contextlib.suppress(Exception):
            note = BOOK.render(
                "trivia/opciones",
                fallback=OPTIONS_TEXT,
                number=index + 1,
                total=self._total,
                question=question.text,
                a=a,
                b=b,
                c=c,
            )
            if self._follow_pending:
                note = BOOK.text("trivia/opciones_espera", WAIT_OPTIONS_TEXT) + " " + note
            await self._host.instruct(note)

    def _question_text(self, index: int, *, lead: str) -> str:
        question = self._questions[index]
        a, b, c = question.options
        return BOOK.render(
            "trivia/pregunta",
            fallback=QUESTION_TEXT,
            lead=lead,
            number=index + 1,
            total=self._total,
            question=question.text,
            a=a,
            b=b,
            c=c,
        )

    def _kickoff_text(self, lead: str) -> str:
        """Que arranque diciendo cuántas preguntas son y con cuántos aciertos se gana."""
        return BOOK.render(
            "trivia/arranque",
            fallback=KICKOFF_TEXT,
            lead=lead,
            total=self._total,
            threshold=self._threshold,
        )

    def _waiting_next_text(self) -> str:
        """Una respuesta o una petición de empezar con el resultado aún en pantalla."""
        return BOOK.render(
            "trivia/espera_siguiente", fallback=WAITING_NEXT_TEXT, number=self._index + 1
        )

    async def _speak_when_quiet(self, game: int, prompt: str) -> None:
        await self._host.wait_idle(PANEL_WAIT_S)
        if game == self._game and self.active:
            await self._host.speak(prompt)

    # -- respuestas ---------------------------------------------------------

    def on_user_text(self, now: float) -> None:
        """Se oye al visitante: sigue ahí (para no dar la partida por abandonada)."""
        if self.active:
            # Sin pisar el margen de :data:`FOLLOW_GRACE_S` mientras sigue a Sonnet Code.
            self._last_user_at = max(self._last_user_at, now)

    def on_user_turn_end(self, now: float, started_at: float) -> None:
        """Terminó un turno del visitante (empezó en ``started_at``): si no delega nada, empujón.

        GPT-Live suele delegar antes de que llegue el final de la transcripción:
        lo delegado desde que empezó a hablar ya cuenta.
        """
        if self.active and not self._follow_pending and self._delegated_at < started_at - 0.5:
            self._nudge_at = now + NUDGE_S

    def on_delegation(self, now: float) -> None:
        """GPT-Live delegó algo: no hace falta empujón."""
        self._delegated_at = now
        self._nudge_at = 0.0

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
                return False, self._waiting_next_text()
            return False, "No hay ninguna pregunta de trivia esperando respuesta."
        if choice not in (0, 1, 2, PASS):
            return False, "Respuesta no válida: A, B, C o que no lo sabe."
        await self.show_screen()
        self._phase = TriviaPhase.REVEALING
        self._follow_pending = False
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
        parts = [self._result_text(question, choice)]
        if last:
            self._final = True
            piece, template = ("trivia/gana", WON_TEXT) if won else ("trivia/pierde", LOST_TEXT)
            parts.append(
                BOOK.render(
                    piece,
                    fallback=template,
                    score=self._score,
                    total=self._total,
                    threshold=self._threshold,
                )
            )
            contact = self._settings.win_contact.strip()
            if won and contact:
                parts.append(
                    BOOK.render("trivia/contacto", fallback=WIN_CONTACT_TEXT, contact=contact)
                )
            parts.append(BOOK.text("trivia/volver_a_conversar", BACK_TO_TALK_TEXT))
            self._spawn(self._finish_when_told(self._game, won), "trivia-final")
        else:
            parts.append(BOOK.text("trivia/siguiente", ASK_NEXT_TEXT))
        script = " ".join(parts)
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

    async def _finish_when_told(self, game: int, won: bool) -> None:
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
        await self._end(won=won, reason="finished")
        with contextlib.suppress(Exception):
            await self._host.instruct(BOOK.text("trivia/fin", OFF_TEXT))

    def _result_text(self, question: TriviaQuestion, choice: int) -> str:
        right_letter = OPTION_LETTERS[question.correct]
        right_option = question.options[question.correct]
        if choice == PASS:
            verdict = BOOK.render(
                "trivia/no_lo_sabe",
                fallback=PASS_TEXT,
                right_letter=right_letter,
                right_option=right_option,
            )
        elif choice == question.correct:
            verdict = BOOK.render(
                "trivia/correcta", fallback=CORRECT_TEXT, letter=right_letter, option=right_option
            )
        else:
            verdict = BOOK.render(
                "trivia/incorrecta",
                fallback=WRONG_TEXT,
                letter=OPTION_LETTERS[choice],
                option=question.options[choice],
                right_letter=right_letter,
                right_option=right_option,
            )
        parts = [verdict, BOOK.text("trivia/explicar", EXPLAIN_TEXT)]
        if question.fact:
            parts.append(BOOK.render("trivia/dato", fallback=FACT_TEXT, fact=question.fact))
        return " ".join(parts)

    # -- ciclo --------------------------------------------------------------

    async def tick(self, now: float) -> None:
        """Lo llama el ciclo del motor: recordar la pregunta y dar la partida por abandonada."""
        if self._phase is TriviaPhase.OFF or self._final:
            self._nudge_at = 0.0
            return
        settings = self._settings
        quiet = self._host.quiet_for()
        if self._held is not None and now >= self._asked_at:
            logger.info("Trivia: pasó el margen para seguir a Sonnet Code; sale en pantalla")
            await self.show_screen()
        if self._nudge_at and now >= self._nudge_at and quiet >= 0.5:
            # Ya contestó sin delegar: que lo decida ella. Va por commentary porque una
            # instrucción silenciosa no le abre turno y no delegaba (probado con la API).
            self._nudge_at = 0.0
            logger.info("Trivia: el visitante habló y no se delegó nada; se le recuerda")
            self._spawn(self._host.speak(BOOK.text("trivia/empujon", NUDGE_TEXT)), "trivia-nudge")
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
            remind = BOOK.render(
                "trivia/recordatorio",
                fallback=REMIND_TEXT,
                number=self._index + 1,
                total=self._total,
            )
            self._spawn(self._host.speak(remind), "trivia-remind")

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


def _words(text: str) -> set[str]:
    """Palabras de cuatro letras o más, en minúsculas y sin tildes, para comparar lo dicho."""
    plain = text.lower().translate(str.maketrans("áéíóúü", "aeiouu"))
    return {w for w in re.findall(r"\w+", plain) if len(w) >= 4}


#: Tope de las notas que van por ``session.instructions.append`` (``APPEND_MAX_CHARS``).
_NOTE_MAX = 1200
#: Lo que va delante de cada pieza del guion en la ayuda del panel.
_JOINED = "Se une a las demás piezas del guion con un espacio."


def prompt_specs() -> list[PromptSpec]:
    """Los textos de la trivia editables desde el panel (grupo «Trivia», ``trivia/*``)."""

    def piece(
        name: str,
        title: str,
        default: str,
        *,
        fields: tuple[str, ...] = (),
        required: tuple[str, ...] = (),
        help: str = "",
        max_len: int = _NOTE_MAX,
    ) -> PromptSpec:
        return PromptSpec(
            id=f"trivia/{name}",
            group="Trivia",
            title=title,
            default=lambda: default,
            fields=fields,
            required=required,
            applies="ronda",
            help=help,
            max_len=max_len,
        )

    counts = "{total}: preguntas de la partida; {threshold}: aciertos para ganar"
    return [
        piece(
            "reglas",
            "Reglas al empezar (nota para Sonia, sin hablar)",
            RULES_TEXT,
            fields=("total", "threshold", "level"),
            help=f"{counts}; {{level}}: fácil, intermedio o difícil. Como mucho 1200 caracteres.",
        ),
        piece(
            "opciones",
            "Cada pregunta con sus opciones (nota para Sonia, sin hablar)",
            OPTIONS_TEXT,
            fields=("number", "total", "question", "a", "b", "c"),
            required=("a", "b", "c"),
            help=(
                "{number}: número de la pregunta; {total}: preguntas de la partida; {question}: "
                "la pregunta; {a}, {b} y {c}: las opciones de cada letra, para que sepa qué "
                "letra elige el visitante. Va en una nota de 1200 caracteres con la pregunta y "
                "las opciones dentro (y, en la primera, con «opciones_espera» delante)."
            ),
            max_len=600,
        ),
        piece(
            "opciones_espera",
            "Delante de la primera pregunta si aún tiene que seguir a Sonnet Code",
            WAIT_OPTIONS_TEXT,
            help="Va delante de «opciones», en la misma nota, con un espacio.",
            max_len=300,
        ),
        piece(
            "presentacion",
            "Arranque: la trivia ya está en pantalla",
            INTRO_TEXT,
            fields=("level", "total", "threshold"),
            help=f"{{level}}: el nivel; {counts}. {_JOINED}",
        ),
        piece(
            "preparada",
            "Arranque: preparada, pero aún sin salir en pantalla (sigue a Sonnet Code)",
            READY_TEXT,
            fields=("level", "total", "threshold"),
            help=f"{{level}}: el nivel; {counts}. {_JOINED}",
        ),
        piece(
            "otro_nivel",
            "Arranque: si pide otro nivel",
            LEVEL_TEXT,
            help=_JOINED,
        ),
        piece(
            "seguir_sonnet_code",
            "Arranque: pedir que siga a Sonnet Code antes de empezar",
            FOLLOW_TEXT,
            help=(
                "Va justo antes de «arranque», que sigue en minúscula («arranca con energía…»): "
                f"deja la última frase a medias para que siga con él. {_JOINED}"
            ),
        ),
        piece(
            "arranque",
            "Arranque: cuántas preguntas son y con cuántos aciertos se gana",
            KICKOFF_TEXT,
            fields=("lead", "total", "threshold"),
            help=(
                "{lead}: «Arranca», o «arranca» si va detrás de «seguir_sonnet_code»; "
                f"{counts}. Si Sonia dice «aciertos», la trivia sale en pantalla en ese momento "
                f"(si no, al leer la pregunta). {_JOINED}"
            ),
        ),
        piece(
            "pregunta",
            "Leer la pregunta",
            QUESTION_TEXT,
            fields=("lead", "number", "total", "question", "a", "b", "c"),
            required=("question",),
            help=(
                "{lead}: «Después di», «Vamos con» o «Si no la has leído, lee»; {number}: número "
                "de la pregunta; {total}: preguntas de la partida; {question}: la pregunta (sin "
                "ella se inventa una); {a}, {b} y {c}: las opciones."
            ),
        ),
        piece(
            "correcta",
            "Resultado: acierto",
            CORRECT_TEXT,
            fields=("letter", "option"),
            help=f"{{letter}}: la letra que eligió; {{option}}: su opción. {_JOINED}",
        ),
        piece(
            "incorrecta",
            "Resultado: fallo",
            WRONG_TEXT,
            fields=("letter", "option", "right_letter", "right_option"),
            required=("right_letter", "right_option"),
            help=(
                "{letter} y {option}: lo que eligió; {right_letter} y {right_option}: la buena "
                f"(sin ella no sabe cuál explicar). {_JOINED}"
            ),
        ),
        piece(
            "no_lo_sabe",
            "Resultado: no lo sabe",
            PASS_TEXT,
            fields=("right_letter", "right_option"),
            required=("right_letter", "right_option"),
            help=f"{{right_letter}} y {{right_option}}: la buena. {_JOINED}",
        ),
        piece(
            "explicar",
            "Resultado: explicar por qué es la buena",
            EXPLAIN_TEXT,
            help=_JOINED,
        ),
        piece(
            "dato",
            "Resultado: el dato de la pregunta (si el banco lo trae)",
            FACT_TEXT,
            fields=("fact",),
            required=("fact",),
            help=f"{{fact}}: la línea «>» de la pregunta en el banco. {_JOINED}",
        ),
        piece(
            "siguiente",
            "Tras el resultado: preguntar si quiere la siguiente",
            ASK_NEXT_TEXT,
            help=_JOINED,
        ),
        piece(
            "espera_siguiente",
            "Contesta otra vez con el resultado aún en pantalla",
            WAITING_NEXT_TEXT,
            fields=("number",),
            help="{number}: la pregunta ya contestada.",
        ),
        piece(
            "gana",
            "Final: ha ganado",
            WON_TEXT,
            fields=("score", "total", "threshold"),
            help=f"{{score}}: aciertos; {counts}. {_JOINED}",
        ),
        piece(
            "pierde",
            "Final: no llegó a los aciertos",
            LOST_TEXT,
            fields=("score", "total", "threshold"),
            help=f"{{score}}: aciertos; {counts}. {_JOINED}",
        ),
        piece(
            "contacto",
            "Final: con quién del stand habla quien gana",
            WIN_CONTACT_TEXT,
            fields=("contact",),
            required=("contact",),
            help=(
                "{contact}: TRIVIA_WIN_CONTACT (Brian o Mariel). Sin contacto no se dice. "
                f"{_JOINED}"
            ),
        ),
        piece(
            "volver_a_conversar",
            "Final: volver a conversar",
            BACK_TO_TALK_TEXT,
            help=_JOINED,
        ),
        piece(
            "recordatorio",
            "Recordatorio si no contesta",
            REMIND_TEXT,
            fields=("number", "total"),
            help="{number}: la pregunta que espera; {total}: preguntas de la partida.",
        ),
        piece(
            "empujon",
            "Empujón si el visitante habló y no se delegó nada",
            NUDGE_TEXT,
            help="La hace hablar: escríbelo como una orden corta, sin frases que pueda repetir.",
        ),
        piece(
            "cancelada_panel",
            "Terminada desde el panel",
            CANCEL_TEXT["panel"],
        ),
        piece(
            "cancelada_abandono",
            "Cancelada porque el visitante ya no contesta",
            CANCEL_TEXT["abandoned"],
        ),
        piece(
            "fin",
            "Fin de la trivia (nota para Sonia, sin hablar)",
            OFF_TEXT,
            help="Como mucho 1200 caracteres.",
        ),
    ]
