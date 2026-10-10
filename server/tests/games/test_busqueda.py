"""La búsqueda relámpago: el flujo entero con un juez falso guionizado (nunca el modelo de verdad).

Rondas, salida con el «¡Ya!», miradas con su cadencia y su tope, encontrar a la primera, a la
quinta o nunca, el juez sin respuesta, ``busqueda_check`` dentro y fuera de ronda, el final
(ganar, perder y cancelar) y la partida entera de punta a punta con el ``GameManager``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterable
from typing import Any

import pytest

from sonia.actions import build_default_registry
from sonia.config import Settings
from sonia.games import SCRIPT_PREFIX, GameError
from sonia.games.busqueda import game as game_module
from sonia.games.busqueda import texts as t
from sonia.games.busqueda.bank import COLORS, OBJECTS, parse_objects
from sonia.games.busqueda.game import BusquedaGame
from sonia.types import ActionContext
from sonia.vision.contracts import JudgeAnswer
from tests.games.fakes import (
    FakeGameHost,
    FakeJudge,
    FakePreview,
    FakeStream,
    FakeVision,
    game_settings,
    make_game,
    make_manager,
)

SEEN = JudgeAnswer(seen=True, what="botella azul")
MISS = JudgeAnswer(seen=False)


class CountingJudge(FakeJudge):
    """``FakeJudge`` con la cuenta de rondas del juez de verdad (``ModelJudge.start_round``)."""

    def __init__(self, answers: Iterable[JudgeAnswer | None] = ()) -> None:
        super().__init__(answers)
        self.rounds: list[int | None] = []

    def start_round(self, max_calls: int | None) -> None:
        self.rounds.append(max_calls)


class GatedJudge(CountingJudge):
    """Su ``ask`` no contesta hasta que el test abre la puerta (para ver que no se solapan)."""

    def __init__(self, answers: Iterable[JudgeAnswer | None] = ()) -> None:
        super().__init__(answers)
        self.gate = asyncio.Event()
        self.pending = 0
        self.max_pending = 0

    async def ask(self, question: str) -> JudgeAnswer | None:
        self.questions.append(question)
        self.pending += 1
        self.max_pending = max(self.max_pending, self.pending)
        try:
            await self.gate.wait()
            return self.answers.popleft() if self.answers else JudgeAnswer(seen=False)
        finally:
            self.pending -= 1


class RoundJudge(CountingJudge):
    """Ve el objeto solo en las rondas que se le dicen (la 1, la 2...), sea cual sea el número de miradas."""

    def __init__(self, seen_in: Iterable[int]) -> None:
        super().__init__()
        self.seen_in = set(seen_in)

    async def ask(self, question: str) -> JudgeAnswer | None:
        self.questions.append(question)
        return SEEN if len(self.rounds) in self.seen_in else MISS


def settings_with(**busqueda: Any) -> Settings:
    """Ajustes de prueba con otros valores en el bloque ``GAME_BUSQUEDA_*``."""
    base = game_settings()
    block = base.games.busqueda.model_copy(update=busqueda)
    return base.model_copy(update={"games": base.games.model_copy(update={"busqueda": block})})


def new_game(
    *answers: JudgeAnswer | None,
    judge: CountingJudge | None = None,
    seed: int = 1,
    recorded: Iterable[str] = (),
    **busqueda: Any,
) -> tuple[BusquedaGame, FakeGameHost, CountingJudge]:
    used = judge if judge is not None else CountingJudge(answers)
    game, host = make_game(
        BusquedaGame,
        settings=settings_with(**busqueda) if busqueda else None,
        vision=FakeVision(judge=used),
        seed=seed,
        recorded=recorded,
    )
    return game, host, used


async def pump(
    game: BusquedaGame,
    host: FakeGameHost,
    seconds: float,
    step: float = 0.05,
    *,
    wait: bool = True,
) -> None:
    """Deja pasar ``seconds`` del reloj del juego, tick a tick, con sus tareas en segundo plano.

    Con ``wait=False`` no espera a que acaben (un juez con la puerta cerrada no acaba nunca).
    """
    end = host.now() + seconds
    while host.now() < end - 1e-9:
        host.clock.advance(step)
        await game.tick(host.now())
        if wait:
            await host.run_tasks()
        else:
            for _ in range(3):
                await asyncio.sleep(0)


def phase(game: BusquedaGame) -> str:
    return str(game.snapshot()["phase"])


def current(game: BusquedaGame) -> str:
    return str(game.snapshot()["object"])


async def say_the_object(game: BusquedaGame, host: FakeGameHost) -> None:
    """Sonia anuncia el objeto de la ronda y calla: se da la salida."""
    await game.on_assistant_text(f"¡El primero que me enseñe {current(game)}!", False)
    host.quiet = 5.0
    await pump(game, host, 0.1)


async def go(game: BusquedaGame, host: FakeGameHost) -> None:
    """Lleva la ronda hasta que corre el contador."""
    await say_the_object(game, host)
    assert phase(game) == "running"


async def next_round(game: BusquedaGame, host: FakeGameHost) -> None:
    """Sonia cuenta el resultado de la ronda (habla y calla) y sale el anuncio de la siguiente."""
    host.quiet = 0.0  # está hablando
    await pump(game, host, 0.5)
    host.quiet = 5.0  # ya calló
    await pump(game, host, 0.1)
    assert phase(game) == "ready"


async def play_round(
    game: BusquedaGame, host: FakeGameHost, *, found: bool, after: float = 2.6
) -> None:
    """Una ronda entera: la salida y, según el juez, ¡encontrado! o se acaba el tiempo."""
    await go(game, host)
    await pump(game, host, after if found else 26.0)


def sent(host: FakeGameHost, event: str) -> list[dict[str, Any]]:
    return host.events(event)


# ---------------------------------------------------------------------------
# Empezar
# ---------------------------------------------------------------------------


async def test_empieza_con_la_vista_en_vivo_las_reglas_y_la_primera_ronda() -> None:
    game, host, judge = new_game()
    script = await game.start("voice", {})

    # La cámara y la vista en vivo, a nombre del juego y sin nada dibujado encima.
    assert host.stream.owners == {"busqueda"}
    assert host.preview.starts == [("busqueda", True)] and host.preview.overlay is None
    start = host.last("start")
    assert start == {"rounds": 3, "round_seconds": 25.0, "preview": True}
    # La primera ronda ya está en pantalla, lista y sin correr.
    first = host.last("round")
    assert first["index"] == 1 and first["total"] == 3 and first["phase"] == "ready"
    assert first["object"] == current(game) and first["seconds"] == 25.0 and first["found"] == 0
    assert first["color"] == "" or first["color"] in COLORS.values()
    assert [m["event"] for m in host.sent] == ["start", "round"]
    # Las reglas van por instruct (el host falso comprueba el tope y las marcas).
    assert len(host.instructions) == 1 and "busqueda_check" in host.instructions[0]
    assert "3 rondas de 25 segundos" in host.instructions[0]
    # El guion de arranque lleva el objeto y la ronda; la salida la da el sistema.
    assert f"«¡El primero que me enseñe {first['object']}!»" in script
    assert "ronda 1 de 3" in script and "No digas «¡ya!»" in script
    # El juez cuenta las fotos de la ronda con el tope.
    assert judge.rounds == [10]
    assert phase(game) == "ready" and host.fixed == [] and host.spoken == []
    await game.stop("panel")


async def test_los_objetos_de_la_partida_son_distintos_y_no_se_repiten_hasta_agotar_el_banco() -> (
    None
):
    game, host, _ = new_game()
    banco = parse_objects(
        (game_settings().games_dir / "busqueda" / OBJECTS.file).read_text(encoding="utf-8")
    )
    names = {e.name for e in banco.entries}
    full_games = len(names) // 3
    seen: list[str] = []
    for _ in range(full_games):
        await game.start("voice", {})
        objects = list(game.snapshot()["objects"])
        assert len(objects) == 3 and len(set(objects)) == 3
        assert not set(objects) & set(seen), "se repitió un objeto antes de agotar el banco"
        seen.extend(objects)
        await game.stop("finished")
    # La partida siguiente empieza por los que aún no habían salido.
    await game.start("voice", {})
    objects = list(game.snapshot()["objects"])
    assert set(objects) >= names - set(seen)
    assert len(set(objects)) == 3
    await game.stop("finished")


async def test_con_menos_objetos_que_rondas_se_juegan_las_que_hay() -> None:
    bank = "\n\n".join(f"## algo número {n}" for n in "ab")
    game, host = make_game(
        BusquedaGame,
        vision=FakeVision(judge=CountingJudge()),
        cloud_banks={OBJECTS.id: bank},
    )
    # La nube pide 6 como mínimo: con 2 se sigue con el banco de la app (3 rondas).
    await game.start("voice", {})
    assert host.last("start")["rounds"] == 3
    assert game.snapshot()["rounds"] == 3


async def test_sin_camara_no_empieza() -> None:
    game, host = make_game(
        BusquedaGame, vision=FakeVision(stream=FakeStream(available=False), judge=CountingJudge())
    )
    with pytest.raises(GameError, match="cámara"):
        await game.start("voice", {})
    assert host.sent == [] and host.preview.starts == []


async def test_sin_vista_en_vivo_no_empieza_y_suelta_la_camara() -> None:
    game, host = make_game(
        BusquedaGame, vision=FakeVision(preview=FakePreview(available=False), judge=CountingJudge())
    )
    with pytest.raises(GameError, match="vista en vivo|cámara en vivo"):
        await game.start("voice", {})
    assert host.stream.owners == set()
    assert host.sent == [] and host.instructions == []


async def test_con_el_banco_vacio_no_empieza(tmp_path: Any) -> None:
    folder = tmp_path / "games" / "busqueda"
    folder.mkdir(parents=True)
    (folder / "objetos.md").write_text("<!-- vacío -->\n", encoding="utf-8")
    settings = game_settings().model_copy(update={"assets_dir": str(tmp_path)})
    game, host = make_game(BusquedaGame, settings=settings, vision=FakeVision())
    with pytest.raises(GameError, match="banco de objetos"):
        await game.start("voice", {})
    assert host.stream.owners == set() and host.sent == []


def test_los_ajustes_que_no_valen_lo_dicen() -> None:
    for bad in ({"rounds": 0}, {"round_seconds": 0.0}, {"check_seconds": 0.0}, {"max_checks": 0}):
        game, _ = make_game(BusquedaGame, settings=settings_with(**bad))
        reason = game.unavailable_reason()
        assert reason and "ajustes" in reason
    game, _ = make_game(BusquedaGame)
    assert game.unavailable_reason() is None


async def test_las_reglas_caben_con_cualquier_ajuste() -> None:
    game, host, _ = new_game(rounds=99, round_seconds=1000.5)
    await game.start("voice", {})
    assert len(host.instructions[0]) <= 1_200
    assert "1000.5 segundos" in host.instructions[0]


# ---------------------------------------------------------------------------
# La salida, las miradas y su tope
# ---------------------------------------------------------------------------


async def test_da_la_salida_cuando_sonia_termina_de_anunciar() -> None:
    game, host, _ = new_game()
    await game.start("voice", {})
    await pump(game, host, 3.0)  # Sonia aún no ha dicho nada: la ronda espera
    assert phase(game) == "ready" and host.sent[-1]["event"] == "round"
    # Habla de otra cosa (una muletilla): sigue esperando al anuncio del objeto.
    host.quiet = 0.0
    await game.on_assistant_text("Claro, un momento...", False)
    await pump(game, host, 3.0)
    assert phase(game) == "ready"
    # Dice el objeto, pero sigue hablando: todavía no.
    await game.on_assistant_text(f"¡El primero que me enseñe {current(game)}!", False)
    await pump(game, host, 1.0)
    assert phase(game) == "ready"
    # Calla: un segundo después da la salida.
    host.quiet = 0.6
    await pump(game, host, 0.2)
    assert phase(game) == "ready"
    host.quiet = 1.2
    await pump(game, host, 0.1)
    assert phase(game) == "running"
    go_msg = host.last("go")
    assert go_msg["phase"] == "running" and go_msg["index"] == 1 and go_msg["seconds"] == 25.0
    # El «¡Ya!» es la frase grabada con el tiempo exacto (aquí no está en la caché).
    assert host.fixed == [("¡Ya!", False)]


async def test_el_ya_suena_grabado_si_esta_en_la_cache() -> None:
    game, host, _ = new_game(recorded={"¡Ya!"})
    await game.start("voice", {})
    await go(game, host)
    assert host.fixed == [("¡Ya!", True)]


async def test_si_no_oye_el_anuncio_da_la_salida_al_tope_de_espera() -> None:
    game, host, _ = new_game()
    await game.start("voice", {})
    await pump(game, host, game_module.READY_CAP_FIRST_S - 1.0)
    assert phase(game) == "ready"
    await pump(game, host, 1.5)
    assert phase(game) == "running"


async def test_mira_cada_check_seconds_con_la_pregunta_del_objeto() -> None:
    game, host, judge = new_game(*[MISS] * 12)
    await game.start("voice", {})
    await go(game, host)
    await pump(game, host, 2.3)
    assert judge.questions == []  # la primera es a los 2,5 s de la salida
    await pump(game, host, 0.3)
    assert len(judge.questions) == 1
    await pump(game, host, 2.4)
    assert len(judge.questions) == 1
    await pump(game, host, 0.2)
    assert len(judge.questions) == 2
    entry = {
        e.name: e
        for e in parse_objects(
            host.settings.games_dir.joinpath("busqueda", OBJECTS.file).read_text(encoding="utf-8")
        ).entries
    }[current(game)]
    assert set(judge.questions) == {entry.question}
    assert "?" in judge.questions[0] and "personas" not in judge.questions[0].lower()
    # Cada foto avisa a la pantalla (el barrido de «mirando») sin quedarse fija.
    checks = [m for m in host.sent if m["event"] == "checking"]
    assert [m["data"] for m in checks] == [{"n": 1, "max": 10}, {"n": 2, "max": 10}]
    assert not any(m["sticky"] for m in checks)


async def test_las_miradas_no_se_solapan_si_una_tarda() -> None:
    judge = GatedJudge([MISS, SEEN])
    game, host, _ = new_game(judge=judge)
    await game.start("voice", {})
    await go(game, host)
    await pump(game, host, 12.0, wait=False)  # la puerta cerrada: la primera sigue en el aire
    assert len(judge.questions) == 1 and judge.max_pending == 1
    judge.gate.set()
    await pump(game, host, 0.3)
    # Contestó: la segunda sale enseguida (ya le tocaba) y es la que ve el objeto.
    assert len(judge.questions) == 2 and judge.max_pending == 1
    assert phase(game) == "between"
    assert sent(host, "found")


async def test_el_tope_de_fotos_por_ronda_se_respeta() -> None:
    game, host, judge = new_game(*[MISS] * 30, max_checks=4)
    await game.start("voice", {})
    await go(game, host)
    await pump(game, host, 26.0)
    assert len(judge.questions) == 4
    assert phase(game) == "between" and sent(host, "timeout")
    assert judge.rounds == [4]


async def test_con_el_tope_justo_las_miradas_se_reparten_por_toda_la_ronda() -> None:
    game, host, judge = new_game(*[MISS] * 30, max_checks=4)
    await game.start("voice", {})
    await go(game, host)
    looks: list[float] = []
    started = host.now()
    seen = 0
    for _ in range(520):  # 26 s a ticks de 0,05
        host.clock.advance(0.05)
        await game.tick(host.now())
        await host.run_tasks()
        if len(judge.questions) > seen:
            seen = len(judge.questions)
            looks.append(round(host.now() - started, 1))
    # 4 fotos: la primera a los 2,5 s y las otras tres repartidas hasta el final (no seguidas).
    assert len(looks) == 4 and looks[0] == pytest.approx(2.5, abs=0.2)
    gaps = [b - a for a, b in zip(looks, looks[1:], strict=False)]
    assert all(5.0 <= gap <= 6.2 for gap in gaps), looks
    assert looks[-1] > 18.0, "la última mirada tiene que caer hacia el final de la ronda"


async def test_las_miradas_manuales_no_dejan_sin_mirar_el_final_de_la_ronda() -> None:
    game, host, judge = new_game(*[MISS] * 40)
    await game.start("voice", {})
    await go(game, host)
    # Alguien grita «¡aquí!» una y otra vez al principio de la ronda: cinco miradas manuales.
    for _ in range(5):
        await pump(game, host, 1.0)
        assert "no se ve todavía" in await game.check({})
    used = game.snapshot()["checks"]
    assert used >= 5
    # Las miradas que quedan se reparten por el resto de la ronda, no se gastan seguidas.
    started = len(judge.questions)
    await pump(game, host, 26.0)
    later = len(judge.questions) - started
    assert 0 < later <= 10 - used + 1
    assert game.snapshot()["checks"] <= 10
    assert sent(host, "timeout")


async def test_una_ronda_entera_hace_nueve_o_diez_miradas_como_mucho() -> None:
    game, host, judge = new_game(*[MISS] * 30)
    await game.start("voice", {})
    await go(game, host)
    await pump(game, host, 26.0)
    assert 9 <= len(judge.questions) <= 10


# ---------------------------------------------------------------------------
# Encontrarlo
# ---------------------------------------------------------------------------


async def test_lo_encuentra_a_la_primera() -> None:
    game, host, judge = new_game(SEEN, recorded={"¡Lo veo!"})
    await game.start("voice", {})
    await go(game, host)
    await pump(game, host, 2.7)
    assert phase(game) == "between"
    found = host.last("found")
    assert found["index"] == 1 and found["phase"] == "found" and found["found"] == 1
    assert found["what"] == "botella azul" and found["object"] == current(game)
    # El sonido inmediato y la ronda contada, sin repetir el «¡Lo veo!».
    assert ("¡Lo veo!", True) in host.fixed
    assert "En la cámara se ve «botella azul»" in host.spoken[-1]
    assert "no lo repitas" in host.spoken[-1] and "nunca de la persona" in host.spoken[-1]
    assert host.spoken[-1].endswith(t.NEXT_TEXT)
    assert host.touches >= 1  # hay gente jugando: la partida no se da por abandonada
    assert len(judge.questions) == 1
    # El resultado es fijo (se repite si Unity se reconecta) y el «mirando» no.
    sticky = [m for m in host.sent if m["event"] in ("found", "round", "go")]
    assert all(m["sticky"] for m in sticky)


async def test_tras_celebrar_sale_la_siguiente_ronda_cuando_sonia_calla() -> None:
    game, host, judge = new_game(SEEN)
    await game.start("voice", {})
    await go(game, host)
    first = current(game)
    await pump(game, host, 2.7)
    assert phase(game) == "between"
    # Mientras Sonia cuenta la ronda no empieza otra.
    host.quiet = 0.0
    await pump(game, host, 3.0)
    assert phase(game) == "between" and len(sent(host, "round")) == 1
    host.quiet = 0.5
    await pump(game, host, 0.3)
    assert phase(game) == "between"
    host.quiet = 1.5
    await pump(game, host, 0.1)
    assert phase(game) == "ready"
    second = host.last("round")
    assert second["index"] == 2 and second["found"] == 1 and second["phase"] == "ready"
    assert second["object"] != first
    assert "ronda 2 de 3" in host.spoken[-1] and second["object"] in host.spoken[-1]
    assert "No digas «¡ya!»" in host.spoken[-1]
    assert judge.rounds == [10, 10]


async def test_lo_encuentra_a_la_quinta() -> None:
    game, host, judge = new_game(MISS, MISS, MISS, MISS, SEEN)
    await game.start("voice", {})
    await go(game, host)
    await pump(game, host, 12.7)
    assert phase(game) == "between" and len(judge.questions) == 5
    assert host.last("found")["found"] == 1


async def test_lo_que_dice_el_modelo_de_la_foto_no_cuela_a_la_persona() -> None:
    answer = JudgeAnswer(seen=True, what="una mujer con camisa azul sosteniendo una botella")
    game, host, _ = new_game(answer)
    await game.start("voice", {})
    await go(game, host)
    name = current(game)
    await pump(game, host, 2.7)
    # Va el objeto que se pidió, nunca lo que dijo el modelo.
    assert host.last("found")["what"] == name
    assert "mujer" not in host.spoken[-1] and "camisa" not in host.spoken[-1]
    assert f"«{name}»" in host.spoken[-1]


async def test_si_se_acaba_el_tiempo_sonia_lo_dice_y_pasa_a_la_siguiente() -> None:
    game, host, judge = new_game(*[MISS] * 20, recorded={"¡Tiempo!"})
    await game.start("voice", {})
    await go(game, host)
    name = current(game)
    await pump(game, host, 24.9)
    assert phase(game) == "running"
    await pump(game, host, 0.3)
    assert phase(game) == "between"
    timeout = host.last("timeout")
    assert timeout["phase"] == "timeout" and timeout["found"] == 0 and timeout["silent"] is False
    assert ("¡Tiempo!", True) in host.fixed
    assert f"nadie enseñó {name}" in host.spoken[-1] and "no lo repitas" in host.spoken[-1]
    await next_round(game, host)
    assert host.last("round")["index"] == 2


async def test_una_foto_en_el_aire_al_acabar_el_tiempo_aun_puede_salvar_la_ronda() -> None:
    judge = GatedJudge([SEEN])
    game, host, _ = new_game(judge=judge, check_seconds=24.0)
    await game.start("voice", {})
    await go(game, host)
    await pump(game, host, 24.3, wait=False)  # sale la mirada de los 24 s y espera al modelo
    assert len(judge.questions) == 1 and phase(game) == "running"
    await pump(game, host, 2.0, wait=False)  # pasó el tiempo, pero la foto sigue en el aire
    assert phase(game) == "running"
    judge.gate.set()
    await pump(game, host, 0.2)
    assert phase(game) == "between" and sent(host, "found") and not sent(host, "timeout")


async def test_una_foto_que_no_llega_nunca_no_frena_el_fin_de_la_ronda() -> None:
    judge = GatedJudge()
    game, host, _ = new_game(judge=judge)
    await game.start("voice", {})
    await go(game, host)
    await pump(game, host, 25.0 + game_module.GRACE_S + 0.5, wait=False)
    for _ in range(10):
        await asyncio.sleep(0)
    assert phase(game) == "between" and sent(host, "timeout")
    # Si el modelo contesta tarde con «lo veo», la ronda ya terminó: no se gana otra vez.
    judge.answers.append(SEEN)
    judge.gate.set()
    await pump(game, host, 0.3)
    assert not sent(host, "found") and game.snapshot()["found"] == 0


# ---------------------------------------------------------------------------
# El juez sin respuesta
# ---------------------------------------------------------------------------


async def test_el_juez_sin_respuesta_no_tira_el_juego_y_el_aviso_es_distinto() -> None:
    game, host, judge = new_game(*[None] * 30)
    await game.start("voice", {})
    await go(game, host)
    await pump(game, host, 26.0)
    assert phase(game) == "between"
    timeout = host.last("timeout")
    assert timeout["silent"] is True
    # No se dice «nadie lo enseñó»: la cámara no contestó.
    assert host.spoken[-1].startswith("BÚSQUEDA: se acabó el tiempo, pero esta ronda no he")
    assert "nadie enseñó" not in host.spoken[-1]
    assert len(judge.questions) >= 9


async def test_si_la_camara_no_contesta_en_dos_rondas_se_cancela_el_juego() -> None:
    game, host, _ = new_game(*[None] * 60)
    await game.start("voice", {})
    await go(game, host)
    await pump(game, host, 26.0)
    assert phase(game) == "between" and host.finished == []
    await next_round(game, host)
    await go(game, host)
    await pump(game, host, 26.0)
    assert phase(game) == "done"
    assert [r for r, _ in host.finished] == ["cancel"]
    assert host.spoken[-1] == t.CANCEL_TEXT
    # Sin tercera ronda.
    assert len(sent(host, "round")) == 2


async def test_una_ronda_muda_seguida_de_una_con_respuesta_no_cancela() -> None:
    game, host, _ = new_game(*[None] * 12, *[MISS] * 12)
    await game.start("voice", {})
    await go(game, host)
    await pump(game, host, 26.0)
    await next_round(game, host)
    await go(game, host)
    await pump(game, host, 26.0)  # esta vez la cámara contestó (no vio nada)
    assert phase(game) == "between" and host.finished == []
    assert host.last("timeout")["silent"] is False


# ---------------------------------------------------------------------------
# busqueda_check
# ---------------------------------------------------------------------------


async def test_busqueda_check_antes_de_la_salida_pide_esperar() -> None:
    game, host, judge = new_game(SEEN)
    await game.start("voice", {})
    assert await game.check({}) == t.NOT_STARTED_TEXT
    assert judge.questions == []


async def test_busqueda_check_si_no_se_ve_dice_que_lo_acerque() -> None:
    game, host, judge = new_game(MISS)
    await game.start("voice", {})
    await go(game, host)
    await pump(game, host, 1.0)
    script = await game.check({})
    assert f"Con la cámara no se ve todavía {current(game)}" in script
    assert "quedan unos 24 segundos" in script and "No digas que lo ves" in script
    assert len(judge.questions) == 1 and phase(game) == "running"
    # La mirada manual cuenta contra el tope y retrasa la siguiente del reloj.
    assert game.snapshot()["checks"] == 1
    await pump(game, host, 2.3)
    assert len(judge.questions) == 1
    await pump(game, host, 0.4)
    assert len(judge.questions) == 2


async def test_busqueda_check_si_la_camara_no_contesta_lo_dice() -> None:
    game, host, _ = new_game(None)
    await game.start("voice", {})
    await go(game, host)
    assert await game.check({}) == t.NO_ANSWER_TEXT
    assert phase(game) == "running"


async def test_busqueda_check_si_se_ve_celebra_y_devuelve_el_guion() -> None:
    game, host, _ = new_game(SEEN, recorded={"¡Lo veo!"})
    await game.start("voice", {})
    await go(game, host)
    name = current(game)
    script = await game.check({})
    assert "En la cámara se ve «botella azul»" in script and script.endswith(t.NEXT_TEXT)
    assert phase(game) == "between"
    found = host.last("found")
    assert found["what"] == "botella azul" and found["object"] == name
    assert host.fixed == [("¡Ya!", False), ("¡Lo veo!", True)]
    # El guion vuelve como resultado de la acción: el sistema no habla encima.
    assert host.spoken == []
    # Y Sonia tarda en empezar a contarlo: la siguiente ronda espera su reacción.
    await pump(game, host, 5.0)
    assert phase(game) == "between"
    host.quiet = 0.0
    await pump(game, host, 2.0)
    host.quiet = 3.0
    await pump(game, host, 0.2)
    assert phase(game) == "ready" and host.last("round")["index"] == 2


async def test_busqueda_check_respeta_el_tope_de_la_ronda() -> None:
    game, host, judge = new_game(MISS, MISS, max_checks=2)
    await game.start("voice", {})
    await go(game, host)
    assert "no se ve todavía" in await game.check({})
    assert "no se ve todavía" in await game.check({})
    assert await game.check({}) == t.NO_MORE_TEXT
    assert len(judge.questions) == 2
    await pump(game, host, 6.0)
    assert len(judge.questions) == 2  # el reloj tampoco pasa del tope


async def test_busqueda_check_con_la_ronda_ya_contada_no_repite_nada() -> None:
    game, host, _ = new_game(SEEN)
    await game.start("voice", {})
    await go(game, host)
    await pump(game, host, 2.7)
    assert phase(game) == "between"
    assert await game.check({}) == t.ALREADY_TEXT
    assert len(sent(host, "found")) == 1


async def test_busqueda_check_sin_partida_en_marcha_dice_que_no_hay() -> None:
    manager, _, _, _ = await make_manager([BusquedaGame], vision=FakeVision(judge=CountingJudge()))
    registry = build_default_registry(include_look=False, games=[BusquedaGame])
    ctx = ActionContext(camera=None, avatar=None, gallery_dir="", extra={"games": manager})
    result = await registry.execute("busqueda_check", {}, ctx)
    assert "No hay ninguna partida" in result.text and "la búsqueda relámpago" in result.text


async def test_busqueda_check_espera_a_una_mirada_en_el_aire_y_no_se_repite() -> None:
    judge = GatedJudge([SEEN])
    game, host, _ = new_game(judge=judge)
    await game.start("voice", {})
    await go(game, host)
    await pump(game, host, 2.6, wait=False)  # sale la mirada del reloj y espera al modelo
    assert len(judge.questions) == 1
    manual = asyncio.create_task(game.check({}))
    await asyncio.sleep(0)
    assert not manual.done()
    judge.gate.set()
    script = await manual
    await host.run_tasks()
    # La del reloj lo vio: esa es la que lo cuenta; la delegación no repite nada.
    assert script == t.ALREADY_TEXT
    assert len(sent(host, "found")) == 1 and len(judge.questions) == 1
    assert game.snapshot()["found"] == 1 and "botella azul" in host.spoken[-1]


async def test_busqueda_check_no_se_queda_colgada_si_la_mirada_del_reloj_tarda(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(game_module, "MANUAL_JOIN_S", 0.05)
    judge = GatedJudge()
    game, host, _ = new_game(judge=judge)
    await game.start("voice", {})
    await go(game, host)
    await pump(game, host, 2.6, wait=False)
    assert await game.check({}) == t.STILL_LOOKING_TEXT
    judge.gate.set()
    await pump(game, host, 0.2)


async def test_una_ronda_la_gana_una_sola_vez_aunque_dos_miradas_la_vean() -> None:
    game, host, _ = new_game(SEEN, SEEN)
    await game.start("voice", {})
    await go(game, host)
    first = await game.check({})
    second = await game.check({})
    assert "se ve «botella azul»" in first and second == t.ALREADY_TEXT
    assert game.snapshot()["found"] == 1 and len(sent(host, "found")) == 1


# ---------------------------------------------------------------------------
# El final
# ---------------------------------------------------------------------------


def game_where(
    *outcomes: bool, **busqueda: Any
) -> tuple[BusquedaGame, FakeGameHost, CountingJudge]:
    """Una partida donde el juez ve el objeto en las rondas con ``True`` y en las demás no."""
    judge = RoundJudge(i + 1 for i, found in enumerate(outcomes) if found)
    return new_game(judge=judge, **busqueda)


async def play_game(game: BusquedaGame, host: FakeGameHost, outcomes: list[bool]) -> None:
    """Juega las rondas: ``True`` la encuentra a la primera mirada y ``False`` agota el tiempo."""
    for index, found in enumerate(outcomes):
        await go(game, host)
        await pump(game, host, 2.7 if found else 26.0)
        if index < len(outcomes) - 1:
            await next_round(game, host)


async def test_gana_si_encuentra_la_mitad_o_mas_y_le_manda_con_el_equipo() -> None:
    game, host, _ = game_where(True, False, True)
    slept: list[float] = []
    real_sleep = host.sleep

    async def spy(seconds: float) -> None:
        slept.append(seconds)
        await real_sleep(seconds)

    host.sleep = spy  # type: ignore[method-assign]
    await game.start("voice", {})
    await play_game(game, host, [True, False, True])
    assert phase(game) == "done"
    result, data = host.finished[0]
    assert result == "win" and data["found"] == 2 and data["total"] == 3
    assert data["photos"] in (11, 12)  # 1 + 9 o 10 + 1
    script = host.spoken[-1]
    assert "han encontrado 2 de 3" in script and t.WON_TEXT in script
    assert "Brian o Mariel" in script and "no prometas ninguno" in script
    assert script.endswith(t.BACK_TO_TALK_TEXT)
    assert t.NEXT_TEXT not in script
    # La vista en vivo se retira un momento después, no antes de ver el final.
    await host.run_tasks()
    assert game_module.FINAL_PREVIEW_S in slept
    assert host.preview.stops == ["busqueda"]
    # Ya no hay más rondas.
    assert len(sent(host, "round")) == 3


async def test_pierde_si_no_llega_a_la_mitad_y_no_hay_contacto() -> None:
    game, host, _ = game_where(True, False, False)
    await game.start("voice", {})
    await play_game(game, host, [True, False, False])
    result, data = host.finished[0]
    assert result == "lose" and data["found"] == 1 and data["total"] == 3
    script = host.spoken[-1]
    assert "han encontrado 1 de 3" in script and t.LOST_TEXT in script
    assert "Brian" not in script and "Mariel" not in script


async def test_las_tres_encontradas_es_un_pleno() -> None:
    game, host, _ = game_where(True, True, True)
    await game.start("voice", {})
    await play_game(game, host, [True, True, True])
    result, data = host.finished[0]
    assert result == "win" and data["found"] == 3
    assert "¡Las 3 de 3!" in host.spoken[-1] and "Brian o Mariel" in host.spoken[-1]


async def test_ninguna_encontrada_pierde_con_animo() -> None:
    game, host, _ = game_where(False, False, False)
    await game.start("voice", {})
    await play_game(game, host, [False, False, False])
    assert host.finished[0][0] == "lose" and host.finished[0][1]["found"] == 0
    assert "han encontrado 0 de 3" in host.spoken[-1]


async def test_la_ultima_ronda_encontrada_por_busqueda_check_cierra_la_partida() -> None:
    game, host, _ = game_where(False, False, True)
    await game.start("voice", {})
    await play_game(game, host, [False, False])
    await next_round(game, host)
    await go(game, host)
    script = await game.check({})  # en la ronda 3 el juez sí lo ve
    assert "han encontrado 1 de 3" in script and script.endswith(t.BACK_TO_TALK_TEXT)
    assert host.finished[0][0] == "lose" and phase(game) == "done"
    assert host.last("found")["found"] == 1


async def test_con_una_sola_ronda() -> None:
    game, host, _ = new_game(SEEN, rounds=1)
    await game.start("voice", {})
    assert host.last("start")["rounds"] == 1
    await go(game, host)
    await pump(game, host, 2.7)
    assert host.finished[0][0] == "win" and "han encontrado 1 de 1" in host.spoken[-1]


# ---------------------------------------------------------------------------
# Parar, el panel, el registro y el coste
# ---------------------------------------------------------------------------


async def test_parar_a_mitad_suelta_la_camara_y_la_vista_en_vivo(
    caplog: pytest.LogCaptureFixture,
) -> None:
    game, host, _ = new_game(MISS)
    with caplog.at_level(logging.INFO, logger="sonia.games.busqueda.game"):
        await game.start("voice", {})
        await go(game, host)
        await pump(game, host, 3.0)
        await game.stop("panel")
    assert phase(game) == "off"
    assert host.stream.owners == set() and host.preview.owners == set()
    assert host.preview.stops == ["busqueda"]
    assert any("Búsqueda terminada (panel)" in r.getMessage() for r in caplog.records)
    # Tras parar, el reloj no hace nada.
    await pump(game, host, 5.0)
    assert [m["event"] for m in host.sent if m["event"] in ("found", "timeout")] == []


async def test_el_coste_queda_en_el_registro_por_ronda_y_por_partida(
    caplog: pytest.LogCaptureFixture,
) -> None:
    game, host, _ = new_game(MISS, MISS, SEEN)
    with caplog.at_level(logging.INFO, logger="sonia.games.busqueda.game"):
        await game.start("voice", {})
        await go(game, host)
        script = await game.check({})  # la primera mirada manual (no se ve)
        assert "no se ve todavía" in script
        await pump(game, host, 5.1)  # y dos del reloj, la segunda lo ve
        await game.stop("panel")
    lines = [r.getMessage() for r in caplog.records]
    round_line = next(line for line in lines if "Búsqueda: ronda 1/3" in line)
    assert "encontrado" in round_line
    assert (
        "3 fotos al modelo de visión (2 periódicas, 1 por busqueda_check; 3 con respuesta)"
        in round_line
    )
    assert any("3 fotos al modelo de visión (3 con respuesta)" in line for line in lines)


async def test_el_estado_del_panel_va_en_tipos_json() -> None:
    game, host, _ = new_game(MISS)
    assert game.snapshot()["phase"] == "off"
    await game.start("voice", {})
    await go(game, host)
    await pump(game, host, 3.0)
    snapshot = game.snapshot()
    assert json.loads(json.dumps(snapshot)) == snapshot
    assert snapshot["phase"] == "running" and snapshot["round"] == 1 and snapshot["rounds"] == 3
    assert snapshot["checks"] == 1 and snapshot["photos"] == 1 and 0 < snapshot["seconds_left"] < 25
    assert len(snapshot["objects"]) == 3 and snapshot["object"] in snapshot["objects"]


async def test_el_resumen_del_panel_cuenta_la_ronda_en_una_linea() -> None:
    game, host, _ = new_game(SEEN)
    assert game.snapshot()["summary"] == ""
    await game.start("voice", {})
    name = current(game)
    assert game.snapshot()["summary"] == f"Ronda 1 de 3: {name} · 0 encontradas"
    await go(game, host)
    await pump(game, host, 2.7)  # la ve
    assert game.snapshot()["summary"] == f"Ronda 1 de 3: {name} · 1 encontrada"
    await game.stop("panel")
    assert game.snapshot()["summary"] == ""


async def test_el_resumen_del_panel_al_terminar() -> None:
    game, host, _ = game_where(True, True, False)
    await game.start("voice", {})
    await play_game(game, host, [True, True, False])
    assert phase(game) == "done"
    assert game.snapshot()["summary"] == "Terminada: 2 encontradas de 3"


async def test_volver_a_pedirlo_con_la_partida_en_marcha_da_la_ronda_de_ahora() -> None:
    game, host, _ = new_game()
    await game.start("voice", {})
    script = await game.resume()
    assert "ronda 1 de 3" in script and current(game) in script
    assert "No hace falta empezarla otra vez" in script


async def test_no_pide_empujones_ni_entiende_al_visitante() -> None:
    game, host, _ = new_game()
    await game.start("voice", {})
    assert game.nudge() is None
    game.on_user_text(host.now())
    game.on_user_turn_end(host.now(), host.now() - 1)
    game.on_delegation(host.now())
    await game.on_unity_event("lo_que_sea", {"x": 1})
    assert host.spoken == [] and host.instructions != []


async def test_lo_que_dice_sonia_fuera_de_la_espera_no_mueve_nada() -> None:
    game, host, _ = new_game(MISS)
    await game.start("voice", {})
    await go(game, host)
    # En plena ronda, nombrar el objeto otra vez no reinicia ni da otra salida.
    await game.on_assistant_text(f"¡{current(game)}!", False)
    await pump(game, host, 1.0)
    assert phase(game) == "running" and len(sent(host, "go")) == 1


def test_las_frases_con_tiempo_exacto_se_graban_con_la_voz_preparada() -> None:
    game, _ = make_game(BusquedaGame)
    assert game.phrases() == ["¡Ya!", "¡Lo veo!", "¡Tiempo!"]


def test_la_jugada_no_lleva_argumentos_y_es_estricta() -> None:
    (spec,) = BusquedaGame.actions()
    assert spec.name == "busqueda_check"
    assert spec.parameters == {"type": "object", "properties": {}, "required": []}
    assert "¡aquí!" in spec.description and "sin esperar" in spec.description


# ---------------------------------------------------------------------------
# De punta a punta, con el GameManager y las acciones que delega GPT-Live
# ---------------------------------------------------------------------------


async def quiesce() -> None:
    """Deja acabar las tareas del juego (algunas pasan por un hilo: la caché de voces)."""
    for _ in range(400):
        pending = [
            task
            for task in asyncio.all_tasks()
            if task.get_name().startswith("sonia-game-") and not task.done()
        ]
        if not pending:
            return
        await asyncio.sleep(0.005)


async def tick_manager(manager: Any, clock: Any, seconds: float, step: float = 0.05) -> None:
    end = clock() + seconds
    while clock() < end - 1e-9:
        clock.advance(step)
        await manager.tick(clock())
        await quiesce()


async def test_partida_entera_por_voz_con_el_manager() -> None:
    judge = RoundJudge([1, 2])  # ve el objeto en las dos primeras rondas y en la tercera no
    settings = game_settings(result_seconds=0.0, final_wait_seconds=0.0, abandon_seconds=10_000.0)
    manager, engine, screen, clock = await make_manager(
        [BusquedaGame],
        settings=settings,
        vision=FakeVision(judge=judge),
        recorded={"¡Ya!", "¡Lo veo!", "¡Tiempo!"},
    )
    registry = build_default_registry(include_look=False, games=[BusquedaGame])
    ctx = ActionContext(camera=None, avatar=None, gallery_dir="", extra={"games": manager})

    assert "game:busqueda" in manager.capabilities()
    result = await registry.execute("start_game", {"juego": "busqueda"}, ctx)
    assert result.text.startswith(SCRIPT_PREFIX) and "ronda 1 de 3" in result.text
    assert manager.active and manager.phase == "playing"
    # `start` va primero, con el título, y queda fijo; la ronda lista, después.
    msgs = screen.game_msgs()
    assert msgs[0]["event"] == "start" and msgs[0]["data"]["title"] == "Búsqueda relámpago"
    assert msgs[1]["event"] == "round" and msgs[1]["data"]["phase"] == "ready"
    assert [m["event"] for m in screen.replay()] == ["start", "round"]
    assert engine.instructions and "busqueda_check" in engine.instructions[0]
    game = manager.current
    assert isinstance(game, BusquedaGame)

    async def sonia_says_the_object() -> None:
        name = game.snapshot()["object"]
        await manager.on_assistant_text(f"¡El primero que me enseñe {name}!", False)
        await tick_manager(manager, clock, 0.1)

    # Ronda 1: Sonia anuncia, suena el «¡Ya!» grabado y, a la primera mirada, ¡lo veo!
    await sonia_says_the_object()
    assert engine.clips[:1] == ["¡Ya!"]
    assert [m["event"] for m in screen.replay()] == ["start", "go"]
    await tick_manager(manager, clock, 2.7)
    assert screen.game_msgs("found")[-1]["data"]["what"] == "botella azul"
    assert engine.clips[1:2] == ["¡Lo veo!"]
    assert "En la cámara se ve" in engine.spoken[-1]
    assert [m["event"] for m in screen.replay()] == ["start", "found"]
    # Sonia lo cuenta y calla: sale la ronda 2.
    engine.quiet = 0.0
    await tick_manager(manager, clock, 0.6)
    engine.quiet = 3.0
    await tick_manager(manager, clock, 0.1)
    assert screen.game_msgs("round")[-1]["data"]["index"] == 2
    assert "ronda 2 de 3" in engine.spoken[-1]

    # Ronda 2: la ve a la primera mirada también.
    await sonia_says_the_object()
    await tick_manager(manager, clock, 2.7)
    assert len(screen.game_msgs("found")) == 2
    engine.quiet = 0.0
    await tick_manager(manager, clock, 0.6)
    engine.quiet = 3.0
    await tick_manager(manager, clock, 0.1)
    assert screen.game_msgs("round")[-1]["data"]["index"] == 3

    # Ronda 3: nadie la trae; se acaba el tiempo y termina la partida con 2 de 3.
    await sonia_says_the_object()
    await tick_manager(manager, clock, 26.0)
    assert engine.clips[-1] == "¡Tiempo!"
    assert "han encontrado 2 de 3" in engine.spoken[-1] and "Brian o Mariel" in engine.spoken[-1]
    await tick_manager(manager, clock, 0.3)
    await quiesce()
    end = screen.game_msgs("end")[-1]
    assert end["data"]["result"] == "win" and end["data"]["found"] == 2
    assert end["data"]["total"] == 3
    assert not manager.active and screen.replay() == []
    assert "vuelve a conversar con normalidad" in engine.instructions[-1]
    # Los seq suben en cada mensaje y la cámara quedó suelta.
    seqs = [m["seq"] for m in screen.game_msgs()]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    assert not manager.vision.stream.active and not manager.vision.preview.active  # type: ignore[attr-defined]


async def test_una_unity_que_se_reconecta_recibe_el_start_y_el_ultimo_estado() -> None:
    manager, _, screen, clock = await make_manager(
        [BusquedaGame], vision=FakeVision(judge=CountingJudge([MISS]))
    )
    ok, _script = await manager.start("busqueda", "voice")
    assert ok
    game = manager.current
    assert isinstance(game, BusquedaGame)
    await manager.on_assistant_text(
        f"¡El primero que me enseñe {game.snapshot()['object']}!", False
    )
    await tick_manager(manager, clock, 4.0)
    replay = screen.replay()
    assert [m["event"] for m in replay] == ["start", "go"]
    # El `go` fijo es el estado completo de la ronda: sirve tal cual para repintarla.
    assert replay[1]["data"]["index"] == 1 and replay[1]["data"]["total"] == 3
    assert replay[1]["data"]["object"] == game.snapshot()["object"]
    assert replay[0]["seq"] < replay[1]["seq"]


async def test_si_se_cae_la_sesion_la_partida_se_cancela_y_suelta_la_camara() -> None:
    vision = FakeVision(judge=CountingJudge())
    manager, _, screen, clock = await make_manager([BusquedaGame], vision=vision)
    ok, _script = await manager.start("busqueda", "voice")
    assert ok and vision.stream.active and vision.preview.active
    await manager.on_session_lost()
    assert not manager.active and not vision.stream.active and not vision.preview.active
    assert screen.game_msgs("end")[-1]["data"]["result"] == "cancel"
    assert screen.replay() == []


async def test_el_abandono_cancela_la_partida_si_nadie_juega() -> None:
    vision = FakeVision(judge=CountingJudge())
    manager, engine, screen, clock = await make_manager([BusquedaGame], vision=vision)
    ok, _script = await manager.start("busqueda", "voice")
    assert ok
    await tick_manager(manager, clock, 20.0, step=0.25)
    assert manager.active
    await tick_manager(manager, clock, 45.0, step=0.25)  # más de GAMES_ABANDON_SECONDS sin nadie
    assert not manager.active
    assert screen.game_msgs("end")[-1]["data"]["result"] == "cancel"
    assert not vision.stream.active


async def test_se_ofrece_solo_con_camara_vista_en_vivo_y_modelo() -> None:
    vision = FakeVision(judge=FakeJudge(available=False))
    manager, _, _, _ = await make_manager([BusquedaGame], vision=vision)
    assert manager.unavailable_reason("busqueda") == "Falta el modelo que mira la cámara."
    manager, _, _, _ = await make_manager([BusquedaGame], camera=False)
    assert manager.unavailable_reason("busqueda") == "No hay cámara para este juego."
    manager, _, _, _ = await make_manager([BusquedaGame], features=())
    reason = manager.unavailable_reason("busqueda")
    assert reason and "cámara en vivo" in reason
    manager, _, _, _ = await make_manager([BusquedaGame], vision=FakeVision(judge=CountingJudge()))
    assert manager.unavailable_reason("busqueda") is None
