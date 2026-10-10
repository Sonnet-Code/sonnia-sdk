"""Textos de la trivia para GPT-Live editables desde la nube (``sonia.prompts``).

Las instantáneas (``snapshots/prompts_trivia.json``) se sacaron con el código de antes de
hacerlos editables: con los textos de la app, lo que recibe GPT-Live (instrucciones,
``commentary`` y guiones de las acciones) tiene que ser idéntico, byte a byte. Sin red ni
GPT-Live real: un motor y una pantalla falsos que apuntan todo en orden.
"""

from __future__ import annotations

import asyncio
import random
from pathlib import Path
from typing import Any

from sonia.actions import build_default_registry
from sonia.config import TriviaSettings
from sonia.trivia import PASS, TriviaGame
from sonia.trivia.game import NUDGE_S
from sonia.types import ActionContext
from tests.prompt_snapshots import assert_snapshot

#: Banco propio (no el del repo, que Jean edita): cuatro preguntas, una con dato y una por
#: nivel, para que las partidas de las instantáneas no cambien al tocar el banco.
BANK = """\
## [fácil] ¿Qué lenguaje se usa para dar estilo a las páginas web?
- [x] CSS
- [ ] SQL
- [ ] Bash
> CSS significa hojas de estilo en cascada.

## ¿Qué empresa organiza los GDG en todo el mundo?
- [ ] Mozilla
- [x] Google
- [ ] La Linux Foundation

## [difícil] ¿En qué año salió la primera versión de Python?
- [ ] 1985
- [x] 1991
- [ ] 2000
> Guido van Rossum la publicó en febrero de 1991.

## ¿Qué significa la «I» de IA?
- [ ] Internet
- [ ] Interfaz
- [x] Inteligencia
"""


class LogHost:
    """El motor GPT-Live visto por la partida: apunta en orden todo lo que le llega."""

    def __init__(self, log: list[list[Any]]) -> None:
        self.log = log
        self.connected = True
        self.quiet = 10.0

    def quiet_for(self) -> float:
        return self.quiet

    async def speak(self, prompt: str) -> bool:
        self.log.append(["speak", prompt])
        return True

    async def instruct(self, text: str) -> bool:
        self.log.append(["instruct", text])
        return True

    async def wait_idle(self, limit_s: float | None = None) -> bool:
        return True

    def touch(self) -> None:
        pass


class NullScreen:
    """La pantalla de Unity: aquí no importa lo que recibe."""

    async def broadcast_json(self, msg: dict[str, Any]) -> None:
        pass

    async def set_sticky(self, key: str, msg: dict[str, Any]) -> None:
        pass

    def clear_sticky(self, key: str) -> None:
        pass

    async def hide_image(self) -> None:
        pass


def make_game(
    tmp_path: Path, *, questions: int = 3, threshold: int = 2, **overrides: Any
) -> tuple[TriviaGame, LogHost, list[list[Any]]]:
    bank = tmp_path / "preguntas.md"
    bank.write_text(BANK, encoding="utf-8")
    values: dict[str, Any] = {"reveal_seconds": 0.0, "final_wait_seconds": 0.0, **overrides}
    settings = TriviaSettings(questions=questions, win_threshold=threshold, **values)
    log: list[list[Any]] = []
    host = LogHost(log)
    game = TriviaGame(settings, bank, host=host, screen=NullScreen(), rng=random.Random(7))
    return game, host, log


async def settle() -> None:
    """Deja correr las tareas de la partida (``reveal_seconds`` es 0)."""
    for _ in range(5):
        await asyncio.sleep(0)


def right(game: TriviaGame) -> int:
    question = game._current
    assert question is not None
    return question.correct


def wrong(game: TriviaGame) -> int:
    return (right(game) + 1) % 3


async def call(log: list[list[Any]], name: str, result: Any) -> None:
    """Apunta lo que devuelve una llamada de la partida (guion o texto para el equipo)."""
    if isinstance(result, tuple):
        log.append([name, *result])
    else:
        log.append([name, result])


async def flow_wins_with_contact(tmp_path: Path) -> list[list[Any]]:
    game, _, log = make_game(tmp_path)
    await call(log, "start", await game.start("voice", "fácil"))
    await call(log, "answer", await game.answer(right(game), "voice"))
    await call(log, "next", await game.next("voice"))
    await call(log, "answer", await game.answer(wrong(game), "voice"))
    await call(log, "next", await game.next("voice"))
    await call(log, "answer", await game.answer(right(game), "voice"))
    # Contestada la última y antes de la pantalla final.
    await call(log, "resume", await game.resume())
    await call(log, "answer", await game.answer(0, "voice"))
    await call(log, "next", await game.next("voice"))
    await settle()
    await call(log, "resume", await game.resume())
    return log


async def flow_loses(tmp_path: Path) -> list[list[Any]]:
    game, _, log = make_game(tmp_path)
    await call(log, "start", await game.start("voice"))
    await call(log, "next", await game.next("voice"))
    await call(log, "answer", await game.answer(PASS, "voice"))
    await call(log, "answer", await game.answer(0, "voice"))
    await call(log, "resume", await game.resume())
    await call(log, "next", await game.next("voice"))
    await call(log, "resume", await game.resume())
    await call(log, "answer", await game.answer(wrong(game), "voice"))
    await call(log, "next", await game.next("voice"))
    await call(log, "answer", await game.answer(right(game), "voice"))
    await settle()
    return log


async def flow_wins_without_contact(tmp_path: Path) -> list[list[Any]]:
    game, _, log = make_game(tmp_path, questions=1, threshold=1, win_contact="")
    await call(log, "start", await game.start("voice", "difícil"))
    await call(log, "answer", await game.answer(right(game), "voice"))
    await settle()
    return log


async def flow_follow_sonnet_code(tmp_path: Path) -> list[list[Any]]:
    game, _, log = make_game(tmp_path)
    await call(log, "start", await game.start("voice", "fácil", ask_follow=True))
    # Otro nivel antes de contestar, con la pantalla aún retenida.
    await call(log, "restart", await game.restart("voice", "difícil"))
    await call(log, "resume", await game.resume())
    await call(log, "restart", await game.restart("voice", "intermedio"))
    await call(log, "answer", await game.answer(right(game), "voice"))
    # Ya contestada una: reiniciar es una partida nueva desde cero.
    await call(log, "restart", await game.restart("voice"))
    await call(log, "stop", await game.stop("voice"))
    await call(log, "resume", await game.resume())
    return log


async def flow_panel(tmp_path: Path) -> list[list[Any]]:
    game, _, log = make_game(tmp_path)
    await call(log, "start", await game.start("panel", "fácil"))
    await settle()
    await call(log, "restart", await game.restart("panel", "difícil"))
    await settle()
    await call(log, "answer", await game.answer(wrong(game), "panel"))
    await call(log, "next", await game.next("panel"))
    await settle()
    await call(log, "answer", await game.answer(PASS, "panel"))
    await call(log, "restart", await game.restart("panel"))
    await settle()
    await call(log, "stop", await game.stop("panel"))
    return log


async def flow_ticks(tmp_path: Path) -> list[list[Any]]:
    game, host, log = make_game(tmp_path, remind_seconds=20.0, abandon_seconds=60.0)
    await call(log, "start", await game.start("voice"))
    host.quiet = 1000.0
    start = game._asked_at
    await game.tick(start + 21)  # recuerda la pregunta
    await settle()
    game.on_user_turn_end(start + 22, start + 21)  # habló y no se delegó nada
    await game.tick(start + 22 + NUDGE_S + 1)
    await settle()
    await game.tick(start + 70)  # se fue: partida abandonada
    await settle()
    return log


async def flow_actions(tmp_path: Path) -> list[list[Any]]:
    """Lo que recibe el backend como resultado de cada acción (con ``PARA SONIA:``)."""
    game, _, log = make_game(tmp_path)
    registry = build_default_registry(include_look=False, include_trivia=True)
    ctx = ActionContext(camera=None, avatar=None, gallery_dir="", extra={"trivia": game})

    async def run(name: str, arguments: dict[str, Any]) -> None:
        result = await registry.execute(name, arguments, ctx)
        log.append([name, result.text])

    await run("start_trivia", {"nivel": "sin_elegir"})
    await run("start_trivia", {"nivel": "sin_elegir", "sigue_a_sonnet_code": True})
    await run("trivia_answer", {"option": "ABC"[right(game)]})
    await run("trivia_next", {})
    await run("trivia_answer", {"option": "no_lo_sabe"})
    await run("restart_trivia", {"nivel": "difícil"})
    await run("stop_trivia", {})
    await run("start_trivia", {"nivel": "fácil", "sigue_a_sonnet_code": True})
    await run("trivia_answer", {"option": "ABC"[wrong(game)]})
    await run("stop_trivia", {})
    await settle()
    return log


async def all_flows(tmp_path: Path) -> dict[str, list[list[Any]]]:
    flows = {
        "gana_con_contacto": flow_wins_with_contact,
        "pierde": flow_loses,
        "gana_sin_contacto": flow_wins_without_contact,
        "sigue_a_sonnet_code": flow_follow_sonnet_code,
        "panel": flow_panel,
        "ciclo": flow_ticks,
        "acciones": flow_actions,
    }
    out: dict[str, list[list[Any]]] = {}
    for name, flow in flows.items():
        folder = tmp_path / name
        folder.mkdir()
        out[name] = await flow(folder)
    return out


async def test_con_los_textos_de_la_app_gpt_live_recibe_lo_mismo_que_antes(
    tmp_path: Path,
) -> None:
    assert_snapshot("prompts_trivia", await all_flows(tmp_path))
