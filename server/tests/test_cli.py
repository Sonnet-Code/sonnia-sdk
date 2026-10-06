"""Pruebas de la línea de comandos.

`sonia check` se prueba con GPT-Live y el modelo de visión sustituidos por
falsos: nunca se hace una petición real. La cámara y el micrófono se simulan.
"""

from __future__ import annotations

import asyncio
import base64
import json
import wave
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from sonia import cli
from sonia.config import (
    AudioSettings,
    LiveSettings,
    LLMSettings,
    Settings,
    VisionSettings,
    WSSettings,
)
from sonia.live.oneshot import ProbeResult
from sonia.llm.client import LLMError
from sonia.types import AudioChunk
from sonia.ws import protocol as p
from sonia.ws.hub import Hub


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    gallery = tmp_path / "gallery"
    gallery.mkdir(exist_ok=True)
    values: dict[str, Any] = {
        "live": LiveSettings(api_key="clave"),
        "llm": LLMSettings(
            base_url="http://llm.test/v1",
            model="modelo-de-prueba",
            api_key="clave-de-prueba",
            reasoning_effort="",
            request_timeout=2.0,
        ),
        "audio": AudioSettings(),
        "vision": VisionSettings(source="none"),
        "ws": WSSettings(host="127.0.0.1", port=0),
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

    async def probe(self, message: dict[str, Any]) -> None:
        FakeLLMClient.probes.append(message)
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


@pytest.fixture
def fake_live(monkeypatch: pytest.MonkeyPatch) -> list[LiveSettings]:
    """Sustituye la sesión de prueba de GPT-Live: nunca se abre una de verdad."""
    probes: list[LiveSettings] = []

    async def fake_probe(settings: LiveSettings) -> ProbeResult:
        probes.append(settings)
        return ProbeResult("sess_1", 0.42, "marin", 3600.0)

    monkeypatch.setattr(cli, "probe_session", fake_probe)
    return probes


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
    fake_live: list[LiveSettings],
    fake_audio: list[dict[str, Any]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    add_gallery_image(tmp_path, "logo.png")
    settings = make_settings(
        tmp_path,
        audio=AudioSettings(input_device="yeti"),
        vision=VisionSettings(source="unity"),
    )

    results = await cli.run_checks(settings)
    assert [(r.name, r.ok) for r in results] == [
        ("Micrófono", True),
        ("Cámara", True),
        ("GPT-Live", True),
        ("Visión", True),
        ("Galería", True),
    ]
    detail = {r.name: r.detail for r in results}
    assert "Yeti" in detail["Micrófono"]
    assert "Unity" in detail["Cámara"]
    assert "420 ms" in detail["GPT-Live"] and "60 min" in detail["GPT-Live"]
    assert "gpt-6-luna" in detail["GPT-Live"]
    assert "pong" in detail["Visión"] and "acepta imágenes" in detail["Visión"]
    assert "logo" in detail["Galería"]
    assert len(fake_live) == 1
    # El modelo de visión: un ping y una petición mínima con imagen.
    assert fake_llm.pings == 1
    assert len(fake_llm.probes) == 1
    assert fake_llm.probes[0]["content"][1]["type"] == "image_url"

    assert cli.print_results(results) is True
    out = capsys.readouterr().out
    assert out.count("OK   ") == 5
    assert "Todo listo." in out


async def test_check_sin_clave_de_gpt_live_es_fallo_critico(
    tmp_path: Path,
    fake_llm: type[FakeLLMClient],
    fake_audio: list[dict[str, Any]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    results = await cli.run_checks(make_settings(tmp_path, live=LiveSettings(api_key="")))
    live = next(r for r in results if r.name == "GPT-Live")
    assert not live.ok and live.critical
    assert "LIVE_API_KEY" in live.detail
    assert next(r for r in results if r.name == "Visión").ok  # sin cámara: desactivada
    gallery = next(r for r in results if r.name == "Galería")
    assert gallery.ok is False and gallery.critical is False  # vacía: aviso, no fallo

    assert cli.print_results(results) is False
    out = capsys.readouterr().out
    assert "FALLO  GPT-Live" in out
    assert "AVISO  Galería" in out


async def test_check_gpt_live_caido_es_fallo_critico(
    tmp_path: Path,
    fake_llm: type[FakeLLMClient],
    fake_audio: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_probe(settings: LiveSettings) -> ProbeResult:
        raise ConnectionError("sin conexión")

    monkeypatch.setattr(cli, "probe_session", failing_probe)
    results = await cli.run_checks(make_settings(tmp_path))
    live = next(r for r in results if r.name == "GPT-Live")
    assert not live.ok and live.critical
    assert "sin conexión" in live.detail


async def test_check_sin_microfono_es_fallo(
    tmp_path: Path,
    fake_llm: type[FakeLLMClient],
    fake_live: list[LiveSettings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "list_input_devices", list)
    results = await cli.run_checks(make_settings(tmp_path))
    mic = results[0]
    assert mic.name == "Micrófono" and not mic.ok and mic.critical


async def test_check_vision_caida_es_solo_un_aviso(
    tmp_path: Path,
    fake_llm: type[FakeLLMClient],
    fake_live: list[LiveSettings],
    fake_audio: list[dict[str, Any]],
) -> None:
    """Sonia conversa igual sin ojos: un fallo del modelo de visión no para el stand."""
    fake_llm.reply = LLMError("El servidor del modelo devolvió 503", status_code=503)
    results = await cli.run_checks(make_settings(tmp_path, vision=VisionSettings(source="unity")))
    vision = next(r for r in results if r.name == "Visión")
    assert vision.ok is False and vision.critical is False
    assert "503" in vision.detail
    assert cli.print_results(results) is True


async def test_check_avisa_si_el_modelo_no_acepta_imagenes(
    tmp_path: Path,
    fake_llm: type[FakeLLMClient],
    fake_live: list[LiveSettings],
    fake_audio: list[dict[str, Any]],
) -> None:
    fake_llm.probe_error = LLMError("El servidor del modelo devolvió 400: no vision")
    results = await cli.run_checks(make_settings(tmp_path, vision=VisionSettings(source="unity")))
    vision = next(r for r in results if r.name == "Visión")
    assert vision.ok is False and vision.critical is False
    # Ya no sugiere apagar la cámara entera: lo que falla es la configuración del modelo.
    assert "LLM_API_KEY" in vision.detail and "LLM_SUPPORTS_VISION=false" not in vision.detail


async def test_la_clave_de_openai_no_sale_hacia_otro_proveedor(
    tmp_path: Path,
    fake_llm: type[FakeLLMClient],
    fake_live: list[LiveSettings],
    fake_audio: list[dict[str, Any]],
) -> None:
    kimi = LLMSettings(
        base_url="https://api.moonshot.ai/v1", api_key="", openai_api_key="clave-de-openai"
    )
    assert kimi.key == ""
    assert LLMSettings(base_url="https://api.openai.com/v1", openai_api_key="o").key == "o"
    assert LLMSettings(base_url="https://api.moonshot.ai/v1", api_key="k").key == "k"
    # Sin clave para ese proveedor, la cámara se apaga en vez de fallar en cada turno.
    settings = make_settings(tmp_path, vision=VisionSettings(source="unity"), llm=kimi)
    components = cli.build_components(settings)
    assert not components.policy.enabled and components.llm is None
    results = await cli.run_checks(settings)
    vision = next(r for r in results if r.name == "Visión")
    assert vision.ok is False and "falta LLM_API_KEY" in vision.detail


def _jpeg_segments(raw: bytes) -> list[tuple[int, int]]:
    """(marcador, longitud) de cada segmento hasta SOS; falla si hay bytes sueltos entre ellos."""
    assert raw[:2] == b"\xff\xd8", "no empieza por SOI"
    assert raw[-2:] == b"\xff\xd9", "no acaba en EOI"
    segments: list[tuple[int, int]] = []
    pos = 2
    while True:
        assert raw[pos] == 0xFF, f"bytes sueltos antes del marcador en el byte {pos}"
        marker = raw[pos + 1]
        length = int.from_bytes(raw[pos + 2 : pos + 4], "big")
        segments.append((marker, length))
        if marker == 0xDA:  # SOS: a partir de aquí van los datos de la imagen
            return segments
        pos += 2 + length


def test_la_imagen_de_prueba_de_check_es_un_jpeg_valido() -> None:
    """Una imagen corrupta haría que un servidor estricto dé la visión por rota.

    La anterior tenía una tabla de cuantización 3 bytes más corta de lo declarado:
    ``sonia check`` fallaba en la visión y su propia ayuda sugería apagar la cámara.
    """
    raw = base64.b64decode(cli._PROBE_JPEG_B64, validate=True)
    markers = [marker for marker, _ in _jpeg_segments(raw)]
    assert markers.count(0xDB) == 2  # tablas de cuantización
    assert 0xC0 in markers  # SOF0: dimensiones
    assert markers.count(0xC4) == 4  # tablas de Huffman
    assert len(raw) < 2_000  # sigue siendo diminuta


def test_la_imagen_de_prueba_se_decodifica() -> None:
    cv2 = pytest.importorskip("cv2")
    raw = base64.b64decode(cli._PROBE_JPEG_B64, validate=True)
    image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    height, width = image.shape[:2]
    assert min(height, width) >= 56  # por encima del mínimo de cualquier modelo con visión


def test_main_check_devuelve_codigo_de_salida(
    tmp_path: Path,
    fake_llm: type[FakeLLMClient],
    fake_live: list[LiveSettings],
    fake_audio: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_gallery_image(tmp_path, "logo.png")
    settings = make_settings(tmp_path)
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    assert cli.main(["check"]) == 0

    settings.live.api_key = ""
    assert cli.main(["check"]) == 1


# ---------------------------------------------------------------------------
# sonia say
# ---------------------------------------------------------------------------


def test_say_guarda_un_wav(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    said: list[str] = []

    async def fake_speak(settings: LiveSettings, text: str) -> bytes:
        said.append(text)
        return np.full(int(0.5 * settings.sample_rate), 1000, dtype="<i2").tobytes()

    monkeypatch.setattr(cli, "speak_text", fake_speak)
    monkeypatch.setattr(cli, "load_settings", lambda: make_settings(tmp_path))
    out = tmp_path / "hola.wav"
    assert cli.main(["say", "Hola, Sonia.", "--out", str(out)]) == 0

    assert said == ["Hola, Sonia."]
    with wave.open(str(out), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 24_000
        assert wav.getnframes() == 12_000
    assert "Guardado en" in capsys.readouterr().out


def test_say_sin_clave_sale_con_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = make_settings(tmp_path, live=LiveSettings(api_key=""))
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    assert cli.main(["say", "Hola"]) == 1
    assert "LIVE_API_KEY" in capsys.readouterr().err


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


async def test_build_components_sin_camara(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, vision=VisionSettings(source="opencv"))
    components = cli.build_components(settings, with_camera=False)
    try:
        assert components.policy.enabled is False
        assert components.narrator is None and components.llm is None
        assert components.registry.names() == ["show_image", "hide_image", "play_animation"]
        assert components.hub.sample_rate == 24_000
        ctx = components.action_context()
        assert ctx.gallery_dir == str(tmp_path / "gallery")
        assert json.dumps(components.registry.to_responses_tools())  # serializable
    finally:
        await components.close()


async def test_build_components_con_camara_de_unity(tmp_path: Path) -> None:
    settings = make_settings(
        tmp_path,
        live=LiveSettings(api_key="clave", sample_rate=16_000),
        vision=VisionSettings(source="unity"),
    )
    components = cli.build_components(settings)
    try:
        assert components.hub.sample_rate == 16_000
        assert components.registry.names() == ["look", "show_image", "hide_image", "play_animation"]
        assert components.narrator is not None
    finally:
        await components.close()


def test_run_sin_clave_sale_con_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = make_settings(tmp_path, live=LiveSettings(api_key=""))
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    assert cli.main(["run", "--no-mic"]) == 1
    assert "LIVE_API_KEY" in capsys.readouterr().err
