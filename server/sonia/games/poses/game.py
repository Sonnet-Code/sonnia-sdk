"""Simón dice con poses (``poses``, ``docs/juegos/poses.md``, plan 5.2).

Sonnia da órdenes con nombre de meme dev y la pose dicha en claro («¡Simón dice: pasaron
todos los tests, brazos arriba!») y la cámara cuenta cuántos la hacen. Algunas rondas son
trampa: la orden sale sin «Simón dice». El resultado es colectivo («7 de 9»): nunca se
elimina a nadie.

Reparto (como la trivia, ``docs/trivia.md``):

- **El orquestador lleva el juego.** Tras ``start_game(poses)`` nada más se delega: las
  rondas las conduce una tarea de la partida. Las órdenes suenan como frases grabadas
  (``say_fixed``: exactas en el tiempo y en si dicen «Simón dice»), la cámara cuenta en una
  ventana tras cada orden (el mejor frame) y el resultado le llega a GPT-Live por ``speak``
  para que reaccione en una frase. Lo que tiene que saber (las reglas) va por ``instruct``.
- **La cámara, en este equipo.** El detector de poses da personas con 17 puntos; juegan las
  que llegan a una altura mínima en la imagen (``GAME_POSES_MIN_PERSON``) y las reglas de
  ``rules.py`` dicen quién hace la pose. La vista en vivo sale encima de Sonnia, en espejo,
  con los esqueletos (``overlay.py``). Nunca se guarda una imagen ni un dato de nadie y no
  se reconoce a nadie.
- **El juez** (``GAMES_JUDGE=gemini``, ``host.referee``): el veredicto de cada ronda, trampas
  incluidas, lo da con una sola foto de la ventana (la del mejor recuento local, en memoria);
  si no contesta a tiempo, vale el recuento local, como antes.
- **Colocación.** Antes de la primera ronda (y entre rondas, si alguien se pega), si hay
  alguien demasiado cerca o no se ve a nadie, Sonia lo pide en una frase.

Nada de lo que pase aquí tumba el motor: si la tarea de las rondas falla, la partida se
cancela con una frase.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Literal

import numpy as np

from sonia.busy import TEXT_POSES
from sonia.games.base import Game, GameError, GameHost, StopReason
from sonia.games.poses.bank import POSES_BANK, PoseEntry
from sonia.games.poses.overlay import Skeleton, Skeletons, Tint
from sonia.games.poses.rules import FrameCount, Mark, Placement, count_frame

if TYPE_CHECKING:
    import random

    from sonia.config import PosesSettings
    from sonia.games.banks import GameBank

__all__ = ["Phase", "PosesGame", "RoundResult", "plan_rounds"]

logger = logging.getLogger(__name__)

#: En qué está la partida (es también el nombre del evento que lo pinta en Unity).
Phase = Literal["off", "placement", "round", "command", "window", "result", "final"]

# -- tiempos (segundos) -----------------------------------------------------------------

#: Cada cuánto se mira la última detección (la vista en vivo y la colocación)...
POLL_S = 0.1
#: ...y durante la ventana en la que se cuenta.
WINDOW_POLL_S = 0.05
#: Una detección más vieja que esto no vale (la gente se ha movido).
FRAME_MAX_AGE_S = 0.6
#: Cada cuánto, como mucho, se avisa de que hay gente jugando (para que no se dé por abandonada).
TOUCH_EVERY_S = 2.0

#: Colocación antes de la primera ronda: como mucho esto desde que empieza la partida...
PLACEMENT_MAX_S = 20.0
#: ...y entre rondas, si alguien se ha pegado a la cámara.
REPLACE_MAX_S = 6.0
#: Si Sonia no empieza a explicar el juego en este tiempo, se da la explicación por hecha.
INTRO_START_MAX_S = 6.0
#: Sonia callada esto tras hablar: ha terminado de explicar (o de pedir algo).
INTRO_QUIET_S = 0.8
#: Colocados así de seguido, empieza la ronda.
READY_STABLE_S = 0.8
#: Sin ver a nadie esto, se pide que se pongan delante (una vez por colocación).
NOBODY_ASK_S = 4.0
#: Entre dos peticiones de dar un paso atrás.
CLOSE_ASK_COOLDOWN_S = 12.0

#: Antes de cada ronda, esperar calma (nadie habla y Sonia callada) como mucho esto...
CALM_MAX_S = 12.0
#: ...con Sonia callada al menos esto.
CALM_QUIET_S = 0.6
#: Con Sonia ya callada, se espera además a que nadie hable como mucho esto: en un stand con
#: barullo (el grupo ríe tras cada ronda) la sesión casi nunca queda del todo en calma.
CALM_IDLE_MAX_S = 4.0
#: La orden tiene que empezar a sonar en esto (si no, se sigue igual)...
PHRASE_START_MAX_S = 4.5
#: ...y como mucho dura esto.
PHRASE_MAX_S = 8.0
#: Callada esto tras la orden: ya terminó.
PHRASE_END_QUIET_S = 0.15
#: Intentos de decir la orden si Sonia estaba hablando.
SAY_ATTEMPTS = 3
#: Tras el resultado, la reacción de Sonia tiene que empezar en esto...
REPLY_START_MAX_S = 4.0
#: ...y como mucho se espera esto.
REPLY_MAX_S = 15.0
#: El resultado se queda en pantalla al menos esto.
RESULT_HOLD_S = 1.2
#: Rondas seguidas sin ver a nadie tras las que el juego se acaba.
EMPTY_ROUNDS_TO_STOP = 2
#: Margen sobre el plazo del juez (``GAMES_JUDGE_TIMEOUT_SECONDS``, que ya corta él): la ronda
#: nunca se queda esperando más que esto.
JUDGE_GRACE_S = 1.0

#: Tope de jugadores cuando solo los cuenta el juez (lo local no vio a nadie): una foto con
#: gente de fondo no puede convertir una ronda en «2 de 40».
MAX_JUDGED_PLAYERS = 10

# -- textos para GPT-Live («Sonia», sin marcas del stack) ------------------------------

RULES_TEXT = """\
SIMÓN DICE CON POSES EN MARCHA ({rounds} rondas). La cámara del stand sale en directo encima de ti y cuenta quién hace cada pose; la imagen no se graba ni se guarda.
- Las órdenes suenan solas con tu voz grabada («¡Simón dice: …!»): no las digas tú, no te adelantes ni inventes otras.
- Tras cada orden te llega el resultado («la hicieron 7 de 9»): reacciona en una frase muy corta, con humor, y calla para que suene la siguiente. No inventes números ni digas quién la hizo: solo lo que te llegue.
- Algunas órdenes son trampa (sin «Simón dice»): quien hace la pose cae. Nunca avises antes de cuál es trampa.
- Nadie queda eliminado: el resultado es del grupo. No comentes el aspecto de nadie.
- Si te llega que alguien está muy cerca o que no se ve a nadie, pídelo en una frase corta.
- Si quieren dejar de jugar, delega terminar el juego. Si te preguntan algo, contesta corto: el juego sigue solo.
- En la pantalla nada cambia por lo que digas tú: los números y las órdenes los pone el juego."""

START_TEXT = (
    "Simón dice con poses está en tu pantalla, con la cámara en directo encima de ti. "
    "Explícalo con energía en dos o tres frases: que se pongan delante a unos dos metros, donde "
    "se vean en la imagen de arriba; que hagan la pose solo si la orden empieza por «Simón dice»; "
    "son {rounds} rondas y nadie queda eliminado. Luego calla: las órdenes empiezan solas."
)

RESUME_TEXT = (
    "Ya están jugando a Simón dice con poses: va por la ronda {round} de {rounds}. Las órdenes y "
    "los resultados te llegan solos: sigue animando sin decir órdenes."
)

BACK_TEXT = (
    "JUEGO: hay alguien demasiado cerca de la cámara y no se le ven bien los brazos. Pídele en "
    "una frase corta que dé un paso atrás, hasta unos dos metros, para verle en la imagen."
)
NOBODY_TEXT = (
    "JUEGO: aún no se ve a nadie delante de la cámara. Pide en una frase corta que se pongan "
    "delante de ti, a unos dos metros, donde se vean en la imagen de arriba."
)
NEXT_TEXT = " Luego calla: la siguiente orden sale sola."
ROUND_TEXT = "JUEGO: ronda {round} de {rounds}, «{label}»: "
ALL_TEXT = "¡la hicieron todos, {count} de {total}! Celébralo en una frase muy corta."
SOME_TEXT = "la hicieron {count} de {total}. Reacciona en una frase muy corta, con humor."
NONE_TEXT = (
    "no la hizo nadie de los {total}. Reacciona en una frase muy corta, con humor, y anímales."
)
TRAP_FELL_TEXT = (
    "era TRAMPA (la orden no decía «Simón dice») y cayeron {count} de {total}. Reacciona en una "
    "frase muy corta, con humor."
)
TRAP_NONE_TEXT = (
    "era TRAMPA (la orden no decía «Simón dice») y no cayó nadie de los {total}. Felicítales en "
    "una frase muy corta."
)
EMPTY_TEXT = (
    "no se ve a nadie delante de la cámara. Pide en una frase corta que se pongan delante, a unos "
    "dos metros."
)
FINAL_TEXT = (
    "JUEGO: fin de Simón dice. Entre todos hicieron bien {done} de {possible} jugadas{trap}. "
    "Celébralo con energía en una o dos frases: nadie queda eliminado."
)
#: Empujón si hablan y no se delega nada: solo para parar. Una orden corta (el manager añade
#: que es una nota interna); nunca en la ventana de la pose, que va con el tiempo justo.
NUDGE_STOP = "SIMÓN DICE: si pidieron parar o se despidieron, delega terminar el juego."
FINAL_TRAP_TEXT = " y en las trampas cayeron {fell}"
FINAL_NO_TRAP_TEXT = " y en las trampas no cayó nadie"
WIN_CONTACT_TEXT = (
    " Si alguien pregunta por premios, que hable con {contact} aquí en el stand; no sabes qué "
    "premios hay: no prometas ninguno."
)
EMPTY_FINAL_TEXT = (
    "JUEGO: no se ve a nadie delante de la cámara, así que Simón dice se acaba aquí. Dilo en una "
    "frase corta y ofrécete a jugar otra vez cuando quieran."
)
FAILED_TEXT = (
    "JUEGO: Simón dice se ha parado por un fallo. Dilo con humor en una frase corta y sigue "
    "conversando con normalidad."
)

# -- textos de la pantalla («Sonnia») ---------------------------------------------------

HINT_CLOSE = "Un paso atrás: a unos 2 m"
HINT_NOBODY = "Pónganse delante, a unos 2 m"


@dataclass(frozen=True, slots=True)
class RoundResult:
    """Cómo fue una ronda: ``count`` de ``total`` hicieron la pose (en una trampa, cayeron)."""

    pose: str
    simon: bool
    count: int
    total: int

    @property
    def done(self) -> int:
        """Jugadas bien hechas: la pose con «Simón dice»; quedarse quieto en una trampa."""
        return self.count if self.simon else self.total - self.count


def plan_rounds(
    entries: list[PoseEntry], rounds: int, tricks: int, rng: random.Random
) -> list[tuple[PoseEntry, bool]]:
    """Las rondas de una partida: ``(pose, simón)`` para cada una.

    Las poses salen barajadas y, si hay menos que rondas, se repiten sin que salga la misma
    dos veces seguidas. ``tricks`` rondas son trampa (``simón`` falso), nunca la primera.
    """
    if not entries:
        return []
    rounds = max(1, rounds)
    tricks = max(0, min(tricks, rounds - 1))
    order: list[PoseEntry] = []
    pool: list[PoseEntry] = []
    while len(order) < rounds:
        if not pool:
            pool = rng.sample(entries, len(entries))
            if order and len(pool) > 1 and pool[0].id == order[-1].id:
                pool[0], pool[-1] = pool[-1], pool[0]
        order.append(pool.pop(0))
    traps = set(rng.sample(range(1, rounds), tricks)) if tricks else set()
    return [(entry, index not in traps) for index, entry in enumerate(order)]


class PosesGame(Game):
    """Órdenes con nombre de meme dev; la cámara cuenta quién hace la pose (plan, 5.2)."""

    id: ClassVar[str] = "poses"
    title: ClassVar[str] = "Simón dice con poses"
    spoken: ClassVar[str] = "Simón dice con poses"
    needs: ClassVar[frozenset[str]] = frozenset({"camera", "preview", "poses"})
    settings_key: ClassVar[str] = "poses"

    def __init__(self, host: GameHost) -> None:
        super().__init__(host)
        self._skeletons = Skeletons()
        self._reset()

    def _reset(self) -> None:
        self._phase: Phase = "off"
        self._plan: list[tuple[PoseEntry, bool]] = []
        self._index = -1
        self._order = ""
        self._seconds = 0.0
        self._count = 0
        self._total = 0
        self._placement = Placement(0, 0)
        self._hint = ""
        self._results: list[RoundResult] = []
        self._empty_rounds = 0
        self._last_frame: object | None = None
        self._last_pose: str | None = None
        self._last_count: FrameCount | None = None
        self._touched_at = float("-inf")
        self._asked_close_at = float("-inf")
        self._shown_players = -1
        self._skeletons.clear()

    # -- lo que declara el juego ----------------------------------------------

    @classmethod
    def banks(cls) -> list[GameBank[Any]]:
        return [POSES_BANK]

    def phrases(self) -> list[str]:
        """Las órdenes de todas las poses activas, con y sin «Simón dice»."""
        out: list[str] = []
        for entry in self.host.read_bank(POSES_BANK):
            out.extend((entry.order(True), entry.order(False)))
        return out

    # -- ciclo de vida ----------------------------------------------------------

    def _cfg(self) -> PosesSettings:
        return self.host.settings.games.poses

    async def start(self, source: str, options: dict[str, Any]) -> str:
        self._reset()
        cfg = self._cfg()
        entries = await self.host.load_bank(POSES_BANK)
        plan = plan_rounds(entries, cfg.rounds, cfg.tricks, self.host.rng)
        if not plan:
            raise GameError(
                "No hay poses en el banco de Simón dice: el equipo del stand tiene que revisarlo."
            )
        if not await self.host.poses.acquire(self.id, cfg.fps):
            raise GameError("La cámara no está lista ahora mismo para Simón dice con poses.")
        if not await self.host.preview.start(self.id, mirror=True, overlay=self._skeletons.draw):
            raise GameError("La pantalla no puede enseñar la cámara en directo ahora mismo.")
        self._plan = plan
        await self.host.send("start", {"rounds": len(plan)})
        await self._show("placement")
        await self.host.instruct(RULES_TEXT.format(rounds=len(plan)))
        self.host.spawn(self._run(), "rondas")
        return START_TEXT.format(rounds=len(plan))

    async def resume(self) -> str:
        return RESUME_TEXT.format(round=max(1, self._index + 1), rounds=len(self._plan))

    async def stop(self, reason: StopReason) -> None:
        self._phase = "off"
        self._skeletons.clear()
        for release in (self.host.preview.stop, self.host.poses.release):
            try:
                await release(self.id)
            except Exception:  # noqa: BLE001 - soltar nunca tumba nada
                logger.debug("No se pudo soltar la visión de poses", exc_info=True)

    def nudge(self) -> str | None:
        if self._phase in ("placement", "round", "result"):
            return NUDGE_STOP
        return None

    def snapshot(self) -> dict[str, Any]:
        done, possible, fell = self._totals()
        entry = self._entry
        return {
            "phase": self._phase,
            "round": self._index + 1,
            "rounds": len(self._plan),
            "pose": entry.id if entry is not None and self._phase != "final" else "",
            "simon": self._simon if self._phase in ("command", "window", "result") else None,
            "players": self._placement.players,
            "close": self._placement.close,
            "results": [
                {"pose": r.pose, "simon": r.simon, "count": r.count, "total": r.total}
                for r in self._results
            ],
            "done": done,
            "possible": possible,
            "fell": fell,
            "summary": self._summary(),
        }

    def _summary(self) -> str:
        """En qué va la partida, en una línea para el panel («Ronda 2 de 6: 7 de 9»)."""
        phase = self._phase
        entry = self._entry
        if phase == "placement":
            text = f"Colocándose: juegan {self._placement.players}"
            return text + (" (alguien muy cerca)" if self._placement.close else "")
        if phase == "final":
            done, possible, fell = self._totals()
            return f"Final: {done} de {possible} bien" + (f", cayeron {fell}" if fell else "")
        if entry is None or phase == "off":
            return ""
        head = f"Ronda {self._index + 1} de {len(self._plan)}" + (
            "" if self._simon else " (trampa)"
        )
        if phase == "result":
            if not self._simon:
                return f"{head}: cayeron {self._count} de {self._total}"
            return f"{head}: {self._count} de {self._total}"
        return f"{head}: {entry.pose}"

    # -- la partida ---------------------------------------------------------------

    @property
    def _entry(self) -> PoseEntry | None:
        if 0 <= self._index < len(self._plan):
            return self._plan[self._index][0]
        return None

    @property
    def _simon(self) -> bool:
        if 0 <= self._index < len(self._plan):
            return self._plan[self._index][1]
        return True

    async def _run(self) -> None:
        """Las rondas, de la colocación al final. Un fallo cancela la partida con una frase."""
        try:
            await self._place(first=True)
            for index in range(len(self._plan)):
                if not await self._play_round(index):
                    await self.host.speak(EMPTY_FINAL_TEXT)
                    await self.host.finish("cancel")
                    return
            await self._final()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - la demo nunca se cae por el juego
            logger.exception("Simón dice: falló la partida; se cancela")
            await self.host.speak(FAILED_TEXT)
            await self.host.finish("cancel")

    async def _place(self, *, first: bool) -> None:
        """Hasta que haya gente colocada (y, en la primera, Sonia haya explicado el juego).

        Si hay alguien demasiado cerca, Sonia le pide un paso atrás (cada
        :data:`CLOSE_ASK_COOLDOWN_S` como mucho); si no se ve a nadie, que se pongan delante
        (una vez). Nunca pasa de ``2 * límite``: la partida sigue aunque no se coloquen.
        """
        host = self.host
        began = host.now()
        limit = PLACEMENT_MAX_S if first else REPLACE_MAX_S
        asked_at = began  # desde cuándo se espera a que Sonia hable (la explicación o un aviso)
        heard = not first  # entre rondas no hay explicación que esperar
        nobody_since: float | None = None
        asked_nobody = False
        ready_since: float | None = None
        self._phase = "placement"
        while True:
            counted = self._poll()
            place = counted.placement if counted is not None else Placement(0, 0)
            await self._show_placement(place)
            now = host.now()
            quiet = host.quiet_for()
            if quiet <= 0.05:
                heard = True
            calm = (heard and quiet >= INTRO_QUIET_S) or (
                not heard and now - asked_at >= INTRO_START_MAX_S
            )
            if place.players == 0 and place.close == 0:
                nobody_since = now if nobody_since is None else nobody_since
            else:
                nobody_since = None
            if calm and place.close and now - self._asked_close_at >= CLOSE_ASK_COOLDOWN_S:
                self._asked_close_at = asked_at = now
                heard = calm = False
                await host.speak(BACK_TEXT)
            elif (
                calm
                and first
                and not asked_nobody
                and nobody_since is not None
                and now - nobody_since >= NOBODY_ASK_S
            ):
                asked_nobody = True
                asked_at = now
                heard = calm = False
                await host.speak(NOBODY_TEXT)
            ready_since = (now if ready_since is None else ready_since) if place.ready else None
            if calm and ready_since is not None and now - ready_since >= READY_STABLE_S:
                return
            if (calm and now - began >= limit) or now - began >= 2 * limit:
                return
            await host.sleep(POLL_S)

    async def _play_round(self, index: int) -> bool:
        """Una ronda entera. ``False`` si ya van demasiadas rondas sin ver a nadie."""
        host = self.host
        await self._wait_calm()
        if index > 0 and self._placement.close:
            await self._place(first=False)
            await self._wait_calm()
        self._index = index
        entry, simon = self._plan[index]
        self._order = entry.order(simon)
        self._count = self._total = 0
        # En la pantalla sigue lo anterior hasta que suene la orden: si Sonia alarga la
        # explicación o vuelve a hablar, el pictograma, la demostración y el rótulo salen
        # con la frase grabada, no antes (con GPT-Live real salían 5,9 s antes). Mientras,
        # la fase ya es la de la ronda para que los esqueletos sigan en gris.
        self._phase = "round"
        said = await self._say(self._order)
        await self._show("round")
        await self._show("command")
        if said:
            await self._wait_phrase()
        self._seconds = max(0.3, float(self._cfg().window_seconds))
        await self._show("window")
        count, total, photo = await self._count_window(self._seconds)
        count, total = await self._judge(entry.id, count, total, photo)
        self._count, self._total = count, total
        result = RoundResult(entry.id, simon, count, total)
        self._results.append(result)
        await self._show("result")
        self._empty_rounds = self._empty_rounds + 1 if total == 0 else 0
        if self._empty_rounds >= EMPTY_ROUNDS_TO_STOP:
            return False
        await host.speak(self._result_text(result, last=index == len(self._plan) - 1))
        await self._pause(RESULT_HOLD_S)
        await self._wait_reply()
        return True

    async def _final(self) -> None:
        done, possible, fell = self._totals()
        await self._show("final")
        trap = ""
        if any(not r.simon for r in self._results):
            trap = FINAL_TRAP_TEXT.format(fell=fell) if fell else FINAL_NO_TRAP_TEXT
        text = FINAL_TEXT.format(done=done, possible=possible, trap=trap)
        contact = self.host.settings.trivia.win_contact.strip()
        if contact:
            text += WIN_CONTACT_TEXT.format(contact=contact)
        await self.host.speak(text)
        await self.host.finish("win", self._state("final"))

    def _result_text(self, result: RoundResult, *, last: bool) -> str:
        entry = self._entry
        label = entry.pose if entry is not None else result.pose
        head = ROUND_TEXT.format(round=self._index + 1, rounds=len(self._plan), label=label)
        count, total = result.count, result.total
        if total == 0:
            body = EMPTY_TEXT
        elif not result.simon:
            body = (TRAP_FELL_TEXT if count else TRAP_NONE_TEXT).format(count=count, total=total)
        elif count >= total:
            body = ALL_TEXT.format(count=count, total=total)
        elif count:
            body = SOME_TEXT.format(count=count, total=total)
        else:
            body = NONE_TEXT.format(total=total)
        return head + body + ("" if last else NEXT_TEXT)

    def _totals(self) -> tuple[int, int, int]:
        """``(bien hechas, posibles, caídos en trampas)`` de toda la partida."""
        done = sum(r.done for r in self._results)
        possible = sum(r.total for r in self._results)
        fell = sum(r.count for r in self._results if not r.simon)
        return done, possible, fell

    # -- esperas que siguen mirando la cámara -----------------------------------------

    async def _pause(self, seconds: float) -> None:
        end = self.host.now() + max(0.0, seconds)
        while self.host.now() < end:
            self._poll()
            await self.host.sleep(POLL_S)

    async def _wait_calm(self) -> bool:
        """Sonia callada y, si se puede, nadie hablando (como mucho :data:`CALM_MAX_S`).

        Pasados :data:`CALM_IDLE_MAX_S` con Sonia callada, basta con eso: la ronda no se
        queda esperando a que el grupo deje de reír o de comentar.
        """
        host = self.host
        began = host.now()
        quiet_since: float | None = None
        while host.now() - began < CALM_MAX_S:
            self._poll()
            now = host.now()
            if host.quiet_for() < CALM_QUIET_S:
                quiet_since = None
            else:
                quiet_since = now if quiet_since is None else quiet_since
                if now - quiet_since >= CALM_IDLE_MAX_S or await host.wait_idle(0.0):
                    return True
            await host.sleep(POLL_S)
        return False

    async def _say(self, order: str) -> bool:
        """La orden como frase grabada; si Sonia estaba hablando, se espera y se reintenta."""
        for _ in range(SAY_ATTEMPTS):
            if await self.host.say_fixed(order):
                return True
            await self._wait_calm()
        logger.info("Simón dice: no se pudo decir la orden %r", order)
        return False

    async def _wait_phrase(self) -> None:
        """Hasta que termina de sonar la orden (la ventana se abre después)."""
        host = self.host
        began = host.now()
        sounding = False
        while host.now() - began < PHRASE_MAX_S:
            self._poll()
            quiet = host.quiet_for()
            sounding = sounding or quiet <= 0.05
            if sounding and quiet >= PHRASE_END_QUIET_S:
                return
            if not sounding and host.now() - began >= PHRASE_START_MAX_S:
                return
            await host.sleep(WINDOW_POLL_S)

    async def _wait_reply(self) -> None:
        """Hasta que Sonia termina de reaccionar al resultado (si llega a hablar)."""
        host = self.host
        began = host.now()
        talked = False
        while host.now() - began < REPLY_MAX_S:
            self._poll()
            quiet = host.quiet_for()
            talked = talked or quiet <= 0.05
            if talked and quiet >= CALM_QUIET_S:
                return
            if not talked and host.now() - began >= REPLY_START_MAX_S:
                return
            await host.sleep(POLL_S)

    async def _count_window(self, seconds: float) -> tuple[int, int, np.ndarray | None]:
        """El mejor recuento de la ventana: ``(cuántos la hicieron, cuántos juegan, foto)``.

        La foto es para el juez (solo si hay, ``host.referee.available``; si no, ``None``): el
        frame de la cámara del mejor recuento local de la ventana, y entre los empatados el
        más reciente, porque la gente termina de colocarse en la pose según pasa la ventana.
        Si lo local no vio a nadie haciéndola, todos empatan a cero y queda el último frame
        de la ventana. Se coge al vuelo (``stream.latest()``) y solo vive en memoria.
        """
        host = self.host
        best = players = 0
        want_photo = host.referee.available
        photo: np.ndarray | None = None
        end = host.now() + seconds
        while True:
            counted = self._poll()
            if counted is not None:
                if want_photo and counted.doing >= best:
                    frame = self._camera_frame()
                    photo = frame if frame is not None else photo
                best = max(best, counted.doing)
                players = max(players, counted.players)
            if host.now() >= end:
                break
            await host.sleep(WINDOW_POLL_S)
        if want_photo and photo is None:
            photo = self._camera_frame()
        return min(best, players), players, photo

    async def _judge(
        self, pose: str, count: int, total: int, photo: np.ndarray | None
    ) -> tuple[int, int]:
        """El veredicto de la ronda: el del juez con ``photo`` o, sin él, el recuento local.

        Si el veredicto trae la pose, cuenta lo suyo: ``(cuántos la hacen, cuántas personas
        ve)``. Mientras mira, la pastilla de espera; la vista en vivo sigue con los esqueletos.
        Sin juez o sin foto, ni foto ni aviso: el recuento local, como antes.
        """
        host = self.host
        if photo is None or not host.referee.available:
            return count, total
        verdict = None
        await self._set_busy(TEXT_POSES)
        task = asyncio.ensure_future(host.referee.poses(photo))
        try:
            limit = host.now() + float(host.settings.games.judge_timeout_seconds) + JUDGE_GRACE_S
            while not task.done() and host.now() < limit:
                self._poll()
                await host.sleep(WINDOW_POLL_S)
            if task.done():
                verdict = task.result()
            else:
                logger.info("Simón dice: el juez no contestó a tiempo; vale el recuento local")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - sin juez, decide lo local
            logger.warning("Simón dice: falló el juez; vale el recuento local", exc_info=True)
            verdict = None
        finally:
            if not task.done():
                task.cancel()
            await self._set_busy(None)
        if verdict is None or pose not in verdict.counts:
            return count, total
        seen = max(0, int(verdict.people))
        judged = min(max(0, int(verdict.counts[pose])), seen)
        # Quién juega: el juez cuenta a todos los que ve, también a quien pasa por el fondo,
        # y la detección local solo a los que están cerca (``GAME_POSES_MIN_PERSON``). Si lo
        # local vio jugadores, el total es el suyo, nunca menos que los que hicieron la pose;
        # si no vio a nadie, el del juez, con tope.
        people = max(total, judged) if total > 0 else max(min(seen, MAX_JUDGED_PLAYERS), judged)
        if (judged, people) != (count, total):
            logger.info(
                "Simón dice, %s: el juez ve %d de %d (lo local, %d de %d)",
                pose,
                judged,
                people,
                count,
                total,
            )
        return judged, people

    async def _set_busy(self, text: str | None) -> None:
        """Enciende o apaga la pastilla de espera del juez; nunca tumba la ronda."""
        try:
            await self.host.set_busy("judge", text)
        except Exception:  # noqa: BLE001
            logger.debug("No se pudo cambiar el aviso de espera", exc_info=True)

    def _camera_frame(self) -> np.ndarray | None:
        """El último frame de la cámara (para la foto del juez), o ``None``."""
        try:
            latest = self.host.stream.latest()
        except Exception:  # noqa: BLE001
            return None
        return latest[1] if latest is not None else None

    # -- cámara y vista en vivo ---------------------------------------------------------

    def _live_pose(self) -> str | None:
        """La pose que se evalúa ahora (se pinta en verde): solo en la ventana y el resultado."""
        entry = self._entry
        if self._phase in ("window", "result") and entry is not None:
            return entry.id
        return None

    def _poll(self) -> FrameCount | None:
        """Mira la última detección: recuento, colocación, esqueletos y actividad."""
        frame = self.host.poses.latest(FRAME_MAX_AGE_S)
        if frame is None:
            self._last_frame = None
            self._last_count = None
            self._skeletons.clear()
            return None
        pose = self._live_pose()
        if frame is self._last_frame and pose == self._last_pose and self._last_count is not None:
            return self._last_count
        counted = count_frame(frame, pose, float(self._cfg().min_person))
        trap = not self._simon
        self._skeletons.show(Skeleton(person, _tint(mark, trap)) for person, mark in counted.marks)
        self._last_frame = frame
        self._last_pose = pose
        self._last_count = counted
        self._placement = counted.placement
        now = self.host.now()
        if counted.players and now - self._touched_at >= TOUCH_EVERY_S:
            self._touched_at = now
            self.host.touch()
        return counted

    # -- pantalla ---------------------------------------------------------------------------

    def _state(self, phase: Phase) -> dict[str, Any]:
        """El estado completo de la pantalla (cada evento lo lleva entero: ver el protocolo)."""
        entry = self._entry if phase not in ("placement", "final") else None
        done, possible, fell = self._totals()
        return {
            "phase": phase,
            "round": self._index + 1 if entry is not None else 0,
            "rounds": len(self._plan),
            "pose": entry.id if entry is not None else "",
            "label": entry.label if entry is not None else "",
            "meme": entry.meme if entry is not None else "",
            "demo": entry.demo if entry is not None else "",
            "order": self._order if phase in ("command", "window", "result") else "",
            "simon": self._simon if entry is not None else True,
            "seconds": round(self._seconds, 2) if phase == "window" else 0.0,
            "count": self._count if phase == "result" else 0,
            "total": self._total if phase == "result" else 0,
            "players": self._placement.players,
            "hint": self._hint if phase == "placement" else "",
            "done": done if phase == "final" else 0,
            "possible": possible if phase == "final" else 0,
            "fell": fell if phase == "final" else 0,
        }

    async def _show(self, phase: Phase) -> None:
        self._phase = phase
        if phase == "placement":
            self._hint = _hint(self._placement)
        await self.host.send(phase, self._state(phase))

    async def _show_placement(self, place: Placement) -> None:
        """La colocación en pantalla, solo si ha cambiado (cuántos y el aviso)."""
        hint = _hint(place)
        if self._phase == "placement" and (hint, place.players) == (
            self._hint,
            self._shown_players,
        ):
            return
        self._placement = place
        self._hint = hint
        self._shown_players = place.players
        await self._show("placement")


def _hint(place: Placement) -> str:
    if place.close:
        return HINT_CLOSE
    if place.players == 0:
        return HINT_NOBODY
    return ""


def _tint(mark: Mark, trap: bool) -> Tint:
    if mark == "ok":
        return "fell" if trap else "ok"
    return mark
