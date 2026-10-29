"""Single registry of the model's actions.

The same definition (`ActionSpec`) feeds the tools of the backend GPT-Live
delegates to (Responses API). This is also where arguments are validated against
each action's JSON Schema: we never raise to the orchestrator, an error is
returned as text for the model to read.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from sonia.types import ActionContext, ActionResult, ActionSpec

logger = logging.getLogger(__name__)


def _matches_type(value: Any, json_type: str) -> bool:
    """Does ``value`` match the schema's primitive type ``json_type``?"""
    match json_type:
        case "string":
            return isinstance(value, str)
        case "boolean":
            return isinstance(value, bool)
        case "integer":
            # ``bool`` is a subclass of ``int`` in Python, but it is not a JSON integer.
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
            # A type we cannot check: accept it.
            return True


class ValidationError(Exception):
    """The arguments do not match the action's JSON Schema."""


def validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Validates ``arguments`` against a simple object JSON Schema.

    Only required fields, primitive types and ``enum`` are checked. Unknown
    arguments are silently dropped (models often make them up and we do not
    want to break the turn over that).

    Raises ``ValidationError`` with a readable message.
    """
    if not isinstance(arguments, dict):
        raise ValidationError("the arguments must be a JSON object")

    properties = schema.get("properties") or {}
    if not isinstance(properties, dict):
        properties = {}
    required = schema.get("required") or []

    for name in required:
        if name not in arguments or arguments[name] is None:
            raise ValidationError(f"missing required argument '{name}'")

    cleaned: dict[str, Any] = {}
    for name, value in arguments.items():
        prop = properties.get(name)
        if not isinstance(prop, dict):
            # Unknown argument: ignored.
            continue

        if value is None and name not in required:
            continue

        declared = prop.get("type")
        types = [declared] if isinstance(declared, str) else list(declared or [])
        types = [t for t in types if isinstance(t, str)]
        if types and not any(_matches_type(value, t) for t in types):
            expected = " or ".join(types)
            raise ValidationError(
                f"argument '{name}' must be of type {expected}, not {type(value).__name__}"
            )

        # An integer is a valid number: normalize it to float.
        if types == ["number"] and isinstance(value, int) and not isinstance(value, bool):
            value = float(value)

        choices = prop.get("enum")
        if isinstance(choices, list) and choices and value not in choices:
            options = ", ".join(repr(c) for c in choices)
            raise ValidationError(f"argument '{name}' must be one of: {options}")

        cleaned[name] = value

    return cleaned


class ActionRegistry:
    """Collection of the actions available to the model."""

    def __init__(self) -> None:
        self._specs: dict[str, ActionSpec] = {}

    def register(self, spec: ActionSpec) -> None:
        """Adds (or replaces) an action."""
        if spec.name in self._specs:
            logger.warning("Replacing the already registered action '%s'", spec.name)
        self._specs[spec.name] = spec

    def get(self, name: str) -> ActionSpec | None:
        """Returns the action by name, or ``None`` if it does not exist."""
        return self._specs.get(name)

    def names(self) -> list[str]:
        """Names of the registered actions, in registration order."""
        return list(self._specs)

    def __len__(self) -> int:
        return len(self._specs)

    def __contains__(self, name: object) -> bool:
        return name in self._specs

    def __iter__(self) -> Iterator[ActionSpec]:
        return iter(self._specs.values())

    def to_responses_tools(self) -> list[dict[str, Any]]:
        """Translates the registry to the Responses API ``tools`` format.

        It is the one used by the backend GPT-Live delegates to: the function is
        flat, without Chat Completions' intermediate ``function`` object.
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

    async def execute(
        self, name: str, arguments: dict[str, Any] | None, ctx: ActionContext
    ) -> ActionResult:
        """Runs an action after validating its arguments.

        Never raises: any problem comes back as an ``ActionResult`` with the
        error as text, which is what the model sees as the result.
        """
        spec = self._specs.get(name)
        if spec is None:
            available = ", ".join(self._specs) or "none"
            logger.warning("The model asked for an unknown action: %r", name)
            return ActionResult(
                text=f"Error: the action '{name}' does not exist. Available: {available}."
            )

        try:
            cleaned = validate_arguments(spec.parameters, arguments or {})
        except ValidationError as exc:
            logger.warning("Invalid arguments for '%s': %s", name, exc)
            return ActionResult(text=f"Error: invalid arguments for '{name}': {exc}.")

        try:
            return await spec.handler(ctx, cleaned)
        except Exception as exc:  # noqa: BLE001 - an action must never bring the app down
            logger.exception("The action '%s' failed", name)
            return ActionResult(text=f"Error: the action '{name}' failed: {exc}.")
