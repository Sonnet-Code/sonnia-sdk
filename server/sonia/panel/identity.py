"""Quién es esta Sonia para el panel: id estable, nombre y equipo.

Puede haber más de una Sonia conectada al panel de Cloudflare (por error o
mientras se cambia de equipo). Cada una se identifica con un id que combina el
nombre del equipo y unos caracteres aleatorios guardados en ``cache/``: dos
equipos nunca comparten id aunque se copie la carpeta entera de uno a otro.
"""

from __future__ import annotations

import logging
import platform
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sonia.config import PanelSettings

__all__ = ["InstanceIdentity", "load_identity", "summarize"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class InstanceIdentity:
    id: str
    name: str
    host: str


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:40] or "equipo"


def load_identity(settings: PanelSettings, *, host: str | None = None) -> InstanceIdentity:
    """Lee (o crea) el id de esta Sonia en ``cache/instance_id``."""
    host = host or platform.node() or "equipo"
    path = Path(settings.state_file).parent / "instance_id"
    suffix = ""
    try:
        stored = path.read_text(encoding="utf-8").strip()
        prefix, _, suffix = stored.rpartition("-")
        # Si la carpeta viene de otro equipo, el prefijo no coincide: id nuevo.
        if prefix != _slug(host) or not re.fullmatch(r"[0-9a-f]{6}", suffix):
            suffix = ""
    except OSError:
        pass
    if not suffix:
        suffix = secrets.token_hex(3)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{_slug(host)}-{suffix}\n", encoding="utf-8")
        except OSError as exc:
            logger.warning("No se pudo guardar el id de esta Sonia: %s", exc)
    return InstanceIdentity(
        id=f"{_slug(host)}-{suffix}",
        name=settings.instance_name.strip() or host,
        host=host,
    )


def summarize(identity: InstanceIdentity, status: dict[str, Any]) -> dict[str, Any]:
    """Resumen de una Sonia para ``/api/instances`` (la forma de ``docs/panel.md``)."""
    health = status.get("health") or {}
    issues = [
        str(item.get("label"))
        for item in health.values()
        if isinstance(item, dict) and item.get("ok") is False
    ]
    usage = status.get("usage") or {}
    return {
        "id": identity.id,
        "name": identity.name,
        "host": identity.host,
        "connected": True,
        "last_seen": int(time.time() * 1000),
        "mode": status.get("mode"),
        "state": status.get("state"),
        "engine": status.get("engine"),
        "healthy": not issues,
        "issues": issues,
        "cost_usd": usage.get("cost_usd"),
    }
