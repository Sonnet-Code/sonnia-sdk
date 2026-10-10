"""El respaldo del juez de la búsqueda: si Gemini falla, la misma foto va a luna. Sin red."""

from __future__ import annotations

import asyncio
from typing import Any

from sonia.llm import Completion, LLMError
from sonia.vision.contracts import JudgeAnswer
from sonia.vision.judge import ModelJudge
from tests.test_vision_judge import FakeCamera

SEEN = '{"visto": true, "objeto": "botella azul"}'
NOT_SEEN = '{"visto": false, "objeto": ""}'


class FakeLLM:
    """Contesta ``reply`` (o lanza ``error``) tras ``delay`` segundos; apunta los mensajes."""

    def __init__(self, reply: str = SEEN, *, delay: float = 0.0, error: Exception | None = None):
        self.reply = reply
        self.delay = delay
        self.error = error
        self.messages: list[list[dict[str, Any]]] = []

    async def complete(self, messages: list[dict[str, Any]]) -> Completion:
        self.messages.append(messages)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return Completion(content=self.reply)


def judge_with(gemini: FakeLLM, luna: FakeLLM | None, camera: FakeCamera | None = None) -> Any:
    return ModelJudge(
        gemini,
        camera or FakeCamera(),
        timeout_s=0.2,
        fallback=luna,
        fallback_timeout_s=0.2,
    )


async def test_si_gemini_falla_luna_contesta_con_la_misma_foto() -> None:
    gemini = FakeLLM(error=LLMError("El servidor del modelo devolvió 429", status_code=429))
    luna = FakeLLM(SEEN)
    camera = FakeCamera()
    judge = judge_with(gemini, luna, camera)
    judge.start_round(3)
    assert await judge.ask("¿Se ve una botella azul?") == JudgeAnswer(True, "botella azul")
    # Una pregunta, una foto: la misma va a los dos y cuenta una sola vez para el tope.
    assert len(camera.requests) == 1
    assert luna.messages == gemini.messages
    assert (judge.calls, judge.remaining, judge.fallback_calls) == (1, 2, 1)


async def test_si_gemini_contesta_luna_no_se_llama() -> None:
    gemini, luna = FakeLLM(SEEN), FakeLLM(SEEN)
    judge = judge_with(gemini, luna)
    assert await judge.ask("¿Se ve una botella azul?") == JudgeAnswer(True, "botella azul")
    # Un «no se ve» también es una respuesta: no se pregunta a luna.
    gemini.reply = NOT_SEEN
    assert await judge.ask("¿Se ve una botella azul?") == JudgeAnswer(False, "")
    assert luna.messages == []
    assert judge.fallback_calls == 0


async def test_si_gemini_no_llega_a_tiempo_o_contesta_raro_va_a_luna() -> None:
    luna = FakeLLM(SEEN)
    slow = judge_with(FakeLLM(SEEN, delay=5.0), luna)
    loop = asyncio.get_running_loop()
    started = loop.time()
    assert await slow.ask("¿Se ve una botella azul?") == JudgeAnswer(True, "botella azul")
    assert loop.time() - started < 2.0
    odd = judge_with(FakeLLM("No puedo ayudar con eso."), luna)
    assert await odd.ask("¿Se ve una botella azul?") == JudgeAnswer(True, "botella azul")
    assert len(luna.messages) == 2


async def test_sin_foto_o_pasado_el_tope_no_se_pregunta_a_ninguno() -> None:
    gemini, luna = FakeLLM(error=RuntimeError("caído")), FakeLLM(SEEN)
    blind = judge_with(gemini, luna, FakeCamera(ok=False))
    assert await blind.ask("¿Se ve una botella azul?") is None
    capped = judge_with(gemini, luna)
    capped.start_round(1)
    assert await capped.ask("¿Se ve una botella azul?") == JudgeAnswer(True, "botella azul")
    assert await capped.ask("¿Se ve una botella azul?") is None
    # Solo la primera pregunta de la segunda llegó a los modelos.
    assert len(gemini.messages) == 1 and len(luna.messages) == 1


async def test_si_fallan_los_dos_no_hay_respuesta() -> None:
    judge = judge_with(FakeLLM(error=RuntimeError("caído")), FakeLLM(error=RuntimeError("caído")))
    assert await judge.ask("¿Se ve una botella azul?") is None


async def test_sin_respaldo_todo_como_antes() -> None:
    judge = judge_with(FakeLLM(error=RuntimeError("caído")), None)
    assert await judge.ask("¿Se ve una botella azul?") is None
    assert judge.fallback_calls == 0
