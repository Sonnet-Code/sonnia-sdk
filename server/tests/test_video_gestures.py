"""Gestos de Sonnia Video: una petición con el guion entero, validada contra el catálogo y
colocada con las reglas de frecuencia de Genies."""

from __future__ import annotations

import pytest

from sonia.config import GestureSettings
from sonia.gestures.catalog import GestureCatalog
from sonia.llm.client import Completion
from sonia.types import Message
from sonia.video.errors import VideoError
from sonia.video.gestures import (
    ScriptPhrase,
    build_system_prompt,
    build_user_message,
    choose_gestures,
    gesture_llm,
    parse_choices,
    resolve_names,
    schedule,
)
from tests.video_fakes import CATALOG

catalog = GestureCatalog.from_message(CATALOG)


class FakeLLM:
    def __init__(self, answer: str | Exception) -> None:
        self.answer = answer
        self.requests: list[list[Message]] = []

    async def complete(self, messages: list[Message]) -> Completion:
        self.requests.append(messages)
        if isinstance(self.answer, Exception):
            raise self.answer
        return Completion(self.answer, "stop")


def phrases(*starts: float, length: float = 2.0) -> list[ScriptPhrase]:
    return [
        ScriptPhrase(uid=i + 1, text=f"Frase {i + 1}.", start=s, duration=length, end=s + length)
        for i, s in enumerate(starts)
    ]


def settings(**values: float) -> GestureSettings:
    base: dict[str, float] = {
        "min_gap_s": 0.5,
        "max_delay_s": 2.5,
        "repeat_s": 90,
        "uncommon_s": 45,
        "rare_s": 300,
    }
    base.update(values)
    return GestureSettings(**base)  # type: ignore[arg-type]


def test_prompt_con_catalogo_y_guion() -> None:
    prompt = build_system_prompt(catalog)
    assert "Gestos de Sage" in prompt
    assert "- waveCalm · Standard, Short, LowImpact, intensidad 2 · Waves hello calmly" in prompt
    assert '{"gestos": [{"frase": 1' in prompt
    user = build_user_message(phrases(0.6, 3.0), {1: "waveCalm"})
    assert "1. (2.0 s) «Frase 1.» — gesto fijado: waveCalm" in user
    assert "2. (2.0 s) «Frase 2.»" in user


def test_respuesta_del_modelo_validada_contra_el_catalogo() -> None:
    text = (
        "```json\n"
        '{"gestos": [{"frase": 1, "gesto": "wavecalm"}, {"frase": 2, "gesto": "ninguno"},'
        ' {"frase": 3, "gesto": "inventado"}, {"frase": 9, "gesto": "shrug"},'
        ' {"frase": "4", "gesto": "thumbsUpCalm"}, {"frase": 1, "gesto": "shrug"}]}\n```'
    )
    chosen, notes = parse_choices(text, catalog, [1, 2, 3, 4])
    assert chosen == {1: "waveCalm", 4: "thumbsUpCalm"}
    assert notes == ["frase 3: «inventado» no está en el catálogo"]
    # Lista suelta, por posición.
    chosen, _ = parse_choices('["shrug", "ninguno"]', catalog, [1, 2])
    assert chosen == {1: "shrug"}
    with pytest.raises(VideoError):
        parse_choices("no sé", catalog, [1])


async def test_una_sola_peticion_y_los_fijados_mandan() -> None:
    llm = FakeLLM(
        '{"gestos": [{"frase": 1, "gesto": "thumbsUpCalm"}, {"frase": 2, "gesto": "shrug"}]}'
    )
    chosen = await choose_gestures(llm, catalog, phrases(0.6, 4.0), {1: "waveCalm"})
    assert chosen == {2: "shrug"}
    assert len(llm.requests) == 1
    system, user = llm.requests[0]
    assert system["role"] == "system" and user["role"] == "user"


async def test_fallo_del_modelo() -> None:
    with pytest.raises(VideoError, match="el modelo de gestos falló: sin red"):
        await choose_gestures(FakeLLM(RuntimeError("sin red")), catalog, phrases(0.6), {})
    with pytest.raises(VideoError, match="no contestó nada"):
        await choose_gestures(FakeLLM(""), catalog, phrases(0.6), {})


def test_reglas_de_frecuencia_en_codigo() -> None:
    # Cuatro frases seguidas de 2 s; los Uncommon, uno como mucho cada 45 s.
    cues, notes = schedule(
        phrases(0.6, 3.0, 5.4, 7.8),
        {1: "shrug", 2: "palmsUp", 3: "shrug", 4: "bigCheer"},
        {},
        catalog,
        settings(),
    )
    assert {uid: cue.name for uid, cue in cues.items()} == {1: "shrug", 4: "bigCheer"}
    assert "frase 2: palmsUp quitado por frecuencia" in notes
    assert "frase 3: shrug quitado por frecuencia" in notes


def test_un_gesto_espera_al_nucleo_del_anterior() -> None:
    # explainHands ocupa 2,5 s de núcleo: el de la frase 2 (1,0 s después) espera.
    cues, _ = schedule(
        phrases(0.6, 1.6, length=3.0),
        {1: "explainHands", 2: "thumbsUpCalm"},
        {},
        catalog,
        settings(),
    )
    assert cues[2].at == pytest.approx(0.6 + 2.5 + 0.5)
    # Si tendría que esperar más de max_delay_s, se quita.
    cues, notes = schedule(
        phrases(0.6, 1.6, length=3.0),
        {1: "explainHands", 2: "thumbsUpCalm"},
        {},
        catalog,
        settings(max_delay_s=1.0),
    )
    assert 2 not in cues
    assert "aún dura el gesto anterior" in notes[0]


def test_los_fijados_van_siempre_y_cuentan_como_usados() -> None:
    cues, notes = schedule(
        phrases(0.6, 0.9),
        {2: "waveCalm"},
        {1: "waveCalm", 2: "shrug"},
        catalog,
        settings(),
    )
    assert cues[1].name == "waveCalm" and cues[2].name == "shrug"
    assert cues[2].at == pytest.approx(0.9)
    assert notes == []


def test_nombres_escritos_a_mano() -> None:
    assert resolve_names(["WAVECALM", " shrug "], catalog, "[[frase]]") == ["waveCalm", "shrug"]
    with pytest.raises(
        VideoError, match="«waveCalma» no está en el catálogo. ¿Quisiste decir waveCalm"
    ):
        resolve_names(["waveCalma"], catalog, "[[frase]]")


def test_cliente_del_modelo_de_gestos(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "GESTURE_BASE_URL",
        "GESTURE_MODEL",
        "GESTURE_API_KEY",
        "LLM_API_KEY",
        "OPENAI_API_KEY",
        "LIVE_API_KEY",
        "LLM_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert gesture_llm() is None
    monkeypatch.setenv("GEMINI_API_KEY", "falsa")
    client = gesture_llm()
    assert client is not None
    assert client._settings.model == "gemini-3.1-flash-lite"  # type: ignore[attr-defined]
    assert client._settings.max_tokens >= 4096  # type: ignore[attr-defined]
