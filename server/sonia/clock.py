"""La fecha y la hora del stand, en español y para leer en voz alta.

Sonia está en Santo Domingo aunque el equipo que la mueve tenga otra zona
horaria (el Mac de desarrollo está en España): la hora sale siempre de
``TIMEZONE`` (por defecto ``America/Santo_Domingo``), no de la del sistema.

Windows no trae la base de datos de zonas horarias que usa :mod:`zoneinfo`; para
Santo Domingo da igual, porque es UTC-4 todo el año (sin horario de verano desde
2000), y cualquier otra zona que falte cae en la hora del sistema con un aviso.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone, tzinfo

__all__ = [
    "Clock",
    "clock_for",
    "place_of",
    "resolve_timezone",
    "spoken_date",
    "spoken_now",
    "spoken_time",
]

logger = logging.getLogger(__name__)

#: Devuelve la hora actual con zona horaria (inyectable en los tests).
Clock = Callable[[], datetime]

#: Zonas sin horario de verano que se pueden resolver sin la base de datos.
_FIXED_OFFSETS = {
    "america/santo_domingo": timedelta(hours=-4),
    "utc": timedelta(0),
}

_WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
_MONTHS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


def resolve_timezone(name: str) -> tzinfo:
    """La zona ``name`` (IANA, como ``America/Santo_Domingo``). Nunca lanza."""
    name = name.strip()
    if not name:
        return _system_timezone()
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 - zona mal escrita o sin base de datos (Windows)
        offset = _FIXED_OFFSETS.get(name.lower())
        if offset is not None:
            return timezone(offset, name)
        logger.warning("Zona horaria desconocida %r: se usa la del sistema", name)
        return _system_timezone()


def _system_timezone() -> tzinfo:
    return datetime.now().astimezone().tzinfo or UTC


def clock_for(tz: tzinfo) -> Clock:
    """Reloj que da la hora actual en ``tz``."""
    return lambda: datetime.now(tz)


def place_of(timezone_name: str) -> str:
    """El sitio de una zona IANA para decirlo: ``America/Santo_Domingo`` -> ``Santo Domingo``."""
    tail = timezone_name.strip().rsplit("/", 1)[-1]
    return tail.replace("_", " ")


def spoken_date(moment: datetime) -> str:
    """``miércoles 7 de octubre de 2026``."""
    weekday = _WEEKDAYS[moment.weekday()]
    return f"{weekday} {moment.day} de {_MONTHS[moment.month - 1]} de {moment.year}"


def spoken_time(moment: datetime) -> str:
    """``19:05 (las 7:05 de la noche)``: la hora de 24 h y como se dice en el Caribe."""
    hour = moment.hour
    twelve = hour % 12 or 12
    if hour < 6:
        part = "de la madrugada"
    elif hour < 12:
        part = "de la mañana"
    elif hour == 12:
        part = "del mediodía"
    elif hour < 19:
        part = "de la tarde"
    else:
        part = "de la noche"
    article = "la" if twelve == 1 else "las"
    return f"{hour:02d}:{moment.minute:02d} ({article} {twelve}:{moment.minute:02d} {part})"


def spoken_now(moment: datetime, place: str = "") -> str:
    """``miércoles 7 de octubre de 2026, 19:05 (las 7:05 de la noche), hora de Santo Domingo``."""
    text = f"{spoken_date(moment)}, {spoken_time(moment)}"
    return f"{text}, hora de {place}" if place else text
