"""La agenda como datos: sesiones, salas, texto para Sonia y cambios entre versiones.

Todo es código determinista: Sonia no compara agendas ni calcula qué toca
ahora; recibe el texto ya hecho (:func:`render_agenda`, :func:`happening`) y la
lista de cambios en frases (:func:`diff_agenda`).
"""

from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Any

from sonia.clock import spoken_date

__all__ = [
    "Room",
    "Schedule",
    "Talk",
    "diff_agenda",
    "happening",
    "render_agenda",
]

logger = logging.getLogger(__name__)

#: Cargos de ponente más largos se recortan (algunos son una biografía entera).
SPEAKER_TITLE_MAX = 70

#: Nombres de los huecos sin charla tal como los escribe la web.
_BREAK_NAMES = {
    "break": "Descanso",
    "coffee break": "Descanso con café",
    "comida": "Almuerzo",
    "almuerzo": "Almuerzo",
    "lunch": "Almuerzo",
}

_ENGLISH = {"en", "english", "inglés", "ingles"}

#: Cómo se nombra un hueco para todos según su tipo.
_KIND_LABELS = {"keynote": "Keynote", "panel": "Panel", "workshop": "Workshop", "talk": "Charla"}


@dataclass(frozen=True, slots=True)
class Room:
    """Una sala (un track de la web): ``Salón Principal``, ``Track 1``, ``talks``."""

    name: str
    track: str = ""
    kind: str = ""

    def to_json(self) -> dict[str, str]:
        return {"name": self.name, "track": self.track, "kind": self.kind}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Room:
        return cls(
            str(data.get("name") or ""), str(data.get("track") or ""), str(data.get("kind") or "")
        )


@dataclass(frozen=True, slots=True)
class Talk:
    """Una sesión de la agenda. Las horas llevan zona horaria."""

    id: str
    title: str
    starts_at: datetime
    ends_at: datetime
    #: ``talk``, ``workshop``, ``keynote``, ``panel`` o ``break``.
    kind: str = "talk"
    #: Para todo el público (apertura, keynotes, paneles, descansos, cierre).
    plenary: bool = False
    room: str = ""
    speaker: str = ""
    speaker_title: str = ""
    topics: tuple[str, ...] = ()
    language: str = ""
    icon: str = ""
    #: Foto del ponente (la de la web) y nivel (``beginner``, ``intermediate``...).
    photo_url: str = ""
    level: str = ""
    #: De qué va (la descripción de la web). No va en las instrucciones: solo en ``show_talk``.
    description: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "starts_at": self.starts_at.isoformat(),
            "ends_at": self.ends_at.isoformat(),
            "kind": self.kind,
            "plenary": self.plenary,
            "room": self.room,
            "speaker": self.speaker,
            "speaker_title": self.speaker_title,
            "topics": list(self.topics),
            "language": self.language,
            "icon": self.icon,
            "photo_url": self.photo_url,
            "level": self.level,
            "description": self.description,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Talk:
        starts = datetime.fromisoformat(str(data["starts_at"]))
        ends = datetime.fromisoformat(str(data["ends_at"]))
        if starts.tzinfo is None or ends.tzinfo is None:
            raise ValueError("hora sin zona horaria")
        return cls(
            id=str(data["id"]),
            title=str(data.get("title") or "").strip(),
            starts_at=starts,
            ends_at=ends,
            kind=str(data.get("kind") or "talk"),
            plenary=bool(data.get("plenary")),
            room=str(data.get("room") or ""),
            speaker=str(data.get("speaker") or ""),
            speaker_title=str(data.get("speaker_title") or ""),
            topics=tuple(str(t) for t in data.get("topics") or ()),
            language=str(data.get("language") or ""),
            icon=str(data.get("icon") or ""),
            photo_url=str(data.get("photo_url") or ""),
            level=str(data.get("level") or ""),
            description=str(data.get("description") or ""),
        )


@dataclass(frozen=True, slots=True)
class Schedule:
    """Una versión de la agenda, con las sesiones en orden de hora."""

    talks: tuple[Talk, ...]
    rooms: tuple[Room, ...] = ()

    def __post_init__(self) -> None:
        order = {room.name: i for i, room in enumerate(self.rooms)}
        talks = sorted(
            self.talks, key=lambda t: (t.starts_at, order.get(t.room, len(order)), t.title)
        )
        object.__setattr__(self, "talks", tuple(talks))

    def __len__(self) -> int:
        return len(self.talks)

    def to_json(self) -> dict[str, Any]:
        return {
            "rooms": [room.to_json() for room in self.rooms],
            "talks": [talk.to_json() for talk in self.talks],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Schedule:
        rooms = tuple(Room.from_json(r) for r in data.get("rooms") or () if isinstance(r, dict))
        talks: list[Talk] = []
        for raw in data.get("talks") or ():
            try:
                talks.append(Talk.from_json(raw))
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Sesión de agenda ilegible en la copia guardada: %s", exc)
        return cls(tuple(talks), rooms)

    @property
    def main_room(self) -> str:
        """La sala de lo que es para todos: la primera de charlas."""
        for room in self.rooms:
            if room.kind != "workshops":
                return room.name
        return self.rooms[0].name if self.rooms else ""


# -- texto ---------------------------------------------------------------------


def _hm(moment: datetime) -> str:
    """``1:05`` (formato de 12 horas, como se dice)."""
    return f"{moment.hour % 12 or 12}:{moment.minute:02d}"


def _day_part(moment: datetime) -> str:
    hour = moment.hour
    if hour < 12:
        return "de la mañana"
    if hour == 12:
        return "del mediodía"
    return "de la tarde" if hour < 19 else "de la noche"


def _day(moment: datetime) -> str:
    """``viernes 9 de octubre``."""
    return spoken_date(moment).rsplit(" de ", 1)[0]


def _span(talk: Talk, tz: tzinfo) -> str:
    """``el viernes 9 de octubre, de 1:05 a 1:45 de la tarde``."""
    start = talk.starts_at.astimezone(tz)
    end = talk.ends_at.astimezone(tz)
    first, second = _day_part(start), _day_part(end)
    if first == second:
        hours = f"de {_hm(start)} a {_hm(end)} {first}"
    else:
        hours = f"de {_hm(start)} {first} a {_hm(end)} {second}"
    return f"el {_day(start)}, {hours}"


def _clean_caps(title: str) -> str:
    """``PANEL - AI`` -> ``Panel - AI``: la web escribe en mayúsculas los huecos sin charla."""
    words = []
    for i, word in enumerate(title.split()):
        if word.isupper() and len(word) > 3:
            word = word.capitalize() if i == 0 else word.lower()
        words.append(word)
    return " ".join(words)


def _plain_title(talk: Talk) -> str:
    """Nombre de un hueco sin ponente (apertura, descanso, panel...)."""
    known = _BREAK_NAMES.get(talk.title.strip().lower())
    if known:
        if known == "Descanso" and talk.icon == "☕":
            return "Descanso con café"
        return known
    return _clean_caps(talk.title.strip().rstrip("."))


def _plain_text(text: str) -> str:
    """Sin emojis ni símbolos: todo se lee en voz alta."""
    kept = "".join(c for c in text if unicodedata.category(c) not in ("So", "Cs", "Co"))
    return " ".join(kept.split())


def _speaker(talk: Talk) -> str:
    if not talk.speaker:
        return ""
    # «CEO | Founder | Software Architect | ...»: basta con el primero.
    title = _plain_text(talk.speaker_title.split(" | ")[0]).strip(" ,;|·-")
    if len(title) > SPEAKER_TITLE_MAX:
        title = title[:SPEAKER_TITLE_MAX].rsplit(" ", 1)[0].rstrip(" ,;|·-") + "…"
    return f"{talk.speaker} ({title})" if title else talk.speaker


def _quoted(talk: Talk) -> str:
    return f"«{talk.title.strip().rstrip('.')}»"


def _where(talk: Talk) -> str:
    if talk.kind == "workshop":
        return f"Workshop en el {talk.room}" if talk.room else "Workshop"
    return talk.room


def _line(talk: Talk, tz: tzinfo) -> str:
    start = talk.starts_at.astimezone(tz)
    end = talk.ends_at.astimezone(tz)
    hours = f"{_hm(start)}-{_hm(end)}"
    speaker = _speaker(talk)
    if not speaker and (talk.plenary or talk.kind == "break"):
        return f"- {hours} {_plain_title(talk)}, para todos."
    if talk.plenary:
        head = f"{_KIND_LABELS.get(talk.kind, 'Charla')} para todos"
    else:
        head = _where(talk) or "Charla"
    text = f"- {hours} {head}: {_quoted(talk)}"
    if speaker:
        text += f" — {speaker}"
    text += "."
    if talk.topics:
        text += " " + ", ".join(talk.topics) + "."
    if talk.language.strip().lower() in _ENGLISH:
        text += " En inglés."
    return text


def render_agenda(schedule: Schedule, tz: tzinfo, *, consulted: str = "") -> str:
    """La agenda en texto para las instrucciones, día por día."""
    if not schedule.talks:
        return ""
    lines = [
        "AGENDA DEL DEVFEST (de la web oficial devfest.gdgsantodomingo.org/schedule"
        + (f", consultada el {consulted}" if consulted else "")
        + "; si cambia algo durante el evento te llega un aviso con los cambios, que mandan "
        "sobre esta lista).",
        "Horas de Santo Domingo en formato de 12 horas: de 7 a 11 es por la mañana, las 12 es "
        "mediodía y de 1 a 6, por la tarde.",
    ]
    rooms = [r for r in schedule.rooms if r.name]
    if rooms:
        names = [f"{r.name} ({r.track})" if r.track else r.name for r in rooms]
        listed = ", ".join(names[:-1]) + f" y {names[-1]}" if len(names) > 1 else names[0]
        lines.append(f"Salas: {listed}. Lo que es para todos va en el {schedule.main_room}.")
    day = None
    for talk in schedule.talks:
        start = talk.starts_at.astimezone(tz)
        if start.date() != day:
            day = start.date()
            lines.append("")
            lines.append(f"## {_day(start).capitalize()}")
        lines.append(_line(talk, tz))
    return "\n".join(lines)


def _name(talk: Talk) -> str:
    """Cómo se nombra una sesión en un cambio: título y ponente."""
    if talk.speaker:
        return f"{_quoted(talk)} de {talk.speaker}"
    return f"«{_plain_title(talk)}»" if talk.plenary or talk.kind == "break" else _quoted(talk)


def _key(title: str) -> str:
    return " ".join(title.casefold().split())


def _pair_by_title(old: list[Talk], new: list[Talk]) -> list[tuple[Talk, Talk]]:
    """Empareja por título las sesiones que cambiaron de id (solo si el título es único)."""
    pairs: list[tuple[Talk, Talk]] = []
    for title in {_key(t.title) for t in old}:
        before = [t for t in old if _key(t.title) == title]
        after = [t for t in new if _key(t.title) == title]
        if len(before) == 1 and len(after) == 1:
            pairs.append((before[0], after[0]))
            old.remove(before[0])
            new.remove(after[0])
    return pairs


def _talk_changes(before: Talk, after: Talk, tz: tzinfo) -> list[str]:
    name = _name(after)
    changes: list[str] = []
    if _key(before.title) != _key(after.title):
        changes.append(f"{_name(before)} ahora se llama {_quoted(after)}.")
    if before.speaker != after.speaker:
        if before.speaker and after.speaker:
            changes.append(
                f"{_quoted(after)}: el ponente era {before.speaker} y ahora es {after.speaker}."
            )
        elif after.speaker:
            changes.append(f"{_quoted(after)} ahora la da {after.speaker}.")
        else:
            changes.append(f"{_quoted(after)} ya no tiene ponente anunciado.")
    if before.starts_at != after.starts_at or before.ends_at != after.ends_at:
        changes.append(
            f"{name} cambia de hora: era {_span(before, tz)} y ahora es {_span(after, tz)}."
        )
    if before.room != after.room and after.room:
        was = f"del {before.room} " if before.room else ""
        changes.append(f"{name} cambia de sala: {was}al {after.room}.")
    return changes


def diff_agenda(old: Schedule, new: Schedule, tz: tzinfo) -> list[str]:
    """Lo que cambió de ``old`` a ``new``, una frase por cambio y en orden de hora.

    Se compara por el id de cada sesión; si una desaparece y aparece otra con el
    mismo título, se toma por la misma (la web la ha vuelto a crear). Se ignoran
    descripciones, fotos y cargos: solo cuenta lo que le importa al visitante
    (título, ponente, día, hora y sala).
    """
    before = {t.id: t for t in old.talks}
    after = {t.id: t for t in new.talks}
    pairs = [(before[i], after[i]) for i in before.keys() & after.keys()]
    gone = [t for i, t in before.items() if i not in after]
    added = [t for i, t in after.items() if i not in before]
    pairs += _pair_by_title(gone, added)

    found: list[tuple[datetime, str]] = []
    for was, now in pairs:
        found.extend((now.starts_at, text) for text in _talk_changes(was, now, tz))
    for talk in gone:
        where = f" en el {talk.room}" if talk.room else ""
        found.append(
            (
                talk.starts_at,
                f"{_name(talk)} ya no está en la agenda (era {_span(talk, tz)}{where}).",
            )
        )
    for talk in added:
        where = f" en el {talk.room}" if talk.room else ""
        found.append(
            (talk.starts_at, f"Nueva en la agenda: {_name(talk)}, {_span(talk, tz)}{where}.")
        )
    found.sort()  # por hora y, a la misma hora, por texto: siempre el mismo orden
    return [text for _, text in found]


def _short(talk: Talk) -> str:
    """Una sesión en pocas palabras: dónde y qué."""
    if not talk.speaker and (talk.plenary or talk.kind == "break"):
        return f"{_plain_title(talk)}, para todos"
    where = "para todos" if talk.plenary else _where(talk)
    title = talk.title.strip().rstrip(".")
    if len(title) > 60:
        title = title[:60].rsplit(" ", 1)[0] + "…"
    who = f" de {talk.speaker}" if talk.speaker else ""
    return f"{where}: «{title}»{who}" if where else f"«{title}»{who}"


def happening(schedule: Schedule, now: datetime, tz: tzinfo) -> str:
    """Qué hay ahora y qué viene, ya calculado (vacío si el evento queda lejos)."""
    talks = schedule.talks
    if not talks:
        return ""
    first, last = talks[0].starts_at, max(t.ends_at for t in talks)
    if now >= last:
        return "El DevFest ya terminó."
    if now < first:
        start = first.astimezone(tz)
        days = (start.date() - now.astimezone(tz).date()).days
        when = "hoy" if days == 0 else "mañana" if days == 1 else f"dentro de {days} días"
        return f"El DevFest empieza {when}, el {_day(start)} a las {_hm(start)} {_day_part(start)}."
    current = [t for t in talks if t.starts_at <= now < t.ends_at]
    upcoming = [t for t in talks if t.starts_at > now]
    parts: list[str] = []
    if current:
        parts.append("Ahora mismo: " + "; ".join(_short(t) for t in current) + ".")
    else:
        parts.append("Ahora mismo no hay ninguna sesión.")
    if upcoming:
        soon = upcoming[0].starts_at
        batch = [t for t in upcoming if t.starts_at == soon]
        local = soon.astimezone(tz)
        day = "" if local.date() == now.astimezone(tz).date() else f"el {_day(local)} "
        parts.append(
            f"Lo siguiente, {day}a las {_hm(local)} {_day_part(local)}: "
            + "; ".join(_short(t) for t in batch)
            + "."
        )
    return " ".join(parts)
