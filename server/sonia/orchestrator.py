"""Orquestador: la máquina de estados que une voz, visión, modelo y avatar.

Un único bucle asyncio (:meth:`Orchestrator.run`) consume una cola de eventos de
turno. Por esa cola entran, sin distinción, los eventos del detector de voz
(`SpeechStarted`, `Utterance`, `SpeechDiscarded`) y los turnos de texto que
llegan por el WebSocket o por la consola (`TextTurn`). El orquestador no sabe si
un texto vino del micrófono o del teclado: todo sigue el mismo camino.

Estados (se difunden a Unity con ``state``)::

    idle ──SpeechStarted──► listening ──Utterance──► thinking ──1ª frase──► speaking
      ▲                        │                        │                     │
      └────SpeechDiscarded─────┘                        └──── fin del turno ──┘
                                                                   (playback_done)

Un turno del usuario corre en una tarea propia con dos hijos: el bucle del
modelo (streaming → frases → cola de síntesis; acciones si el modelo las pide) y
el bucle de síntesis (cola → TTS → frames binarios, visemas, envolvente). Al
cancelar el turno (barge-in o ``interrupt``) se cancelan los dos, se vacía la
cola y se envía ``stop_speaking``.

Regla de oro: el bucle principal nunca muere por un error de una etapa. Un fallo
del modelo o del TTS se registra, se difunde como ``error``, se pide disculpas
en voz si se puede y se vuelve a ``idle``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from sonia.actions.gallery import Gallery
from sonia.actions.registry import ActionRegistry
from sonia.audio.vad import SpeechDiscarded, SpeechStarted, TurnEvent
from sonia.config import Settings
from sonia.llm.conversation import Conversation
from sonia.llm.messages import (
    assistant_text,
    assistant_tool_calls,
    tool_result,
    user_text,
    user_with_image,
)
from sonia.llm.prompt_tools import PromptToolParser, render_tools_prompt
from sonia.persona import build_system_prompt, describe_stack
from sonia.sentences import SentenceSplitter
from sonia.showcase import Showcase, ShowcaseBit
from sonia.tts.base import aclosing
from sonia.types import (
    ActionContext,
    ActionResult,
    AssistantState,
    AudioChunk,
    AvatarLink,
    CameraSource,
    Frame,
    LLMEvent,
    Message,
    SpeechToText,
    TextDelta,
    TextToSpeech,
    ToolCall,
    ToolCallsEvent,
    TurnDone,
    Utterance,
)
from sonia.visemes import envelope_for, visemes_for
from sonia.vision.policy import VisionPolicy
from sonia.ws import protocol as p
from sonia.ws.hub import MessageCallback

__all__ = [
    "APOLOGY_TEXT",
    "HubLike",
    "Interrupt",
    "LLMLike",
    "Orchestrator",
    "TextTurn",
    "TurnInput",
]

logger = logging.getLogger(__name__)


def _log_stage_failure(msg: str, *args: Any) -> None:
    """Registra el fallo recuperable de una etapa sin ensuciar la consola.

    Un modelo caído o un TTS que no responde son incidencias esperadas en el
    stand y el orquestador ya se recupera de ellas: basta una línea legible.
    La traza completa solo aparece con ``LOG_LEVEL=DEBUG``, cuando se está
    depurando de verdad.
    """
    logger.error(msg, *args, exc_info=logger.isEnabledFor(logging.DEBUG))


#: Lo que dice Sonia cuando el modelo o el TTS fallan a mitad de un turno.
APOLOGY_TEXT = "Perdona, se me fue el hilo. ¿Me lo repites?"

#: Texto del mensaje de usuario que acompaña a la imagen devuelta por ``look``.
LOOK_IMAGE_TEXT = "[Imagen de la cámara pedida por la acción look]"

#: Segundos de audio que se permite adelantar al tiempo real entre frases.
#: Unity bufferiza, pero enviarle el turno entero de golpe gasta memoria y deja
#: la estimación de ``playback_done`` sin sentido. Dentro de una frase no se
#: frena (ver :meth:`Orchestrator._speak_sentence`), así que el adelanto real
#: puede llegar a este margen más lo que dure la última frase enviada.
MAX_AUDIO_LEAD_S = 2.0

#: Margen que se suma a la duración estimada al esperar ``playback_done``.
PLAYBACK_GRACE_S = 1.0

#: Cuánto se espera a la cámara antes de mandar el turno sin imagen.
FRAME_WAIT_S = 1.5

#: Una captura pendiente más vieja que esto se descarta y se repite.
FRAME_MAX_AGE_S = 5.0

#: Intervalo de la envolvente de amplitud que se envía a Unity.
ENVELOPE_INTERVAL_MS = 20

#: Periodo del bucle principal cuando no hay eventos (reinicio por inactividad).
DEFAULT_TICK_S = 1.0


# ---------------------------------------------------------------------------
# Eventos de entrada
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class TextTurn:
    """Turno de texto ya transcrito (``text_input`` del WS o la consola)."""

    text: str
    at: float = 0.0


@dataclass(slots=True)
class Interrupt:
    """Interrupción explícita (mensaje ``interrupt`` de Unity)."""

    reason: str = "interrupted"


#: Todo lo que puede entrar por la cola del orquestador.
TurnInput = SpeechStarted | Utterance | SpeechDiscarded | TextTurn | Interrupt


# ---------------------------------------------------------------------------
# Interfaces que el orquestador necesita de sus colaboradores
# ---------------------------------------------------------------------------


class HubLike(AvatarLink, Protocol):
    """Lo que el orquestador usa del hub WebSocket (y las acciones del avatar)."""

    def on(self, type: str, callback: MessageCallback) -> None: ...
    async def broadcast_json(self, msg: dict[str, Any]) -> None: ...
    async def send_audio(self, utterance_id: int, chunk: AudioChunk) -> None: ...


class LLMLike(Protocol):
    """Lo que el orquestador usa del cliente del modelo."""

    def stream(
        self, messages: list[Message], tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[LLMEvent]: ...


# ---------------------------------------------------------------------------
# Estado interno de un turno
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _Turn:
    """Lo que comparten el bucle del modelo y el de síntesis durante un turno."""

    #: Frases pendientes de sintetizar; ``None`` cierra la cola.
    sentences: asyncio.Queue[str | None] = field(default_factory=asyncio.Queue)
    #: Frases cuyo ``speech_start`` ya se envió y aún no están en el historial.
    spoken: list[str] = field(default_factory=list)
    #: Texto completo de la última ronda con texto (se guarda al terminar).
    final_text: str = ""
    #: Frases encoladas en la ronda actual (para el historial si el modelo falla).
    round_sentences: list[str] = field(default_factory=list)
    #: Estimación de cuándo Unity termina de reproducir lo enviado hasta ahora.
    playback_end_at: float = 0.0
    #: Último ``utterance_id`` de este turno (para esperar su ``playback_done``).
    last_utterance_id: int | None = None


# ---------------------------------------------------------------------------
# Orquestador
# ---------------------------------------------------------------------------


class Orchestrator:
    """Máquina de estados asincrónica de Sonia.

    Todas las dependencias entran por el constructor para que los tests puedan
    usar un STT falso, un TTS falso, un cliente de modelo con ``MockTransport``,
    una cámara falsa y un hub real en un puerto libre.

    ``on_speaking_changed`` recibe ``True`` al entrar en ``speaking`` y ``False``
    al salir; se usa para avisar al detector de turnos (``set_speaking``) sin
    acoplar el orquestador a la capa de audio.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        stt: SpeechToText,
        llm: LLMLike,
        tts: TextToSpeech,
        hub: HubLike,
        camera: CameraSource | None = None,
        vision_policy: VisionPolicy | None = None,
        registry: ActionRegistry | None = None,
        system_prompt: str | None = None,
        on_speaking_changed: Callable[[bool], None] | None = None,
        max_audio_lead_s: float = MAX_AUDIO_LEAD_S,
        tick_s: float = DEFAULT_TICK_S,
        showcase: Showcase | None = None,
    ) -> None:
        self._settings = settings
        self._stt = stt
        self._llm = llm
        self._tts = tts
        self._hub = hub
        self._camera = camera
        self._policy = vision_policy or VisionPolicy(settings.vision, settings.llm.supports_vision)
        self._registry = registry
        self._base_prompt = system_prompt
        self._on_speaking_changed = on_speaking_changed
        self._max_lead = max(0.0, max_audio_lead_s)
        self._tick = max(0.01, tick_s)

        self._tool_mode = settings.llm.tool_mode
        self._tools: list[dict[str, Any]] | None = None
        if self._tool_mode == "native" and registry is not None and len(registry) > 0:
            self._tools = registry.to_openai_tools()

        self._conversation = Conversation(self._build_system_prompt(), settings.llm.history_turns)
        self._queue: asyncio.Queue[TurnInput] = asyncio.Queue()
        self._state = AssistantState.IDLE
        self._turn_task: asyncio.Task[None] | None = None
        self._frame_task: asyncio.Task[Frame | None] | None = None
        self._frame_task_at = 0.0
        self._last_frame: Frame | None = None
        self._utterance_counter = 0
        self._playback_done_id = 0
        self._playback_event = asyncio.Event()
        #: Se activa cuando no hay eventos pendientes ni turno en curso.
        self._idle_event = asyncio.Event()
        self._idle_event.set()

        # Animación de stand: frases y bailes cantados mientras no hay nadie.
        show = settings.showcase
        if showcase is None and show.enabled:
            showcase = Showcase.from_dir(
                settings.showcase_dir,
                dance_chance=show.dance_chance,
                gesture_chance=show.gesture_chance,
            )
        self._showcase = (
            showcase if (showcase is not None and showcase.enabled and show.enabled) else None
        )
        self._ambient_task: asyncio.Task[None] | None = None
        self._next_showcase_at = time.monotonic() + max(0.0, show.first_delay_seconds)
        self._last_activity = time.monotonic()

        hub.on(p.MSG_INTERRUPT, self._on_ws_interrupt)
        hub.on(p.MSG_PLAYBACK_DONE, self._on_ws_playback_done)
        hub.on(p.MSG_TEXT_INPUT, self._on_ws_text_input)
        # Si la cámara la sirve Unity, los frames llegan por el mismo WebSocket.
        on_frame = getattr(camera, "on_frame", None)
        if callable(on_frame):
            hub.on(p.MSG_CAMERA_FRAME, lambda msg: self._on_ws_camera_frame(on_frame, msg))

    # -- propiedades --------------------------------------------------------

    @property
    def state(self) -> AssistantState:
        return self._state

    @property
    def conversation(self) -> Conversation:
        return self._conversation

    @property
    def last_frame(self) -> Frame | None:
        return self._last_frame

    @property
    def turn_active(self) -> bool:
        """¿Hay un turno del usuario en curso (pensando o hablando)?"""
        return self._turn_task is not None and not self._turn_task.done()

    @property
    def vision_enabled(self) -> bool:
        return self._policy.enabled

    # -- entrada de eventos -------------------------------------------------

    async def submit(self, event: TurnInput) -> None:
        """Encola un evento de turno (detector de voz, texto o interrupción)."""
        self.submit_nowait(event)

    def submit_nowait(self, event: TurnInput) -> None:
        self._idle_event.clear()
        self._queue.put_nowait(event)

    async def wait_idle(self, limit_s: float | None = None) -> bool:
        """Espera a que no queden eventos pendientes ni turno en curso.

        Devuelve ``False`` si venció ``limit_s`` antes. Útil para que ``sonia
        chat`` deje terminar la respuesta en curso antes de salir.
        """
        try:
            await asyncio.wait_for(self._idle_event.wait(), timeout=limit_s)
        except TimeoutError:
            return False
        return True

    def _refresh_idle_event(self, *_: object) -> None:
        if self._queue.empty() and not self.turn_active:
            self._idle_event.set()

    async def submit_text(self, text: str) -> None:
        """Atajo para un turno de texto."""
        await self.submit(TextTurn(text=text, at=time.monotonic()))

    async def feed(self, events: AsyncIterator[TurnEvent]) -> None:
        """Vuelca un flujo de eventos del detector de turnos en la cola."""
        async for event in events:
            await self.submit(event)

    def notify_playback_done(self, utterance_id: int) -> None:
        """Unity (o el reproductor local) terminó de reproducir ``utterance_id``."""
        if utterance_id > self._playback_done_id:
            self._playback_done_id = utterance_id
        self._playback_event.set()

    # -- callbacks del hub --------------------------------------------------

    def _on_ws_interrupt(self, msg: dict[str, Any]) -> None:
        self.submit_nowait(Interrupt())

    def _on_ws_playback_done(self, msg: dict[str, Any]) -> None:
        utterance_id = msg.get("utterance_id")
        if isinstance(utterance_id, int) and not isinstance(utterance_id, bool):
            self.notify_playback_done(utterance_id)

    def _on_ws_text_input(self, msg: dict[str, Any]) -> None:
        text = msg.get("text")
        if isinstance(text, str) and text.strip():
            self.submit_nowait(TextTurn(text=text, at=time.monotonic()))

    @staticmethod
    def _on_ws_camera_frame(on_frame: Callable[..., Any], msg: dict[str, Any]) -> None:
        data = msg.get("data_base64")
        if isinstance(data, str) and data:
            on_frame(str(msg.get("mime") or "image/jpeg"), data)

    # -- bucle principal ----------------------------------------------------

    async def run(self) -> None:
        """Bucle principal. Solo termina al cancelar la tarea."""
        logger.info(
            "Orquestador en marcha (acciones: %s, visión: %s, barge-in: %s)",
            self._tool_mode,
            "sí" if self._policy.enabled else "no",
            "sí" if self._settings.audio.barge_in else "no",
        )
        await self._hub.broadcast_json(p.msg_state(self._state))
        try:
            while True:
                try:
                    event = await asyncio.wait_for(self._queue.get(), timeout=self._tick)
                except TimeoutError:
                    await self._maybe_reset_idle()
                    await self._maybe_showcase()
                    continue
                try:
                    await self._handle_event(event)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Error procesando %s; se vuelve a idle", type(event).__name__)
                    with contextlib.suppress(Exception):
                        await self._cancel_turn("error")
                        await self._set_state(AssistantState.IDLE)
                finally:
                    self._refresh_idle_event()
        finally:
            await self._shutdown()

    async def _shutdown(self) -> None:
        """Cancela lo que quede en marcha al apagar el orquestador."""
        with contextlib.suppress(Exception):
            await self._cancel_ambient("shutdown")
            await self._cancel_turn("shutdown")
        self._drop_frame_task()

    async def _handle_event(self, event: TurnInput) -> None:
        match event:
            case SpeechStarted():
                await self._on_speech_started()
            case SpeechDiscarded():
                await self._on_speech_discarded()
            case Utterance() | TextTurn():
                await self._start_turn(event)
            case Interrupt():
                await self._on_interrupt(event.reason)

    async def _on_speech_started(self) -> None:
        self._touch()
        await self._cancel_ambient("interrupted")
        if self._state is AssistantState.SPEAKING:
            if not self._settings.audio.barge_in:
                return
            logger.info("Barge-in: el usuario habla mientras Sonia habla")
            await self._cancel_turn("interrupted")
            await self._set_state(AssistantState.LISTENING)
        elif self._state is AssistantState.IDLE:
            await self._set_state(AssistantState.LISTENING)
        # En ``thinking`` no se cambia de estado: si el habla resulta ser un
        # turno de verdad, la ``Utterance`` que llegue cancelará el turno.
        self._maybe_capture(turn_start=True)

    async def _on_speech_discarded(self) -> None:
        """El habla era ruido: se deshace lo que hizo ``SpeechStarted``."""
        self._drop_frame_task()
        if self._state is AssistantState.LISTENING and not self.turn_active:
            await self._set_state(AssistantState.IDLE)

    async def _on_interrupt(self, reason: str) -> None:
        self._touch()
        await self._cancel_ambient(reason)
        await self._cancel_turn(reason)
        self._drop_frame_task()
        await self._set_state(AssistantState.IDLE)

    async def _start_turn(self, source: Utterance | TextTurn) -> None:
        self._touch()
        await self._cancel_ambient("interrupted")
        if self.turn_active:
            # Un texto explícito siempre interrumpe; la voz solo con barge-in.
            if isinstance(source, Utterance) and not self._settings.audio.barge_in:
                logger.info("Turno de voz ignorado: Sonia está ocupada y barge_in=false")
                return
            logger.info("Nuevo turno del usuario: se cancela la respuesta en curso")
            await self._cancel_turn("interrupted")
        self._turn_task = asyncio.create_task(self._run_turn(source), name="sonia-turn")
        self._turn_task.add_done_callback(self._refresh_idle_event)

    # -- turno --------------------------------------------------------------

    async def _run_turn(self, source: Utterance | TextTurn) -> None:
        """STT (si hace falta), transcript del usuario y respuesta del modelo."""
        cancelled = False
        try:
            await self._set_state(AssistantState.THINKING)
            frame_task = self._maybe_capture(turn_start=True)
            if isinstance(source, Utterance):
                text = await self._stt.transcribe(source)
            else:
                text = source.text
            text = text.strip()
            if not text:
                logger.info("Turno sin texto reconocible; se vuelve a idle")
                self._drop_frame_task()
                return
            logger.info("Usuario: %s", text)
            await self._hub.broadcast_json(p.msg_transcript("user", text, True))
            frame = await self._collect_frame(frame_task)
            await self.handle_user_text(text, frame)
        except asyncio.CancelledError:
            cancelled = True
            raise
        except Exception as exc:
            logger.exception("El turno falló")
            await self._hub.broadcast_json(p.msg_error(f"Fallo en el turno: {exc}"))
        finally:
            if not cancelled:
                await self._set_state(AssistantState.IDLE)

    async def handle_user_text(self, text: str, frame: Frame | None = None) -> None:
        """Responde a un texto del usuario: modelo, acciones y síntesis.

        Devuelve cuando Sonia ha terminado de hablar (o cuando venció el
        timeout de ``playback_done``). El estado al salir lo gestiona quien llama.
        """
        self._touch()
        if self._state is not AssistantState.THINKING:
            await self._set_state(AssistantState.THINKING)
        if frame is not None and self._policy.enabled:
            self._conversation.add(user_with_image(text, frame))
        else:
            self._conversation.add(user_text(text))

        turn = _Turn()
        try:
            async with asyncio.TaskGroup() as group:
                group.create_task(self._speak_loop(turn), name="sonia-speak")
                group.create_task(self._llm_loop(turn), name="sonia-llm")
        except asyncio.CancelledError:
            self._record_partial(turn)
            raise
        except ExceptionGroup:
            # Los dos bucles capturan sus propios errores; esto es una red de seguridad.
            logger.exception("Error inesperado en el turno")
            self._record_partial(turn)
            return
        if turn.final_text:
            self._conversation.add(assistant_text(turn.final_text))

    def _record_partial(self, turn: _Turn) -> None:
        """Guarda en el historial lo que Sonia alcanzó a decir antes de cortarla."""
        spoken = " ".join(turn.spoken).strip()
        if spoken:
            self._conversation.add(assistant_text(spoken))
            turn.spoken.clear()

    # -- bucle del modelo ---------------------------------------------------

    async def _llm_loop(self, turn: _Turn) -> None:
        try:
            await self._llm_rounds(turn)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log_stage_failure("Fallo hablando con el modelo: %s", exc)
            await self._hub.broadcast_json(p.msg_error(f"Fallo del modelo: {exc}"))
            turn.final_text = " ".join([*turn.round_sentences, APOLOGY_TEXT])
            turn.sentences.put_nowait(APOLOGY_TEXT)
        finally:
            turn.sentences.put_nowait(None)

    async def _llm_rounds(self, turn: _Turn) -> None:
        """Hasta ``max_tool_rounds`` rondas de acciones y una respuesta final."""
        max_rounds = self._settings.llm.max_tool_rounds
        rounds = 0
        while True:
            splitter = SentenceSplitter()
            parser = PromptToolParser() if self._tool_mode == "prompt" else None
            prompt_calls: list[ToolCall] = []
            turn.round_sentences = []
            final: LLMEvent | None = None

            async for event in self._llm.stream(self._conversation.messages(), self._tools):
                if isinstance(event, TextDelta):
                    text = event.text
                    if parser is not None:
                        text, calls = parser.feed(text)
                        prompt_calls.extend(calls)
                    self._feed_text(turn, splitter, text)
                    continue
                final = event
                break

            if parser is not None:
                self._feed_text(turn, splitter, parser.flush())
            self._feed_text(turn, splitter, splitter.flush() or "", flush=True)

            if isinstance(final, ToolCallsEvent):
                # Tool calling nativo: el mensaje del asistente y los
                # resultados van al historial y se vuelve a llamar al modelo.
                rounds += 1
                spoken_this_round = final.content.strip() or " ".join(turn.round_sentences).strip()
                turn.spoken.clear()
                if rounds > max_rounds:
                    logger.warning("Se alcanzó max_tool_rounds=%d; no se ejecutan más", max_rounds)
                    # El mensaje con ``tool_calls`` NO entra en el historial: sin
                    # un ``tool`` por cada id, los servidores compatibles con
                    # OpenAI rechazan todas las peticiones siguientes con un 400.
                    if spoken_this_round:
                        self._conversation.add(assistant_text(spoken_this_round))
                    turn.final_text = ""
                    return
                results = await self._execute_calls(final.calls)
                # El asistente y sus resultados entran juntos y sin ningún await
                # de por medio: si cancelan el turno mientras corre una acción,
                # el historial nunca se queda con ``tool_calls`` sin responder.
                self._conversation.add(assistant_tool_calls(final))
                image: Frame | None = None
                for call, result in results:
                    self._conversation.add(tool_result(call.id, call.name, result.text))
                    if result.image is not None:
                        image = result.image
                if image is not None and self._policy.enabled:
                    self._conversation.add(user_with_image(LOOK_IMAGE_TEXT, image))
                continue

            content = final.content if isinstance(final, TurnDone) else ""
            if prompt_calls:
                # Modo prompt: las acciones iban dentro del texto. Se ejecutan
                # siempre; solo hay otra ronda si el modelo necesita ver el
                # resultado (una imagen) o si no dijo nada aparte de la acción.
                results = await self._execute_calls(prompt_calls)
                image = next((r.image for _, r in results if r.image is not None), None)
                needs_follow_up = image is not None or not turn.round_sentences
                if needs_follow_up and rounds < max_rounds:
                    rounds += 1
                    self._conversation.add(
                        assistant_text(content or " ".join(turn.round_sentences))
                    )
                    turn.spoken.clear()
                    summary = "\n".join(
                        f"[Resultado de la acción {call.name}: {result.text}]"
                        for call, result in results
                    )
                    if image is not None and self._policy.enabled:
                        self._conversation.add(user_with_image(summary, image))
                    else:
                        self._conversation.add(user_text(summary))
                    continue
                if needs_follow_up:
                    logger.warning("Se alcanzó max_tool_rounds=%d; no hay más rondas", max_rounds)

            turn.final_text = content.strip() or " ".join(turn.round_sentences).strip()
            if not turn.final_text and rounds == 0 and not prompt_calls:
                # Terminar sin texto ni acciones no es una respuesta: casi
                # siempre es un servidor que abortó el stream por dentro (varios
                # mandan el error como un chunk más, con HTTP 200). Se trata
                # como fallo para que Sonia al menos se disculpe en voz alta.
                raise RuntimeError("el modelo terminó el turno sin decir nada")
            return

    def _feed_text(
        self, turn: _Turn, splitter: SentenceSplitter, text: str, *, flush: bool = False
    ) -> None:
        """Pasa texto hablable por el splitter y encola las frases cerradas."""
        sentences = [text] if flush else splitter.feed(text)
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            turn.round_sentences.append(sentence)
            turn.sentences.put_nowait(sentence)

    async def _execute_calls(self, calls: list[ToolCall]) -> list[tuple[ToolCall, ActionResult]]:
        """Ejecuta las acciones en orden y devuelve sus resultados."""
        ctx = ActionContext(
            camera=self._camera,
            avatar=self._hub,
            gallery_dir=str(self._settings.gallery_dir),
            last_frame=self._last_frame,
        )
        results: list[tuple[ToolCall, ActionResult]] = []
        for call in calls:
            if self._registry is None:
                result = ActionResult(text="Error: no hay acciones disponibles.")
            else:
                result = await self._registry.execute(call.name, call.arguments, ctx)
            logger.info("Acción %s(%s) -> %s", call.name, call.arguments, result.text)
            results.append((call, result))
        if ctx.last_frame is not None:
            self._last_frame = ctx.last_frame
        return results

    # -- bucle de síntesis --------------------------------------------------

    async def _speak_loop(self, turn: _Turn) -> None:
        """Sintetiza las frases en orden y espera a que Unity termine de reproducir."""
        while True:
            sentence = await turn.sentences.get()
            if sentence is None:
                break
            self._utterance_counter += 1
            utterance_id = self._utterance_counter
            turn.last_utterance_id = utterance_id
            try:
                await self._speak_sentence(turn, utterance_id, sentence)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _log_stage_failure("Fallo del TTS con la frase %r: %s", sentence, exc)
                await self._hub.broadcast_json(p.msg_error(f"Fallo del TTS: {exc}"))
                # Se cierra la frase igualmente para que Unity no espere audio.
                with contextlib.suppress(Exception):
                    await self._hub.send_audio(
                        utterance_id,
                        AudioChunk(pcm=b"", sample_rate=self._tts.sample_rate, is_last=True),
                    )
                    await self._hub.broadcast_json(p.msg_speech_end(utterance_id))

        if turn.last_utterance_id is not None:
            remaining = max(0.0, turn.playback_end_at - time.monotonic())
            await self._wait_playback_done(turn.last_utterance_id, remaining + PLAYBACK_GRACE_S)

    async def _speak_sentence(self, turn: _Turn, utterance_id: int, text: str) -> None:
        """Sintetiza una frase, la envía y se espera para no adelantar el turno.

        Los frames de audio salen al ritmo al que los produce el TTS, sin frenar
        dentro de la frase: así ``visemes`` y ``envelope``, que necesitan la
        duración total y por tanto la frase entera, llegan a Unity nada más
        terminar de sintetizarse, cuando apenas ha empezado a sonar. El freno
        (:meth:`_pace`) se aplica al cerrar la frase, de modo que lo que se
        retrasa es la frase siguiente y el adelanto del turno sigue acotado.

        ``aclosing`` cierra el generador del TTS de forma determinista al
        cancelar el turno: los backends con sesión persistente (Gemini Live)
        necesitan enterarse en ese momento, no cuando pase el recolector.
        """
        hub = self._hub
        await hub.broadcast_json(p.msg_transcript("assistant", text, True))
        await hub.broadcast_json(p.msg_speech_start(utterance_id, text))
        turn.spoken.append(text)
        if self._state is not AssistantState.SPEAKING:
            await self._set_state(AssistantState.SPEAKING)

        pcm = bytearray()
        sample_rate = self._tts.sample_rate
        saw_last = False
        async with aclosing(self._tts.synthesize(text)) as chunks:
            async for chunk in chunks:
                saw_last = saw_last or chunk.is_last
                sample_rate = chunk.sample_rate
                await hub.send_audio(utterance_id, chunk)
                pcm += chunk.pcm
        if not saw_last:
            await hub.send_audio(
                utterance_id, AudioChunk(pcm=b"", sample_rate=sample_rate, is_last=True)
            )

        duration = len(pcm) / 2 / sample_rate if sample_rate > 0 else 0.0
        await hub.broadcast_json(p.msg_visemes(utterance_id, visemes_for(text, duration)))
        envelope = envelope_for(bytes(pcm), sample_rate, ENVELOPE_INTERVAL_MS)
        await hub.broadcast_json(p.msg_envelope(utterance_id, ENVELOPE_INTERVAL_MS, envelope))
        await hub.broadcast_json(p.msg_speech_end(utterance_id))
        logger.info("Sonia (%d, %.2f s): %s", utterance_id, duration, text)
        await self._pace(turn, duration)

    async def _pace(self, turn: _Turn, added: float) -> None:
        """Limita cuánto audio va por delante del tiempo real de reproducción."""
        now = time.monotonic()
        turn.playback_end_at = max(turn.playback_end_at, now) + added
        ahead = turn.playback_end_at - now
        if ahead > self._max_lead:
            await asyncio.sleep(ahead - self._max_lead)

    async def _wait_playback_done(self, utterance_id: int, limit_s: float) -> bool:
        """Espera el ``playback_done`` de ``utterance_id`` (o vence ``limit_s``)."""
        deadline = time.monotonic() + limit_s
        while self._playback_done_id < utterance_id:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.debug("Sin playback_done de %d tras %.1f s", utterance_id, limit_s)
                return False
            self._playback_event.clear()
            try:
                await asyncio.wait_for(self._playback_event.wait(), timeout=remaining)
            except TimeoutError:
                logger.debug("Sin playback_done de %d tras %.1f s", utterance_id, limit_s)
                return False
        return True

    # -- cancelación --------------------------------------------------------

    async def _cancel_turn(self, reason: str) -> bool:
        """Cancela el turno en curso y avisa a Unity. Devuelve si había turno."""
        task, self._turn_task = self._turn_task, None
        if task is None or task.done():
            return False
        task.cancel()
        await self._hub.broadcast_json(p.msg_stop_speaking(reason))
        # ``wait`` en vez de ``await task``: no queremos confundir la
        # cancelación del turno con una cancelación de quien llama.
        await asyncio.wait([task])
        if not task.cancelled() and task.exception() is not None:
            logger.error("El turno terminó con error al cancelarlo: %r", task.exception())
        return True

    # -- cámara -------------------------------------------------------------

    def _maybe_capture(self, *, turn_start: bool) -> asyncio.Task[Frame | None] | None:
        """Lanza una captura en segundo plano si la política lo pide."""
        if self._camera is None or not self._policy.enabled:
            return None
        if self._frame_task is not None:
            # Ya hay una captura (en curso o lista) que nadie ha recogido aún.
            if time.monotonic() - self._frame_task_at <= FRAME_MAX_AGE_S:
                return self._frame_task
            self._drop_frame_task()
        wanted = (
            turn_start and self._policy.should_capture_on_turn_start()
        ) or self._policy.should_capture_periodic()
        if not wanted:
            return self._frame_task
        self._frame_task = asyncio.create_task(self._capture_frame(), name="sonia-camera")
        self._frame_task_at = time.monotonic()
        return self._frame_task

    async def _capture_frame(self) -> Frame | None:
        assert self._camera is not None
        try:
            frame = await self._camera.capture()
        except Exception:
            logger.exception("Fallo capturando la cámara")
            return None
        self._policy.note_captured()
        if frame is not None:
            self._last_frame = frame
            self._policy.maybe_save_debug(frame)
        return frame

    async def _collect_frame(self, task: asyncio.Task[Frame | None] | None) -> Frame | None:
        """Recoge la captura (esperando un poco si aún no llegó)."""
        if task is None:
            return None
        if self._frame_task is task:
            self._frame_task = None
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=FRAME_WAIT_S)
        except TimeoutError:
            logger.warning("La cámara no respondió en %.1f s; el turno va sin imagen", FRAME_WAIT_S)
            return None
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Fallo esperando la captura")
            return None

    def _drop_frame_task(self) -> None:
        task, self._frame_task = self._frame_task, None
        if task is not None and not task.done():
            task.cancel()

    # -- estado -------------------------------------------------------------

    async def _set_state(self, state: AssistantState) -> None:
        if state is self._state:
            return
        previous, self._state = self._state, state
        logger.info("Estado: %s -> %s", previous, state)
        was_speaking = previous is AssistantState.SPEAKING
        is_speaking = state is AssistantState.SPEAKING
        if was_speaking != is_speaking and self._on_speaking_changed is not None:
            try:
                self._on_speaking_changed(is_speaking)
            except Exception:
                logger.exception("Fallo en on_speaking_changed")
        await self._hub.broadcast_json(p.msg_state(state))

    def _touch(self) -> None:
        self._last_activity = time.monotonic()
        # Cualquier actividad real pospone el siguiente número del stand.
        if self._showcase is not None:
            self._next_showcase_at = max(
                self._next_showcase_at,
                self._last_activity + self._settings.showcase.first_delay_seconds,
            )

    # -- animación de stand -------------------------------------------------

    @property
    def ambient_active(self) -> bool:
        """Cierto mientras suena una frase o un baile cantado del stand."""
        return self._ambient_task is not None and not self._ambient_task.done()

    async def _maybe_showcase(self) -> None:
        """Lanza un número del stand si Sonia lleva bastante sola."""
        if self._showcase is None or self.ambient_active or self.turn_active:
            return
        if self._state is not AssistantState.IDLE:
            return
        if time.monotonic() < self._next_showcase_at:
            return
        bit = self._showcase.next_bit()
        self._schedule_next_showcase()
        if bit is None:
            return
        self._ambient_task = asyncio.create_task(self._run_ambient(bit), name="sonia-ambient")

    def _schedule_next_showcase(self) -> None:
        show = self._settings.showcase
        low = max(5.0, show.interval_min_seconds)
        high = max(low, show.interval_max_seconds)
        rng = self._showcase.rng if self._showcase is not None else None
        wait = rng.uniform(low, high) if rng is not None else low
        self._next_showcase_at = time.monotonic() + wait

    async def _run_ambient(self, bit: ShowcaseBit) -> None:
        """Gesto (si lo hay) y frase, sin salir de ``idle``.

        La frase viaja como cualquier otra pero marcada ``ambient``: Unity
        mueve la boca y no toca el estado, así que un baile sigue bailando
        mientras "canta". Al micrófono se le avisa igual que si hablara, para
        que no se oiga a sí misma.
        """
        hub = self._hub
        if bit.attention:
            await hub.broadcast_json(p.msg_attention(bit.attention))
            # Un baile arranca con un fundido; la voz entra un poco después.
            await asyncio.sleep(0.6 if bit.is_dance else 0.25)
        self._utterance_counter += 1
        utterance_id = self._utterance_counter
        self._notify_speaking(True)
        try:
            await hub.broadcast_json(p.msg_transcript("assistant", bit.text, True))
            await hub.broadcast_json(p.msg_speech_start(utterance_id, bit.text, ambient=True))
            pcm = bytearray()
            sample_rate = self._tts.sample_rate
            saw_last = False
            async with aclosing(self._tts.synthesize(bit.text)) as chunks:
                async for chunk in chunks:
                    saw_last = saw_last or chunk.is_last
                    sample_rate = chunk.sample_rate
                    await hub.send_audio(utterance_id, chunk)
                    pcm += chunk.pcm
            if not saw_last:
                await hub.send_audio(
                    utterance_id, AudioChunk(pcm=b"", sample_rate=sample_rate, is_last=True)
                )
            duration = len(pcm) / 2 / sample_rate if sample_rate > 0 else 0.0
            await hub.broadcast_json(p.msg_visemes(utterance_id, visemes_for(bit.text, duration)))
            envelope = envelope_for(bytes(pcm), sample_rate, ENVELOPE_INTERVAL_MS)
            await hub.broadcast_json(p.msg_envelope(utterance_id, ENVELOPE_INTERVAL_MS, envelope))
            await hub.broadcast_json(p.msg_speech_end(utterance_id))
            logger.info("Sonia (stand, %d, %.2f s): %s", utterance_id, duration, bit.text)
            await self._wait_playback_done(utterance_id, duration + PLAYBACK_GRACE_S)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log_stage_failure("Fallo del TTS en la animación de stand: %s", exc)
            with contextlib.suppress(Exception):
                await hub.send_audio(
                    utterance_id,
                    AudioChunk(pcm=b"", sample_rate=self._tts.sample_rate, is_last=True),
                )
                await hub.broadcast_json(p.msg_speech_end(utterance_id))
        finally:
            self._notify_speaking(False)

    async def _cancel_ambient(self, reason: str) -> bool:
        """Corta el número del stand en curso (alguien habló o hay turno)."""
        task, self._ambient_task = self._ambient_task, None
        if task is None or task.done():
            return False
        task.cancel()
        await self._hub.broadcast_json(p.msg_stop_speaking(reason))
        await asyncio.wait([task])
        return True

    def _notify_speaking(self, speaking: bool) -> None:
        if self._on_speaking_changed is None:
            return
        try:
            self._on_speaking_changed(speaking)
        except Exception:
            logger.exception("Fallo en on_speaking_changed")

    async def _maybe_reset_idle(self) -> None:
        """Reinicia la conversación tras ``idle_reset_seconds`` sin actividad."""
        limit = self._settings.idle_reset_seconds
        if limit <= 0 or self._state is not AssistantState.IDLE or self.turn_active:
            return
        if len(self._conversation) == 0 and self._last_frame is None:
            return
        if time.monotonic() - self._last_activity < limit:
            return
        logger.info("Sin actividad durante %.0f s: se reinicia la conversación", limit)
        self._conversation.reset()
        # Se relee la galería por si añadieron imágenes sin reiniciar.
        self._conversation.set_system_prompt(self._build_system_prompt())
        self._last_frame = None
        self._touch()
        await self._hub.hide_image()

    def _build_system_prompt(self) -> str:
        """Prompt de sistema con la galería y, en modo ``prompt``, las acciones."""
        extra = ""
        if self._tool_mode == "prompt" and self._registry is not None and len(self._registry):
            extra = render_tools_prompt(self._registry.to_openai_tools())
        gallery_ids = Gallery(self._settings.gallery_dir).ids()
        action_names = (
            list(self._registry.names())
            if self._registry is not None and self._tool_mode != "none"
            else None
        )
        # Descripción del stack real (modelo, voz, oídos, ojos) para que Sonia
        # hable con propiedad de sí misma y no presuma de local si hay nube.
        stack = describe_stack(self._settings, action_names=action_names)
        if self._base_prompt is None:
            return build_system_prompt(gallery_ids=gallery_ids, extra=extra, stack=stack)
        parts = [self._base_prompt]
        if gallery_ids:
            parts.append(
                "Imágenes disponibles en la galería (usa el id exacto): " + ", ".join(gallery_ids)
            )
        if extra:
            parts.append(extra)
        parts.append(stack)
        return "\n\n".join(parts)
