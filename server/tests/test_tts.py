"""Pruebas del módulo de síntesis de voz.

No cargan modelos, no tocan hardware y no llaman a ninguna API real: el motor
HTTP usa ``httpx.MockTransport`` y OmniVoice recibe un modelo falso inyectado.
"""

from __future__ import annotations

import asyncio
import io
import json
import threading
import time
import wave
from typing import Any

import httpx
import numpy as np
import pytest

from sonia.config import TTSSettings
from sonia.tts import (
    HTTPTTS,
    MockTTS,
    OmniVoiceTTS,
    build_tts,
    chunk_pcm,
    float_to_pcm16,
    pcm16_to_float,
    resample,
    wav_to_pcm,
)

# ---------------------------------------------------------------------------
# Ayudas
# ---------------------------------------------------------------------------


def make_wav(samples: np.ndarray, sample_rate: int, channels: int = 1) -> bytes:
    """Construye un WAV PCM de 16 bits en memoria con el módulo `wave`."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(np.asarray(samples, dtype="<i2").tobytes())
    return buffer.getvalue()


def sine(n_samples: int, sample_rate: int, freq: float = 440.0) -> np.ndarray:
    t = np.arange(n_samples, dtype=np.float64) / sample_rate
    return np.sin(2 * np.pi * freq * t).astype(np.float32)


async def collect(engine: Any, text: str) -> list[Any]:
    return [chunk async for chunk in engine.synthesize(text)]


# ---------------------------------------------------------------------------
# base.float_to_pcm16
# ---------------------------------------------------------------------------


def test_float_to_pcm16_recorta_fuera_de_rango() -> None:
    audio = np.array([0.0, 1.0, -1.0, 2.5, -3.0], dtype=np.float32)
    values = np.frombuffer(float_to_pcm16(audio), dtype="<i2")
    assert list(values) == [0, 32767, -32767, 32767, -32767]


def test_float_to_pcm16_es_little_endian_y_16_bits() -> None:
    pcm = float_to_pcm16(np.array([1.0], dtype=np.float32))
    assert pcm == b"\xff\x7f"
    assert len(float_to_pcm16(np.zeros(10, dtype=np.float32))) == 20


def test_float_to_pcm16_vacio() -> None:
    assert float_to_pcm16(np.zeros(0, dtype=np.float32)) == b""


def test_pcm16_to_float_es_inversa_aproximada() -> None:
    audio = sine(500, 24_000)
    recovered = pcm16_to_float(float_to_pcm16(audio))
    assert recovered.shape == audio.shape
    assert np.max(np.abs(recovered - audio)) < 1e-3


# ---------------------------------------------------------------------------
# base.chunk_pcm
# ---------------------------------------------------------------------------


def test_chunk_pcm_tamanos_e_is_last() -> None:
    sample_rate = 24_000
    # 250 ms de audio: dos chunks completos de 100 ms y uno de 50 ms.
    pcm = b"\x00\x00" * (sample_rate // 4)
    chunks = chunk_pcm(pcm, sample_rate, 100)

    assert len(chunks) == 3
    assert [len(c.pcm) for c in chunks] == [4800, 4800, 2400]
    assert [c.is_last for c in chunks] == [False, False, True]
    assert all(c.sample_rate == sample_rate for c in chunks)
    assert b"".join(c.pcm for c in chunks) == pcm


def test_chunk_pcm_multiplo_exacto() -> None:
    pcm = b"\x01\x00" * 4800
    chunks = chunk_pcm(pcm, 24_000, 100)
    assert len(chunks) == 2
    assert chunks[-1].is_last
    assert not chunks[0].is_last


def test_chunk_pcm_vacio_devuelve_un_chunk_final() -> None:
    chunks = chunk_pcm(b"", 24_000, 100)
    assert len(chunks) == 1
    assert chunks[0].pcm == b""
    assert chunks[0].is_last


def test_chunk_pcm_duracion_del_chunk() -> None:
    chunks = chunk_pcm(b"\x00\x00" * 2400, 24_000, 100)
    assert chunks[0].duration == pytest.approx(0.1)


def test_chunk_pcm_rechaza_parametros_invalidos() -> None:
    with pytest.raises(ValueError):
        chunk_pcm(b"\x00\x00", 0, 100)
    with pytest.raises(ValueError):
        chunk_pcm(b"\x00\x00", 24_000, 0)


# ---------------------------------------------------------------------------
# base.wav_to_pcm
# ---------------------------------------------------------------------------


def test_wav_to_pcm_mono() -> None:
    samples = (sine(1000, 22_050) * 20000).astype("<i2")
    pcm, rate = wav_to_pcm(make_wav(samples, 22_050))

    assert rate == 22_050
    assert np.array_equal(np.frombuffer(pcm, dtype="<i2"), samples)


def test_wav_to_pcm_estereo_se_mezcla_a_mono() -> None:
    left = np.array([100, 200, 300, -400], dtype="<i2")
    right = np.array([300, 0, -300, 400], dtype="<i2")
    interleaved = np.empty(left.size * 2, dtype="<i2")
    interleaved[0::2] = left
    interleaved[1::2] = right

    pcm, rate = wav_to_pcm(make_wav(interleaved, 24_000, channels=2))
    mono = np.frombuffer(pcm, dtype="<i2")

    assert rate == 24_000
    assert mono.size == 4
    assert list(mono) == [200, 100, 0, 0]


def test_wav_to_pcm_rechaza_datos_no_wav() -> None:
    with pytest.raises(ValueError):
        wav_to_pcm(b"no soy un wav en absoluto")


def test_wav_to_pcm_rechaza_profundidad_distinta_de_16() -> None:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(1)
        handle.setframerate(24_000)
        handle.writeframes(b"\x80" * 100)
    with pytest.raises(ValueError):
        wav_to_pcm(buffer.getvalue())


# ---------------------------------------------------------------------------
# base.resample
# ---------------------------------------------------------------------------


def test_resample_sin_cambio_devuelve_lo_mismo() -> None:
    audio = sine(100, 24_000)
    assert np.array_equal(resample(audio, 24_000, 24_000), audio)


def test_resample_cambia_la_longitud_proporcionalmente() -> None:
    audio = sine(22_050, 22_050)  # un segundo
    out = resample(audio, 22_050, 24_000)
    assert out.dtype == np.float32
    assert out.size == 24_000


def test_resample_interpola_linealmente() -> None:
    audio = np.array([0.0, 1.0, 2.0, 3.0], dtype=np.float32)
    out = resample(audio, 1, 2)
    # Posiciones 0, 0.5, 1, 1.5, ... sobre la rampa original.
    assert out.size == 8
    assert out[:4] == pytest.approx([0.0, 0.5, 1.0, 1.5])


def test_resample_conserva_una_senal_tras_ida_y_vuelta() -> None:
    audio = sine(4800, 24_000, freq=100.0)
    ida = resample(audio, 24_000, 48_000)
    vuelta = resample(ida, 48_000, 24_000)
    assert vuelta.size == audio.size
    assert np.max(np.abs(vuelta - audio)) < 0.01


def test_resample_vacio() -> None:
    assert resample(np.zeros(0, dtype=np.float32), 22_050, 24_000).size == 0


# ---------------------------------------------------------------------------
# MockTTS
# ---------------------------------------------------------------------------


async def test_mock_tts_duracion_proporcional_al_texto() -> None:
    tts = MockTTS(sample_rate=24_000, ms_per_char=60)
    corto = await collect(tts, "hola")  # 4 caracteres -> 240 ms
    largo = await collect(tts, "hola hola")  # 9 caracteres -> 540 ms

    bytes_corto = sum(len(c.pcm) for c in corto)
    bytes_largo = sum(len(c.pcm) for c in largo)

    assert bytes_corto == 4 * 0.06 * 24_000 * 2
    assert bytes_largo == pytest.approx(bytes_corto * 9 / 4, rel=0.01)
    assert tts.calls == ["hola", "hola hola"]


async def test_mock_tts_marca_el_ultimo_chunk() -> None:
    tts = MockTTS(sample_rate=24_000, ms_per_char=60)
    chunks = await collect(tts, "hola sonia")

    assert len(chunks) > 1
    assert chunks[-1].is_last
    assert not any(c.is_last for c in chunks[:-1])
    assert all(c.sample_rate == 24_000 for c in chunks)


async def test_mock_tts_texto_vacio_emite_un_chunk_final() -> None:
    chunks = await collect(MockTTS(), "")
    assert len(chunks) == 1
    assert chunks[0].pcm == b""
    assert chunks[0].is_last


async def test_mock_tts_tono_y_silencio() -> None:
    con_tono = await collect(MockTTS(tone=True), "hola sonia")
    silencio = await collect(MockTTS(tone=False), "hola sonia")

    pcm_tono = pcm16_to_float(b"".join(c.pcm for c in con_tono))
    pcm_silencio = pcm16_to_float(b"".join(c.pcm for c in silencio))

    assert np.max(np.abs(pcm_tono)) > 0.2
    assert np.max(np.abs(pcm_silencio)) == 0.0
    # Envolvente suave: el audio empieza y termina cerca de cero.
    assert abs(pcm_tono[0]) < 0.01
    assert abs(pcm_tono[-1]) < 0.01


# ---------------------------------------------------------------------------
# HTTPTTS
# ---------------------------------------------------------------------------


def http_settings(**overrides: Any) -> TTSSettings:
    values: dict[str, Any] = {
        "backend": "http",
        "base_url": "http://tts.local/v1",
        "api_key": "clave-de-prueba",
        "http_model": "omnivoice",
        "voice_instruct": "voz de prueba",
        "speed": 1.25,
        "sample_rate": 24_000,
    }
    values.update(overrides)
    return TTSSettings(**values)


async def test_http_tts_envia_el_body_correcto_y_remuestrea() -> None:
    captured: dict[str, Any] = {}
    source_rate = 22_050
    samples = (sine(source_rate, source_rate, freq=110.0) * 10_000).astype("<i2")

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            content=make_wav(samples, source_rate),
            headers={"content-type": "audio/wav"},
        )

    tts = HTTPTTS(http_settings(), transport=httpx.MockTransport(handler))
    try:
        chunks = await collect(tts, "hola sonia")
    finally:
        await tts.aclose()

    assert captured["url"] == "http://tts.local/v1/audio/speech"
    assert captured["headers"]["authorization"] == "Bearer clave-de-prueba"
    assert captured["body"] == {
        "model": "omnivoice",
        "input": "hola sonia",
        "voice": "voz de prueba",
        "response_format": "wav",
        "speed": 1.25,
    }

    # Un segundo a 22 050 Hz remuestreado a 24 000 Hz -> 24 000 muestras.
    total = sum(len(c.pcm) for c in chunks)
    assert total == 24_000 * 2
    assert all(c.sample_rate == 24_000 for c in chunks)
    assert chunks[-1].is_last
    assert len(chunks) == 10  # chunks de 100 ms


async def test_http_tts_acepta_pcm_crudo() -> None:
    pcm = float_to_pcm16(sine(2400, 24_000))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=pcm, headers={"content-type": "audio/pcm"})

    tts = HTTPTTS(http_settings(), transport=httpx.MockTransport(handler))
    try:
        chunks = await collect(tts, "hola")
    finally:
        await tts.aclose()

    assert b"".join(c.pcm for c in chunks) == pcm
    assert chunks[-1].is_last


async def test_http_tts_respuesta_vacia_no_rompe() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"", headers={"content-type": "audio/wav"})

    tts = HTTPTTS(http_settings(), transport=httpx.MockTransport(handler))
    try:
        chunks = await collect(tts, "hola")
    finally:
        await tts.aclose()

    assert len(chunks) == 1
    assert chunks[0].is_last
    assert chunks[0].pcm == b""


async def test_http_tts_propaga_errores_del_servidor() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    tts = HTTPTTS(http_settings(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await collect(tts, "hola")
    finally:
        await tts.aclose()


# ---------------------------------------------------------------------------
# OmniVoiceTTS con modelo falso
# ---------------------------------------------------------------------------


class FakeOmniVoice:
    """Modelo falso: registra los kwargs y devuelve una lista de arrays."""

    def __init__(self, pieces: list[np.ndarray] | None = None, delay: float = 0.0) -> None:
        self.pieces = pieces if pieces is not None else [np.zeros(2400, dtype=np.float32)]
        self.delay = delay
        self.calls: list[dict[str, Any]] = []
        self.concurrent = 0
        self.max_concurrent = 0
        self._guard = threading.Lock()

    def generate(self, **kwargs: Any) -> list[np.ndarray]:
        with self._guard:
            self.calls.append(kwargs)
            self.concurrent += 1
            self.max_concurrent = max(self.max_concurrent, self.concurrent)
        try:
            if self.delay:
                time.sleep(self.delay)
            return list(self.pieces)
        finally:
            with self._guard:
                self.concurrent -= 1


def omni_settings(**overrides: Any) -> TTSSettings:
    values: dict[str, Any] = {
        "backend": "omnivoice",
        "voice_instruct": "voz calida",
        "ref_audio": "",
        "ref_text": "",
        "num_step": 16,
        "speed": 1.0,
        "sample_rate": 24_000,
        "device": "cpu",
    }
    values.update(overrides)
    return TTSSettings(**values)


async def test_omnivoice_concatena_los_arrays_y_trocea() -> None:
    pieces = [sine(2400, 24_000, 100.0), sine(1200, 24_000, 200.0)]
    model = FakeOmniVoice(pieces)
    tts = OmniVoiceTTS(omni_settings(), model_factory=lambda: model)

    chunks = await collect(tts, "hola sonia")

    esperado = float_to_pcm16(np.concatenate(pieces))
    assert b"".join(c.pcm for c in chunks) == esperado
    assert len(chunks) == 2  # 3600 muestras = 100 ms + 50 ms
    assert [len(c.pcm) for c in chunks] == [4800, 2400]
    assert chunks[-1].is_last
    assert tts.sample_rate == 24_000


async def test_omnivoice_pasa_instruct_cuando_no_hay_audio_de_referencia() -> None:
    model = FakeOmniVoice()
    tts = OmniVoiceTTS(omni_settings(), model_factory=lambda: model)

    await collect(tts, "hola")

    assert model.calls == [
        {
            "text": "hola",
            "num_step": 16,
            "speed": 1.0,
            "instruct": "voz calida",
        }
    ]


async def test_omnivoice_usa_ref_audio_con_prioridad() -> None:
    model = FakeOmniVoice()
    settings = omni_settings(ref_audio="/tmp/voz.wav", ref_text="hola que tal", num_step=8)
    tts = OmniVoiceTTS(settings, model_factory=lambda: model)

    await collect(tts, "hola")

    kwargs = model.calls[0]
    assert kwargs["ref_audio"] == "/tmp/voz.wav"
    assert kwargs["ref_text"] == "hola que tal"
    assert kwargs["num_step"] == 8
    assert "instruct" not in kwargs


async def test_omnivoice_ref_text_vacio_va_como_none() -> None:
    model = FakeOmniVoice()
    tts = OmniVoiceTTS(omni_settings(ref_audio="/tmp/voz.wav"), model_factory=lambda: model)

    await collect(tts, "hola")

    assert model.calls[0]["ref_text"] is None


async def test_omnivoice_carga_el_modelo_una_sola_vez() -> None:
    cargas = 0
    model = FakeOmniVoice()

    def factory() -> FakeOmniVoice:
        nonlocal cargas
        cargas += 1
        return model

    tts = OmniVoiceTTS(omni_settings(), model_factory=factory)
    await collect(tts, "una")
    await collect(tts, "dos")

    assert cargas == 1
    assert len(model.calls) == 2


async def test_omnivoice_serializa_las_llamadas_al_modelo() -> None:
    model = FakeOmniVoice(delay=0.05)
    tts = OmniVoiceTTS(omni_settings(), model_factory=lambda: model)

    await asyncio.gather(*(collect(tts, f"frase {i}") for i in range(4)))

    assert len(model.calls) == 4
    assert model.max_concurrent == 1


async def test_omnivoice_remuestrea_si_la_tasa_configurada_difiere() -> None:
    model = FakeOmniVoice([np.zeros(24_000, dtype=np.float32)])
    tts = OmniVoiceTTS(omni_settings(sample_rate=16_000), model_factory=lambda: model)

    chunks = await collect(tts, "hola")

    assert all(c.sample_rate == 16_000 for c in chunks)
    assert sum(len(c.pcm) for c in chunks) == 16_000 * 2


async def test_omnivoice_salida_vacia_emite_un_chunk_final() -> None:
    model = FakeOmniVoice([])
    tts = OmniVoiceTTS(omni_settings(), model_factory=lambda: model)

    chunks = await collect(tts, "hola")

    assert len(chunks) == 1
    assert chunks[0].pcm == b""
    assert chunks[0].is_last


async def test_omnivoice_warmup_sintetiza_una_frase() -> None:
    model = FakeOmniVoice()
    tts = OmniVoiceTTS(omni_settings(), model_factory=lambda: model)

    await tts.warmup()

    assert len(model.calls) == 1
    assert model.calls[0]["text"]


async def test_omnivoice_warmup_no_propaga_errores() -> None:
    def factory() -> Any:
        raise RuntimeError("no hay pesos")

    tts = OmniVoiceTTS(omni_settings(), model_factory=factory)
    await tts.warmup()  # no debe lanzar


def test_omnivoice_device_configurado_gana_al_auto() -> None:
    tts = OmniVoiceTTS(omni_settings(device="cuda"), model_factory=lambda: FakeOmniVoice())
    assert tts.resolve_device() == "cuda"


def test_omnivoice_device_auto_devuelve_algo_valido() -> None:
    tts = OmniVoiceTTS(omni_settings(device="auto"), model_factory=lambda: FakeOmniVoice())
    assert tts.resolve_device() in ("cuda", "mps", "cpu")


# ---------------------------------------------------------------------------
# factory
# ---------------------------------------------------------------------------


def test_build_tts_elige_el_backend() -> None:
    assert isinstance(build_tts(TTSSettings(backend="mock")), MockTTS)
    assert isinstance(build_tts(TTSSettings(backend="http")), HTTPTTS)
    assert isinstance(build_tts(TTSSettings(backend="omnivoice")), OmniVoiceTTS)


def test_build_tts_gemini_lee_el_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    from sonia.tts.gemini import GeminiTTS

    monkeypatch.setenv("TTS_GEMINI_API_KEY", "clave-de-prueba")
    monkeypatch.setenv("TTS_GEMINI_VOICE", "Kore")
    engine = build_tts(TTSSettings(backend="gemini"))
    assert isinstance(engine, GeminiTTS)
    assert engine.sample_rate == 24_000


def test_build_tts_acepta_los_settings_completos() -> None:
    from sonia.config import Settings

    settings = Settings(tts=TTSSettings(backend="mock", sample_rate=16_000))
    engine = build_tts(settings)
    assert isinstance(engine, MockTTS)
    assert engine.sample_rate == 16_000


def test_build_tts_rechaza_backend_desconocido() -> None:
    settings = TTSSettings(backend="mock")
    object.__setattr__(settings, "backend", "inventado")
    with pytest.raises(ValueError):
        build_tts(settings)
