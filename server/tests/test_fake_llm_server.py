"""El servidor falso de scripts/fake_llm_server.py debe hablar el dialecto que espera LLMClient.

Se arranca en un hilo, en un puerto libre, y se consume con el cliente real:
texto en streaming, y una tool call fragmentada seguida del texto de cierre.
"""

from __future__ import annotations

import importlib.util
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from sonia.config import LLMSettings
from sonia.llm.client import LLMClient
from sonia.llm.messages import assistant_tool_calls, tool_result, user_text
from sonia.types import TextDelta, ToolCallsEvent, TurnDone

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "fake_llm_server.py"


@pytest.fixture(scope="module")
def fake_server() -> Iterator[str]:
    spec = importlib.util.spec_from_file_location("fake_llm_server", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.Handler.delay = 0.0
    server = ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()
        server.server_close()


def _client(base_url: str) -> LLMClient:
    return LLMClient(
        LLMSettings(
            base_url=base_url, api_key="x", model="fake", reasoning_effort="", request_timeout=5.0
        )
    )


async def test_texto_en_streaming(fake_server: str) -> None:
    client = _client(fake_server)
    try:
        deltas: list[str] = []
        done = None
        async for event in client.stream([user_text("Hola")]):
            if isinstance(event, TextDelta):
                deltas.append(event.text)
            elif isinstance(event, TurnDone):
                done = event
        assert done is not None
        assert len(deltas) > 5, "debe llegar palabra a palabra"
        assert "Sonia" in "".join(deltas)
    finally:
        await client.aclose()


async def test_tool_call_y_texto_de_cierre(fake_server: str) -> None:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "show_image",
                "description": "Muestra una imagen",
                "parameters": {"type": "object", "properties": {"image_id": {"type": "string"}}},
            },
        }
    ]
    client = _client(fake_server)
    try:
        messages = [user_text("Enséñame el logo")]
        events = [event async for event in client.stream(messages, tools=tools)]
        calls = [event for event in events if isinstance(event, ToolCallsEvent)]
        assert len(calls) == 1
        call = calls[0].calls[0]
        assert call.name == "show_image"
        assert call.arguments == {"image_id": "logo-sonnet", "caption": "Sonnet Code"}

        messages.append(assistant_tool_calls(calls[0]))
        messages.append(tool_result(call.id, call.name, "Mostrando la imagen 'logo-sonnet'."))
        parts: list[str] = []
        async for event in client.stream(messages, tools=tools):
            if isinstance(event, TextDelta):
                parts.append(event.text)
        assert "logo" in "".join(parts).lower()
    finally:
        await client.aclose()
