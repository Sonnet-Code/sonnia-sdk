"""Modo ``prompt`` de tool calling, para servidores sin soporte nativo.

Las acciones se describen en el system prompt y el modelo las invoca escribiendo
bloques ``<action>{"name": ..., "arguments": {...}}</action>`` dentro del texto.
El texto de fuera de los bloques se habla; los bloques se ejecutan y nunca se
pronuncian.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sonia.types import ToolCall

__all__ = ["PromptToolParser", "render_tools_prompt"]

logger = logging.getLogger(__name__)

OPEN_TAG = "<action>"
CLOSE_TAG = "</action>"


def render_tools_prompt(tools: list[dict[str, Any]]) -> str:
    """Describe las acciones disponibles y el formato para invocarlas.

    ``tools`` viene en formato OpenAI (``{"type": "function", "function": ...}``);
    también se aceptan definiciones planas con ``name``/``description``.
    """
    if not tools:
        return ""
    lines = [
        "Puedes ejecutar acciones. Para invocar una, escribe un bloque exactamente así:",
        f'{OPEN_TAG}{{"name": "nombre_de_la_accion", "arguments": {{}}}}{CLOSE_TAG}',
        "",
        "Reglas de las acciones:",
        "- El bloque va en una sola línea, con JSON válido y sin markdown alrededor.",
        "- Todo lo que escribas fuera de los bloques se dice en voz alta; los bloques no se leen.",
        "- Usa una acción solo cuando aporte; si no hace falta, responde con texto normal.",
        "- Si una acción no lleva argumentos, escribe un objeto vacío.",
        "",
        "Acciones disponibles:",
    ]
    for tool in tools:
        inner = tool.get("function")
        function: dict[str, Any] = inner if isinstance(inner, dict) else tool
        name = str(function.get("name", "")).strip()
        if not name:
            continue
        description = str(function.get("description", "")).strip()
        lines.append(f"- {name}: {description}" if description else f"- {name}")
        arguments = _describe_parameters(function.get("parameters"))
        lines.append(f"  Argumentos: {arguments}")
    return "\n".join(lines)


def _describe_parameters(parameters: Any) -> str:
    """Resumen legible del JSON Schema de argumentos de una acción."""
    if not isinstance(parameters, dict):
        return "ninguno"
    properties = parameters.get("properties")
    if not isinstance(properties, dict) or not properties:
        return "ninguno"
    required = parameters.get("required")
    required_names = set(required) if isinstance(required, list) else set()
    parts: list[str] = []
    for key, schema in properties.items():
        kind = "string"
        detail = ""
        if isinstance(schema, dict):
            kind = str(schema.get("type", "string"))
            description = str(schema.get("description", "")).strip()
            if description:
                detail = f" ({description})"
        flag = "obligatorio" if key in required_names else "opcional"
        parts.append(f"{key}: {kind}, {flag}{detail}")
    return "; ".join(parts)


class PromptToolParser:
    """Separa el texto hablable de los bloques ``<action>`` en un stream.

    Se alimenta con los deltas del modelo tal como llegan. Retiene cualquier
    fragmento que podría ser el comienzo de ``<action>`` para no pronunciar
    media etiqueta, y lo suelta en cuanto sabe que no lo era.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._inside = False
        self._counter = 0

    def feed(self, delta: str) -> tuple[str, list[ToolCall]]:
        """Consume un delta y devuelve (texto hablable, acciones completas)."""
        self._buffer += delta
        spoken: list[str] = []
        calls: list[ToolCall] = []

        while True:
            if self._inside:
                end = self._buffer.find(CLOSE_TAG)
                if end < 0:
                    break  # el bloque sigue abierto: no se emite nada
                payload = self._buffer[:end]
                self._buffer = self._buffer[end + len(CLOSE_TAG) :]
                self._inside = False
                call = self._build_call(payload)
                if call is not None:
                    calls.append(call)
                continue

            start = self._buffer.find(OPEN_TAG)
            if start >= 0:
                spoken.append(self._buffer[:start])
                self._buffer = self._buffer[start + len(OPEN_TAG) :]
                self._inside = True
                continue

            held = _open_tag_prefix_len(self._buffer)
            if held:
                spoken.append(self._buffer[: len(self._buffer) - held])
                self._buffer = self._buffer[len(self._buffer) - held :]
            else:
                spoken.append(self._buffer)
                self._buffer = ""
            break

        return "".join(spoken), calls

    def flush(self) -> str:
        """Cierra el stream y devuelve el texto retenido pendiente."""
        if self._inside:
            logger.warning("Bloque de acción sin cerrar, se descarta: %r", self._buffer[:200])
            self._buffer = ""
            self._inside = False
            return ""
        rest = self._buffer
        self._buffer = ""
        return rest

    def reset(self) -> None:
        """Vuelve al estado inicial (los ids empiezan de nuevo en ``prompt_0``)."""
        self._buffer = ""
        self._inside = False
        self._counter = 0

    def _build_call(self, payload: str) -> ToolCall | None:
        raw = payload.strip().strip("`").strip()
        if raw.startswith("json"):
            raw = raw[len("json") :].strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error("Bloque de acción con JSON inválido (%s): %r", exc, raw[:200])
            return None
        if not isinstance(parsed, dict):
            logger.error("Bloque de acción que no es un objeto: %r", raw[:200])
            return None
        name = parsed.get("name")
        if not isinstance(name, str) or not name:
            logger.error("Bloque de acción sin nombre: %r", raw[:200])
            return None
        arguments = parsed.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {}
        call = ToolCall(id=f"prompt_{self._counter}", name=name, arguments=arguments)
        self._counter += 1
        return call


def _open_tag_prefix_len(buffer: str) -> int:
    """Longitud del final de ``buffer`` que podría ser el inicio de ``<action>``."""
    longest = min(len(buffer), len(OPEN_TAG) - 1)
    for size in range(longest, 0, -1):
        if buffer.endswith(OPEN_TAG[:size]):
            return size
    return 0
