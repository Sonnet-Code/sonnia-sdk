"""Pruebas del director de gestos, sin red ni APIs reales.

El modelo de gestos es un falso que contesta lo que se le diga, tarda lo que
se le diga o falla; Unity es una lista que graba lo que se le manda. Las
pruebas de punta a punta usan el GPT-Live falso de ``test_live``.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from sonia import cli
from sonia.config import GEMINI_OPENAI_URL, GestureSettings, LLMSettings
from sonia.gestures import GestureCatalog, GestureDirector, build_system_prompt, parse_choice
from sonia.gestures.catalog import DEFAULT_CORE_S
from sonia.gestures.prompt import Cooldowns, build_user_message, gesture_line
from sonia.llm.client import Completion, LLMClient, LLMError
from sonia.llm.messages import system, user_text
from sonia.types import Message
from sonia.ws import protocol as p
from sonia.ws.hub import Hub
from tests.test_live import make_rig, pcm

# ---------------------------------------------------------------------------
# Falsos y catálogo
# ---------------------------------------------------------------------------


class FakeGestureLLM:
    """Modelo de gestos falso. Gasta las respuestas en orden y repite la última."""

    def __init__(self, *answers: str | Exception, delay: float = 0.0) -> None:
        self.answers: list[str | Exception] = list(answers) or ['{"gesto": "ninguno"}']
        self.delay = delay
        self.requests: list[list[Message]] = []

    async def complete(self, messages: list[Message]) -> Completion:
        self.requests.append(messages)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if self.delay:
            await asyncio.sleep(self.delay)
        if isinstance(answer, Exception):
            raise answer
        return Completion(
            answer, "stop", prompt_tokens=8000, cached_tokens=7900, completion_tokens=9
        )

    def user(self, index: int = -1) -> str:
        return str(self.requests[index][1]["content"])


class Sent:
    """Lo que el director manda a Unity."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def __call__(self, msg: dict[str, Any]) -> None:
        self.messages.append(msg)

    def gestures(self) -> list[dict[str, Any]]:
        return [m for m in self.messages if m["type"] == "gesture"]


def gesture(name: str, **fields: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "name": name,
        "lists": ["Sage(IDset)"],
        "duration": 1.0,
        "core_start": 0.05,
        "core_stop": 0.2,
        "critical_beat": None,
        "held": False,
        "min_duration": None,
        "frequency": "Standard",
        "timing": "Short",
        "impact": "LowImpact",
        "intensity": 2,
        "special": False,
        "description": f"Gesto {name}.",
        "intents": ["To Convey"],
        "intent_description": "",
        "tags": [],
    }
    item.update(fields)
    return item


FILLERS = {"noImpact01", "noImpact02", "listeningNod"}

CATALOG: dict[str, Any] = {
    "type": "gesture_catalog",
    "character": "Sage",
    "transition_s": 0.8,
    "gestures": [
        gesture("wave", intents=["To Greet"]),
        gesture("explain"),
        gesture("pointOut"),
        gesture("shrug", frequency="Uncommon"),
        gesture("palmsUp", frequency="Uncommon"),
        gesture("bigCheer", frequency="Rare", impact="HighImpact"),
        gesture("bigWow", frequency="Rare", impact="HighImpact"),
        gesture("longTalk", timing="Long", duration=3.0, core_stop=1.5),
        gesture(
            "handOnChest",
            frequency="Uncommon",
            intensity=1,
            description="Hand over chest, solemn (sincerity/pledge).",
            intents=["To Comfort", "To Appreciate"],
            intent_description="USE: Used to show appreciation\nDO NOT USE: Not sarcastically",
            tags=["descriptor:Gesture", "personality:Earnest", "intent:To Comfort"],
        ),
        gesture("noImpact01", lists=["Utility_NoImpact"], impact="NoImpact", special=True),
        gesture("noImpact02", lists=["Utility_NoImpact"], impact="NoImpact", special=True),
        gesture("listeningNod", lists=["Utility_NoImpact"], frequency="Uncommon", timing="Long"),
    ],
}

#: Una frase con texto de sobra para pedir su gesto enseguida.
TEXT = "Sonnet Code hace software a medida con inteligencia artificial"


def fast(**overrides: Any) -> GestureSettings:
    """Tiempos cortos para que las pruebas vayan rápido."""
    values: dict[str, Any] = {
        "enabled": True,
        "timeout_s": 0.5,
        "trigger_chars": 20,
        "trigger_s": 0.05,
        "min_gap_s": 0.0,
        "max_delay_s": 0.8,
        "repeat_s": 90.0,
        "uncommon_s": 45.0,
        "rare_s": 300.0,
        "fallback": True,
        "gemini_api_key": "",
    }
    values.update(overrides)
    return GestureSettings(**values)


def make_director(
    llm: FakeGestureLLM, settings: GestureSettings | None = None, **kwargs: Any
) -> tuple[GestureDirector, Sent]:
    sent = Sent()
    director = GestureDirector(settings or fast(), llm, sent, rng=random.Random(3), **kwargs)
    director.on_catalog(CATALOG)
    director.on_session(True)
    return director, sent


async def wait_until(predicate: Callable[[], bool], limit: float = 2.0) -> None:
    async with asyncio.timeout(limit):
        while not predicate():  # noqa: ASYNC110 - sondeo de un predicado
            await asyncio.sleep(0.01)


def decided(director: GestureDirector) -> int:
    snap = director.snapshot()
    return int(snap["gestures"] + snap["none"] + snap["late"])


async def say(director: GestureDirector, uid: int, text: str = TEXT) -> None:
    """Una frase entera: empieza, espera a la decisión de su gesto y termina."""
    before = decided(director)
    director.on_speech_start(uid, ambient=False, text=text)
    await wait_until(lambda: decided(director) > before)
    director.on_speech_end(uid, text)


# ---------------------------------------------------------------------------
# Protocolo y catálogo
# ---------------------------------------------------------------------------


def test_msg_gesture_lleva_la_frase_o_null() -> None:
    assert p.msg_gesture("noBigDeal", 12) == {
        "type": "gesture",
        "name": "noBigDeal",
        "utterance_id": 12,
    }
    assert p.msg_gesture("noBigDeal", None) == {
        "type": "gesture",
        "name": "noBigDeal",
        "utterance_id": None,
    }
    assert json.loads(p.dumps(p.msg_gesture("x", None)))["utterance_id"] is None


def test_el_catalogo_de_gestos_es_tolerante_con_lo_que_falte() -> None:
    msg = {
        "type": "gesture_catalog",
        "character": "Sage",
        "transition_s": "0.8",
        "gestures": [
            gesture("noBigDeal", core_stop=2.1, intents=["To Dismiss"]),
            {"name": "  minimo  ", "intensity": 0},
            {
                "name": "texto",
                "duration": "2.5",
                "core_stop": "1.2",
                "intensity": "3",
                "frequency": "rare",
                "timing": "LONG",
                "impact": "loquesea",
                "critical_beat": "nan",
                "lists": "no es una lista",
                "held": "true",
            },
            {"name": "noBigDeal"},  # repetido
            {"name": ""},
            {"duration": 2},
            "no es un objeto",
        ],
    }
    parsed = p.parse_gesture_catalog(msg)
    assert parsed["character"] == "Sage" and parsed["transition_s"] == 0.8
    assert [g["name"] for g in parsed["gestures"]] == ["noBigDeal", "minimo", "texto"]
    full, minimal, text = parsed["gestures"]
    assert full["core_stop"] == 2.1 and full["intents"] == ["To Dismiss"]
    assert minimal["frequency"] == "Standard"  # sin frecuencia cuenta como normal
    assert minimal["timing"] == minimal["impact"] == minimal["description"] == ""
    assert minimal["duration"] == minimal["core_stop"] == 0.0
    assert minimal["intensity"] is None and minimal["critical_beat"] is None
    assert text["duration"] == 2.5 and text["core_stop"] == 1.2 and text["intensity"] == 3
    assert text["frequency"] == "Rare" and text["timing"] == "Long" and text["impact"] == ""
    assert text["critical_beat"] is None and text["lists"] == [] and text["held"] is False
    assert p.parse_gesture_catalog({"type": "gesture_catalog"}) == {
        "character": "",
        "transition_s": None,
        "gestures": [],
    }


def test_catalogo_relleno_nucleo_y_nombres_sin_mayusculas() -> None:
    catalog = GestureCatalog.from_message(CATALOG)
    assert len(catalog) == len(CATALOG["gestures"]) and catalog.character == "Sage"
    assert {g.name for g in catalog.fillers()} == FILLERS
    longest = catalog.get("longTalk")
    assert longest is not None and longest.core_s == 1.5
    minimal = GestureCatalog.from_message({"gestures": [{"name": "solo"}]}).get("solo")
    assert minimal is not None and minimal.core_s == DEFAULT_CORE_S
    found = catalog.resolve(" WAVE ")
    assert found is not None and found.name == "wave"
    assert catalog.resolve("moonwalk") is None


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


def test_el_prompt_fijo_lleva_una_linea_compacta_por_gesto() -> None:
    catalog = GestureCatalog.from_message(CATALOG)
    prompt = build_system_prompt(catalog)
    assert prompt == build_system_prompt(catalog)  # idéntico: caché de prompts
    assert "Sonnia" in prompt and "DevFest Santo Domingo 2026" in prompt
    assert '{"gesto": "ninguno"}' in prompt and "Gestos de Sage" in prompt
    assert prompt.split("Gestos de Sage", 1)[1].count("\n- ") == len(catalog)
    hand = catalog.get("handOnChest")
    assert hand is not None
    assert gesture_line(hand) == (
        "- handOnChest · Uncommon, Short, LowImpact, intensidad 1 · "
        "Hand over chest, solemn (sincerity/pledge) · intención: Comfort, Appreciate · "
        "estilo: Earnest · USE: Used to show appreciation DO NOT USE: Not sarcastically"
    )
    filler = catalog.get("noImpact01")
    assert filler is not None and "relleno" in gesture_line(filler)


def test_el_mensaje_de_usuario_cuenta_el_momento_y_lo_vetado() -> None:
    opening = build_user_message(opening=True, user_text="¡Hola, Sonnia!", said=[])
    assert opening.startswith("Apertura") and "«¡Hola, Sonnia!»" in opening
    assert "Frase actual" not in opening and "Gestos recientes: ninguno." in opening

    phrase = build_user_message(
        opening=False,
        user_text="¿Qué es Sonnet Code?",
        said=["¡Claro que sí!"],
        phrase_text="",
        phrase_index=2,
        phrase_age_s=0.5,
        recent=[("explain", 12.0), ("wave", 130.0)],
        cooldowns=Cooldowns(rare_left_s=200.0, uncommon_left_s=0.0, repeated=("explain",)),
    )
    assert "Frase 2" in phrase and "0.5 s" in phrase
    assert "Sonnia ya ha dicho: «¡Claro que sí!»" in phrase
    assert "aún sin texto" in phrase
    assert "explain hace 12 s, wave hace 2 min" in phrase
    assert "los Rare (hasta dentro de 3 min)" in phrase and "Uncommon" not in phrase
    assert "explain (usados hace poco)" in phrase


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"gesto": "wave"}', ("wave", True)),
        ('```json\n{"gesto": "Wave"}\n```', ("wave", True)),
        ('{"gesto": "ninguno"}', (None, True)),
        ('{"gesto": null}', (None, True)),
        ("ninguno", (None, True)),
        ("", (None, True)),
        ("wave", ("wave", True)),
        ('{"gesto": "moonwalk"}', (None, False)),
        ("El mejor gesto aquí es wave", (None, False)),
        ('{"gesto": 3}', (None, False)),
    ],
)
def test_la_respuesta_del_modelo_se_entiende_o_cuenta_como_ninguno(
    raw: str, expected: tuple[str | None, bool]
) -> None:
    assert parse_choice(raw, GestureCatalog.from_message(CATALOG)) == expected


# ---------------------------------------------------------------------------
# Director
# ---------------------------------------------------------------------------


async def test_sin_catalogo_no_pide_nada() -> None:
    llm = FakeGestureLLM('{"gesto": "wave"}')
    sent = Sent()
    director = GestureDirector(fast(), llm, sent)
    director.on_session(True)
    director.on_user_turn("¡Hola!")
    director.on_speech_start(1, ambient=False, text=TEXT)
    await asyncio.sleep(0.15)
    director.on_catalog({"type": "gesture_catalog", "gestures": []})
    director.on_speech_start(2, ambient=False, text=TEXT)
    await asyncio.sleep(0.15)
    assert llm.requests == [] and sent.messages == []


async def test_apertura_con_utterance_id_null_que_cubre_la_primera_frase() -> None:
    llm = FakeGestureLLM('{"gesto": "wave"}')
    director, sent = make_director(llm)
    director.on_user_turn("¡Hola, Sonnia!")
    await wait_until(lambda: bool(sent.gestures()))
    assert sent.gestures() == [{"type": "gesture", "name": "wave", "utterance_id": None}]
    system_message, user_message = llm.requests[0]
    assert system_message["role"] == "system" and "- wave ·" in system_message["content"]
    assert user_message["role"] == "user" and "Apertura" in user_message["content"]
    assert "¡Hola, Sonnia!" in user_message["content"]
    # Unity lo lanza con la siguiente frase, que ya no pide otro.
    director.on_speech_start(1, ambient=False, text=TEXT)
    await asyncio.sleep(0.15)
    assert len(llm.requests) == 1 and director.snapshot()["last"] == "wave"


async def test_cada_frase_pide_su_gesto_en_cuanto_tiene_texto() -> None:
    llm = FakeGestureLLM('{"gesto": "explain"}')
    director, sent = make_director(llm, fast(trigger_s=5.0))
    director.on_speech_start(7, ambient=False, text="Sonnet")
    await asyncio.sleep(0.05)
    assert llm.requests == []  # ni 20 caracteres ni el tiempo
    director.on_assistant_text(7, TEXT)
    await wait_until(lambda: bool(sent.gestures()))
    assert sent.gestures() == [{"type": "gesture", "name": "explain", "utterance_id": 7}]
    assert "Frase 1" in llm.user() and TEXT in llm.user()
    snap = director.snapshot()
    assert snap["requests"] == 1 and snap["gestures"] == 1 and snap["avg_latency_s"] is not None


async def test_sin_texto_lo_pide_al_pasar_el_tiempo() -> None:
    llm = FakeGestureLLM('{"gesto": "explain"}')
    director, sent = make_director(llm)
    director.on_speech_start(3, ambient=False)
    await wait_until(lambda: bool(sent.gestures()))
    assert "aún sin texto" in llm.user()


async def test_las_frases_ambientales_no_llevan_gesto() -> None:
    llm = FakeGestureLLM('{"gesto": "wave"}')
    director, sent = make_director(llm)
    director.on_speech_start(2, ambient=True, text="¡Ven a conocer Sonnet Code, te espero aquí!")
    await asyncio.sleep(0.15)
    assert llm.requests == [] and sent.messages == []


async def test_ninguno_es_normal_y_no_pone_relleno() -> None:
    llm = FakeGestureLLM('{"gesto": "ninguno"}')
    director, sent = make_director(llm)
    await say(director, 1)
    snap = director.snapshot()
    assert sent.messages == [] and snap["none"] == 1 and snap["fallbacks"] == 0


async def test_un_nombre_inventado_cuenta_como_ninguno() -> None:
    llm = FakeGestureLLM('{"gesto": "moonwalk"}')
    director, sent = make_director(llm)
    await say(director, 1)
    snap = director.snapshot()
    assert sent.messages == [] and snap["unknown"] == 1 and snap["fallbacks"] == 0


async def test_si_el_modelo_falla_va_un_gesto_de_relleno() -> None:
    llm = FakeGestureLLM(LLMError("El servidor del modelo devolvió 503"))
    director, sent = make_director(llm)
    director.on_speech_start(1, ambient=False, text=TEXT)
    await wait_until(lambda: bool(sent.gestures()))
    [msg] = sent.gestures()
    assert msg["name"] in FILLERS and msg["utterance_id"] == 1
    snap = director.snapshot()
    assert snap["failures"] == 1 and snap["fallbacks"] == 1 and snap["gestures"] == 1


async def test_si_el_modelo_tarda_el_relleno_llega_dentro_del_plazo_de_la_frase() -> None:
    llm = FakeGestureLLM('{"gesto": "explain"}', delay=5.0)
    director, sent = make_director(llm, fast(max_delay_s=0.5, timeout_s=3.0))
    started = time.monotonic()
    director.on_speech_start(1, ambient=False, text=TEXT)
    await wait_until(lambda: bool(sent.gestures()))
    assert time.monotonic() - started < 0.5
    assert sent.gestures()[0]["name"] in FILLERS


async def test_sin_relleno_un_fallo_deja_la_frase_sin_gesto() -> None:
    llm = FakeGestureLLM(LLMError("caído"))
    director, sent = make_director(llm, fast(fallback=False))
    director.on_speech_start(1, ambient=False, text=TEXT)
    await wait_until(lambda: director.snapshot()["failures"] == 1)
    await asyncio.sleep(0.05)
    assert sent.messages == []


async def test_el_relleno_no_repite_el_ultimo() -> None:
    llm = FakeGestureLLM(LLMError("caído"))
    director, sent = make_director(llm)
    for uid in (1, 2, 3, 4):
        await say(director, uid)
    names = [m["name"] for m in sent.gestures()]
    assert len(names) == 4 and set(names) <= FILLERS
    assert all(a != b for a, b in zip(names, names[1:], strict=False))


async def test_lo_que_llega_tras_acabar_su_frase_se_tira() -> None:
    llm = FakeGestureLLM('{"gesto": "explain"}', delay=0.3)
    director, sent = make_director(llm, fast(max_delay_s=2.0, timeout_s=2.0))
    director.on_speech_start(1, ambient=False, text=TEXT)
    await wait_until(lambda: bool(llm.requests))
    director.on_speech_end(1, TEXT)
    await asyncio.sleep(0.4)
    assert sent.messages == [] and director.snapshot()["late"] == 1


async def test_un_gesto_no_empieza_hasta_que_acaba_el_nucleo_del_anterior() -> None:
    # explain tiene el núcleo hasta 0,2 s; con 0,1 s de margen, el siguiente no antes de 0,3 s.
    llm = FakeGestureLLM('{"gesto": "explain"}', '{"gesto": "pointOut"}')
    director, sent = make_director(llm, fast(min_gap_s=0.1, max_delay_s=1.5))
    director.on_speech_start(1, ambient=False, text=TEXT)
    await wait_until(lambda: len(sent.gestures()) == 1)
    first = time.monotonic()
    director.on_speech_end(1, TEXT)
    director.on_speech_start(2, ambient=False, text=TEXT)
    await wait_until(lambda: len(sent.gestures()) == 2)
    assert time.monotonic() - first >= 0.28
    assert [m["utterance_id"] for m in sent.gestures()] == [1, 2]


async def test_si_el_anterior_sigue_en_su_nucleo_la_frase_no_pide_gesto() -> None:
    # longTalk ocupa 1,5 s: a la frase siguiente (plazo de 0,8 s) ya no le da tiempo.
    llm = FakeGestureLLM('{"gesto": "longTalk"}', '{"gesto": "explain"}')
    director, sent = make_director(llm)
    await say(director, 1)
    director.on_speech_start(2, ambient=False, text=TEXT)
    await asyncio.sleep(0.2)
    assert len(llm.requests) == 1 and [m["name"] for m in sent.gestures()] == ["longTalk"]


async def test_el_mismo_gesto_no_se_repite() -> None:
    llm = FakeGestureLLM('{"gesto": "explain"}')
    director, sent = make_director(llm)
    await say(director, 1)
    await say(director, 2)
    assert [m["name"] for m in sent.gestures()] == ["explain"]
    assert director.snapshot()["vetoed"] == 1
    # También se le dice al modelo, sin tocar la parte fija del prompt (caché).
    assert "explain (usados hace poco)" in llm.user(1)
    assert llm.requests[0][0] == llm.requests[1][0]
    assert llm.user(0) != llm.user(1)


async def test_rare_y_uncommon_se_dosifican() -> None:
    llm = FakeGestureLLM(
        '{"gesto": "bigCheer"}',
        '{"gesto": "bigWow"}',
        '{"gesto": "shrug"}',
        '{"gesto": "palmsUp"}',
        '{"gesto": "explain"}',
    )
    director, sent = make_director(llm)
    for uid in range(1, 6):
        await say(director, uid)
    assert [m["name"] for m in sent.gestures()] == ["bigCheer", "shrug", "explain"]
    assert director.snapshot()["vetoed"] == 2
    assert "los Rare" in llm.user(1)
    assert "los Uncommon" in llm.user(3)


async def test_una_interrupcion_cancela_lo_pendiente() -> None:
    llm = FakeGestureLLM('{"gesto": "explain"}', delay=0.3)
    director, sent = make_director(llm, fast(max_delay_s=2.0, timeout_s=2.0))
    director.on_speech_start(1, ambient=False, text=TEXT)
    await wait_until(lambda: bool(llm.requests))
    director.on_interrupt()
    await asyncio.sleep(0.4)
    assert sent.messages == []


async def test_con_la_sesion_cerrada_no_pide_y_cerrarla_cancela() -> None:
    llm = FakeGestureLLM('{"gesto": "wave"}', delay=0.3)
    director, sent = make_director(llm, fast(timeout_s=2.0))
    director.on_user_turn("¡Hola!")
    await wait_until(lambda: bool(llm.requests))
    director.on_session(False)
    director.on_user_turn("¿Sigues ahí?")
    director.on_speech_start(1, ambient=False, text=TEXT)
    await asyncio.sleep(0.4)
    assert len(llm.requests) == 1 and sent.messages == []


async def test_sin_unity_conectado_no_gasta() -> None:
    llm = FakeGestureLLM('{"gesto": "wave"}')
    director, sent = make_director(llm, has_clients=lambda: False)
    director.on_user_turn("¡Hola!")
    director.on_speech_start(1, ambient=False, text=TEXT)
    await asyncio.sleep(0.15)
    assert llm.requests == [] and sent.messages == []


async def test_apagado_no_pide_nada() -> None:
    llm = FakeGestureLLM('{"gesto": "wave"}')
    director, sent = make_director(llm, fast(enabled=False))
    director.on_user_turn("¡Hola!")
    director.on_speech_start(1, ambient=False, text=TEXT)
    await asyncio.sleep(0.15)
    assert llm.requests == [] and not director.snapshot()["enabled"]


async def test_una_sola_peticion_en_vuelo_y_la_apertura_sirve_a_la_frase_ya_empezada() -> None:
    llm = FakeGestureLLM('{"gesto": "wave"}', delay=0.2)
    director, sent = make_director(llm, fast(max_delay_s=2.0, timeout_s=2.0))
    director.on_user_turn("¡Hola, Sonnia!")
    await wait_until(lambda: bool(llm.requests))
    director.on_speech_start(1, ambient=False, text=TEXT)
    await wait_until(lambda: bool(sent.gestures()))
    assert sent.gestures() == [{"type": "gesture", "name": "wave", "utterance_id": 1}]
    await asyncio.sleep(0.1)
    assert len(llm.requests) == 1


async def test_la_apertura_que_llega_con_la_primera_frase_ya_acabada_se_tira() -> None:
    llm = FakeGestureLLM('{"gesto": "wave"}', delay=0.3)
    director, sent = make_director(llm, fast(max_delay_s=2.0, timeout_s=2.0))
    director.on_user_turn("¡Hola, Sonnia!")
    await wait_until(lambda: bool(llm.requests))
    director.on_speech_start(1, ambient=False, text="¡Hola!")
    director.on_speech_end(1, "¡Hola!")
    await asyncio.sleep(0.4)
    # Mandarla con null la colaría en la frase siguiente, que ya es otra cosa.
    assert sent.messages == [] and director.snapshot()["late"] == 1


async def test_una_apertura_mandada_sigue_valiendo_si_el_visitante_sigue_hablando() -> None:
    llm = FakeGestureLLM('{"gesto": "wave"}', '{"gesto": "ninguno"}')
    director, sent = make_director(llm)
    director.on_user_turn("¡Hola!")
    await wait_until(lambda: bool(sent.gestures()))
    director.on_user_turn("¡Hola! Quería preguntarte una cosa")
    await wait_until(lambda: director.snapshot()["none"] == 1)
    # Unity sigue guardando «wave» y lo lanza con la primera frase.
    director.on_speech_start(1, ambient=False, text=TEXT)
    await asyncio.sleep(0.15)
    assert len(llm.requests) == 2 and director.snapshot()["last"] == "wave"


async def test_si_sonia_ya_contesta_no_hay_apertura() -> None:
    llm = FakeGestureLLM('{"gesto": "explain"}')
    director, sent = make_director(llm, fast(trigger_s=5.0))
    # Sonia empieza a contestar con el turno del visitante aún abierto.
    director.on_speech_start(1, ambient=False, text="Claro", user_text="¿Qué es Sonnet")
    director.on_user_turn("¿Qué es Sonnet Code?", answering=True)
    await asyncio.sleep(0.05)
    assert llm.requests == []
    director.on_assistant_text(1, TEXT)
    await wait_until(lambda: bool(sent.gestures()))
    assert "Frase 1" in llm.user() and "¿Qué es Sonnet Code?" in llm.user()


# ---------------------------------------------------------------------------
# Motor de punta a punta (GPT-Live falso y Unity por WebSocket)
# ---------------------------------------------------------------------------


def director_for(llm: FakeGestureLLM) -> Callable[[Hub], GestureDirector]:
    def build(hub: Hub) -> GestureDirector:
        return GestureDirector(
            fast(), llm, hub.broadcast_json, has_clients=lambda: hub.client_count > 0
        )

    return build


async def test_el_motor_manda_a_unity_el_gesto_de_cada_frase(tmp_path: Path) -> None:
    llm = FakeGestureLLM('{"gesto": "explain"}')
    async with make_rig(tmp_path, gestures=director_for(llm)) as rig:
        conn = await rig.conn()
        await rig.unity(CATALOG)
        snapshot = rig.engine.snapshot
        await wait_until(lambda: snapshot()["gestures"]["catalog"] == len(CATALOG["gestures"]))
        await conn.say("Sonnet Code hace software a medida, ")
        for _ in range(3):
            await conn.audio(pcm(2_400))
        await rig.rec.wait_type("gesture")
        assert rig.rec.of_type("gesture") == [
            {"type": "gesture", "name": "explain", "utterance_id": 1}
        ]
        assert rig.rec.of_type("speech_start")[0]["utterance_id"] == 1
        assert "Sonnet Code hace software a medida" in llm.user()
        assert snapshot()["gestures"]["gestures"] == 1


async def test_un_texto_escrito_pide_el_gesto_de_apertura(tmp_path: Path) -> None:
    llm = FakeGestureLLM('{"gesto": "wave"}')
    async with make_rig(tmp_path, gestures=director_for(llm)) as rig:
        await rig.conn()
        await rig.unity(CATALOG)
        await wait_until(lambda: rig.engine.snapshot()["gestures"]["catalog"] > 0)
        await rig.unity({"type": "text_input", "text": "¡Hola, Sonnia!"})
        await rig.rec.wait_type("gesture")
        assert rig.rec.of_type("gesture") == [
            {"type": "gesture", "name": "wave", "utterance_id": None}
        ]
        assert "Apertura" in llm.user() and "¡Hola, Sonnia!" in llm.user()


async def test_sin_director_el_catalogo_se_ignora(tmp_path: Path) -> None:
    async with make_rig(tmp_path) as rig:
        conn = await rig.conn()
        await rig.unity(CATALOG)
        await conn.audio(pcm(2_400))
        await rig.rec.wait_type("speech_end")
        assert rig.rec.of_type("gesture") == []
        assert rig.engine.snapshot()["gestures"] is None


# ---------------------------------------------------------------------------
# Cliente del modelo y configuración
# ---------------------------------------------------------------------------


OPENAI = LLMSettings(
    base_url="https://api.openai.com/v1",
    model="gpt-6-luna",
    api_key="",
    openai_api_key="clave-openai",
    reasoning_effort="low",
    extra_body={"service_tier": "default"},
)


def test_los_gestos_heredan_el_modelo_de_vision() -> None:
    settings = fast(timeout_s=3.0).llm_settings(OPENAI)
    assert settings.model == "gpt-6-luna" and settings.key == "clave-openai"
    # El razonamiento más bajo que acepta OpenAI: lo más rápido.
    assert settings.reasoning_effort == "none"
    assert settings.max_tokens == 64 and settings.request_timeout == 3.0
    assert settings.extra_body == {"service_tier": "default"}
    # Otro servidor: ni la clave de OpenAI ni lo propio del de visión.
    kimi = fast(base_url="https://api.moonshot.ai/v1", model="kimi-k2.6").llm_settings(OPENAI)
    assert kimi.key == "" and kimi.reasoning_effort == "off" and kimi.extra_body == {}
    assert fast(base_url="https://api.moonshot.ai/v1", api_key="k").llm_settings(OPENAI).key == "k"
    # El mismo servidor que la visión (no OpenAI): hereda su clave y su ajuste.
    local = LLMSettings(
        base_url="https://api.moonshot.ai/v1",
        api_key="clave-kimi",
        reasoning_effort="off",
        extra_body={"thinking": {"type": "disabled"}},
    )
    same = fast().llm_settings(local)
    assert same.key == "clave-kimi" and same.reasoning_effort == "off"
    assert same.extra_body == {"thinking": {"type": "disabled"}}
    # Lo que se ponga a mano manda.
    assert fast(reasoning_effort="low").llm_settings(OPENAI).reasoning_effort == "low"
    assert fast(model="otro").llm_settings(OPENAI).model == "otro"


def test_los_gestos_pueden_ir_por_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "clave-gemini")
    monkeypatch.setenv("GESTURE_BASE_URL", GEMINI_OPENAI_URL)
    monkeypatch.setenv("GESTURE_MODEL", "gemini-3.1-flash-lite")
    settings = GestureSettings().llm_settings(OPENAI)
    # Sin GESTURE_API_KEY, la de Gemini; nunca la de OpenAI.
    assert settings.key == "clave-gemini" and settings.model == "gemini-3.1-flash-lite"
    assert settings.max_tokens_param == "max_tokens"
    # Gemini 3 no deja apagar el razonamiento: lo más bajo, con sitio en el tope.
    assert settings.reasoning_effort == "minimal" and settings.max_tokens == 512
    assert settings.extra_body == {}
    # GESTURE_API_KEY manda sobre GEMINI_API_KEY.
    monkeypatch.setenv("GESTURE_API_KEY", "otra")
    assert GestureSettings().llm_settings(OPENAI).key == "otra"
    # Con OpenAI no se usa la de Gemini ni cambia el parámetro de tokens.
    for name in ("GESTURE_API_KEY", "GESTURE_BASE_URL", "GESTURE_MODEL"):
        monkeypatch.delenv(name)
    # Solo con la clave de Gemini, los gestos van por Gemini (luna es lenta para esto).
    default = fast(gemini_api_key="clave-gemini").llm_settings(OPENAI)
    assert default.base_url == GEMINI_OPENAI_URL and default.model == "gemini-3.1-flash-lite"
    assert default.key == "clave-gemini" and default.reasoning_effort == "minimal"
    # Con un modelo de OpenAI puesto a mano no se usa la de Gemini ni cambia el parámetro.
    openai = fast(gemini_api_key="clave-gemini", model="gpt-4.1-mini").llm_settings(OPENAI)
    assert openai.base_url == OPENAI.base_url and openai.key == "clave-openai"
    assert openai.max_tokens_param == OPENAI.max_tokens_param
    # Sin clave de Gemini, el modelo de visión, como siempre.
    assert fast(gemini_api_key="").llm_settings(OPENAI).model == "gpt-6-luna"
    # URL de Gemini sin modelo: el ligero de Gemini, no el de visión.
    assert fast(base_url=GEMINI_OPENAI_URL, gemini_api_key="k").llm_settings(OPENAI).model == (
        "gemini-3.1-flash-lite"
    )


def test_las_variables_de_los_gestos_se_leen_del_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GESTURES_ENABLED", "false")
    monkeypatch.setenv("GESTURE_MODEL", "gpt-6-luna-mini")
    monkeypatch.setenv("GESTURE_MAX_DELAY_S", "2")
    settings = GestureSettings()
    assert settings.enabled is False and settings.model == "gpt-6-luna-mini"
    assert settings.max_delay_s == 2.0


async def test_complete_pide_sin_streaming_y_lee_el_uso_de_tokens() -> None:
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "gpt-6-luna",
                "choices": [{"message": {"content": '{"gesto": "wave"}'}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 8123,
                    "completion_tokens": 9,
                    "prompt_tokens_details": {"cached_tokens": 7936},
                },
            },
        )

    settings = fast().llm_settings(OPENAI)
    async with LLMClient(settings, transport=httpx.MockTransport(handler)) as client:
        completion = await client.complete([system("fijo"), user_text("frase")])
    assert completion == Completion('{"gesto": "wave"}', "stop", 8123, 7936, 9)
    [body] = captured
    assert body["stream"] is False and body["model"] == "gpt-6-luna"
    assert body["reasoning_effort"] == "none" and body["max_completion_tokens"] == 64
    assert body["messages"][0] == {"role": "system", "content": "fijo"}


async def test_complete_no_reintenta_y_lanza_llmerror() -> None:
    calls = 0

    def failing(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, text="ocupado")

    settings = fast().llm_settings(OPENAI)
    async with LLMClient(settings, transport=httpx.MockTransport(failing)) as client:
        with pytest.raises(LLMError, match="503"):
            await client.complete([user_text("frase")])
    assert calls == 1

    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin red", request=request)

    async with LLMClient(settings, transport=httpx.MockTransport(broken)) as client:
        with pytest.raises(LLMError, match="red"):
            await client.complete([user_text("frase")])


async def test_build_components_monta_el_director_si_hay_clave(tmp_path: Path) -> None:
    from tests.test_cli import make_settings

    components = cli.build_components(make_settings(tmp_path))
    try:
        assert components.gestures is not None and components.gesture_llm is not None
        assert components.gestures.enabled
    finally:
        await components.close()
    for components in (
        cli.build_components(make_settings(tmp_path, gestures=GestureSettings(enabled=False))),
        cli.build_components(make_settings(tmp_path), with_gestures=False),
        cli.build_components(
            make_settings(tmp_path, llm=LLMSettings(base_url="http://llm.test/v1", api_key=""))
        ),
    ):
        try:
            assert components.gestures is None and components.gesture_llm is None
        finally:
            await components.close()


# ---------------------------------------------------------------------------
# Gemini por su endpoint compatible con OpenAI
# ---------------------------------------------------------------------------


def gemini(model: str = "gemini-3.1-flash-lite", **fields: Any) -> GestureSettings:
    return fast(base_url=GEMINI_OPENAI_URL, model=model, gemini_api_key="clave-gemini", **fields)


def test_con_gemini_3_razona_lo_minimo_y_el_tope_deja_sitio() -> None:
    settings = gemini().llm_settings(OPENAI)
    assert settings.key == "clave-gemini" and settings.model == "gemini-3.1-flash-lite"
    # Gemini 3 no deja apagar el razonamiento: «minimal» es lo más bajo, y lo
    # que razona cuenta en el tope.
    assert settings.reasoning_effort == "minimal" and settings.max_tokens == 512
    assert settings.max_tokens_param == "max_tokens"
    # Lo propio de OpenAI no viaja a Google.
    assert settings.extra_body == {} and settings.temperature is None
    # Los 2.5 sí se pueden apagar.
    old = gemini("gemini-2.5-flash-lite").llm_settings(OPENAI)
    assert old.reasoning_effort == "none" and old.max_tokens == 64
    # Lo que se ponga a mano manda.
    custom = gemini(
        reasoning_effort="off",
        max_tokens=300,
        max_tokens_param="max_completion_tokens",
        extra_body={"extra_body": {"google": {"thinking_config": {"thinking_level": "low"}}}},
    ).llm_settings(OPENAI)
    assert custom.reasoning_effort == "off" and custom.max_tokens == 300
    assert custom.max_tokens_param == "max_completion_tokens"
    assert custom.extra_body["extra_body"]["google"]["thinking_config"]["thinking_level"] == "low"


def test_la_clave_de_openai_nunca_va_a_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    settings = fast(base_url=GEMINI_OPENAI_URL, model="gemini-3.1-flash-lite")
    assert settings.llm_settings(OPENAI).key == ""


async def test_complete_contra_gemini_manda_lo_que_entiende() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"gesto": "wave"}'}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 8400,
                    "completion_tokens": 30,
                    "completion_tokens_details": {"reasoning_tokens": 21},
                },
            },
        )

    settings = gemini().llm_settings(OPENAI)
    async with LLMClient(settings, transport=httpx.MockTransport(handler)) as client:
        completion = await client.complete([system("fijo"), user_text("frase")])
    assert completion.content == '{"gesto": "wave"}' and completion.reasoning_tokens == 21
    [request] = seen
    assert str(request.url) == (
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    )
    assert request.headers["authorization"] == "Bearer clave-gemini"
    assert request.headers["accept"] == "application/json"
    body = json.loads(request.content)
    assert set(body) == {"model", "messages", "stream", "max_tokens", "reasoning_effort"}
    assert body["model"] == "gemini-3.1-flash-lite" and body["stream"] is False
    assert body["max_tokens"] == 512 and body["reasoning_effort"] == "minimal"


async def test_si_razona_hasta_agotar_el_tope_es_un_fallo_con_relleno() -> None:
    class Thinker(FakeGestureLLM):
        async def complete(self, messages: list[Message]) -> Completion:
            self.requests.append(messages)
            return Completion("", "length", prompt_tokens=8000, completion_tokens=512)

    llm = Thinker()
    director, sent = make_director(llm)
    director.on_speech_start(1, ambient=False, text=TEXT)
    await wait_until(lambda: bool(sent.gestures()))
    assert sent.gestures()[0]["name"] in FILLERS
    snap = director.snapshot()
    assert snap["failures"] == 1 and snap["fallbacks"] == 1 and snap["none"] == 0


# ---------------------------------------------------------------------------
# Gestos que pide el visitante («tócate un ojo»)
# ---------------------------------------------------------------------------


async def test_un_gesto_pedido_lo_elige_el_modelo_aunque_sea_rare() -> None:
    llm = FakeGestureLLM('{"gesto": "bigCheer"}')
    director, sent = make_director(llm)
    director.note_requested("bigWow")  # un Rare reciente no impide pedir otro
    choice = await director.choose_requested("celebrar a lo grande")
    assert choice.name == "bigCheer" and not choice.error
    # Mismo mensaje de sistema (las fichas, en caché); otra pregunta.
    assert llm.requests[0][0]["content"] == director.system_prompt
    assert (
        "Petición: el visitante le pide a Sonnia que haga este gesto o movimiento: «celebrar a lo grande»."
        in llm.user()
    )
    assert "no cuentan la frecuencia" in llm.user()
    # Elegir no manda nada a Unity: lo lanza play_animation.
    assert sent.messages == []
    director.note_requested("bigCheer")
    assert "bigCheer" in director._cooldowns(time.monotonic()).repeated


async def test_un_gesto_pedido_sin_parecido_o_con_fallo_no_da_nada() -> None:
    director, _ = make_director(FakeGestureLLM('{"gesto": "ninguno"}'))
    assert (await director.choose_requested("volar")).name is None
    director, _ = make_director(FakeGestureLLM(RuntimeError("caído")))
    choice = await director.choose_requested("tocarse un ojo")
    assert choice.name is None and choice.error == "caído"
    empty = GestureDirector(fast(), FakeGestureLLM(), Sent())
    assert not empty.can_choose
    assert (await empty.choose_requested("tocarse un ojo")).error
