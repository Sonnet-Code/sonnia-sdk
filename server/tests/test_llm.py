"""Pruebas de la capa del modelo de lenguaje.

Nunca se llama a una API real: todo pasa por ``httpx.MockTransport`` con SSE
simulado.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from sonia.config import LLMSettings
from sonia.llm.client import LLMClient, LLMError
from sonia.llm.messages import system, user_text, user_with_image
from sonia.types import Frame, TextDelta, TurnDone

# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------


def make_settings(**overrides: Any) -> LLMSettings:
    """Configuración fija: los tests no deben depender del `.env` del equipo."""
    base: dict[str, Any] = {
        "base_url": "http://llm.test/v1",
        "model": "modelo-de-prueba",
        "api_key": "clave-de-prueba",
        "reasoning_effort": "",
        "temperature": 0.5,
        "max_tokens": 128,
        "max_tokens_param": "max_tokens",
        "request_timeout": 5.0,
    }
    base.update(overrides)
    return LLMSettings(**base)


def sse(*payloads: dict[str, Any] | str) -> bytes:
    """Serializa payloads como un stream SSE, con ruido realista de por medio."""
    lines: list[str] = [": ping\n\n"]  # comentario que debe ignorarse
    for payload in payloads:
        data = payload if isinstance(payload, str) else json.dumps(payload)
        lines.append(f"data: {data}\n\n")
    return "".join(lines).encode("utf-8")


def chunk(delta: dict[str, Any], finish_reason: str | None = None) -> dict[str, Any]:
    """Un chunk de chat completions con un único choice."""
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion.chunk",
        "model": "modelo-de-prueba",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


def streaming_transport(
    body: bytes,
    *,
    captured: list[dict[str, Any]] | None = None,
    chunk_size: int = 7,
) -> httpx.MockTransport:
    """Transporte que devuelve ``body`` troceado, como haría un servidor real."""

    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append(json.loads(request.content))

        async def stream() -> AsyncIterator[bytes]:
            for start in range(0, len(body), chunk_size):
                yield body[start : start + chunk_size]

        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=stream())

    return httpx.MockTransport(handler)


async def collect(client: LLMClient, messages: list[dict[str, Any]]) -> list[Any]:
    return [event async for event in client.stream(messages)]


def make_frame(data: bytes = b"jpeg-falso") -> Frame:
    return Frame(data=data, mime="image/jpeg", width=64, height=48)


# ---------------------------------------------------------------------------
# LLMClient: texto
# ---------------------------------------------------------------------------


async def test_texto_en_varios_chunks() -> None:
    body = sse(
        chunk({"role": "assistant", "content": ""}),
        chunk({"content": "Hola"}),
        chunk({"content": ", ¿cómo "}),
        chunk({"content": "estás?"}),
        chunk({}, finish_reason="stop"),
        "[DONE]",
    )
    client = LLMClient(make_settings(), transport=streaming_transport(body))
    events = await collect(client, messages=[user_text("hola")])
    await client.aclose()

    deltas = [e for e in events if isinstance(e, TextDelta)]
    assert [d.text for d in deltas] == ["Hola", ", ¿cómo ", "estás?"]
    done = events[-1]
    assert isinstance(done, TurnDone)
    assert done.content == "Hola, ¿cómo estás?"
    assert done.finish_reason == "stop"
    assert done.reasoning_content is None


async def test_reasoning_no_se_emite_pero_se_conserva() -> None:
    body = sse(
        chunk({"reasoning_content": "pienso "}),
        chunk({"reasoning_content": "un poco"}),
        chunk({"content": "Listo."}),
        chunk({}, finish_reason="stop"),
        "[DONE]",
    )
    client = LLMClient(make_settings(), transport=streaming_transport(body))
    events = await collect(client, messages=[user_text("hola")])
    await client.aclose()

    assert [e.text for e in events if isinstance(e, TextDelta)] == ["Listo."]
    done = events[-1]
    assert isinstance(done, TurnDone)
    assert done.reasoning_content == "pienso un poco"
    assert done.content == "Listo."


async def test_lineas_raras_y_chunk_de_usage_se_toleran() -> None:
    body = (
        b": keep-alive\n\n"
        b"\n"
        b"event: message\n"
        b"data: " + json.dumps(chunk({"content": "ok"})).encode() + b"\n\n"
        b"data: no-es-json\n\n"
        b"data: " + json.dumps({"choices": [], "usage": {"total_tokens": 3}}).encode() + b"\n\n"
        b"data: [DONE]\n\n"
    )
    client = LLMClient(make_settings(), transport=streaming_transport(body))
    events = await collect(client, messages=[user_text("hola")])
    await client.aclose()

    assert [e.text for e in events if isinstance(e, TextDelta)] == ["ok"]
    assert isinstance(events[-1], TurnDone)


# ---------------------------------------------------------------------------
# LLMClient: tool calls
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# LLMClient: cuerpo de la petición
# ---------------------------------------------------------------------------


async def test_body_sin_temperature_cuando_es_none() -> None:
    captured: list[dict[str, Any]] = []
    body = sse(chunk({"content": "ok"}, finish_reason="stop"), "[DONE]")
    client = LLMClient(
        make_settings(temperature=None), transport=streaming_transport(body, captured=captured)
    )
    await collect(client, messages=[user_text("hola")])
    await client.aclose()
    assert "temperature" not in captured[0]


async def test_body_sin_reasoning() -> None:
    captured: list[dict[str, Any]] = []
    body = sse(chunk({"content": "ok"}, finish_reason="stop"), "[DONE]")
    client = LLMClient(make_settings(), transport=streaming_transport(body, captured=captured))
    await collect(client, messages=[user_text("hola")])
    await client.aclose()

    sent = captured[0]
    assert sent["model"] == "modelo-de-prueba"
    assert sent["stream"] is True
    assert sent["temperature"] == 0.5
    assert sent["max_tokens"] == 128
    assert "tools" not in sent
    assert "reasoning_effort" not in sent
    assert "stream_options" not in sent


async def test_max_completion_tokens_para_la_api_de_openai() -> None:
    captured: list[dict[str, Any]] = []
    body = sse(chunk({"content": "ok"}, finish_reason="stop"), "[DONE]")
    client = LLMClient(
        make_settings(max_tokens_param="max_completion_tokens"),
        transport=streaming_transport(body, captured=captured),
    )
    await collect(client, messages=[user_text("hola")])
    await client.aclose()
    assert captured[0]["max_completion_tokens"] == 128
    assert "max_tokens" not in captured[0]


async def test_url_y_cabecera_de_autorizacion() -> None:
    seen: list[httpx.Request] = []
    body = sse(chunk({"content": "ok"}, finish_reason="stop"), "[DONE]")

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=body)

    client = LLMClient(
        make_settings(base_url="http://llm.test/v1/"), transport=httpx.MockTransport(handler)
    )
    await collect(client, messages=[user_text("hola")])
    await client.aclose()

    assert str(seen[0].url) == "http://llm.test/v1/chat/completions"
    assert seen[0].headers["authorization"] == "Bearer clave-de-prueba"


# ---------------------------------------------------------------------------
# LLMClient: errores y reintentos
# ---------------------------------------------------------------------------


async def test_error_401_lanza_llm_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "clave inválida"}})

    client = LLMClient(make_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(LLMError) as info:
        await collect(client, messages=[user_text("hola")])
    await client.aclose()

    assert info.value.status_code == 401
    assert "clave inválida" in info.value.body


async def test_reintento_tras_fallo_de_red() -> None:
    body = sse(chunk({"content": "segundo intento"}, finish_reason="stop"), "[DONE]")
    intentos = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal intentos
        intentos += 1
        if intentos == 1:
            raise httpx.ConnectError("conexión rechazada", request=request)
        return httpx.Response(200, content=body)

    client = LLMClient(make_settings(), transport=httpx.MockTransport(handler))
    events = await collect(client, messages=[user_text("hola")])
    await client.aclose()

    assert intentos == 2
    assert [e.text for e in events if isinstance(e, TextDelta)] == ["segundo intento"]


async def test_un_error_dentro_del_stream_lanza_llm_error() -> None:
    """vLLM y llama.cpp mandan el error como un chunk más, con HTTP 200.

    Descartarlo (no trae ``choices``) dejaba a Sonia muda y sin mensaje de
    error: el turno terminaba con texto vacío y nadie se enteraba.
    """
    body = sse(
        chunk({"role": "assistant", "content": ""}),
        {"error": {"message": "context overflow", "code": 500}},
    )
    client = LLMClient(make_settings(), transport=streaming_transport(body))
    with pytest.raises(LLMError, match="context overflow"):
        await collect(client, messages=[user_text("hola")])
    await client.aclose()


async def test_un_timeout_no_se_reintenta() -> None:
    """Reintentar un timeout duplicaría el silencio delante del visitante."""
    intentos = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal intentos
        intentos += 1
        raise httpx.ReadTimeout("el modelo no dice nada", request=request)

    client = LLMClient(make_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(LLMError, match="LLM_REQUEST_TIMEOUT"):
        await collect(client, messages=[user_text("hola")])
    await client.aclose()

    assert intentos == 1


def test_el_timeout_de_lectura_es_el_configurado() -> None:
    """``LLM_REQUEST_TIMEOUT`` tiene que poder bajar de los dos minutos."""
    client = LLMClient(make_settings(request_timeout=15.0))
    assert client._client.timeout.read == 15.0
    assert client._client.timeout.connect == 10.0


async def test_dos_fallos_de_red_lanzan_llm_error() -> None:
    intentos = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal intentos
        intentos += 1
        raise httpx.ConnectError("conexión rechazada", request=request)

    client = LLMClient(make_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(LLMError):
        await collect(client, messages=[user_text("hola")])
    await client.aclose()

    assert intentos == 2


# ---------------------------------------------------------------------------
# LLMClient: ping
# ---------------------------------------------------------------------------


async def test_ping_devuelve_modelo_y_texto() -> None:
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "modelo-real",
                "choices": [{"message": {"role": "assistant", "content": "pong"}}],
            },
        )

    client = LLMClient(make_settings(), transport=httpx.MockTransport(handler))
    result = await client.ping()
    await client.aclose()

    assert result == "modelo-real: pong"
    assert captured[0]["stream"] is False
    assert captured[0]["max_tokens"] == 5


async def test_ping_con_error_lanza_llm_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="no such model")

    client = LLMClient(make_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(LLMError):
        await client.ping()
    await client.aclose()


# ---------------------------------------------------------------------------
# messages
# ---------------------------------------------------------------------------


def test_mensajes_de_texto_y_con_imagen() -> None:
    assert system("eres sonia") == {"role": "system", "content": "eres sonia"}
    assert user_text("hola") == {"role": "user", "content": "hola"}
    message = user_with_image("¿qué ves?", make_frame())
    assert message["role"] == "user"
    parts = message["content"]
    assert parts[0] == {"type": "text", "text": "¿qué ves?"}
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert parts[1]["image_url"]["detail"] == "low"
    assert user_with_image("", make_frame())["content"][0]["type"] == "image_url"


# ---------------------------------------------------------------------------
# Cancelación
# ---------------------------------------------------------------------------


async def test_cancelar_el_turno_cierra_la_respuesta() -> None:
    """Al cancelar la tarea, el ``async with`` cierra el stream del servidor."""
    cerrado = asyncio.Event()
    primer_delta = asyncio.Event()

    def handler(request: httpx.Request) -> httpx.Response:
        async def stream() -> AsyncIterator[bytes]:
            try:
                yield b"data: " + json.dumps(chunk({"content": "Hola"})).encode() + b"\n\n"
                await asyncio.Event().wait()  # el servidor se queda pensando
            finally:
                cerrado.set()

        return httpx.Response(200, content=stream())

    client = LLMClient(make_settings(), transport=httpx.MockTransport(handler))

    async def consumir() -> None:
        async for event in client.stream([user_text("hola")]):
            if isinstance(event, TextDelta):
                primer_delta.set()

    tarea = asyncio.create_task(consumir())
    await asyncio.wait_for(primer_delta.wait(), timeout=2)
    tarea.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tarea
    await asyncio.wait_for(cerrado.wait(), timeout=2)
    await client.aclose()
