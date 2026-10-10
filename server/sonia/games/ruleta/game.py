"""La ruleta de Sonnia (``ruleta``): una ruleta en pantalla elige uno de cinco retos.

Plan, sección 5.1; detalle en ``docs/juegos/ruleta.md``. Cómo va una vuelta:

1. **El giro.** El orquestador elige la casilla con los pesos de ``GAME_RULETA_WEIGHTS``,
   sin repetir la anterior, prepara ya su reto (la pregunta, la adivinanza...) y manda
   ``spin`` con la casilla de destino. Unity gira, frena y contesta ``wheel_stopped``. Si
   no contesta en :data:`SPIN_SECONDS` + :data:`SPIN_GRACE_S`, el orquestador sigue solo:
   nunca se queda colgado esperando.
2. **El reto.** Con la ruleta parada, la tarjeta del reto va a la pantalla
   (``challenge``), sus reglas a GPT-Live (``instruct``) y, en cuanto Sonia calla, que lo
   anuncie (``speak``). Los contadores (el visual de la trivia relámpago, la pista de la
   adivinanza, los segundos para explicar) cuentan desde que termina de anunciarlo.
3. **El resultado.** Las jugadas delegadas (``ruleta_answer``, ``ruleta_score`` y
   ``ruleta_prediccion``) lo ponen en pantalla (``result``) y devuelven la reacción, y Sonia
   ofrece otra vuelta (``ruleta_spin``) o terminar (``stop_game``).

La partida no termina sola: dura hasta ``stop_game``, el panel o el abandono. GPT-Live no
sabe la buena de la trivia relámpago hasta el resultado; la respuesta de la adivinanza y de
las preguntas de Sonnet Code sí la recibe, para juzgar respuestas libres, y no la dice.
Toda jugada fuera de turno devuelve un texto que reconduce (``GameError``), nunca un fallo.
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, TypeVar

from sonia.actions.games import game_action
from sonia.games.banks import GameBank
from sonia.games.base import (
    INSTRUCT_MAX_CHARS,
    NOT_SAID,
    Game,
    GameError,
    GameHost,
    StopReason,
)
from sonia.games.ruleta import texts as t
from sonia.games.ruleta.banks import RIDDLES, SONNET, TECHS, Riddle, SonnetChallenge, Tech
from sonia.types import ActionSpec

__all__ = [
    "ANSWER_VALUES",
    "DEFAULT_WEIGHTS",
    "SPIN_SECONDS",
    "Kind",
    "Round",
    "RuletaGame",
    "Segment",
    "build_segments",
    "challenge_data",
    "clean_prediction",
    "for_live",
    "for_screen",
    "parse_weights",
    "result_data",
    "segment_data",
    "spin_data",
]

logger = logging.getLogger(__name__)

T = TypeVar("T")

#: Los cinco retos, en el orden de las casillas y de ``GAME_RULETA_WEIGHTS``.
Kind = Literal["trivia", "adivinanza", "explica", "futuro", "sonnet"]
KINDS: tuple[Kind, ...] = ("trivia", "adivinanza", "explica", "futuro", "sonnet")

#: En qué va la partida: girando, jugando un reto o enseñando su resultado.
Phase = Literal["idle", "spinning", "challenge", "result"]

#: Cómo acabó un reto: superado, fallado, se rindieron o hecho (la nota y la predicción).
Outcome = Literal["win", "lose", "pass", "done"]

DEFAULT_WEIGHTS: tuple[float, ...] = (1.0, 1.0, 1.0, 1.0, 1.0)

#: Lo que dura el giro en Unity (va en ``spin``), y lo que se espera de más a ``wheel_stopped``.
SPIN_SECONDS = 4.6
SPIN_GRACE_S = 3.0

#: Antes de anunciar el reto, espera a que Sonia calle como mucho esto.
ANNOUNCE_WAIT_S = 6.0
#: Sonia terminó de anunciarlo cuando, tras oírla, lleva esto callada...
ANNOUNCE_QUIET_S = 0.8
#: ...o, si no se la oye (sin sesión), pasado esto desde que se le pidió.
ANNOUNCE_FALLBACK_S = 15.0
#: Por debajo de esto, Sonia está hablando (``quiet_for``).
SPEAKING_S = 0.3

#: Explica en 20 segundos: si el visitante no empieza a hablar, el tiempo arranca a esto.
EXPLAIN_AUTOSTART_S = 5.0
#: Tras «¡Tiempo!», espera a que se callen como mucho esto antes de pedir la nota.
TIME_UP_WAIT_S = 4.0
#: Trivia relámpago: pasado el contador (y esto), un recordatorio si no hay respuesta.
QUIZ_REMIND_GRACE_S = 2.0
QUIZ_REMIND_QUIET_S = 1.0
#: La pista se dice en cuanto Sonia calla, como mucho tras esto.
HINT_WAIT_S = 3.0

#: Intentos de la adivinanza (la pista sale con el primer fallo) y de las preguntas de
#: Sonnet Code.
RIDDLE_TRIES = 3
SONNET_TRIES = 2

#: Nota a partir de la que «explica en 20 segundos» cuenta como reto superado.
GOOD_SCORE = 7
#: Retos superados en una partida a los que Sonia manda al visitante con el equipo del stand.
WIN_MARK = 3

#: Tope de la predicción en pantalla.
PREDICTION_MAX = 120

#: Enum de ``ruleta_answer``, válido en todos los retos: la letra de la trivia relámpago,
#: acierto o fallo (lo juzga Sonia: adivinanza y Sonnet Code), se rinden y no lo dijo.
ANSWER_VALUES: tuple[str, ...] = ("A", "B", "C", "acierto", "fallo", "se_rinden", NOT_SAID)
OPTION_LETTERS = ("A", "B", "C")
GIVE_UP = "se_rinden"

#: Lo que sale en la tarjeta de «predice el futuro de la IA» (no tiene banco).
FUTURE_PROMPT = "¿Qué pasará con la inteligencia artificial en los próximos años?"

_SONIA = re.compile(r"\bSonia\b")
_SONNIA = re.compile(r"\bSonnia\b")
_SPACES = re.compile(r"\s+")


def for_screen(text: str) -> str:
    """En pantalla se escribe «Sonnia» (``CLAUDE.md``, principio 6)."""
    return _SONIA.sub("Sonnia", text)


def for_live(text: str) -> str:
    """Lo que lee GPT-Live dice «Sonia»."""
    return _SONNIA.sub("Sonia", text)


_ARTICLES = ("El ", "La ", "Los ", "Las ", "Un ", "Una ")


def _in_sentence(name: str) -> str:
    """«La nube» → «la nube», para decirlo en mitad de una frase."""
    for article in _ARTICLES:
        if name.startswith(article):
            return article.lower() + name[len(article) :]
    return name


def _seconds(value: float) -> str:
    """20.0 → «20»; 12.5 → «12,5»."""
    return f"{value:g}".replace(".", ",")


def _clip(text: str, limit: int) -> str:
    text = _SPACES.sub(" ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,.;:")
    return (cut or text[: limit - 1]) + "…"


def clean_prediction(value: object) -> str:
    """La predicción tal como sale en pantalla: una línea de :data:`PREDICTION_MAX` como mucho."""
    if not isinstance(value, str):
        return ""
    text = value.strip().strip("«»\"'").strip()
    return _clip(text, PREDICTION_MAX) if text else ""


def _as_int(value: object, low: int, high: int, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    if isinstance(value, float) and not math.isfinite(value):
        return default
    return max(low, min(high, round(value)))


def parse_weights(raw: str) -> tuple[float, ...]:
    """``GAME_RULETA_WEIGHTS`` («1,1,1,1,1»): cinco pesos de 0 en adelante.

    Si no se entiende (otro número de pesos, negativos, todo ceros), los de por defecto.
    """
    parts = [part for part in re.split(r"[,;\s]+", raw.strip()) if part]
    try:
        values = tuple(float(part) for part in parts)
    except ValueError:
        values = ()
    if (
        len(values) != len(KINDS)
        or any(not math.isfinite(v) or v < 0 for v in values)
        or not any(v > 0 for v in values)
    ):
        logger.warning("GAME_RULETA_WEIGHTS=%r no vale: se usan los pesos iguales", raw)
        return DEFAULT_WEIGHTS
    return values


@dataclass(frozen=True, slots=True)
class Segment:
    """Una casilla de la ruleta: su reto, lo que pone en la ruleta y en la tarjeta, cómo se
    le llama ante GPT-Live y su icono (Unity lo dibuja)."""

    kind: Kind
    label: str
    title: str
    spoken: str
    icon: str


def build_segments(explain_seconds: float) -> tuple[Segment, ...]:
    """Las cinco casillas, en el orden de los pesos."""
    s = _seconds(explain_seconds)
    return (
        Segment("trivia", "Trivia relámpago", "TRIVIA RELÁMPAGO", "trivia relámpago", "bolt"),
        Segment("adivinanza", "Adivinanza geek", "ADIVINANZA GEEK", "adivinanza geek", "riddle"),
        Segment(
            "explica",
            f"Explica en {s} s",
            f"EXPLICA EN {s} SEGUNDOS",
            f"explica una tecnología en {s} segundos",
            "mic",
        ),
        Segment(
            "futuro",
            "Futuro de la IA",
            "PREDICE EL FUTURO DE LA IA",
            "predice el futuro de la IA",
            "crystal",
        ),
        Segment(
            "sonnet",
            "Reto Sonnet Code",
            "RETO SORPRESA DE SONNET CODE",
            "reto sorpresa de Sonnet Code",
            "star",
        ),
    )


@dataclass(slots=True)
class Round:
    """Una vuelta de la ruleta: la casilla, su reto ya preparado y cómo va."""

    spin: int
    segment: int
    kind: Kind
    #: El texto del reto tal cual (pregunta, adivinanza, tecnología o reto).
    prompt: str
    options: tuple[str, ...] = ()
    correct: int = -1
    fact: str = ""
    answer: str = ""
    variants: tuple[str, ...] = ()
    hint: str = ""
    description: str = ""
    #: Reto de stand de Sonnet Code (se le cree), no una pregunta.
    task: bool = False
    tries: int = 0
    misses: int = 0
    hint_shown: bool = False
    timer_s: float = 0.0
    timer_at: float | None = None
    time_up: bool = False
    outcome: Outcome | None = None
    chosen: int = -1
    score: int = 0
    prediction: str = ""
    probability: int = -1


class RuletaGame(Game):
    """Una ruleta en pantalla elige uno de cinco retos (plan, 5.1)."""

    id: ClassVar[str] = "ruleta"
    title: ClassVar[str] = "La ruleta de Sonnia"
    spoken: ClassVar[str] = "la ruleta de Sonia"
    needs: ClassVar[frozenset[str]] = frozenset()
    settings_key: ClassVar[str] = "ruleta"

    def __init__(self, host: GameHost) -> None:
        super().__init__(host)
        self._segments = build_segments(20.0)
        self._weights = DEFAULT_WEIGHTS
        self._riddles: list[Riddle] = []
        self._techs: list[Tech] = []
        self._sonnet: list[SonnetChallenge] = []
        #: Entradas de cada banco -> cuándo salieron: no se repiten hasta agotarlas. Dura
        #: lo que el motor (no se borra entre partidas), como el «sin repetir» de la trivia.
        self._recent: dict[str, dict[str, int]] = {"adivinanza": {}, "explica": {}, "sonnet": {}}
        self._uses = 0
        self._reset()

    def _reset(self) -> None:
        self._phase: Phase = "idle"
        self._spins = 0
        self._wins = 0
        self._contact_said = False
        self._round: Round | None = None
        self._previous: int | None = None
        #: Casillas sin reto en esta partida (banco vacío, trivia apagada).
        self._off: set[int] = set()
        self._spin_deadline = 0.0
        self._landed_at = 0.0
        self._announce_asked_at: float | None = None
        self._announce_heard = False
        self._announced_at: float | None = None
        self._hint_at: float | None = None
        self._quiz_deadline: float | None = None
        self._quiz_reminded = False
        self._voice_at: float | None = None

    # -- lo que declara el juego ----------------------------------------------

    @classmethod
    def actions(cls) -> list[ActionSpec]:
        return [
            game_action(
                cls,
                name="ruleta_spin",
                description=(
                    "Gira otra vez la ruleta de Sonia cuando el visitante quiere otra vuelta "
                    "(o cambiar de reto). Devuelve qué decir mientras gira; el reto nuevo le "
                    "llega a Sonia cuando la ruleta para."
                ),
                parameters={"type": "object", "properties": {}, "required": []},
                play=RuletaGame.spin_again,
            ),
            game_action(
                cls,
                name="ruleta_answer",
                description=(
                    "Registra la respuesta del visitante al reto de la ruleta. Trivia "
                    "relámpago: la letra que eligió (A, B o C). Adivinanza y reto de Sonnet "
                    "Code: acierto (contestó bien o hizo el reto) o fallo. se_rinden si no lo "
                    "sabe, se rinde o no quiere hacerlo; no_lo_dijo si aún no contestó. "
                    "Devuelve el resultado y cómo seguir."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "respuesta": {
                            "type": "string",
                            "enum": list(ANSWER_VALUES),
                            "description": (
                                "A, B o C en la trivia relámpago; acierto o fallo en la "
                                "adivinanza y en el reto de Sonnet Code; se_rinden; o "
                                "no_lo_dijo si aún no contestó."
                            ),
                        }
                    },
                    "required": ["respuesta"],
                },
                play=RuletaGame.answer,
            ),
            game_action(
                cls,
                name="ruleta_score",
                description=(
                    "Pone en la pantalla la nota del 1 al 10 que Sonia le da a la explicación "
                    "del visitante en el reto de explicar una tecnología. Devuelve cómo "
                    "comentarla."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "nota": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 10,
                            "description": "La nota, un número entero del 1 al 10.",
                        }
                    },
                    "required": ["nota"],
                },
                play=RuletaGame.score,
            ),
            game_action(
                cls,
                name="ruleta_prediccion",
                description=(
                    "Pone en la pantalla la predicción del visitante sobre el futuro de la "
                    "IA, resumida por Sonia, y la probabilidad de 0 a 100 que ella le da. "
                    "Devuelve cómo comentarla."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "prediccion": {
                            "type": "string",
                            "maxLength": PREDICTION_MAX,
                            "description": (
                                "La predicción resumida en una frase en español, de "
                                f"{PREDICTION_MAX} caracteres como mucho."
                            ),
                        },
                        "probabilidad": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 100,
                            "description": "La probabilidad que le da Sonia, de 0 a 100.",
                        },
                    },
                    "required": ["prediccion", "probabilidad"],
                },
                play=RuletaGame.predict,
            ),
        ]

    @classmethod
    def banks(cls) -> list[GameBank[Any]]:
        return [RIDDLES, TECHS, SONNET]

    def phrases(self) -> list[str]:
        return [t.TIME_PHRASE]

    # -- ciclo de vida --------------------------------------------------------

    async def start(self, source: str, options: dict[str, Any]) -> str:
        self._reset()
        settings = self.host.settings.games.ruleta
        self._segments = build_segments(settings.explain_seconds)
        self._weights = parse_weights(settings.weights)
        self._riddles = await self.host.load_bank(RIDDLES)
        self._techs = await self.host.load_bank(TECHS)
        self._sonnet = await self.host.load_bank(SONNET)
        empty = {"adivinanza": not self._riddles, "explica": not self._techs}
        empty["sonnet"] = not self._sonnet
        self._off = {i for i, seg in enumerate(self._segments) if empty.get(seg.kind, False)}
        if not self._live_segments():
            raise GameError(
                "La ruleta no tiene retos que jugar ahora mismo (bancos vacíos o pesos a cero)."
            )
        await self.host.send("start", {"segments": self._segment_data()})
        await self.host.instruct(self._rules_text())
        await self._spin()
        logger.info("Ruleta en marcha (%s)", source)
        return t.START_TEXT

    async def resume(self) -> str:
        round_ = self._round
        if self._phase == "spinning" or round_ is None:
            return t.RESUME_SPINNING
        if self._phase == "challenge":
            return t.RESUME_CHALLENGE.format(spoken=self._segments[round_.segment].spoken)
        return t.RESUME_RESULT

    async def stop(self, reason: StopReason) -> None:
        logger.info(
            "Ruleta terminada (%s): %d vueltas, %d retos superados", reason, self._spins, self._wins
        )
        self._phase = "idle"
        self._hint_at = None
        self._quiz_deadline = None

    async def tick(self, now: float) -> None:
        round_ = self._round
        if round_ is None:
            return
        if self._phase == "spinning":
            if now >= self._spin_deadline:
                logger.info("Ruleta: la pantalla no avisó de que paró; se sigue sin esperar")
                await self._land(now)
            return
        if self._phase != "challenge":
            return
        await self._track_announcement(now, round_)
        if round_.kind == "trivia":
            self._tick_quiz(now, round_)
        elif round_.kind == "adivinanza":
            await self._tick_hint(now, round_)
        elif round_.kind == "explica":
            await self._tick_explain(now, round_)

    # -- ganchos --------------------------------------------------------------

    def on_user_text(self, now: float) -> None:
        round_ = self._round
        if (
            self._phase == "challenge"
            and round_ is not None
            and round_.kind == "explica"
            and self._announced_at is not None
            and round_.timer_at is None
            and self._voice_at is None
        ):
            # El visitante empieza a explicar: el contador arranca en el próximo tick.
            self._voice_at = now

    async def on_unity_event(self, event: str, data: dict[str, Any]) -> None:
        if event != "wheel_stopped":
            logger.debug("Ruleta: evento de la pantalla desconocido %r", event)
            return
        round_ = self._round
        if self._phase != "spinning" or round_ is None:
            return
        spin = data.get("spin")
        if isinstance(spin, int) and not isinstance(spin, bool) and spin != round_.spin:
            logger.debug("Ruleta: wheel_stopped de la vuelta %s (va la %d)", spin, round_.spin)
            return
        segment = data.get("segment")
        if isinstance(segment, int) and segment != round_.segment:
            logger.warning(
                "Ruleta: la pantalla paró en la casilla %s y tocaba la %d: manda la del "
                "orquestador",
                segment,
                round_.segment,
            )
        await self._land(self.host.now())

    def nudge(self) -> str | None:
        round_ = self._round
        if self._phase == "challenge" and round_ is not None:
            if round_.kind == "explica" and not round_.time_up:
                return None  # está explicando: nada de empujones
            return t.NUDGE_CHALLENGE
        if self._phase == "result":
            return t.NUDGE_RESULT
        return None

    def snapshot(self) -> dict[str, Any]:
        round_ = self._round
        segment = self._segments[round_.segment] if round_ is not None else None
        return {
            "summary": self._summary(),
            "phase": self._phase,
            "spins": self._spins,
            "wins": self._wins,
            "challenge": round_.kind if round_ is not None else "",
            "title": segment.title if segment is not None else "",
            "prompt": for_screen(round_.prompt) if round_ is not None else "",
            "outcome": (round_.outcome or "") if round_ is not None else "",
        }

    def _summary(self) -> str:
        """Una línea para la tarjeta «Juegos» del panel: «Vuelta 3: Adivinanza geek, superada»."""
        round_ = self._round
        if round_ is None or self._phase == "idle":
            return "Sin vuelta en marcha"
        head = f"Vuelta {round_.spin}"
        label = self._segments[round_.segment].label
        if self._phase == "spinning":
            text = f"{head}: girando"
        elif self._phase == "challenge":
            text = f"{head}: {label}"
        else:
            if round_.kind == "explica" and round_.outcome == "done":
                how = f"nota {round_.score}"
            elif round_.kind == "futuro" and round_.outcome == "done":
                how = f"{round_.probability} %"
            else:
                how = {"win": "superado", "lose": "fallado", "pass": "se rindieron"}.get(
                    round_.outcome or "", "hecho"
                )
            text = f"{head}: {label}, {how}"
        if self._wins:
            text += f" · {self._wins} {'superado' if self._wins == 1 else 'superados'}"
        return text

    # -- jugadas ----------------------------------------------------------------

    async def spin_again(self, arguments: dict[str, Any]) -> str:
        """``ruleta_spin``: otra vuelta (con un reto a medias, se lo salta)."""
        if self._phase == "spinning":
            raise GameError(t.ALREADY_SPINNING)
        skipped = self._phase == "challenge"
        if skipped and self._round is not None:
            logger.info("Ruleta: se salta el reto %s sin jugarlo", self._round.kind)
        await self._spin()
        return t.SKIP_TEXT if skipped else t.SPIN_TEXT

    async def answer(self, arguments: dict[str, Any]) -> str:
        """``ruleta_answer``: la letra, acierto, fallo o se rinden, según el reto."""
        value = str(arguments.get("respuesta", NOT_SAID))
        round_ = self._challenge()
        if value == NOT_SAID:
            raise GameError(t.NOT_SAID_YET)
        if round_.kind == "trivia":
            return await self._answer_quiz(round_, value)
        if round_.kind == "adivinanza":
            return await self._answer_riddle(round_, value)
        if round_.kind == "sonnet":
            return await self._answer_sonnet(round_, value)
        if value != GIVE_UP:
            raise GameError(t.WRONG_PLAY[round_.kind])
        await self._resolve(round_, "pass")
        text = t.EXPLAIN_PASS if round_.kind == "explica" else t.FUTURE_PASS
        return text + self._after(round_)

    async def score(self, arguments: dict[str, Any]) -> str:
        """``ruleta_score``: la nota de la explicación."""
        round_ = self._challenge()
        if round_.kind != "explica":
            raise GameError(t.WRONG_PLAY[round_.kind])
        round_.score = _as_int(arguments.get("nota"), 1, 10, 5)
        await self._resolve(round_, "done")
        return t.EXPLAIN_SCORE.format(score=round_.score) + self._after(round_)

    async def predict(self, arguments: dict[str, Any]) -> str:
        """``ruleta_prediccion``: la predicción resumida y su probabilidad."""
        round_ = self._challenge()
        if round_.kind != "futuro":
            raise GameError(t.WRONG_PLAY[round_.kind])
        prediction = clean_prediction(arguments.get("prediccion"))
        if not prediction:
            raise GameError(t.NO_PREDICTION)
        round_.prediction = prediction
        round_.probability = _as_int(arguments.get("probabilidad"), 0, 100, 50)
        await self._resolve(round_, "done")
        script = t.FUTURE_DONE.format(
            prediction=for_live(prediction), probability=round_.probability
        )
        return script + self._after(round_)

    def _challenge(self) -> Round:
        """El reto en juego, o un ``GameError`` que reconduce si ahora no hay ninguno."""
        round_ = self._round
        if self._phase == "spinning":
            raise GameError(t.SPINNING_WAIT)
        if self._phase != "challenge" or round_ is None:
            raise GameError(t.ROUND_OVER)
        return round_

    async def _answer_quiz(self, round_: Round, value: str) -> str:
        right_letter = OPTION_LETTERS[round_.correct]
        right_option = for_live(round_.options[round_.correct])
        if value == GIVE_UP:
            await self._resolve(round_, "pass")
            script = t.TRIVIA_PASS.format(right_letter=right_letter, right_option=right_option)
        elif value in OPTION_LETTERS:
            round_.chosen = OPTION_LETTERS.index(value)
            option = for_live(round_.options[round_.chosen])
            if round_.chosen == round_.correct:
                await self._resolve(round_, "win")
                script = t.TRIVIA_RIGHT.format(letter=value, option=option)
            else:
                await self._resolve(round_, "lose")
                script = t.TRIVIA_WRONG.format(
                    letter=value,
                    option=option,
                    right_letter=right_letter,
                    right_option=right_option,
                )
        else:
            raise GameError(t.WRONG_PLAY["trivia"])
        if round_.fact:
            script += t.FACT_TEXT.format(fact=for_live(round_.fact))
        return script + self._after(round_)

    async def _answer_riddle(self, round_: Round, value: str) -> str:
        answer = for_live(round_.answer)
        if value == "acierto":
            await self._resolve(round_, "win")
            return t.RIDDLE_RIGHT.format(answer=answer) + self._after(round_)
        if value == GIVE_UP:
            await self._resolve(round_, "pass")
            return t.RIDDLE_PASS.format(answer=answer) + self._after(round_)
        if value != "fallo":
            raise GameError(t.WRONG_PLAY["adivinanza"])
        round_.misses += 1
        if round_.misses >= round_.tries:
            await self._resolve(round_, "lose")
            return t.RIDDLE_LOST.format(answer=answer) + self._after(round_)
        # Con el primer fallo sale la pista, si aún no había salido.
        hint_now = not round_.hint_shown
        round_.hint_shown = True
        self._hint_at = None
        await self.host.send("challenge", self._challenge_data(round_))
        script = t.RIDDLE_MISS.format(left=self._left(round_))
        if hint_now:
            script += t.RIDDLE_MISS_HINT.format(hint=for_live(round_.hint))
        return script

    async def _answer_sonnet(self, round_: Round, value: str) -> str:
        if value not in ("acierto", "fallo", GIVE_UP):
            raise GameError(t.WRONG_PLAY["sonnet"])
        if round_.task:
            # Un reto de stand: se le cree, como en la trivia.
            if value == "acierto":
                await self._resolve(round_, "win")
                text = t.SONNET_DONE
            elif value == "fallo":
                await self._resolve(round_, "lose")
                text = t.SONNET_TASK_FAILED
            else:
                await self._resolve(round_, "pass")
                text = t.SONNET_TASK_PASS
            return text + self._after(round_)
        answer = for_live(round_.answer)
        if value == "acierto":
            await self._resolve(round_, "win")
            return t.SONNET_RIGHT.format(answer=answer) + self._after(round_)
        if value == GIVE_UP:
            await self._resolve(round_, "pass")
            return t.SONNET_QUESTION_PASS.format(answer=answer) + self._after(round_)
        round_.misses += 1
        if round_.misses >= round_.tries:
            await self._resolve(round_, "lose")
            return t.SONNET_LOST.format(answer=answer) + self._after(round_)
        await self.host.send("challenge", self._challenge_data(round_))
        return t.SONNET_MISS.format(left=self._left(round_))

    @staticmethod
    def _left(round_: Round) -> str:
        left = max(0, round_.tries - round_.misses)
        return t.LEFT_ONE if left == 1 else t.LEFT_MANY.format(left=left)

    # -- el giro ----------------------------------------------------------------

    def _live_segments(self) -> list[int]:
        """Las casillas que pueden salir: con peso y con reto."""
        return [i for i, w in enumerate(self._weights) if w > 0 and i not in self._off]

    def _choose(self) -> int | None:
        """Una casilla al azar según los pesos, sin repetir la anterior (si hay otra)."""
        candidates = self._live_segments()
        if not candidates:
            return None
        if self._previous in candidates and len(candidates) > 1:
            candidates.remove(self._previous)
        weights = [self._weights[i] for i in candidates]
        return self.host.rng.choices(candidates, weights=weights, k=1)[0]

    async def _spin(self) -> None:
        """Elige la casilla, prepara su reto y manda ``spin``. ``GameError`` si no hay retos."""
        while True:
            index = self._choose()
            if index is None:
                raise GameError("La ruleta se ha quedado sin retos que jugar.")
            round_ = self._prepare(index, self._spins + 1)
            if round_ is not None:
                break
            logger.warning("Ruleta: la casilla %s no tiene reto ahora; fuera", KINDS[index])
            self._off.add(index)
        self._spins = round_.spin
        self._round = round_
        self._previous = index
        self._phase = "spinning"
        self._spin_deadline = self.host.now() + SPIN_SECONDS + SPIN_GRACE_S
        self._announce_asked_at = None
        self._announce_heard = False
        self._announced_at = None
        self._hint_at = None
        self._quiz_deadline = None
        self._quiz_reminded = False
        self._voice_at = None
        logger.info("Ruleta: vuelta %d, cae en %s", round_.spin, round_.kind)
        await self.host.send("spin", spin_data(round_, self._wins))

    def _prepare(self, index: int, spin: int) -> Round | None:
        """El reto de la casilla ``index`` ya elegido (``None`` si no hay con qué)."""
        kind = self._segments[index].kind
        settings = self.host.settings.games.ruleta
        if kind == "trivia":
            question = self.host.draw_trivia(None)
            if question is None or len(question.options) != len(OPTION_LETTERS):
                return None
            return Round(
                spin,
                index,
                kind,
                prompt=question.text,
                options=tuple(question.options),
                correct=question.correct,
                fact=question.fact,
                timer_s=max(0.0, settings.quiz_seconds),
            )
        if kind == "adivinanza":
            riddle = self._pick(kind, self._riddles, lambda r: r.text)
            if riddle is None:
                return None
            return Round(
                spin,
                index,
                kind,
                prompt=riddle.text,
                answer=riddle.answer,
                variants=riddle.variants,
                hint=riddle.hint,
                tries=RIDDLE_TRIES,
            )
        if kind == "explica":
            tech = self._pick(kind, self._techs, lambda x: x.name)
            if tech is None:
                return None
            return Round(
                spin,
                index,
                kind,
                prompt=tech.name,
                description=tech.description,
                timer_s=max(1.0, settings.explain_seconds),
            )
        if kind == "futuro":
            return Round(spin, index, kind, prompt=FUTURE_PROMPT)
        challenge = self._pick(kind, self._sonnet, lambda c: c.text)
        if challenge is None:
            return None
        contact = self.host.settings.trivia.win_contact.strip() or t.NO_CONTACT
        task = challenge.kind == "reto"
        return Round(
            spin,
            index,
            kind,
            prompt=challenge.text.replace("{contacto}", contact),
            answer=challenge.answer,
            variants=challenge.variants,
            task=task,
            tries=0 if task else SONNET_TRIES,
        )

    def _pick(self, kind: str, entries: Sequence[T], key: Callable[[T], str]) -> T | None:
        """Una entrada al azar, primero las que nunca salieron y luego las que hace más."""
        if not entries:
            return None
        recent = self._recent.setdefault(kind, {})
        fresh = [e for e in entries if key(e) not in recent]
        if fresh:
            choice = self.host.rng.choice(fresh)
        else:
            oldest = min(recent[key(e)] for e in entries)
            choice = self.host.rng.choice([e for e in entries if recent[key(e)] == oldest])
        self._uses += 1
        recent[key(choice)] = self._uses
        return choice

    # -- la ruleta para: el reto ------------------------------------------------

    async def _land(self, now: float) -> None:
        """La ruleta paró: tarjeta del reto, sus reglas y, en cuanto Sonia calle, el anuncio."""
        round_ = self._round
        if self._phase != "spinning" or round_ is None:
            return
        self._phase = "challenge"
        self._landed_at = now
        logger.info("Ruleta: reto %s (vuelta %d)", round_.kind, round_.spin)
        await self.host.send("challenge", self._challenge_data(round_))
        await self.host.instruct(self._rules_for(round_))
        self.host.spawn(self._announce(round_.spin), "anuncio")

    async def _announce(self, spin: int) -> None:
        await self.host.wait_idle(ANNOUNCE_WAIT_S)
        round_ = self._round
        if round_ is None or round_.spin != spin or self._phase != "challenge":
            return
        self._announce_asked_at = self.host.now()
        self._announce_heard = False
        await self.host.speak(self._announce_for(round_))

    async def _track_announcement(self, now: float, round_: Round) -> None:
        """¿Terminó Sonia de anunciar el reto? Desde ahí cuentan los contadores."""
        if self._announced_at is not None:
            return
        asked = self._announce_asked_at
        if asked is None:
            if now - self._landed_at < ANNOUNCE_WAIT_S + ANNOUNCE_FALLBACK_S:
                return
        else:
            quiet = self.host.quiet_for()
            if quiet < SPEAKING_S:
                self._announce_heard = True
            done = self._announce_heard and quiet >= ANNOUNCE_QUIET_S
            if not done and now - asked < ANNOUNCE_FALLBACK_S:
                return
        self._announced_at = now
        settings = self.host.settings.games.ruleta
        if round_.kind == "trivia" and round_.timer_s > 0:
            round_.timer_at = now
            self._quiz_deadline = now + round_.timer_s
            await self.host.send("challenge", self._challenge_data(round_))
        elif round_.kind == "adivinanza" and not round_.hint_shown:
            self._hint_at = now + max(0.0, settings.hint_seconds)

    def _tick_quiz(self, now: float, round_: Round) -> None:
        deadline = self._quiz_deadline
        if (
            deadline is None
            or self._quiz_reminded
            or now < deadline + QUIZ_REMIND_GRACE_S
            or self.host.quiet_for() < QUIZ_REMIND_QUIET_S
        ):
            return
        self._quiz_reminded = True
        self.host.spawn(self._say_if_current(round_.spin, t.QUIZ_REMIND_TEXT, 0.0), "recordatorio")

    async def _tick_hint(self, now: float, round_: Round) -> None:
        if self._hint_at is None or round_.hint_shown or now < self._hint_at:
            return
        self._hint_at = None
        round_.hint_shown = True
        await self.host.send("challenge", self._challenge_data(round_))
        text = t.HINT_TEXT.format(hint=for_live(round_.hint))
        self.host.spawn(self._say_if_current(round_.spin, text, HINT_WAIT_S), "pista")

    async def _tick_explain(self, now: float, round_: Round) -> None:
        if round_.timer_at is None:
            announced = self._announced_at
            if announced is None:
                return
            start = self._voice_at
            if start is None and now >= announced + EXPLAIN_AUTOSTART_S:
                start = now
            if start is None:
                return
            round_.timer_at = start
            logger.info("Ruleta: arranca el tiempo para explicar %s", round_.prompt)
            await self.host.send("challenge", self._challenge_data(round_))
            return
        if round_.time_up or now < round_.timer_at + round_.timer_s:
            return
        round_.time_up = True
        await self.host.send("challenge", self._challenge_data(round_))
        self.host.spawn(self._time_up(round_.spin), "tiempo")

    async def _time_up(self, spin: int) -> None:
        """«¡Tiempo!» (grabado si lo está) y que Sonia ponga la nota."""
        played = await self.host.say_fixed(t.TIME_PHRASE)
        await self.host.wait_idle(TIME_UP_WAIT_S)
        round_ = self._round
        if round_ is None or round_.spin != spin or self._phase != "challenge":
            return
        await self.host.speak(t.TIME_UP_TEXT if played else t.TIME_UP_SAY_TEXT)

    async def _say_if_current(self, spin: int, text: str, wait_s: float) -> None:
        """Que Sonia diga ``text`` si el reto de la vuelta ``spin`` sigue en juego."""
        if wait_s > 0:
            await self.host.wait_idle(wait_s)
        round_ = self._round
        if round_ is None or round_.spin != spin or self._phase != "challenge":
            return
        await self.host.speak(text)

    # -- el resultado ------------------------------------------------------------

    async def _resolve(self, round_: Round, outcome: Outcome) -> None:
        """El reto terminó: resultado en pantalla (Unity hace la reacción de Sonnia)."""
        round_.outcome = outcome
        self._phase = "result"
        self._hint_at = None
        self._quiz_deadline = None
        if outcome == "win" or (round_.kind == "explica" and round_.score >= GOOD_SCORE):
            self._wins += 1
        logger.info("Ruleta: %s → %s (%d superados)", round_.kind, outcome, self._wins)
        await self.host.send("result", self._result_data(round_))

    def _after(self, round_: Round) -> str:
        """Lo que va tras el resultado: el equipo del stand al llegar a :data:`WIN_MARK` y
        la pregunta de otra vuelta."""
        text = ""
        superado = round_.outcome == "win" or (
            round_.kind == "explica" and round_.score >= GOOD_SCORE
        )
        contact = self.host.settings.trivia.win_contact.strip()
        if superado and contact and self._wins >= WIN_MARK and not self._contact_said:
            self._contact_said = True
            text += t.WIN_CONTACT_TEXT.format(wins=self._wins, contact=contact)
        return text + t.AGAIN_TEXT

    # -- textos para GPT-Live -----------------------------------------------------

    def _rules_text(self) -> str:
        names = [self._segments[i].spoken for i in self._live_segments()]
        listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + f" y {names[-1]}"
        contact = self.host.settings.trivia.win_contact.strip() or t.NO_CONTACT
        return _fit(t.RULES_TEXT.format(segments=listed, contact=contact))

    def _rules_for(self, round_: Round) -> str:
        settings = self.host.settings.games.ruleta
        if round_.kind == "trivia":
            a, b, c = (for_live(_clip(o, 90)) for o in round_.options)
            text = t.TRIVIA_RULES.format(
                question=for_live(_clip(round_.prompt, 300)),
                a=a,
                b=b,
                c=c,
                seconds=_seconds(round_.timer_s),
            )
        elif round_.kind == "adivinanza":
            text = t.RIDDLE_RULES.format(
                riddle=for_live(round_.prompt),
                answer=for_live(round_.answer),
                variants=self._variants(round_),
                tries=round_.tries,
                hint_seconds=_seconds(settings.hint_seconds),
            )
        elif round_.kind == "explica":
            description = (
                t.EXPLAIN_DESCRIPTION.format(description=for_live(round_.description))
                if round_.description
                else ""
            )
            text = t.EXPLAIN_RULES.format(
                tech_upper=for_live(round_.prompt).upper(),
                tech=_in_sentence(for_live(round_.prompt)),
                seconds=_seconds(round_.timer_s),
                description=description,
            )
        elif round_.kind == "futuro":
            text = t.FUTURE_RULES
        elif round_.task:
            text = t.SONNET_TASK_RULES.format(task=for_live(round_.prompt))
        else:
            text = t.SONNET_QUESTION_RULES.format(
                question=for_live(round_.prompt),
                answer=for_live(round_.answer),
                variants=self._variants(round_),
                tries=round_.tries,
            )
        return _fit(text)

    @staticmethod
    def _variants(round_: Round) -> str:
        if not round_.variants:
            return ""
        return t.VARIANTS_TEXT.format(variants=", ".join(for_live(v) for v in round_.variants))

    def _announce_for(self, round_: Round) -> str:
        if round_.kind == "trivia":
            return t.TRIVIA_ANNOUNCE.format(question=for_live(_clip(round_.prompt, 300)))
        if round_.kind == "adivinanza":
            return t.RIDDLE_ANNOUNCE.format(riddle=for_live(round_.prompt))
        if round_.kind == "explica":
            return t.EXPLAIN_ANNOUNCE.format(
                tech=_in_sentence(for_live(round_.prompt)), seconds=_seconds(round_.timer_s)
            )
        if round_.kind == "futuro":
            return t.FUTURE_ANNOUNCE
        if round_.task:
            return t.SONNET_TASK_ANNOUNCE.format(task=for_live(round_.prompt))
        return t.SONNET_QUESTION_ANNOUNCE.format(question=for_live(round_.prompt))

    # -- la pantalla ------------------------------------------------------------

    def _segment_data(self) -> list[dict[str, Any]]:
        return segment_data(self._segments, self._live_segments())

    def _challenge_data(self, round_: Round) -> dict[str, Any]:
        return challenge_data(round_, self._segments[round_.segment], self._wins)

    def _result_data(self, round_: Round) -> dict[str, Any]:
        return result_data(round_, self._segments[round_.segment], self._wins)


# ---------------------------------------------------------------------------
# Los datos de la pantalla (``docs/protocolo.md``, eventos de ``ruleta``). Funciones
# sueltas para que la secuencia del orquestador falso (``demo.py``) mande lo mismo.
# ---------------------------------------------------------------------------


def segment_data(segments: Sequence[Segment], live: Sequence[int]) -> list[dict[str, Any]]:
    """Las casillas para el ``start``: id, texto de la ruleta, título de la tarjeta e icono."""
    return [
        {"id": s.kind, "label": s.label, "title": s.title, "icon": s.icon, "off": i not in live}
        for i, s in enumerate(segments)
    ]


def spin_data(round_: Round, wins: int) -> dict[str, Any]:
    """``spin``: la casilla de destino y lo que dura el giro."""
    return {
        "spin": round_.spin,
        "segment": round_.segment,
        "duration_s": SPIN_SECONDS,
        "wins": wins,
    }


def challenge_data(round_: Round, segment: Segment, wins: int) -> dict[str, Any]:
    """``challenge``: el estado completo del reto (fijo: se repite si Unity se reconecta)."""
    data: dict[str, Any] = {
        "spin": round_.spin,
        "segment": round_.segment,
        "kind": round_.kind,
        "title": segment.title,
        "prompt": for_screen(round_.prompt),
        "wins": wins,
    }
    if round_.kind == "trivia":
        data["options"] = [for_screen(o) for o in round_.options]
    if round_.tries:
        data["tries"] = round_.tries
        data["misses"] = round_.misses
    if round_.kind == "adivinanza":
        data["hint"] = for_screen(round_.hint) if round_.hint_shown else ""
    if round_.kind == "sonnet":
        data["task"] = round_.task
    if round_.timer_s > 0:
        data["timer"] = {"seconds": round_.timer_s, "running": round_.timer_at is not None}
    if round_.kind == "explica":
        data["time_up"] = round_.time_up
    return data


def result_data(round_: Round, segment: Segment, wins: int) -> dict[str, Any]:
    """``result``: el estado completo del resultado, con cómo acabó y la solución."""
    data = challenge_data(round_, segment, wins)
    data.pop("timer", None)
    data["outcome"] = round_.outcome
    if round_.kind == "trivia":
        data["chosen"] = round_.chosen
        data["correct"] = round_.correct
    elif round_.kind == "adivinanza" or (round_.kind == "sonnet" and not round_.task):
        data["answer"] = for_screen(round_.answer)
    elif round_.kind == "explica":
        data["score"] = round_.score
    elif round_.kind == "futuro":
        data["prediction"] = for_screen(round_.prediction)
        data["probability"] = max(0, round_.probability)
    return data


def _fit(text: str) -> str:
    """Las instrucciones nunca pasan del tope de ``instruct`` (los bancos ya lo garantizan)."""
    if len(text) <= INSTRUCT_MAX_CHARS:
        return text
    logger.warning("Ruleta: instrucción de %d caracteres; se recorta", len(text))
    return text[: INSTRUCT_MAX_CHARS - 1].rstrip() + "…"
