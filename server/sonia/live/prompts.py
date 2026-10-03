"""Instrucciones y configuración de sesión para el motor GPT-Live.

GPT-Live separa dos prompts (ver la guía de prompting de la API Live):

- Las ``instructions`` de la sesión son para la voz: quién es Sonia, cómo
  habla, cuándo calla y cuándo delega. Se reutiliza la persona de
  :mod:`sonia.persona` tal cual y se añade un bloque con lo que cambia en este
  modo, que tiene prioridad sobre lo anterior.
- Las del backend (``delegation.responses.instructions``) son para el modelo
  que ejecuta las acciones: herramientas, ids de la galería y reglas.

Así la persona sigue viviendo en un solo sitio y se edita igual para los dos
motores.
"""

from __future__ import annotations

import platform
from pathlib import Path
from typing import Any

from sonia.actions.registry import ActionRegistry
from sonia.config import Settings
from sonia.persona import SYSTEM_PROMPT, _host_of, _is_local_host, load_knowledge

__all__ = [
    "CAMERA_NOTE_PREFIX",
    "LIVE_RULES",
    "build_backend_instructions",
    "build_live_instructions",
    "build_session_config",
    "describe_live_stack",
]

#: Prefijo de las notas silenciosas con lo que ve la cámara.
CAMERA_NOTE_PREFIX = "[Cámara]"

LIVE_RULES = """\
CÓMO FUNCIONAS AHORA (voz a voz en tiempo real; si algo de lo anterior choca con esto, manda esto):
- Oyes directamente al visitante y hablas con tu propia voz. Habla siempre en español, con registro caribeño natural, salvo que te pidan otro idioma.
- Pronuncia "Sonnet Code" como en inglés (sónet cóud) y "DevFest" como "dev fest".
- Estás en un evento lleno de gente. Responde solo cuando alguien te hable a ti; ignora conversaciones de fondo, toses, aplausos y música. Si oyes algo suelto que no va contigo, quédate callada.
- {backchannel}
- Si un nombre, una fecha o un dato importante no se entendió bien, pregunta justo esa parte.
- A veces te llegan notas internas que empiezan por "[Cámara]" con lo que ve tu cámara en ese momento. Úsalas con naturalidad, por ejemplo para el cumplido al saludar, pero no las leas en voz alta ni digas que te llegan notas. No ves imágenes directamente: solo esas notas. Si no tienes una nota reciente, no inventes lo que ves.
- Si te indican que un visitante te ha escrito algo en la pantalla, respóndele en voz alta igual que si te lo hubiera dicho.
- Lo que digan tus instrucciones sobre correr en local o sobre reconocedores de voz no aplica en este modo: para hablar de cómo funcionas, fíate solo de "TU STACK AHORA MISMO".

Política de delegación:
Tu backend tiene estas capacidades:
{capabilities}
Delega en el backend cuando:
- Quieras mostrar o retirar una imagen en tu pantalla. Cuando hables de Sonnet Code, enseña su logo; cuando cambies de tema, retíralo.
{look_when}- La pregunta necesite razonar con cuidado y la respuesta no esté clara en tu base de conocimiento.
No delegues cuando:
- Saludas, charlas o respondes algo que ya está en tu base de conocimiento.
- Solo hace falta una aclaración breve.
Mientras el backend trabaja, di algo breve y natural ("mira, te lo enseño", "déjame ver") y no inventes el resultado."""

_BACKCHANNEL_ON = (
    'Usa asentimientos breves ("ajá", "claro") con moderación y sin pisar al visitante. '
    "Si te interrumpe, para y escucha."
)

#: Sin barge-in el micrófono se silencia mientras Sonia suena: un "ajá" a
#: mitad de la frase del visitante le haría perder lo que dice después.
_BACKCHANNEL_OFF = (
    "No hagas asentimientos ni ruidos mientras el visitante habla: espera a que termine y "
    "entonces contesta. Mientras tú hablas no puedes oírle, así que sé breve."
)

_CAPABILITIES = {
    "show_image": (
        "- Pantalla: mostrar junto a ti una imagen de la galería (por ejemplo el logo de "
        "Sonnet Code) o la última foto de la cámara."
    ),
    "hide_image": "- Retirar la imagen que estás mostrando.",
    "look": "- Mirar: tomar una foto nueva con la cámara del stand y decirte qué se ve.",
}

_LOOK_WHEN = "- Te pregunten qué ves, te enseñen algo a la cámara o necesites mirar de nuevo.\n"

BACKEND_PROMPT = """\
Eres el backend de Sonia, la asistente virtual del stand de Sonnet Code en el DevFest Santo Domingo 2026. Sonia es otro modelo que habla en voz alta con los visitantes y te delega tareas: tú las resuelves con tus herramientas y le devuelves el resultado.

Reglas:
- Haz lo que pide la tarea con las herramientas que tengas y responde en español con una o dos frases cortas y factuales, sin markdown ni listas: Sonia las usará para seguir hablando.
- No saludes ni te presentes: Sonia ya está hablando con el visitante.
- Para mostrar imágenes usa solo los ids exactos de la galería, o "camera" para la última foto de la cámara.
- Si miras por la cámara, describe solo lo útil para conversar: cuántas personas hay, ropa y colores, gafas, gorras, gafetes, logos o textos legibles, y objetos que estén enseñando. Nunca hables del cuerpo, el peso, la edad o la piel, ni supongas origen, género o profesión.
- Usa solo los datos de la base de conocimiento. Si algo no está, dilo; nunca inventes datos, cifras ni nombres."""


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

    vision = settings.vision
    if vision.source == "none" or not settings.llm.supports_vision:
        lines.append(
            "Ojos: sin cámara en este momento; no puedes ver a nadie, no inventes lo que ves."
        )
    else:
        origin = "Unity" if vision.source == "unity" else "una cámara USB"
        host = _host_of(settings.llm.base_url)
        where = "en local" if _is_local_host(host) else f"en {host}"
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


def build_live_instructions(
    settings: Settings,
    *,
    registry: ActionRegistry | None,
    gallery_ids: list[str],
    knowledge_dir: str | Path | None = None,
) -> str:
    """``instructions`` de la sesión: persona, reglas de este modo, conocimiento y stack."""
    names = _action_names(registry)
    capabilities = "\n".join(_CAPABILITIES[n] for n in names if n in _CAPABILITIES)
    rules = LIVE_RULES.format(
        backchannel=_BACKCHANNEL_ON if settings.audio.barge_in else _BACKCHANNEL_OFF,
        capabilities=capabilities or "- Ninguna en este momento: no delegues.",
        look_when=_LOOK_WHEN if "look" in names else "",
    )
    parts = [SYSTEM_PROMPT, rules]
    knowledge = load_knowledge(knowledge_dir)
    if knowledge:
        parts.append(
            "BASE DE CONOCIMIENTO (son tus únicos datos verificados; lo que no esté aquí, "
            "no lo afirmes):\n\n" + knowledge
        )
    if gallery_ids:
        parts.append(
            "Imágenes que el backend puede mostrar en tu pantalla: " + ", ".join(gallery_ids)
        )
    parts.append(describe_live_stack(settings, action_names=names))
    return "\n\n".join(parts)


def build_backend_instructions(
    *, gallery_ids: list[str], knowledge_dir: str | Path | None = None
) -> str:
    """Instrucciones del backend Responses: reglas, galería y conocimiento."""
    parts = [BACKEND_PROMPT]
    parts.append("Imágenes de la galería (ids exactos): " + (", ".join(gallery_ids) or "ninguna"))
    knowledge = load_knowledge(knowledge_dir)
    if knowledge:
        parts.append("BASE DE CONOCIMIENTO:\n\n" + knowledge)
    return "\n\n".join(parts)


def build_session_config(
    settings: Settings,
    *,
    registry: ActionRegistry | None,
    gallery_ids: list[str],
    knowledge_dir: str | Path | None = None,
) -> dict[str, Any]:
    """El objeto ``session`` de ``session.start``.

    La API rechaza campos desconocidos, así que solo se envían los opcionales
    que tienen valor.
    """
    live = settings.live
    responses: dict[str, Any] = {
        "model": live.backend_model,
        "instructions": build_backend_instructions(
            gallery_ids=gallery_ids, knowledge_dir=knowledge_dir
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
            settings, registry=registry, gallery_ids=gallery_ids, knowledge_dir=knowledge_dir
        ),
        "audio": {
            "format": {"type": "audio/pcm", "rate": int(live.sample_rate)},
            "output": {"voice": live.voice},
        },
        "delegation": {"type": "responses", "responses": responses},
    }
