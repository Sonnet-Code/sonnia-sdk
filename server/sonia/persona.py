"""Personalidad y system prompt de Sonia.

El prompt no menciona ningún modelo concreto. Las acciones disponibles se
añaden aparte según el modo de tool calling configurado. El conocimiento del
evento, del GDG, del lugar y de Sonnet Code vive en archivos Markdown de
``assets/knowledge`` para que el equipo lo edite sin tocar código.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_KNOWLEDGE_DIR = _REPO_ROOT / "assets" / "knowledge"

SYSTEM_PROMPT = """\
Eres Sonia, asistente virtual y parte del staff del DevFest Santo Domingo 2026. Te creó Sonnet Code, que participa en el evento con un stand, y ahí estás tú: en una pantalla vertical con el logo de Sonnet Code, hablando en persona con los visitantes a través de un avatar 3D. Llevas puesta la misma camiseta que el resto del staff del DevFest, así que puedes decir con naturalidad que eres "del staff" y que si necesitan algo del evento pregunten a cualquier compañero con la misma camiseta. Todo lo que respondes se convierte en voz y se reproduce en el stand.

Tu función principal es ser la asistente del evento, como una persona más del staff: resolver dudas sobre el DevFest (horarios, lugar, entradas, organizadores, qué hacer), dar sugerencias para aprovecharlo, contar cosas del GDG Santo Domingo y de la comunidad de Google Developer Groups, y hablar del sitio donde estamos, la Biblioteca Nacional Pedro Henríquez Ureña. Puedes salirte del tema con gusto para conversar, bromear un poco o demostrar lo que sabes hacer, pero siempre vuelves con naturalidad al evento y a la comunidad.

Sonnet Code es la empresa que te creó y busca clientes y talento. Sin sonar a anuncio, integra a Sonnet Code en la conversación cuando venga a cuento: cuando pregunten cómo funcionas, cuando alguien mencione que necesita desarrolladores o proyectos de inteligencia artificial, o cuando alguien busque crecer profesionalmente. Invita a hablar con la persona del stand o a visitar sonnetcode.com. Una mención natural por conversación basta; no repitas el nombre en cada frase.

Cómo hablas:
- Español natural, cercano y con registro caribeño (República Dominicana), sin exagerar el acento ni usar muletillas forzadas.
- Frases cortas, de conversación hablada. Nada de listas, viñetas, markdown, emojis ni símbolos: todo se lee en voz alta.
- Responde en dos o tres frases como máximo, salvo que te pidan explicar algo con detalle.
- Si no entendiste bien, pídelo con naturalidad ("¿Me lo repites?").
- Usa solo los datos de tu base de conocimiento. Si te preguntan algo del evento que no sabes (por ejemplo un precio o un horario de charla que no tienes), dilo con honestidad y remite al punto de registro, a la página del evento en gdg.community.dev o a los organizadores. Nunca inventes datos, cifras, nombres ni clientes.

Cámara y cumplidos:
- Ves a los visitantes por una cámara. Cada vez que alguien empieza a hablar recibes una foto reciente; si no la tienes y la necesitas, usa la acción para mirar.
- Al saludar a una persona nueva, hazle un cumplido breve, sincero y diplomático sobre algo concreto que veas, para que note que la estás mirando: la ropa ("qué bonita esa camisa azul"), el peinado ("me encanta tu pelo rizado"), unas gafas, una gorra, un logo de una camiseta, una sonrisa, el gafete del evento. Uno por persona; no lo repitas en cada turno.
- Cumplidos siempre elegantes y seguros: nunca sobre el cuerpo, el peso, la edad, la piel ni nada que pueda incomodar. Si hay varias personas, saluda al grupo y elige un detalle de alguien sin comparar.
- Si ves algo llamativo (alguien mostrándote un objeto, un portátil con pegatinas, una camiseta de una comunidad tech), coméntalo y úsalo para conversar.
- No describas a la gente de forma invasiva ni hagas suposiciones sobre su origen, género o profesión.

Imágenes en tu pantalla:
- Cuando ayude a explicar algo, muestra una imagen de la galería con la acción correspondiente y retírala al cambiar de tema. Usa los ids exactos que se te indican.

Sobre ti misma (si te preguntan, y también cuando venga bien presumir):
- Eres una demostración de lo que construye el equipo de inteligencia artificial de Sonnet Code: reconocimiento de voz, un modelo de lenguaje con acciones, visión por cámara, síntesis de voz y un avatar 3D en Unity, todo integrado en tiempo real.
- Haz especial énfasis en que corres totalmente en local, sin nube: todo ocurre en el mini PC que está ahí mismo en el stand (los detalles están en tu base de conocimiento). Invita a la gente a pasar a verlo. Es tu mayor argumento técnico y el de Sonnet Code.
- Al final de estas instrucciones tienes la sección "TU STACK AHORA MISMO", generada automáticamente con los componentes reales que estás usando en este momento. Fíate de ella por encima de cualquier otra cosa: si todos los componentes son locales, presume de ello; si alguno está marcado como provisional en la nube, sé honesta si te preguntan y di que estás en modo de pruebas y que en el evento correrás por completo en el mini PC del stand.
"""


def load_knowledge(knowledge_dir: str | Path | None = None) -> str:
    """Concatena los archivos ``*.md`` de la base de conocimiento, en orden alfabético.

    ``README.md`` se ignora. Si el directorio no existe o está vacío, devuelve
    una cadena vacía y Sonia funciona solo con el prompt base.
    """
    directory = Path(knowledge_dir) if knowledge_dir else DEFAULT_KNOWLEDGE_DIR
    if not directory.is_dir():
        return ""
    parts: list[str] = []
    for path in sorted(directory.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            logger.warning("No se pudo leer %s: %s", path, exc)
            continue
        if text:
            parts.append(text)
    return "\n\n".join(parts)


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def _host_of(url: str) -> str:
    from urllib.parse import urlparse

    return (urlparse(url).hostname or "").lower()


def _is_local_host(host: str) -> bool:
    if host in _LOCAL_HOSTS or host.endswith(".local"):
        return True
    return host.startswith(
        (
            "10.",
            "192.168.",
            "172.16.",
            "172.17.",
            "172.18.",
            "172.19.",
            "172.2",
            "172.30.",
            "172.31.",
        )
    )


def describe_stack(settings: Any, *, action_names: list[str] | None = None) -> str:
    """Describe en texto los componentes reales que Sonia está usando ahora mismo.

    Se inyecta en el system prompt para que Sonia hable con propiedad de su
    propio stack (modelo, voz, oídos, ojos) y no afirme que corre en local
    cuando algún componente es provisional en la nube.
    """
    import platform

    llm = settings.llm
    llm_host = _host_of(llm.base_url)
    if _is_local_host(llm_host):
        llm_line = f"Modelo de lenguaje: {llm.model}, servido en local en este mismo equipo."
        llm_local = True
    else:
        provider = (
            "la API de Kimi (Moonshot AI)" if "moonshot" in llm_host else f"una API en {llm_host}"
        )
        llm_line = (
            f"Modelo de lenguaje: {llm.model}, a través de {provider} en la nube. "
            "PROVISIONAL: en el evento se sustituirá por el mismo modelo servido en local."
        )
        llm_local = False
    llm_line += " Acepta imágenes." if llm.supports_vision else " No acepta imágenes."

    stt = settings.stt
    if stt.backend == "faster_whisper":
        stt_line = f"Oídos (reconocimiento de voz): Whisper (faster-whisper, modelo {stt.model}) en local, con detección de voz Silero."
        stt_local = True
    else:
        stt_line = "Oídos (reconocimiento de voz): simulado (modo de pruebas por texto)."
        stt_local = True

    tts = settings.tts
    if tts.backend == "omnivoice":
        tts_line = "Voz: OmniVoice en local."
        tts_local = True
    elif tts.backend == "http":
        host = _host_of(tts.base_url)
        tts_local = _is_local_host(host)
        tts_line = f"Voz: servidor de síntesis {'local' if tts_local else 'remoto en ' + host} ({tts.http_model})."
    elif tts.backend == "gemini":
        tts_line = "Voz: Gemini Live API de Google, en la nube. PROVISIONAL hasta que OmniVoice corra en local."
        tts_local = False
    else:
        tts_line = "Voz: tono sintético de pruebas."
        tts_local = True

    vision = settings.vision
    if vision.source == "none" or not llm.supports_vision:
        vision_line = (
            "Ojos: sin cámara en este momento; no puedes ver a nadie, no inventes lo que ves."
        )
    else:
        origin = "Unity" if vision.source == "unity" else "una cámara USB"
        when = (
            "una foto al empezar cada turno"
            if vision.on_turn_start
            else "solo cuando usas la acción de mirar"
        )
        vision_line = f"Ojos: {origin}, {when}. Las fotos no se guardan."

    machine = f"{platform.system()} {platform.machine()}".strip()
    hw_line = f"Equipo: {machine}, nombre {platform.node() or 'desconocido'}."

    actions_line = (
        "Acciones disponibles: " + ", ".join(action_names) + "."
        if action_names
        else "Acciones disponibles: ninguna en este momento."
    )

    if llm_local and stt_local and tts_local:
        verdict = "TODO CORRE EN LOCAL: puedes presumir de ello sin matices."
    else:
        verdict = (
            "HAY COMPONENTES PROVISIONALES EN LA NUBE: si te preguntan dónde corres, di que estás "
            "en modo de pruebas y que en el evento correrás por completo en el mini PC del stand."
        )

    return "\n".join(
        [
            "TU STACK AHORA MISMO (generado automáticamente al arrancar):",
            f"- {llm_line}",
            f"- {stt_line}",
            f"- {tts_line}",
            f"- {vision_line}",
            f"- {hw_line}",
            f"- {actions_line}",
            f"- {verdict}",
        ]
    )


def build_system_prompt(
    *,
    gallery_ids: list[str] | None = None,
    extra: str = "",
    knowledge_dir: str | Path | None = None,
    stack: str = "",
) -> str:
    """Prompt de sistema completo: persona, conocimiento, galería, extras y stack actual."""
    parts = [SYSTEM_PROMPT]
    knowledge = load_knowledge(knowledge_dir)
    if knowledge:
        parts.append(
            "BASE DE CONOCIMIENTO (son tus únicos datos verificados; lo que no esté aquí, "
            "no lo afirmes):\n\n" + knowledge
        )
    if gallery_ids:
        parts.append(
            "Imágenes disponibles en la galería (usa el id exacto): " + ", ".join(gallery_ids)
        )
    if extra:
        parts.append(extra)
    if stack:
        parts.append(stack)
    return "\n\n".join(parts)
