"""Tarjeta de una charla para la pantalla de Sonia.

La dibuja el orquestador (Pillow) y va a Unity como cualquier imagen
(``show_image`` con ``source: agenda``): Sonia señala, sale en la franja alta y
se retira sola, sin nada nuevo en Unity. Lleva lo que la agenda sabe de la
charla: tipo, día, hora y sala, título, ponente con su foto de la web, temas,
nivel e idioma. Mismas letras que la pantalla del stand (Manrope).

También aquí: buscar una charla por lo que dice el backend (título o ponente) y
bajar la foto del ponente, con una caché en memoria.
"""

from __future__ import annotations

import io
import logging
import re
import unicodedata
from collections.abc import Iterable
from datetime import datetime, tzinfo
from difflib import SequenceMatcher
from typing import Any

import httpx

from sonia.agenda.schedule import Schedule, Talk, _day, _hm, _plain_text, _plain_title
from sonia.paths import BUNDLE_ROOT

__all__ = ["USER_AGENT", "PhotoCache", "find_talk", "render_talk_card"]

#: Cómo se presenta Sonia a la web del DevFest (agenda y fotos de ponentes).
USER_AGENT = "Sonnia/0.1 (asistente del stand de Sonnet Code, DevFest Santo Domingo)"

logger = logging.getLogger(__name__)

FONTS_DIR = BUNDLE_ROOT / "assets" / "fonts"

WIDTH, HEIGHT = 1600, 900
MARGIN = 72
NAVY = (22, 31, 64)
BORDER = (96, 140, 255)
WHITE = (255, 255, 255)
SOFT = (184, 196, 222)
ACCENT = (138, 180, 248)
CHIP = (40, 54, 104)
#: Colores de Google para los puntos de los temas.
DOTS = ((66, 133, 244), (234, 67, 53), (251, 188, 4), (52, 168, 83))

_KIND = {
    "keynote": "KEYNOTE",
    "panel": "PANEL",
    "workshop": "WORKSHOP",
    "break": "",
    "talk": "CHARLA",
}
_LEVELS = {
    "beginner": "Nivel básico",
    "intermediate": "Nivel intermedio",
    "advanced": "Nivel avanzado",
}
_ENGLISH = {"en", "english", "inglés", "ingles"}

#: Lo mínimo que se tiene que parecer el texto pedido a un título o un ponente.
MATCH_THRESHOLD = 0.47


# -- buscar la charla ------------------------------------------------------------


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


def _score(query: str, candidate: str) -> float:
    """Cuánto se parece: 1 si es igual, algo menos si lo contiene, y si no, el parecido."""
    if not query or not candidate:
        return 0.0
    if query == candidate:
        return 1.0
    if query in candidate:
        # «cierre» encaja más con «Cierre» que con «… al Cierre de Negocios».
        return 0.85 + 0.1 * len(query) / len(candidate)
    if len(candidate) > 6 and candidate in query:
        return 0.85
    return 0.85 * SequenceMatcher(None, query, candidate).ratio()


def find_talk(schedule: Schedule, query: str, now: datetime | None = None) -> Talk | None:
    """La sesión que mejor encaja con ``query``: su título (o parte), su ponente o su nombre.

    También la apertura, la keynote, un panel, el almuerzo o el cierre, por cómo se
    llaman en la agenda («Descanso con café», «Almuerzo»...). Si varias encajan igual
    (hay varios descansos), la próxima a ``now``; si ya pasaron todas, la primera.
    """
    wanted = _norm(query)
    scored: list[tuple[float, Talk]] = []
    for talk in schedule.talks:
        names = (talk.title, _plain_title(talk), talk.speaker)
        score = max(_score(wanted, _norm(name)) for name in names)
        scored.append((score, talk))
    if not scored:
        return None
    best = max(score for score, _ in scored)
    if best < MATCH_THRESHOLD:
        return None
    tied = [talk for score, talk in scored if score >= best - 1e-9]
    if now is not None:
        upcoming = [talk for talk in tied if talk.ends_at > now]
        if upcoming:
            return min(upcoming, key=lambda t: t.starts_at)
    return tied[0]


# -- foto del ponente -------------------------------------------------------------


class PhotoCache:
    """Fotos de ponentes ya bajadas (son públicas y pocas: caben en memoria)."""

    def __init__(
        self, *, timeout_s: float = 3.0, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._timeout = timeout_s
        self._transport = transport
        self._photos: dict[str, bytes | None] = {}

    async def get(self, url: str) -> bytes | None:
        """La foto de ``url``, o ``None`` si no hay o no se pudo bajar (no lo reintenta)."""
        if not url:
            return None
        if url in self._photos:
            return self._photos[url]
        data: bytes | None = None
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=self._timeout,
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT},
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.content[:5_000_000]
        except httpx.HTTPError as exc:
            logger.warning("No se pudo bajar la foto del ponente: %s", exc)
        self._photos[url] = data
        return data


# -- dibujo ------------------------------------------------------------------------


def _font(bold: bool, size: int) -> Any:
    from PIL import ImageFont

    name = "Manrope-ExtraBold.ttf" if bold else "Manrope-SemiBold.ttf"
    path = FONTS_DIR / name
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        logger.warning("Falta la fuente %s: se usa la de Pillow", path)
        return ImageFont.load_default(size)


def _wrap(draw: Any, text: str, font: Any, width: int, max_lines: int) -> list[str]:
    """Parte ``text`` en líneas que caben en ``width``; si sobra, la última acaba en «…»."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if current and draw.textlength(trial, font=font) > width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    if len(lines) <= max_lines:
        return lines or [""]
    kept = lines[:max_lines]
    last = kept[-1]
    while last and draw.textlength(last + "…", font=font) > width:
        last = last[:-1]
    kept[-1] = last.rstrip(" ,.;:-") + "…"
    return kept


def _avatar(photo: bytes | None, name: str, size: int) -> Any:
    """La foto en círculo o, sin foto, las iniciales."""
    from PIL import Image, ImageDraw, ImageOps

    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    mask = mask.resize((size, size), Image.Resampling.LANCZOS)
    picture: Any = None
    if photo:
        try:
            picture = Image.open(io.BytesIO(photo)).convert("RGB")
            picture = ImageOps.fit(picture, (size, size), Image.Resampling.LANCZOS)
        except Exception:  # noqa: BLE001 - una foto rara no tumba la tarjeta
            picture = None
    if picture is None:
        picture = Image.new("RGB", (size, size), DOTS[0])
        initials = "".join(part[0] for part in name.split()[:2]).upper() or "?"
        draw = ImageDraw.Draw(picture)
        font = _font(True, size // 3)
        box = draw.textbbox((0, 0), initials, font=font)
        draw.text(
            ((size - (box[2] - box[0])) / 2 - box[0], (size - (box[3] - box[1])) / 2 - box[1]),
            initials,
            font=font,
            fill=WHITE,
        )
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(picture, (0, 0), mask)
    return out


def _header(talk: Talk, tz: tzinfo) -> str:
    start = talk.starts_at.astimezone(tz)
    end = talk.ends_at.astimezone(tz)
    kind = _KIND.get(talk.kind, "CHARLA")
    if talk.plenary and kind:
        kind += " PARA TODOS"
    where = talk.room or ("Salón Principal" if talk.plenary else "")
    parts = [kind, _day(start).upper(), f"{_hm(start)} – {_hm(end)}"]
    if where:
        parts.append(where.upper())
    return "  ·  ".join(p for p in parts if p)


def _chips(talk: Talk) -> Iterable[str]:
    yield from talk.topics[:4]
    level = _LEVELS.get(talk.level.strip().lower())
    if level:
        yield level
    if talk.language.strip().lower() in _ENGLISH:
        yield "En inglés"


def render_talk_card(talk: Talk, tz: tzinfo, *, photo: bytes | None = None) -> bytes:
    """La tarjeta de ``talk`` en PNG (1600x900, se ve bien a 750 px de ancho)."""
    from PIL import Image, ImageDraw

    # Opaca y de esquinas rectas: el panel de imágenes de Unity no usa la transparencia
    # (unas esquinas redondeadas salían con triángulos negros).
    card = Image.new("RGBA", (WIDTH, HEIGHT), NAVY + (255,))
    draw = ImageDraw.Draw(card)
    draw.rectangle((0, 0, WIDTH - 1, HEIGHT - 1), outline=BORDER, width=6)
    inner = WIDTH - 2 * MARGIN

    # Cabecera: tipo, día, hora y sala.
    y = MARGIN - 6
    header_font = _font(True, 40)
    header = _header(talk, tz)
    while draw.textlength(header, font=header_font) > inner and header_font.size > 26:
        header_font = _font(True, header_font.size - 2)
    draw.text((MARGIN, y), header, font=header_font, fill=ACCENT)
    y += header_font.size + 34

    # Título, lo más grande que quepa en tres líneas.
    title = _plain_text(talk.title.strip().rstrip("."))
    if not talk.speaker and (talk.plenary or talk.kind == "break"):
        title = _plain_title(talk)
    for size in (84, 76, 68, 60, 54):
        title_font = _font(True, size)
        lines = _wrap(draw, title, title_font, inner, 3)
        if not lines[-1].endswith("…") or size == 54:
            break
    for line in lines:
        draw.text((MARGIN, y), line, font=title_font, fill=WHITE)
        y += int(title_font.size * 1.18)

    # Ponente con su foto, abajo.
    chips = list(_chips(talk))
    bottom = HEIGHT - MARGIN - (64 if chips else 0) - (24 if chips else 0)
    if talk.speaker:
        size = 176
        top = bottom - size
        card.alpha_composite(_avatar(photo, talk.speaker, size), (MARGIN, top))
        x = MARGIN + size + 40
        name_font = _font(True, 54)
        name = _wrap(draw, _plain_text(talk.speaker), name_font, WIDTH - x - MARGIN, 1)[0]
        role = _plain_text(talk.speaker_title.split(" | ")[0])
        role_font = _font(False, 38)
        role_lines = _wrap(draw, role, role_font, WIDTH - x - MARGIN, 2) if role else []
        block = name_font.size + (
            len(role_lines) * int(role_font.size * 1.25) + 10 if role_lines else 0
        )
        ty = top + (size - block) // 2
        draw.text((x, ty), name, font=name_font, fill=WHITE)
        ty += name_font.size + 10
        for line in role_lines:
            draw.text((x, ty), line, font=role_font, fill=SOFT)
            ty += int(role_font.size * 1.25)

    # Temas, nivel e idioma en píldoras.
    if chips:
        chip_font = _font(False, 32)
        x = MARGIN
        cy = HEIGHT - MARGIN - 64
        for i, chip in enumerate(chips):
            width = int(draw.textlength(chip, font=chip_font)) + 78
            if x + width > WIDTH - MARGIN:
                break
            draw.rounded_rectangle((x, cy, x + width, cy + 64), radius=32, fill=CHIP)
            dot = DOTS[i % len(DOTS)]
            draw.ellipse((x + 24, cy + 25, x + 38, cy + 39), fill=dot)
            draw.text((x + 52, cy + 13), chip, font=chip_font, fill=WHITE)
            x += width + 18

    out = io.BytesIO()
    card.convert("RGB").save(out, format="PNG")
    return out.getvalue()
