"""Pruebas de integración del orquestador, sin hardware, modelos ni red.

El modelo es un ``httpx.MockTransport`` que devuelve SSE; el STT y el TTS son
los falsos del repositorio; la cámara es una clase de este archivo; y Unity es
un cliente ``websockets`` conectado a un ``Hub`` real en un puerto libre que
graba todo lo que recibe para comprobar la secuencia exacta de mensajes.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest

from sonia.actions import build_default_registry
from sonia.audio.vad import SpeechDiscarded, SpeechStarted
from sonia.config import (
    AudioSettings,
    LLMSettings,
    MCPSettings,
    Settings,
    ShowcaseSettings,
    STTSettings,
    TTSSettings,
    VisionSettings,
    WSSettings,
)
from sonia.llm.client import LLMClient
from sonia.orchestrator import APOLOGY_TEXT, Interrupt, Orchestrator, TextTurn
from sonia.stt.mock import MockSTT
from sonia.tts.mock import MockTTS
from sonia.types import AudioChunk, Frame, Utterance
from sonia.vision.policy import VisionPolicy
from sonia.ws import protocol as p
from sonia.ws.hub import Hub

# ---------------------------------------------------------------------------
# Modelo falso (SSE)
# ---------------------------------------------------------------------------


def _chunk(delta: dict[str, Any], finish_reason: str | None = None) -> dict[str, Any]:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion.chunk",
        "model": "modelo-de-prueba",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


def _sse(*payloads: dict[str, Any]) -> bytes:
    lines = [f"data: {json.dumps(payload)}\n\n" for payload in payloads]
    lines.append("data: [DONE]\n\n")
    return "".join(lines).encode("utf-8")


def text_stream(*parts: str) -> bytes:
    """Respuesta del modelo con texto troceado en varios deltas."""
    chunks = [_chunk({"role": "assistant", "content": ""})]
    chunks.extend(_chunk({"content": part}) for part in parts)
    chunks.append(_chunk({}, finish_reason="stop"))
    return _sse(*chunks)


def tool_stream(name: str, arguments: dict[str, Any], *, content: str = "") -> bytes:
    """Respuesta del modelo que pide una acción (argumentos en dos deltas)."""
    raw = json.dumps(arguments)
    half = len(raw) // 2
    chunks = [_chunk({"role": "assistant", "content": content})]
    chunks.append(
        _chunk(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": name, "arguments": raw[:half]},
                    }
                ]
            }
        )
    )
    chunks.append(_chunk({"tool_calls": [{"index": 0, "function": {"arguments": raw[half:]}}]}))
    chunks.append(_chunk({}, finish_reason="tool_calls"))
    return _sse(*chunks)


def sse_response(body: bytes) -> httpx.Response:
    async def stream() -> AsyncIterator[bytes]:
        for start in range(0, len(body), 16):
            yield body[start : start + 16]

    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=stream())


Handler = Callable[[httpx.Request], httpx.Response]


def text_handler(captured: list[dict[str, Any]], *parts: str) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return sse_response(text_stream(*parts))

    return handler


# ---------------------------------------------------------------------------
# Colaboradores falsos
# ---------------------------------------------------------------------------


class FakeCamera:
    def __init__(self, data: bytes = b"\xff\xd8jpeg-falso", delay: float = 0.0) -> None:
        self.data = data
        self.delay = delay
        self.captures = 0

    async def capture(self) -> Frame | None:
        self.captures += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return Frame(data=self.data, mime="image/jpeg", width=4, height=3)


class SlowTTS(MockTTS):
    """MockTTS que tarda entre chunks, para poder interrumpirlo a mitad."""

    def __init__(self, delay: float = 0.05, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.delay = delay

    async def synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        async for chunk in super().synthesize(text):
            yield chunk
            await asyncio.sleep(self.delay)


class Recorder:
    """Graba todo lo que recibe el cliente WebSocket de prueba."""

    def __init__(self, client: Any) -> None:
        self.messages: list[Any] = []
        self._event = asyncio.Event()
        self._task = asyncio.create_task(self._pump(client))

    async def _pump(self, client: Any) -> None:
        with contextlib.suppress(Exception):
            async for raw in client:
                if isinstance(raw, bytes | bytearray):
                    self.messages.append(("audio", *p.decode_audio_frame(bytes(raw))))
                else:
                    self.messages.append(json.loads(raw))
                self._event.set()

    async def wait_for(self, predicate: Callable[[list[Any]], bool], limit: float = 3.0) -> None:
        async with asyncio.timeout(limit):
            while not predicate(self.messages):
                self._event.clear()
                await self._event.wait()

    async def wait_state(self, state: str, count: int = 1, limit: float = 3.0) -> None:
        await self.wait_for(lambda msgs: self.states(msgs).count(state) >= count, limit)

    async def wait_type(self, kind: str, count: int = 1, limit: float = 3.0) -> None:
        await self.wait_for(lambda msgs: self.of_type(kind, msgs).__len__() >= count, limit)

    def json(self, msgs: list[Any] | None = None) -> list[dict[str, Any]]:
        return [m for m in (self.messages if msgs is None else msgs) if isinstance(m, dict)]

    def of_type(self, kind: str, msgs: list[Any] | None = None) -> list[dict[str, Any]]:
        return [m for m in self.json(msgs) if m["type"] == kind]

    def states(self, msgs: list[Any] | None = None) -> list[str]:
        return [m["state"] for m in self.of_type("state", msgs)]

    def audio(self, utterance_id: int | None = None) -> list[tuple[str, int, bool, bytes]]:
        frames = [m for m in self.messages if isinstance(m, tuple)]
        if utterance_id is None:
            return frames
        return [f for f in frames if f[1] == utterance_id]

    def kinds(self) -> list[str]:
        """Secuencia de tipos, con los frames binarios contraídos a ``audio``."""
        out: list[str] = []
        for m in self.messages:
            kind = "audio" if isinstance(m, tuple) else m["type"]
            if kind == "audio" and out and out[-1] == "audio":
                continue
            out.append(kind)
        return out

    async def close(self) -> None:
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task


# ---------------------------------------------------------------------------
# Montaje
# ---------------------------------------------------------------------------


def make_settings(
    tmp_path: Path,
    *,
    tool_mode: str = "native",
    vision_source: str = "opencv",
    barge_in: bool = True,
    idle_reset: float = 120.0,
    max_tool_rounds: int = 3,
    showcase: ShowcaseSettings | None = None,
) -> Settings:
    gallery = tmp_path / "gallery"
    gallery.mkdir(exist_ok=True)
    values: dict[str, Any] = dict(
        _env_file=None,
        llm=LLMSettings(
            base_url="http://llm.test/v1",
            model="modelo-de-prueba",
            api_key="clave-de-prueba",
            supports_vision=True,
            tool_mode=tool_mode,  # type: ignore[arg-type]
            reasoning_effort="",
            max_tool_rounds=max_tool_rounds,
            history_turns=12,
            request_timeout=5.0,
        ),
        stt=STTSettings(backend="mock"),
        tts=TTSSettings(backend="mock", sample_rate=24_000),
        audio=AudioSettings(barge_in=barge_in),
        vision=VisionSettings(source=vision_source, on_turn_start=True),  # type: ignore[arg-type]
        ws=WSSettings(host="127.0.0.1", port=0),
        mcp=MCPSettings(enabled=False),
        assets_dir=str(tmp_path),
        log_level="DEBUG",
        idle_reset_seconds=idle_reset,
    )
    if showcase is not None:
        values["showcase"] = showcase
    return Settings(**values)


@dataclass
class Rig:
    settings: Settings
    hub: Hub
    orch: Orchestrator
    client: Any
    rec: Recorder
    captured: list[dict[str, Any]]
    tts: MockTTS
    stt: MockSTT
    camera: FakeCamera | None
    speaking: list[bool] = field(default_factory=list)

    async def send(self, msg: dict[str, Any]) -> None:
        await self.client.send(json.dumps(msg))


@contextlib.asynccontextmanager
async def make_rig(
    tmp_path: Path,
    handler: Handler,
    *,
    captured: list[dict[str, Any]] | None = None,
    stt_texts: Iterable[str] = ("hola sonia",),
    tts: MockTTS | None = None,
    camera: FakeCamera | None = None,
    tick: float = 1.0,
    **settings_overrides: Any,
) -> AsyncIterator[Rig]:
    from websockets.asyncio.client import connect

    settings = make_settings(tmp_path, **settings_overrides)
    captured = [] if captured is None else captured
    tts = tts or MockTTS(ms_per_char=10.0, tone=True)
    stt = MockSTT(list(stt_texts))
    if camera is None and settings.vision.source != "none":
        camera = FakeCamera()
    policy = VisionPolicy(settings.vision, settings.llm.supports_vision)
    registry = build_default_registry(include_look=policy.enabled)
    hub = Hub(settings.ws, sample_rate=tts.sample_rate)
    llm = LLMClient(settings.llm, transport=httpx.MockTransport(handler))
    speaking: list[bool] = []
    orch = Orchestrator(
        settings,
        stt=stt,
        llm=llm,
        tts=tts,
        hub=hub,
        camera=camera,
        vision_policy=policy,
        registry=registry,
        on_speaking_changed=speaking.append,
        tick_s=tick,
    )

    async with hub, connect(f"ws://127.0.0.1:{hub.port}/") as client:
        hello = json.loads(await asyncio.wait_for(client.recv(), 2.0))
        assert hello["type"] == "hello"
        rec = Recorder(client)
        run_task = asyncio.create_task(orch.run())
        await rec.wait_state("idle")  # el orquestador anuncia su estado inicial
        rig = Rig(settings, hub, orch, client, rec, captured, tts, stt, camera, speaking)
        try:
            yield rig
        finally:
            run_task.cancel()
            await asyncio.gather(run_task, return_exceptions=True)
            await rec.close()
            await llm.aclose()


def utterance(seconds: float = 1.0) -> Utterance:
    return Utterance(audio=np.zeros(int(16_000 * seconds), dtype=np.float32))


def add_gallery_image(tmp_path: Path, name: str, data: bytes) -> bytes:
    gallery = tmp_path / "gallery"
    gallery.mkdir(exist_ok=True)
    (gallery / name).write_bytes(data)
    return data


def current_state(rig: Rig) -> str:
    """Estado como cadena (evita que mypy "fije" el enum entre asertos)."""
    return str(rig.orch.state)


def last_user_message(request: dict[str, Any]) -> dict[str, Any]:
    users: list[dict[str, Any]] = [m for m in request["messages"] if m["role"] == "user"]
    return users[-1]


def dangling_tool_calls(messages: list[dict[str, Any]]) -> list[int]:
    """Índices de los ``assistant`` con ``tool_calls`` sin sus mensajes ``tool``.

    Es la secuencia que los servidores compatibles con OpenAI rechazan con un
    400 ("must be followed by tool messages responding to each tool_call_id").
    Una vez en el historial, envenena todas las peticiones siguientes.
    """
    bad: list[int] = []
    for index, message in enumerate(messages):
        if message.get("role") != "assistant" or not message.get("tool_calls"):
            continue
        pending = {call["id"] for call in message["tool_calls"]}
        for later in messages[index + 1 :]:
            if later.get("role") != "tool":
                break
            pending.discard(later.get("tool_call_id"))
        if pending:
            bad.append(index)
    return bad


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_turno_de_voz_completo(tmp_path: Path) -> None:
    captured: list[dict[str, Any]] = []
    handler = text_handler(captured, "Hola, ¿cómo ", "estás? Bienvenido ", "al stand.")

    async with make_rig(tmp_path, handler, captured=captured) as rig:
        await rig.orch.submit(SpeechStarted(at=0.0))
        await rig.rec.wait_state("listening")
        assert current_state(rig) == "listening"

        await rig.orch.submit(utterance())
        await rig.rec.wait_type("speech_end", count=2)

        kinds = rig.rec.kinds()
        # Secuencia exacta hasta el final de la segunda frase.
        assert kinds[: kinds.index("speech_end") + 1] == [
            "state",  # idle inicial
            "state",  # listening
            "state",  # thinking
            "transcript",  # usuario
            "transcript",  # asistente, frase 1
            "speech_start",
            "state",  # speaking
            "audio",
            "visemes",
            "envelope",
            "speech_end",
        ]
        assert rig.rec.states() == ["idle", "listening", "thinking", "speaking"]

        transcripts = rig.rec.of_type("transcript")
        assert transcripts[0] == {
            "type": "transcript",
            "role": "user",
            "text": "hola sonia",
            "final": True,
        }
        assert [t["text"] for t in transcripts[1:]] == [
            "Hola, ¿cómo estás?",
            "Bienvenido al stand.",
        ]

        starts = rig.rec.of_type("speech_start")
        assert [(s["utterance_id"], s["text"]) for s in starts] == [
            (1, "Hola, ¿cómo estás?"),
            (2, "Bienvenido al stand."),
        ]

        # Frames binarios: todos con su utterance_id, el último marcado, y con
        # exactamente el audio que produjo el TTS.
        for uid, text in ((1, "Hola, ¿cómo estás?"), (2, "Bienvenido al stand.")):
            frames = rig.rec.audio(uid)
            assert frames, uid
            assert [f[2] for f in frames] == [False] * (len(frames) - 1) + [True]
            pcm = b"".join(f[3] for f in frames)
            expected = int(rig.tts.duration_for(text) * rig.tts.sample_rate) * 2
            assert len(pcm) == expected

        visemes = rig.rec.of_type("visemes")
        assert [v["utterance_id"] for v in visemes] == [1, 2]
        assert visemes[0]["frames"][0]["v"] in ("oh", "sil")
        assert visemes[0]["frames"][-1]["v"] == "sil"
        assert visemes[0]["frames"][-1]["t"] == pytest.approx(
            rig.tts.duration_for("Hola, ¿cómo estás?"), abs=0.01
        )
        envelopes = rig.rec.of_type("envelope")
        assert [e["utterance_id"] for e in envelopes] == [1, 2]
        assert envelopes[0]["interval_ms"] == 20
        assert max(envelopes[0]["values"]) == 1.0
        assert [e["utterance_id"] for e in rig.rec.of_type("speech_end")] == [1, 2]

        # Sigue en speaking hasta que Unity confirma la última frase.
        await asyncio.sleep(0.05)
        assert current_state(rig) == "speaking"
        await rig.send({"type": "playback_done", "utterance_id": 1})
        await asyncio.sleep(0.05)
        assert current_state(rig) == "speaking"
        await rig.send({"type": "playback_done", "utterance_id": 2})
        await rig.rec.wait_state("idle", count=2)
        assert current_state(rig) == "idle"
        assert rig.speaking == [True, False]

        # La captura de cámara del SpeechStarted viajó con el turno.
        assert rig.camera is not None and rig.camera.captures == 1
        assert len(captured) == 1
        user = last_user_message(captured[0])
        assert user["content"][0] == {"type": "text", "text": "hola sonia"}
        assert user["content"][1]["type"] == "image_url"
        assert user["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        assert captured[0]["tools"][0]["function"]["name"] == "look"

        # Historial coherente: usuario + asistente con el texto completo.
        history = rig.orch.conversation.messages()
        assert [m["role"] for m in history] == ["system", "user", "assistant"]
        assert history[-1]["content"] == "Hola, ¿cómo estás? Bienvenido al stand."
        assert rig.stt.calls and rig.stt.calls[0].duration == pytest.approx(1.0)


async def test_text_input_por_ws_sigue_el_mismo_flujo(tmp_path: Path) -> None:
    captured: list[dict[str, Any]] = []
    handler = text_handler(captured, "Claro que sí.")

    async with make_rig(tmp_path, handler, captured=captured, vision_source="none") as rig:
        await rig.send({"type": "text_input", "text": "¿Qué es Sonnet Code?"})
        await rig.rec.wait_type("speech_end")
        assert rig.rec.kinds()[1:] == [
            "state",  # thinking (sin listening: no hubo SpeechStarted)
            "transcript",
            "transcript",
            "speech_start",
            "state",
            "audio",
            "visemes",
            "envelope",
            "speech_end",
        ]
        assert rig.rec.of_type("transcript")[0]["text"] == "¿Qué es Sonnet Code?"
        assert rig.rec.of_type("speech_start")[0]["text"] == "Claro que sí."
        assert rig.orch.turn_active
        assert await rig.orch.wait_idle(limit_s=0.05) is False
        await rig.send({"type": "playback_done", "utterance_id": 1})
        await rig.rec.wait_state("idle", count=2)
        assert await rig.orch.wait_idle(limit_s=1.0) is True

        # Sin visión no se anuncia `look` y el mensaje de usuario es texto plano.
        assert [t["function"]["name"] for t in captured[0]["tools"]] == [
            "show_image",
            "hide_image",
        ]
        assert last_user_message(captured[0]) == {
            "role": "user",
            "content": "¿Qué es Sonnet Code?",
        }
        assert rig.stt.calls == []  # el texto no pasa por el STT


async def test_tool_call_show_image_y_luego_texto(tmp_path: Path) -> None:
    logo = add_gallery_image(tmp_path, "logo-sonnet.png", b"\x89PNG\r\n\x1a\nlogo-de-prueba")
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured.append(body)
        if any(m["role"] == "tool" for m in body["messages"]):
            return sse_response(text_stream("Este es el logo de Sonnet Code."))
        return sse_response(
            tool_stream(
                "show_image",
                {"image_id": "logo-sonnet", "caption": "Sonnet Code"},
                content="Mira.",
            )
        )

    async with make_rig(tmp_path, handler, captured=captured, vision_source="none") as rig:
        await rig.orch.submit(TextTurn("enséñame el logo"))
        await rig.rec.wait_type("speech_end", count=2)

        shown = rig.rec.of_type("show_image")
        assert len(shown) == 1
        assert shown[0]["image_id"] == "logo-sonnet"
        assert shown[0]["source"] == "gallery"
        assert shown[0]["mime"] == "image/png"
        assert shown[0]["caption"] == "Sonnet Code"
        assert base64.b64decode(shown[0]["data_base64"]) == logo

        # Lo que dijo antes de la acción se habla, y la imagen llega antes de
        # la frase de la segunda ronda.
        kinds = rig.rec.kinds()
        assert kinds.index("show_image") < kinds.index("speech_end")
        assert [s["text"] for s in rig.rec.of_type("speech_start")] == [
            "Mira.",
            "Este es el logo de Sonnet Code.",
        ]

        # Segunda petición: assistant con tool_calls + resultado de la acción.
        assert len(captured) == 2
        messages = captured[1]["messages"]
        assert messages[-2]["role"] == "assistant"
        assert messages[-2]["content"] == "Mira."
        assert messages[-2]["tool_calls"][0]["id"] == "call_1"
        assert messages[-2]["tool_calls"][0]["function"]["name"] == "show_image"
        assert json.loads(messages[-2]["tool_calls"][0]["function"]["arguments"]) == {
            "image_id": "logo-sonnet",
            "caption": "Sonnet Code",
        }
        assert messages[-1] == {
            "role": "tool",
            "tool_call_id": "call_1",
            "name": "show_image",
            "content": "Mostrando la imagen 'logo-sonnet'.",
        }
        # El prompt de sistema anuncia el id de la galería.
        assert "logo-sonnet" in captured[0]["messages"][0]["content"]

        await rig.send({"type": "playback_done", "utterance_id": 2})
        await rig.rec.wait_state("idle", count=2)
        roles = [m["role"] for m in rig.orch.conversation.messages()]
        assert roles == ["system", "user", "assistant", "tool", "assistant"]


async def test_look_adjunta_la_imagen_al_modelo(tmp_path: Path) -> None:
    captured: list[dict[str, Any]] = []
    camera = FakeCamera(b"\xff\xd8foto")

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured.append(body)
        if any(m["role"] == "tool" for m in body["messages"]):
            return sse_response(text_stream("Veo a dos personas."))
        return sse_response(tool_stream("look", {}))

    async with make_rig(tmp_path, handler, captured=captured, camera=camera) as rig:
        # Turno de texto: sin SpeechStarted, la política captura al empezar.
        await rig.orch.submit(TextTurn("¿qué ves?"))
        await rig.rec.wait_type("speech_end")
        await rig.send({"type": "playback_done", "utterance_id": 1})
        await rig.rec.wait_state("idle", count=2)

        assert camera.captures == 2  # una de la política y otra de `look`
        second = captured[1]["messages"]
        assert second[-1]["role"] == "user"
        assert second[-1]["content"][0]["text"] == "[Imagen de la cámara pedida por la acción look]"
        assert second[-1]["content"][1]["type"] == "image_url"
        assert second[-2] == {
            "role": "tool",
            "tool_call_id": "call_1",
            "name": "look",
            "content": "Captura tomada.",
        }
        assert rig.orch.last_frame is not None
        # En el historial final la imagen de `look` sigue en el turno actual.
        history = rig.orch.conversation.messages()
        assert [m["role"] for m in history] == [
            "system",
            "user",
            "assistant",
            "tool",
            "user",
            "assistant",
        ]


async def test_barge_in_cancela_la_sintesis(tmp_path: Path) -> None:
    captured: list[dict[str, Any]] = []
    handler = text_handler(
        captured, "Hola, ¿cómo estás? ", "Bienvenido al stand de Sonnet Code, ", "pasa y mira."
    )
    slow = SlowTTS(delay=0.05, ms_per_char=60.0)

    async with make_rig(
        tmp_path, handler, captured=captured, tts=slow, vision_source="none"
    ) as rig:
        await rig.orch.submit(SpeechStarted(at=0.0))
        await rig.orch.submit(utterance())
        # Esperamos a que haya audio en el aire de la primera frase.
        await rig.rec.wait_for(lambda msgs: len(rig.rec.audio(1)) >= 2)
        assert current_state(rig) == "speaking"
        assert rig.speaking == [True]

        # El usuario empieza a hablar: barge-in.
        await rig.orch.submit(SpeechStarted(at=1.0))
        await rig.rec.wait_state("listening", count=2)
        kinds = rig.rec.kinds()
        stop = kinds.index("stop_speaking")
        assert kinds[stop + 1] == "state"
        assert rig.rec.of_type("stop_speaking")[0]["reason"] == "interrupted"
        assert current_state(rig) == "listening"
        assert rig.speaking == [True, False]
        assert not rig.orch.turn_active

        # Tras el corte no llega más audio (como mucho un frame ya en vuelo)
        # ni ninguna frase nueva.
        await asyncio.sleep(0.2)
        stop_index = next(
            i
            for i, m in enumerate(rig.rec.messages)
            if isinstance(m, dict) and m["type"] == "stop_speaking"
        )
        after = rig.rec.messages[stop_index + 1 :]
        after_kinds = ["audio" if isinstance(m, tuple) else m["type"] for m in after]
        assert after_kinds.count("audio") <= 1
        assert "speech_start" not in after_kinds
        assert "speech_end" not in after_kinds
        assert len(slow.calls) == 1

        # Lo que alcanzó a decir queda en el historial.
        history = rig.orch.conversation.messages()
        assert [m["role"] for m in history] == ["system", "user", "assistant"]
        assert history[-1]["content"] == "Hola, ¿cómo estás?"

        # Resultó ser ruido: se vuelve a idle.
        await rig.orch.submit(SpeechDiscarded(at=1.2))
        await rig.rec.wait_state("idle", count=2)
        assert current_state(rig) == "idle"


async def test_interrupt_desde_unity(tmp_path: Path) -> None:
    handler = text_handler([], "Una frase larga para que dé tiempo a interrumpirla.")
    slow = SlowTTS(delay=0.05, ms_per_char=60.0)

    async with make_rig(tmp_path, handler, tts=slow, vision_source="none") as rig:
        await rig.orch.submit(TextTurn("hola"))
        await rig.rec.wait_for(lambda msgs: len(rig.rec.audio(1)) >= 1)
        await rig.send({"type": "interrupt"})
        await rig.rec.wait_type("stop_speaking")
        await rig.rec.wait_state("idle", count=2)
        assert current_state(rig) == "idle"
        assert not rig.orch.turn_active

        # El orquestador sigue vivo: otro turno funciona.
        await rig.orch.submit(Interrupt())  # sin turno en curso no hace nada
        await rig.orch.submit(TextTurn("otra vez"))
        await rig.rec.wait_type("speech_start", count=2)
        assert rig.rec.of_type("speech_start")[-1]["utterance_id"] == 2


async def test_error_del_llm_no_mata_el_orquestador(tmp_path: Path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls <= 2:  # la primera petición y su reintento fallan
            return httpx.Response(500, text="modelo caído")
        return sse_response(text_stream("Ahora sí."))

    async with make_rig(tmp_path, handler, vision_source="none") as rig:
        await rig.orch.submit(TextTurn("hola"))
        await rig.rec.wait_type("error", limit=5.0)
        await rig.rec.wait_type("speech_end")
        assert "500" in rig.rec.of_type("error")[0]["message"]
        assert rig.rec.of_type("speech_start")[0]["text"] == APOLOGY_TEXT
        await rig.send({"type": "playback_done", "utterance_id": 1})
        await rig.rec.wait_state("idle", count=2)
        assert calls == 2
        history = rig.orch.conversation.messages()
        assert history[-1] == {"role": "assistant", "content": APOLOGY_TEXT}

        # Segundo turno: el modelo vuelve y todo sigue funcionando.
        await rig.orch.submit(TextTurn("¿sigues ahí?"))
        await rig.rec.wait_type("speech_end", count=2)
        assert rig.rec.of_type("speech_start")[-1]["text"] == "Ahora sí."
        await rig.send({"type": "playback_done", "utterance_id": 2})
        await rig.rec.wait_state("idle", count=3)
        assert calls == 3


async def test_modo_prompt_ejecuta_las_acciones_del_texto(tmp_path: Path) -> None:
    add_gallery_image(tmp_path, "diagrama.png", b"\x89PNGdiagrama")
    captured: list[dict[str, Any]] = []
    handler = text_handler(
        captured,
        "Te lo enseño. <act",
        'ion>{"name": "show_image", "arguments": {"image_id": "diagrama"}}</action>',
        " Este es el diagrama.",
    )

    async with make_rig(tmp_path, handler, captured=captured, tool_mode="prompt") as rig:
        await rig.orch.submit(TextTurn("muéstrame el diagrama"))
        await rig.rec.wait_type("speech_end", count=2)
        await rig.send({"type": "playback_done", "utterance_id": 2})
        await rig.rec.wait_state("idle", count=2)

        assert [s["text"] for s in rig.rec.of_type("speech_start")] == [
            "Te lo enseño.",
            "Este es el diagrama.",
        ]
        assert rig.rec.of_type("show_image")[0]["image_id"] == "diagrama"
        # Una sola petición: no hace falta otra ronda si ya habló.
        assert len(captured) == 1
        assert "tools" not in captured[0]
        system = captured[0]["messages"][0]["content"]
        assert "<action>" in system and "show_image" in system
        # El historial guarda el texto tal cual, con el bloque de acción.
        assert "<action>" in rig.orch.conversation.messages()[-1]["content"]


async def test_speech_discarded_vuelve_a_idle_y_utterance_vacia_no_llama_al_modelo(
    tmp_path: Path,
) -> None:
    captured: list[dict[str, Any]] = []
    handler = text_handler(captured, "No debería llegar.")

    async with make_rig(tmp_path, handler, captured=captured, stt_texts=("",)) as rig:
        await rig.orch.submit(SpeechStarted(at=0.0))
        await rig.rec.wait_state("listening")
        await rig.orch.submit(SpeechDiscarded(at=0.1, duration=0.1))
        await rig.rec.wait_state("idle", count=2)
        assert rig.rec.states() == ["idle", "listening", "idle"]

        # Un turno cuya transcripción sale vacía vuelve a idle sin hablar.
        await rig.orch.submit(SpeechStarted(at=1.0))
        await rig.orch.submit(utterance())
        await rig.rec.wait_state("idle", count=3)
        assert rig.rec.states() == ["idle", "listening", "idle", "listening", "thinking", "idle"]
        assert captured == []
        assert rig.rec.of_type("transcript") == []


async def test_reinicio_del_historial_por_inactividad(tmp_path: Path) -> None:
    handler = text_handler([], "Hasta luego.")

    async with make_rig(tmp_path, handler, vision_source="none", idle_reset=0.15, tick=0.02) as rig:
        await rig.orch.submit(TextTurn("adiós"))
        await rig.rec.wait_type("speech_end")
        await rig.send({"type": "playback_done", "utterance_id": 1})
        await rig.rec.wait_state("idle", count=2)
        assert len(rig.orch.conversation) == 2

        await rig.rec.wait_type("hide_image", limit=2.0)
        assert len(rig.orch.conversation) == 0
        assert current_state(rig) == "idle"


async def test_agotar_max_tool_rounds_no_deja_tool_calls_sin_respuesta(tmp_path: Path) -> None:
    """El corte por rondas no puede envenenar el historial del resto del día."""
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return sse_response(tool_stream("hide_image", {}, content="Un momento."))

    async with make_rig(
        tmp_path, handler, captured=captured, vision_source="none", max_tool_rounds=2
    ) as rig:
        await rig.orch.submit(TextTurn("quita la imagen"))
        await rig.rec.wait_state("idle", count=2, limit=5.0)

        history = rig.orch.conversation.messages()
        assert dangling_tool_calls(history) == []

        # Y el turno siguiente sale con un historial que el servidor acepta.
        await rig.orch.submit(TextTurn("¿y ahora?"))
        await rig.rec.wait_state("idle", count=3, limit=5.0)
        for request in captured:
            assert dangling_tool_calls(request["messages"]) == []


async def test_interrumpir_durante_una_accion_no_deja_tool_calls_sin_respuesta(
    tmp_path: Path,
) -> None:
    """La cámara tarda; llega un ``interrupt`` justo mientras corre ``look``."""
    captured: list[dict[str, Any]] = []
    camera = FakeCamera(b"\xff\xd8foto", delay=0.5)

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return sse_response(tool_stream("look", {}))

    async with make_rig(tmp_path, handler, captured=captured, camera=camera) as rig:
        await rig.orch.submit(TextTurn("¿qué ves?"))
        # La política captura al empezar el turno; la segunda captura ya es la
        # de `look`, así que ahí dentro es donde tiene que caer la interrupción.
        async with asyncio.timeout(3.0):
            while camera.captures < 2:  # noqa: ASYNC110 - sondeo deliberado
                await asyncio.sleep(0.01)
        await rig.send({"type": "interrupt"})
        await rig.rec.wait_type("stop_speaking", limit=3.0)
        await rig.rec.wait_state("idle", count=2, limit=3.0)

        history = rig.orch.conversation.messages()
        assert dangling_tool_calls(history) == []

        # El orquestador sigue vivo y el turno siguiente va con un historial sano.
        await rig.orch.submit(TextTurn("da igual"))
        await rig.rec.wait_for(lambda msgs: len(captured) >= 2, limit=3.0)
        assert dangling_tool_calls(captured[-1]["messages"]) == []


async def test_respuesta_vacia_del_modelo_se_disculpa_en_voz(tmp_path: Path) -> None:
    """Un stream que termina sin texto (error dentro del SSE) no deja a Sonia muda."""

    def handler(request: httpx.Request) -> httpx.Response:
        return sse_response(text_stream())

    async with make_rig(tmp_path, handler, vision_source="none") as rig:
        await rig.orch.submit(TextTurn("hola"))
        await rig.rec.wait_type("speech_end", limit=5.0)
        assert rig.rec.of_type("speech_start")[0]["text"] == APOLOGY_TEXT
        assert rig.rec.of_type("error")


async def test_sin_barge_in_la_voz_no_interrumpe(tmp_path: Path) -> None:
    handler = text_handler([], "Sigo hablando aunque me hables encima.")
    slow = SlowTTS(delay=0.05, ms_per_char=60.0)

    async with make_rig(tmp_path, handler, tts=slow, vision_source="none", barge_in=False) as rig:
        await rig.orch.submit(TextTurn("hola"))
        await rig.rec.wait_for(lambda msgs: len(rig.rec.audio(1)) >= 1)
        await rig.orch.submit(SpeechStarted(at=1.0))
        await rig.orch.submit(utterance())
        await asyncio.sleep(0.15)
        assert rig.rec.of_type("stop_speaking") == []
        assert current_state(rig) == "speaking"
        assert rig.stt.calls == []  # el turno de voz se descartó sin transcribir
