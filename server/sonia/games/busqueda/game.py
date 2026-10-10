"""Búsqueda relámpago (``busqueda``): «¡El primero que me enseñe algo azul!» (plan, 5.6).

Se juegan ``GAME_BUSQUEDA_ROUNDS`` rondas. En cada una sale un objeto al azar del banco
(``assets/games/busqueda/objetos.md``) con su tarjeta y un contador de
``GAME_BUSQUEDA_ROUND_SECONDS``, y la vista en vivo de la cámara en la franja alta para que
el grupo sepa dónde enseñarlo. El orquestador lleva todo el ritmo; GPT-Live solo anuncia,
celebra y, si alguien grita «¡aquí!», delega ``busqueda_check``.

Cada ronda tiene estas fases (``_phase``):

- ``ready``: el objeto está en pantalla y Sonia lo anuncia. Cuando termina de decirlo
  (se sigue su transcripción, ``on_assistant_text``) suena el «¡Ya!» grabado y arranca.
- ``running``: cada ``GAME_BUSQUEDA_CHECK_SECONDS`` va una foto reducida al modelo de
  visión (``VisionJudge.ask``) con una pregunta cerrada del banco, hasta
  ``GAME_BUSQUEDA_MAX_CHECKS`` por ronda. Las miradas no se solapan: si una tarda, la
  siguiente espera. Si el modelo ve el objeto, la ronda se gana; si se acaba el tiempo, se
  pierde.
- ``between``: Sonia cuenta el resultado y, al callar, empieza la siguiente ronda.
- ``done``: era la última ronda (o la cámara no responde): ``finish`` y fuera.

Las dos cosas que se dicen con tiempo exacto (el «¡Ya!» y el «¡Lo veo!» / «¡Tiempo!») son
frases grabadas (``say_fixed``); lo demás lo dice Sonia con sus palabras (``speak``).

Nunca se guarda una foto ni se describe a una persona: el modelo solo contesta si se ve el
objeto y cuál (``JudgeAnswer.what``), y eso pasa por :func:`clean_what` antes de llegar a
Sonia o a la pantalla. Cada foto al modelo cuesta, así que se cuentan y se anotan en el
registro por ronda y por partida (para medir el gasto en la primera prueba real).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

from sonia.actions.games import game_action
from sonia.games.banks import GameBank
from sonia.games.base import Game, GameError, GameHost, GameResult, StopReason
from sonia.games.busqueda import texts as t
from sonia.games.busqueda.bank import OBJECTS, ObjectEntry, announced, clean_what
from sonia.types import ActionSpec
from sonia.vision.contracts import JudgeAnswer

__all__ = ["BusquedaGame"]

logger = logging.getLogger(__name__)

#: Cuánto lleva Sonia callada para darla por terminada de hablar.
SETTLE_S = 1.0
#: Por debajo de esto, Sonia está hablando (o el clip acaba de sonar).
SPOKE_BELOW_S = 0.5
#: Tope de espera a que Sonia anuncie la primera ronda (llega por la delegación de
#: ``start_game``, que tarda) y las demás (por ``commentary``, más rápido).
READY_CAP_FIRST_S = 14.0
READY_CAP_S = 9.0
#: Tope de espera a que Sonia empiece a contar el resultado de una ronda: si lo dice el
#: sistema (``speak``), y si llega como resultado de ``busqueda_check`` (más lento).
SPEAK_FIRST_WORD_S = 7.0
VOICE_FIRST_WORD_S = 12.0
#: Tras ``busqueda_check`` ganada, lo que se oiga antes de esto es el clip o una muletilla
#: de Sonia, no su reacción.
VOICE_MIN_DELAY_S = 1.6
#: Tope de lo que dura la reacción de Sonia antes de seguir con la siguiente ronda.
SPEECH_MAX_S = 20.0
#: Una foto en el aire al acabar el tiempo aún cuenta.
GRACE_S = 3.0
#: Tope de espera al modelo de visión por mirada (la mirada que no contesta no frena el juego).
JUDGE_TIMEOUT_S = 12.0
#: Cuánto espera ``busqueda_check`` a que acabe una mirada en el aire.
MANUAL_JOIN_S = 4.0
#: Para hablar tras un clip hay que esperar a que acabe.
CLIP_WAIT_S = 3.0
CLIP_DONE_QUIET_S = 0.6
#: Dos rondas seguidas sin que la cámara conteste a ninguna mirada: se cancela el juego.
MAX_SILENT_ROUNDS = 2
#: Tras la última ronda, la vista en vivo se queda esto antes de retirarse (dejando ver el final).
FINAL_PREVIEW_S = 3.0

Phase = Literal["off", "ready", "running", "between", "done"]


@dataclass(slots=True)
class _Outcome:
    """Cómo acabó una ronda: lo que ve la pantalla, lo que cuenta Sonia y si acaba la partida."""

    kind: Literal["found", "timeout"]
    last: bool
    result: GameResult
    screen: dict[str, Any]
    script: str
    data: dict[str, Any]


def _seconds(value: float) -> str:
    """25.0 -> «25», 2.5 -> «2.5»."""
    return f"{value:g}"


class BusquedaGame(Game):
    """«¡El primero que me enseñe algo azul!»: la cámara comprueba quién lo trae (plan, 5.6)."""

    id: ClassVar[str] = "busqueda"
    title: ClassVar[str] = "Búsqueda relámpago"
    spoken: ClassVar[str] = "la búsqueda relámpago"
    needs: ClassVar[frozenset[str]] = frozenset({"camera", "preview", "vision_llm"})
    settings_key: ClassVar[str] = "busqueda"

    def __init__(self, host: GameHost) -> None:
        super().__init__(host)
        #: Memoria entre partidas: en qué partida salió cada objeto (para no repetir).
        self._used: dict[str, int] = {}
        self._plays = 0
        self._reset()

    def _reset(self) -> None:
        self._phase: Phase = "off"
        self._objects: list[ObjectEntry] = []
        self._current: ObjectEntry | None = None
        self._round = 0
        self._total = 0
        self._found = 0
        self._results: list[str] = []
        self._silent_rounds = 0
        self._started_at = 0.0
        # Reloj de la ronda.
        self._go_at = 0.0
        self._deadline = 0.0
        self._next_check_at = 0.0
        # Miradas de la ronda y de la partida.
        self._checks = 0
        self._manual = 0
        self._answered = 0
        self._photos = 0
        self._answered_total = 0
        self._inflight: asyncio.Future[None] | None = None
        # Sincronía con la voz de Sonia.
        self._ready_at = 0.0
        self._ready_cap = READY_CAP_S
        self._heard = False
        self._speech_at: float | None = None
        self._spoke = False
        self._first_word_s = SPEAK_FIRST_WORD_S
        self._min_delay_s = 0.0

    # -- lo que declara el juego ----------------------------------------------------

    @classmethod
    def banks(cls) -> list[GameBank[Any]]:
        return [OBJECTS]

    @classmethod
    def actions(cls) -> list[ActionSpec]:
        return [
            game_action(
                cls,
                name="busqueda_check",
                description=(
                    "Mira ahora mismo la cámara para comprobar si ya han enseñado el objeto de la "
                    "ronda de la búsqueda relámpago. Úsala en cuanto alguien grite «¡aquí!» o "
                    "«¡ya lo tengo!» o te enseñe algo, sin esperar ni decir nada antes. Devuelve "
                    "qué hacer: celebrarlo si se ve, o pedir que lo enseñen mejor."
                ),
                parameters={"type": "object", "properties": {}, "required": []},
                play=BusquedaGame.check,
            )
        ]

    def phrases(self) -> list[str]:
        return [t.GO_PHRASE, t.FOUND_PHRASE, t.TIMEOUT_PHRASE]

    def unavailable_reason(self) -> str | None:
        cfg = self.host.settings.games.busqueda
        if cfg.rounds < 1 or cfg.round_seconds <= 0 or cfg.check_seconds <= 0 or cfg.max_checks < 1:
            return "Los ajustes de la búsqueda relámpago no valen (rondas, tiempo o miradas)."
        return None

    # -- ciclo de vida ------------------------------------------------------------------

    async def start(self, source: str, options: dict[str, Any]) -> str:
        cfg = self.host.settings.games.busqueda
        reason = self.unavailable_reason()
        if reason:
            raise GameError(reason)
        entries = await self.host.load_bank(OBJECTS)
        if not entries:
            raise GameError(
                "El banco de objetos de la búsqueda relámpago está vacío o mal formado."
            )
        self._reset()
        self._total = max(1, min(int(cfg.rounds), len(entries)))
        self._objects = self._pick(entries, self._total)
        if not await self.host.stream.acquire(self.id):
            raise GameError("No puedo usar la cámara ahora mismo: esta vez no se puede jugar.")
        if not await self.host.preview.start(self.id, mirror=True):
            await self.host.stream.release(self.id)
            raise GameError("No he podido encender la cámara en vivo en la pantalla.")
        now = self.host.now()
        self._started_at = now
        await self.host.send(
            "start",
            {"rounds": self._total, "round_seconds": float(cfg.round_seconds), "preview": True},
        )
        await self.host.instruct(
            t.RULES_TEXT.format(total=self._total, seconds=_seconds(cfg.round_seconds))
        )
        self._open_round(now, first=True)
        await self.host.send("round", self._state("ready"))
        entry = self._objects[0]
        logger.info(
            "Búsqueda: %d rondas de %s s (miradas cada %s s, tope %d por ronda): %s",
            self._total,
            _seconds(cfg.round_seconds),
            _seconds(cfg.check_seconds),
            cfg.max_checks,
            ", ".join(e.name for e in self._objects),
        )
        return t.START_TEXT.format(
            total=self._total, seconds=_seconds(cfg.round_seconds), name=entry.name
        )

    async def resume(self) -> str:
        entry = self._current
        if entry is None:
            return await super().resume()
        return t.RESUME_TEXT.format(number=self._round, total=self._total, name=entry.name)

    async def stop(self, reason: StopReason) -> None:
        if self._phase != "off":
            logger.info(
                "Búsqueda terminada (%s): %d de %d rondas encontradas, %d fotos al modelo de "
                "visión (%d con respuesta) en %.0f s",
                reason,
                self._found,
                self._total,
                self._photos,
                self._answered_total,
                self.host.now() - self._started_at,
            )
        self._phase = "off"
        for release in (self.host.preview.stop, self.host.stream.release):
            try:
                await release(self.id)
            except Exception:  # noqa: BLE001 - soltar la cámara nunca tumba nada
                logger.exception("Búsqueda: no se pudo soltar la cámara")

    def snapshot(self) -> dict[str, Any]:
        entry = self._current
        left = 0.0
        if self._phase == "running":
            left = max(0.0, self._deadline - self.host.now())
        return {
            "phase": self._phase,
            "round": self._round,
            "rounds": self._total,
            "object": entry.name if entry is not None else "",
            "found": self._found,
            "seconds_left": round(left, 1),
            "checks": self._checks,
            "photos": self._photos,
        }

    # -- el reloj -----------------------------------------------------------------------

    async def tick(self, now: float) -> None:
        phase = self._phase
        if phase == "ready":
            if self._ready_over(now):
                self._go(now)
        elif phase == "running":
            self._tick_running(now)
        elif phase == "between" and self._speech_over(now):
            self._next_round(now)

    def _ready_over(self, now: float) -> bool:
        """¿Terminó Sonia de anunciar la ronda? (o se acabó la paciencia)."""
        if now - self._ready_at >= self._ready_cap:
            return True
        return self._heard and self.host.quiet_for() >= SETTLE_S

    def _speech_over(self, now: float) -> bool:
        """¿Contó Sonia el resultado de la ronda y calló? (o se acabó la paciencia)."""
        at = self._speech_at
        if at is None:
            return False
        waited = now - at
        quiet = self.host.quiet_for()
        if quiet < SPOKE_BELOW_S and waited >= self._min_delay_s:
            self._spoke = True
        if self._spoke:
            return quiet >= SETTLE_S or waited >= SPEECH_MAX_S
        return waited >= self._first_word_s

    def _expect_speech(self, now: float, first_word_s: float, min_delay_s: float = 0.0) -> None:
        """Se espera a que Sonia cuente algo: ``first_word_s`` es lo más que se aguanta a que empiece."""
        self._speech_at = now
        self._spoke = False
        self._first_word_s = first_word_s
        self._min_delay_s = min_delay_s

    def _go(self, now: float) -> None:
        """Da la salida: arranca el contador y las miradas, y suena el «¡Ya!»."""
        cfg = self.host.settings.games.busqueda
        self._phase = "running"
        self._go_at = now
        self._deadline = now + float(cfg.round_seconds)
        self._next_check_at = now + float(cfg.check_seconds)
        self.host.spawn(self._announce_go(), "busqueda-go")

    async def _announce_go(self) -> None:
        await self.host.send("go", self._state("running"))
        await self.host.say_fixed(t.GO_PHRASE)

    def _tick_running(self, now: float) -> None:
        cfg = self.host.settings.games.busqueda
        if now >= self._deadline:
            if self._inflight is not None and now < self._deadline + GRACE_S:
                return  # la foto que va en el aire todavía puede salvar la ronda
            outcome = self._resolve("timeout", now, None)
            if outcome is not None:
                self.host.spawn(self._deliver(outcome), "busqueda-tiempo")
            return
        if self._inflight is None and now >= self._next_check_at and self._checks < cfg.max_checks:
            fut = self._begin_look(now, manual=False)
            assert self._current is not None
            self.host.spawn(
                self._periodic(fut, self._round, self._current.question), "busqueda-mirada"
            )

    # -- rondas -------------------------------------------------------------------------

    def _pick(self, entries: list[ObjectEntry], count: int) -> list[ObjectEntry]:
        """Los objetos de la partida: primero los que más hace que no salen."""
        rng = self.host.rng
        order = sorted(entries, key=lambda e: (self._used.get(e.name, 0), rng.random()))
        chosen = order[:count]
        rng.shuffle(chosen)
        self._plays += 1
        for entry in chosen:
            self._used[entry.name] = self._plays
        return chosen

    def _open_round(self, now: float, *, first: bool) -> None:
        """Abre la ronda siguiente (estado; la pantalla y la voz las pone quien llama)."""
        self._round += 1
        self._current = self._objects[self._round - 1]
        self._checks = self._manual = self._answered = 0
        self._phase = "ready"
        self._ready_at = now
        self._ready_cap = READY_CAP_FIRST_S if first else READY_CAP_S
        self._heard = False
        self._speech_at = None

    def _next_round(self, now: float) -> None:
        self._open_round(now, first=False)
        self.host.spawn(self._announce_round(), "busqueda-ronda")

    async def _announce_round(self) -> None:
        entry = self._current
        if entry is None:
            return
        await self.host.send("round", self._state("ready"))
        await self.host.speak(
            t.ROUND_TEXT.format(number=self._round, total=self._total, name=entry.name)
        )

    async def on_assistant_text(self, text: str, final: bool) -> None:
        """Sonia dice el objeto de la ronda: terminada la frase, se da la salida."""
        entry = self._current
        if (
            self._phase == "ready"
            and not self._heard
            and entry is not None
            and announced(text, entry.name)
        ):
            self._heard = True

    def _state(self, phase: str, **extra: Any) -> dict[str, Any]:
        """El estado completo de la ronda (los mensajes fijos se repiten tal cual al reconectar)."""
        cfg = self.host.settings.games.busqueda
        entry = self._current
        data: dict[str, Any] = {
            "index": self._round,
            "total": self._total,
            "object": entry.name if entry is not None else "",
            "color": entry.color if entry is not None else "",
            "seconds": float(cfg.round_seconds),
            "found": self._found,
            "phase": phase,
        }
        data.update(extra)
        return data

    # -- las miradas ----------------------------------------------------------------------

    def _begin_look(self, now: float, *, manual: bool) -> asyncio.Future[None]:
        """Cuenta una foto más y reserva la mirada (de una en una). Síncrona: sin carreras."""
        cfg = self.host.settings.games.busqueda
        self._checks += 1
        self._photos += 1
        if manual:
            self._manual += 1
        self._next_check_at = now + float(cfg.check_seconds)
        fut: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._inflight = fut
        return fut

    async def _run_look(
        self, fut: asyncio.Future[None], question: str, round_no: int
    ) -> JudgeAnswer | None:
        """La foto al modelo de visión. Nunca lanza ni se queda colgada (``JUDGE_TIMEOUT_S``)."""
        cfg = self.host.settings.games.busqueda
        answer: JudgeAnswer | None = None
        try:
            await self.host.send(
                "checking", {"n": self._checks, "max": cfg.max_checks}, sticky=False
            )
            answer = await asyncio.wait_for(self.host.judge.ask(question), JUDGE_TIMEOUT_S)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - un fallo del modelo es una mirada sin respuesta
            logger.warning("Búsqueda: la mirada falló (%s)", exc or type(exc).__name__)
            answer = None
        finally:
            self._inflight = None
            if not fut.done():
                fut.set_result(None)
        if answer is not None:
            self._answered_total += 1
            if round_no == self._round:
                self._answered += 1
        return answer

    async def _periodic(self, fut: asyncio.Future[None], round_no: int, question: str) -> None:
        """Una mirada del reloj: si se ve el objeto, la ronda se gana."""
        answer = await self._run_look(fut, question, round_no)
        if answer is None or not answer.seen or self._round != round_no:
            return
        outcome = self._resolve("found", self.host.now(), answer)
        if outcome is not None:
            await self._deliver(outcome)

    async def check(self, arguments: dict[str, Any]) -> str:
        """``busqueda_check``: alguien grita «¡aquí!»: se mira ya, dentro del tope de la ronda."""
        if self._phase == "ready":
            return t.NOT_STARTED_TEXT
        if self._phase != "running" or self._current is None:
            return t.ALREADY_TEXT
        cfg = self.host.settings.games.busqueda
        round_no = self._round
        pending = self._inflight
        if pending is not None:
            # Una mirada va en el aire: se espera a que acabe (si ve el objeto, Sonia se
            # entera por el sistema y esta delegación ya no toca).
            try:
                await asyncio.wait_for(asyncio.shield(pending), MANUAL_JOIN_S)
            except TimeoutError:
                return t.STILL_LOOKING_TEXT
            if self._phase != "running" or self._round != round_no:
                return t.ALREADY_TEXT
        if self._checks >= cfg.max_checks:
            return t.NO_MORE_TEXT
        entry = self._current
        fut = self._begin_look(self.host.now(), manual=True)
        answer = await self._run_look(fut, entry.question, round_no)
        if self._phase != "running" or self._round != round_no:
            return t.ALREADY_TEXT
        if answer is None:
            return t.NO_ANSWER_TEXT
        if not answer.seen:
            left = max(0, round(self._deadline - self.host.now()))
            return t.NOT_YET_TEXT.format(name=entry.name, left=left)
        outcome = self._resolve("found", self.host.now(), answer)
        if outcome is None:
            return t.ALREADY_TEXT
        await self._show(outcome)
        await self._settle(outcome, first_word_s=VOICE_FIRST_WORD_S, min_delay_s=VOICE_MIN_DELAY_S)
        return outcome.script

    # -- el resultado de la ronda ----------------------------------------------------------

    def _resolve(
        self, kind: Literal["found", "timeout"], now: float, answer: JudgeAnswer | None
    ) -> _Outcome | None:
        """Cierra la ronda (síncrona: solo una vez, gane quien gane). ``None`` si ya no tocaba."""
        entry = self._current
        if self._phase != "running" or entry is None:
            return None
        silent = kind == "timeout" and self._checks > 0 and self._answered == 0
        what = ""
        if kind == "found":
            self._found += 1
            what = clean_what(answer.what if answer is not None else "", entry.name)
            self._silent_rounds = 0
        elif silent:
            self._silent_rounds += 1
        else:
            self._silent_rounds = 0
        cancel = silent and self._silent_rounds >= MAX_SILENT_ROUNDS
        last = self._round >= self._total or cancel
        self._phase = "done" if last else "between"
        self._results.append("silent" if silent else kind)
        self._speech_at = None  # hasta que quien lo cuente diga qué esperar (``_settle``)
        self._log_round(kind, silent)

        won = self._found * 2 >= self._total
        result: GameResult = "cancel" if cancel else ("win" if won else "lose")
        if kind == "found":
            screen = self._state("found", what=what)
            script = t.FOUND_TEXT.format(what=what)
        else:
            screen = self._state("timeout", silent=silent)
            script = t.SILENT_TEXT if silent else t.TIMEOUT_TEXT.format(name=entry.name)
        if cancel:
            script = t.CANCEL_TEXT
        elif last:
            script += self._final_text(won)
        else:
            script += t.NEXT_TEXT
        data = {"found": self._found, "total": self._total, "photos": self._photos}
        return _Outcome(kind, last, result, screen, script, data)

    def _final_text(self, won: bool) -> str:
        text = t.FINAL_TEXT.format(found=self._found, total=self._total)
        if self._found >= self._total:
            text += t.ALL_FOUND_TEXT.format(total=self._total)
        else:
            text += t.WON_TEXT if won else t.LOST_TEXT
        contact = self.host.settings.trivia.win_contact.strip()
        if won and contact:
            text += t.WIN_CONTACT_TEXT.format(contact=contact)
        return text + t.BACK_TO_TALK_TEXT

    def _log_round(self, kind: str, silent: bool) -> None:
        entry = self._current
        how = (
            "encontrado"
            if kind == "found"
            else ("sin respuesta de la cámara" if silent else "se acabó el tiempo")
        )
        logger.info(
            "Búsqueda: ronda %d/%d «%s»: %s. %d fotos al modelo de visión (%d periódicas, %d "
            "por busqueda_check; %d con respuesta). Partida: %d fotos, %d de %d encontrados",
            self._round,
            self._total,
            entry.name if entry is not None else "?",
            how,
            self._checks,
            self._checks - self._manual,
            self._manual,
            self._answered,
            self._photos,
            self._found,
            self._total,
        )

    async def _show(self, outcome: _Outcome) -> None:
        """Lo inmediato: el resultado en pantalla y el «¡Lo veo!» o «¡Tiempo!» grabado."""
        if outcome.kind == "found":
            self.host.touch()
        phrase = t.FOUND_PHRASE if outcome.kind == "found" else t.TIMEOUT_PHRASE
        try:
            await self.host.send(outcome.kind, outcome.screen)
            await self.host.say_fixed(phrase)
        except Exception:  # noqa: BLE001 - la pantalla no frena el juego
            logger.exception("Búsqueda: no se pudo mostrar el resultado")

    async def _settle(self, outcome: _Outcome, *, first_word_s: float, min_delay_s: float) -> None:
        """Tras contar la ronda: la siguiente (al callar Sonia) o el final de la partida."""
        if not outcome.last:
            self._expect_speech(self.host.now(), first_word_s, min_delay_s)
            return
        self.host.spawn(self._hide_preview_later(), "busqueda-vista")
        await self.host.finish(outcome.result, outcome.data)

    async def _hide_preview_later(self) -> None:
        """La vista en vivo no acompaña al resultado final: se retira un momento después."""
        await self.host.sleep(FINAL_PREVIEW_S)
        await self.host.preview.stop(self.id)

    async def _deliver(self, outcome: _Outcome) -> None:
        """Camino del sistema (una mirada o el reloj): pantalla, sonido y que Sonia lo cuente."""
        try:
            await self._show(outcome)
            await self._wait_clip()
            await self.host.speak(outcome.script)
        except Exception:  # noqa: BLE001
            logger.exception("Búsqueda: no se pudo contar el resultado")
        await self._settle(outcome, first_word_s=SPEAK_FIRST_WORD_S, min_delay_s=0.0)

    async def _wait_clip(self) -> None:
        """Espera a que acabe el clip grabado: GPT-Live no habla encima de él."""
        waited = 0.0
        while waited < CLIP_WAIT_S and self.host.quiet_for() < CLIP_DONE_QUIET_S:
            await self.host.sleep(0.05)
            waited += 0.05
