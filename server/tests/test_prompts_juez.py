"""Prompts del juez de las rondas de cámara y del director de gestos editables desde la nube.

Sin red: modelos falsos que apuntan los mensajes. Con los textos de la app, lo que se manda
tiene que ser idéntico a lo de antes (``snapshots/prompts_juez.json``, sacada con el código
sin cambiar).
"""

from __future__ import annotations

from typing import Any

import numpy as np

from sonia.gestures.prompt import Cooldowns, build_user_message
from sonia.llm import Completion
from sonia.types import Message
from sonia.vision.judge import ModelJudge
from sonia.vision.referee import GeminiReferee
from tests.prompt_snapshots import assert_snapshot
from tests.test_gestures import FakeGestureLLM, make_director
from tests.test_vision_judge import FakeCamera


class RecordingLLM:
    """Contesta siempre lo mismo y apunta los mensajes."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.messages: list[list[Message]] = []

    async def complete(self, messages: list[Message]) -> Completion:
        self.messages.append(messages)
        return Completion(content=self.reply, prompt_tokens=1350)


def _text_parts(message: Message) -> Any:
    """El contenido de un mensaje sin la foto (que cambia con la codificación)."""
    content = message["content"]
    if isinstance(content, str):
        return content
    return [part["text"] for part in content if part.get("type") == "text"]


def _sent(messages: list[Message]) -> list[dict[str, Any]]:
    return [{"role": m["role"], "content": _text_parts(m)} for m in messages]


def _frame() -> np.ndarray:
    return np.zeros((360, 640, 3), dtype=np.uint8)


async def _judge_messages() -> list[dict[str, Any]]:
    llm = RecordingLLM('{"visto": true, "objeto": "botella azul"}')
    judge = ModelJudge(llm, FakeCamera())
    assert await judge.ask("  ¿Alguien enseña algo azul a la cámara?  ") is not None
    return _sent(llm.messages[0])


async def _referee_messages() -> dict[str, list[dict[str, Any]]]:
    poses = RecordingLLM('{"personas": 1, "brazos_arriba": 1}')
    hands = RecordingLLM('{"manos": ["piedra"]}')
    assert await GeminiReferee(poses, timeout_s=4).poses(_frame()) is not None
    assert await GeminiReferee(hands, timeout_s=4).hands(_frame()) is not None
    return {"poses": _sent(poses.messages[0]), "manos": _sent(hands.messages[0])}


async def _gesture_messages() -> dict[str, Any]:
    llm = FakeGestureLLM('{"gesto": "wave"}')
    director, _ = make_director(llm)
    choice = await director.choose_requested("  tocarse   un ojo ")
    assert choice.name == "wave"
    return {
        "sistema": director.system_prompt,
        "peticion": _sent(llm.requests[0]),
        "peticion_larga": await _long_request(),
        "usuario_apertura": build_user_message(
            opening=True, user_text="Hola, ¿qué tal?", said=(), recent=()
        ),
        "usuario_frase": build_user_message(
            opening=False,
            user_text="¿Qué hace Sonnet Code?",
            said=("Pues mira,",),
            phrase_text="hacemos software a medida",
            phrase_index=2,
            phrase_age_s=1.25,
            recent=(("wave", 30.0), ("explain", 200.0)),
            cooldowns=Cooldowns(rare_left_s=120.0, uncommon_left_s=10.0, repeated=("wave",)),
        ),
    }


async def _long_request() -> str:
    llm = FakeGestureLLM('{"gesto": "ninguno"}')
    director, _ = make_director(llm)
    await director.choose_requested("hacer un truco de magia " * 20)
    return str(llm.requests[0][1]["content"])


async def test_con_los_textos_de_la_app_no_cambia_nada() -> None:
    assert_snapshot(
        "prompts_juez",
        {
            "juez_busqueda": await _judge_messages(),
            "juez_rondas": await _referee_messages(),
            "gestos": await _gesture_messages(),
        },
    )
