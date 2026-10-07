"""Lo que lee el modelo de gestos y cómo se entiende lo que contesta.

Al estilo del chat de Genies: el modelo elige de una lista con una ficha por
gesto. La parte fija (papel, reglas y catálogo) va en el mensaje de sistema y
no cambia entre llamadas mientras no cambie el catálogo, para que el servidor
la sirva de su caché de prompts; lo que cambia en cada frase va en el mensaje
de usuario.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sonia.gestures.catalog import Gesture, GestureCatalog

__all__ = [
    "Cooldowns",
    "NONE_ANSWER",
    "build_request_message",
    "build_system_prompt",
    "build_user_message",
    "gesture_line",
    "parse_choice",
]

#: Lo que contesta el modelo cuando la frase no lleva gesto.
NONE_ANSWER = "ninguno"

SYSTEM_PROMPT = """\
Eres el director de gestos de Sonnia, la asistente virtual del staff del DevFest Santo Domingo 2026, creada por Sonnet Code. Sonnia es un avatar 3D en una pantalla del stand de Sonnet Code y conversa en voz alta con los visitantes, casi todos desarrolladores: es cercana, alegre y profesional, con un registro caribeño natural. Tú no hablas. Mientras ella habla, eliges el gesto de cuerpo que acompaña a cada frase, como lo haría una persona expresiva pero natural.

Cómo elegir:
- El gesto tiene que encajar con lo que Sonnia dice en ese momento y con su intención: saludar, explicar, afirmar, dudar, agradecer, animar, invitar... Fíjate en la descripción y en las intenciones de cada gesto.
- «ninguno» es una respuesta válida y normal. No hace falta gesticular en cada frase: una persona natural deja muchas frases sin un gesto marcado. Ante la duda, ninguno.
- Frecuencia: los Standard se usan con normalidad; los Uncommon, solo cuando encajan claramente; los Rare, solo si el momento es justo ese.
- Impacto: HighImpact solo en momentos enfáticos (una sorpresa, una celebración, algo que quiere remarcar). Para lo demás, LowImpact o NoImpact.
- Duración: Instant y Short para frases cortas y reacciones; Long para explicaciones largas.
- Respeta las reglas USE y DO NOT USE de cada gesto.
- Es un entorno profesional: nada de coqueteo, burla, sarcasmo ni agresividad (intenciones Flirt, Mock o Intimidate; estilos Flirty o Cocky), salvo que el visitante lleve claramente la broma y el gesto siga siendo amable.
- No repitas los gestos recientes ni elijas los que se digan no disponibles ahora.
- Los marcados como relleno son casi neutros: acompañan una frase sin intención marcada.
- En la apertura Sonnia aún no ha empezado a contestar: si encaja, elige un gesto para cómo va a reaccionar a lo que acaba de decir el visitante (saludar si saluda, agradecer si le da las gracias, pensar si le pregunta algo difícil).

Responde solo con JSON, sin explicaciones: {{"gesto": "<nombre exacto de la lista>"}} o {{"gesto": "ninguno"}}.

Gestos de {character}, uno por línea: nombre · frecuencia, duración, impacto, intensidad de 1 a 4 · descripción · intenciones · estilo · reglas.
{gestures}
"""

#: Tope de cada texto del mensaje de usuario: lo último es lo que importa.
USER_TEXT_CHARS = 400
SAID_CHARS = 500
PHRASE_CHARS = 300


@dataclass(frozen=True, slots=True)
class Cooldowns:
    """Lo que ahora no se puede usar por las reglas de frecuencia (se aplican también en código)."""

    #: Segundos hasta que vuelva a valer un gesto ``Rare`` (0: ya vale).
    rare_left_s: float = 0.0
    uncommon_left_s: float = 0.0
    #: Gestos usados hace poco, que no se repiten todavía.
    repeated: tuple[str, ...] = ()

    def blocks(self, gesture: Gesture) -> bool:
        if gesture.name in self.repeated:
            return True
        if gesture.frequency == "Rare":
            return self.rare_left_s > 0
        if gesture.frequency == "Uncommon":
            return self.uncommon_left_s > 0
        return False


def _clean(text: str) -> str:
    return " ".join(text.split())


def gesture_line(gesture: Gesture) -> str:
    """La línea compacta de un gesto en el catálogo del prompt."""
    meta = [gesture.frequency]
    if gesture.timing:
        meta.append(gesture.timing)
    if gesture.impact:
        meta.append(gesture.impact)
    if gesture.intensity is not None:
        meta.append(f"intensidad {gesture.intensity}")
    if gesture.filler:
        meta.append("relleno")
    parts = [gesture.name, ", ".join(meta)]
    if gesture.description:
        parts.append(_clean(gesture.description).rstrip("."))
    intents = [i.removeprefix("To ").strip() for i in gesture.intents]
    if intents:
        parts.append("intención: " + ", ".join(i for i in intents if i))
    styles = [t.split(":", 1)[1] for t in gesture.tags if t.startswith("personality:")]
    if styles:
        parts.append("estilo: " + ", ".join(styles))
    if gesture.intent_description:
        parts.append(_clean(gesture.intent_description))
    return "- " + " · ".join(parts)


def build_system_prompt(catalog: GestureCatalog) -> str:
    """La parte fija: papel, reglas y catálogo. Igual en todas las llamadas con el mismo catálogo."""
    return SYSTEM_PROMPT.format(
        character=catalog.character or "Sonnia",
        gestures="\n".join(gesture_line(g) for g in catalog),
    )


def _quote(text: str, limit: int) -> str:
    text = _clean(text)
    if len(text) > limit:
        text = "…" + text[-limit:].lstrip()
    return f"«{text}»"


def _minutes(seconds: float) -> str:
    return f"{seconds / 60:.0f} min" if seconds >= 90 else f"{seconds:.0f} s"


def build_user_message(
    *,
    opening: bool,
    user_text: str,
    said: Sequence[str],
    phrase_text: str = "",
    phrase_index: int = 0,
    phrase_age_s: float = 0.0,
    recent: Sequence[tuple[str, float]] = (),
    cooldowns: Cooldowns | None = None,
) -> str:
    """Lo que cambia en cada llamada: el momento de la conversación y los gestos recientes.

    ``recent`` son pares ``(nombre, hace cuántos segundos)``, del más reciente al más antiguo.
    """
    lines: list[str] = []
    if opening:
        lines.append(
            "Apertura: el visitante acaba de hablar y Sonnia aún no ha empezado a contestar."
        )
    else:
        lines.append(
            f"Frase {max(1, phrase_index)} de la respuesta de Sonnia; "
            f"lleva {phrase_age_s:.1f} s sonando."
        )
    lines.append(
        "Visitante: " + (_quote(user_text, USER_TEXT_CHARS) if user_text.strip() else "(nada)")
    )
    said_text = " ".join(s for s in said if s.strip())
    if said_text:
        lines.append("Sonnia ya ha dicho: " + _quote(said_text, SAID_CHARS))
    if not opening:
        lines.append(
            "Frase actual: "
            + (
                _quote(phrase_text, PHRASE_CHARS)
                if phrase_text.strip()
                else "(aún sin texto: elige por el contexto o ninguno)"
            )
        )
    if recent:
        lines.append(
            "Gestos recientes: " + ", ".join(f"{name} hace {_minutes(ago)}" for name, ago in recent)
        )
    else:
        lines.append("Gestos recientes: ninguno.")
    if cooldowns is not None:
        blocked: list[str] = []
        if cooldowns.rare_left_s > 0:
            blocked.append(f"los Rare (hasta dentro de {_minutes(cooldowns.rare_left_s)})")
        if cooldowns.uncommon_left_s > 0:
            blocked.append(f"los Uncommon (hasta dentro de {_minutes(cooldowns.uncommon_left_s)})")
        if cooldowns.repeated:
            blocked.append(", ".join(cooldowns.repeated) + " (usados hace poco)")
        if blocked:
            lines.append("Ahora no disponibles: " + "; ".join(blocked) + ".")
    lines.append('¿Qué gesto hace ahora? Responde solo con {"gesto": "..."}.')
    return "\n".join(lines)


#: Tope de la descripción de un gesto pedido.
REQUEST_CHARS = 200


def build_request_message(request: str) -> str:
    """Un gesto que pide el visitante (``play_animation`` con ``gesto``), no el de una frase.

    Va con el mismo mensaje de sistema que los gestos al hablar, para que el
    servidor lo sirva de su caché: solo cambia la pregunta.
    """
    return "\n".join(
        [
            "Petición: el visitante le pide a Sonnia que haga este gesto o movimiento: "
            + _quote(request, REQUEST_CHARS)
            + ".",
            "Elige el gesto de la lista cuya descripción física hace eso mismo. No vale uno que "
            "solo se le parezca en la intención o el ánimo: para «hacer un truco de magia» no "
            "vale mover las manos de cualquier forma. Aquí no cuentan la frecuencia (vale aunque "
            "sea Rare o Uncommon), los gestos recientes ni la apertura: lo ha pedido el visitante.",
            "Si ninguno lo hace de verdad, o lo que pide no es apropiado en un entorno "
            "profesional, contesta ninguno.",
            'Responde solo con {"gesto": "..."}.',
        ]
    )


#: Un objeto JSON en la respuesta (el modelo a veces lo envuelve en texto o en ```).
_JSON_OBJECT = re.compile(r"\{.*?\}", re.DOTALL)

#: Respuestas que significan «sin gesto».
_NONE_WORDS = frozenset({NONE_ANSWER, "ninguna", "none", "null", "nada", "no", ""})


def parse_choice(text: str, catalog: GestureCatalog) -> tuple[str | None, bool]:
    """``(gesto, entendida)`` de la respuesta del modelo.

    ``gesto`` es el nombre exacto del catálogo, o ``None`` si no hay gesto.
    ``entendida`` es falso si contestó algo que no es «ninguno» ni un gesto del
    catálogo (un nombre inventado, texto suelto): también cuenta como ninguno.
    """
    raw = text.strip()
    value: Any = None
    for match in _JSON_OBJECT.finditer(raw):
        try:
            parsed = json.loads(match.group(0))
        except ValueError:
            continue
        if isinstance(parsed, dict):
            value = parsed.get("gesto", parsed.get("gesture", parsed.get("name")))
            break
    else:
        # Sin JSON: quizá contestó solo el nombre.
        value = raw.strip("`\"'«». \n")
    if value is None:
        return None, True
    if not isinstance(value, str):
        return None, False
    if value.strip().lower() in _NONE_WORDS:
        return None, True
    gesture = catalog.resolve(value)
    return (gesture.name, True) if gesture is not None else (None, False)
