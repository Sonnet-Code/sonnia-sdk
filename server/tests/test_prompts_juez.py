"""Prompts del juez de las rondas de cámara y del director de gestos editables desde la nube.

Sin red: modelos falsos que apuntan los mensajes. Con los textos de la app, lo que se manda
tiene que ser idéntico a lo de antes (``snapshots/prompts_juez.json``, sacada con el código
sin cambiar).
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np

from sonia.gestures.prompt import Cooldowns, build_user_message
from sonia.llm import Completion
from sonia.prompts import BOOK
from sonia.types import Message
from sonia.vision.judge import JUDGE_PROMPT, ModelJudge
from sonia.vision.referee import GeminiReferee
from tests.prompt_snapshots import assert_snapshot, cloud_prompts
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


# ---------------------------------------------------------------------------
# Versiones de la nube
# ---------------------------------------------------------------------------

JUEZ_NUBE = 'Juez nuevo. Contesta en JSON: {"visto": true o false, "objeto": "..."}.'
POSES_NUBE = (
    'Simón nuevo. Solo JSON: {"personas": N, "brazos_arriba": n, "un_brazo": n, "pose_t": n, '
    '"manos_cabeza": n, "biceps": n, "barbilla": n}.'
)
MANOS_NUBE = 'Manos nuevas. Solo JSON: {"manos": ["piedra" | "papel" | "tijera"]}.'
GESTOS_NUBE = 'Director nuevo de {character}. Contesta en JSON: {"gesto": "..."}.\n{gestures}'
PETICION_NUBE = 'Haz esto: {request}. Contesta {"gesto": "..."}.'


def test_las_piezas_del_juez_y_de_los_gestos_validan_con_su_texto_de_la_app() -> None:
    ids = (
        "juez/busqueda",
        "juez/poses",
        "juez/piedra_papel_tijera",
        "gestos/sistema",
        "gestos/peticion",
    )
    for prompt_id in ids:
        assert prompt_id in BOOK
        assert BOOK.validate(prompt_id, BOOK.default(prompt_id)) == [], prompt_id
        assert BOOK.spec(prompt_id).applies == "peticion"
    assert BOOK.spec("juez/busqueda").group == BOOK.spec("juez/poses").group == "Juez (Gemini)"
    assert BOOK.spec("gestos/sistema").group == "Gestos"
    # Lo que necesita el código para entender la respuesta no se puede quitar.
    assert BOOK.validate("juez/busqueda", "Contesta en JSON si se ve.")
    assert BOOK.validate("juez/poses", POSES_NUBE.replace('"barbilla": n', ""))
    assert BOOK.validate("juez/piedra_papel_tijera", MANOS_NUBE.replace('"tijera"', "tijeras"))
    assert BOOK.validate("gestos/sistema", GESTOS_NUBE.replace("{gestures}", ""))


async def test_el_juez_usa_la_version_de_la_nube_y_no_la_de_la_app() -> None:
    app = await _judge_messages()
    with cloud_prompts(
        {
            "juez/busqueda": JUEZ_NUBE,
            "juez/poses": POSES_NUBE,
            "juez/piedra_papel_tijera": MANOS_NUBE,
        }
    ):
        judge = await _judge_messages()
        rounds = await _referee_messages()
    assert judge[0]["content"] == JUEZ_NUBE
    assert judge[1] == app[1]  # la pregunta del reto no cambia
    assert rounds["poses"][0]["content"] == POSES_NUBE
    assert rounds["manos"][0]["content"] == MANOS_NUBE
    sent = json.dumps([judge, rounds], ensure_ascii=False)
    assert "Eres el juez" not in sent
    # Al quitarla, vuelve la de la app.
    assert await _judge_messages() == app


async def test_los_gestos_usan_la_version_de_la_nube_y_no_la_de_la_app() -> None:
    llm = FakeGestureLLM('{"gesto": "wave"}')
    director, _ = make_director(llm)
    app_system = director.system_prompt
    with cloud_prompts({"gestos/sistema": GESTOS_NUBE, "gestos/peticion": PETICION_NUBE}):
        # Vale desde la siguiente petición, sin catálogo nuevo.
        await director.choose_requested("tocarse un ojo")
    system_sent, user_sent = (m["content"] for m in llm.requests[0])
    assert isinstance(system_sent, str)
    assert system_sent.startswith("Director nuevo de Sage. Contesta en JSON")
    assert "\n- wave · Standard" in system_sent  # el catálogo entra por {gestures}
    assert "Eres el director de gestos" not in system_sent
    assert user_sent == 'Haz esto: «tocarse un ojo». Contesta {"gesto": "..."}.'
    assert director.system_prompt == app_system


def test_una_version_de_la_nube_que_no_vale_no_se_usa() -> None:
    warnings = BOOK.set_overrides(
        {"juez/busqueda": "Sin formato.", "gestos/sistema": "Sin catálogo, en JSON: gesto"}
    )
    try:
        assert len(warnings) == 2
        assert BOOK.source("juez/busqueda") == BOOK.source("gestos/sistema") == "app"
        assert BOOK.text("juez/busqueda") == JUDGE_PROMPT
    finally:
        BOOK.set_overrides(None)
