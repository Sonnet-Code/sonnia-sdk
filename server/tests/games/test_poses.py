"""«Simón dice con poses» de punta a punta, sin cámara ni red (``sonia.games.poses``).

La gente delante de la cámara es una :class:`Crowd`: monigotes inventados que, en la ventana
de cada ronda, hacen la pose que toca (o caen en la trampa). Se prueba el juego suelto con
``FakeGameHost`` y entero con el ``GameManager`` y las acciones que delega GPT-Live.
"""

from __future__ import annotations

import asyncio
from typing import Any

import numpy as np
import pytest

from sonia.actions import build_default_registry
from sonia.games import SCRIPT_PREFIX, GameError
from sonia.games.poses import PosesGame
from sonia.games.poses import game as poses_game
from sonia.games.poses.bank import MIN_POSES, POSES_BANK, PoseEntry, parse_poses
from sonia.games.poses.game import RoundResult, plan_rounds
from sonia.games.poses.overlay import TINTS
from sonia.games.poses.puppets import DOWN, POSE_ARMS, puppet
from sonia.games.poses.rules import POSE_IDS
from sonia.types import ActionContext
from sonia.vision.contracts import PoseFrame
from tests.games.fakes import (
    FakePoses,
    FakePreview,
    FakeVision,
    check_for_live,
    game_settings,
    make_game,
    make_manager,
)

#: Lo que trae cada evento de la pantalla (el estado completo, ver el protocolo).
STATE_KEYS = {
    "phase",
    "round",
    "rounds",
    "pose",
    "label",
    "meme",
    "demo",
    "order",
    "simon",
    "seconds",
    "count",
    "total",
    "players",
    "hint",
    "done",
    "possible",
    "fell",
}


class Crowd(FakePoses):
    """La gente delante de la cámara.

    ``players`` monigotes de frente; en la ventana y el resultado de cada ronda, ``doers``
    hacen la pose (en las trampas, ``fallers``). Además, ``close`` personas pegadas a la
    cámara y ``far`` al fondo (no juegan). Lee la ronda del ``snapshot`` del juego.
    """

    def __init__(
        self,
        players: int = 5,
        doers: int = 3,
        fallers: int = 1,
        *,
        close: int = 0,
        far: int = 0,
        fail: bool = False,
    ) -> None:
        super().__init__()
        self.game: PosesGame | None = None
        self.players = players
        self.doers = doers
        self.fallers = fallers
        self.close = close
        self.far = far
        self.fail = fail
        self.calls = 0

    def latest(self, max_age_s: float = 0.5) -> PoseFrame | None:
        if self.fail:
            raise RuntimeError("el detector se ha roto")
        self.calls += 1
        snap: dict[str, Any] = self.game.snapshot() if self.game is not None else {}
        pose = snap.get("pose") or ""
        acting = 0
        if snap.get("phase") in ("window", "result") and pose in POSE_ARMS:
            acting = self.doers if snap.get("simon") is not False else self.fallers
        people = []
        for index in range(self.players):
            left, right = POSE_ARMS[pose] if index < acting else (DOWN, DOWN)
            people.append(puppet(left, right, cx=64.0 + index * 128.0, sy=140.0, s=40.0))
        for index in range(self.close):
            people.append(puppet(cx=200.0 + index * 240.0, sy=260.0, s=0.33 * 640))
        for index in range(self.far):
            people.append(puppet(cx=100.0 + index * 60.0, sy=60.0, s=10.0))
        return PoseFrame(at=float(self.calls), width=640, height=360, people=tuple(people))


def crowd_game(crowd: Crowd | None = None, **kwargs: Any) -> tuple[PosesGame, Any, Crowd]:
    crowd = crowd or Crowd()
    vision = kwargs.pop("vision", None) or FakeVision(poses=crowd)
    game, host = make_game(PosesGame, vision=vision, **kwargs)
    crowd.game = game
    return game, host, crowd


def sent(host: Any, event: str) -> list[dict[str, Any]]:
    return host.events(event)


# ---------------------------------------------------------------------------
# Banco
# ---------------------------------------------------------------------------


def test_el_banco_de_la_app_tiene_las_seis_poses() -> None:
    settings = game_settings()
    text = (settings.games_dir / "poses" / POSES_BANK.file).read_text(encoding="utf-8")
    parsed = parse_poses(text)
    assert parsed.warnings == []
    assert [entry.id for entry in parsed.entries] == list(POSE_IDS)
    assert len(parsed.entries) >= POSES_BANK.min_entries == MIN_POSES
    assert "pendiente de revisión de Jean" in text


def test_las_ordenes_se_dicen_con_y_sin_simon() -> None:
    entry = PoseEntry("brazos_arriba", "Pasaron todos los tests", "brazos arriba")
    assert entry.order(True) == "¡Simón dice: pasaron todos los tests, brazos arriba!"
    assert entry.order(False) == "¡Pasaron todos los tests, brazos arriba!"
    assert entry.label == "Brazos arriba"
    # Las siglas no se tocan.
    pr = PoseEntry("barbilla", "PR aprobado", "mano en la barbilla")
    assert pr.order(True) == "¡Simón dice: PR aprobado, mano en la barbilla!"


def test_el_banco_salta_lo_mal_formado() -> None:
    text = """\
<!-- ## comentario que no cuenta -->
# Poses
## brazos_arriba
- orden: «¡Pasaron todos los tests!»
- pose: Brazos arriba
## voltereta
- orden: Merge sin conflictos
- pose: una voltereta
## pose_t
- orden: Pose T
## biceps
- orden: Compiló a la primera
- pose: saquen bíceps
- activa: no
## barbilla
- orden: Revisando el PR de un compañero que no deja de escribir y escribir sin parar nunca
- pose: mano en la barbilla
## brazos_arriba
- orden: Otra vez
- pose: brazos arriba
## un_brazo
- orden: Subiendo a producción
- pose: un brazo arriba
- demo: touchBeard
## manos_cabeza
- orden: Deploy un viernes
- pose: manos a la cabeza
- demo: <script>
"""
    parsed = parse_poses(text)
    ids = [entry.id for entry in parsed.entries]
    assert ids == ["brazos_arriba", "un_brazo", "manos_cabeza"]
    first = parsed.entries[0]
    assert (first.meme, first.pose) == ("Pasaron todos los tests", "brazos arriba")
    assert parsed.entries[1].demo == "touchBeard"
    assert parsed.entries[2].demo == ""  # un clip con nombre raro se cambia por la pose
    joined = " ".join(parsed.warnings)
    assert "voltereta" in joined and "pose_t" in joined and "barbilla" in joined
    assert "repetida" in joined and "demo" in joined
    # La desactivada no es entrada ni aviso.
    assert not any(w.startswith("«biceps»") for w in parsed.warnings)


async def test_el_panel_no_guarda_un_banco_con_menos_de_tres_poses() -> None:
    manager, *_ = await make_manager([PosesGame])
    ok, message = manager.validate_bank(
        POSES_BANK.id, "## brazos_arriba\n- orden: Tests\n- pose: brazos arriba\n"
    )
    assert not ok and "3" in message
    settings = game_settings()
    app = (settings.games_dir / "poses" / POSES_BANK.file).read_text(encoding="utf-8")
    assert manager.validate_bank(POSES_BANK.id, app)[0]


def test_las_frases_grabadas_son_las_ordenes() -> None:
    game, _ = make_game(PosesGame)
    phrases = game.phrases()
    assert len(phrases) == 2 * len(POSE_IDS) == len(set(phrases))
    assert "¡Simón dice: pasaron todos los tests, brazos arriba!" in phrases
    assert "¡Pasaron todos los tests, brazos arriba!" in phrases
    for phrase in phrases:
        check_for_live(phrase)


# ---------------------------------------------------------------------------
# Rondas
# ---------------------------------------------------------------------------


def _entries() -> list[PoseEntry]:
    settings = game_settings()
    text = (settings.games_dir / "poses" / POSES_BANK.file).read_text(encoding="utf-8")
    return parse_poses(text).entries


@pytest.mark.parametrize("seed", range(30))
def test_la_trampa_nunca_es_la_primera_y_no_se_repite_pose_seguida(seed: int) -> None:
    import random

    plan = plan_rounds(_entries()[:3], 8, 2, random.Random(seed))
    assert len(plan) == 8
    assert plan[0][1] is True
    assert sum(1 for _, simon in plan if not simon) == 2
    ids = [entry.id for entry, _ in plan]
    assert all(a != b for a, b in zip(ids, ids[1:], strict=False))


def test_las_trampas_se_quedan_en_lo_que_cabe() -> None:
    import random

    assert plan_rounds(_entries(), 1, 3, random.Random(1)) == [
        (plan_rounds(_entries(), 1, 0, random.Random(1))[0][0], True)
    ]
    assert plan_rounds([], 6, 1, random.Random(1)) == []
    plan = plan_rounds(_entries(), 3, 5, random.Random(2))
    assert [simon for _, simon in plan].count(False) == 2


def test_lo_bien_hecho_de_cada_ronda() -> None:
    assert RoundResult("brazos_arriba", True, 7, 9).done == 7
    assert RoundResult("brazos_arriba", False, 4, 9).done == 5  # cayeron 4: 5 aguantaron


# ---------------------------------------------------------------------------
# El juego suelto (FakeGameHost)
# ---------------------------------------------------------------------------


async def test_empieza_con_la_vista_en_vivo_y_sus_reglas() -> None:
    game, host, crowd = crowd_game()
    script = await game.start("voice", {})
    assert "6 rondas" in script and "Simón dice" in script
    assert len(host.instructions) == 1 and "SIMÓN DICE CON POSES EN MARCHA" in host.instructions[0]
    assert host.preview.starts == [("poses", True)] and host.preview.overlay is not None
    assert host.poses.owners == {"poses": 8.0}
    assert host.sent[0]["event"] == "start" and host.sent[0]["data"] == {"rounds": 6}
    assert sent(host, "placement")[0]["phase"] == "placement"
    assert len(host.tasks) == 1
    host.tasks[0].cancel()


async def test_partida_entera() -> None:
    game, host, crowd = crowd_game(Crowd(players=5, doers=3, fallers=1))
    await game.start("voice", {})
    await host.run_tasks()
    # Cada ronda: demostración, orden, ventana y resultado; al final, el total.
    for event in ("round", "command", "window", "result"):
        assert len(sent(host, event)) == 6, event
    results = sent(host, "result")
    traps = [r for r in results if not r["simon"]]
    assert len(traps) == 1 and results[0]["simon"] is True
    for result in results:
        expected = 3 if result["simon"] else 1
        assert (result["count"], result["total"]) == (expected, 5)
    # Las órdenes suenan como frases fijas, con «Simón dice» salvo en la trampa.
    orders = [text for text, _ in host.fixed]
    assert len(orders) == 6
    assert sum(1 for o in orders if o.startswith("¡Simón dice:")) == 5
    assert [c["order"] for c in sent(host, "command")] == orders
    # GPT-Live reacciona a cada resultado y al final.
    assert sum(1 for s in host.spoken if "de 5" in s) >= 5
    assert any("TRAMPA" in s and "cayeron 1 de 5" in s for s in host.spoken)
    final = sent(host, "final")[-1]
    assert (final["done"], final["possible"], final["fell"]) == (5 * 3 + 4, 30, 1)
    assert "hicieron bien 19 de 30" in host.spoken[-1]
    assert "Brian o Mariel" in host.spoken[-1]
    assert host.finished == [("win", final)]
    # Ventana de la duración de los ajustes.
    assert {w["seconds"] for w in sent(host, "window")} == {1.8}


async def test_cada_evento_lleva_el_estado_completo() -> None:
    game, host, _ = crowd_game()
    await game.start("voice", {})
    await host.run_tasks()
    for message in host.sent[1:]:
        assert set(message["data"]) == STATE_KEYS, message["event"]
        assert message["data"]["phase"] == message["event"]
        assert message["sticky"] is True
    rounds = sent(host, "round")
    assert [r["round"] for r in rounds] == [1, 2, 3, 4, 5, 6]
    assert all(r["order"] == "" and r["label"] for r in rounds)


async def test_las_ordenes_grabadas_suenan_tal_cual() -> None:
    probe, _ = make_game(PosesGame)
    game, host, _ = crowd_game(recorded=probe.phrases())
    await game.start("voice", {})
    await host.run_tasks()
    assert host.fixed and all(recorded for _, recorded in host.fixed)


async def test_cuenta_el_mejor_frame_de_la_ventana_y_solo_a_quien_juega() -> None:
    game, host, crowd = crowd_game(Crowd(players=4, doers=4, fallers=0, far=3))
    await game.start("voice", {})
    await host.run_tasks()
    first = sent(host, "result")[0]
    assert (first["count"], first["total"]) == (4, 4)
    assert any("la hicieron todos" in s for s in host.spoken)


async def test_si_alguien_esta_demasiado_cerca_pide_un_paso_atras() -> None:
    game, host, _ = crowd_game(Crowd(players=2, close=1))
    await game.start("voice", {})
    await host.run_tasks()
    assert poses_game.BACK_TEXT in host.spoken
    hints = {p["hint"] for p in sent(host, "placement")}
    assert poses_game.HINT_CLOSE in hints
    # No se pide sin parar: como mucho una vez cada CLOSE_ASK_COOLDOWN_S.
    assert host.spoken.count(poses_game.BACK_TEXT) <= 10


async def test_sin_nadie_pide_que_se_pongan_delante_y_acaba() -> None:
    game, host, _ = crowd_game(Crowd(players=0))
    await game.start("voice", {})
    await host.run_tasks()
    assert poses_game.NOBODY_TEXT in host.spoken
    assert {p["hint"] for p in sent(host, "placement")} == {poses_game.HINT_NOBODY}
    # Dos rondas seguidas sin ver a nadie: se acaba sin final.
    assert len(sent(host, "result")) == poses_game.EMPTY_ROUNDS_TO_STOP
    assert host.spoken[-1] == poses_game.EMPTY_FINAL_TEXT
    assert host.finished == [("cancel", None)]
    assert not sent(host, "final")


async def test_ve_gente_y_avisa_de_que_sigue_la_partida() -> None:
    game, host, _ = crowd_game()
    await game.start("voice", {})
    await host.run_tasks()
    assert host.touches >= 10


async def test_si_falla_la_camara_a_mitad_se_cancela_con_una_frase() -> None:
    game, host, crowd = crowd_game(Crowd(fail=True))
    await game.start("voice", {})
    await host.run_tasks()
    assert host.spoken[-1] == poses_game.FAILED_TEXT
    assert host.finished == [("cancel", None)]


async def test_sin_detector_o_sin_vista_no_empieza() -> None:
    game, _ = make_game(PosesGame, vision=FakeVision(poses=FakePoses(available=False)))
    with pytest.raises(GameError):
        await game.start("voice", {})
    game, _ = make_game(PosesGame, vision=FakeVision(preview=FakePreview(available=False)))
    with pytest.raises(GameError):
        await game.start("voice", {})


async def test_sin_poses_en_el_banco_no_empieza() -> None:
    game, _ = make_game(PosesGame, cloud_banks={POSES_BANK.id: "## nada"})
    # El de la nube no llega al mínimo: sigue el de la app.
    script = await game.start("voice", {})
    assert "rondas" in script

    class Empty(PosesGame):
        async def start(self, source: str, options: dict[str, Any]) -> str:
            self.host.read_bank = lambda bank: []  # type: ignore[method-assign]
            return await super().start(source, options)

    async def no_entries(bank: Any) -> list[Any]:
        return []

    game2, host2 = make_game(PosesGame)
    host2.load_bank = no_entries  # type: ignore[method-assign]
    with pytest.raises(GameError, match="banco"):
        await game2.start("voice", {})


async def test_stop_suelta_la_camara_y_borra_los_esqueletos() -> None:
    game, host, _ = crowd_game()
    await game.start("voice", {})
    for _ in range(50):
        await asyncio.sleep(0)
    await game.stop("voice")
    for task in host.tasks:
        task.cancel()
    assert host.preview.stops == ["poses"] and host.poses.owners == {}
    assert game.snapshot()["phase"] == "off"
    image = host.preview.draw(np.zeros((360, 640, 3), dtype=np.uint8))
    assert not image.any()


async def test_el_panel_ve_en_que_va_la_partida() -> None:
    game, host, _ = crowd_game(Crowd(players=4, doers=3, fallers=1))
    await game.start("voice", {})
    assert game.snapshot()["summary"].startswith("Colocándose")
    await host.run_tasks()
    snap = game.snapshot()
    assert snap["summary"] == "Final: 18 de 24 bien, cayeron 1"  # 5 x 3 + (4 - 1)
    assert [r["count"] for r in snap["results"] if r["simon"]] == [3] * 5
    game._phase = "result"
    game._index, game._count, game._total = 0, 3, 4
    assert game._summary() == "Ronda 1 de 6: 3 de 4"


async def test_resume_dice_por_donde_va() -> None:
    game, host, _ = crowd_game()
    await game.start("voice", {})
    host.tasks[0].cancel()
    text = await game.resume()
    check_for_live(text)
    assert "ronda 1 de 6" in text


async def test_con_barullo_la_ronda_no_espera_de_mas() -> None:
    game, host, _ = crowd_game()
    await game.start("voice", {})
    host.tasks[0].cancel()
    # Sonia callada pero la sesión nunca en calma (el grupo charla): basta con esperar un poco.
    host.idle = False
    began = host.now()
    assert await game._wait_calm()
    assert host.now() - began == pytest.approx(poses_game.CALM_IDLE_MAX_S, abs=0.25)
    # En calma, enseguida.
    host.idle = True
    began = host.now()
    assert await game._wait_calm()
    assert host.now() - began < 0.2


async def test_la_ventana_se_abre_cuando_termina_la_orden() -> None:
    game, host, _ = crowd_game()
    await game.start("voice", {})
    host.tasks[0].cancel()
    t0 = host.now()

    def quiet_for() -> float:
        # La orden empieza a sonar a los 0,5 s y dura 2,5 s.
        now = host.now() - t0
        if now < 0.5:
            return 10.0
        return 0.0 if now < 3.0 else now - 3.0

    host.quiet_for = quiet_for  # type: ignore[method-assign]
    await game._wait_phrase()
    assert 3.1 <= host.now() - t0 <= 3.3


def test_ningun_texto_para_sonia_nombra_el_stack_ni_se_pasa() -> None:
    check_for_live(poses_game.RULES_TEXT.format(rounds=12), limit=1200)
    texts = [
        poses_game.START_TEXT,
        poses_game.RESUME_TEXT,
        poses_game.BACK_TEXT,
        poses_game.NOBODY_TEXT,
        poses_game.ROUND_TEXT + poses_game.ALL_TEXT + poses_game.NEXT_TEXT,
        poses_game.SOME_TEXT,
        poses_game.NONE_TEXT,
        poses_game.TRAP_FELL_TEXT,
        poses_game.TRAP_NONE_TEXT,
        poses_game.EMPTY_TEXT,
        poses_game.FINAL_TEXT + poses_game.FINAL_TRAP_TEXT + poses_game.WIN_CONTACT_TEXT,
        poses_game.EMPTY_FINAL_TEXT,
        poses_game.FAILED_TEXT,
    ]
    for text in texts:
        check_for_live(text)
        assert "Sonnia" not in text


def test_no_tiene_jugadas_delegadas() -> None:
    # Todo lo lleva el orquestador con la cámara: solo se delega empezar y terminar.
    assert PosesGame.actions() == []


# ---------------------------------------------------------------------------
# Vista en vivo
# ---------------------------------------------------------------------------


async def test_los_esqueletos_salen_en_verde_en_la_ventana_y_en_espejo() -> None:
    game, host, crowd = crowd_game(Crowd(players=1, doers=1))
    await game.start("voice", {})
    host.tasks[0].cancel()
    # Fuera de la ventana, todos en gris.
    game._poll()
    assert {s.tint for s in game._skeletons.shown} == {"no"}
    # En la ventana de una ronda normal, en verde quien hace la pose.
    game._index = 0
    game._phase = "window"
    game._poll()
    assert {s.tint for s in game._skeletons.shown} == {"ok"}
    image = host.preview.draw(np.zeros((360, 640, 3), dtype=np.uint8), mirrored=False)
    green = np.all(image == np.array(TINTS["ok"], dtype=np.uint8), axis=-1)
    assert green.any()
    # El monigote está a la izquierda de la imagen (cx = 64): en espejo sale a la derecha.
    xs = np.nonzero(green)[1]
    assert xs.mean() < 320
    mirrored = host.preview.draw(np.zeros((360, 640, 3), dtype=np.uint8), mirrored=True)
    green_m = np.all(mirrored == np.array(TINTS["ok"], dtype=np.uint8), axis=-1)
    assert np.nonzero(green_m)[1].mean() > 320


async def test_en_una_trampa_quien_cae_sale_en_rojo() -> None:
    game, host, crowd = crowd_game(Crowd(players=2, doers=0, fallers=2))
    await game.start("voice", {})
    host.tasks[0].cancel()
    trap = next(i for i, (_, simon) in enumerate(game._plan) if not simon)
    game._index = trap
    game._phase = "window"
    game._poll()
    assert {s.tint for s in game._skeletons.shown} == {"fell"}


async def test_sin_deteccion_reciente_no_se_dibuja_nada() -> None:
    game, host, _ = crowd_game(vision=FakeVision(poses=FakePoses()))
    await game.start("voice", {})
    host.tasks[0].cancel()
    assert game._poll() is None and game._skeletons.shown == ()


# ---------------------------------------------------------------------------
# De punta a punta con el GameManager
# ---------------------------------------------------------------------------


async def _drive(manager: Any, clock: Any, *, until_off: bool = True, steps: int = 20000) -> None:
    """Deja correr la partida llamando al ``tick`` del manager, como el motor."""
    for _ in range(steps):
        await manager.tick(clock())
        await asyncio.sleep(0)
        if until_off and not manager.active:
            return


def _ctx(manager: Any) -> ActionContext:
    return ActionContext(camera=None, avatar=None, gallery_dir="", extra={"games": manager})


async def test_partida_por_voz_con_el_manager() -> None:
    crowd = Crowd(players=3, doers=2, fallers=1)
    vision = FakeVision(poses=crowd)
    manager, engine, screen, clock = await make_manager([PosesGame], vision=vision)
    crowd.game = manager.game("poses")  # type: ignore[assignment]
    registry = build_default_registry(include_look=False, games=[PosesGame])
    result = await registry.execute("start_game", {"juego": "poses"}, _ctx(manager))
    assert result.text.startswith(SCRIPT_PREFIX) and "rondas" in result.text
    first = screen.game_msgs()[0]
    assert first["event"] == "start" and first["data"]["title"] == "Simón dice con poses"
    await _drive(manager, clock)
    end = screen.game_msgs("end")[-1]
    assert end["data"]["result"] == "win" and end["data"]["possible"] == 18
    assert not manager.active
    # Las órdenes sin grabar se piden tal cual por commentary; las reglas, por instruct.
    assert sum(1 for s in engine.spoken if "¡Simón dice:" in s) == 5
    assert any("SIMÓN DICE CON POSES EN MARCHA" in i for i in engine.instructions)
    assert "vuelve a conversar con normalidad" in engine.instructions[-1]
    # La cámara y la vista en vivo, sueltas.
    assert vision.preview.owners == set() and vision.poses.owners == {}


async def test_las_ordenes_grabadas_suenan_desde_la_cache() -> None:
    probe, _ = make_game(PosesGame)
    crowd = Crowd(players=2, doers=2)
    manager, engine, _, clock = await make_manager(
        [PosesGame], vision=FakeVision(poses=crowd), recorded=probe.phrases()
    )
    crowd.game = manager.game("poses")  # type: ignore[assignment]
    await manager.start("poses", "voice")
    await _drive(manager, clock)
    assert len(engine.clips) == 6 and all(c.startswith("¡") for c in engine.clips)


async def test_stop_game_a_mitad_de_partida() -> None:
    crowd = Crowd()
    vision = FakeVision(poses=crowd)
    manager, _, screen, clock = await make_manager([PosesGame], vision=vision)
    crowd.game = manager.game("poses")  # type: ignore[assignment]
    registry = build_default_registry(include_look=False, games=[PosesGame])
    await registry.execute("start_game", {"juego": "poses"}, _ctx(manager))
    await _drive(manager, clock, until_off=False, steps=300)
    assert manager.active
    # Otra vez start_game: sigue la misma partida.
    again = await registry.execute("start_game", {"juego": "poses"}, _ctx(manager))
    assert "Ya están jugando" in again.text
    result = await registry.execute("stop_game", {}, _ctx(manager))
    assert "terminado" in result.text
    assert screen.game_msgs("end")[-1]["data"]["result"] == "cancel"
    assert vision.preview.owners == set() and vision.poses.owners == {}
    # Lo que quedaba de la partida ya no pinta nada.
    before = len(screen.game_msgs())
    await _drive(manager, clock, until_off=False, steps=200)
    assert len(screen.game_msgs()) == before


async def test_con_gente_delante_no_se_abandona_aunque_nadie_hable() -> None:
    crowd = Crowd()
    manager, _, screen, clock = await make_manager(
        [PosesGame],
        vision=FakeVision(poses=crowd),
        settings=game_settings(result_seconds=0.0, final_wait_seconds=0.0, abandon_seconds=10.0),
    )
    crowd.game = manager.game("poses")  # type: ignore[assignment]
    await manager.start("poses", "voice")
    await _drive(manager, clock)
    assert screen.game_msgs("end")[-1]["data"]["result"] == "win"


async def test_sin_nadie_delante_ni_voz_se_abandona() -> None:
    crowd = Crowd(players=0)
    manager, engine, screen, clock = await make_manager(
        [PosesGame],
        vision=FakeVision(poses=crowd),
        settings=game_settings(result_seconds=0.0, final_wait_seconds=0.0, abandon_seconds=10.0),
    )
    crowd.game = manager.game("poses")  # type: ignore[assignment]
    await manager.start("poses", "voice")
    await _drive(manager, clock)
    assert screen.game_msgs("end")[-1]["data"]["result"] == "cancel"
    assert any("nadie sigue jugando" in s for s in engine.spoken)


async def test_una_unity_que_se_reconecta_recibe_el_ultimo_estado() -> None:
    crowd = Crowd()
    manager, _, screen, clock = await make_manager([PosesGame], vision=FakeVision(poses=crowd))
    crowd.game = manager.game("poses")  # type: ignore[assignment]
    await manager.start("poses", "voice")
    await _drive(manager, clock, until_off=False, steps=400)
    replay = screen.replay()
    assert replay[0]["event"] == "start"
    assert len(replay) == 2 and set(replay[1]["data"]) == STATE_KEYS
    await manager.stop("panel")


async def test_no_se_ofrece_sin_camara_ni_con_la_trivia() -> None:
    manager, *_ = await make_manager([PosesGame], camera=False)
    assert manager.unavailable_reason("poses") == "No hay cámara para este juego."
    manager, *_ = await make_manager([PosesGame], busy=lambda: "Hay una trivia en marcha.")
    ok, message = await manager.start("poses", "voice")
    assert not ok and "trivia" in message


# ---------------------------------------------------------------------------
# La secuencia del orquestador falso
# ---------------------------------------------------------------------------


def test_la_secuencia_del_orquestador_falso_pasa_por_cada_estado() -> None:
    from sonia.games.demo import Capture, GameMsg, Preview, load_demo

    steps = load_demo("poses")
    msgs = [s for s in steps if isinstance(s, GameMsg)]
    assert msgs[0].event == "start" and msgs[-1].event == "end"
    events = {m.event for m in msgs}
    assert {"placement", "round", "command", "window", "result", "final"} <= events
    for msg in msgs[1:-1]:
        assert set(msg.data) == STATE_KEYS and msg.data["phase"] == msg.event
    assert {m.data["pose"] for m in msgs if m.event == "round"} == set(POSE_IDS)
    names = [s.name for s in steps if isinstance(s, Capture)]
    assert len(names) == len(set(names)) >= 10
    # La vista en vivo sintética se dibuja sin fallar, en espejo y sin él.
    for step in steps:
        if isinstance(step, Preview) and step.draw is not None:
            for mirrored in (True, False):
                frame = np.zeros((360, 640, 3), dtype=np.uint8)
                step.draw(frame, mirrored)
                assert frame.any()
