"""El contrato de un juego del stand (``docs/juegos.md``).

Un juego es una subclase de :class:`Game` que sobreescribe solo lo suyo: los
ganchos vienen vacíos. Lo que el juego puede usar del motor, de la pantalla y de
la cámara le llega por :class:`GameHost` (``self.host``): nunca toca el motor ni
el hub directamente, así se prueba entero con ``tests/games/fakes.py``.

Reparto (lección de la trivia, ``docs/trivia.md``):

- **GPT-Live entiende y conduce.** Una sola delegación para empezar
  (``start_game``); las jugadas que exigen entender al visitante van por una
  acción del juego (:meth:`Game.actions`), una por jugada. Nada de parsers de lo
  que dice el visitante.
- **El orquestador guarda la clave y la pantalla.** Lo que GPT-Live tiene que
  saber va por :meth:`GameHost.instruct` (no la hace hablar, 1200 caracteres
  como mucho) y lo que tiene que decir ya, por :meth:`GameHost.speak` o como
  resultado de la acción (marcado con :data:`SCRIPT_PREFIX`).
- **Nada tumba el motor.** Un fallo de un juego va al registro; si la sesión se
  cae, la partida se cancela.
"""

from __future__ import annotations

import random
from collections.abc import Coroutine
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Protocol, TypeVar

from sonia.types import ActionSpec
from sonia.vision.contracts import (
    CameraStream,
    GameReferee,
    HandDetector,
    PoseDetector,
    PreviewStreamer,
    VisionJudge,
)

if TYPE_CHECKING:
    from sonia.busy import BusyKind
    from sonia.config import Settings
    from sonia.games.banks import GameBank
    from sonia.trivia.bank import TriviaQuestion

__all__ = [
    "INSTRUCT_MAX_CHARS",
    "NEEDS",
    "NOT_SAID",
    "NOT_SAID_VALUES",
    "SCRIPT_PREFIX",
    "STOP_REASONS",
    "Game",
    "GameError",
    "GameHost",
    "GameResult",
    "Need",
    "StopReason",
]

#: Lo que puede necesitar un juego para ofrecerse (``Game.needs``):
#:
#: - ``camera``: la cámara USB (``VISION_SOURCE=opencv``).
#: - ``preview``: la vista en vivo en la pantalla (la Unity anuncia ``camera_preview``).
#: - ``poses``: el detector de poses (``PoseDetector.available``).
#: - ``hands``: el lector de manos (``HandDetector.available``).
#: - ``vision_llm``: el modelo de visión de la nube (``VisionJudge.available``).
Need = Literal["camera", "preview", "poses", "hands", "vision_llm"]
NEEDS: frozenset[str] = frozenset({"camera", "preview", "poses", "hands", "vision_llm"})

#: Resultado de una partida (``data.result`` del evento ``end``).
GameResult = Literal["win", "lose", "cancel"]

#: Por qué termina una partida (lo recibe :meth:`Game.stop`):
#:
#: - ``finished``: el juego terminó solo (:meth:`GameHost.finish`).
#: - ``voice``: GPT-Live delegó ``stop_game``.
#: - ``panel``: «Terminar juego» en el panel, o el juego se apagó desde el panel.
#: - ``abandoned``: nadie habla ni hay nadie delante durante su tiempo de abandono.
#: - ``session``: se cayó o se renovó la sesión de GPT-Live, o cambió el modo.
#: - ``unity``: la Unity que se conectó no sabe pintar el juego.
#: - ``replaced``: empezó otro juego cuando este ya había terminado.
#: - ``error``: el juego falló al empezar.
#: - ``shutdown``: se apaga el orquestador.
StopReason = Literal[
    "finished", "voice", "panel", "abandoned", "session", "unity", "replaced", "error", "shutdown"
]
STOP_REASONS: frozenset[str] = frozenset(
    {"finished", "voice", "panel", "abandoned", "session", "unity", "replaced", "error", "shutdown"}
)

#: Marca del guion que el backend le pasa entero a Sonia (``BACKEND_PROMPT``), como en la trivia.
SCRIPT_PREFIX = "PARA SONIA:"

#: Tope de cada :meth:`GameHost.instruct` (``session.instructions.append`` corta ahí). Las
#: instrucciones largas hicieron que GPT-Live dejara de delegar (7 de octubre de 2026).
INSTRUCT_MAX_CHARS = 1_200

#: Valor de un enum de una jugada cuando el visitante no lo dijo. Cada enum lleva uno de
#: :data:`NOT_SAID_VALUES` (lección de la trivia: con el nivel opcional, el backend lo
#: rellenaba siempre con «fácil»).
NOT_SAID = "no_lo_dijo"
NOT_SAID_VALUES: frozenset[str] = frozenset({NOT_SAID, "no_lo_sabe", "se_rinden", "sin_elegir"})

T = TypeVar("T")


class GameError(Exception):
    """El juego no puede hacer eso ahora. El mensaje lo lee GPT-Live (o el panel) tal cual.

    Lánzala desde :meth:`Game.start` (no se puede empezar: banco vacío, sin cámara...) o
    desde una jugada (no toca ahora). El manager la convierte en el texto del resultado.
    """


class GameHost(Protocol):
    """Lo que un juego puede usar: GPT-Live, la pantalla de Unity, la cámara y el reloj.

    Cada juego tiene el suyo, atado a su id (:class:`sonia.games.host.ManagedGameHost`
    sobre el motor; ``tests/games/fakes.py:FakeGameHost`` en los tests). Nada lanza:
    sin sesión o sin pantalla, lo que no se pudo hacer devuelve ``False`` o no hace nada.
    """

    # -- ajustes, azar y reloj ------------------------------------------------

    @property
    def settings(self) -> Settings:
        """Toda la configuración. Lo tuyo está en ``settings.games.<tu bloque>``
        (``GAME_<X>_*``); también vale ``settings.trivia.win_contact`` (a quién mandar
        a quien gana)."""
        ...

    @property
    def rng(self) -> random.Random:
        """El azar del juego (en los tests, con semilla)."""
        ...

    def now(self) -> float:
        """El reloj del juego: ``time.monotonic()`` (en los tests, uno que se adelanta a mano).

        Es el mismo reloj del ``now`` de :meth:`Game.tick`.
        """
        ...

    async def sleep(self, seconds: float) -> None:
        """Espera con el reloj del juego (en los tests no espera de verdad: adelanta el reloj)."""
        ...

    # -- GPT-Live -------------------------------------------------------------

    @property
    def connected(self) -> bool:
        """¿Hay sesión de GPT-Live?"""
        ...

    async def speak(self, prompt: str) -> bool:
        """Que Sonia diga algo ya (``session.commentary.append``). Lo dice con sus palabras."""
        ...

    async def instruct(self, text: str) -> bool:
        """Que GPT-Live lo sepa sin hablar (``session.instructions.append``).

        Como mucho :data:`INSTRUCT_MAX_CHARS` caracteres: lo que pase se corta (y en
        los tests, falla). Las reglas del juego entran así al empezar.
        """
        ...

    async def say_fixed(self, text: str) -> bool:
        """Una frase exacta en el tiempo («¡Simón dice…!»).

        Si está grabada en la caché de voces (``cache/voice``) suena tal cual, sin
        gastar y con el micro callado mientras suena; si no, se le pide a GPT-Live por
        ``commentary`` que la diga tal cual. Declárala en :meth:`Game.phrases` para que
        se grabe. ``False`` si no se pudo (Sonia ya está hablando o no hay sesión).
        """
        ...

    async def wait_idle(self, limit_s: float | None = None) -> bool:
        """Espera a que nadie hable y Sonia no hable ni piense. ``False`` si venció ``limit_s``."""
        ...

    def quiet_for(self) -> float:
        """Segundos que Sonia lleva callada (0 mientras habla)."""
        ...

    def touch(self) -> None:
        """Hay actividad: la partida no se da por abandonada y el motor no se aburre.

        Llámala si ves gente con la cámara aunque nadie hable (poses, piedra, papel o tijera).
        """
        ...

    # -- pantalla de Unity ----------------------------------------------------

    async def send(
        self, event: str, data: dict[str, Any] | None = None, *, sticky: bool = True
    ) -> None:
        """Manda ``{"type": "game", "game": <tu id>, "event": ..., "seq": ..., "data": ...}``.

        - ``start`` monta tu pantalla: si no lo mandas tú en :meth:`Game.start`, sale solo
          con ``{"title": title}``; si lo mandas, ``title`` se añade si falta. Va siempre
          el primero.
        - ``end`` no lo mandes: termina con :meth:`finish`.
        - ``sticky``: el mensaje se repite si Unity se reconecta (tras ``start``). Solo
          se guarda el último, así que manda estados completos o ``sticky=False`` para
          los efectos sueltos (un confeti).
        """
        ...

    async def play_animation(self, clip: str) -> None:
        """Una animación o gesto de Sonia, entero (``play_animation`` con ``whole=True``)."""
        ...

    async def finish(self, result: GameResult, data: dict[str, Any] | None = None) -> None:
        """El juego terminó: ``win``, ``lose`` o ``cancel``. No bloquea.

        Con ``win`` o ``lose`` el resultado se queda en pantalla al menos
        ``GAMES_RESULT_SECONDS`` y hasta que Sonia termina de contarlo (como mucho
        ``GAMES_FINAL_WAIT_SECONDS``); luego el manager llama a :meth:`Game.stop`
        (``finished``), manda ``end`` con ``data`` y le dice a GPT-Live que vuelva a
        conversar. Con ``cancel``, ya. Mientras tanto las jugadas ya no llegan al juego.
        """
        ...

    # -- cámara y visión (``sonia.vision.contracts``) --------------------------

    @property
    def stream(self) -> CameraStream:
        """La cámara USB en continuo. ``acquire(<tu id>)`` y ``release`` al acabar."""
        ...

    @property
    def preview(self) -> PreviewStreamer:
        """La vista en vivo encima de Sonnia. ``start(<tu id>, overlay=...)``."""
        ...

    @property
    def poses(self) -> PoseDetector: ...

    @property
    def hands(self) -> HandDetector: ...

    @property
    def judge(self) -> VisionJudge: ...

    @property
    def referee(self) -> GameReferee:
        """El juez de las rondas de cámara (``GAMES_JUDGE``): una foto reducida por ronda.

        ``available`` es ``False`` con ``GAMES_JUDGE=local`` o sin clave; sus respuestas
        ``None`` (sin respuesta a tiempo) obligan a decidir con la detección local.
        """
        ...

    # -- aviso de espera (``sonia.busy``) ---------------------------------------

    async def set_busy(self, kind: BusyKind, text: str | None) -> None:
        """Enciende (``text``) o apaga (``None``) la pastilla de espera de la pantalla.

        Para lo que el visitante espera sin ver nada: el juez mirando la foto de la ronda
        (``judge``), la cámara arrancando (``camera``). Una por tipo; se apagan todas al
        terminar la partida. Los textos están en ``sonia.busy`` (``TEXT_POSES``...).
        """
        ...

    # -- tareas y bancos ------------------------------------------------------

    def spawn(self, coro: Coroutine[Any, Any, Any], name: str) -> None:
        """Una tarea en segundo plano del juego: se cancela sola al terminar la partida.

        Sus errores van al registro y no tumban nada.
        """
        ...

    async def load_bank(self, bank: GameBank[T]) -> list[T]:
        """Las entradas del banco en uso, leídas ahora (en un hilo).

        Manda el de la nube (``game_banks``, editado desde el panel) si tiene al menos
        ``bank.min_entries`` válidas; si no, el archivo de la app
        (``assets/games/<juego>/<archivo>``). Llámala al empezar cada partida.
        """
        ...

    def read_bank(self, bank: GameBank[T]) -> list[T]:
        """Como :meth:`load_bank`, pero síncrona (lee disco): solo desde un hilo o en
        :meth:`Game.phrases`."""
        ...

    def draw_trivia(self, level: str | None = None) -> TriviaQuestion | None:
        """Una pregunta del banco de la trivia en uso (``TriviaGame.draw_one``).

        Con las opciones barajadas y sin repetir hasta agotar el nivel (``fácil``,
        ``intermedio`` o ``difícil``; sin nivel, el de ``TRIVIA_DEFAULT_LEVEL``).
        ``None`` si la trivia está apagada o sin preguntas. La usa la ruleta.
        """
        ...


class Game:
    """Un juego del stand. Sobreescribe solo lo tuyo: los ganchos vienen vacíos.

    Hay una instancia por juego durante toda la vida del motor: :meth:`start` empieza
    de cero (reinicia todo tu estado). La crea el manager con su :class:`GameHost`.
    """

    #: Id del juego: el del protocolo, el de ``start_game`` y el de ``client_hello.games``.
    id: ClassVar[str]
    #: En pantalla (con «Sonnia», nunca «Sonia»): «Wordle de tecnología».
    title: ClassVar[str]
    #: Para GPT-Live y el panel (con «Sonia»): «el Wordle de tecnología».
    spoken: ClassVar[str]
    #: Lo que necesita para ofrecerse (:data:`NEEDS`).
    needs: ClassVar[frozenset[str]] = frozenset()
    #: Su bloque en ``Settings.games`` (``GAME_<X>_*``): ``ruleta``, ``ppt``...
    settings_key: ClassVar[str]

    def __init__(self, host: GameHost) -> None:
        self.host = host

    # -- lo que declara el juego ----------------------------------------------

    @classmethod
    def actions(cls) -> list[ActionSpec]:
        """Sus jugadas delegadas (además de ``start_game`` y ``stop_game``).

        Se registran al arrancar, así que es de clase. Créalas con
        :func:`sonia.actions.games.game_action`: el handler recibe la partida en marcha.
        Nombres con el prefijo del juego (``wordle_guess``) y esquemas estrictos: todos
        los parámetros obligatorios y en cada enum un valor de :data:`NOT_SAID_VALUES`.
        """
        return []

    @classmethod
    def banks(cls) -> list[GameBank[Any]]:
        """Sus bancos editables desde el backoffice (:class:`sonia.games.banks.GameBank`)."""
        return []

    def phrases(self) -> list[str]:
        """Las frases fijas que dice con :meth:`GameHost.say_fixed`, para grabarlas.

        Entran en «Preparar voces» y en la grabación automática de ``cache/voice``. Puede
        leer los bancos con :meth:`GameHost.read_bank` (se llama en un hilo).
        """
        return []

    def unavailable_reason(self) -> str | None:
        """Por qué no se puede jugar ahora (``None``: se puede). Lo lee GPT-Live.

        El manager ya comprueba lo común (apagado, Unity, ``needs``, sesión, otro
        juego o la trivia): aquí va lo propio, como un banco sin entradas.
        """
        return None

    # -- ciclo de vida ----------------------------------------------------------

    async def start(self, source: str, options: dict[str, Any]) -> str:
        """Empieza una partida y devuelve el guion de arranque para Sonia.

        ``source``: ``voice`` (``start_game``: el guion vuelve como resultado de la
        acción) o ``panel`` (el manager se lo pasa a GPT-Live en cuanto calla).
        ``options``: lo que añada el panel (de momento, nada).

        Aquí: reinicia tu estado, carga tus bancos (:meth:`GameHost.load_bank`), manda
        ``start`` y tu primera pantalla, y pasa tus reglas con :meth:`GameHost.instruct`.
        Si no se puede, lanza :class:`GameError` con el motivo.
        """
        raise GameError("Este juego aún no está listo.")

    async def resume(self) -> str:
        """El guion si GPT-Live vuelve a delegar empezar el juego que ya está en marcha."""
        return (
            f"Ya estáis jugando a {self.spoken}: no hace falta empezarlo. Sigue con la partida "
            "donde iba."
        )

    async def stop_requested(self, source: str) -> str | None:
        """Le piden terminar con la partida en marcha: por voz (``stop_game``, ``source`` =
        ``voice``) o con «Terminar juego» en el panel (``panel``). Opcional.

        Por defecto devuelve ``None`` y la partida se cancela como siempre. Si el juego
        quiere cerrar enseñando su final (el Wordle enseña la palabra, como al perder),
        lo enseña, se cierra él mismo con :meth:`GameHost.finish` y devuelve el guion para
        Sonia: el manager no cancela, sigue el final normal (``GAMES_RESULT_SECONDS`` y a
        que Sonia termine de hablar) y le pasa el guion a GPT-Live (por voz, como
        resultado de ``stop_game``; desde el panel, por ``speak``). Si devuelve un guion
        sin haber llamado a ``finish``, se cancela igual.
        """
        return None

    async def stop(self, reason: StopReason) -> None:
        """La partida termina (siempre una vez, sea cual sea el motivo): suelta lo tuyo.

        El manager ya cancela tus tareas (:meth:`GameHost.spawn`), suelta la cámara, la
        vista en vivo y los detectores a tu nombre, manda ``end`` y le dice a GPT-Live
        que vuelva a conversar. No hables aquí.
        """
        return None

    async def tick(self, now: float) -> None:
        """Cada 50 ms mientras dura la partida (``now``: :meth:`GameHost.now`)."""
        return None

    # -- ganchos (por defecto no hacen nada) -------------------------------------

    async def on_assistant_text(self, text: str, final: bool) -> None:
        """Lo que va diciendo Sonia: el texto acumulado de la frase en curso.

        Con ``final=True``, la frase entera, una vez al cerrarse. Sirve para sincronizar
        la pantalla con lo que dice (contar sus preguntas en el Akinator), no para
        entender al visitante.
        """
        return None

    def on_user_text(self, now: float) -> None:
        """Se oye al visitante (llega transcripción). Sin texto: no se parsea al visitante."""
        return None

    def on_user_turn_end(self, now: float, started_at: float) -> None:
        """Terminó un turno del visitante que empezó en ``started_at``."""
        return None

    def on_delegation(self, now: float) -> None:
        """GPT-Live delegó algo en el backend."""
        return None

    async def on_unity_event(self, event: str, data: dict[str, Any]) -> None:
        """Un ``game_event`` de tu pantalla (``wheel_stopped``...)."""
        return None

    def nudge(self) -> str | None:
        """Texto del empujón si el visitante habla y no se delega nada (``None``: sin empujón).

        Como el de la trivia: si en ``GAMES_NUDGE_SECONDS`` tras su turno no se delegó
        nada y Sonia calla, el manager se lo pasa por ``commentary``. Útil cuando cada
        turno del visitante debería ser una jugada (el Wordle); no en el Akinator, donde
        Sonia pregunta sin delegar.
        """
        return None

    def snapshot(self) -> dict[str, Any]:
        """Para el panel: en qué va la partida (tipos JSON)."""
        return {}

    # -- control a mano desde el panel (``docs/juegos.md``, «Control a mano») ------

    def panel_controls(self) -> list[dict[str, Any]]:
        """Los controles del panel para llevar la partida a mano ahora, por si falla la voz
        o la cámara (Jean, 10 de octubre de 2026: «por si acaso algo sale mal»).

        Solo los que valen en este momento de la partida, en orden: cada uno
        ``{"id": "found", "label": "¡Lo encontró!"}`` (un botón) o, con ``"kind": "text"``,
        un campo de texto con su botón (``"placeholder"`` opcional). El panel los pinta tal
        cual y manda el ``id`` (y el texto) a :meth:`panel_control`. «Reiniciar» y
        «Terminar» los pone el manager para todos.
        """
        return []

    async def panel_control(self, control: str, value: str) -> str:
        """Lo que hace el control ``control`` del panel (``value``: el texto de un campo).

        Mueve el juego y la pantalla como la jugada de GPT-Live (reutiliza su handler) y
        devuelve el guion para Sonia, que el manager le pasa en cuanto calla. ``GameError``
        con un mensaje para el equipo si no vale ahora.
        """
        raise GameError("Ese control no está disponible ahora.")
