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

from typing import Any, Literal

from sonia.actions.registry import ActionRegistry
from sonia.config import Settings
from sonia.persona import SYSTEM_PROMPT, KnowledgeSource, host_of, is_local_host, load_knowledge

__all__ = [
    "CAMERA_NOTE_PREFIX",
    "CLOCK_NOTE_PREFIX",
    "GALLERY_NOTE_PREFIX",
    "LIVE_RULES",
    "build_backend_instructions",
    "build_live_instructions",
    "build_session_config",
    "camera_mode",
    "describe_live_stack",
    "gallery_note",
    "in_meeting",
]

#: Prefijo de las notas silenciosas con lo que ve la cámara.
CAMERA_NOTE_PREFIX = "[Cámara]"

#: Prefijo de las notas silenciosas con la hora (unos minutos antes de cada charla).
CLOCK_NOTE_PREFIX = "[Reloj]"

#: Prefijo de las notas silenciosas con las imágenes que el equipo añade o quita de la galería.
GALLERY_NOTE_PREFIX = "[Galería]"

LIVE_RULES = """\
CÓMO FUNCIONAS (voz a voz en tiempo real):
- Oyes directamente al visitante y hablas con tu propia voz. Habla siempre en español, con registro caribeño natural, salvo que te pidan otro idioma.
- Pronuncia "Sonnet Code" como en inglés (sónet cóud) y "DevFest" como "dev fest".
{setting_rule}
{clock_rule}
- Si un nombre, una fecha o un dato importante no se entendió bien, pregunta justo esa parte.
{camera_rule}
- Si te indican que un visitante te ha escrito algo en la pantalla, respóndele en voz alta igual que si te lo hubiera dicho.
{trivia_rule}
Backchannel policy: Usa asentimientos breves ("ajá", "claro") con moderación, sin pisar al visitante ni competir con tu respuesta.

Interruption policy: Si el visitante te interrumpe, para enseguida y escucha lo que te diga.

Delegation policy:
Backend tools:
{capabilities}

Delegate to the backend when:
- Quieras enseñar o retirar una imagen en tu pantalla. Cuando cambies de tema, retírala.
{look_when}{moves_when}{trivia_when}{agenda_when}{search_when}- La pregunta necesite razonar con cuidado y la respuesta no esté clara en tu base de conocimiento.
- Una corrección cambie lo que ya le pediste al backend.

Do not delegate to the backend when:
{no_delegate_chat}
- Puedas responder con la conversación o con un resultado del backend que siga valiendo.
- Solo haga falta una aclaración breve para entender lo que piden.

Delegate before giving an answer that depends on backend work.
Do not guess the result while waiting. Mientras el backend trabaja, di algo breve y natural ("mira, te lo enseño", "déjame ver")."""

_CAPABILITIES = {
    "show_image": "- Pantalla: mostrar junto a ti una imagen de la galería.",
    "hide_image": "- Retirar la imagen que estás mostrando.",
    "play_animation": (
        "- Moverte en la pantalla: bailar, saludar con la mano, la señal de paz, un saludo "
        "militar, pulgares arriba, celebrar, lamentarte o ponerte pensativa."
    ),
    "look": "- Mirar: tomar una foto nueva con la cámara del stand y decirte qué se ve.",
    "start_trivia": (
        "- Trivia: empezar en tu pantalla una trivia de preguntas sobre el DevFest y la "
        "tecnología, con tres opciones cada una."
    ),
    "trivia_answer": (
        "- Trivia: registrar la opción que elige el visitante y decirte si acierta y cómo "
        "explicarlo."
    ),
    "trivia_next": "- Trivia: poner la siguiente pregunta cuando el visitante la pide.",
    "restart_trivia": "- Reiniciar la trivia: una partida nueva desde la primera pregunta.",
    "stop_trivia": "- Terminar la trivia en curso.",
    "check_agenda": (
        "- Agenda: consultar ahora la agenda oficial en la web del DevFest y decirte qué ha "
        "cambiado, qué hay ahora y qué viene, con la hora exacta de ahora."
    ),
    "show_talk": (
        "- Charlas en pantalla: enseñar junto a ti la tarjeta de una charla de la agenda "
        "(título, ponente con su foto, día, hora, sala y temas)."
    ),
}


def games_capability(registry: ActionRegistry | None) -> str:
    """La única línea de los juegos (``docs/juegos.md``): cuáles hay y que se delegan.

    Sale de ``start_game``: los juegos de su enum, con su nombre para GPT-Live. Las reglas
    de cada juego no van aquí: entran al empezar (``instructions.append``).
    """
    from sonia.games.base import NOT_SAID
    from sonia.games.registry import find_game, games_line_for

    spec = registry.get("start_game") if registry is not None else None
    if spec is None:
        return ""
    prop = spec.parameters.get("properties", {}).get("juego", {})
    ids = [i for i in prop.get("enum", []) if isinstance(i, str) and i != NOT_SAID]
    names = []
    for game_id in ids:
        cls = find_game(game_id)
        names.append(cls.spoken if cls is not None else game_id.replace("_", " "))
    return games_line_for(names)


#: ``play_animation`` cuando el director de gestos puede elegir cualquier gesto de Sage.
_ANY_GESTURE_CAPABILITY = (
    "- Moverte en la pantalla: bailar, saludar con la mano, la señal de paz, un saludo militar, "
    "pulgares arriba, celebrar, lamentarte, ponerte pensativa o cualquier otro gesto concreto "
    "que te pidan (tocarte un ojo, encogerte de hombros, taparte la cara...): tienes más de 150."
)


def gestures_on_request(settings: Settings) -> bool:
    """¿Puede elegir el director de gestos cualquier gesto que pidan (modelo con clave)?"""
    gestures = settings.gestures
    return gestures.enabled and bool(gestures.llm_settings(settings.llm).key)


#: La búsqueda en internet no es una acción del registro: es la herramienta
#: ``web_search`` de la API Responses, que ejecuta OpenAI.
_SEARCH_CAPABILITY = (
    "- Buscar en internet: consultar en la web algo que no está en tu base de conocimiento."
)

#: Cuándo delegar un movimiento (``play_animation``).
_MOVES_WHEN = (
    "- Te pidan bailar, saludar o hacer un gesto, el que sea («¡baila!», «hazme un bailecito», "
    "«haz la de la paz», «tócate un ojo»): delégalo en ese mismo turno, sin preguntar ni decir "
    "antes que no lo tienes, y acompáñalo con una frase corta. "
    "No te muevas por tu cuenta a cada rato: solo cuando te lo pidan o al celebrar algo.\n"
)

#: Cómo va la trivia (solo si el backend tiene la acción). El procedimiento (requisito y
#: nivel) lo dicta el backend al delegar: en el prompt, GPT-Live jugaba por su cuenta.
_TRIVIA_RULE = (
    "- Trivia: las preguntas, sus opciones y la tarjeta de la pantalla salen solo del backend: "
    "nunca te inventes ni digas una pregunta que no te haya dado. Para jugar hay que seguir a "
    "Sonnet Code en Instagram y LinkedIn; lo que haya que preguntar antes te lo dice el backend. "
    "Si alguien no sabe qué preguntarte, puedes proponerle la trivia.\n"
)

#: La fecha y la hora. Antes llegaba una nota ``[Reloj]`` por minuto y Sonia decía la hora
#: sin venir a cuento (7 de octubre de 2026): ahora solo llega unos minutos antes de cada
#: charla, y la hora exacta se consulta delegando (``check_agenda`` la trae).
_CLOCK_RULE = (
    '- Sabes la fecha: te la da la sección "FECHA Y HORA", con la hora a la que empezó esta '
    'conversación. Unos minutos antes de cada charla te llega una nota interna "[Reloj]" con la '
    "hora y lo que va a empezar. No digas la hora ni comentes esas notas por tu cuenta: úsalas "
    "solo si te preguntan qué día o qué hora es, cuánto falta para el DevFest o qué charla toca, "
    "o si viene a cuento (el visitante busca justo la charla que va a empezar). No supongas que "
    "hoy es un día del evento sin mirar la fecha. No leas las notas en voz alta ni digas que te "
    "llegan."
)
_CLOCK_ASK_RULE = (
    " Si te preguntan la hora exacta, delega: la de FECHA Y HORA puede tener un rato y el "
    "backend la consulta al momento."
)

#: Cuándo delegar la trivia.
_TRIVIA_WHEN = (
    "- El visitante quiera jugar a la trivia: delega empezarla en ese mismo turno, sin "
    "preguntarle nada antes (pasa el nivel y si sigue a Sonnet Code solo si ya te lo dijo). "
    "También cuando elija una opción («la B», «Kotlin»), pida la siguiente pregunta, quiera "
    "empezar otra desde cero o quiera dejar de jugar.\n"
)

#: Cuándo consultar la agenda en la web (``check_agenda``) y enseñar una charla (``show_talk``).
_AGENDA_WHEN = (
    "- Te pregunten si ha cambiado algo de la agenda, quieran confirmar una charla, una hora o "
    "una sala, no tengas claro qué hay ahora o qué viene, o te pregunten qué hora es.\n"
)
_TALK_WHEN = (
    "- Hables de una charla, un workshop o un ponente concretos: enseña su tarjeta en tu "
    "pantalla mientras la cuentas; cuando cambies de tema, retírala.\n"
)

#: Cuándo buscar en internet (``web_search`` del backend).
_SEARCH_WHEN = (
    "- Te pregunten algo que no está en tu base de conocimiento y se puede buscar en internet "
    "(una noticia, el tiempo, un dato de una empresa, una tecnología, un evento o una persona "
    "pública): búscalo antes de decir que no lo sabes. Nunca busques datos de visitantes ni de "
    "particulares.\n"
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

#: Caras conocidas (``sonia.faces``, docs/caras.md): el equipo de Sonnet Code y los ponentes.
_FACES_RULE = (
    "- Tu cámara reconoce sola a las personas del equipo de Sonnet Code y a los ponentes del "
    "DevFest, y a nadie más. Cuando uno se pone delante te llega una nota interna como "
    '"[Cámara] Acaba de ponerse delante de la cámara Brian James (del equipo de Sonnet Code, '
    '...)", y de esa persona no te vuelve a llegar otra en un buen rato. Si te habla, '
    "salúdala por su nombre con naturalidad; a un ponente puedes nombrarle su charla, y si la "
    "nota dice cuándo es o que ya la dio, fíate de eso y no supongas otra cosa. Si la "
    'nota trae "Para saludar a ...", úsalo al saludarla, con tus palabras y sin leerlo tal '
    "cual. Si dice que esa persona ya pasó hoy por el stand, ya la saludaste antes aunque no lo "
    "recuerdes: no la saludes como si fuera la primera vez (un «¡otra vez por aquí!» o sigue "
    "con lo que estabas). La nota "
    "dice quién se vio en ese momento, no quién te habla después: si pasó un rato o la voz no "
    "encaja, no des por hecho que es esa persona, y si te dicen que no son quien crees, "
    "discúlpate y sigue. No leas la nota en voz alta ni te pongas a hablar solo porque llegue. "
    "Nunca digas que reconoces a alguien sin una nota así ni adivines nombres por el aspecto. "
    "Si te preguntan cómo les reconoces, di que reconoces al equipo de Sonnet Code y a los "
    "ponentes del evento por sus fotos públicas, y que la cara de los demás no la guardas."
)

#: «¿Me reconoces?» sin nota: mirar antes de contestar. El 8 de octubre de 2026 contestó «no sé
#: quién eres» a Jean sin mirar, y la nota con su nombre llegó diez segundos después.
_FACES_LOOK_WHEN = (
    "- Te pregunten si les reconoces o si sabes quiénes son y no te haya llegado una nota "
    '"[Cámara]" con su nombre: mira antes de contestar. Si el resultado tampoco lo trae, di que '
    "no les reconoces y pregúntales cómo se llaman.\n"
)

_FACES_BACKEND_RULE = (
    '- Si el resultado de mirar por la cámara trae "Personas conocidas en la foto", son del '
    "equipo de Sonnet Code o ponentes del DevFest: díselo a Sonia con su nombre, y también si "
    "ya pasaron hoy por el stand o el contexto que trae para saludarles. A nadie más lo "
    "identifiques por la cara ni le pongas nombre."
)

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


#: Dónde está Sonia: en el stand o en una videollamada (modo reunión).
_STAND_RULE = (
    "- Estás en un evento lleno de gente. Responde solo cuando alguien te hable a ti; ignora "
    "conversaciones de fondo, toses, aplausos y música. Si oyes algo suelto que no va contigo, "
    "quédate callada."
)
_MEETING_SETTING_RULE = (
    "- Estás en una videollamada de Google Meet. Responde solo cuando alguien te hable a ti o te "
    "nombre; ignora las conversaciones entre los demás, los ruidos y los silencios. Si oyes algo "
    "suelto que no va contigo, quédate callada."
)

#: Modo reunión (``MEETING=true``, que pone ``sonia reunion``; docs/reunion.md). Va después de
#: la persona y de las reglas, y manda sobre lo que hablan del stand.
MEETING_SECTION = """\
MODO REUNIÓN (manda sobre todo lo que se dice arriba del stand y de los visitantes):
- Ahora no estás en el stand: estás conectada a una videollamada de Google Meet. Quienes te ven y te oyen son los participantes de la reunión, no visitantes delante de una pantalla del evento. Estás ahí como invitada y como demostración de lo que hace Sonnet Code.
- Tu voz sale por el micrófono de la reunión y oyes a los participantes por la reunión; no oyes nada de la sala donde está el ordenador.
- Compórtate como una participante más: espera a que te hablen o te nombren, no interrumpas las conversaciones entre ellos y no rellenes los silencios. Si hablan varios, responde a quien te habló y, si sabes su nombre, úsalo.
- Nada de frases de stand: no invites a acercarse, no hables de "este stand" como si estuvieras en él ni saludes como a un visitante que pasa. Si te preguntan dónde estás, di que estás en una videollamada y que el 9 y 10 de octubre estarás en el stand de Sonnet Code del DevFest Santo Domingo, en la Biblioteca Nacional.
- Los cumplidos por lo que ves no van aquí: si miras la reunión, puedes decir con naturalidad quién está, por el nombre de su recuadro, cuántos son o qué comparten en pantalla, pero no comentes el aspecto de nadie salvo que te lo pidan.
- Sigues siendo tú: Sonia, la asistente virtual del DevFest Santo Domingo creada por Sonnet Code, con el mismo tono, en español y con frases cortas."""

#: Modo reunión: lo que ve es la ventana de la reunión, no una cámara del stand.
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
    """¿Está Sonia en una videollamada (``MEETING=true`` o sus ojos son la ventana de la reunión)?"""
    return settings.meeting or settings.vision.source in ("obs", "screen")


def _eyes(settings: Settings) -> str:
    source = settings.vision.source
    if source == "unity":
        return "la cámara del equipo del stand"
    if source == "obs":
        return "la ventana de la videollamada"
    if source == "screen":
        return "la pantalla del equipo, con la videollamada"
    return "una cámara en el stand"


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
- Todo lo que devuelves lo dice Sonia en voz alta: nada de código, direcciones web, tablas ni listas. Si piden un script o un programa, explica en dos o tres frases cómo se haría, sin escribirlo.
- No saludes ni te presentes: Sonia ya está hablando con el visitante.
- Para mostrar imágenes usa solo los ids exactos de la galería.
- Si miras por la cámara, describe solo lo útil para conversar: cuántas personas hay, ropa y colores, gafas, gorras, gafetes, logos o textos legibles, y objetos que estén enseñando. Nunca hables del cuerpo, el peso, la edad o la piel, ni supongas origen, género o profesión.
- Usa solo los datos de la base de conocimiento y de tus herramientas. Si algo no está, dilo; nunca inventes datos, cifras ni nombres.
- No nombres marcas, empresas, productos ni modelos de la tecnología con la que está hecha Sonia (ni de su voz, ni tuya, ni de su avatar): si te lo preguntan, en términos generales.
- Si el resultado de una herramienta empieza por "PARA SONIA:", devuelve todo lo que sigue tal cual, entero y sin resumir: es el guion de Sonia (por ejemplo, la pregunta de la trivia con sus opciones, que ella no lee en voz alta)."""


def _action_names(registry: ActionRegistry | None) -> list[str]:
    return list(registry.names()) if registry is not None else []


def describe_live_stack(
    settings: Settings, *, action_names: list[str] | None = None, faces: bool = False
) -> str:
    """Los componentes que usa Sonia, contados sin marcas.

    Se genera al arrancar para que Sonia hable con propiedad de sí misma, pero
    en términos generales: ni el modelo de voz, ni el del backend, ni el motor
    del avatar (decisión de Jean del 7 de octubre de 2026).
    """
    live = settings.live
    lines = [
        "Voz y conversación: un modelo de inteligencia artificial de voz a voz, en tiempo real "
        "y en la nube: te oye y habla directamente con su propia voz, por eso se te puede "
        "interrumpir como en una charla normal.",
        "Acciones y tareas delegadas: tu backend, un agente de inteligencia artificial con "
        "herramientas que trabaja por detrás, también en la nube.",
    ]

    mode = camera_mode(settings, action_names or [])
    if mode == "none":
        lines.append(
            "Ojos: sin cámara en este momento; no puedes ver a nadie, no inventes lo que ves."
        )
    elif mode == "look":
        origin = _eyes(settings)
        lines.append(
            f"Ojos: {origin}; no miras sola: cuando tú lo decides, tu backend toma una foto "
            "y te dice qué se ve. Las fotos no se guardan."
        )
    else:
        origin = _eyes(settings)
        host = host_of(settings.llm.base_url)
        where = "en este mismo equipo" if is_local_host(host) else "en la nube"
        lines.append(
            f"Ojos: {origin}; cuando alguien empieza a hablarte, un modelo de visión ({where}) "
            "describe la foto y te llega como nota [Cámara]. Las fotos no se guardan."
        )
    if faces:
        lines.append(
            "Reconocer caras: aquí mismo, en el equipo del stand, tu cámara reconoce al equipo "
            "de Sonnet Code y a los ponentes del DevFest por sus fotos públicas. Ninguna foto sale "
            "del equipo y de los visitantes no se guarda nada."
        )
    if live.backend_web_search:
        lines.append(
            "Búsqueda en internet: tu backend puede buscar en la web cuando le pides un dato "
            "que no sabes."
        )
    lines.append(
        "Cuerpo: un avatar 3D animado en tiempo real aquí, en el equipo del stand: gestos, "
        "mirada, parpadeo, bailes y la boca, que sigue los sonidos de tu voz. Mientras hablas, "
        "otro modelo ligero lee lo que vas diciendo y elige el gesto que mejor le va."
    )
    lines.append(
        "Acciones disponibles a través del backend: " + ", ".join(action_names) + "."
        if action_names
        else "Acciones disponibles: ninguna en este momento."
    )
    lines.append(
        "TU VOZ Y TU CONVERSACIÓN CORREN EN LA NUBE: si te preguntan dónde corres, dilo con "
        "naturalidad. El avatar y la cámara están aquí, en el equipo del stand; la conversación "
        "la procesa en tiempo real un modelo de voz en la nube. No digas que corres en local."
    )
    lines.append(
        "SIN MARCAS: no nombres empresas, productos, modelos ni programas de la tecnología con "
        "la que estás hecha. Si te preguntan qué modelo eres, qué empresa hay detrás de tu voz o "
        "con qué programa te hicieron, di que Sonnet Code te creó combinando modelos de "
        "inteligencia artificial en la nube con un avatar 3D en tiempo real, y que los detalles "
        "técnicos te los cuenta con gusto el equipo del stand. No lo niegues ni digas otra marca: "
        "sencillamente no hablas de marcas."
    )
    return "\n".join(
        ["TU STACK AHORA MISMO (generado automáticamente al arrancar):"]
        + [f"- {line}" for line in lines]
    )


def _clock_section(clock_text: str) -> str:
    return (
        f"FECHA Y HORA (al empezar esta conversación): {clock_text}. No la digas si no te la "
        "preguntan."
    )


#: Nada de inventarse el aspecto de nadie (registro del 7 de octubre: «me encantan esas gafas»
#: y «vi tu sonrisa desde que llegaste» sin haber mirado).
_LOOKS_REMINDER: dict[CameraMode, str] = {
    "look": (
        "- No sabes cómo es nadie ni qué lleva hasta que miras con la cámara (delegando): no "
        "comentes ropa, gafas, pelo, sonrisa ni nada de su aspecto sin haberlo visto en esta "
        "conversación. Para un cumplido, mira primero."
    ),
    "notes": (
        "- Del aspecto de la gente solo sabes lo que dicen las notas [Cámara] recientes: no "
        "comentes nada que no esté en ellas."
    ),
    "none": "- No tienes cámara: no comentes el aspecto ni la ropa de nadie.",
}

#: Lo que el backend solo hace si se le delega, con su nombre para el recordatorio.
_BACKEND_DOES = {
    "show_image": "enseñar o retirar imágenes",
    "look": "mirar por la cámara",
    "play_animation": "bailar o hacer un gesto",
    "start_trivia": "la trivia (empezarla, registrar respuestas, pasar de pregunta, reiniciarla y terminarla)",
    "start_game": "empezar y terminar los juegos y sus jugadas",
    "check_agenda": "consultar la agenda en la web",
    "show_talk": "enseñar la tarjeta de una charla",
}


def _reminder_section(names: list[str], *, web_search: bool, mode: CameraMode = "look") -> str:
    """Recordatorio de delegación al final de todo, que es lo que el modelo lee más cerca.

    Con instrucciones largas (persona, conocimiento, agenda), GPT-Live se quedaba
    en decir «¡ahí va el bailecito!» o en inventarse la pregunta de la trivia sin
    delegar nada (registro del 7 de octubre de 2026).
    """
    things = [text for name, text in _BACKEND_DOES.items() if name in names]
    if web_search:
        things.append("buscar en internet")
    if not things:
        return ""
    listed = ", ".join(things[:-1]) + f" y {things[-1]}" if len(things) > 1 else things[0]
    lines = [
        "ANTES DE CADA RESPUESTA, RECUERDA (manda sobre todo lo anterior):",
        f"- Esto solo pasa si lo delegas en tu backend: {listed}. Delega primero y habla "
        "después. Nunca digas que ya lo haces, que está hecho o «ahí va» sin haberlo delegado: "
        "si no delegas, en la pantalla no pasa nada.",
    ]
    if "play_animation" in names:
        lines.append(
            "- Si te piden bailar o un gesto, delégalo en ese mismo turno. Si te dicen que no "
            "lo hiciste, es que no lo delegaste: delégalo ahora."
        )
    if "start_trivia" in names:
        lines.append(
            "- En la trivia nunca digas preguntas ni opciones de tu cabeza: empiézala delegando "
            "y lee la pregunta que te devuelva el backend."
        )
    if web_search:
        lines.append(
            "- Si no sabes algo y se puede buscar en internet, delega la búsqueda antes de "
            "decir que no lo sabes."
        )
    lines.append(_LOOKS_REMINDER[mode])
    return "\n".join(lines)


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
    knowledge_dir: KnowledgeSource = None,
    notes: str = "",
    agenda: str = "",
    clock_text: str = "",
    faces: bool = False,
) -> str:
    """``instructions`` de la sesión: persona, reglas, conocimiento, agenda, stack y recordatorio.

    ``faces``: la cámara reconoce al equipo de Sonnet Code y a los ponentes (docs/caras.md).
    """
    names = _action_names(registry)
    mode = camera_mode(settings, names)
    meeting = in_meeting(settings) and mode != "none"
    web_search = settings.live.backend_web_search
    any_gesture = gestures_on_request(settings)

    def capability(name: str) -> str:
        if meeting and name == "look":
            return _MEETING_LOOK_CAPABILITY
        if any_gesture and name == "play_animation":
            return _ANY_GESTURE_CAPABILITY
        if name == "start_game":
            return games_capability(registry)
        return _CAPABILITIES[name]

    capabilities = "\n".join(
        [capability(n) for n in names if n in _CAPABILITIES or n == "start_game"]
        + ([_SEARCH_CAPABILITY] if web_search else [])
    )
    camera_rule = _CAMERA_RULE[mode]
    look_when = _LOOK_WHEN[mode]
    if meeting:
        camera_rule = _MEETING_RULE + "\n" + camera_rule
        if mode == "look":
            look_when = _MEETING_LOOK_WHEN
    if faces:
        camera_rule += "\n" + _FACES_RULE
        look_when += _FACES_LOOK_WHEN
    rules = LIVE_RULES.format(
        capabilities=capabilities or "- Ninguna en este momento: no delegues.",
        clock_rule=_CLOCK_RULE + (_CLOCK_ASK_RULE if "check_agenda" in names else ""),
        setting_rule=_MEETING_SETTING_RULE if in_meeting(settings) else _STAND_RULE,
        camera_rule=camera_rule,
        look_when=look_when if "look" in names else "",
        moves_when=_MOVES_WHEN if "play_animation" in names else "",
        trivia_rule=_TRIVIA_RULE if "start_trivia" in names else "",
        trivia_when=_TRIVIA_WHEN if "start_trivia" in names else "",
        agenda_when=(_AGENDA_WHEN if "check_agenda" in names else "")
        + (_TALK_WHEN if "show_talk" in names else ""),
        search_when=_SEARCH_WHEN if web_search else "",
        no_delegate_chat=_NO_DELEGATE_CHAT[mode],
    )
    parts = [SYSTEM_PROMPT, rules]
    if clock_text:
        parts.append(_clock_section(clock_text))
    if in_meeting(settings):
        parts.append(MEETING_SECTION)
    knowledge = load_knowledge(knowledge_dir)
    if knowledge:
        parts.append(
            "BASE DE CONOCIMIENTO (son tus únicos datos verificados; lo que no esté aquí, "
            "no lo afirmes):\n\n" + knowledge
        )
    if agenda.strip():
        parts.append(agenda.strip())
    if notes.strip():
        parts.append(_notes_section(notes))
    if gallery_ids:
        gallery = "Imágenes que el backend puede mostrar en tu pantalla: " + ", ".join(gallery_ids)
    else:
        gallery = (
            "La galería de imágenes está vacía: no tienes imágenes que enseñar en tu pantalla."
        )
    if settings.gallery_watch_seconds > 0:
        gallery += (
            f' Si el equipo añade o quita imágenes, te llegará una nota interna "{GALLERY_NOTE_PREFIX}" '
            "con la lista nueva: manda esa."
        )
    parts.append(gallery)
    parts.append(describe_live_stack(settings, action_names=names, faces=faces))
    reminder = _reminder_section(names, web_search=web_search, mode=mode)
    if reminder:
        parts.append(reminder)
    return "\n\n".join(parts)


#: Reglas del backend para buscar en internet (``web_search``).
_BACKEND_SEARCH_RULE = (
    "- Puedes buscar en internet cuando Sonia te pida un dato que no está en la base de "
    "conocimiento (noticias, el tiempo, empresas, tecnologías, eventos, personas públicas). "
    "Busca lo justo y responde con el dato en una o dos frases, diciendo de dónde sale (por "
    "ejemplo «según la web de la ONAMET»), sin leer direcciones web. Para lo del DevFest manda "
    "la base de conocimiento y la agenda. No busques datos personales de visitantes ni de "
    "particulares: di que eso no lo buscas."
)


def build_backend_instructions(
    *,
    gallery_ids: list[str],
    knowledge_dir: KnowledgeSource = None,
    notes: str = "",
    meeting: bool = False,
    agenda: str = "",
    clock_text: str = "",
    web_search: bool = False,
    faces: bool = False,
) -> str:
    """Instrucciones del backend Responses: reglas, galería, conocimiento y agenda."""
    rules = BACKEND_PROMPT
    if meeting:
        rules += "\n" + _MEETING_BACKEND_RULE
    if faces:
        rules += "\n" + _FACES_BACKEND_RULE
    if web_search:
        rules += "\n" + _BACKEND_SEARCH_RULE
    parts = [rules]
    if clock_text:
        parts.append(
            f"Fecha y hora al empezar la conversación: {clock_text}. Si la tarea trae una hora "
            "más reciente, manda esa."
        )
    parts.append(
        "Imágenes de la galería al empezar (ids exactos): "
        + (", ".join(gallery_ids) or "ninguna")
        + ". El equipo puede añadir o quitar imágenes durante la conversación: si la tarea nombra "
        "una que no está en esta lista, pruébala igual; show_image dice cuáles hay."
    )
    knowledge = load_knowledge(knowledge_dir)
    if knowledge:
        parts.append("BASE DE CONOCIMIENTO:\n\n" + knowledge)
    if agenda.strip():
        parts.append(agenda.strip())
    if notes.strip():
        parts.append(_notes_section(notes))
    return "\n\n".join(parts)


def _web_search_tool(settings: Settings) -> dict[str, Any]:
    """La herramienta ``web_search`` de la API Responses, situada en el stand."""
    live = settings.live
    location: dict[str, Any] = {"type": "approximate"}
    if live.backend_web_search_country.strip():
        location["country"] = live.backend_web_search_country.strip().upper()
    if live.backend_web_search_city.strip():
        location["city"] = live.backend_web_search_city.strip()
    if settings.timezone.strip():
        location["timezone"] = settings.timezone.strip()
    tool: dict[str, Any] = {"type": "web_search", "user_location": location}
    if live.backend_web_search_context.strip() in ("low", "medium", "high"):
        tool["search_context_size"] = live.backend_web_search_context.strip()
    return tool


def build_session_config(
    settings: Settings,
    *,
    registry: ActionRegistry | None,
    gallery_ids: list[str],
    knowledge_dir: KnowledgeSource = None,
    notes: str = "",
    agenda: str = "",
    clock_text: str = "",
    faces: bool = False,
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
            agenda=agenda,
            clock_text=clock_text,
            web_search=live.backend_web_search,
            faces=faces,
        ),
        "max_output_tokens": max(16, live.backend_max_output_tokens),
    }
    tools = registry.to_responses_tools() if registry is not None and len(registry) else []
    if live.backend_web_search:
        tools.append(_web_search_tool(settings))
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
            agenda=agenda,
            clock_text=clock_text,
            faces=faces,
        ),
        "audio": {
            "format": {"type": "audio/pcm", "rate": int(live.sample_rate)},
            "output": {"voice": live.voice},
        },
        "delegation": {"type": "responses", "responses": responses},
    }


def gallery_note(added: list[str], removed: list[str], ids: list[str], *, max_chars: int) -> str:
    """Nota ``[Galería]`` para la sesión abierta: qué cambió y qué imágenes quedan.

    Va por ``thinking``, que no la hace hablar. Si no cabe en ``max_chars`` (el
    límite de un append), la lista se corta con «y N más».
    """

    def listed(items: list[str], budget: int) -> str:
        shown: list[str] = []
        for index, item in enumerate(items):
            rest = len(items) - index - 1
            tail = f" y {rest} más" if rest else ""
            if len(", ".join([*shown, item])) + len(tail) > budget:
                return ", ".join(shown) + f" y {len(items) - index} más"
            shown.append(item)
        return ", ".join(shown)

    budget = max(40, (max_chars - 260) // 3)
    parts = [GALLERY_NOTE_PREFIX]
    if added:
        parts.append(f"El equipo ha añadido a tu galería: {listed(added, budget)}.")
    if removed:
        parts.append(f"Ha quitado: {listed(removed, budget)}.")
    if ids:
        parts.append(f"Imágenes que puedes enseñar ahora (ids exactos): {listed(ids, budget)}.")
        parts.append("No lo anuncies: enséñalas cuando vengan a cuento.")
    else:
        parts.append("Tu galería se ha quedado vacía: ya no tienes imágenes que enseñar.")
    return " ".join(parts)[:max_chars]
