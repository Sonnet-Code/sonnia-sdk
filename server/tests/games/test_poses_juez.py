"""Simón dice con el juez de rondas (``GAMES_JUDGE=gemini``), sin cámara ni red.

El juez es un :class:`FakeReferee` con veredictos guionizados; la gente, la :class:`Crowd` de
``test_poses.py``. Se prueba que el veredicto manda, que sin él decide lo local, que la
pastilla de espera se enciende y se apaga, qué foto se le pasa y que sin juez no hay foto.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from sonia.busy import TEXT_POSES
from sonia.games.poses import game as poses_game
from sonia.games.poses.rules import POSE_IDS
from sonia.vision.contracts import PoseFrame, PoseVerdict
from tests.games.fakes import FakeReferee, FakeStream, FakeVision
from tests.games.test_poses import Crowd, crowd_game, sent

ROUNDS = 6


def judged_game(
    crowd: Crowd, referee: FakeReferee, stream: FakeStream | None = None
) -> tuple[Any, Any, Crowd]:
    """La partida con el juez; la cámara ya leyendo (la abre el detector de poses)."""
    stream = stream or FakeStream()
    stream.owners.add("poses:poses")
    vision = FakeVision(poses=crowd, stream=stream, referee=referee)
    return crowd_game(crowd, vision=vision)


def everyone(count: int, people: int) -> PoseVerdict:
    """El veredicto de una ronda, sea cual sea la pose: ``count`` de ``people``."""
    return PoseVerdict(people, {pose: count for pose in POSE_IDS})


async def test_el_veredicto_del_juez_manda_en_cada_ronda_y_en_las_trampas() -> None:
    referee = FakeReferee(poses=[everyone(4, 6)] * ROUNDS)
    game, host, _ = judged_game(Crowd(players=5, doers=3, fallers=1), referee)
    await game.start("voice", {})
    await host.run_tasks()
    results = sent(host, "result")
    assert len(results) == ROUNDS
    # Lo local veía 3 de 5 (1 en la trampa): cuántos la hacen lo dice el juez, también en la
    # trampa; cuántos juegan, lo local (el juez cuenta también a quien pasa por el fondo).
    assert {(r["count"], r["total"]) for r in results} == {(4, 5)}
    assert any(not r["simon"] for r in results)
    assert any("TRAMPA" in s and "cayeron 4 de 5" in s for s in host.spoken)
    assert sum(1 for s in host.spoken if "4 de 5" in s) == ROUNDS
    final = sent(host, "final")[-1]
    assert (final["done"], final["possible"], final["fell"]) == (5 * 4 + 1, 30, 4)
    # Una foto por ronda, la de la cámara, entera (la reduce el juez).
    assert referee.photos == [("poses", (360, 640, 3))] * ROUNDS
    # La pastilla, encendida mientras mira y apagada después, en cada ronda.
    assert host.busy == [("judge", TEXT_POSES), ("judge", None)] * ROUNDS
    assert host.busy_now == {}


async def test_sin_respuesta_del_juez_decide_lo_local() -> None:
    referee = FakeReferee(poses=[None] * ROUNDS)
    game, host, _ = judged_game(Crowd(players=5, doers=3, fallers=1), referee)
    await game.start("voice", {})
    await host.run_tasks()
    for result in sent(host, "result"):
        assert (result["count"], result["total"]) == ((3 if result["simon"] else 1), 5)
    assert len(referee.photos) == ROUNDS
    assert host.busy == [("judge", TEXT_POSES), ("judge", None)] * ROUNDS
    assert host.busy_now == {}


async def test_un_veredicto_sin_la_pose_deja_lo_local() -> None:
    referee = FakeReferee(poses=[PoseVerdict(6, {})] * ROUNDS)
    game, host, _ = judged_game(Crowd(players=5, doers=3, fallers=1), referee)
    await game.start("voice", {})
    await host.run_tasks()
    assert {(r["count"], r["total"]) for r in sent(host, "result") if r["simon"]} == {(3, 5)}


async def test_la_cuenta_del_juez_no_pasa_de_sus_personas() -> None:
    referee = FakeReferee(poses=[PoseVerdict(2, {pose: 3 for pose in POSE_IDS})] * ROUNDS)
    game, host, _ = judged_game(Crowd(players=5, doers=3, fallers=1), referee)
    await game.start("voice", {})
    await host.run_tasks()
    # El juez ve 2 personas: no puede decir que la hicieron 3. Juegan los 5 que ve lo local.
    assert {(r["count"], r["total"]) for r in sent(host, "result")} == {(2, 5)}


async def test_gente_de_fondo_no_infla_el_total() -> None:
    # Lo local ve a los 2 que juegan; el juez cuenta 40 personas (el pasillo) y 2 con la pose.
    referee = FakeReferee(poses=[everyone(2, 40)] * ROUNDS)
    game, host, _ = judged_game(Crowd(players=2, doers=1, fallers=0), referee)
    await game.start("voice", {})
    await host.run_tasks()
    assert {(r["count"], r["total"]) for r in sent(host, "result")} == {(2, 2)}


async def test_si_lo_local_no_ve_a_nadie_el_total_del_juez_va_con_tope() -> None:
    referee = FakeReferee(poses=[everyone(3, 40)] * ROUNDS)
    game, host, _ = judged_game(Crowd(players=0), referee)
    await game.start("voice", {})
    await host.run_tasks()
    results = sent(host, "result")
    assert results and {(r["count"], r["total"]) for r in results} == {
        (3, poses_game.MAX_JUDGED_PLAYERS)
    }


async def test_si_nadie_ve_a_nadie_las_rondas_vacias_acaban_el_juego() -> None:
    referee = FakeReferee(poses=[everyone(0, 0)] * ROUNDS)
    game, host, _ = judged_game(Crowd(players=0), referee)
    await game.start("voice", {})
    await host.run_tasks()
    assert len(sent(host, "result")) == poses_game.EMPTY_ROUNDS_TO_STOP
    assert host.spoken[-1] == poses_game.EMPTY_FINAL_TEXT
    assert host.finished == [("cancel", None)]
    assert host.busy_now == {}


async def test_sin_juez_ni_foto_ni_aviso() -> None:
    referee = FakeReferee(poses=[everyone(4, 6)] * ROUNDS, available=False)
    game, host, _ = judged_game(Crowd(players=5, doers=3, fallers=1), referee)
    await game.start("voice", {})
    await host.run_tasks()
    assert referee.photos == []
    assert host.busy == []
    assert {(r["count"], r["total"]) for r in sent(host, "result") if r["simon"]} == {(3, 5)}


async def test_un_juez_que_falla_deja_lo_local_y_apaga_el_aviso() -> None:
    class BrokenReferee(FakeReferee):
        async def poses(self, frame_bgr: np.ndarray) -> PoseVerdict | None:
            raise RuntimeError("roto")

    game, host, _ = judged_game(Crowd(players=5, doers=3, fallers=1), BrokenReferee())
    await game.start("voice", {})
    await host.run_tasks()
    assert len(sent(host, "result")) == ROUNDS
    assert {(r["count"], r["total"]) for r in sent(host, "result") if r["simon"]} == {(3, 5)}
    assert host.busy_now == {}
    assert host.finished and host.finished[0][0] == "win"


class PeakCrowd(Crowd):
    """En la ventana de cada ronda, cuántos hacen la pose va según ``plan`` (y luego ``rest``)."""

    def __init__(self, plan: list[int], rest: int) -> None:
        super().__init__(players=5, doers=0, fallers=0)
        self.plan = plan
        self.rest = rest
        self.window_polls = 0
        self._round = 0

    def latest(self, max_age_s: float = 0.5) -> PoseFrame | None:
        snap: dict[str, Any] = self.game.snapshot() if self.game is not None else {}
        if snap.get("round") != self._round:
            self._round = snap.get("round", 0)
            self.window_polls = 0
        if snap.get("phase") == "window":
            self.window_polls += 1
            n = self.window_polls
            self.doers = self.fallers = self.plan[n - 1] if n <= len(self.plan) else self.rest
        return super().latest(max_age_s)


class MarkedStream(FakeStream):
    """Cada frame lleva pintado en qué lectura de la ventana se cogió (y se apuntan todos)."""

    def __init__(self, crowd: PeakCrowd) -> None:
        super().__init__()
        self.crowd = crowd
        self.served: list[int] = []

    def latest(self) -> tuple[float, np.ndarray] | None:
        value = self.crowd.window_polls
        self.served.append(value)
        return 0.0, np.full((360, 640, 3), value % 256, dtype=np.uint8)


class FrameReferee(FakeReferee):
    """Apunta la marca de cada foto, la del último frame que dio la cámara y cuántas
    lecturas llevaba la ventana al llegarle la foto."""

    def __init__(self, stream: MarkedStream) -> None:
        super().__init__()
        self.stream = stream
        self.marks: list[tuple[int, int, int]] = []

    async def poses(self, frame_bgr: np.ndarray) -> PoseVerdict | None:
        mark = int(frame_bgr[0, 0, 0])
        self.marks.append((mark, self.stream.served[-1], self.stream.crowd.window_polls))
        return await super().poses(frame_bgr)


async def test_la_foto_es_la_del_mejor_recuento_local_y_la_mas_reciente() -> None:
    crowd = PeakCrowd(plan=[1, 3, 3], rest=2)
    stream = MarkedStream(crowd)
    referee = FrameReferee(stream)
    game, host, _ = judged_game(crowd, referee, stream)
    await game.start("voice", {})
    await host.run_tasks()
    assert len(referee.marks) == ROUNDS
    # El mejor recuento (3) fue en la 2.ª y la 3.ª lectura: va la 3.ª, aunque la ventana siguió.
    for mark, _, polls in referee.marks:
        assert mark == 3 and polls > 10


async def test_si_lo_local_no_ve_a_nadie_haciendola_va_el_ultimo_frame_de_la_ventana() -> None:
    crowd = PeakCrowd(plan=[], rest=0)
    stream = MarkedStream(crowd)
    referee = FrameReferee(stream)
    game, host, _ = judged_game(crowd, referee, stream)
    await game.start("voice", {})
    await host.run_tasks()
    assert len(referee.marks) == ROUNDS
    for mark, last_served, polls in referee.marks:
        assert mark == last_served > 10
        # La última lectura de la ventana (el juez lee una más al empezar a esperar).
        assert mark == polls - 1
