"""Control de Sonia desde el panel: modos, acciones y estado en lenguaje llano.

Es la capa entre el panel web y el motor. Sabe en qué modo está Sonia
(conversando, solo saludos o fuera), lo aplica al motor y a Unity, guarda lo
que el equipo cambia para que sobreviva a un reinicio y traduce el estado
técnico a frases que entiende cualquiera del stand ("La pantalla de Sonia no
está conectada: abre la app").

Los ajustes (letrero, avisos, volumen, voz, subtítulos, animaciones,
Developer...) son de Sonia, no de un equipo: se guardan en la nube y valen
para todas las Sonias (``SHARED_SETTINGS``). Se cambien desde el panel de
Cloudflare o desde el local, quedan apuntados como pendientes hasta que la
nube los confirma (``CloudLink``), así que un cambio hecho sin internet sube
en cuanto vuelve la conexión. El modo, el modo debug y el gasto son de cada
Sonia: con dos encendidas por error, cada una sigue en el suyo y el panel
deja elegir cuál conversa.

"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import random
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypeGuard

from sonia.actions.gallery import Gallery
from sonia.actions.registry import ActionRegistry
from sonia.config import Settings
from sonia.showcase import ATTENTION_DANCE, ATTENTION_FOURTH_WALL, load_lines
from sonia.types import ActionContext
from sonia.ws import protocol as p

if TYPE_CHECKING:  # pragma: no cover - solo para tipado
    from sonia.guest.mode import GuestMode
    from sonia.live.engine import LiveEngine
    from sonia.live.voicecache import VoiceCache
    from sonia.ws.hub import Hub

__all__ = [
    "DEFAULT_AWAY_MESSAGE",
    "MODES",
    "SHARED_SETTINGS",
    "TUNING_LIMITS",
    "PanelState",
    "StandControl",
    "default_tuning",
    "merge_tuning",
]

logger = logging.getLogger(__name__)

Mode = Literal["conversation", "greeter", "away"]
MODES: tuple[Mode, ...] = ("conversation", "greeter", "away")

DEFAULT_AWAY_MESSAGE = "Me fui a ver una charla, regreso en un momento"

#: Voces integradas de GPT-Live que se ofrecen en el panel.
VOICES = ["marin", "cedar", "coral", "sage", "shimmer", "ballad", "verse", "alloy", "ash", "echo"]

GESTURES = ("greeting", "dance", "fourth_wall", "soft")

#: Todo lo que el panel puede hacer con cada motor.
CAPABILITIES = [
    "modes",
    "say",
    "ask",
    "stop",
    "mute",
    "restart",
    "images",
    "gestures",
    "animations",
    "animation_toggles",
    "subtitles",
    "debug",
    "greet",
    "showcase",
    "volume",
    "mic_gate",
    "voice",
    "notes",
    "voice_cache",
    "tuning",
    "cloud_settings",
    "avatar_editor",
    "guest_avatar_editor",
]

#: Ajustes que se guardan en la nube y comparten todas las Sonias. El modo, el
#: modo debug y el gasto no están: son de cada equipo.
SHARED_SETTINGS: tuple[str, ...] = (
    "away_message",
    "notes",
    "volume",
    "mic_gate",
    "voice",
    "showcase",
    "subtitles",
    "disabled_animations",
    "tuning",
    "avatar",
    "guest_avatar",
)

#: Ajustes de «Developer»: grupo -> valor -> (mínimo, máximo, por defecto). La
#: boca va en multiplicadores de lo que trae la escena de Unity (1 = tal cual) y
#: la cámara en desplazamientos sobre su plano base (metros y grados) más un
#: zoom que estrecha o abre el campo de visión.
TUNING_LIMITS: dict[str, dict[str, tuple[float, float, float]]] = {
    "mouth": {
        "open": (0.0, 2.0, 1.0),  # apertura de vocales y mandíbula
        "jaw": (0.0, 3.0, 1.0),  # mandíbula extra en las sílabas fuertes
        "closure": (0.0, 1.5, 1.0),  # cierre de labios en p, b, m
        "speed": (0.5, 2.0, 1.0),  # rapidez de la boca
    },
    "camera": {
        "height": (-0.5, 0.5, 0.0),  # metros, + sube
        "distance": (-0.6, 1.0, 0.0),  # metros, + se aleja
        "side": (-0.4, 0.4, 0.0),  # metros, + a la derecha de la pantalla
        "zoom": (0.5, 2.0, 1.0),  # >1 acerca (campo de visión más estrecho)
        "tilt": (-15.0, 15.0, 0.0),  # grados, + mira más abajo
    },
}

#: Tope del texto de los avisos del día.
NOTES_MAX_LEN = 1_000

#: Tope del texto del letrero de «Fuera».
AWAY_MESSAGE_MAX_LEN = 140

#: Primer saludo al entrar en el modo saludos.
GREETER_FIRST_DELAY_S = 4.0

#: Antes de grabar las frases fijas al arrancar se deja respirar a la sesión.
VOICE_WARMUP_DELAY_S = 20.0

#: Sin bloques del micrófono durante esto, se da por caído.
MIC_STALE_S = 3.0

#: Sin ningún sonido (ni ruido de fondo) durante esto, el micro no capta nada.
MIC_DEAF_S = 30.0

#: Cada cuánto se guarda el gasto del día.
USAGE_SAVE_S = 30.0


def default_tuning() -> dict[str, dict[str, float]]:
    """Ajustes de «Developer» sin tocar: la boca y la cámara como vienen de la escena."""
    return {
        group: {name: limits[2] for name, limits in values.items()}
        for group, values in TUNING_LIMITS.items()
    }


def merge_tuning(*sources: Any) -> dict[str, dict[str, float]]:
    """Ajustes de «Developer» completos a partir de los valores por defecto.

    Cada fuente (grupo -> valor -> número) se mezcla encima de la anterior,
    recortada a ``TUNING_LIMITS``. Lo desconocido o mal formado se ignora, así
    que sirve igual para lo guardado en disco, lo que manda la nube y los
    cambios parciales de un deslizador del panel.
    """
    result = default_tuning()
    for source in sources:
        if not isinstance(source, dict):
            continue
        for group, values in source.items():
            limits = TUNING_LIMITS.get(group)
            if limits is None or not isinstance(values, dict):
                continue
            for name, value in values.items():
                bounds = limits.get(name)
                if bounds is None or not _is_number(value) or not math.isfinite(value):
                    continue
                result[group][name] = round(max(bounds[0], min(bounds[1], float(value))), 4)
    return result


@dataclass
class PanelState:
    """Lo que el equipo cambia desde el panel y se guarda en disco.

    Es la copia local: los ajustes de ``SHARED_SETTINGS`` mandan desde la nube
    en cuanto hay conexión, y lo de aquí es lo último que se supo de ella más
    lo cambiado en este equipo que aún no ha subido (``pending_settings``).
    """

    mode: Mode = "conversation"
    away_message: str = DEFAULT_AWAY_MESSAGE
    notes: str = ""
    volume: float = 1.0
    mic_gate: float | None = None
    voice: str | None = None
    showcase: bool | None = None
    #: Subtítulos en la pantalla de Unity.
    subtitles: bool = True
    #: Clips que Sonia no usa por su cuenta (bloque «Animaciones»).
    disabled_animations: list[str] = field(default_factory=list)
    #: Ajustes de «Developer»: boca y cámara (ver ``TUNING_LIMITS``).
    tuning: dict[str, dict[str, float]] = field(default_factory=default_tuning)
    #: Definición del avatar de Genies guardada en el editor de personaje (JSON en
    #: texto); ``None``: el personaje que trae la app.
    avatar: str | None = None
    #: Lo mismo para el invitado del Modo Jean; ``None``: su avatar de prueba.
    guest_avatar: str | None = None
    #: Modo debug: Sonia quieta (sin GPT-Live ni nada automático) para pruebas visuales.
    debug: bool = False
    #: Gasto del día: segundos de sesión de GPT-Live acumulados en ``usage_date``
    #: (sobrevive a los reinicios del orquestador).
    usage_date: str = ""
    usage_seconds: float = 0.0
    #: Revisión de los ajustes compartidos que mandó la nube por última vez.
    cloud_rev: int = 0
    #: Ajustes compartidos cambiados en este equipo que la nube aún no ha confirmado.
    pending_settings: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> PanelState:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError) as exc:
            logger.warning("No se pudo leer el estado del panel (%s); se empieza de cero", exc)
            return cls()
        state = cls()
        if not isinstance(raw, dict):
            return state
        if raw.get("mode") in MODES:
            state.mode = raw["mode"]
        for name in ("away_message", "notes", "voice", "usage_date"):
            if isinstance(raw.get(name), str):
                setattr(state, name, raw[name])
        with contextlib.suppress(ValueError):
            state.avatar = _normalize_shared("avatar", raw.get("avatar"))
        with contextlib.suppress(ValueError):
            state.guest_avatar = _normalize_shared("guest_avatar", raw.get("guest_avatar"))
        for name in ("volume", "mic_gate", "usage_seconds"):
            value = raw.get(name)
            if _is_number(value):
                setattr(state, name, float(value))
        for name in ("showcase", "subtitles", "debug"):
            if isinstance(raw.get(name), bool):
                setattr(state, name, raw[name])
        disabled = raw.get("disabled_animations")
        if isinstance(disabled, list):
            state.disabled_animations = sorted({c for c in disabled if isinstance(c, str) and c})
        state.tuning = merge_tuning(raw.get("tuning"))
        if isinstance(raw.get("cloud_rev"), int) and not isinstance(raw["cloud_rev"], bool):
            state.cloud_rev = max(0, raw["cloud_rev"])
        pending = raw.get("pending_settings")
        if isinstance(pending, list):
            state.pending_settings = sorted({k for k in pending if k in SHARED_SETTINGS})
        return state

    def save(self, path: Path) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
        except OSError as exc:
            logger.warning("No se pudo guardar el estado del panel: %s", exc)


@dataclass(frozen=True)
class _GreeterBit:
    text: str
    gesture: str | None


@dataclass
class _Material:
    """Frases fijas: saludos, frases del stand, cantos y entradas del Modo Jean."""

    greetings: list[str] = field(default_factory=list)
    phrases: list[str] = field(default_factory=list)
    songs: list[str] = field(default_factory=list)
    #: Lo que dice Sonia al presentar al invitado sorpresa (Modo Jean).
    guest_intros: list[str] = field(default_factory=list)

    @classmethod
    def from_dir(cls, directory: Path) -> _Material:
        return cls(
            greetings=load_lines(directory / "saludos.md"),
            phrases=load_lines(directory / "frases.md"),
            songs=load_lines(directory / "cantos.md"),
            guest_intros=load_lines(directory / "invitado.md"),
        )

    def all_texts(self) -> list[str]:
        return [*self.greetings, *self.phrases, *self.songs, *self.guest_intros]


class StandControl:
    """Estado y acciones del panel sobre el motor GPT-Live (o el anterior)."""

    def __init__(
        self,
        settings: Settings,
        *,
        hub: Hub,
        registry: ActionRegistry | None,
        engine: LiveEngine,
        voice_cache: VoiceCache | None = None,
        material: _Material | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._settings = settings
        self._hub = hub
        self._registry = registry
        self._engine = engine
        self._voice_cache = voice_cache
        self._material = material or _Material.from_dir(settings.showcase_dir)
        self._rng = rng or random.Random()
        self._state_path = Path(settings.panel.state_file)
        self.state = PanelState.load(self._state_path)
        # Lo que trae este equipo en su .env: un ajuste compartido a None
        # (nunca tocado desde el panel) vuelve a esto.
        self._default_voice = settings.live.voice
        self._default_gate = settings.live.gate_rms
        self._default_showcase = engine.showcase_enabled
        #: Ajuste compartido -> número del último cambio hecho aquí sin confirmar por la nube.
        self._pending = {key: n for n, key in enumerate(self.state.pending_settings, start=1)}
        self._settings_seq = len(self._pending)
        self._settings_listeners: list[Callable[[], None]] = []
        #: Conexión con la nube: ``off`` (sin token), ``offline`` u ``online``.
        self._cloud_state = "off"
        #: ¿Llegaron ya los ajustes de la nube en esta conexión?
        self._cloud_synced = False
        self._tasks: set[asyncio.Task[Any]] = set()
        self._loop_task: asyncio.Task[None] | None = None
        self._next_greet_at = 0.0
        self._last_greeting: str | None = None
        self._image: dict[str, Any] | None = None
        #: Clips que Unity dice tener (mensaje ``animations`` al conectar).
        self._animations: list[dict[str, str]] = []
        #: Clip del catálogo que suena ahora en Unity (``animation_playing``).
        self._current_animation: str | None = None
        #: ¿Está la pantalla de Sonia en la escena de editar personaje?
        self._avatar_editor_open = False
        #: De quién es el personaje que se edita: "sonia" o "guest" (Jean).
        self._avatar_editor_target = "sonia"
        #: Modo Jean (invitado sorpresa); solo con nube (lo engancha ``attach_guest``).
        self._guest: GuestMode | None = None
        #: Segundos de sesión de arranques anteriores del mismo día.
        self._usage_base = 0.0
        self._last_usage_save = time.monotonic()
        self._roll_usage_day(engine_seconds=0.0)
        hub.add_listener(self._watch_outgoing)
        hub.on(p.MSG_ANIMATIONS, self._on_animations)
        hub.on(p.MSG_ANIMATION_PLAYING, self._on_animation_playing)
        hub.on(p.MSG_AVATAR_EDITOR, self._on_avatar_editor)
        hub.on(p.MSG_AVATAR_SAVED, self._on_avatar_saved)
        hub.on(p.MSG_GUEST_STATE, self._on_guest_state)

    # -- ciclo de vida --------------------------------------------------------

    @property
    def capabilities(self) -> list[str]:
        caps = list(CAPABILITIES)
        if self._guest is not None:
            caps.append("guest_mode")
        return caps

    def attach_guest(self, guest: GuestMode) -> None:
        """Engancha el Modo Jean (lo crea la CLI cuando hay nube)."""
        self._guest = guest

    @property
    def guest_intro_lines(self) -> list[str]:
        """Frases con las que Sonia presenta al invitado (se graban con «Preparar voces»)."""
        return self._material.guest_intros

    @property
    def _guest_active(self) -> bool:
        return self._guest is not None and self._guest.active

    async def guest_changed(self) -> None:
        """El Modo Jean empezó o terminó: GPT-Live y el modo se ajustan."""
        await self._apply_mode(self.state.mode, announce=False)

    async def start(self) -> None:
        """Aplica lo guardado y arranca el bucle de saludos. Antes de ``engine.run()``."""
        state = self.state
        engine = self._engine
        if state.voice in VOICES:
            self._settings.live.voice = state.voice
        if state.mic_gate is not None:
            engine.set_gate(state.mic_gate)
        if state.showcase is not None:
            engine.set_showcase_enabled(state.showcase)
        if state.notes:
            await engine.set_notes(state.notes)
        await self._hub.set_sticky("volume", p.msg_set_volume(state.volume))
        await self._hub.set_sticky("subtitles", p.msg_set_subtitles(state.subtitles))
        await self._hub.set_sticky(
            "disabled_animations", p.msg_set_disabled_animations(state.disabled_animations)
        )
        await self._hub.set_sticky("debug", p.msg_set_debug(state.debug))
        await self._hub.set_sticky("tuning", p.msg_set_tuning(state.tuning))
        await self._hub.set_sticky("avatar", p.msg_set_avatar(state.avatar))
        await self._hub.set_sticky("guest_avatar", p.msg_set_guest_avatar(state.guest_avatar))
        await self._apply_mode(state.mode, announce=False)
        if state.debug:
            logger.info("El panel dejó a Sonia en modo debug: quieta y sin GPT-Live")
        elif state.mode != "conversation":
            logger.info("El panel dejó a Sonia en modo %s: no se abre GPT-Live", state.mode)
        self._loop_task = asyncio.create_task(self._loop(), name="sonia-panel-loop")
        if self._voice_cache is not None and self._settings.live.api_key and not state.debug:
            self._spawn(self._prepare_voices(delay=VOICE_WARMUP_DELAY_S), "voice-warmup")

    async def stop(self) -> None:
        if self._guest is not None:
            await self._guest.close()
        self._save_usage()
        tasks = [t for t in [self._loop_task, *self._tasks] if t is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # -- modos ----------------------------------------------------------------

    @property
    def mode(self) -> Mode:
        return self.state.mode

    async def set_mode(self, mode: Mode) -> None:
        if mode == self.state.mode:
            return
        logger.info("Panel: modo %s -> %s", self.state.mode, mode)
        self.state.mode = mode
        self._save()
        await self._apply_mode(mode, announce=True)

    async def _apply_mode(self, mode: Mode, *, announce: bool) -> None:
        engine = self._engine
        hub = self._hub
        if mode == "away":
            await engine.set_active(False)
            await hub.hide_image()
            await hub.set_sticky("presence", p.msg_presence(False, self._away_message))
            return
        await hub.set_sticky("presence", p.msg_presence(True, self._away_message))
        if mode == "conversation":
            # En modo debug, con el editor de personaje en pantalla o con el invitado
            # del Modo Jean no se abre GPT-Live.
            await engine.set_active(
                not self.state.debug and not self._avatar_editor_open and not self._guest_active
            )
        else:
            await engine.set_active(False)
            self._next_greet_at = time.monotonic() + GREETER_FIRST_DELAY_S

    @property
    def _away_message(self) -> str:
        return self.state.away_message.strip() or DEFAULT_AWAY_MESSAGE

    # -- bucle de saludos -----------------------------------------------------

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            try:
                if self._avatar_editor_open and self._hub.client_count == 0:
                    # La pantalla se cerró con el editor abierto: Sonia vuelve a su modo.
                    await self._set_avatar_editor_open(False)
                if time.monotonic() - self._last_usage_save >= USAGE_SAVE_S:
                    self._save_usage()
                if (
                    self.state.mode == "greeter"
                    and not self.state.debug
                    and not self._avatar_editor_open
                    and not self._guest_active
                    and time.monotonic() >= self._next_greet_at
                ):
                    self._schedule_next_greeting()
                    await self.greet()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error en el modo saludos")

    def _schedule_next_greeting(self) -> None:
        panel = self._settings.panel
        low = max(5.0, panel.greeter_interval_min_seconds)
        high = max(low, panel.greeter_interval_max_seconds)
        self._next_greet_at = time.monotonic() + self._rng.uniform(low, high)

    def _next_bit(self, kind: str | None = None) -> _GreeterBit | None:
        material = self._material
        roll = self._rng.random()
        if kind == "greeting" or (kind is None and roll < 0.6 and material.greetings):
            pool, gesture = material.greetings, "greeting"
        elif kind is None and roll < 0.85 and material.phrases:
            pool, gesture = material.phrases, ATTENTION_FOURTH_WALL
        elif material.songs:
            pool, gesture = material.songs, ATTENTION_DANCE
        else:
            pool, gesture = material.greetings or material.phrases, "greeting"
        if not pool:
            return None
        candidates = [t for t in pool if t != self._last_greeting] or pool
        text = self._rng.choice(candidates)
        self._last_greeting = text
        return _GreeterBit(text, gesture)

    async def greet(self, kind: str | None = None) -> tuple[bool, str]:
        """Un saludo con frase grabada (o solo el gesto si aún no está grabada)."""
        if self.state.mode == "away":
            return False, "Sonia está fuera. Tráela de vuelta para que salude."
        bit = self._next_bit(kind)
        if bit is None:
            await self._hub.broadcast_json(p.msg_attention("greeting"))
            return True, "Sonia saluda con la mano."
        pcm = self._voice_cache.get(bit.text) if self._voice_cache is not None else None
        if pcm is None:
            if bit.gesture:
                await self._hub.broadcast_json(p.msg_attention(bit.gesture))
            return (
                True,
                "Sonia saluda con un gesto (la frase aún no está grabada: usa «Preparar voces»).",
            )
        played = await self._engine.play_clip(pcm, bit.text, attention=bit.gesture)
        if not played:
            return False, "Sonia está hablando ahora; prueba en un momento."
        return True, f"Sonia dice: «{bit.text}»"

    # -- voces grabadas -------------------------------------------------------

    async def _prepare_voices(self, delay: float = 0.0) -> int:
        if self._voice_cache is None:
            return 0
        if delay:
            await asyncio.sleep(delay)
        return await self._voice_cache.prepare(self._material.all_texts())

    def _voice_cache_status(self) -> dict[str, Any]:
        cache = self._voice_cache
        texts = self._material.all_texts()
        if cache is None:
            return {"ready": 0, "total": len(texts), "busy": False, "error": ""}
        return {
            "ready": cache.count_ready(texts),
            "total": len(set(t.strip() for t in texts if t.strip())),
            "busy": cache.busy,
            "error": cache.last_error,
        }

    # -- acciones -------------------------------------------------------------

    async def act(self, action: str, params: dict[str, Any]) -> tuple[bool, str]:
        """Ejecuta una acción del panel. Nunca lanza: los fallos vuelven como texto."""
        handler = getattr(self, f"_act_{action}", None)
        if handler is None:
            return False, f"Acción desconocida: {action}"
        try:
            result: tuple[bool, str] = await handler(params)
        except _BadRequest as exc:
            return False, str(exc)
        except Exception as exc:
            logger.exception("La acción del panel %s falló", action)
            return False, f"No se pudo: {exc}"
        logger.info("Panel: %s %s -> %s", action, _summary(params), result[1])
        return result

    def _need_present(self) -> None:
        if self.state.mode == "away":
            raise _BadRequest("Sonia está fuera. Tráela de vuelta primero.")

    async def _act_set_mode(self, params: dict[str, Any]) -> tuple[bool, str]:
        mode = params.get("mode")
        if mode not in MODES:
            raise _BadRequest("Modo no válido.")
        if self._guest_active and mode != self.state.mode:
            raise _BadRequest("Termina antes el Modo Jean: Sonia no está en el stand.")
        await self.set_mode(mode)
        return True, {
            "conversation": "Sonia vuelve a conversar.",
            "greeter": "Sonia solo saluda: no conversa ni gasta.",
            "away": "Sonia se va de la pantalla y deja el letrero.",
        }[mode]

    async def _act_set_away_message(self, params: dict[str, Any]) -> tuple[bool, str]:
        text = _text(params, "text", max_len=AWAY_MESSAGE_MAX_LEN)
        await self._set_shared("away_message", text or DEFAULT_AWAY_MESSAGE)
        return True, "Letrero actualizado."

    async def _act_say(self, params: dict[str, Any]) -> tuple[bool, str]:
        text = _text(params, "text", max_len=400, required=True)
        self._need_present()
        if self.state.mode == "conversation":
            if not await self._engine.announce(text):
                raise _BadRequest("Sonia no está conectada ahora mismo; prueba en unos segundos.")
            return True, "Sonia lo dirá en un momento."
        # Solo saludos: se graba con su voz (una sesión corta) y se reproduce.
        if self._voice_cache is None or not self._settings.live.api_key:
            raise _BadRequest("No se puede grabar la frase: falta la clave de GPT-Live.")
        self._spawn(self._record_and_play(text), "panel-say")
        return True, "Grabando el aviso con su voz; lo dirá en unos segundos."

    async def _record_and_play(self, text: str) -> None:
        assert self._voice_cache is not None
        pcm = self._voice_cache.get(text)
        if pcm is None:
            try:
                pcm = await self._voice_cache.record(text)
            except Exception as exc:  # noqa: BLE001
                logger.warning("No se pudo grabar el aviso: %s", exc)
                return
        if self.state.mode != "away":
            await self._engine.play_clip(pcm, text, attention="soft")

    async def _act_ask(self, params: dict[str, Any]) -> tuple[bool, str]:
        text = _text(params, "text", max_len=400, required=True)
        if self.state.mode != "conversation":
            raise _BadRequest("Sonia no está conversando. Pásala a «Conversando» primero.")
        await self._engine.submit_text(text)
        return True, "Enviado. Sonia responderá en voz alta."

    async def _act_stop(self, params: dict[str, Any]) -> tuple[bool, str]:
        await self._engine.interrupt()
        return True, "Sonia se calla."

    async def _act_mute(self, params: dict[str, Any]) -> tuple[bool, str]:
        engine = self._engine
        muted = _flag(params, "muted")
        engine.set_mic_muted(muted)
        return True, "Micrófono silenciado: Sonia no oye." if muted else "Micrófono activado."

    async def _act_restart(self, params: dict[str, Any]) -> tuple[bool, str]:
        engine = self._engine
        if self.state.mode != "conversation":
            raise _BadRequest("Sonia no está conversando; no hay conversación que reiniciar.")
        if not await engine.restart_session("pedido desde el panel"):
            raise _BadRequest("Ya se está conectando; espera unos segundos.")
        return True, "Conversación nueva: Sonia olvida lo hablado y empieza de cero."

    async def _act_show_image(self, params: dict[str, Any]) -> tuple[bool, str]:
        self._need_present()
        image_id = _text(params, "image_id", max_len=120, required=True)
        caption = _text(params, "caption", max_len=120) or None
        if self._registry is None or "show_image" not in self._registry:
            raise _BadRequest("No hay acción para mostrar imágenes.")
        ctx = ActionContext(
            camera=None, avatar=self._hub, gallery_dir=str(self._settings.gallery_dir)
        )
        args: dict[str, Any] = {"image_id": image_id}
        if caption:
            args["caption"] = caption
        result = await self._registry.execute("show_image", args, ctx)
        return result.text.startswith("Mostrando"), result.text

    async def _act_hide_image(self, params: dict[str, Any]) -> tuple[bool, str]:
        await self._hub.hide_image()
        return True, "Imagen retirada."

    async def _act_gesture(self, params: dict[str, Any]) -> tuple[bool, str]:
        self._need_present()
        category = params.get("category")
        if category not in GESTURES:
            raise _BadRequest("Gesto no válido.")
        await self._hub.broadcast_json(p.msg_attention(str(category)))
        return True, "Hecho."

    async def _act_animation(self, params: dict[str, Any]) -> tuple[bool, str]:
        self._need_present()
        clip = _text(params, "clip", max_len=80, required=True)
        if self._hub.client_count == 0:
            raise _BadRequest("La pantalla de Sonia no está conectada.")
        if not self._animations:
            raise _BadRequest(
                "La app de Sonia no ha mandado su lista de animaciones: actualízala o ábrela otra vez."
            )
        if clip not in {a["clip"] for a in self._animations}:
            raise _BadRequest("Esa animación no está en la app de Sonia.")
        await self._hub.broadcast_json(p.msg_play_animation(clip))
        return True, f"Sonia hace «{clip}»."

    async def _act_set_animation_enabled(self, params: dict[str, Any]) -> tuple[bool, str]:
        clip = _text(params, "clip", max_len=80, required=True)
        enabled = _flag(params, "enabled")
        known = {a["clip"] for a in self._animations}
        if known and clip not in known:
            raise _BadRequest("Esa animación no está en la app de Sonia.")
        disabled = set(self.state.disabled_animations)
        if enabled:
            disabled.discard(clip)
        else:
            disabled.add(clip)
        await self._set_shared("disabled_animations", sorted(disabled))
        return True, (
            f"Sonia vuelve a usar «{clip}» por su cuenta."
            if enabled
            else f"Sonia ya no hará «{clip}» por su cuenta (sigue disponible en su botón)."
        )

    async def _act_open_avatar_editor(self, params: dict[str, Any]) -> tuple[bool, str]:
        target = params.get("target", "sonia")
        if target not in p.AVATAR_TARGETS:
            raise _BadRequest("¿De quién es el personaje: de Sonia o de Jean?")
        self._need_present()
        if self._hub.client_count == 0:
            raise _BadRequest("La pantalla de Sonia no está conectada.")
        if self._guest_active:
            raise _BadRequest("Termina antes el Modo Jean.")
        self._avatar_editor_target = str(target)
        await self._hub.broadcast_json(p.msg_open_avatar_editor(str(target)))
        who = "de Jean" if target == "guest" else "de Sonia"
        return True, (
            f"La pantalla de Sonia pasa al editor del personaje {who}: edítalo allí con el ratón y "
            "pulsa Guardar. Mientras tanto Sonia no conversa."
        )

    async def _act_close_avatar_editor(self, params: dict[str, Any]) -> tuple[bool, str]:
        await self._hub.broadcast_json(p.msg_close_avatar_editor())
        return True, "Editor de personaje cerrado sin guardar: Sonia vuelve."

    async def _act_set_guest_mode(self, params: dict[str, Any]) -> tuple[bool, str]:
        active = _flag(params, "active")
        guest = self._guest
        if guest is None:
            raise _BadRequest(
                "Esta Sonia no tiene el Modo Jean: hace falta conectarla a la nube "
                "(PANEL_CLOUD_TOKEN)."
            )
        if active:
            self._need_present()
            if self._hub.client_count == 0:
                raise _BadRequest("La pantalla de Sonia no está conectada.")
            if self._avatar_editor_open:
                raise _BadRequest("Cierra antes el editor de personaje.")
            ok, message = await guest.start()
        else:
            ok, message = await guest.stop()
        if not ok:
            raise _BadRequest(message)
        return True, message

    async def _act_guest_animation(self, params: dict[str, Any]) -> tuple[bool, str]:
        clip = _text(params, "clip", max_len=80, required=True)
        if self._guest is None or self._guest.phase not in ("entering", "live"):
            raise _BadRequest("El invitado no está en el stand.")
        known = {a["clip"] for a in self._animations}
        if known and clip not in known:
            raise _BadRequest("Esa animación no está en la app de Sonia.")
        await self._hub.broadcast_json(p.msg_guest_animation(clip))
        return True, "Hecho."

    async def _act_reset_avatar(self, params: dict[str, Any]) -> tuple[bool, str]:
        target = params.get("target", "sonia")
        if target not in p.AVATAR_TARGETS:
            raise _BadRequest("¿De quién es el personaje: de Sonia o de Jean?")
        if target == "guest":
            if self.state.guest_avatar is None:
                return True, "Jean ya tiene el avatar de prueba de la app."
            await self._set_shared("guest_avatar", None)
            return True, "Jean vuelve al avatar de prueba de la app (en todas las Sonias)."
        if self.state.avatar is None:
            return True, "Sonia ya tiene el personaje de la app."
        await self._set_shared("avatar", None)
        return True, "Sonia vuelve al personaje que trae la app (en todas las Sonias)."

    async def _act_greet(self, params: dict[str, Any]) -> tuple[bool, str]:
        return await self.greet("greeting")

    async def _act_showcase(self, params: dict[str, Any]) -> tuple[bool, str]:
        enabled = _flag(params, "enabled")
        await self._set_shared("showcase", enabled)
        return True, (
            "Sonia dirá frases y bailará sola cuando no haya nadie."
            if enabled
            else "Sonia ya no dirá frases ni bailará sola."
        )

    async def _act_set_debug(self, params: dict[str, Any]) -> tuple[bool, str]:
        enabled = _flag(params, "enabled")
        if enabled == self.state.debug:
            return True, "Modo debug activado." if enabled else "Modo debug desactivado."
        self.state.debug = enabled
        self._save()
        await self._hub.set_sticky("debug", p.msg_set_debug(enabled))
        if enabled:
            logger.info("Panel: modo debug activado; GPT-Live apagada y Sonia quieta")
            await self._engine.set_active(False)
            return True, (
                "Modo debug: Sonia se queda quieta y desconectada de OpenAI. "
                "Los botones del panel siguen funcionando."
            )
        logger.info("Panel: modo debug desactivado; vuelve el modo %s", self.state.mode)
        await self._apply_mode(self.state.mode, announce=False)
        return True, "Modo debug desactivado: Sonia vuelve a su modo normal."

    async def _act_set_subtitles(self, params: dict[str, Any]) -> tuple[bool, str]:
        enabled = _flag(params, "enabled")
        await self._set_shared("subtitles", enabled)
        return True, (
            "Subtítulos visibles en la pantalla."
            if enabled
            else "Subtítulos ocultos: en la pantalla no sale lo que se dice."
        )

    async def _act_set_volume(self, params: dict[str, Any]) -> tuple[bool, str]:
        value = _number(params, "value", 0.0, 1.5)
        await self._set_shared("volume", value)
        return True, f"Volumen al {value * 100:.0f} %."

    async def _act_set_mic_gate(self, params: dict[str, Any]) -> tuple[bool, str]:
        value = _number(params, "value", 0.0, 0.2)
        await self._set_shared("mic_gate", value)
        if value <= 0:
            return True, "Filtro de ruido apagado: Sonia oye todo."
        return True, "Filtro de ruido ajustado."

    async def _act_set_voice(self, params: dict[str, Any]) -> tuple[bool, str]:
        voice = params.get("voice")
        if voice not in VOICES:
            raise _BadRequest("Voz no válida.")
        if voice == self._settings.live.voice:
            return True, "Esa voz ya está puesta."
        await self._set_shared("voice", str(voice))
        return True, f"Voz cambiada a {voice}. La conversación empieza de nuevo."

    async def _act_set_notes(self, params: dict[str, Any]) -> tuple[bool, str]:
        text = _text(params, "text", max_len=NOTES_MAX_LEN)
        await self._set_shared("notes", text)
        return True, "Avisos guardados. Sonia ya los conoce." if text else "Avisos borrados."

    async def _act_set_tuning(self, params: dict[str, Any]) -> tuple[bool, str]:
        changes = {group: params[group] for group in TUNING_LIMITS if group in params}
        if not changes or not all(isinstance(values, dict) for values in changes.values()):
            raise _BadRequest("Faltan los valores de la boca o de la cámara.")
        await self._set_shared("tuning", merge_tuning(self.state.tuning, changes))
        return True, "Ajuste aplicado."

    async def _act_reset_tuning(self, params: dict[str, Any]) -> tuple[bool, str]:
        part = params.get("part", "all")
        if part not in (*TUNING_LIMITS, "all"):
            raise _BadRequest("¿Qué hay que restablecer: la boca, la cámara o todo?")
        defaults = default_tuning()
        if part == "all":
            tuning = defaults
        else:
            tuning = merge_tuning(self.state.tuning, {part: defaults[part]})
        await self._set_shared("tuning", tuning)
        return True, {
            "mouth": "Boca como viene de la escena.",
            "camera": "Cámara en su encuadre de siempre.",
            "all": "Boca y cámara como vienen de la escena.",
        }[str(part)]

    async def _act_prepare_voices(self, params: dict[str, Any]) -> tuple[bool, str]:
        if self._voice_cache is None:
            raise _BadRequest("No hay caché de voces.")
        if not self._settings.live.api_key:
            raise _BadRequest("Falta la clave de GPT-Live para grabar las frases.")
        if self._voice_cache.busy:
            return True, "Ya se están grabando."
        missing = self._voice_cache.missing(self._material.all_texts())
        if not missing:
            return True, "Todas las frases ya están grabadas."
        self._spawn(self._prepare_voices(), "voice-prepare")
        return True, f"Grabando {len(missing)} frases; tarda unos segundos por frase."

    # -- ajustes compartidos (nube) --------------------------------------------

    async def _set_shared(self, key: str, value: Any) -> None:
        """Un ajuste compartido cambiado desde un panel: se aplica y queda pendiente de subir."""
        if _same(getattr(self.state, key), value):
            return
        await self._apply_shared(key, value)
        self._settings_seq += 1
        self._pending[key] = self._settings_seq
        self.state.pending_settings = sorted(self._pending)
        self._save()
        for listener in list(self._settings_listeners):
            try:
                listener()
            except Exception:
                logger.exception("Error avisando de un ajuste cambiado")

    async def _apply_shared(self, key: str, value: Any) -> None:
        """Aplica un ajuste compartido ya validado al estado, al motor y a Unity."""
        state = self.state
        engine = self._engine
        hub = self._hub
        if key == "away_message":
            state.away_message = value
            if state.mode == "away":
                await hub.set_sticky("presence", p.msg_presence(False, self._away_message))
        elif key == "notes":
            await engine.set_notes(value)
            state.notes = value
        elif key == "volume":
            state.volume = value
            await hub.set_sticky("volume", p.msg_set_volume(value))
        elif key == "mic_gate":
            state.mic_gate = value
            engine.set_gate(self._default_gate if value is None else value)
        elif key == "voice":
            state.voice = value
            voice = self._default_voice if value is None else value
            if voice != self._settings.live.voice:
                self._settings.live.voice = voice
                await engine.restart_session(f"voz cambiada a {voice}")
                if self._voice_cache is not None and self._settings.live.api_key:
                    self._spawn(self._prepare_voices(delay=5.0), "voice-change")
        elif key == "showcase":
            state.showcase = value
            engine.set_showcase_enabled(self._default_showcase if value is None else value)
        elif key == "subtitles":
            state.subtitles = value
            await hub.set_sticky("subtitles", p.msg_set_subtitles(value))
        elif key == "disabled_animations":
            state.disabled_animations = value
            await hub.set_sticky("disabled_animations", p.msg_set_disabled_animations(value))
        elif key == "tuning":
            state.tuning = value
            await hub.set_sticky("tuning", p.msg_set_tuning(value))
        elif key == "avatar":
            state.avatar = value
            await hub.set_sticky("avatar", p.msg_set_avatar(value))
        elif key == "guest_avatar":
            state.guest_avatar = value
            await hub.set_sticky("guest_avatar", p.msg_set_guest_avatar(value))
        else:  # pragma: no cover - SHARED_SETTINGS y esto van juntos
            raise ValueError(f"Ajuste desconocido: {key}")

    def add_settings_listener(self, callback: Callable[[], None]) -> None:
        """``callback()`` cada vez que un panel cambia un ajuste compartido."""
        self._settings_listeners.append(callback)

    def shared_settings(self) -> dict[str, Any]:
        """Todos los ajustes compartidos, en tipos JSON (para la nube)."""
        return {key: _copy(getattr(self.state, key)) for key in SHARED_SETTINGS}

    def pending_settings(self) -> tuple[dict[str, Any], int]:
        """Lo cambiado aquí que la nube aún no confirmó y el número del último cambio."""
        changes = {key: _copy(getattr(self.state, key)) for key in sorted(self._pending)}
        return changes, self._settings_seq

    def set_cloud_state(self, state: Literal["off", "offline", "online"]) -> None:
        """Lo pone ``CloudLink``: si hay nube y si está conectada ahora."""
        if state != "online":
            self._cloud_synced = False
        self._cloud_state = state

    async def apply_cloud_settings(
        self, values: dict[str, Any], *, rev: int, ack: int
    ) -> list[str]:
        """Aplica los ajustes que manda la nube y devuelve los que cambiaron aquí.

        ``ack`` es el número del último cambio de este equipo que la nube ya
        tiene: lo cambiado aquí después (aún en camino) no se pisa.
        """
        changed: list[str] = []
        for key in SHARED_SETTINGS:
            if key not in values or self._pending.get(key, 0) > ack:
                continue
            try:
                value = _normalize_shared(key, values[key])
            except ValueError:
                logger.warning("Ajuste de la nube no válido, se ignora: %s", key)
                continue
            if _same(getattr(self.state, key), value):
                continue
            try:
                await self._apply_shared(key, value)
            except Exception:
                logger.exception("No se pudo aplicar el ajuste %s de la nube", key)
                continue
            changed.append(key)
        self._pending = {key: n for key, n in self._pending.items() if n > ack}
        self.state.pending_settings = sorted(self._pending)
        self.state.cloud_rev = max(0, rev)
        self._cloud_synced = True
        self._save()
        if changed:
            logger.info("Ajustes de la nube aplicados: %s", ", ".join(changed))
        return changed

    def _settings_sync(self) -> dict[str, Any]:
        return {
            "cloud": self._cloud_state,
            "synced": self._cloud_synced,
            "pending": sorted(self._pending),
            "rev": self.state.cloud_rev,
        }

    # -- estado ---------------------------------------------------------------

    def _watch_outgoing(self, msg: dict[str, Any]) -> None:
        kind = msg.get("type")
        if kind == p.MSG_SHOW_IMAGE:
            self._image = {"id": msg.get("image_id"), "caption": msg.get("caption")}
        elif kind == p.MSG_HIDE_IMAGE:
            self._image = None

    def _on_animations(self, msg: dict[str, Any]) -> None:
        self._animations = p.parse_animations(msg)
        logger.info("Unity tiene %d animaciones para el panel", len(self._animations))

    def _on_animation_playing(self, msg: dict[str, Any]) -> None:
        self._current_animation = p.parse_animation_playing(msg)

    async def _on_avatar_editor(self, msg: dict[str, Any]) -> None:
        open_ = msg.get("open")
        if isinstance(open_, bool):
            if open_:
                self._avatar_editor_target = p.parse_avatar_target(msg)
            await self._set_avatar_editor_open(open_)

    async def _set_avatar_editor_open(self, open_: bool) -> None:
        """Con el editor de personaje en pantalla Sonia no conversa; al salir vuelve a su modo."""
        if open_ == self._avatar_editor_open:
            return
        self._avatar_editor_open = open_
        logger.info("Editor de personaje %s", "abierto" if open_ else "cerrado")
        if open_:
            await self._engine.set_active(False)
        else:
            await self._apply_mode(self.state.mode, announce=False)

    def _on_guest_state(self, msg: dict[str, Any]) -> None:
        phase = p.parse_guest_state(msg)
        if phase is not None and self._guest is not None:
            self._guest.on_unity_state(phase)

    async def _on_avatar_saved(self, msg: dict[str, Any]) -> None:
        definition = p.parse_avatar_definition(msg)
        if definition is None:
            logger.warning("Unity mandó una definición de avatar no válida; se ignora")
            return
        guest = p.parse_avatar_target(msg) == "guest"
        await self._set_shared("guest_avatar" if guest else "avatar", definition)
        logger.info(
            "Personaje nuevo %s guardado desde el editor (%d caracteres)",
            "de Jean" if guest else "de Sonia",
            len(definition),
        )

    def status(self) -> dict[str, Any]:
        """La instantánea de ``GET /api/status`` (forma en ``docs/panel.md``)."""
        settings = self._settings
        engine = self._engine
        snap = engine.snapshot()
        usage_s = self.usage_today()
        return {
            "engine": "live",
            "mode": self.state.mode,
            "away_message": self._away_message,
            "state": snap.get("state") or "idle",
            "health": self._health(snap),
            "session": {
                "id": snap.get("session_id") or None,
                "uptime_s": snap.get("uptime_s"),
                "expires_in_s": snap.get("expires_in_s"),
                "context_ratio": snap.get("context_ratio"),
            },
            "usage": {
                "live_seconds": round(usage_s, 1),
                "cost_usd": round(usage_s / 60.0 * settings.panel.live_price_per_minute, 2),
            },
            "image": self._image,
            "animations": self._animations,
            "current_animation": self._current_animation if self._hub.client_count else None,
            "disabled_animations": self.state.disabled_animations,
            "subtitles": self.state.subtitles,
            "debug": self.state.debug,
            "showcase": {"enabled": engine.showcase_enabled},
            "voice": settings.live.voice,
            "voices": VOICES,
            "volume": self.state.volume,
            "mic_gate": snap.get("mic_gate", 0.0),
            "notes": engine.notes,
            "voice_cache": self._voice_cache_status(),
            "tuning": self.state.tuning,
            "avatar": {
                "custom": self.state.avatar is not None,
                "editor_open": self._avatar_editor_open and self._hub.client_count > 0,
                "editor_target": self._avatar_editor_target,
            },
            "guest_avatar": {"custom": self.state.guest_avatar is not None},
            "guest": (
                self._guest.status()
                if self._guest is not None
                else {"available": False, "phase": "off"}
            ),
            "settings_sync": self._settings_sync(),
            "last_error": snap.get("last_error") or None,
            "capabilities": self.capabilities,
        }

    def _health(self, snap: dict[str, Any]) -> dict[str, dict[str, Any]]:
        mode = self.state.mode
        screen = (
            _health(True, "Pantalla conectada")
            if self._hub.client_count > 0
            else _health(
                False,
                "La pantalla de Sonia no está conectada",
                "Abre la app de Sonia en el ordenador del stand (o ciérrala y ábrela otra vez).",
            )
        )
        if self.state.debug:
            internet = _health(None, "Modo debug: no conversa, así que no gasta")
        elif mode != "conversation":
            internet = _health(None, "No conversa ahora, así que no gasta")
        elif snap.get("connected"):
            internet = _health(True, "Conversación conectada")
        elif not self._settings.live.api_key:
            internet = _health(
                False, "Falta la clave de GPT-Live", "Avisa al equipo técnico (LIVE_API_KEY)."
            )
        else:
            internet = _health(
                False,
                "Conectando con GPT-Live…",
                "Si en un minuto no conecta, revisa el internet del stand o pasa a "
                "«Solo saludos» mientras tanto.",
            )

        level = float(snap.get("mic_level") or 0.0)
        mic_age = snap.get("mic_age_s")
        sound_age = snap.get("mic_sound_age_s")
        if mode != "conversation" or self.state.debug:
            mic = _health(None, "No se usa en este modo")
        elif snap.get("mic_muted"):
            mic = _health(
                False,
                "Micrófono silenciado desde el panel",
                "Pulsa «Activar micrófono» para que Sonia vuelva a oír.",
            )
        elif mic_age is None or mic_age > MIC_STALE_S:
            mic = _health(
                False,
                "El micrófono no envía audio",
                "Revisa que esté enchufado; Sonia lo vuelve a intentar sola cada pocos segundos.",
            )
        elif sound_age is None or sound_age > MIC_DEAF_S:
            mic = _health(
                False,
                "El micrófono no capta nada",
                "Puede estar silenciado con su botón o desenchufado.",
            )
        else:
            mic = _health(True, "Micrófono recibe sonido")
        mic["level"] = level
        mic["muted"] = bool(snap.get("mic_muted"))

        if not snap.get("camera_enabled"):
            camera = _health(None, "Cámara desactivada")
        elif snap.get("camera_ok") is False:
            camera = _health(
                False,
                "La cámara no responde",
                "Revisa el cable USB. Sonia sigue conversando, pero sin ver.",
            )
        else:
            camera = _health(True, "Cámara lista")
        return {"internet": internet, "screen": screen, "mic": mic, "camera": camera}

    # -- gasto del día ----------------------------------------------------------

    def _engine_usage(self) -> float:
        return float(self._engine.snapshot().get("usage_s") or 0.0)

    def _roll_usage_day(self, engine_seconds: float) -> None:
        """Al cambiar de día el contador empieza de cero."""
        today = time.strftime("%Y-%m-%d")
        if self.state.usage_date == today:
            self._usage_base = self.state.usage_seconds
            return
        self.state.usage_date = today
        self.state.usage_seconds = 0.0
        # Lo que el motor ya llevaba de ayer no cuenta para hoy.
        self._usage_base = -engine_seconds

    def usage_today(self) -> float:
        engine_seconds = self._engine_usage()
        if self.state.usage_date != time.strftime("%Y-%m-%d"):
            self._roll_usage_day(engine_seconds)
        return max(0.0, self._usage_base + engine_seconds)

    def _save_usage(self) -> None:
        self._last_usage_save = time.monotonic()
        self.state.usage_seconds = round(self.usage_today(), 1)
        self._save()

    # -- utilidades -------------------------------------------------------------

    def _save(self) -> None:
        self.state.save(self._state_path)

    def _spawn(self, coro: Any, name: str) -> None:
        task = asyncio.create_task(coro, name=f"sonia-panel-{name}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def gallery(self) -> Gallery:
        return Gallery(self._settings.gallery_dir)


class _BadRequest(Exception):
    """Petición del panel que no se puede atender (el texto va al operador)."""


def _health(ok: bool | None, label: str, hint: str = "") -> dict[str, Any]:
    return {"ok": ok, "label": label, "hint": hint if ok is False else ""}


def _text(params: dict[str, Any], name: str, *, max_len: int, required: bool = False) -> str:
    value = params.get(name, "")
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise _BadRequest(f"«{name}» tiene que ser texto.")
    value = value.strip()
    if required and not value:
        raise _BadRequest("Escribe algo primero.")
    if len(value) > max_len:
        raise _BadRequest(f"Demasiado largo (máximo {max_len} caracteres).")
    return value


def _flag(params: dict[str, Any], name: str) -> bool:
    value = params.get(name)
    if not isinstance(value, bool):
        raise _BadRequest(f"«{name}» tiene que ser sí o no.")
    return value


def _number(params: dict[str, Any], name: str, low: float, high: float) -> float:
    value = params.get(name)
    if not _is_number(value) or not math.isfinite(value):
        raise _BadRequest(f"«{name}» tiene que ser un número.")
    return max(low, min(high, float(value)))


def _is_number(value: Any) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _copy(value: Any) -> Any:
    """Copia de un ajuste para mandarlo fuera sin compartir listas ni diccionarios."""
    return json.loads(json.dumps(value))


def _same(a: Any, b: Any) -> bool:
    """¿Mismo ajuste? Compara como JSON (``1`` y ``1.0`` cuentan igual)."""
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True) or a == b


def _normalize_shared(key: str, value: Any) -> Any:
    """Valida un ajuste compartido que llega de la nube. ``ValueError`` si no vale."""
    if key == "away_message":
        if not isinstance(value, str):
            raise ValueError(key)
        return value.strip()[:AWAY_MESSAGE_MAX_LEN] or DEFAULT_AWAY_MESSAGE
    if key == "notes":
        if not isinstance(value, str):
            raise ValueError(key)
        return value.strip()[:NOTES_MAX_LEN]
    if key in ("volume", "mic_gate"):
        if value is None and key == "mic_gate":
            return None
        if not _is_number(value) or not math.isfinite(value):
            raise ValueError(key)
        return max(0.0, min(1.5 if key == "volume" else 0.2, float(value)))
    if key == "voice":
        if value is None or value in VOICES:
            return value
        raise ValueError(key)
    if key == "showcase":
        if value is None or isinstance(value, bool):
            return value
        raise ValueError(key)
    if key == "subtitles":
        if isinstance(value, bool):
            return value
        raise ValueError(key)
    if key == "disabled_animations":
        if not isinstance(value, list):
            raise ValueError(key)
        return sorted({c for c in value if isinstance(c, str) and c})
    if key == "tuning":
        if not isinstance(value, dict):
            raise ValueError(key)
        return merge_tuning(value)
    if key in ("avatar", "guest_avatar"):
        if value is None:
            return None
        definition = p.parse_avatar_definition({"definition": value})
        if definition is None:
            raise ValueError(key)
        return definition
    raise ValueError(key)


def _summary(params: dict[str, Any]) -> str:
    """Parámetros para el log, sin textos largos."""
    if not params:
        return ""
    with contextlib.suppress(Exception):
        return json.dumps(
            {
                k: (v[:40] + "…" if isinstance(v, str) and len(v) > 40 else v)
                for k, v in params.items()
            },
            ensure_ascii=False,
        )
    return ""
