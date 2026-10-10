"""Los textos de la ruleta para GPT-Live, editables desde la nube (``sonia.prompts``).

1. Instantánea: con los textos de la app, todo lo que va a GPT-Live (reglas, avisos,
   guiones de las jugadas, empujones y reconducciones) es idéntico, byte a byte, a lo que
   salía antes de hacerlos editables (``snapshots/prompts_ruleta.json``). Los bancos son
   fijos, del propio test, para que editar los de la app no cambie la instantánea.
2. Con una versión de la nube se usa esa y no la de la app.

Sin red, sin Unity y sin APIs reales.
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any

from sonia.config import Settings
from sonia.games import GameError
from sonia.games.ruleta import texts as t
from sonia.games.ruleta.banks import RIDDLES, SONNET, TECHS
from sonia.games.ruleta.game import RuletaGame
from sonia.trivia.bank import TriviaQuestion
from tests.games.fakes import FakeGameHost, game_settings, make_game
from tests.prompt_snapshots import assert_snapshot

QUESTIONS = [
    TriviaQuestion(
        "¿Quién organiza el DevFest Santo Domingo?",
        ("Google, directamente", "GDG Santo Domingo", "La Biblioteca Nacional"),
        1,
        "Lo organiza la comunidad, con voluntarios.",
        "fácil",
    ),
    TriviaQuestion(
        "¿Qué lenguaje se ejecuta en el navegador?",
        ("JavaScript", "COBOL", "Fortran"),
        0,
        "",
        "fácil",
    ),
    TriviaQuestion(
        "¿Quién creó a Sonnia?",
        ("Un mago", "Sonnet Code", "Nadie"),
        1,
        "La hizo el equipo de Sonnet Code.",
        "media",
    ),
] * 3

RIDDLE_BANK = "\n\n".join(
    [
        "## Tengo teclas y no soy piano, ¿quién soy?\n- Respuesta: el teclado\n"
        "- También vale: teclado, keyboard\n- Pista: Sirve para escribir.",
        "## Sin mí no hay commit, ¿quién soy?\n- Respuesta: Git\n- Pista: Lo inventó Linus.",
        *(
            f"## Adivinanza número {i} de Sonnia\n- Respuesta: respuesta {i}\n"
            + (f"- También vale: otra {i}, una más {i}\n" if i % 2 else "")
            + f"- Pista: la pista {i}."
            for i in range(10)
        ),
    ]
)

TECH_BANK = "\n\n".join(
    [
        "## La nube\n> Usar servidores de otros por internet.",
        "## Kubernetes\n> Orquesta contenedores.",
        "## Git",
        *(f"## Tecnología {i}" + (f"\n> De qué va la {i}." if i % 2 else "") for i in range(10)),
    ]
)

SONNET_TASKS = "\n".join(
    f"## [reto] Reto de stand número {i}: choca los cinco con {{contacto}} y con Sonnia."
    for i in range(5)
)
SONNET_QUESTIONS = "\n".join(
    f"## [pregunta] ¿Pregunta {i} sobre Sonnet Code?\n- Respuesta: respuesta {i}\n"
    + (f"- También vale: otra {i}" if i % 2 else "")
    for i in range(5)
)

#: Pesos que fuerzan cada casilla.
ONLY = {
    "trivia": "1,0,0,0,0",
    "adivinanza": "0,1,0,0,0",
    "explica": "0,0,1,0,0",
    "futuro": "0,0,0,1,0",
    "sonnet": "0,0,0,0,1",
}


def ruleta_settings(
    weights: str = "1,1,1,1,1", contact: str | None = None, **fields: Any
) -> Settings:
    base = game_settings(result_seconds=0.0, final_wait_seconds=0.0)
    block = base.games.ruleta.model_copy(update={"weights": weights, **fields})
    update: dict[str, Any] = {"games": base.games.model_copy(update={"ruleta": block})}
    if contact is not None:
        update["trivia"] = base.trivia.model_copy(update={"win_contact": contact})
    return base.model_copy(update=update)


def new_game(
    weights: str = "1,1,1,1,1",
    *,
    sonnet: str = SONNET_TASKS,
    contact: str | None = None,
    fields: dict[str, Any] | None = None,
    **kwargs: Any,
) -> tuple[RuletaGame, FakeGameHost]:
    kwargs.setdefault("settings", ruleta_settings(weights, contact, **(fields or {})))
    kwargs.setdefault("trivia_questions", list(QUESTIONS))
    kwargs.setdefault(
        "cloud_banks", {RIDDLES.id: RIDDLE_BANK, TECHS.id: TECH_BANK, SONNET.id: sonnet}
    )
    return make_game(RuletaGame, **kwargs)


class Log:
    """Lo que GPT-Live recibe de la ruleta en una partida, en orden."""

    def __init__(self, game: RuletaGame, host: FakeGameHost) -> None:
        self.game = game
        self.host = host
        self.scripts: list[str] = []

    async def play(self, step: Awaitable[str]) -> None:
        """Una jugada: su guion, o el texto que reconduce si no vale ahora."""
        try:
            self.scripts.append("guion: " + await step)
        except GameError as exc:
            self.scripts.append("error: " + str(exc))

    def nudge(self) -> None:
        self.scripts.append(f"empujón: {self.game.nudge()}")

    async def resume(self) -> None:
        self.scripts.append("seguir: " + await self.game.resume())

    async def stop_wheel(self) -> None:
        """Unity dice que la ruleta paró, y corre el anuncio del reto."""
        spin = self.host.last("spin")
        await self.game.on_unity_event(
            "wheel_stopped", {"spin": spin["spin"], "segment": spin["segment"]}
        )
        await self.host.run_tasks()

    async def announced(self) -> None:
        """Sonia lee el anuncio del reto y calla: desde ahí cuentan los contadores."""
        self.host.quiet = 0.0
        await self.game.tick(self.host.now())
        self.host.quiet = 1.0
        await self.game.tick(self.host.now())

    async def spin(self) -> None:
        await self.play(self.game.spin_again({}))
        await self.stop_wheel()

    def data(self) -> dict[str, Any]:
        return {
            "instructions": list(self.host.instructions),
            "spoken": list(self.host.spoken),
            "fixed": [phrase for phrase, _ in self.host.fixed],
            "scripts": list(self.scripts),
        }


async def start(**kwargs: Any) -> Log:
    game, host = new_game(**kwargs)
    log = Log(game, host)
    log.scripts.append("empezar: " + await game.start("voice", {}))
    return log


async def scenario_start() -> dict[str, Any]:
    log = await start()
    await log.resume()
    log.nudge()
    await log.play(log.game.answer({"respuesta": "A"}))
    await log.play(log.game.score({"nota": 5}))
    await log.play(log.game.spin_again({}))
    return log.data()


async def scenario_start_without_contact() -> dict[str, Any]:
    log = await start(weights="1,1,0,0,0", contact="", fields={"explain_seconds": 12.5})
    await log.stop_wheel()
    return log.data()


async def scenario_one_segment() -> dict[str, Any]:
    log = await start(weights=ONLY["futuro"])
    return log.data()


async def scenario_trivia() -> dict[str, Any]:
    log = await start(weights=ONLY["trivia"])
    await log.stop_wheel()
    await log.play(log.game.answer({"respuesta": "no_lo_dijo"}))
    await log.play(log.game.answer({"respuesta": "acierto"}))
    await log.play(log.game.score({"nota": 5}))
    await log.resume()
    log.nudge()
    # El contador acaba sin respuesta: el recordatorio.
    await log.announced()
    host = log.host
    host.quiet = 2.0
    await log.game.tick(host.now() + 25.0)
    await host.run_tasks()
    await log.play(log.game.answer({"respuesta": "B"}))
    log.nudge()
    await log.resume()
    await log.play(log.game.answer({"respuesta": "B"}))
    await log.spin()
    await log.play(log.game.answer({"respuesta": "B"}))
    await log.spin()
    await log.play(log.game.answer({"respuesta": "se_rinden"}))
    await log.spin()
    await log.play(log.game.answer({"respuesta": "A"}))
    return log.data()


async def scenario_riddle() -> dict[str, Any]:
    log = await start(weights=ONLY["adivinanza"])
    await log.stop_wheel()
    await log.resume()
    log.nudge()
    await log.play(log.game.answer({"respuesta": "A"}))
    await log.play(log.game.answer({"respuesta": "fallo"}))
    await log.play(log.game.answer({"respuesta": "fallo"}))
    await log.play(log.game.answer({"respuesta": "fallo"}))
    await log.spin()
    # La pista sale sola.
    await log.announced()
    await log.game.tick(log.host.now() + 30.0)
    await log.host.run_tasks()
    await log.play(log.game.answer({"respuesta": "acierto"}))
    for _ in range(4):
        await log.spin()
        await log.play(log.game.answer({"respuesta": "se_rinden"}))
    return log.data()


async def scenario_explain() -> dict[str, Any]:
    log = await start(weights=ONLY["explica"], recorded=[t.TIME_PHRASE])
    await log.stop_wheel()
    await log.play(log.game.answer({"respuesta": "acierto"}))
    await log.play(log.game.predict({"prediccion": "algo", "probabilidad": 5}))
    await log.announced()
    host = log.host
    start_at = host.now() + 5.0
    await log.game.tick(start_at)
    await log.game.tick(start_at + 20.0)
    await host.run_tasks()
    log.nudge()
    await log.play(log.game.score({"nota": 8}))
    for note in (42, -3):
        await log.spin()
        await log.play(log.game.score({"nota": note}))
    for _ in range(3):
        await log.spin()
        await log.play(log.game.answer({"respuesta": "se_rinden"}))
    return log.data()


async def scenario_explain_unrecorded() -> dict[str, Any]:
    log = await start(weights=ONLY["explica"], connected=False, fields={"explain_seconds": 12.5})
    await log.stop_wheel()
    host = log.host
    await log.game.tick(host.now() + 21.0)
    await log.game.tick(host.now() + 26.0)
    await log.game.tick(host.now() + 200.0)
    await host.run_tasks()
    return log.data()


async def scenario_future() -> dict[str, Any]:
    log = await start(weights=ONLY["futuro"])
    await log.stop_wheel()
    await log.play(log.game.answer({"respuesta": "acierto"}))
    await log.play(log.game.score({"nota": 3}))
    await log.play(log.game.predict({"prediccion": "  «»  ", "probabilidad": 40}))
    await log.play(
        log.game.predict({"prediccion": "«Sonnia tendrá cuerpo de robot»", "probabilidad": 140})
    )
    await log.spin()
    await log.play(log.game.answer({"respuesta": "se_rinden"}))
    return log.data()


async def scenario_sonnet_tasks() -> dict[str, Any]:
    log = await start(weights=ONLY["sonnet"])
    await log.stop_wheel()
    await log.play(log.game.answer({"respuesta": "C"}))
    await log.play(log.game.answer({"respuesta": "acierto"}))
    await log.spin()
    await log.play(log.game.answer({"respuesta": "fallo"}))
    await log.spin()
    await log.play(log.game.answer({"respuesta": "se_rinden"}))
    return log.data()


async def scenario_sonnet_questions() -> dict[str, Any]:
    log = await start(weights=ONLY["sonnet"], sonnet=SONNET_QUESTIONS)
    await log.stop_wheel()
    await log.play(log.game.answer({"respuesta": "fallo"}))
    await log.play(log.game.answer({"respuesta": "fallo"}))
    for value in ("acierto", "se_rinden", "fallo", "acierto"):
        await log.spin()
        await log.play(log.game.answer({"respuesta": value}))
    return log.data()


async def scenario_three_wins() -> dict[str, Any]:
    log = await start(weights=ONLY["adivinanza"])
    await log.stop_wheel()
    for _ in range(4):
        await log.play(log.game.answer({"respuesta": "acierto"}))
        await log.spin()
    return log.data()


async def scenario_skip() -> dict[str, Any]:
    log = await start(weights="1,1,0,0,0")
    await log.stop_wheel()
    await log.play(log.game.spin_again({}))
    log.nudge()
    await log.resume()
    return log.data()


async def scenario_panel() -> dict[str, Any]:
    log = await start(weights="0,0,1,1,0")
    await log.stop_wheel()
    for _ in range(4):
        round_ = log.game._round
        assert round_ is not None
        control = "predict" if round_.kind == "futuro" else "right"
        await log.play(log.game.panel_control(control, "La IA escribirá todo el código"))
        await log.play(log.game.panel_control("spin", ""))
        await log.stop_wheel()
    return log.data()


SCENARIOS = {
    "arranque": scenario_start,
    "arranque_sin_contacto": scenario_start_without_contact,
    "una_casilla": scenario_one_segment,
    "trivia": scenario_trivia,
    "adivinanza": scenario_riddle,
    "explica": scenario_explain,
    "explica_sin_grabar": scenario_explain_unrecorded,
    "futuro": scenario_future,
    "sonnet_retos": scenario_sonnet_tasks,
    "sonnet_preguntas": scenario_sonnet_questions,
    "tres_superados": scenario_three_wins,
    "saltar": scenario_skip,
    "panel": scenario_panel,
}


async def all_scenarios() -> dict[str, Any]:
    return {name: await scenario() for name, scenario in SCENARIOS.items()}


async def test_con_los_textos_de_la_app_no_cambia_nada() -> None:
    assert_snapshot("prompts_ruleta", await all_scenarios())
