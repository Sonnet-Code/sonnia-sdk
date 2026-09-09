"""Definición única de las acciones del modelo (tool calling y MCP)."""

from __future__ import annotations

from sonia.actions.builtin import (
    HIDE_IMAGE,
    LOOK,
    SHOW_IMAGE,
    build_default_registry,
    hide_image,
    look,
    show_image,
)
from sonia.actions.gallery import Gallery
from sonia.actions.registry import ActionRegistry, ValidationError, validate_arguments

__all__ = [
    "HIDE_IMAGE",
    "LOOK",
    "SHOW_IMAGE",
    "ActionRegistry",
    "Gallery",
    "ValidationError",
    "build_default_registry",
    "hide_image",
    "look",
    "show_image",
    "validate_arguments",
]
