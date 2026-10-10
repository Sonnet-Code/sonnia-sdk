"""Piedra, papel o tijera con el juez de rondas (``GAMES_JUDGE=gemini``), sin red ni cámara.

La lectura local elige el momento y su frame va al juez (``FakeReferee``), que decide la
jugada: manda aunque lo local diga otra cosa; sin veredicto, decide lo local; sin juez, ni
foto ni aviso. Mientras el juez mira, el aviso de espera «Mirando tu mano…».
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

import numpy as np
import pytest

from sonia.busy import TEXT_HAND
from sonia.games.ppt import game as ppt_game
from sonia.games.ppt.game import RETRY_NO_HAND, RETRY_UNCLEAR, PptGame
from sonia.games.ppt.logic import Sample
from sonia.vision.contracts import HandReading, HandShape, HandVerdict
from tests.games.fakes import (
    FakeGameHost,
    FakePoses,
    FakeReferee,
    FakeStream,
    FakeVision,
    pose_frame,
)
from tests.games.test_ppt import (
    BEATS_IT,
    LOSES_TO,
    PlayerHands,
    body,
    by_throw,
    hand,
    nothing,
    wins,
)

PAPER = HandShape.PAPER
JUDGE_ON_OFF = [("judge", TEXT_HAND), ("judge", None)]


@pytest.fixture(autouse=True)
def _sin_frase_grabada(monkeypatch: pytest.MonkeyPatch) -> None:
    """La frase no está medida (como en ``test_ppt.py``): nunca la caché de voces del equipo."""
    monkeypatch.setattr(ppt_game, "phrase_go_seconds", lambda settings: None)


class PlanReferee(FakeReferee):
    """Un juez que contesta según la partida (``plan(juego)``) y guarda las fotos que ve."""

    def __init__(self, plan: Callable[[PptGame], HandVerdict | None]) -> None:
        super().__init__()
        self.plan = plan
        self.game: Callable[[], PptGame | None] = lambda: None
        self.frames: list[np.ndarray] = []

    async def hands(self, frame_bgr: np.ndarray) -> HandVerdict | None:
        await super().hands(frame_bgr)
        self.frames.append(frame_bgr)
        game = self.game()
        assert game is not None, "foto al juez sin partida"
        return self.plan(game)


class BrokenReferee(FakeReferee):
    async def hands(self, frame_bgr: np.ndarray) -> HandVerdict | None:
        await super().hands(frame_bgr)
        raise RuntimeError("el juez se cayó")


class CountingStream(FakeStream):
    """Cada ``latest`` da un frame nuevo, relleno con su número de orden (1, 2, 3...)."""

    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def latest(self) -> tuple[float, np.ndarray] | None:
        if not self.owners:
            return None
        self.count += 1
        return float(self.count), np.full((360, 640, 3), self.count, dtype=np.uint8)


def make_judged(
    plan: Callable[[PptGame], list[HandReading]],
    referee: FakeReferee,
    *,
    stream: FakeStream | None = None,
    **kwargs: Any,
) -> tuple[PptGame, FakeGameHost, PlayerHands]:
    hands = PlayerHands(plan)
    vision = FakeVision(
        stream=stream,
        poses=FakePoses([pose_frame(body())]),
        hands=hands,
        referee=referee,
    )
    host = FakeGameHost(PptGame.id, vision=vision, **kwargs)
    game = PptGame(host)
    hands.game = lambda: game
    if isinstance(referee, PlanReferee):
        referee.game = lambda: game
    return game, host, hands


async def play(game: PptGame, host: FakeGameHost) -> None:
    await game.start("voice", {})
    await host.run_tasks()


def loses_verdict(game: PptGame) -> HandVerdict:
    """El juez ve la jugada que pierde contra la de Sonia."""
    assert game.move is not None
    return HandVerdict((LOSES_TO[game.move],))


def verdicts(*items: HandVerdict | None) -> Iterable[HandVerdict | None]:
    return items


async def test_el_juez_manda_sobre_la_lectura_local() -> None:
    # Lo local ve la jugada que gana; el juez, la que pierde: gana Sonia.
    referee = PlanReferee(loses_verdict)
    game, host, _ = make_judged(wins, referee, seed=5)
    await play(game, host)
    assert host.finished == [("lose", {"winner": "sonnia", "score": {"sonnia": 2, "player": 0}})]
    results = host.events("result")
    assert [r["winner"] for r in results] == ["sonnia", "sonnia"]
    for result in results:
        assert result["player"] == LOSES_TO[HandShape(result["sonnia"])].value
    assert "ganas tú" in host.spoken[0]
    # Una foto por tirada, la de la cámara, y el aviso encendido y apagado en cada una.
    assert referee.photos == [("hands", (360, 640, 3))] * 2
    assert host.busy == JUDGE_ON_OFF * 2
    assert host.busy_now == {}


async def test_el_juez_que_no_ve_jugada_y_lo_local_tampoco_es_no_hand() -> None:
    referee = FakeReferee(hands=verdicts(HandVerdict(())))
    game, host, _ = make_judged(by_throw(nothing, wins, wins), referee)
    await play(game, host)
    first = host.events("result")[0]
    assert (first["winner"], first["reason"], first["retry"]) == ("none", "no_hand", True)
    assert host.spoken[0] == RETRY_NO_HAND
    # Las siguientes, sin veredicto (la cola se acabó): decide lo local.
    assert host.finished == [("win", {"winner": "player", "score": {"sonnia": 0, "player": 2}})]
    assert len(referee.photos) == 3
    assert host.busy == JUDGE_ON_OFF * 3


async def test_el_juez_que_no_ve_jugada_manda_aunque_lo_local_viera_una() -> None:
    referee = FakeReferee(hands=verdicts(HandVerdict(())))
    game, host, _ = make_judged(wins, referee)
    await play(game, host)
    first = host.events("result")[0]
    # Lo local vio una mano (la que gana), así que es que no se entendió.
    assert (first["winner"], first["reason"], first["retry"]) == ("none", "unclear", True)
    assert first["player"] is None
    assert host.spoken[0] == RETRY_UNCLEAR
    assert host.finished[0][0] == "win"


async def test_sin_veredicto_decide_la_lectura_local() -> None:
    referee = FakeReferee()  # disponible, pero nunca contesta a tiempo
    game, host, _ = make_judged(wins, referee)
    await play(game, host)
    assert host.finished == [("win", {"winner": "player", "score": {"sonnia": 0, "player": 2}})]
    assert referee.photos == [("hands", (360, 640, 3))] * 2
    assert host.busy == JUDGE_ON_OFF * 2
    assert host.busy_now == {}


async def test_si_el_juez_falla_decide_la_lectura_local_y_se_apaga_el_aviso() -> None:
    referee = BrokenReferee()
    game, host, _ = make_judged(wins, referee)
    await play(game, host)
    assert host.finished[0][0] == "win"
    assert len(referee.photos) == 2
    assert host.busy == JUDGE_ON_OFF * 2
    assert host.busy_now == {}


async def test_sin_juez_ni_foto_ni_aviso() -> None:
    referee = FakeReferee(hands=verdicts(HandVerdict((PAPER,))), available=False)
    game, host, _ = make_judged(wins, referee)
    await play(game, host)
    assert host.finished == [("win", {"winner": "player", "score": {"sonnia": 0, "player": 2}})]
    assert referee.photos == []
    assert host.busy == []


async def test_al_juez_va_el_frame_de_la_lectura_estable() -> None:
    """Papel en las tres primeras lecturas y luego nada: va el frame de la tercera."""

    def paper_then_nothing(game: PptGame) -> list[HandReading]:
        return [hand(PAPER)] if hands.reads <= 3 else []

    referee = PlanReferee(lambda game: None)
    stream = CountingStream()
    game, host, hands = make_judged(paper_then_nothing, referee, stream=stream)
    assert await host.stream.acquire(PptGame.id)
    sample, reason = await game._read(host.now())
    assert (sample.shape, reason) == (PAPER, "")
    assert stream.count > 3
    assert [int(frame[0, 0, 0]) for frame in referee.frames] == [3]


class TimedStream(CountingStream):
    """Como ``CountingStream`` y apunta cuándo dio cada frame (con el reloj del juego)."""

    def __init__(self) -> None:
        super().__init__()
        self.clock: Callable[[], float] = lambda: 0.0
        self.times: list[float] = []

    def latest(self) -> tuple[float, np.ndarray] | None:
        self.times.append(self.clock())
        return super().latest()


async def read_with_soft_end(game: PptGame, host: FakeGameHost, stream: TimedStream) -> Any:
    """``_read`` con el «¡ya!» ahora; devuelve lo leído y el número del frame de ``soft_end``."""
    stream.clock = host.now
    ya_at = host.now()
    soft_end = ya_at + ppt_game.REACTION_S + max(0.2, float(host.settings.games.ppt.read_seconds))
    result = await game._read(ya_at)
    soft = next(index + 1 for index, at in enumerate(stream.times) if at >= soft_end)
    return result, soft


async def test_sin_jugada_estable_va_el_frame_de_soft_end() -> None:
    referee = PlanReferee(lambda game: HandVerdict((PAPER,)))
    stream = TimedStream()
    game, host, _ = make_judged(nothing, referee, stream=stream)
    assert await host.stream.acquire(PptGame.id)
    (sample, reason), soft = await read_with_soft_end(game, host, stream)
    # El juez ve papel aunque lo local no viera ninguna mano.
    assert (sample.shape, reason) == (PAPER, "")
    # El frame leído al llegar a soft_end, no el último del alargue.
    assert [int(frame[0, 0, 0]) for frame in referee.frames] == [soft]
    assert stream.count > soft


async def test_sin_persona_ni_mano_el_juez_ve_el_frame_igual() -> None:
    """Lo local no ve a nadie (anoche, tijera_1 y tijera_2): la foto va al juez igual."""
    referee = PlanReferee(lambda game: HandVerdict((HandShape.SCISSORS,)))
    stream = TimedStream()
    hands = PlayerHands(nothing)
    vision = FakeVision(
        stream=stream, poses=FakePoses([pose_frame()]), hands=hands, referee=referee
    )
    host = FakeGameHost(PptGame.id, vision=vision)
    game = PptGame(host)
    hands.game = lambda: game
    referee.game = lambda: game
    assert await host.stream.acquire(PptGame.id)
    (sample, reason), soft = await read_with_soft_end(game, host, stream)
    assert (sample.shape, reason) == (HandShape.SCISSORS, "")
    assert [int(frame[0, 0, 0]) for frame in referee.frames] == [soft]
    assert host.busy == JUDGE_ON_OFF


async def test_sin_ningun_frame_de_la_camara_no_se_pregunta() -> None:
    referee = PlanReferee(lambda game: HandVerdict((PAPER,)))
    game, host, _ = make_judged(nothing, referee)
    # La cámara sin dueño no da frames (``stream.latest()`` es None).
    sample, reason = await game._read(host.now())
    assert (sample.shape, reason) == (None, "no_hand")
    assert referee.photos == [] and host.busy == []


async def test_la_caja_de_la_mano_sigue_siendo_la_local() -> None:
    referee = FakeReferee(hands=verdicts(HandVerdict((PAPER,)), HandVerdict(())))
    game, _, _ = make_judged(wins, referee)
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    box = (0.45, 0.35, 0.1, 0.1)
    local = Sample(None, True, box)
    judged, reason = await game._judged(local, "unclear", [local], frame)
    assert (judged, reason) == (Sample(PAPER, True, box), "")
    # Sin jugada del juez y con una mano vista en local: no se entendió, con su caja.
    judged, reason = await game._judged(Sample(PAPER, True, box), "", [local], frame)
    assert (judged, reason) == (Sample(None, True, box), "unclear")


async def test_el_juez_que_ve_la_que_gana_da_la_tirada_al_jugador() -> None:
    def beats(game: PptGame) -> HandVerdict:
        assert game.move is not None
        return HandVerdict((BEATS_IT[game.move], LOSES_TO[game.move]))

    # Lo local no ve nada; el juez ve dos manos y manda la primera.
    referee = PlanReferee(beats)
    game, host, _ = make_judged(nothing, referee)
    await play(game, host)
    assert host.finished == [("win", {"winner": "player", "score": {"sonnia": 0, "player": 2}})]
    assert [r["reason"] for r in host.events("result")] == ["", ""]
