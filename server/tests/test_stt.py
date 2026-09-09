"""Tests de la etapa de reconocimiento de voz.

No se carga ningún modelo real: `FasterWhisperSTT` se prueba sustituyendo su
carga por un modelo falso.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from sonia.config import STTSettings
from sonia.stt import FasterWhisperSTT, MockSTT, build_stt
from sonia.stt.faster_whisper import resolve_device
from sonia.types import INPUT_SAMPLE_RATE, Utterance


def _utterance(seconds: float = 0.5, sample_rate: int = INPUT_SAMPLE_RATE) -> Utterance:
    """Un turno de audio sintético (tono suave, nunca hardware ni archivos)."""
    t = np.arange(int(seconds * sample_rate), dtype=np.float32) / sample_rate
    audio = (0.2 * np.sin(2 * np.pi * 220.0 * t)).astype(np.float32)
    return Utterance(audio=audio, sample_rate=sample_rate)


class _FakeSegment:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeModel:
    """Sustituto de `faster_whisper.WhisperModel` con la misma forma de API."""

    def __init__(self, segments: list[str]) -> None:
        self.segments = segments
        self.calls: list[dict[str, Any]] = []

    def transcribe(self, audio: Any, **kwargs: Any) -> tuple[list[_FakeSegment], object]:
        self.calls.append({"samples": len(audio), **kwargs})
        return [_FakeSegment(text) for text in self.segments], object()


# ---------------------------------------------------------------------------
# MockSTT
# ---------------------------------------------------------------------------


async def test_mock_stt_devuelve_los_textos_en_orden() -> None:
    stt = MockSTT(["hola", "qué tal"])
    assert await stt.transcribe(_utterance()) == "hola"
    assert await stt.transcribe(_utterance()) == "qué tal"


async def test_mock_stt_repite_el_ultimo_texto() -> None:
    stt = MockSTT(["uno", "dos"])
    await stt.transcribe(_utterance())
    await stt.transcribe(_utterance())
    assert await stt.transcribe(_utterance()) == "dos"
    assert await stt.transcribe(_utterance()) == "dos"


async def test_mock_stt_acepta_una_cadena_y_guarda_las_llamadas() -> None:
    stt = MockSTT("hola sonia")
    assert await stt.transcribe(_utterance()) == "hola sonia"
    assert await stt.transcribe(_utterance()) == "hola sonia"
    assert len(stt.calls) == 2
    stt.reset()
    assert stt.calls == []


async def test_mock_stt_sin_textos_devuelve_vacio() -> None:
    assert await MockSTT([]).transcribe(_utterance()) == ""


# ---------------------------------------------------------------------------
# FasterWhisperSTT
# ---------------------------------------------------------------------------


async def test_faster_whisper_transcribe_concatena_y_limpia(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _FakeModel(["  Hola, ", " ¿cómo\nestás? "])
    monkeypatch.setattr(FasterWhisperSTT, "_load_model", lambda self: model)

    stt = FasterWhisperSTT(STTSettings(model="small", language="es", beam_size=1))
    assert await stt.transcribe(_utterance()) == "Hola, ¿cómo estás?"

    assert len(model.calls) == 1
    call = model.calls[0]
    assert call["language"] == "es"
    assert call["beam_size"] == 1
    assert call["vad_filter"] is False
    assert call["condition_on_previous_text"] is False


async def test_faster_whisper_carga_el_modelo_una_sola_vez(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loads = 0

    def fake_load(self: FasterWhisperSTT) -> _FakeModel:
        nonlocal loads
        loads += 1
        return _FakeModel(["texto"])

    monkeypatch.setattr(FasterWhisperSTT, "_load_model", fake_load)

    stt = FasterWhisperSTT(STTSettings())
    assert stt.loaded is False
    await stt.warmup()
    assert stt.loaded is True
    await stt.transcribe(_utterance())
    await stt.transcribe(_utterance())
    assert loads == 1


async def test_faster_whisper_audio_vacio_no_carga_el_modelo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_load(self: FasterWhisperSTT) -> Any:  # pragma: no cover - no debe llamarse
        raise AssertionError("no debería cargar el modelo con audio vacío")

    monkeypatch.setattr(FasterWhisperSTT, "_load_model", fail_load)
    stt = FasterWhisperSTT(STTSettings())
    empty = Utterance(audio=np.zeros(0, dtype=np.float32))
    assert await stt.transcribe(empty) == ""


async def test_faster_whisper_remuestrea_a_16k(monkeypatch: pytest.MonkeyPatch) -> None:
    model = _FakeModel(["hola"])
    monkeypatch.setattr(FasterWhisperSTT, "_load_model", lambda self: model)

    stt = FasterWhisperSTT(STTSettings())
    await stt.transcribe(_utterance(seconds=1.0, sample_rate=48_000))
    assert model.calls[0]["samples"] == INPUT_SAMPLE_RATE


def test_resolve_device_respeta_lo_configurado() -> None:
    assert resolve_device("cpu", "int8") == ("cpu", "int8")
    assert resolve_device("cuda", "float16") == ("cuda", "float16")


def test_resolve_device_auto_no_usa_mps() -> None:
    device, compute_type = resolve_device("mps", "auto")
    assert device == "cpu"
    assert compute_type == "int8"


def test_resolve_device_auto_elige_algo_valido() -> None:
    device, compute_type = resolve_device("auto", "auto")
    assert device in ("cpu", "cuda")
    assert compute_type == ("float16" if device == "cuda" else "int8")


# ---------------------------------------------------------------------------
# Fábrica
# ---------------------------------------------------------------------------


def test_build_stt_segun_backend() -> None:
    assert isinstance(build_stt(STTSettings(backend="mock")), MockSTT)
    assert isinstance(build_stt(STTSettings(backend="faster_whisper")), FasterWhisperSTT)


def test_build_stt_acepta_settings_completos() -> None:
    from sonia.config import Settings

    settings = Settings(stt=STTSettings(backend="mock"))
    assert isinstance(build_stt(settings), MockSTT)


def test_build_stt_backend_desconocido() -> None:
    settings = STTSettings()
    settings.backend = "inventado"  # type: ignore[assignment]
    with pytest.raises(ValueError):
        build_stt(settings)
