"""El ``GameManager``: exclusividad, ciclo de vida, abandono, reconexión de Unity, sesión
perdida, bancos, frases grabadas y los textos para GPT-Live (sección 8 del plan)."""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

import pytest

from sonia.actions import build_default_registry
from sonia.actions.games import STOP_GAME, build_start_game
from sonia.games import NOT_SAID, BankParse, Game, GameBank, GameError, StopReason
from sonia.games.banks import BANK_MAX_CHARS
from sonia.games.manager import (
    CANCEL_TEXT,
    CHOOSE_TEXT,
    FIXED_TEXT,
    NOTHING_TO_PLAY_TEXT,
    OFF_TEXT,
    PANEL_START_TEXT,
    STICKY_START,
    STICKY_STATE,
    normalize_game_banks,
    normalize_games_off,
)
from sonia.types import ActionContext
from sonia.vision.contracts import JudgeAnswer
from sonia.ws import protocol as p
from tests.games.fakes import (
    FakeJudge,
    FakePoses,
    FakeVision,
    brands_in,
    game_settings,
    make_manager,
    settle,
)


def parse_lines(text: str) -> BankParse[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    good = [line for line in lines if not line.startswith("!")]
    return BankParse(good, [f"«{line}» no vale" for line in lines if line.startswith("!")])


WORDS = GameBank(
    id="sonda_palabras", title="Palabras", file="palabras.md", parse=parse_lines, min_entries=2
)


class ProbeGame(Game):
    """Un juego de prueba que apunta lo que le pasa."""

    id: ClassVar[str] = "sonda"
    title: ClassVar[str] = "Sonda de Sonnia"
    spoken: ClassVar[str] = "la sonda"
    settings_key: ClassVar[str] = "wordle"

    def __init__(self, host: Any) -> None:
        super().__init__(host)
        self.calls: list[str] = []
        self.stops: list[StopReason] = []
        self.fail_start: Exception | None = None
        self.nudge_text: str | None = None
        self.tick_error: Exception | None = None
        self.reason: str | None = None

    @classmethod
    def banks(cls) -> list[GameBank[Any]]:
        return [WORDS]

    def phrases(self) -> list[str]:
        return ["¡Uno, dos, tres!", " ¡Uno, dos, tres! ", "¡Ya!"]

    def unavailable_reason(self) -> str | None:
        return self.reason

    async def start(self, source: str, options: dict[str, Any]) -> str:
        self.calls.append(f"start:{source}")
        if self.fail_start is not None:
            await self.host.send("board", {"n": 0})
            raise self.fail_start
        await self.host.instruct("SONDA EN MARCHA: reglas cortas.")
        return "Arranca la sonda."

    async def stop(self, reason: StopReason) -> None:
        self.stops.append(reason)

    async def tick(self, now: float) -> None:
        if self.tick_error is not None:
            raise self.tick_error

    async def on_assistant_text(self, text: str, final: bool) -> None:
        self.calls.append(f"assistant:{final}:{text}")

    def on_user_text(self, now: float) -> None:
        self.calls.append("user")

    async def on_unity_event(self, event: str, data: dict[str, Any]) -> None:
        self.calls.append(f"unity:{event}:{data}")

    def nudge(self) -> str | None:
        return self.nudge_text

    def snapshot(self) -> dict[str, Any]:
        return {"calls": len(self.calls)}


class CameraGame(Game):
    id: ClassVar[str] = "camara"
    title: ClassVar[str] = "Cámara"
    spoken: ClassVar[str] = "la cámara"
    settings_key: ClassVar[str] = "poses"
    needs: ClassVar[frozenset[str]] = frozenset({"camera", "preview", "poses"})

    async def start(self, source: str, options: dict[str, Any]) -> str:
        await self.host.stream.acquire(self.id)
        await self.host.poses.acquire(self.id, 8)
        await self.host.preview.start(self.id)
        return "Ponte delante."


class SlowCameraGame(CameraGame):
    """Como ``CameraGame``, pero la cámara tarda en abrir: ``start`` espera a ``gate``."""

    id: ClassVar[str] = "lenta"
    title: ClassVar[str] = "Lenta"
    spoken: ClassVar[str] = "la lenta"

    def __init__(self, host: Any) -> None:
        super().__init__(host)
        self.gate = asyncio.Event()
        self.fail_after: Exception | None = None

    async def start(self, source: str, options: dict[str, Any]) -> str:
        gate = self.gate
        await gate.wait()
        script = await super().start(source, options)
        if self.fail_after is not None:
            raise self.fail_after
        return script


def slow(manager: Any) -> SlowCameraGame:
    game = manager.game("lenta")
    assert isinstance(game, SlowCameraGame)
    return game


class JudgeGame(Game):
    id: ClassVar[str] = "juez"
    title: ClassVar[str] = "Juez"
    spoken: ClassVar[str] = "el juez"
    settings_key: ClassVar[str] = "busqueda"
    needs: ClassVar[frozenset[str]] = frozenset({"camera", "vision_llm"})


def probe(manager: Any) -> ProbeGame:
    game = manager.game("sonda")
    assert isinstance(game, ProbeGame)
    return game


# ---------------------------------------------------------------------------
# Arranque, exclusividad y final
# ---------------------------------------------------------------------------


async def test_un_juego_a_la_vez_y_el_mismo_sigue() -> None:
    manager, _, screen, _ = await make_manager([ProbeGame, CameraGame])
    ok, script = await manager.start("sonda", "voice")
    assert ok and script == "Arranca la sonda."
    # Otra vez el mismo: sigue donde iba (GPT-Live a veces vuelve a delegar).
    ok, script = await manager.start("sonda", "voice")
    assert ok and "Ya estáis jugando" in script
    # Otro distinto: dice cuál está en marcha.
    ok, text = await manager.start("camara", "voice")
    assert not ok and "la sonda" in text
    assert [m["event"] for m in screen.game_msgs()] == ["start"]
    assert screen.hidden == 1  # la imagen que hubiera se retira


async def test_no_se_pisa_con_la_trivia() -> None:
    trivia_on = {"active": True}

    def busy() -> str | None:
        return "Hay una trivia en marcha." if trivia_on["active"] else None

    manager, _, _, _ = await make_manager([ProbeGame], busy=busy)
    ok, text = await manager.start("sonda", "voice")
    assert not ok and "trivia" in text
    trivia_on["active"] = False
    ok, _ = await manager.start("sonda", "voice")
    assert ok
    # Y al revés: la trivia pregunta al manager.
    assert "la sonda" in (manager.busy_reason() or "")
    await manager.stop("voice")
    assert manager.busy_reason() is None


async def test_el_final_espera_a_que_sonia_lo_cuente() -> None:
    settings = game_settings(result_seconds=1.0, final_wait_seconds=10.0)
    manager, engine, screen, clock = await make_manager([ProbeGame], settings=settings)
    await manager.start("sonda", "voice")
    game = probe(manager)
    engine.quiet = 0.0  # Sonia habla
    await game.host.finish("win", {"word": "LINUX"})
    assert manager.phase == "finishing" and manager.active
    # Las jugadas ya no llegan al juego mientras se enseña el resultado.
    result = await manager.play(ProbeGame, _never_called, {})
    assert "ya ha terminado" in result.text
    await settle()
    assert not screen.game_msgs("end")
    engine.quiet = 2.0  # calla
    await settle(30)
    end = screen.game_msgs("end")[-1]
    assert end["data"] == {"word": "LINUX", "result": "win"}
    assert game.stops == ["finished"]
    assert OFF_TEXT.format(spoken="la sonda") in engine.instructions
    assert screen.replay() == [] and not manager.active
    assert clock() >= 1000.0 + 1.0


async def _never_called(game: ProbeGame, arguments: dict[str, Any]) -> str:
    raise AssertionError("la jugada no debía llegar al juego")


async def test_cancelar_desde_el_juego_cierra_ya() -> None:
    manager, _, screen, _ = await make_manager([ProbeGame])
    await manager.start("sonda", "voice")
    await probe(manager).host.finish("cancel")
    await settle()
    assert screen.game_msgs("end")[-1]["data"] == {"result": "cancel"}
    assert not manager.active


async def test_empezar_otro_mientras_se_ve_el_final_cierra_el_anterior() -> None:
    settings = game_settings(result_seconds=30.0)
    manager, _, screen, _ = await make_manager([ProbeGame, CameraGame], settings=settings)
    await manager.start("sonda", "voice")
    await probe(manager).host.finish("lose")
    ok, _ = await manager.start("camara", "voice")
    assert ok
    ends = screen.game_msgs("end")
    assert ends[-1]["game"] == "sonda" and ends[-1]["data"]["result"] == "lose"
    assert probe(manager).stops == ["replaced"]
    assert manager.current is manager.game("camara")


async def test_si_el_juego_no_puede_empezar_se_retira_sin_hablar() -> None:
    manager, engine, screen, _ = await make_manager([ProbeGame])
    probe(manager).fail_start = GameError("No hay palabras.")
    ok, text = await manager.start("sonda", "voice")
    assert not ok and text == "No hay palabras."
    assert screen.game_msgs("end")[-1]["data"] == {"result": "cancel"}
    assert probe(manager).stops == ["error"]
    assert not manager.active and engine.spoken == []
    # Un fallo inesperado tampoco tumba nada.
    probe(manager).fail_start = RuntimeError("roto")
    ok, text = await manager.start("sonda", "voice")
    assert not ok and "falló al prepararse" in text


async def test_desde_el_panel_lo_cuenta_gpt_live_cuando_calla() -> None:
    manager, engine, _, _ = await make_manager([ProbeGame])
    ok, text = await manager.start("sonda", "panel")
    assert ok and text == "Sonda de Sonnia en marcha."
    await settle()
    assert engine.spoken == [PANEL_START_TEXT.format(spoken="la sonda") + "Arranca la sonda."]


async def test_sin_sesion_no_empieza() -> None:
    manager, engine, _, _ = await make_manager([ProbeGame])
    engine.connected = False
    ok, text = await manager.start("sonda", "panel")
    assert not ok and "no hay sesión de voz" in text


# ---------------------------------------------------------------------------
# Cuándo se ofrece
# ---------------------------------------------------------------------------


async def test_solo_se_ofrece_lo_que_la_pantalla_anuncia() -> None:
    manager, _, screen, _ = await make_manager([ProbeGame, CameraGame], unity_games=["camara"])
    reason = manager.unavailable_reason("sonda")
    assert reason is not None and "versión anterior" in reason
    ok, text = await manager.start("sonda", "voice")
    assert not ok and "versión anterior" in text and "la cámara" in text  # propone la que sí
    assert manager.capabilities() == ["games", "game:camara", "game_banks"]
    # Una Unity anterior a los juegos no anuncia ninguno.
    await manager.on_client_hello({"type": "client_hello", "client": "unity", "version": "1.0.195"})
    assert manager.playable() == [] and manager.capabilities() == ["games", "game_banks"]
    assert manager.choose_text() == NOTHING_TO_PLAY_TEXT
    # Sin pantalla conectada, nada.
    await manager.on_client_hello(
        {"type": "client_hello", "games": ["sonda", "camara"], "features": ["camera_preview"]}
    )
    screen.client_count = 0
    assert manager.unavailable_reason("camara") == "La pantalla no está conectada."


async def test_lo_que_necesita_cada_juego() -> None:
    vision = FakeVision(poses=FakePoses(available=False), judge=FakeJudge(available=False))
    manager, _, _, _ = await make_manager([CameraGame, JudgeGame], vision=vision)
    assert "posturas" in (manager.unavailable_reason("camara") or "")
    assert "modelo" in (manager.unavailable_reason("juez") or "")
    vision.poses.available_flag = True
    vision.judge.available_flag = True
    assert manager.unavailable_reason("camara") is None
    assert manager.unavailable_reason("juez") is None
    # Sin la vista en vivo en la pantalla, los que la necesitan no se ofrecen.
    await manager.on_client_hello({"type": "client_hello", "games": ["camara", "juez"]})
    assert "en vivo" in (manager.unavailable_reason("camara") or "")
    assert manager.unavailable_reason("juez") is None
    # Sin cámara USB, ninguno.
    no_camera, _, _, _ = await make_manager([CameraGame, JudgeGame], vision=vision, camera=False)
    assert no_camera.playable() == []


async def test_la_camara_se_suelta_al_terminar() -> None:
    vision = FakeVision()
    manager, _, _, _ = await make_manager([CameraGame], vision=vision)
    await manager.start("camara", "voice")
    assert vision.stream.owners == {"camara"} and "camara" in vision.poses.owners
    assert vision.preview.owners == {"camara"}
    await manager.stop("panel")
    assert not vision.stream.owners and not vision.poses.owners and not vision.preview.owners


async def test_si_la_partida_se_cancela_mientras_abre_la_camara_no_se_queda_abierta() -> None:
    """La sesión se cae mientras ``start`` aún está abriendo la cámara: lo que pida
    después de que el manager soltara la visión se suelta también (si no, la cámara se
    quedaba leyendo hasta la siguiente partida de ese juego)."""
    vision = FakeVision()
    manager, _, _, _ = await make_manager([SlowCameraGame], vision=vision)
    game = slow(manager)
    starting = asyncio.create_task(manager.start("lenta", "voice"))
    await settle()
    assert manager.active and not vision.stream.owners
    await manager.on_session_lost()
    assert not manager.active
    game.gate.set()
    ok, text = await starting
    assert not ok and "se canceló" in text
    assert not vision.stream.owners and not vision.poses.owners and not vision.preview.owners


async def test_si_falla_al_empezar_con_la_partida_ya_cerrada_suelta_la_camara() -> None:
    vision = FakeVision()
    manager, _, _, _ = await make_manager([SlowCameraGame], vision=vision)
    game = slow(manager)
    game.fail_after = GameError("No hay nadie delante.")
    starting = asyncio.create_task(manager.start("lenta", "voice"))
    await settle()
    await manager.stop("panel")
    game.gate.set()
    ok, _ = await starting
    assert not ok
    assert not vision.stream.owners and not vision.poses.owners and not vision.preview.owners


async def test_una_partida_nueva_del_mismo_juego_no_pierde_su_camara() -> None:
    """Si el mismo juego ya está otra vez en pantalla cuando termina el ``start``
    rezagado, la cámara es de la partida nueva y no se toca."""
    vision = FakeVision()
    manager, _, _, _ = await make_manager([SlowCameraGame], vision=vision)
    game = slow(manager)
    first_gate = game.gate
    first = asyncio.create_task(manager.start("lenta", "voice"))
    await settle()
    await manager.on_session_lost()
    game.gate = asyncio.Event()
    game.gate.set()
    ok, _ = await manager.start("lenta", "voice")
    assert ok and vision.stream.owners == {"lenta"}
    first_gate.set()
    ok, _ = await first
    assert not ok
    assert vision.stream.owners == {"lenta"} and "lenta" in vision.poses.owners
    assert vision.preview.owners == {"lenta"}
    await manager.stop("panel")
    assert not vision.stream.owners and not vision.poses.owners and not vision.preview.owners


async def test_apagado_desde_el_panel() -> None:
    manager, engine, screen, _ = await make_manager([ProbeGame])
    await manager.start("sonda", "voice")
    await manager.set_games_off(["sonda", "inventado"])
    assert not manager.active
    assert screen.game_msgs("end")[-1]["data"]["result"] == "cancel"
    assert engine.spoken[-1] == CANCEL_TEXT["panel"].format(spoken="la sonda")
    assert "apagado desde el panel" in (manager.unavailable_reason("sonda") or "")
    snapshot = manager.snapshot()
    assert snapshot["games"][0]["off"] is True and snapshot["games_off"] == ["inventado", "sonda"]
    await manager.set_games_off([])
    assert manager.unavailable_reason("sonda") is None


async def test_el_juego_dice_si_no_puede() -> None:
    manager, _, _, _ = await make_manager([ProbeGame])
    probe(manager).reason = "No hay palabras en el banco."
    ok, text = await manager.start("sonda", "voice")
    assert not ok and text.startswith("No hay palabras en el banco.")


async def test_en_una_videollamada_no_hay_juegos() -> None:
    manager, _, _, _ = await make_manager([ProbeGame])
    manager._meeting = True
    assert manager.unavailable_reason("sonda") == "En una videollamada no hay juegos."


# ---------------------------------------------------------------------------
# Abandono, sesión perdida y Unity
# ---------------------------------------------------------------------------


async def test_abandono_sin_voz_ni_actividad() -> None:
    settings = game_settings(abandon_seconds=60.0)
    settings.games.wordle.abandon_seconds = 0.0  # ProbeGame usa el bloque del Wordle
    manager, engine, screen, clock = await make_manager([ProbeGame], settings=settings)
    await manager.start("sonda", "voice")
    clock.advance(50)
    manager.on_user_text(clock())  # se oye al visitante: sigue ahí
    clock.advance(50)
    await manager.tick(clock())
    assert manager.active
    clock.advance(11)
    engine.quiet = 0.2  # mientras Sonia habla no se da por abandonada
    await manager.tick(clock())
    assert manager.active
    engine.quiet = 5.0
    await manager.tick(clock())
    assert not manager.active and probe(manager).stops == ["abandoned"]
    assert screen.game_msgs("end")[-1]["data"]["result"] == "cancel"
    assert engine.spoken[-1] == CANCEL_TEXT["abandoned"].format(spoken="la sonda")


async def test_cada_juego_puede_tener_su_abandono() -> None:
    settings = game_settings(abandon_seconds=60.0)
    settings.games.wordle.abandon_seconds = 90.0
    manager, _, _, clock = await make_manager([ProbeGame], settings=settings)
    await manager.start("sonda", "voice")
    clock.advance(70)
    await manager.tick(clock())
    assert manager.active
    clock.advance(25)
    await manager.tick(clock())
    assert not manager.active


async def test_la_sesion_perdida_cancela_sin_hablar() -> None:
    manager, engine, screen, _ = await make_manager([ProbeGame])
    await manager.start("sonda", "voice")
    instructions = len(engine.instructions)
    await manager.on_session_lost()
    assert not manager.active and probe(manager).stops == ["session"]
    assert screen.game_msgs("end")[-1]["data"]["result"] == "cancel"
    assert len(engine.instructions) == instructions and engine.spoken == []


async def test_unity_que_se_reconecta_recibe_el_start_y_el_ultimo_estado() -> None:
    manager, _, screen, _ = await make_manager([ProbeGame])
    await manager.start("sonda", "voice")
    host = probe(manager).host
    await host.send("board", {"row": 0})
    await host.send("confeti", {}, sticky=False)
    await host.send("board", {"row": 1})
    replay = screen.replay()
    assert [m["event"] for m in replay] == ["start", "board"]
    assert replay[0]["data"] == {"title": "Sonda de Sonnia"}
    assert replay[1]["data"] == {"row": 1}
    assert list(screen.sticky) == [STICKY_START, STICKY_STATE]
    # Una Unity que sí sabe pintarla, se queda; una que no, la cancela.
    await manager.on_client_hello({"type": "client_hello", "games": ["sonda"]})
    assert manager.active
    await manager.on_client_hello({"type": "client_hello", "games": ["otra"]})
    assert not manager.active and probe(manager).stops == ["unity"]
    assert screen.replay() == []


async def test_start_va_siempre_el_primero_y_con_titulo() -> None:
    manager, _, screen, _ = await make_manager([ProbeGame])
    await manager.start("sonda", "voice")
    host = probe(manager).host
    await host.send("start", {"rows": 6})
    first = screen.game_msgs()[-1]
    assert first["event"] == "start" and first["data"] == {"title": "Sonda de Sonnia", "rows": 6}
    await host.send("end", {"result": "win"})  # «end» no se manda a mano
    assert not screen.game_msgs("end")


async def test_los_game_event_van_al_juego_en_marcha() -> None:
    manager, _, _, _ = await make_manager([ProbeGame])
    await manager.on_game_event(
        {"type": "game_event", "game": "sonda", "event": "listo", "data": {}}
    )
    await manager.start("sonda", "voice")
    await manager.on_game_event({"type": "game_event", "game": "otro", "event": "listo"})
    await manager.on_game_event({"type": "game_event", "game": "sonda", "event": "Mal-Nombre"})
    await manager.on_game_event(
        {"type": "game_event", "game": "sonda", "event": "wheel_stopped", "data": {"segment": 3}}
    )
    assert [c for c in probe(manager).calls if c.startswith("unity")] == [
        "unity:wheel_stopped:{'segment': 3}"
    ]


async def test_un_juego_muerto_no_sigue_pintando() -> None:
    manager, engine, screen, _ = await make_manager([ProbeGame])
    await manager.start("sonda", "voice")
    host = probe(manager).host
    await manager.stop("panel")
    sent = len(screen.sent)
    await host.send("board", {"row": 9})
    assert not await host.speak("hola") and not await host.instruct("x")
    assert len(screen.sent) == sent


# ---------------------------------------------------------------------------
# GPT-Live: instrucciones, frases fijas y empujón
# ---------------------------------------------------------------------------


async def test_las_instrucciones_largas_se_cortan_a_1200() -> None:
    manager, engine, _, _ = await make_manager([ProbeGame])
    await manager.start("sonda", "voice")
    assert await probe(manager).host.instruct("x" * 5000)
    assert len(engine.instructions[-1]) == 1200 and engine.instructions[-1].endswith("…")


async def test_frase_fija_grabada_o_por_commentary() -> None:
    manager, engine, _, _ = await make_manager([ProbeGame], recorded=["¡Ya!"])
    await manager.start("sonda", "voice")
    host = probe(manager).host
    assert await host.say_fixed("¡Ya!")
    assert engine.clips == ["¡Ya!"]
    assert await host.say_fixed("¡Uno, dos, tres!")
    assert engine.spoken[-1] == FIXED_TEXT.format(text="¡Uno, dos, tres!")


async def test_las_frases_fijas_de_todos_los_juegos_sin_repetir() -> None:
    manager, _, _, _ = await make_manager([ProbeGame, CameraGame])
    assert manager.fixed_phrases() == ["¡Uno, dos, tres!", "¡Ya!"]


async def test_empujon_si_el_visitante_habla_y_no_se_delega() -> None:
    manager, engine, _, clock = await make_manager([ProbeGame])
    await manager.start("sonda", "voice")
    game = probe(manager)
    # Sin texto de empujón (por defecto), nunca.
    manager.on_user_turn_end(clock(), clock() - 1)
    clock.advance(5)
    await manager.tick(clock())
    await settle()
    assert engine.spoken == []
    game.nudge_text = "SONDA: si te dijo su jugada, delégala."
    manager.on_user_turn_end(clock(), clock() - 1)
    clock.advance(1)
    await manager.tick(clock())
    assert engine.spoken == []
    clock.advance(3)
    await manager.tick(clock())
    await settle()
    assert engine.spoken == [game.nudge_text]
    # Si delegó algo desde que empezó a hablar, no hay empujón.
    started = clock()
    manager.on_delegation(clock())
    manager.on_user_turn_end(clock() + 1, started)
    clock.advance(10)
    await manager.tick(clock())
    await settle()
    assert len(engine.spoken) == 1


async def test_el_turno_que_pide_el_juego_no_da_empujon() -> None:
    # GPT-Live delega start_game antes de que se cierre el turno del visitante que lo pidió.
    manager, engine, _, clock = await make_manager([ProbeGame])
    started = clock()
    manager.on_delegation(clock())
    await manager.start("sonda", "voice")
    probe(manager).nudge_text = "SONDA: delega su jugada."
    clock.advance(1)
    manager.on_user_turn_end(clock(), started)
    clock.advance(5)
    await manager.tick(clock())
    await settle()
    assert engine.spoken == []


async def test_un_tick_que_falla_sin_parar_cancela_la_partida() -> None:
    manager, _, _, clock = await make_manager([ProbeGame])
    await manager.start("sonda", "voice")
    probe(manager).tick_error = RuntimeError("roto")
    for _ in range(25):
        manager.on_user_text(clock())
        await manager.tick(clock())
    assert not manager.active


# ---------------------------------------------------------------------------
# Bancos
# ---------------------------------------------------------------------------


async def test_validar_un_banco_antes_de_guardarlo() -> None:
    manager, _, _, _ = await make_manager([ProbeGame])
    ok, text = manager.validate_bank("sonda_palabras", "uno\n!mala\ndos\n")
    assert ok and "2 entradas válidas" in text and "«!mala» no vale" in text
    ok, text = manager.validate_bank("sonda_palabras", "uno\n")
    assert not ok and "hacen falta 2" in text
    ok, text = manager.validate_bank("sonda_palabras", "x" * (BANK_MAX_CHARS + 1))
    assert not ok and "tope" in text
    ok, text = manager.validate_bank("sonda_palabras", "")
    assert ok and "vuelve el de la app" in text
    ok, _ = manager.validate_bank("no_existe", "uno\ndos")
    assert not ok


async def test_el_banco_de_la_nube_manda_si_vale(tmp_path: Any) -> None:
    settings = game_settings()
    settings.assets_dir = str(tmp_path)
    (tmp_path / "games" / "sonda").mkdir(parents=True)
    (tmp_path / "games" / "sonda" / "palabras.md").write_text("app1\napp2\n", encoding="utf-8")
    manager, _, _, _ = await make_manager([ProbeGame], settings=settings)
    host = probe(manager).host
    assert await host.load_bank(WORDS) == ["app1", "app2"]
    manager.use_cloud_banks({"sonda_palabras": "nube1\nnube2\nnube3"})
    assert await host.load_bank(WORDS) == ["nube1", "nube2", "nube3"]
    assert manager.bank_text("sonda_palabras") == "nube1\nnube2\nnube3"
    assert manager.bank_list()[0]["source"] == "cloud"
    # Uno de la nube que no llega al mínimo no se usa: sigue el de la app.
    manager.use_cloud_banks({"sonda_palabras": "sola"})
    assert host.read_bank(WORDS) == ["app1", "app2"]
    manager.use_cloud_banks(None)
    assert manager.bank_text("sonda_palabras") == "app1\napp2\n"
    with pytest.raises(KeyError):
        manager.bank_text("no_existe")


def test_normalizar_lo_que_llega_de_la_nube() -> None:
    assert normalize_games_off(["wordle", "Mal Id", 3, "wordle", "ruleta"]) == ["ruleta", "wordle"]
    assert normalize_games_off("wordle") == []
    banks = {"ruleta_retos": "a", "Mal": "b", "vacio": "  ", "largo": "x" * (BANK_MAX_CHARS + 1)}
    assert normalize_game_banks(banks) == {"ruleta_retos": "a"}
    assert normalize_game_banks({}) is None and normalize_game_banks([1]) is None


# ---------------------------------------------------------------------------
# Acciones y textos para GPT-Live
# ---------------------------------------------------------------------------


async def test_start_game_y_stop_game() -> None:
    manager, _, _, _ = await make_manager([ProbeGame])
    registry = build_default_registry(include_look=False, games=[ProbeGame])
    assert {"start_game", "stop_game"} <= set(registry.names())
    ctx = ActionContext(camera=None, avatar=None, gallery_dir="", extra={"games": manager})
    result = await registry.execute("start_game", {"juego": "otro"}, ctx)
    assert result.text.startswith("Error: argumentos inválidos")  # enum fijo
    result = await registry.execute("start_game", {"juego": NOT_SAID}, ctx)
    assert CHOOSE_TEXT.split(":")[0] in result.text and "la sonda" in result.text
    result = await registry.execute("stop_game", {}, ctx)
    assert result.text == "No hay ningún juego en marcha."
    # Sin manager en el contexto (motor sin juegos), no se rompe.
    empty = ActionContext(camera=None, avatar=None, gallery_dir="")
    assert "no están disponibles" in (await registry.execute("stop_game", {}, empty)).text


def test_sin_juegos_no_hay_acciones_de_juegos() -> None:
    names = build_default_registry(include_look=False).names()
    assert "start_game" not in names and "stop_game" not in names


async def test_ningun_texto_para_gpt_live_nombra_el_stack() -> None:
    texts = [
        OFF_TEXT,
        PANEL_START_TEXT,
        CHOOSE_TEXT,
        NOTHING_TO_PLAY_TEXT,
        FIXED_TEXT,
        *CANCEL_TEXT.values(),
        build_start_game([ProbeGame]).description,
        STOP_GAME.description,
    ]
    manager, _, _, _ = await make_manager([CameraGame, JudgeGame], camera=False)
    texts += [manager.unavailable_reason(g.id) or "" for g in manager.games()]
    vision = FakeVision(poses=FakePoses(available=False), judge=FakeJudge(available=False))
    manager, _, _, _ = await make_manager([CameraGame, JudgeGame], vision=vision)
    texts += [manager.unavailable_reason(g.id) or "" for g in manager.games()]
    for text in texts:
        assert not brands_in(text), text
        assert "Sonnia" not in text or text in (PANEL_START_TEXT,), text


async def test_el_juez_falso_apunta_y_responde() -> None:
    judge = FakeJudge([JudgeAnswer(seen=True, what="una botella azul")])
    assert (await judge.ask("¿algo azul?")) == JudgeAnswer(True, "una botella azul")
    assert (await judge.ask("¿algo rojo?")) == JudgeAnswer(False)
    assert judge.questions == ["¿algo azul?", "¿algo rojo?"]


def test_el_protocolo_de_los_juegos() -> None:
    assert p.msg_game_end("wordle", 3, "lose", {"word": "REDIS"}) == {
        "type": "game",
        "game": "wordle",
        "event": "end",
        "seq": 3,
        "data": {"word": "REDIS", "result": "lose"},
    }
    with pytest.raises(ValueError):
        p.msg_game_end("wordle", 3, "empate")
    with pytest.raises(ValueError):
        p.msg_game("Wordle", "guess", 1)
    hello = p.parse_client_hello(
        {
            "client": "unity",
            "version": "1.0.200",
            "games": ["ruleta", "Mal", 3],
            "features": ["camera_preview", ""],
        }
    )
    assert hello.games == frozenset({"ruleta"}) and hello.features == frozenset({"camera_preview"})
    assert p.parse_client_hello({"client": "unity"}).games is None
    assert p.parse_game_event({"game": "ruleta", "event": "wheel_stopped"}) == (
        "ruleta",
        "wheel_stopped",
        {},
    )
    assert p.parse_game_event({"game": "ruleta", "event": "x", "data": [1]}) is None
