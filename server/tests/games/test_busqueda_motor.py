"""La búsqueda relámpago dentro del motor GPT-Live: un GPT-Live falso, un ``Hub`` de verdad y una
Unity de mentira. Sin red ni APIs reales ni cámara: el modelo de visión es el ``FakeJudge``.

Comprueba lo que los tests con un ``GameHost`` falso no ven: que la salida se da cuando Sonia
termina de decir el objeto (su transcripción y su audio de verdad), que la celebración y el
anuncio de la ronda siguiente llegan a GPT-Live por ``commentary`` y que las delegaciones de
las jugadas van por el backend como en el stand.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from sonia.games import SCRIPT_PREFIX
from sonia.games.busqueda import game as game_module
from sonia.games.busqueda.game import BusquedaGame
from tests.games.fakes import FakeVision, game_settings
from tests.games.test_busqueda import SEEN, CountingJudge, RoundJudge
from tests.games.test_motor import games_rig
from tests.test_live import _backend_call, pcm, wait_until


def commentary(conn: object, fragment: str, count: int = 1) -> bool:
    """¿Le han llegado a GPT-Live ``count`` comentarios con ``fragment``?"""
    found = [
        m
        for m in conn.received  # type: ignore[attr-defined]
        if m["type"] == "session.commentary.append" and fragment in str(m["content"])
    ]
    return len(found) >= count


async def test_una_ronda_por_voz_de_punta_a_punta_en_el_motor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shutil.copytree(game_settings().games_dir / "busqueda", tmp_path / "games" / "busqueda")
    monkeypatch.setattr(game_module, "SETTLE_S", 0.25)
    async with games_rig(tmp_path, games=[BusquedaGame]) as rig:
        manager = rig.engine.games
        assert manager is not None
        vision = FakeVision(judge=CountingJudge([SEEN]))
        manager.attach_vision(vision.game_vision())
        manager._camera_ready = lambda: True  # type: ignore[assignment]  # un equipo con cámara USB
        rig.settings.games.busqueda.round_seconds = 5.0
        rig.settings.games.busqueda.check_seconds = 0.3
        conn = await rig.conn()
        session = conn.start["session"]
        assert session["instructions"].count("Juegos en tu pantalla: la búsqueda relámpago.") == 1
        tools = [t.get("name") for t in session["delegation"]["responses"]["tools"]]
        assert {"start_game", "stop_game", "busqueda_check"} <= set(tools)

        # GPT-Live delega empezar: una sola delegación; el guion lleva el objeto y la ronda.
        script = await _backend_call(
            conn, "b1", "start_game", {"juego": "busqueda", "sigue_a_sonnet_code": True}
        )
        assert script.startswith(SCRIPT_PREFIX) and "ronda 1 de 3" in script
        await rig.rec.wait_for(
            lambda msgs: any(m.get("event") == "round" for m in rig.rec.of_type("game", msgs))
        )
        first = rig.rec.of_type("game")[-1]["data"]
        assert first["index"] == 1 and first["phase"] == "ready" and first["seconds"] == 5.0
        assert f"«¡El primero que me enseñe {first['object']}!»" in script
        # Las reglas llegan por instructions.append (no hacen hablar a Sonia).
        await conn.wait_for(
            lambda msgs: any(
                m["type"] == "session.instructions.append" and "busqueda_check" in m["content"]
                for m in msgs
            )
        )
        assert vision.stream.active and vision.preview.active

        # Antes de la salida, una delegación de busqueda_check pide esperar (y no mira).
        assert "Todavía no se ha dado la salida" in await _backend_call(
            conn, "b2", "busqueda_check", {}
        )
        assert vision.judge.questions == []  # type: ignore[attr-defined]

        # Sonia anuncia el objeto, de verdad: audio y transcripción. Al callar, la salida.
        await conn.audio(pcm(2400))
        await conn.say(f"¡El primero que me enseñe {first['object']}!")
        await conn.audio(pcm(2400))
        await rig.rec.wait_for(
            lambda msgs: any(m.get("event") == "go" for m in rig.rec.of_type("game", msgs)),
            limit=5.0,
        )
        go = next(m for m in rig.rec.of_type("game") if m["event"] == "go")
        assert go["data"]["phase"] == "running" and go["data"]["object"] == first["object"]
        await conn.wait_for(lambda _msgs: commentary(conn, "«¡Ya!»"))  # el «¡Ya!», sin grabar

        # La primera mirada ve el objeto: ¡encontrado!, el «¡Lo veo!» y la celebración.
        await rig.rec.wait_for(
            lambda msgs: any(m.get("event") == "found" for m in rig.rec.of_type("game", msgs)),
            limit=5.0,
        )
        found = next(m for m in rig.rec.of_type("game") if m["event"] == "found")
        assert found["data"]["what"] == "botella azul" and found["data"]["found"] == 1
        await conn.wait_for(lambda _msgs: commentary(conn, "En la cámara se ve «botella azul»"))
        assert commentary(conn, "«¡Lo veo!»")
        assert manager.snapshot()["state"]["found"] == 1

        # Sonia lo cuenta y calla: sale la ronda 2 con su anuncio por commentary.
        await conn.audio(pcm(2400))
        await conn.say("¡Qué rápidos!")
        await conn.audio(pcm(2400))
        await rig.rec.wait_for(
            lambda msgs: (
                len([m for m in rig.rec.of_type("game", msgs) if m["event"] == "round"]) >= 2
            ),
            limit=5.0,
        )
        second = [m for m in rig.rec.of_type("game") if m["event"] == "round"][-1]["data"]
        assert second["index"] == 2 and second["found"] == 1 and second["object"] != first["object"]
        await conn.wait_for(lambda _msgs: commentary(conn, "ronda 2 de 3"))

        # Terminar a mitad: end con cancel, la cámara suelta y vuelta a conversar.
        script = await _backend_call(conn, "b3", "stop_game", {})
        assert "Juego terminado" in script
        await rig.rec.wait_for(
            lambda msgs: any(m.get("event") == "end" for m in rig.rec.of_type("game", msgs))
        )
        assert rig.rec.of_type("game")[-1]["data"]["result"] == "cancel"
        await wait_until(lambda: not vision.stream.active and not vision.preview.active)
        assert rig.hub.sticky("game_start") is None and rig.hub.sticky("game") is None
        await conn.wait_for(
            lambda msgs: any(
                "vuelve a conversar con normalidad" in str(m.get("content")) for m in msgs
            )
        )


async def sonia_says(conn: object, text: str) -> None:
    """Sonia dice algo: audio y transcripción, como llegan de GPT-Live."""
    await conn.audio(pcm(2400))  # type: ignore[attr-defined]
    await conn.say(text)  # type: ignore[attr-defined]
    await conn.audio(pcm(2400))  # type: ignore[attr-defined]


async def test_una_partida_de_tres_rondas_hasta_el_final_en_el_motor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shutil.copytree(game_settings().games_dir / "busqueda", tmp_path / "games" / "busqueda")
    monkeypatch.setattr(game_module, "SETTLE_S", 0.25)
    async with games_rig(tmp_path, games=[BusquedaGame]) as rig:
        manager = rig.engine.games
        assert manager is not None
        vision = FakeVision(judge=RoundJudge([1, 2, 3]))  # ve el objeto a la primera en cada ronda
        manager.attach_vision(vision.game_vision())
        manager._camera_ready = lambda: True  # type: ignore[assignment]
        rig.settings.games.busqueda.round_seconds = 5.0
        rig.settings.games.busqueda.check_seconds = 0.3
        rig.settings.games.result_seconds = 0.2
        rig.settings.games.final_wait_seconds = 4.0
        conn = await rig.conn()

        def events(kind: str) -> list[dict[str, Any]]:
            return [m for m in rig.rec.of_type("game") if m["event"] == kind]

        async def wait_event(kind: str, count: int) -> dict[str, Any]:
            await rig.rec.wait_for(lambda _msgs: len(events(kind)) >= count, limit=6.0)
            return events(kind)[count - 1]

        await _backend_call(
            conn, "b1", "start_game", {"juego": "busqueda", "sigue_a_sonnet_code": True}
        )
        for number in (1, 2, 3):
            ronda = await wait_event("round", number)
            assert ronda["data"]["index"] == number and ronda["data"]["found"] == number - 1
            await sonia_says(conn, f"¡El primero que me enseñe {ronda['data']['object']}!")
            go = await wait_event("go", number)
            assert go["data"]["index"] == number
            found = await wait_event("found", number)
            assert found["data"]["found"] == number and found["data"]["what"] == "botella azul"
            await conn.wait_for(lambda _msgs, n=number: commentary(conn, "En la cámara se ve", n))
            if number < 3:
                await sonia_says(conn, "¡Qué buen ojo!")

        # La última ronda lleva el final en el mismo guion: encontraron las tres.
        await conn.wait_for(lambda _msgs: commentary(conn, "han encontrado 3 de 3"))
        assert commentary(conn, "¡Las 3 de 3!") and commentary(conn, "Brian o Mariel")
        assert len(events("round")) == 3 and events("end") == []
        # Sonia lo cuenta y calla; entonces sale el final de la pantalla.
        await sonia_says(conn, "¡Las tres! ¡Pasen a ver a Brian o a Mariel!")
        end = await wait_event("end", 1)
        assert end["data"] == {"result": "win", "found": 3, "total": 3, "photos": 3}
        await wait_until(lambda: not manager.active)
        await wait_until(lambda: not vision.stream.active and not vision.preview.active)
        assert rig.hub.sticky("game_start") is None and rig.hub.sticky("game") is None
        await conn.wait_for(
            lambda msgs: any(
                "vuelve a conversar con normalidad" in str(m.get("content")) for m in msgs
            )
        )
