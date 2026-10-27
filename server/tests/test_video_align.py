"""Tiempos por palabra de Sonnia Video: números en letra, alineación difusa y respaldo local."""

from __future__ import annotations

import numpy as np
import pytest

from sonia.video.align import (
    TimedWord,
    align_words,
    atoms,
    distribute,
    fill_gaps,
    similarity,
    spell_number,
    words_from_characters,
)
from sonia.video.audio import (
    SAMPLE_RATE,
    limit,
    quietest_point,
    read_wav,
    resample,
    speech_level,
    to_unity_level,
    unity_gain,
    voiced_runs,
    window_rms,
    write_wav,
)
from tests.video_fakes import synth_take


@pytest.mark.parametrize(
    ("number", "text"),
    [
        (0, "cero"),
        (16, "dieciseis"),
        (21, "veintiuno"),
        (35, "treinta y cinco"),
        (100, "cien"),
        (101, "ciento uno"),
        (515, "quinientos quince"),
        (1000, "mil"),
        (2026, "dos mil veintiseis"),
        (21000, "veintiuno mil"),
        (1_000_000, "un millon"),
        (3_200_001, "tres millones doscientos mil uno"),
    ],
)
def test_numeros_en_letra(number: int, text: str) -> None:
    assert spell_number(number) == text


def test_atomos() -> None:
    assert atoms("¡Hola!") == ["hola"]
    assert atoms("DevFest,") == ["devfest"]
    assert atoms("2026") == ["dos", "mil", "veintiseis"]
    assert atoms("10:30") == ["diez", "treinta"]
    assert atoms("Señoría") == ["senoria"]
    assert atoms("—") == []


def test_parecido() -> None:
    assert similarity("hola", "hola") == 1.0
    assert similarity("sonia", "sonnia") > 0.8
    assert similarity("", "x") == 0.0


def heard(*items: tuple[str, float, float]) -> list[TimedWord]:
    return [TimedWord(*item) for item in items]


def test_alineacion_exacta_con_signos_y_tildes() -> None:
    words = ["¡Hola!", "soy", "Sonia,", "la", "asistente."]
    asr = heard(
        ("hola", 0.1, 0.4),
        ("Soy", 0.5, 0.7),
        ("Sonía", 0.7, 1.1),
        ("la", 1.1, 1.2),
        ("asistente", 1.2, 1.9),
    )
    assert align_words(words, asr) == [(0.1, 0.4), (0.5, 0.7), (0.7, 1.1), (1.1, 1.2), (1.2, 1.9)]


def test_numero_en_cifra_frente_a_letra_y_al_reves() -> None:
    words = ["el", "DevFest", "2026", "empieza"]
    asr = heard(
        ("el", 0.0, 0.1),
        ("DevFest", 0.1, 0.6),
        ("dos", 0.6, 0.8),
        ("mil", 0.8, 1.0),
        ("veintiséis", 1.0, 1.6),
        ("empieza", 1.7, 2.2),
    )
    times = align_words(words, asr)
    assert times[2] == pytest.approx((0.6, 1.6))
    assert times[3] == (1.7, 2.2)
    # La transcripción en cifra y el guion en letra.
    times = align_words(["dos", "mil", "veintiséis"], heard(("2026", 0.0, 1.2)))
    assert all(t is not None for t in times)
    assert times[0][0] == pytest.approx(0.0) and times[2][1] == pytest.approx(1.2)  # type: ignore[index]


def test_palabras_partidas_y_juntadas() -> None:
    words = ["el", "DevFest", "de", "Sonnet", "Code"]
    asr = heard(
        ("el", 0.0, 0.1),
        ("Dev", 0.1, 0.3),
        ("Fest", 0.3, 0.6),
        ("de", 0.6, 0.7),
        ("SonnetCode", 0.7, 1.4),
    )
    times = align_words(words, asr)
    assert times[1] == (0.1, 0.6)
    assert times[3] == (0.7, 1.4) and times[4] == (0.7, 1.4)


def test_palabras_sin_pareja_quedan_sin_tiempo_y_se_interpolan() -> None:
    words = ["uno", "dos", "xyzzy", "cuatro"]
    asr = heard(("uno", 0.0, 0.5), ("dos", 0.5, 1.0), ("cuatro", 2.0, 2.5))
    times = align_words(words, asr)
    assert times[2] is None
    filled = fill_gaps(times, words, end=3.0)
    assert filled[2] == pytest.approx((1.0, 2.0))
    assert filled[3] == (2.0, 2.5)


def test_rellenar_huecos_en_los_extremos_y_en_orden() -> None:
    filled = fill_gaps([None, (1.0, 1.2), None, None], ["aa", "b", "cc", "dddd"], end=2.0)
    assert filled[0] == pytest.approx((0.0, 1.0))
    assert filled[2][0] == pytest.approx(1.2)
    assert filled[3][1] == pytest.approx(2.0)
    # Un tiempo fuera de orden se lleva al de la anterior.
    filled = fill_gaps([(1.0, 1.5), (0.5, 0.6)], ["a", "b"], end=2.0)
    assert filled[1][0] >= filled[0][0]


def test_palabras_desde_los_caracteres() -> None:
    text = "¡Hola! Soy  Sonia."
    starts = [i * 0.1 for i in range(len(text))]
    ends = [s + 0.1 for s in starts]
    words = words_from_characters(list(text), starts, ends)
    assert [w.text for w in words] == ["¡Hola!", "Soy", "Sonia."]
    assert words[0].start == pytest.approx(0.0) and words[0].end == pytest.approx(0.6)
    assert words[2].start == pytest.approx(1.2)


def test_respaldo_local_encuentra_las_pausas_entre_frases() -> None:
    phrases = [["uno", "dos", "tres"], ["cuatro", "cinco"], ["seis"]]
    samples, truth = synth_take(phrases)
    times = distribute(phrases, samples, SAMPLE_RATE)
    assert len(times) == 6
    # Cada frase cae dentro de su tramo de voz real (con un margen de 50 ms).
    starts = [0, 3, 5]
    ends = [2, 4, 5]
    for a, z in zip(starts, ends, strict=True):
        assert times[a][0] >= truth[a][0] - 0.05
        assert times[z][1] <= truth[z][1] + 0.05
    assert all(b[0] >= a[0] for a, b in zip(times, times[1:], strict=False))


def test_respaldo_local_sin_pausas_suficientes() -> None:
    samples, _ = synth_take([["uno", "dos"]], gap_s=0.02)
    times = distribute([["uno"], ["dos"], ["tres"]], samples, SAMPLE_RATE)
    assert len(times) == 3
    assert times[0][0] < times[1][0] < times[2][0]


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------


def test_wav_de_ida_y_vuelta_y_remuestreo(tmp_path) -> None:  # type: ignore[no-untyped-def]
    samples, _ = synth_take([["a", "b"]])
    path = write_wav(tmp_path / "x.wav", samples)
    back, rate = read_wav(path)
    assert rate == SAMPLE_RATE
    assert np.max(np.abs(back - samples)) < 1e-3
    half = resample(samples, SAMPLE_RATE, SAMPLE_RATE // 2)
    assert len(half) == pytest.approx(len(samples) / 2, abs=1)


def test_tramos_con_voz_y_punto_de_corte() -> None:
    samples, truth = synth_take([["a", "b"], ["c"]], gap_s=0.05, phrase_gap_s=0.6)
    runs = voiced_runs(samples, SAMPLE_RATE)
    assert len(runs) == 2
    assert runs[0][0] == pytest.approx(truth[0][0], abs=0.02)
    assert runs[1][1] == pytest.approx(truth[2][1], abs=0.02)
    cut = quietest_point(samples, SAMPLE_RATE, truth[1][1], truth[2][0])
    assert cut == pytest.approx((truth[1][1] + truth[2][0]) / 2, abs=0.03)


def test_nivel_de_unity_y_limitador_sin_recortes() -> None:
    samples, _ = synth_take([["a", "b", "c"]], amplitude=0.9)
    level = speech_level(samples, SAMPLE_RATE)
    assert level == pytest.approx(0.9 / np.sqrt(2), rel=0.05)
    gain = unity_gain(samples, SAMPLE_RATE)
    leveled = to_unity_level(samples, SAMPLE_RATE, gain)
    assert speech_level(leveled, SAMPLE_RATE) == pytest.approx(0.059, rel=0.05)
    # Con mucha ganancia el limitador deja todo por debajo del techo y sin escalones.
    loud = limit(samples * 3, SAMPLE_RATE)
    assert float(np.max(np.abs(loud))) <= 0.97 + 1e-6
    assert float(np.max(np.abs(np.diff(loud)))) < 0.2


def test_rms_por_ventanas() -> None:
    rms = window_rms(np.ones(SAMPLE_RATE, dtype=np.float32), SAMPLE_RATE)
    assert len(rms) == 50
    assert float(rms[0]) == pytest.approx(1.0)
