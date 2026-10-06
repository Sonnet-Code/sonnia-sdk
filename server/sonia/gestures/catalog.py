"""Catálogo de gestos de hablar que manda Unity (``gesture_catalog``).

Cada gesto trae la ficha que Genies le da a su LLM (``llmMetadata``):
descripción física, intenciones, frecuencia de uso, duración, impacto,
intensidad y las reglas USE / DO NOT USE, más los tiempos del clip con los que
el director decide cuándo puede empezar el siguiente. Solo vienen los que
Unity sabe reproducir; se reemplaza entero en cada reconexión.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from sonia.ws import protocol as p

__all__ = ["FILLER_LIST", "Gesture", "GestureCatalog"]

#: Lista de Genies con los gestos de relleno casi neutros (asentir, mover un poco las manos).
FILLER_LIST = "Utility_NoImpact"

#: Lo que ocupa un gesto sin duración ni núcleo en su ficha.
DEFAULT_CORE_S = 2.0


@dataclass(frozen=True, slots=True)
class Gesture:
    """Un gesto del catálogo con su ficha."""

    name: str
    lists: tuple[str, ...] = ()
    duration: float = 0.0
    core_start: float = 0.0
    core_stop: float = 0.0
    critical_beat: float | None = None
    held: bool = False
    min_duration: float | None = None
    #: ``Standard``, ``Uncommon`` o ``Rare``.
    frequency: str = "Standard"
    #: ``Instant``, ``Short``, ``Long`` o vacío.
    timing: str = ""
    #: ``NoImpact``, ``LowImpact``, ``HighImpact`` o vacío.
    impact: str = ""
    intensity: int | None = None
    special: bool = False
    description: str = ""
    intents: tuple[str, ...] = ()
    #: Reglas «USE: ... DO NOT USE: ...» de la ficha (vacío si no las tiene).
    intent_description: str = ""
    tags: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, item: dict[str, Any]) -> Gesture:
        """Desde una entrada ya normalizada por ``protocol.parse_gesture_catalog``."""
        return cls(
            name=item["name"],
            lists=tuple(item.get("lists") or ()),
            duration=float(item.get("duration") or 0.0),
            core_start=float(item.get("core_start") or 0.0),
            core_stop=float(item.get("core_stop") or 0.0),
            critical_beat=item.get("critical_beat"),
            held=bool(item.get("held")),
            min_duration=item.get("min_duration"),
            frequency=str(item.get("frequency") or "Standard"),
            timing=str(item.get("timing") or ""),
            impact=str(item.get("impact") or ""),
            intensity=item.get("intensity"),
            special=bool(item.get("special")),
            description=str(item.get("description") or ""),
            intents=tuple(item.get("intents") or ()),
            intent_description=str(item.get("intent_description") or ""),
            tags=tuple(item.get("tags") or ()),
        )

    @property
    def filler(self) -> bool:
        """¿Es de relleno neutro (lista ``Utility_NoImpact``)?"""
        return FILLER_LIST in self.lists

    @property
    def core_s(self) -> float:
        """Hasta dónde llega el núcleo desde que empieza el clip: antes no puede empezar otro."""
        return self.core_stop or self.duration or DEFAULT_CORE_S


class GestureCatalog:
    """Los gestos que Unity puede reproducir, en el orden en que los mandó."""

    def __init__(
        self,
        gestures: list[Gesture],
        *,
        character: str = "",
        transition_s: float | None = None,
    ) -> None:
        self._gestures = {g.name: g for g in gestures}
        self._lower = {name.lower(): name for name in self._gestures}
        self.character = character
        self.transition_s = transition_s

    @classmethod
    def from_message(cls, msg: dict[str, Any]) -> GestureCatalog:
        """Desde un mensaje ``gesture_catalog`` de Unity (tolerante con lo que falte)."""
        parsed = p.parse_gesture_catalog(msg)
        return cls(
            [Gesture.from_dict(item) for item in parsed["gestures"]],
            character=parsed["character"],
            transition_s=parsed["transition_s"],
        )

    def __len__(self) -> int:
        return len(self._gestures)

    def __iter__(self) -> Iterator[Gesture]:
        return iter(self._gestures.values())

    def __contains__(self, name: object) -> bool:
        return name in self._gestures

    def get(self, name: str) -> Gesture | None:
        return self._gestures.get(name)

    def resolve(self, name: str) -> Gesture | None:
        """El gesto con ese nombre, sin mirar mayúsculas ni espacios de más (``None`` si no está)."""
        name = name.strip()
        exact = self._gestures.get(name)
        if exact is not None:
            return exact
        found = self._lower.get(name.lower())
        return self._gestures[found] if found is not None else None

    def fillers(self) -> list[Gesture]:
        return [g for g in self._gestures.values() if g.filler]
