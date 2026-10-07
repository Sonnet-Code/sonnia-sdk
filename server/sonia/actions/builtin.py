"""Acciones integradas: `look`, `show_image`, `hide_image` y `play_animation`.

Las de la trivia y `check_agenda` viven en sus módulos y se registran aquí.

Los textos que devuelven vuelven al modelo como resultado de la tool call, así
que son cortos y en español: el modelo los usa para decidir qué decir en voz.
Ninguna acción lanza; los problemas se cuentan en el texto.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sonia.actions.gallery import Gallery
from sonia.actions.registry import ActionRegistry
from sonia.types import ActionContext, ActionResult, ActionSpec, Frame

logger = logging.getLogger(__name__)

#: Id reservado que significa "la última captura de la cámara".
CAMERA_ID = "camera"

#: Tope de espera de una captura pedida por el modelo. Un driver de cámara
#: colgado no puede dejar el turno en ``thinking`` para siempre: mejor decirle
#: al modelo que no se pudo mirar y seguir la conversación.
CAPTURE_TIMEOUT_S = 3.0

NO_CAMERA = "No hay cámara disponible."
NO_AVATAR = "El avatar no está conectado."


# ---------------------------------------------------------------------------
# look
# ---------------------------------------------------------------------------

LOOK_SPEC_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
}


async def _capture(ctx: ActionContext) -> Frame | None:
    """Captura de la cámara del contexto y la guarda en ``ctx.last_frame``."""
    if ctx.camera is None:
        return None
    try:
        frame = await asyncio.wait_for(ctx.camera.capture(), timeout=CAPTURE_TIMEOUT_S)
    except TimeoutError:
        logger.warning("La cámara no respondió en %.1f s a la acción", CAPTURE_TIMEOUT_S)
        return None
    if frame is not None:
        ctx.last_frame = frame
    return frame


async def look(ctx: ActionContext, arguments: dict[str, Any]) -> ActionResult:
    """Toma una captura fresca y se la devuelve al modelo como imagen."""
    if ctx.camera is None:
        return ActionResult(text=NO_CAMERA)
    frame = await _capture(ctx)
    if frame is None:
        return ActionResult(text="No pude tomar la captura de la cámara.")
    return ActionResult(text="Captura tomada." + await _known_faces(ctx, frame), image=frame)


async def _known_faces(ctx: ActionContext, frame: Frame) -> str:
    """Quién del equipo de Sonnet Code o de los ponentes sale en la foto (docs/caras.md).

    Sonia usa la cámara: se le dice aunque se le dijera hace poco, y el plazo
    para volver a avisarla de esa persona empieza de nuevo. También si ya pasó
    hoy por el stand (para no saludarle como nuevo) y, si no, su saludo propio.
    """
    from sonia.faces import FaceWatcher

    faces = ctx.extra.get("faces")
    if not isinstance(faces, FaceWatcher):
        return ""
    try:
        sightings = faces.used(await faces.identify(frame))
    except Exception as exc:  # noqa: BLE001 - sin caras, la foto sigue valiendo
        logger.warning("No se pudieron reconocer caras en la foto: %s", exc)
        return ""
    if not sightings:
        return ""
    logger.info(
        "Caras en la foto de look: %s",
        ", ".join(f"{s.match.person.name} ({s.match.score:.2f})" for s in sightings),
    )
    text = faces.known_note(sightings)
    await faces.remember(sightings)
    return " " + text


# ---------------------------------------------------------------------------
# show_image
# ---------------------------------------------------------------------------

SHOW_IMAGE_SPEC_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "image_id": {
            "type": "string",
            "description": (
                "Id de una imagen de la galería local (nombre de archivo sin extensión) "
                "o 'camera' para mostrar la última captura de la cámara."
            ),
        },
        "caption": {
            "type": "string",
            "description": "Pie de texto opcional, corto.",
        },
    },
    "required": ["image_id"],
}


async def show_image(ctx: ActionContext, arguments: dict[str, Any]) -> ActionResult:
    """Muestra una imagen en el panel de la escena de Unity."""
    image_id: str = arguments["image_id"]
    caption: str | None = arguments.get("caption") or None

    if ctx.avatar is None:
        return ActionResult(text=NO_AVATAR)

    if image_id == CAMERA_ID:
        frame = ctx.last_frame
        if frame is None:
            frame = await _capture(ctx)
        if frame is None:
            return ActionResult(text="No hay ninguna captura de la cámara que mostrar.")
        await ctx.avatar.show_image(
            image_id=CAMERA_ID,
            source="camera",
            mime=frame.mime,
            data=frame.data,
            caption=caption,
        )
        return ActionResult(text="Mostrando la última captura de la cámara.")

    gallery = Gallery(ctx.gallery_dir)
    loaded = gallery.load(image_id)
    if loaded is None:
        disponibles = ", ".join(gallery.ids()) or "ninguna"
        return ActionResult(
            text=f"No existe la imagen '{image_id}' en la galería. Disponibles: {disponibles}."
        )

    data, mime = loaded
    await ctx.avatar.show_image(
        image_id=image_id,
        source="gallery",
        mime=mime,
        data=data,
        caption=caption,
    )
    return ActionResult(text=f"Mostrando la imagen '{image_id}'.")


# ---------------------------------------------------------------------------
# hide_image
# ---------------------------------------------------------------------------

HIDE_IMAGE_SPEC_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
}


async def hide_image(ctx: ActionContext, arguments: dict[str, Any]) -> ActionResult:
    """Retira el panel de imágenes."""
    if ctx.avatar is None:
        return ActionResult(text=NO_AVATAR)
    await ctx.avatar.hide_image()
    return ActionResult(text="Panel de imágenes retirado.")


# ---------------------------------------------------------------------------
# Definiciones
# ---------------------------------------------------------------------------

LOOK = ActionSpec(
    name="look",
    description=(
        "Mira por la cámara del stand y toma una foto para verla. Úsala cuando te "
        "pregunten qué ves o cuando te enseñen algo y no tengas una imagen reciente."
    ),
    parameters=LOOK_SPEC_PARAMETERS,
    handler=look,
)

SHOW_IMAGE = ActionSpec(
    name="show_image",
    description=(
        "Muestra una imagen en tu pantalla, junto a ti. Usa un id de la galería local "
        "o 'camera' para enseñar la última foto de la cámara."
    ),
    parameters=SHOW_IMAGE_SPEC_PARAMETERS,
    handler=show_image,
)

HIDE_IMAGE = ActionSpec(
    name="hide_image",
    description="Retira la imagen que estás mostrando en tu pantalla.",
    parameters=HIDE_IMAGE_SPEC_PARAMETERS,
    handler=hide_image,
)


def build_default_registry(
    *, include_look: bool = True, include_trivia: bool = False, include_agenda: bool = False
) -> ActionRegistry:
    """Registro con las acciones integradas.

    ``include_look`` permite no anunciar ``look`` cuando el modelo configurado
    no soporta imágenes (``LLM_SUPPORTS_VISION=false``) o no hay cámara.
    ``play_animation`` (bailes y gestos por voz, :mod:`sonia.actions.moves`) va siempre.
    ``include_trivia`` anuncia ``start_trivia``, ``trivia_answer``, ``trivia_next``,
    ``restart_trivia`` y ``stop_trivia`` cuando hay banco de preguntas
    (``assets/trivia/preguntas.md``). ``include_agenda`` anuncia ``check_agenda``
    (:mod:`sonia.actions.agenda`) cuando hay agenda del evento.
    """
    from sonia.actions.agenda import CHECK_AGENDA, SHOW_TALK
    from sonia.actions.moves import PLAY_ANIMATION
    from sonia.actions.trivia import (
        RESTART_TRIVIA,
        START_TRIVIA,
        STOP_TRIVIA,
        TRIVIA_ANSWER,
        TRIVIA_NEXT,
    )

    registry = ActionRegistry()
    if include_look:
        registry.register(LOOK)
    registry.register(SHOW_IMAGE)
    registry.register(HIDE_IMAGE)
    registry.register(PLAY_ANIMATION)
    if include_trivia:
        registry.register(START_TRIVIA)
        registry.register(TRIVIA_ANSWER)
        registry.register(TRIVIA_NEXT)
        registry.register(RESTART_TRIVIA)
        registry.register(STOP_TRIVIA)
    if include_agenda:
        registry.register(CHECK_AGENDA)
        registry.register(SHOW_TALK)
    return registry
