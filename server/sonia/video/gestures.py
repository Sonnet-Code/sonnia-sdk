"""Los gestos del vídeo: una sola petición al modelo de gestos del stand con el guion entero.

En el stand el director de gestos (``sonia/gestures``) elige frase a frase mientras
Sonia habla. Aquí se conoce el guion entero de antemano, así que se le pide todo de
una vez, con el mismo catálogo de Genies (``/catalog`` del renderizador) y las mismas
fichas (``gesture_line``). Como mucho un gesto por frase, sin repetir, y las reglas de
frecuencia de Genies se aplican también en código con los tiempos reales de cada
frase (``schedule``): un gesto no empieza hasta que acaba el núcleo del anterior (si
tarda más de ``GESTURE_MAX_DELAY_S`` desde que empieza su frase, se descarta), pocos
``Uncommon`` y menos ``Rare``. Los gestos escritos en el guion mandan siempre.

Si el modelo falla, el vídeo sale sin gestos elegidos (se avisa).
"""

from __future__ import annotations

import difflib
import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from sonia.config import GestureSettings, LLMSettings
from sonia.gestures.catalog import GestureCatalog
from sonia.gestures.prompt import Cooldowns, catalog_text
from sonia.llm.client import Completion, LLMClient
from sonia.llm.messages import system, user_text
from sonia.types import Message
from sonia.video.errors import VideoError
from sonia.video.plan import GestureCue

__all__ = [
    "GestureCue",
    "ScriptPhrase",
    "build_system_prompt",
    "build_user_message",
    "choose_gestures",
    "gesture_llm",
    "parse_choices",
    "resolve_names",
    "schedule",
]

logger = logging.getLogger(__name__)

#: Tope de la respuesta: unos 20 tokens por frase y lo que razone el modelo.
MAX_TOKENS = 4096
#: Una sola petición con todo el guion: sin la prisa del stand.
TIMEOUT_S = 90.0

_NONE_WORDS = frozenset({"ninguno", "ninguna", "none", "null", "nada", "no", ""})

SYSTEM_PROMPT = """\
Eres el director de gestos de Sonnia, la asistente virtual del staff del DevFest Santo Domingo 2026, creada por Sonnet Code. Sonnia es un avatar 3D y está grabando un vídeo corto para redes sociales: dice un guion ya escrito, frase a frase. Tú no hablas. Eliges el gesto de cuerpo que acompaña a cada frase, como lo haría una persona expresiva pero natural delante de la cámara.

Cómo elegir:
- El gesto tiene que encajar con lo que dice la frase y con su intención: saludar, explicar, afirmar, agradecer, animar, invitar, despedirse... Fíjate en la descripción y en las intenciones de cada gesto.
- Si la primera frase saluda («¡Hola!», «¡Buenas!»), un gesto de saludar con la mano encaja muy bien; si la última se despide, uno de despedida.
- Como mucho un gesto por frase y nunca el mismo gesto dos veces en el vídeo.
- «ninguno» es una respuesta válida y normal: una persona natural deja muchas frases sin un gesto marcado. Ante la duda, ninguno. En un vídeo de varias frases, más o menos la mitad llevan gesto.
- Frecuencia: los Standard se usan con normalidad; los Uncommon, uno como mucho y solo si encaja claramente; los Rare, casi nunca, solo si el momento es justo ese.
- Impacto: HighImpact solo en momentos enfáticos (una sorpresa, una celebración, algo que quiere remarcar). Para lo demás, LowImpact o NoImpact.
- Duración: Instant y Short para frases cortas; Long para frases largas. Un gesto largo en una frase corta se come la siguiente.
- Respeta las reglas USE y DO NOT USE de cada gesto.
- Es un entorno profesional: nada de coqueteo, burla, sarcasmo ni agresividad (intenciones Flirt, Mock o Intimidate; estilos Flirty o Cocky).
- Los marcados como relleno son casi neutros: acompañan una frase sin intención marcada.
- Las frases con un gesto ya fijado no se tocan: cuenta ese gesto como usado.

Responde solo con JSON, sin explicaciones, con una entrada por frase en orden:
{"gestos": [{"frase": 1, "gesto": "<nombre exacto de la lista o ninguno>"}, ...]}

Gestos de {character}, uno por línea: nombre · frecuencia, duración, impacto, intensidad de 1 a 4 · descripción · intenciones · estilo · reglas.
{gestures}
"""


class CompletingLLM(Protocol):
    """Lo que se usa del cliente del modelo (``LLMClient.complete``)."""

    async def complete(self, messages: list[Message]) -> Completion: ...


@dataclass(frozen=True, slots=True)
class ScriptPhrase:
    """Una frase del vídeo tal como la ve el modelo de gestos."""

    uid: int
    text: str
    #: Segundo del vídeo en que empieza a sonar y cuánto dura su voz.
    start: float
    duration: float
    #: Segundo en que acaba su voz (los gestos que llegarían después se descartan).
    end: float


def gesture_llm() -> LLMClient | None:
    """El cliente del modelo de gestos del stand (``GESTURE_*``; Gemini con ``GEMINI_API_KEY``)."""
    settings = GestureSettings()
    llm = settings.llm_settings(LLMSettings())
    if not llm.key:
        return None
    return LLMClient(
        llm.model_copy(
            update={"max_tokens": max(MAX_TOKENS, llm.max_tokens), "request_timeout": TIMEOUT_S}
        )
    )


def build_system_prompt(catalog: GestureCatalog) -> str:
    return SYSTEM_PROMPT.replace("{character}", catalog.character or "Sonnia").replace(
        "{gestures}", catalog_text(catalog)
    )


def build_user_message(phrases: Sequence[ScriptPhrase], fixed: Mapping[int, str]) -> str:
    lines = [f"Guion del vídeo ({len(phrases)} frases):"]
    for phrase in phrases:
        line = f"{phrase.uid}. ({phrase.duration:.1f} s) «{' '.join(phrase.text.split())}»"
        if phrase.uid in fixed:
            line += f" — gesto fijado: {fixed[phrase.uid]}"
        lines.append(line)
    lines.append('¿Qué gesto lleva cada frase? Responde solo con {"gestos": [...]}.')
    return "\n".join(lines)


def _json_payload(text: str) -> Any:
    raw = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    for opener, closer in (("{", "}"), ("[", "]")):
        first, last = raw.find(opener), raw.rfind(closer)
        if first != -1 and last > first:
            try:
                return json.loads(raw[first : last + 1])
            except ValueError:
                continue
    return None


def parse_choices(
    text: str, catalog: GestureCatalog, uids: Sequence[int]
) -> tuple[dict[int, str], list[str]]:
    """Los gestos que eligió el modelo (``uid`` → nombre exacto) y avisos de lo que no valía."""
    payload = _json_payload(text)
    items = payload.get("gestos", payload.get("gestures")) if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise VideoError("El modelo de gestos no contestó con la lista de gestos.")
    chosen: dict[int, str] = {}
    notes: list[str] = []
    valid = set(uids)
    for position, item in enumerate(items):
        if isinstance(item, dict):
            uid = item.get("frase", item.get("phrase"))
            name = item.get("gesto", item.get("gesture"))
        else:
            uid, name = (uids[position] if position < len(uids) else None), item
        if isinstance(uid, str) and uid.strip().isdigit():
            uid = int(uid)
        if not isinstance(uid, int) or uid not in valid or uid in chosen:
            continue
        if not isinstance(name, str) or name.strip().lower() in _NONE_WORDS:
            continue
        gesture = catalog.resolve(name)
        if gesture is None:
            notes.append(f"frase {uid}: «{name}» no está en el catálogo")
            continue
        chosen[uid] = gesture.name
    return chosen, notes


async def choose_gestures(
    llm: CompletingLLM,
    catalog: GestureCatalog,
    phrases: Sequence[ScriptPhrase],
    fixed: Mapping[int, str],
) -> dict[int, str]:
    """Una petición al modelo con el guion entero. Lanza ``VideoError`` si falla."""
    messages = [system(build_system_prompt(catalog)), user_text(build_user_message(phrases, fixed))]
    try:
        completion = await llm.complete(messages)
    except Exception as exc:  # noqa: BLE001 - cualquier fallo del modelo: vídeo sin gestos
        raise VideoError(f"el modelo de gestos falló: {exc}") from None
    if not completion.content.strip():
        raise VideoError("el modelo de gestos no contestó nada")
    chosen, notes = parse_choices(completion.content, catalog, [p.uid for p in phrases])
    for note in notes:
        logger.warning("Gesto descartado: %s", note)
    return {uid: name for uid, name in chosen.items() if uid not in fixed}


def schedule(
    phrases: Sequence[ScriptPhrase],
    chosen: Mapping[int, str],
    fixed: Mapping[int, str],
    catalog: GestureCatalog,
    settings: GestureSettings | None = None,
) -> tuple[dict[int, GestureCue], list[str]]:
    """Coloca los gestos con las reglas de frecuencia de Genies. Los fijados van siempre.

    Devuelve los gestos por ``uid`` y avisos de los que se quitaron y por qué.
    """
    settings = settings or GestureSettings()
    cues: dict[int, GestureCue] = {}
    notes: list[str] = []
    busy_until = float("-inf")
    history: list[tuple[str, str, float]] = []
    for phrase in sorted(phrases, key=lambda p: p.start):
        name = fixed.get(phrase.uid) or chosen.get(phrase.uid)
        if not name:
            continue
        gesture = catalog.get(name)
        at = phrase.start
        if phrase.uid not in fixed:
            if gesture is None:
                notes.append(f"frase {phrase.uid}: {name} no está en el catálogo")
                continue
            rare_left = uncommon_left = 0.0
            repeated: list[str] = []
            for played, frequency, played_at in history:
                ago = at - played_at
                if frequency == "Rare":
                    rare_left = max(rare_left, settings.rare_s - ago)
                elif frequency == "Uncommon":
                    uncommon_left = max(uncommon_left, settings.uncommon_s - ago)
                if ago < settings.repeat_s:
                    repeated.append(played)
            if Cooldowns(rare_left, uncommon_left, tuple(repeated)).blocks(gesture):
                notes.append(f"frase {phrase.uid}: {name} quitado por frecuencia")
                continue
            at = max(at, busy_until)
            if at > phrase.start + settings.max_delay_s or at > phrase.end:
                notes.append(f"frase {phrase.uid}: {name} quitado (aún dura el gesto anterior)")
                continue
        frequency = gesture.frequency if gesture is not None else "Standard"
        core = gesture.core_s if gesture is not None else 2.0
        history.append((name, frequency, at))
        busy_until = at + core + settings.min_gap_s
        cues[phrase.uid] = GestureCue(name, round(at, 4))
    return cues, notes


def resolve_names(names: Sequence[str], catalog: GestureCatalog, where: str) -> list[str]:
    """Los nombres exactos de unos gestos escritos a mano, o un error con los parecidos."""
    out: list[str] = []
    for name in names:
        gesture = catalog.resolve(name)
        if gesture is None:
            close = difflib.get_close_matches(name, [g.name for g in catalog], n=4, cutoff=0.5)
            hint = f" ¿Quisiste decir {', '.join(close)}?" if close else ""
            raise VideoError(
                f"{where}: el gesto «{name}» no está en el catálogo.{hint} "
                "Lista: sonnia-video gestos"
            )
        out.append(gesture.name)
    return out
