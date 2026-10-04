"""Pruebas de la captura de micrófono.

No se abre ningún dispositivo real: ``sounddevice`` se sustituye por uno falso.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator, Callable
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
from sonia.config import AudioSettings
from sonia.types import INPUT_SAMPLE_RATE, AudioArray

BLOCK_MS = 32
BLOCK_SAMPLES = BLOCK_MS * INPUT_SAMPLE_RATE // 1000


def make_settings(**overrides: object) -> AudioSettings:
    """Configuración de audio determinista para los tests (bloques de 32 ms)."""
    defaults: dict[str, object] = {"block_ms": BLOCK_MS}
    defaults.update(overrides)
    return AudioSettings(**defaults)  # type: ignore[arg-type]


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
