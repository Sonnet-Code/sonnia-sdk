"""Pruebas del detector de turnos y de las utilidades de audio.

No se abre ningún dispositivo real ni se carga ningún modelo: el VAD se
sustituye por uno falso que devuelve probabilidades de una secuencia
predefinida, un bloque por probabilidad.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator, Callable, Iterable, Sequence
from typing import Any

import numpy as np
import pytest

from sonia.audio.capture import (
    QUEUE_MAXSIZE,
    MicCapture,
    MicStalled,
    list_input_devices,
    resolve_input_device,
)
from sonia.audio.vad import (
    BargeIn,
    SpeechDiscarded,
    SpeechStarted,
    TurnDetector,
    TurnEvent,
    resample_to_16k,
)
from sonia.config import AudioSettings
from sonia.types import INPUT_SAMPLE_RATE, AudioArray, Utterance

BLOCK_MS = 32
BLOCK_SAMPLES = BLOCK_MS * INPUT_SAMPLE_RATE // 1000  # 512 muestras


class FakeVad:
    """VAD falso: devuelve las probabilidades de una secuencia, en orden."""

    def __init__(self, probabilities: Sequence[float]) -> None:
        self._probabilities = list(probabilities)
        self.calls = 0

    def probability(self, block: AudioArray) -> float:
        index = min(self.calls, len(self._probabilities) - 1)
        self.calls += 1
        return self._probabilities[index]


def make_settings(**overrides: object) -> AudioSettings:
    """Configuración de audio determinista para los tests (bloques de 32 ms)."""
    defaults: dict[str, object] = {
        "block_ms": BLOCK_MS,
        "vad_threshold": 0.5,
        "vad_threshold_while_speaking": 0.8,
        "end_silence_ms": 96,  # 3 bloques
        "min_speech_ms": 64,  # 2 bloques
        "barge_in_min_speech_ms": 128,  # 4 bloques
        "barge_in_warmup_ms": 0,
        "barge_in_over_echo": 2.5,
        "echo_level_tau_ms": 640,  # 20 bloques
        "max_utterance_s": 10.0,
        "pre_roll_ms": 64,  # 2 bloques
    }
    defaults.update(overrides)
    return AudioSettings(**defaults)  # type: ignore[arg-type]


def make_blocks(probabilities: Sequence[float]) -> list[AudioArray]:
    """Un bloque por probabilidad, con un valor distinto en cada uno.

    El valor permite identificar qué bloques acabaron dentro de la `Utterance`.
    """
    return [
        np.full(BLOCK_SAMPLES, float(i + 1), dtype=np.float32) for i in range(len(probabilities))
    ]


async def _aiter(blocks: Iterable[AudioArray]) -> AsyncIterator[AudioArray]:
    for block in blocks:
        yield block


async def run_detector(
    detector: TurnDetector, probabilities: Sequence[float]
) -> tuple[list[TurnEvent], list[AudioArray]]:
    """Pasa un bloque por probabilidad y devuelve los eventos producidos."""
    blocks = make_blocks(probabilities)
    events = [event async for event in detector.events(_aiter(blocks))]
    return events, blocks


# ---------------------------------------------------------------------------
# Turno normal
# ---------------------------------------------------------------------------


async def test_emite_speech_started_en_el_primer_bloque_con_voz() -> None:
    probabilities = [0.0, 0.9, 0.9, 0.9]
    detector = TurnDetector(make_settings(), FakeVad(probabilities))

    events, _ = await run_detector(detector, probabilities)

    assert isinstance(events[0], SpeechStarted)
    assert events[0].at > 0.0
    # El flujo se acaba mientras hay voz: el turno se cierra al vaciarse.
    assert isinstance(events[1], Utterance)


async def test_cierra_el_turno_tras_el_silencio_final() -> None:
    # 4 bloques de voz y luego 3 de silencio (96 ms = end_silence_ms).
    probabilities = [0.0, 0.9, 0.9, 0.9, 0.9, 0.0, 0.0, 0.0, 0.0, 0.0]
    detector = TurnDetector(make_settings(), FakeVad(probabilities))

    events, _ = await run_detector(detector, probabilities)

    assert [type(e) for e in events] == [SpeechStarted, Utterance]
    utterance = events[1]
    assert isinstance(utterance, Utterance)
    # 1 bloque de pre-roll + 4 de voz + 3 de silencio de cierre.
    assert len(utterance.audio) == 8 * BLOCK_SAMPLES
    assert utterance.sample_rate == INPUT_SAMPLE_RATE
    assert utterance.ended_at >= utterance.started_at > 0.0
    assert utterance.duration == pytest.approx(8 * BLOCK_MS / 1000)


async def test_pre_roll_conserva_solo_el_audio_reciente() -> None:
    # 5 bloques de silencio antes de la voz: solo caben 2 (pre_roll_ms = 64).
    probabilities = [0.0] * 5 + [0.9] * 3 + [0.0] * 3
    detector = TurnDetector(make_settings(), FakeVad(probabilities))

    events, blocks = await run_detector(detector, probabilities)

    utterance = events[1]
    assert isinstance(utterance, Utterance)
    # 2 de pre-roll + 3 de voz + 3 de silencio.
    assert len(utterance.audio) == 8 * BLOCK_SAMPLES
    # El pre-roll son los dos últimos bloques silenciosos (índices 3 y 4).
    assert utterance.audio[0] == blocks[3][0]
    assert utterance.audio[BLOCK_SAMPLES] == blocks[4][0]
    assert utterance.audio[2 * BLOCK_SAMPLES] == blocks[5][0]


async def test_sin_voz_no_hay_eventos() -> None:
    probabilities = [0.0] * 10
    detector = TurnDetector(make_settings(), FakeVad(probabilities))

    events, _ = await run_detector(detector, probabilities)

    assert events == []


# ---------------------------------------------------------------------------
# Habla demasiado corta
# ---------------------------------------------------------------------------


async def test_descarta_habla_demasiado_corta() -> None:
    # Un solo bloque de voz (32 ms) frente a min_speech_ms = 64.
    probabilities = [0.9] + [0.0] * 4
    detector = TurnDetector(make_settings(), FakeVad(probabilities))

    events, _ = await run_detector(detector, probabilities)

    assert [type(e) for e in events] == [SpeechStarted, SpeechDiscarded]
    discarded = events[1]
    assert isinstance(discarded, SpeechDiscarded)
    assert discarded.duration == pytest.approx(BLOCK_MS / 1000)


async def test_tras_descartar_puede_detectar_un_turno_nuevo() -> None:
    probabilities = [0.9, 0.0, 0.0, 0.0] + [0.9] * 3 + [0.0] * 3
    detector = TurnDetector(make_settings(), FakeVad(probabilities))

    events, _ = await run_detector(detector, probabilities)

    assert [type(e) for e in events] == [SpeechStarted, SpeechDiscarded, SpeechStarted, Utterance]


# ---------------------------------------------------------------------------
# Corte por duración máxima
# ---------------------------------------------------------------------------


async def test_max_utterance_fuerza_el_cierre() -> None:
    settings = make_settings(max_utterance_s=BLOCK_MS * 4 / 1000)  # 4 bloques
    probabilities = [0.9] * 10
    detector = TurnDetector(settings, FakeVad(probabilities))

    events, _ = await run_detector(detector, probabilities)

    kinds = [type(e) for e in events]
    assert kinds[:2] == [SpeechStarted, Utterance]
    first = events[1]
    assert isinstance(first, Utterance)
    # El máximo cuenta las muestras del turno, sin el pre-roll (aquí no hay).
    assert len(first.audio) == 4 * BLOCK_SAMPLES
    # El audio que sigue abre otro turno en vez de perderse.
    assert kinds.count(SpeechStarted) >= 2


# ---------------------------------------------------------------------------
# Barge-in (Sonia hablando)
# ---------------------------------------------------------------------------


async def test_mientras_habla_usa_el_umbral_alto() -> None:
    # 0.6 supera vad_threshold (0.5) pero no vad_threshold_while_speaking (0.8).
    probabilities = [0.6] * 6
    detector = TurnDetector(make_settings(), FakeVad(probabilities))
    detector.set_speaking(True)

    assert detector.threshold == pytest.approx(0.8)
    events, _ = await run_detector(detector, probabilities)
    assert events == []

    # Con el umbral normal, ese mismo audio sí abre turno.
    detector_escuchando = TurnDetector(make_settings(), FakeVad(probabilities))
    events, _ = await run_detector(detector_escuchando, probabilities)
    assert isinstance(events[0], SpeechStarted)


async def test_mientras_habla_exige_el_minimo_de_barge_in() -> None:
    settings = make_settings()
    # 3 bloques de voz (96 ms): bastan para min_speech_ms pero no para
    # barge_in_min_speech_ms (128 ms).
    probabilities = [0.9] * 3 + [0.0] * 4
    detector = TurnDetector(settings, FakeVad(probabilities))
    detector.set_speaking(True)

    events, _ = await run_detector(detector, probabilities)
    assert [type(e) for e in events] == [SpeechStarted, SpeechDiscarded]

    # Escuchando (sin hablar), esos mismos 3 bloques sí forman un turno.
    detector_escuchando = TurnDetector(settings, FakeVad(probabilities))
    events, _ = await run_detector(detector_escuchando, probabilities)
    assert [type(e) for e in events] == [SpeechStarted, Utterance]


def make_leveled_blocks(levels: Sequence[float]) -> list[AudioArray]:
    """Un bloque por nivel, con ese valor RMS (señal constante)."""
    return [np.full(BLOCK_SAMPLES, float(level), dtype=np.float32) for level in levels]


async def run_leveled(
    detector: TurnDetector, probabilities: Sequence[float], levels: Sequence[float]
) -> list[TurnEvent]:
    blocks = make_leveled_blocks(levels)
    assert len(blocks) == len(probabilities)
    return [event async for event in detector.events(_aiter(blocks))]


async def test_barge_in_con_voz_por_encima_del_eco_se_confirma() -> None:
    # Sonia suena y el micrófono la oye a nivel 0.1: el VAD lo toma por voz y
    # abre turno con el eco. Luego el visitante habla a 0.5 (x5) durante 6
    # bloques.
    probabilities = [0.9] * 14 + [0.0] * 4
    levels = [0.1] * 8 + [0.5] * 6 + [0.0] * 4
    detector = TurnDetector(make_settings(), FakeVad(probabilities))
    detector.set_speaking(True)

    events = await run_leveled(detector, probabilities, levels)

    assert [type(e) for e in events] == [SpeechStarted, BargeIn, Utterance]
    barge = events[1]
    assert isinstance(barge, BargeIn)
    assert barge.level > barge.echo_level * 2.5
    # El audio entregado empieza en la voz del visitante, no en el eco.
    utterance = events[2]
    assert isinstance(utterance, Utterance)
    assert float(utterance.audio.max()) == pytest.approx(0.5)
    leading_echo = int(np.argmax(utterance.audio >= 0.5))
    assert leading_echo <= BLOCK_SAMPLES * 2, "solo queda un pre-roll corto de eco"


async def test_solo_eco_se_descarta_al_cerrar() -> None:
    # Voz sostenida al mismo nivel que el eco: es Sonia oyéndose.
    probabilities = [0.9] * 12 + [0.0] * 4
    levels = [0.1] * 12 + [0.0] * 4
    detector = TurnDetector(make_settings(), FakeVad(probabilities))
    detector.set_speaking(True)

    events = await run_leveled(detector, probabilities, levels)

    assert [type(e) for e in events] == [SpeechStarted, SpeechDiscarded]


async def test_sin_calentamiento_no_hay_barge_in() -> None:
    probabilities = [0.9] * 6 + [0.0] * 4
    levels = [0.5] * 6 + [0.0] * 4
    settings = make_settings(barge_in_warmup_ms=320)  # 10 bloques de eco antes
    detector = TurnDetector(settings, FakeVad(probabilities))
    detector.set_speaking(True)

    events = await run_leveled(detector, probabilities, levels)

    assert [type(e) for e in events] == [SpeechStarted, SpeechDiscarded]


async def test_si_sonia_calla_el_turno_de_eco_se_olvida() -> None:
    probabilities = [0.9] * 3
    detector = TurnDetector(make_settings(), FakeVad(probabilities))
    detector.set_speaking(True)
    events: list[TurnEvent] = []
    for block in make_leveled_blocks([0.1] * 3):
        events.extend(detector.feed(block))
    assert [type(e) for e in events] == [SpeechStarted]

    detector.set_speaking(False)
    # El turno abierto era eco: se descarta sin evento y el siguiente bloque
    # con voz abre un turno nuevo.
    events = detector.feed(make_leveled_blocks([0.3])[0])
    assert [type(e) for e in events] == [SpeechStarted]


async def test_nivel_minimo_absoluto_bloquea_el_barge_in() -> None:
    probabilities = [0.9] * 10 + [0.0] * 4
    levels = [0.02] * 4 + [0.2] * 6 + [0.0] * 4
    settings = make_settings(barge_in_min_rms=0.3)
    detector = TurnDetector(settings, FakeVad(probabilities))
    detector.set_speaking(True)

    events = await run_leveled(detector, probabilities, levels)

    assert [type(e) for e in events] == [SpeechStarted, SpeechDiscarded]


async def test_turno_por_debajo_del_nivel_minimo_se_descarta_como_fondo() -> None:
    probabilities = [0.9] * 10 + [0.0] * 4
    levels = [0.02] * 10 + [0.0] * 4
    settings = make_settings(min_turn_rms=0.05)
    detector = TurnDetector(settings, FakeVad(probabilities))

    events = await run_leveled(detector, probabilities, levels)

    assert [type(e) for e in events] == [SpeechStarted, SpeechDiscarded]


async def test_turno_con_nivel_suficiente_lleva_su_nivel_medio() -> None:
    probabilities = [0.9] * 10 + [0.0] * 4
    levels = [0.1] * 5 + [0.2] * 5 + [0.0] * 4
    settings = make_settings(min_turn_rms=0.05)
    detector = TurnDetector(settings, FakeVad(probabilities))

    events = await run_leveled(detector, probabilities, levels)

    assert [type(e) for e in events] == [SpeechStarted, Utterance]
    utterance = events[-1]
    assert isinstance(utterance, Utterance)
    assert utterance.level == pytest.approx(0.15, abs=1e-3)


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------


def test_resample_to_16k_es_identidad_a_16k() -> None:
    audio = np.linspace(-1.0, 1.0, 100, dtype=np.float32)
    salida = resample_to_16k(audio, INPUT_SAMPLE_RATE)
    assert salida.dtype == np.float32
    np.testing.assert_array_equal(salida, audio)


def test_resample_to_16k_ajusta_la_longitud_y_conserva_la_forma() -> None:
    sample_rate = 48_000
    t = np.linspace(0.0, 1.0, sample_rate, endpoint=False, dtype=np.float32)
    audio = np.sin(2 * np.pi * 220 * t).astype(np.float32)

    salida = resample_to_16k(audio, sample_rate)

    assert salida.dtype == np.float32
    assert len(salida) == INPUT_SAMPLE_RATE
    # Una senoide bien remuestreada conserva su energía aproximada.
    assert float(np.sqrt(np.mean(salida**2))) == pytest.approx(
        float(np.sqrt(np.mean(audio**2))), abs=0.02
    )


def test_resample_to_16k_con_audio_vacio() -> None:
    salida = resample_to_16k(np.zeros(0, dtype=np.float32), 44_100)
    assert len(salida) == 0


# ---------------------------------------------------------------------------
# Importaciones perezosas
# ---------------------------------------------------------------------------


def test_los_modulos_se_importan_sin_dependencias_pesadas() -> None:
    import sonia.audio
    import sonia.audio.capture as capture

    assert hasattr(sonia.audio, "MicCapture")
    assert callable(capture.list_input_devices)


# ---------------------------------------------------------------------------
# Captura de micrófono (con un sounddevice falso: nunca se abre hardware)
# ---------------------------------------------------------------------------


class _FakeStream:
    """Stream de sounddevice falso: guarda el callback y anota su ciclo de vida."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs: dict[str, Any] = kwargs
        self.callback: Callable[..., None] = kwargs["callback"]
        self.started = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def close(self) -> None:
        self.closed = True


class _FakeSounddevice:
    """Sustituto de `sounddevice` con dos dispositivos de entrada."""

    DEVICES: list[dict[str, Any]] = [
        {
            "name": "MacBook Pro Microphone",
            "index": 0,
            "max_input_channels": 1,
            "default_samplerate": 48_000.0,
        },
        {"name": "Altavoces", "index": 1, "max_input_channels": 0, "default_samplerate": 48_000.0},
        {
            "name": "Yeti Nano USB",
            "index": 2,
            "max_input_channels": 2,
            "default_samplerate": 44_100.0,
        },
    ]

    class default:  # noqa: N801 - imita la API de sounddevice
        device = [0, 1]

    def __init__(self) -> None:
        self.streams: list[_FakeStream] = []

    def query_devices(self) -> list[dict[str, Any]]:
        return list(self.DEVICES)

    def InputStream(self, **kwargs: Any) -> _FakeStream:  # noqa: N802 - API de sounddevice
        stream = _FakeStream(**kwargs)
        self.streams.append(stream)
        return stream


@pytest.fixture
def fake_sd(monkeypatch: pytest.MonkeyPatch) -> _FakeSounddevice:
    fake = _FakeSounddevice()
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    return fake


def test_list_input_devices_solo_devuelve_entradas(fake_sd: _FakeSounddevice) -> None:
    devices = list_input_devices()

    assert [d["index"] for d in devices] == [0, 2]
    assert devices[0]["default"] is True
    assert devices[1]["name"] == "Yeti Nano USB"


def test_resolve_input_device_acepta_indice_nombre_y_vacio(fake_sd: _FakeSounddevice) -> None:
    assert resolve_input_device("") is None
    assert resolve_input_device("  ") is None
    assert resolve_input_device("3") == 3
    assert resolve_input_device("yeti") == 2
    assert resolve_input_device("USB") == 2
    with pytest.raises(ValueError):
        resolve_input_device("micrófono inexistente")


async def test_mic_capture_entrega_los_bloques_del_callback(fake_sd: _FakeSounddevice) -> None:
    settings = make_settings(input_device="yeti")

    async with MicCapture(settings) as mic:
        stream = fake_sd.streams[0]
        assert stream.started
        assert stream.kwargs["samplerate"] == INPUT_SAMPLE_RATE
        assert stream.kwargs["blocksize"] == BLOCK_SAMPLES
        assert stream.kwargs["channels"] == 1
        assert stream.kwargs["dtype"] == "float32"
        assert stream.kwargs["device"] == 2

        # El callback llega desde el hilo de audio con datos (frames, canales).
        for value in (1.0, 2.0):
            stream.callback(
                np.full((BLOCK_SAMPLES, 1), value, dtype=np.float32), BLOCK_SAMPLES, None, None
            )

        received: list[AudioArray] = []
        async for block in mic.blocks():
            received.append(block)
            if len(received) == 2:
                break

    assert [float(b[0]) for b in received] == [1.0, 2.0]
    assert all(b.shape == (BLOCK_SAMPLES,) for b in received)
    assert stream.closed


async def test_mic_capture_descarta_los_bloques_mas_viejos(fake_sd: _FakeSounddevice) -> None:
    async with MicCapture(make_settings()) as mic:
        stream = fake_sd.streams[0]
        total = QUEUE_MAXSIZE + 5
        for value in range(total):
            stream.callback(
                np.full((BLOCK_SAMPLES, 1), float(value), dtype=np.float32),
                BLOCK_SAMPLES,
                None,
                None,
            )
        # Los callbacks encolan con call_soon_threadsafe: hay que ceder el bucle.
        await asyncio.sleep(0)

        assert mic.dropped_blocks == 5
        first = await anext(mic.blocks())

    # Se conservaron los últimos bloques, no los primeros.
    assert float(first[0]) == 5.0


async def test_mic_capture_termina_el_iterador_al_cerrar(fake_sd: _FakeSounddevice) -> None:
    mic = MicCapture(make_settings())
    async with mic:
        blocks = mic.blocks()
        task = asyncio.create_task(_drain(blocks))
        await asyncio.sleep(0)
    await asyncio.wait_for(task, timeout=1.0)


async def _drain(blocks: AsyncIterator[AudioArray]) -> list[AudioArray]:
    return [block async for block in blocks]


async def test_mic_capture_sin_context_manager_falla() -> None:
    mic = MicCapture(make_settings())
    with pytest.raises(RuntimeError):
        await anext(mic.blocks())


async def test_mic_capture_avisa_si_deja_de_llegar_audio(fake_sd: _FakeSounddevice) -> None:
    """PortAudio deja de llamar al callback: sin esto, `blocks()` no vuelve nunca.

    Es lo que pasa cuando se desconecta el micro USB o cambia el dispositivo por
    defecto: no llega ninguna excepción y Sonia se quedaría sorda en silencio.
    """
    async with MicCapture(make_settings(), stall_timeout=0.05) as mic:
        stream = fake_sd.streams[0]
        stream.callback(np.zeros((BLOCK_SAMPLES, 1), dtype=np.float32), BLOCK_SAMPLES, None, None)

        blocks = mic.blocks()
        assert (await anext(blocks)).shape == (BLOCK_SAMPLES,)
        with pytest.raises(MicStalled):
            await anext(blocks)


async def test_mic_capture_el_cierre_no_se_confunde_con_un_cuelgue(
    fake_sd: _FakeSounddevice,
) -> None:
    mic = MicCapture(make_settings(), stall_timeout=0.05)
    async with mic:
        task = asyncio.create_task(_drain(mic.blocks()))
        await asyncio.sleep(0)
    assert await asyncio.wait_for(task, timeout=1.0) == []
