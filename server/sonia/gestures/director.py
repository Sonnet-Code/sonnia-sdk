"""Director de gestos: un modelo de texto ligero elige el gesto de cada frase de Sonia.

En el chat de Genies el LLM que escribe la respuesta mete etiquetas de gesto
y su backend las alinea con la voz. GPT-Live habla voz a voz y no escribe
etiquetas, así que aquí un modelo aparte, rápido, lee lo que Sonia va diciendo
(la transcripción de su voz llega casi a la vez que el audio) y elige un gesto
del catálogo que mandó Unity, con la ficha de cada uno. El nombre va a Unity
en un mensaje ``gesture`` con el ``utterance_id`` de la frase que acompaña.

Cuándo se pide (como mucho una petición en vuelo):

- Apertura: al cerrarse el turno del visitante (o llegar un texto escrito), con
  lo que dijo, mientras GPT-Live prepara la respuesta. Va con
  ``utterance_id: null`` y Unity lo lanza con la siguiente frase.
- Por frase: en cada ``speech_start`` no ambiental, en cuanto su texto llega a
  ``GESTURE_TRIGGER_CHARS`` caracteres o pasan ``GESTURE_TRIGGER_S`` segundos.

Las reglas de frecuencia de Genies se piden al modelo y además se aplican en
código: un gesto no empieza hasta que acaba el núcleo del anterior, uno por
frase como mucho, sin repetir uno reciente, pocos ``Uncommon`` y menos ``Rare``,
y lo que llega tarde se tira. Nada de lo que pase con el modelo tumba el
motor: un fallo se registra y, si está activado, se pone un gesto de relleno.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from typing import Any, Protocol

from sonia.config import GestureSettings
from sonia.gestures.catalog import DEFAULT_CORE_S, GestureCatalog
from sonia.gestures.prompt import (
    Cooldowns,
    build_request_message,
    build_system_prompt,
    build_user_message,
    catalog_text,
    parse_choice,
)
from sonia.llm.client import Completion
from sonia.llm.messages import system, user_text
from sonia.types import Message
from sonia.ws import protocol as p

__all__ = ["GestureDirector"]

logger = logging.getLogger(__name__)

#: Unity guarda un gesto de apertura (``utterance_id: null``) como mucho esto.
OPENING_HOLD_S = 4.0

#: Tiempo mínimo que tiene que quedarle al modelo antes del plazo de su frase
#: para que merezca la pena pedirle el gesto.
MIN_REQUEST_S = 0.3

#: La espera al modelo acaba esto antes del plazo de la frase, para que aún
#: llegue a tiempo el gesto de relleno si no contesta.
FALLBACK_MARGIN_S = 0.1

#: Gestos recientes que se le cuentan al modelo, y hasta cuántos segundos atrás.
RECENT_SHOWN = 5
RECENT_WINDOW_S = 300.0

#: Frases ya dichas de la respuesta en curso que se recuerdan para el contexto.
SAID_KEPT = 6

#: Peso de cada frecuencia al sortear un gesto de relleno.
FILLER_WEIGHTS = {"Standard": 6.0, "Uncommon": 2.0, "Rare": 1.0}

#: Manda un mensaje JSON a Unity (``hub.broadcast_json``).
SendJson = Callable[[dict[str, Any]], Awaitable[None]]


class CompletingLLM(Protocol):
    """Lo que el director usa del cliente del modelo (``LLMClient.complete``)."""

    async def complete(self, messages: list[Message]) -> Completion: ...


@dataclass(slots=True)
class _Utterance:
    """Una frase no ambiental de Sonia, desde su ``speech_start``."""

    uid: int
    started_at: float
    #: Número de frase dentro de la respuesta (desde 1).
    index: int
    text: str = ""
    open: bool = True
    #: Ya lleva gesto: el suyo o el de apertura.
    gestured: bool = False
    #: Ya se pidió su gesto (o se decidió no pedirlo).
    requested: bool = False
    #: Ya se cumplió el disparador (texto suficiente o tiempo).
    triggered: bool = False
    timer: asyncio.TimerHandle | None = None


@dataclass(slots=True)
class _Played:
    name: str
    frequency: str
    at: float


@dataclass(slots=True)
class _Stats:
    requests: int = 0
    gestures: int = 0
    fallbacks: int = 0
    none: int = 0
    unknown: int = 0
    vetoed: int = 0
    late: int = 0
    failures: int = 0
    answered: int = 0
    latency_total_s: float = 0.0


@dataclass(frozen=True, slots=True)
class RequestedGesture:
    """El gesto que eligió el modelo para lo que pidió el visitante."""

    #: Nombre exacto del catálogo, o ``None`` si ninguno lo hace (o falló el modelo).
    name: str | None
    #: Por qué no hay gesto cuando falló el modelo (vacío si contestó).
    error: str = ""
    latency_s: float = 0.0


class GestureDirector:
    """Elige y manda a Unity los gestos de hablar. Todo entra por el constructor.

    El motor le cuenta lo que pasa con métodos síncronos y baratos (``on_*``);
    las peticiones al modelo corren en una tarea aparte y nunca bloquean el
    bucle. Sin catálogo, sin sesión, sin Unity conectado o con
    ``GESTURES_ENABLED=false`` no pide nada.
    """

    def __init__(
        self,
        settings: GestureSettings,
        llm: CompletingLLM | None,
        send: SendJson,
        *,
        has_clients: Callable[[], bool] | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._settings = settings
        self._llm = llm
        self._send = send
        self._has_clients = has_clients
        self._rng = rng or random.Random()
        self._catalog = GestureCatalog([])
        #: Mensaje de sistema: idéntico en todas las llamadas con el mismo catálogo.
        #: El catálogo ya montado para el prompt (``{gestures}``), uno por catálogo.
        self._gestures = ""
        self._live = False

        # Conversación.
        self._user_text = ""
        self._said: list[str] = []
        self._phrase_index = 0
        self._utterance: _Utterance | None = None
        #: Cuándo empezó la última frase no ambiental.
        self._last_speech_at = float("-inf")

        # Petición en vuelo y gestos.
        self._task: asyncio.Task[None] | None = None
        #: Frase a la que va la petición en vuelo (``None``: la de apertura).
        self._task_target: _Utterance | None = None
        #: Gesto de apertura mandado con ``utterance_id: null`` y cuándo: lo que
        #: Unity tiene guardado para la próxima frase (gana el último).
        self._opening: tuple[str, float] | None = None
        #: Antes de esto no empieza otro gesto (núcleo del anterior más el margen).
        self._busy_until = 0.0
        self._history: list[_Played] = []
        self._stats = _Stats()

    # -- propiedades ----------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._settings.enabled and self._llm is not None

    @property
    def catalog(self) -> GestureCatalog:
        return self._catalog

    @property
    def system_prompt(self) -> str:
        """El mensaje de sistema, con el texto en uso (el de la app o el de la nube) en cada
        petición: un cambio en el panel vale desde la siguiente."""
        if not len(self._catalog):
            return ""
        return build_system_prompt(self._catalog, self._gestures)

    def _ready(self) -> bool:
        if not self.enabled or not self._live or not len(self._catalog):
            return False
        return self._has_clients is None or self._has_clients()

    # -- gestos pedidos por el visitante -----------------------------------------

    @property
    def can_choose(self) -> bool:
        """¿Puede elegir un gesto que pida el visitante (modelo y catálogo de Unity)?"""
        return self.enabled and len(self._catalog) > 0

    async def choose_requested(self, request: str) -> RequestedGesture:
        """El gesto del catálogo que hace lo que pide el visitante («tocarse un ojo»).

        Lo decide el mismo modelo que los gestos al hablar, con el mismo mensaje
        de sistema (las fichas de Genies, ya en su caché) y otra pregunta: así
        las fichas no van en el contexto de GPT-Live ni del backend. No manda
        nada a Unity; quien lo lance avisa con :meth:`note_requested`.
        """
        if not self.can_choose:
            return RequestedGesture(None, "sin modelo de gestos o sin catálogo de Unity")
        assert self._llm is not None
        messages = [system(self.system_prompt), user_text(build_request_message(request))]
        started = time.monotonic()
        timeout = self._settings.timeout_s
        try:
            async with asyncio.timeout(max(0.05, timeout)):
                completion = await self._llm.complete(messages)
        except TimeoutError:
            return RequestedGesture(None, f"no contestó en {timeout:.1f} s", timeout)
        except Exception as exc:  # noqa: BLE001 - un fallo del modelo no tumba nada
            return RequestedGesture(None, str(exc) or type(exc).__name__)
        latency = time.monotonic() - started
        name, understood = parse_choice(completion.content, self._catalog)
        if not understood:
            logger.info(
                "Respuesta del modelo de gestos que no es un gesto: %r", completion.content[:120]
            )
        logger.info(
            "Gesto pedido %s -> %s (%.2f s%s)",
            f"«{' '.join(request.split())[:80]}»",
            name or "ninguno",
            latency,
            _usage(completion),
        )
        return RequestedGesture(name, latency_s=latency)

    def note_requested(self, name: str) -> None:
        """Se lanzó un gesto pedido: cuenta como hecho para no repetirlo ni pisarlo al hablar."""
        self._played(name, time.monotonic())

    # -- lo que cuenta el motor -------------------------------------------------

    def on_catalog(self, msg: dict[str, Any]) -> None:
        """Catálogo nuevo (``gesture_catalog`` de Unity): reemplaza al anterior."""
        catalog = GestureCatalog.from_message(msg)
        self._catalog = catalog
        self._gestures = catalog_text(catalog)
        logger.info(
            "Catálogo de gestos de %s: %d gestos (%d de relleno)%s",
            catalog.character or "Unity",
            len(catalog),
            len(catalog.fillers()),
            "" if self.enabled else "; el director de gestos está apagado",
        )

    def on_session(self, live: bool) -> None:
        """Se abrió o se cerró la sesión de GPT-Live. Al cerrarse se cancela lo pendiente."""
        self._live = live
        if not live:
            self._cancel_task()
            self._close_utterance()
            self._utterance = None
            self._last_speech_at = float("-inf")
            self._opening = None
            self._busy_until = 0.0
            self._user_text = ""
            self._said = []
            self._phrase_index = 0

    def on_user_turn(self, text: str, *, answering: bool = False) -> None:
        """El visitante cerró su turno (o escribió ``text``): se pide el gesto de apertura.

        Con ``answering`` Sonia ya está contestando: solo se actualiza el
        contexto y siguen los gestos por frase.
        """
        text = text.strip()
        if not text:
            return
        self._user_text = text
        if answering:
            return
        self._said = []
        self._phrase_index = 0
        # Lo que quedara por llegar de la respuesta anterior ya no vale. Una
        # apertura ya mandada se queda: Unity la sigue guardando.
        self._cancel_task()
        if self._ready():
            self._start(self._request(None), None)

    def on_speech_start(
        self, uid: int, *, ambient: bool, text: str = "", user_text: str | None = None
    ) -> None:
        """Empieza una frase de Sonia. Las ambientales (stand, saludos) no llevan gesto.

        ``user_text`` es lo que va diciendo el visitante si su turno sigue
        abierto: Sonia empezó a contestar antes de que se cerrara.
        """
        if ambient:
            return
        now = time.monotonic()
        self._close_utterance()
        if user_text is not None and user_text.strip():
            self._user_text = user_text.strip()
            self._said = []
            self._phrase_index = 0
        self._phrase_index += 1
        utterance = _Utterance(uid, now, self._phrase_index, text=text)
        self._utterance = utterance
        self._last_speech_at = now
        opening, self._opening = self._opening, None
        if not self._ready():
            return
        if opening is not None and now - opening[1] <= OPENING_HOLD_S:
            # Unity lanza ahora el gesto de apertura que tenía guardado.
            utterance.gestured = True
            self._played(opening[0], now)
            logger.debug("Gesto de apertura %s con la frase %d", opening[0], uid)
            return
        utterance.timer = asyncio.get_running_loop().call_later(
            max(0.0, self._settings.trigger_s), self._on_trigger, utterance
        )
        if len(text) >= self._settings.trigger_chars:
            self._on_trigger(utterance)

    def on_assistant_text(self, uid: int, text: str) -> None:
        """Llega más transcripción de la frase ``uid`` (``text`` es la frase entera hasta ahora)."""
        utterance = self._utterance
        if utterance is None or utterance.uid != uid or not utterance.open:
            return
        utterance.text = text
        if not utterance.triggered and len(text) >= self._settings.trigger_chars:
            self._on_trigger(utterance)

    def on_speech_end(self, uid: int, text: str = "") -> None:
        """Terminó la frase ``uid``: su gesto ya no se pide y, si estaba en vuelo, se tira."""
        utterance = self._utterance
        if utterance is None or utterance.uid != uid:
            return
        if text:
            utterance.text = text
        self._close_utterance()

    def on_interrupt(self) -> None:
        """Interrupción: Unity corta voz y gesto; se cancela todo lo pendiente."""
        self._cancel_task()
        self._opening = None
        self._close_utterance()
        self._busy_until = min(self._busy_until, time.monotonic())

    def on_state(self, state: str) -> None:
        """Unity corta el gesto al salir de ``speaking``: el siguiente puede empezar ya."""
        if str(state) != "speaking":
            self._busy_until = min(self._busy_until, time.monotonic())

    def close(self) -> None:
        """Cancela la petición en vuelo (al apagar el motor)."""
        self._cancel_task()
        self._close_utterance()

    def snapshot(self) -> dict[str, Any]:
        """Contadores para el estado del panel, en tipos JSON."""
        stats = self._stats
        return {
            "enabled": self.enabled,
            "character": self._catalog.character,
            "catalog": len(self._catalog),
            "requests": stats.requests,
            "gestures": stats.gestures,
            "fallbacks": stats.fallbacks,
            "none": stats.none,
            "unknown": stats.unknown,
            "vetoed": stats.vetoed,
            "late": stats.late,
            "failures": stats.failures,
            "avg_latency_s": (
                round(stats.latency_total_s / stats.answered, 2) if stats.answered else None
            ),
            "last": self._history[-1].name if self._history else None,
        }

    # -- peticiones ---------------------------------------------------------------

    def _on_trigger(self, utterance: _Utterance) -> None:
        utterance.triggered = True
        self._maybe_request(utterance)

    def _maybe_request(self, utterance: _Utterance) -> None:
        """Pide el gesto de la frase si toca y si todavía puede llegar a tiempo."""
        if (
            utterance is not self._utterance
            or not utterance.open
            or utterance.gestured
            or utterance.requested
            or not self._ready()
        ):
            return
        if self._task is not None and not self._task.done():
            return  # una en vuelo; al terminar se vuelve a mirar
        if utterance.timer is not None:
            utterance.timer.cancel()
            utterance.timer = None
        utterance.requested = True
        now = time.monotonic()
        deadline = utterance.started_at + self._settings.max_delay_s
        if max(now, self._busy_until) > deadline - MIN_REQUEST_S:
            logger.debug(
                "Frase %d sin gesto: el anterior sigue en su núcleo o ya no da tiempo",
                utterance.uid,
            )
            return
        self._start(self._request(utterance), utterance)

    def _start(self, coro: Coroutine[Any, Any, None], target: _Utterance | None) -> None:
        task = asyncio.create_task(coro, name="sonia-gesture")
        self._task = task
        self._task_target = target
        task.add_done_callback(self._task_done)

    def _task_done(self, task: asyncio.Task[None]) -> None:
        if self._task is task:
            self._task = None
            self._task_target = None
        if not task.cancelled() and task.exception() is not None:
            logger.error("El director de gestos falló: %r", task.exception())
        # Una frase que esperaba a que quedara libre la petición.
        utterance = self._utterance
        if utterance is not None and utterance.triggered:
            self._maybe_request(utterance)

    def _cancel_task(self) -> None:
        task, self._task = self._task, None
        self._task_target = None
        if task is not None and not task.done():
            task.cancel()

    async def _request(self, utterance: _Utterance | None) -> None:
        """Pide el gesto al modelo y lo manda a Unity si sigue valiendo. ``None``: apertura."""
        assert self._llm is not None
        settings = self._settings
        started = time.monotonic()
        timeout = settings.timeout_s
        if utterance is not None:
            # Lo que llegue después del plazo de la frase se tiraría igual.
            deadline = utterance.started_at + settings.max_delay_s - FALLBACK_MARGIN_S
            timeout = min(timeout, deadline - started)
        messages = [system(self.system_prompt), user_text(self._user_message(utterance, started))]
        self._stats.requests += 1
        completion: Completion | None = None
        error = ""
        try:
            async with asyncio.timeout(max(0.05, timeout)):
                completion = await self._llm.complete(messages)
        except TimeoutError:
            error = f"no contestó en {timeout:.1f} s"
        except Exception as exc:  # noqa: BLE001 - un fallo del modelo no tumba nada
            error = str(exc) or type(exc).__name__
        now = time.monotonic()
        latency = now - started
        if (
            completion is not None
            and not completion.content.strip()
            and completion.finish_reason == "length"
        ):
            # Se gastó el tope razonando y no llegó a contestar: es un fallo, no «ninguno».
            error = (
                f"agotó {completion.completion_tokens or 'los'} tokens sin contestar; "
                "baja GESTURE_REASONING_EFFORT o sube GESTURE_MAX_TOKENS"
            )
            completion = None

        target = utterance
        if utterance is None and self._last_speech_at >= started:
            # Sonia ya empezó a contestar: la apertura es el gesto de esa frase,
            # o de nada si esa frase ya terminó.
            current = self._utterance
            if current is None or not current.open or current.started_at < started:
                self._stats.late += 1
                logger.info("Gesto de apertura descartado: la primera frase ya terminó")
                return
            target = current
            current.requested = True
            if current.timer is not None:
                current.timer.cancel()
                current.timer = None
        where = _where(target)

        fallback = False
        if completion is None:
            self._stats.failures += 1
            name = self._filler(now) if settings.fallback else None
            if name is None:
                logger.warning("Sin gesto (%s): el modelo falló (%s)", where, error)
                return
            fallback = True
            logger.warning("El modelo de gestos falló (%s); relleno %s (%s)", error, name, where)
        else:
            self._stats.answered += 1
            self._stats.latency_total_s += latency
            name, understood = parse_choice(completion.content, self._catalog)
            if not understood:
                self._stats.unknown += 1
                logger.info(
                    "Respuesta del modelo de gestos que no es un gesto (%s): %r",
                    where,
                    completion.content[:120],
                )
            gesture = self._catalog.get(name) if name is not None else None
            if gesture is not None and self._cooldowns(now).blocks(gesture):
                self._stats.vetoed += 1
                logger.info("Gesto %s vetado por frecuencia (%s)", name, where)
                name = None
            if name is None:
                self._stats.none += 1
                logger.info(
                    "Sin gesto (%s, %.2f s%s)%s",
                    where,
                    latency,
                    _usage(completion),
                    _phrase(target),
                )
                return
        await self._deliver(name, target, latency, completion, fallback=fallback)

    async def _deliver(
        self,
        name: str,
        target: _Utterance | None,
        latency: float,
        completion: Completion | None,
        *,
        fallback: bool,
    ) -> None:
        """Manda el gesto a Unity si su frase sigue sonando y aún llega a tiempo."""
        if not self._ready():
            return
        now = time.monotonic()
        source = "relleno" if fallback else f"{latency:.2f} s{_usage(completion)}"
        if target is None:
            # Apertura con nadie hablando todavía: Unity lo lanza con la próxima frase.
            await self._send(p.msg_gesture(name, None))
            self._opening = (name, now)
            self._count_sent(fallback)
            logger.info("Gesto de apertura %s (%s)", name, source)
            return
        deadline = target.started_at + self._settings.max_delay_s
        start_at = max(now, self._busy_until)
        if target.gestured:
            # Ya lleva el de apertura que tenía guardado Unity.
            self._stats.late += 1
            return
        if not self._still_valid(target) or start_at > deadline:
            self._stats.late += 1
            logger.info(
                "Gesto %s descartado (%s): llegaría %.1f s después de empezar su frase%s",
                name,
                _where(target),
                start_at - target.started_at,
                "" if target.open else ", que ya terminó",
            )
            return
        if start_at > now:
            # Espera a que acabe el núcleo del gesto anterior.
            await asyncio.sleep(start_at - now)
            if not self._still_valid(target) or target.gestured:
                self._stats.late += 1
                return
        await self._send(p.msg_gesture(name, target.uid))
        target.gestured = True
        self._played(name, time.monotonic())
        self._count_sent(fallback)
        logger.info("Gesto %s (%s, %s)%s", name, _where(target), source, _phrase(target))

    def _still_valid(self, target: _Utterance) -> bool:
        return target.open and target is self._utterance and self._ready()

    def _count_sent(self, fallback: bool) -> None:
        self._stats.gestures += 1
        if fallback:
            self._stats.fallbacks += 1

    # -- frecuencia -------------------------------------------------------------

    def _played(self, name: str, at: float) -> None:
        gesture = self._catalog.get(name)
        self._history.append(_Played(name, gesture.frequency if gesture else "Standard", at))
        core = gesture.core_s if gesture is not None else DEFAULT_CORE_S
        self._busy_until = at + core + self._settings.min_gap_s
        settings = self._settings
        keep = max(settings.repeat_s, settings.uncommon_s, settings.rare_s, RECENT_WINDOW_S)
        self._history = [h for h in self._history if at - h.at <= keep]

    def _cooldowns(self, now: float) -> Cooldowns:
        """Lo que ahora no se puede usar: Rare, Uncommon y repetidos recientes."""
        settings = self._settings
        rare_left = uncommon_left = 0.0
        repeated: list[str] = []
        for played in reversed(self._history):
            ago = now - played.at
            if played.frequency == "Rare":
                rare_left = max(rare_left, settings.rare_s - ago)
            elif played.frequency == "Uncommon":
                uncommon_left = max(uncommon_left, settings.uncommon_s - ago)
            if ago < settings.repeat_s and played.name not in repeated:
                repeated.append(played.name)
        return Cooldowns(max(0.0, rare_left), max(0.0, uncommon_left), tuple(repeated))

    def _filler(self, now: float) -> str | None:
        """Un gesto de relleno al azar (ponderado por frecuencia), sin repetir el último."""
        last = self._history[-1].name if self._history else ""
        fillers = [g for g in self._catalog.fillers() if g.name != last]
        cooldowns = self._cooldowns(now)
        pool = [g for g in fillers if not cooldowns.blocks(g)]
        if not pool:
            pool = [g for g in fillers if g.frequency == "Standard"]
        if not pool:
            return None
        weights = [FILLER_WEIGHTS.get(g.frequency, 1.0) for g in pool]
        return self._rng.choices(pool, weights=weights)[0].name

    def _user_message(self, utterance: _Utterance | None, now: float) -> str:
        recent = [
            (played.name, now - played.at)
            for played in reversed(self._history)
            if now - played.at <= RECENT_WINDOW_S
        ][:RECENT_SHOWN]
        return build_user_message(
            opening=utterance is None,
            user_text=self._user_text,
            said=self._said,
            phrase_text=utterance.text if utterance is not None else "",
            phrase_index=utterance.index if utterance is not None else 0,
            phrase_age_s=now - utterance.started_at if utterance is not None else 0.0,
            recent=recent,
            cooldowns=self._cooldowns(now),
        )

    def _close_utterance(self) -> None:
        """La frase en curso terminó: su gesto ya no se pide y, si estaba en vuelo, se tira."""
        utterance = self._utterance
        if utterance is None or not utterance.open:
            return
        utterance.open = False
        if self._task_target is utterance:
            self._stats.late += 1
            logger.info("Gesto de la frase %d descartado: la frase terminó antes", utterance.uid)
            self._cancel_task()
        if utterance.timer is not None:
            utterance.timer.cancel()
            utterance.timer = None
        if utterance.text:
            self._said = [*self._said, utterance.text][-SAID_KEPT:]


def _where(target: _Utterance | None) -> str:
    return "apertura" if target is None else f"frase {target.uid}"


def _phrase(target: _Utterance | None) -> str:
    if target is None or not target.text:
        return ""
    text = target.text if len(target.text) <= 60 else target.text[:59] + "…"
    return f": {text}"


def _usage(completion: Completion | None) -> str:
    """Tokens de la petición para el registro, si el servidor los dio."""
    if completion is None or completion.prompt_tokens is None:
        return ""
    cached = f", {completion.cached_tokens} en caché" if completion.cached_tokens else ""
    out = (
        f" + {completion.completion_tokens} de salida"
        if completion.completion_tokens is not None
        else ""
    )
    if completion.reasoning_tokens:
        out += f" ({completion.reasoning_tokens} razonando)"
    return f", {completion.prompt_tokens} tokens{cached}{out}"
