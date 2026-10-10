"""Acción ``check_agenda``: Sonia vuelve a mirar la agenda en la web del DevFest.

El código hace todo el trabajo: baja la página, la compara con la agenda que
Sonia tenía al empezar esta conversación (``ctx.extra["agenda_baseline"]``) y
devuelve los cambios ya escritos, más la hora de ahora y qué hay ahora y qué
viene (:mod:`sonia.agenda`). El modelo solo tiene que contarlo.

El motor deja la agenda en ``ctx.extra["agenda"]`` (un :class:`AgendaBook`).
"""

from __future__ import annotations

import asyncio
from typing import Any

from sonia.actions.builtin import screen_busy
from sonia.clock import spoken_now
from sonia.types import ActionContext, ActionResult, ActionSpec

#: Lo que se le pasa de la descripción de la charla (la de la web puede ser larga).
ABOUT_CHARS = 420

NO_AGENDA = (
    "Ahora mismo no tienes la agenda disponible. Remite a la web del evento "
    "(devfest.gdgsantodomingo.org) o al punto de registro."
)


async def check_agenda(ctx: ActionContext, arguments: dict[str, Any]) -> ActionResult:
    """Consulta la agenda ahora y cuenta qué cambió y qué hay ahora."""
    from sonia.agenda import AgendaBook

    book = ctx.extra.get("agenda")
    if not isinstance(book, AgendaBook):
        return ActionResult(text=NO_AGENDA)
    update = await book.refresh("pedida por Sonia")
    parts: list[str] = []
    if not update.ok:
        when = book.consulted()
        parts.append(
            "No se pudo consultar la web de la agenda ahora mismo"
            + (f"; lo que sabes es de la consulta del {when}." if when else ".")
        )
    else:
        changes = book.diff_from(ctx.extra.get("agenda_baseline"))
        if changes:
            parts.append(
                "Consultada ahora la agenda oficial. Cambios respecto a la que conocías: "
                + " ".join(changes)
            )
        else:
            parts.append(
                "Consultada ahora la agenda oficial: no ha cambiado nada respecto a la que "
                "conoces, sigue valiendo."
            )
    # La hora va siempre: GPT-Live solo tiene la de cuando empezó la conversación.
    parts.append(f"Hora de ahora: {spoken_now(book.now())}.")
    now = book.happening()
    if now:
        parts.append(now)
    if book.schedule is None:
        return ActionResult(text=NO_AGENDA)
    return ActionResult(text=" ".join(parts))


async def show_talk(ctx: ActionContext, arguments: dict[str, Any]) -> ActionResult:
    """Enseña en la pantalla la tarjeta de una charla de la agenda."""
    from sonia.agenda import AgendaBook
    from sonia.agenda.card import find_talk, render_talk_card
    from sonia.agenda.schedule import _span

    book = ctx.extra.get("agenda")
    if not isinstance(book, AgendaBook) or book.schedule is None:
        return ActionResult(text=NO_AGENDA)
    if ctx.avatar is None:
        return ActionResult(text="El avatar no está conectado.")
    busy = screen_busy(ctx, "la tarjeta de la charla")
    if busy:
        return ActionResult(text=busy)
    query = " ".join(str(arguments.get("charla") or "").split())
    talk = find_talk(book.schedule, query, now=book.now())
    if talk is None:
        return ActionResult(
            text=f"No encuentro en la agenda ninguna charla que sea «{query}». Pide el título o "
            "el nombre del ponente."
        )
    photo = await book.photos.get(talk.photo_url)
    png = await asyncio.to_thread(render_talk_card, talk, book.tz, photo=photo)
    await ctx.avatar.show_image(
        image_id=f"charla-{talk.id[:8]}", source="agenda", mime="image/png", data=png, caption=None
    )
    who = f" de {talk.speaker}" if talk.speaker else ""
    where = f" en el {talk.room}" if talk.room else ""
    about = " ".join(talk.description.split())
    if len(about) > ABOUT_CHARS:
        about = about[:ABOUT_CHARS].rsplit(" ", 1)[0] + "…"
    return ActionResult(
        text=(
            f"Mostrando ya en tu pantalla la tarjeta de la charla «{talk.title.strip().rstrip('.')}»"
            f"{who}, {_span(talk, book.tz)}{where}. Ya se ve: no ofrezcas enseñarla."
            + (f" De qué va, según la web: {about}" if about else "")
            + " Cuéntala en una o dos frases."
        )
    )


SHOW_TALK = ActionSpec(
    name="show_talk",
    description=(
        "Enseña en la pantalla de Sonia la tarjeta de una charla de la agenda: título, "
        "ponente con su foto, día, hora, sala y temas. Úsala cuando pregunten por una charla, "
        "un workshop o un ponente concretos. Se retira con hide_image o sola al rato."
    ),
    parameters={
        "type": "object",
        "properties": {
            "charla": {
                "type": "string",
                "description": "Título de la charla (o parte) o nombre del ponente, como en la agenda.",
            }
        },
        "required": ["charla"],
    },
    handler=show_talk,
)

CHECK_AGENDA = ActionSpec(
    name="check_agenda",
    description=(
        "Consulta ahora mismo la agenda oficial del DevFest en su web y dice qué ha cambiado "
        "respecto a la que conoce Sonia (horas, salas, ponentes, charlas nuevas o quitadas) y "
        "qué hay ahora y qué viene, con la hora exacta de ahora. Úsala cuando pregunten si "
        "cambió algo de la agenda, quieran confirmar una charla o un horario, pregunten qué hay "
        "ahora o qué viene después, o pregunten qué hora es."
    ),
    parameters={"type": "object", "properties": {}, "required": []},
    handler=check_agenda,
)
