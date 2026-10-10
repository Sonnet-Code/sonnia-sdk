"""Pruebas del aviso de espera en pantalla (``sonia.busy``), sin Unity ni red."""

from __future__ import annotations

from typing import Any

import pytest

from sonia.busy import TEXT_CAMERA, TEXT_GAME, TEXT_SEARCH, TEXT_THINK, BusyBoard
from sonia.ws import protocol as p


class Sent:
    """Lo que el tablero manda a Unity."""

    def __init__(self) -> None:
        self.msgs: list[dict[str, Any]] = []

    async def __call__(self, msg: dict[str, Any]) -> None:
        self.msgs.append(msg)


def on(kind: str, text: str) -> dict[str, Any]:
    return p.msg_busy(True, kind, text)


OFF = p.msg_busy(False)


async def test_manda_la_espera_de_mas_prioridad() -> None:
    sent = Sent()
    board = BusyBoard(sent)
    await board.set("live:think:a", "think", TEXT_THINK)
    await board.set("live:search:a", "search", TEXT_SEARCH)
    await board.set("game:poses:camera", "camera", TEXT_CAMERA)
    # Una de menos prioridad que llega después no tapa a la que se ve.
    await board.set("game:poses:game", "game", TEXT_GAME)
    assert board.current() == ("camera", TEXT_CAMERA)
    assert sent.msgs == [
        on("think", TEXT_THINK),
        on("search", TEXT_SEARCH),
        on("camera", TEXT_CAMERA),
    ]
    # Al irse la cámara, la siguiente en prioridad.
    await board.clear("game:poses:camera")
    assert sent.msgs[-1] == on("game", TEXT_GAME)
    await board.clear("game:poses:game")
    await board.clear("live:search:a")
    assert sent.msgs[-1] == on("think", TEXT_THINK)
    await board.clear("live:think:a")
    assert sent.msgs[-1] == OFF
    assert board.current() is None and board.keys == ()


async def test_entre_iguales_se_ve_la_mas_reciente() -> None:
    sent = Sent()
    board = BusyBoard(sent)
    await board.set("game:poses:judge", "judge", "Mirando las poses…")
    await board.set("game:ppt:judge", "judge", "Mirando tu mano…")
    assert board.current() == ("judge", "Mirando tu mano…")
    # Volver a poner una clave la hace la más reciente (y cambia el texto).
    await board.set("game:poses:judge", "judge", "Mirando las poses…")
    assert board.current() == ("judge", "Mirando las poses…")
    await board.clear("game:poses:judge")
    assert board.current() == ("judge", "Mirando tu mano…")
    assert [m.get("text") for m in sent.msgs] == [
        "Mirando las poses…",
        "Mirando tu mano…",
        "Mirando las poses…",
        "Mirando tu mano…",
    ]


async def test_no_repite_lo_que_ya_se_ve() -> None:
    sent = Sent()
    board = BusyBoard(sent)
    await board.set("live:think:a", "think", TEXT_THINK)
    await board.set("live:think:b", "think", TEXT_THINK)
    await board.clear("live:think:a")
    await board.clear("no-estaba")
    assert sent.msgs == [on("think", TEXT_THINK)]
    await board.clear("live:think:b")
    await board.clear("live:think:b")
    assert sent.msgs == [on("think", TEXT_THINK), OFF]


async def test_clear_prefix_apaga_las_de_un_juego() -> None:
    sent = Sent()
    board = BusyBoard(sent)
    await board.set("live:think:a", "think", TEXT_THINK)
    await board.set("game:poses:game", "game", TEXT_GAME)
    await board.set("game:poses:camera", "camera", TEXT_CAMERA)
    await board.clear_prefix("game:poses:")
    assert board.keys == ("live:think:a",)
    assert sent.msgs[-1] == on("think", TEXT_THINK)
    # Un prefijo sin claves no manda nada.
    count = len(sent.msgs)
    await board.clear_prefix("game:ppt:")
    assert len(sent.msgs) == count
    # Con "", todas.
    await board.clear_prefix("")
    assert board.keys == () and sent.msgs[-1] == OFF


async def test_message_sirve_para_repetirlo_al_reconectarse() -> None:
    board = BusyBoard()
    assert board.message() == OFF
    await board.set("live:search:a", "search", TEXT_SEARCH)
    assert board.message() == on("search", TEXT_SEARCH)


async def test_un_fallo_al_mandar_no_rompe_nada(caplog: pytest.LogCaptureFixture) -> None:
    calls: list[dict[str, Any]] = []

    async def broken(msg: dict[str, Any]) -> None:
        calls.append(msg)
        raise ConnectionError("Unity se fue")

    board = BusyBoard(broken)
    await board.set("live:think:a", "think", TEXT_THINK)
    assert board.current() == ("think", TEXT_THINK)
    assert "No se pudo mandar" in caplog.text
    # Sigue llevando la cuenta y, con otro destino, manda el cambio siguiente.
    sent = Sent()
    board.bind(sent)
    await board.clear("live:think:a")
    assert len(calls) == 1 and sent.msgs == [OFF]


async def test_sin_destino_solo_lleva_la_cuenta() -> None:
    board = BusyBoard()
    await board.set("live:think:a", "think", TEXT_THINK)
    assert board.keys == ("live:think:a",)
    await board.clear("live:think:a")
    assert board.current() is None


def test_tipo_desconocido_no_vale() -> None:
    with pytest.raises(ValueError):
        p.msg_busy(True, "cargando", "…")
