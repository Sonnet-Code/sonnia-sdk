"""La búsqueda relámpago y el aviso de espera (``busy``, tipo ``judge``): solo con una foto en juicio.

Nunca el modelo de verdad: jueces falsos guionizados (los de ``test_busqueda.py``).
"""

from __future__ import annotations

from sonia.busy import TEXT_LOOK
from sonia.vision.contracts import JudgeAnswer
from tests.games.test_busqueda import (
    MISS,
    SEEN,
    CountingJudge,
    GatedJudge,
    go,
    new_game,
    phase,
    pump,
    sent,
)

ON = ("judge", TEXT_LOOK)
OFF = ("judge", None)


class FailingJudge(CountingJudge):
    """Un juez que siempre falla (el modelo de visión caído)."""

    async def ask(self, question: str) -> JudgeAnswer | None:
        self.questions.append(question)
        raise RuntimeError("el modelo no contesta")


async def test_una_mirada_enciende_el_aviso_y_lo_apaga_al_contestar() -> None:
    game, host, judge = new_game(*[MISS] * 12)
    await game.start("voice", {})
    await go(game, host)
    assert host.busy == []  # sin foto en juicio, sin aviso
    await pump(game, host, 2.6)
    assert len(judge.questions) == 1
    assert host.busy == [ON, OFF]
    assert host.busy_now == {}
    await pump(game, host, 2.6)
    assert len(judge.questions) == 2
    assert host.busy == [ON, OFF, ON, OFF]
    assert host.busy_now == {}


async def test_el_aviso_dura_lo_que_la_foto_esta_en_el_aire() -> None:
    judge = GatedJudge([SEEN])
    game, host, _ = new_game(judge=judge)
    await game.start("voice", {})
    await go(game, host)
    await pump(game, host, 4.0, wait=False)  # la puerta cerrada: la foto sigue en juicio
    assert len(judge.questions) == 1
    assert host.busy_now == {"judge": TEXT_LOOK}
    judge.gate.set()
    await pump(game, host, 0.3)
    assert sent(host, "found") and phase(game) == "between"
    assert host.busy[-1] == OFF and host.busy_now == {}


async def test_si_el_juez_no_contesta_el_aviso_tambien_se_apaga() -> None:
    game, host, judge = new_game(*[None] * 12)
    await game.start("voice", {})
    await go(game, host)
    await pump(game, host, 2.6)
    assert len(judge.questions) == 1
    assert host.busy == [ON, OFF] and host.busy_now == {}


async def test_si_el_juez_falla_el_aviso_se_apaga_y_el_juego_sigue() -> None:
    judge = FailingJudge()
    game, host, _ = new_game(judge=judge)
    await game.start("voice", {})
    await go(game, host)
    await pump(game, host, 5.2)
    assert len(judge.questions) == 2
    assert host.busy == [ON, OFF, ON, OFF] and host.busy_now == {}
    assert phase(game) == "running"


async def test_si_el_aviso_falla_la_mirada_sigue() -> None:
    game, host, judge = new_game(SEEN)

    async def broken(kind: str, text: str | None) -> None:
        raise RuntimeError("sin pantalla")

    host.set_busy = broken  # type: ignore[method-assign]
    await game.start("voice", {})
    await go(game, host)
    await pump(game, host, 2.6)
    assert len(judge.questions) == 1
    assert sent(host, "found") and phase(game) == "between"
