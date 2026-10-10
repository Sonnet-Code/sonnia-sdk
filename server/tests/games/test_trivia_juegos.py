"""Lo que la trivia añade para los juegos: no empieza con un juego en marcha y saca
preguntas sueltas para la ruleta (``draw_one``) sin repetir hasta agotar el nivel."""

from __future__ import annotations

import random
from pathlib import Path

from sonia.config import TriviaSettings
from sonia.trivia import TriviaGame
from tests.test_trivia import FakeHost, FakeScreen

BANK = """\
## [fácil] ¿Fácil uno?
- [x] Bien
- [ ] Mal
- [ ] Peor

## [fácil] ¿Fácil dos?
- [x] Bien
- [ ] Mal
- [ ] Peor

## [fácil] ¿Fácil tres?
- [x] Bien
- [ ] Mal
- [ ] Peor

## [difícil] ¿Difícil uno?
- [x] Bien
- [ ] Mal
- [ ] Peor
"""


def make_trivia(tmp_path: Path, busy: str | None = None) -> TriviaGame:
    bank = tmp_path / "preguntas.md"
    bank.write_text(BANK, encoding="utf-8")
    return TriviaGame(
        TriviaSettings(questions=1, win_threshold=1),
        bank,
        host=FakeHost(),
        screen=FakeScreen(),
        rng=random.Random(3),
        busy=lambda: busy,
    )


def test_draw_one_no_repite_hasta_agotar_el_nivel(tmp_path: Path) -> None:
    trivia = make_trivia(tmp_path)
    drawn = [trivia.draw_one("fácil") for _ in range(3)]
    texts = [q.text for q in drawn if q is not None]
    assert sorted(texts) == ["¿Fácil dos?", "¿Fácil tres?", "¿Fácil uno?"]
    # Agotadas las fáciles, vuelve a empezar por ellas antes que pasar de nivel.
    again = trivia.draw_one("fácil")
    assert again is not None and again.level == "fácil"
    hard = trivia.draw_one("difícil")
    assert hard is not None and hard.text == "¿Difícil uno?"
    assert len(hard.options) == 3 and 0 <= hard.correct < 3


async def test_la_trivia_no_empieza_con_un_juego_en_marcha(tmp_path: Path) -> None:
    trivia = make_trivia(tmp_path, busy="Ahora mismo se está jugando a la sonda.")
    ok, text = await trivia.start("voice")
    assert not ok and text == "Ahora mismo se está jugando a la sonda."
    assert not trivia.active
