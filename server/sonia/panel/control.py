"""Control de Sonia desde el panel: modos, acciones y estado en lenguaje llano.

Es la capa entre el panel web y el motor. Sabe en qué modo está Sonia
(conversando, solo saludos o fuera), lo aplica al motor y a Unity, guarda lo
que el equipo cambia para que sobreviva a un reinicio y traduce el estado
técnico a frases que entiende cualquiera del stand ("La pantalla de Sonia no
está conectada: abre la app").

Con el motor GPT-Live funciona todo. Con el motor anterior (``pipeline``)
solo lo que no depende de GPT-Live: preguntar, callar, imágenes, gestos y
volumen (``capabilities``).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from sonia.actions.gallery import Gallery
from sonia.actions.registry import ActionRegistry
from sonia.config import Settings
from sonia.showcase import ATTENTION_DANCE, ATTENTION_FOURTH_WALL, load_lines
from sonia.types import ActionContext
from sonia.ws import protocol as p

if TYPE_CHECKING:  # pragma: no cover - solo para tipado
    from sonia.live.engine import LiveEngine
    from sonia.live.voicecache import VoiceCache
    from sonia.orchestrator import Orchestrator
    from sonia.ws.hub import Hub

__all__ = ["DEFAULT_AWAY_MESSAGE", "MODES", "PanelState", "StandControl"]

logger = logging.getLogger(__name__)

Mode = Literal["conversation", "greeter", "away"]
MODES: tuple[Mode, ...] = ("conversation", "greeter", "away")

DEFAULT_AWAY_MESSAGE = "Me fui a ver una charla, regreso en un momento"

#: Voces integradas de GPT-Live que se ofrecen en el panel.
VOICES = ["marin", "cedar", "coral", "sage", "shimmer", "ballad", "verse", "alloy", "ash", "echo"]

GESTURES = ("greeting", "dance", "fourth_wall", "soft")

#: Todo lo que el panel puede hacer con cada motor.
LIVE_CAPABILITIES = [
    "modes",
    "say",
    "ask",
    "stop",
    "mute",
    "restart",
    "images",
    "gestures",
    "greet",
    "showcase",
    "volume",
    "mic_gate",
    "barge_in",
    "voice",
    "notes",
    "voice_cache",
]
PIPELINE_CAPABILITIES = ["ask", "stop", "images", "gestures", "volume"]

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


@dataclass
class PanelState:
    """Lo que el equipo cambia desde el panel y se guarda en disco."""

    mode: Mode = "conversation"
    away_message: str = DEFAULT_AWAY_MESSAGE
    notes: str = ""
    volume: float = 1.0
    mic_gate: float | None = None
    voice: str | None = None
    showcase: bool | None = None
    barge_in: bool | None = None
    #: Gasto del día: segundos de sesión de GPT-Live acumulados en ``usage_date``
    #: (sobrevive a los reinicios del orquestador).
    usage_date: str = ""
    usage_seconds: float = 0.0

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
        for name in ("volume", "mic_gate", "usage_seconds"):
            value = raw.get(name)
            if isinstance(value, int | float) and not isinstance(value, bool):
                setattr(state, name, float(value))
        for name in ("showcase", "barge_in"):
            if isinstance(raw.get(name), bool):
                setattr(state, name, raw[name])
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
    """Frases fijas: saludos, frases del stand y cantos para bailar."""

    greetings: list[str] = field(default_factory=list)
    phrases: list[str] = field(default_factory=list)
    songs: list[str] = field(default_factory=list)

    @classmethod
    def from_dir(cls, directory: Path) -> _Material:
        return cls(
            greetings=load_lines(directory / "saludos.md"),
            phrases=load_lines(directory / "frases.md"),
            songs=load_lines(directory / "cantos.md"),
        )

    def all_texts(self) -> list[str]:
        return [*self.greetings, *self.phrases, *self.songs]


class StandControl:
    """Estado y acciones del panel sobre el motor GPT-Live (o el anterior)."""

    def __init__(
        self,
        settings: Settings,
        *,
        hub: Hub,
        registry: ActionRegistry | None,
        engine: LiveEngine | None = None,
        orchestrator: Orchestrator | None = None,
        voice_cache: VoiceCache | None = None,
        material: _Material | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._settings = settings
        self._hub = hub
        self._registry = registry
        self._engine = engine
        self._orchestrator = orchestrator
        self._voice_cache = voice_cache
        self._material = material or _Material.from_dir(settings.showcase_dir)
        self._rng = rng or random.Random()
        self._state_path = Path(settings.panel.state_file)
        self.state = PanelState.load(self._state_path)
        self._tasks: set[asyncio.Task[Any]] = set()
        self._loop_task: asyncio.Task[None] | None = None
        self._next_greet_at = 0.0
        self._last_greeting: str | None = None
        self._image: dict[str, Any] | None = None
        #: Segundos de sesión de arranques anteriores del mismo día.
        self._usage_base = 0.0
        self._last_usage_save = time.monotonic()
        self._roll_usage_day(engine_seconds=0.0)
        hub.add_listener(self._watch_outgoing)

    # -- ciclo de vida --------------------------------------------------------

    @property
    def capabilities(self) -> list[str]:
        return list(LIVE_CAPABILITIES if self._engine is not None else PIPELINE_CAPABILITIES)

    async def start(self) -> None:
        """Aplica lo guardado y arranca el bucle de saludos. Antes de ``engine.run()``."""
        state = self.state
        engine = self._engine
        if engine is not None:
            if state.voice in VOICES:
                self._settings.live.voice = state.voice
            if state.barge_in is not None:
                self._settings.audio.barge_in = state.barge_in
            if state.mic_gate is not None:
                engine.set_gate(state.mic_gate)
            if state.showcase is not None:
                engine.set_showcase_enabled(state.showcase)
            if state.notes:
                await engine.set_notes(state.notes)
        await self._hub.set_sticky("volume", p.msg_set_volume(state.volume))
        if engine is not None:
            await self._apply_mode(state.mode, announce=False)
            if state.mode != "conversation":
                logger.info("El panel dejó a Sonia en modo %s: no se abre GPT-Live", state.mode)
        self._loop_task = asyncio.create_task(self._loop(), name="sonia-panel-loop")
        if self._voice_cache is not None and self._settings.live.api_key:
            self._spawn(self._prepare_voices(delay=VOICE_WARMUP_DELAY_S), "voice-warmup")

    async def stop(self) -> None:
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
        if engine is None:
            return
        hub = self._hub
        if mode == "away":
            await engine.set_active(False)
            await hub.hide_image()
            await hub.set_sticky("presence", p.msg_presence(False, self._away_message))
            return
        await hub.set_sticky("presence", p.msg_presence(True, self._away_message))
        if mode == "conversation":
            await engine.set_active(True)
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
                if time.monotonic() - self._last_usage_save >= USAGE_SAVE_S:
                    self._save_usage()
                if self.state.mode == "greeter" and time.monotonic() >= self._next_greet_at:
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
        if pcm is None or self._engine is None:
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

    def _need_live(self) -> LiveEngine:
        if self._engine is None:
            raise _BadRequest("Esto solo funciona con el motor GPT-Live.")
        return self._engine

    def _need_present(self) -> None:
        if self.state.mode == "away":
            raise _BadRequest("Sonia está fuera. Tráela de vuelta primero.")

    async def _act_set_mode(self, params: dict[str, Any]) -> tuple[bool, str]:
        self._need_live()
        mode = params.get("mode")
        if mode not in MODES:
            raise _BadRequest("Modo no válido.")
        await self.set_mode(mode)
        return True, {
            "conversation": "Sonia vuelve a conversar.",
            "greeter": "Sonia solo saluda: no conversa ni gasta.",
            "away": "Sonia se va de la pantalla y deja el letrero.",
        }[mode]

    async def _act_set_away_message(self, params: dict[str, Any]) -> tuple[bool, str]:
        text = _text(params, "text", max_len=140)
        self.state.away_message = text or DEFAULT_AWAY_MESSAGE
        self._save()
        if self.state.mode == "away":
            await self._hub.set_sticky("presence", p.msg_presence(False, self._away_message))
        return True, "Letrero actualizado."

    async def _act_say(self, params: dict[str, Any]) -> tuple[bool, str]:
        text = _text(params, "text", max_len=400, required=True)
        self._need_present()
        if self._engine is None:
            raise _BadRequest("Con este motor usa «Preguntar como visitante».")
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
        assert self._voice_cache is not None and self._engine is not None
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
        if self._engine is not None:
            if self.state.mode != "conversation":
                raise _BadRequest("Sonia no está conversando. Pásala a «Conversando» primero.")
            await self._engine.submit_text(text)
        elif self._orchestrator is not None:
            await self._orchestrator.submit_text(text)
        return True, "Enviado. Sonia responderá en voz alta."

    async def _act_stop(self, params: dict[str, Any]) -> tuple[bool, str]:
        if self._engine is not None:
            await self._engine.interrupt()
        elif self._orchestrator is not None:
            from sonia.orchestrator import Interrupt

            self._orchestrator.submit_nowait(Interrupt())
        return True, "Sonia se calla."

    async def _act_mute(self, params: dict[str, Any]) -> tuple[bool, str]:
        engine = self._need_live()
        muted = _flag(params, "muted")
        engine.set_mic_muted(muted)
        return True, "Micrófono silenciado: Sonia no oye." if muted else "Micrófono activado."

    async def _act_restart(self, params: dict[str, Any]) -> tuple[bool, str]:
        engine = self._need_live()
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

    async def _act_greet(self, params: dict[str, Any]) -> tuple[bool, str]:
        self._need_live()
        return await self.greet("greeting")

    async def _act_showcase(self, params: dict[str, Any]) -> tuple[bool, str]:
        engine = self._need_live()
        enabled = _flag(params, "enabled")
        engine.set_showcase_enabled(enabled)
        self.state.showcase = enabled
        self._save()
        return True, (
            "Sonia dirá frases y bailará sola cuando no haya nadie."
            if enabled
            else "Sonia ya no dirá frases ni bailará sola."
        )

    async def _act_set_volume(self, params: dict[str, Any]) -> tuple[bool, str]:
        value = _number(params, "value", 0.0, 1.5)
        self.state.volume = value
        self._save()
        await self._hub.set_sticky("volume", p.msg_set_volume(value))
        return True, f"Volumen al {value * 100:.0f} %."

    async def _act_set_mic_gate(self, params: dict[str, Any]) -> tuple[bool, str]:
        engine = self._need_live()
        value = _number(params, "value", 0.0, 0.2)
        engine.set_gate(value)
        self.state.mic_gate = value
        self._save()
        if value <= 0:
            return True, "Filtro de ruido apagado: Sonia oye todo."
        return True, "Filtro de ruido ajustado."

    async def _act_set_barge_in(self, params: dict[str, Any]) -> tuple[bool, str]:
        self._need_live()
        enabled = _flag(params, "enabled")
        self._settings.audio.barge_in = enabled
        self.state.barge_in = enabled
        self._save()
        return True, (
            "Ahora se la puede interrumpir hablando (usa auriculares o cancelación de eco)."
            if enabled
            else "Ya no se la puede interrumpir hablando."
        )

    async def _act_set_voice(self, params: dict[str, Any]) -> tuple[bool, str]:
        engine = self._need_live()
        voice = params.get("voice")
        if voice not in VOICES:
            raise _BadRequest("Voz no válida.")
        if voice == self._settings.live.voice:
            return True, "Esa voz ya está puesta."
        self._settings.live.voice = str(voice)
        self.state.voice = str(voice)
        self._save()
        await engine.restart_session(f"voz cambiada a {voice}")
        if self._voice_cache is not None and self._settings.live.api_key:
            self._spawn(self._prepare_voices(delay=5.0), "voice-change")
        return True, f"Voz cambiada a {voice}. La conversación empieza de nuevo."

    async def _act_set_notes(self, params: dict[str, Any]) -> tuple[bool, str]:
        engine = self._need_live()
        text = _text(params, "text", max_len=1_000)
        await engine.set_notes(text)
        self.state.notes = text
        self._save()
        return True, "Avisos guardados. Sonia ya los conoce." if text else "Avisos borrados."

    async def _act_prepare_voices(self, params: dict[str, Any]) -> tuple[bool, str]:
        self._need_live()
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

    # -- estado ---------------------------------------------------------------

    def _watch_outgoing(self, msg: dict[str, Any]) -> None:
        kind = msg.get("type")
        if kind == p.MSG_SHOW_IMAGE:
            self._image = {"id": msg.get("image_id"), "caption": msg.get("caption")}
        elif kind == p.MSG_HIDE_IMAGE:
            self._image = None

    def status(self) -> dict[str, Any]:
        """La instantánea de ``GET /api/status`` (forma en ``docs/panel.md``)."""
        settings = self._settings
        engine = self._engine
        snap = engine.snapshot() if engine is not None else {}
        usage_s = self.usage_today()
        return {
            "engine": "live" if engine is not None else "pipeline",
            "mode": self.state.mode if engine is not None else "conversation",
            "away_message": self._away_message,
            "state": snap.get("state") or str(getattr(self._orchestrator, "state", "idle")),
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
            "showcase": {"enabled": engine.showcase_enabled if engine is not None else False},
            "voice": settings.live.voice,
            "voices": VOICES,
            "barge_in": settings.audio.barge_in,
            "volume": self.state.volume,
            "mic_gate": snap.get("mic_gate", 0.0),
            "notes": engine.notes if engine is not None else "",
            "voice_cache": self._voice_cache_status(),
            "last_error": snap.get("last_error") or None,
            "capabilities": self.capabilities,
        }

    def _health(self, snap: dict[str, Any]) -> dict[str, dict[str, Any]]:
        mode = self.state.mode
        engine = self._engine
        screen = (
            _health(True, "Pantalla conectada")
            if self._hub.client_count > 0
            else _health(
                False,
                "La pantalla de Sonia no está conectada",
                "Abre la app de Sonia en el ordenador del stand (o ciérrala y ábrela otra vez).",
            )
        )
        if engine is None:
            return {
                "internet": _health(None, "Motor anterior (sin GPT-Live)"),
                "screen": screen,
                "mic": _health(None, "Sin datos del micrófono con este motor"),
                "camera": _health(None, "Sin datos de la cámara con este motor"),
            }

        if mode != "conversation":
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
        if mode != "conversation":
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
        if self._engine is None:
            return 0.0
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
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise _BadRequest(f"«{name}» tiene que ser un número.")
    return max(low, min(high, float(value)))


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
