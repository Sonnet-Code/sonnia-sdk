"""Pruebas de la capa del modelo de lenguaje.

Nunca se llama a una API real: todo pasa por ``httpx.MockTransport`` con SSE
simulado.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterable
from typing import Any

import httpx
import pytest

from sonia.config import LLMSettings
from sonia.llm.client import LLMClient, LLMError
from sonia.llm.conversation import Conversation
from sonia.llm.messages import (
    assistant_text,
    assistant_tool_calls,
    has_image,
    strip_images,
    tool_result,
    user_text,
    user_with_image,
)
from sonia.llm.prompt_tools import PromptToolParser, render_tools_prompt
from sonia.types import Frame, TextDelta, ToolCall, ToolCallsEvent, TurnDone

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


async def collect(client: LLMClient, **kwargs: Any) -> list[Any]:
    return [event async for event in client.stream(kwargs.pop("messages", []), **kwargs)]


TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "show_image",
            "description": "Muestra una imagen en el panel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "image_id": {"type": "string", "description": "id de la galería"},
                    "caption": {"type": "string"},
                },
                "required": ["image_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hide_image",
            "description": "Retira el panel.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


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


async def test_tool_call_con_argumentos_fragmentados() -> None:
    body = sse(
        chunk(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_abc",
                        "type": "function",
                        "function": {"name": "show_image", "arguments": ""},
                    }
                ]
            }
        ),
        chunk({"tool_calls": [{"index": 0, "function": {"arguments": '{"image_'}}]}),
        chunk({"tool_calls": [{"index": 0, "function": {"arguments": 'id": "logo'}}]}),
        chunk({"tool_calls": [{"index": 0, "function": {"arguments": '-sonnet"}'}}]}),
        chunk({}, finish_reason="tool_calls"),
        "[DONE]",
    )
    client = LLMClient(make_settings(), transport=streaming_transport(body))
    events = await collect(client, messages=[user_text("enséñame el logo")], tools=TOOLS)
    await client.aclose()

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, ToolCallsEvent)
    assert len(event.calls) == 1
    call = event.calls[0]
    assert call.id == "call_abc"
    assert call.name == "show_image"
    assert call.arguments == {"image_id": "logo-sonnet"}


async def test_dos_tool_calls_intercaladas_por_index() -> None:
    body = sse(
        chunk(
            {
                "tool_calls": [
                    {"index": 0, "id": "a", "function": {"name": "show_image", "arguments": "{"}}
                ]
            }
        ),
        chunk(
            {
                "tool_calls": [
                    {"index": 1, "id": "b", "function": {"name": "hide_image", "arguments": "{"}}
                ]
            }
        ),
        chunk({"tool_calls": [{"index": 0, "function": {"arguments": '"image_id": "x"'}}]}),
        chunk({"tool_calls": [{"index": 1, "function": {"arguments": "}"}}]}),
        chunk({"tool_calls": [{"index": 0, "function": {"arguments": "}"}}]}),
        chunk({}, finish_reason="tool_calls"),
        "[DONE]",
    )
    client = LLMClient(make_settings(), transport=streaming_transport(body))
    events = await collect(client, messages=[user_text("hola")], tools=TOOLS)
    await client.aclose()

    event = events[0]
    assert isinstance(event, ToolCallsEvent)
    assert [(c.id, c.name, c.arguments) for c in event.calls] == [
        ("a", "show_image", {"image_id": "x"}),
        ("b", "hide_image", {}),
    ]


async def test_tool_calls_sin_finish_reason_al_cerrar_el_stream() -> None:
    """Si el servidor corta sin ``finish_reason`` pero hay calls, se emiten igual."""
    body = sse(
        chunk({"content": "Voy a mirar. "}),
        chunk({"reasoning_content": "hmm"}),
        chunk(
            {
                "tool_calls": [
                    {"index": 0, "id": "c1", "function": {"name": "look", "arguments": "{}"}}
                ]
            }
        ),
        "[DONE]",
    )
    client = LLMClient(make_settings(), transport=streaming_transport(body))
    events = await collect(client, messages=[user_text("¿qué ves?")], tools=TOOLS)
    await client.aclose()

    assert isinstance(events[0], TextDelta)
    event = events[-1]
    assert isinstance(event, ToolCallsEvent)
    assert event.content == "Voy a mirar. "
    assert event.reasoning_content == "hmm"
    assert event.calls[0].arguments == {}


async def test_argumentos_json_invalido_dan_diccionario_vacio() -> None:
    body = sse(
        chunk(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "c1",
                        "function": {"name": "show_image", "arguments": "{roto"},
                    }
                ]
            }
        ),
        chunk({}, finish_reason="tool_calls"),
        "[DONE]",
    )
    client = LLMClient(make_settings(), transport=streaming_transport(body))
    events = await collect(client, messages=[user_text("hola")], tools=TOOLS)
    await client.aclose()

    event = events[0]
    assert isinstance(event, ToolCallsEvent)
    assert event.calls[0].arguments == {}


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


async def test_body_sin_tools_ni_reasoning() -> None:
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
    assert "tool_choice" not in sent
    assert "reasoning_effort" not in sent
    assert "stream_options" not in sent


async def test_body_con_tools_y_reasoning_effort() -> None:
    captured: list[dict[str, Any]] = []
    body = sse(chunk({"content": "ok"}, finish_reason="stop"), "[DONE]")
    client = LLMClient(
        make_settings(reasoning_effort="high"),
        transport=streaming_transport(body, captured=captured),
    )
    await collect(client, messages=[user_text("hola")], tools=TOOLS)
    await client.aclose()

    sent = captured[0]
    assert sent["tools"] == TOOLS
    assert sent["tool_choice"] == "auto"
    assert sent["reasoning_effort"] == "high"


async def test_tools_vacias_no_se_envian() -> None:
    captured: list[dict[str, Any]] = []
    body = sse(chunk({"content": "ok"}, finish_reason="stop"), "[DONE]")
    client = LLMClient(make_settings(), transport=streaming_transport(body, captured=captured))
    await collect(client, messages=[user_text("hola")], tools=[])
    await client.aclose()

    assert "tools" not in captured[0]
    assert "tool_choice" not in captured[0]


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


def test_user_with_image_y_strip_images() -> None:
    message = user_with_image("¿qué ves?", make_frame())
    assert message["role"] == "user"
    parts = message["content"]
    assert parts[0] == {"type": "text", "text": "¿qué ves?"}
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert parts[1]["image_url"]["detail"] == "low"
    assert has_image(message)

    plain = strip_images(message)
    assert plain == {"role": "user", "content": "¿qué ves?"}
    assert not has_image(plain)
    # No muta el original.
    assert has_image(message)


def test_strip_images_deja_igual_el_texto_plano() -> None:
    message = user_text("hola")
    assert strip_images(message) == message


def test_assistant_tool_calls_serializa_al_formato_openai() -> None:
    event = ToolCallsEvent(
        calls=[ToolCall(id="c1", name="show_image", arguments={"image_id": "logo"})],
        reasoning_content="porque sí",
        content="",
    )
    message = assistant_tool_calls(event)
    assert message["role"] == "assistant"
    assert message["content"] is None
    assert message["reasoning_content"] == "porque sí"
    call = message["tool_calls"][0]
    assert call == {
        "id": "c1",
        "type": "function",
        "function": {"name": "show_image", "arguments": '{"image_id": "logo"}'},
    }


def test_assistant_tool_calls_sin_reasoning_no_incluye_la_clave() -> None:
    event = ToolCallsEvent(
        calls=[ToolCall(id="c1", name="hide_image", arguments={})],
        content="Ya te lo quito.",
    )
    message = assistant_tool_calls(event)
    assert "reasoning_content" not in message
    assert message["content"] == "Ya te lo quito."


def test_tool_result_y_assistant_text() -> None:
    assert tool_result("c1", "look", "Captura tomada.") == {
        "role": "tool",
        "tool_call_id": "c1",
        "name": "look",
        "content": "Captura tomada.",
    }
    assert assistant_text("hola") == {"role": "assistant", "content": "hola"}


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------


def test_conversation_pone_el_system_delante() -> None:
    conversation = Conversation("eres sonia", history_turns=4)
    conversation.add(user_text("hola"))
    conversation.add(assistant_text("¿qué tal?"))

    messages = conversation.messages()
    assert messages[0] == {"role": "system", "content": "eres sonia"}
    assert [m["role"] for m in messages] == ["system", "user", "assistant"]

    conversation.set_system_prompt("eres otra")
    assert conversation.messages()[0]["content"] == "eres otra"

    conversation.reset()
    assert [m["role"] for m in conversation.messages()] == ["system"]


def test_conversation_trunca_por_turnos_de_usuario() -> None:
    conversation = Conversation("s", history_turns=2)
    for i in range(4):
        conversation.add(user_text(f"pregunta {i}"))
        conversation.add(assistant_text(f"respuesta {i}"))

    contents = [m["content"] for m in conversation.messages()[1:]]
    assert contents == ["pregunta 2", "respuesta 2", "pregunta 3", "respuesta 3"]


def test_conversation_no_separa_tool_calls_de_sus_resultados() -> None:
    conversation = Conversation("s", history_turns=1)
    conversation.add(user_text("turno viejo"))
    conversation.add(assistant_text("ya"))

    conversation.add(user_text("enséñame el logo"))
    event = ToolCallsEvent(
        calls=[ToolCall(id="c1", name="show_image", arguments={"image_id": "l"})]
    )
    conversation.add(assistant_tool_calls(event))
    conversation.add(tool_result("c1", "show_image", "hecho"))
    # La imagen que devolvió la acción entra como mensaje de usuario, pero no
    # abre un turno nuevo.
    conversation.add(user_with_image("", make_frame()))
    conversation.add(assistant_text("ahí lo tienes"))

    roles = [m["role"] for m in conversation.messages()]
    assert roles == ["system", "user", "assistant", "tool", "user", "assistant"]
    assert conversation.messages()[1]["content"] == "enséñame el logo"


def test_conversation_solo_conserva_la_imagen_del_turno_actual() -> None:
    conversation = Conversation("s", history_turns=5)
    conversation.add(user_with_image("mira esto", make_frame(b"vieja")))
    conversation.add(assistant_text("qué bonito"))
    conversation.add(user_with_image("¿y ahora?", make_frame(b"nueva")))

    messages = conversation.messages()
    assert not has_image(messages[1])
    assert messages[1]["content"] == "mira esto"
    assert has_image(messages[3])


def test_conversation_quita_la_imagen_cuando_el_turno_siguiente_es_texto() -> None:
    conversation = Conversation("s", history_turns=5)
    conversation.add(user_with_image("mira esto", make_frame()))
    conversation.add(assistant_text("qué bonito"))
    conversation.add(user_text("¿y qué es Sonnet Code?"))

    assert not any(has_image(m) for m in conversation.messages())


# ---------------------------------------------------------------------------
# prompt_tools
# ---------------------------------------------------------------------------


def test_render_tools_prompt_describe_acciones_y_formato() -> None:
    prompt = render_tools_prompt(TOOLS)
    assert "<action>" in prompt and "</action>" in prompt
    assert "show_image" in prompt
    assert "hide_image" in prompt
    assert "image_id: string, obligatorio" in prompt
    assert "caption: string, opcional" in prompt
    assert render_tools_prompt([]) == ""


def _feed_all(parser: PromptToolParser, deltas: Iterable[str]) -> tuple[str, list[Any]]:
    text: list[str] = []
    calls: list[Any] = []
    for delta in deltas:
        spoken, found = parser.feed(delta)
        text.append(spoken)
        calls.extend(found)
    text.append(parser.flush())
    return "".join(text), calls


def test_parser_bloque_partido_en_varios_deltas() -> None:
    parser = PromptToolParser()
    deltas = [
        "Ahora mismo te lo muestro. ",
        "<acti",
        'on>{"name": "show_ima',
        'ge", "arguments": {"image_id": "logo-sonnet"}}</act',
        "ion> Ya está.",
    ]
    text, calls = _feed_all(parser, deltas)

    assert text == "Ahora mismo te lo muestro.  Ya está."
    assert len(calls) == 1
    assert calls[0].id == "prompt_0"
    assert calls[0].name == "show_image"
    assert calls[0].arguments == {"image_id": "logo-sonnet"}


def test_parser_no_emite_media_etiqueta() -> None:
    parser = PromptToolParser()
    spoken, calls = parser.feed("hola <ac")
    assert spoken == "hola "
    assert calls == []
    spoken, calls = parser.feed('tion>{"name": "hide_image", "arguments": {}}</action>')
    assert spoken == ""
    assert [c.name for c in calls] == ["hide_image"]


def test_parser_menor_que_suelto_se_habla() -> None:
    parser = PromptToolParser()
    text, calls = _feed_all(parser, ["si a < b ", "entonces b > a"])
    assert text == "si a < b entonces b > a"
    assert calls == []


def test_parser_menor_que_al_final_se_suelta_en_flush() -> None:
    parser = PromptToolParser()
    spoken, _ = parser.feed("fin <")
    assert spoken == "fin "
    assert parser.flush() == "<"


def test_parser_dos_acciones_con_ids_correlativos() -> None:
    parser = PromptToolParser()
    text, calls = _feed_all(
        parser,
        [
            'Mira. <action>{"name": "look", "arguments": {}}</action>',
            ' y luego <action>{"name": "hide_image", "arguments": {}}</action> listo.',
        ],
    )
    assert text == "Mira.  y luego  listo."
    assert [c.id for c in calls] == ["prompt_0", "prompt_1"]
    assert [c.name for c in calls] == ["look", "hide_image"]


def test_parser_json_invalido_no_produce_accion() -> None:
    parser = PromptToolParser()
    text, calls = _feed_all(parser, ["texto <action>{roto}</action> más texto"])
    assert text == "texto  más texto"
    assert calls == []


def test_parser_bloque_sin_cerrar_no_se_habla() -> None:
    parser = PromptToolParser()
    spoken, calls = parser.feed('hola <action>{"name": "look"')
    assert spoken == "hola "
    assert calls == []
    assert parser.flush() == ""


def test_parser_reset() -> None:
    parser = PromptToolParser()
    parser.feed('<action>{"name": "look", "arguments": {}}</action>')
    parser.reset()
    _, calls = parser.feed('<action>{"name": "look", "arguments": {}}</action>')
    assert calls[0].id == "prompt_0"


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
