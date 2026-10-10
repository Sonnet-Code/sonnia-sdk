"""No regresión del editor de prompts contra la referencia sacada antes de él (441157a).

Con los prompts de la app (sin nada de la nube), las instrucciones de GPT-Live y del backend
en 8 configuraciones, la visión, los gestos y los jueces tienen que salir idénticos, byte a
byte, a ``data/prompts_referencia.json``. Los textos de la trivia y de los juegos tienen sus
propias instantáneas en sus tests.
"""

from __future__ import annotations

import json
from pathlib import Path

from sonia.prompts import BOOK
from tests.prompt_cases import render_shared_cases

REFERENCE = Path(__file__).parent / "data" / "prompts_referencia.json"


async def test_con_los_prompts_de_la_app_todo_sale_igual_que_antes(tmp_path: Path) -> None:
    BOOK.set_overrides(None)
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    now = await render_shared_cases(tmp_path)
    assert now, "sin casos"
    differences = [name for name in now if name in reference and now[name] != reference[name]]
    missing = [name for name in now if name not in reference]
    assert not missing, f"casos sin referencia: {missing}"
    assert not differences, f"textos distintos de la referencia: {differences}"
