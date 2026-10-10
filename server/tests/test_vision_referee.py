"""El juez de las rondas con Gemini (``sonia.vision.referee``) y su montaje, sin red.

Ninguna llamada real: un LLM falso que apunta los mensajes o tarda lo que se le diga, y
``build_game_vision`` con clientes que nunca llegan a mandar nada.
"""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest

from sonia.config import Settings
from sonia.games.poses.rules import POSE_IDS
from sonia.llm import Completion, LLMClient
from sonia.vision import models as models_module
from sonia.vision.camera import OpenCVCamera
from sonia.vision.contracts import HandShape, HandVerdict, NoReferee, PoseVerdict
from sonia.vision.games import NoJudge, SwitchedJudge, SwitchedReferee, build_game_vision
from sonia.vision.judge import FallbackJudge, ModelJudge
from sonia.vision.referee import (
    HANDS_PROMPT,
    HANDS_QUESTION,
    POSE_KEYS,
    POSES_PROMPT,
    POSES_QUESTION,
    REFEREE_MAX_TOKENS,
    GeminiReferee,
    gemini_llm_settings,
    parse_hand_verdict,
    parse_pose_verdict,
)

GOOD_POSES = (
    '{"personas": 3, "brazos_arriba": 2, "un_brazo": 1, "pose_t": 0, "manos_cabeza": 0, '
    '"biceps": 0, "barbilla": 0, "ninguna": 0}'
)


# ---------------------------------------------------------------------------
# Respuestas
# ---------------------------------------------------------------------------


def test_el_prompt_cubre_todas_las_poses_del_juego() -> None:
    assert set(POSE_IDS) <= set(POSE_KEYS)
    for pose in POSE_KEYS:
        assert pose in POSES_PROMPT


def test_poses_bien() -> None:
    verdict = parse_pose_verdict(GOOD_POSES)
    assert verdict == PoseVerdict(
        3,
        {
            "brazos_arriba": 2,
            "un_brazo": 1,
            "pose_t": 0,
            "manos_cabeza": 0,
            "biceps": 0,
            "barbilla": 0,
        },
    )


@pytest.mark.parametrize(
    "text",
    [
        f"```json\n{GOOD_POSES}\n```",
        f"Aquí tienes el recuento: {GOOD_POSES} Eso es todo.",
        f"```\n{GOOD_POSES}\n```\n",
    ],
)
def test_poses_con_envoltorio(text: str) -> None:
    verdict = parse_pose_verdict(text)
    assert verdict is not None
    assert verdict.people == 3 and verdict.counts["brazos_arriba"] == 2


@pytest.mark.parametrize(
    "text",
    [
        "",
        "no sé",
        '{"personas": 3, "brazos_arriba": ',
        '{"brazos_arriba": 2}',
        '{"personas": "muchas", "brazos_arriba": 2}',
        '{"personas": true}',
        '["personas", 3]',
    ],
)
def test_poses_rotas(text: str) -> None:
    assert parse_pose_verdict(text) is None


def test_poses_desconocidas_negativos_y_tope() -> None:
    verdict = parse_pose_verdict(
        '{"personas": 2, "baile": 1, "brazos_arriba": -1, "un_brazo": 5, "pose_t": "x",'
        ' "biceps": 1.0, "ninguna": 1}'
    )
    assert verdict is not None
    assert verdict.people == 2
    # Sin la desconocida ni ``ninguna``; sin negativos; sin pasar de las personas; la que no
    # es un número se queda fuera (el juego usa entonces su recuento local).
    assert verdict.counts == {"brazos_arriba": 0, "un_brazo": 2, "biceps": 1}
    negative = parse_pose_verdict('{"personas": -3, "brazos_arriba": 1}')
    assert negative == PoseVerdict(0, {"brazos_arriba": 0})


def test_manos_bien_y_con_envoltorio() -> None:
    assert parse_hand_verdict('{"manos": ["tijera", "piedra"]}') == HandVerdict(
        (HandShape.SCISSORS, HandShape.ROCK)
    )
    assert parse_hand_verdict('```json\n{"manos": ["Papel"]}\n```') == HandVerdict(
        (HandShape.PAPER,)
    )
    assert parse_hand_verdict('Veo esto: {"manos": []}.') == HandVerdict(())


def test_manos_desconocidas_se_descartan() -> None:
    assert parse_hand_verdict('{"manos": ["lagarto", "spock", "papel", 3, null]}') == HandVerdict(
        (HandShape.PAPER,)
    )
    assert parse_hand_verdict('{"manos": ["lagarto"]}') == HandVerdict(())


@pytest.mark.parametrize(
    "text", ["", '{"manos": "piedra"}', '{"mano": ["piedra"]}', '{"manos": ["piedra"', "[]"]
)
def test_manos_rotas(text: str) -> None:
    assert parse_hand_verdict(text) is None


# ---------------------------------------------------------------------------
# El juez
# ---------------------------------------------------------------------------


class FakeLLM:
    """Contesta ``reply`` después de ``delay`` segundos (o lanza ``error``); apunta los mensajes."""

    def __init__(self, reply: str = "", *, delay: float = 0.0, error: Exception | None = None):
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
        return Completion(content=self.reply, prompt_tokens=1350)


def frame(width: int = 1280, height: int = 720) -> np.ndarray:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, : width // 2] = (255, 0, 0)
    return image


def sent_image(message: dict[str, Any]) -> np.ndarray:
    """La imagen que viajó en el mensaje del usuario (data URL en JPEG)."""
    url = next(part for part in message["content"] if part["type"] == "image_url")
    data = url["image_url"]["url"].split(",", 1)[1]
    image = cv2.imdecode(np.frombuffer(base64.b64decode(data), np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    return image


async def test_la_foto_va_reducida_a_640_con_su_prompt() -> None:
    llm = FakeLLM(GOOD_POSES)
    referee = GeminiReferee(llm, timeout_s=4.0)
    assert referee.available
    verdict = await referee.poses(frame())
    assert verdict is not None and verdict.counts["brazos_arriba"] == 2
    system_message, user_message = llm.messages[0]
    assert system_message == {"role": "system", "content": POSES_PROMPT}
    assert user_message["content"][0] == {"type": "text", "text": POSES_QUESTION}
    assert sent_image(user_message).shape[:2] == (360, 640)

    llm.reply = '{"manos": ["piedra"]}'
    assert await referee.hands(frame(1920, 1080)) == HandVerdict((HandShape.ROCK,))
    system_message, user_message = llm.messages[1]
    assert system_message["content"] == HANDS_PROMPT
    assert "la persona más cercana" in HANDS_PROMPT
    assert user_message["content"][0]["text"] == HANDS_QUESTION
    assert sent_image(user_message).shape[:2] == (360, 640)
    assert referee.calls == 2


async def test_una_foto_pequena_no_se_agranda() -> None:
    llm = FakeLLM('{"manos": []}')
    await GeminiReferee(llm, timeout_s=4.0).hands(frame(320, 240))
    assert sent_image(llm.messages[0][1]).shape[:2] == (240, 320)


async def test_plazo_agotado_da_none_sin_esperar_de_mas() -> None:
    referee = GeminiReferee(FakeLLM(GOOD_POSES, delay=5.0), timeout_s=0.1)
    loop = asyncio.get_running_loop()
    started = loop.time()
    assert await referee.poses(frame()) is None
    assert await referee.hands(frame()) is None
    assert loop.time() - started < 2.0


async def test_un_fallo_o_un_json_raro_da_none() -> None:
    failing = GeminiReferee(FakeLLM(error=RuntimeError("500")), timeout_s=1.0)
    assert await failing.poses(frame()) is None
    assert await failing.hands(frame()) is None
    odd = GeminiReferee(FakeLLM("No puedo ayudar con eso."), timeout_s=1.0)
    assert await odd.poses(frame()) is None
    assert await odd.hands(frame()) is None


async def test_sin_cliente_no_esta_disponible() -> None:
    referee = GeminiReferee(None, timeout_s=4.0)
    assert not referee.available
    assert await referee.poses(frame()) is None
    assert await referee.hands(frame()) is None


def gemini_settings(*, key: str = "", judge: str = "gemini", source: str = "opencv") -> Settings:
    """Ajustes sin ``.env`` ni variables del equipo: los gestos, sin nada dicho salvo la clave."""
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    settings.vision.source = source  # type: ignore[assignment]
    settings.games.judge = judge  # type: ignore[assignment]
    gestures = settings.gestures
    gestures.base_url = gestures.model = gestures.api_key = gestures.reasoning_effort = ""
    gestures.gemini_api_key = key
    settings.llm.api_key = ""
    settings.llm.base_url = "https://api.openai.com/v1"
    return settings


def test_sin_clave_de_gemini_no_hay_ajustes() -> None:
    assert gemini_llm_settings(gemini_settings(), 8.0) is None
    # Los gestos por otro servidor (aunque haya clave de Gemini): tampoco.
    other = gemini_settings(key="clave-de-prueba")
    other.gestures.base_url = "https://api.openai.com/v1"
    assert gemini_llm_settings(other, 8.0) is None


def test_con_clave_los_ajustes_son_los_del_banco() -> None:
    llm = gemini_llm_settings(gemini_settings(key="clave-de-prueba"), 8.0)
    assert llm is not None
    assert llm.base_url.startswith("https://generativelanguage.googleapis.com/")
    assert llm.model == "gemini-3.1-flash-lite"
    assert llm.reasoning_effort == "minimal"
    assert llm.max_tokens == REFEREE_MAX_TOKENS == 1024
    assert llm.request_timeout == 8.0
    assert llm.key == "clave-de-prueba"


# ---------------------------------------------------------------------------
# El montaje (``build_game_vision``)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _sin_modelos_del_equipo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Nunca los modelos de verdad de ``cache/games/modelos``: una carpeta vacía."""
    monkeypatch.setattr(models_module, "games_models_dir", lambda settings=None: tmp_path)


async def nothing(_: Any) -> None:
    return None


def build(settings: Settings, vision_llm: Any = None) -> Any:
    return build_game_vision(
        settings=settings,
        camera=OpenCVCamera(settings.vision),
        send_json=nothing,
        send_bytes=nothing,
        preview_supported=lambda: True,
        vision_llm=vision_llm,
        download_models=False,
    )


async def test_con_gemini_y_clave_juzga_gemini_y_la_busqueda_tambien(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[LLMClient] = []
    original = LLMClient.aclose

    async def aclose(self: LLMClient) -> None:
        closed.append(self)
        await original(self)

    monkeypatch.setattr(LLMClient, "aclose", aclose)
    luna = object()
    vision = build(gemini_settings(key="clave-de-prueba"), vision_llm=luna)
    assert vision.judge_switch is not None and vision.judge_switch.mode == "gemini"
    assert isinstance(vision.referee, SwitchedReferee)
    referee = vision.referee.current
    assert isinstance(referee, GeminiReferee)
    assert vision.referee.available
    # La búsqueda pregunta primero a Gemini (el mismo cliente que las rondas) y, si falla,
    # al modelo de visión.
    assert isinstance(vision.judge, SwitchedJudge)
    judge = vision.judge.current
    assert isinstance(judge, FallbackJudge)
    client = referee._llm
    assert isinstance(client, LLMClient)
    assert judge._primary._llm is client
    assert judge._secondary._llm is luna
    await vision.close()
    assert closed == [client]
    # Sin modelo de visión, solo Gemini.
    vision = build(gemini_settings(key="clave-de-prueba"))
    assert isinstance(vision.judge, SwitchedJudge) and isinstance(vision.referee, SwitchedReferee)
    judge = vision.judge.current
    assert isinstance(judge, ModelJudge) and judge._llm is vision.referee.current._llm
    await vision.close()


async def test_con_gemini_sin_clave_todo_como_antes() -> None:
    luna = object()
    vision = build(gemini_settings(), vision_llm=luna)
    assert isinstance(vision.referee, NoReferee)
    assert isinstance(vision.judge, ModelJudge) and vision.judge._llm is luna
    # El panel no puede elegir Gemini: el modo es local y el estado lo dice.
    switch = vision.judge_switch
    assert switch is not None
    assert switch.state() == {"mode": "local", "app": "gemini", "requested": None, "gemini": False}
    assert switch.set_mode("gemini") == "local"
    assert switch.state()["requested"] == "gemini" and switch.mode == "local"
    vision = build(gemini_settings())
    assert isinstance(vision.referee, NoReferee)
    assert isinstance(vision.judge, NoJudge)
    await vision.close()


async def test_con_local_no_se_usa_gemini_aunque_haya_clave() -> None:
    luna = object()
    vision = build(gemini_settings(key="clave-de-prueba", judge="local"), vision_llm=luna)
    # Gemini se monta igual, para poder pasar a él desde el panel, pero no juzga.
    switch = vision.judge_switch
    assert switch is not None
    assert switch.state() == {"mode": "local", "app": "local", "requested": None, "gemini": True}
    assert isinstance(vision.referee, SwitchedReferee) and isinstance(vision.judge, SwitchedJudge)
    assert not vision.referee.available
    assert isinstance(vision.referee.current, NoReferee)
    judge = vision.judge.current
    assert isinstance(judge, ModelJudge) and judge._llm is luna
    # Desde el panel, a Gemini y de vuelta al de la app.
    assert switch.set_mode("gemini") == "gemini"
    assert vision.referee.available and isinstance(vision.referee.current, GeminiReferee)
    assert isinstance(vision.judge.current, FallbackJudge)
    assert switch.set_mode(None) == "local"
    assert not vision.referee.available and vision.judge.current is judge
    await vision.close()


async def test_sin_camara_usb_no_hay_juez_de_rondas() -> None:
    vision = build(gemini_settings(key="clave-de-prueba", source="unity"))
    assert not vision.referee.available
    assert not vision.judge.available


# ---------------------------------------------------------------------------
# La búsqueda: Gemini y, si falla, el modelo de visión (``FallbackJudge``)
# ---------------------------------------------------------------------------


class _FakeCamera:
    def __init__(self, *, frames: bool = True) -> None:
        self.frames = frames
        self.captures = 0

    async def capture(self, *, max_width: int | None = None, quality: int | None = None) -> Any:
        from sonia.types import Frame

        self.captures += 1
        return Frame(data=b"\xff\xd8jpeg", width=640, height=360) if self.frames else None


class _FakeVisionLLM:
    def __init__(self, reply: str | None = None, *, error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error
        self.calls = 0

    async def complete(self, messages: Any) -> Any:
        from sonia.llm import Completion

        self.calls += 1
        if self.error is not None:
            raise self.error
        return Completion(content=self.reply or "")


async def test_busqueda_va_a_luna_si_gemini_falla() -> None:
    camera = _FakeCamera()
    gemini = _FakeVisionLLM(error=RuntimeError("429 Too Many Requests"))
    luna = _FakeVisionLLM('{"visto": true, "objeto": "botella azul"}')
    judge = FallbackJudge(ModelJudge(gemini, camera), ModelJudge(luna, camera))
    judge.start_round(3)
    answer = await judge.ask("¿Alguien enseña algo azul?")
    assert answer is not None and answer.seen and answer.what == "botella azul"
    assert (gemini.calls, luna.calls, judge.fallbacks) == (1, 1, 1)
    # El tope cuenta preguntas, no llamadas: queda lo mismo que si hubiera contestado Gemini.
    assert judge.remaining == 2 and judge.calls == 1


async def test_busqueda_no_va_a_luna_si_gemini_contesta_o_no_hay_foto() -> None:
    camera = _FakeCamera()
    gemini = _FakeVisionLLM('{"visto": false, "objeto": ""}')
    luna = _FakeVisionLLM('{"visto": true, "objeto": "taza"}')
    judge = FallbackJudge(ModelJudge(gemini, camera), ModelJudge(luna, camera))
    judge.start_round(1)
    answer = await judge.ask("¿Una taza?")
    assert answer is not None and not answer.seen
    assert luna.calls == 0
    # Tope alcanzado: ni Gemini ni luna.
    assert await judge.ask("¿Una taza?") is None
    assert (gemini.calls, luna.calls) == (1, 0)
    # Sin foto: tampoco se repite.
    blind = FallbackJudge(
        ModelJudge(_FakeVisionLLM(error=RuntimeError("x")), _FakeCamera(frames=False)),
        ModelJudge(luna, _FakeCamera()),
    )
    assert await blind.ask("¿Una taza?") is None
    assert luna.calls == 0


async def test_busqueda_va_a_luna_si_gemini_no_llega_a_tiempo() -> None:
    class _Slow(_FakeVisionLLM):
        async def complete(self, messages: Any) -> Any:
            self.calls += 1
            await asyncio.sleep(1.0)
            return await super().complete(messages)

    camera = _FakeCamera()
    gemini = _Slow('{"visto": true, "objeto": "tarde"}')
    luna = _FakeVisionLLM('{"visto": true, "objeto": "libro"}')
    judge = FallbackJudge(ModelJudge(gemini, camera, timeout_s=0.05), ModelJudge(luna, camera))
    answer = await judge.ask("¿Un libro?")
    assert answer is not None and answer.what == "libro"
    assert judge.fallbacks == 1
