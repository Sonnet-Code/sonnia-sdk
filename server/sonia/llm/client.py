"""Streaming client for any OpenAI-compatible endpoint.

With GPT-Live it is used to describe the camera (``sonia/live/vision.py``):
text and image in, text out, no actions. :meth:`LLMClient.complete` also
offers a non-streamed completion for short replies. No SDK is used: only
``httpx`` and an SSE parser. Everything server-specific comes from
:class:`LLMSettings`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from sonia.config import LLMSettings
from sonia.types import LLMEvent, Message, TextDelta, TurnDone

__all__ = ["Completion", "LLMClient", "LLMError"]

logger = logging.getLogger(__name__)

#: Wait before the single retry after a network failure. Short on purpose: in a
#: live demo it is better to fail fast and go back to listening than to hang.
_RETRY_BACKOFF_SECONDS = 0.4

#: ``LLM_REQUEST_TIMEOUT`` bounds the gap between two stream chunks: if the
#: server accepts the connection and then goes silent, Sonnia does not stay in
#: ``thinking`` longer than that. A server that is still loading the model
#: needs a high value; that is what the variable is for (and ``sonia check``,
#: which already pays that wait before going live).
#:
#: Multiplied by this, it gives the total deadline of a turn, so that a model
#: that trickles a token now and then cannot drag it out forever either.
_TOTAL_TIMEOUT_FACTOR = 4.0

_CONNECT_TIMEOUT = 10.0

#: Value of ``LLM_REASONING_EFFORT`` and ``LLM_IMAGE_DETAIL`` that means "do not send
#: the field". An empty value will not do: in ``.env`` it means the variable is unset.
_OFF = "off"

#: Body fields that ``LLM_EXTRA_BODY`` cannot override: without them the client
#: would not understand the response (``stream``) or it would not be the same request.
_PROTECTED_BODY_KEYS = frozenset({"model", "messages", "stream"})


class LLMError(RuntimeError):
    """Failure talking to the model server."""

    def __init__(self, message: str, *, status_code: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


@dataclass(frozen=True, slots=True)
class Completion:
    """Full reply from :meth:`LLMClient.complete`, with token usage if the server reports it."""

    content: str
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    #: Of ``prompt_tokens``, how many came from the server's prompt cache.
    cached_tokens: int | None = None
    completion_tokens: int | None = None
    #: Of ``completion_tokens``, how many were spent reasoning (if the server says).
    reasoning_tokens: int | None = None


@dataclass(slots=True)
class _StreamState:
    """State accumulated while a stream is consumed."""

    content: list[str] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)
    finish_reason: str | None = None


class LLMClient:
    """Talks to ``POST {base_url}/chat/completions``, always streaming."""

    def __init__(
        self,
        settings: LLMSettings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._url = settings.base_url.rstrip("/") + "/chat/completions"
        self._total_timeout = settings.request_timeout * _TOTAL_TIMEOUT_FACTOR
        timeout = httpx.Timeout(
            settings.request_timeout,
            connect=min(_CONNECT_TIMEOUT, settings.request_timeout),
            read=settings.request_timeout,
        )
        self._client = httpx.AsyncClient(
            timeout=timeout,
            transport=transport,
            headers={
                "Authorization": f"Bearer {settings.key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
        )

    # -- lifecycle --------------------------------------------------------

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> LLMClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    # -- request body -----------------------------------------------------

    def _build_body(
        self,
        messages: list[Message],
        *,
        stream: bool,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        settings = self._settings
        body: dict[str, Any] = {
            "model": settings.model,
            "messages": _with_image_detail(messages, settings.image_detail),
            "stream": stream,
            settings.max_tokens_param: settings.max_tokens if max_tokens is None else max_tokens,
        }
        if settings.temperature is not None:
            body["temperature"] = settings.temperature
        effort = settings.reasoning_effort.strip()
        if effort and effort.lower() != _OFF:
            body["reasoning_effort"] = effort
        for key, value in settings.extra_body.items():
            if key not in _PROTECTED_BODY_KEYS:
                body[key] = value
        # Note: ``stream_options.include_usage`` is not sent. Several local
        # servers reject the whole request if they do not support it.
        return body

    # -- streaming ---------------------------------------------------------

    async def stream(self, messages: list[Message]) -> AsyncIterator[LLMEvent]:
        """Yields model events as they arrive.

        Yields a :class:`TextDelta` for each text fragment and, at the end, a
        :class:`TurnDone`. ``reasoning_content`` is accumulated but never
        yielded as text.

        A network failure before anything is received is retried once; if text
        was already yielded it is not retried (it would repeat what was said).
        A timeout is never retried: it would double the wait in front of the
        user. When the task is cancelled, ``async with`` closes the response and
        the connection.
        """
        body = self._build_body(messages, stream=True)
        attempt = 0
        while True:
            emitted = False
            deadline = time.monotonic() + self._total_timeout
            try:
                async with self._client.stream("POST", self._url, json=body) as response:
                    if response.status_code >= 400:
                        raw = await response.aread()
                        text = raw.decode("utf-8", errors="replace")
                        if response.status_code >= 500 and attempt == 0:
                            logger.warning(
                                "The model server returned %s; retrying",
                                response.status_code,
                            )
                            raise _Retry
                        raise LLMError(
                            f"The model server returned {response.status_code}: {text}",
                            status_code=response.status_code,
                            body=text,
                        )
                    state = _StreamState()
                    async for line in response.aiter_lines():
                        if time.monotonic() > deadline:
                            raise LLMError(
                                "The model went past "
                                f"{self._total_timeout:.0f} s without finishing the turn."
                            )
                        data = _sse_data(line)
                        if data is None:
                            continue
                        if data == "[DONE]":
                            break
                        chunk = _load_chunk(data)
                        if chunk is None:
                            continue
                        for event in self._consume_chunk(chunk, state):
                            emitted = True
                            yield event
                    yield self._finish(state)
                    return
            except _Retry:
                pass
            except httpx.TimeoutException as exc:
                raise LLMError(
                    f"The model sent nothing for {self._settings.request_timeout:g} s "
                    "(LLM_REQUEST_TIMEOUT)."
                ) from exc
            except httpx.TransportError as exc:
                if emitted or attempt > 0:
                    raise LLMError(f"Network failure talking to the model: {exc}") from exc
                logger.warning("Network failure talking to the model (%s); retrying", exc)
            attempt += 1
            await asyncio.sleep(_RETRY_BACKOFF_SECONDS)

    def _consume_chunk(self, chunk: dict[str, Any], state: _StreamState) -> list[LLMEvent]:
        """Processes a stream chunk and returns the events it produces."""
        events: list[LLMEvent] = []
        error = chunk.get("error")
        if error:
            # vLLM, llama.cpp and several proxies send the error INSIDE the stream
            # with HTTP 200. Discarding it would leave Sonnia mute with no explanation.
            raise LLMError(
                f"The model server returned an error in the stream: {_error_text(error)}"
            )
        choices = chunk.get("choices") or []
        if not choices:
            return events  # usage or keep-alive chunk
        choice = choices[0] if isinstance(choices[0], dict) else {}
        delta = choice.get("delta") or {}
        if not isinstance(delta, dict):
            delta = {}

        reasoning = delta.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning:
            state.reasoning.append(reasoning)

        content = delta.get("content")
        if isinstance(content, str) and content:
            state.content.append(content)
            events.append(TextDelta(content))

        finish_reason = choice.get("finish_reason")
        if isinstance(finish_reason, str) and finish_reason:
            state.finish_reason = finish_reason
        return events

    def _finish(self, state: _StreamState) -> TurnDone:
        """Builds the final event of the turn."""
        content = "".join(state.content)
        reasoning = "".join(state.reasoning) or None
        if not content.strip() and state.finish_reason == "length":
            # A reasoning model can spend the whole cap thinking and never answer:
            # without this warning the camera description comes out empty with no clue.
            logger.warning(
                "The model hit the %d-token cap without producing text (still reasoning?); "
                "raise LLM_MAX_TOKENS or lower LLM_REASONING_EFFORT",
                self._settings.max_tokens,
            )
        return TurnDone(
            content=content,
            reasoning_content=reasoning,
            finish_reason=state.finish_reason,
        )

    # -- full reply ---------------------------------------------------------

    async def complete(self, messages: list[Message]) -> Completion:
        """A non-streamed request for short replies that are needed quickly.

        No retries: the caller has a deadline and would rather go on without a
        reply than get one late. Raises :class:`LLMError` if the server fails,
        takes longer than ``request_timeout`` or returns an error.
        """
        body = self._build_body(messages, stream=False)
        try:
            # The whole reply as JSON, not the SSE the client asks for by default.
            response = await self._client.post(
                self._url, json=body, headers={"Accept": "application/json"}
            )
        except httpx.TimeoutException as exc:
            raise LLMError(
                f"The model did not reply within {self._settings.request_timeout:g} s."
            ) from exc
        except httpx.TransportError as exc:
            raise LLMError(f"Network failure talking to the model: {exc}") from exc
        if response.status_code >= 400:
            text = response.text
            raise LLMError(
                f"The model server returned {response.status_code}: {text[:300]}",
                status_code=response.status_code,
                body=text,
            )
        payload = _load_chunk(response.text) or {}
        error = payload.get("error")
        if error:
            raise LLMError(f"The model server returned an error: {_error_text(error)}")
        content = ""
        finish_reason: str | None = None
        choices = payload.get("choices") or []
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message") or {}
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                content = message["content"]
            reason = choices[0].get("finish_reason")
            finish_reason = reason if isinstance(reason, str) else None
        usage = payload.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        prompt_details = usage.get("prompt_tokens_details")
        prompt_details = prompt_details if isinstance(prompt_details, dict) else {}
        output_details = usage.get("completion_tokens_details")
        output_details = output_details if isinstance(output_details, dict) else {}
        return Completion(
            content=content,
            finish_reason=finish_reason,
            prompt_tokens=_count(usage.get("prompt_tokens")),
            cached_tokens=_count(prompt_details.get("cached_tokens")),
            completion_tokens=_count(usage.get("completion_tokens")),
            reasoning_tokens=_count(output_details.get("reasoning_tokens")),
        )

    # -- checks ------------------------------------------------------------

    async def ping(self) -> str:
        """Minimal non-streamed request for ``sonia check``.

        Returns the model the server reports and, if there is one, the text it
        replied with. Raises :class:`LLMError` if the endpoint does not respond.
        """
        body = self._build_body(
            [{"role": "user", "content": "ping"}],
            stream=False,
            max_tokens=5,
        )
        attempt = 0
        while True:
            try:
                response = await self._client.post(self._url, json=body)
            except httpx.TransportError as exc:
                if attempt > 0:
                    raise LLMError(f"Network failure talking to the model: {exc}") from exc
                logger.warning("Network failure on the model ping (%s); retrying", exc)
                attempt += 1
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS)
                continue

            if response.status_code >= 400:
                text = response.text
                raise LLMError(
                    f"The model server returned {response.status_code}: {text}",
                    status_code=response.status_code,
                    body=text,
                )
            payload = _load_chunk(response.text) or {}
            model = str(payload.get("model") or self._settings.model)
            choices = payload.get("choices") or []
            text = ""
            if choices and isinstance(choices[0], dict):
                message = choices[0].get("message") or {}
                if isinstance(message, dict) and isinstance(message.get("content"), str):
                    text = message["content"].strip()
            return f"{model}: {text}" if text else model

    async def probe(self, message: Message) -> None:
        """Minimal request with a specific message (for example, with an image).

        ``ping`` only checks that the server answers plain text, but the camera
        sends it images. A model without vision answers 400 to that and the
        description would fail on every turn; this catches it before going live.
        Raises :class:`LLMError` if the server rejects the request.
        """
        body = self._build_body([message], stream=False, max_tokens=5)
        try:
            response = await self._client.post(self._url, json=body)
        except httpx.TransportError as exc:
            raise LLMError(f"Network failure talking to the model: {exc}") from exc
        if response.status_code >= 400:
            raise LLMError(
                f"The model server returned {response.status_code}: {response.text}",
                status_code=response.status_code,
                body=response.text,
            )


class _Retry(Exception):
    """Internal signal: retry the request."""


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _with_image_detail(messages: list[Message], detail: str) -> list[Message]:
    """Copy of ``messages`` with the ``detail`` of every image set to ``detail``.

    ``off`` (or empty) removes it. It is done here and not when the message is
    built so that it applies the same to every request, including those of
    ``sonia check``.
    """
    value = detail.strip()
    send = bool(value) and value.lower() != _OFF

    def adjust(part: Any) -> Any:
        image = part.get("image_url") if isinstance(part, dict) else None
        if not isinstance(image, dict):
            return part
        image = {key: item for key, item in image.items() if key != "detail"}
        if send:
            image["detail"] = value
        return {**part, "image_url": image}

    return [
        {**message, "content": [adjust(part) for part in message["content"]]}
        if isinstance(message.get("content"), list)
        else message
        for message in messages
    ]


def _sse_data(line: str) -> str | None:
    """Extracts the payload of an SSE line, or ``None`` if there is none.

    Tolerates empty lines, comments (``:``) and fields other than ``data``.
    """
    line = line.rstrip("\r\n")
    if not line or line.startswith(":"):
        return None
    if not line.startswith("data:"):
        return None
    return line[len("data:") :].strip()


def _error_text(error: Any) -> str:
    """Readable text of a stream ``error`` (an OpenAI-style dict or a string)."""
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message:
            code = error.get("code")
            return f"{message} (code={code})" if code is not None else message
        return json.dumps(error)[:300]
    return str(error)[:300]


def _count(value: Any) -> int | None:
    """A token count from the ``usage`` field (``None`` if missing or invalid)."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _load_chunk(data: str) -> dict[str, Any] | None:
    """Decodes a JSON chunk; returns ``None`` if it is malformed."""
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError:
        logger.warning("Model chunk with invalid JSON, ignoring it: %r", data[:200])
        return None
    return parsed if isinstance(parsed, dict) else None
