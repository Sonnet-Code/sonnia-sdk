"""Quién puede reconocer Sonia y sus huellas: el equipo de Sonnet Code, los ponentes del DevFest
y las personas conocidas que el equipo añade a mano.

- El equipo sale de ``assets/faces/staff.json`` (nombre, cargo y fotos: las de la
  web de Sonnet Code o fotos locales en ``cache/faces/fotos``).
- Los ponentes, de la agenda (``sonia.agenda``): su nombre, su charla y la foto
  que publica la web del DevFest.
- Las personas conocidas, de ``assets/faces/invitados.json`` (mismo formato que el
  equipo, con fotos locales recortadas a su cara).

De cada foto se guarda solo la huella (128 números) en
``cache/faces/huellas/caras.json``; la foto no se guarda. Nunca hay huellas de
visitantes: a ellos solo se les compara en memoria y se les olvida.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import httpx
import numpy as np

from sonia.agenda.schedule import Schedule
from sonia.faces.model import RECOGNIZER, FaceAnalyzer

__all__ = [
    "EnrollReport",
    "FaceBook",
    "Greetings",
    "Match",
    "Person",
    "enroll",
    "known_people",
    "load_greetings",
    "load_staff",
    "name_key",
    "speakers_from",
]

logger = logging.getLogger(__name__)

#: ``staff`` (equipo de Sonnet Code), ``speaker`` (ponente) o ``guest`` (persona conocida).
Kind = Literal["staff", "speaker", "guest"]

#: Lado mayor al que se reduce una foto de referencia antes de buscarle la cara.
REFERENCE_MAX_SIDE = 640
#: Largo máximo del título de una charla en la nota a Sonia (hay títulos de más de 100).
_TITLE_MAX_CHARS = 70
#: Fotos que se descargan a la vez al dar de alta.
_DOWNLOADS_AT_ONCE = 6
_STORE_VERSION = 1


@dataclass(frozen=True, slots=True)
class Person:
    """Alguien a quien Sonia puede reconocer."""

    id: str
    name: str
    kind: Kind
    #: Cargo en Sonnet Code o, de un ponente, su charla.
    role: str = ""
    #: De dónde salen sus huellas: URLs ``https://`` o rutas (relativas a ``cache/faces``).
    photos: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        """Cómo se le presenta a Sonia: «Brian James (del equipo de Sonnet Code, ...)»."""
        if self.kind == "staff":
            detail = "del equipo de Sonnet Code" + (f", {self.role}" if self.role else "")
        elif self.kind == "guest":
            detail = "persona conocida del equipo de Sonnet Code" + (
                f", {self.role}" if self.role else ""
            )
        else:
            detail = "ponente del DevFest" + (f": {self.role}" if self.role else "")
        return f"{self.name} ({detail})"

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "kind": self.kind, "role": self.role}


@dataclass(frozen=True, slots=True)
class Match:
    person: Person
    #: Similitud con su huella más parecida (coseno de SFace).
    score: float
    #: La de la segunda persona más parecida (0 si no hay otra).
    runner_up: float = 0.0


_KINDS: dict[str, Kind] = {"staff": "staff", "speaker": "speaker", "guest": "guest"}


def _slug(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")


def name_key(name: str) -> str:
    """El nombre sin acentos, mayúsculas ni signos: «Brian James» -> ``brian-james``."""
    return _slug(name)


@dataclass(frozen=True, slots=True)
class Greetings:
    """Contexto para saludar: el propio de algunas personas y el de cada grupo."""

    #: Por :func:`name_key` del nombre.
    people: dict[str, str] = field(default_factory=dict)
    #: Por grupo (``staff``, ``speaker`` o ``guest``): para quien no tiene uno propio.
    groups: dict[str, str] = field(default_factory=dict)

    def for_person(self, person: Person) -> tuple[str, bool]:
        """El saludo de ``person`` y si es suyo propio (o el de su grupo, o ninguno)."""
        own = self.people.get(name_key(person.name), "")
        if own:
            return own, True
        return self.groups.get(person.kind, ""), False


def load_greetings(path: Path) -> Greetings:
    """El contexto para saludar de ``saludos.json``.

    ``people`` es una lista de ``{"name": ..., "greeting": ...}`` con el nombre como
    sale en ``staff.json``, ``invitados.json`` o la agenda; ``groups``, el de cada
    grupo. Sin archivo, ninguno; los textos vacíos no cuentan.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Greetings()
    except (OSError, ValueError) as exc:
        logger.warning("No se pudo leer %s: %s", path, exc)
        return Greetings()
    if not isinstance(data, dict):
        return Greetings()
    people: dict[str, str] = {}
    for entry in data.get("people") or ():
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        text = " ".join(str(entry.get("greeting") or "").split())
        if name and text:
            people[name_key(name)] = text
    groups: dict[str, str] = {}
    raw_groups = data.get("groups")
    for kind in _KINDS:
        text = " ".join(str((raw_groups or {}).get(kind) or "").split())
        if isinstance(raw_groups, dict) and text:
            groups[kind] = text
    return Greetings(people, groups)


def load_staff(path: Path, *, kind: Kind = "staff") -> list[Person]:
    """El equipo de Sonnet Code de ``staff.json`` (o, con ``kind="guest"``, las personas
    conocidas de ``invitados.json``). Sin archivo o mal escrito, nadie."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if kind == "staff":
            logger.warning("No está la lista del equipo para reconocer caras: %s", path)
        return []
    except (OSError, ValueError) as exc:
        logger.warning("No se pudo leer %s: %s", path, exc)
        return []
    entries = data.get("people") if isinstance(data, dict) else None
    people: list[Person] = []
    for entry in entries or ():
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        photos = tuple(
            str(p).strip() for p in entry.get("photos") or () if isinstance(p, str) and p.strip()
        )
        if not name or not photos:
            logger.warning("Entrada sin nombre o sin fotos en %s: %s", path, entry)
            continue
        people.append(
            Person(
                id=f"{kind}:{_slug(name)}",
                name=name,
                kind=kind,
                role=str(entry.get("role") or "").strip(),
                photos=photos,
            )
        )
    return people


def speakers_from(schedule: Schedule | None) -> list[Person]:
    """Los ponentes de la agenda con foto, cada uno con su charla (o sus charlas).

    Una sesión con varios ponentes trae la foto de uno solo y no se sabe de cuál:
    no se da de alta a nadie por ella.
    """
    if schedule is None:
        return []
    talks: dict[str, list[str]] = {}
    photos: dict[str, list[str]] = {}
    names: dict[str, str] = {}
    for talk in schedule.talks:
        name = talk.speaker.strip()
        if not name or not talk.photo_url or " y " in name or "," in name:
            continue
        key = _slug(name)
        names.setdefault(key, name)
        title = talk.title.strip()
        if len(title) > _TITLE_MAX_CHARS:
            title = title[: _TITLE_MAX_CHARS - 1].rstrip(" ,.:;-") + "…"
        if title and f"«{title}»" not in talks.setdefault(key, []):
            talks[key].append(f"«{title}»")
        if talk.photo_url not in photos.setdefault(key, []):
            photos[key].append(talk.photo_url)
    return [
        Person(
            id=f"speaker:{key}",
            name=names[key],
            kind="speaker",
            role=" y ".join(talks.get(key, [])),
            photos=tuple(photos[key]),
        )
        for key in names
    ]


def known_people(staff: list[Person], speakers: list[Person]) -> list[Person]:
    """Equipo (y personas conocidas) con los ponentes. Si alguien de la lista da una charla, es
    una sola persona."""
    people = {_slug(p.name): p for p in staff}
    for speaker in speakers:
        key = _slug(speaker.name)
        mine = people.get(key)
        if mine is None:
            people[key] = speaker
            continue
        role = f"{mine.role}; ponente: {speaker.role}" if speaker.role else mine.role
        photos = mine.photos + tuple(p for p in speaker.photos if p not in mine.photos)
        people[key] = Person(mine.id, mine.name, mine.kind, role.strip("; "), photos)
    return list(people.values())


@dataclass(slots=True)
class EnrollReport:
    """Qué pasó al dar de alta: huellas nuevas, personas quitadas y fotos que fallaron."""

    added: int = 0
    removed: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)


class FaceBook:
    """Las huellas de las personas conocidas, en memoria y en ``caras.json``.

    No es seguro entre hilos: se modifica solo al dar de alta (antes de empezar
    a reconocer) y después solo se lee.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._people: dict[str, Person] = {}
        #: Por persona: de qué foto sale cada huella.
        self._prints: dict[str, dict[str, np.ndarray[Any, Any]]] = {}
        self._matrix: np.ndarray[Any, Any] = np.zeros((0, 128), dtype=np.float32)
        self._owners: list[str] = []

    def __len__(self) -> int:
        """Personas con al menos una huella."""
        return sum(1 for prints in self._prints.values() if prints)

    @property
    def people(self) -> list[Person]:
        return [self._people[pid] for pid, prints in self._prints.items() if prints]

    def has_print(self, person_id: str, source: str) -> bool:
        return source in self._prints.get(person_id, {})

    def saved_people(self, kind: Kind) -> list[Person]:
        """Los de ``kind`` que ya tienen huella, con sus fotos: para conservarlos tal cual."""
        return [
            Person(p.id, p.name, p.kind, p.role, tuple(self._prints[p.id]))
            for p in self.people
            if p.kind == kind
        ]

    # -- disco -------------------------------------------------------------

    def load(self) -> None:
        """Lee ``caras.json`` si existe y es del mismo modelo. No lanza nunca."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            logger.warning("No se pudo leer %s (se rehará): %s", self.path, exc)
            return
        if not isinstance(data, dict) or data.get("model") != RECOGNIZER.name:
            logger.info("Las huellas guardadas son de otro modelo: se rehacen")
            return
        for entry in data.get("people") or ():
            try:
                person = Person(
                    id=str(entry["id"]),
                    name=str(entry["name"]),
                    kind=_KINDS.get(str(entry.get("kind")), "staff"),
                    role=str(entry.get("role") or ""),
                )
                prints = {
                    str(source): _normalized(vector)
                    for source, vector in (entry.get("prints") or {}).items()
                }
            except (KeyError, TypeError, ValueError):
                continue
            self._people[person.id] = person
            self._prints[person.id] = {s: v for s, v in prints.items() if v is not None}
        self._rebuild()

    def save(self) -> None:
        """Escribe ``caras.json`` de golpe (archivo temporal y renombrado)."""
        people = []
        for pid, prints in self._prints.items():
            if not prints:
                continue
            entry = self._people[pid].to_json()
            entry["prints"] = {
                source: [round(float(x), 6) for x in vector] for source, vector in prints.items()
            }
            people.append(entry)
        data = {"version": _STORE_VERSION, "model": RECOGNIZER.name, "people": people}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        partial = self.path.with_name(self.path.name + ".part")
        partial.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        partial.replace(self.path)

    # -- altas y bajas -----------------------------------------------------

    def keep_only(self, people: list[Person]) -> list[str]:
        """Pone al día nombres y cargos y quita a quien ya no está en la lista. Devuelve los quitados.

        De cada persona se quitan también las huellas de fotos que ya no tiene
        (un ponente que cambió su foto en la web).
        """
        wanted = {p.id: p for p in people}
        removed = [self._people[pid].name for pid in self._people if pid not in wanted]
        for pid in list(self._people):
            if pid not in wanted:
                del self._people[pid]
                self._prints.pop(pid, None)
        for pid, person in wanted.items():
            self._people[pid] = person
            prints = self._prints.setdefault(pid, {})
            for source in [s for s in prints if s not in person.photos]:
                del prints[source]
        self._rebuild()
        return removed

    def adopt(self, other: FaceBook, people: list[Person]) -> int:
        """Copia de ``other`` las huellas de ``people`` que aquí faltan; devuelve cuántas.

        Es para las que trae la app (``cache/faces/huellas`` de la build): de alguien
        dado de alta con fotos locales, este equipo no tiene las fotos.
        """
        added = 0
        for person in people:
            theirs = other._prints.get(person.id, {})
            for source in person.photos:
                if source in theirs and not self.has_print(person.id, source):
                    self._people[person.id] = person
                    self._prints.setdefault(person.id, {})[source] = theirs[source]
                    added += 1
        if added:
            self._rebuild()
        return added

    def add_print(self, person: Person, source: str, embedding: np.ndarray[Any, Any]) -> None:
        self._people[person.id] = person
        vector = _normalized(embedding)
        if vector is not None:
            self._prints.setdefault(person.id, {})[source] = vector
            self._rebuild()

    def _rebuild(self) -> None:
        rows: list[np.ndarray[Any, Any]] = []
        owners: list[str] = []
        for pid, prints in self._prints.items():
            for vector in prints.values():
                rows.append(vector)
                owners.append(pid)
        self._matrix = (
            np.stack(rows).astype(np.float32) if rows else np.zeros((0, 128), dtype=np.float32)
        )
        self._owners = owners

    # -- reconocer -----------------------------------------------------------

    def best(self, embedding: np.ndarray[Any, Any]) -> Match | None:
        """La persona más parecida a ``embedding`` y la ventaja sobre la segunda, sin umbral."""
        if not self._owners:
            return None
        scores = self._matrix @ np.asarray(embedding, dtype=np.float32).reshape(-1)
        per_person: dict[str, float] = {}
        for owner, score in zip(self._owners, scores.tolist(), strict=True):
            if score > per_person.get(owner, -1.0):
                per_person[owner] = score
        ranked = sorted(per_person.items(), key=lambda item: item[1], reverse=True)
        pid, score = ranked[0]
        runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
        return Match(self._people[pid], float(score), float(runner_up))

    def match(
        self, embedding: np.ndarray[Any, Any], *, threshold: float, margin: float
    ) -> Match | None:
        """La persona reconocida, o ``None`` si nadie llega al umbral o hay dos demasiado parecidas."""
        found = self.best(embedding)
        if found is None or found.score < threshold or found.score - found.runner_up < margin:
            return None
        return found


def _normalized(vector: Any) -> np.ndarray[Any, Any] | None:
    array = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(array))
    if array.size != 128 or not np.isfinite(norm) or norm <= 0:
        return None
    return array / norm


async def _fetch(client: httpx.AsyncClient, source: str, base_dir: Path) -> bytes:
    if source.startswith(("https://", "http://")):
        response = await client.get(source)
        response.raise_for_status()
        return response.content
    return await asyncio.to_thread(_read_local, source, base_dir)


def _read_local(source: str, base_dir: Path) -> bytes:
    """Una foto local del equipo; las rutas relativas, desde ``cache/faces``."""
    path = Path(source).expanduser()
    return (path if path.is_absolute() else base_dir / path).read_bytes()


def _print_of(analyzer: FaceAnalyzer, data: bytes) -> tuple[np.ndarray[Any, Any] | None, str]:
    """La huella de la cara más grande de una foto de referencia, o por qué no la hay."""
    image = analyzer.decode(data, REFERENCE_MAX_SIDE)
    if image is None:
        return None, "la foto no se puede abrir"
    faces = analyzer.faces(image, limit=1)
    if not faces:
        return None, "no se le encuentra la cara"
    return faces[0].embedding, ""


async def enroll(
    book: FaceBook,
    people: list[Person],
    analyzer: FaceAnalyzer,
    *,
    base_dir: Path,
    timeout_s: float = 30.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> EnrollReport:
    """Saca la huella de las fotos que aún no la tienen y quita a quien ya no está.

    Solo descarga lo nuevo: con todo hecho, no toca la red. Una foto que falla
    (sin red, sin cara) no impide el resto; la persona sigue con las huellas que
    ya tuviera (por ejemplo, una foto local que solo está en el equipo donde se
    dio de alta).
    """
    report = EnrollReport(removed=book.keep_only(people))
    pending = [(p, s) for p in people for s in p.photos if not book.has_print(p.id, s)]
    if not pending:
        return report
    gate = asyncio.Semaphore(_DOWNLOADS_AT_ONCE)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_s, connect=min(10.0, timeout_s)),
        follow_redirects=True,
        headers={"User-Agent": "Sonia/1.0 (stand de Sonnet Code)"},
        transport=transport,
    ) as client:

        async def one(person: Person, source: str) -> None:
            try:
                async with gate:
                    data = await _fetch(client, source, base_dir)
                vector, why = await asyncio.to_thread(_print_of, analyzer, data)
            except (httpx.HTTPError, OSError) as exc:
                report.failed.append((person.name, f"{source}: {exc}"))
                return
            if vector is None:
                report.failed.append((person.name, f"{source}: {why}"))
                return
            book.add_print(person, source, vector)
            report.added += 1

        await asyncio.gather(*(one(person, source) for person, source in pending))
    return report
