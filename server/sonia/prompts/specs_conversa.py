"""Piezas de la conversación: persona, conocimiento, GPT-Live, backend y visión.

Cada pieza se registra en :func:`register_all` con su texto de la app en una función
perezosa (importa el módulo dentro, para no crear ciclos), y el módulo que la usa pide su
texto con ``BOOK.text(id)`` o ``BOOK.render(id, ...)`` en el momento de usarla. Con las
versiones de la app el resultado tiene que ser idéntico, byte a byte, al de antes.

Qué bloques entran en las instrucciones según la configuración (cámara, reunión, caras,
búsqueda, acciones del registro) lo sigue decidiendo ``sonia/live/prompts.py``: aquí solo
está el texto de cada bloque.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from pathlib import Path

from sonia.prompts.book import PROMPT_MAX_LEN, Applies, PromptSpec, register

logger = logging.getLogger(__name__)

SONNIA = "Sonnia"
KNOWLEDGE = "Conocimiento"
CONVERSATION = "Conversación (GPT-Live)"
BACKEND = "Backend (acciones)"
VISION = "Visión"
SHOWCASE = "Animación"

#: Tope real de un ``session.commentary.append`` (``APPEND_MAX_CHARS`` del cliente): lo que
#: pasa de ahí se corta. Cuenta también lo que rellena el código.
APPEND_MAX = 1_200

#: Ayuda común de las piezas que se pegan en las reglas a través de un marcador.
_IN_RULES = "Va dentro de «Reglas de la voz» ({marker}) solo si {when}."


def _const(module: str, name: str, key: str | None = None) -> Callable[[], str]:
    """El texto de la app: una constante (o una entrada de un diccionario) de ``module``,
    leída al pedirla."""

    def read() -> str:
        import importlib

        value = getattr(importlib.import_module(module), name)
        return str(value[key] if key is not None else value)

    return read


def _add(
    prompt_id: str,
    group: str,
    title: str,
    default: Callable[[], str],
    *,
    fields: tuple[str, ...] = (),
    required: tuple[str, ...] = (),
    must_contain: tuple[str, ...] = (),
    applies: Applies = "sesion",
    help: str = "",
    max_len: int = PROMPT_MAX_LEN,
    literal: bool = False,
) -> None:
    register(
        PromptSpec(
            id=prompt_id,
            group=group,
            title=title,
            default=default,
            fields=fields,
            required=required,
            must_contain=must_contain,
            applies=applies,
            help=help,
            max_len=max_len,
            literal=literal,
        )
    )


def register_all() -> None:
    """Registra las piezas de este grupo (idempotente: registrar otra vez sustituye)."""
    parts = (
        _register_persona,
        _register_knowledge,
        _register_live,
        _register_live_notes,
        _register_backend,
        _register_vision,
        _register_showcase,
    )
    for part in parts:
        try:
            part()
        except Exception:  # noqa: BLE001 - sin estas piezas, cada módulo usa su texto de la app
            logger.exception("No se pudieron registrar los prompts de %s", part.__name__)


# -- Sonnia y conocimiento ------------------------------------------------------------------


def _register_persona() -> None:
    _add(
        "sonnia/persona",
        SONNIA,
        "Persona: quién es Sonnia, cómo habla, la cámara, las imágenes y su aspecto",
        _const("sonia.persona", "SYSTEM_PROMPT"),
        literal=True,
        help=(
            "Lo primero de las instrucciones de GPT-Live. Detrás van las reglas de la voz, la "
            "fecha, el conocimiento, la agenda, los avisos, la galería, el stack y el "
            "recordatorio, cada uno con su pieza. Se escribe «Sonnia» pero lo que lee el "
            "modelo dice «Sonia», para que lo pronuncie bien."
        ),
    )


def _read_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _knowledge_title(path: Path) -> str:
    """El nombre del archivo y su primer título (``# ...``), para el selector del panel."""
    for line in _read_file(path).splitlines():
        heading = line.strip().lstrip("#").strip()
        if heading:
            return f"{path.name}: {heading}"[:120]
    return path.name


def _register_knowledge() -> None:
    """Una pieza por archivo de ``assets/knowledge`` de la app (sin el ``README.md``)."""
    from sonia.persona import DEFAULT_KNOWLEDGE_DIR, knowledge_files, knowledge_prompt_id

    for path in knowledge_files(DEFAULT_KNOWLEDGE_DIR):
        prompt_id = knowledge_prompt_id(path)
        if prompt_id is None:
            continue
        _add(
            prompt_id,
            KNOWLEDGE,
            _knowledge_title(path),
            functools.partial(_read_file, path),
            literal=True,
            help=(
                f"El archivo assets/knowledge/{path.name}. Va en la «BASE DE CONOCIMIENTO» de "
                "GPT-Live y del backend, en su sitio (por orden de nombre). Si guardas una "
                "versión en la nube, sustituye al archivo entero."
            ),
        )


# -- GPT-Live -------------------------------------------------------------------------------

_LIVE = "sonia.live.prompts"

#: Las acciones del registro con su línea de capacidad (``_CAPABILITIES``).
_CAPABILITY_TITLES = {
    "show_image": "enseñar una imagen de la galería",
    "hide_image": "retirar la imagen",
    "play_animation": "bailar o hacer un gesto de la lista fija",
    "look": "mirar por la cámara",
    "start_trivia": "empezar la trivia",
    "trivia_answer": "registrar la respuesta de la trivia",
    "trivia_next": "siguiente pregunta de la trivia",
    "restart_trivia": "reiniciar la trivia",
    "stop_trivia": "terminar la trivia",
    "check_agenda": "consultar la agenda en la web",
    "show_talk": "enseñar la tarjeta de una charla",
}

#: Lo que solo hace el backend, para el recordatorio (``_BACKEND_DOES``).
_DOES_TITLES = {
    "show_image": "imágenes",
    "look": "mirar",
    "play_animation": "bailes y gestos",
    "start_trivia": "trivia",
    "start_game": "juegos",
    "check_agenda": "agenda",
    "show_talk": "tarjeta de una charla",
}

_MODES = {
    "notes": "notas [Cámara] automáticas",
    "look": "mira solo si delega",
    "none": "sin cámara",
}


def _register_live() -> None:
    from sonia.live import prompts as live

    def add(
        prompt_id: str,
        title: str,
        name: str,
        key: str | None = None,
        *,
        fields: tuple[str, ...] = (),
        required: tuple[str, ...] = (),
        must_contain: tuple[str, ...] = (),
        help: str = "",
    ) -> None:
        _add(
            f"conversacion/{prompt_id}",
            CONVERSATION,
            title,
            _const(_LIVE, name, key),
            fields=fields,
            required=required,
            must_contain=must_contain,
            help=help,
        )

    rules_fields = (
        "setting_rule",
        "clock_rule",
        "camera_rule",
        "trivia_rule",
        "capabilities",
        "look_when",
        "moves_when",
        "trivia_when",
        "agenda_when",
        "search_when",
        "no_delegate_chat",
    )
    add(
        "reglas",
        "Reglas de la voz: cómo funciona, política de turnos y de delegación (plantilla)",
        "LIVE_RULES",
        fields=rules_fields,
        required=rules_fields,
        must_contain=("Delegation policy",),
        help=(
            "Va justo después de la persona. Los marcadores los rellena el código con otras "
            "piezas de este grupo, según la configuración (vacíos si no aplican): "
            "{setting_rule} dónde está (stand o videollamada), {clock_rule} la hora, "
            "{camera_rule} cómo ve (y las caras), {trivia_rule} la trivia, {capabilities} las "
            "herramientas del backend, {look_when} {moves_when} {trivia_when} {agenda_when} "
            "{search_when} cuándo delegar cada cosa (cada una acaba en salto de línea, por eso "
            "van pegadas) y {no_delegate_chat} cuándo no delegar. Todos son obligatorios: para "
            "cambiar lo que dicen, edita su pieza. Los encabezados en inglés (Delegation "
            "policy...) son los de la plantilla oficial de GPT-Live: sin ellos no delegaba."
        ),
    )

    # Capacidades del backend ({capabilities}): una línea por acción.
    for name, title in _CAPABILITY_TITLES.items():
        if name in live._CAPABILITIES:
            add(
                f"capacidades/{name}",
                f"Herramienta del backend: {title}",
                "_CAPABILITIES",
                name,
                help=_IN_RULES.format(marker="{capabilities}", when=f"está la acción {name}"),
            )
    add(
        "capacidades/play_animation_cualquiera",
        "Herramienta del backend: cualquier gesto de Sage (con director de gestos)",
        "_ANY_GESTURE_CAPABILITY",
        help=(
            "Sustituye a la de «bailar o hacer un gesto de la lista fija» cuando el director de "
            "gestos tiene modelo y puede elegir cualquier gesto."
        ),
    )
    add(
        "capacidades/look_reunion",
        "Herramienta del backend: mirar la videollamada (modo reunión)",
        "_MEETING_LOOK_CAPABILITY",
        help="Sustituye a «mirar por la cámara» en una videollamada.",
    )
    add(
        "capacidades/web_search",
        "Herramienta del backend: buscar en internet",
        "_SEARCH_CAPABILITY",
        help=_IN_RULES.format(marker="{capabilities}", when="el backend puede buscar"),
    )
    add(
        "capacidades/ninguna",
        "Herramientas del backend: ninguna",
        "_NO_CAPABILITIES",
        help="Va en {capabilities} cuando el backend no tiene ninguna herramienta.",
    )

    # Cuándo delegar (van pegadas en la plantilla, una por línea).
    add(
        "delegar/mirar_notes",
        "Cuándo delegar: mirar (con notas [Cámara] automáticas)",
        "_LOOK_WHEN",
        "notes",
        help=_IN_RULES.format(marker="{look_when}", when="está «look» y llegan notas [Cámara]"),
    )
    add(
        "delegar/mirar_look",
        "Cuándo delegar: mirar (solo mira si delega)",
        "_LOOK_WHEN",
        "look",
        help=_IN_RULES.format(marker="{look_when}", when="está «look» y no hay notas automáticas"),
    )
    add(
        "delegar/mirar_reunion",
        "Cuándo delegar: mirar la videollamada (modo reunión)",
        "_MEETING_LOOK_WHEN",
        help="Sustituye a «mirar (solo mira si delega)» en una videollamada.",
    )
    add(
        "delegar/caras",
        "Cuándo delegar: «¿me reconoces?» sin nota de la cámara",
        "_FACES_LOOK_WHEN",
        help=_IN_RULES.format(marker="{look_when}", when="la cámara reconoce caras"),
    )
    add(
        "delegar/gestos",
        "Cuándo delegar: bailar o hacer un gesto",
        "_MOVES_WHEN",
        help=_IN_RULES.format(marker="{moves_when}", when="está play_animation"),
    )
    add(
        "delegar/trivia",
        "Cuándo delegar: la trivia",
        "_TRIVIA_WHEN",
        help=_IN_RULES.format(marker="{trivia_when}", when="hay trivia"),
    )
    add(
        "delegar/agenda",
        "Cuándo delegar: consultar la agenda",
        "_AGENDA_WHEN",
        help=_IN_RULES.format(marker="{agenda_when}", when="está check_agenda"),
    )
    add(
        "delegar/charla",
        "Cuándo delegar: enseñar la tarjeta de una charla",
        "_TALK_WHEN",
        help=_IN_RULES.format(marker="{agenda_when}", when="está show_talk"),
    )
    add(
        "delegar/busqueda",
        "Cuándo delegar: buscar en internet",
        "_SEARCH_WHEN",
        help=_IN_RULES.format(marker="{search_when}", when="el backend puede buscar"),
    )
    for mode, title in _MODES.items():
        add(
            f"no_delegar/{mode}",
            f"Cuándo no delegar: charlar ({title})",
            "_NO_DELEGATE_CHAT",
            mode,
            help=_IN_RULES.format(marker="{no_delegate_chat}", when=f"la cámara va así: {title}"),
        )

    # Bloques de las reglas.
    add(
        "lugar/stand",
        "Dónde está: en el stand, lleno de gente",
        "_STAND_RULE",
        help=_IN_RULES.format(marker="{setting_rule}", when="no está en una videollamada"),
    )
    add(
        "lugar/reunion",
        "Dónde está: en una videollamada",
        "_MEETING_SETTING_RULE",
        help=_IN_RULES.format(marker="{setting_rule}", when="está en modo reunión"),
    )
    add(
        "reloj",
        "La fecha, la hora y las notas [Reloj]",
        "_CLOCK_RULE",
        help=_IN_RULES.format(marker="{clock_rule}", when="siempre"),
    )
    add(
        "reloj/hora_exacta",
        "La hora exacta se pregunta al backend",
        "_CLOCK_ASK_RULE",
        help="Va detrás de «La fecha, la hora y las notas [Reloj]» si está check_agenda.",
    )
    for mode, title in _MODES.items():
        add(
            f"camara/{mode}",
            f"Cómo ve: {title}",
            "_CAMERA_RULE",
            mode,
            help=_IN_RULES.format(marker="{camera_rule}", when=f"la cámara va así: {title}"),
        )
    add(
        "camara/reunion",
        "Cómo ve: la pantalla de la videollamada",
        "_MEETING_RULE",
        help="Va delante de «Cómo ve» en una videollamada con cámara.",
    )
    add(
        "caras",
        "Caras conocidas: cómo usar las notas de quién llega",
        "_FACES_RULE",
        help="Va detrás de «Cómo ve» si la cámara reconoce caras.",
    )
    add(
        "trivia",
        "La trivia: las preguntas salen del backend",
        "_TRIVIA_RULE",
        help=_IN_RULES.format(marker="{trivia_rule}", when="hay trivia"),
    )

    # Secciones detrás de las reglas.
    add(
        "fecha_hora",
        "Fecha y hora al empezar la conversación",
        "_CLOCK_SECTION",
        fields=("fecha",),
        required=("fecha",),
        help="{fecha}: la fecha y la hora de Santo Domingo al abrir la sesión, en palabras.",
    )
    add(
        "reunion",
        "Modo reunión (manda sobre lo del stand)",
        "MEETING_SECTION",
        help="Va detrás de las reglas solo en modo reunión (sonia reunion).",
    )
    add(
        "conocimiento",
        "Encabezado de la base de conocimiento",
        "_KNOWLEDGE_SECTION",
        fields=("conocimiento",),
        required=("conocimiento",),
        help="{conocimiento}: los archivos del grupo «Conocimiento», uno detrás de otro.",
    )
    add(
        "avisos",
        "Encabezado de los avisos de hoy (también en el backend)",
        "_NOTES_SECTION",
        fields=("avisos",),
        required=("avisos",),
        help=(
            "{avisos}: los avisos del día escritos en el panel. Solo va si hay avisos, en las "
            "instrucciones de GPT-Live y en las del backend."
        ),
    )
    add(
        "galeria",
        "Galería: las imágenes que puede enseñar",
        "_GALLERY_LINE",
        fields=("imagenes",),
        required=("imagenes",),
        help="{imagenes}: los ids de la galería, separados por comas.",
    )
    add(
        "galeria/vacia",
        "Galería vacía",
        "_GALLERY_EMPTY",
        help="Sustituye a «Galería: las imágenes que puede enseñar» si no hay imágenes.",
    )
    add(
        "galeria/cambios",
        "Galería: avisos [Galería] cuando el equipo cambia imágenes",
        "_GALLERY_WATCH",
        help="Va detrás de la línea de la galería si se vigila la carpeta (GALLERY_WATCH_SECONDS).",
    )

    # El stack (cómo funciona Sonnia, sin marcas).
    stack = [
        ("titulo", "Stack: encabezado", "_STACK_TITLE", (), ""),
        ("voz", "Stack: voz y conversación", "_STACK_VOICE", (), ""),
        ("backend", "Stack: el backend", "_STACK_BACKEND", (), ""),
        ("ojos_ninguno", "Stack: ojos (sin cámara)", "_STACK_EYES_NONE", (), ""),
        (
            "ojos_look",
            "Stack: ojos (mira solo si delega)",
            "_STACK_EYES_LOOK",
            ("origen",),
            "{origen}: de dónde salen las fotos (la cámara del stand, la videollamada...).",
        ),
        (
            "ojos_notas",
            "Stack: ojos (notas [Cámara] automáticas)",
            "_STACK_EYES_NOTES",
            ("origen", "donde"),
            "{origen}: de dónde salen las fotos. {donde}: «en este mismo equipo» o «en la nube».",
        ),
        ("caras", "Stack: reconocer caras", "_STACK_FACES", (), ""),
        ("busqueda", "Stack: búsqueda en internet", "_STACK_SEARCH", (), ""),
        ("cuerpo", "Stack: el avatar", "_STACK_BODY", (), ""),
        (
            "acciones",
            "Stack: acciones disponibles",
            "_STACK_ACTIONS",
            ("acciones",),
            "{acciones}: los nombres de las acciones del backend, separados por comas.",
        ),
        ("sin_acciones", "Stack: sin acciones", "_STACK_NO_ACTIONS", (), ""),
        ("nube", "Stack: corre en la nube", "_STACK_CLOUD", (), ""),
        ("sin_marcas", "Stack: sin marcas", "_STACK_NO_BRANDS", (), ""),
    ]
    for key, title, name, fields, extra in stack:
        add(
            f"stack/{key}",
            title,
            name,
            fields=fields,
            help=(
                "Una línea de «TU STACK AHORA MISMO», casi al final de las instrucciones; el "
                "código le pone el guion delante. " + extra
            ).strip(),
        )

    # El recordatorio del final.
    add(
        "recordatorio/titulo",
        "Recordatorio final: encabezado",
        "_REMINDER_TITLE",
        help="Lo último de las instrucciones, que es lo que GPT-Live tiene más presente.",
    )
    add(
        "recordatorio/delegar",
        "Recordatorio final: delegar primero",
        "_REMINDER_DELEGATE",
        fields=("lista",),
        required=("lista",),
        help=(
            "{lista}: lo que solo hace el backend, con comas y una «y» (piezas «Recordatorio "
            "final: solo lo hace el backend»)."
        ),
    )
    for name, title in _DOES_TITLES.items():
        if name in live._BACKEND_DOES:
            add(
                f"recordatorio/hace/{name}",
                f"Recordatorio final: solo lo hace el backend ({title})",
                "_BACKEND_DOES",
                name,
                help="Un trozo de {lista} en «Recordatorio final: delegar primero».",
            )
    add(
        "recordatorio/hace/web_search",
        "Recordatorio final: solo lo hace el backend (buscar en internet)",
        "_BACKEND_DOES_SEARCH",
        help="Un trozo de {lista} en «Recordatorio final: delegar primero».",
    )
    add(
        "recordatorio/gestos",
        "Recordatorio final: bailes y gestos",
        "_REMINDER_MOVES",
        help="Si está play_animation.",
    )
    add(
        "recordatorio/trivia",
        "Recordatorio final: trivia",
        "_REMINDER_TRIVIA",
        help="Si hay trivia.",
    )
    add(
        "recordatorio/busqueda",
        "Recordatorio final: buscar en internet",
        "_REMINDER_SEARCH",
        help="Si el backend puede buscar.",
    )
    for mode, title in _MODES.items():
        add(
            f"recordatorio/aspecto_{mode}",
            f"Recordatorio final: el aspecto de la gente ({title})",
            "_LOOKS_REMINDER",
            mode,
            help=f"La última línea de las instrucciones cuando la cámara va así: {title}.",
        )


def _register_live_notes() -> None:
    """Lo que el motor le manda a GPT-Live con la sesión abierta (``session.*.append``)."""
    engine = "sonia.live.engine"
    cut = f" Con lo que rellena el código, lo que pase de {APPEND_MAX} caracteres se corta."
    notes = (
        (
            "texto_escrito",
            "Durante la conversación: un visitante escribe en la pantalla",
            "TEXT_INPUT_TEMPLATE",
            ("text",),
            "{text}: lo que escribió. Se le pide que conteste en voz alta.",
        ),
        (
            "interrupcion",
            "Durante la conversación: interrupción desde Unity",
            "INTERRUPT_TEXT",
            (),
            "Al tocar «Interrumpir» en los controles de desarrollo.",
        ),
        (
            "aviso",
            "Durante la conversación: aviso del panel para decir en voz alta",
            "ANNOUNCE_TEMPLATE",
            ("text",),
            "{text}: el aviso que escribe el equipo en el panel.",
        ),
        (
            "avisos_del_dia",
            "Durante la conversación: cambian los avisos de hoy",
            "NOTES_TEMPLATE",
            ("text",),
            "{text}: los avisos nuevos del panel. Al abrir sesión van con «Encabezado de los "
            "avisos de hoy».",
        ),
        (
            "avisos_retirados",
            "Durante la conversación: se retiran los avisos de hoy",
            "NOTES_CLEARED_TEXT",
            (),
            "",
        ),
        (
            "delegacion_fallida",
            "Durante la conversación: el backend no terminó la tarea",
            "DELEGATION_FAILED_TEXT",
            (),
            "Se le pide que lo diga en voz alta sin inventarse la respuesta.",
        ),
        (
            "agenda_cambiada",
            "Durante la conversación: la agenda cambió en la web",
            "AGENDA_CHANGED_TEMPLATE",
            ("changes",),
            "{changes}: los cambios detectados, ya escritos (los que caben).",
        ),
        (
            "agenda_mas",
            "Durante la conversación: hay más cambios de agenda de los que caben",
            "AGENDA_MORE_TEXT",
            (),
            "Va detrás de «la agenda cambió en la web» si no caben todos los cambios.",
        ),
    )
    for key, title, name, fields, extra in notes:
        _add(
            f"conversacion/notas/{key}",
            CONVERSATION,
            title,
            _const(engine, name),
            fields=fields,
            required=fields,
            applies="peticion",
            max_len=APPEND_MAX,
            help=(extra + cut).strip(),
        )


# -- Backend --------------------------------------------------------------------------------


def _register_backend() -> None:
    def add(
        prompt_id: str,
        title: str,
        name: str,
        *,
        fields: tuple[str, ...] = (),
        required: tuple[str, ...] = (),
        must_contain: tuple[str, ...] = (),
        help: str = "",
    ) -> None:
        _add(
            f"backend/{prompt_id}",
            BACKEND,
            title,
            _const(_LIVE, name),
            fields=fields,
            required=required,
            must_contain=must_contain,
            help=help,
        )

    add(
        "reglas",
        "Reglas del backend que ejecuta las acciones",
        "BACKEND_PROMPT",
        must_contain=("PARA SONIA:",),
        help=(
            "Lo primero de las instrucciones del backend en el que delega GPT-Live. Tiene que "
            "seguir diciendo «PARA SONIA:»: las acciones de la trivia y los juegos marcan así "
            "el guion que el backend le pasa entero a Sonnia."
        ),
    )
    add(
        "reunion",
        "Regla del backend en una videollamada",
        "_MEETING_BACKEND_RULE",
        help="Va detrás de las reglas del backend solo en modo reunión.",
    )
    add(
        "caras",
        "Regla del backend con caras conocidas",
        "_FACES_BACKEND_RULE",
        help=(
            "Va detrás de las reglas del backend si la cámara reconoce caras. El resultado de "
            "mirar trae «Personas conocidas en la foto»."
        ),
    )
    add(
        "busqueda",
        "Regla del backend para buscar en internet",
        "_BACKEND_SEARCH_RULE",
        help="Va detrás de las reglas del backend si puede buscar en internet.",
    )
    add(
        "fecha_hora",
        "Fecha y hora al empezar la conversación (backend)",
        "_BACKEND_CLOCK",
        fields=("fecha",),
        required=("fecha",),
        help="{fecha}: la fecha y la hora de Santo Domingo al abrir la sesión, en palabras.",
    )
    add(
        "galeria",
        "Galería al empezar (backend)",
        "_BACKEND_GALLERY",
        fields=("imagenes",),
        required=("imagenes",),
        help="{imagenes}: los ids de la galería, separados por comas, o «ninguna».",
    )
    add(
        "conocimiento",
        "Encabezado de la base de conocimiento (backend)",
        "_BACKEND_KNOWLEDGE",
        fields=("conocimiento",),
        required=("conocimiento",),
        help="{conocimiento}: los archivos del grupo «Conocimiento», uno detrás de otro.",
    )


# -- Visión y animación de stand -------------------------------------------------------------


def _register_vision() -> None:
    _add(
        "vision/narrador",
        VISION,
        "Prompt del modelo de visión que describe la cámara",
        _const("sonia.live.vision", "NARRATOR_PROMPT"),
        applies="peticion",
        help=(
            "Lo usa el modelo de visión para describir una foto de la cámara: las notas "
            "[Cámara] automáticas y los momentos de la animación de stand. La acción «look» "
            "no pasa por aquí: manda la foto al backend."
        ),
    )
    _add(
        "vision/pregunta",
        VISION,
        "Pregunta que acompaña a la foto (modelo de visión)",
        _const("sonia.live.vision", "NARRATOR_REQUEST"),
        applies="peticion",
    )
    _add(
        "vision/look",
        VISION,
        "Texto que acompaña a la foto de «look» (backend)",
        _const("sonia.live.engine", "LOOK_IMAGE_TEXT"),
        applies="peticion",
        help="Va con la foto que el backend recibe cuando Sonnia mira con la acción «look».",
    )


def _register_showcase() -> None:
    engine = "sonia.live.engine"
    cut = f" Con lo que rellena el código, lo que pase de {APPEND_MAX} caracteres se corta."
    _add(
        "animacion/frase",
        SHOWCASE,
        "Cómo se pide una frase del stand que no está grabada",
        _const(engine, "SHOWCASE_TEMPLATE"),
        fields=("text",),
        required=("text",),
        applies="peticion",
        max_len=APPEND_MAX,
        help="{text}: la frase de assets/showcase/frases.md que tiene que decir tal cual." + cut,
    )
    _add(
        "animacion/momento",
        SHOWCASE,
        "Momento del stand: cómo se pide una invitación improvisada",
        _const(engine, "MOMENT_TEMPLATE"),
        fields=("focus",),
        required=("focus",),
        applies="peticion",
        max_len=APPEND_MAX,
        help="{focus}: de qué tira el momento (las tres piezas «Momento del stand: tira de...»)."
        + cut,
    )
    focus = (
        ("agenda", "agenda", "lo que pasa ahora en el DevFest", ("text",)),
        ("camara", "cámara", "lo que ve la cámara", ("text",)),
        ("invitacion", "invitación", "algo que se puede probar", ()),
    )
    helps = {
        "agenda": "{text}: lo que hay ahora y a continuación hoy en la agenda.",
        "camara": "{text}: lo que describe el modelo de visión de una foto de la cámara.",
        "invitacion": "",
    }
    for key, name, title, fields in focus:
        _add(
            f"animacion/momento/{key}",
            SHOWCASE,
            f"Momento del stand: tira de {title}",
            _const(engine, "MOMENT_FOCUS", name),
            fields=fields,
            required=fields,
            applies="peticion",
            max_len=APPEND_MAX,
            help=(helps[key] + " Va en {focus} de «Momento del stand»." + cut).strip(),
        )
