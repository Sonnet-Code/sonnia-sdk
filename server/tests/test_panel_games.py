"""Pruebas del panel con los juegos del stand (``docs/juegos.md``, «El panel»).

La tarjeta «Juegos» (``game_start``, ``game_stop``), el interruptor de cada juego
(ajuste compartido ``games_off``), «Bancos de los juegos» (``game_bank``,
``set_game_bank`` y el ajuste compartido ``game_banks``), las capacidades (``games``,
``game:<id>`` y ``game_banks``), las frases fijas de los juegos en «Preparar voces» y
la compatibilidad con las Sonnias y los paneles anteriores.

Panel, motor y hub de verdad contra el GPT-Live falso (``make_panel_rig``), con dos
juegos de mentira: nada llama a APIs reales ni usa la cámara.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, ClassVar

import pytest

from sonia.games import BankParse, Game, GameBank, GameError
from sonia.games.banks import BANK_MAX_CHARS, markdown_sections
from sonia.games.manager import GameManager
from sonia.panel import control as control_module
from sonia.panel.control import EMPTY_GAME_BANK, SHARED_SETTINGS, PanelState
from sonia.panel.server import STATIC_DIR
from sonia.ws import protocol as p
from tests.test_live import pcm, wait_until
from tests.test_panel import TRIVIA_BANK, PanelRig, make_panel_rig, write_clip

# ---------------------------------------------------------------------------
# Juegos de mentira
# ---------------------------------------------------------------------------


def parse_questions(text: str) -> BankParse[str]:
    """``## pregunta`` con una línea ``> respuesta`` debajo; lo demás, aviso y fuera."""
    entries: list[str] = []
    warnings: list[str] = []
    for heading, lines in markdown_sections(text):
        if heading and any(line.startswith(">") for line in lines):
            entries.append(heading)
        else:
            warnings.append(f"«{heading}» no tiene respuesta (> respuesta)")
    return BankParse(entries, warnings)


QUESTIONS = GameBank(
    id="quiz_preguntas",
    title="Preguntas del quiz",
    file="preguntas.md",
    parse=parse_questions,
    min_entries=3,
)

APP_BANK = """\
<!-- Formato: ## pregunta y debajo > respuesta. -->
## ¿Qué lenguaje usa Flutter?
> Dart

## ¿Quién organiza el DevFest?
> El GDG

## ¿Qué es un commit?
> Un cambio guardado
"""

CLOUD_BANK = """\
## ¿Qué es Kotlin?
> Un lenguaje

## ¿Qué es Android?
> Un sistema

## ¿Qué es Firebase?
> Una plataforma

## Sin respuesta
"""

START_PHRASE = "¡Empieza el quiz de prueba!"


class QuizGame(Game):
    id: ClassVar[str] = "quiz"
    title: ClassVar[str] = "Quiz de prueba"
    spoken: ClassVar[str] = "el quiz de prueba"
    settings_key: ClassVar[str] = "wordle"

    @classmethod
    def banks(cls) -> list[GameBank[Any]]:
        return [QUESTIONS]

    def phrases(self) -> list[str]:
        # Una fija y otra que sale del banco en uso (las frases pueden depender de él).
        first = self.host.read_bank(QUESTIONS)[:1]
        return [START_PHRASE, *(f"Primera pregunta: {q}" for q in first)]

    async def start(self, source: str, options: dict[str, Any]) -> str:
        questions = await self.host.load_bank(QUESTIONS)
        if len(questions) < QUESTIONS.min_entries:
            raise GameError("No hay preguntas para el quiz.")
        self.question = questions[0]
        await self.host.send("start", {"question": self.question})
        await self.host.instruct("JUEGO EN MARCHA: el quiz de prueba. Lee la pregunta.")
        return f"Lee la pregunta: «{self.question}»."

    def snapshot(self) -> dict[str, Any]:
        return {"summary": "Pregunta 1 de 3", "question": getattr(self, "question", "")}


class CameraGame(Game):
    id: ClassVar[str] = "camara"
    title: ClassVar[str] = "Juego con cámara"
    spoken: ClassVar[str] = "el juego con cámara"
    needs: ClassVar[frozenset[str]] = frozenset({"camera"})
    settings_key: ClassVar[str] = "poses"


GAMES: list[type[Game]] = [QuizGame, CameraGame]


def write_app_bank(tmp_path: Path, text: str = APP_BANK) -> Path:
    path = tmp_path / "games" / "quiz" / "preguntas.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


async def unity_hello(rig: PanelRig, games: list[str], features: list[str] | None = None) -> None:
    """La Unity conectada (el cliente del rig) anuncia los juegos que sabe pintar."""
    hello = {
        "type": p.MSG_CLIENT_HELLO,
        "client": "unity",
        "version": "test",
        "games": games,
        "features": features if features is not None else [p.FEATURE_CAMERA_PREVIEW],
    }
    await rig.client.send(json.dumps(hello))
    manager = rig.engine.games
    assert manager is not None
    await wait_until(lambda: manager.snapshot()["unity_games"] == sorted(games))


def games_status(rig: PanelRig) -> dict[str, Any]:
    status: dict[str, Any] = rig.control.status()["games"]
    return status


def game_entry(rig: PanelRig, game_id: str) -> dict[str, Any]:
    return next(g for g in games_status(rig)["games"] if g["id"] == game_id)


# ---------------------------------------------------------------------------
# Sin juegos
# ---------------------------------------------------------------------------


async def test_sin_juegos_el_panel_no_los_ofrece(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path, games=[]) as rig:
        assert rig.engine.games is None
        caps = rig.control.capabilities
        assert "games" not in caps and "game_banks" not in caps
        assert not any(c.startswith("game:") for c in caps)
        assert rig.control.status()["games"] == {"enabled": False}
        ok, message = await rig.control.act("game_start", {"game": "quiz"})
        assert not ok and "no tiene juegos" in message
        ok, message = await rig.control.act("set_game_enabled", {"game": "quiz", "enabled": False})
        assert not ok and "no tiene juegos" in message
        ok, message = await rig.control.act("set_game_bank", {"bank": "quiz_preguntas", "text": ""})
        assert not ok
        ok, message = await rig.control.act("game_stop", {})
        assert ok and "No hay" in message
        # Los ajustes compartidos van igual a la nube aunque esta Sonnia no tenga juegos.
        values = rig.control.shared_settings()
        assert values["games_off"] == [] and values["game_banks"] is None


# ---------------------------------------------------------------------------
# Capacidades y estado
# ---------------------------------------------------------------------------


async def test_capacidades_segun_lo_que_anuncia_la_pantalla(tmp_path: Path) -> None:
    write_app_bank(tmp_path)
    async with make_panel_rig(tmp_path, games=GAMES) as rig:
        caps = rig.control.capabilities
        assert "games" in caps and "game_banks" in caps
        # Hasta que la pantalla no anuncia sus juegos, no hay botones de empezar.
        assert not any(c.startswith("game:") for c in caps)
        status = games_status(rig)
        assert status["enabled"] is True and status["active"] is None
        assert status["unity_games"] is None
        assert game_entry(rig, "quiz")["reason"] == "La pantalla es de una versión sin juegos."

        # Una pantalla que solo sabe pintar el quiz.
        await unity_hello(rig, ["quiz"])
        caps = rig.control.capabilities
        assert "game:quiz" in caps and "game:camara" not in caps
        quiz, camera = game_entry(rig, "quiz"), game_entry(rig, "camara")
        assert (
            quiz["available"] is True and quiz["off"] is False and quiz["title"] == "Quiz de prueba"
        )
        assert camera["available"] is False and "versión anterior" in camera["reason"]

        # Con las dos, el juego de cámara sigue sin poderse: esta Sonnia no tiene cámara USB.
        await unity_hello(rig, ["quiz", "camara"])
        assert "game:camara" in rig.control.capabilities
        camera = game_entry(rig, "camara")
        assert camera["available"] is False and "cámara" in camera["reason"]
        assert camera["needs"] == ["camera"]
        banks = games_status(rig)["banks"]
        assert banks == [
            {
                "id": "quiz_preguntas",
                "game": "quiz",
                "title": "Preguntas del quiz",
                "file": "assets/games/quiz/preguntas.md",
                "min_entries": 3,
                "source": "app",
            }
        ]


# ---------------------------------------------------------------------------
# Empezar y terminar
# ---------------------------------------------------------------------------


async def test_empezar_y_terminar_un_juego_desde_el_panel(tmp_path: Path) -> None:
    write_app_bank(tmp_path)
    async with make_panel_rig(tmp_path, games=GAMES) as rig:
        conn = await rig.conn()
        await unity_hello(rig, ["quiz", "camara"])

        ok, message = await rig.control.act("game_start", {"game": "nada"})
        assert not ok and "no está en esta Sonnia" in message
        ok, message = await rig.control.act("game_start", {"game": "camara"})
        assert not ok and "cámara" in message

        ok, message = await rig.control.act("game_start", {"game": "quiz"})
        assert ok and "Quiz de prueba en marcha" in message, message
        await rig.rec.wait_type(p.MSG_GAME)
        start = rig.rec.of_type(p.MSG_GAME)[0]
        assert start["game"] == "quiz" and start["event"] == "start"
        assert start["data"] == {
            "title": "Quiz de prueba",
            "question": "¿Qué lenguaje usa Flutter?",
        }
        # Las reglas por instrucciones y el arranque, por commentary en cuanto calla.
        await conn.wait_type("session.instructions.append")
        await conn.wait_type("session.commentary.append")
        spoken = conn.of_type("session.commentary.append")[-1]["content"]
        assert "el equipo del stand ha puesto el quiz de prueba" in spoken
        status = games_status(rig)
        assert status["active"] == "quiz" and status["phase"] == "playing"
        assert status["title"] == "Quiz de prueba"
        assert status["state"]["summary"] == "Pregunta 1 de 3"

        # Mientras se juega no empieza otro ni la trivia.
        ok, message = await rig.control.act("game_start", {"game": "quiz"})
        assert ok and "ya está en marcha" in message
        ok, message = await rig.control.act("trivia_start", {})
        assert not ok

        ok, message = await rig.control.act("game_stop", {})
        assert ok and "terminado" in message
        await rig.rec.wait_for(
            lambda msgs: any(m["event"] == "end" for m in rig.rec.of_type(p.MSG_GAME, msgs))
        )
        end = [m for m in rig.rec.of_type(p.MSG_GAME) if m["event"] == "end"][-1]
        assert end["data"]["result"] == "cancel"
        assert games_status(rig)["active"] is None and games_status(rig)["phase"] == "off"
        ok, message = await rig.control.act("game_stop", {})
        assert ok and "No hay" in message


async def test_los_juegos_piden_lo_mismo_que_la_trivia(tmp_path: Path) -> None:
    write_app_bank(tmp_path)
    async with make_panel_rig(tmp_path, games=GAMES) as rig:
        await rig.conn()
        await unity_hello(rig, ["quiz"])
        await rig.control.act("set_debug", {"enabled": True})
        ok, message = await rig.control.act("game_start", {"game": "quiz"})
        assert not ok and "debug" in message
        await rig.control.act("set_debug", {"enabled": False})
        await rig.control.act("set_mode", {"mode": "greeter"})
        ok, message = await rig.control.act("game_start", {"game": "quiz"})
        assert not ok and "Conversando" in message
        await rig.control.act("set_mode", {"mode": "away"})
        ok, message = await rig.control.act("game_start", {"game": "quiz"})
        assert not ok and "fuera" in message
        assert games_status(rig)["active"] is None


async def test_con_la_trivia_en_marcha_no_empieza_un_juego(tmp_path: Path) -> None:
    write_app_bank(tmp_path)
    (tmp_path / "trivia").mkdir()
    (tmp_path / "trivia" / "preguntas.md").write_text(TRIVIA_BANK, encoding="utf-8")
    async with make_panel_rig(tmp_path, games=GAMES) as rig:
        rig.settings.trivia.questions = 2
        await rig.conn()
        await unity_hello(rig, ["quiz"])
        ok, message = await rig.control.act("trivia_start", {})
        assert ok, message
        ok, message = await rig.control.act("game_start", {"game": "quiz"})
        assert not ok and "trivia" in message
        assert games_status(rig)["active"] is None


# ---------------------------------------------------------------------------
# Interruptores (games_off)
# ---------------------------------------------------------------------------


async def test_apagar_un_juego_lo_guarda_en_la_nube_y_no_se_puede_empezar(tmp_path: Path) -> None:
    write_app_bank(tmp_path)
    async with make_panel_rig(tmp_path, games=GAMES) as rig:
        await rig.conn()
        await unity_hello(rig, ["quiz", "camara"])
        ok, message = await rig.control.act("set_game_enabled", {"game": "quiz"})
        assert not ok  # falta enabled
        ok, message = await rig.control.act("set_game_enabled", {"game": "otro", "enabled": False})
        assert not ok and "no está en esta Sonnia" in message

        ok, message = await rig.control.act("set_game_enabled", {"game": "quiz", "enabled": False})
        assert ok and "apagado" in message, message
        assert rig.control.state.games_off == ["quiz"]
        assert rig.control.shared_settings()["games_off"] == ["quiz"]
        status = rig.control.status()
        assert status["settings_sync"]["pending"] == ["games_off"]
        assert status["games"]["games_off"] == ["quiz"]
        quiz = game_entry(rig, "quiz")
        assert quiz["off"] is True and quiz["available"] is False
        # Apagado sigue en las capacidades (para volver a encenderlo), pero no empieza.
        assert "game:quiz" in rig.control.capabilities
        ok, message = await rig.control.act("game_start", {"game": "quiz"})
        assert not ok and "apagado" in message

        ok, message = await rig.control.act("set_game_enabled", {"game": "quiz", "enabled": True})
        assert ok and "encendido" in message
        assert rig.control.state.games_off == []
        ok, message = await rig.control.act("game_start", {"game": "quiz"})
        assert ok, message

        # Apagar el que se está jugando lo termina.
        ok, message = await rig.control.act("set_game_enabled", {"game": "quiz", "enabled": False})
        assert ok and "se ha terminado" in message, message
        await rig.rec.wait_for(
            lambda msgs: any(m["event"] == "end" for m in rig.rec.of_type(p.MSG_GAME, msgs))
        )
        assert games_status(rig)["active"] is None
    saved = PanelState.load(tmp_path / "cache" / "panel_state.json")
    assert saved.games_off == ["quiz"] and "games_off" in saved.pending_settings


async def test_los_ajustes_de_los_juegos_llegan_de_la_nube(tmp_path: Path) -> None:
    write_app_bank(tmp_path)
    async with make_panel_rig(tmp_path, games=GAMES) as rig:
        await rig.conn()
        await unity_hello(rig, ["quiz", "camara"])
        values = rig.control.shared_settings()
        # Lo que manda la nube; «sudoku» es de otra Sonnia más nueva: se guarda sin tocarlo.
        changed = await rig.control.apply_cloud_settings(
            {
                **values,
                "games_off": ["quiz", "sudoku", "NO VALE", 3],
                "game_banks": {"quiz_preguntas": CLOUD_BANK, "sudoku_tableros": "## 1\n> 2\n"},
            },
            rev=5,
            ack=0,
        )
        assert sorted(changed) == ["game_banks", "games_off"]
        assert rig.control.state.games_off == ["quiz", "sudoku"]
        manager = rig.engine.games
        assert manager is not None
        assert manager.games_off == frozenset({"quiz", "sudoku"})
        assert manager.cloud_banks["quiz_preguntas"] == CLOUD_BANK
        assert games_status(rig)["banks"][0]["source"] == "cloud"
        assert game_entry(rig, "quiz")["off"] is True
        ok, text = await rig.control.act("game_bank", {"bank": "quiz_preguntas"})
        assert ok and text == CLOUD_BANK

        # Lo mal formado de la nube se ignora y deja lo que había.
        changed = await rig.control.apply_cloud_settings(
            {"games_off": "quiz", "game_banks": 5}, rev=6, ack=0
        )
        assert changed == []
        assert rig.control.state.games_off == ["quiz", "sudoku"]

        # La nube lo vacía: todo encendido y los bancos de la app.
        changed = await rig.control.apply_cloud_settings(
            {"games_off": [], "game_banks": None}, rev=7, ack=0
        )
        assert sorted(changed) == ["game_banks", "games_off"]
        assert manager.games_off == frozenset() and manager.cloud_banks == {}
        assert games_status(rig)["banks"][0]["source"] == "app"
    saved = PanelState.load(tmp_path / "cache" / "panel_state.json")
    assert saved.games_off == [] and saved.game_banks is None and saved.cloud_rev == 7


async def test_los_ajustes_de_los_juegos_sobreviven_al_reinicio(tmp_path: Path) -> None:
    write_app_bank(tmp_path)
    state = PanelState(games_off=["camara"], game_banks={"quiz_preguntas": CLOUD_BANK})
    async with make_panel_rig(tmp_path, games=GAMES, state=state) as rig:
        manager = rig.engine.games
        assert manager is not None
        assert manager.games_off == frozenset({"camara"})
        assert manager.cloud_banks == {"quiz_preguntas": CLOUD_BANK}
        assert games_status(rig)["games_off"] == ["camara"]


# ---------------------------------------------------------------------------
# Bancos de los juegos (game_banks)
# ---------------------------------------------------------------------------


async def test_bancos_de_los_juegos_desde_el_panel(tmp_path: Path) -> None:
    write_app_bank(tmp_path)
    async with make_panel_rig(tmp_path, games=GAMES) as rig:
        ok, text = await rig.control.act("game_bank", {"bank": "quiz_preguntas"})
        assert ok and text == APP_BANK
        ok, message = await rig.control.act("game_bank", {"bank": "no_existe"})
        assert not ok and "no_existe" in message
        ok, message = await rig.control.act("game_bank", {"bank": "Mal Id"})
        assert not ok

        # Con pocas entradas válidas no se guarda.
        ok, message = await rig.control.act(
            "set_game_bank", {"bank": "quiz_preguntas", "text": "## ¿Una?\n> Sí\n\n## ¿Dos?\n"}
        )
        assert not ok and "solo hay 1" in message and "hacen falta 3" in message, message
        # Ni de más de 15 000 caracteres.
        huge = CLOUD_BANK + "\n<!-- " + "x" * BANK_MAX_CHARS + " -->"
        ok, message = await rig.control.act(
            "set_game_bank", {"bank": "quiz_preguntas", "text": huge}
        )
        assert not ok and str(BANK_MAX_CHARS) in message
        ok, message = await rig.control.act("set_game_bank", {"bank": "quiz_preguntas", "text": 7})
        assert not ok
        assert rig.control.status()["settings_sync"]["pending"] == []
        assert rig.control.state.game_banks is None

        ok, message = await rig.control.act(
            "set_game_bank", {"bank": "quiz_preguntas", "text": f"\n{CLOUD_BANK}\n"}
        )
        assert ok and "3 entradas válidas" in message and "Se saltó 1" in message, message
        assert rig.control.state.game_banks == {"quiz_preguntas": CLOUD_BANK.strip()}
        status = rig.control.status()
        assert status["settings_sync"]["pending"] == ["game_banks"]
        assert status["games"]["banks"][0]["source"] == "cloud"
        ok, text = await rig.control.act("game_bank", {"bank": "quiz_preguntas"})
        assert ok and text == CLOUD_BANK.strip()
        manager = rig.engine.games
        assert manager is not None
        assert manager.read_bank("quiz", QUESTIONS) == [
            "¿Qué es Kotlin?",
            "¿Qué es Android?",
            "¿Qué es Firebase?",
        ]

        # «Volver al de la app» borra la de la nube.
        ok, message = await rig.control.act(
            "set_game_bank", {"bank": "quiz_preguntas", "text": " "}
        )
        assert ok and "vuelve el de la app" in message
        assert rig.control.state.game_banks is None
        assert rig.control.status()["games"]["banks"][0]["source"] == "app"
        ok, text = await rig.control.act("game_bank", {"bank": "quiz_preguntas"})
        assert ok and text == APP_BANK
        ok, message = await rig.control.act("set_game_bank", {"bank": "quiz_preguntas", "text": ""})
        assert ok
    saved = PanelState.load(tmp_path / "cache" / "panel_state.json")
    assert saved.game_banks is None


async def test_un_banco_sin_texto_se_abre_con_una_nota(tmp_path: Path) -> None:
    # Sin archivo en la app ni banco en la nube: el editor no se abre con «Listo.».
    async with make_panel_rig(tmp_path, games=GAMES) as rig:
        ok, text = await rig.control.act("game_bank", {"bank": "quiz_preguntas"})
        assert ok and text == EMPTY_GAME_BANK
        assert parse_questions(text).entries == []


async def test_guardar_un_banco_respeta_los_bancos_de_otras_sonnias(tmp_path: Path) -> None:
    write_app_bank(tmp_path)
    other = {"sudoku_tableros": "## 1\n> 2\n"}
    async with make_panel_rig(tmp_path, games=GAMES, state=PanelState(game_banks=other)) as rig:
        ok, message = await rig.control.act(
            "set_game_bank", {"bank": "quiz_preguntas", "text": CLOUD_BANK}
        )
        assert ok, message
        assert rig.control.state.game_banks == {**other, "quiz_preguntas": CLOUD_BANK.strip()}
        ok, message = await rig.control.act("set_game_bank", {"bank": "quiz_preguntas", "text": ""})
        assert ok
        assert rig.control.state.game_banks == other


async def test_un_banco_que_no_cabe_en_la_nube_no_se_guarda(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_app_bank(tmp_path)
    async with make_panel_rig(tmp_path, games=GAMES) as rig:
        used = len(
            json.dumps(rig.control.shared_settings(), ensure_ascii=False, separators=(",", ":"))
        )
        monkeypatch.setattr(control_module, "SHARED_SETTINGS_MAX_CHARS", used + 20)
        ok, message = await rig.control.act(
            "set_game_bank", {"bank": "quiz_preguntas", "text": CLOUD_BANK}
        )
        assert not ok and "No cabe en la nube" in message, message
        assert rig.control.state.game_banks is None
        assert rig.control.status()["settings_sync"]["pending"] == []


# ---------------------------------------------------------------------------
# Frases fijas de los juegos en «Preparar voces»
# ---------------------------------------------------------------------------


async def test_preparar_voces_graba_tambien_las_frases_de_los_juegos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sonia.live.oneshot as oneshot
    from tests.test_live import FakeConn

    monkeypatch.setattr(oneshot, "SAY_END_GAP_S", 0.2)
    write_app_bank(tmp_path)
    async with make_panel_rig(tmp_path, games=GAMES) as rig:
        game_phrases = [START_PHRASE, "Primera pregunta: ¿Qué lenguaje usa Flutter?"]
        # Las del stand ya están grabadas: solo faltan las de los juegos.
        for text in rig.control._material.all_texts():
            write_clip(rig.cache, text)
        await wait_until(lambda: rig.control.status()["voice_cache"]["total"] == 4)
        cache = rig.control.status()["voice_cache"]
        assert cache["ready"] == 2 and cache["total"] == 4

        async def react(conn: FakeConn, message: dict[str, Any]) -> None:
            if message["type"] == "session.commentary.append":
                await conn.audio(pcm(12_000, 900))

        rig.server.on_message = react
        ok, message = await rig.control.act("prepare_voices", {})
        assert ok and "Grabando 2 frases" in message, message
        await wait_until(lambda: all(rig.cache.has(t) for t in game_phrases), limit=10.0)
        await wait_until(lambda: rig.control.status()["voice_cache"]["ready"] == 4)

        # Las frases que salen del banco cambian con él: la de Kotlin aún no está grabada.
        ok, _ = await rig.control.act(
            "set_game_bank", {"bank": "quiz_preguntas", "text": CLOUD_BANK}
        )
        assert ok
        await wait_until(lambda: rig.control.status()["voice_cache"]["ready"] == 3)
        assert rig.control.status()["voice_cache"]["total"] == 4
        ok, message = await rig.control.act("prepare_voices", {})
        assert ok and "Grabando 1 frases" in message, message
        await wait_until(lambda: rig.cache.has("Primera pregunta: ¿Qué es Kotlin?"), limit=10.0)


# ---------------------------------------------------------------------------
# Modelo de poses (games_pose_model)
# ---------------------------------------------------------------------------


class PoseModelCalls:
    """``GameManager.set_pose_model`` falso: apunta las variantes que le llegan
    (``None``: el de la app, ``GAME_POSES_MODEL``)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[str | None] = []
        calls = self.calls

        def set_pose_model(manager: GameManager, variant: str | None) -> None:
            calls.append(variant)

        monkeypatch.setattr(GameManager, "set_pose_model", set_pose_model, raising=False)


async def test_el_modelo_de_poses_se_cambia_desde_el_panel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pose = PoseModelCalls(monkeypatch)
    async with make_panel_rig(tmp_path, games=GAMES) as rig:
        # Al arrancar, el de la app.
        assert pose.calls == [None]
        assert rig.control.status()["games_pose_model"] is None

        ok, message = await rig.control.act("set_game_pose_model", {"model": "s"})
        assert ok and "preciso" in message, message
        assert pose.calls[-1] == "s"
        assert rig.control.state.games_pose_model == "s"
        assert rig.control.shared_settings()["games_pose_model"] == "s"
        status = rig.control.status()
        assert status["games_pose_model"] == "s"
        assert status["settings_sync"]["pending"] == ["games_pose_model"]

        ok, message = await rig.control.act("set_game_pose_model", {"model": "xl"})
        assert not ok and pose.calls[-1] == "s"
        ok, message = await rig.control.act("set_game_pose_model", {"model": 3})
        assert not ok

        # «Volver al de la app» borra el ajuste.
        ok, message = await rig.control.act("set_game_pose_model", {"model": ""})
        assert ok and "app" in message
        assert pose.calls[-1] is None and rig.control.state.games_pose_model is None
        ok, message = await rig.control.act("set_game_pose_model", {"model": "app"})
        assert ok and "ya usan" in message
    saved = PanelState.load(tmp_path / "cache" / "panel_state.json")
    assert saved.games_pose_model is None


async def test_el_modelo_de_poses_llega_de_la_nube_y_sobrevive_al_reinicio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pose = PoseModelCalls(monkeypatch)
    state = PanelState(games_pose_model="s")
    async with make_panel_rig(tmp_path, games=GAMES, state=state) as rig:
        assert pose.calls == ["s"]
        assert rig.control.status()["games_pose_model"] == "s"
        values = rig.control.shared_settings()
        changed = await rig.control.apply_cloud_settings(
            {**values, "games_pose_model": "n"}, rev=2, ack=0
        )
        assert changed == ["games_pose_model"] and pose.calls[-1] == "n"
        # Lo que no es un modelo se ignora.
        changed = await rig.control.apply_cloud_settings({"games_pose_model": "xxl"}, rev=3, ack=0)
        assert changed == [] and rig.control.state.games_pose_model == "n"
        changed = await rig.control.apply_cloud_settings({"games_pose_model": None}, rev=4, ack=0)
        assert changed == ["games_pose_model"] and pose.calls[-1] is None


async def test_sin_juegos_no_se_cambia_el_modelo_de_poses(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path, games=[]) as rig:
        ok, message = await rig.control.act("set_game_pose_model", {"model": "s"})
        assert not ok and "no tiene juegos" in message
        assert rig.control.state.games_pose_model is None


# ---------------------------------------------------------------------------
# Compatibilidad
# ---------------------------------------------------------------------------


def test_los_ajustes_de_los_juegos_son_compartidos_y_un_estado_viejo_carga(tmp_path: Path) -> None:
    assert {"games_off", "game_banks", "games_pose_model"} <= set(SHARED_SETTINGS)
    # El estado de una Sonnia anterior a los juegos (sin las claves nuevas).
    path = tmp_path / "panel_state.json"
    path.write_text(json.dumps({"mode": "greeter", "volume": 0.5}), encoding="utf-8")
    state = PanelState.load(path)
    assert state.games_off == [] and state.game_banks is None and state.mode == "greeter"
    assert state.games_pose_model is None
    # Lo mal formado en disco no rompe la carga.
    path.write_text(
        json.dumps({"games_off": "quiz", "game_banks": ["x"], "games_pose_model": "z"}),
        encoding="utf-8",
    )
    state = PanelState.load(path)
    assert state.games_off == [] and state.game_banks is None and state.games_pose_model is None
    # Y lo bueno vuelve igual.
    PanelState(
        games_off=["quiz"], game_banks={"quiz_preguntas": CLOUD_BANK}, games_pose_model="s"
    ).save(path)
    state = PanelState.load(path)
    assert state.games_off == ["quiz"] and state.game_banks == {"quiz_preguntas": CLOUD_BANK}
    assert state.games_pose_model == "s"


def test_los_controles_de_los_juegos_llevan_su_capacidad() -> None:
    """Con una Sonnia anterior a los juegos (sin ``games`` ni ``game_banks`` en sus
    capacidades), el panel nuevo los deja desactivados y enseña la nota."""
    page = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    script = (STATIC_DIR / "panel.js").read_text(encoding="utf-8")
    for element in ("game-stop-btn",):
        assert re.search(rf'id="{element}"[^>]*data-cap="games"', page), element
    for element in (
        "game-bank-select",
        "game-bank-load-btn",
        "game-bank-input",
        "game-bank-save-btn",
        "game-bank-reset-btn",
    ):
        assert re.search(rf'id="{element}"[^>]*data-cap="game_banks"', page), element
    assert 'data-cap-note="games"' in page and 'data-cap-note="game_banks"' in page
    # El modelo de poses, solo en las Sonnias que lo anuncian.
    assert re.search(r'id="game-pose-select"[^>]*data-cap="game_pose_model"', page)
    assert 'data-cap-note="game_pose_model"' in page
    # Los botones de cada juego se crean con su capacidad (game:<id>) y los interruptores
    # con la de los juegos.
    assert '"data-cap": `game:${game.id}`' in script
    assert '"data-cap": "games"' in script
    for action in (
        "game_start",
        "game_stop",
        "set_game_enabled",
        "game_bank",
        "set_game_bank",
        "set_game_pose_model",
    ):
        assert f'"{action}"' in script, action
    # El editor no deja escribir más de lo que acepta el orquestador.
    assert re.search(rf'id="game-bank-input"[^>]*maxlength="{BANK_MAX_CHARS}"', page)
