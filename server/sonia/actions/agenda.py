"""Acción ``check_agenda``: Sonia vuelve a mirar la agenda en la web del DevFest.

El código hace todo el trabajo: baja la página, la compara con la agenda que
Sonia tenía al empezar esta conversación (``ctx.extra["agenda_baseline"]``) y
devuelve los cambios ya escritos, más qué hay ahora y qué viene
(:mod:`sonia.agenda`). El modelo solo tiene que contarlo.

El motor deja la agenda en ``ctx.extra["agenda"]`` (un :class:`AgendaBook`).
"""

from __future__ import annotations

from typing import Any

from sonia.types import ActionContext, ActionResult, ActionSpec

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
    now = book.happening()
    if now:
        parts.append(now)
    if book.schedule is None:
        return ActionResult(text=NO_AGENDA)
    return ActionResult(text=" ".join(parts))


CHECK_AGENDA = ActionSpec(
    name="check_agenda",
    description=(
        "Consulta ahora mismo la agenda oficial del DevFest en su web y dice qué ha cambiado "
        "respecto a la que conoce Sonia (horas, salas, ponentes, charlas nuevas o quitadas) y "
        "qué hay ahora y qué viene. Úsala cuando pregunten si cambió algo de la agenda, quieran "
        "confirmar una charla o un horario, o pregunten qué hay ahora o qué viene después."
    ),
    parameters={"type": "object", "properties": {}, "required": []},
    handler=check_agenda,
)
