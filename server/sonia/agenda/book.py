"""La agenda que sabe Sonia: dónde se guarda, cuándo se vuelve a mirar y qué cambió.

``AgendaBook`` arranca con la última agenda descargada (``cache/agenda.json``) o
con la copia que trae la app (``assets/agenda/agenda.json``), así que Sonia sabe
la agenda aunque no haya red. Después la descarga de la web al arrancar y cada
``AGENDA_REFRESH_MINUTES``, y también cuando Sonia la consulta con la acción
``check_agenda``. Cada versión nueva se compara en código con la anterior
(:func:`~sonia.agenda.schedule.diff_agenda`) y los oyentes reciben solo los
cambios, ya escritos en frases.

Una descarga fallida, o una página que de repente trae menos de la mitad de las
sesiones, no borra lo que se sabía: se registra y se sigue con la anterior.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Any

import httpx

from sonia.agenda.card import USER_AGENT, PhotoCache
from sonia.agenda.schedule import Schedule, diff_agenda, happening, render_agenda
from sonia.agenda.source import AgendaError, parse_schedule_page
from sonia.clock import Clock, clock_for, spoken_date, spoken_time
from sonia.config import AgendaSettings

__all__ = ["AgendaBook", "AgendaUpdate"]

logger = logging.getLogger(__name__)


#: Con menos de esta parte de las sesiones de antes, la página nueva se toma por rota.
SUSPICIOUS_SHRINK = 0.5

#: Recibe los cambios de una versión nueva (frases ya escritas).
ChangeListener = Callable[[list[str]], Awaitable[None]]


@dataclass(slots=True)
class AgendaUpdate:
    """Lo que pasó en una consulta a la web."""

    ok: bool
    #: Cambios respecto a la versión anterior (vacío si no cambió nada o falló).
    changes: list[str] = field(default_factory=list)
    error: str = ""


class AgendaBook:
    """La agenda actual, su caché en disco y la consulta periódica a la web."""

    def __init__(
        self,
        settings: AgendaSettings,
        *,
        tz: tzinfo,
        fallback_file: Path | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._settings = settings
        self._tz = tz
        self._fallback_file = fallback_file
        self._transport = transport
        self._clock = clock or clock_for(tz)
        self._schedule: Schedule | None = None
        #: Cuándo se bajó de la web la versión actual (``None`` si es la copia de la app).
        self._fetched_at: datetime | None = None
        self._source = ""
        self._lock = asyncio.Lock()
        self._listeners: list[ChangeListener] = []
        self._loaded = False
        #: Fotos de los ponentes para las tarjetas de ``show_talk``.
        self.photos = PhotoCache(transport=transport)

    # -- estado ---------------------------------------------------------------

    @property
    def schedule(self) -> Schedule | None:
        return self._schedule

    @property
    def tz(self) -> tzinfo:
        """La zona horaria del stand, con la que se dicen las horas."""
        return self._tz

    @property
    def source(self) -> str:
        """De dónde viene la versión actual: ``web``, ``caché``, ``copia de la app`` o vacío."""
        return self._source

    @property
    def fetched_at(self) -> datetime | None:
        return self._fetched_at

    def on_change(self, listener: ChangeListener) -> None:
        self._listeners.append(listener)

    def consulted(self) -> str:
        """``el martes 6 de octubre de 2026 a las 19:05 (...)`` o vacío si nunca se bajó."""
        if self._fetched_at is None:
            return ""
        moment = self._fetched_at.astimezone(self._tz)
        return f"{spoken_date(moment)} a las {spoken_time(moment)}"

    def text(self) -> str:
        """La agenda para las instrucciones (vacío si no hay ninguna)."""
        if self._schedule is None:
            return ""
        return render_agenda(self._schedule, self._tz, consulted=self.consulted())

    def happening(self) -> str:
        """Qué hay ahora y qué viene, calculado con la hora del stand."""
        if self._schedule is None:
            return ""
        return happening(self._schedule, self._clock(), self._tz)

    def diff_from(self, baseline: Schedule | None) -> list[str]:
        """Cambios de ``baseline`` a la versión actual."""
        if baseline is None or self._schedule is None or baseline is self._schedule:
            return []
        return diff_agenda(baseline, self._schedule, self._tz)

    # -- disco ------------------------------------------------------------------

    async def load(self) -> None:
        """La última agenda guardada, o la de la app. Sin red; se puede llamar varias veces."""
        if self._loaded:
            return
        self._loaded = True
        cache = Path(self._settings.cache_file)
        for path, source in ((cache, "caché"), (self._fallback_file, "copia de la app")):
            if path is None:
                continue
            loaded = await asyncio.to_thread(_read_saved, path)
            if loaded is None:
                continue
            schedule, fetched_at = loaded
            if self._schedule is None:
                self._schedule, self._fetched_at, self._source = schedule, fetched_at, source
                logger.info(
                    "Agenda cargada de la %s: %d sesiones%s",
                    source,
                    len(schedule),
                    f" (consultada el {self.consulted()})" if fetched_at else "",
                )
            return

    async def _save(self, schedule: Schedule, fetched_at: datetime) -> None:
        data = {
            "fetched_at": fetched_at.isoformat(),
            "url": self._settings.url,
            **schedule.to_json(),
        }
        try:
            await asyncio.to_thread(_write_json, Path(self._settings.cache_file), data)
        except OSError as exc:
            logger.warning("No se pudo guardar la agenda en %s: %s", self._settings.cache_file, exc)

    # -- web --------------------------------------------------------------------

    async def _download(self) -> str:
        async with httpx.AsyncClient(
            transport=self._transport,
            timeout=self._settings.timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
        ) as client:
            response = await client.get(self._settings.url)
            response.raise_for_status()
            return response.text

    async def refresh(self, reason: str = "periódica") -> AgendaUpdate:
        """Baja la agenda de la web, la compara con la actual y avisa si cambió."""
        await self.load()
        if not self._settings.enabled:
            return AgendaUpdate(ok=False, error="la consulta a la web está desactivada")
        async with self._lock:
            try:
                html = await asyncio.wait_for(
                    self._download(), timeout=self._settings.timeout_seconds + 1
                )
                fresh = await asyncio.to_thread(parse_schedule_page, html)
            except (AgendaError, httpx.HTTPError, TimeoutError, OSError) as exc:
                text = str(exc) or type(exc).__name__
                logger.warning("No se pudo consultar la agenda (%s): %s", reason, text)
                return AgendaUpdate(ok=False, error=text)
            previous = self._schedule
            shrunk = previous is not None and len(fresh) < len(previous) * SUSPICIOUS_SHRINK
            if previous is not None and len(previous) >= 6 and shrunk:
                logger.warning(
                    "La agenda de la web trae %d sesiones y antes había %d: se ignora",
                    len(fresh),
                    len(previous),
                )
                return AgendaUpdate(ok=False, error="la página vino con muy pocas sesiones")
            changes = diff_agenda(previous, fresh, self._tz) if previous is not None else []
            now = self._clock()
            self._schedule, self._fetched_at, self._source = fresh, now, "web"
            await self._save(fresh, now)
        if changes:
            logger.info(
                "Agenda consultada (%s): %d cambios\n  %s",
                reason,
                len(changes),
                "\n  ".join(changes),
            )
            for listener in list(self._listeners):
                try:
                    await listener(changes)
                except Exception:  # noqa: BLE001 - un oyente roto no para la agenda
                    logger.exception("Error avisando de un cambio de agenda")
        else:
            logger.info("Agenda consultada (%s): %d sesiones, sin cambios", reason, len(fresh))
        return AgendaUpdate(ok=True, changes=changes)

    async def watch(self) -> None:
        """Consulta la web al arrancar y cada ``AGENDA_REFRESH_MINUTES``. Hasta que la cancelen."""
        await self.load()
        if not self._settings.enabled:
            logger.info(
                "Agenda sin consultar la web (AGENDA_URL=off): %s", self._source or "ninguna"
            )
            return
        interval = self._settings.refresh_minutes * 60
        while True:
            try:
                await self.refresh("al arrancar" if self._source != "web" else "periódica")
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - la agenda nunca tumba el orquestador
                logger.exception("Error consultando la agenda")
            if interval <= 0:
                return
            await asyncio.sleep(interval)


def _read_saved(path: Path) -> tuple[Schedule, datetime | None] | None:
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Agenda guardada ilegible en %s: %s", path, exc)
        return None
    if not isinstance(data, dict):
        return None
    schedule = Schedule.from_json(data)
    if not schedule.talks:
        return None
    fetched_at = None
    with contextlib.suppress(TypeError, ValueError):
        fetched_at = datetime.fromisoformat(str(data.get("fetched_at")))
    return schedule, fetched_at


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)
