"""Cliente de streaming para cualquier endpoint compatible con OpenAI.

No se usa ningún SDK: solo ``httpx`` y un parser de SSE. El cliente es agnóstico
al modelo; todo lo específico del servidor viene de :class:`LLMSettings`.
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
from sonia.types import LLMEvent, Message, TextDelta, ToolCall, ToolCallsEvent, TurnDone

__all__ = ["LLMClient", "LLMError"]

logger = logging.getLogger(__name__)

#: Espera antes del único reintento tras un fallo de red. Corto a propósito:
#: en el stand vale más fallar rápido y volver a escuchar que quedarse colgada.
_RETRY_BACKOFF_SECONDS = 0.4

#: ``LLM_REQUEST_TIMEOUT`` acota el hueco entre dos trozos del stream: si el
#: servidor acepta la conexión y luego enmudece, Sonia no se queda en
#: ``thinking`` más de ese tiempo. Un servidor que aún está cargando el modelo
#: necesita un valor alto; para eso está la variable (y ``sonia check``, que ya
#: paga esa espera antes de abrir el stand).
#:
#: Multiplicado por esto sale el plazo total de un turno, para que un modelo
#: que gotea un token de vez en cuando tampoco pueda alargarlo sin fin.
_TOTAL_TIMEOUT_FACTOR = 4.0

_CONNECT_TIMEOUT = 10.0


class LLMError(RuntimeError):
    """Fallo al hablar con el servidor del modelo."""

    def __init__(self, message: str, *, status_code: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


@dataclass(slots=True)
class _ToolCallBuffer:
    """Acumulador de una tool call que llega troceada en varios deltas."""

    index: int
    id: str = ""
    name: str = ""
    arguments: str = ""


@dataclass(slots=True)
class _StreamState:
    """Estado acumulado mientras se consume un stream."""

    content: list[str] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)
    tool_calls: dict[int, _ToolCallBuffer] = field(default_factory=dict)
    finish_reason: str | None = None


class LLMClient:
    """Habla con ``POST {base_url}/chat/completions``, siempre en streaming."""

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
                "Authorization": f"Bearer {settings.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
        )

    # -- ciclo de vida ----------------------------------------------------

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> LLMClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    # -- cuerpo de la petición --------------------------------------------

    def _build_body(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        *,
        stream: bool,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        settings = self._settings
        body: dict[str, Any] = {
            "model": settings.model,
            "messages": messages,
            "stream": stream,
            settings.max_tokens_param: settings.max_tokens if max_tokens is None else max_tokens,
        }
        if settings.temperature is not None:
            body["temperature"] = settings.temperature
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if settings.reasoning_effort.strip():
            body["reasoning_effort"] = settings.reasoning_effort
        # Nota: no se envía ``stream_options.include_usage``. Varios servidores
        # locales rechazan la petición entera si no lo soportan.
        return body

    # -- streaming ---------------------------------------------------------

    async def stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[LLMEvent]:
        """Emite eventos del modelo según van llegando.

        Emite un :class:`TextDelta` por cada fragmento de texto hablable y, al
        cerrar el turno, un :class:`ToolCallsEvent` (si el modelo pidió
        acciones) o un :class:`TurnDone`. El ``reasoning_content`` se acumula
        pero nunca se emite como texto: no se habla, solo se reenvía.

        Un fallo de red antes de recibir nada se reintenta una vez; si ya se
        había emitido texto no se reintenta (duplicaría lo dicho). Un timeout
        no se reintenta nunca: duplicaría la espera delante del visitante. Al
        cancelar la tarea, ``async with`` cierra la respuesta y la conexión.
        """
        body = self._build_body(messages, tools, stream=True)
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
                                "El servidor del modelo devolvió %s; reintentando",
                                response.status_code,
                            )
                            raise _Retry
                        raise LLMError(
                            f"El servidor del modelo devolvió {response.status_code}: {text}",
                            status_code=response.status_code,
                            body=text,
                        )
                    state = _StreamState()
                    async for line in response.aiter_lines():
                        if time.monotonic() > deadline:
                            raise LLMError(
                                "El modelo pasó de "
                                f"{self._total_timeout:.0f} s sin terminar el turno."
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
                    f"El modelo no envió nada durante {self._settings.request_timeout:g} s "
                    "(LLM_REQUEST_TIMEOUT)."
                ) from exc
            except httpx.TransportError as exc:
                if emitted or attempt > 0:
                    raise LLMError(f"Fallo de red hablando con el modelo: {exc}") from exc
                logger.warning("Fallo de red hablando con el modelo (%s); reintentando", exc)
            attempt += 1
            await asyncio.sleep(_RETRY_BACKOFF_SECONDS)

    def _consume_chunk(self, chunk: dict[str, Any], state: _StreamState) -> list[LLMEvent]:
        """Procesa un chunk del stream y devuelve los eventos que genera."""
        events: list[LLMEvent] = []
        error = chunk.get("error")
        if error:
            # vLLM, llama.cpp y varios proxies mandan el error DENTRO del stream
            # con HTTP 200. Descartarlo dejaría a Sonia muda y sin explicación.
            raise LLMError(
                f"El servidor del modelo devolvió un error en el stream: {_error_text(error)}"
            )
        choices = chunk.get("choices") or []
        if not choices:
            return events  # chunk de usage o keep-alive
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

        for raw_call in delta.get("tool_calls") or []:
            if isinstance(raw_call, dict):
                _merge_tool_call(raw_call, state.tool_calls)

        finish_reason = choice.get("finish_reason")
        if isinstance(finish_reason, str) and finish_reason:
            state.finish_reason = finish_reason
        return events

    def _finish(self, state: _StreamState) -> LLMEvent:
        """Construye el evento final del turno."""
        content = "".join(state.content)
        reasoning = "".join(state.reasoning) or None
        if state.tool_calls:
            calls = [
                ToolCall(
                    id=buf.id or f"call_{buf.index}",
                    name=buf.name,
                    arguments=_parse_arguments(buf),
                )
                for buf in sorted(state.tool_calls.values(), key=lambda b: b.index)
            ]
            return ToolCallsEvent(calls=calls, reasoning_content=reasoning, content=content)
        return TurnDone(
            content=content,
            reasoning_content=reasoning,
            finish_reason=state.finish_reason,
        )

    # -- comprobación ------------------------------------------------------

    async def ping(self) -> str:
        """Petición mínima no streaming para ``sonia check``.

        Devuelve el modelo que reporta el servidor y, si lo hay, el texto que
        contestó. Lanza :class:`LLMError` si el endpoint no responde.
        """
        body = self._build_body(
            [{"role": "user", "content": "ping"}],
            None,
            stream=False,
            max_tokens=5,
        )
        attempt = 0
        while True:
            try:
                response = await self._client.post(self._url, json=body)
            except httpx.TransportError as exc:
                if attempt > 0:
                    raise LLMError(f"Fallo de red hablando con el modelo: {exc}") from exc
                logger.warning("Fallo de red en el ping del modelo (%s); reintentando", exc)
                attempt += 1
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS)
                continue

            if response.status_code >= 400:
                text = response.text
                raise LLMError(
                    f"El servidor del modelo devolvió {response.status_code}: {text}",
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

    async def probe(
        self,
        *,
        image: Message | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> None:
        """Petición mínima que ejercita una capacidad concreta del endpoint.

        ``ping`` solo comprueba que el servidor conteste a texto plano, pero en
        cada turno real se le mandan imágenes y ``tools``. Un servidor sin
        ``mmproj`` o sin tool calling responde 400 a eso y Sonia se disculpa
        turno tras turno; esto lo detecta antes de abrir el stand. Lanza
        :class:`LLMError` si el servidor rechaza la petición.
        """
        message = image if image is not None else {"role": "user", "content": "ping"}
        body = self._build_body([message], tools, stream=False, max_tokens=5)
        try:
            response = await self._client.post(self._url, json=body)
        except httpx.TransportError as exc:
            raise LLMError(f"Fallo de red hablando con el modelo: {exc}") from exc
        if response.status_code >= 400:
            raise LLMError(
                f"El servidor del modelo devolvió {response.status_code}: {response.text}",
                status_code=response.status_code,
                body=response.text,
            )


class _Retry(Exception):
    """Señal interna: reintentar la petición."""


# ---------------------------------------------------------------------------
# Utilidades de parseo
# ---------------------------------------------------------------------------


def _sse_data(line: str) -> str | None:
    """Extrae el payload de una línea SSE, o ``None`` si no la hay.

    Tolera líneas vacías, comentarios (``:``) y campos que no son ``data``.
    """
    line = line.rstrip("\r\n")
    if not line or line.startswith(":"):
        return None
    if not line.startswith("data:"):
        return None
    return line[len("data:") :].strip()


def _error_text(error: Any) -> str:
    """Texto legible de un ``error`` del stream (dict al estilo OpenAI o cadena)."""
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message:
            code = error.get("code")
            return f"{message} (code={code})" if code is not None else message
        return json.dumps(error)[:300]
    return str(error)[:300]


def _load_chunk(data: str) -> dict[str, Any] | None:
    """Decodifica un chunk JSON; devuelve ``None`` si viene roto."""
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError:
        logger.warning("Chunk del modelo con JSON inválido, se ignora: %r", data[:200])
        return None
    return parsed if isinstance(parsed, dict) else None


def _merge_tool_call(raw: dict[str, Any], buffers: dict[int, _ToolCallBuffer]) -> None:
    """Acumula un fragmento de tool call en su buffer por ``index``."""
    index = raw.get("index")
    if not isinstance(index, int):
        index = 0
    buffer = buffers.get(index)
    if buffer is None:
        buffer = _ToolCallBuffer(index=index)
        buffers[index] = buffer
    call_id = raw.get("id")
    if isinstance(call_id, str) and call_id:
        buffer.id = call_id
    function = raw.get("function") or {}
    if not isinstance(function, dict):
        return
    name = function.get("name")
    if isinstance(name, str) and name:
        buffer.name = name
    arguments = function.get("arguments")
    if isinstance(arguments, str) and arguments:
        buffer.arguments += arguments


def _parse_arguments(buffer: _ToolCallBuffer) -> dict[str, Any]:
    """Parsea los argumentos acumulados; ``{}`` si el JSON vino roto."""
    raw = buffer.arguments.strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("Argumentos inválidos para la acción %r (%s): %r", buffer.name, exc, raw[:200])
        return {}
    if not isinstance(parsed, dict):
        logger.error("Argumentos de %r no son un objeto: %r", buffer.name, raw[:200])
        return {}
    return parsed
