"""Lee la agenda de la web del DevFest (devfest.gdgsantodomingo.org/schedule).

La página es de Next.js y trae los datos de la agenda dentro del HTML, en el
flujo de React Server Components (``self.__next_f.push([1, "..."])``): una
lista ``talkRows`` con cada sesión (horas en UTC, ponente, temas, track) y
otra ``trackRows`` con las salas. Aquí se juntan esos trozos, se sacan las dos
listas y se pasan a :class:`~sonia.agenda.schedule.Schedule`. Nada de modelos
de lenguaje ni de leer el HTML pintado.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from sonia.agenda.schedule import Room, Schedule, Talk

__all__ = ["AgendaError", "parse_schedule_page", "schedule_from_rows"]

#: Cada trozo del flujo RSC: ``self.__next_f.push([1,"<cadena JSON>"])``.
_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', re.S)


class AgendaError(Exception):
    """La página no se pudo leer como agenda (cambió de formato, vino vacía...)."""


def _flight_payload(html: str) -> str:
    parts: list[str] = []
    for chunk in _PUSH_RE.findall(html):
        try:
            parts.append(json.loads(f'"{chunk}"'))
        except json.JSONDecodeError:
            continue
    return "".join(parts)


def _array_after(text: str, key: str) -> list[Any] | None:
    """La lista JSON que sigue a ``"key":`` en ``text`` (la primera que se pueda leer)."""
    marker = f'"{key}":'
    decoder = json.JSONDecoder()
    start = text.find(marker)
    while start >= 0:
        at = start + len(marker)
        while at < len(text) and text[at].isspace():
            at += 1
        try:
            value, _ = decoder.raw_decode(text, at)
        except json.JSONDecodeError:
            value = None
        if isinstance(value, list):
            return value
        start = text.find(marker, start + 1)
    return None


def _when(value: Any) -> datetime:
    moment = datetime.fromisoformat(str(value))
    if moment.tzinfo is None:
        raise ValueError(f"hora sin zona horaria: {value!r}")
    return moment


def _speaker(raw: Any) -> tuple[str, str]:
    """Nombre y cargo del ponente (o de los ponentes, separados por «y»)."""
    people = raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) else []
    names = [str(p.get("name") or "").strip() for p in people if isinstance(p, dict)]
    names = [n for n in names if n]
    titles = [str(p.get("title") or "").strip() for p in people if isinstance(p, dict)]
    if not names:
        return "", ""
    joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " y " + names[-1]
    return joined, titles[0] if len(names) == 1 else ""


def schedule_from_rows(talk_rows: list[Any], track_rows: list[Any] | None = None) -> Schedule:
    """Las filas de la web (``talkRows`` y ``trackRows``) como :class:`Schedule`."""
    tracks: dict[str, Room] = {}
    ordered: list[tuple[float, Room]] = []
    for row in track_rows or ():
        if not isinstance(row, dict) or not row.get("id"):
            continue
        room = Room(
            name=str(row.get("room") or row.get("name") or "").strip(),
            track=str(row.get("name") or "").strip(),
            kind=str(row.get("kind") or "").strip(),
        )
        tracks[str(row["id"])] = room
        order = row.get("display_order")
        ordered.append((float(order) if isinstance(order, (int, float)) else 1e9, room))
    ordered.sort(key=lambda item: item[0])

    talks: list[Talk] = []
    for row in talk_rows:
        if not isinstance(row, dict):
            continue
        try:
            track = tracks.get(str(row.get("track_id") or ""))
            speaker, speaker_title = _speaker(row.get("speakers"))
            topics = row.get("topics") or ()
            kind = str(row.get("talk_type") or "talk")
            if kind == "talk" and track is not None and track.kind == "workshops":
                kind = "workshop"
            talks.append(
                Talk(
                    id=str(row["id"]),
                    title=str(row.get("title") or "").strip(),
                    starts_at=_when(row["starts_at"]),
                    ends_at=_when(row["ends_at"]),
                    kind=kind,
                    plenary=bool(row.get("is_plenary")),
                    room=str(row.get("room") or (track.name if track else "") or "").strip(),
                    speaker=speaker,
                    speaker_title=speaker_title,
                    topics=tuple(str(t) for t in topics if isinstance(t, str)),
                    language=str(row.get("language") or ""),
                    icon=str(row.get("icon") or ""),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    if not talks:
        raise AgendaError("la página no trae ninguna sesión legible")
    return Schedule(tuple(talks), tuple(room for _, room in ordered))


def parse_schedule_page(html: str) -> Schedule:
    """La agenda de la página HTML de la web del DevFest. Lanza :class:`AgendaError`."""
    payload = _flight_payload(html)
    talk_rows = _array_after(payload, "talkRows") if payload else None
    track_rows = _array_after(payload, "trackRows") if payload else None
    if talk_rows is None:
        # Por si un día viene como JSON normal dentro del HTML.
        talk_rows = _array_after(html, "talkRows")
        track_rows = track_rows or _array_after(html, "trackRows")
    if talk_rows is None:
        raise AgendaError("no se encontró la lista de sesiones (talkRows) en la página")
    return schedule_from_rows(talk_rows, track_rows)
