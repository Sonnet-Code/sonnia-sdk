"""Command line tests.

`sonia check` is tested with GPT-Live and the vision model replaced by fakes: no
real request is ever made. The camera and the microphone are simulated.
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
        "live": LiveSettings(api_key="key"),
        "llm": LLMSettings(
            base_url="http://llm.test/v1",
            model="test-model",
            api_key="test-key",
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
    """Stand-in for ``LLMClient`` in ``sonia check``: it never touches the network."""

    reply: str | Exception = "test-model: pong"
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
    FakeLLMClient.reply = "test-model: pong"
    FakeLLMClient.probe_error = None
    FakeLLMClient.pings = 0
    FakeLLMClient.probes = []
    monkeypatch.setattr(cli, "LLMClient", FakeLLMClient)
    return FakeLLMClient


@pytest.fixture
def fake_live(monkeypatch: pytest.MonkeyPatch) -> list[LiveSettings]:
    """Replaces the GPT-Live probe session: a real one is never opened."""
    probes: list[LiveSettings] = []

    async def fake_probe(settings: LiveSettings) -> ProbeResult:
        probes.append(settings)
        return ProbeResult("sess_1", 0.42, "marin", 3600.0)

    monkeypatch.setattr(cli, "probe_session", fake_probe)
    return probes


@pytest.fixture
def fake_audio(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    devices = [
        {"index": 0, "name": "USB Mic", "channels": 1, "sample_rate": 48_000.0, "default": False},
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
        (["say", "Hello"], {"command": "say", "text": "Hello", "out": None}),
        (["say", "Hello", "--out", "x.wav"], {"command": "say", "out": Path("x.wav")}),
        (["check"], {"command": "check"}),
        (["--log-level", "DEBUG", "check"], {"command": "check", "log_level": "DEBUG"}),
    ],
)
def test_parser(argv: list[str], expected: dict[str, Any]) -> None:
    args = vars(cli.build_parser().parse_args(argv))
    for key, value in expected.items():
        assert args[key] == value


def test_parser_requires_a_subcommand() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([])


# ---------------------------------------------------------------------------
# sonia check
# ---------------------------------------------------------------------------


async def test_check_all_ok(
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
        ("Microphone", True),
        ("Camera", True),
        ("GPT-Live", True),
        ("Vision", True),
        ("Gallery", True),
    ]
    detail = {r.name: r.detail for r in results}
    assert "Yeti" in detail["Microphone"]
    assert "avatar client" in detail["Camera"]
    assert "420 ms" in detail["GPT-Live"] and "60 min" in detail["GPT-Live"]
    assert "gpt-6-luna" in detail["GPT-Live"]
    assert "pong" in detail["Vision"] and "accepts images" in detail["Vision"]
    assert "logo" in detail["Gallery"]
    assert len(fake_live) == 1
    # The vision model: a ping and a minimal request with an image.
    assert fake_llm.pings == 1
    assert len(fake_llm.probes) == 1
    assert fake_llm.probes[0]["content"][1]["type"] == "image_url"

    assert cli.print_results(results) is True
    out = capsys.readouterr().out
    assert out.count("OK  ") == 5
    assert "All set." in out


async def test_check_without_gpt_live_key_is_a_critical_failure(
    tmp_path: Path,
    fake_llm: type[FakeLLMClient],
    fake_audio: list[dict[str, Any]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    results = await cli.run_checks(make_settings(tmp_path, live=LiveSettings(api_key="")))
    live = next(r for r in results if r.name == "GPT-Live")
    assert not live.ok and live.critical
    assert "LIVE_API_KEY" in live.detail
    assert next(r for r in results if r.name == "Vision").ok  # no camera: disabled
    gallery = next(r for r in results if r.name == "Gallery")
    assert gallery.ok is False and gallery.critical is False  # empty: a warning, not a failure

    assert cli.print_results(results) is False
    out = capsys.readouterr().out
    assert "FAIL  GPT-Live" in out
    assert "WARN  Gallery" in out


async def test_check_gpt_live_down_is_a_critical_failure(
    tmp_path: Path,
    fake_llm: type[FakeLLMClient],
    fake_audio: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_probe(settings: LiveSettings) -> ProbeResult:
        raise ConnectionError("no connection")

    monkeypatch.setattr(cli, "probe_session", failing_probe)
    results = await cli.run_checks(make_settings(tmp_path))
    live = next(r for r in results if r.name == "GPT-Live")
    assert not live.ok and live.critical
    assert "no connection" in live.detail


async def test_check_without_microphone_fails(
    tmp_path: Path,
    fake_llm: type[FakeLLMClient],
    fake_live: list[LiveSettings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "list_input_devices", list)
    results = await cli.run_checks(make_settings(tmp_path))
    mic = results[0]
    assert mic.name == "Microphone" and not mic.ok and mic.critical


async def test_check_vision_down_is_only_a_warning(
    tmp_path: Path,
    fake_llm: type[FakeLLMClient],
    fake_live: list[LiveSettings],
    fake_audio: list[dict[str, Any]],
) -> None:
    """Sonnia converses without eyes too: a vision model failure does not stop her."""
    fake_llm.reply = LLMError("The model server returned 503", status_code=503)
    results = await cli.run_checks(make_settings(tmp_path, vision=VisionSettings(source="unity")))
    vision = next(r for r in results if r.name == "Vision")
    assert vision.ok is False and vision.critical is False
    assert "503" in vision.detail
    assert cli.print_results(results) is True


async def test_check_warns_if_the_model_does_not_accept_images(
    tmp_path: Path,
    fake_llm: type[FakeLLMClient],
    fake_live: list[LiveSettings],
    fake_audio: list[dict[str, Any]],
) -> None:
    fake_llm.probe_error = LLMError("The model server returned 400: no vision")
    results = await cli.run_checks(make_settings(tmp_path, vision=VisionSettings(source="unity")))
    vision = next(r for r in results if r.name == "Vision")
    assert vision.ok is False and vision.critical is False
    # It does not suggest turning the whole camera off: what fails is the model settings.
    assert "LLM_API_KEY" in vision.detail and "LLM_SUPPORTS_VISION=false" not in vision.detail


async def test_the_openai_key_never_goes_to_another_provider(
    tmp_path: Path,
    fake_llm: type[FakeLLMClient],
    fake_live: list[LiveSettings],
    fake_audio: list[dict[str, Any]],
) -> None:
    other = LLMSettings(
        base_url="https://api.example-llm.test/v1", api_key="", openai_api_key="openai-key"
    )
    assert other.key == ""
    assert LLMSettings(base_url="https://api.openai.com/v1", openai_api_key="o").key == "o"
    assert LLMSettings(base_url="https://api.example-llm.test/v1", api_key="k").key == "k"
    # Without a key for that provider, the camera turns off instead of failing every turn.
    settings = make_settings(tmp_path, vision=VisionSettings(source="unity"), llm=other)
    components = cli.build_components(settings)
    assert not components.policy.enabled and components.llm is None
    results = await cli.run_checks(settings)
    vision = next(r for r in results if r.name == "Vision")
    assert vision.ok is False and "LLM_API_KEY is missing" in vision.detail


def _jpeg_segments(raw: bytes) -> list[tuple[int, int]]:
    """(marker, length) of each segment up to SOS; fails if there are loose bytes between them."""
    assert raw[:2] == b"\xff\xd8", "does not start with SOI"
    assert raw[-2:] == b"\xff\xd9", "does not end with EOI"
    segments: list[tuple[int, int]] = []
    pos = 2
    while True:
        assert raw[pos] == 0xFF, f"loose bytes before the marker at byte {pos}"
        marker = raw[pos + 1]
        length = int.from_bytes(raw[pos + 2 : pos + 4], "big")
        segments.append((marker, length))
        if marker == 0xDA:  # SOS: the image data starts here
            return segments
        pos += 2 + length


def test_the_check_probe_image_is_a_valid_jpeg() -> None:
    """A corrupt image would make a strict server report vision as broken."""
    raw = base64.b64decode(cli._PROBE_JPEG_B64, validate=True)
    markers = [marker for marker, _ in _jpeg_segments(raw)]
    assert markers.count(0xDB) == 2  # quantization tables
    assert 0xC0 in markers  # SOF0: dimensions
    assert markers.count(0xC4) == 4  # Huffman tables
    assert len(raw) < 2_000  # still tiny


def test_the_probe_image_decodes() -> None:
    cv2 = pytest.importorskip("cv2")
    raw = base64.b64decode(cli._PROBE_JPEG_B64, validate=True)
    image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    height, width = image.shape[:2]
    assert min(height, width) >= 56  # above the minimum of any vision model


def test_main_check_returns_the_exit_code(
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


def test_say_saves_a_wav(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    said: list[str] = []

    async def fake_speak(settings: LiveSettings, text: str) -> bytes:
        said.append(text)
        return np.full(int(0.5 * settings.sample_rate), 1000, dtype="<i2").tobytes()

    monkeypatch.setattr(cli, "speak_text", fake_speak)
    monkeypatch.setattr(cli, "load_settings", lambda: make_settings(tmp_path))
    out = tmp_path / "hello.wav"
    assert cli.main(["say", "Hello, Sonia.", "--out", str(out)]) == 0

    assert said == ["Hello, Sonia."]
    with wave.open(str(out), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 24_000
        assert wav.getnframes() == 12_000
    assert "Saved to" in capsys.readouterr().out


def test_say_without_key_exits_with_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = make_settings(tmp_path, live=LiveSettings(api_key=""))
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    assert cli.main(["say", "Hello"]) == 1
    assert "LIVE_API_KEY" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# sonia chat: the console tap
# ---------------------------------------------------------------------------


async def test_console_tap_prints_and_confirms_playback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    hub = Hub(WSSettings(host="127.0.0.1", port=0), sample_rate=24_000)
    tap = cli.ConsoleTap(hub)
    done: list[int] = []
    tap.playback_done = done.append

    await tap.broadcast_json(p.msg_state("thinking"))
    await tap.broadcast_json(p.msg_transcript("user", "hi there", True))
    await tap.broadcast_json(p.msg_transcript("assistant", "Hi, how are you?", True))
    await tap.send_audio(3, AudioChunk(pcm=b"\x00\x00", sample_rate=24_000, is_last=True))
    await tap.broadcast_json(p.msg_speech_end(3))
    await tap.broadcast_json(p.msg_error("the model went down"))
    await tap.show_image(
        image_id="logo", source="gallery", mime="image/png", data=b"x", caption="L"
    )
    await tap.hide_image()

    out = capsys.readouterr().out
    assert "[thinking]" in out
    assert "Sonnia: Hi, how are you?" in out
    assert "hi there" not in out  # what the user says is not repeated
    assert "[error] the model went down" in out
    assert "[image: logo (gallery, 1 bytes) — L]" in out
    assert "[image hidden]" in out
    assert done == [3]  # without a local player, speech_end confirms the utterance


async def test_console_tap_does_not_confirm_when_a_client_is_connected() -> None:
    """With a client connected it sends its own ``playback_done``, not the console shortcut.

    Confirming here would bring `idle` forward by up to two seconds and the avatar
    would go back to its idle animation with the mouth still moving.
    """
    from websockets.asyncio.client import connect

    hub = Hub(WSSettings(host="127.0.0.1", port=0), sample_rate=24_000)
    tap = cli.ConsoleTap(hub)
    done: list[int] = []
    tap.playback_done = done.append

    async with hub, connect(f"ws://127.0.0.1:{hub.port}/") as client:
        await asyncio.wait_for(client.recv(), 2.0)  # hello
        async with asyncio.timeout(2.0):
            while hub.client_count == 0:  # noqa: ASYNC110 - deliberate polling
                await asyncio.sleep(0.01)
        await tap.broadcast_json(p.msg_speech_end(1))
        assert done == []

    async with asyncio.timeout(2.0):
        while hub.client_count:  # noqa: ASYNC110 - deliberate polling
            await asyncio.sleep(0.01)
    await tap.broadcast_json(p.msg_speech_end(2))
    assert done == [2]
    await hub.stop()


async def test_build_components_without_camera(tmp_path: Path) -> None:
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


async def test_build_components_with_the_client_camera(tmp_path: Path) -> None:
    settings = make_settings(
        tmp_path,
        live=LiveSettings(api_key="key", sample_rate=16_000),
        vision=VisionSettings(source="unity"),
    )
    components = cli.build_components(settings)
    try:
        assert components.hub.sample_rate == 16_000
        assert components.registry.names() == ["look", "show_image", "hide_image", "play_animation"]
        assert components.narrator is not None
    finally:
        await components.close()


def test_run_without_key_exits_with_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = make_settings(tmp_path, live=LiveSettings(api_key=""))
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    assert cli.main(["run", "--no-mic"]) == 1
    assert "LIVE_API_KEY" in capsys.readouterr().err
