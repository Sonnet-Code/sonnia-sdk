"""Motor de voz GPT-Live: une el micrófono, la sesión de GPT-Live, las acciones y Unity.

GPT-Live es full duplex: oye el micrófono de forma continua, decide él solo
cuándo le hablan y cuándo contestar, se calla si le interrumpen y devuelve su
voz en streaming. Este motor se limita a:

- Mandarle el micrófono tal cual, siempre (silencio solo si el panel lo
  silencia o por debajo de la puerta de ruido ``LIVE_GATE_RMS``).
- Traducir su voz al protocolo de Unity: GPT-Live manda audio sin parar,
  también callado, así que cada tramo con voz separado por un silencio es una
  frase (``speech_start`` + frames binarios + ``speech_end``), y la
  transcripción viaja como ``transcript`` parcial.
- Deducir el estado del avatar (``listening``, ``thinking``, ``speaking``,
  ``idle``) de lo que llega: GPT-Live no emite eventos de turno.
- Ejecutar las acciones que pide el backend Responses al que delega
  (``response.event`` con ``function_call``) y devolverle el resultado.
- Darle ojos: al empezar a hablar alguien, describir la cámara con un modelo
  de visión y pasárselo como nota silenciosa.
- Contarle al director de gestos (``sonia/gestures``) lo que pasa para que
  elija el gesto de cada frase de Sonia.
- Mantener la sesión viva: reconectar con espera creciente si se cae y
  empezar una sesión limpia tras un rato sin nadie (modo kiosco).

Regla de oro: nada de lo que pase en una sesión tumba el motor. Un fallo se registra, se avisa a Unity y se reconecta.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import json
import logging
import re
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol

import numpy as np

from sonia.actions.gallery import Gallery
from sonia.actions.moves import MoveCatalog
from sonia.actions.registry import ActionRegistry
from sonia.agenda import AgendaBook, Schedule
from sonia.clock import Clock, clock_for, place_of, resolve_timezone, spoken_now, spoken_time
from sonia.config import Settings
from sonia.faces import FaceWatcher, Sighting
from sonia.gestures.director import GestureDirector
from sonia.live.audio import MicGate, rms
from sonia.live.client import APPEND_MAX_CHARS, LiveClient, WsConnect, describe_error
from sonia.live.prompts import (
    CAMERA_NOTE_PREFIX,
    CLOCK_NOTE_PREFIX,
    build_session_config,
    in_meeting,
)
from sonia.live.vision import VisionNarrator
from sonia.live.voicecache import VoiceCache
from sonia.persona import KnowledgeSource
from sonia.showcase import Showcase
from sonia.trivia import TriviaGame
from sonia.types import (
    ActionContext,
    ActionResult,
    AssistantState,
    AudioArray,
    AudioChunk,
    AvatarLink,
    CameraSource,
    Frame,
)
from sonia.vision.policy import VisionPolicy
from sonia.vision.presence import PresenceWatch
from sonia.ws import protocol as p
from sonia.ws.hub import MessageCallback

__all__ = ["LiveEngine"]

logger = logging.getLogger(__name__)

#: Margen sobre la duración estimada al esperar el ``playback_done`` de Unity.
PLAYBACK_GRACE_S = 1.0

#: Tras callar Sonia, se espera esto antes de cambiar el estado del avatar: una
#: pausa entre dos frases de la misma respuesta no debe pasar por ``idle``.
SPEECH_HOLD_S = 0.6

#: Cuánto se queda en ``thinking`` esperando a que GPT-Live conteste.
RESPONSE_WAIT_S = 4.0

#: Una tarea delegada que no termina en este tiempo se da por perdida.
DELEGATION_TIMEOUT_S = 90.0

#: Una tarea delegada que lleva más que esto se le cuenta a Unity (``activity``
#: ``think``) para la lluvia estilo Matrix. En los registros del 7 de octubre de
#: 2026 las tareas con acciones tardaban 3,4 s de mediana (4,8 s el percentil
#: 75): con menos, la lluvia saldría en casi todas (enseñar una imagen, la
#: agenda) y no solo en las que tardan de verdad.
SLOW_TASK_S = 5.0

#: Ventana en la que la próxima voz de Sonia se considera el número del stand pedido.
AMBIENT_WAIT_S = 8.0
#: Tras un tramo de frase del stand, lo que diga GPT-Live en este tiempo es su
#: continuación: un momento largo salía en dos tramos y el segundo ya no iba como
#: frase del stand (el avatar pasaba a «hablando»; 7 de octubre de 2026).
AMBIENT_CONTINUE_S = 2.5

#: Adelanto del audio sobre el tiempo real a partir del cual se avisa en el log.
LEAD_WARN_S = 1.5

#: Tope de espera de una captura para describirla.
CAPTURE_TIMEOUT_S = 3.0

#: Antes de que caduque la sesión se abre otra en el siguiente momento de calma.
EXPIRY_MARGIN_S = 120.0

#: Una sesión que duró más que esto reinicia la espera entre reconexiones.
HEALTHY_SESSION_S = 60.0

#: Unos 16 000 tokens en español: por encima se avisa en el log.
INSTRUCTIONS_WARN_CHARS = 50_000

#: Texto que acompaña a la foto pedida por la acción ``look`` en el backend.
LOOK_IMAGE_TEXT = "[Foto de la cámara pedida por la acción look]"

#: Cómo se le pasa a GPT-Live un texto escrito en la pantalla del stand.
TEXT_INPUT_TEMPLATE = (
    "Un visitante te ha escrito en la pantalla del stand (no lo ha dicho en voz alta): "
    "«{text}». Respóndele ahora en voz alta como si te lo hubiera dicho."
)

#: Instrucción tras una interrupción desde Unity (por ejemplo, tocar la pantalla).
INTERRUPT_TEXT = "El visitante te ha interrumpido: deja de hablar ahora y escucha lo que te diga."

#: Cómo se pasa un aviso del panel para que lo diga en voz alta.
ANNOUNCE_TEMPLATE = (
    "Aviso del equipo del stand para los visitantes. Dilo ahora en voz alta, con tus "
    "palabras pero sin cambiar los datos: «{text}»"
)

#: Cómo se pasan los avisos del día cuando cambian durante una sesión.
NOTES_TEMPLATE = (
    "Avisos de hoy del equipo del stand (son más recientes que tu base de conocimiento; "
    "si chocan, mandan estos): {text}"
)
NOTES_CLEARED_TEXT = "El equipo del stand ha retirado los avisos de hoy: ya no aplican."

#: Cómo se le cuenta a GPT-Live que su tarea delegada se quedó sin resultado: no se
#: entera solo y seguía dando largas («estoy cuadrando cómo explicártelo»).
DELEGATION_FAILED_TEXT = (
    "Tu backend no pudo terminar la tarea que le pediste y no tienes el resultado. Díselo "
    "ahora al visitante en una frase, sin inventarte la respuesta, y ofrécele intentarlo de "
    "otra forma o contarle lo que sí sabes."
)

#: Cómo se pasan los cambios de la agenda detectados durante una sesión.
AGENDA_CHANGED_TEMPLATE = (
    "La agenda oficial del DevFest acaba de cambiar en su web (mandan estos cambios sobre la "
    "agenda que tienes): {changes}"
)
AGENDA_MORE_TEXT = " Hay más cambios: si te preguntan por otra charla, consulta la agenda."

#: Nivel RMS (0..1) a partir del cual un trozo de la voz de GPT-Live es voz.
#: GPT-Live manda audio sin parar, también cuando calla (silencio digital, 0):
#: las frases hacia Unity se cortan por nivel, no por huecos en el envío.
OUTPUT_VOICE_RMS = 0.003

#: Decaimiento por bloque del medidor de nivel del micrófono.
MIC_LEVEL_DECAY = 0.85

#: Nivel por debajo del cual un bloque se considera silencio absoluto.
MIC_SILENCE_RMS = 0.0005

#: Segundos que el micrófono sigue mandando silencio a GPT-Live después de una
#: frase grabada (búfer de Unity y cola del altavoz en la sala).
CLIP_ECHO_TAIL_S = 0.8

#: Cómo se pide un número de la animación de stand.
SHOWCASE_TEMPLATE = (
    "Ahora mismo nadie está hablando contigo. Para animar el stand, di en voz alta, una sola "
    "vez y tal cual, esta frase: «{text}»"
)

#: Cómo se le pide a GPT-Live un momento del stand (``{focus}``: de qué tira).
MOMENT_TEMPLATE = (
    "Ahora mismo nadie está hablando contigo. Para animar el stand, di en voz alta una sola "
    "frase corta y nueva, distinta de las que ya has dicho, que invite a la gente que pasa a "
    "acercarse a hablar contigo. Quien pasa ya está aquí, en el DevFest: no le hables del "
    "evento como si aún fuera a venir, ni de entradas. {focus} Dila sin más: sin saludar como "
    "si te hubieran hablado y sin explicar por qué la dices."
)

#: De qué tira cada momento, por turnos entre los que hay. La hora no: la decía de más.
MOMENT_FOCUS = {
    "agenda": "Tira de lo que pasa ahora en el DevFest, sin cambiar títulos, salas ni horas: {text}",
    "cámara": (
        "Tira de lo que ve ahora tu cámara, en tono simpático: como mucho una prenda, un gafete "
        "o un objeto, nunca el cuerpo, la edad, la piel ni nada personal. Lo que ve: {text}"
    ),
    "invitación": (
        "Propón algo concreto: jugar a la trivia, preguntarte por la agenda o por Sonnet Code, o "
        "interrumpirte para ver que hablas en tiempo real."
    ),
}

#: Tope para preparar un momento (la foto y su descripción): mientras, no sale otro número.
MOMENT_PREP_S = 15.0


class HubLike(AvatarLink, Protocol):
    """Lo que el motor usa del hub WebSocket (y las acciones del avatar)."""

    def on(self, type: str, callback: MessageCallback) -> None: ...
    async def broadcast_json(self, msg: dict[str, Any]) -> None: ...
    async def send_audio(self, utterance_id: int, chunk: AudioChunk) -> None: ...
    async def set_sticky(self, key: str, msg: dict[str, Any]) -> None: ...
    def clear_sticky(self, key: str) -> None: ...


def _log_stage_failure(msg: str, *args: Any) -> None:
    """Una línea legible por fallo; la traza solo con ``LOG_LEVEL=DEBUG``."""
    logger.error(msg, *args, exc_info=logger.isEnabledFor(logging.DEBUG))


@dataclass(slots=True)
class _Segment:
    """Un tramo continuo de voz de Sonia: una frase para Unity."""

    uid: int
    ambient: bool
    parts: list[str] = field(default_factory=list)
    seconds: float = 0.0
    #: Silencio recibido tras la última voz: se manda solo si vuelve la voz
    #: (pausa dentro de la frase); si la frase termina, se tira.
    held_silence: list[bytes] = field(default_factory=list)

    @property
    def text(self) -> str:
        # Sin "[laugh]" ni "[sigh]": va a los subtítulos que ve el público.
        return clean_transcript("".join(self.parts))


@dataclass(slots=True)
class _Delegation:
    """Una tarea que GPT-Live delegó en el backend Responses."""

    id: str
    created_at: float
    rounds: int = 0
    #: Acciones en marcha (aún sin resultado enviado).
    running_calls: int = 0
    #: Acciones pedidas en la respuesta actual del backend.
    calls_in_response: int = 0
    #: Acciones pedidas en toda la tarea (para el registro).
    calls_total: int = 0
    #: La respuesta actual del backend ya terminó (``response.completed``...).
    response_done: bool = False
    text: list[str] = field(default_factory=list)
    #: Búsquedas en internet (``web_search``) en marcha, por id del elemento.
    searches: set[str] = field(default_factory=set)


#: Eventos anidados que cierran una respuesta del backend.
_TERMINAL_RESPONSE_EVENTS = frozenset(
    {"response.completed", "response.failed", "response.incomplete", "response.cancelled", "error"}
)


def _is_web_search_event(kind: Any, item: Any) -> bool:
    """Eventos del backend de una búsqueda en internet: los suyos o los de su elemento de salida."""
    if isinstance(kind, str) and kind.startswith("response.web_search_call."):
        return True
    return (
        kind in ("response.output_item.added", "response.output_item.done")
        and isinstance(item, dict)
        and item.get("type") == "web_search_call"
    )


class LiveEngine:
    """Motor de Sonia sobre GPT-Live. Todas las dependencias entran por el constructor."""

    def __init__(
        self,
        settings: Settings,
        *,
        hub: HubLike,
        registry: ActionRegistry | None = None,
        camera: CameraSource | None = None,
        vision_policy: VisionPolicy | None = None,
        narrator: VisionNarrator | None = None,
        showcase: Showcase | None = None,
        connect: WsConnect | None = None,
        knowledge_dir: KnowledgeSource = None,
        voice_cache: VoiceCache | None = None,
        gestures: GestureDirector | None = None,
        agenda: AgendaBook | None = None,
        clock: Clock | None = None,
        faces: FaceWatcher | None = None,
        presence: PresenceWatch | None = None,
        tick_s: float = 0.05,
    ) -> None:
        self._settings = settings
        self._voice_cache = voice_cache
        self._live = settings.live
        self._hub = hub
        self._registry = registry
        self._camera = camera
        self._policy = vision_policy or VisionPolicy(settings.vision, settings.llm.supports_vision)
        self._narrator = narrator
        self._connect = connect
        self._knowledge_dir = knowledge_dir
        self._tick = max(0.01, tick_s)
        self._rate = int(self._live.sample_rate)
        #: Si hay alguien delante de la cámara (``sonia.vision.presence``).
        self._presence = presence
        #: Qué oye GPT-Live en cada bloque: todas las medidas del micro juntas.
        self._mic = MicGate(
            threshold=self._live.gate_rms,
            hold_ms=self._live.gate_hold_ms,
            comfort_rms=self._live.comfort_noise_rms,
            near_scale=self._live.presence_near_gate_scale,
            presence=presence.gate if presence is not None else None,
            silence_rms=MIC_SILENCE_RMS,
        )

        self._client: LiveClient | None = None
        #: Con ``False`` no se abre sesión: GPT-Live apagada, sin gasto.
        self._active = True
        self._active_event = asyncio.Event()
        self._active_event.set()
        self._state = AssistantState.IDLE
        self._utterance_counter = 0
        self._tasks: set[asyncio.Task[Any]] = set()

        # Voz de Sonia.
        self._segment: _Segment | None = None
        self._pending_assistant: list[str] = []
        self._last_audio_at = 0.0
        self._last_voice_at = 0.0
        self._playback_end_at = 0.0
        self._last_closed_uid = 0
        self._last_closed_deadline = 0.0
        self._playback_done_id = 0
        self._audible = False
        self._settle_after = 0.0
        self._discard_audio = False
        self._lead_warned = False

        # Voz del visitante.
        self._user_parts: list[str] = []
        self._user_turn_open = False
        self._user_turn_started_at = 0.0
        self._last_input_at = 0.0
        self._turn_level = 0.0
        self._expect_response_until = 0.0

        # Micrófono (para el panel).
        self._mic_manual_mute = False
        #: Oyentes de cada bloque del micro (el Modo Jean lo manda a España).
        self._mic_listeners: list[Callable[[AudioArray], None]] = []
        #: Hasta cuándo el micrófono manda silencio porque suena una frase grabada.
        self._clip_mute_until = 0.0
        self._clip_uid = 0
        self._mic_level = 0.0
        self._last_mic_at = 0.0
        self._last_sound_at = 0.0

        # Backend y sesión.
        self._delegations: dict[str, _Delegation] = {}
        self._last_delegation_id: str | None = None
        #: Lo último que se le dijo a Unity en ``activity``.
        self._activity = "none"
        #: ``event_id`` de los comandos enviados al backend → delegación, para
        #: cerrar la tarea si la API responde a uno de ellos con ``error``.
        self._command_owner: dict[str, str] = {}
        self._session_conversation = False
        self._session_started_at = 0.0
        self._context_full = False
        self._restarting = False
        self._last_activity = time.monotonic()
        #: Avisos del día que el equipo escribe en el panel.
        self._notes = ""
        self._usage_closed_s = 0.0
        self._usage_session_s = 0.0
        self._context_ratio: float | None = None
        self.last_error = ""

        # Cámara e imagen en pantalla.
        self._last_frame: Frame | None = None
        self._vision_task: asyncio.Task[None] | None = None
        self._last_vision_at = float("-inf")
        self._camera_ok: bool | None = None
        self._image_hide_task: asyncio.Task[None] | None = None
        #: Reconocer al equipo de Sonnet Code y a los ponentes (``sonia.faces``, docs/caras.md).
        self._faces = faces

        # Animación de stand.
        # Se carga siempre (si hay material) para poder activarla desde el panel.
        show = settings.showcase
        if showcase is None:
            showcase = Showcase.from_dir(
                settings.showcase_dir,
                dance_chance=show.dance_chance,
                gesture_chance=show.gesture_chance,
                moment_chance=show.moment_chance,
            )
        self._showcase = showcase if showcase.enabled else None
        # En una videollamada (modo reunión) no hay animación de stand: en los
        # silencios de la reunión Sonia se pondría a bailar o a decir frases del stand.
        self._meeting = in_meeting(settings)
        self._showcase_enabled = show.enabled and not self._meeting
        self._next_showcase_at = time.monotonic() + max(0.0, show.first_delay_seconds)
        self._ambient_expected_until = 0.0
        #: Momentos del stand pedidos: de qué tira el siguiente va por turnos.
        self._moment_turn = 0

        # Modo trivia (``sonia.trivia``): GPT-Live la conduce; aquí van la clave y la pantalla.
        self._trivia: TriviaGame | None = (
            TriviaGame(settings.trivia, settings.trivia_file, host=self, screen=hub)
            if settings.trivia.enabled
            else None
        )

        # Fecha y hora del stand (``TIMEZONE``) y agenda del evento en vivo (``sonia.agenda``).
        tz = resolve_timezone(settings.timezone)
        self._place = place_of(settings.timezone)
        self._now: Clock = clock or clock_for(tz)
        #: Inicio de las charlas de la última nota ``[Reloj]`` de la sesión abierta.
        self._clock_noted: datetime | None = None
        #: Cambios de agenda a la espera de un momento de calma para pasárselos a la sesión.
        self._pending_agenda_note = ""
        self._agenda = agenda
        #: La agenda que se puso en las instrucciones de la sesión abierta.
        self._session_agenda: Schedule | None = None
        if agenda is not None:
            agenda.on_change(self._on_agenda_change)

        # Movimientos por voz (``play_animation``): el catálogo lo manda Unity al conectar.
        self._moves = MoveCatalog(hub.broadcast_json)
        hub.on(p.MSG_ANIMATIONS, self._moves.update)

        # Gestos al hablar: el catálogo lo manda Unity al conectar; el director los elige.
        self._gestures = gestures
        if gestures is not None:
            hub.on(p.MSG_GESTURE_CATALOG, gestures.on_catalog)

        hub.on(p.MSG_INTERRUPT, lambda msg: self._spawn(self._on_interrupt(), "interrupt"))
        hub.on(p.MSG_PLAYBACK_DONE, self._on_ws_playback_done)
        hub.on(p.MSG_TEXT_INPUT, self._on_ws_text_input)
        on_frame = getattr(camera, "on_frame", None)
        if callable(on_frame):
            hub.on(p.MSG_CAMERA_FRAME, lambda msg: _forward_camera_frame(on_frame, msg))

    # -- propiedades --------------------------------------------------------

    @property
    def state(self) -> AssistantState:
        return self._state

    @property
    def session_id(self) -> str:
        return self._client.session_id if self._client is not None else ""

    @property
    def connected(self) -> bool:
        return self._client is not None

    @property
    def last_frame(self) -> Frame | None:
        return self._last_frame

    @property
    def active(self) -> bool:
        return self._active

    @property
    def showcase(self) -> Showcase | None:
        return self._showcase

    @property
    def trivia(self) -> TriviaGame | None:
        return self._trivia

    # -- entrada ------------------------------------------------------------

    async def push_mic(self, block: AudioArray) -> None:
        """Un bloque del micrófono (float32 mono a la tasa de la sesión).

        Va siempre a GPT-Live, también mientras habla Sonia: así se la puede
        interrumpir hablando. :class:`MicGate` decide si GPT-Live oye el bloque
        o un ruido muy suave del mismo tamaño (micro silenciado, frase grabada,
        nadie delante de la cámara, puerta de ruido, silencio), porque GPT-Live
        necesita un flujo continuo y con ceros absolutos se retrasa. Sin
        sesión, el bloque se pierde.
        """
        now = time.monotonic()
        level = rms(block)
        self._mic_level = max(level, self._mic_level * MIC_LEVEL_DECAY)
        self._last_mic_at = now
        if level > MIC_SILENCE_RMS:
            self._last_sound_at = now
        if self._mic_listeners:
            # El Modo Jean oye el stand aunque GPT-Live esté cerrada; silenciado
            # desde el panel, tampoco lo oye él.
            heard = np.zeros_like(block) if self._mic_manual_mute else block
            for listener in list(self._mic_listeners):
                try:
                    listener(heard)
                except Exception:  # noqa: BLE001 - un oyente roto no corta el micro
                    logger.exception("Error en un oyente del micrófono")
        client = self._client
        if client is None or self._restarting:
            return
        echo = now < self._clip_mute_until
        if self._user_turn_open and not (self._mic_manual_mute or echo):
            self._turn_level = max(self._turn_level, level)
        pcm = self._mic.pcm(block, level, now, muted=self._mic_manual_mute, echo=echo)
        try:
            await client.append_audio(pcm)
        except Exception as exc:  # noqa: BLE001 - la sesión se reconecta sola
            logger.debug("No se pudo enviar audio a GPT-Live: %s", exc)

    async def submit_text(self, text: str) -> None:
        """Un texto escrito (``text_input`` de Unity o la consola de ``sonia chat``)."""
        text = text.strip()
        if not text:
            return
        now = time.monotonic()
        self._touch()
        self._session_conversation = True
        self._ambient_expected_until = 0.0
        await self._hub.broadcast_json(p.msg_transcript("user", text, True))
        logger.info("Usuario (texto): %s", text)
        client = self._client
        if client is None:
            logger.warning("Texto ignorado: GPT-Live no está conectado")
            await self._hub.broadcast_json(p.msg_error("GPT-Live no está conectado"))
            return
        try:
            # ``instructions.append`` no la hace hablar; ``commentary`` sí.
            await client.append_commentary(TEXT_INPUT_TEMPLATE.format(text=text))
        except Exception as exc:  # noqa: BLE001
            _log_stage_failure("No se pudo pasar el texto a GPT-Live: %s", exc)
            return
        if self._gestures is not None:
            self._gestures.on_user_turn(text, answering=self._audible)
        self._expect_response_until = now + RESPONSE_WAIT_S
        if not self._audible:
            await self._set_state(AssistantState.THINKING)

    def notify_playback_done(self, utterance_id: int) -> None:
        """Unity (o el reproductor local) terminó de reproducir ``utterance_id``."""
        self._playback_done_id = max(self._playback_done_id, utterance_id)
        if utterance_id == self._clip_uid:
            # Unity sabe mejor que la estimación cuándo terminó la frase grabada.
            self._clip_mute_until = time.monotonic() + CLIP_ECHO_TAIL_S

    async def wait_idle(self, limit_s: float | None = None) -> bool:
        """Espera a que Sonia no hable, no piense y nadie esté hablando."""
        deadline = None if limit_s is None else time.monotonic() + limit_s
        while not self._is_idle(time.monotonic()):
            if deadline is not None and time.monotonic() >= deadline:
                return False
            await asyncio.sleep(0.05)
        return True

    # -- callbacks del hub --------------------------------------------------

    def _on_ws_playback_done(self, msg: dict[str, Any]) -> None:
        utterance_id = msg.get("utterance_id")
        if isinstance(utterance_id, int) and not isinstance(utterance_id, bool):
            self.notify_playback_done(utterance_id)

    def _on_ws_text_input(self, msg: dict[str, Any]) -> None:
        text = msg.get("text")
        if isinstance(text, str) and text.strip():
            self._spawn(self.submit_text(text), "text-input")

    # -- bucle principal ----------------------------------------------------

    async def run(self) -> None:
        """Mantiene una sesión de GPT-Live abierta. Solo termina al cancelarlo."""
        live = self._live
        logger.info(
            "Motor GPT-Live en marcha (modelo %s, voz %s, backend %s, visión %s)",
            live.model,
            live.voice,
            live.backend_model,
            "sí" if self._narrator is not None and self._policy.enabled else "no",
        )
        await self._hub.broadcast_json(p.msg_state(self._state))
        ticker = asyncio.create_task(self._tick_loop(), name="sonia-live-tick")
        watcher: asyncio.Task[None] | None = None
        if self._agenda is not None:
            # La guardada entra ya en la primera sesión; la de la web, cuando llegue.
            await self._agenda.load()
            watcher = asyncio.create_task(self._agenda.watch(), name="sonia-agenda")
        faces: asyncio.Task[None] | None = None
        if self._faces is not None and self._camera is not None:
            faces = asyncio.create_task(self._faces_loop(self._faces), name="sonia-faces")
        presence: asyncio.Task[None] | None = None
        if self._presence is not None:
            presence = asyncio.create_task(
                self._presence.run(active=self._session_open, busy=self._in_conversation),
                name="sonia-presence",
            )
        delay = live.reconnect_min_seconds
        try:
            while True:
                if not self._active:
                    await self._active_event.wait()
                    delay = live.reconnect_min_seconds
                started = time.monotonic()
                renewed = False
                try:
                    renewed = await self._run_session()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    _log_stage_failure("Sesión de GPT-Live caída: %s", exc)
                    self.last_error = str(exc)
                    await self._hub.broadcast_json(p.msg_error(f"GPT-Live: {exc}"))
                if renewed or time.monotonic() - started > HEALTHY_SESSION_S:
                    delay = live.reconnect_min_seconds
                if renewed:
                    continue
                # Cualquier otro final (caducidad, filtro de contenido, red, un
                # servidor que cierra nada más abrir) espera antes de reconectar:
                # abrir sesiones sin freno durante horas cuesta dinero.
                logger.info("Se reintenta conectar con GPT-Live en %.0f s", delay)
                await asyncio.sleep(delay)
                delay = min(max(delay * 2, live.reconnect_min_seconds), live.reconnect_max_seconds)
        finally:
            extra = [task for task in (watcher, faces, presence) if task is not None]
            for task in (ticker, *extra):
                task.cancel()
            await asyncio.gather(ticker, *extra, return_exceptions=True)
            await self._shutdown()

    async def _run_session(self) -> bool:
        """Una sesión de principio a fin. Devuelve si terminó porque el motor la renovó."""
        client = LiveClient(self._live, connect=self._connect)
        clock_text = spoken_now(self._now(), self._place)
        agenda = self._agenda
        config = build_session_config(
            self._settings,
            registry=self._registry,
            gallery_ids=Gallery(self._settings.gallery_dir).ids(),
            knowledge_dir=self._knowledge_dir,
            notes=self._notes,
            agenda=agenda.text() if agenda is not None else "",
            clock_text=clock_text,
            faces=self._faces is not None and self._camera is not None,
        )
        self._session_agenda = agenda.schedule if agenda is not None else None
        self._clock_noted = None
        self._pending_agenda_note = ""
        if len(config["instructions"]) > INSTRUCTIONS_WARN_CHARS:
            logger.warning(
                "Las instrucciones de GPT-Live ocupan %d caracteres: pueden pasar del límite de "
                "16 384 tokens. Recorta assets/knowledge.",
                len(config["instructions"]),
            )
        try:
            await client.start(config)
            self._begin_session(client)
            expires = client.expires_at
            logger.info(
                "Sesión de GPT-Live lista (%s%s)",
                client.session_id or "sin id",
                f"; caduca en {(expires - time.time()) / 60:.0f} min" if expires else "",
            )
            async for event in client.events():
                try:
                    await self._handle_event(event)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Error procesando el evento %s de GPT-Live", event.get("type"))
            logger.info(
                "La sesión de GPT-Live terminó (%s)", client.close_reason or "conexión cerrada"
            )
            return self._restarting
        finally:
            self._client = None
            # Si el motor se está apagando no se espera la respuesta del cierre.
            await client.close(wait=False)
            await self._end_session()

    def _begin_session(self, client: LiveClient) -> None:
        self._client = client
        self.last_error = ""
        self._usage_session_s = 0.0
        self._context_ratio = None
        self._session_conversation = False
        self._session_started_at = time.monotonic()
        self._context_full = False
        self._restarting = False
        self._lead_warned = False
        self._delegations.clear()
        self._last_delegation_id = None
        self._command_owner.clear()
        if self._gestures is not None:
            self._gestures.on_session(True)

    async def _end_session(self) -> None:
        """Deja a Unity en un estado coherente cuando cae la sesión."""
        if self._session_started_at:
            lasted = time.monotonic() - self._session_started_at
            self._usage_closed_s += max(self._usage_session_s, lasted)
            self._session_started_at = 0.0
            self._usage_session_s = 0.0
        if self._segment is not None:
            with contextlib.suppress(Exception):
                await self._close_segment(time.monotonic())
        if self._gestures is not None:
            self._gestures.on_session(False)
        self._pending_assistant = []
        self._discard_audio = False
        self._playback_end_at = min(self._playback_end_at, time.monotonic())
        self._delegations.clear()
        self._user_turn_open = False
        self._user_parts = []
        self._expect_response_until = 0.0
        if self._trivia is not None:
            with contextlib.suppress(Exception):
                await self._trivia.on_session_lost()

    async def _shutdown(self) -> None:
        if self._gestures is not None:
            self._gestures.close()
        for task in [*self._tasks, self._vision_task, self._image_hide_task]:
            if task is not None and not task.done():
                task.cancel()
        client, self._client = self._client, None
        if client is not None:
            with contextlib.suppress(Exception):
                await client.close(wait=False)

    # -- eventos de GPT-Live ------------------------------------------------

    async def _handle_event(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        match kind:
            case "session.output_audio.delta":
                await self._on_output_audio(event)
            case "session.output_transcript.delta":
                await self._on_output_transcript(event)
            case "session.input_transcript.delta":
                await self._on_input_transcript(event)
            case "session.delegation.created":
                await self._on_delegation_created(event)
            case "response.event":
                await self._on_response_event(event)
            case "session.usage.updated":
                self._on_usage(event)
            case "error":
                self.last_error = describe_error(event)
                logger.warning("GPT-Live informó de un error: %s", self.last_error)
                self._on_command_error(event)
                await self._on_handoff_error(event)
            case "session.closed":
                logger.info("GPT-Live cerró la sesión (%s)", event.get("reason"))
            case _:
                logger.debug("Evento de GPT-Live: %s", kind)

    async def _on_output_audio(self, event: dict[str, Any]) -> None:
        data = event.get("delta")
        if not isinstance(data, str) or not data:
            return
        try:
            pcm = base64.b64decode(data)
        except (binascii.Error, ValueError):
            logger.debug("Audio de GPT-Live con base64 inválido; se descarta")
            return
        if len(pcm) % 2:
            pcm = pcm[:-1]
        if not pcm:
            return
        now = time.monotonic()
        self._last_audio_at = now
        voiced = _pcm16_rms(pcm) >= OUTPUT_VOICE_RMS
        if voiced:
            self._last_voice_at = now
        if self._discard_audio:
            return
        segment = self._segment
        if segment is None:
            if not voiced:
                return  # GPT-Live calla: nada que mandar a Unity
            segment = await self._open_segment(now)
        if not voiced:
            segment.held_silence.append(pcm)
            return
        for chunk in [*segment.held_silence, pcm]:
            seconds = len(chunk) / 2 / self._rate
            segment.seconds += seconds
            self._playback_end_at = max(self._playback_end_at, now) + seconds
            await self._hub.send_audio(segment.uid, AudioChunk(pcm=chunk, sample_rate=self._rate))
        segment.held_silence.clear()
        lead = self._playback_end_at - now
        if lead > LEAD_WARN_S and not self._lead_warned:
            self._lead_warned = True
            logger.warning(
                "GPT-Live manda la voz %.1f s por delante del tiempo real: al interrumpirla, "
                "Unity seguirá sonando lo que tenga en cola",
                lead,
            )

    async def _open_segment(self, now: float) -> _Segment:
        self._utterance_counter += 1
        ambient = now < self._ambient_expected_until and not self._user_turn_open
        self._ambient_expected_until = 0.0
        segment = _Segment(uid=self._utterance_counter, ambient=ambient)
        segment.parts, self._pending_assistant = self._pending_assistant, []
        self._segment = segment
        self._audible = True
        await self._hub.broadcast_json(
            p.msg_speech_start(segment.uid, segment.text, ambient=ambient)
        )
        if self._gestures is not None:
            # Si el visitante aún no cerró su turno, Sonia le está contestando ya.
            self._gestures.on_speech_start(
                segment.uid,
                ambient=ambient,
                text=segment.text,
                user_text=self._user_text if self._user_turn_open else None,
            )
        if not ambient:
            self._touch()
            self._session_conversation = True
            self._expect_response_until = 0.0
            await self._set_state(AssistantState.SPEAKING)
        if segment.text:
            await self._hub.broadcast_json(p.msg_transcript("assistant", segment.text, False))
        return segment

    async def _close_segment(self, now: float) -> None:
        segment, self._segment = self._segment, None
        if segment is None:
            return
        hub = self._hub
        text = segment.text
        if text:
            await hub.broadcast_json(p.msg_transcript("assistant", text, True))
        await hub.send_audio(segment.uid, AudioChunk(pcm=b"", sample_rate=self._rate, is_last=True))
        await hub.broadcast_json(p.msg_speech_end(segment.uid))
        if self._gestures is not None:
            self._gestures.on_speech_end(segment.uid, text)
        logger.info(
            "Sonia (%s%d, %.2f s): %s",
            "stand, " if segment.ambient else "",
            segment.uid,
            segment.seconds,
            text or "(sin transcripción)",
        )
        self._last_closed_uid = segment.uid
        self._last_closed_deadline = max(self._playback_end_at, now) + PLAYBACK_GRACE_S
        if segment.ambient and not self._user_turn_open:
            self._ambient_expected_until = max(
                self._ambient_expected_until, now + AMBIENT_CONTINUE_S
            )

    async def _on_output_transcript(self, event: dict[str, Any]) -> None:
        delta = event.get("delta")
        if not isinstance(delta, str) or not delta or self._discard_audio:
            return
        segment = self._segment
        if segment is None:
            # El texto puede adelantarse un poco a su audio.
            self._pending_assistant.append(delta)
            return
        segment.parts.append(delta)
        text = segment.text
        await self._hub.broadcast_json(p.msg_transcript("assistant", text, False))
        if self._gestures is not None:
            self._gestures.on_assistant_text(segment.uid, text)
        if self._trivia is not None:
            # La trivia retenida mientras pregunta por Sonnet Code sale cuando arranca.
            await self._trivia.on_assistant_text(text)

    async def _on_input_transcript(self, event: dict[str, Any]) -> None:
        delta = event.get("delta")
        if not isinstance(delta, str) or not delta:
            return
        if not self._user_turn_open and not delta.strip():
            return
        now = time.monotonic()
        if not self._user_turn_open:
            self._user_turn_open = True
            self._user_turn_started_at = now
            self._user_parts = []
            self._turn_level = 0.0
            self._session_conversation = True
            # Alguien habla: lo próximo que diga Sonia es una respuesta.
            self._ambient_expected_until = 0.0
            self._maybe_look(turn_start=True)
        self._user_parts.append(delta)
        self._last_input_at = now
        self._touch()
        if self._trivia is not None:
            self._trivia.on_user_text(now)
        await self._hub.broadcast_json(p.msg_transcript("user", self._user_text, False))
        if not self._audible:
            await self._set_state(AssistantState.LISTENING)

    @property
    def _user_text(self) -> str:
        return clean_transcript("".join(self._user_parts))

    async def _finish_user_turn(self, now: float) -> None:
        self._user_turn_open = False
        text = self._user_text
        self._user_parts = []
        if text:
            await self._hub.broadcast_json(p.msg_transcript("user", text, True))
            logger.info("Usuario (nivel %.3f): %s", self._turn_level, text)
            if self._gestures is not None:
                self._gestures.on_user_turn(text, answering=self._audible)
        if not self._audible:
            self._expect_response_until = now + RESPONSE_WAIT_S
        if self._trivia is not None and text:
            self._trivia.on_user_turn_end(now, self._user_turn_started_at)

    # -- delegación y acciones ----------------------------------------------

    async def _on_delegation_created(self, event: dict[str, Any]) -> None:
        delegation = event.get("delegation")
        if not isinstance(delegation, dict) or not isinstance(delegation.get("id"), str):
            return
        delegation_id = delegation["id"]
        target = delegation.get("target")
        now = time.monotonic()
        self._delegations[delegation_id] = _Delegation(delegation_id, now)
        self._last_delegation_id = delegation_id
        self._session_conversation = True
        self._touch()
        # Lo que traiga la delegación además de sus ids (la tarea, si la API la manda).
        details = {
            k: v for k, v in delegation.items() if k not in ("id", "type", "target", "response_id")
        }
        logger.info(
            "GPT-Live delega una tarea en el backend %s (%s)%s",
            target,
            delegation_id,
            f": {json.dumps(details, ensure_ascii=False)[:300]}" if details else "",
        )
        if self._trivia is not None:
            self._trivia.on_delegation(now)
        if not self._audible:
            await self._set_state(AssistantState.THINKING)

    async def _on_response_event(self, event: dict[str, Any]) -> None:
        nested = event.get("event")
        if not isinstance(nested, dict):
            return
        kind = nested.get("type")
        item = nested.get("item")
        is_call = (
            kind == "response.output_item.done"
            and isinstance(item, dict)
            and item.get("type") == "function_call"
        )
        delegation_id = event.get("delegation_id") or self._last_delegation_id
        delegation = (
            self._delegations.get(delegation_id) if isinstance(delegation_id, str) else None
        )
        if delegation is None and (kind == "response.created" or is_call):
            # Trabajo nuevo sin ``session.delegation.created`` (perdido o sin id
            # correlacionable): se le da una delegación para poder continuarlo.
            # Cualquier otro evento tardío de una tarea ya cerrada se ignora.
            new_id = delegation_id if isinstance(delegation_id, str) else "sin-id"
            delegation = _Delegation(new_id, time.monotonic())
            self._delegations[new_id] = delegation
            self._last_delegation_id = new_id

        if delegation is not None and _is_web_search_event(kind, item):
            self._track_search(delegation, kind, nested)
        if kind == "response.created" and delegation is not None:
            delegation.response_done = False
            delegation.calls_in_response = 0
        elif kind == "response.output_text.delta" and delegation is not None:
            delta = nested.get("delta")
            if isinstance(delta, str):
                delegation.text.append(delta)
        elif is_call and isinstance(item, dict):
            self._start_call(delegation, item)
        elif kind in _TERMINAL_RESPONSE_EVENTS:
            if kind != "response.completed":
                logger.warning(
                    "El backend no terminó bien la tarea (%s): %s",
                    kind,
                    json.dumps(nested.get("response", nested.get("error", "")), ensure_ascii=False)[
                        :300
                    ],
                )
            if delegation is not None:
                delegation.response_done = True
                delegation.searches.clear()
                await self._maybe_continue(delegation)

    def _track_search(self, delegation: _Delegation, kind: Any, nested: dict[str, Any]) -> None:
        """Apunta qué búsquedas en internet del backend siguen en marcha."""
        item = nested.get("item")
        item_id = nested.get("item_id") or (item.get("id") if isinstance(item, dict) else None)
        key = str(item_id or "web_search")
        done = kind in ("response.web_search_call.completed", "response.output_item.done")
        if done:
            delegation.searches.discard(key)
        elif key not in delegation.searches:
            delegation.searches.add(key)
            logger.info("El backend busca en internet (%s)", delegation.id)

    def _start_call(self, delegation: _Delegation | None, item: dict[str, Any]) -> None:
        name = str(item.get("name") or "")
        call_id = str(item.get("call_id") or "")
        raw = item.get("arguments")
        arguments: dict[str, Any] | None
        try:
            parsed = json.loads(raw) if isinstance(raw, str) and raw.strip() else {}
            arguments = parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            arguments = None
        if arguments is None:
            logger.warning(
                "Acción %s con argumentos que no son JSON válido: %s", name, str(raw)[:200]
            )
        if delegation is not None:
            delegation.running_calls += 1
            delegation.calls_in_response += 1
            delegation.calls_total += 1
        self._spawn(
            self._run_call(self._client, delegation, name, call_id, arguments), f"action-{name}"
        )

    async def _run_call(
        self,
        client: LiveClient | None,
        delegation: _Delegation | None,
        name: str,
        call_id: str,
        arguments: dict[str, Any] | None,
    ) -> None:
        try:
            if arguments is None:
                result = ActionResult(text=f"Error: los argumentos de '{name}' no son JSON válido.")
            else:
                result = await self._execute(name, arguments)
            if client is None or client is not self._client:
                # La sesión que pidió la acción ya no existe: el resultado no va a otra.
                return
            sent = await client.create_item(
                {"type": "function_call_output", "call_id": call_id, "output": result.text}
            )
            self._own_command(sent, delegation)
            if result.image is not None:
                sent = await client.create_item(
                    {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": LOOK_IMAGE_TEXT},
                            {
                                "type": "input_image",
                                "image_url": result.image.to_data_url(),
                                "detail": "low",
                            },
                        ],
                    }
                )
                self._own_command(sent, delegation)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log_stage_failure("No se pudo devolver el resultado de %s al backend: %s", name, exc)
        finally:
            if delegation is not None:
                delegation.running_calls = max(0, delegation.running_calls - 1)
                with contextlib.suppress(Exception):
                    await self._maybe_continue(delegation)

    async def _execute(self, name: str, arguments: dict[str, Any]) -> ActionResult:
        """Ejecuta una acción del registro (la misma definición que usa MCP)."""
        ctx = ActionContext(
            camera=self._camera,
            avatar=self._hub,
            gallery_dir=str(self._settings.gallery_dir),
            last_frame=self._last_frame,
            extra={
                "trivia": self._trivia,
                "moves": self._moves,
                "gestures": self._gestures,
                "agenda": self._agenda,
                "agenda_baseline": self._session_agenda,
                "faces": self._faces,
            },
        )
        if self._registry is None:
            result = ActionResult(text="Error: no hay acciones disponibles.")
        else:
            result = await self._registry.execute(name, arguments, ctx)
        logger.info("Acción %s(%s) -> %s", name, arguments, result.text)
        if name in ("show_image", "show_talk") and result.text.startswith("Mostrando"):
            self._schedule_image_auto_hide()
        elif name == "hide_image":
            self._cancel_image_auto_hide()
        if ctx.last_frame is not None:
            self._last_frame = ctx.last_frame
        return result

    async def _maybe_continue(self, delegation: _Delegation) -> None:
        """Pide al backend que siga cuando ya tiene todos los resultados."""
        if not delegation.response_done or delegation.running_calls > 0:
            return
        if delegation.calls_in_response == 0:
            self._finish_delegation(delegation)
            return
        delegation.rounds += 1
        if delegation.rounds > max(1, self._live.backend_max_tool_rounds):
            logger.warning(
                "El backend pasó de %d rondas de acciones; no se le pide que siga",
                self._live.backend_max_tool_rounds,
            )
            self._finish_delegation(delegation)
            return
        delegation.calls_in_response = 0
        delegation.response_done = False
        client = self._client
        if client is not None:
            self._own_command(await client.create_response(), delegation)

    def _own_command(self, event_id: str, delegation: _Delegation | None) -> None:
        if delegation is not None:
            self._command_owner[event_id] = delegation.id

    def _on_command_error(self, event: dict[str, Any]) -> None:
        """Si el error responde a un comando de una tarea delegada, se da por perdida.

        Sin esto la tarea esperaría un evento final que nunca llega y el
        avatar se quedaría en ``thinking`` hasta ``DELEGATION_TIMEOUT_S``.
        """
        error = event.get("error")
        client_event_id = error.get("client_event_id") if isinstance(error, dict) else None
        client_event_id = client_event_id or event.get("client_event_id")
        if not isinstance(client_event_id, str):
            return
        owner = self._command_owner.pop(client_event_id, None)
        delegation = self._delegations.get(owner) if owner is not None else None
        if delegation is not None:
            logger.warning("El backend rechazó un comando de la tarea %s; se cierra", owner)
            self._finish_delegation(delegation)

    async def _on_handoff_error(self, event: dict[str, Any]) -> None:
        """GPT-Live no recibió el resultado de una tarea delegada (``Responses handoff incomplete``).

        Pasa cuando el backend no termina su respuesta (por ejemplo, si se queda
        sin tokens buscando en internet). La API no manda ningún evento final de
        esa tarea y GPT-Live no se entera: Sonia se quedaba pensando hasta
        ``DELEGATION_TIMEOUT_S`` (registro del 7 de octubre de 2026). Se da la
        tarea por cerrada y se le pide a GPT-Live que se lo diga al visitante.
        """
        if "handoff" not in self.last_error.lower():
            return
        error = event.get("error")
        ids = [
            event.get("delegation_id"),
            error.get("delegation_id") if isinstance(error, dict) else None,
        ]
        delegation_id = next((i for i in ids if isinstance(i, str)), self._last_delegation_id)
        delegation = self._delegations.get(delegation_id) if delegation_id else None
        logger.warning(
            "La tarea delegada %s se quedó sin resultado: %s",
            delegation.id if delegation is not None else "(sin tarea abierta)",
            json.dumps(event, ensure_ascii=False)[:500],
        )
        if delegation is not None:
            self._finish_delegation(delegation)
        await self.speak(DELEGATION_FAILED_TEXT)

    def _finish_delegation(self, delegation: _Delegation) -> None:
        self._delegations.pop(delegation.id, None)
        if self._last_delegation_id == delegation.id:
            self._last_delegation_id = None
        for event_id in [k for k, v in self._command_owner.items() if v == delegation.id]:
            del self._command_owner[event_id]
        text = " ".join("".join(delegation.text).split())
        calls = delegation.calls_total
        logger.info(
            "Backend (%s, %.1f s, %s): %s",
            delegation.id,
            time.monotonic() - delegation.created_at,
            f"{calls} {'acción' if calls == 1 else 'acciones'}" if calls else "sin acciones",
            text[:300] or "(sin texto)",
        )
        # GPT-Live dirá ahora el resultado: se espera su voz en ``thinking``.
        self._expect_response_until = time.monotonic() + RESPONSE_WAIT_S

    def _on_usage(self, event: dict[str, Any]) -> None:
        window = event.get("context_window")
        ratio = window.get("usage_ratio") if isinstance(window, dict) else None
        usage = event.get("usage")
        seconds = usage.get("seconds") if isinstance(usage, dict) else None
        if isinstance(seconds, int | float):
            self._usage_session_s = float(seconds)
        if isinstance(ratio, int | float):
            self._context_ratio = float(ratio)
        if (
            isinstance(ratio, int | float)
            and ratio >= self._live.context_restart_ratio
            and not self._context_full
        ):
            logger.info("Contexto de GPT-Live al %.0f %%: se renovará la sesión", ratio * 100)
            self._context_full = True
        logger.debug("Uso de GPT-Live: %s s de voz, contexto %s", seconds, ratio)

    # -- interrupción -------------------------------------------------------

    async def interrupt(self, *, tell_model: bool = True) -> None:
        """Calla a Sonia ya (Unity tira lo que tenga en cola)."""
        await self._on_interrupt(tell_model=tell_model)

    async def _on_interrupt(self, *, tell_model: bool = True) -> None:
        """Interrupción desde Unity: se calla la voz en curso y se le pide que escuche."""
        self._touch()
        was_audible = self._audible
        await self._hub.broadcast_json(p.msg_stop_speaking("interrupted"))
        if self._gestures is not None:
            self._gestures.on_interrupt()
        segment, self._segment = self._segment, None
        if segment is not None:
            # El resto de esa respuesta se tira hasta el siguiente silencio.
            self._discard_audio = True
            self._last_closed_uid = segment.uid
        # Unity vació su cola: no hay nada pendiente de reproducir.
        self._playback_done_id = max(self._playback_done_id, self._utterance_counter)
        self._last_closed_deadline = 0.0
        self._playback_end_at = time.monotonic()
        self._clip_mute_until = min(self._clip_mute_until, self._playback_end_at + CLIP_ECHO_TAIL_S)
        self._pending_assistant = []
        client = self._client
        if tell_model and was_audible and client is not None:
            with contextlib.suppress(Exception):
                await client.append_instructions(INTERRUPT_TEXT)
        self._audible = False
        self._settle_after = 0.0
        self._expect_response_until = 0.0
        await self._set_state(AssistantState.IDLE)

    # -- ciclo periódico ----------------------------------------------------

    async def _tick_loop(self) -> None:
        while True:
            await asyncio.sleep(self._tick)
            try:
                await self._tick_once(time.monotonic())
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error en el ciclo del motor GPT-Live")

    async def _tick_once(self, now: float) -> None:
        gap = self._live.segment_gap_ms / 1000.0
        if self._segment is not None and now - self._last_voice_at >= gap:
            await self._close_segment(now)
        if self._discard_audio and now - self._last_voice_at >= gap:
            self._discard_audio = False

        audible = self._segment is not None or (
            self._playback_done_id < self._last_closed_uid and now < self._last_closed_deadline
        )
        if self._audible and not audible:
            self._settle_after = now + SPEECH_HOLD_S
        self._audible = audible

        if (
            self._user_turn_open
            and now - self._last_input_at >= self._live.user_turn_gap_ms / 1000.0
        ):
            await self._finish_user_turn(now)

        for delegation in list(self._delegations.values()):
            if now - delegation.created_at > DELEGATION_TIMEOUT_S:
                logger.warning("La tarea delegada %s no terminó; se olvida", delegation.id)
                self._delegations.pop(delegation.id, None)

        await self._update_activity(now)

        if not audible and now >= self._settle_after:
            await self._set_state(self._rest_state(now))

        if self._trivia is not None:
            await self._trivia.tick(now)

        if self._state is not AssistantState.IDLE:
            self._maybe_look(turn_start=False)

        if self._is_idle(now) and self._client is not None and not self._restarting:
            await self._maybe_renew_session(now)
            if not self._restarting:
                await self._between_turns()
                await self._maybe_showcase(now)

    async def _update_activity(self, now: float) -> None:
        """Le cuenta a Unity si Sonia busca en internet o si una tarea tarda (efectos de la escena)."""
        if any(d.searches for d in self._delegations.values()):
            activity = "search"
        elif any(now - d.created_at >= SLOW_TASK_S for d in self._delegations.values()):
            activity = "think"
        else:
            activity = "none"
        if activity == self._activity:
            return
        self._activity = activity
        logger.debug("Actividad para Unity: %s", activity)
        await self._hub.broadcast_json(p.msg_activity(activity))

    def _session_open(self) -> bool:
        """¿Hay una sesión de GPT-Live oyendo el micro?"""
        return self._client is not None and not self._restarting and self._active

    def _in_conversation(self) -> bool:
        """¿Escucha, piensa o habla Sonia con alguien? (la animación de stand no cuenta)"""
        return self._state is not AssistantState.IDLE

    def _rest_state(self, now: float) -> AssistantState:
        """Estado del avatar cuando Sonia no está hablando."""
        if self._user_turn_open:
            return AssistantState.LISTENING
        if self._delegations or now < self._expect_response_until:
            return AssistantState.THINKING
        return AssistantState.IDLE

    def _is_idle(self, now: float) -> bool:
        return (
            self._state is AssistantState.IDLE
            and not self._audible
            and self._segment is None
            and not self._delegations
            and not self._user_turn_open
            and now >= self._expect_response_until
        )

    # -- renovación de la sesión --------------------------------------------

    async def _maybe_renew_session(self, now: float) -> None:
        """Abre una sesión limpia en un momento de calma si toca."""
        reason = ""
        limit = self._settings.idle_reset_seconds
        playing = self._trivia is not None and self._trivia.active
        if (
            limit > 0
            and not playing
            and self._session_conversation
            and now - self._last_activity >= limit
        ):
            reason = f"{limit:.0f} s sin actividad"
        elif self._context_full:
            reason = "contexto casi lleno"
        else:
            expires = self._client.expires_at if self._client is not None else None
            aged = now - self._session_started_at > HEALTHY_SESSION_S
            if aged and expires is not None and expires - time.time() < EXPIRY_MARGIN_S:
                reason = "la sesión está a punto de caducar"
        if reason:
            await self.restart_session(reason)

    async def restart_session(self, reason: str = "pedido desde el panel") -> bool:
        """Cierra la sesión actual para abrir otra limpia (olvida lo hablado)."""
        if self._client is None or self._restarting:
            return False
        logger.info("Se abre una sesión nueva de GPT-Live (%s)", reason)
        self._restarting = True
        self._last_frame = None
        self._cancel_image_auto_hide()
        await self._hub.hide_image()
        client = self._client
        if client is not None:
            # El bucle de la sesión ve el cierre y reconecta enseguida.
            self._spawn(client.close(), "live-renew")
        return True

    # -- animación de stand -------------------------------------------------

    async def _maybe_showcase(self, now: float) -> None:
        """Un número del stand si Sonia lleva bastante sola.

        Si la frase está en la caché de voces se reproduce tal cual (sin
        gastar ni meter nada en la conversación); si no, se le pide a GPT-Live.
        """
        if self._showcase is None or not self._showcase_enabled or now < self._next_showcase_at:
            return
        if self._trivia is not None and self._trivia.active:
            return
        if now < self._ambient_expected_until:
            return
        bit = self._showcase.next_bit()
        show = self._settings.showcase
        low = max(5.0, show.interval_min_seconds)
        high = max(low, show.interval_max_seconds)
        self._next_showcase_at = now + self._showcase.rng.uniform(low, high)
        client = self._client
        if bit is None or client is None:
            return
        if bit.moment:
            # Mientras se prepara (foto y descripción) no sale otro número.
            self._ambient_expected_until = now + MOMENT_PREP_S
            self._spawn(self._request_moment(client, bit.attention), "showcase")
            return
        recorded = self._voice_cache.get(bit.text) if self._voice_cache is not None else None
        if recorded is not None:
            self._spawn(self.play_clip(recorded, bit.text, attention=bit.attention), "showcase")
            return
        if bit.attention:
            await self._hub.broadcast_json(p.msg_attention(bit.attention))
        self._ambient_expected_until = now + AMBIENT_WAIT_S
        # En segundo plano: el ciclo de 50 ms no puede quedarse esperando a la red.
        self._spawn(self._request_showcase(client, bit.text), "showcase")

    async def _request_showcase(self, client: LiveClient, text: str) -> None:
        try:
            await client.append_commentary(SHOWCASE_TEMPLATE.format(text=text))
        except Exception as exc:  # noqa: BLE001
            logger.debug("No se pudo pedir el número del stand: %s", exc)
            self._ambient_expected_until = 0.0
            return
        logger.info("Número del stand pedido: %s", text)

    async def _request_moment(self, client: LiveClient, attention: str | None) -> None:
        """Un momento del stand: GPT-Live improvisa una invitación con lo que pasa ahora."""
        focus = await self._moment_focus()
        if client is not self._client or not self._is_idle(time.monotonic()):
            # Alguien se puso a hablar mientras se preparaba: ya no toca.
            self._ambient_expected_until = 0.0
            return
        if attention:
            await self._hub.broadcast_json(p.msg_attention(attention))
        self._ambient_expected_until = time.monotonic() + AMBIENT_WAIT_S
        try:
            await client.append_commentary(MOMENT_TEMPLATE.format(focus=focus))
        except Exception as exc:  # noqa: BLE001
            logger.debug("No se pudo pedir el momento del stand: %s", exc)
            self._ambient_expected_until = 0.0
            return
        logger.info("Momento del stand pedido: %s", focus)

    async def _moment_focus(self) -> str:
        """De qué tira el momento: por turnos, la agenda, la cámara y una invitación concreta.

        La agenda solo si hoy hay algo ahora o a continuación: antes del evento,
        entre días o al terminar no se anuncia nada (quien pasa ya está en el DevFest).
        """
        today = self._agenda.today() if self._agenda is not None else ""
        options = ["agenda"] if today else []
        if (
            self._settings.showcase.moment_camera
            and self._camera is not None
            and self._narrator is not None
            and self._policy.enabled
        ):
            options.append("cámara")
        options.append("invitación")
        kind = options[self._moment_turn % len(options)]
        self._moment_turn += 1
        if kind == "agenda":
            return MOMENT_FOCUS["agenda"].format(text=today)
        if kind == "cámara":
            text = await self._moment_scene()
            if text:
                return MOMENT_FOCUS["cámara"].format(text=text)
        return MOMENT_FOCUS["invitación"]

    async def _moment_scene(self) -> str:
        """Lo que ve ahora la cámara para un momento (vacío si no se pudo). La foto no se guarda."""
        assert self._camera is not None and self._narrator is not None
        try:
            frame = await asyncio.wait_for(self._camera.capture(), timeout=CAPTURE_TIMEOUT_S)
            if frame is None:
                return ""
            return await self._narrator.describe(frame)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - sin foto, el momento tira de otra cosa
            logger.debug("Momento del stand sin cámara: %s", exc)
            return ""

    # -- cámara -------------------------------------------------------------

    def _maybe_look(self, *, turn_start: bool) -> None:
        """Describe la cámara en segundo plano si la política lo pide."""
        if self._camera is None or self._narrator is None or not self._policy.enabled:
            return
        if self._vision_task is not None and not self._vision_task.done():
            return
        now = time.monotonic()
        if now - self._last_vision_at < self._live.vision_min_interval_seconds:
            return
        wanted = (
            turn_start and self._policy.should_capture_on_turn_start()
        ) or self._policy.should_capture_periodic(now)
        if not wanted:
            return
        self._last_vision_at = now
        self._vision_task = asyncio.create_task(self._describe_scene(), name="sonia-live-vision")

    async def _describe_scene(self) -> None:
        assert self._camera is not None and self._narrator is not None
        started = time.monotonic()
        try:
            frame = await asyncio.wait_for(self._camera.capture(), timeout=CAPTURE_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001
            logger.warning("No se pudo capturar la cámara: %s", exc)
            self._camera_ok = False
            return
        self._policy.note_captured()
        self._camera_ok = frame is not None
        if frame is None:
            return
        self._last_frame = frame
        self._policy.maybe_save_debug(frame)
        try:
            text = await self._narrator.describe(frame)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log_stage_failure("No se pudo describir la cámara: %s", exc)
            return
        client = self._client
        if not text or client is None:
            return
        known = await self._known_in(frame)
        faces = self._faces
        if known and faces is not None:
            text = f"{text} {faces.known_note(known)}"
        try:
            await client.append_thinking(f"{CAMERA_NOTE_PREFIX} {text}")
        except Exception as exc:  # noqa: BLE001
            logger.debug("No se pudo pasar la nota de la cámara: %s", exc)
            return
        if known and faces is not None:
            await faces.remember(known)
        logger.info("Cámara descrita en %.1f s", time.monotonic() - started)
        logger.debug("Cámara: %s", text)

    # -- caras conocidas (docs/caras.md) ---------------------------------------

    async def _known_in(self, frame: Frame) -> list[Sighting]:
        """Sonia usa la cámara: quién conocido sale en la foto, aunque ya se le dijera hace poco."""
        faces = self._faces
        if faces is None:
            return []
        try:
            sightings = await faces.identify(frame)
        except Exception as exc:  # noqa: BLE001 - sin caras, la foto sigue valiendo
            logger.warning("No se pudieron reconocer caras: %s", exc)
            return []
        if sightings:
            logger.info(
                "Caras en la foto: %s",
                ", ".join(f"{s.match.person.name} ({s.match.score:.2f})" for s in sightings),
            )
        return faces.used(sightings)

    async def _faces_loop(self, faces: FaceWatcher) -> None:
        """Prepara el reconocimiento y, con sesión abierta, revisa la cámara cada poco."""
        schedule = self._agenda.schedule if self._agenda is not None else None
        agenda = self._agenda
        if agenda is not None:
            # Las notas de los ponentes dicen cuándo es su charla con la agenda de ahora.
            faces.follow_agenda(lambda: agenda.schedule)
        try:
            await faces.prepare(schedule)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log_stage_failure("Reconocimiento de caras apagado: %s", exc)
            return
        every = faces.scan_seconds
        if every <= 0 or not faces.ready or self._meeting:
            # En una videollamada los ojos son OBS o la pantalla: cada foto abre una conexión
            # y los nombres ya salen en los recuadros. Ahí solo cuenta cuando Sonia mira.
            return
        while True:
            await asyncio.sleep(every)
            try:
                await self._scan_faces(faces)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - una revisión fallida no para las demás
                logger.debug("Revisión de caras fallida: %s", exc)

    async def _scan_faces(self, faces: FaceWatcher) -> None:
        """Una revisión sola: avisa a Sonia de quien acaba de llegar (una vez cada su plazo)."""
        client = self._client
        if client is None or self._camera is None or self._restarting or not self._active:
            # Sin sesión no hay a quién avisar: en «Solo saludos» y «Fuera» no se mira.
            return
        try:
            frame = await asyncio.wait_for(self._camera.capture(), timeout=CAPTURE_TIMEOUT_S)
        except Exception:  # noqa: BLE001 - la cámara falla a ratos; la próxima revisión, otra
            return
        if frame is None:
            return
        fresh = faces.due(await faces.identify(frame))
        if not fresh:
            return
        if client is not self._client:
            faces.retract(fresh)
            return
        note = faces.arrival_note(fresh)
        try:
            await client.append_thinking(f"{CAMERA_NOTE_PREFIX} {note}")
        except Exception as exc:  # noqa: BLE001
            faces.retract(fresh)
            logger.debug("No se pudo avisar de las caras: %s", exc)
            return
        # Solo cuando la nota llegó: si no, la próxima diría que ya pasó sin que Sonia lo sepa.
        await faces.remember(fresh)
        logger.info(
            "Caras: aviso a Sonia de %s",
            ", ".join(f"{s.match.person.name} ({s.match.score:.2f})" for s in fresh),
        )
        logger.debug("Caras: %s", note)

    # -- imagen en pantalla ---------------------------------------------------

    def _schedule_image_auto_hide(self) -> None:
        self._cancel_image_auto_hide()
        seconds = self._settings.image_auto_hide_seconds
        if seconds <= 0:
            return
        self._image_hide_task = asyncio.create_task(
            self._auto_hide_image(seconds), name="sonia-image-auto-hide"
        )

    def _cancel_image_auto_hide(self) -> None:
        task, self._image_hide_task = self._image_hide_task, None
        if task is not None and not task.done():
            task.cancel()

    async def _auto_hide_image(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
        logger.info("Imagen retirada sola tras %.0f s", seconds)
        self._image_hide_task = None
        await self._hub.hide_image()

    # -- controles del panel ------------------------------------------------

    async def set_active(self, active: bool) -> None:
        """Enciende o apaga GPT-Live. Apagada no hay sesión, así que no gasta."""
        if active == self._active:
            return
        self._active = active
        if active:
            logger.info("GPT-Live encendida: se abre sesión")
            self._next_showcase_at = time.monotonic() + max(
                0.0, self._settings.showcase.first_delay_seconds
            )
            self._active_event.set()
            return
        logger.info("GPT-Live apagada: se cierra la sesión y deja de gastar")
        self._active_event.clear()
        if self._trivia is not None:
            await self._trivia.on_session_lost()
        await self.interrupt(tell_model=False)
        if self._vision_task is not None and not self._vision_task.done():
            self._vision_task.cancel()
        client = self._client
        if client is not None:
            self._restarting = True
            self._spawn(client.close(), "live-off")

    async def play_clip(self, pcm: bytes, text: str, *, attention: str | None = None) -> bool:
        """Reproduce una frase grabada como voz ``ambient`` (sin cambiar de estado).

        No pisa a GPT-Live: si Sonia ya está hablando, no hace nada y devuelve
        ``False``. Mientras suena (y ``CLIP_ECHO_TAIL_S`` después) el micrófono
        manda silencio a GPT-Live: la frase no la dijo él y, si la oyera por
        los altavoces, la contestaría como si se la hubiera dicho un visitante.
        """
        if self._audible or self._segment is not None:
            return False
        hub = self._hub
        if attention:
            await hub.broadcast_json(p.msg_attention(attention))
            # Un baile arranca con un fundido; la voz entra un poco después.
            await asyncio.sleep(0.6 if attention == "dance" else 0.25)
            if self._audible or self._segment is not None:
                return False
        if not pcm:
            return True
        self._utterance_counter += 1
        uid = self._utterance_counter
        now = time.monotonic()
        seconds = len(pcm) / 2 / self._rate
        self._audible = True
        self._last_closed_uid = uid
        self._playback_end_at = max(self._playback_end_at, now) + seconds
        self._last_closed_deadline = self._playback_end_at + PLAYBACK_GRACE_S
        self._clip_uid = uid
        self._clip_mute_until = self._playback_end_at + CLIP_ECHO_TAIL_S
        await hub.broadcast_json(p.msg_speech_start(uid, text, ambient=True))
        await hub.broadcast_json(p.msg_transcript("assistant", text, True))
        chunk = max(2, self._rate // 10 * 2)  # 100 ms
        for start in range(0, len(pcm), chunk):
            await hub.send_audio(
                uid, AudioChunk(pcm=pcm[start : start + chunk], sample_rate=self._rate)
            )
        await hub.send_audio(uid, AudioChunk(pcm=b"", sample_rate=self._rate, is_last=True))
        await hub.broadcast_json(p.msg_speech_end(uid))
        logger.info("Sonia (grabada, %d, %.2f s): %s", uid, seconds, text)
        return True

    async def announce(self, text: str) -> bool:
        """Pide a GPT-Live que diga un aviso en voz alta. Necesita sesión."""
        client = self._client
        text = text.strip()
        if client is None or not text:
            return False
        await client.append_commentary(ANNOUNCE_TEMPLATE.format(text=text))
        self._touch()
        self._expect_response_until = time.monotonic() + RESPONSE_WAIT_S
        logger.info("Aviso pedido desde el panel: %s", text)
        return True

    async def speak(self, prompt: str) -> bool:
        """Le pide a GPT-Live que diga algo ahora (``session.commentary.append``)."""
        client = self._client
        if client is None:
            return False
        try:
            await client.append_commentary(prompt)
        except Exception as exc:  # noqa: BLE001 - la sesión se reconecta sola
            _log_stage_failure("No se pudo pedir a GPT-Live que hable: %s", exc)
            return False
        self._touch()
        self._expect_response_until = time.monotonic() + RESPONSE_WAIT_S
        return True

    async def instruct(self, text: str) -> bool:
        """Añade una instrucción a la sesión sin hacerla hablar."""
        client = self._client
        if client is None:
            return False
        try:
            await client.append_instructions(text)
        except Exception as exc:  # noqa: BLE001
            _log_stage_failure("No se pudo pasar una instrucción a GPT-Live: %s", exc)
            return False
        return True

    def quiet_for(self) -> float:
        """Segundos que Sonia lleva callada según lo que Unity tiene por reproducir (0 si habla)."""
        if self._segment is not None:
            return 0.0
        return max(0.0, time.monotonic() - self._playback_end_at)

    def touch(self) -> None:
        """Hay actividad: retrasa la animación de stand y la sesión nueva por inactividad."""
        self._touch()

    async def _between_turns(self) -> None:
        """Lo que se le pasa a la sesión solo en calma: la hora y los cambios de agenda.

        Nunca mientras alguien habla: un append justo cuando GPT-Live decide si
        delega puede cambiar lo que hace (el 7 de octubre de 2026 una nota de
        reloj al empezar a contestar coincidió con una respuesta de la trivia
        que no se registró).
        """
        client = self._client
        if client is None:
            return
        if self._pending_agenda_note:
            text, self._pending_agenda_note = self._pending_agenda_note, ""
            try:
                await client.append_instructions(text)
            except Exception as exc:  # noqa: BLE001
                _log_stage_failure("No se pudo pasar el cambio de agenda a GPT-Live: %s", exc)
            else:
                logger.info("Cambios de agenda pasados a GPT-Live: %s", text)
        await self._clock_note()

    async def _clock_note(self) -> None:
        """Nota ``[Reloj]`` unos minutos antes de cada charla: la hora y lo que empieza.

        Es la única nota de hora (la de abrir la sesión va en las instrucciones):
        con una por minuto, Sonia decía la hora sin venir a cuento (7 de octubre
        de 2026). Va por ``thinking``, que no la hace hablar, y una por tanda.
        """
        client = self._client
        agenda = self._agenda
        lead = self._settings.agenda.notice_minutes
        if client is None or agenda is None or lead <= 0:
            return
        soon = agenda.starting_soon(timedelta(minutes=lead))
        if soon is None or soon[0] == self._clock_noted:
            return
        self._clock_noted = soon[0]
        note = f"{CLOCK_NOTE_PREFIX} Son las {spoken_time(self._now())}. {soon[1]}"
        try:
            await client.append_thinking(note)
        except Exception as exc:  # noqa: BLE001 - la sesión se reconecta sola
            logger.debug("No se pudo pasar la hora a GPT-Live: %s", exc)
            return
        logger.info("Nota de reloj: %s", note)

    async def _on_agenda_change(self, changes: list[str]) -> None:
        """La agenda cambió en la web: se le contará a la sesión abierta en un momento de calma.

        Las sesiones nuevas ya traen la agenda entera.
        """
        if self._client is None or not changes:
            return
        budget = APPEND_MAX_CHARS - len(AGENDA_CHANGED_TEMPLATE) - len(AGENDA_MORE_TEXT)
        shown: list[str] = []
        for change in changes:
            if sum(len(c) + 1 for c in shown) + len(change) > budget:
                break
            shown.append(change)
        text = AGENDA_CHANGED_TEMPLATE.format(changes=" ".join(shown))
        if len(shown) < len(changes):
            text += AGENDA_MORE_TEXT
        # Si ya había otro pendiente, el nuevo lo incluye: la web solo va a más.
        self._pending_agenda_note = text
        logger.info(
            "Cambios de agenda (%d de %d) a la espera de un momento de calma",
            len(shown),
            len(changes),
        )

    async def set_notes(self, text: str) -> None:
        """Avisos del día: entran ya en la sesión y en las instrucciones de las siguientes."""
        text = text.strip()
        if text == self._notes:
            return
        self._notes = text
        client = self._client
        if client is not None:
            content = NOTES_TEMPLATE.format(text=text) if text else NOTES_CLEARED_TEXT
            with contextlib.suppress(Exception):
                await client.append_instructions(content)
        logger.info("Avisos del día actualizados (%d caracteres)", len(text))

    @property
    def notes(self) -> str:
        return self._notes

    def add_mic_listener(self, listener: Callable[[AudioArray], None]) -> None:
        """``listener(block)`` con cada bloque del micro, haya sesión o no (síncrono y barato)."""
        self._mic_listeners.append(listener)

    def remove_mic_listener(self, listener: Callable[[AudioArray], None]) -> None:
        with contextlib.suppress(ValueError):
            self._mic_listeners.remove(listener)

    def set_mic_muted(self, muted: bool) -> None:
        self._mic_manual_mute = muted
        logger.info("Micrófono %s desde el panel", "silenciado" if muted else "activado")

    @property
    def mic_muted(self) -> bool:
        return self._mic_manual_mute

    def set_gate(self, threshold: float) -> None:
        self._live.gate_rms = max(0.0, float(threshold))
        self._mic.set_threshold(self._live.gate_rms)

    @property
    def presence_available(self) -> bool:
        """¿Tiene la puerta del micro con la cámara? (cámara USB y ``LIVE_PRESENCE_GATE``)."""
        return self._presence is not None

    def set_presence_enabled(self, enabled: bool) -> None:
        """Enciende o apaga la puerta de la cámara (interruptor del panel)."""
        if self._presence is None:
            return
        self._presence.gate.enabled = enabled
        logger.info(
            "Puerta del micro con la cámara %s",
            "encendida: sin nadie delante, GPT-Live no oye"
            if enabled
            else "apagada: GPT-Live oye siempre",
        )

    def set_showcase_enabled(self, enabled: bool) -> None:
        enabled = enabled and not self._meeting
        self._showcase_enabled = enabled
        if enabled:
            self._next_showcase_at = time.monotonic() + max(
                0.0, self._settings.showcase.first_delay_seconds
            )

    @property
    def showcase_enabled(self) -> bool:
        return self._showcase_enabled

    def snapshot(self) -> dict[str, Any]:
        """Lo que el panel necesita saber del motor, en tipos JSON."""
        now = time.monotonic()
        client = self._client
        expires = client.expires_at if client is not None else None
        uptime = now - self._session_started_at if self._session_started_at else 0.0
        current = max(self._usage_session_s, uptime) if client is not None else 0.0
        return {
            "active": self._active,
            "connected": client is not None,
            "session_id": client.session_id if client is not None else "",
            "uptime_s": round(uptime, 1),
            "expires_in_s": round(expires - time.time(), 1) if expires is not None else None,
            "context_ratio": self._context_ratio,
            "state": str(self._state),
            "speaking": self._audible,
            "delegations": len(self._delegations),
            "usage_s": round(self._usage_closed_s + current, 1),
            "mic_level": round(self._mic_level, 4),
            "mic_age_s": round(now - self._last_mic_at, 1) if self._last_mic_at else None,
            "mic_sound_age_s": (
                round(now - self._last_sound_at, 1) if self._last_sound_at else None
            ),
            "mic_muted": self._mic_manual_mute,
            "mic_gate": self._live.gate_rms,
            #: Por qué GPT-Live no oyó el último bloque del micro (vacío si lo oyó).
            "mic_reason": self._mic.reason,
            "mic_presence": (self._presence.snapshot(now) if self._presence is not None else None),
            "camera_enabled": self._camera is not None and self._policy.enabled,
            "camera_ok": self._camera_ok,
            "last_error": self.last_error,
            "trivia": self._trivia.snapshot() if self._trivia is not None else None,
            "gestures": self._gestures.snapshot() if self._gestures is not None else None,
        }

    # -- utilidades -----------------------------------------------------------

    async def _set_state(self, state: AssistantState) -> None:
        if state is self._state:
            return
        previous, self._state = self._state, state
        logger.info("Estado: %s -> %s", previous, state)
        await self._hub.broadcast_json(p.msg_state(state))
        if self._gestures is not None:
            self._gestures.on_state(state)

    def _touch(self) -> None:
        self._last_activity = time.monotonic()
        if self._showcase is not None:
            self._next_showcase_at = max(
                self._next_showcase_at,
                self._last_activity + self._settings.showcase.first_delay_seconds,
            )

    def _spawn(self, coro: Coroutine[Any, Any, Any], name: str) -> None:
        """Lanza una tarea en segundo plano con referencia fuerte y errores al log."""
        task = asyncio.create_task(coro, name=f"sonia-live-{name}")
        self._tasks.add(task)
        task.add_done_callback(self._task_done)

    def _task_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("La tarea %s falló: %r", task.get_name(), task.exception())


#: Marcas de sonido que GPT-Live mete en la transcripción ("[laugh]", "[sigh]").
#: Pueden llegar partidas entre dos turnos ("[sigh" en uno y "]" en el siguiente).
_TAG = re.compile(r"\[[^\[\]]*\]")
_TAG_TAIL = re.compile(r"\[[^\[\]]*$")
_TAG_HEAD = re.compile(r"^[^\[\]]*\]")


#: Cómo se escribe su nombre: «Sonnia», con doble n como Sonnet Code, aunque se
#: diga «Sonia». La transcripción trae lo que se oye; los subtítulos y el panel,
#: lo que se lee.
WRITTEN_NAME = "Sonnia"
_SPOKEN_NAME = re.compile(r"\bson[ií]a\b", re.IGNORECASE)


def _written_name(match: re.Match[str]) -> str:
    word = match.group(0)
    if word.isupper():
        return WRITTEN_NAME.upper()
    return WRITTEN_NAME if word[0].isupper() else WRITTEN_NAME.lower()


def clean_transcript(text: str) -> str:
    """Texto legible de una transcripción: sin marcas de sonido ni espacios de más, y
    con el nombre de Sonnia bien escrito."""
    text = _SPOKEN_NAME.sub(_written_name, text)
    text = _TAG.sub(" ", text)
    text = _TAG_TAIL.sub(" ", text)
    if "[" not in text:
        # Un "]" suelto al principio es la cola de una marca del turno anterior.
        head = _TAG_HEAD.match(text)
        if head is not None and len(head.group(0).strip()) <= 12:
            text = text[head.end() :]
    return " ".join(text.split())


def _pcm16_rms(pcm: bytes) -> float:
    import numpy as np

    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    return float(np.sqrt(np.mean(samples * samples))) if len(samples) else 0.0


def _forward_camera_frame(on_frame: Callable[..., Any], msg: dict[str, Any]) -> None:
    data = msg.get("data_base64")
    if isinstance(data, str) and data:
        on_frame(str(msg.get("mime") or "image/jpeg"), data)
