"""Registro único de acciones del modelo.

La misma definición (`ActionSpec`) alimenta el tool calling de la API compatible
con OpenAI y el servidor MCP local. Aquí vive también la validación básica de
argumentos contra el JSON Schema de cada acción: nunca lanzamos hacia el
orquestador, un error se devuelve como texto para que el modelo lo lea.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from sonia.types import ActionContext, ActionResult, ActionSpec

logger = logging.getLogger(__name__)


def _matches_type(value: Any, json_type: str) -> bool:
    """¿Encaja ``value`` con el tipo primitivo ``json_type`` del schema?"""
    match json_type:
        case "string":
            return isinstance(value, str)
        case "boolean":
            return isinstance(value, bool)
        case "integer":
            # ``bool`` es subclase de ``int`` en Python, pero no es un entero JSON.
            return isinstance(value, int) and not isinstance(value, bool)
        case "number":
            return isinstance(value, int | float) and not isinstance(value, bool)
        case "null":
            return value is None
        case "array":
            return isinstance(value, list)
        case "object":
            return isinstance(value, dict)
        case _:
            # Tipo que no sabemos comprobar: lo damos por bueno.
            return True


class ValidationError(Exception):
    """Los argumentos no encajan con el JSON Schema de la acción."""


def validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Valida ``arguments`` contra un JSON Schema sencillo de objeto.

    Solo se comprueban campos requeridos, tipos primitivos y ``enum``. Los
    argumentos desconocidos se descartan en silencio (los modelos los inventan
    con frecuencia y no queremos romper el turno por eso).

    Lanza ``ValidationError`` con un mensaje legible en español.
    """
    if not isinstance(arguments, dict):
        raise ValidationError("los argumentos deben ser un objeto JSON")

    properties = schema.get("properties") or {}
    if not isinstance(properties, dict):
        properties = {}
    required = schema.get("required") or []

    for name in required:
        if name not in arguments or arguments[name] is None:
            raise ValidationError(f"falta el argumento requerido '{name}'")

    cleaned: dict[str, Any] = {}
    for name, value in arguments.items():
        prop = properties.get(name)
        if not isinstance(prop, dict):
            # Argumento desconocido: se ignora.
            continue

        if value is None and name not in required:
            continue

        declared = prop.get("type")
        types = [declared] if isinstance(declared, str) else list(declared or [])
        types = [t for t in types if isinstance(t, str)]
        if types and not any(_matches_type(value, t) for t in types):
            expected = " o ".join(types)
            raise ValidationError(
                f"el argumento '{name}' debe ser de tipo {expected}, no {type(value).__name__}"
            )

        # Un entero vale como número: lo normalizamos a float.
        if types == ["number"] and isinstance(value, int) and not isinstance(value, bool):
            value = float(value)

        choices = prop.get("enum")
        if isinstance(choices, list) and choices and value not in choices:
            opciones = ", ".join(repr(c) for c in choices)
            raise ValidationError(f"el argumento '{name}' debe ser uno de: {opciones}")

        cleaned[name] = value

    return cleaned


class ActionRegistry:
    """Colección de acciones disponibles para el modelo."""

    def __init__(self) -> None:
        self._specs: dict[str, ActionSpec] = {}

    def register(self, spec: ActionSpec) -> None:
        """Añade (o reemplaza) una acción."""
        if spec.name in self._specs:
            logger.warning("Se reemplaza la acción ya registrada '%s'", spec.name)
        self._specs[spec.name] = spec

    def get(self, name: str) -> ActionSpec | None:
        """Devuelve la acción por nombre, o ``None`` si no existe."""
        return self._specs.get(name)

    def names(self) -> list[str]:
        """Nombres de las acciones registradas, en orden de registro."""
        return list(self._specs)

    def __len__(self) -> int:
        return len(self._specs)

    def __contains__(self, name: object) -> bool:
        return name in self._specs

    def __iter__(self) -> Iterator[ActionSpec]:
        return iter(self._specs.values())

    def to_openai_tools(self) -> list[dict[str, Any]]:
        """Traduce el registro al formato ``tools`` de la API de OpenAI."""
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            }
            for spec in self._specs.values()
        ]

    def to_responses_tools(self) -> list[dict[str, Any]]:
        """Traduce el registro al formato ``tools`` de la API Responses.

        Es el que usa el backend al que delega GPT-Live: la función va plana,
        sin el objeto ``function`` intermedio de Chat Completions.
        """
        return [
            {
                "type": "function",
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            }
            for spec in self._specs.values()
        ]

    def to_mcp_tools(self) -> list[dict[str, Any]]:
        """Traduce el registro al formato de tools de MCP."""
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "inputSchema": spec.parameters,
            }
            for spec in self._specs.values()
        ]

    async def execute(
        self, name: str, arguments: dict[str, Any] | None, ctx: ActionContext
    ) -> ActionResult:
        """Ejecuta una acción validando antes sus argumentos.

        Nunca lanza: cualquier problema vuelve como ``ActionResult`` con el
        error en texto, que es lo que el modelo verá como resultado.
        """
        spec = self._specs.get(name)
        if spec is None:
            disponibles = ", ".join(self._specs) or "ninguna"
            logger.warning("El modelo pidió una acción desconocida: %r", name)
            return ActionResult(
                text=f"Error: la acción '{name}' no existe. Disponibles: {disponibles}."
            )

        try:
            cleaned = validate_arguments(spec.parameters, arguments or {})
        except ValidationError as exc:
            logger.warning("Argumentos inválidos para '%s': %s", name, exc)
            return ActionResult(text=f"Error: argumentos inválidos para '{name}': {exc}.")

        try:
            return await spec.handler(ctx, cleaned)
        except Exception as exc:  # noqa: BLE001 - la demo nunca debe caerse por una acción
            logger.exception("La acción '%s' falló", name)
            return ActionResult(text=f"Error: la acción '{name}' falló: {exc}.")
