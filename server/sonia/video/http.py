"""Peticiones a las APIs de voz con reintentos: 429 y 5xx esperan cada vez más.

Los mensajes de error nunca llevan la clave (va en una cabecera que no se registra)
y recortan el cuerpo de la respuesta.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from sonia.video.errors import VideoError

__all__ = ["RETRY_STATUS", "HttpError", "request_json"]

logger = logging.getLogger(__name__)

#: Respuestas que se reintentan: límite de uso y fallos del servidor.
RETRY_STATUS = frozenset({408, 429, 500, 502, 503, 504})

#: Cuánto se recorta del cuerpo de una respuesta de error.
ERROR_BODY_CHARS = 500


class HttpError(VideoError):
    """La API contestó con un error que no se reintenta."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


def _error_text(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:ERROR_BODY_CHARS]
    if isinstance(body, dict):
        error = body.get("error") or body.get("detail")
        if isinstance(error, dict):
            message = error.get("message") or error.get("status")
            if isinstance(message, str):
                return message[:ERROR_BODY_CHARS]
        if isinstance(error, str):
            return error[:ERROR_BODY_CHARS]
    return response.text[:ERROR_BODY_CHARS]


async def request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    what: str,
    json: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    tries: int = 4,
    backoff_s: float = 2.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> dict[str, Any]:
    """La respuesta JSON de una petición, con hasta ``tries`` intentos.

    Reintenta los 429, los 5xx, los timeouts y los fallos de red, esperando
    ``backoff_s``, el doble, el triple... Cualquier otro error HTTP se cuenta tal cual
    (``what`` dice qué se estaba haciendo, por ejemplo «la voz de Gemini»).
    """
    last = ""
    for attempt in range(1, tries + 1):
        try:
            response = await client.request(method, url, json=json, params=params)
        except httpx.TimeoutException:
            last = "no contestó a tiempo"
        except httpx.TransportError as exc:
            last = f"fallo de red ({type(exc).__name__})"
        else:
            if response.status_code < 400:
                try:
                    data = response.json()
                except ValueError:
                    raise VideoError(f"{what}: la respuesta no es JSON") from None
                if not isinstance(data, dict):
                    raise VideoError(f"{what}: respuesta inesperada")
                return data
            if response.status_code not in RETRY_STATUS:
                raise HttpError(
                    f"{what} devolvió {response.status_code}: {_error_text(response)}",
                    response.status_code,
                )
            last = f"{response.status_code}: {_error_text(response)}"
        if attempt < tries:
            wait = backoff_s * attempt
            logger.warning("%s: %s; reintento %d en %.0f s", what, last, attempt, wait)
            await sleep(wait)
    raise VideoError(f"{what} falló {tries} veces; la última: {last}")
