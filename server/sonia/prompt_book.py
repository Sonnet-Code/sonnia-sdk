"""The texts the models receive, editable from the local panel.

Every long text a model gets is registered here as a :class:`PromptSpec`: the persona,
the knowledge base, the voice-model rules, the backend rules and the vision prompt. The
panel's prompt editor shows them, checks an edited version with :meth:`PromptBook.validate`
and saves it in the panel state file (``PANEL_STATE_FILE``). From then on Sonnia uses the
edited version instead of the built-in one, never both, until it is reset:

    from sonia.prompt_book import BOOK
    BOOK.text("backend_rules")          # the text in use
    BOOK.override("knowledge")          # the edited version, or None

An edited version that no longer validates (after an upgrade changed the placeholders a
template takes, for example) is ignored with a warning and the built-in text is used.

Changes apply without restarting the orchestrator: the conversation texts from the next
conversation (a new realtime session) and the vision prompt from the next photo.
"""

from __future__ import annotations

import logging
import string
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

__all__ = [
    "APPLIES_TEXT",
    "BOOK",
    "LIVE_RULE_FIELDS",
    "PROMPT_MAX_LEN",
    "Applies",
    "PromptBook",
    "PromptSpec",
    "placeholders",
    "use_knowledge_dirs",
]

logger = logging.getLogger(__name__)

#: Longest text the editor accepts. The knowledge base is the biggest piece.
PROMPT_MAX_LEN = 60_000

#: When an edit is noticed.
Applies = Literal["conversation", "request"]

APPLIES_TEXT: dict[str, str] = {
    "conversation": "from the next conversation",
    "request": "from the next photo",
}


@dataclass(frozen=True, slots=True)
class PromptSpec:
    """One text a model receives."""

    #: Stable id, the key in the panel state file.
    id: str
    #: What it is, in a few words, for the editor's list.
    title: str
    #: The built-in text. Lazy: called every time (the knowledge base reads files).
    default: Callable[[], str]
    #: Placeholders the code fills in (``{capabilities}``), without braces. Empty for a
    #: plain text.
    fields: tuple[str, ...] = ()
    #: Placeholders an edited version must keep.
    required: tuple[str, ...] = ()
    #: A template is filled in with ``str.format``; a plain text is used as is, braces
    #: and all.
    template: bool = False
    #: When an edit is noticed.
    applies: Applies = "conversation"
    #: Help for the editor: where the text goes and what each placeholder becomes.
    help: str = ""


def placeholders(text: str) -> tuple[list[str], list[str]]:
    """The placeholders of a ``str.format`` template and the problems that stop it from
    being one (a lone brace, ``{}``, ``{0}``, ``{a.b}``, a format spec)."""
    names: list[str] = []
    problems: list[str] = []
    try:
        parsed = list(string.Formatter().parse(text))
    except ValueError as exc:
        return [], [f"It is not a valid template ({exc}). Write a literal brace as {{{{ or }}}}."]
    for _, name, spec, conversion in parsed:
        if name is None:
            continue
        if not name.isidentifier():
            problems.append(f"{{{name}}} is not a placeholder: use a name like {{capabilities}}.")
        elif spec or conversion:
            problems.append(f"{{{name}}} cannot carry a format: write just {{{name}}}.")
        elif name not in names:
            names.append(name)
    return names, problems


class PromptBook:
    """The registered texts and the edited versions that validate."""

    def __init__(self) -> None:
        self._specs: dict[str, PromptSpec] = {}
        #: What the panel saved, as is (also ids this version does not register).
        self._raw: dict[str, str] = {}
        #: Of those, the ones that validate: the only ones used.
        self._valid: dict[str, str] = {}

    # -- registry ------------------------------------------------------------------------

    def register(self, spec: PromptSpec) -> PromptSpec:
        """Adds a text, or replaces the one with the same id."""
        if not spec.id.isidentifier() or spec.id != spec.id.lower():
            raise ValueError(f"invalid prompt id: {spec.id!r}")
        if spec.fields and not spec.template:
            raise ValueError(f"{spec.id}: only a template has placeholders")
        unknown = set(spec.required) - set(spec.fields)
        if unknown:
            raise ValueError(f"{spec.id}: required placeholders it does not take: {unknown}")
        self._specs[spec.id] = spec
        self._revalidate(spec.id)
        return spec

    def spec(self, prompt_id: str) -> PromptSpec:
        """The spec. ``KeyError`` if it is not registered."""
        return self._specs[prompt_id]

    def ids(self) -> tuple[str, ...]:
        return tuple(self._specs)

    def __contains__(self, prompt_id: object) -> bool:
        return prompt_id in self._specs

    # -- text in use ---------------------------------------------------------------------

    def default(self, prompt_id: str) -> str:
        """The built-in text."""
        return self._specs[prompt_id].default()

    def override(self, prompt_id: str) -> str | None:
        """The edited version in use, or ``None`` if the built-in text is used."""
        return self._valid.get(prompt_id)

    def text(self, prompt_id: str) -> str:
        """The text in use: the edited version if there is a valid one, else the built-in."""
        override = self._valid.get(prompt_id)
        return override if override is not None else self.default(prompt_id)

    # -- edits ---------------------------------------------------------------------------

    def validate(self, prompt_id: str, text: str) -> list[str]:
        """Why ``text`` cannot replace the text ``prompt_id`` (empty if it can)."""
        spec = self._specs.get(prompt_id)
        if spec is None:
            return [f"There is no prompt {prompt_id!r}."]
        if not text.strip():
            return ["It is empty. To go back to the built-in text, reset it."]
        problems: list[str] = []
        if len(text) > PROMPT_MAX_LEN:
            problems.append(
                f"It is too long: {len(text)} characters, the limit is {PROMPT_MAX_LEN}."
            )
        if not spec.template:
            return problems
        found, syntax = placeholders(text)
        problems.extend(syntax)
        extra = [name for name in found if name not in spec.fields]
        if extra:
            takes = ", ".join(f"{{{name}}}" for name in spec.fields)
            problems.append(
                "The code does not fill in "
                + ", ".join(f"{{{name}}}" for name in extra)
                + f". This text takes: {takes}. Write a literal brace as {{{{ or }}}}."
            )
        missing = [name for name in spec.required if name not in found]
        if missing:
            problems.append("It must keep " + ", ".join(f"{{{name}}}" for name in missing) + ".")
        return problems

    def load(self, edits: Mapping[str, Any] | None) -> list[str]:
        """Replaces every edited version (``{id: text}``, as saved). Returns a warning for
        each one that does not validate; those are kept but not used."""
        self._raw = {
            str(key): value for key, value in (edits or {}).items() if isinstance(value, str)
        }
        self._valid = {}
        warnings = [w for w in (self._revalidate(prompt_id) for prompt_id in self._raw) if w]
        for warning in warnings:
            logger.warning("Edited prompt ignored: %s", warning)
        return warnings

    def set(self, prompt_id: str, text: str) -> list[str]:
        """Uses ``text`` for ``prompt_id`` if it validates. Returns the problems if not, and
        then nothing changes."""
        problems = self.validate(prompt_id, text)
        if not problems:
            self._raw[prompt_id] = text
            self._valid[prompt_id] = text
        return problems

    def reset(self, prompt_id: str) -> bool:
        """Back to the built-in text. ``False`` if it was not edited."""
        self._valid.pop(prompt_id, None)
        return self._raw.pop(prompt_id, None) is not None

    def edits(self) -> dict[str, str]:
        """Every edited version, as saved (also the ignored ones)."""
        return dict(self._raw)

    def _revalidate(self, prompt_id: str) -> str:
        self._valid.pop(prompt_id, None)
        text = self._raw.get(prompt_id)
        if text is None or prompt_id not in self._specs:
            return ""
        problems = self.validate(prompt_id, text)
        if problems:
            return f"{prompt_id}: {' '.join(problems)}"
        self._valid[prompt_id] = text
        return ""

    # -- panel ---------------------------------------------------------------------------

    def catalog(self) -> list[dict[str, Any]]:
        """Every text for the panel's editor, with the text in use and the built-in one."""
        out: list[dict[str, Any]] = []
        for spec in self._specs.values():
            default = spec.default()
            saved = self._raw.get(spec.id)
            out.append(
                {
                    "id": spec.id,
                    "title": spec.title,
                    "help": spec.help,
                    "fields": list(spec.fields),
                    "required": list(spec.required),
                    "template": spec.template,
                    "applies": spec.applies,
                    "applies_text": APPLIES_TEXT[spec.applies],
                    "max_len": PROMPT_MAX_LEN,
                    "default": default,
                    "text": saved if saved is not None else default,
                    "edited": saved is not None,
                    "ignored": saved is not None and spec.id not in self._valid,
                }
            )
        return out


#: The orchestrator's book.
BOOK = PromptBook()


# -- the texts ---------------------------------------------------------------------------


def _const(module: str, name: str) -> Callable[[], str]:
    """A module constant, read when asked for (no import cycles)."""

    def read() -> str:
        import importlib

        return str(getattr(importlib.import_module(module), name))

    return read


_knowledge_dirs: list[Path] | None = None


def use_knowledge_dirs(directories: Sequence[str | Path] | None) -> None:
    """The folders whose files are the built-in knowledge base (``ASSETS_DIR`` and
    ``KNOWLEDGE_EXTRA_DIR``); ``None``: the bundled ``assets/knowledge``."""
    global _knowledge_dirs
    _knowledge_dirs = None if directories is None else [Path(d) for d in directories]


def _knowledge() -> str:
    from sonia.persona import load_knowledge

    return load_knowledge(_knowledge_dirs)


#: The placeholders ``build_live_instructions`` fills in ``LIVE_RULES`` (a test checks
#: they match).
LIVE_RULE_FIELDS = (
    "language",
    "setting_rule",
    "clock_rule",
    "camera_rule",
    "trivia_rule",
    "capabilities",
    "look_when",
    "moves_when",
    "emotion_when",
    "trivia_when",
    "search_when",
    "agenda_when",
    "no_delegate_chat",
)


def _specs() -> Iterable[PromptSpec]:
    yield PromptSpec(
        id="persona",
        title="Persona",
        default=_const("sonia.persona", "SYSTEM_PROMPT"),
        help=(
            "Who Sonnia is and how she speaks: the first thing in the voice model's "
            "instructions. Write her name as she should say it."
        ),
    )
    yield PromptSpec(
        id="knowledge",
        title="Knowledge base",
        default=_knowledge,
        help=(
            "What she knows about the place, the event and the people behind her. The "
            "built-in text is the files of assets/knowledge, one after another; an edited "
            "version replaces all of them, for both the voice model and the backend."
        ),
    )
    yield PromptSpec(
        id="live_rules",
        title="Voice model rules",
        default=_const("sonia.live.prompts", "LIVE_RULES"),
        fields=LIVE_RULE_FIELDS,
        required=("capabilities",),
        template=True,
        help=(
            "How the voice model takes turns, uses the camera and delegates to the backend. "
            "Each placeholder becomes a rule, or nothing, depending on the settings and the "
            "actions; {capabilities} is the list of backend tools and {language} the "
            'LANGUAGE setting ("Spanish").'
        ),
    )
    yield PromptSpec(
        id="backend_rules",
        title="Backend rules",
        default=_const("sonia.live.prompts", "BACKEND_PROMPT"),
        help=(
            "The instructions of the model that runs the actions. The default language, the "
            "date, the gallery ids and the knowledge base are added after it."
        ),
    )
    yield PromptSpec(
        id="vision",
        title="Vision",
        default=_const("sonia.live.vision", "NARRATOR_PROMPT"),
        applies="request",
        help=(
            "What the vision model is asked to describe in an automatic camera photo "
            "(VISION_ON_TURN_START or VISION_INTERVAL_SECONDS). The look action sends its "
            "photo to the backend instead."
        ),
    )


for _spec in _specs():
    BOOK.register(_spec)
