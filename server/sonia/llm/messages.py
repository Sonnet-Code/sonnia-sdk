"""Constructores de mensajes en formato OpenAI.

El formato es el estándar de la API de chat completions, así que funciona con
cualquier servidor compatible. Con GPT-Live solo se usan para describir la
cámara.
"""

from __future__ import annotations

from typing import Any

from sonia.types import Frame, Message

__all__ = ["system", "user_text", "user_with_image"]


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
