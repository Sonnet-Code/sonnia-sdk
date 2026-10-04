"""Pruebas del protocolo WebSocket y del hub.

No hacen falta ni Unity ni red externa: el hub se levanta en un puerto libre de
localhost y se conecta un cliente ``websockets`` de prueba.
"""

from __future__ import annotations

import asyncio
import base64
import json
import struct
import time
from collections.abc import Callable
from typing import Any

import pytest

from sonia.config import WSSettings
from sonia.types import AudioChunk
from sonia.ws import protocol as p
from sonia.ws.hub import Hub

# ---------------------------------------------------------------------------
# Frames binarios
# ---------------------------------------------------------------------------


def test_encode_decode_round_trip() -> None:
    pcm = b"\x01\x02\x03\x04" * 10
    frame = p.encode_audio_frame(7, pcm, is_last=False)

    assert frame[:4] == p.MAGIC
    assert len(frame) == p.HEADER_SIZE + len(pcm)

    utterance_id, is_last, payload = p.decode_audio_frame(frame)
    assert utterance_id == 7
    assert is_last is False
    assert payload == pcm


def test_encode_marks_last_chunk() -> None:
    frame = p.encode_audio_frame(3, b"\x00\x00", is_last=True)
    _, _, flags = struct.unpack(p.HEADER_FORMAT, frame[: p.HEADER_SIZE])
    assert flags & p.FLAG_LAST

    utterance_id, is_last, payload = p.decode_audio_frame(frame)
    assert (utterance_id, is_last, payload) == (3, True, b"\x00\x00")


def test_encode_accepts_empty_pcm() -> None:
    utterance_id, is_last, payload = p.decode_audio_frame(p.encode_audio_frame(1, b"", True))
    assert (utterance_id, is_last, payload) == (1, True, b"")


def test_decode_rejects_bad_magic() -> None:
    bad = b"NOPE" + struct.pack("<II", 1, 0) + b"\x00\x00"
    with pytest.raises(ValueError, match="marca"):
        p.decode_audio_frame(bad)


def test_decode_rejects_short_frame() -> None:
    with pytest.raises(ValueError, match="corto"):
        p.decode_audio_frame(b"SNIA\x00\x00")


def test_header_layout_matches_docs() -> None:
    # 12 bytes little endian: magic + uint32 + uint32.
    assert p.HEADER_SIZE == 12
    assert p.MAGIC == b"SNIA"
    assert p.FLAG_LAST == 1


# ---------------------------------------------------------------------------
# Forma exacta de los mensajes JSON (docs/protocolo.md)
# ---------------------------------------------------------------------------


def test_msg_hello() -> None:
    assert p.msg_hello(24_000) == {
        "type": "hello",
        "version": 1,
        "sample_rate": 24_000,
        "channels": 1,
        "format": "pcm_s16le",
    }


def test_msg_state() -> None:
    assert p.msg_state("idle") == {"type": "state", "state": "idle"}


def test_msg_transcript() -> None:
    assert p.msg_transcript("user", "hola sonia", True) == {
        "type": "transcript",
        "role": "user",
        "text": "hola sonia",
        "final": True,
    }


def test_msg_speech_start() -> None:
    assert p.msg_speech_start(7, "Hola, ¿cómo estás?") == {
        "type": "speech_start",
        "utterance_id": 7,
        "text": "Hola, ¿cómo estás?",
    }


def test_msg_speech_end_and_stop_speaking() -> None:
    assert p.msg_speech_end(7) == {"type": "speech_end", "utterance_id": 7}
    assert p.msg_stop_speaking("interrupted") == {
        "type": "stop_speaking",
        "reason": "interrupted",
    }


def test_msg_show_and_hide_image() -> None:
    data = b"\x89PNG\r\n"
    msg = p.msg_show_image("logo-sonnet", "gallery", "image/png", data, "Sonnet Code")
    assert msg == {
        "type": "show_image",
        "image_id": "logo-sonnet",
        "source": "gallery",
        "mime": "image/png",
        "data_base64": base64.b64encode(data).decode("ascii"),
        "caption": "Sonnet Code",
    }
    assert p.msg_hide_image() == {"type": "hide_image"}


def test_msg_error_and_request_frame() -> None:
    assert p.msg_error("se cayó el modelo") == {
        "type": "error",
        "message": "se cayó el modelo",
    }
    assert p.msg_request_frame() == {"type": "request_frame"}


def test_dumps_keeps_accents() -> None:
    text = p.dumps(p.msg_speech_start(1, "¿cómo estás?"))
    assert "¿cómo estás?" in text
    assert json.loads(text)["utterance_id"] == 1


# ---------------------------------------------------------------------------
# Parseo de mensajes entrantes
# ---------------------------------------------------------------------------


def test_parse_client_message_ok() -> None:
    assert p.parse_client_message('{"type": "interrupt"}') == {"type": "interrupt"}
    assert p.parse_client_message(b'{"type": "playback_done", "utterance_id": 2}') == {
        "type": "playback_done",
        "utterance_id": 2,
    }


@pytest.mark.parametrize(
    "raw",
    ["no es json", "[1, 2, 3]", '"solo texto"', "{}", '{"type": 3}', "null"],
)
def test_parse_client_message_rejects(raw: str) -> None:
    assert p.parse_client_message(raw) is None


# ---------------------------------------------------------------------------
# Hub: integración real con un cliente websockets
# ---------------------------------------------------------------------------


async def _wait_for(condition: Callable[[], object], limite: float = 2.0) -> None:
    """Espera activa cortita, para no depender de los tiempos del bucle."""
    async with asyncio.timeout(limite):
        while not condition():  # noqa: ASYNC110 - sondeo deliberado en tests
            await asyncio.sleep(0.01)


async def test_hub_end_to_end() -> None:
    from websockets.asyncio.client import connect

    hub = Hub(WSSettings(host="127.0.0.1", port=0), sample_rate=24_000)
    interrupts: list[dict[str, Any]] = []
    texts: list[dict[str, Any]] = []
    hub.on("interrupt", lambda msg: interrupts.append(msg))
    hub.on("interrupt", lambda msg: interrupts.append({"segundo": True}))

    async def on_text(msg: dict[str, Any]) -> None:
        texts.append(msg)

    hub.on("text_input", on_text)

    async with hub:
        assert hub.port != 0
        assert hub.client_count == 0

        async with connect(f"ws://127.0.0.1:{hub.port}/") as client:
            # 1) hello al conectar
            hello = json.loads(await asyncio.wait_for(client.recv(), 2.0))
            assert hello == p.msg_hello(24_000)
            assert hub.client_count == 1

            # 2) mensaje entrante despachado a los dos callbacks
            await client.send(json.dumps({"type": "interrupt"}))
            await _wait_for(lambda: len(interrupts) == 2)
            assert interrupts[0] == {"type": "interrupt"}

            # 3) un mensaje sin callback registrado no rompe nada
            await client.send(json.dumps({"type": "desconocido"}))
            await client.send("esto no es json")
            await client.send(json.dumps({"type": "text_input", "text": "¿qué tal?"}))
            await _wait_for(lambda: texts)
            assert texts[0]["text"] == "¿qué tal?"

            # 4) broadcast JSON
            await hub.broadcast_json(p.msg_state("thinking"))
            assert json.loads(await asyncio.wait_for(client.recv(), 2.0)) == {
                "type": "state",
                "state": "thinking",
            }

            # 5) broadcast binario y audio
            await hub.broadcast_bytes(p.encode_audio_frame(1, b"\x01\x02", False))
            raw = await asyncio.wait_for(client.recv(), 2.0)
            assert isinstance(raw, bytes)
            assert p.decode_audio_frame(raw) == (1, False, b"\x01\x02")

            await hub.send_audio(1, AudioChunk(pcm=b"\x03\x04", sample_rate=24_000, is_last=True))
            raw = await asyncio.wait_for(client.recv(), 2.0)
            assert isinstance(raw, bytes)
            assert p.decode_audio_frame(raw) == (1, True, b"\x03\x04")

            # 6) AvatarLink
            await hub.show_image(
                image_id="logo-sonnet",
                source="gallery",
                mime="image/png",
                data=b"\x89PNG",
                caption=None,
            )
            shown = json.loads(await asyncio.wait_for(client.recv(), 2.0))
            assert shown["type"] == "show_image"
            assert base64.b64decode(shown["data_base64"]) == b"\x89PNG"
            assert shown["caption"] is None

            await hub.hide_image()
            assert json.loads(await asyncio.wait_for(client.recv(), 2.0)) == {"type": "hide_image"}

        # 7) tras desconectar, difundir no lanza aunque no haya nadie
        await _wait_for(lambda: hub.client_count == 0)
        await hub.broadcast_json(p.msg_state("idle"))
        await hub.broadcast_bytes(p.encode_audio_frame(2, b"\x00", True))
        await hub.hide_image()

    assert hub.client_count == 0


async def test_hub_broadcast_sin_clientes_ni_servidor() -> None:
    """El orquestador puede arrancar antes que el hub y no debe enterarse."""
    hub = Hub(WSSettings(host="127.0.0.1", port=0), sample_rate=24_000)
    await hub.broadcast_json(p.msg_state("idle"))
    await hub.broadcast_bytes(b"loquesea")
    await hub.stop()  # parar sin haber arrancado es válido


async def test_hub_callback_que_lanza_no_tumba_el_hub() -> None:
    from websockets.asyncio.client import connect

    llamadas: list[str] = []

    def explota(msg: dict[str, Any]) -> None:
        llamadas.append("explota")
        raise RuntimeError("callback roto")

    async def sigue(msg: dict[str, Any]) -> None:
        llamadas.append("sigue")

    hub = Hub(WSSettings(host="127.0.0.1", port=0), sample_rate=16_000)
    hub.on("interrupt", explota)
    hub.on("interrupt", sigue)

    async with hub, connect(f"ws://127.0.0.1:{hub.port}/") as client:
        await asyncio.wait_for(client.recv(), 2.0)  # hello
        await client.send(json.dumps({"type": "interrupt"}))
        await _wait_for(lambda: "sigue" in llamadas)

        # La conexión sigue viva: recibe un broadcast posterior.
        await hub.broadcast_json(p.msg_state("listening"))
        assert json.loads(await asyncio.wait_for(client.recv(), 2.0))["state"] == "listening"

    assert llamadas == ["explota", "sigue"]


async def test_hub_acepta_un_camera_frame_grande() -> None:
    """El límite por defecto de websockets (1 MiB) corta las webcams grandes."""
    from websockets.asyncio.client import connect

    recibidos: list[dict[str, Any]] = []
    hub = Hub(WSSettings(host="127.0.0.1", port=0), sample_rate=24_000)
    hub.on("camera_frame", lambda msg: recibidos.append(msg))

    grande = base64.b64encode(b"\xff\xd8" * 1_200_000).decode("ascii")  # ~3,2 MiB
    async with hub, connect(f"ws://127.0.0.1:{hub.port}/", max_size=None) as client:
        await asyncio.wait_for(client.recv(), 2.0)  # hello
        await client.send(json.dumps({"type": "camera_frame", "data_base64": grande}))
        await _wait_for(lambda: recibidos, 5.0)
        assert recibidos[0]["data_base64"] == grande
        # La conexión sigue viva: no se cerró con 1009.
        await hub.broadcast_json(p.msg_state("idle"))
        assert json.loads(await asyncio.wait_for(client.recv(), 2.0))["state"] == "idle"


async def test_hub_un_cliente_que_no_lee_no_bloquea_la_demo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unity congelado: sus envíos no pueden colgar el bucle del orquestador."""
    from websockets.asyncio.client import connect

    import sonia.ws.hub as hub_module

    monkeypatch.setattr(hub_module, "SEND_TIMEOUT_S", 0.2)
    hub = Hub(WSSettings(host="127.0.0.1", port=0), sample_rate=24_000)

    async with hub:
        uri = f"ws://127.0.0.1:{hub.port}/"
        async with connect(uri, max_size=None, max_queue=1, close_timeout=0.2) as client:  # noqa: F841
            await _wait_for(lambda: hub.client_count == 1)
            # El cliente nunca hace recv(): su buffer de escritura se llena.
            payload = p.encode_audio_frame(1, b"\x00" * 4_000_000, False)
            inicio = time.monotonic()
            async with asyncio.timeout(20.0):
                while hub.client_count == 1:
                    await hub.broadcast_bytes(payload)
            # Se descartó al cliente en vez de quedarse esperando para siempre.
            assert hub.client_count == 0
            # Un broadcast posterior vuelve enseguida.
            antes = time.monotonic()
            await hub.broadcast_json(p.msg_stop_speaking("interrupted"))
            assert time.monotonic() - antes < 1.0
            assert time.monotonic() - inicio < 20.0


async def test_hub_varios_clientes_reciben_lo_mismo() -> None:
    from websockets.asyncio.client import connect

    hub = Hub(WSSettings(host="127.0.0.1", port=0), sample_rate=24_000)
    async with hub:
        uri = f"ws://127.0.0.1:{hub.port}/"
        async with connect(uri) as a, connect(uri) as b:
            await asyncio.wait_for(a.recv(), 2.0)
            await asyncio.wait_for(b.recv(), 2.0)
            await _wait_for(lambda: hub.client_count == 2)

            await hub.broadcast_json(p.msg_speech_end(9))
            for client in (a, b):
                assert json.loads(await asyncio.wait_for(client.recv(), 2.0)) == {
                    "type": "speech_end",
                    "utterance_id": 9,
                }
