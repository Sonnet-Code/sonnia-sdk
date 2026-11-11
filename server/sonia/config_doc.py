"""Generates ``docs/configuration.md`` from the settings model (``sonia/config.py``).

The reference is never written by hand: every setting, its environment variable, its
default and its description come from the code, so the document cannot drift. The
descriptions are the ``#:`` comments above each field (or the field docstring of the
class for the section text). A test checks that the committed file matches.

Run it from ``server/``::

    uv run --no-sync python -m sonia.config_doc > ../docs/configuration.md
"""

from __future__ import annotations

import ast
import inspect
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import AliasChoices
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings

from sonia import config
from sonia.paths import BUNDLE_ROOT, home

__all__ = ["SettingDoc", "SectionDoc", "collect", "render"]

#: Sections in the order they appear in the document, with the attribute of
#: ``Settings`` that holds them (``None`` = the top-level settings).
_SECTIONS: list[tuple[str | None, str]] = [
    ("live", "Voice and conversation (GPT-Live)"),
    ("llm", "Vision model"),
    ("vision", "Camera"),
    ("audio", "Microphone"),
    ("ws", "Avatar client WebSocket"),
    ("showcase", "Idle animation"),
    ("trivia", "Trivia"),
    ("panel", "Local control panel"),
    (None, "General"),
]


@dataclass(frozen=True)
class SettingDoc:
    """One documented setting."""

    variables: tuple[str, ...]
    type: str
    default: str
    description: str


@dataclass(frozen=True)
class SectionDoc:
    title: str
    intro: str
    settings: tuple[SettingDoc, ...]


def _field_comments(cls: type) -> dict[str, str]:
    """The ``#:`` comment block right above each annotated field of ``cls``."""
    source = inspect.getsource(cls)
    lines = source.splitlines()
    tree = ast.parse(source)
    class_node = tree.body[0]
    assert isinstance(class_node, ast.ClassDef)
    comments: dict[str, str] = {}
    for node in class_node.body:
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        block: list[str] = []
        index = node.lineno - 2
        while index >= 0 and lines[index].strip().startswith("#:"):
            block.insert(0, lines[index].strip()[2:].strip())
            index -= 1
        if block:
            comments[node.target.id] = " ".join(block)
    return comments


def _variables(cls: type[BaseSettings], name: str, field: FieldInfo) -> tuple[str, ...]:
    alias = field.validation_alias
    if isinstance(alias, AliasChoices):
        return tuple(str(choice) for choice in alias.choices)
    if isinstance(alias, str):
        return (alias,)
    prefix = str(cls.model_config.get("env_prefix", ""))
    return (f"{prefix}{name}".upper(),)


def _type_name(annotation: Any) -> str:
    text = annotation.__name__ if isinstance(annotation, type) else str(annotation)
    text = text.replace("typing.", "").removesuffix(" | None")
    match = re.fullmatch(r"Literal\[(.*)\]", text)
    if match:
        return " \\| ".join(part.strip().strip("'\"") for part in match.group(1).split(","))
    return {"str": "text", "int": "integer", "float": "number", "bool": "true/false"}.get(
        text, text.replace("|", "\\|")
    )


def _default(field: FieldInfo) -> str:
    value = field.get_default(call_default_factory=True)
    if value is None:
        return "(unset)"
    if value == "" or value == {}:
        return "(empty)"
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    # Paths under SONIA_HOME (or the repository) are shown relative to it, so the
    # document does not depend on the machine that generated it.
    roots = (
        (BUNDLE_ROOT / "assets", "<repo>/assets"),
        (home(), "<SONIA_HOME>"),
        (BUNDLE_ROOT, "<repo>"),
    )
    for root, label in roots:
        prefix = str(root)
        if text == prefix or text.startswith(prefix + "/") or text.startswith(prefix + "\\"):
            rest = text[len(prefix) :].replace("\\", "/")
            return f"{label}{rest}"
    return text


def _section(cls: type[BaseSettings], title: str, *, skip: set[str]) -> SectionDoc:
    comments = _field_comments(cls)
    settings = []
    for name, field in cls.model_fields.items():
        if name in skip:
            continue
        settings.append(
            SettingDoc(
                variables=_variables(cls, name, field),
                type=_type_name(field.annotation),
                default=_default(field),
                description=comments.get(name, ""),
            )
        )
    intro = inspect.cleandoc(cls.__doc__ or "") if cls.__doc__ else ""
    return SectionDoc(title=title, intro=intro, settings=tuple(settings))


def collect() -> list[SectionDoc]:
    """Every section of the settings model, in document order."""
    nested = {name for name, _ in _SECTIONS if name}
    sections = []
    for attribute, title in _SECTIONS:
        if attribute is None:
            sections.append(_section(config.Settings, title, skip=nested))
            continue
        annotation = config.Settings.model_fields[attribute].annotation
        assert isinstance(annotation, type) and issubclass(annotation, BaseSettings)
        sections.append(_section(annotation, title, skip=set()))
    return sections


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _markdown(description: str, variables: tuple[str, ...]) -> str:
    """The ``#:`` comment as Markdown: single backticks and no "``VAR``:" prefix."""
    text = description.replace("``", "`")
    for name in variables:
        text = text.removeprefix(f"`{name}`: ")
    return text[:1].upper() + text[1:]


def render() -> str:
    """The whole ``docs/configuration.md``."""
    out = [
        "# Configuration reference",
        "",
        "<!-- Generated by `python -m sonia.config_doc` from server/sonia/config.py. "
        "Do not edit by hand. -->",
        "",
        "Sonnia is configured only through environment variables. They are read from the "
        "process environment and from these files, the first one that defines a variable "
        "wins:",
        "",
        "1. `overrides.env` in `SONIA_HOME` (per-machine changes that win over the rest);",
        "2. `.env` at the repository root (copy it from `.env.example`);",
        "3. `.env` in the current directory.",
        "",
        "An empty variable is the same as an unset one: the default is used. "
        "`SONIA_HOME` is where the runtime data lives (`cache/`, `overrides.env`); "
        "it defaults to the repository root.",
        "",
        "Never commit `.env`: it holds your API keys.",
        "",
    ]
    for section in collect():
        out += [f"## {section.title}", ""]
        if section.intro:
            out += [" ".join(section.intro.split("\n\n")[0].split()).replace("``", "`"), ""]
        out += ["| Variable | Type | Default | Description |", "|---|---|---|---|"]
        for setting in section.settings:
            variables = "<br>".join(f"`{name}`" for name in setting.variables)
            default = f"`{_cell(setting.default)}`"
            if setting.default.startswith("("):
                default = setting.default
            out.append(
                f"| {variables} | {setting.type} | {default} | {_cell(_markdown(setting.description, setting.variables))} |"
            )
        out.append("")
    return "\n".join(out)


def default_path() -> Path:
    """Where the generated document lives in the repository."""
    return BUNDLE_ROOT / "docs" / "configuration.md"


def main() -> None:
    import sys

    sys.stdout.write(render())


if __name__ == "__main__":
    main()
