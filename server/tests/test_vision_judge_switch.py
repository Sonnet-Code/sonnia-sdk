"""El juez de las rondas de cámara cambiable en caliente (``games_judge``), sin red.

``JudgeSwitch`` dice quién juzga y los envoltorios (``SwitchedReferee``, ``SwitchedJudge``)
lo miran en cada llamada: el cambio vale al momento, también a media ronda.
"""

from __future__ import annotations

import numpy as np
import pytest

from sonia.vision.contracts import (
    JUDGE_MODES,
    JudgeAnswer,
    JudgeSwitch,
    NoReferee,
    PoseVerdict,
    judge_mode,
)
from sonia.vision.games import NoJudge, SwitchedJudge, SwitchedReferee
from tests.games.fakes import FakeJudge, FakeReferee


def frame() -> np.ndarray:
    return np.zeros((48, 64, 3), dtype=np.uint8)


class CountingJudge(FakeJudge):
    """Un juez con la cuenta de fotos de la ronda, como ``ModelJudge``."""

    def __init__(self, answers: list[JudgeAnswer | None] | None = None) -> None:
        super().__init__(answers or [])
        self.rounds: list[int | None] = []
        self.calls = 0
        self.limit: int | None = None

    @property
    def remaining(self) -> int | None:
        return None if self.limit is None else max(0, self.limit - self.calls)

    def start_round(self, max_calls: int | None) -> None:
        self.rounds.append(max_calls)
        self.limit = max_calls
        self.calls = 0

    async def ask(self, question: str) -> JudgeAnswer | None:
        self.calls += 1
        return await super().ask(question)


def test_judge_mode_normaliza() -> None:
    assert JUDGE_MODES == ("gemini", "local")
    assert judge_mode("gemini") == "gemini"
    assert judge_mode(" Local ") == "local"
    for raw in ("", "app", "luna", None, 1, ["gemini"]):
        assert judge_mode(raw) is None


def test_el_conmutador_manda_el_pedido_o_el_de_la_app() -> None:
    switch = JudgeSwitch("gemini", gemini=True)
    assert switch.state() == {"mode": "gemini", "app": "gemini", "requested": None, "gemini": True}
    assert switch.set_mode("local") == "local"
    assert switch.state() == {
        "mode": "local",
        "app": "gemini",
        "requested": "local",
        "gemini": True,
    }
    # None, vacío o algo que no es un modo: el de la app (GAMES_JUDGE).
    for back in (None, "", "app", "xx"):
        switch.set_mode("local")
        assert switch.set_mode(back) == "gemini" and switch.requested is None
    # Un GAMES_JUDGE raro arranca con el de por defecto.
    assert JudgeSwitch("raro", gemini=True).app_mode == "gemini"
    assert JudgeSwitch("local", gemini=True).mode == "local"


def test_sin_gemini_siempre_local() -> None:
    switch = JudgeSwitch("gemini", gemini=False)
    assert switch.mode == "local" and not switch.gemini_available
    assert switch.set_mode("gemini") == "local"
    # El estado dice qué se pidió y que no hay Gemini.
    assert switch.state() == {
        "mode": "local",
        "app": "gemini",
        "requested": "gemini",
        "gemini": False,
    }


async def test_el_juez_de_rondas_sigue_al_conmutador() -> None:
    switch = JudgeSwitch("gemini", gemini=True)
    verdict = PoseVerdict(people=1, counts={"brazos_arriba": 1})
    gemini = FakeReferee(poses=[verdict, verdict])
    referee = SwitchedReferee(switch, gemini)
    assert referee.available and referee.current is gemini
    assert await referee.poses(frame()) == verdict

    # A local: sin juez (deciden las detecciones locales) y sin fotos a Gemini.
    switch.set_mode("local")
    assert not referee.available and isinstance(referee.current, NoReferee)
    assert await referee.poses(frame()) is None
    assert await referee.hands(frame()) is None
    assert gemini.photos == [("poses", (48, 64, 3))]

    # Y de vuelta, al momento.
    switch.set_mode(None)
    assert referee.available
    assert await referee.poses(frame()) == verdict
    assert len(gemini.photos) == 2


async def test_la_busqueda_sigue_al_conmutador_y_los_topes_cuadran() -> None:
    switch = JudgeSwitch("gemini", gemini=True)
    gemini = CountingJudge([JudgeAnswer(seen=True, what="una botella")])
    local = CountingJudge([JudgeAnswer(seen=False)])
    judge = SwitchedJudge(switch, gemini, local)
    assert judge.available and judge.current is gemini

    # La ronda empieza en los dos: si el modo cambia a media ronda, el otro ya tiene su tope.
    judge.start_round(3)
    assert gemini.rounds == [3] and local.rounds == [3]
    assert await judge.ask("¿Hay una botella?") == JudgeAnswer(seen=True, what="una botella")
    assert judge.remaining == 2

    switch.set_mode("local")
    assert judge.current is local and judge.remaining == 3
    assert await judge.ask("¿Hay una botella?") == JudgeAnswer(seen=False)
    assert gemini.questions == ["¿Hay una botella?"] and local.questions == ["¿Hay una botella?"]


async def test_en_local_sin_modelo_de_vision_no_hay_busqueda() -> None:
    switch = JudgeSwitch("gemini", gemini=True)
    judge = SwitchedJudge(switch, FakeJudge(), NoJudge())
    assert judge.available
    switch.set_mode("local")
    assert not judge.available
    assert await judge.ask("¿Hay una taza?") is None
    # Los jueces sin cuenta (sin ``start_round`` ni ``remaining``) no rompen nada.
    judge.start_round(2)
    assert judge.remaining is None


@pytest.mark.parametrize("mode", ["gemini", "local"])
async def test_sin_gemini_el_envoltorio_nunca_va_a_gemini(mode: str) -> None:
    switch = JudgeSwitch(mode, gemini=False)
    gemini = FakeReferee(poses=[PoseVerdict(people=1)])
    referee = SwitchedReferee(switch, gemini)
    switch.set_mode("gemini")
    assert not referee.available
    assert await referee.poses(frame()) is None and gemini.photos == []
