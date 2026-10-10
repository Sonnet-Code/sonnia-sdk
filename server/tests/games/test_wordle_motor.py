"""El Wordle dentro del motor GPT-Live: un GPT-Live falso, un ``Hub`` de verdad y una Unity de
mentira que anuncia el juego. Sin red ni APIs reales.

Lo que prueba que no prueban los tests del juego suelto ni del manager: el cableado real. Que
GPT-Live ve las herramientas ``start_game`` y ``wordle_guess`` y la línea de juegos del prompt
(sin las reglas), que las reglas le llegan por ``instructions.append``, que cada intento vuelve
como guion marcado con ``PARA SONIA:`` y que la pantalla recibe ``start``, ``guess`` y ``end``.
"""

from __future__ import annotations

from pathlib import Path

from sonia.games import INSTRUCT_MAX_CHARS, SCRIPT_PREFIX
from sonia.games.wordle import WordleGame
from sonia.games.wordle.bank import WORDS
from tests.games.test_motor import games_rig
from tests.games.test_wordle import bank_text
from tests.test_live import LiveRig, _backend_call


def secret_of(rig: LiveRig) -> str:
    games = rig.engine.games
    assert games is not None and isinstance(games.current, WordleGame)
    return games.current.word


async def test_el_wordle_por_voz_de_punta_a_punta_en_el_motor(tmp_path: Path) -> None:
    async with games_rig(tmp_path, games=[WordleGame]) as rig:
        games = rig.engine.games
        assert games is not None
        games.use_cloud_banks({WORDS.id: bank_text()})
        # Sin esperas largas al terminar: el resultado se cuenta y se cierra.
        rig.settings.games.result_seconds = 0.0
        rig.settings.games.final_wait_seconds = 0.0
        conn = await rig.conn()

        # Una sola línea con los juegos; las reglas no van en el prompt base.
        session = conn.start["session"]
        instructions = session["instructions"]
        assert instructions.count("Juegos en tu pantalla: el Wordle de tecnología.") == 1
        assert "NO conoces la palabra" not in instructions
        tools = {t.get("name"): t for t in session["delegation"]["responses"]["tools"]}
        assert {"start_game", "stop_game", "wordle_guess"} <= set(tools)
        assert tools["wordle_guess"]["parameters"]["required"] == ["palabra"]

        # Empezar: el guion vuelve como resultado; la pantalla recibe el start.
        script = await _backend_call(
            conn, "w1", "start_game", {"juego": "wordle", "sigue_a_sonnet_code": True}
        )
        assert script.startswith(SCRIPT_PREFIX) and "5 letras" in script
        await rig.rec.wait_type("game")
        start = rig.rec.of_type("game")[0]
        assert start["game"] == "wordle" and start["event"] == "start"
        assert start["data"] == {
            "title": "Wordle de tecnología",
            "rows": 6,
            "cols": 5,
            "hint_after": 4,
        }
        assert rig.hub.sticky("game_start") == start
        # Las reglas le llegan por instructions.append (sin hablar), cortas y sin la palabra.
        secret = secret_of(rig)
        await conn.wait_for(
            lambda msgs: any(
                "NO conoces la palabra" in m["content"]
                for m in conn.of_type("session.instructions.append")
            )
        )
        rules = next(
            m["content"]
            for m in conn.of_type("session.instructions.append")
            if "NO conoces la palabra" in m["content"]
        )
        assert len(rules) <= INSTRUCT_MAX_CHARS and secret not in rules

        # Un intento que no es la palabra: el resumen vuelve como guion y la pantalla lo pinta.
        script = await _backend_call(conn, "w2", "wordle_guess", {"palabra": "linux"})
        assert script.startswith(f"{SCRIPT_PREFIX} Intento 1 de 6, «LINUX»")
        await rig.rec.wait_for(
            lambda msgs: any(m.get("event") == "guess" for m in rig.rec.of_type("game", msgs))
        )
        guess = next(m for m in rig.rec.of_type("game") if m["event"] == "guess")
        assert guess["data"]["row"] == 0 and guess["data"]["letters"] == "LINUX"
        assert guess["data"]["word"] == "" and secret not in str(guess["data"])
        assert rig.hub.sticky("game") == guess

        # Una palabra que no vale no gasta intento y sacude la fila (suelto, sin quedar fijo).
        script = await _backend_call(conn, "w3", "wordle_guess", {"palabra": "web"})
        assert "No cuenta como intento: llevan 1 de 6" in script
        await rig.rec.wait_for(
            lambda msgs: any(m.get("event") == "invalid" for m in rig.rec.of_type("game", msgs))
        )
        assert rig.hub.sticky("game") == guess

        # Acertar: confeti en pantalla (result win), el end con la palabra y vuelta a conversar.
        script = await _backend_call(conn, "w4", "wordle_guess", {"palabra": secret})
        assert "LO HAN ADIVINADO en el intento 2 de 6" in script
        assert "Brian o Mariel" in script
        await rig.rec.wait_for(
            lambda msgs: any(m.get("event") == "end" for m in rig.rec.of_type("game", msgs))
        )
        last_guess = [m for m in rig.rec.of_type("game") if m["event"] == "guess"][-1]
        assert last_guess["data"]["result"] == "win" and last_guess["data"]["word"] == secret
        end = rig.rec.of_type("game")[-1]
        assert end["event"] == "end"
        assert end["data"] == {"word": secret, "attempts": 2, "result": "win"}
        assert rig.hub.sticky("game_start") is None and rig.hub.sticky("game") is None
        await conn.wait_for(
            lambda msgs: any(
                "vuelve a conversar con normalidad" in str(m.get("content")) for m in msgs
            )
        )
        assert games.active is False

        # Fuera de turno: sin partida, el guion lo dice y no pasa nada.
        script = await _backend_call(conn, "w5", "wordle_guess", {"palabra": "REACT"})
        assert "No hay ninguna partida" in script
