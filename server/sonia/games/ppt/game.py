"""Piedra, papel o tijera (``piedra_papel_tijera``): uno contra Sonia, la cámara lee la mano
del jugador y ella saca la suya con el avatar (``docs/juegos/piedra_papel_tijera.md``).

Una sola delegación: ``start_game``. A partir de ahí la partida va sola, sin jugadas
delegadas, porque la jugada del visitante no se entiende por voz: la lee la cámara.

Cada tirada:

1. Se espera a que haya un jugador delante de la cámara (la persona más cercana y
   centrada; los demás no cuentan) y a que nadie hable.
2. El orquestador elige la jugada de Sonia **antes** de mirar.
3. ``round`` y ``ready`` (Sonnia sube el puño), y ``countdown`` justo antes de la frase
   grabada «¡Piedra, papel o tijera… ya!» (``say_fixed``). ``countdown`` lleva ``go_s``, los
   segundos del principio de la frase al «¡ya!» medidos en la grabación, para que Unity
   agite el puño al ritmo y saque la mano en el «ya». Sin grabación, el «ya» se toma de
   la transcripción de Sonia. En el «ya», ``go``.
4. Se lee la mano del jugador durante ``GAME_PPT_READ_SECONDS`` (un poco después del
   «ya», lo que se tarda en reaccionar) y se queda con la lectura estable
   (:func:`~sonia.games.ppt.logic.settle`). Con juez de rondas (``GAMES_JUDGE=gemini``),
   el frame de esa lectura va al juez, que decide la jugada; si no contesta a tiempo,
   decide la lectura local.
5. ``result`` y la reacción de Sonia (``speak``). Sin lectura, «¡no te vi la mano!» y
   se repite la ronda (``GAME_PPT_RETRIES``); si tampoco, la ronda no cuenta.
6. Al mejor de ``GAME_PPT_ROUNDS``: ``final`` y ``finish``. Si gana el visitante, se le
   manda con el equipo del stand (``TRIVIA_WIN_CONTACT``).

Nada se guarda ni se reconoce a nadie: el jugador es «el más grande y centrado» de cada
momento, y si cambia a mitad de partida, el juego sigue con quien tenga la mano delante.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, ClassVar, Literal

import numpy as np

from sonia.busy import TEXT_HAND
from sonia.games.base import Game, GameError, GameHost, StopReason
from sonia.games.ppt.logic import (
    MOVES,
    NO_HAND,
    Box,
    Sample,
    contradicted,
    pick_player,
    read_sample,
    says_ya,
    settle,
    winner_of,
    ya_onset,
)
from sonia.games.ppt.overlay import OverlayState, draw_state
from sonia.vision.contracts import HandShape, HandVerdict, Person, PoseFrame

if TYPE_CHECKING:
    from sonia.config import PptSettings, Settings

__all__ = ["PHRASE", "PptGame", "phrase_go_seconds"]

logger = logging.getLogger(__name__)

#: La frase grabada de la cuenta (``say_fixed``; se graba con «Preparar voces»).
PHRASE = "¡Piedra, papel o tijera… ya!"

# -- tiempos ----------------------------------------------------------------

#: Sonnia sube el puño (``ready``) este rato antes de la cuenta.
READY_LEAD_S = 0.8
#: Lo que tarda en sonar en Unity la frase desde que se manda (búfer y retardo del lip-sync).
AUDIO_LAG_S = 0.12
#: Sin frase grabada medida: tope para oír el «ya» en la transcripción de Sonia.
GO_TIMEOUT_S = 5.0
#: La lectura empieza esto después del «ya» (lo que se tarda en reaccionar y abrir la mano).
REACTION_S = 0.25
#: Cada cuánto se lee la mano durante la lectura.
READ_STEP_S = 0.08
#: Si al acabar la lectura no hay jugada estable (o la última lectura la contradice), se
#: alarga como mucho esto.
READ_EXTEND_S = 0.6
#: Cada cuánto se mira quién juega mientras se espera.
TRACK_STEP_S = 0.1
#: Detección de poses que se da por buena (más vieja, no hay nadie).
POSE_MAX_AGE_S = 0.6
#: Sin jugador delante: el rótulo y el aviso a Sonia salen a los 5 s; a los 30, se cancela.
HINT_AFTER_S = 5.0
NO_PLAYER_CANCEL_S = 30.0
#: Como mucho un ``touch`` por segundo mientras se ve al jugador.
TOUCH_EVERY_S = 1.0
#: Esperas a que Sonia cuente algo: que empiece a hablar en ``start_s`` y termine (lleve
#: ``SPOKEN_QUIET_S`` callada) antes de ``limit_s``.
INTRO_START_S = 7.0
INTRO_LIMIT_S = 15.0
REACTION_START_S = 3.5
REACTION_LIMIT_S = 10.0
SPOKEN_QUIET_S = 0.8
#: Antes de cada cuenta, a que nadie hable (como mucho esto, y luego se intenta igual).
IDLE_WAIT_S = 8.0
#: Pausa entre una reacción y la siguiente tirada.
BETWEEN_S = 0.5
#: Intentos seguidos de cuenta que no llegan a sonar (Sonia hablaba) antes de dejarlo.
MAX_SAY_FAILURES = 5
#: Rondas seguidas sin ver la mano antes de dejarlo.
MAX_VOID_IN_A_ROW = 2
#: Tope de tiradas por partida: ``rounds`` por esto (empates y rondas nulas incluidos).
THROWS_PER_ROUND = 4
#: Sacudidas del puño antes del «ya».
BEATS = 3

# -- textos de pantalla («Sonnia») -------------------------------------------

HINT_NO_PLAYER = "¡Ponte delante de la cámara!"

# -- textos para GPT-Live («Sonia», sin marcas del stack) ---------------------

RULES = (
    "JUEGO EN MARCHA: piedra, papel o tijera, el visitante contra ti, al mejor de {rounds} "
    "(gana quien llegue a {target}). La pantalla lo lleva todo sola: antes de cada ronda elige "
    "tu jugada, suena tu voz con «¡Piedra, papel o tijera… ya!», tu mano sale en la pantalla y "
    "la cámara lee la mano del jugador (la persona más cercana y centrada). Tú no eliges ni ves "
    "ninguna jugada: no digas tú la cuenta, no anuncies jugadas ni resultados por tu cuenta y no "
    "inventes lo que sacó nadie. Te iré pasando cada resultado: reacciónalo en una frase corta, "
    "con chispa, y calla para que la siguiente ronda empiece sola. Para que la cámara le vea, el "
    "jugador se pone a un paso, con la mano delante del pecho, y la enseña quieta justo en el "
    "«¡ya!». Si piden parar o cambiar de juego, delega terminar el juego. Si preguntan, la "
    "cámara solo mira la mano mientras dura el juego, en este equipo, y no guarda nada."
)

START_SCRIPT = (
    "Di en una o dos frases que vais a jugar a piedra, papel o tijera, al mejor de {rounds}: "
    "que se ponga delante de la cámara, a un paso, con la mano a la altura del pecho, y que la "
    "enseñe justo en el «¡ya!». Después calla: la primera ronda empieza sola."
)

RESUME_SCRIPT = (
    "Ya estáis jugando a piedra, papel o tijera, al mejor de {rounds}: va Sonia {sonnia}, "
    "jugador {player}. No hace falta empezarlo: la siguiente ronda empieza sola cuando calles."
)

THROW_DECIDED = "RESULTADO de la ronda {round}: sacaste {sonnia} y el jugador {player}: {who}."
THROW_TIE = "RESULTADO de la ronda {round}: los dos sacasteis {sonnia}, empate."
THROW_VOID = "Tampoco esta vez viste la mano del jugador: esta ronda no cuenta para nadie."

GOES_ON = (
    " Marcador: Sonia {sonnia}, jugador {player}. Reacciona en una frase corta y calla: la "
    "siguiente ronda empieza sola."
)
TIE_GOES_ON = " La ronda se repite. Dilo en una frase muy corta y calla."

RETRY_NO_HAND = (
    "No viste la mano del jugador: dile «¡no te vi la mano!», que la ponga delante del pecho, "
    "de cara a la cámara, y que repetís la ronda. Una frase corta y calla."
)
RETRY_UNCLEAR = (
    "No entendiste la mano del jugador: dile que no la viste clara, que enseñe una sola mano, "
    "quieta, justo en el «¡ya!», y que repetís la ronda. Una frase corta y calla."
)

FINAL_PLAYER = (
    " Con eso el jugador GANA LA PARTIDA {player} a {sonnia}: felicítale con alegría y dile "
    "que pase a ver a {contact} del equipo del stand."
)
FINAL_SONNIA = (
    " Con eso GANAS TÚ LA PARTIDA {sonnia} a {player}: celébralo con gracia, sin burlarte, y "
    "anímale a pedir la revancha."
)
FINAL_TIE = (
    " Se acabaron las rondas y quedáis empate a {sonnia}: dilo con gracia y anímale a pedir la "
    "revancha."
)

NO_PLAYER_TEXT = (
    "No ves a nadie delante de la cámara para jugar a piedra, papel o tijera: pide en una frase "
    "que el jugador se ponga delante, a un paso, con la mano a la altura del pecho."
)
NO_PLAYER_CANCEL_TEXT = (
    "Sigue sin haber nadie delante de la cámara: di en una frase que dejáis piedra, papel o "
    "tijera para otro momento."
)
CANT_SEE_TEXT = (
    "La cámara no consigue ver la mano del jugador: discúlpate en una frase, dile que lo "
    "dejáis aquí y proponle otro juego o charlar."
)
SAY_FAILED_TEXT = (
    "La cuenta de piedra, papel o tijera no consigue arrancar: di en una frase que lo dejáis "
    "para otro momento."
)

# -- control a mano desde el panel --------------------------------------------

#: La jugada del visitante, puesta a mano en la tirada en curso (manda sobre la lectura).
MOVE_CONTROLS: dict[str, HandShape] = {
    "piedra": HandShape.ROCK,
    "papel": HandShape.PAPER,
    "tijera": HandShape.SCISSORS,
}
#: «Otra ronda»: la siguiente tirada ya, sin esperar a nadie delante ni a que callen.
CONTROL_AGAIN = "again"

#: En qué anda la partida (para el panel).
Phase = Literal["off", "intro", "waiting", "ready", "countdown", "reading", "result", "final"]

#: Quién ganó, para la pantalla: el de una tirada (``none``: sin lectura) o el de la partida.
ThrowWinner = Literal["sonnia", "player", "tie", "none"]


def phrase_go_seconds(settings: Settings) -> float | None:
    """Del principio de la frase grabada al «¡ya!», en segundos (``None`` sin grabación).

    Lee la caché de voces como el motor (``VoiceCache`` sobre ``PANEL_VOICE_CACHE_DIR``
    con la voz y la tasa de ahora). Lee disco: en un hilo.
    """
    try:
        from sonia.live.voicecache import VoiceCache

        pcm = VoiceCache(settings.panel.voice_cache_dir, settings.live).get(PHRASE)
        if not pcm:
            return None
        return ya_onset(pcm, settings.live.sample_rate)
    except Exception:  # noqa: BLE001 - sin medida, el «ya» sale de la transcripción
        logger.debug("No se pudo medir la frase grabada de piedra, papel o tijera", exc_info=True)
        return None


class PptGame(Game):
    """Uno contra Sonia: la cámara lee la mano del jugador y ella saca la suya (plan, 5.4)."""

    id: ClassVar[str] = "piedra_papel_tijera"
    title: ClassVar[str] = "Piedra, papel o tijera"
    spoken: ClassVar[str] = "piedra, papel o tijera"
    needs: ClassVar[frozenset[str]] = frozenset({"camera", "preview", "poses", "hands"})
    settings_key: ClassVar[str] = "ppt"

    def __init__(self, host: GameHost) -> None:
        super().__init__(host)
        self._reset()

    # -- estado -----------------------------------------------------------------

    def _reset(self) -> None:
        self._phase: Phase = "off"
        self._round = 1
        self._throws = 0
        self._points = {"sonnia": 0, "player": 0}
        self._retries_left = 0
        self._void_in_a_row = 0
        self._move: HandShape | None = None
        self._last: dict[str, Any] | None = None
        self._go_s: float | None = None
        self._ya_heard = False
        self._player_box: Box | None = None
        self._player_seen_at = float("-inf")
        self._touched_at = float("-inf")
        self._overlay = OverlayState()
        #: Control a mano del panel: la jugada del visitante y si la tirada va ya.
        self._manual_move: HandShape | None = None
        self._again = False

    @property
    def options(self) -> PptSettings:
        """Los ajustes del juego (``GAME_PPT_*``)."""
        return self.host.settings.games.ppt

    @property
    def rounds(self) -> int:
        return max(1, min(15, int(self.options.rounds)))

    @property
    def target(self) -> int:
        """Victorias para ganar la partida (al mejor de ``rounds``)."""
        return self.rounds // 2 + 1

    @property
    def phase(self) -> Phase:
        return self._phase

    @property
    def round(self) -> int:
        return self._round

    @property
    def throws(self) -> int:
        """Tiradas terminadas (con empates, repeticiones y rondas nulas)."""
        return self._throws

    @property
    def move(self) -> HandShape | None:
        """La jugada de Sonia en la tirada en curso (elegida antes de mirar)."""
        return self._move

    @property
    def score(self) -> dict[str, int]:
        return dict(self._points)

    def _base(self) -> dict[str, Any]:
        return {
            "round": self._round,
            "rounds": self.rounds,
            "target": self.target,
            "score": self.score,
        }

    # -- lo que declara el juego ------------------------------------------------

    def phrases(self) -> list[str]:
        return [PHRASE]

    def rules(self) -> str:
        """Las reglas para GPT-Live (``instruct``, 1200 caracteres como mucho)."""
        return RULES.format(rounds=self.rounds, target=self.target)

    # -- ciclo de vida ----------------------------------------------------------

    async def start(self, source: str, options: dict[str, Any]) -> str:
        self._reset()
        self._retries_left = max(0, int(self.options.retries))
        host = self.host
        if not await host.stream.acquire(self.id):
            raise GameError("No hay cámara para jugar a piedra, papel o tijera ahora mismo.")
        fps = max(2.0, min(30.0, float(self.options.fps)))
        if not await host.poses.acquire(self.id, fps):
            raise GameError("La cámara no consigue ver a las personas ahora mismo.")
        try:
            if not await host.preview.start(self.id, mirror=True, overlay=self._draw):
                logger.info("Piedra, papel o tijera sin vista en vivo")
        except Exception:  # noqa: BLE001 - sin vista en vivo se juega igual
            logger.exception("No se pudo encender la vista en vivo")
        self._phase = "intro"
        await host.send("start", self._base())
        await host.instruct(self.rules())
        host.spawn(self._run(), "match")
        return START_SCRIPT.format(rounds=self.rounds)

    async def resume(self) -> str:
        return RESUME_SCRIPT.format(
            rounds=self.rounds, sonnia=self._points["sonnia"], player=self._points["player"]
        )

    async def stop(self, reason: StopReason) -> None:
        self._phase = "off"
        self._overlay = OverlayState()

    async def on_assistant_text(self, text: str, final: bool) -> None:
        if self._phase == "countdown" and not self._ya_heard and says_ya(text):
            self._ya_heard = True

    def snapshot(self) -> dict[str, Any]:
        summary = (
            f"Ronda {self._round} (al mejor de {self.rounds}), "
            f"Sonnia {self._points['sonnia']} - {self._points['player']} Tú"
        )
        return {
            "summary": summary,
            "phase": self._phase,
            "round": self._round,
            "rounds": self.rounds,
            "target": self.target,
            "score": self.score,
            "throws": self._throws,
            "player_seen": self._player_box is not None,
            "last": dict(self._last) if self._last else None,
        }

    # -- la vista en vivo -------------------------------------------------------

    def _draw(self, image: np.ndarray, mirrored: bool) -> None:
        """El ``Overlay`` de la vista en vivo (en su hilo): solo lee el estado de ahora."""
        draw_state(image, self._overlay, mirrored)

    # -- la partida ---------------------------------------------------------------

    async def _run(self) -> None:
        try:
            await self._match()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - la demo no se cae por una partida rota
            logger.exception("La partida de piedra, papel o tijera falló")
            if self._phase != "off":
                await self.host.finish("cancel", {"score": self.score, "reason": "error"})

    async def _match(self) -> None:
        host = self.host
        try:
            self._go_s = await asyncio.to_thread(phrase_go_seconds, host.settings)
        except Exception:  # noqa: BLE001
            self._go_s = None
        logger.info(
            "Piedra, papel o tijera: «ya» de la frase grabada a %s",
            f"{self._go_s:.2f} s" if self._go_s is not None else "(sin grabar: transcripción)",
        )
        await self._wait_spoken(INTRO_START_S, INTRO_LIMIT_S)
        say_failures = 0
        max_throws = self.rounds * THROWS_PER_ROUND
        while self._phase != "off":
            if not await self._wait_player():
                return
            await self._wait_idle()
            # Empieza una tirada: lo del panel de antes ya no vale.
            self._again = False
            self._manual_move = None
            self._move = host.rng.choice(MOVES)
            ya_at = await self._countdown(self._move)
            if ya_at is None:
                say_failures += 1
                if say_failures >= MAX_SAY_FAILURES:
                    await host.speak(SAY_FAILED_TEXT)
                    await self._finish_cancel("countdown")
                    return
                await self._wait_idle()
                continue
            say_failures = 0
            sample, reason = await self._read(ya_at)
            self._throws += 1
            if await self._resolve(self._move, sample, reason, max_throws):
                return
            await self._wait_spoken(REACTION_START_S, REACTION_LIMIT_S)
            await self._wait_idle()
            await self._pause(BETWEEN_S)

    async def _countdown(self, move: HandShape) -> float | None:
        """``round``, ``ready``, ``countdown`` y la frase grabada. Devuelve cuándo cayó el
        «¡ya!» (con el reloj del juego), o ``None`` si la frase no llegó a sonar."""
        host = self.host
        retry = self._throws > 0 and self._last is not None and self._last["round"] == self._round
        self._overlay = OverlayState(player=self._player_box)
        await host.send("round", {**self._base(), "retry": retry})
        self._phase = "ready"
        await host.send("ready", {"round": self._round}, sticky=False)
        await self._pause(READY_LEAD_S)
        self._phase = "countdown"
        self._ya_heard = False
        go_s = self._go_s
        await host.send(
            "countdown",
            {"round": self._round, "sonnia": move.value, "go_s": go_s, "beats": BEATS},
            sticky=False,
        )
        started = host.now()
        if not await host.say_fixed(PHRASE):
            logger.info("Piedra, papel o tijera: la cuenta no sonó (Sonia hablaba); se repite")
            self._phase = "waiting"
            await host.send("abort", {"round": self._round}, sticky=False)
            return None
        if go_s is not None:
            ya_at = started + go_s + AUDIO_LAG_S
            await self._sleep_until(ya_at)
        else:
            deadline = started + GO_TIMEOUT_S
            while not self._ya_heard and host.now() < deadline and self._phase == "countdown":
                await host.sleep(0.05)
            ya_at = host.now()
        await host.send("go", {"round": self._round, "sonnia": move.value}, sticky=False)
        return ya_at

    async def _read(self, ya_at: float) -> tuple[Sample, str]:
        """Lee la mano del jugador tras el «¡ya!» y se queda con la lectura estable.

        Devuelve la muestra elegida (jugada y caja) y, sin jugada, por qué: ``no_hand``
        (no se vio ninguna mano enseñándose) o ``unclear`` (se vio pero no se entendió).
        Con juez de rondas, la jugada la decide él sobre el frame de esa lectura
        (:meth:`_judged`); la lectura local solo elige el momento y decide si el juez no
        contesta.
        """
        host = self.host
        self._phase = "reading"
        start = ya_at + REACTION_S
        await self._sleep_until(start)
        soft_end = start + max(0.2, float(self.options.read_seconds))
        hard_end = soft_end + READ_EXTEND_S
        samples: list[Sample] = []
        #: El frame de cada muestra (``None`` si no había), solo en memoria: uno va al juez.
        #: Las muestras sin mano ni persona también llevan el suyo: ahí es donde más aporta.
        frames: list[np.ndarray | None] = []
        #: La muestra con la que se llegó a ``soft_end`` (el final de la lectura sin alargar).
        soft_index: int | None = None
        while self._manual_move is None:
            began = host.now()
            sample, frame = await self._sample()
            samples.append(sample)
            frames.append(frame)
            shapes = [s.shape for s in samples]
            now = host.now()
            if now >= soft_end:
                if soft_index is None:
                    soft_index = len(samples) - 1
                found = settle(shapes)
                if (found is not None and not contradicted(shapes, found)) or now >= hard_end:
                    break
            # Una lectura tarda lo suyo (poses y manos, en hilos): se espera solo lo que falte.
            await host.sleep(max(0.01, READ_STEP_S - (now - began)))
        if self._manual_move is not None:
            return self._manual_sample(samples), ""
        shapes = [s.shape for s in samples]
        found = settle(shapes)
        last_frame = next((f for f in reversed(frames) if f is not None), None)
        if found is None:
            reason = "unclear" if any(s.seen for s in samples) else "no_hand"
            box = next((s.box for s in reversed(samples) if s.box is not None), None)
            # Sin jugada estable (tampoco si lo local no vio persona ni mano), el último frame
            # leído al llegar a ``soft_end``: la mano ya quieta tras el «¡ya!» y antes de que
            # la bajen durante el alargue.
            upto = frames if soft_index is None else frames[: soft_index + 1]
            soft_frame = next((f for f in reversed(upto) if f is not None), None)
            local, photo = Sample(None, reason == "unclear", box), soft_frame
        else:
            index = max(i for i, s in enumerate(samples) if s.shape is found)
            reason = ""
            local, photo = samples[index], frames[index]
        # Al juez, el frame de la lectura estable (la jugada ya quieta tras el «¡ya!») o el de
        # ``soft_end``; solo sin ningún frame de la cámara se queda lo local sin preguntar.
        judged = await self._judged(
            local, reason, samples, photo if photo is not None else last_frame
        )
        if self._manual_move is not None:  # puesta a mano mientras miraba el juez
            return self._manual_sample(samples), ""
        return judged

    def _manual_sample(self, samples: list[Sample]) -> Sample:
        """La jugada puesta a mano desde el panel, con la caja de la mano local si la hubo."""
        move = self._manual_move
        assert move is not None
        logger.info("Piedra, papel o tijera: jugada puesta a mano desde el panel: %s", move.value)
        box = next((s.box for s in reversed(samples) if s.box is not None), None)
        return Sample(move, True, box)

    # -- control a mano desde el panel ------------------------------------------------

    def panel_controls(self) -> list[dict[str, Any]]:
        """Durante la tirada, la jugada del visitante; entre tiradas, «Otra ronda»."""
        if self._phase in ("ready", "countdown", "reading"):
            return [
                {"id": control, "label": move.value.capitalize()}
                for control, move in MOVE_CONTROLS.items()
            ]
        if self._phase in ("intro", "waiting", "result"):
            return [{"id": CONTROL_AGAIN, "label": "Otra ronda"}]
        return []

    async def panel_control(self, control: str, value: str) -> str:
        """La jugada del visitante manda en la tirada en curso; «Otra ronda» la lanza ya."""
        move = MOVE_CONTROLS.get(control)
        if move is not None:
            if self._phase not in ("ready", "countdown", "reading"):
                raise GameError("La jugada del visitante solo se puede poner durante la tirada.")
            self._manual_move = move
            return ""
        if control == CONTROL_AGAIN:
            if self._phase not in ("intro", "waiting", "result"):
                raise GameError("Ya hay una tirada en marcha.")
            self._again = True
            return ""
        raise GameError("Ese control no es de piedra, papel o tijera.")

    async def _judged(
        self, local: Sample, reason: str, samples: list[Sample], photo: np.ndarray | None
    ) -> tuple[Sample, str]:
        """La jugada que ve el juez de rondas en ``photo``; sin veredicto, la lectura local.

        Con veredicto manda el juez aunque la lectura local dijera otra cosa: su primera
        jugada es la del jugador y, si no ve ninguna, no hay jugada (``unclear`` si la
        lectura local vio una mano, ``no_hand`` si no). La caja de la mano sigue siendo la
        local (la vista en vivo la marca), o ninguna.
        """
        verdict = await self._ask_referee(photo)
        if verdict is None:
            return local, reason
        box = local.box or next((s.box for s in reversed(samples) if s.box is not None), None)
        plays = [shape for shape in verdict.shapes if shape in MOVES]
        if plays:
            judged = plays[0]
            if judged is not local.shape:
                logger.info(
                    "Piedra, papel o tijera: el juez ve %s y la lectura local %s",
                    judged.value,
                    local.shape.value if local.shape is not None else f"nada ({reason})",
                )
            return Sample(judged, True, box), ""
        judged_reason = "unclear" if any(s.seen for s in samples) else "no_hand"
        if local.shape is not None:
            logger.info(
                "Piedra, papel o tijera: el juez no ve jugada y la lectura local %s",
                local.shape.value,
            )
        return Sample(None, judged_reason == "unclear", box), judged_reason

    async def _ask_referee(self, photo: np.ndarray | None) -> HandVerdict | None:
        """El veredicto del juez sobre ``photo``, con el aviso de espera mientras mira.

        ``None`` sin juez (``GAMES_JUDGE=local`` o sin clave: ni foto ni aviso), sin foto,
        sin respuesta a tiempo o si falla. Nunca lanza.
        """
        host = self.host
        referee = host.referee
        if photo is None or not referee.available:
            return None
        try:
            await host.set_busy("judge", TEXT_HAND)
            return await referee.hands(photo)
        except Exception:  # noqa: BLE001 - sin veredicto, decide la lectura local
            logger.warning("Piedra, papel o tijera: el juez falló", exc_info=True)
            return None
        finally:
            try:
                await host.set_busy("judge", None)
            except Exception:  # noqa: BLE001 - apagar el aviso nunca tumba nada
                logger.debug("No se pudo apagar el aviso del juez", exc_info=True)

    async def _sample(self) -> tuple[Sample, np.ndarray | None]:
        """Una lectura: el jugador y la mano que enseña, los dos del mismo frame.

        Las poses se detectan sobre el frame de ahora (``poses.detect``) para que la
        persona y su mano sean del mismo instante; si falla, la última detección continua.
        Devuelve también ese frame (``None`` si la cámara no dio ninguno) para el juez.
        """
        host = self.host
        latest = host.stream.latest()
        if latest is None:
            self._track()
            return NO_HAND, None
        at, frame = latest
        try:
            pose = await host.poses.detect(frame, at)
        except Exception:  # noqa: BLE001 - sin detección suelta, la continua
            logger.debug("Falló la detección de poses de la lectura", exc_info=True)
            pose = None
        person = self._track(pose) if pose is not None else self._track()
        if person is None:
            return NO_HAND, frame
        try:
            readings = await host.hands.read(frame, person)
        except Exception:  # noqa: BLE001 - una lectura fallida es una muestra sin mano
            logger.debug("Falló una lectura de manos", exc_info=True)
            return NO_HAND, frame
        sample = read_sample(readings, person)
        self._overlay = OverlayState(
            player=self._player_box, hand=sample.box, hand_ok=sample.shape is not None
        )
        return sample, frame

    async def _resolve(self, move: HandShape, sample: Sample, reason: str, max_throws: int) -> bool:
        """Cuenta la tirada, la pinta y se la pasa a Sonia. ``True`` si la partida acabó."""
        host = self.host
        self._phase = "result"
        self._overlay = OverlayState(
            player=self._player_box, hand=sample.box, hand_ok=sample.shape is not None
        )
        player = sample.shape
        thrown_round = self._round
        retry = False
        void = False
        winner: ThrowWinner
        if player is None:
            winner = "none"
            if self._retries_left > 0:
                self._retries_left -= 1
                retry = True
            else:
                void = True
                self._void_in_a_row += 1
                self._next_round()
        else:
            self._void_in_a_row = 0
            winner = winner_of(move, player)
            if winner != "tie":
                self._points[winner] += 1
                self._next_round()
        self._last = {
            "round": thrown_round,
            "sonnia": move.value,
            "player": player.value if player is not None else None,
            "winner": winner,
            "reason": reason if player is None else "",
            "retry": retry,
        }
        await host.send("result", {**self._base(), **self._last, "round": thrown_round})
        logger.info(
            "Piedra, papel o tijera, tirada %d: Sonia %s, jugador %s → %s (%d-%d)",
            self._throws,
            move.value,
            player.value if player is not None else f"sin lectura ({reason})",
            winner,
            self._points["sonnia"],
            self._points["player"],
        )
        if retry:
            await host.speak(RETRY_UNCLEAR if reason == "unclear" else RETRY_NO_HAND)
            return False
        if void and self._void_in_a_row >= MAX_VOID_IN_A_ROW:
            await host.speak(CANT_SEE_TEXT)
            await self._finish_cancel("no_hand")
            return True
        throw_text = self._throw_text(thrown_round, move, player, winner)
        best = max(self._points.values())
        if best >= self.target or self._throws >= max_throws:
            await self._final(throw_text)
            return True
        tail = TIE_GOES_ON if winner == "tie" else GOES_ON.format(**self._points)
        await host.speak(throw_text + tail)
        return False

    def _next_round(self) -> None:
        self._round += 1
        self._retries_left = max(0, int(self.options.retries))

    @staticmethod
    def _throw_text(
        number: int, move: HandShape, player: HandShape | None, winner: ThrowWinner
    ) -> str:
        if player is None:
            return THROW_VOID
        if winner == "tie":
            return THROW_TIE.format(round=number, sonnia=move.value)
        who = "gana el jugador" if winner == "player" else "ganas tú"
        return THROW_DECIDED.format(round=number, sonnia=move.value, player=player.value, who=who)

    async def _final(self, throw_text: str) -> None:
        host = self.host
        self._phase = "final"
        sonnia, player = self._points["sonnia"], self._points["player"]
        winner: Literal["sonnia", "player", "tie"] = (
            "player" if player > sonnia else "sonnia" if sonnia > player else "tie"
        )
        contact = host.settings.trivia.win_contact
        last = self._last or {}
        await host.send(
            "final",
            {
                "winner": winner,
                "score": self.score,
                "rounds": self.rounds,
                "target": self.target,
                "sonnia": last.get("sonnia"),
                "player": last.get("player"),
                "contact": contact,
            },
        )
        text = {"player": FINAL_PLAYER, "sonnia": FINAL_SONNIA, "tie": FINAL_TIE}[winner]
        await host.speak(throw_text + text.format(sonnia=sonnia, player=player, contact=contact))
        logger.info("Piedra, papel o tijera: final %s (%d-%d)", winner, sonnia, player)
        await host.finish(
            "win" if winner == "player" else "lose", {"winner": winner, "score": self.score}
        )

    async def _finish_cancel(self, reason: str) -> None:
        self._phase = "final"
        await self.host.finish("cancel", {"score": self.score, "reason": reason})

    # -- esperas ------------------------------------------------------------------

    def _track(self, frame: PoseFrame | None = None) -> Person | None:
        """Quién juega ahora (y su marca en la vista en vivo); avisa de que hay alguien.

        Sin ``frame``, la última detección continua (``poses.latest``).
        """
        host = self.host
        if frame is None:
            try:
                frame = host.poses.latest(POSE_MAX_AGE_S)
            except Exception:  # noqa: BLE001
                frame = None
        person = pick_player(frame, self._player_box)
        self._player_box = person.box if person is not None else None
        if self._overlay.player != self._player_box:
            self._overlay = OverlayState(
                player=self._player_box, hand=self._overlay.hand, hand_ok=self._overlay.hand_ok
            )
        if person is not None:
            now = host.now()
            self._player_seen_at = now
            if now - self._touched_at >= TOUCH_EVERY_S:
                self._touched_at = now
                host.touch()
        return person

    async def _pause(self, seconds: float) -> None:
        """Espera ``seconds`` mirando quién juega."""
        host = self.host
        deadline = host.now() + max(0.0, seconds)
        while host.now() < deadline and not self._again:
            self._track()
            await host.sleep(min(TRACK_STEP_S, max(0.0, deadline - host.now())))

    async def _sleep_until(self, when: float) -> None:
        delay = when - self.host.now()
        if delay > 0:
            await self.host.sleep(delay)

    async def _wait_spoken(self, start_s: float, limit_s: float) -> None:
        """Espera a que Sonia cuente lo que se le pidió: que empiece a hablar (como mucho
        ``start_s``) y termine (``SPOKEN_QUIET_S`` callada), con un tope de ``limit_s``."""
        host = self.host
        begin = host.now()
        spoke = False
        while (now := host.now()) - begin < limit_s and not self._again:
            quiet = host.quiet_for()
            if quiet < 0.5:
                spoke = True
            elif (spoke and quiet >= SPOKEN_QUIET_S) or (not spoke and now - begin >= start_s):
                # Ya lo contó, o no empieza a hablar: se sigue.
                return
            self._track()
            await host.sleep(TRACK_STEP_S)

    async def _wait_idle(self) -> None:
        """Espera a que nadie hable (como mucho ``IDLE_WAIT_S``), mirando quién juega."""
        host = self.host
        deadline = host.now() + IDLE_WAIT_S
        while host.now() < deadline and not self._again:
            if await host.wait_idle(0.5):
                return
            self._track()
            await host.sleep(TRACK_STEP_S)

    async def _wait_player(self) -> bool:
        """Espera a que haya alguien delante de la cámara. ``False`` si se cansa y cancela."""
        host = self.host
        begin = host.now()
        hinted = False
        while True:
            # «Otra ronda» desde el panel: la tirada va aunque la cámara no vea a nadie.
            if self._track() is not None or self._again:
                return True
            waited = host.now() - begin
            if waited >= NO_PLAYER_CANCEL_S:
                await host.speak(NO_PLAYER_CANCEL_TEXT)
                await self._finish_cancel("no_player")
                return False
            if waited >= HINT_AFTER_S and not hinted:
                hinted = True
                self._phase = "waiting"
                await host.send("hint", {"text": HINT_NO_PLAYER}, sticky=False)
                await host.speak(NO_PLAYER_TEXT)
            await host.sleep(TRACK_STEP_S)
