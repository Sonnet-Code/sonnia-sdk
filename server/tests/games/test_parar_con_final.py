"""El gancho ``Game.stop_requested``: un juego que, al terminarlo por voz o desde el panel con
la partida en marcha, cierra enseñando su final en vez de cancelarse."""

from __future__ import annotations

from typing import Any, ClassVar

from sonia.actions import build_default_registry
from sonia.games import SCRIPT_PREFIX, Game, StopReason
from sonia.games.manager import CANCEL_TEXT, PANEL_STOP_TEXT
from sonia.types import ActionContext
from tests.games.fakes import make_manager, settle

FINAL = "Se acabó: la respuesta era 42. Dilo con gracia en una frase."


class FinalGame(Game):
    """Enseña su final al terminarlo (como el Wordle)."""

    id: ClassVar[str] = "final"
    title: ClassVar[str] = "Con final"
    spoken: ClassVar[str] = "el juego con final"
    settings_key: ClassVar[str] = "wordle"

    def __init__(self, host: Any) -> None:
        super().__init__(host)
        self.requests: list[str] = []
        self.stops: list[StopReason] = []
        self.finish = True

    async def start(self, source: str, options: dict[str, Any]) -> str:
        return "Arranca."

    async def stop_requested(self, source: str) -> str | None:
        self.requests.append(source)
        await self.host.send("reveal", {"answer": 42})
        if self.finish:
            await self.host.finish("lose", {"answer": 42})
        return FINAL

    async def stop(self, reason: StopReason) -> None:
        self.stops.append(reason)


class PlainGame(Game):
    """Sin gancho: se cancela como siempre."""

    id: ClassVar[str] = "simple"
    title: ClassVar[str] = "Simple"
    spoken: ClassVar[str] = "el juego simple"
    settings_key: ClassVar[str] = "wordle"

    async def start(self, source: str, options: dict[str, Any]) -> str:
        return "Arranca."


def final_game(manager: Any) -> FinalGame:
    game = manager.game("final")
    assert isinstance(game, FinalGame)
    return game


async def test_por_voz_no_cancela_y_devuelve_el_guion() -> None:
    manager, engine, screen, _ = await make_manager([FinalGame])
    registry = build_default_registry(include_look=False, games=[FinalGame])
    ctx = ActionContext(camera=None, avatar=None, gallery_dir="", extra={"games": manager})
    await registry.execute("start_game", {"juego": "final"}, ctx)
    result = await registry.execute("stop_game", {}, ctx)
    assert result.text == f"{SCRIPT_PREFIX} {FINAL}"
    game = final_game(manager)
    assert game.requests == ["voice"]
    # Sigue el final normal: el final en pantalla hasta que Sonia lo cuenta, y luego «end».
    assert manager.phase == "finishing" and not screen.game_msgs("end")
    assert screen.game_msgs("reveal")[-1]["data"] == {"answer": 42}
    await settle()
    assert screen.game_msgs("end")[-1]["data"] == {"answer": 42, "result": "lose"}
    assert game.stops == ["finished"] and not manager.active
    assert not any(t.startswith("JUEGO: el equipo") for t in engine.spoken)
    assert "vuelve a conversar con normalidad" in engine.instructions[-1]


async def test_desde_el_panel_se_lo_pasa_a_gpt_live_por_speak() -> None:
    manager, engine, screen, _ = await make_manager([FinalGame])
    await manager.start("final", "voice")
    ok, text = await manager.stop("panel")
    assert ok and text == "Con final: enseña su final y se cierra."
    assert final_game(manager).requests == ["panel"]
    await settle()
    assert engine.spoken == [PANEL_STOP_TEXT.format(spoken="el juego con final") + FINAL]
    assert screen.game_msgs("end")[-1]["data"]["result"] == "lose"


async def test_sin_gancho_se_cancela_como_siempre() -> None:
    manager, engine, screen, _ = await make_manager([PlainGame])
    registry = build_default_registry(include_look=False, games=[PlainGame])
    ctx = ActionContext(camera=None, avatar=None, gallery_dir="", extra={"games": manager})
    await registry.execute("start_game", {"juego": "simple"}, ctx)
    result = await registry.execute("stop_game", {}, ctx)
    assert result.text.startswith("Juego terminado.")
    assert screen.game_msgs("end")[-1]["data"] == {"result": "cancel"}
    assert not manager.active
    await manager.start("simple", "voice")
    ok, _ = await manager.stop("panel")
    assert ok and engine.spoken[-1] == CANCEL_TEXT["panel"].format(spoken="el juego simple")


async def test_un_final_sin_finish_se_cancela_igual() -> None:
    manager, _, screen, _ = await make_manager([FinalGame])
    await manager.start("final", "voice")
    final_game(manager).finish = False
    ok, text = await manager.stop("voice")
    assert ok and text == "Con final terminado."
    assert screen.game_msgs("end")[-1]["data"] == {"result": "cancel"}


async def test_solo_por_voz_o_desde_el_panel_y_con_la_partida_en_marcha() -> None:
    manager, _, screen, _ = await make_manager([FinalGame])
    await manager.start("final", "voice")
    await manager.on_session_lost()  # la sesión se cae: se cancela, sin gancho
    assert final_game(manager).requests == []
    assert screen.game_msgs("end")[-1]["data"] == {"result": "cancel"}
    # Si ya enseñaba un final, terminarlo lo cierra con ese final, sin preguntar otra vez.
    await manager.start("final", "voice")
    await final_game(manager).host.finish("win", {"answer": 7})
    ok, _ = await manager.stop("panel")
    assert ok and final_game(manager).requests == []
    assert screen.game_msgs("end")[-1]["data"] == {"answer": 7, "result": "win"}
