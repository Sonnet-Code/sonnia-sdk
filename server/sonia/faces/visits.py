"""Quién del equipo o de los ponentes ya pasó hoy por el stand, para no saludarle dos veces como nuevo.

Por persona conocida se apunta cuándo se le dijo a Sonia que estaba delante de
la cámara: la primera vez de cada día, la última y cuántas veces. Va en
``cache/faces/visitas.json``, así que sobrevive a que la conversación se
reinicie (dos minutos sin nadie) y a reiniciar el orquestador: con eso la nota a
Sonia dice «ya pasó hoy por el stand» en vez de presentársela otra vez. Solo
cuenta el día: al siguiente se le saluda de nuevo como la primera vez.

Solo hay gente conocida (equipo y ponentes): de los visitantes no se apunta
nada. ``sonia caras --olvidar-visitas`` lo borra, por ejemplo tras las pruebas.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

__all__ = ["Visit", "VisitLog", "same_day_as"]

logger = logging.getLogger(__name__)

_STORE_VERSION = 1


def same_day_as(moment: datetime, now: datetime) -> bool:
    """¿``moment`` cae el mismo día que ``now``, contado en la zona horaria de ``now``?"""
    if moment.tzinfo is not None and now.tzinfo is not None:
        moment = moment.astimezone(now.tzinfo)
    return moment.date() == now.date()


@dataclass(frozen=True, slots=True)
class Visit:
    """Los avisos a Sonia de que una persona estaba delante de la cámara."""

    name: str
    #: El primero del día de :attr:`last`.
    day_first: datetime
    #: El último.
    last: datetime
    #: Cuántos en total.
    count: int

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "day_first": self.day_first.isoformat(),
            "last": self.last.isoformat(),
            "count": self.count,
        }

    @staticmethod
    def from_json(data: Any) -> Visit | None:
        if not isinstance(data, dict):
            return None
        try:
            return Visit(
                name=str(data.get("name") or ""),
                day_first=datetime.fromisoformat(str(data["day_first"])),
                last=datetime.fromisoformat(str(data["last"])),
                count=max(1, int(data.get("count") or 1)),
            )
        except (KeyError, TypeError, ValueError):
            return None


class VisitLog:
    """Las visitas por id de persona (``staff:brian-james``), en un JSON pequeño."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._visits: dict[str, Visit] = {}

    def __len__(self) -> int:
        return len(self._visits)

    @property
    def entries(self) -> dict[str, Visit]:
        return dict(self._visits)

    def get(self, person_id: str) -> Visit | None:
        return self._visits.get(person_id)

    def load(self) -> None:
        """Lee el archivo. Sin él o ilegible, nadie ha venido (con un aviso si estaba roto)."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._visits = {}
            return
        except (OSError, ValueError) as exc:
            logger.warning("Visitas ilegibles en %s; se empieza de cero: %s", self.path, exc)
            self._visits = {}
            return
        people = data.get("people") if isinstance(data, dict) else None
        visits: dict[str, Visit] = {}
        for person_id, entry in (people or {}).items():
            visit = Visit.from_json(entry)
            if visit is not None:
                visits[str(person_id)] = visit
        self._visits = visits

    def save(self) -> None:
        """Escribe el archivo entero (primero a uno temporal, para no dejarlo a medias)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": _STORE_VERSION,
            "people": {pid: visit.to_json() for pid, visit in sorted(self._visits.items())},
        }
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        temporary.replace(self.path)

    def record(self, person_id: str, name: str, when: datetime) -> None:
        """Se le dijo a Sonia que ``name`` estaba delante a la hora ``when``."""
        previous = self._visits.get(person_id)
        if previous is None:
            self._visits[person_id] = Visit(name, when, when, 1)
            return
        same_day = same_day_as(previous.last, when)
        self._visits[person_id] = Visit(
            name=name,
            day_first=previous.day_first if same_day else when,
            last=max(previous.last, when),
            count=previous.count + 1,
        )

    def clear(self) -> int:
        """Olvida todas las visitas; devuelve cuántas personas había."""
        forgotten = len(self._visits)
        self._visits = {}
        return forgotten
