"""Los juegos dentro del motor GPT-Live: un GPT-Live falso, un ``Hub`` de verdad y una
Unity de mentira que anuncia sus juegos. Sin red ni APIs reales."""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

from sonia.actions import build_default_registry
from sonia.games import SCRIPT_PREFIX, Game
from sonia.games.registry import all_games
from sonia.live.engine import TRIVIA_PLAYING_TEXT, LiveEngine
from sonia.live.prompts import build_session_config
from sonia.ws.hub import Hub
from tests.games.fakes import STACK_BRANDS
from tests.games.test_manager import ProbeGame
from tests.helpers import Recorder
from tests.test_live import (
    TRIVIA_BANK,
    FakeLiveServer,
    LiveRig,
    _backend_call,
    make_settings,
    pcm,
    running,
    wait_until,
)


@contextlib.asynccontextmanager
async def games_rig(
    tmp_path: Path,
    *,
    games: Sequence[type[Game]] = (ProbeGame,),
    unity_games: Sequence[str] | None = None,
    trivia: bool = False,
    **overrides: Any,
) -> AsyncIterator[LiveRig]:
    from websockets.asyncio.client import connect

    settings = make_settings(tmp_path, **overrides)
    if trivia:
        (tmp_path / "trivia").mkdir(exist_ok=True)
        (tmp_path / "trivia" / "preguntas.md").write_text(TRIVIA_BANK, encoding="utf-8")
    server = FakeLiveServer()
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir(exist_ok=True)
    registry = build_default_registry(include_look=False, include_trivia=trivia, games=games)
    hub = Hub(settings.ws, sample_rate=settings.live.sample_rate)
    async with running(server) as live_connect, hub:
        engine = LiveEngine(
            settings,
            hub=hub,
            registry=registry,
            connect=live_connect,
            knowledge_dir=knowledge,
            games=games,
            tick_s=0.02,
        )
        async with connect(f"ws://127.0.0.1:{hub.port}/") as client:
            assert json.loads(await asyncio.wait_for(client.recv(), 2.0))["type"] == "hello"
            rec = Recorder(client)
            await client.send(
                json.dumps(
                    {
                        "type": "client_hello",
                        "client": "unity",
                        "version": "test",
                        "games": list(
                            unity_games if unity_games is not None else [g.id for g in games]
                        ),
                        "features": ["camera_preview"],
                    }
                )
            )
            task = asyncio.create_task(engine.run())
            await rec.wait_state("idle")
            games_manager = engine.games
            assert games_manager is not None
            await wait_until(lambda: games_manager.unity_games is not None)
            try:
                yield LiveRig(settings, server, engine, hub, client, rec)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                await rec.close()


def probe(rig: LiveRig) -> ProbeGame:
    assert rig.engine.games is not None
    game = rig.engine.games.game("sonda")
    assert isinstance(game, ProbeGame)
    return game


async def test_partida_por_voz_en_el_motor(tmp_path: Path) -> None:
    async with games_rig(tmp_path) as rig:
        conn = await rig.conn()
        session = conn.start["session"]
        # Una sola línea con los juegos; las reglas no van en el prompt base.
        instructions = session["instructions"]
        assert instructions.count("Juegos en tu pantalla: la sonda.") == 1
        assert "SONDA EN MARCHA" not in instructions
        tools = [t.get("name") for t in session["delegation"]["responses"]["tools"]]
        assert "start_game" in tools and "stop_game" in tools
        # GPT-Live delega «empieza la sonda».
        script = await _backend_call(
            conn, "g1", "start_game", {"juego": "sonda", "sigue_a_sonnet_code": True}
        )
        assert script == f"{SCRIPT_PREFIX} Arranca la sonda."
        await rig.rec.wait_type("game")
        start = rig.rec.of_type("game")[0]
        assert start["event"] == "start" and start["data"] == {"title": "Sonda de Sonnia"}
        assert rig.hub.sticky("game_start") == start
        # Las reglas le llegan a GPT-Live por instructions.append, no por commentary.
        await conn.wait_for(
            lambda msgs: any(
                m["type"] == "session.instructions.append" and "SONDA EN MARCHA" in m["content"]
                for m in msgs
            )
        )
        snapshot = rig.engine.snapshot()["games"]
        assert snapshot["active"] == "sonda" and snapshot["phase"] == "playing"
        # stop_game: end con cancel, fijos fuera y vuelta a conversar.
        script = await _backend_call(conn, "g2", "stop_game", {})
        assert "Juego terminado" in script
        await rig.rec.wait_for(
            lambda msgs: any(m.get("event") == "end" for m in rig.rec.of_type("game", msgs))
        )
        assert rig.rec.of_type("game")[-1]["data"] == {"result": "cancel"}
        assert rig.hub.sticky("game_start") is None and rig.hub.sticky("game") is None
        await conn.wait_for(
            lambda msgs: any(
                "vuelve a conversar con normalidad" in str(m.get("content")) for m in msgs
            )
        )


async def test_el_juego_oye_a_sonia_al_visitante_y_a_unity(tmp_path: Path) -> None:
    async with games_rig(tmp_path) as rig:
        conn = await rig.conn()
        assert rig.engine.games is not None
        ok, _ = await rig.engine.games.start("sonda", "panel")
        assert ok
        game = probe(rig)
        await conn.audio(pcm(2400))
        await conn.say("¿Es un lenguaje?")
        await conn.audio(pcm(2400))
        await wait_until(lambda: any(c.startswith("assistant:True:") for c in game.calls))
        assert "assistant:True:¿Es un lenguaje?" in game.calls
        assert any(c.startswith("assistant:False:") for c in game.calls)
        await conn.hear("sí")
        await wait_until(lambda: "user" in game.calls)
        await rig.unity({"type": "game_event", "game": "sonda", "event": "listo", "data": {"n": 1}})
        await wait_until(lambda: "unity:listo:{'n': 1}" in game.calls)
        # Mientras dura, el motor no anima el stand ni renueva la sesión por inactividad.
        assert rig.engine._playing()


async def test_el_juego_se_cancela_si_se_cae_la_sesion(tmp_path: Path) -> None:
    async with games_rig(tmp_path) as rig:
        conn = await rig.conn()
        assert rig.engine.games is not None
        ok, _ = await rig.engine.games.start("sonda", "panel")
        assert ok
        await conn.ws.close()
        await rig.rec.wait_for(
            lambda msgs: any(m.get("event") == "end" for m in rig.rec.of_type("game", msgs))
        )
        assert rig.rec.of_type("game")[-1]["data"]["result"] == "cancel"
        assert probe(rig).stops == ["session"]
        assert not rig.engine.games.active


async def test_apagar_gpt_live_cancela_el_juego(tmp_path: Path) -> None:
    async with games_rig(tmp_path) as rig:
        await rig.conn()
        assert rig.engine.games is not None
        await rig.engine.games.start("sonda", "panel")
        await rig.engine.set_active(False)  # cambio de modo desde el panel
        assert not rig.engine.games.active and probe(rig).stops == ["session"]


async def test_no_se_pisa_con_la_trivia_en_el_motor(tmp_path: Path) -> None:
    async with games_rig(tmp_path, trivia=True) as rig:
        conn = await rig.conn()
        rig.settings.trivia.questions = 2
        trivia, games = rig.engine.trivia, rig.engine.games
        assert trivia is not None and games is not None
        ok, _ = await trivia.start("panel")
        assert ok
        script = await _backend_call(
            conn, "g1", "start_game", {"juego": "sonda", "sigue_a_sonnet_code": True}
        )
        assert TRIVIA_PLAYING_TEXT in script and not games.active
        await trivia.stop("panel")
        script = await _backend_call(
            conn, "g2", "start_game", {"juego": "sonda", "sigue_a_sonnet_code": True}
        )
        assert script.startswith(SCRIPT_PREFIX) and games.active
        script = await _backend_call(
            conn, "g3", "start_trivia", {"nivel": "sin_elegir", "sigue_a_sonnet_code": True}
        )
        assert "la sonda" in script and not trivia.active


async def test_una_unity_vieja_no_recibe_juegos(tmp_path: Path) -> None:
    async with games_rig(tmp_path, unity_games=["otro"]) as rig:
        conn = await rig.conn()
        script = await _backend_call(
            conn, "g1", "start_game", {"juego": "sonda", "sigue_a_sonnet_code": True}
        )
        assert "versión anterior" in script
        assert rig.rec.of_type("game") == []


def test_las_instrucciones_con_los_seis_juegos_no_nombran_el_stack(tmp_path: Path) -> None:
    for source in ("opencv", "none"):
        settings = make_settings(tmp_path, vision_source=source)
        registry = build_default_registry(include_look=True, include_trivia=True, games=all_games())
        config = build_session_config(settings, registry=registry, gallery_ids=[])
        backend = config["delegation"]["responses"]
        texts = [config["instructions"], backend["instructions"]]
        texts += [json.dumps(t, ensure_ascii=False) for t in backend["tools"]]
        for text in texts:
            found = [b for b in STACK_BRANDS if re.search(rf"\b{b}\b", text, re.IGNORECASE)]
            assert not found, found
        # Una sola línea para los juegos.
        assert config["instructions"].count("Juegos en tu pantalla") == 1


def test_sin_juegos_no_hay_linea_de_juegos(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    config = build_session_config(
        settings, registry=build_default_registry(include_look=False), gallery_ids=[]
    )
    assert "Juegos en tu pantalla" not in config["instructions"]


def test_el_motor_sin_juegos_no_tiene_manager(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    hub = Hub(settings.ws, sample_rate=settings.live.sample_rate)
    engine = LiveEngine(settings, hub=hub, games=[])
    assert engine.games is None
    assert engine.snapshot()["games"] is None
    # Ni con juegos si GAMES_ENABLED=false, ni en una videollamada.
    settings.games.enabled = False
    assert LiveEngine(settings, hub=hub, games=[ProbeGame]).games is None
    settings.games.enabled = True
    settings.meeting = True
    assert LiveEngine(settings, hub=hub).games is None
