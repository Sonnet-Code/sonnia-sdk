"""Cuándo decirle a Sonia que tiene delante a alguien conocido, sin agobiarla.

Dos caminos (docs/caras.md):

- **Revisión sola.** Con sesión abierta, el motor mira la cámara cada
  ``FACES_SCAN_SECONDS``. Quien sale en ``FACES_CONFIRM_SCANS`` revisiones de
  los últimos ``FACES_CONFIRM_SECONDS`` (seguidas o no) se le avisa a Sonia una
  vez, y de esa persona no se vuelve a avisar en ``FACES_COOLDOWN_MINUTES``:
  Brian pasa el día en el stand y no puede llenar la conversación de notas.
- **Sonia usa la cámara** (``look`` o la nota automática ``[Cámara]``). Se le dice
  quién sale en esa foto aunque se lo hayan dicho hace poco, y su plazo vuelve a
  empezar.

El plazo vale entre sesiones: cuando la conversación se reinicia (dos minutos
sin nadie) Sonia olvida la nota, pero no se repite hasta que pase el plazo o
ella mire.

Además se apunta quién ya pasó hoy por el stand (``visits.py``). La memoria es
por días, no por conversaciones (decisión de Jean del 7 de octubre de 2026): la
primera nota del día de alguien trae su contexto para saludarle
(``assets/faces/saludos.json``: el suyo propio o el de su grupo, como preguntar a
un ponente por su charla) y las siguientes de ese día dicen que ya pasó hoy, para
que Sonia no le salude otra vez como si fuera nuevo aunque la conversación se
haya reiniciado entre medias. Al día siguiente se empieza de cero.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from sonia.agenda.schedule import Schedule, Talk
from sonia.clock import Clock, spoken_date, spoken_hour
from sonia.config import FaceSettings
from sonia.faces.book import (
    EnrollReport,
    FaceBook,
    Match,
    Person,
    enroll,
    known_people,
    load_greetings,
    load_staff,
    name_key,
)
from sonia.faces.book import speakers_from as _speakers_from
from sonia.faces.model import FaceAnalyzer, FaceModel, ensure_models
from sonia.faces.visits import Visit, VisitLog, same_day_as
from sonia.types import CameraSource, Frame
from sonia.vision.camera import OpenCVCamera

__all__ = ["FaceWatcher", "Probe", "Sighting", "arrival_text", "join_labels", "known_text"]

logger = logging.getLogger(__name__)

#: Caras de una misma foto que se comparan como mucho (las más grandes). Con la foto a
#: resolución completa salen también las del fondo: un ponente puede estar detrás del visitante.
MAX_FACES = 6

#: Lo que vio la revisión sola hace este tiempo cuenta como «en la foto» de ``look``: la
#: revisión mira a resolución completa y ve más lejos que esa foto, reducida para la visión.
RECENT_S = 3.0

#: Una cara cuya persona más parecida se queda a menos de esto del umbral se apunta en el
#: registro («se parece a ... pero no llega»), una vez por minuto y persona como mucho: sin
#: esto, el registro no dice por qué no se reconoce a alguien (8 de octubre de 2026).
NEAR_MISS = 0.12
NEAR_MISS_LOG_S = 60.0

#: Calidad JPEG de la foto a resolución completa en la que se buscan caras.
CAPTURE_QUALITY = 90


@dataclass(frozen=True, slots=True)
class Sighting:
    """Alguien conocido en una foto."""

    match: Match
    #: Ancho de su cara en la foto, en píxeles.
    width: int

    @property
    def person_id(self) -> str:
        return self.match.person.id

    @property
    def label(self) -> str:
        return self.match.person.label


@dataclass(frozen=True, slots=True)
class Probe:
    """Una cara de la foto con su candidato, para calibrar (``sonia caras --probar``)."""

    width: int
    name: str
    score: float
    runner_up: float
    accepted: bool
    #: Por qué no se acepta: ``pequeña``, ``umbral`` o ``margen`` (vacío si se acepta).
    why: str = ""


def join_labels(sightings: list[Sighting]) -> str:
    """«A», «A y B», «A, B y C»."""
    labels = [s.label for s in sightings]
    if len(labels) <= 1:
        return "".join(labels)
    return ", ".join(labels[:-1]) + " y " + labels[-1]


def _seen_today(visit: Visit | None, now: datetime | None) -> bool:
    return visit is not None and now is not None and same_day_as(visit.last, now)


def _join_names(sightings: list[Sighting]) -> str:
    names = [s.match.person.name for s in sightings]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " y " + names[-1]


def _greeting_lines(sightings: list[Sighting], greetings: Mapping[str, str]) -> list[str]:
    """«Para saludar a Brian James: ...» de quien tenga contexto (los que vienen por primera vez hoy)."""
    lines: list[str] = []
    for sighting in sightings:
        text = greetings.get(sighting.person_id, "").strip()
        if text:
            end = "" if text[-1] in ".!?…" else "."
            lines.append(f"Para saludar a {sighting.match.person.name}: {text}{end}")
    return lines


#: Largo máximo del título de una charla cuando hay que nombrarla (un ponente con varias).
_TITLE_MAX_CHARS = 70


def _talks_of(schedule: Schedule, name: str) -> list[Talk]:
    """Las charlas de ``name`` en la agenda (también las que da con otros), por hora."""
    key = name_key(name)
    found: list[Talk] = []
    for talk in schedule.talks:
        speakers = re.split(r",|\s+y\s+", talk.speaker)
        if any(name_key(speaker) == key for speaker in speakers if speaker.strip()):
            found.append(talk)
    return found


def _day_phrase(moment: datetime, now: datetime) -> str:
    """«hoy», «mañana», «pasado mañana (el viernes 9 de octubre)», «hace 3 días (el ...)»...

    Contado en la zona de ``now`` y ya hecho: GPT-Live, con «el viernes 9» y la fecha
    de hoy en sus instrucciones, llegó a decir «mañana» un miércoles 7.
    """
    days = (moment.date() - now.date()).days
    named = {0: "hoy", 1: "mañana", -1: "ayer"}
    if days in named:
        return named[days]
    date = f"el {spoken_date(moment).rsplit(' de ', 1)[0]}"
    if days == 2:
        return f"pasado mañana ({date})"
    if days == -2:
        return f"anteayer ({date})"
    return f"dentro de {days} días ({date})" if days > 0 else f"hace {-days} días ({date})"


def _talk_line(name: str, talk: Talk, now: datetime, *, titled: bool) -> str:
    """Si la charla de ``name`` aún no ha pasado, es ahora o ya la dio: calculado aquí, no por Sonia."""
    tz = now.tzinfo
    start = talk.starts_at.astimezone(tz) if tz else talk.starts_at
    end = talk.ends_at.astimezone(tz) if tz else talk.ends_at
    title = talk.title.strip()
    if len(title) > _TITLE_MAX_CHARS:
        title = title[: _TITLE_MAX_CHARS - 1].rstrip(" ,.:;-") + "…"
    which = f"La charla «{title}» de {name}" if titled else f"La charla de {name}"
    when = f"{_day_phrase(start, now)} a {spoken_hour(start)}"
    if now < start:
        return f"{which} es {when}: todavía no la ha dado."
    if now < end:
        return f"{which} es ahora mismo, hasta {spoken_hour(end)}."
    mine = f"su charla «{title}»" if titled else "su charla"
    return f"{name} ya dio {mine} {when}."


def _talk_lines(
    sightings: list[Sighting], schedule: Schedule | None, now: datetime | None
) -> list[str]:
    """Cuándo es la charla de cada ponente de la foto: si ya la dio o no, que Sonia no lo adivine."""
    if schedule is None or now is None:
        return []
    lines: list[str] = []
    for sighting in sightings:
        name = sighting.match.person.name
        talks = _talks_of(schedule, name)
        lines.extend(_talk_line(name, talk, now, titled=len(talks) > 1) for talk in talks)
    return lines


def _already_here(
    sightings: list[Sighting], visits: Mapping[str, Visit], *, lead: str, relative: bool
) -> str:
    """Quien ya pasó hoy por el stand: que Sonia no le salude como si fuera la primera vez.

    ``relative`` encadena con «, que» (tras «Está delante de la cámara ...»).
    """
    joiner = ", que" if relative else ""
    if len(sightings) == 1:
        visit = visits[sightings[0].person_id]
        return (
            f"{lead}{joiner} ya pasó hoy por el stand (la primera vez, a "
            f"{spoken_hour(visit.day_first)}): no le saludes como si fuera la primera vez."
        )
    return (
        f"{lead}{joiner} ya pasaron hoy por el stand: no les saludes como si fuera la primera vez."
    )


def arrival_text(
    sightings: list[Sighting],
    *,
    now: datetime | None = None,
    visits: Mapping[str, Visit] | None = None,
    greetings: Mapping[str, str] | None = None,
    schedule: Schedule | None = None,
) -> str:
    """La nota de una revisión sola: quién acaba de llegar y quién ya pasó hoy por el stand.

    Sin ``now`` ni ``visits``, todos acaban de llegar. El contexto para saludar
    (``greetings``, por id de persona) solo va la primera vez del día. Con
    ``schedule``, de cada ponente se dice cuándo es su charla (si ya la dio o no).
    """
    visits = visits or {}
    greetings = greetings or {}
    new = [s for s in sightings if not _seen_today(visits.get(s.person_id), now)]
    back = [s for s in sightings if s not in new]
    parts: list[str] = []
    if new:
        verb = "Acaba" if len(new) == 1 else "Acaban"
        parts.append(f"{verb} de ponerse delante de la cámara {join_labels(new)}.")
        parts.extend(_talk_lines(new, schedule, now))
        parts.extend(_greeting_lines(new, greetings))
    if back:
        verb = "Está" if len(back) == 1 else "Están"
        lead = f"{verb} delante de la cámara {join_labels(back)}"
        parts.append(_already_here(back, visits, lead=lead, relative=True))
        parts.extend(_talk_lines(back, schedule, now))
    return " ".join(parts)


def known_text(
    sightings: list[Sighting],
    *,
    now: datetime | None = None,
    visits: Mapping[str, Visit] | None = None,
    greetings: Mapping[str, str] | None = None,
    schedule: Schedule | None = None,
) -> str:
    """Lo que se añade cuando Sonia usa la cámara: quién sale en la foto, si ya pasó hoy y,
    de un ponente, cuándo es su charla."""
    visits = visits or {}
    greetings = greetings or {}
    new = [s for s in sightings if not _seen_today(visits.get(s.person_id), now)]
    back = [s for s in sightings if s not in new]
    parts = [f"Personas conocidas en la foto: {join_labels(sightings)}."]
    if back:
        parts.append(_already_here(back, visits, lead=_join_names(back), relative=False))
    parts.extend(_talk_lines(sightings, schedule, now))
    parts.extend(_greeting_lines(new, greetings))
    return " ".join(parts)


AnalyzerFactory = Callable[[Path], FaceAnalyzer]


class FaceWatcher:
    """Reconoce caras conocidas en las fotos de la cámara y decide cuándo avisar.

    ``prepare`` (al arrancar, en segundo plano) baja los modelos y da de alta a
    quien falte; hasta que termina, ``ready`` es ``False`` y no se reconoce a nadie.
    """

    def __init__(
        self,
        settings: FaceSettings,
        *,
        staff_file: Path,
        analyzer_factory: AnalyzerFactory | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        models: bool = True,
        greetings_file: Path | None = None,
        guests_file: Path | None = None,
        bundled_book: Path | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._settings = settings
        self._folder = Path(settings.dir)
        self._staff_file = staff_file
        self._greetings_file = greetings_file
        self._guests_file = guests_file
        #: Las huellas que trae la app (solo en la app congelada): de quien se dio de alta
        #: con fotos locales, este equipo no tiene las fotos.
        self._bundled_book = bundled_book
        #: Hora de pared (con zona) para apuntar las visitas; la del stand en ``build_faces``.
        self._clock: Clock = clock or (lambda: datetime.now().astimezone())
        self._factory: AnalyzerFactory = analyzer_factory or FaceModel
        self._transport = transport
        #: Bajar los modelos de OpenCV (los tests con un analizador falso no los necesitan).
        self._models = models
        self.book = FaceBook(self._folder / "huellas" / "caras.json")
        #: Quién ya pasó por el stand (no viaja en la build: es de cada equipo).
        self.visits = VisitLog(self._folder / "visitas.json")
        #: Contexto para saludar por id de persona (``saludos.json``): el propio o el de su grupo.
        self._greetings: dict[str, str] = {}
        #: Quién tiene uno propio.
        self._own_greetings: set[str] = set()
        #: La agenda con la que se preparó y, si el motor la da, la de ahora (para las charlas).
        self._schedule: Schedule | None = None
        self._agenda: Callable[[], Schedule | None] | None = None
        self._analyzer: FaceAnalyzer | None = None
        #: Cuándo ha salido cada persona en las revisiones de la ventana de confirmación
        #: (``time.monotonic()``).
        self._hits: dict[str, list[float]] = {}
        #: Lo último que vio de cada persona la revisión sola, y cuándo (para ``look``).
        self._seen: dict[str, tuple[Sighting, float]] = {}
        #: Cuándo se apuntó en el registro que alguien se parecía sin llegar, por nombre.
        self._miss_logged: dict[str, float] = {}
        #: Cuándo se le avisó a Sonia de cada persona (``time.monotonic()``).
        self._noticed: dict[str, float] = {}
        self.last_report: EnrollReport | None = None

    @property
    def ready(self) -> bool:
        return self._analyzer is not None and len(self.book) > 0

    @property
    def scan_seconds(self) -> float:
        return max(0.0, self._settings.scan_seconds)

    @property
    def cooldown_s(self) -> float:
        return max(0.0, self._settings.cooldown_minutes) * 60.0

    @property
    def confirm_window_s(self) -> float:
        """Segundos en que tienen que caer las revisiones que confirman a alguien.

        Nunca menos de dos revisiones seguidas (con su retraso): mirar más despacio
        no puede dejar sin confirmar a quien sale en todas.
        """
        return max(self._settings.confirm_seconds, 2.0 * self.scan_seconds)

    # -- preparar ------------------------------------------------------------

    def follow_agenda(self, current: Callable[[], Schedule | None]) -> None:
        """Las notas de los ponentes dicen cuándo es su charla con la agenda de ahora (la del motor)."""
        self._agenda = current

    def _current_schedule(self) -> Schedule | None:
        schedule = self._agenda() if self._agenda is not None else None
        return schedule if schedule is not None else self._schedule

    async def prepare(self, schedule: Schedule | None) -> EnrollReport:
        """Modelos, huellas guardadas y alta de quien falte. Lanza si no hay modelos."""
        cfg = self._settings
        if schedule is not None:
            self._schedule = schedule
        await asyncio.to_thread(self.book.load)
        if self._models:
            downloaded = await ensure_models(
                self._folder / "modelos",
                timeout_s=max(cfg.download_timeout_seconds, 30.0),
                transport=self._transport,
            )
            if downloaded:
                logger.info("Modelos de caras descargados: %s", ", ".join(downloaded))
        analyzer = await asyncio.to_thread(self._factory, self._folder / "modelos")
        staff = await asyncio.to_thread(load_staff, self._staff_file)
        if self._guests_file is not None:
            staff += await asyncio.to_thread(load_staff, self._guests_file, kind="guest")
        if not cfg.speakers:
            speakers = []
        elif schedule is None:
            # Sin agenda (sin red ni copia) no se sabe quién habla: se quedan los que ya había.
            speakers = self.book.saved_people("speaker")
        else:
            speakers = _speakers_from(schedule)
        people = known_people(staff, speakers)
        await self._adopt_bundled(people)
        report = await enroll(
            self.book,
            people,
            analyzer,
            base_dir=self._folder,
            timeout_s=cfg.download_timeout_seconds,
            transport=self._transport,
        )
        # Siempre: también cambian cargos y títulos de charla, no solo las huellas.
        await asyncio.to_thread(self.book.save)
        for name, why in report.failed:
            logger.warning("Caras: sin huella nueva de %s (%s)", name, why)
        await asyncio.to_thread(self.visits.load)
        await self._load_greetings()
        self._analyzer = analyzer
        self.last_report = report
        known = self.book.people
        logger.info(
            "Caras: reconoce a %d personas (%d del equipo, %d ponentes, %d conocidas)%s",
            len(known),
            sum(1 for p in known if p.kind == "staff"),
            sum(1 for p in known if p.kind == "speaker"),
            sum(1 for p in known if p.kind == "guest"),
            f"; {report.added} huellas nuevas" if report.added else "",
        )
        return report

    async def _adopt_bundled(self, people: list[Person]) -> None:
        """En la app: las huellas que trae la build de quien aquí no tiene ni huella ni fotos."""
        bundled = self._bundled_book
        if bundled is None or bundled.resolve() == self.book.path.resolve():
            return
        source = FaceBook(bundled)
        await asyncio.to_thread(source.load)
        adopted = self.book.adopt(source, people)
        if adopted:
            logger.info("Caras: %d huellas tomadas de las que trae la app", adopted)

    async def _load_greetings(self) -> None:
        """Lee ``saludos.json`` y lo cruza con quien sabe reconocer (avisa de nombres sin nadie)."""
        self._greetings = {}
        self._own_greetings = set()
        if self._greetings_file is None:
            return
        loaded = await asyncio.to_thread(load_greetings, self._greetings_file)
        unknown = set(loaded.people)
        for person in self.book.people:
            text, own = loaded.for_person(person)
            unknown.discard(name_key(person.name))
            if text:
                self._greetings[person.id] = text
            if own:
                self._own_greetings.add(person.id)
        for key in sorted(unknown):
            logger.warning(
                "Caras: hay un saludo para «%s» pero nadie con ese nombre en el equipo, las "
                "personas conocidas ni la agenda (%s)",
                key,
                self._greetings_file,
            )

    @property
    def greetings(self) -> dict[str, str]:
        """Contexto para saludar por id de persona: el suyo propio o el de su grupo."""
        return dict(self._greetings)

    @property
    def own_greetings(self) -> set[str]:
        """Ids de quien tiene un saludo propio en ``saludos.json``."""
        return set(self._own_greetings)

    # -- reconocer -------------------------------------------------------------

    async def capture(self, camera: CameraSource) -> Frame | None:
        """La foto en la que buscar caras: a la resolución de la cámara (hasta
        ``FACES_ANALYSIS_WIDTH``), no la de 768 px de la visión.

        Reducida, una cara a dos metros se quedaba en unos 40 px y la de más de un metro
        no llegaba al mínimo; a 1920 px mide más del doble (docs/caras.md, 8-oct-2026).
        Las demás fuentes (Unity, OBS, la pantalla) dan la foto que tienen.
        """
        if isinstance(camera, OpenCVCamera):
            width = max(0, self._settings.analysis_width)
            return await camera.capture(max_width=width, quality=CAPTURE_QUALITY)
        return await camera.capture()

    async def identify(self, frame: Frame) -> list[Sighting]:
        """Las personas conocidas en ``frame`` (en un hilo). Sin preparar, nadie.

        De quien se queda cerca sin pasar queda una línea en el registro.
        """
        if not self.ready:
            return []
        sightings, misses = await asyncio.to_thread(self._identify_sync, frame.data)
        self._log_near_misses(misses)
        return sightings

    async def seen_in(self, frame: Frame) -> list[Sighting]:
        """Quién conocido sale en una foto que pidió Sonia, y quién vio la revisión sola hace un
        momento (``RECENT_S``): esa mira a resolución completa y ve más lejos que la foto."""
        found = {s.person_id: s for s in await self.identify(frame)}
        for sighting in self.recent():
            found.setdefault(sighting.person_id, sighting)
        return sorted(found.values(), key=lambda s: s.width, reverse=True)

    def recent(self, within_s: float = RECENT_S, now: float | None = None) -> list[Sighting]:
        """Quién reconoció la revisión sola en los últimos ``within_s`` segundos."""
        now = time.monotonic() if now is None else now
        return [s for s, at in self._seen.values() if now - at <= within_s]

    def _why_not(self, found: Match, width: int) -> str:
        """Por qué no se acepta: ``pequeña``, ``umbral`` o ``margen`` (vacío si se acepta)."""
        cfg = self._settings
        if width < cfg.min_face_px:
            return "pequeña"
        if found.score < cfg.threshold:
            return "umbral"
        if found.score - found.runner_up < cfg.margin:
            return "margen"
        return ""

    def _identify_sync(self, data: bytes) -> tuple[list[Sighting], list[Probe]]:
        analyzer = self._analyzer
        if analyzer is None:
            return [], []
        image = analyzer.decode(data)
        if image is None:
            return [], []
        cfg = self._settings
        best: dict[str, Sighting] = {}
        misses: list[Probe] = []
        for face in analyzer.faces(image, min_width=cfg.min_face_px, limit=MAX_FACES):
            found = self.book.best(face.embedding)
            if found is None:
                continue
            why = self._why_not(found, face.width)
            if why:
                if found.score >= cfg.threshold - NEAR_MISS:
                    name = found.person.name
                    misses.append(Probe(face.width, name, found.score, found.runner_up, False, why))
                continue
            seen = best.get(found.person.id)
            if seen is None or found.score > seen.match.score:
                best[found.person.id] = Sighting(found, face.width)
        return sorted(best.values(), key=lambda s: s.width, reverse=True), misses

    def _log_near_misses(self, misses: list[Probe]) -> None:
        """«Se parece a Jean Calderon pero no llega»: una vez por minuto y persona como mucho."""
        now = time.monotonic()
        for miss in misses:
            last = self._miss_logged.get(miss.name)
            if last is not None and now - last < NEAR_MISS_LOG_S:
                continue
            self._miss_logged[miss.name] = now
            if miss.why == "margen":
                logger.info(
                    "Caras: se parece a %s pero también a otra persona (%.2f frente a %.2f; "
                    "cara de %d px)",
                    miss.name,
                    miss.score,
                    miss.runner_up,
                    miss.width,
                )
            else:
                logger.info(
                    "Caras: se parece a %s pero no llega (%.2f de %.2f; cara de %d px)",
                    miss.name,
                    miss.score,
                    self._settings.threshold,
                    miss.width,
                )

    async def probe(self, frame: Frame) -> list[Probe]:
        """Todas las caras de la foto con su mejor candidato, se acepten o no (para calibrar)."""
        analyzer = self._analyzer
        if analyzer is None or not len(self.book):
            return []
        return await asyncio.to_thread(self._probe_sync, analyzer, frame.data)

    def _probe_sync(self, analyzer: FaceAnalyzer, data: bytes) -> list[Probe]:
        image = analyzer.decode(data)
        if image is None:
            return []
        result: list[Probe] = []
        for face in analyzer.faces(image, limit=MAX_FACES):
            found = self.book.best(face.embedding)
            if found is None:
                continue
            why = self._why_not(found, face.width)
            result.append(
                Probe(face.width, found.person.name, found.score, found.runner_up, not why, why)
            )
        return result

    # -- cuándo avisar ---------------------------------------------------------

    def due(self, sightings: list[Sighting], now: float | None = None) -> list[Sighting]:
        """De una revisión sola: a quién hay que avisar ya (confirmado y fuera de su plazo).

        Confirmado es salir en ``FACES_CONFIRM_SCANS`` revisiones de los últimos
        ``FACES_CONFIRM_SECONDS``, seguidas o no. Quien habla moviendo la cabeza pasa
        el umbral a ratos (de lado no se parece a su foto): con revisiones seguidas,
        Jean tardó 75 s en salir el 8 de octubre de 2026 (docs/caras.md).

        Los devueltos se dan por avisados: si el aviso no llega a la sesión, se
        llama a :meth:`retract`.
        """
        now = time.monotonic() if now is None else now
        window = self.confirm_window_s
        hits: dict[str, list[float]] = {}
        for pid, times in self._hits.items():
            recent = [t for t in times if now - t <= window]
            if recent:
                hits[pid] = recent
        for pid in {s.person_id for s in sightings}:
            hits.setdefault(pid, []).append(now)
        self._hits = hits
        self._seen = {pid: seen for pid, seen in self._seen.items() if now - seen[1] <= RECENT_S}
        for sighting in sightings:
            self._seen[sighting.person_id] = (sighting, now)
        confirm = max(1, self._settings.confirm_scans)
        fresh: list[Sighting] = []
        for sighting in sightings:
            pid = sighting.person_id
            if len(hits[pid]) < confirm:
                continue
            last = self._noticed.get(pid)
            if last is not None and now - last < self.cooldown_s:
                continue
            self._noticed[pid] = now
            fresh.append(sighting)
        return fresh

    def used(self, sightings: list[Sighting], now: float | None = None) -> list[Sighting]:
        """Sonia usó la cámara: se le dice quién sale aunque ya se le dijera, y su plazo empieza de nuevo."""
        now = time.monotonic() if now is None else now
        for sighting in sightings:
            self._noticed[sighting.person_id] = now
        return list(sightings)

    def arrival_note(self, sightings: list[Sighting]) -> str:
        """La nota de una revisión sola, con quién ya pasó hoy y los saludos propios.

        No apunta nada: cuando la nota llega a Sonia, :meth:`remember`.
        """
        return arrival_text(
            sightings,
            now=self._clock(),
            visits=self.visits.entries,
            greetings=self._greetings,
            schedule=self._current_schedule(),
        )

    def known_note(self, sightings: list[Sighting]) -> str:
        """Lo que se añade a una foto que pidió Sonia (``look`` o la nota ``[Cámara]``)."""
        return known_text(
            sightings,
            now=self._clock(),
            visits=self.visits.entries,
            greetings=self._greetings,
            schedule=self._current_schedule(),
        )

    async def remember(self, sightings: list[Sighting]) -> None:
        """A Sonia ya se le dijo que estaban delante: se apunta su visita y se guarda."""
        if not sightings:
            return
        now = self._clock()
        for sighting in sightings:
            self.visits.record(sighting.person_id, sighting.match.person.name, now)
        try:
            await asyncio.to_thread(self.visits.save)
        except OSError as exc:
            logger.warning("Caras: no se pudieron guardar las visitas: %s", exc)

    async def forget_visits(self) -> int:
        """Olvida quién ha pasado por el stand (``sonia caras --olvidar-visitas``)."""
        await asyncio.to_thread(self.visits.load)
        forgotten = self.visits.clear()
        await asyncio.to_thread(self.visits.save)
        return forgotten

    def retract(self, sightings: list[Sighting]) -> None:
        """El aviso de :meth:`due` no llegó: se podrá avisar de ellos en la próxima revisión."""
        for sighting in sightings:
            self._noticed.pop(sighting.person_id, None)

    def snapshot(self) -> dict[str, Any]:
        people = self.book.people
        return {
            "ready": self.ready,
            "people": len(people),
            "staff": sum(1 for p in people if p.kind == "staff"),
            "speakers": sum(1 for p in people if p.kind == "speaker"),
            "guests": sum(1 for p in people if p.kind == "guest"),
        }
