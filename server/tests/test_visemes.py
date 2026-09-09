"""Tests del lip-sync: visemas por texto y envolvente por audio."""

from __future__ import annotations

import math
import struct

import numpy as np

from sonia.types import VisemeFrame
from sonia.visemes import envelope_for, visemes_for


def _ids(frames: list[VisemeFrame]) -> list[str]:
    return [frame.viseme for frame in frames]


def _speech_ids(text: str) -> list[str]:
    """Visemas del texto sin los silencios, para comprobar el mapeo."""
    return [v for v in _ids(visemes_for(text, 1.0)) if v != "sil"]


# ---------------------------------------------------------------------------
# visemes_for: tiempos
# ---------------------------------------------------------------------------


def test_los_tiempos_son_crecientes_y_caben_en_la_duracion() -> None:
    frames = visemes_for("Hola, ¿cómo estás? Yo soy Sonia.", 2.5)
    tiempos = [frame.t for frame in frames]
    assert tiempos[0] == 0.0
    assert tiempos == sorted(tiempos)
    assert max(tiempos) <= 2.5
    assert frames[-1].t == 2.5


def test_siempre_termina_en_silencio() -> None:
    assert visemes_for("hola", 1.0)[-1].viseme == "sil"
    assert visemes_for("hola.", 1.0)[-1].viseme == "sil"
    assert visemes_for("", 1.0)[-1].viseme == "sil"


def test_texto_vacio_o_duracion_cero() -> None:
    assert _ids(visemes_for("", 0.0)) == ["sil"]
    assert _ids(visemes_for("hola", 0.0)) == ["sil"]
    frames = visemes_for("", 1.0)
    assert _ids(frames) == ["sil", "sil"]
    assert frames[-1].t == 1.0


def test_los_espacios_y_la_puntuacion_generan_silencio() -> None:
    ids = _ids(visemes_for("la, la", 1.0))
    assert ids.count("sil") >= 2  # la coma/espacio del medio y el final
    assert ids[:2] == ["nn", "aa"]


def test_mas_texto_no_alarga_la_frase() -> None:
    corto = visemes_for("hola", 1.0)
    largo = visemes_for("hola, mucho gusto, yo soy Sonia", 1.0)
    assert corto[-1].t == largo[-1].t == 1.0
    assert len(largo) > len(corto)


def test_el_orden_sigue_al_texto() -> None:
    assert _speech_ids("papa") == ["PP", "aa", "PP", "aa"]


# ---------------------------------------------------------------------------
# visemes_for: heurística del español
# ---------------------------------------------------------------------------


def test_vocales() -> None:
    assert _speech_ids("aeiou") == ["aa", "E", "ih", "oh", "ou"]
    assert _speech_ids("áéíóú") == ["aa", "E", "ih", "oh", "ou"]


def test_digrafos() -> None:
    assert _speech_ids("chico") == ["CH", "ih", "kk", "oh"]
    assert _speech_ids("llave") == ["CH", "aa", "FF", "E"]
    assert _speech_ids("perro") == ["PP", "E", "RR", "oh"]
    # La u de "que" y "gue" es muda: un solo visema kk antes de la vocal.
    assert _speech_ids("queso") == ["kk", "E", "SS", "oh"]
    assert _speech_ids("guerra") == ["kk", "E", "RR", "aa"]


def test_c_y_g_suaves() -> None:
    assert _speech_ids("cielo") == ["SS", "ih", "E", "nn", "oh"]
    assert _speech_ids("casa") == ["kk", "aa", "SS", "aa"]
    assert _speech_ids("gente") == ["kk", "E", "nn", "DD", "E"]


def test_h_muda() -> None:
    assert _speech_ids("hola") == ["oh", "nn", "aa"]
    assert _speech_ids("ahora") == ["aa", "oh", "RR", "aa"]


def test_y_y_enie() -> None:
    assert _speech_ids("año") == ["aa", "CH", "oh"]
    assert _speech_ids("yo") == ["CH", "oh"]
    assert _speech_ids("hay") == ["aa", "ih"]  # h muda y la y final suena a vocal


def test_x_y_w() -> None:
    assert _speech_ids("taxi") == ["DD", "aa", "SS", "ih"]
    assert _speech_ids("web") == ["ou", "E", "PP"]


def test_los_digitos_se_ignoran() -> None:
    assert _speech_ids("a1a") == ["aa", "aa"]


def test_las_silabas_reparten_el_tiempo() -> None:
    # Dos sílabas iguales: la segunda empieza cerca de la mitad.
    frames = [f for f in visemes_for("papa", 2.0) if f.viseme != "sil"]
    assert len(frames) == 4
    assert 0.9 <= frames[2].t <= 1.1


# ---------------------------------------------------------------------------
# envelope_for
# ---------------------------------------------------------------------------


def _sine_pcm(seconds: float, sample_rate: int, freq: float = 220.0, amp: float = 0.5) -> bytes:
    t = np.arange(int(seconds * sample_rate), dtype=np.float64) / sample_rate
    samples = (np.sin(2 * np.pi * freq * t) * amp * 32767).astype("<i2")
    return samples.tobytes()


def test_envolvente_de_una_senoidal_es_plana() -> None:
    sample_rate = 24_000
    values = envelope_for(_sine_pcm(0.5, sample_rate), sample_rate, interval_ms=20)
    assert len(values) == 25  # 500 ms / 20 ms
    assert max(values) == 1.0
    assert all(0.0 <= v <= 1.0 for v in values)
    assert all(v > 0.9 for v in values)  # amplitud constante


def test_envolvente_sigue_la_amplitud() -> None:
    sample_rate = 16_000
    fuerte = _sine_pcm(0.1, sample_rate, amp=0.9)
    flojo = _sine_pcm(0.1, sample_rate, amp=0.1)
    values = envelope_for(fuerte + flojo, sample_rate, interval_ms=20)
    assert len(values) == 10
    assert max(values[:5]) == 1.0  # el pico está en la mitad fuerte
    assert min(values[:5]) > 0.9
    assert max(values[5:]) < 0.2  # la mitad floja va nueve veces por debajo
    assert values == [round(v, 3) for v in values]


def test_envolvente_de_silencio_es_cero() -> None:
    silencio = struct.pack("<800h", *([0] * 800))
    values = envelope_for(silencio, 16_000, interval_ms=20)
    assert values == [0.0] * (800 // 320 + 1)
    assert not any(values)


def test_envolvente_vacia() -> None:
    assert envelope_for(b"", 24_000) == []
    assert envelope_for(_sine_pcm(0.1, 16_000), 0) == []


def test_envolvente_incluye_la_ventana_incompleta() -> None:
    sample_rate = 16_000
    pcm = _sine_pcm(0.025, sample_rate)  # 400 muestras: una ventana y media
    values = envelope_for(pcm, sample_rate, interval_ms=20)
    assert len(values) == math.ceil(400 / 320)
