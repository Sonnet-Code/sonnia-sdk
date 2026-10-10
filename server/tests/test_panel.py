"""Pruebas del panel de control: modos, acciones, estado, seguridad y caché de voces.

Sin red ni clave: GPT-Live es el servidor falso de ``test_live`` y el panel se
levanta de verdad en un puerto libre de 127.0.0.1.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import wave
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest

from sonia.actions import build_default_registry
from sonia.config import PanelSettings, Settings
from sonia.games.base import Game
from sonia.live.engine import LiveEngine
from sonia.live.voicecache import VoiceCache
from sonia.panel.control import (
    DEFAULT_AWAY_MESSAGE,
    TRIAL_OVER_MESSAGE,
    PanelState,
    StandControl,
    _Material,
    merge_tuning,
)
from sonia.panel.logs import LogBuffer
from sonia.panel.server import AccessVerifier, PanelServer
from sonia.vision.presence import PresenceWatch
from sonia.ws.hub import Hub
from tests.helpers import Recorder
from tests.test_live import (
    RATE,
    FakeConn,
    FakeLiveServer,
    NoCamera,
    make_settings,
    pcm,
    pcm_level,
    running,
    voice_block,
    wait_until,
)

GREETING = "¡Hola, bienvenidos al DevFest!"
SONG = "¡Lalalá, esto es DevFest!"


def write_clip(cache: VoiceCache, text: str, samples: int = 4_800) -> bytes:
    """Deja una frase "grabada" en la caché sin pasar por GPT-Live."""
    data = pcm(samples, 321)
    path = cache.path_for(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(data)
    return data


def panel_settings(tmp_path: Path, **overrides: Any) -> Settings:
    settings = make_settings(tmp_path, **overrides)
    settings.panel = PanelSettings(
        port=0,
        state_file=str(tmp_path / "cache" / "panel_state.json"),
        voice_cache_dir=str(tmp_path / "cache" / "voice"),
        greeter_interval_min_seconds=60,
        greeter_interval_max_seconds=60,
    )
    return settings


@dataclass
class PanelRig:
    settings: Settings
    server: FakeLiveServer
    engine: LiveEngine
    control: StandControl
    hub: Hub
    rec: Recorder
    cache: VoiceCache
    client: Any

    async def conn(self, count: int = 1) -> FakeConn:
        conn = await self.server.wait_conn(count)
        await wait_until(lambda: self.engine.session_id == f"sess_{count}")
        return conn


@contextlib.asynccontextmanager
async def make_panel_rig(
    tmp_path: Path,
    *,
    state: PanelState | None = None,
    material: _Material | None = None,
    trial_minutes: float = 0.0,
    presence: PresenceWatch | None = None,
    games: Sequence[type[Game]] | None = None,
    **overrides: Any,
) -> AsyncIterator[PanelRig]:
    """Panel, motor y hub de verdad contra el GPT-Live falso, con un cliente que hace de
    Unity. ``games``: los juegos del motor (por defecto, los encendidos del registro)."""
    from websockets.asyncio.client import connect

    settings = panel_settings(tmp_path, **overrides)
    settings.trial_limit_minutes = trial_minutes
    if state is not None:
        state.save(Path(settings.panel.state_file))
    server = FakeLiveServer()
    registry = build_default_registry(include_look=False)
    hub = Hub(settings.ws, sample_rate=RATE)
    async with running(server) as live_connect, hub:
        # Si algo graba voces (el calentamiento a los 20 s, «say» en modo saludos),
        # lo hace contra el GPT-Live falso: ni una conexión a OpenAI.
        cache = VoiceCache(settings.panel.voice_cache_dir, settings.live, connect=live_connect)
        engine = LiveEngine(
            settings,
            hub=hub,
            registry=registry,
            connect=live_connect,
            knowledge_dir=tmp_path,
            voice_cache=cache,
            presence=presence,
            games=games,
            tick_s=0.02,
        )
        control = StandControl(
            settings,
            hub=hub,
            registry=registry,
            engine=engine,
            voice_cache=cache,
            material=material or _Material(greetings=[GREETING], phrases=[], songs=[SONG]),
        )
        async with connect(f"ws://127.0.0.1:{hub.port}/") as client:
            rec = Recorder(client)
            await control.start()
            task = asyncio.create_task(engine.run())
            try:
                yield PanelRig(settings, server, engine, control, hub, rec, cache, client)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                await control.stop()
                await rec.close()


# ---------------------------------------------------------------------------
# Modos
# ---------------------------------------------------------------------------


async def test_fuera_cierra_gpt_live_y_deja_el_letrero(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        conn = await rig.conn()
        ok, _ = await rig.control.act("set_away_message", {"text": "Vuelvo a las 3"})
        assert ok
        ok, message = await rig.control.act("set_mode", {"mode": "away"})
        assert ok and "letrero" in message
        await conn.wait_type("session.close")
        await rig.rec.wait_type("presence", count=2)
        presence = rig.rec.of_type("presence")[-1]
        assert presence == {"type": "presence", "present": False, "message": "Vuelvo a las 3"}
        assert rig.rec.of_type("hide_image")
        await wait_until(lambda: not rig.engine.connected)
        await asyncio.sleep(0.3)
        assert rig.server.attempts == 1  # apagada no reconecta: no gasta
        status = rig.control.status()
        assert status["mode"] == "away"
        assert status["health"]["internet"]["ok"] is None
        # Y vuelve: Sonia entra y se abre una sesión nueva.
        await rig.control.act("set_mode", {"mode": "conversation"})
        await rig.conn(2)
        assert rig.rec.of_type("presence")[-1]["present"] is True


async def test_la_build_de_prueba_se_apaga_al_acabar_su_tiempo(tmp_path: Path) -> None:
    # 0,01 minutos: 0,6 s de conversación.
    async with make_panel_rig(tmp_path, trial_minutes=0.01) as rig:
        conn = await rig.conn()
        await conn.wait_type("session.close", limit=4.0)
        await wait_until(lambda: not rig.engine.connected, limit=4.0)
        await wait_until(lambda: rig.rec.of_type("presence")[-1]["present"] is False, limit=4.0)
        assert rig.rec.of_type("presence")[-1]["message"] == TRIAL_OVER_MESSAGE
        # Ni el panel la devuelve a conversar.
        ok, message = await rig.control.act("set_mode", {"mode": "conversation"})
        assert not ok and "prueba" in message
        ok, _ = await rig.control.act("greet", {})
        assert not ok
        assert rig.control.status()["mode"] == "away"
        await asyncio.sleep(0.3)
        assert rig.server.attempts == 1
    saved = PanelState.load(tmp_path / "cache" / "panel_state.json")
    assert saved.trial_seconds >= 0.6 and saved.mode == "away"

    # Al volver a abrir la app sigue fuera, con el letrero, y no abre sesión.
    async with make_panel_rig(tmp_path, trial_minutes=0.01) as rig:
        await rig.rec.wait_type("presence")
        assert rig.rec.of_type("presence")[-1] == {
            "type": "presence",
            "present": False,
            "message": TRIAL_OVER_MESSAGE,
        }
        await asyncio.sleep(0.5)
        assert rig.server.attempts == 0


async def test_sin_limite_de_prueba_conversa_igual(tmp_path: Path) -> None:
    usada = PanelState(trial_seconds=99_999.0)
    async with make_panel_rig(tmp_path, state=usada) as rig:
        await rig.conn()
        assert rig.rec.of_type("presence")[-1]["present"] is True
        assert not rig.control.trial_over


async def test_solo_saludos_reproduce_frases_grabadas_sin_gpt_live(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        await rig.conn()
        clip = write_clip(rig.cache, GREETING)
        await rig.control.act("set_mode", {"mode": "greeter"})
        await wait_until(lambda: not rig.engine.connected)
        ok, message = await rig.control.act("greet", {})
        assert ok and GREETING in message
        await rig.rec.wait_type("speech_end")
        assert rig.rec.of_type("attention")[-1]["category"] == "greeting"
        start = rig.rec.of_type("speech_start")[-1]
        assert start["ambient"] is True and start["text"] == GREETING
        assert b"".join(f[3] for f in rig.rec.audio(start["utterance_id"])) == clip
        assert "speaking" not in rig.rec.states()
        assert rig.server.attempts == 1


async def test_gpt_live_no_oye_la_frase_grabada_mientras_suena(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GPT-Live no dijo la frase grabada: si la oyera por los altavoces, la contestaría."""
    import numpy as np

    monkeypatch.setattr("sonia.live.engine.CLIP_ECHO_TAIL_S", 0.05)
    loud = np.full(768, 0.5, dtype=np.float32)
    async with make_panel_rig(tmp_path) as rig:
        conn = await rig.conn()
        write_clip(rig.cache, GREETING)
        ok, _ = await rig.control.act("greet", {})
        assert ok
        await rig.rec.wait_type("speech_end")
        await rig.engine.push_mic(loud)
        await conn.wait_type("session.input_audio.append")
        assert pcm_level(conn.audio_in()[-1]) < 0.01
        # Unity confirma que terminó de sonar: pasada la cola, GPT-Live vuelve a oír.
        rig.engine.notify_playback_done(rig.rec.of_type("speech_start")[-1]["utterance_id"])
        await asyncio.sleep(0.1)
        await rig.engine.push_mic(loud)
        await conn.wait_type("session.input_audio.append", count=2)
        assert pcm_level(conn.audio_in()[-1]) == pytest.approx(0.5, rel=0.01)


async def test_sin_frase_grabada_saluda_solo_con_el_gesto(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        await rig.control.act("set_mode", {"mode": "greeter"})
        ok, message = await rig.control.act("greet", {})
        assert ok and "Preparar voces" in message
        await rig.rec.wait_type("attention")
        assert not rig.rec.of_type("speech_start")


async def test_el_modo_guardado_se_aplica_al_arrancar_sin_conectar(tmp_path: Path) -> None:
    state = PanelState(mode="away", away_message="En una charla", volume=0.6)
    async with make_panel_rig(tmp_path, state=state) as rig:
        await asyncio.sleep(0.3)
        assert rig.server.attempts == 0
        assert rig.control.status()["mode"] == "away"
        # Una pantalla que se conecta ahora recibe el letrero y el volumen tras hello.
        from websockets.asyncio.client import connect

        async with connect(f"ws://127.0.0.1:{rig.hub.port}/") as late:
            # Tras hello llegan todos los mensajes fijos; el letrero, el último.
            kinds = [json.loads(await late.recv())]
            while kinds[-1]["type"] != "presence" and len(kinds) < 10:
                kinds.append(json.loads(await late.recv()))
        assert kinds[0]["type"] == "hello"
        assert {"type": "set_volume", "value": 0.6} in kinds
        assert {"type": "presence", "present": False, "message": "En una charla"} in kinds


async def test_los_cambios_del_panel_se_guardan(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        await rig.conn()
        await rig.control.act("set_volume", {"value": 3})
        await rig.control.act("set_mic_gate", {"value": 0.05})
        await rig.control.act("showcase", {"enabled": False})
        await rig.control.act("set_mode", {"mode": "greeter"})
    saved = PanelState.load(tmp_path / "cache" / "panel_state.json")
    assert saved.mode == "greeter"
    assert saved.volume == 1.5  # recortado al máximo
    assert saved.mic_gate == 0.05
    assert saved.showcase is False
    assert saved.away_message == DEFAULT_AWAY_MESSAGE


# ---------------------------------------------------------------------------
# Acciones
# ---------------------------------------------------------------------------


async def test_avisos_del_dia_llegan_a_la_sesion_y_a_las_siguientes(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        conn = await rig.conn()
        ok, _ = await rig.control.act("set_notes", {"text": "La charla de IA es en la sala B."})
        assert ok
        await conn.wait_type("session.instructions.append")
        assert "sala B" in conn.of_type("session.instructions.append")[0]["content"]
        await rig.control.act("restart", {})
        conn2 = await rig.conn(2)
        assert "sala B" in conn2.start["session"]["instructions"]
        assert "sala B" in conn2.start["session"]["delegation"]["responses"]["instructions"]


async def test_say_en_conversacion_va_como_commentary(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        conn = await rig.conn()
        ok, _ = await rig.control.act("say", {"text": "El almuerzo es a la una."})
        assert ok
        await conn.wait_type("session.commentary.append")
        assert "almuerzo" in conn.of_type("session.commentary.append")[0]["content"]


async def test_acciones_mal_formadas_no_rompen_nada(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        assert (await rig.control.act("volar", {}))[0] is False
        assert (await rig.control.act("set_mode", {"mode": "fiesta"}))[0] is False
        assert (await rig.control.act("say", {"text": "  "}))[0] is False
        assert (await rig.control.act("mute", {"muted": "sí"}))[0] is False
        assert (await rig.control.act("set_voice", {"voice": "robot"}))[0] is False
        await rig.control.act("set_mode", {"mode": "away"})
        ok, message = await rig.control.act("gesture", {"category": "dance"})
        assert not ok and "fuera" in message


async def test_animaciones_con_la_lista_que_manda_unity(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        ok, message = await rig.control.act("animation", {"clip": "Dance_HipHop"})
        assert not ok and "lista" in message
        await rig.client.send(
            json.dumps(
                {
                    "type": "animations",
                    "animations": [
                        {"clip": "Dance_HipHop", "group": "dance"},
                        {"clip": "Dance_HipHop", "group": "soft"},  # repetido: fuera
                        {"clip": "Shrug"},  # sin grupo: fuera
                        "basura",
                        {"clip": "ListeningNod", "group": "nod"},
                    ],
                }
            )
        )
        await wait_until(lambda: bool(rig.control.status()["animations"]))
        assert rig.control.status()["animations"] == [
            {"clip": "Dance_HipHop", "group": "dance"},
            {"clip": "ListeningNod", "group": "nod"},
        ]
        assert "animations" in rig.control.status()["capabilities"]
        ok, message = await rig.control.act("animation", {"clip": "Dance_HipHop"})
        assert ok and "Dance_HipHop" in message
        await rig.rec.wait_type("play_animation")
        assert rig.rec.of_type("play_animation")[-1] == {
            "type": "play_animation",
            "clip": "Dance_HipHop",
        }
        ok, message = await rig.control.act("animation", {"clip": "Moonwalk"})
        assert not ok and "no está" in message
        await rig.control.act("set_mode", {"mode": "away"})
        ok, message = await rig.control.act("animation", {"clip": "Dance_HipHop"})
        assert not ok and "fuera" in message
        assert len(rig.rec.of_type("play_animation")) == 1


async def test_animaciones_desactivadas_se_guardan_y_llegan_a_unity(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        await rig.rec.wait_type("set_disabled_animations")
        assert rig.rec.of_type("set_disabled_animations")[-1]["clips"] == []
        ok, message = await rig.control.act(
            "set_animation_enabled", {"clip": "Dance_Gangnam", "enabled": False}
        )
        assert ok and "ya no" in message
        await rig.rec.wait_type("set_disabled_animations", count=2)
        assert rig.rec.of_type("set_disabled_animations")[-1]["clips"] == ["Dance_Gangnam"]
        assert rig.control.status()["disabled_animations"] == ["Dance_Gangnam"]
        assert "animation_toggles" in rig.control.status()["capabilities"]
        # Con la lista de Unity se rechaza lo que no existe.
        await rig.client.send(
            json.dumps(
                {"type": "animations", "animations": [{"clip": "Dance_Gangnam", "group": "dance"}]}
            )
        )
        await wait_until(lambda: bool(rig.control.status()["animations"]))
        ok, _ = await rig.control.act(
            "set_animation_enabled", {"clip": "Moonwalk", "enabled": False}
        )
        assert not ok
        saved = PanelState.load(Path(rig.settings.panel.state_file))
        assert saved.disabled_animations == ["Dance_Gangnam"]
        ok, _ = await rig.control.act(
            "set_animation_enabled", {"clip": "Dance_Gangnam", "enabled": True}
        )
        assert ok and rig.control.status()["disabled_animations"] == []


async def test_modo_debug_apaga_gpt_live_y_los_saludos(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        conn = await rig.conn()
        ok, message = await rig.control.act("set_debug", {"enabled": True})
        assert ok and "quieta" in message
        await conn.wait_type("session.close")
        await wait_until(lambda: not rig.engine.connected)
        assert rig.rec.of_type("set_debug")[-1] == {"type": "set_debug", "enabled": True}
        status = rig.control.status()
        assert status["debug"] is True and status["health"]["internet"]["ok"] is None
        # «Conversando» no abre GPT-Live mientras dure el modo debug.
        await rig.control.act("set_mode", {"mode": "greeter"})
        await rig.control.act("set_mode", {"mode": "conversation"})
        await asyncio.sleep(0.3)
        assert rig.server.attempts == 1
        # Ni el bucle de saludos: aunque toque saludar, no saluda.
        write_clip(rig.cache, GREETING)
        await rig.control.act("set_mode", {"mode": "greeter"})
        rig.control._next_greet_at = 0.0
        await asyncio.sleep(1.3)
        assert not rig.rec.of_type("speech_start")
        # Los botones del panel sí funcionan.
        ok, _ = await rig.control.act("greet", {})
        assert ok
        await rig.rec.wait_type("speech_start")
        # Al quitarlo vuelve lo normal: en «Conversando» se abre sesión.
        await rig.control.act("set_mode", {"mode": "conversation"})
        ok, _ = await rig.control.act("set_debug", {"enabled": False})
        assert ok
        await rig.conn(2)
        assert rig.rec.of_type("set_debug")[-1]["enabled"] is False


async def test_la_pantalla_sabe_si_sonia_puede_conversar(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        await rig.conn()

        def last() -> dict[str, object]:
            return rig.rec.of_type("stage_mode")[-1]

        await rig.rec.wait_type("stage_mode")
        assert last() == {"type": "stage_mode", "mode": "conversation", "talk": True}
        await rig.control.act("set_mode", {"mode": "greeter"})
        await rig.rec.wait_type("stage_mode", count=2)
        assert last() == {"type": "stage_mode", "mode": "greeter", "talk": False}
        await rig.control.act("set_mode", {"mode": "away"})
        await rig.rec.wait_type("stage_mode", count=3)
        assert last() == {"type": "stage_mode", "mode": "away", "talk": False}
        await rig.control.act("set_mode", {"mode": "conversation"})
        await rig.rec.wait_type("stage_mode", count=4)
        assert last() == {"type": "stage_mode", "mode": "conversation", "talk": True}
        # Con el modo debug GPT-Live se apaga: la pantalla deja de invitar a hablar.
        await rig.control.act("set_debug", {"enabled": True})
        await rig.rec.wait_type("stage_mode", count=5)
        assert last() == {"type": "stage_mode", "mode": "conversation", "talk": False}
        # Y es un mensaje fijo: una Unity que se conecta ahora lo recibe tras hello.
        assert rig.hub.sticky("stage_mode") == last()


async def test_el_estado_dice_que_animacion_suena(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        assert rig.control.status()["current_animation"] is None
        await rig.client.send(json.dumps({"type": "animation_playing", "clip": "Dance_Jazz"}))
        await wait_until(lambda: rig.control.status()["current_animation"] == "Dance_Jazz")
        await rig.client.send(json.dumps({"type": "animation_playing", "clip": None}))
        await wait_until(lambda: rig.control.status()["current_animation"] is None)


async def test_subtitulos_se_apagan_y_se_recuerdan(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        await rig.rec.wait_type("set_subtitles")
        assert rig.rec.of_type("set_subtitles")[-1]["enabled"] is True
        ok, message = await rig.control.act("set_subtitles", {"enabled": False})
        assert ok and "ocultos" in message
        await rig.rec.wait_type("set_subtitles", count=2)
        assert rig.rec.of_type("set_subtitles")[-1] == {"type": "set_subtitles", "enabled": False}
        assert rig.control.status()["subtitles"] is False
        ok, _ = await rig.control.act("set_subtitles", {"enabled": "no"})
        assert not ok
    # Tras un reinicio se aplica lo guardado, también a los Unity que se conecten después.
    state = PanelState.load(tmp_path / "cache" / "panel_state.json")
    assert state.subtitles is False
    async with make_panel_rig(tmp_path, state=state) as rig:
        await rig.rec.wait_type("set_subtitles")
        assert rig.rec.of_type("set_subtitles")[-1]["enabled"] is False


async def test_developer_ajusta_boca_y_camara_y_llega_a_unity(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        await rig.rec.wait_type("set_tuning")
        first = rig.rec.of_type("set_tuning")[-1]
        assert first["mouth"] == {"open": 1.0, "jaw": 1.0, "closure": 1.0, "speed": 1.0}
        assert first["camera"]["zoom"] == 1.0 and first["camera"]["height"] == 0.0
        assert first["idle"] == {"breath": 1.0, "accents": 1.0, "speed": 1.0}
        ok, _ = await rig.control.act(
            "set_tuning", {"mouth": {"open": 1.4, "nariz": 2}, "camera": {"height": 9, "zoom": 1.2}}
        )
        assert ok
        await rig.rec.wait_type("set_tuning", count=2)
        sent = rig.rec.of_type("set_tuning")[-1]
        assert sent["mouth"] == {"open": 1.4, "jaw": 1.0, "closure": 1.0, "speed": 1.0}
        assert sent["camera"]["height"] == 0.5  # recortado al máximo
        assert sent["camera"]["zoom"] == 1.2
        # Restablecer la cámara no toca la boca.
        ok, _ = await rig.control.act("reset_tuning", {"part": "camera"})
        assert ok
        tuning = rig.control.status()["tuning"]
        assert tuning["camera"]["height"] == 0.0 and tuning["mouth"]["open"] == 1.4
        for bad in ({}, {"mouth": 3}, {"camera": "alto"}, {"idle": [1]}):
            ok, _ = await rig.control.act("set_tuning", bad)
            assert not ok
        ok, _ = await rig.control.act("reset_tuning", {"part": "pies"})
        assert not ok
    # Se recuerda y, sin nube, queda pendiente de subir.
    state = PanelState.load(tmp_path / "cache" / "panel_state.json")
    assert state.tuning["mouth"]["open"] == 1.4
    assert state.pending_settings == ["tuning"]
    async with make_panel_rig(tmp_path, state=state) as rig:
        await rig.rec.wait_type("set_tuning")
        assert rig.rec.of_type("set_tuning")[-1]["mouth"]["open"] == 1.4


AVATAR = json.dumps({"JsonVersion": "2-0-0", "equippedAssetIds": ["AvatarBase/rec1"]})


async def test_el_editor_de_personaje_pausa_gpt_live_y_guarda_el_avatar(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        conn = await rig.conn()
        await rig.rec.wait_type("set_avatar")
        assert rig.rec.of_type("set_avatar")[-1] == {"type": "set_avatar", "definition": None}
        ok, message = await rig.control.act("open_avatar_editor", {})
        assert ok and "editor del personaje de Sonnia" in message
        await rig.rec.wait_type("open_avatar_editor")
        # Unity avisa de que ya está en la escena del editor: GPT-Live se cierra.
        await rig.client.send(json.dumps({"type": "avatar_editor", "open": True}))
        await conn.wait_type("session.close")
        await wait_until(lambda: not rig.engine.connected)
        assert rig.control.status()["avatar"] == {
            "custom": False,
            "editor_open": True,
            "editor_target": "sonia",
        }
        # Lo que no es una definición de Genies con piezas se ignora.
        for bad in ("[1, 2]", "{}", '{"JsonVersion": "2-0-0", "equippedAssetIds": []}'):
            await rig.client.send(json.dumps({"type": "avatar_saved", "definition": bad}))
        await rig.client.send(json.dumps({"type": "avatar_saved", "definition": AVATAR}))
        await rig.client.send(json.dumps({"type": "avatar_editor", "open": False}))
        await wait_until(lambda: rig.control.status()["avatar"]["custom"])
        await rig.rec.wait_for(
            lambda msgs: rig.rec.of_type("set_avatar", msgs)[-1]["definition"] == AVATAR
        )
        # Al salir del editor vuelve a conversar.
        await rig.conn(2)
        assert rig.control.status()["avatar"] == {
            "custom": True,
            "editor_open": False,
            "editor_target": "sonia",
        }
        assert rig.control.status()["settings_sync"]["pending"] == ["avatar"]
        ok, _ = await rig.control.act("close_avatar_editor", {})
        assert ok
        await rig.rec.wait_type("close_avatar_editor")
        # Volver al personaje de la app.
        ok, _ = await rig.control.act("reset_avatar", {})
        assert ok
        await rig.rec.wait_for(
            lambda msgs: rig.rec.of_type("set_avatar", msgs)[-1]["definition"] is None
        )
    # Lo último (el de la app) es lo que queda guardado.
    assert PanelState.load(tmp_path / "cache" / "panel_state.json").avatar is None


JEAN = json.dumps({"JsonVersion": "2-0-0", "equippedAssetIds": ["AvatarBase/recJean"]})


async def test_el_editor_tambien_edita_el_avatar_de_jean_sin_tocar_a_sonia(
    tmp_path: Path,
) -> None:
    async with make_panel_rig(tmp_path) as rig:
        await rig.conn()
        await rig.rec.wait_type("set_guest_avatar")
        assert rig.rec.of_type("set_guest_avatar")[-1] == {
            "type": "set_guest_avatar",
            "definition": None,
        }
        ok, message = await rig.control.act("open_avatar_editor", {"target": "guest"})
        assert ok and "de Jean" in message
        await rig.rec.wait_type("open_avatar_editor")
        assert rig.rec.of_type("open_avatar_editor")[-1] == {
            "type": "open_avatar_editor",
            "target": "guest",
        }
        await rig.client.send(
            json.dumps({"type": "avatar_editor", "open": True, "target": "guest"})
        )
        await wait_until(lambda: rig.control.status()["avatar"]["editor_open"])
        assert rig.control.status()["avatar"]["editor_target"] == "guest"
        # Una definición sin piezas no vale, tampoco para Jean.
        empty = json.dumps({"JsonVersion": "2-0-0", "equippedAssetIds": []})
        await rig.client.send(
            json.dumps({"type": "avatar_saved", "definition": empty, "target": "guest"})
        )
        await rig.client.send(
            json.dumps({"type": "avatar_saved", "definition": JEAN, "target": "guest"})
        )
        await wait_until(lambda: rig.control.status()["guest_avatar"]["custom"])
        await rig.rec.wait_for(
            lambda msgs: rig.rec.of_type("set_guest_avatar", msgs)[-1]["definition"] == JEAN
        )
        # Sonia no cambia y lo de Jean va a la nube como ajuste compartido aparte.
        assert rig.control.status()["avatar"]["custom"] is False
        assert rig.control.shared_settings()["guest_avatar"] == JEAN
        assert rig.control.shared_settings()["avatar"] is None
        assert rig.control.status()["settings_sync"]["pending"] == ["guest_avatar"]
        # Sin target (Unity antigua) sigue siendo Sonia.
        await rig.client.send(json.dumps({"type": "avatar_saved", "definition": AVATAR}))
        await wait_until(lambda: rig.control.status()["avatar"]["custom"])
        assert rig.control.shared_settings()["guest_avatar"] == JEAN
        # Volver al avatar de prueba de Jean.
        ok, message = await rig.control.act("reset_avatar", {"target": "guest"})
        assert ok and "Jean" in message
        await rig.rec.wait_for(
            lambda msgs: rig.rec.of_type("set_guest_avatar", msgs)[-1]["definition"] is None
        )
        assert rig.control.shared_settings()["avatar"] == AVATAR
        for bad in ({"target": "perro"},):
            ok, _ = await rig.control.act("open_avatar_editor", bad)
            assert not ok
    # El avatar de Jean se recuerda en disco como el de Sonia.
    assert PanelState.load(tmp_path / "cache" / "panel_state.json").guest_avatar is None


async def test_sin_pantalla_no_se_abre_el_editor_y_si_se_cierra_sonia_vuelve(
    tmp_path: Path,
) -> None:
    async with make_panel_rig(tmp_path) as rig:
        conn = await rig.conn()
        await rig.client.send(json.dumps({"type": "avatar_editor", "open": True}))
        await conn.wait_type("session.close")
        # La app de Unity se cierra con el editor abierto: Sonia vuelve a su modo.
        await rig.client.close()
        await rig.conn(2)
        assert rig.control.status()["avatar"]["editor_open"] is False
        ok, message = await rig.control.act("open_avatar_editor", {})
        assert not ok and "no está conectada" in message


async def test_developer_ajusta_el_movimiento_en_reposo(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        await rig.rec.wait_type("set_tuning")
        ok, _ = await rig.control.act(
            "set_tuning", {"idle": {"breath": 1.6, "accents": 5, "speed": 0.1}}
        )
        assert ok
        await rig.rec.wait_type("set_tuning", count=2)
        sent = rig.rec.of_type("set_tuning")[-1]
        # Recortado a sus límites; la boca y la cámara siguen como estaban.
        assert sent["idle"] == {"breath": 1.6, "accents": 2.0, "speed": 0.5}
        assert sent["mouth"]["open"] == 1.0 and sent["camera"]["zoom"] == 1.0
        ok, _ = await rig.control.act("set_tuning", {"mouth": {"open": 1.2}})
        assert ok
        # Restablecer el movimiento no toca la boca.
        ok, _ = await rig.control.act("reset_tuning", {"part": "idle"})
        assert ok
        tuning = rig.control.status()["tuning"]
        assert tuning["idle"] == {"breath": 1.0, "accents": 1.0, "speed": 1.0}
        assert tuning["mouth"]["open"] == 1.2


async def test_un_ajuste_guardado_sin_movimiento_recibe_sus_valores_por_defecto(
    tmp_path: Path,
) -> None:
    # Guardado por un orquestador anterior: boca y cámara, sin «idle».
    path = tmp_path / "panel_state.json"
    path.write_text(
        json.dumps({"tuning": {"mouth": {"open": 1.3}, "camera": {"zoom": 1.1}}}), encoding="utf-8"
    )
    state = PanelState.load(path)
    assert state.tuning["mouth"]["open"] == 1.3
    assert state.tuning["idle"] == {"breath": 1.0, "accents": 1.0, "speed": 1.0}
    assert merge_tuning({"mouth": {"open": 1.3}})["idle"]["speed"] == 1.0


async def test_el_estado_viejo_del_panel_carga_con_los_valores_nuevos_por_defecto(
    tmp_path: Path,
) -> None:
    path = tmp_path / "panel_state.json"
    path.write_text(json.dumps({"mode": "greeter", "volume": 0.7}), encoding="utf-8")
    state = PanelState.load(path)
    assert state.mode == "greeter" and state.subtitles is True
    assert state.disabled_animations == []
    assert state.tuning["camera"]["zoom"] == 1.0
    assert state.cloud_rev == 0 and state.pending_settings == []


async def test_silenciar_el_micro_manda_silencio(tmp_path: Path) -> None:
    import numpy as np

    async with make_panel_rig(tmp_path) as rig:
        conn = await rig.conn()
        await rig.control.act("mute", {"muted": True})
        await rig.engine.push_mic(np.full(768, 0.5, dtype=np.float32))
        await conn.wait_type("session.input_audio.append")
        assert pcm_level(conn.audio_in()[-1]) < 0.01
        health = rig.control.status()["health"]["mic"]
        assert health["ok"] is False and health["muted"] is True


# ---------------------------------------------------------------------------
# Servidor web
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def running_panel(
    rig: PanelRig, *, verifier: Any = None
) -> AsyncIterator[tuple[str, PanelServer]]:
    logs = LogBuffer()
    server = PanelServer(rig.settings.panel, rig.control, rig.hub, logs, verifier=verifier)
    await server.start()
    try:
        yield f"127.0.0.1:{server.port}", server
    finally:
        await server.stop()


async def test_el_servidor_sirve_estado_galeria_y_acciones(tmp_path: Path) -> None:
    (tmp_path / "gallery").mkdir(exist_ok=True)
    (tmp_path / "gallery" / "logo-sonnet.png").write_bytes(b"\x89PNG-logo")
    async with make_panel_rig(tmp_path) as rig, running_panel(rig) as (host, _):
        await rig.conn()
        async with httpx.AsyncClient(base_url=f"http://{host}") as http:
            status = (await http.get("/api/status")).json()
            assert status["engine"] == "live" and status["mode"] == "conversation"
            assert "modes" in status["capabilities"]
            page = await http.get("/")
            assert page.status_code == 200
            assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
            gallery = (await http.get("/api/gallery")).json()
            assert gallery == {"images": [{"id": "logo-sonnet", "url": "/api/gallery/logo-sonnet"}]}
            assert (await http.get("/api/gallery/logo-sonnet")).content == b"\x89PNG-logo"

            body = {"action": "show_image", "image_id": "logo-sonnet"}
            sin_cabecera = await http.post("/api/action", json=body)
            assert sin_cabecera.status_code == 403
            ok = await http.post("/api/action", json=body, headers={"X-Sonia-Panel": "1"})
            assert ok.status_code == 200 and ok.json()["ok"] is True
            assert (await http.get("/api/status")).json()["image"]["id"] == "logo-sonnet"
            malo = await http.post(
                "/api/action", json={"action": "volar"}, headers={"X-Sonia-Panel": "1"}
            )
            assert malo.status_code == 400


async def test_por_cloudflare_hace_falta_un_jwt_de_access(tmp_path: Path) -> None:
    async def verifier(token: str) -> bool:
        return token == "jwt-bueno"

    async with (
        make_panel_rig(tmp_path) as rig,
        running_panel(rig, verifier=verifier) as (host, _),
        httpx.AsyncClient(base_url=f"http://{host}") as http,
    ):
        cf = {"Cf-Connecting-Ip": "203.0.113.7", "Cf-Ray": "abc"}
        assert (await http.get("/api/status", headers=cf)).status_code == 403
        malo = {**cf, "Cf-Access-Jwt-Assertion": "jwt-malo"}
        assert (await http.get("/api/status", headers=malo)).status_code == 403
        bueno = {**cf, "Cf-Access-Jwt-Assertion": "jwt-bueno"}
        assert (await http.get("/api/status", headers=bueno)).status_code == 200
        cookie = {**cf, "Cookie": "CF_Authorization=jwt-bueno"}
        assert (await http.get("/api/status", headers=cookie)).status_code == 200
        # En local no hace falta.
        assert (await http.get("/api/status")).status_code == 200


async def test_sin_access_configurado_se_rechaza_todo_lo_remoto(tmp_path: Path) -> None:
    async with (
        make_panel_rig(tmp_path) as rig,
        running_panel(rig) as (host, _),
        httpx.AsyncClient(base_url=f"http://{host}") as http,
    ):
        remote = {"Cf-Connecting-Ip": "203.0.113.7", "Cf-Access-Jwt-Assertion": "x"}
        assert (await http.get("/", headers=remote)).status_code == 403


async def test_el_websocket_manda_historial_estado_y_mensajes(tmp_path: Path) -> None:
    from websockets.asyncio.client import connect
    from websockets.exceptions import InvalidStatus

    async with make_panel_rig(tmp_path) as rig, running_panel(rig) as (host, _):
        conn = await rig.conn()
        with pytest.raises(InvalidStatus):
            async with connect(f"ws://{host}/api/events", origin="https://otra-web.example"):  # type: ignore[arg-type]
                pass
        async with connect(f"ws://{host}/api/events", origin=f"http://{host}") as ws:  # type: ignore[arg-type]
            listing = json.loads(await ws.recv())
            assert listing["type"] == "instances" and len(listing["instances"]) == 1
            first = json.loads(await ws.recv())
            assert first["type"] == "history" and isinstance(first["logs"], list)
            second = json.loads(await ws.recv())
            assert second["type"] == "status" and second["status"]["mode"] == "conversation"
            await conn.hear("Hola Sonia")
            async with asyncio.timeout(3):
                while True:
                    item = json.loads(await ws.recv())
                    message = item.get("message") or {}
                    if message.get("type") == "transcript" and message.get("role") == "user":
                        assert "Hola Sonnia" in message["text"]
                        break


# ---------------------------------------------------------------------------
# Caché de voces y Access
# ---------------------------------------------------------------------------


async def test_la_cache_graba_con_gpt_live_y_separa_por_voz(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sonia.live.oneshot as oneshot

    monkeypatch.setattr(oneshot, "SAY_END_GAP_S", 0.2)
    server = FakeLiveServer()

    async def react(conn: FakeConn, message: dict[str, Any]) -> None:
        if message["type"] == "session.commentary.append":
            await conn.audio(pcm(12_000, 900))

    server.on_message = react
    settings = panel_settings(tmp_path)
    async with running(server) as connect:
        cache = VoiceCache(settings.panel.voice_cache_dir, settings.live, connect=connect)
        done = await cache.prepare([GREETING, GREETING, "  ", SONG])
    assert done == 2
    assert cache.get(GREETING) == pcm(12_000, 900)
    assert cache.count_ready([GREETING, SONG]) == 2
    settings.live.voice = "cedar"
    assert cache.get(GREETING) is None  # otra voz, otra grabación
    assert cache.missing([GREETING]) == [GREETING]


def test_access_verifier_valida_firma_audiencia_y_emisor() -> None:
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    team = "sonnetcode.cloudflareaccess.com"

    class FakeJWKClient:
        def get_signing_key_from_jwt(self, token: str) -> Any:
            return type("K", (), {"key": key.public_key()})()

    def token(**claims: Any) -> str:
        base = {"aud": ["aud-bueno"], "iss": f"https://{team}", "exp": int(time.time()) + 60}
        base.update(claims)
        return jwt.encode(base, key, algorithm="RS256")

    verifier = AccessVerifier(team, "aud-bueno")
    verifier._client = FakeJWKClient()
    assert asyncio.run(verifier(token())) is True
    assert asyncio.run(verifier(token(aud=["otra-app"]))) is False
    assert asyncio.run(verifier(token(iss="https://otro.cloudflareaccess.com"))) is False
    assert asyncio.run(verifier(token(exp=int(time.time()) - 10))) is False
    assert asyncio.run(AccessVerifier("", "")(token())) is False


async def test_la_cache_deja_de_grabar_tras_dos_fallos_seguidos(tmp_path: Path) -> None:
    server = FakeLiveServer(reject=True)
    settings = panel_settings(tmp_path)
    async with running(server) as connect:
        cache = VoiceCache(settings.panel.voice_cache_dir, settings.live, connect=connect)
        done = await cache.prepare(["uno", "dos", "tres", "cuatro"])
    assert done == 0
    assert server.attempts == 2
    assert "model_not_found" in cache.last_error


async def test_el_gasto_del_dia_sobrevive_al_reinicio_y_empieza_de_cero_cada_dia(
    tmp_path: Path,
) -> None:
    today = time.strftime("%Y-%m-%d")
    hoy = PanelState(usage_date=today, usage_seconds=600.0)
    async with make_panel_rig(tmp_path, state=hoy) as rig:
        await rig.conn()
        usage = rig.control.status()["usage"]
        assert usage["live_seconds"] >= 600.0
        assert usage["cost_usd"] == pytest.approx(0.5, abs=0.02)
    saved = PanelState.load(tmp_path / "cache" / "panel_state.json")
    assert saved.usage_date == today and saved.usage_seconds >= 600.0

    ayer = PanelState(usage_date="2026-10-02", usage_seconds=9_999.0)
    (tmp_path / "otro").mkdir()
    async with make_panel_rig(tmp_path / "otro", state=ayer) as rig:
        assert rig.control.status()["usage"]["live_seconds"] < 60.0


# ---------------------------------------------------------------------------
# Trivia
# ---------------------------------------------------------------------------

TRIVIA_BANK = """\
## ¿Primera?
- [x] Uno bien
- [ ] Uno mal
- [ ] Uno peor

## ¿Segunda?
- [ ] Dos mal
- [x] Dos bien
- [ ] Dos peor
"""


async def test_trivia_desde_el_panel(tmp_path: Path) -> None:
    (tmp_path / "trivia").mkdir()
    (tmp_path / "trivia" / "preguntas.md").write_text(TRIVIA_BANK, encoding="utf-8")
    async with make_panel_rig(tmp_path) as rig:
        rig.settings.trivia.questions = 2
        rig.settings.trivia.reveal_seconds = 30.0
        conn = await rig.conn()
        assert "trivia" in rig.control.capabilities
        assert rig.control.status()["trivia"]["available"] is True

        ok, message = await rig.control.act("trivia_start", {})
        assert ok, message
        await rig.rec.wait_type("trivia_question")
        await conn.wait_type("session.commentary.append")
        question = rig.rec.of_type("trivia_question")[0]
        assert question["question"] in conn.of_type("session.commentary.append")[-1]["content"]
        status = rig.control.status()["trivia"]
        assert (
            status["active"] and status["number"] == 1 and status["options"] == question["options"]
        )

        ok, message = await rig.control.act("trivia_answer", {"option": "Z"})
        assert not ok
        ok, message = await rig.control.act("trivia_answer", {"option": "B"})
        assert ok
        await rig.rec.wait_type("trivia_answer")
        assert rig.rec.of_type("trivia_answer")[0]["chosen"] == 1
        await conn.wait_type("session.commentary.append", count=2)
        assert "equipo del stand" in conn.of_type("session.commentary.append")[-1]["content"]

        ok, message = await rig.control.act("trivia_restart", {})
        assert ok and "primera pregunta" in message
        await rig.rec.wait_type("trivia_end")
        assert rig.rec.of_type("trivia_end")[0]["reason"] == "cancelled"
        assert rig.control.status()["trivia"]["number"] == 1
        rig.rec.messages.clear()

        # Al cambiar de modo se cierra GPT-Live y la partida se cancela.
        await rig.control.act("set_mode", {"mode": "greeter"})
        await rig.rec.wait_type("trivia_end")
        assert rig.rec.of_type("trivia_end")[0]["reason"] == "cancelled"
        ok, message = await rig.control.act("trivia_start", {})
        assert not ok and "Conversando" in message
        ok, message = await rig.control.act("trivia_stop", {})
        assert ok and "No hay" in message


async def test_banco_de_la_trivia_desde_el_panel(tmp_path: Path) -> None:
    (tmp_path / "trivia").mkdir()
    (tmp_path / "trivia" / "preguntas.md").write_text(TRIVIA_BANK, encoding="utf-8")
    async with make_panel_rig(tmp_path) as rig:
        rig.settings.trivia.questions = 2
        assert "trivia_bank" in rig.control.capabilities
        status = rig.control.status()["trivia"]
        assert status["bank_source"] == "app" and status["bank"] == 2

        ok, text = await rig.control.act("trivia_bank", {})
        assert ok and text == TRIVIA_BANK

        ok, message = await rig.control.act(
            "set_trivia_bank", {"text": "## ¿Una?\n- [x] Sí\n- [ ] No\n- [ ] Quizá\n"}
        )
        assert not ok and "Solo hay 1" in message
        assert rig.control.status()["settings_sync"]["pending"] == []

        cloud = TRIVIA_BANK + "\n## [difícil] ¿Tercera?\n- [x] Sí\n- [ ] No\n\n## ¿Cuarta?\n"
        cloud += "- [ ] No\n- [x] Sí\n- [ ] Quizá\n"
        ok, message = await rig.control.act("set_trivia_bank", {"text": cloud})
        assert ok and "3 preguntas" in message and "Se saltó 1 mal formada" in message, message
        assert "fácil" in message and "difícil" in message  # niveles con menos de 2
        status = rig.control.status()
        assert status["trivia"]["bank_source"] == "cloud" and status["trivia"]["bank"] == 3
        assert status["settings_sync"]["pending"] == ["trivia_bank"]
        ok, text = await rig.control.act("trivia_bank", {})
        assert ok and text == cloud.strip()

        ok, message = await rig.control.act("set_trivia_bank", {"text": "  "})
        assert ok and "app" in message
        assert rig.control.status()["trivia"]["bank_source"] == "app"
    assert PanelState.load(tmp_path / "cache" / "panel_state.json").trivia_bank is None


async def test_el_banco_de_la_nube_sobrevive_al_reinicio(tmp_path: Path) -> None:
    (tmp_path / "trivia").mkdir()
    (tmp_path / "trivia" / "preguntas.md").write_text(TRIVIA_BANK, encoding="utf-8")
    cloud = "".join(f"## ¿Nube {i}?\n- [x] Sí\n- [ ] No\n- [ ] Quizá\n\n" for i in range(6))
    async with make_panel_rig(tmp_path, state=PanelState(trivia_bank=cloud)) as rig:
        await rig.conn()
        status = rig.control.status()["trivia"]
        assert status["bank_source"] == "cloud" and status["bank"] == 6


async def test_sin_banco_la_trivia_no_esta_disponible(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        await rig.conn()
        assert rig.control.status()["trivia"]["available"] is False
        ok, message = await rig.control.act("trivia_start", {})
        assert not ok and "preguntas" in message


async def test_interruptor_oir_solo_con_alguien_delante(tmp_path: Path) -> None:
    watch = PresenceWatch(make_settings(tmp_path).live, NoCamera(), model=tmp_path / "no-esta.onnx")
    async with make_panel_rig(tmp_path, presence=watch) as rig:
        # Arranca apagado (LIVE_PRESENCE_GATE) y se enciende y apaga en caliente.
        assert "mic_presence" in rig.control.capabilities
        assert rig.control.status()["mic_presence"]["enabled"] is False
        ok, _ = await rig.control.act("set_mic_presence", {"enabled": True})
        assert ok and watch.gate.enabled is True
        ok, _ = await rig.control.act("set_mic_presence", {"enabled": False})
        assert ok and watch.gate.enabled is False
        assert rig.control.status()["mic_presence"]["enabled"] is False
    # Se guarda en este equipo: al volver a arrancar sigue apagado.
    assert PanelState.load(Path(rig.settings.panel.state_file)).mic_presence is False
    live = make_settings(tmp_path, presence_gate=True).live
    watch = PresenceWatch(live, NoCamera(), model=tmp_path / "no-esta.onnx")
    async with make_panel_rig(tmp_path, presence=watch) as rig:
        assert watch.gate.enabled is False  # lo guardado en el panel manda sobre el .env


async def test_sin_camara_usb_no_hay_interruptor_de_alguien_delante(tmp_path: Path) -> None:
    async with make_panel_rig(tmp_path) as rig:
        assert "mic_presence" not in rig.control.capabilities
        ok, _ = await rig.control.act("set_mic_presence", {"enabled": True})
        assert not ok
        assert rig.control.status()["mic_presence"] is None


async def test_salud_del_micro_sin_nadie_delante(tmp_path: Path) -> None:
    live = make_settings(tmp_path, presence_gate=True).live
    watch = PresenceWatch(live, NoCamera(), model=tmp_path / "no-esta.onnx")
    async with make_panel_rig(tmp_path, presence=watch) as rig:
        conn = await rig.conn()
        now = time.monotonic()
        watch.gate.scanned(1, now - 1_000.0)
        watch.gate.scanned(0, now)
        await rig.engine.push_mic(voice_block(0.5))
        await conn.wait_type("session.input_audio.append")
        mic = rig.control.status()["health"]["mic"]
        assert mic["ok"] is True and "sin nadie delante" in mic["label"]
