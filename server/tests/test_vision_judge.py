"""El juez de la búsqueda relámpago con ``httpx.MockTransport``: nunca la API real."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx
import pytest

from sonia.config import LLMSettings
from sonia.llm import Completion, LLMClient
from sonia.types import Frame, Message
from sonia.vision.contracts import JudgeAnswer
from sonia.vision.judge import JUDGE_PROMPT, ModelJudge, parse_judge_answer

JPEG = b"\xff\xd8\xff\xe0 foto falsa \xff\xd9"


class FakeCamera:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.requests: list[tuple[int | None, int | None]] = []

    async def capture(
        self, *, max_width: int | None = None, quality: int | None = None
    ) -> Frame | None:
        self.requests.append((max_width, quality))
        if not self.ok:
            return None
        return Frame(
            data=JPEG, mime="image/jpeg", width=640, height=360, captured_at=time.monotonic()
        )


def completion_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "modelo-de-vision",
            "choices": [
                {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
            ],
        },
    )


def make_client(handler: Any) -> LLMClient:
    settings = LLMSettings(
        base_url="https://vision.invalid/v1", api_key="clave-de-prueba", model="vision"
    )
    return LLMClient(settings, transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"visto": true, "objeto": "botella azul"}', JudgeAnswer(True, "botella azul")),
        ('```json\n{"visto": false, "objeto": ""}\n```', JudgeAnswer(False, "")),
        (
            'Claro: {"visto": true, "objeto": " llaves  rojas "} ¡listo!',
            JudgeAnswer(True, "llaves rojas"),
        ),
        ('{"visto": false, "objeto": "botella"}', JudgeAnswer(False, "")),
        ('{"visto": true}', JudgeAnswer(True, "")),
    ],
)
def test_parse_judge_answer_acepta_el_json(text: str, expected: JudgeAnswer) -> None:
    assert parse_judge_answer(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "sí, la veo",
        '{"visto": "sí", "objeto": "botella"}',
        '{"objeto": "botella"}',
        "[true]",
        "{roto",
    ],
)
def test_parse_judge_answer_rechaza_lo_que_no_cuadra(text: str) -> None:
    assert parse_judge_answer(text) is None


def test_parse_judge_answer_recorta_objetos_largos() -> None:
    answer = parse_judge_answer(json.dumps({"visto": True, "objeto": "x" * 200}))
    assert answer is not None and len(answer.what) <= 60


def test_el_prompt_prohibe_describir_personas() -> None:
    assert "Nunca describas a las personas" in JUDGE_PROMPT
    assert '"visto"' in JUDGE_PROMPT and '"objeto"' in JUDGE_PROMPT


async def test_el_juez_manda_la_foto_y_la_pregunta_y_entiende_la_respuesta() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return completion_response('{"visto": true, "objeto": "botella azul"}')

    camera = FakeCamera()
    async with make_client(handler) as client:
        judge = ModelJudge(client, camera)
        assert judge.available
        answer = await judge.ask("¿Alguien enseña algo azul a la cámara?")
    assert answer == JudgeAnswer(seen=True, what="botella azul")
    assert camera.requests == [(640, 75)]  # foto reducida
    assert judge.calls == 1 and judge.total_calls == 1
    (body,) = bodies
    assert body["stream"] is False
    messages = body["messages"]
    assert messages[0] == {"role": "system", "content": JUDGE_PROMPT}
    parts = messages[1]["content"]
    assert parts[0] == {"type": "text", "text": "¿Alguien enseña algo azul a la cámara?"}
    assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


async def test_el_tope_de_la_ronda_se_respeta_sin_llamar() -> None:
    requests: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(1)
        return completion_response('{"visto": false, "objeto": ""}')

    async with make_client(handler) as client:
        judge = ModelJudge(client, FakeCamera())
        judge.start_round(2)
        assert judge.remaining == 2
        assert await judge.ask("¿algo rojo?") == JudgeAnswer(False, "")
        assert await judge.ask("¿algo rojo?") == JudgeAnswer(False, "")
        assert judge.remaining == 0
        assert await judge.ask("¿algo rojo?") is None
        assert len(requests) == 2
        judge.start_round(1)
        assert await judge.ask("¿una botella?") is not None
        assert judge.total_calls == 3
        judge.start_round(None)
        assert judge.remaining is None


async def test_sin_foto_no_se_llama_ni_se_cuenta() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no debía llamar al modelo")

    async with make_client(handler) as client:
        judge = ModelJudge(client, FakeCamera(ok=False))
        judge.start_round(3)
        assert await judge.ask("¿algo azul?") is None
        assert judge.calls == 0


async def test_errores_y_respuestas_raras_dan_none() -> None:
    replies = iter(
        [
            httpx.Response(500, text="caído"),
            completion_response("no sé qué es eso"),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return next(replies)

    async with make_client(handler) as client:
        judge = ModelJudge(client, FakeCamera())
        assert await judge.ask("¿algo azul?") is None
        assert await judge.ask("¿algo azul?") is None
        assert judge.calls == 2  # las fotos que salieron cuentan para el tope


class SlowLLM:
    async def complete(self, messages: list[Message]) -> Completion:
        await asyncio.sleep(5)
        return Completion(content='{"visto": true, "objeto": "tarde"}')


async def test_si_el_modelo_tarda_se_sigue_sin_respuesta() -> None:
    judge = ModelJudge(SlowLLM(), FakeCamera(), timeout_s=0.05)
    started = time.monotonic()
    assert await judge.ask("¿algo azul?") is None
    assert time.monotonic() - started < 1.0
    assert judge.last_seconds < 1.0
