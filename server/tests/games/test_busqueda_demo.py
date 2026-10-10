"""La secuencia del orquestador falso de la búsqueda relámpago manda lo mismo que el juego."""

from __future__ import annotations

import pytest

from sonia.games.busqueda.demo import steps
from sonia.games.busqueda.game import BusquedaGame
from sonia.games.demo import Capture, GameMsg, Preview, load_demo
from tests.games.fakes import FakeVision, make_game
from tests.games.test_busqueda import RoundJudge, go, next_round, pump


def _demo_messages(event: str) -> list[dict[str, object]]:
    return [s.data for s in steps() if isinstance(s, GameMsg) and s.event == event]


async def test_los_mensajes_de_la_secuencia_tienen_las_claves_de_los_del_juego() -> None:
    judge = RoundJudge([1])  # la ronda 1 la encuentra y en la 2 se acaba el tiempo
    game, host = make_game(BusquedaGame, vision=FakeVision(judge=judge))
    await game.start("voice", {})
    await go(game, host)
    real_go = host.last("go")
    await pump(game, host, 2.7)
    real_found = host.last("found")
    await next_round(game, host)
    real_round = host.last("round")
    await go(game, host)
    await pump(game, host, 26.0)
    real_timeout = host.last("timeout")
    real_checking = host.last("checking")

    assert set(_demo_messages("start")[0]) - {"title"} == set(host.last("start"))
    for event, real in (
        ("round", real_round),
        ("go", real_go),
        ("found", real_found),
        ("timeout", real_timeout),
    ):
        for data in _demo_messages(event):
            assert set(data) == set(real), event
    assert set(_demo_messages("checking")[0]) == set(real_checking)
    # Los colores de la secuencia son los que mandaría el banco.
    assert {m["color"] for m in _demo_messages("round")} >= {"#4285F4", "#EA4335"}


def test_la_secuencia_pasa_por_cada_estado_de_la_pantalla_con_su_captura() -> None:
    sequence = load_demo("busqueda")
    assert [type(s) for s in sequence] == [type(s) for s in steps()]
    events = [s.event for s in sequence if isinstance(s, GameMsg)]
    for needed in ("start", "round", "go", "checking", "found", "timeout", "end"):
        assert needed in events
    assert events[0] == "start" and events[-1] == "end"
    captures = [s.name for s in sequence if isinstance(s, Capture)]
    assert len(captures) == len(set(captures)) >= 8
    assert all(name.startswith("busqueda-") for name in captures)
    assert any(isinstance(s, Preview) for s in sequence)
    end = next(s for s in sequence if isinstance(s, GameMsg) and s.event == "end")
    found, total = end.data["found"], end.data["total"]
    assert isinstance(found, int) and isinstance(total, int)
    assert end.data["result"] == "win" and found <= total


def test_la_vista_en_vivo_sale_de_una_foto_publica_o_de_una_imagen_sintetica(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BUSQUEDA_DEMO_FOTO", raising=False)
    preview = next(s for s in steps() if isinstance(s, Preview))
    assert preview.source == ""  # sintética salvo que se dé una foto pública
    monkeypatch.setenv("BUSQUEDA_DEMO_FOTO", "/tmp/foto-publica.jpg")
    preview = next(s for s in steps() if isinstance(s, Preview))
    assert preview.source == "/tmp/foto-publica.jpg"
