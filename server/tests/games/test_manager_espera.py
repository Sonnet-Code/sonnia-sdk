"""El aviso de espera de los juegos (``sonia.busy``) en el ``GameManager``: «Preparando el
juego…» hasta la primera pantalla y «Encendiendo la cámara…» hasta el primer frame."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Callable
from typing import Any, ClassVar

import numpy as np

from sonia.busy import TEXT_CAMERA, TEXT_GAME, TEXT_POSES, BusyBoard
from sonia.games import Game, GameError, StopReason
from sonia.games.manager import CAMERA_BUSY_MAX_S, GameManager
from sonia.ws import protocol as p
from tests.games.fakes import (
    FakeClock,
    FakeEngine,
    FakeScreen,
    FakeStream,
    FakeVision,
    FakeVoiceCache,
    game_settings,
)


class SlowStream(FakeStream):
    """Una cámara que tarda en dar su primer frame (``ready``)."""

    def __init__(self) -> None:
        super().__init__()
        self.ready = False

    def latest(self) -> tuple[float, np.ndarray] | None:
        return super().latest() if self.ready else None


class SlowGame(Game):
    """Un juego que tarda en prepararse: su ``start`` espera a ``gate``."""

    id: ClassVar[str] = "lento"
    title: ClassVar[str] = "Lento"
    spoken: ClassVar[str] = "el lento"
    settings_key: ClassVar[str] = "wordle"

    def __init__(self, host: Any) -> None:
        super().__init__(host)
        self.gate = asyncio.Event()
        self.fail: Exception | None = None

    async def start(self, source: str, options: dict[str, Any]) -> str:
        await self.gate.wait()
        if self.fail is not None:
            raise self.fail
        return "Arranca."


class SlowCameraGame(SlowGame):
    """Un juego de cámara: la pide al empezar y la suelta al terminar."""

    id: ClassVar[str] = "lento_camara"
    title: ClassVar[str] = "Lento con cámara"
    spoken: ClassVar[str] = "el lento con cámara"
    settings_key: ClassVar[str] = "poses"
    needs: ClassVar[frozenset[str]] = frozenset({"camera"})

    async def start(self, source: str, options: dict[str, Any]) -> str:
        if not await self.host.stream.acquire(self.id):
            raise GameError("No hay cámara.")
        return await super().start(source, options)

    async def stop(self, reason: StopReason) -> None:
        await self.host.stream.release(self.id)


class Rig:
    def __init__(self, stream: FakeStream | None = None) -> None:
        self.engine, self.screen, self.clock = FakeEngine(), FakeScreen(), FakeClock()
        self.board = BusyBoard(self.screen.broadcast_json)
        self.stream = stream or SlowStream()
        self.manager = GameManager(
            game_settings(result_seconds=0.0, final_wait_seconds=0.0),
            engine=self.engine,
            screen=self.screen,
            vision=FakeVision(stream=self.stream).game_vision(),
            voice_cache=FakeVoiceCache(),
            games=[SlowGame, SlowCameraGame],
            camera_ready=lambda: True,
            busy_board=self.board,
            rng=random.Random(1),
            clock=self.clock,
            # Sin avanzar el reloj falso: el tope de la cámara lo adelanta el test.
            sleep=lambda _s: asyncio.sleep(0.001),
        )

    async def hello(self) -> None:
        await self.manager.on_client_hello(
            {"type": p.MSG_CLIENT_HELLO, "games": [SlowGame.id, SlowCameraGame.id]}
        )

    def game(self, cls: type[SlowGame]) -> SlowGame:
        game = self.manager.game(cls.id)
        assert isinstance(game, SlowGame)
        return game

    def busy(self) -> list[str]:
        """Los ``busy`` mandados a Unity: el texto de cada ``on`` o ``off``."""
        return [
            m["text"] if m["on"] else "off" for m in self.screen.sent if m.get("type") == p.MSG_BUSY
        ]

    def kinds(self) -> list[str]:
        """``busy:<texto>`` y ``game:<evento>`` en el orden en que salieron."""
        out = []
        for m in self.screen.sent:
            if m.get("type") == p.MSG_BUSY:
                out.append(f"busy:{m['text'] if m['on'] else 'off'}")
            elif m.get("type") == p.MSG_GAME:
                out.append(f"game:{m['event']}")
        return out


async def until(predicate: Callable[[], bool], limit: float = 2.0) -> None:
    async with asyncio.timeout(limit):
        while not predicate():  # noqa: ASYNC110 - sondeo de un predicado
            await asyncio.sleep(0.002)


async def test_preparando_el_juego_hasta_la_primera_pantalla() -> None:
    rig = Rig()
    await rig.hello()
    task = asyncio.create_task(rig.manager.start(SlowGame.id, "voice"))
    await until(lambda: rig.busy() == [TEXT_GAME])
    assert rig.board.current() == ("game", TEXT_GAME)
    assert not rig.screen.game_msgs()
    rig.game(SlowGame).gate.set()
    ok, _ = await task
    assert ok
    # Se va con la primera pantalla del juego, justo después de su ``start``.
    assert rig.kinds() == [f"busy:{TEXT_GAME}", "game:start", "busy:off"]
    assert rig.board.current() is None


async def test_preparando_el_juego_se_va_si_no_arranca() -> None:
    rig = Rig()
    await rig.hello()
    game = rig.game(SlowGame)
    game.fail = GameError("Hoy no.")
    game.gate.set()
    ok, text = await rig.manager.start(SlowGame.id, "voice")
    assert not ok and text == "Hoy no."
    assert rig.busy() == [TEXT_GAME, "off"]
    assert rig.board.keys == ()


async def test_encendiendo_la_camara_hasta_el_primer_frame() -> None:
    rig = Rig()
    await rig.hello()
    task = asyncio.create_task(rig.manager.start(SlowCameraGame.id, "voice"))
    # La cámara tiene más prioridad que «Preparando el juego…».
    await until(lambda: rig.busy() == [TEXT_GAME, TEXT_CAMERA])
    rig.game(SlowCameraGame).gate.set()
    ok, _ = await task
    assert ok
    # Ya está la primera pantalla, pero la cámara aún no da imagen.
    await asyncio.sleep(0.02)
    assert rig.board.current() == ("camera", TEXT_CAMERA)
    assert rig.board.keys == (f"game:{SlowCameraGame.id}:camera",)
    rig.stream.ready = True  # type: ignore[attr-defined]
    await until(lambda: rig.busy()[-1:] == ["off"])
    assert rig.busy() == [TEXT_GAME, TEXT_CAMERA, "off"]
    assert rig.board.keys == ()
    # La partida sigue: la vigía de la cámara ya terminó.
    assert rig.manager.is_playing(SlowCameraGame.id)


async def test_encendiendo_la_camara_tiene_tope() -> None:
    rig = Rig()
    await rig.hello()
    rig.game(SlowCameraGame).gate.set()
    ok, _ = await rig.manager.start(SlowCameraGame.id, "voice")
    assert ok
    await until(lambda: rig.board.current() == ("camera", TEXT_CAMERA))
    rig.clock.advance(CAMERA_BUSY_MAX_S + 0.1)
    await until(lambda: rig.board.current() is None)
    assert rig.busy()[-1] == "off"


async def test_sin_espera_de_camara_si_ya_da_imagen() -> None:
    rig = Rig(stream=FakeStream())
    await rig.hello()
    rig.game(SlowCameraGame).gate.set()
    ok, _ = await rig.manager.start(SlowCameraGame.id, "voice")
    assert ok
    await asyncio.sleep(0.02)
    assert rig.busy() == [TEXT_GAME, "off"]


async def test_al_terminar_la_partida_no_queda_nada() -> None:
    rig = Rig()
    await rig.hello()
    task = asyncio.create_task(rig.manager.start(SlowCameraGame.id, "voice"))
    await until(lambda: rig.board.current() == ("camera", TEXT_CAMERA))
    rig.game(SlowCameraGame).gate.set()
    assert (await task)[0]
    # Un juez del juego mirando una foto (``GameHost.set_busy``), con la cámara aún sin imagen.
    await rig.manager.set_busy(SlowCameraGame.id, "judge", TEXT_POSES)
    assert rig.board.current() == ("judge", TEXT_POSES)
    ok, _ = await rig.manager.stop("panel")
    assert ok
    assert rig.board.keys == ()
    assert rig.busy()[-1] == "off"
    # La vigía de la cámara se canceló con la partida: no vuelve a encender nada.
    count = len(rig.busy())
    await asyncio.sleep(0.05)
    assert len(rig.busy()) == count
    # Un juego que ya no está en pantalla no enciende avisos.
    await rig.manager.set_busy(SlowCameraGame.id, "judge", TEXT_POSES)
    assert rig.board.keys == ()


async def test_al_perder_la_sesion_mientras_se_prepara() -> None:
    rig = Rig()
    await rig.hello()
    task = asyncio.create_task(rig.manager.start(SlowCameraGame.id, "voice"))
    await until(lambda: rig.board.current() == ("camera", TEXT_CAMERA))
    await rig.manager.on_session_lost()
    assert rig.board.keys == ()
    rig.game(SlowCameraGame).gate.set()
    ok, _ = await task
    assert not ok
    await asyncio.sleep(0.02)
    assert rig.board.keys == ()
    assert rig.busy()[-1] == "off"
