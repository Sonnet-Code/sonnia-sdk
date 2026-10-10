"""El control a mano desde el panel de los juegos de cámara (``Game.panel_control``), sin red.

Simón dice («Lo hicieron», «No lo hicieron», «Siguiente orden»), piedra, papel o tijera
(«Piedra», «Papel», «Tijera», «Otra ronda») y la búsqueda («¡Lo encontró!», «Saltar
objeto»): qué controles hay en cada fase, que mueven el juego y que fuera de turno dan
``GameError`` con un mensaje para el equipo.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import numpy as np
import pytest

from sonia.games import GameError
from sonia.games.poses import game as poses_game
from sonia.games.ppt.game import PptGame
from sonia.vision.contracts import HandShape, PoseFrame, PoseVerdict
from tests.games.fakes import (
    FakeGameHost,
    FakePoses,
    FakeReferee,
    FakeStream,
    FakeVision,
    pose_frame,
)
from tests.games.test_busqueda import MISS, go, new_game, phase, pump, sent
from tests.games.test_poses import Crowd, crowd_game
from tests.games.test_poses import sent as poses_sent
from tests.games.test_ppt import BEATS_IT, PlayerHands, loses, nothing
from tests.games.test_ppt_juez import make_judged


def ids(controls: list[dict[str, Any]]) -> list[str]:
    return [c["id"] for c in controls]


async def run_all(tasks: list[asyncio.Task[Any]]) -> None:
    """Como ``FakeGameHost.run_tasks``, sin que un control que falla corte la espera."""
    while any(not t.done() for t in tasks):
        await asyncio.gather(*tasks, return_exceptions=True)


# ---------------------------------------------------------------------------
# Búsqueda relámpago
# ---------------------------------------------------------------------------


async def test_busqueda_lo_encontro_desde_el_panel() -> None:
    game, host, _ = new_game(*[MISS] * 12)
    assert game.panel_controls() == []
    with pytest.raises(GameError):
        await game.panel_control("found", "")
    await game.start("voice", {})
    # Mientras Sonia anuncia el objeto aún no hay ronda en marcha.
    assert game.panel_controls() == []
    with pytest.raises(GameError):
        await game.panel_control("found", "")
    await go(game, host)
    assert ids(game.panel_controls()) == ["found", "skip"]
    script = await game.panel_control("found", "")
    assert "lo han encontrado" in script
    assert sent(host, "found") and phase(game) == "between"
    assert game.snapshot()["found"] == 1
    # La ronda ya está contada: fuera de turno.
    assert game.panel_controls() == []
    with pytest.raises(GameError):
        await game.panel_control("skip", "")


async def test_busqueda_saltar_objeto_no_cuenta_como_camara_muda() -> None:
    game, host, judge = new_game(*[None] * 12)
    await game.start("voice", {})
    await go(game, host)
    await pump(game, host, 2.6)  # una mirada sin respuesta
    assert len(judge.questions) == 1
    script = await game.panel_control("skip", "")
    assert "se salta" in script
    assert sent(host, "timeout") and phase(game) == "between"
    snap = game.snapshot()
    assert snap["found"] == 0 and snap["results"] == ["timeout"]
    with pytest.raises(GameError):
        await game.panel_control("nada", "")


# ---------------------------------------------------------------------------
# Simón dice
# ---------------------------------------------------------------------------


class PanelCrowd(Crowd):
    """La gente de ``test_poses`` y alguien del equipo que pulsa ``control`` en el panel la
    primera vez que ve la fase ``phase`` en las rondas ``rounds`` (0: la colocación)."""

    def __init__(self, control: str, phase: str, rounds: set[int], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.control = control
        self.phase = phase
        self.rounds = rounds
        self.pressed: set[int] = set()
        self.presses: list[asyncio.Task[str]] = []

    def latest(self, max_age_s: float = 0.5) -> PoseFrame | None:
        snap: dict[str, Any] = self.game.snapshot() if self.game is not None else {}
        number = int(snap.get("round") or 0)
        if snap.get("phase") == self.phase and number in self.rounds and number not in self.pressed:
            self.pressed.add(number)
            assert self.game is not None
            press = self.game.panel_control(self.control, "")
            self.presses.append(asyncio.ensure_future(press))
        return super().latest(max_age_s)


async def play_poses(crowd: PanelCrowd, **kwargs: Any) -> tuple[Any, Any]:
    game, host, _ = crowd_game(crowd, **kwargs)
    await game.start("voice", {})
    await run_all(host.tasks)
    await run_all(crowd.presses)
    return game, host


async def test_poses_controles_por_fase_y_fuera_de_turno() -> None:
    game, host, _ = crowd_game(Crowd())
    assert game.panel_controls() == []
    with pytest.raises(GameError):
        await game.panel_control("did", "")
    await game.start("voice", {})
    assert ids(game.panel_controls()) == ["next"]
    with pytest.raises(GameError):
        await game.panel_control("did", "")  # en la colocación no hay ronda que contar
    with pytest.raises(GameError):
        await game.panel_control("baila", "")
    for phase_name in ("round", "command", "window", "result"):
        game._phase = phase_name
        assert ids(game.panel_controls()) == ["did", "didnt", "next"]
    game._phase = "final"
    assert game.panel_controls() == []
    with pytest.raises(GameError):
        await game.panel_control("next", "")
    host.tasks[0].cancel()


async def test_poses_no_lo_hicieron_manda_sobre_el_juez_y_lo_local() -> None:
    referee = FakeReferee(poses=[PoseVerdict(5, {"brazos_arriba": 5})] * 6)
    crowd = PanelCrowd("didnt", "window", set(range(1, 7)), players=5, doers=3, fallers=1)
    stream = FakeStream()
    stream.owners.add("poses:poses")
    vision = FakeVision(poses=crowd, stream=stream, referee=referee)
    game, host = await play_poses(crowd, vision=vision)
    assert [p.result() for p in crowd.presses] == [""] * 6
    assert {(r["count"], r["total"]) for r in poses_sent(host, "result")} == {(0, 5)}
    # Con el veredicto ya puesto, el juez ni mira.
    assert referee.photos == []
    final = poses_sent(host, "final")[-1]
    assert (final["done"], final["fell"]) == (5 * 0 + 5, 0)


async def test_poses_lo_hicieron_con_el_resultado_en_pantalla_lo_corrige() -> None:
    crowd = PanelCrowd("did", "result", {1}, players=5, doers=3, fallers=1)
    game, host = await play_poses(crowd)
    script = crowd.presses[0].result()
    assert script.startswith("Corrige el resultado de la ronda 1:") and "5 de 5" in script
    first = [r for r in poses_sent(host, "result") if r["round"] == 1]
    assert [(r["count"], r["total"]) for r in first] == [(3, 5), (5, 5)]
    final = poses_sent(host, "final")[-1]
    # La ronda 1 cuenta como corregida: 5 + 3 * 4 con «Simón dice» y 4 quietos en la trampa.
    assert (final["done"], final["possible"]) == (5 + 3 * 4 + 4, 30)


async def test_poses_siguiente_orden_salta_la_ronda_sin_contarla() -> None:
    crowd = PanelCrowd("next", "window", {2}, players=5, doers=3, fallers=1)
    game, host = await play_poses(crowd)
    assert crowd.presses[0].result() == ""
    rounds = [r["round"] for r in poses_sent(host, "result")]
    assert 2 not in rounds and len(rounds) == 5
    assert host.finished and host.finished[0][0] == "win"
    assert poses_sent(host, "final")[-1]["possible"] == 25


async def test_poses_siguiente_orden_en_la_colocacion_empieza_ya() -> None:
    crowd = PanelCrowd("next", "placement", {0}, players=0)
    game, host = await play_poses(crowd)
    # Sin el control, sin nadie delante, Sonia pedía que se pusieran delante.
    assert poses_game.NOBODY_TEXT not in host.spoken
    assert poses_sent(host, "command")


# ---------------------------------------------------------------------------
# Piedra, papel o tijera
# ---------------------------------------------------------------------------


async def test_ppt_controles_por_fase_y_fuera_de_turno() -> None:
    game, host, _ = make_judged(nothing, FakeReferee(available=False))
    assert game.panel_controls() == []
    for phase_name in ("ready", "countdown", "reading"):
        game._phase = phase_name  # type: ignore[assignment]
        controls = game.panel_controls()
        assert ids(controls) == ["piedra", "papel", "tijera"]
        assert [c["label"] for c in controls] == ["Piedra", "Papel", "Tijera"]
        with pytest.raises(GameError):
            await game.panel_control("again", "")
    for phase_name in ("intro", "waiting", "result"):
        game._phase = phase_name  # type: ignore[assignment]
        assert ids(game.panel_controls()) == ["again"]
        with pytest.raises(GameError):
            await game.panel_control("papel", "")
    game._phase = "final"
    assert game.panel_controls() == []
    with pytest.raises(GameError):
        await game.panel_control("tijera", "")
    with pytest.raises(GameError):
        await game.panel_control("lagarto", "")


class PressingStream(FakeStream):
    """La cámara, y alguien del equipo que pulsa en el panel al leer cada tirada."""

    def __init__(self, choose: Callable[[PptGame], str]) -> None:
        super().__init__()
        self.choose = choose
        self.game: PptGame | None = None
        self.pressed_throws: set[int] = set()
        self.presses: list[asyncio.Task[str]] = []

    def latest(self) -> tuple[float, np.ndarray] | None:
        game = self.game
        if game is not None and game.phase == "reading" and game.throws not in self.pressed_throws:
            self.pressed_throws.add(game.throws)
            self.presses.append(asyncio.ensure_future(game.panel_control(self.choose(game), "")))
        return super().latest()


async def test_ppt_la_jugada_a_mano_manda_sobre_la_lectura_y_el_juez() -> None:
    def winning(game: PptGame) -> str:
        assert game.move is not None
        return BEATS_IT[game.move].value

    stream = PressingStream(winning)
    referee = FakeReferee(hands=[], available=True)
    game, host, _ = make_judged(loses, referee, stream=stream)
    stream.game = game
    await game.start("voice", {})
    await run_all(host.tasks)
    assert [p.result() for p in stream.presses] == ["", ""]
    # Lo local leía la jugada que pierde; manda la del panel, y el juez no llega a mirar.
    assert host.finished == [("win", {"winner": "player", "score": {"sonnia": 0, "player": 2}})]
    assert referee.photos == []


async def test_ppt_otra_ronda_lanza_la_tirada_sin_nadie_delante() -> None:
    vision = FakeVision(poses=FakePoses([pose_frame()]), hands=PlayerHands(nothing))
    host = FakeGameHost(PptGame.id, vision=vision)
    game = PptGame(host)
    await game.start("voice", {})
    assert ids(game.panel_controls()) == ["again"]
    assert await game.panel_control("again", "") == ""
    await run_all(host.tasks)
    # Sin el control y sin nadie delante no había cuenta: a los 30 s se cancelaba sin jugar.
    countdowns = host.events("countdown")
    assert countdowns and countdowns[0]["round"] == 1


async def test_ppt_sin_nadie_detectado_la_partida_va_a_mano() -> None:
    """La cámara no ve a nadie: «Otra ronda» y la jugada del panel llevan la tirada."""
    stream = PressingStream(lambda game: HandShape.ROCK.value)
    vision = FakeVision(stream=stream, poses=FakePoses([pose_frame()]), hands=PlayerHands(nothing))
    host = FakeGameHost(PptGame.id, vision=vision)
    game = PptGame(host)
    stream.game = game
    await game.start("voice", {})
    await game.panel_control("again", "")
    await run_all(host.tasks)
    results = host.events("result")
    assert results and results[0]["player"] == "piedra" and results[0]["reason"] == ""
