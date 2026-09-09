"""Constructores de mensajes en formato OpenAI.

Ningún otro módulo debería construir diccionarios de mensajes a mano: estos
helpers son la única fuente de verdad de la forma que tienen. El formato es el
estándar de la API de chat completions, así que funciona con cualquier servidor
compatible (llama.cpp, vLLM, Ollama...).
"""

from __future__ import annotations

import json
from typing import Any

from sonia.types import Frame, Message, ToolCallsEvent

__all__ = [
    "assistant_text",
    "assistant_tool_calls",
    "has_image",
    "strip_images",
    "system",
    "tool_result",
    "user_text",
    "user_with_image",
]


def system(text: str) -> Message:
    """Mensaje de sistema (el prompt de personalidad)."""
    return {"role": "system", "content": text}


def user_text(text: str) -> Message:
    """Turno del usuario, solo texto."""
    return {"role": "user", "content": text}


def user_with_image(text: str, frame: Frame, detail: str = "low") -> Message:
    """Turno del usuario con una captura adjunta.

    La imagen viaja como ``image_url`` con una data URL, que es el formato
    estándar. ``detail`` se manda por compatibilidad; los servidores que no lo
    entienden lo ignoran.
    """
    content: list[dict[str, Any]] = []
    if text:
        content.append({"type": "text", "text": text})
    content.append(
        {
            "type": "image_url",
            "image_url": {"url": frame.to_data_url(), "detail": detail},
        }
    )
    return {"role": "user", "content": content}


def assistant_text(text: str) -> Message:
    """Turno del asistente, solo texto."""
    return {"role": "assistant", "content": text}


def assistant_tool_calls(event: ToolCallsEvent) -> Message:
    """Mensaje del asistente que pide ejecutar acciones.

    Se reenvía tal cual al continuar la conversación tras ejecutar las
    acciones. ``reasoning_content`` se incluye cuando el modelo lo devolvió:
    algunos servidores lo exigen para retomar el turno y el resto lo ignora.
    """
    message: Message = {
        "role": "assistant",
        "content": event.content or None,
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                },
            }
            for call in event.calls
        ],
    }
    if event.reasoning_content is not None:
        message["reasoning_content"] = event.reasoning_content
    return message


def tool_result(call_id: str, name: str, text: str) -> Message:
    """Resultado de una acción, de vuelta al modelo.

    Los resultados de herramientas solo aceptan texto: si la acción produjo una
    imagen, el orquestador la adjunta aparte con :func:`user_with_image`.
    """
    return {"role": "tool", "tool_call_id": call_id, "name": name, "content": text}


def has_image(message: Message) -> bool:
    """``True`` si el mensaje lleva alguna parte de tipo imagen."""
    content = message.get("content")
    if not isinstance(content, list):
        return False
    return any(isinstance(part, dict) and part.get("type") == "image_url" for part in content)


def strip_images(message: Message) -> Message:
    """Devuelve el mensaje sin imágenes, conservando solo su texto.

    Se usa con los turnos antiguos del historial: reenviar imágenes viejas
    dispara el prefill del modelo y añade latencia sin aportar nada.
    """
    content = message.get("content")
    if not isinstance(content, list):
        return dict(message)
    texts = [
        part["text"]
        for part in content
        if isinstance(part, dict) and part.get("type") == "text" and part.get("text")
    ]
    stripped = dict(message)
    stripped["content"] = "\n".join(texts)
    return stripped
