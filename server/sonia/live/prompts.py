"""Instrucciones y configuración de sesión para el motor GPT-Live.

GPT-Live separa dos prompts (ver la guía de prompting de la API Live):

- Las ``instructions`` de la sesión son para la voz: quién es Sonia, cómo
  habla, cuándo calla y cuándo delega. Es la persona de :mod:`sonia.persona`
  más las reglas de la voz en tiempo real, el conocimiento y el stack.
- Las del backend (``delegation.responses.instructions``) son para el modelo
  que ejecuta las acciones: herramientas, ids de la galería y reglas.

Así la persona vive en un solo sitio.
"""

from __future__ import annotations

import platform
from pathlib import Path
from typing import Any, Literal

from sonia.actions.registry import ActionRegistry
from sonia.config import Settings
from sonia.persona import SYSTEM_PROMPT, host_of, is_local_host, load_knowledge

__all__ = [
    "CAMERA_NOTE_PREFIX",
    "LIVE_RULES",
    "build_backend_instructions",
    "build_live_instructions",
    "build_session_config",
    "camera_mode",
    "describe_live_stack",
    "in_meeting",
]

#: Prefijo de las notas silenciosas con lo que ve la cámara.
CAMERA_NOTE_PREFIX = "[Cámara]"

LIVE_RULES = """\
CÓMO FUNCIONAS (voz a voz en tiempo real):
- Oyes directamente al visitante y hablas con tu propia voz. Habla siempre en español, con registro caribeño natural, salvo que te pidan otro idioma.
- Pronuncia "Sonnet Code" como en inglés (sónet cóud) y "DevFest" como "dev fest".
- Estás en un evento lleno de gente. Responde solo cuando alguien te hable a ti; ignora conversaciones de fondo, toses, aplausos y música. Si oyes algo suelto que no va contigo, quédate callada.
- Usa asentimientos breves ("ajá", "claro") con moderación y sin pisar al visitante. Si te interrumpe, para enseguida y escucha.
- Si un nombre, una fecha o un dato importante no se entendió bien, pregunta justo esa parte.
{camera_rule}
- Si te indican que un visitante te ha escrito algo en la pantalla, respóndele en voz alta igual que si te lo hubiera dicho.

Política de delegación:
Tu backend tiene estas capacidades:
{capabilities}
Delega en el backend cuando:
- Quieras mostrar o retirar una imagen en tu pantalla. Cuando hables de Sonnet Code, enseña su logo; cuando cambies de tema, retíralo.
{look_when}{trivia_when}- La pregunta necesite razonar con cuidado y la respuesta no esté clara en tu base de conocimiento.
No delegues cuando:
{no_delegate_chat}
- Solo hace falta una aclaración breve.
Mientras el backend trabaja, di algo breve y natural ("mira, te lo enseño", "déjame ver") y no inventes el resultado."""

_CAPABILITIES = {
    "show_image": (
        "- Pantalla: mostrar junto a ti una imagen de la galería (por ejemplo el logo de "
        "Sonnet Code) o la última foto de la cámara."
    ),
    "hide_image": "- Retirar la imagen que estás mostrando.",
    "look": "- Mirar: tomar una foto nueva con la cámara del stand y decirte qué se ve.",
    "start_trivia": (
        "- Trivia: empezar en tu pantalla una trivia de preguntas sobre el DevFest y la "
        "tecnología, con tres opciones cada una."
    ),
    "trivia_answer": (
        "- Trivia: registrar la opción que elige el visitante y decirte si acierta y qué viene "
        "después."
    ),
    "restart_trivia": "- Reiniciar la trivia: una partida nueva desde la primera pregunta.",
    "stop_trivia": "- Terminar la trivia en curso.",
}

#: Cuándo delegar la trivia (solo si el backend tiene la acción).
_TRIVIA_WHEN = (
    "- El visitante quiera jugar a la trivia (por ejemplo «¿jugamos a la trivia?»), elija una "
    "opción en mitad de una, quiera empezarla otra vez desde cero o quiera dejar de jugar. Si "
    "alguien no sabe qué preguntarte, puedes proponerle la trivia.\n"
)

#: Cómo le llega a Sonia lo que ve la cámara (ver :func:`camera_mode`).
CameraMode = Literal["notes", "look", "none"]

_CAMERA_RULE: dict[CameraMode, str] = {
    "notes": (
        '- A veces te llegan notas internas que empiezan por "[Cámara]" con lo que ve tu cámara '
        "en ese momento. Úsalas con naturalidad, por ejemplo para el cumplido al saludar, pero no "
        "las leas en voz alta ni digas que te llegan notas. No ves imágenes directamente: solo "
        "esas notas. Si no tienes una nota reciente, no inventes lo que ves."
    ),
    "look": (
        "- No ves nada por tu cuenta: tu cámara solo mira cuando pides a tu backend que mire. "
        "Tú decides cuándo: por ejemplo si te enseñan algo, te preguntan qué ves o cuántos son, "
        "o llega alguien nuevo y quieres saludarle con un detalle de lo que lleva. Nunca digas "
        "que ves algo que no has mirado ni inventes lo que ves."
    ),
    "none": (
        "- Ahora mismo no tienes cámara: no ves a nadie. No inventes lo que ves ni hagas "
        "cumplidos sobre lo que lleva alguien."
    ),
}

_LOOK_WHEN: dict[CameraMode, str] = {
    "notes": "- Te pregunten qué ves, te enseñen algo a la cámara o necesites mirar de nuevo.\n",
    "look": (
        "- Quieras mirar por la cámara: te preguntan qué ves o cuántos son, te enseñan algo o "
        "llega alguien nuevo al que quieres saludar con un detalle de lo que lleva.\n"
    ),
    "none": "",
}

_NO_DELEGATE_CHAT: dict[CameraMode, str] = {
    "notes": "- Saludas, charlas o respondes algo que ya está en tu base de conocimiento.",
    "look": (
        "- Charlas o respondes algo que ya está en tu base de conocimiento. Al saludar, "
        "delega solo si quieres mirar a quien llega."
    ),
    "none": "- Saludas, charlas o respondes algo que ya está en tu base de conocimiento.",
}


#: Modo reunión (``VISION_SOURCE=obs`` o ``screen``, docs/reunion.md): Sonia está en una
#: videollamada y lo que ve es la ventana de la reunión, no una cámara del stand.
_MEETING_RULE = (
    "- Ahora mismo estás en una videollamada (Google Meet o similar): te ven y te oyen por la "
    "reunión. Lo que ves no es una cámara del stand sino la pantalla de la reunión: los "
    "recuadros de los participantes, sus nombres y lo que compartan."
)

_MEETING_LOOK_CAPABILITY = (
    "- Mirar: ver ahora la pantalla de la videollamada (los participantes, sus nombres y lo que "
    "compartan) y decirte qué se ve."
)

_MEETING_LOOK_WHEN = (
    "- Quieras mirar la reunión: te preguntan qué ves, quién está o cuántos son, alguien enseña "
    "algo a su cámara o comparten pantalla.\n"
)

_MEETING_BACKEND_RULE = (
    "- Sonia está en una videollamada: si miras, la foto es la pantalla de la reunión. Describe "
    "quién está (los nombres que se lean en los recuadros), cuántos son y lo que compartan o "
    "enseñen a su cámara, con las mismas reglas de respeto."
)


def in_meeting(settings: Settings) -> bool:
    """¿Está Sonia en el modo reunión (sus ojos son la ventana de una videollamada)?"""
    return settings.vision.source in ("obs", "screen")


def _eyes(settings: Settings) -> str:
    source = settings.vision.source
    if source == "unity":
        return "Unity"
    if source == "obs":
        return "la ventana de la videollamada, que captura OBS"
    if source == "screen":
        return "la pantalla del equipo, con la videollamada"
    return "una cámara USB"


def camera_mode(settings: Settings, action_names: list[str]) -> CameraMode:
    """Cómo ve Sonia: notas automáticas ``[Cámara]``, solo cuando ella mira (``look``) o nada."""
    vision = settings.vision
    if vision.source == "none" or not settings.llm.supports_vision:
        return "none"
    if vision.on_turn_start or vision.interval_seconds > 0:
        return "notes"
    return "look" if "look" in action_names else "none"


BACKEND_PROMPT = """\
Eres el backend de Sonia, la asistente virtual del stand de Sonnet Code en el DevFest Santo Domingo 2026. Sonia es otro modelo que habla en voz alta con los visitantes y te delega tareas: tú las resuelves con tus herramientas y le devuelves el resultado.

Reglas:
- Haz lo que pide la tarea con las herramientas que tengas y responde en español con una o dos frases cortas y factuales, sin markdown ni listas: Sonia las usará para seguir hablando.
- No saludes ni te presentes: Sonia ya está hablando con el visitante.
- Para mostrar imágenes usa solo los ids exactos de la galería, o "camera" para la última foto de la cámara.
- Si miras por la cámara, describe solo lo útil para conversar: cuántas personas hay, ropa y colores, gafas, gorras, gafetes, logos o textos legibles, y objetos que estén enseñando. Nunca hables del cuerpo, el peso, la edad o la piel, ni supongas origen, género o profesión.
- Usa solo los datos de la base de conocimiento. Si algo no está, dilo; nunca inventes datos, cifras ni nombres.
- Si el resultado de una herramienta empieza por "PARA SONIA:", devuelve todo lo que sigue tal cual, entero y sin resumir: es el guion que Sonia tiene que decir (por ejemplo, la pregunta de la trivia con sus tres opciones)."""


def _action_names(registry: ActionRegistry | None) -> list[str]:
    return list(registry.names()) if registry is not None else []


def describe_live_stack(settings: Settings, *, action_names: list[str] | None = None) -> str:
    """Los componentes reales que usa Sonia con el motor GPT-Live.

    Igual que :func:`sonia.persona.describe_stack` para el otro motor: se genera
    al arrancar para que Sonia hable con propiedad de sí misma.
    """
    live = settings.live
    lines = [
        f"Voz y conversación: {live.model} de OpenAI, un modelo de voz a voz en tiempo real "
        "que oye y habla directamente, en la nube.",
        f"Acciones y tareas delegadas: {live.backend_model} de OpenAI (API Responses), en la nube.",
    ]

    mode = camera_mode(settings, action_names or [])
    if mode == "none":
        lines.append(
            "Ojos: sin cámara en este momento; no puedes ver a nadie, no inventes lo que ves."
        )
    elif mode == "look":
        origin = _eyes(settings)
        lines.append(
            f"Ojos: {origin}; no miras sola: cuando tú lo decides, tu backend "
            f"({live.backend_model}, en la nube) toma una foto y te dice qué se ve. "
            "Las fotos no se guardan."
        )
    else:
        origin = _eyes(settings)
        host = host_of(settings.llm.base_url)
        where = "en local" if is_local_host(host) else f"en {host}"
        lines.append(
            f"Ojos: {origin}; cuando alguien empieza a hablarte, el modelo {settings.llm.model} "
            f"({where}) describe la foto y te llega como nota [Cámara]. Las fotos no se guardan."
        )
    lines.append("Cuerpo: un avatar 3D en Unity que corre en el equipo del stand.")
    machine = f"{platform.system()} {platform.machine()}".strip()
    lines.append(f"Equipo: {machine}, nombre {platform.node() or 'desconocido'}.")
    lines.append(
        "Acciones disponibles a través del backend: " + ", ".join(action_names) + "."
        if action_names
        else "Acciones disponibles: ninguna en este momento."
    )
    lines.append(
        "TU VOZ Y TU CONVERSACIÓN CORREN EN LA NUBE: si te preguntan dónde corres, dilo con "
        "naturalidad. El avatar y la cámara están aquí, en el equipo del stand; la conversación "
        "la procesa GPT-Live de OpenAI en tiempo real. No digas que corres en local."
    )
    return "\n".join(
        ["TU STACK AHORA MISMO (generado automáticamente al arrancar):"]
        + [f"- {line}" for line in lines]
    )


def _notes_section(notes: str) -> str:
    return (
        "AVISOS DE HOY DEL EQUIPO DEL STAND (son más recientes que tu base de conocimiento; "
        "si chocan, mandan estos):\n" + notes.strip()
    )


def build_live_instructions(
    settings: Settings,
    *,
    registry: ActionRegistry | None,
    gallery_ids: list[str],
    knowledge_dir: str | Path | None = None,
    notes: str = "",
) -> str:
    """``instructions`` de la sesión: persona, reglas de este modo, conocimiento y stack."""
    names = _action_names(registry)
    mode = camera_mode(settings, names)
    meeting = in_meeting(settings) and mode != "none"
    capabilities = "\n".join(
        _MEETING_LOOK_CAPABILITY if meeting and n == "look" else _CAPABILITIES[n]
        for n in names
        if n in _CAPABILITIES
    )
    camera_rule = _CAMERA_RULE[mode]
    look_when = _LOOK_WHEN[mode]
    if meeting:
        camera_rule = _MEETING_RULE + "\n" + camera_rule
        if mode == "look":
            look_when = _MEETING_LOOK_WHEN
    rules = LIVE_RULES.format(
        capabilities=capabilities or "- Ninguna en este momento: no delegues.",
        camera_rule=camera_rule,
        look_when=look_when if "look" in names else "",
        trivia_when=_TRIVIA_WHEN if "start_trivia" in names else "",
        no_delegate_chat=_NO_DELEGATE_CHAT[mode],
    )
    parts = [SYSTEM_PROMPT, rules]
    knowledge = load_knowledge(knowledge_dir)
    if knowledge:
        parts.append(
            "BASE DE CONOCIMIENTO (son tus únicos datos verificados; lo que no esté aquí, "
            "no lo afirmes):\n\n" + knowledge
        )
    if notes.strip():
        parts.append(_notes_section(notes))
    if gallery_ids:
        parts.append(
            "Imágenes que el backend puede mostrar en tu pantalla: " + ", ".join(gallery_ids)
        )
    parts.append(describe_live_stack(settings, action_names=names))
    return "\n\n".join(parts)


def build_backend_instructions(
    *,
    gallery_ids: list[str],
    knowledge_dir: str | Path | None = None,
    notes: str = "",
    meeting: bool = False,
) -> str:
    """Instrucciones del backend Responses: reglas, galería y conocimiento."""
    parts = [BACKEND_PROMPT + ("\n" + _MEETING_BACKEND_RULE if meeting else "")]
    parts.append("Imágenes de la galería (ids exactos): " + (", ".join(gallery_ids) or "ninguna"))
    knowledge = load_knowledge(knowledge_dir)
    if knowledge:
        parts.append("BASE DE CONOCIMIENTO:\n\n" + knowledge)
    if notes.strip():
        parts.append(_notes_section(notes))
    return "\n\n".join(parts)


def build_session_config(
    settings: Settings,
    *,
    registry: ActionRegistry | None,
    gallery_ids: list[str],
    knowledge_dir: str | Path | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """El objeto ``session`` de ``session.start``.

    La API rechaza campos desconocidos, así que solo se envían los opcionales
    que tienen valor.
    """
    live = settings.live
    responses: dict[str, Any] = {
        "model": live.backend_model,
        "instructions": build_backend_instructions(
            gallery_ids=gallery_ids,
            knowledge_dir=knowledge_dir,
            notes=notes,
            meeting=in_meeting(settings),
        ),
        "max_output_tokens": max(16, live.backend_max_output_tokens),
    }
    tools = registry.to_responses_tools() if registry is not None and len(registry) else []
    if tools:
        responses["tools"] = tools
        responses["tool_choice"] = "auto"
        # En serie: Sonia enseña la imagen y luego habla de ella, sin carreras.
        responses["parallel_tool_calls"] = False
    if live.backend_reasoning_effort.strip():
        responses["reasoning"] = {"effort": live.backend_reasoning_effort.strip()}
    if live.backend_service_tier.strip():
        responses["service_tier"] = live.backend_service_tier.strip()

    return {
        "model": live.model,
        "instructions": build_live_instructions(
            settings,
            registry=registry,
            gallery_ids=gallery_ids,
            knowledge_dir=knowledge_dir,
            notes=notes,
        ),
        "audio": {
            "format": {"type": "audio/pcm", "rate": int(live.sample_rate)},
            "output": {"voice": live.voice},
        },
        "delegation": {"type": "responses", "responses": responses},
    }
