"""Pruebas del Modo Jean sin red: media, bitrate adaptable y enlace con una sala falsa."""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
from collections.abc import AsyncIterator
from typing import Any

import numpy as np
import pytest

import sonia.guest.link as link_module
from sonia.config import PanelSettings
from sonia.guest.link import GuestLink, guest_url
from sonia.guest.media import (
    KIND_GUEST_AUDIO,
    KIND_STAND_AUDIO,
    KIND_VIDEO,
    START_STEP,
    VIDEO_STEPS,
    GuestSpeechSegmenter,
    LinearResampler,
    StandAudioPacker,
    VideoRateController,
    decode_room_frame,
    encode_room_frame,
)
from sonia.panel.identity import InstanceIdentity
from sonia.ws.protocol import encode_guest_audio_frame
from tests.test_live import wait_until

RATE = 24_000


def tone(seconds: float, rate: int = RATE, freq: float = 220.0, amp: float = 0.3) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    return (amp * np.sin(2 * math.pi * freq * t)).astype(np.float32)


def pcm(samples: np.ndarray) -> bytes:
    return (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()


# ---------------------------------------------------------------------------
# Formatos
# ---------------------------------------------------------------------------


def test_frames_de_la_sala_ida_y_vuelta() -> None:
    raw = encode_room_frame(KIND_STAND_AUDIO, 7, 123456, b"\x01\x02", rate=16_000)
    assert len(raw) == 16 + 2
    frame = decode_room_frame(raw)
    assert (frame.kind, frame.seq, frame.t_ms, frame.rate, frame.payload) == (
        KIND_STAND_AUDIO,
        7,
        123456,
        16_000,
        b"\x01\x02",
    )
    # El número y la hora dan la vuelta sin romperse.
    wrapped = decode_room_frame(encode_room_frame(KIND_VIDEO, 2**32 + 5, 2**33 + 9, b""))
    assert wrapped.seq == 5 and wrapped.t_ms == 9
    for bad in (b"", b"XX" + bytes(14), encode_room_frame(KIND_VIDEO, 1, 1, b"")[:10]):
        with pytest.raises(ValueError):
            decode_room_frame(bad)
    with pytest.raises(ValueError):
        encode_room_frame(9, 1, 1, b"")


def test_la_voz_del_invitado_va_con_marca_propia_para_unity() -> None:
    frame = encode_guest_audio_frame(3, b"\x10\x00", is_last=True)
    assert frame[:4] == b"SNGU"
    assert int.from_bytes(frame[4:8], "little") == 3
    assert int.from_bytes(frame[8:12], "little") == 1
    assert frame[12:] == b"\x10\x00"


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------


def test_el_remuestreo_por_bloques_encadena_sin_saltos() -> None:
    signal = tone(1.0, freq=300.0)
    whole = LinearResampler(RATE, 16_000).process(signal)
    chunked = LinearResampler(RATE, 16_000)
    parts = [chunked.process(signal[i : i + 480]) for i in range(0, len(signal), 480)]
    joined = np.concatenate(parts)
    assert len(whole) == 16_000 and len(joined) == 16_000
    assert np.max(np.abs(whole - joined)) < 1e-4
    # Y la señal sigue siendo la misma (salvo el filtro paso bajo, muy suave a 300 Hz).
    t = np.arange(16_000) / 16_000
    expected = 0.3 * np.sin(2 * math.pi * 300.0 * t)
    assert np.max(np.abs(joined[50:] - expected[50:])) < 0.03
    up = LinearResampler(16_000, RATE)
    # Al subir de tasa, como mucho una muestra queda para el bloque siguiente.
    assert abs(sum(len(up.process(tone(0.02, 16_000))) for _ in range(50)) - RATE) <= 1


def test_el_micro_del_stand_sale_en_bloques_de_100_ms_a_16_khz() -> None:
    packer = StandAudioPacker(RATE)
    blocks: list[bytes] = []
    for _ in range(25):  # 25 bloques de 20 ms = 500 ms
        blocks.extend(packer.push(tone(0.02)))
    assert len(blocks) == 5
    assert all(len(block) == 1_600 * 2 for block in blocks)


def test_la_voz_de_jean_se_corta_en_rachas_con_colchon() -> None:
    seg = GuestSpeechSegmenter(rate=RATE)
    chunk = 0.06  # bloques de 60 ms como los manda el navegador
    silence = pcm(np.zeros(int(chunk * RATE), dtype=np.float32))
    voice = pcm(tone(chunk))
    now = 0.0
    assert seg.push(silence, now=now) == []  # silencio sin racha: nada
    out: list[tuple[int, bytes, bool]] = []
    out += seg.push(voice, now=now)
    out += seg.push(voice, now=now)
    assert out == []  # 120 ms: aún llenando el colchón de 150 ms
    out += seg.push(voice, now=now)
    assert [frame[0] for frame in out] == [1, 1, 1] and not any(frame[2] for frame in out)
    # Una pausa corta va dentro de la racha.
    assert seg.push(silence, now=now) == [(1, silence, False)]
    assert seg.push(voice, now=now) == [(1, voice, False)]
    # 500 ms de silencio la cierran con un frame vacío.
    closed: list[tuple[int, bytes, bool]] = []
    for _ in range(9):
        closed += seg.push(silence, now=now)
    assert closed[-1] == (1, b"", True)
    # La siguiente voz abre la racha 2.
    for _ in range(3):
        out = seg.push(voice, now=now)
    assert out and out[0][0] == 2
    # Si deja de llegar audio, la racha se cierra sola.
    assert seg.close_if_stale(now=now + 0.1) == []
    assert seg.close_if_stale(now=now + 1.0) == [(2, b"", True)]


# ---------------------------------------------------------------------------
# Vídeo
# ---------------------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_la_ventana_no_deja_apilar_fotogramas() -> None:
    clock = Clock()
    video = VideoRateController(clock=clock)
    assert video.can_send()
    video.on_sent(1, 30_000)
    clock.now += 0.1
    assert video.can_send()
    video.on_sent(2, 30_000)
    clock.now += 0.1
    assert not video.can_send()  # dos sin confirmar: se espera
    video.on_ack(1)
    assert video.can_send()
    # Tope de fps: no más de 12 por segundo aunque la ventana esté libre.
    video.on_sent(3, 30_000)
    clock.now += 0.01
    video.on_ack(2)
    video.on_ack(3)
    assert not video.can_send()


def test_con_red_buena_sube_de_calidad_y_con_red_mala_baja() -> None:
    clock = Clock()
    video = VideoRateController(clock=clock)
    assert video.step == VIDEO_STEPS[START_STEP]
    seq = 0
    for _second in range(3):
        for _ in range(10):
            if video.can_send():
                seq += 1
                video.on_sent(seq, 30_000)
            clock.now += 0.05
            video.on_ack(seq)  # RTT de 50 ms
            clock.now += 0.05
        stats = video.tick()
    assert video.step == VIDEO_STEPS[0]
    assert stats.fps > 8 and stats.kbps > 1_000 and stats.rtt_ms is not None
    # RTT alto: baja.
    for _ in range(5):
        seq += 1
        video.on_sent(seq, 30_000)
        clock.now += 0.9
        video.on_ack(seq)
    video.tick()
    assert video.step == VIDEO_STEPS[1]
    # Fotogramas que nunca se confirman: se dan por perdidos y baja otro.
    seq += 1
    video.on_sent(seq, 30_000)
    clock.now += 3.0
    stats = video.tick()
    assert stats.lost >= 1 and video.step == VIDEO_STEPS[2]
    assert video.in_flight == 0


# ---------------------------------------------------------------------------
# GuestLink contra una sala falsa
# ---------------------------------------------------------------------------


def test_la_url_de_la_sala_sale_de_la_del_panel() -> None:
    assert guest_url("wss://sonia.sonnetcode.com/agent") == "wss://sonia.sonnetcode.com/guest/agent"
    assert guest_url("ws://localhost:8787/agent") == "ws://localhost:8787/guest/agent"
    assert guest_url("wss://x.test") == "wss://x.test/guest/agent"


class FakeRoom:
    def __init__(self) -> None:
        self.paths: list[str] = []
        self.headers: list[dict[str, str]] = []
        self.binary: list[bytes] = []
        self.text: list[dict[str, Any]] = []
        self.ws: Any = None
        self._changed = asyncio.Event()

    async def handler(self, ws: Any) -> None:
        self.ws = ws
        self.paths.append(ws.request.path)
        self.headers.append({k.lower(): v for k, v in ws.request.headers.items()})
        with contextlib.suppress(Exception):
            async for raw in ws:
                if isinstance(raw, bytes):
                    self.binary.append(raw)
                else:
                    self.text.append(json.loads(raw))
                self._changed.set()

    def frames(self, kind: int) -> list[Any]:
        return [
            decode_room_frame(raw) for raw in self.binary if decode_room_frame(raw).kind == kind
        ]

    async def wait_for(self, predicate: Any, limit: float = 3.0) -> None:
        async with asyncio.timeout(limit):
            while not predicate():
                self._changed.clear()
                await self._changed.wait()


class FakeSink:
    def __init__(self) -> None:
        self.frames: list[bytes] = []

    async def broadcast_bytes(self, data: bytes) -> None:
        self.frames.append(data)


@contextlib.asynccontextmanager
async def linked(room: FakeRoom) -> AsyncIterator[tuple[GuestLink, FakeSink]]:
    from websockets.asyncio.client import connect as client_connect
    from websockets.asyncio.server import serve

    async with serve(room.handler, "127.0.0.1", 0) as srv:
        port = srv.sockets[0].getsockname()[1]
        captured: list[str] = []

        async def connect(url: str, headers: dict[str, str]) -> Any:
            captured.append(url)
            path = url.split("/", 3)[3]
            return await client_connect(f"ws://127.0.0.1:{port}/{path}", additional_headers=headers)

        grabs: list[tuple[int, int]] = []

        async def grab(width: int, quality: int) -> bytes:
            grabs.append((width, quality))
            return b"\xff\xd8" + bytes(1_000) + b"\xff\xd9"

        settings = PanelSettings(cloud_url="wss://sonia.test/agent", cloud_token="token")
        identity = InstanceIdentity(id="stand-abc123", name="Stand", host="stand")
        sink = FakeSink()
        link = GuestLink(
            settings,
            identity,
            sink=sink,
            unity_rate=RATE,
            mic_rate=RATE,
            grab=grab,
            connect=connect,
        )
        task = asyncio.create_task(link.run())
        try:
            yield link, sink
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        assert captured[0] == "wss://sonia.test/guest/agent"


async def test_sin_nadie_mirando_no_manda_media(monkeypatch: pytest.MonkeyPatch) -> None:
    room = FakeRoom()
    async with linked(room) as (link, _):
        await wait_until(lambda: link.connected)
        link.push_mic(tone(0.2))
        await asyncio.sleep(0.2)
        assert room.binary == []
        assert room.paths == ["/guest/agent"]
        assert room.headers[0]["authorization"] == "Bearer token"
        assert room.headers[0]["x-sonia-instance"] == "stand-abc123"


async def test_con_alguien_mirando_manda_camara_y_micro_y_respeta_la_ventana(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(link_module, "STATS_INTERVAL_S", 0.1)
    room = FakeRoom()
    async with linked(room) as (link, _):
        await wait_until(lambda: room.ws is not None and link.connected)
        await room.ws.send(json.dumps({"type": "viewers", "count": 1}))
        await room.wait_for(lambda: len(room.frames(KIND_VIDEO)) >= 2)
        await asyncio.sleep(0.3)
        # Sin acks no hay más de dos fotogramas en vuelo.
        assert len(room.frames(KIND_VIDEO)) == 2
        first = room.frames(KIND_VIDEO)[0]
        assert first.payload.startswith(b"\xff\xd8") and first.seq == 1
        for frame in room.frames(KIND_VIDEO):
            await room.ws.send(json.dumps({"type": "ack", "seq": frame.seq, "t": frame.t_ms}))
        await room.wait_for(lambda: len(room.frames(KIND_VIDEO)) >= 4)
        # El micro del stand sale en bloques de 100 ms a 16 kHz.
        for _ in range(10):
            link.push_mic(tone(0.02))
        await room.wait_for(lambda: len(room.frames(KIND_STAND_AUDIO)) >= 2)
        audio = room.frames(KIND_STAND_AUDIO)[0]
        assert audio.rate == 16_000 and len(audio.payload) == 3_200
        # Y las estadísticas llegan a quien mira.
        await room.wait_for(lambda: any(m.get("type") == "stats" for m in room.text))
        stats = next(m for m in room.text if m.get("type") == "stats")
        assert stats["viewers"] == 1 and "video" in stats


async def test_la_voz_de_jean_llega_a_unity_por_rachas() -> None:
    room = FakeRoom()
    async with linked(room) as (link, sink):
        await wait_until(lambda: room.ws is not None and link.connected)
        voice = pcm(tone(0.06))
        for seq in range(1, 6):
            await room.ws.send(encode_room_frame(KIND_GUEST_AUDIO, seq, seq * 60, voice, rate=RATE))
        silence = pcm(np.zeros(int(0.06 * RATE), dtype=np.float32))
        for seq in range(6, 16):
            await room.ws.send(
                encode_room_frame(KIND_GUEST_AUDIO, seq, seq * 60, silence, rate=RATE)
            )
        await asyncio.sleep(0.3)
        assert sink.frames, "la voz de Jean no llegó a Unity"
        assert all(frame[:4] == b"SNGU" for frame in sink.frames)
        flags = [int.from_bytes(frame[8:12], "little") for frame in sink.frames]
        assert flags[-1] == 1 and flags.count(1) == 1  # una racha cerrada
        assert link.stats()["guest_frames"] == 15
        # A 16 kHz se remuestrea a la tasa de Unity.
        await room.ws.send(
            encode_room_frame(KIND_GUEST_AUDIO, 99, 0, pcm(tone(0.3, 16_000)), rate=16_000)
        )
        await asyncio.sleep(0.2)
        last = sink.frames[-1]
        assert abs((len(last) - 12) // 2 - int(0.3 * RATE)) <= 1


# ---------------------------------------------------------------------------
# GuestMode dentro del panel (con un enlace falso)
# ---------------------------------------------------------------------------


class FakeLink:
    """Imita ``GuestLink``: sin red, cuenta lo que le llega del micro."""

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self.running = False
        self.mic_blocks = 0

    async def run(self) -> None:
        self.running = True
        try:
            await asyncio.Event().wait()
        finally:
            self.running = False

    def push_mic(self, block: np.ndarray) -> None:
        self.mic_blocks += 1

    def stats(self) -> dict[str, Any]:
        return {"connected": self.running, "viewers": 0}


INTRO = "¡Atención, DevFest! Acaba de llegar un invitado sorpresa."


async def test_el_modo_jean_presenta_al_invitado_y_devuelve_a_sonia(tmp_path: Any) -> None:
    from sonia.guest.mode import GuestMode
    from sonia.panel.control import _Material
    from tests.test_panel import GREETING, make_panel_rig, write_clip

    material = _Material(greetings=[GREETING], guest_intros=[INTRO])
    async with make_panel_rig(tmp_path, material=material) as rig:
        conn = await rig.conn()
        ok, message = await rig.control.act("set_guest_mode", {"active": True})
        assert not ok and "nube" in message
        assert "guest_mode" not in rig.control.status()["capabilities"]

        link = FakeLink()
        guest = GuestMode(
            hub=rig.hub,
            engine=rig.engine,
            link=link,  # type: ignore[arg-type]
            voice_cache=rig.cache,
            intro_lines=rig.control.guest_intro_lines,
            unity_rate=RATE,
            on_change=rig.control.guest_changed,
        )
        rig.control.attach_guest(guest)
        assert "guest_mode" in rig.control.status()["capabilities"]
        assert rig.control.status()["guest"]["intro_ready"] is False
        write_clip(rig.cache, INTRO, samples=2_400)  # 0,1 s de "frase grabada"
        assert rig.control.status()["guest"]["intro_ready"] is True

        ok, message = await rig.control.act("set_guest_mode", {"active": True})
        assert ok and "Jean" in message
        # GPT-Live se cierra y Sonia anuncia al invitado con la frase grabada.
        await conn.wait_type("session.close")
        await wait_until(lambda: not rig.engine.connected)
        await rig.rec.wait_for(
            lambda msgs: any(m.get("text") == INTRO for m in rig.rec.of_type("speech_start", msgs))
        )
        # Luego entra el invitado: mensaje fijo para Unity.
        await rig.rec.wait_type("guest_mode")
        enter = rig.rec.of_type("guest_mode")[-1]
        assert enter == {
            "type": "guest_mode",
            "phase": "enter",
            "name": "Jean",
            "sample_rate": RATE,
        }
        assert guest.phase == "entering" and link.running
        # El micro del stand va al enlace mientras dura el modo.
        await rig.engine.push_mic(np.zeros(480, dtype=np.float32))
        assert link.mic_blocks == 1
        # Unity confirma: en directo.
        await rig.client.send(json.dumps({"type": "guest_state", "phase": "live"}))
        await wait_until(lambda: guest.phase == "live")
        assert rig.control.status()["guest"]["phase"] == "live"
        # Gestos del invitado; el modo de Sonia no se puede cambiar mientras tanto.
        ok, _ = await rig.control.act("guest_animation", {"clip": "Wave"})
        assert ok
        await rig.rec.wait_type("guest_animation")
        assert rig.rec.of_type("guest_animation")[-1] == {"type": "guest_animation", "clip": "Wave"}
        ok, message = await rig.control.act("set_mode", {"mode": "greeter"})
        assert not ok and "Modo Jean" in message
        # Termina: se despide, Unity confirma y vuelve GPT-Live.
        ok, _ = await rig.control.act("set_guest_mode", {"active": False})
        assert ok
        await rig.rec.wait_for(
            lambda msgs: rig.rec.of_type("guest_mode", msgs)[-1]["phase"] == "leave"
        )
        await rig.client.send(json.dumps({"type": "guest_state", "phase": "off"}))
        await wait_until(lambda: guest.phase == "off")
        assert not link.running
        await rig.engine.push_mic(np.zeros(480, dtype=np.float32))
        assert link.mic_blocks == 1  # ya no se oye desde fuera
        await rig.conn(2)
        ok, message = await rig.control.act("guest_animation", {"clip": "Wave"})
        assert not ok


async def test_sin_unity_el_modo_jean_sigue_igual(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sonia.guest.mode as mode_module
    from sonia.guest.mode import GuestMode
    from tests.test_panel import make_panel_rig

    monkeypatch.setattr(mode_module, "ENTER_TIMEOUT_S", 0.1)
    monkeypatch.setattr(mode_module, "LEAVE_TIMEOUT_S", 0.1)
    async with make_panel_rig(tmp_path) as rig:
        await rig.conn()
        link = FakeLink()
        guest = GuestMode(
            hub=rig.hub,
            engine=rig.engine,
            link=link,  # type: ignore[arg-type]
            voice_cache=rig.cache,
            intro_lines=[],
            unity_rate=RATE,
            on_change=rig.control.guest_changed,
        )
        rig.control.attach_guest(guest)
        # Sin frase grabada ni respuesta de Unity: entra igual y sale igual.
        ok, _ = await rig.control.act("set_guest_mode", {"active": True})
        assert ok
        await wait_until(lambda: guest.phase == "live")
        ok, _ = await rig.control.act("set_guest_mode", {"active": False})
        assert ok
        await wait_until(lambda: guest.phase == "off")
        await rig.conn(2)
        # Con la sala sin nube, ni empieza.
        rig.control.attach_guest(
            GuestMode(
                hub=rig.hub,
                engine=rig.engine,
                link=FakeLink(enabled=False),  # type: ignore[arg-type]
                voice_cache=None,
                intro_lines=[],
                unity_rate=RATE,
                on_change=rig.control.guest_changed,
            )
        )
        ok, message = await rig.control.act("set_guest_mode", {"active": True})
        assert not ok and "PANEL_CLOUD_TOKEN" in message
