"""Plan de Sonnia Video: cortes entre frases, voz maestra, niveles para Unity y línea de tiempo."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from sonia.video.audio import SAMPLE_RATE, read_wav, speech_level
from sonia.video.plan import (
    IDLE_AFTER_S,
    LEAD_IN_S,
    TRANSCRIPT_DELAY_S,
    GestureCue,
    Plan,
    build_plan,
    build_timeline,
    write_unity_wavs,
)
from sonia.video.script import Action, parse_script, phrase_texts
from sonia.video.voice import Take
from tests.video_fakes import synth_take

PHRASE_GAP = 0.5


def make_plan(
    *, pauses: tuple[float, ...] = (0.0, 0.5, 0.0), amplitude: float = 0.3
) -> tuple[Plan, list[tuple[float, float]]]:
    script = parse_script(
        {
            "pronunciacion": {"sonnetcode.com": "sónet code punto com"},
            "frase": [
                {"texto": "¡Hola! Soy Sonia."},
                {"texto": "Visita sonnetcode.com."},
                {"texto": "Adiós."},
            ],
        }
    )
    texts = phrase_texts(script)
    samples, truth = synth_take(
        [t.spoken_words for t in texts], phrase_gap_s=PHRASE_GAP, amplitude=amplitude
    )
    take = Take(
        samples=samples,
        rate=SAMPLE_RATE,
        words=truth,
        engine="gemini",
        voice="x",
        model="y",
        timing="transcripcion",
    )
    plan = build_plan(texts, take, pauses=list(pauses), lead_s=0.6, tail_s=1.5)
    return plan, truth


def test_cortes_por_el_medio_del_silencio_y_pausas() -> None:
    plan, truth = make_plan()
    first, second, third = plan.phrases
    assert [p.uid for p in plan.phrases] == [1, 2, 3]
    # El silencio del principio se recorta a LEAD_IN_S antes de la voz.
    assert first.audio_start == 0.0
    assert first.voice_start == pytest.approx(LEAD_IN_S, abs=0.011)
    # Entre frases se corta por el medio del silencio.
    assert first.audio_end - first.voice_end == pytest.approx(PHRASE_GAP / 2, abs=0.02)
    assert second.voice_start - second.audio_start == pytest.approx(PHRASE_GAP / 2, abs=0.02)
    # La pausa de la segunda frase va entre su audio y el de la tercera.
    assert third.audio_start == pytest.approx(second.audio_end + 0.5, abs=1e-3)
    # La voz maestra lleva los trozos y la pausa, y nada más.
    pieces = sum(len(p.samples) for p in plan.phrases) + round(0.5 * SAMPLE_RATE)
    assert len(plan.master) == pieces
    assert plan.duration_s == pytest.approx(0.6 + plan.master_duration + 1.5)
    # Las palabras conservan su duración en la voz maestra.
    shift = first.voice_start - truth[0][0]
    assert first.units[1].start == pytest.approx(truth[1][0] + shift, abs=1e-3)


def test_un_trozo_con_varias_palabras_dichas() -> None:
    plan, _ = make_plan()
    second = plan.phrases[1]
    assert [u.display for u in second.units] == ["Visita", "sonnetcode.com."]
    unit = second.units[1]
    # De «sónet» a «com»: cuatro palabras de 0,25 s con tres huecos de 0,08 s.
    assert unit.end - unit.start == pytest.approx(4 * 0.25 + 3 * 0.08, abs=0.01)


def test_wavs_de_unity_al_nivel_de_gpt_live(tmp_path: Path) -> None:
    plan, _ = make_plan(amplitude=0.8)
    wavs = write_unity_wavs(plan, tmp_path)
    assert sorted(wavs) == [1, 2, 3]
    assert wavs[1].name == "u001.wav"
    joined = np.concatenate([read_wav(wavs[uid])[0] for uid in (1, 2, 3)])
    assert read_wav(wavs[1])[1] == SAMPLE_RATE
    assert speech_level(joined, SAMPLE_RATE) == pytest.approx(0.059, rel=0.08)
    assert float(np.max(np.abs(joined))) <= 0.97 + 1e-3
    # La voz maestra sigue a su nivel original.
    assert speech_level(plan.master, SAMPLE_RATE) == pytest.approx(0.8 / np.sqrt(2), rel=0.05)


def messages(timeline: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [e for e in timeline if "message" in e and e["message"]["type"] == kind]


def test_linea_de_tiempo_como_en_el_stand(tmp_path: Path) -> None:
    plan, _ = make_plan()
    wavs = write_unity_wavs(plan, tmp_path)
    timeline = build_timeline(
        plan,
        wavs,
        gestures={1: GestureCue("waveCalm", plan.phrase_t(0))},
        actions=[Action.model_validate({"segundo": 0.2, "gesto": "thumbsUpCalm", "espejo": True})],
        fps=30,
    )
    times = [e["t"] for e in timeline]
    assert times == sorted(times)
    assert all(0 <= t <= plan.duration_s for t in times)
    # Arranque: modo del stand sin conversación y reposo.
    assert timeline[0] == {
        "t": 0.0,
        "message": {"type": "stage_mode", "mode": "greeter", "talk": False},
    }
    assert timeline[1] == {"t": 0.0, "message": {"type": "state", "state": "idle"}}
    # Acción suelta a su hora.
    assert {"t": 0.2, "action": {"name": "thumbsUpCalm", "mirror": True}} in timeline
    # La primera frase: speaking, gesto, speech_start y audio, en ese orden y a la misma hora.
    t0 = plan.phrase_t(0)
    assert t0 == pytest.approx(0.6)
    start = next(
        i for i, e in enumerate(timeline) if e.get("message", {}).get("state") == "speaking"
    )
    kinds = [
        e.get("message", {}).get("type") or ("audio" if "audio" in e else "action")
        for e in timeline[start : start + 4]
    ]
    assert kinds == ["state", "gesture", "speech_start", "audio"]
    assert all(e["t"] == pytest.approx(t0) for e in timeline[start : start + 4])
    assert timeline[start + 1]["message"] == {
        "type": "gesture",
        "name": "waveCalm",
        "utterance_id": 1,
    }
    assert timeline[start + 2]["message"] == {"type": "speech_start", "utterance_id": 1, "text": ""}
    assert timeline[start + 3]["audio"] == {"utterance_id": 1, "wav": str(wavs[1])}
    # Un audio por frase, a su hora.
    audio = [e for e in timeline if "audio" in e]
    assert [e["t"] for e in audio] == [pytest.approx(plan.phrase_t(k)) for k in range(3)]
    # Subtítulos acumulados palabra a palabra, con «Sonnia», y el final.
    first = [
        e["message"]
        for e in messages(timeline, "transcript")
        if e["message"]["text"].startswith("¡Hola")
    ]
    assert [m["text"] for m in first] == [
        "¡Hola!",
        "¡Hola! Soy",
        "¡Hola! Soy Sonnia.",
        "¡Hola! Soy Sonnia.",
    ]
    assert [m["final"] for m in first] == [False, False, False, True]
    assert all(m["role"] == "assistant" for m in first)
    word = next(e for e in timeline if e.get("message", {}).get("text") == "¡Hola! Soy")
    unit = plan.phrases[0].units[1]
    assert word["t"] == pytest.approx(t0 + unit.start + TRANSCRIPT_DELAY_S, abs=1e-3)
    # Lo de una frase nunca llega después de que empiece la siguiente.
    for k, phrase in enumerate(plan.phrases[:-1]):
        own = [
            e["t"]
            for e in messages(timeline, "transcript")
            if e["message"]["text"].startswith(phrase.units[0].display)
        ]
        assert max(own) < plan.phrase_t(k + 1)
    # Reposo al acabar la voz.
    assert timeline[-1]["message"] == {"type": "state", "state": "idle"}
    assert timeline[-1]["t"] == pytest.approx(
        plan.lead_s + plan.master_duration + IDLE_AFTER_S, abs=1e-3
    )


def test_gesto_retrasado_va_tras_el_speech_start(tmp_path: Path) -> None:
    plan, _ = make_plan()
    wavs = write_unity_wavs(plan, tmp_path)
    late = plan.phrase_t(1) + 0.4
    timeline = build_timeline(plan, wavs, gestures={2: GestureCue("thumbsUpCalm", late)})
    gesture = messages(timeline, "gesture")[0]
    assert gesture["t"] == pytest.approx(late)
    start = next(
        i
        for i, e in enumerate(timeline)
        if e.get("message", {}).get("type") == "speech_start" and e["message"]["utterance_id"] == 2
    )
    assert timeline.index(gesture) > start


def test_reposo_final_nunca_despues_del_ultimo_cuadro(tmp_path: Path) -> None:
    plan, _ = make_plan()
    plan.tail_s = 0.0
    timeline = build_timeline(plan, write_unity_wavs(plan, tmp_path), fps=30)
    assert timeline[-1]["t"] <= plan.duration_s - 1 / 30 + 1e-6
