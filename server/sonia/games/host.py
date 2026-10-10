"""``GameHost`` sobre el motor: lo que cada juego usa, atado a su id (``docs/juegos.md``).

Cada juego tiene el suyo (:class:`ManagedGameHost`), que pasa por el
:class:`~sonia.games.manager.GameManager`. Así:

- Un juego que ya no está en pantalla no puede hablar ni mandar nada a Unity (una
  tarea rezagada no pinta encima del siguiente juego).
- ``instruct`` corta a 1200 caracteres (``session.instructions.append``).
- ``say_fixed`` usa la frase grabada si la hay (``LiveEngine.play_clip``: sin gastar
  y con el micro callado mientras suena) y, si no, ``commentary`` con el texto exacto.
- ``send`` pone el ``seq``, guarda el último estado como mensaje fijo y manda ``start``
  el primero; ``play_animation`` va siempre con ``whole=True``.
- Las tareas de :meth:`ManagedGameHost.spawn` se cancelan al terminar la partida.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Coroutine
from typing import TYPE_CHECKING, Any, TypeVar

from sonia.games.base import GameResult
from sonia.vision.contracts import (
    CameraStream,
    HandDetector,
    PoseDetector,
    PreviewStreamer,
    VisionJudge,
)

if TYPE_CHECKING:
    from sonia.config import Settings
    from sonia.games.banks import GameBank
    from sonia.games.manager import GameManager
    from sonia.trivia.bank import TriviaQuestion

__all__ = ["ManagedGameHost"]

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ManagedGameHost:
    """El :class:`~sonia.games.base.GameHost` de un juego, sobre el manager y el motor."""

    def __init__(self, manager: GameManager, game_id: str) -> None:
        self._manager = manager
        self._game_id = game_id
        self._tasks: set[asyncio.Task[Any]] = set()

    @property
    def game_id(self) -> str:
        return self._game_id

    # -- ajustes, azar y reloj ------------------------------------------------

    @property
    def settings(self) -> Settings:
        return self._manager.settings

    @property
    def rng(self) -> random.Random:
        return self._manager.rng

    def now(self) -> float:
        return self._manager.now()

    async def sleep(self, seconds: float) -> None:
        await self._manager.sleep(seconds)

    # -- GPT-Live -------------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._manager.engine.connected

    async def speak(self, prompt: str) -> bool:
        return await self._manager.speak(self._game_id, prompt)

    async def instruct(self, text: str) -> bool:
        return await self._manager.instruct(self._game_id, text)

    async def say_fixed(self, text: str) -> bool:
        return await self._manager.say_fixed(self._game_id, text)

    async def wait_idle(self, limit_s: float | None = None) -> bool:
        return await self._manager.engine.wait_idle(limit_s)

    def quiet_for(self) -> float:
        return self._manager.engine.quiet_for()

    def touch(self) -> None:
        if self._manager.is_active(self._game_id):
            self._manager.touch()

    # -- pantalla de Unity ----------------------------------------------------

    async def send(
        self, event: str, data: dict[str, Any] | None = None, *, sticky: bool = True
    ) -> None:
        await self._manager.send(self._game_id, event, data, sticky=sticky)

    async def play_animation(self, clip: str) -> None:
        await self._manager.play_animation(self._game_id, clip)

    async def finish(self, result: GameResult, data: dict[str, Any] | None = None) -> None:
        await self._manager.finish(self._game_id, result, data)

    # -- cámara y visión --------------------------------------------------------

    @property
    def stream(self) -> CameraStream:
        return self._manager.vision.stream

    @property
    def preview(self) -> PreviewStreamer:
        return self._manager.vision.preview

    @property
    def poses(self) -> PoseDetector:
        return self._manager.vision.poses

    @property
    def hands(self) -> HandDetector:
        return self._manager.vision.hands

    @property
    def judge(self) -> VisionJudge:
        return self._manager.vision.judge

    # -- tareas y bancos ------------------------------------------------------

    def spawn(self, coro: Coroutine[Any, Any, Any], name: str) -> None:
        if not self._manager.is_active(self._game_id):
            coro.close()
            logger.debug("Tarea %s de %s sin partida en marcha: no se lanza", name, self._game_id)
            return
        task = asyncio.create_task(coro, name=f"sonia-game-{self._game_id}-{name}")
        self._tasks.add(task)
        task.add_done_callback(self._task_done)

    def _task_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("La tarea %s falló: %r", task.get_name(), task.exception())

    def cancel_tasks(self) -> None:
        """Cancela las tareas del juego (lo llama el manager al terminar la partida)."""
        current = asyncio.current_task()
        for task in list(self._tasks):
            if task is not current and not task.done():
                task.cancel()

    async def load_bank(self, bank: GameBank[T]) -> list[T]:
        return await self._manager.load_bank(self._game_id, bank)

    def read_bank(self, bank: GameBank[T]) -> list[T]:
        return self._manager.read_bank(self._game_id, bank)

    def draw_trivia(self, level: str | None = None) -> TriviaQuestion | None:
        return self._manager.draw_trivia(level)
