"""Tests for the language model layer.

No real API is ever called: everything goes through ``httpx.MockTransport``
with simulated SSE.
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
# Helpers
# ---------------------------------------------------------------------------


def make_settings(**overrides: Any) -> LLMSettings:
    """Fixed settings: tests must not depend on the machine's `.env`."""
    base: dict[str, Any] = {
        "base_url": "http://llm.test/v1",
        "model": "test-model",
        "api_key": "test-key",
        "reasoning_effort": "",
        "temperature": 0.5,
        "max_tokens": 128,
        "max_tokens_param": "max_tokens",
        "request_timeout": 5.0,
    }
    base.update(overrides)
    return LLMSettings(**base)


def sse(*payloads: dict[str, Any] | str) -> bytes:
    """Serializes payloads as an SSE stream, with realistic noise in between."""
    lines: list[str] = [": ping\n\n"]  # comment that must be ignored
    for payload in payloads:
        data = payload if isinstance(payload, str) else json.dumps(payload)
        lines.append(f"data: {data}\n\n")
    return "".join(lines).encode("utf-8")


def chunk(delta: dict[str, Any], finish_reason: str | None = None) -> dict[str, Any]:
    """A chat completions chunk with a single choice."""
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion.chunk",
        "model": "test-model",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


def streaming_transport(
    body: bytes,
    *,
    captured: list[dict[str, Any]] | None = None,
    chunk_size: int = 7,
) -> httpx.MockTransport:
    """Transport that returns ``body`` in pieces, as a real server would."""

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


def make_frame(data: bytes = b"fake-jpeg") -> Frame:
    return Frame(data=data, mime="image/jpeg", width=64, height=48)


# ---------------------------------------------------------------------------
# LLMClient: text
# ---------------------------------------------------------------------------


async def test_text_across_several_chunks() -> None:
    body = sse(
        chunk({"role": "assistant", "content": ""}),
        chunk({"content": "Hello"}),
        chunk({"content": ", how "}),
        chunk({"content": "are you?"}),
        chunk({}, finish_reason="stop"),
        "[DONE]",
    )
    client = LLMClient(make_settings(), transport=streaming_transport(body))
    events = await collect(client, messages=[user_text("hello")])
    await client.aclose()

    deltas = [e for e in events if isinstance(e, TextDelta)]
    assert [d.text for d in deltas] == ["Hello", ", how ", "are you?"]
    done = events[-1]
    assert isinstance(done, TurnDone)
    assert done.content == "Hello, how are you?"
    assert done.finish_reason == "stop"
    assert done.reasoning_content is None


async def test_reasoning_is_not_yielded_but_is_kept() -> None:
    body = sse(
        chunk({"reasoning_content": "thinking "}),
        chunk({"reasoning_content": "a bit"}),
        chunk({"content": "Done."}),
        chunk({}, finish_reason="stop"),
        "[DONE]",
    )
    client = LLMClient(make_settings(), transport=streaming_transport(body))
    events = await collect(client, messages=[user_text("hello")])
    await client.aclose()

    assert [e.text for e in events if isinstance(e, TextDelta)] == ["Done."]
    done = events[-1]
    assert isinstance(done, TurnDone)
    assert done.reasoning_content == "thinking a bit"
    assert done.content == "Done."


async def test_cap_used_up_reasoning_warns_and_returns_no_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A reasoning model can spend the whole cap thinking: it must show up in the log."""
    body = sse(
        chunk({"reasoning_content": "let me think hard"}),
        chunk({}, finish_reason="length"),
        "[DONE]",
    )
    client = LLMClient(make_settings(max_tokens=64), transport=streaming_transport(body))
    with caplog.at_level("WARNING", logger="sonia.llm.client"):
        events = await collect(client, messages=[user_text("hello")])
    await client.aclose()

    done = events[-1]
    assert isinstance(done, TurnDone)
    assert done.content == ""
    assert done.finish_reason == "length"
    assert "hit the 64-token cap" in caplog.text
    assert "LLM_MAX_TOKENS" in caplog.text


async def test_truncated_reply_with_text_does_not_warn(caplog: pytest.LogCaptureFixture) -> None:
    body = sse(
        chunk({"content": "There are two people and"}), chunk({}, finish_reason="length"), "[DONE]"
    )
    client = LLMClient(make_settings(), transport=streaming_transport(body))
    with caplog.at_level("WARNING", logger="sonia.llm.client"):
        await collect(client, messages=[user_text("hello")])
    await client.aclose()
    assert "token cap" not in caplog.text


async def test_odd_lines_and_usage_chunk_are_tolerated() -> None:
    body = (
        b": keep-alive\n\n"
        b"\n"
        b"event: message\n"
        b"data: " + json.dumps(chunk({"content": "ok"})).encode() + b"\n\n"
        b"data: not-json\n\n"
        b"data: " + json.dumps({"choices": [], "usage": {"total_tokens": 3}}).encode() + b"\n\n"
        b"data: [DONE]\n\n"
    )
    client = LLMClient(make_settings(), transport=streaming_transport(body))
    events = await collect(client, messages=[user_text("hello")])
    await client.aclose()

    assert [e.text for e in events if isinstance(e, TextDelta)] == ["ok"]
    assert isinstance(events[-1], TurnDone)


# ---------------------------------------------------------------------------
# LLMClient: tool calls
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# LLMClient: request body
# ---------------------------------------------------------------------------


async def test_body_without_temperature_when_none() -> None:
    captured: list[dict[str, Any]] = []
    body = sse(chunk({"content": "ok"}, finish_reason="stop"), "[DONE]")
    client = LLMClient(
        make_settings(temperature=None), transport=streaming_transport(body, captured=captured)
    )
    await collect(client, messages=[user_text("hello")])
    await client.aclose()
    assert "temperature" not in captured[0]


async def test_body_without_reasoning() -> None:
    captured: list[dict[str, Any]] = []
    body = sse(chunk({"content": "ok"}, finish_reason="stop"), "[DONE]")
    client = LLMClient(make_settings(), transport=streaming_transport(body, captured=captured))
    await collect(client, messages=[user_text("hello")])
    await client.aclose()

    sent = captured[0]
    assert sent["model"] == "test-model"
    assert sent["stream"] is True
    assert sent["temperature"] == 0.5
    assert sent["max_tokens"] == 128
    assert "tools" not in sent
    assert "reasoning_effort" not in sent
    assert "stream_options" not in sent


async def test_max_completion_tokens_for_the_openai_api() -> None:
    captured: list[dict[str, Any]] = []
    body = sse(chunk({"content": "ok"}, finish_reason="stop"), "[DONE]")
    client = LLMClient(
        make_settings(max_tokens_param="max_completion_tokens"),
        transport=streaming_transport(body, captured=captured),
    )
    await collect(client, messages=[user_text("hello")])
    await client.aclose()
    assert captured[0]["max_completion_tokens"] == 128
    assert "max_tokens" not in captured[0]


async def _sent(settings: LLMSettings, messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Body that ``stream`` sends to the server with these settings."""
    captured: list[dict[str, Any]] = []
    body = sse(chunk({"content": "ok"}, finish_reason="stop"), "[DONE]")
    client = LLMClient(settings, transport=streaming_transport(body, captured=captured))
    await collect(client, messages)
    await client.aclose()
    return captured[0]


async def test_reasoning_effort_is_sent_and_off_removes_it() -> None:
    messages = [user_text("hello")]
    assert (await _sent(make_settings(reasoning_effort="low"), messages))[
        "reasoning_effort"
    ] == "low"
    for value in ("off", "OFF", " off "):
        sent = await _sent(make_settings(reasoning_effort=value), messages)
        assert "reasoning_effort" not in sent


async def test_extra_body_is_merged_into_the_body() -> None:
    settings = make_settings(extra_body={"thinking": {"type": "disabled"}, "temperature": 0.6})
    sent = await _sent(settings, [user_text("hello")])
    assert sent["thinking"] == {"type": "disabled"}
    assert sent["temperature"] == 0.6  # server-specific fields may override a normal value


async def test_extra_body_does_not_override_model_messages_or_stream() -> None:
    settings = make_settings(
        extra_body={"model": "other", "messages": [], "stream": False, "thinking": 1}
    )
    sent = await _sent(settings, [user_text("hello")])
    assert sent["model"] == "test-model"
    assert sent["messages"] == [user_text("hello")]
    assert sent["stream"] is True
    assert sent["thinking"] == 1


async def test_image_detail_applies_to_images_without_touching_the_original() -> None:
    message = user_with_image("what do you see?", make_frame())  # carries detail="low"
    system_message = system("you are sonnia")

    def image_url(sent: dict[str, Any]) -> dict[str, Any]:
        return sent["messages"][1]["content"][1]["image_url"]

    default = await _sent(make_settings(), [system_message, message])
    assert image_url(default)["detail"] == "low"
    assert default["messages"][0] == system_message  # text messages pass through as they are

    high = await _sent(make_settings(image_detail="high"), [system_message, message])
    assert image_url(high)["detail"] == "high"

    for value in ("off", "OFF", ""):
        without_detail = await _sent(make_settings(image_detail=value), [system_message, message])
        assert "detail" not in image_url(without_detail)
        assert image_url(without_detail)["url"].startswith("data:image/jpeg;base64,")

    # The message the caller built is not modified.
    assert message["content"][1]["image_url"]["detail"] == "low"


async def test_probe_sends_the_image_like_the_real_request() -> None:
    """``sonia check`` must catch a server that rejects what will really be sent."""
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": []})

    image = {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:x"}}]}
    for setting in ("low", "off"):
        client = LLMClient(
            make_settings(image_detail=setting), transport=httpx.MockTransport(handler)
        )
        await client.probe(image)
        await client.aclose()

    assert captured[0]["messages"][0]["content"][0]["image_url"] == {
        "url": "data:x",
        "detail": "low",
    }
    assert captured[1]["messages"][0]["content"][0]["image_url"] == {"url": "data:x"}


async def test_compatible_server_recipe_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-OpenAI server configured from the environment gets the request it expects."""
    environment = {
        "LLM_BASE_URL": "https://llm.example.com/v1",
        "LLM_MODEL": "vision-model",
        "LLM_API_KEY": "test-key",
        "LLM_REASONING_EFFORT": "off",
        "LLM_IMAGE_DETAIL": "off",
        "LLM_EXTRA_BODY": '{"thinking": {"type": "disabled"}}',
        "LLM_MAX_TOKENS": "300",
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("LLM_TEMPERATURE", raising=False)
    monkeypatch.delenv("LLM_MAX_TOKENS_PARAM", raising=False)

    settings = LLMSettings()
    assert settings.extra_body == {"thinking": {"type": "disabled"}}

    seen: list[httpx.Request] = []
    body = sse(chunk({"content": "There is one person."}, finish_reason="stop"), "[DONE]")

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=body)

    client = LLMClient(settings, transport=httpx.MockTransport(handler))
    await collect(client, [system("eyes"), user_with_image("what do you see?", make_frame())])
    await client.aclose()

    assert str(seen[0].url) == "https://llm.example.com/v1/chat/completions"
    sent = json.loads(seen[0].content)
    assert sent["model"] == "vision-model"
    assert sent["thinking"] == {"type": "disabled"}
    assert sent["max_completion_tokens"] == 300
    assert sent["stream"] is True
    assert "reasoning_effort" not in sent
    assert "temperature" not in sent  # some servers fix the temperature and reject other values
    assert "detail" not in sent["messages"][1]["content"][1]["image_url"]


def test_openai_key_is_only_sent_to_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    assert LLMSettings().key == "openai-key"
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example.com/v1")
    assert LLMSettings().key == ""
    monkeypatch.setenv("LLM_API_KEY", "other-server-key")
    assert LLMSettings().key == "other-server-key"
    # Neither over plain HTTP nor with a domain that only looks like it.
    monkeypatch.delenv("LLM_API_KEY")
    for url in ("http://api.openai.com/v1", "https://api.openai.com.evil.test/v1"):
        monkeypatch.setenv("LLM_BASE_URL", url)
        assert LLMSettings().key == ""
    assert "openai-key" not in repr(LLMSettings())


def test_invalid_extra_body_in_the_environment_fails_at_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_EXTRA_BODY", "{this is not json")
    with pytest.raises(Exception, match="LLM_EXTRA_BODY|extra_body"):
        LLMSettings()


async def test_url_and_authorization_header() -> None:
    seen: list[httpx.Request] = []
    body = sse(chunk({"content": "ok"}, finish_reason="stop"), "[DONE]")

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=body)

    client = LLMClient(
        make_settings(base_url="http://llm.test/v1/"), transport=httpx.MockTransport(handler)
    )
    await collect(client, messages=[user_text("hello")])
    await client.aclose()

    assert str(seen[0].url) == "http://llm.test/v1/chat/completions"
    assert seen[0].headers["authorization"] == "Bearer test-key"


# ---------------------------------------------------------------------------
# LLMClient: errors and retries
# ---------------------------------------------------------------------------


async def test_error_401_raises_llm_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "invalid key"}})

    client = LLMClient(make_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(LLMError) as info:
        await collect(client, messages=[user_text("hello")])
    await client.aclose()

    assert info.value.status_code == 401
    assert "invalid key" in info.value.body


async def test_retry_after_network_failure() -> None:
    body = sse(chunk({"content": "second attempt"}, finish_reason="stop"), "[DONE]")
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200, content=body)

    client = LLMClient(make_settings(), transport=httpx.MockTransport(handler))
    events = await collect(client, messages=[user_text("hello")])
    await client.aclose()

    assert attempts == 2
    assert [e.text for e in events if isinstance(e, TextDelta)] == ["second attempt"]


async def test_error_inside_the_stream_raises_llm_error() -> None:
    """vLLM and llama.cpp send the error as one more chunk, with HTTP 200.

    Discarding it (it carries no ``choices``) left Sonnia mute with no error
    message: the turn ended with empty text and nobody noticed.
    """
    body = sse(
        chunk({"role": "assistant", "content": ""}),
        {"error": {"message": "context overflow", "code": 500}},
    )
    client = LLMClient(make_settings(), transport=streaming_transport(body))
    with pytest.raises(LLMError, match="context overflow"):
        await collect(client, messages=[user_text("hello")])
    await client.aclose()


async def test_timeout_is_not_retried() -> None:
    """Retrying a timeout would double the silence in front of the user."""
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("the model says nothing", request=request)

    client = LLMClient(make_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(LLMError, match="LLM_REQUEST_TIMEOUT"):
        await collect(client, messages=[user_text("hello")])
    await client.aclose()

    assert attempts == 1


def test_read_timeout_is_the_configured_one() -> None:
    """``LLM_REQUEST_TIMEOUT`` must be able to go below two minutes."""
    client = LLMClient(make_settings(request_timeout=15.0))
    assert client._client.timeout.read == 15.0
    assert client._client.timeout.connect == 10.0


async def test_two_network_failures_raise_llm_error() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("connection refused", request=request)

    client = LLMClient(make_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(LLMError):
        await collect(client, messages=[user_text("hello")])
    await client.aclose()

    assert attempts == 2


# ---------------------------------------------------------------------------
# LLMClient: ping
# ---------------------------------------------------------------------------


async def test_ping_returns_model_and_text() -> None:
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "real-model",
                "choices": [{"message": {"role": "assistant", "content": "pong"}}],
            },
        )

    client = LLMClient(make_settings(), transport=httpx.MockTransport(handler))
    result = await client.ping()
    await client.aclose()

    assert result == "real-model: pong"
    assert captured[0]["stream"] is False
    assert captured[0]["max_tokens"] == 5


async def test_ping_with_error_raises_llm_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="no such model")

    client = LLMClient(make_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(LLMError):
        await client.ping()
    await client.aclose()


# ---------------------------------------------------------------------------
# messages
# ---------------------------------------------------------------------------


def test_text_and_image_messages() -> None:
    assert system("you are sonnia") == {"role": "system", "content": "you are sonnia"}
    assert user_text("hello") == {"role": "user", "content": "hello"}
    message = user_with_image("what do you see?", make_frame())
    assert message["role"] == "user"
    parts = message["content"]
    assert parts[0] == {"type": "text", "text": "what do you see?"}
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert parts[1]["image_url"]["detail"] == "low"
    assert user_with_image("", make_frame())["content"][0]["type"] == "image_url"


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


async def test_cancelling_the_turn_closes_the_response() -> None:
    """When the task is cancelled, ``async with`` closes the server stream."""
    closed = asyncio.Event()
    first_delta = asyncio.Event()

    def handler(request: httpx.Request) -> httpx.Response:
        async def stream() -> AsyncIterator[bytes]:
            try:
                yield b"data: " + json.dumps(chunk({"content": "Hello"})).encode() + b"\n\n"
                await asyncio.Event().wait()  # the server keeps thinking
            finally:
                closed.set()

        return httpx.Response(200, content=stream())

    client = LLMClient(make_settings(), transport=httpx.MockTransport(handler))

    async def consume() -> None:
        async for event in client.stream([user_text("hello")]):
            if isinstance(event, TextDelta):
                first_delta.set()

    task = asyncio.create_task(consume())
    await asyncio.wait_for(first_delta.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.wait_for(closed.wait(), timeout=2)
    await client.aclose()
