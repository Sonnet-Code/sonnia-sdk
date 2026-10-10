"""Registro de los prompts de Sonnia y de sus versiones guardadas en la nube.

Cada pieza (:class:`PromptSpec`) tiene su texto de la app, perezoso porque puede leer un
archivo (el conocimiento), y los marcadores ``{nombre}`` que admite. El ajuste compartido
``prompts`` del panel trae las versiones de la nube (``{id: texto}``, solo las cambiadas):
:meth:`PromptBook.set_overrides` se queda con las válidas y, para esas piezas, se usa SOLO
la de la nube, nunca las dos. Una versión que no valida (le falta un marcador, sobra uno que
el código no rellena, o le falta «JSON» a un juez) se ignora con un aviso en el registro, y
se usa la de la app.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

__all__ = [
    "BOOK",
    "PLACEHOLDER",
    "PROMPT_ID",
    "PROMPT_MAX_LEN",
    "Applies",
    "PromptBook",
    "PromptSpec",
    "register",
]

logger = logging.getLogger(__name__)

#: ``{nombre}``: un marcador que rellena el código (minúsculas, cifras y guion bajo). Las
#: llaves de los JSON de ejemplo (``{"visto": true}``) no lo son: llevan comillas.
PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")

#: Id de una pieza: ``grupo/nombre`` (hasta cuatro tramos), en minúsculas.
PROMPT_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*(/[a-z0-9][a-z0-9_.-]*){1,3}$")

#: Tope de una pieza guardada en la nube. La más grande (las reglas de GPT-Live) cabe de
#: sobra; todas juntas tienen que caber además en los ajustes compartidos de la nube.
PROMPT_MAX_LEN = 60_000

#: Cuándo se nota un cambio: en la próxima sesión de GPT-Live, en la próxima ronda de un
#: juego o en la próxima petición a su modelo (gestos, visión, juez).
Applies = Literal["sesion", "ronda", "peticion"]

APPLIES_TEXT: dict[str, str] = {
    "sesion": "desde la próxima conversación (sesión nueva de GPT-Live)",
    "ronda": "desde la próxima ronda o partida",
    "peticion": "desde la próxima petición a ese modelo",
}


@dataclass(frozen=True, slots=True)
class PromptSpec:
    """Una pieza de texto editable desde el panel."""

    #: ``grupo/nombre``, estable: es la clave en la nube (``juez/busqueda``).
    id: str
    #: Grupo en el panel: «Sonnia», «Conocimiento», «Conversación», «Juez»...
    group: str
    #: Qué es, en una línea, para el selector del panel.
    title: str
    #: El texto de la app. Perezoso: se llama cada vez (puede leer un archivo).
    default: Callable[[], str]
    #: Marcadores que el código rellena en esta pieza (sin llaves).
    fields: tuple[str, ...] = ()
    #: De esos, los que no pueden faltar en una versión de la nube.
    required: tuple[str, ...] = ()
    #: Textos que tiene que conservar una versión de la nube (``JSON`` en los jueces).
    must_contain: tuple[str, ...] = ()
    #: Cuándo se nota un cambio.
    applies: Applies = "sesion"
    #: Ayuda para el panel: qué rellena cada marcador, cuidados.
    help: str = ""
    max_len: int = PROMPT_MAX_LEN


class PromptBook:
    """Las piezas registradas y las versiones de la nube que valen. Seguro entre hilos."""

    def __init__(self) -> None:
        self._specs: dict[str, PromptSpec] = {}
        #: Lo que llegó de la nube, tal cual (también ids que esta app aún no registra).
        self._raw: dict[str, str] = {}
        #: De eso, lo que valida contra su pieza: lo único que se usa.
        self._valid: dict[str, str] = {}
        self._lock = threading.RLock()
        #: Registra todas las piezas la primera vez que se pide una (``load_specs``).
        self._loader: Callable[[], None] | None = None
        self._loaded = False
        self._warned: set[str] = set()

    def set_loader(self, loader: Callable[[], None]) -> None:
        """La función que registra todas las piezas; se llama una vez, al pedir la primera."""
        self._loader = loader
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded or self._loader is None:
            return
        with self._lock:
            if self._loaded:
                return
            self._loaded = True
            try:
                self._loader()
            except Exception:  # noqa: BLE001 - sin catálogo, cada módulo usa su texto de la app
                logger.exception("No se pudieron registrar los prompts editables")

    # -- registro ----------------------------------------------------------------------

    def register(self, spec: PromptSpec) -> PromptSpec:
        """Añade (o sustituye) una pieza. Se puede llamar en cualquier momento."""
        if not PROMPT_ID.match(spec.id):
            raise ValueError(f"Id de prompt no válido: {spec.id!r}")
        unknown = set(spec.required) - set(spec.fields)
        if unknown:
            raise ValueError(f"{spec.id}: marcadores obligatorios que no admite: {unknown}")
        with self._lock:
            self._specs[spec.id] = spec
            self._revalidate(spec.id)
        return spec

    def spec(self, prompt_id: str) -> PromptSpec:
        """La pieza. ``KeyError`` si no está registrada."""
        self._ensure_loaded()
        return self._specs[prompt_id]

    def ids(self) -> tuple[str, ...]:
        self._ensure_loaded()
        return tuple(self._specs)

    def __contains__(self, prompt_id: object) -> bool:
        self._ensure_loaded()
        return prompt_id in self._specs

    # -- texto en uso --------------------------------------------------------------------

    def default(self, prompt_id: str) -> str:
        """El texto de la app."""
        self._ensure_loaded()
        return self._specs[prompt_id].default()

    def text(self, prompt_id: str, fallback: str | None = None) -> str:
        """El texto en uso: la versión de la nube si la hay y vale; si no, la de la app.

        ``fallback`` es el texto de la app que tiene a mano quien llama: si la pieza no
        estuviera registrada (un fallo), se usa ese en vez de romper la conversación.
        """
        self._ensure_loaded()
        override = self._valid.get(prompt_id)
        if override is not None:
            return override
        spec = self._specs.get(prompt_id)
        if spec is None:
            if fallback is None:
                raise KeyError(prompt_id)
            if prompt_id not in self._warned:
                self._warned.add(prompt_id)
                logger.warning("Prompt sin registrar: %s (se usa el de la app)", prompt_id)
            return fallback
        return spec.default()

    def source(self, prompt_id: str) -> Literal["nube", "app"]:
        self._ensure_loaded()
        return "nube" if prompt_id in self._valid else "app"

    def render(self, prompt_id: str, /, fallback: str | None = None, **values: Any) -> str:
        """:meth:`text` con sus marcadores rellenos. Solo se tocan los que declara la pieza
        y vienen en ``values``; las demás llaves se quedan como están."""
        text = self.text(prompt_id, fallback)
        spec = self._specs.get(prompt_id)
        allowed = set(spec.fields) if spec is not None else set(values)

        def fill(match: re.Match[str]) -> str:
            name = match.group(1)
            if name in allowed and name in values:
                return str(values[name])
            return match.group(0)

        return PLACEHOLDER.sub(fill, text)

    # -- nube ----------------------------------------------------------------------------

    def validate(self, prompt_id: str, text: str) -> list[str]:
        """Por qué ``text`` no vale como versión de la pieza (vacío si vale)."""
        self._ensure_loaded()
        spec = self._specs.get(prompt_id)
        if spec is None:
            return [f"No hay ningún prompt «{prompt_id}» en esta Sonnia."]
        problems: list[str] = []
        if not text.strip():
            problems.append("Está vacío: para volver al de la app, usa «Volver al de la app».")
            return problems
        if len(text) > spec.max_len:
            problems.append(
                f"Es demasiado largo: {len(text)} caracteres y el tope es {spec.max_len}."
            )
        found = set(PLACEHOLDER.findall(text))
        extra = sorted(found - set(spec.fields))
        if extra:
            allowed = ", ".join(f"{{{name}}}" for name in spec.fields) or "ninguno"
            problems.append(
                "Lleva marcadores que el código no rellena: "
                + ", ".join(f"{{{name}}}" for name in extra)
                + f". Esta pieza admite: {allowed}."
            )
        missing = [name for name in spec.required if name not in found]
        if missing:
            problems.append(
                "Le faltan marcadores obligatorios: "
                + ", ".join(f"{{{name}}}" for name in missing)
                + "."
            )
        for needed in spec.must_contain:
            if needed not in text:
                problems.append(f"Tiene que seguir diciendo «{needed}» (lo necesita el código).")
        return problems

    def set_overrides(self, overrides: Mapping[str, str] | None) -> list[str]:
        """Las versiones de la nube (``{id: texto}``). Devuelve avisos de las que no valen."""
        self._ensure_loaded()
        with self._lock:
            self._raw = {
                str(key): value
                for key, value in (overrides or {}).items()
                if isinstance(value, str)
            }
            self._valid = {}
            warnings: list[str] = []
            for prompt_id in self._raw:
                warning = self._revalidate(prompt_id)
                if warning:
                    warnings.append(warning)
        for warning in warnings:
            logger.warning("Prompt de la nube ignorado: %s", warning)
        return warnings

    def overrides(self) -> dict[str, str]:
        """Lo que llegó de la nube, tal cual."""
        return dict(self._raw)

    def _revalidate(self, prompt_id: str) -> str:
        """Recalcula si la versión de la nube de ``prompt_id`` vale. Con el cerrojo cogido."""
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
        """Las piezas para el selector del panel, sin el texto (que se pide una a una)."""
        self._ensure_loaded()
        out: list[dict[str, Any]] = []
        for spec in self._specs.values():
            out.append(
                {
                    "id": spec.id,
                    "group": spec.group,
                    "title": spec.title,
                    "fields": list(spec.fields),
                    "required": list(spec.required),
                    "must_contain": list(spec.must_contain),
                    "applies": spec.applies,
                    "applies_text": APPLIES_TEXT[spec.applies],
                    "help": spec.help,
                    "source": self.source(spec.id),
                    "ignored": spec.id in self._raw and spec.id not in self._valid,
                }
            )
        return out


#: El registro de la app. Los módulos piden su texto con ``BOOK.text(id)`` o ``BOOK.render``.
BOOK = PromptBook()

#: Atajo para registrar piezas: ``register(PromptSpec(...))``.
register = BOOK.register
