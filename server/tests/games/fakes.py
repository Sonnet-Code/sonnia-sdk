"""Versiones falsas para probar los juegos sin motor, sin Unity, sin cámara y sin red.

- :class:`FakeGameHost`: el ``GameHost`` de un juego suelto. Apunta lo que se dijo
  (``speak``, ``instruct``, ``say_fixed``), lo que se mandó a Unity y las animaciones,
  con un reloj y un azar controlables. Cada texto para GPT-Live se comprueba: 1200
  caracteres como mucho en ``instruct`` y ninguna marca del stack (:data:`STACK_BRANDS`).
- :class:`FakeVision`: cámara, vista en vivo, poses, manos y modelo de visión con
  personas y manos inventadas y respuestas guionizadas (:func:`person`, :func:`pose_frame`).
- :class:`FakeEngine` y :class:`FakeScreen`: el motor y el hub vistos por el
  ``GameManager``, para probar un juego de punta a punta (:func:`make_manager`).

Plantilla de uso: ``tests/games/test_ejemplo.py``.
"""

from __future__ import annotations

import asyncio
import random
import re
from collections import deque
from collections.abc import Coroutine, Iterable, Mapping, Sequence
from typing import Any, TypeVar

import numpy as np

from sonia.busy import BusyKind
from sonia.config import Settings
from sonia.games.banks import GameBank
from sonia.games.base import INSTRUCT_MAX_CHARS, Game, GameResult
from sonia.games.manager import GameManager
from sonia.trivia.bank import TriviaQuestion
from sonia.vision.contracts import (
    BODY_POINTS,
    GameVision,
    HandReading,
    HandVerdict,
    JudgeAnswer,
    Overlay,
    Person,
    Point,
    PoseFrame,
    PoseVerdict,
)
from sonia.ws import protocol as p

G = TypeVar("G", bound=Game)
T = TypeVar("T")

#: Lo que GPT-Live no puede leer: las marcas del stack (``test_sonia_no_conoce_las_marcas_de_su_stack``
#: y ``docs/plan-juegos.md``, regla 7). Sin «windows» ni «luna»: en juegos de tecnología
#: pueden salir con otro sentido.
STACK_BRANDS = (
    "gpt",
    "openai",
    "unity",
    "genies",
    "gemini",
    "yolo",
    "yolov8",
    "opencv",
    "mediapipe",
    "onnx",
)


def brands_in(text: str) -> list[str]:
    """Las marcas del stack que nombra ``text``."""
    return [b for b in STACK_BRANDS if re.search(rf"\b{b}\b", text, re.IGNORECASE)]


def check_for_live(text: str, *, limit: int | None = None) -> None:
    """Falla si ``text`` (para GPT-Live) nombra el stack o pasa de ``limit`` caracteres."""
    found = brands_in(text)
    assert not found, f"texto para GPT-Live con marcas del stack {found}: {text[:160]!r}"
    if limit is not None:
        assert len(text) <= limit, f"texto para GPT-Live de {len(text)} caracteres (tope {limit})"


def game_settings(**games: Any) -> Settings:
    """Ajustes de prueba sin leer ``.env``. ``games`` cambia campos de ``GamesSettings``."""
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    if games:
        settings = settings.model_copy(update={"games": settings.games.model_copy(update=games)})
    return settings


class FakeClock:
    """Un reloj que solo avanza cuando se le dice (``sleep`` lo adelanta sin esperar)."""

    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += max(0.0, seconds)

    async def sleep(self, seconds: float) -> None:
        self.advance(seconds)
        await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# Visión
# ---------------------------------------------------------------------------


def person(
    points: Mapping[int, tuple[float, float]],
    *,
    box: tuple[float, float, float, float] | None = None,
    score: float = 0.9,
    point_score: float = 0.9,
) -> Person:
    """Una persona inventada: sus puntos (``{L_WRIST: (x, y), ...}``) y los demás sin ver.

    Coordenadas de 0 a 1 sobre la imagen sin espejo. Sin ``box``, la caja que envuelve
    los puntos vistos.
    """
    full = tuple(
        Point(points[i][0], points[i][1], point_score) if i in points else Point(0.0, 0.0, 0.0)
        for i in range(len(BODY_POINTS))
    )
    if box is None:
        xs = [x for x, _ in points.values()] or [0.0]
        ys = [y for _, y in points.values()] or [0.0]
        box = (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
    return Person(box=box, score=score, points=full)


def pose_frame(*people: Person, at: float = 0.0, width: int = 640, height: int = 360) -> PoseFrame:
    return PoseFrame(at=at, width=width, height=height, people=tuple(people))


class FakeStream:
    def __init__(self, *, available: bool = True, frame: np.ndarray | None = None) -> None:
        self.available = available
        self.frame = frame if frame is not None else np.zeros((360, 640, 3), dtype=np.uint8)
        self.owners: set[str] = set()
        self.at = 0.0

    @property
    def active(self) -> bool:
        return bool(self.owners)

    async def acquire(self, owner: str) -> bool:
        if not self.available:
            return False
        self.owners.add(owner)
        return True

    async def release(self, owner: str) -> None:
        self.owners.discard(owner)

    def latest(self) -> tuple[float, np.ndarray] | None:
        if not self.owners:
            return None
        return self.at, self.frame


class FakePreview:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.owners: set[str] = set()
        self.starts: list[tuple[str, bool]] = []
        self.stops: list[str] = []
        self.overlay: Overlay | None = None

    @property
    def active(self) -> bool:
        return bool(self.owners)

    async def start(
        self, owner: str, *, mirror: bool = True, overlay: Overlay | None = None
    ) -> bool:
        if not self.available:
            return False
        self.owners.add(owner)
        self.starts.append((owner, mirror))
        self.overlay = overlay
        return True

    def set_overlay(self, overlay: Overlay | None) -> None:
        self.overlay = overlay

    async def stop(self, owner: str) -> None:
        if owner in self.owners:
            self.owners.discard(owner)
            self.stops.append(owner)

    def draw(self, frame: np.ndarray | None = None, *, mirrored: bool = True) -> np.ndarray:
        """Pinta el overlay actual sobre un frame (negro si no se da), para probarlo."""
        image = frame if frame is not None else np.zeros((360, 640, 3), dtype=np.uint8)
        if self.overlay is not None:
            self.overlay(image, mirrored)
        return image


class FakePoses:
    """Detecciones guionizadas: ``frames`` salen en orden; agotadas, se repite la última."""

    def __init__(self, frames: Iterable[PoseFrame] = (), *, available: bool = True) -> None:
        self.available_flag = available
        self.frames: deque[PoseFrame] = deque(frames)
        self.current: PoseFrame | None = None
        self.owners: dict[str, float] = {}

    @property
    def available(self) -> bool:
        return self.available_flag

    def push(self, *frames: PoseFrame) -> None:
        self.frames.extend(frames)

    def _next(self) -> PoseFrame | None:
        if self.frames:
            self.current = self.frames.popleft()
        return self.current

    async def acquire(self, owner: str, fps: float) -> bool:
        if not self.available_flag:
            return False
        self.owners[owner] = fps
        return True

    async def release(self, owner: str) -> None:
        self.owners.pop(owner, None)

    def latest(self, max_age_s: float = 0.5) -> PoseFrame | None:
        return self._next()

    async def detect(self, frame_bgr: np.ndarray, at: float) -> PoseFrame:
        found = self._next()
        if found is not None:
            return found
        height, width = frame_bgr.shape[:2]
        return PoseFrame(at=at, width=int(width), height=int(height), people=())


class FakeHands:
    """Lecturas guionizadas: cada ``read`` saca la siguiente lista (agotadas, vacío)."""

    def __init__(
        self, readings: Iterable[list[HandReading]] = (), *, available: bool = True
    ) -> None:
        self.available_flag = available
        self.readings: deque[list[HandReading]] = deque(readings)
        self.reads = 0

    @property
    def available(self) -> bool:
        return self.available_flag

    async def read(self, frame_bgr: np.ndarray, person: Person) -> list[HandReading]:
        self.reads += 1
        return self.readings.popleft() if self.readings else []


class FakeJudge:
    """Respuestas guionizadas del modelo de visión (agotadas, «no se ve»); apunta las preguntas."""

    def __init__(
        self, answers: Iterable[JudgeAnswer | None] = (), *, available: bool = True
    ) -> None:
        self.available_flag = available
        self.answers: deque[JudgeAnswer | None] = deque(answers)
        self.questions: list[str] = []

    @property
    def available(self) -> bool:
        return self.available_flag

    async def ask(self, question: str) -> JudgeAnswer | None:
        self.questions.append(question)
        return self.answers.popleft() if self.answers else JudgeAnswer(seen=False)


class FakeReferee:
    """Veredictos guionizados del juez de rondas (``GAMES_JUDGE``); apunta las fotos.

    Sin veredictos en la cola, ``None`` (como si no contestara a tiempo): el juego decide
    con la detección local. ``available=False`` es ``GAMES_JUDGE=local`` o sin clave.
    """

    def __init__(
        self,
        poses: Iterable[PoseVerdict | None] = (),
        hands: Iterable[HandVerdict | None] = (),
        *,
        available: bool = True,
    ) -> None:
        self.available_flag = available
        self.pose_verdicts: deque[PoseVerdict | None] = deque(poses)
        self.hand_verdicts: deque[HandVerdict | None] = deque(hands)
        #: ``("poses" | "hands", forma del frame)`` de cada foto que se le pasó.
        self.photos: list[tuple[str, tuple[int, ...]]] = []

    @property
    def available(self) -> bool:
        return self.available_flag

    async def poses(self, frame_bgr: np.ndarray) -> PoseVerdict | None:
        self.photos.append(("poses", tuple(frame_bgr.shape)))
        return self.pose_verdicts.popleft() if self.pose_verdicts else None

    async def hands(self, frame_bgr: np.ndarray) -> HandVerdict | None:
        self.photos.append(("hands", tuple(frame_bgr.shape)))
        return self.hand_verdicts.popleft() if self.hand_verdicts else None


class FakeVision:
    """Toda la visión falsa junta; :meth:`game_vision` la da como ``GameVision``."""

    def __init__(
        self,
        *,
        stream: FakeStream | None = None,
        preview: FakePreview | None = None,
        poses: FakePoses | None = None,
        hands: FakeHands | None = None,
        judge: FakeJudge | None = None,
        referee: FakeReferee | None = None,
    ) -> None:
        self.stream = stream or FakeStream()
        self.preview = preview or FakePreview()
        self.poses = poses or FakePoses()
        self.hands = hands or FakeHands()
        self.judge = judge or FakeJudge()
        #: Por defecto, sin juez de rondas (``GAMES_JUDGE=local``): los tests de antes
        #: siguen decidiendo con la detección local.
        self.referee = referee or FakeReferee(available=False)
        self.closed = False

    async def _close(self) -> None:
        self.closed = True

    def game_vision(self) -> GameVision:
        return GameVision(
            stream=self.stream,
            preview=self.preview,
            poses=self.poses,
            hands=self.hands,
            judge=self.judge,
            close=self._close,
            referee=self.referee,
        )


# ---------------------------------------------------------------------------
# GameHost falso (un juego suelto)
# ---------------------------------------------------------------------------


class FakeGameHost:
    """El ``GameHost`` de un juego suelto, sin motor ni Unity. Apunta todo.

    - ``spoken``, ``instructions``: lo que se le pasó a GPT-Live (comprobado: sin marcas
      del stack y, ``instructions``, 1200 caracteres como mucho).
    - ``fixed``: ``(frase, grabada)`` de cada ``say_fixed``; ``recorded`` son las frases
      que están en la caché de voces.
    - ``sent``: ``{"event", "data", "sticky"}`` de cada ``send``; :meth:`events` y :meth:`last`.
    - ``animations``, ``finished`` (``(resultado, data)``) y ``touches``.
    - ``clock``: el reloj (``now``/``sleep``); ``rng`` con semilla.
    - ``cloud_banks``: bancos «guardados en la nube» (``{banco: texto}``); si no, el
      archivo de la app en ``settings.games_dir/<game_id>/``.
    - ``trivia_questions``: lo que dará ``draw_trivia`` (``TriviaQuestion``), en orden.
    """

    def __init__(
        self,
        game_id: str = "",
        *,
        settings: Settings | None = None,
        seed: int = 1,
        vision: FakeVision | None = None,
        cloud_banks: Mapping[str, str] | None = None,
        recorded: Iterable[str] = (),
        connected: bool = True,
        clock: FakeClock | None = None,
        trivia_questions: Iterable[TriviaQuestion] = (),
    ) -> None:
        self.game_id = game_id
        self.settings = settings or game_settings()
        self.rng = random.Random(seed)
        self.clock = clock or FakeClock()
        self.vision = vision or FakeVision()
        self.cloud_banks = dict(cloud_banks or {})
        self.recorded = set(recorded)
        self.connected = connected
        self.quiet = 10.0
        self.idle = True
        self.spoken: list[str] = []
        self.instructions: list[str] = []
        self.fixed: list[tuple[str, bool]] = []
        self.sent: list[dict[str, Any]] = []
        self.animations: list[str] = []
        self.finished: list[tuple[GameResult, dict[str, Any] | None]] = []
        #: ``(tipo, texto o None)`` de cada ``set_busy``; ``busy_now``, los encendidos ahora.
        self.busy: list[tuple[str, str | None]] = []
        self.busy_now: dict[str, str] = {}
        self.touches = 0
        self.tasks: list[asyncio.Task[Any]] = []
        #: Preguntas de la trivia que dará ``draw_trivia``, en orden.
        self.trivia_questions: deque[TriviaQuestion] = deque(trivia_questions)
        self.trivia_levels: list[str | None] = []

    # -- reloj ---------------------------------------------------------------

    def now(self) -> float:
        return self.clock()

    async def sleep(self, seconds: float) -> None:
        await self.clock.sleep(seconds)

    # -- GPT-Live ------------------------------------------------------------

    async def speak(self, prompt: str) -> bool:
        check_for_live(prompt)
        self.spoken.append(prompt)
        return self.connected

    async def instruct(self, text: str) -> bool:
        check_for_live(text, limit=INSTRUCT_MAX_CHARS)
        self.instructions.append(text)
        return self.connected

    async def say_fixed(self, text: str) -> bool:
        check_for_live(text)
        self.fixed.append((text, text in self.recorded))
        return self.connected

    async def wait_idle(self, limit_s: float | None = None) -> bool:
        return self.idle

    def quiet_for(self) -> float:
        return self.quiet

    def touch(self) -> None:
        self.touches += 1

    # -- pantalla ------------------------------------------------------------

    async def send(
        self, event: str, data: dict[str, Any] | None = None, *, sticky: bool = True
    ) -> None:
        assert p.is_game_name(event), f"evento con forma inválida: {event!r}"
        assert event != p.GAME_EVENT_END, "«end» no se manda a mano: usa finish()"
        self.sent.append({"event": event, "data": dict(data or {}), "sticky": sticky})

    def events(self, event: str | None = None) -> list[dict[str, Any]]:
        """Los ``data`` de lo mandado (de un evento, o de todos)."""
        return [m["data"] for m in self.sent if event is None or m["event"] == event]

    def last(self, event: str) -> dict[str, Any]:
        found = self.events(event)
        assert found, f"no se mandó ningún «{event}»"
        return found[-1]

    async def play_animation(self, clip: str) -> None:
        self.animations.append(clip)

    async def finish(self, result: GameResult, data: dict[str, Any] | None = None) -> None:
        assert result in p.GAME_RESULTS
        self.finished.append((result, data))

    # -- visión --------------------------------------------------------------

    @property
    def stream(self) -> FakeStream:
        return self.vision.stream

    @property
    def preview(self) -> FakePreview:
        return self.vision.preview

    @property
    def poses(self) -> FakePoses:
        return self.vision.poses

    @property
    def hands(self) -> FakeHands:
        return self.vision.hands

    @property
    def judge(self) -> FakeJudge:
        return self.vision.judge

    @property
    def referee(self) -> FakeReferee:
        return self.vision.referee

    # -- aviso de espera -----------------------------------------------------

    async def set_busy(self, kind: BusyKind, text: str | None) -> None:
        self.busy.append((kind, text))
        if text is None:
            self.busy_now.pop(kind, None)
        else:
            self.busy_now[kind] = text

    # -- tareas y bancos -----------------------------------------------------

    def spawn(self, coro: Coroutine[Any, Any, Any], name: str) -> None:
        self.tasks.append(asyncio.create_task(coro, name=f"test-{name}"))

    async def run_tasks(self) -> None:
        """Espera a que terminen las tareas lanzadas con ``spawn`` (y las que lancen)."""
        while any(not t.done() for t in self.tasks):
            await asyncio.gather(*self.tasks)

    def read_bank(self, bank: GameBank[T]) -> list[T]:
        text = self.cloud_banks.get(bank.id)
        if text is not None:
            parsed = bank.parse(text)
            if len(parsed.entries) >= bank.min_entries:
                return list(parsed.entries)
        path = self.settings.games_dir / self.game_id / bank.file
        return list(bank.parse(path.read_text(encoding="utf-8")).entries)

    async def load_bank(self, bank: GameBank[T]) -> list[T]:
        return self.read_bank(bank)

    def draw_trivia(self, level: str | None = None) -> TriviaQuestion | None:
        """La siguiente de ``trivia_questions`` (apunta el nivel pedido en ``trivia_levels``)."""
        self.trivia_levels.append(level)
        return self.trivia_questions.popleft() if self.trivia_questions else None


def make_game[G: Game](cls: type[G], **kwargs: Any) -> tuple[G, FakeGameHost]:
    """Un juego suelto con su :class:`FakeGameHost` (``kwargs`` van al host)."""
    host = FakeGameHost(cls.id, **kwargs)
    return cls(host), host


# ---------------------------------------------------------------------------
# Motor y pantalla falsos (el GameManager de punta a punta)
# ---------------------------------------------------------------------------


class FakeEngine:
    """El motor GPT-Live visto por el ``GameManager``. Apunta y comprueba lo que se le pasa."""

    def __init__(self) -> None:
        self.connected = True
        self.quiet = 10.0
        self.spoken: list[str] = []
        self.instructions: list[str] = []
        self.clips: list[str] = []
        self.touches = 0

    async def speak(self, prompt: str) -> bool:
        check_for_live(prompt)
        self.spoken.append(prompt)
        return self.connected

    async def instruct(self, text: str) -> bool:
        check_for_live(text, limit=INSTRUCT_MAX_CHARS)
        self.instructions.append(text)
        return self.connected

    async def wait_idle(self, limit_s: float | None = None) -> bool:
        return True

    def quiet_for(self) -> float:
        return self.quiet

    def touch(self) -> None:
        self.touches += 1

    async def play_clip(self, pcm: bytes, text: str, *, attention: str | None = None) -> bool:
        self.clips.append(text)
        return True


class FakeScreen:
    """El hub de Unity visto por el ``GameManager``: apunta lo mandado y los mensajes fijos."""

    def __init__(self, clients: int = 1) -> None:
        self.client_count = clients
        self.sent: list[dict[str, Any]] = []
        self.sticky: dict[str, dict[str, Any]] = {}
        self.hidden = 0

    async def broadcast_json(self, msg: dict[str, Any]) -> None:
        self.sent.append(msg)

    async def set_sticky(self, key: str, msg: dict[str, Any]) -> None:
        self.sticky[key] = msg
        self.sent.append(msg)

    def clear_sticky(self, key: str) -> None:
        self.sticky.pop(key, None)

    async def hide_image(self) -> None:
        self.hidden += 1

    def game_msgs(self, event: str | None = None) -> list[dict[str, Any]]:
        """Los mensajes ``game`` mandados (de un evento, o todos)."""
        return [
            m
            for m in self.sent
            if m.get("type") == p.MSG_GAME and (event is None or m.get("event") == event)
        ]

    def replay(self) -> list[dict[str, Any]]:
        """Lo que recibiría una Unity que se reconecta ahora (los fijos, en orden)."""
        return list(self.sticky.values())


class FakeVoiceCache:
    """Las frases grabadas: ``get`` devuelve PCM para las de ``recorded``."""

    def __init__(self, recorded: Iterable[str] = ()) -> None:
        self.recorded = set(recorded)

    def get(self, text: str) -> bytes | None:
        return b"\x00\x01" * 2400 if text in self.recorded else None


async def make_manager(
    games: Sequence[type[Game]],
    *,
    settings: Settings | None = None,
    vision: FakeVision | None = None,
    unity_games: Iterable[str] | None = None,
    features: Iterable[str] = (p.FEATURE_CAMERA_PREVIEW,),
    camera: bool = True,
    recorded: Iterable[str] = (),
    busy: Any = None,
    trivia_draw: Any = None,
    seed: int = 1,
) -> tuple[GameManager, FakeEngine, FakeScreen, FakeClock]:
    """Un ``GameManager`` con motor, pantalla, visión y reloj falsos, y una Unity que ya
    anunció ``unity_games`` (por defecto, todos los ``games``)."""
    engine, screen, clock = FakeEngine(), FakeScreen(), FakeClock()
    manager = GameManager(
        settings or game_settings(result_seconds=0.0, final_wait_seconds=0.0),
        engine=engine,
        screen=screen,
        vision=(vision or FakeVision()).game_vision(),
        voice_cache=FakeVoiceCache(recorded),
        games=games,
        camera_ready=lambda: camera,
        busy=busy,
        trivia_draw=trivia_draw,
        rng=random.Random(seed),
        clock=clock,
        sleep=clock.sleep,
    )
    ids = [g.id for g in games] if unity_games is None else list(unity_games)
    await manager.on_client_hello(
        {
            "type": p.MSG_CLIENT_HELLO,
            "client": "unity",
            "version": "test",
            "games": ids,
            "features": list(features),
        }
    )
    return manager, engine, screen, clock


async def settle(rounds: int = 5) -> None:
    """Deja correr las tareas en segundo plano del manager (finales, empujones)."""
    for _ in range(rounds):
        await asyncio.sleep(0)
