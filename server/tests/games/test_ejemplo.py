"""Plantilla para los tests de un juego (cópiala a ``tests/games/test_<juego>.py``).

Usa un juego de ejemplo de mentira, «Adivina el lenguaje», con todo lo que tiene un
juego de verdad: un banco editable, sus reglas por ``instruct``, una jugada delegada
creada con ``game_action``, su pantalla y el final con ``finish``. Se prueba de dos
formas:

1. **El juego suelto** con :class:`FakeGameHost`: lo que dice, lo que manda a Unity y
   cómo termina. Rápido y sin manager.
2. **De punta a punta** con :func:`make_manager`: las acciones ``start_game``, la
   jugada y ``stop_game`` como las delega GPT-Live (``ctx.extra["games"]``), los
   mensajes ``game`` con su ``seq`` y el ``end``.

Nada llama a APIs reales ni usa la cámara: todo es falso.
"""

from __future__ import annotations

from typing import Any, ClassVar

from sonia.actions import build_default_registry
from sonia.actions.games import game_action
from sonia.games import NOT_SAID, SCRIPT_PREFIX, BankParse, Game, GameBank, GameError
from sonia.games.banks import markdown_sections
from sonia.types import ActionContext, ActionSpec
from sonia.ws import protocol as p
from tests.games.fakes import make_game, make_manager, settle

# ---------------------------------------------------------------------------
# El juego de ejemplo (en un juego de verdad, en ``sonia/games/<juego>/``)
# ---------------------------------------------------------------------------


def parse_languages(text: str) -> BankParse[tuple[str, str]]:
    """``## Lenguaje`` y una línea ``> pista`` debajo. Lo que no encaja, aviso y fuera."""
    entries: list[tuple[str, str]] = []
    warnings: list[str] = []
    for heading, lines in markdown_sections(text):
        hints = [line[1:].strip() for line in lines if line.startswith(">")]
        if not heading or not hints:
            warnings.append(f"«{heading}» no tiene pista (> pista)")
            continue
        entries.append((heading, hints[0]))
    return BankParse(entries, warnings)


LANGUAGES = GameBank(
    id="adivina_lenguajes",
    title="Lenguajes de «Adivina el lenguaje»",
    file="lenguajes.md",
    parse=parse_languages,
    min_entries=2,
)

BANK = """\
<!-- Formato: ## Lenguaje y debajo > una pista. -->
## Kotlin
> El favorito de Android.

## Python
> Se llama así por unos cómicos ingleses.

## Sin pista
"""

RULES = (
    "JUEGO EN MARCHA: adivina el lenguaje. Tienes una pista en pantalla. Cuando el visitante "
    "diga un lenguaje, delega «adivina: responde» con lo que dijo. No sabes la respuesta."
)


class AdivinaGame(Game):
    id: ClassVar[str] = "adivina"
    title: ClassVar[str] = "Adivina el lenguaje"
    spoken: ClassVar[str] = "adivina el lenguaje"
    settings_key: ClassVar[str] = "akinator"  # un bloque cualquiera de Settings.games

    answer = ""
    tries = 0

    @classmethod
    def banks(cls) -> list[GameBank[Any]]:
        return [LANGUAGES]

    @classmethod
    def actions(cls) -> list[ActionSpec]:
        return [
            game_action(
                cls,
                name="adivina_guess",
                description="Registra el lenguaje que dice el visitante en «adivina el lenguaje».",
                parameters={
                    "type": "object",
                    "properties": {
                        "lenguaje": {"type": "string", "description": "Lo que dijo."},
                        "seguro": {
                            "type": "string",
                            "enum": ["si", "no", NOT_SAID],
                            "description": f"Si lo dijo seguro, o {NOT_SAID}.",
                        },
                    },
                    "required": ["lenguaje", "seguro"],
                },
                play=AdivinaGame.guess,
            )
        ]

    def phrases(self) -> list[str]:
        return ["¡Adivina, adivinanza!"]

    async def start(self, source: str, options: dict[str, Any]) -> str:
        languages = await self.host.load_bank(LANGUAGES)
        if not languages:
            raise GameError("No hay lenguajes en el banco.")
        self.answer, hint = self.host.rng.choice(languages)
        self.tries = 0
        await self.host.send("start", {"hint": hint})
        await self.host.instruct(RULES)
        await self.host.say_fixed("¡Adivina, adivinanza!")
        return f"Lee la pista: «{hint}» y pregunta qué lenguaje es."

    async def guess(self, arguments: dict[str, Any]) -> str:
        said = str(arguments["lenguaje"]).strip()
        self.tries += 1
        if said.lower() == self.answer.lower():
            await self.host.send("solved", {"answer": self.answer})
            await self.host.finish("win", {"answer": self.answer})
            return f"¡Acertó, era {self.answer}! Celébralo."
        if self.tries >= 2:
            await self.host.finish("lose", {"answer": self.answer})
            return f"Falló otra vez: era {self.answer}. Díselo con cariño."
        await self.host.send("miss", {"said": said}, sticky=False)
        return "No es ese. Anímale a probar otra vez."

    def snapshot(self) -> dict[str, Any]:
        return {"tries": self.tries}


# ---------------------------------------------------------------------------
# 1. El juego suelto, con FakeGameHost
# ---------------------------------------------------------------------------


async def test_el_juego_empieza_con_su_pista_y_sus_reglas() -> None:
    game, host = make_game(AdivinaGame, cloud_banks={LANGUAGES.id: BANK})
    script = await game.start("voice", {})
    assert game.answer in ("Kotlin", "Python")
    assert host.last("start")["hint"] in script
    # Las reglas van por instruct (FakeGameHost comprueba el tope y las marcas).
    assert host.instructions == [RULES]
    # La frase fija sale grabada si está en la caché (aquí no lo está).
    assert host.fixed == [("¡Adivina, adivinanza!", False)]


async def test_acertar_termina_con_victoria() -> None:
    game, host = make_game(AdivinaGame, cloud_banks={LANGUAGES.id: BANK}, seed=3)
    await game.start("voice", {})
    script = await game.guess({"lenguaje": game.answer, "seguro": "si"})
    assert "Acertó" in script
    assert host.finished == [("win", {"answer": game.answer})]


async def test_dos_fallos_terminan_con_derrota() -> None:
    game, host = make_game(AdivinaGame, cloud_banks={LANGUAGES.id: BANK})
    await game.start("voice", {})
    await game.guess({"lenguaje": "Cobol", "seguro": NOT_SAID})
    assert host.events("miss") == [{"said": "Cobol"}]
    await game.guess({"lenguaje": "Fortran", "seguro": "no"})
    assert host.finished[0][0] == "lose"


def test_el_banco_salta_lo_mal_formado() -> None:
    parsed = parse_languages(BANK)
    assert [name for name, _ in parsed.entries] == ["Kotlin", "Python"]
    assert len(parsed.warnings) == 1


# ---------------------------------------------------------------------------
# 2. De punta a punta, con GameManager y las acciones que delega GPT-Live
# ---------------------------------------------------------------------------


async def test_partida_entera_por_voz() -> None:
    manager, engine, screen, _ = await make_manager([AdivinaGame])
    manager.use_cloud_banks({LANGUAGES.id: BANK})
    registry = build_default_registry(include_look=False, games=[AdivinaGame])
    ctx = ActionContext(camera=None, avatar=None, gallery_dir="", extra={"games": manager})

    result = await registry.execute(
        "start_game", {"juego": "adivina", "sigue_a_sonnet_code": True}, ctx
    )
    assert result.text.startswith(SCRIPT_PREFIX)
    assert manager.active and manager.phase == "playing"
    # «start» va el primero, con el título, y queda fijo para una Unity que se reconecte.
    first = screen.game_msgs()[0]
    assert first["event"] == "start" and first["data"]["title"] == "Adivina el lenguaje"
    assert screen.replay()[0] == first

    game = manager.current
    assert isinstance(game, AdivinaGame)
    result = await registry.execute("adivina_guess", {"lenguaje": game.answer, "seguro": "si"}, ctx)
    assert "Acertó" in result.text
    await settle()
    # El final: «end» con el resultado, fuera los fijos y vuelta a conversar.
    end = screen.game_msgs("end")[-1]
    assert end["data"] == {"answer": game.answer, "result": "win"}
    assert not manager.active and screen.replay() == []
    assert "vuelve a conversar con normalidad" in engine.instructions[-1]
    # Los seq suben en cada mensaje.
    seqs = [m["seq"] for m in screen.game_msgs()]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)


async def test_stop_game_cancela_la_partida() -> None:
    manager, _, screen, _ = await make_manager([AdivinaGame])
    manager.use_cloud_banks({LANGUAGES.id: BANK})
    registry = build_default_registry(include_look=False, games=[AdivinaGame])
    ctx = ActionContext(camera=None, avatar=None, gallery_dir="", extra={"games": manager})
    await registry.execute("start_game", {"juego": "adivina", "sigue_a_sonnet_code": True}, ctx)
    result = await registry.execute("stop_game", {}, ctx)
    assert "terminado" in result.text
    assert screen.game_msgs("end")[-1]["data"]["result"] == "cancel"
    # Una jugada sin partida no llega al juego.
    result = await registry.execute("adivina_guess", {"lenguaje": "Kotlin", "seguro": "si"}, ctx)
    assert "No hay ninguna partida" in result.text


async def test_sin_juego_elegido_pregunta_a_cual() -> None:
    manager, _, _, _ = await make_manager([AdivinaGame])
    manager.use_cloud_banks({LANGUAGES.id: BANK})
    registry = build_default_registry(include_look=False, games=[AdivinaGame])
    ctx = ActionContext(camera=None, avatar=None, gallery_dir="", extra={"games": manager})
    result = await registry.execute("start_game", {"juego": NOT_SAID}, ctx)
    assert "adivina el lenguaje" in result.text and not manager.active


def test_la_pantalla_es_el_sobre_comun() -> None:
    msg = p.msg_game("adivina", "solved", 7, {"answer": "Kotlin"})
    assert msg == {
        "type": "game",
        "game": "adivina",
        "event": "solved",
        "seq": 7,
        "data": {"answer": "Kotlin"},
    }
