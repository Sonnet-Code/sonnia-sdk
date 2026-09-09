"""Pruebas de la línea de comandos.

`sonia check` se prueba con el cliente del modelo sustituido por uno falso:
nunca se hace una petición real. El TTS es el backend ``mock`` y la cámara y
el micrófono se simulan.
"""

from __future__ import annotations

import asyncio
import json
import wave
from pathlib import Path
from typing import Any

import pytest

from sonia import cli
from sonia.config import (
    AudioSettings,
    LLMSettings,
    MCPSettings,
    Settings,
    STTSettings,
    TTSSettings,
    VisionSettings,
    WSSettings,
)
from sonia.llm.client import LLMError
from sonia.types import AudioChunk
from sonia.ws import protocol as p
from sonia.ws.hub import Hub


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    gallery = tmp_path / "gallery"
    gallery.mkdir(exist_ok=True)
    values: dict[str, Any] = {
        "llm": LLMSettings(
            base_url="http://llm.test/v1",
            model="modelo-de-prueba",
            api_key="clave-de-prueba",
            reasoning_effort="",
            request_timeout=2.0,
        ),
        "stt": STTSettings(backend="mock"),
        "tts": TTSSettings(backend="mock", sample_rate=24_000),
        "audio": AudioSettings(),
        "vision": VisionSettings(source="none"),
        "ws": WSSettings(host="127.0.0.1", port=0),
        "mcp": MCPSettings(enabled=False),
        "assets_dir": str(tmp_path),
        "log_level": "WARNING",
    }
    values.update(overrides)
    values["_env_file"] = None
    return Settings(**values)


def add_gallery_image(tmp_path: Path, name: str, data: bytes = b"\x89PNG") -> None:
    gallery = tmp_path / "gallery"
    gallery.mkdir(exist_ok=True)
    (gallery / name).write_bytes(data)


class FakeLLMClient:
    """Sustituto de ``LLMClient`` para ``sonia check``: nunca toca la red."""

    reply: str | Exception = "modelo-de-prueba: pong"
    probe_error: Exception | None = None
    pings = 0
    probes: list[dict[str, Any]] = []

    def __init__(self, settings: LLMSettings) -> None:
        self.settings = settings

    async def __aenter__(self) -> FakeLLMClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def ping(self) -> str:
        FakeLLMClient.pings += 1
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply

    async def probe(
        self,
        *,
        image: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> None:
        FakeLLMClient.probes.append({"image": image, "tools": tools})
        if FakeLLMClient.probe_error is not None:
            raise FakeLLMClient.probe_error


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> type[FakeLLMClient]:
    FakeLLMClient.reply = "modelo-de-prueba: pong"
    FakeLLMClient.probe_error = None
    FakeLLMClient.pings = 0
    FakeLLMClient.probes = []
    monkeypatch.setattr(cli, "LLMClient", FakeLLMClient)
    return FakeLLMClient


class _FakeVad:
    """Silero falso: `sonia check` no debe cargar torch en los tests."""

    def warmup(self) -> None:
        return None

    def probability(self, block: Any) -> float:
        return 0.0


@pytest.fixture(autouse=True)
def fake_vad(monkeypatch: pytest.MonkeyPatch) -> None:
    """Evita cargar Silero de verdad en cada `run_checks`."""
    import sonia.audio.vad as vad_module

    monkeypatch.setattr(vad_module, "VoiceActivityDetector", _FakeVad)


@pytest.fixture
def fake_audio(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    devices = [
        {"index": 0, "name": "Micro USB", "channels": 1, "sample_rate": 48_000.0, "default": False},
        {"index": 2, "name": "Yeti", "channels": 2, "sample_rate": 44_100.0, "default": True},
    ]
    monkeypatch.setattr(cli, "list_input_devices", lambda: devices)
    monkeypatch.setattr(cli, "resolve_input_device", lambda spec: 2 if spec == "yeti" else None)
    return devices


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["run"], {"command": "run", "no_mic": False}),
        (["run", "--no-mic"], {"command": "run", "no_mic": True}),
        (["chat"], {"command": "chat", "speak": False}),
        (["chat", "--speak"], {"command": "chat", "speak": True}),
        (["say", "Hola"], {"command": "say", "text": "Hola", "out": None}),
        (["say", "Hola", "--out", "x.wav"], {"command": "say", "out": Path("x.wav")}),
        (["check"], {"command": "check"}),
        (["mcp"], {"command": "mcp"}),
        (["--log-level", "DEBUG", "check"], {"command": "check", "log_level": "DEBUG"}),
    ],
)
def test_parser(argv: list[str], expected: dict[str, Any]) -> None:
    args = vars(cli.build_parser().parse_args(argv))
    for key, value in expected.items():
        assert args[key] == value


def test_parser_exige_subcomando() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([])


# ---------------------------------------------------------------------------
# sonia check
# ---------------------------------------------------------------------------


async def test_check_todo_ok(
    tmp_path: Path,
    fake_llm: type[FakeLLMClient],
    fake_audio: list[dict[str, Any]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    add_gallery_image(tmp_path, "logo.png")
    settings = make_settings(tmp_path, audio=AudioSettings(input_device="yeti"))

    results = await cli.run_checks(settings)
    assert [(r.name, r.ok) for r in results] == [
        ("Micrófono", True),
        ("VAD", True),
        ("STT", True),
        ("Cámara", True),
        ("LLM", True),
        ("Capacidad", True),
        ("TTS", True),
        ("Galería", True),
    ]
    detail = {r.name: r.detail for r in results}
    assert "Yeti" in detail["Micrófono"]
    assert "Silero" in detail["VAD"]
    assert "backend mock" in detail["STT"]
    assert "VISION_SOURCE=none" in detail["Cámara"]
    assert "pong" in detail["LLM"]
    assert detail["Capacidad"] == "visión: OK; acciones: OK"
    assert "backend mock" in detail["TTS"] and "24000 Hz" in detail["TTS"]
    assert "logo" in detail["Galería"]
    assert fake_llm.pings == 1  # una única petición mínima de conectividad

    # Las capacidades se prueban tal como se usan en cada turno: imagen y tools.
    assert len(fake_llm.probes) == 2
    assert fake_llm.probes[0]["image"]["content"][1]["type"] == "image_url"
    assert fake_llm.probes[0]["tools"] is None
    assert fake_llm.probes[1]["image"] is None
    assert [t["function"]["name"] for t in fake_llm.probes[1]["tools"]] == [
        "show_image",
        "hide_image",
    ]

    assert cli.print_results(results) is True
    out = capsys.readouterr().out
    assert out.count("OK   ") == 8
    assert "Todo listo." in out


async def test_check_llm_caido_es_fallo_critico(
    tmp_path: Path,
    fake_llm: type[FakeLLMClient],
    fake_audio: list[dict[str, Any]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_llm.reply = LLMError("El servidor del modelo devolvió 503", status_code=503)
    settings = make_settings(tmp_path)

    results = await cli.run_checks(settings)
    llm = next(r for r in results if r.name == "LLM")
    assert llm.ok is False and llm.critical is True
    assert "503" in llm.detail
    gallery = next(r for r in results if r.name == "Galería")
    assert gallery.ok is False and gallery.critical is False  # vacía: aviso, no fallo

    assert cli.print_results(results) is False
    out = capsys.readouterr().out
    assert "FALLO  LLM" in out
    assert "AVISO  Galería" in out


async def test_check_sin_microfono_es_fallo(
    tmp_path: Path, fake_llm: type[FakeLLMClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "list_input_devices", list)
    results = await cli.run_checks(make_settings(tmp_path))
    mic = results[0]
    assert mic.name == "Micrófono" and not mic.ok and mic.critical


def test_main_check_devuelve_codigo_de_salida(
    tmp_path: Path,
    fake_llm: type[FakeLLMClient],
    fake_audio: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_gallery_image(tmp_path, "logo.png")
    monkeypatch.setattr(cli, "load_settings", lambda: make_settings(tmp_path))
    assert cli.main(["check"]) == 0

    fake_llm.reply = ConnectionError("sin conexión")
    assert cli.main(["check"]) == 1


# ---------------------------------------------------------------------------
# sonia say
# ---------------------------------------------------------------------------


def test_say_guarda_un_wav(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "load_settings", lambda: make_settings(tmp_path))
    out = tmp_path / "hola.wav"
    assert cli.main(["say", "Hola, Sonia.", "--out", str(out)]) == 0

    with wave.open(str(out), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 24_000
        # MockTTS: 60 ms por carácter -> 12 caracteres = 0.72 s.
        assert wav.getnframes() == int(0.72 * 24_000)
    assert "Guardado en" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# sonia chat: el tap de consola
# ---------------------------------------------------------------------------


async def test_console_tap_imprime_y_confirma_la_reproduccion(
    capsys: pytest.CaptureFixture[str],
) -> None:
    hub = Hub(WSSettings(host="127.0.0.1", port=0), sample_rate=24_000)
    tap = cli.ConsoleTap(hub)
    done: list[int] = []
    tap.playback_done = done.append

    await tap.broadcast_json(p.msg_state("thinking"))
    await tap.broadcast_json(p.msg_transcript("user", "hola", True))
    await tap.broadcast_json(p.msg_transcript("assistant", "Hola, ¿qué tal?", True))
    await tap.send_audio(3, AudioChunk(pcm=b"\x00\x00", sample_rate=24_000, is_last=True))
    await tap.broadcast_json(p.msg_speech_end(3))
    await tap.broadcast_json(p.msg_error("se cayó el modelo"))
    await tap.show_image(
        image_id="logo", source="gallery", mime="image/png", data=b"x", caption="L"
    )
    await tap.hide_image()

    out = capsys.readouterr().out
    assert "[thinking]" in out
    assert "Sonia: Hola, ¿qué tal?" in out
    assert "hola" not in out.split("Sonia:")[0]  # lo del usuario no se repite
    assert "[error] se cayó el modelo" in out
    assert "[imagen: logo (gallery, 1 bytes) — L]" in out
    assert "[imagen retirada]" in out
    assert done == [3]  # sin reproductor local, speech_end confirma la frase


async def test_console_tap_no_confirma_si_unity_esta_conectado() -> None:
    """Con Unity delante manda su ``playback_done``, no el atajo de la consola.

    Confirmar aquí adelantaría el `idle` hasta dos segundos y el avatar volvería
    a la animación de reposo con la boca todavía en marcha.
    """
    from websockets.asyncio.client import connect

    hub = Hub(WSSettings(host="127.0.0.1", port=0), sample_rate=24_000)
    tap = cli.ConsoleTap(hub)
    done: list[int] = []
    tap.playback_done = done.append

    async with hub, connect(f"ws://127.0.0.1:{hub.port}/") as client:
        await asyncio.wait_for(client.recv(), 2.0)  # hello
        async with asyncio.timeout(2.0):
            while hub.client_count == 0:  # noqa: ASYNC110 - sondeo deliberado
                await asyncio.sleep(0.01)
        await tap.broadcast_json(p.msg_speech_end(1))
        assert done == []

    async with asyncio.timeout(2.0):
        while hub.client_count:  # noqa: ASYNC110 - sondeo deliberado
            await asyncio.sleep(0.01)
    await tap.broadcast_json(p.msg_speech_end(2))
    assert done == [2]
    await hub.stop()


async def test_check_avisa_si_el_modelo_no_acepta_imagenes(
    tmp_path: Path,
    fake_llm: type[FakeLLMClient],
    fake_audio: list[dict[str, Any]],
) -> None:
    """Un endpoint sin mmproj pasaba el check y luego fallaba todos los turnos."""
    fake_llm.probe_error = LLMError("El servidor del modelo devolvió 400: no vision")

    results = await cli.run_checks(make_settings(tmp_path))
    features = next(r for r in results if r.name == "Capacidad")
    assert features.ok is False
    assert features.critical is False  # aviso: puede ser el parámetro, no el modelo
    assert "LLM_SUPPORTS_VISION=false" in features.detail
    assert "LLM_TOOL_MODE=prompt" in features.detail


async def test_build_components_sin_camara(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, vision=VisionSettings(source="opencv"))
    components = cli.build_components(settings, with_camera=False)
    try:
        assert components.policy.enabled is False
        assert components.registry.names() == ["show_image", "hide_image"]
        assert components.hub.sample_rate == 24_000
        ctx = components.action_context()
        assert ctx.gallery_dir == str(tmp_path / "gallery")
        assert json.dumps(components.registry.to_openai_tools())  # serializable
    finally:
        await components.close()
