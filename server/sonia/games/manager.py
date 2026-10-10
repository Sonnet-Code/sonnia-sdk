"""``GameManager``: los juegos del stand sobre el motor GPT-Live (``docs/juegos.md``).

Lleva un juego a la vez y todo lo común, para que cada juego solo haga lo suyo:

- **Registro y exclusividad.** Los juegos encendidos (``games/registry.py`` y los
  ajustes ``GAMES_*``/``GAME_<X>_ENABLED``) tienen una instancia cada uno. Solo uno en
  marcha, y nunca a la vez que la trivia (``busy``).
- **Cuándo se ofrece un juego** (:meth:`unavailable_reason`): no está apagado desde el
  panel (``games_off``), no hay videollamada, la pantalla está conectada y anuncia el
  juego (``client_hello.games``), y hay lo que necesita (cámara, vista en vivo,
  detectores, modelo de visión). Además, lo propio del juego.
- **Ciclo de vida.** :meth:`start` (por voz o desde el panel), :meth:`stop` y el final
  que pide el propio juego (:meth:`finish`): ``end`` a Unity, vuelta a conversar y la
  cámara suelta.
- **Pausas, abandono y cancelación.** Mientras hay juego, el motor no hace animación de
  stand ni renueva la sesión por inactividad (:attr:`active`). Sin voz ni actividad
  durante el tiempo de abandono, se cancela; también si se cae o se renueva la sesión,
  cambia el modo o la Unity que se conecta no sabe pintarlo.
- **Reconexión de Unity.** El ``start`` de la partida y su último estado son mensajes
  fijos del hub: se repiten tras ``hello``.
- **Estado y órdenes del panel**: :meth:`snapshot`, :meth:`capabilities`, ``games_off``,
  los bancos editables (``game_banks``) y el modelo de poses (``games_pose_model``,
  :meth:`set_pose_model`).

Nada de lo que pase aquí tumba el motor: los fallos de un juego van al registro.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time
from collections.abc import Awaitable, Callable, Coroutine, Iterable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypeVar

from sonia.games.banks import BANK_MAX_CHARS, GameBank, is_bank_id
from sonia.games.base import (
    INSTRUCT_MAX_CHARS,
    SCRIPT_PREFIX,
    Game,
    GameError,
    GameResult,
    StopReason,
)
from sonia.types import ActionResult
from sonia.vision.contracts import GameVision
from sonia.vision.models import DEFAULT_POSE_VARIANT, POSE_VARIANTS, pose_variant
from sonia.ws import protocol as p

if TYPE_CHECKING:
    from sonia.busy import BusyBoard, BusyKind
    from sonia.config import Settings
    from sonia.games.host import ManagedGameHost
    from sonia.trivia.bank import TriviaQuestion

__all__ = [
    "GameEngineLink",
    "GameManager",
    "GameScreen",
    "Phase",
    "VoiceClips",
    "normalize_game_banks",
    "normalize_games_off",
    "normalize_pose_model",
]

logger = logging.getLogger(__name__)

G = TypeVar("G", bound=Game)
T = TypeVar("T")

#: Claves de los mensajes fijos del hub: el ``start`` de la partida y su último estado.
#: Se repiten tras ``hello`` en este orden, así que una Unity que se reconecta vuelve a
#: montar la pantalla y a pintar el estado.
STICKY_START = "game_start"
STICKY_STATE = "game"

#: Tope de espera a que Sonia calle antes de contar un juego arrancado desde el panel.
PANEL_WAIT_S = 3.0

#: Fallos seguidos de ``Game.tick`` tras los que la partida se cancela (un juego roto no
#: puede llenar el registro 20 veces por segundo).
MAX_TICK_FAILURES = 20

#: En qué está el manager: sin juego, jugando o enseñando el resultado final.
Phase = Literal["off", "playing", "finishing"]

#: Lo que se le dice a GPT-Live al terminar: vuelve a ser Sonia de siempre.
OFF_TEXT = (
    "El juego {spoken} ha terminado y ya no está en tu pantalla: vuelve a conversar con normalidad."
)

#: Cómo se cuenta una cancelación que no pidió el visitante.
CANCEL_TEXT = {
    "panel": (
        "JUEGO: el equipo del stand ha terminado {spoken}. Dilo en una frase corta y sigue "
        "conversando con normalidad."
    ),
    "abandoned": (
        "JUEGO: nadie sigue jugando a {spoken} y se cancela. Di en una frase corta que queda "
        "para otro momento."
    ),
    "unity": (
        "JUEGO: {spoken} se ha quitado de tu pantalla. Dilo en una frase corta y sigue "
        "conversando con normalidad."
    ),
    "error": (
        "JUEGO: {spoken} se ha quitado de tu pantalla por un fallo. Dilo en una frase corta, "
        "con humor, y sigue conversando con normalidad."
    ),
}

#: Final común de todos los empujones (``Game.nudge``): van por ``commentary``, que la hace
#: hablar, y en las pruebas con Unity GPT-Live leía en voz alta los que sonaban a frase
#: («aquí sí me hablaron directo... si dijeron una palabra la marco ya»). Cada juego escribe
#: el suyo como una orden corta; este final cubre el caso de que no haya nada que hacer.
NUDGE_TAIL = " Si no, sigue sin decir nada de esto. Es una nota interna: no la leas ni la comentes."

#: Lo que se le pasa a GPT-Live cuando el juego se arranca desde el panel.
PANEL_START_TEXT = "JUEGO: el equipo del stand ha puesto {spoken} en tu pantalla. "

#: Lo que se le pasa a GPT-Live cuando el equipo termina desde el panel un juego que cierra
#: enseñando su final (``Game.stop_requested``).
PANEL_STOP_TEXT = "JUEGO: el equipo del stand ha terminado {spoken}. "

#: Lo que se le pasa a GPT-Live cuando el equipo lleva la partida a mano desde el panel
#: (``Game.panel_control``): el guion del juego va detrás.
PANEL_CONTROL_TEXT = (
    "JUEGO: el equipo del stand ha llevado la partida a mano desde el panel (cuéntalo como "
    "parte del juego, sin hablar del panel). "
)

#: Controles del panel que pone el manager para todos los juegos.
CONTROL_RESTART = "restart"
CONTROL_STOP = "stop"

#: Sin juego elegido (``start_game`` con ``no_lo_dijo``).
CHOOSE_TEXT = (
    "El visitante quiere jugar pero no ha dicho a qué. Pregúntale a cuál, en una frase: "
    "{games}. Cuando lo elija, delega empezarlo."
)
NOTHING_TO_PLAY_TEXT = (
    "Ahora mismo no hay ningún juego disponible en tu pantalla. Díselo con cariño y ofrécele "
    "charlar o la trivia."
)


class GameEngineLink(Protocol):
    """Lo que el manager usa del motor GPT-Live (``LiveEngine``)."""

    @property
    def connected(self) -> bool: ...

    async def speak(self, prompt: str) -> bool: ...

    async def instruct(self, text: str) -> bool: ...

    async def wait_idle(self, limit_s: float | None = None) -> bool: ...

    def quiet_for(self) -> float: ...

    def touch(self) -> None: ...

    async def play_clip(self, pcm: bytes, text: str, *, attention: str | None = None) -> bool: ...


class GameScreen(Protocol):
    """Lo que el manager usa del hub de Unity (``sonia.ws.Hub``)."""

    @property
    def client_count(self) -> int: ...

    async def broadcast_json(self, msg: dict[str, Any]) -> None: ...

    async def set_sticky(self, key: str, msg: dict[str, Any]) -> None: ...

    def clear_sticky(self, key: str) -> None: ...

    async def hide_image(self) -> None: ...


class VoiceClips(Protocol):
    """Las frases grabadas (``sonia.live.voicecache.VoiceCache``)."""

    def get(self, text: str) -> bytes | None: ...


class GameManager:
    """Los juegos del stand: uno a la vez, sobre la sesión de GPT-Live del motor.

    Lo crea el motor (``LiveEngine``) junto a la trivia. Los tests lo montan con
    ``tests/games/fakes.py`` (``FakeEngine`` y ``FakeScreen``).
    """

    def __init__(
        self,
        settings: Settings,
        *,
        engine: GameEngineLink,
        screen: GameScreen,
        vision: GameVision | None = None,
        voice_cache: VoiceClips | None = None,
        games: Sequence[type[Game]] | None = None,
        camera_ready: Callable[[], bool] | None = None,
        meeting: bool = False,
        busy: Callable[[], str | None] | None = None,
        busy_board: BusyBoard | None = None,
        trivia_draw: Callable[[str | None], TriviaQuestion | None] | None = None,
        rng: random.Random | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """
        - ``games``: las clases de los juegos encendidos; por defecto, las del registro
          que dejan los ajustes (:func:`sonia.games.registry.enabled_games`).
        - ``camera_ready``: ``True`` si hay cámara USB para los juegos (``VISION_SOURCE=opencv``).
        - ``meeting``: Sonia está en una videollamada: no hay juegos.
        - ``busy``: por qué no se puede empezar un juego ahora por otra cosa (la trivia en
          marcha), o ``None``.
        - ``busy_board``: el aviso de espera en pantalla (``sonia.busy``); sin él, los
          ``set_busy`` de los juegos no hacen nada.
        - ``trivia_draw``: una pregunta del banco de la trivia (``TriviaGame.draw_one``).
        - ``clock`` y ``sleep``: el reloj de los juegos (en los tests, uno falso).
        """
        from sonia.games.host import ManagedGameHost
        from sonia.vision.games import unavailable_game_vision

        if games is None:
            from sonia.games.registry import enabled_games

            games = enabled_games(settings)
        self._settings = settings
        self._engine = engine
        self._screen = screen
        self._vision = vision or unavailable_game_vision()
        self._voice_cache = voice_cache
        self._camera_ready = camera_ready or (lambda: False)
        self._meeting = meeting
        self._busy = busy
        self._busy_board = busy_board
        self._trivia_draw = trivia_draw
        self._rng = rng or random.Random()
        self._clock = clock
        self._sleep = sleep
        self._hosts: dict[str, ManagedGameHost] = {}
        self._games: dict[str, Game] = {}
        for cls in games:
            if cls.id in self._games:
                logger.warning("Juego repetido en el registro: %s", cls.id)
                continue
            host = ManagedGameHost(self, cls.id)
            try:
                # Lo que se lee al arrancar: un juego roto se queda fuera y Sonia sigue.
                cls.actions()
                cls.banks()
                game = cls(host)
            except Exception:  # noqa: BLE001 - un juego roto no tumba el arranque
                logger.exception("El juego %s está roto y se deja fuera", cls.id)
                continue
            self._hosts[cls.id] = host
            self._games[cls.id] = game
        #: Modelo de poses pedido desde el panel (ajuste compartido ``games_pose_model``);
        #: ``None``: el de ``GAME_POSES_MODEL``. Se guarda por si la visión llega después.
        self._pose_model_request: str | None = None
        #: Apagados desde el panel (ajuste compartido ``games_off``).
        self._off: frozenset[str] = frozenset()
        #: Bancos guardados en la nube desde el panel (``game_banks``): ``{banco: texto}``.
        self._cloud_banks: dict[str, str] = {}
        #: Lo que anunció la última Unity en ``client_hello`` (``None``: nada aún, o una
        #: Unity anterior a los juegos).
        self._unity_games: frozenset[str] | None = None
        self._features: frozenset[str] = frozenset()
        # Partida en marcha.
        self._active: Game | None = None
        self._phase: Phase = "off"
        self._match = 0
        self._seq = 0
        self._started_at = 0.0
        self._screen_started = False
        self._last_activity = 0.0
        self._nudge_at = 0.0
        self._delegated_at = float("-inf")
        self._tick_failures = 0
        self._pending: tuple[GameResult, dict[str, Any] | None] | None = None
        self._tasks: set[asyncio.Task[Any]] = set()

    # -- montaje --------------------------------------------------------------

    def attach_vision(self, vision: GameVision) -> None:
        """La visión de los juegos (``build_game_vision``), que se monta después del manager."""
        self._vision = vision
        if self._pose_model_request is not None:
            self._apply_pose_model()

    @property
    def vision(self) -> GameVision:
        return self._vision

    def preview_supported(self) -> bool:
        """¿Sabe la Unity conectada pintar la vista en vivo (``client_hello.features``)?"""
        return p.FEATURE_CAMERA_PREVIEW in self._features and self._screen.client_count > 0

    # -- estado ---------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """¿Hay algún juego en esta Sonnia (registro y ajustes)?"""
        return bool(self._games)

    @property
    def active(self) -> bool:
        """¿Hay un juego en pantalla (jugando o enseñando el resultado)? El motor lo usa
        para pausar la animación de stand y la renovación de la sesión por inactividad."""
        return self._active is not None

    @property
    def phase(self) -> Phase:
        return self._phase

    @property
    def current(self) -> Game | None:
        """El juego en pantalla, o ``None``."""
        return self._active

    def games(self) -> list[Game]:
        """Los juegos de esta Sonnia, en el orden del registro."""
        return list(self._games.values())

    def game(self, game_id: str) -> Game | None:
        return self._games.get(game_id)

    def busy_reason(self) -> str | None:
        """Para la trivia: por qué no puede empezar ahora (hay un juego), o ``None``."""
        game = self._active
        if game is None:
            return None
        return (
            f"Ahora mismo se está jugando a {game.spoken}: termina antes el juego (o sigue con "
            "él) para empezar la trivia."
        )

    def unavailable_reason(self, game_id: str) -> str | None:
        """Por qué no se puede jugar ahora a ``game_id`` (``None``: se puede).

        No mira si hay otra partida en marcha ni si hay sesión de GPT-Live: eso lo dice
        :meth:`start`. Lo leen GPT-Live y el panel: sin nombres del stack ni de Sonia.
        """
        game = self._games.get(game_id)
        if game is None:
            return "Ese juego no está en esta versión."
        if game_id in self._off:
            return f"{game.title} está apagado desde el panel."
        if self._meeting:
            return "En una videollamada no hay juegos."
        if self._screen.client_count == 0:
            return "La pantalla no está conectada."
        if self._unity_games is None:
            return "La pantalla es de una versión sin juegos."
        if game_id not in self._unity_games:
            return f"La pantalla no sabe pintar {game.spoken} (es de una versión anterior)."
        missing = self._missing_need(game)
        if missing:
            return missing
        try:
            return game.unavailable_reason()
        except Exception:  # noqa: BLE001 - un juego roto se da por no disponible
            logger.exception("Falló unavailable_reason de %s", game_id)
            return f"{game.title} no está disponible ahora."

    def _missing_need(self, game: Game) -> str | None:
        needs = game.needs
        vision = self._vision
        if needs & {"camera", "preview", "poses", "hands"} and not self._camera_ready():
            return "No hay cámara para este juego."
        if "preview" in needs and p.FEATURE_CAMERA_PREVIEW not in self._features:
            return "La pantalla no sabe enseñar la cámara en vivo (es de una versión anterior)."
        if "poses" in needs and not vision.poses.available:
            return "Falta el detector de posturas de la cámara."
        if "hands" in needs and not vision.hands.available:
            return "Falta el lector de manos de la cámara."
        if "vision_llm" in needs and not vision.judge.available:
            return "Falta el modelo que mira la cámara."
        return None

    def playable(self) -> list[Game]:
        """Los juegos que se pueden empezar ahora mismo (sin contar si hay otro en marcha)."""
        return [g for g in self._games.values() if self.unavailable_reason(g.id) is None]

    def choose_text(self) -> str:
        """El guion de ``start_game`` sin juego elegido: que pregunte a cuál."""
        games = self.playable()
        if not games:
            return NOTHING_TO_PLAY_TEXT
        return CHOOSE_TEXT.format(games=_spoken_list([g.spoken for g in games]))

    def _suggest(self, exclude: str = "") -> str:
        others = [g.spoken for g in self.playable() if g.id != exclude]
        if not others:
            return ""
        return f" Ahora se puede jugar a {_spoken_list(others)}."

    def snapshot(self) -> dict[str, Any]:
        """Para el panel (tipos JSON). Forma en ``docs/juegos.md``, «Panel»."""
        game = self._active
        state: dict[str, Any] = {}
        if game is not None:
            try:
                state = dict(game.snapshot())
            except Exception:  # noqa: BLE001
                logger.exception("Falló snapshot de %s", game.id)
        games = []
        for item in self._games.values():
            reason = self.unavailable_reason(item.id)
            games.append(
                {
                    "id": item.id,
                    "title": item.title,
                    "needs": sorted(item.needs),
                    "off": item.id in self._off,
                    "available": reason is None,
                    "reason": reason or "",
                }
            )
        return {
            "enabled": self.enabled,
            "active": game.id if game is not None else None,
            "title": game.title if game is not None else "",
            "phase": self._phase,
            "elapsed_s": round(self._clock() - self._started_at, 1) if game is not None else 0.0,
            "state": state,
            "controls": self._controls(game),
            "games": games,
            "games_off": sorted(self._off),
            "banks": self.bank_list(),
            "unity_games": sorted(self._unity_games) if self._unity_games is not None else None,
            "preview": self.preview_supported(),
            "pose_model": self._pose_model_state(),
        }

    def _controls(self, game: Game | None) -> list[dict[str, Any]]:
        """Los controles a mano de la partida en marcha (``Game.panel_controls``) más los comunes."""
        if game is None:
            return []
        controls: list[dict[str, Any]] = []
        if self._phase == "playing":
            try:
                controls = [dict(c) for c in game.panel_controls()]
            except Exception:  # noqa: BLE001
                logger.exception("Falló panel_controls de %s", game.id)
                controls = []
        controls.append({"id": CONTROL_RESTART, "label": "Reiniciar"})
        controls.append({"id": CONTROL_STOP, "label": "Terminar"})
        return controls

    async def panel_control(self, control: str, value: str = "") -> tuple[bool, str]:
        """Un control a mano del panel con el juego en marcha (acción ``game_control``).

        ``restart`` empieza el mismo juego desde cero y ``stop`` lo termina, para todos; el
        resto los resuelve el juego (:meth:`Game.panel_control`) y su guion se le pasa a
        GPT-Live en cuanto calla. Nunca lanza: ``(ok, mensaje para el equipo)``.
        """
        game = self._active
        if game is None:
            return False, "No hay ningún juego en marcha."
        if control == CONTROL_STOP:
            return await self.stop("panel")
        if control == CONTROL_RESTART:
            await self.stop("panel")
            return await self.start(game.id, "panel")
        if self._phase != "playing":
            return False, f"{game.title} ya está terminando."
        self._note_activity()
        try:
            script = await game.panel_control(control, str(value or ""))
        except GameError as exc:
            return False, str(exc) or "Ese control no está disponible ahora."
        except Exception:  # noqa: BLE001 - la demo nunca se cae por un botón
            logger.exception("Falló el control %s de %s", control, game.id)
            return False, "Ese control falló; prueba otra vez o termina el juego."
        if script:
            self._spawn(
                self._speak_when_quiet(self._match, PANEL_CONTROL_TEXT + script), "game-control"
            )
        return True, "Hecho."

    def capabilities(self) -> list[str]:
        """Capacidades para el panel (``data-cap``): ``games``, ``game:<id>`` y ``game_banks``.

        ``game:<id>`` solo de los juegos que anuncia la Unity conectada.
        """
        if not self._games:
            return []
        caps = ["games"]
        shown = self._unity_games or frozenset()
        caps.extend(f"game:{gid}" for gid in self._games if gid in shown)
        if self.bank_specs():
            caps.append("game_banks")
        if self._pose_model_setter() is not None:
            caps.append("game_pose_model")
        # Controles a mano de la partida en marcha (``snapshot()["controls"]``, acción
        # ``game_control``): las apps anteriores no los tienen.
        caps.append("game_controls")
        return caps

    # -- panel: modelo de poses -------------------------------------------------

    def set_pose_model(self, variant: str | None) -> None:
        """El modelo de poses que pide el panel (ajuste compartido ``games_pose_model``).

        ``n`` (ligero) o ``s`` (preciso); ``None`` (o algo que no es ninguno) vuelve al de
        ``GAME_POSES_MODEL``. No bloquea: el detector carga el nuevo en un hilo y sigue con
        el viejo mientras tanto, también con una partida en marcha. Sin un detector que lo
        admita (``set_variant``), no hace nada.
        """
        self._pose_model_request = normalize_pose_model(variant)
        self._apply_pose_model()

    def _pose_model_default(self) -> str:
        """El de ``GAME_POSES_MODEL``."""
        games = getattr(self._settings, "games", None)
        poses = getattr(games, "poses", None)
        return normalize_pose_model(getattr(poses, "model", None)) or DEFAULT_POSE_VARIANT

    def _pose_model_setter(self) -> Callable[[str], None] | None:
        """``set_variant`` del detector de poses, si lo tiene (por duck typing)."""
        setter = getattr(self._vision.poses, "set_variant", None)
        return setter if callable(setter) else None

    def _apply_pose_model(self) -> None:
        setter = self._pose_model_setter()
        if setter is None:
            return
        wanted = self._pose_model_request or self._pose_model_default()
        try:
            setter(wanted)
        except Exception:  # noqa: BLE001 - el panel no tumba el motor
            logger.exception("No se pudo cambiar el modelo de poses a %s", wanted)

    def _pose_model_state(self) -> dict[str, Any] | None:
        """``{"current", "default", "options"}`` para el panel, o ``None`` si no se puede cambiar."""
        if self._pose_model_setter() is None:
            return None
        default = self._pose_model_default()
        current = normalize_pose_model(getattr(self._vision.poses, "variant", None))
        return {
            "current": current or default,
            "default": default,
            "options": list(POSE_VARIANTS),
        }

    # -- panel: interruptores -------------------------------------------------

    @property
    def games_off(self) -> frozenset[str]:
        return self._off

    @property
    def unity_games(self) -> frozenset[str] | None:
        """Los juegos que anunció la Unity conectada (``None``: ninguna lo anunció aún)."""
        return self._unity_games

    async def set_games_off(self, ids: Iterable[str]) -> None:
        """Los juegos apagados desde el panel (ajuste compartido ``games_off``).

        Si el que está en marcha se apaga, se termina como desde el panel.
        """
        self._off = frozenset(i for i in ids if isinstance(i, str))
        game = self._active
        if game is not None and game.id in self._off and self._phase == "playing":
            logger.info("Juegos: %s apagado desde el panel en plena partida", game.id)
            await self.stop("panel")

    # -- Unity ----------------------------------------------------------------

    async def on_client_hello(self, msg: dict[str, Any]) -> None:
        """``client_hello``: qué juegos sabe pintar la Unity conectada y qué más sabe hacer."""
        hello = p.parse_client_hello(msg)
        self._unity_games = hello.games
        self._features = hello.features
        logger.info(
            "Unity (%s %s) anuncia juegos: %s; capacidades: %s",
            hello.client or "?",
            hello.version or "?",
            ", ".join(sorted(hello.games)) if hello.games else "ninguno",
            ", ".join(sorted(hello.features)) or "ninguna",
        )
        game = self._active
        if game is not None and (hello.games is None or game.id not in hello.games):
            logger.warning("La Unity que se conectó no sabe pintar %s: se cancela", game.id)
            await self.stop("unity")

    async def on_game_event(self, msg: dict[str, Any]) -> None:
        """``game_event`` de Unity: al juego en marcha si es el suyo."""
        parsed = p.parse_game_event(msg)
        game = self._active
        if parsed is None or game is None:
            return
        game_id, event, data = parsed
        if game_id != game.id or self._phase != "playing":
            logger.debug("game_event de %s ignorado (en marcha: %s)", game_id, game.id)
            return
        self._note_activity()
        try:
            await game.on_unity_event(event, data)
        except Exception:  # noqa: BLE001 - un juego roto no tumba el motor
            logger.exception("Falló on_unity_event(%s) de %s", event, game.id)

    # -- arranque y final -----------------------------------------------------

    async def start(
        self, game_id: str, source: str = "panel", options: dict[str, Any] | None = None
    ) -> tuple[bool, str]:
        """Empieza ``game_id``. Nunca lanza.

        Con ``source="voice"`` (``start_game``) devuelve el guion de arranque para
        GPT-Live. Con ``panel`` se lo pasa a GPT-Live en cuanto calla y devuelve un texto
        para el equipo del stand. Si no se puede, ``(False, motivo)`` con los juegos que
        sí se pueden jugar.
        """
        game = self._games.get(game_id)
        if game is None:
            return False, f"No hay ningún juego «{game_id}» en esta versión.{self._suggest()}"
        active = self._active
        if active is game and self._phase == "playing":
            self._note_activity()
            return True, await self._resume(game)
        if active is not None and self._phase == "playing":
            return False, (
                f"Ahora mismo se está jugando a {active.spoken}. Si quieren cambiar a "
                f"{game.spoken}, primero hay que terminar el que está en marcha."
            )
        if active is not None:
            # Enseñaba el resultado final: se cierra ya para empezar el nuevo.
            await self._end_now("replaced")
        busy = self._busy() if self._busy is not None else None
        if busy:
            return False, busy
        reason = self.unavailable_reason(game_id)
        if reason:
            return False, reason + self._suggest(exclude=game_id)
        if not self._engine.connected:
            return False, "Sonnia no está conectada ahora mismo: no hay sesión de voz."
        self._match += 1
        match = self._match
        now = self._clock()
        self._active = game
        self._phase = "playing"
        self._started_at = now
        self._last_activity = now
        self._screen_started = False
        self._nudge_at = 0.0
        # ``_delegated_at`` no se olvida: el turno que pidió el juego delegó start_game y,
        # si se olvidara, su final de turno daría un empujón de más (banco de pruebas).
        self._tick_failures = 0
        self._pending = None
        self._engine.touch()
        logger.info("Juego %s en marcha (%s)", game_id, source)
        with contextlib.suppress(Exception):
            await self._screen.hide_image()
        try:
            script = await game.start(source, dict(options or {}))
        except GameError as exc:
            logger.info("Juego %s: no se pudo empezar: %s", game_id, exc)
            await self._abort(match, game)
            return False, str(exc) or f"No se pudo empezar {game.spoken}."
        except Exception:  # noqa: BLE001 - un juego roto no tumba el motor
            logger.exception("Juego %s: falló al empezar", game_id)
            await self._abort(match, game)
            return False, f"No se pudo empezar {game.spoken}: falló al prepararse."
        if match != self._match or self._phase != "playing":
            await self._release_orphaned_vision(game)
            return False, f"{game.title} se canceló al empezar."
        await self._ensure_started(game)
        if source == "voice":
            return True, script
        self._spawn(
            self._speak_when_quiet(match, PANEL_START_TEXT.format(spoken=game.spoken) + script),
            "game-intro",
        )
        return True, f"{game.title} en marcha."

    async def _resume(self, game: Game) -> str:
        try:
            return await game.resume()
        except Exception:  # noqa: BLE001
            logger.exception("Falló resume de %s", game.id)
            return f"{game.spoken} ya está en marcha: sigue con la partida."

    async def _abort(self, match: int, game: Game) -> None:
        """El juego no pudo empezar: se retira sin decir nada."""
        if match == self._match and self._active is game:
            await self._end_now("error", result="cancel")
            return
        await self._release_orphaned_vision(game)

    async def _release_orphaned_vision(self, game: Game) -> None:
        """``game.start`` terminó cuando su partida ya se había cerrado por fuera (la
        sesión se cayó, el panel, la Unity que se reconectó): la vista en vivo, las poses
        o la cámara que pidiera después de que ``_end_now`` las soltara se quedarían
        abiertas hasta la siguiente partida de ese juego. Si el mismo juego ya está otra
        vez en pantalla, lo suyo es de esa partida y no se toca."""
        if self._active is not game:
            await self._release_vision(game.id)

    async def stop(self, reason: StopReason = "panel") -> tuple[bool, str]:
        """Termina el juego en marcha. ``reason``: ``voice``, ``panel``, ``abandoned``,
        ``session``, ``unity``... (:data:`sonia.games.base.StopReason`). Nunca lanza.

        Si ya enseñaba el resultado final, se cierra con ese resultado.
        """
        game = self._active
        if game is None:
            return False, "No hay ningún juego en marcha."
        if reason in ("voice", "panel") and self._phase == "playing":
            ending = await self._stop_with_ending(game, reason)
            if ending is not None:
                return True, ending
        was_playing = self._phase == "playing"
        logger.info("Juego %s terminado (%s)", game.id, reason)
        await self._end_now(reason)
        if reason not in ("session", "shutdown") and self._engine.connected:
            with contextlib.suppress(Exception):
                await self._engine.instruct(OFF_TEXT.format(spoken=game.spoken))
                text = CANCEL_TEXT.get(reason)
                if text and was_playing:
                    await self._engine.speak(text.format(spoken=game.spoken))
        return True, f"{game.title} terminado."

    async def _stop_with_ending(self, game: Game, reason: StopReason) -> str | None:
        """Si el juego sabe terminar enseñando su final (``Game.stop_requested``), lo deja.

        El juego se cierra él mismo con ``host.finish`` (la fase pasa a ``finishing``): aquí
        no se cancela y la pantalla sigue el final normal. Por voz devuelve el guion (que
        ``stop_game`` pasa con ``PARA SONIA:``); desde el panel se lo pasa a GPT-Live en
        cuanto calla y devuelve un texto para el equipo. ``None``: se cancela como siempre.
        """
        try:
            script = await game.stop_requested(reason)
        except Exception:  # noqa: BLE001 - un juego roto se cancela como siempre
            logger.exception("Falló stop_requested de %s", game.id)
            return None
        if not script:
            return None
        if self._active is not game or self._phase != "finishing":
            logger.warning(
                "Juego %s: devolvió un final sin cerrarse con finish; se cancela", game.id
            )
            return None
        logger.info("Juego %s: lo terminan (%s) y enseña su final", game.id, reason)
        if reason == "voice":
            return script
        self._spawn(
            self._speak_ending(self._match, PANEL_STOP_TEXT.format(spoken=game.spoken) + script),
            "game-stop",
        )
        return f"{game.title}: enseña su final y se cierra."

    async def _speak_ending(self, match: int, prompt: str) -> None:
        """El final de un juego terminado desde el panel, en cuanto Sonia calla."""
        await self._engine.wait_idle(PANEL_WAIT_S)
        if match == self._match and self._active is not None:
            await self._engine.speak(prompt)

    async def finish(
        self, game_id: str, result: GameResult, data: dict[str, Any] | None = None
    ) -> None:
        """El juego ``game_id`` terminó (:meth:`sonia.games.base.GameHost.finish`)."""
        game = self._active
        if game is None or game.id != game_id or self._phase != "playing":
            return
        if result not in p.GAME_RESULTS:
            logger.warning(
                "Juego %s: resultado desconocido %r; se da por cancelado", game_id, result
            )
            result = "cancel"
        self._phase = "finishing"
        self._pending = (result, dict(data) if data else None)
        self._nudge_at = 0.0
        logger.info("Juego %s: final (%s)", game_id, result)
        self._spawn(self._finish_later(self._match, game), "game-final")

    async def _finish_later(self, match: int, game: Game) -> None:
        """Tras el resultado, ``end`` cuando Sonia termina de contarlo (como la trivia)."""
        settings = self._settings.games
        pending = self._pending
        if pending is not None and pending[0] != "cancel":
            await self._sleep(max(0.0, settings.result_seconds))
            deadline = self._clock() + max(0.0, settings.final_wait_seconds)
            spoke = False
            while self._clock() < deadline and match == self._match:
                quiet = self._engine.quiet_for()
                spoke = spoke or quiet < 0.5
                if spoke and quiet >= 1.5:
                    break
                await self._sleep(0.25)
        else:
            await self._sleep(0)
        if match != self._match or self._active is not game:
            return
        await self._end_now("finished")
        if self._engine.connected:
            with contextlib.suppress(Exception):
                await self._engine.instruct(OFF_TEXT.format(spoken=game.spoken))

    async def _end_now(
        self,
        reason: StopReason,
        *,
        result: GameResult | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Cierra la partida: ``Game.stop``, cámara suelta, fijos fuera y ``end`` a Unity."""
        game = self._active
        if game is None:
            return
        pending = self._pending
        if result is None:
            result, data = pending if pending is not None else ("cancel", None)
        self._active = None
        self._phase = "off"
        self._pending = None
        self._nudge_at = 0.0
        self._match += 1
        self._cancel_tasks()
        host = self._hosts.get(game.id)
        if host is not None:
            host.cancel_tasks()
        try:
            await game.stop(reason)
        except Exception:  # noqa: BLE001
            logger.exception("Falló stop de %s", game.id)
        await self._release_vision(game.id)
        await self._clear_busy(game.id)
        self._screen.clear_sticky(STICKY_START)
        self._screen.clear_sticky(STICKY_STATE)
        if self._screen_started:
            self._screen_started = False
            with contextlib.suppress(Exception):
                await self._screen.broadcast_json(
                    p.msg_game_end(game.id, self._next_seq(), result, data)
                )
        logger.info(
            "Juego %s fuera de la pantalla (%s, %s, %.0f s)",
            game.id,
            reason,
            result,
            self._clock() - self._started_at,
        )

    async def _release_vision(self, owner: str) -> None:
        """Suelta a nombre del juego lo que pudiera tener: vista en vivo, poses y cámara."""
        vision = self._vision
        for release in (vision.preview.stop, vision.poses.release, vision.stream.release):
            try:
                await release(owner)
            except Exception:  # noqa: BLE001
                logger.exception("No se pudo soltar la visión de %s", owner)

    async def on_session_lost(self) -> None:
        """Se cayó o se renovó la sesión de GPT-Live, o cambió el modo: la partida no sigue."""
        if self._active is not None:
            await self.stop("session")

    async def close(self) -> None:
        """Al apagar el motor: termina lo que haya y suelta la visión."""
        if self._active is not None:
            await self.stop("shutdown")
        with contextlib.suppress(Exception):
            await self._vision.close()

    # -- jugadas --------------------------------------------------------------

    async def play(
        self,
        game_cls: type[G],
        play: Callable[[G, dict[str, Any]], Awaitable[str]],
        arguments: dict[str, Any],
    ) -> ActionResult:
        """Una jugada delegada (:func:`sonia.actions.games.game_action`). Nunca lanza.

        Llega al juego solo si es el que está en marcha y aún se juega. El guion que
        devuelve va marcado con :data:`SCRIPT_PREFIX`; un :class:`GameError`, tal cual.
        """
        game = self._active
        if game is None:
            return ActionResult(
                text=(
                    f"No hay ninguna partida de {game_cls.spoken} en marcha. Si el visitante "
                    "quiere jugar, delega empezarla."
                )
            )
        if not isinstance(game, game_cls):
            return ActionResult(
                text=f"Ahora se está jugando a {game.spoken}, no a {game_cls.spoken}."
            )
        if self._phase != "playing":
            return ActionResult(
                text=(
                    f"La partida de {game.spoken} ya ha terminado. Si quieren otra, delega "
                    "empezarla de nuevo."
                )
            )
        self._note_activity()
        try:
            script = await play(game, arguments)
        except GameError as exc:
            return ActionResult(text=str(exc))
        except Exception:  # noqa: BLE001 - la demo nunca se cae por una jugada
            logger.exception("Falló una jugada de %s", game.id)
            return ActionResult(
                text="La jugada falló por un error. Díselo al visitante con humor y seguid jugando."
            )
        return ActionResult(text=f"{SCRIPT_PREFIX} {script}")

    # -- ganchos del motor ----------------------------------------------------

    async def on_assistant_text(self, text: str, final: bool) -> None:
        """Lo que va diciendo Sonia (texto acumulado de la frase; ``final`` al cerrarla)."""
        game = self._active
        if game is None or self._phase != "playing":
            return
        try:
            await game.on_assistant_text(text, final)
        except Exception:  # noqa: BLE001
            logger.exception("Falló on_assistant_text de %s", game.id)

    def on_user_text(self, now: float) -> None:
        """Se oye al visitante: sigue ahí."""
        game = self._active
        if game is None:
            return
        self._note_activity()
        try:
            game.on_user_text(now)
        except Exception:  # noqa: BLE001
            logger.exception("Falló on_user_text de %s", game.id)

    def on_user_turn_end(self, now: float, started_at: float) -> None:
        """Terminó un turno del visitante: si el juego lo pide y no se delegó nada, empujón."""
        game = self._active
        if game is None or self._phase != "playing":
            return
        try:
            # Primero el juego (puede decidir su empujón por el turno, como el Akinator con
            # los turnos largos) y luego si lo quiere.
            game.on_user_turn_end(now, started_at)
            wants_nudge = game.nudge() is not None
        except Exception:  # noqa: BLE001
            logger.exception("Falló on_user_turn_end de %s", game.id)
            return
        if wants_nudge and self._delegated_at < started_at - 0.5:
            self._nudge_at = now + max(0.0, self._settings.games.nudge_seconds)

    def on_delegation(self, now: float) -> None:
        """GPT-Live delegó algo: no hace falta empujón."""
        self._delegated_at = now
        self._nudge_at = 0.0
        game = self._active
        if game is None:
            return
        self._note_activity()
        try:
            game.on_delegation(now)
        except Exception:  # noqa: BLE001
            logger.exception("Falló on_delegation de %s", game.id)

    async def tick(self, now: float) -> None:
        """Lo llama el ciclo del motor (cada 50 ms): empujón, abandono y ``Game.tick``."""
        game = self._active
        if game is None or self._phase != "playing":
            return
        quiet = self._engine.quiet_for()
        if self._nudge_at and now >= self._nudge_at and quiet >= 0.5:
            self._nudge_at = 0.0
            text = None
            with contextlib.suppress(Exception):
                text = game.nudge()
            if text:
                logger.info("Juego %s: el visitante habló y no se delegó nada; empujón", game.id)
                self._spawn(self._engine.speak(text.rstrip() + NUDGE_TAIL), "game-nudge")
        limit = self._abandon_seconds(game)
        if limit > 0 and now - self._last_activity >= limit and quiet >= 1.0:
            logger.info("Juego %s abandonado tras %.0f s sin actividad", game.id, limit)
            await self.stop("abandoned")
            return
        try:
            await game.tick(now)
        except Exception:  # noqa: BLE001
            self._tick_failures += 1
            if self._tick_failures == 1:
                logger.exception("Falló tick de %s", game.id)
            if self._tick_failures >= MAX_TICK_FAILURES and self._active is game:
                logger.error("tick de %s falla sin parar: se cancela la partida", game.id)
                await self.stop("error")
        else:
            self._tick_failures = 0

    def _abandon_seconds(self, game: Game) -> float:
        block = getattr(self._settings.games, type(game).settings_key, None)
        own = float(getattr(block, "abandon_seconds", 0.0) or 0.0)
        return own if own > 0 else float(self._settings.games.abandon_seconds)

    def touch(self) -> None:
        """Actividad en la partida (lo llama ``GameHost.touch``)."""
        self._note_activity()
        self._engine.touch()

    def _note_activity(self) -> None:
        self._last_activity = self._clock()

    # -- pantalla (lo usa ``GameHost``) ---------------------------------------

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    async def set_busy(self, game_id: str, kind: BusyKind, text: str | None) -> None:
        """Enciende (``text``) o apaga (``None``) un aviso de espera del juego ``game_id``.

        Uno por tipo y juego. Un juego que ya no está en pantalla no lo enciende, y al
        terminar la partida se apagan todos los suyos.
        """
        board = self._busy_board
        if board is None:
            return
        key = f"game:{game_id}:{kind}"
        if text is None:
            await board.clear(key)
        elif self.is_active(game_id):
            await board.set(key, kind, text)

    async def _clear_busy(self, game_id: str) -> None:
        if self._busy_board is not None:
            await self._busy_board.clear_prefix(f"game:{game_id}:")

    def is_active(self, game_id: str) -> bool:
        """¿Es ``game_id`` el juego en pantalla?"""
        return self._active is not None and self._active.id == game_id

    def is_playing(self, game_id: str) -> bool:
        """¿Es ``game_id`` el juego en pantalla y aún se juega (no enseña el final)?"""
        return self.is_active(game_id) and self._phase == "playing"

    async def send(
        self, game_id: str, event: str, data: dict[str, Any] | None, *, sticky: bool
    ) -> None:
        """Manda un mensaje de la pantalla del juego en marcha (``GameHost.send``)."""
        game = self._active
        if game is None or game.id != game_id:
            logger.debug("Mensaje %s de %s sin partida en marcha: se ignora", event, game_id)
            return
        if event == p.GAME_EVENT_END:
            logger.warning("Juego %s: «end» no se manda a mano; usa finish()", game_id)
            return
        if event == p.GAME_EVENT_START:
            payload = {"title": game.title, **(data or {})}
            msg = p.msg_game(game_id, event, self._next_seq(), payload)
            self._screen_started = True
            self._screen.clear_sticky(STICKY_STATE)
            await self._screen.set_sticky(STICKY_START, msg)
            return
        await self._ensure_started(game)
        msg = p.msg_game(game_id, event, self._next_seq(), data)
        if sticky:
            await self._screen.set_sticky(STICKY_STATE, msg)
        else:
            await self._screen.broadcast_json(msg)

    async def _ensure_started(self, game: Game) -> None:
        """``start`` va siempre el primero: si el juego no lo mandó, sale solo con el título."""
        if not self._screen_started:
            await self.send(game.id, p.GAME_EVENT_START, None, sticky=True)

    async def play_animation(self, game_id: str, clip: str) -> None:
        if not self.is_active(game_id) or not clip.strip():
            return
        await self._screen.broadcast_json(p.msg_play_animation(clip.strip(), whole=True))

    # -- GPT-Live (lo usa ``GameHost``) -----------------------------------------

    @property
    def engine(self) -> GameEngineLink:
        return self._engine

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def rng(self) -> random.Random:
        return self._rng

    def now(self) -> float:
        return self._clock()

    async def sleep(self, seconds: float) -> None:
        await self._sleep(max(0.0, seconds))

    async def instruct(self, game_id: str, text: str) -> bool:
        if not self.is_active(game_id):
            return False
        text = text.strip()
        if len(text) > INSTRUCT_MAX_CHARS:
            logger.warning(
                "Instrucción de %s de %d caracteres: se corta a %d",
                game_id,
                len(text),
                INSTRUCT_MAX_CHARS,
            )
            text = text[: INSTRUCT_MAX_CHARS - 1].rstrip() + "…"
        return await self._engine.instruct(text)

    async def speak(self, game_id: str, prompt: str) -> bool:
        if not self.is_active(game_id):
            return False
        return await self._engine.speak(prompt)

    async def say_fixed(self, game_id: str, text: str) -> bool:
        """Frase grabada si la hay (sin gastar, micro callado); si no, por ``commentary``."""
        if not self.is_active(game_id) or not text.strip():
            return False
        cache = self._voice_cache
        pcm: bytes | None = None
        if cache is not None:
            try:
                pcm = await asyncio.to_thread(cache.get, text)
            except Exception:  # noqa: BLE001 - sin grabación, se pide a GPT-Live
                logger.debug("No se pudo leer la frase grabada %r", text[:60])
        if pcm:
            return await self._engine.play_clip(pcm, text)
        return await self._engine.speak(FIXED_TEXT.format(text=text.strip()))

    # -- bancos ---------------------------------------------------------------

    def bank_specs(self) -> list[tuple[Game, GameBank[Any]]]:
        """Los bancos de los juegos de esta Sonnia: ``[(juego, banco), ...]``."""
        out: list[tuple[Game, GameBank[Any]]] = []
        for game in self._games.values():
            try:
                banks = type(game).banks()
            except Exception:  # noqa: BLE001
                logger.exception("Falló banks de %s", game.id)
                continue
            out.extend((game, bank) for bank in banks)
        return out

    def _find_bank(self, bank_id: str) -> tuple[Game, GameBank[Any]] | None:
        for game, bank in self.bank_specs():
            if bank.id == bank_id:
                return game, bank
        return None

    def bank_file(self, game_id: str, bank: GameBank[Any]) -> Path:
        """El archivo de la app de un banco: ``assets/games/<juego>/<archivo>``."""
        return self._settings.games_dir / game_id / bank.file

    def bank_list(self) -> list[dict[str, Any]]:
        """Los bancos para el panel: id, juego, título, archivo, mínimo y de dónde sale."""
        return [
            {
                "id": bank.id,
                "game": game.id,
                "title": bank.title,
                "file": f"assets/games/{game.id}/{bank.file}",
                "min_entries": bank.min_entries,
                "source": "cloud" if bank.id in self._cloud_banks else "app",
            }
            for game, bank in self.bank_specs()
        ]

    def bank_text(self, bank_id: str) -> str:
        """El banco en uso, en su formato, para editarlo en el panel. Lee disco: en un hilo.

        Lanza ``KeyError`` si no existe ese banco.
        """
        found = self._find_bank(bank_id)
        if found is None:
            raise KeyError(bank_id)
        game, bank = found
        cloud = self._cloud_banks.get(bank_id)
        if cloud is not None:
            return cloud
        try:
            return self.bank_file(game.id, bank).read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("No se pudo leer el banco %s: %s", bank_id, exc)
            return ""

    def validate_bank(self, bank_id: str, text: str) -> tuple[bool, str]:
        """¿Vale ``text`` como banco ``bank_id``? ``(ok, mensaje para el panel)``. No guarda.

        Lo usa el panel antes de guardar en ``game_banks`` (orden ``set_game_bank``):
        como mucho :data:`BANK_MAX_CHARS` caracteres y al menos ``min_entries`` entradas
        válidas según el analizador del juego. Un texto vacío vale: vuelve el de la app.
        """
        found = self._find_bank(bank_id)
        if found is None:
            return False, f"No hay ningún banco «{bank_id}»."
        _, bank = found
        if not text.strip():
            return True, f"{bank.title}: vuelve el de la app."
        if len(text) > BANK_MAX_CHARS:
            return False, (
                f"{bank.title}: ocupa {len(text)} caracteres y el tope es {BANK_MAX_CHARS}."
            )
        try:
            parsed = bank.parse(text)
        except Exception as exc:  # noqa: BLE001 - un analizador roto no guarda nada
            logger.exception("Falló el analizador del banco %s", bank_id)
            return False, f"{bank.title}: no se pudo leer ({exc})."
        count = len(parsed.entries)
        if count < bank.min_entries:
            detail = f" Primer problema: {parsed.warnings[0]}" if parsed.warnings else ""
            return False, (
                f"{bank.title}: solo hay {count} entradas válidas y hacen falta "
                f"{bank.min_entries}. Revisa el formato.{detail}"
            )
        message = f"{bank.title}: {count} entradas válidas."
        skipped = len(parsed.warnings)
        if skipped == 1:
            message += f" Se saltó 1: {parsed.warnings[0]}"
        elif skipped > 1:
            message += f" Se saltaron {skipped}; la primera: {parsed.warnings[0]}"
        return True, message

    def use_cloud_banks(self, banks: Mapping[str, str] | None) -> None:
        """Los bancos guardados en la nube (``game_banks``). Mandan desde la próxima partida."""
        self._cloud_banks = normalize_game_banks(banks) or {}

    @property
    def cloud_banks(self) -> dict[str, str]:
        return dict(self._cloud_banks)

    def read_bank(self, game_id: str, bank: GameBank[T]) -> list[T]:
        """Las entradas del banco en uso (síncrona: lee disco). Nunca lanza."""
        cloud = self._cloud_banks.get(bank.id)
        if cloud is not None:
            entries = self._parse(bank, cloud, "la nube")
            if len(entries) >= bank.min_entries:
                return entries
            logger.warning(
                "El banco %s de la nube tiene %d entradas válidas y hacen falta %d: sigue el "
                "de la app",
                bank.id,
                len(entries),
                bank.min_entries,
            )
        path = self.bank_file(game_id, bank)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("No se pudo leer el banco %s (%s): %s", bank.id, path, exc)
            return []
        return self._parse(bank, text, str(path))

    @staticmethod
    def _parse(bank: GameBank[T], text: str, source: str) -> list[T]:
        try:
            parsed = bank.parse(text)
        except Exception:  # noqa: BLE001
            logger.exception("Falló el analizador del banco %s (%s)", bank.id, source)
            return []
        for warning in parsed.warnings:
            logger.warning("Banco %s (%s): %s", bank.id, source, warning)
        return list(parsed.entries)

    def draw_trivia(self, level: str | None = None) -> TriviaQuestion | None:
        """Una pregunta del banco de la trivia en uso, sin repetir (``GameHost.draw_trivia``)."""
        if self._trivia_draw is None:
            return None
        try:
            return self._trivia_draw(level)
        except Exception:  # noqa: BLE001
            logger.exception("No se pudo sacar una pregunta de la trivia")
            return None

    async def load_bank(self, game_id: str, bank: GameBank[T]) -> list[T]:
        """Como :meth:`read_bank`, en un hilo."""
        return await asyncio.to_thread(self.read_bank, game_id, bank)

    # -- frases grabadas --------------------------------------------------------

    def fixed_phrases(self) -> list[str]:
        """Las frases fijas de todos los juegos, sin repetir, para grabarlas en ``cache/voice``.

        Para «Preparar voces» y la grabación automática del panel. Puede leer disco
        (los bancos): llámala en un hilo.
        """
        seen: set[str] = set()
        out: list[str] = []
        for game in self._games.values():
            try:
                phrases = game.phrases()
            except Exception:  # noqa: BLE001
                logger.exception("Falló phrases de %s", game.id)
                continue
            for phrase in phrases:
                text = phrase.strip()
                if text and text not in seen:
                    seen.add(text)
                    out.append(text)
        return out

    # -- utilidades -----------------------------------------------------------

    async def _speak_when_quiet(self, match: int, prompt: str) -> None:
        await self._engine.wait_idle(PANEL_WAIT_S)
        if match == self._match and self._phase == "playing":
            await self._engine.speak(prompt)

    def _spawn(self, coro: Coroutine[Any, Any, Any], name: str) -> None:
        task = asyncio.create_task(coro, name=f"sonia-{name}")
        self._tasks.add(task)
        task.add_done_callback(self._task_done)

    def _task_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("La tarea %s de los juegos falló: %r", task.get_name(), task.exception())

    def _cancel_tasks(self) -> None:
        current = asyncio.current_task()
        for task in list(self._tasks):
            if task is not current and not task.done():
                task.cancel()


#: Cómo se pide una frase fija que no está grabada.
FIXED_TEXT = "Di ahora en voz alta, tal cual y sin añadir nada, esta frase: «{text}»"


def _spoken_list(items: Sequence[str]) -> str:
    """«a, b y c»."""
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + f" y {items[-1]}"


def normalize_games_off(value: Any) -> list[str]:
    """``games_off`` tal como llega de la nube: lista de ids válidos, sin repetir y ordenada."""
    if not isinstance(value, list):
        return []
    return sorted({v for v in value if p.is_game_name(v)})


def normalize_pose_model(value: Any) -> str | None:
    """``games_pose_model`` tal como llega de la nube: ``n``, ``s`` o ``None`` (el de los ajustes)."""
    return pose_variant(value)


def normalize_game_banks(value: Any) -> dict[str, str] | None:
    """``game_banks`` tal como llega de la nube: ``{banco: texto}`` válidos, o ``None`` si vacío.

    Se descartan las claves que no son ids de banco y los textos vacíos o de más de
    :data:`BANK_MAX_CHARS` caracteres.
    """
    if not isinstance(value, Mapping):
        return None
    banks = {
        key: text
        for key, text in value.items()
        if is_bank_id(key)
        and isinstance(text, str)
        and text.strip()
        and len(text) <= BANK_MAX_CHARS
    }
    return banks or None
