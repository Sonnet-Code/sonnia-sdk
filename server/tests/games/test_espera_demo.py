"""La secuencia del aviso de espera del orquestador falso (``--juego espera``)."""

from __future__ import annotations

from sonia import busy
from sonia.games.demo import ESPERA, Capture, GameMsg, Send, load_demo
from sonia.games.registry import find_game
from sonia.ws import protocol as p


def test_la_secuencia_de_espera_se_carga_y_pinta_cada_aviso() -> None:
    steps = load_demo(ESPERA)
    busies = [s.msg for s in steps if isinstance(s, Send) and s.msg.get("type") == p.MSG_BUSY]
    shown = {m["text"] for m in busies if m["on"]}
    assert shown == {
        busy.TEXT_THINK,
        busy.TEXT_SEARCH,
        busy.TEXT_GAME,
        busy.TEXT_CAMERA,
        busy.TEXT_POSES,
        busy.TEXT_HAND,
        busy.TEXT_LOOK,
    }
    assert all(m["kind"] in p.BUSY_KINDS for m in busies if m["on"])
    # Cada aviso se acaba apagando y el último mensaje de espera es un off.
    assert busies[-1] == p.msg_busy(False)


def test_los_mensajes_de_juego_van_a_nombre_de_juegos_de_verdad() -> None:
    steps = load_demo(ESPERA)
    games = {s.game for s in steps if isinstance(s, GameMsg)}
    assert games == {"poses", "piedra_papel_tijera", "busqueda", "wordle"}
    assert all(find_game(game) is not None for game in games)
    names = [s.name for s in steps if isinstance(s, Capture)]
    assert len(names) == len(set(names))
    assert all(name.startswith("espera-") for name in names)
