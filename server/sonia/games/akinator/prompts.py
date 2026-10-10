"""Lo que lee GPT-Live en el Akinator dev: las reglas, los guiones y los empujones.

Todo esto es texto para GPT-Live: «Sonia» con una n y nada que nombre el stack (GPT-Live,
OpenAI, Unity...). Las reglas entran al empezar por ``instructions.append`` y no pasan de
1200 caracteres (``INSTRUCT_MAX_CHARS``): con el prompt muy largo dejó de delegar
(7 de octubre de 2026). Los guiones vuelven como resultado de cada jugada, marcados con
``PARA SONIA:``.

Las piezas se pueden cambiar desde el panel de la nube (``sonia.prompts``, :func:`prompt_specs`):
el juego pide cada una con :func:`live_text` al usarla. Los trozos que se pegan a otra pieza
(``RESUME_GUESS``, ``GIVEUP_REASON_MISS``, ``LOSE_CONTACT_TEXT``) siguen en el código.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from sonia.games.akinator.bank import Theme, themes_for_live
from sonia.games.base import INSTRUCT_MAX_CHARS
from sonia.prompts import BOOK, PROMPT_MAX_LEN, PromptSpec

__all__ = [
    "ASKING_NUDGE",
    "FEW_LEFT_TEXT",
    "GUESS_REMIND_TEXT",
    "GIVEUP_NUDGE",
    "START_NUDGE",
    "GIVEUP_SCRIPT",
    "GUESS_NUDGE",
    "GUESS_SCRIPT",
    "LAST_QUESTION_TEXT",
    "LIMIT_NUDGE",
    "LOSE_SCRIPT",
    "MISS_SCRIPT",
    "NOT_CLEAR_SCRIPT",
    "NO_GUESS_SCRIPT",
    "PANEL_ANSWER_SCRIPT",
    "PANEL_READY_SCRIPT",
    "RESUME_SCRIPT",
    "WIN_SCRIPT",
    "build_rules",
    "build_start_script",
    "live_text",
    "prompt_specs",
]

#: Margen bajo el tope de ``instruct`` por si cambia algo al montarlo.
RULES_MARGIN = 20

RULES_TEXT = """\
AKINATOR EN MARCHA: el visitante piensa en algo del mundo tech y tú lo adivinas con preguntas de sí o no ({max} como mucho).
- Una pregunta corta cada vez, solo de sí o no, y espera. Reacciona en pocas palabras. Las haces tú, sin delegar.
- Acepta «sí», «no», «no sé», «a veces» y «probablemente». No repitas preguntas. Lo que hablan entre ellos no es una respuesta.
- Empieza por lo general (¿persona?, ¿lenguaje?, ¿de Google?) y afina.
- Puede ser: {themes}.
- No arriesgues antes de la pregunta {min}. Si lo tienes claro, delega «akinator: adivina X» y pregunta «¿es X?».
- En cuanto diga si acertaste o qué era, delega «akinator: resultado» (acierto sí o no y lo que era) antes de celebrar o lamentarte; nunca «adivina» con lo que te diga.
- Si llegas a la {max} sin saberlo, arriesga o ríndete y pídele qué era.
- Si quieren dejarlo, delega terminar el juego: decir «paramos» no lo para.
- La pantalla solo cambia si delegas: nunca digas que acertaste o fallaste sin delegarlo."""

START_SCRIPT = (
    "Arranca el Akinator dev con energía. En dos frases cortas: que vas a adivinar lo que piense, "
    "y que piense en algo del mundo tech ({themes}) sin decírtelo. Si no sabe en qué pensar, dale "
    "una idea (un lenguaje, una empresa o alguien famoso de la informática). Pídele que te avise "
    "cuando lo tenga y espera: todavía no hagas ninguna pregunta. Cuando te diga que ya, empieza "
    "con tu primera pregunta de sí o no, una sola."
)

#: Cuántos temas nombra Sonia al abrir el juego (más se hace largo de decir).
START_THEMES = 5

GUESS_SCRIPT = (
    "Tu respuesta «{answer}» ya sale en la pantalla. Pregúntaselo con emoción, en una frase "
    "corta («¿Es… {answer}?»), y espera lo que conteste. Cuando diga si acertaste, o qué era, "
    "delega «akinator: resultado»."
)

EARLY_GUESS_SCRIPT = (
    "Todavía es pronto para arriesgar: llevas {asked} preguntas y no puedes adivinar antes de la "
    "{min}. Sigue con tus preguntas de sí o no y arriesga cuando lo tengas claro."
)

REPEATED_GUESS_SCRIPT = (
    "Ya probaste con «{answer}» y no era. Arriesga otra cosa o sigue con tus preguntas."
)

WIN_SCRIPT = (
    "¡Acertaste! Era «{answer}», en {asked} preguntas. Celébralo presumiendo con humor en una o "
    "dos frases cortas (el genio dev nunca falla) y pregúntale si quiere jugar otra vez."
)

#: A quien le gana a Sonia se le manda con el equipo del stand, como a quien gana la trivia.
LOSE_SCRIPT = (
    "Te ganó: era «{answer}». Reconócelo con humor («¡me ganaste!») en una o dos frases cortas y "
    "felicítale.{contact} Luego pregúntale si quiere jugar otra vez."
)
LOSE_CONTACT_TEXT = (
    " Dile que pase a hablar con {contact} aquí en el stand. No sabes qué premios hay: no "
    "prometas ninguno."
)

MISS_SCRIPT = (
    "«{answer}» no era. Díselo con humor en media frase y sigue con otra pregunta de sí o no, "
    "usando lo que ya sabes. Te quedan {left} preguntas."
)

#: Sin preguntas o sin intentos: se rinde y pregunta qué era.
GIVEUP_SCRIPT = (
    "{reason}Reconócelo con humor en una frase y pregúntale qué era. Cuando te lo diga, delega "
    "«akinator: resultado» con lo que era."
)
GIVEUP_REASON_MISS = "«{answer}» no era y ya no puedes arriesgar más. "
GIVEUP_REASON_LIMIT = "Ya no te quedan preguntas. "

NOT_CLEAR_SCRIPT = (
    "No quedó claro si acertaste. Pregúntaselo claro («¿acerté?») y, cuando conteste, delega "
    "«akinator: resultado»."
)

#: ``akinator_result`` sin ninguna respuesta tuya pendiente ni nada que contar.
NO_GUESS_SCRIPT = (
    "No hay ninguna respuesta tuya en la pantalla: las preguntas de sí o no no se delegan. Sigue "
    "preguntando y, cuando lo tengas claro, delega «akinator: adivina X»."
)

NO_ANSWER_SCRIPT = (
    "No sé qué respuesta es esa. Pásame en respuesta_real lo que era; si no te lo dijo, "
    "pregúntaselo."
)

RESUME_SCRIPT = (
    "Ya estáis jugando al Akinator dev: no hace falta empezarlo otra vez. Llevas {asked} de {max} "
    "preguntas.{guess} Sigue donde ibas."
)

#: Control a mano desde el panel (``AkinatorGame.panel_control``): lo que el equipo marca por
#: el visitante. El manager le pone delante que lo hizo el equipo.
PANEL_READY_SCRIPT = (
    "El visitante ya tiene algo pensado. Empieza con tu primera pregunta de sí o no, una sola, y "
    "espera lo que conteste."
)
PANEL_ANSWER_SCRIPT = (
    "El visitante contesta «{answer}» a tu última pregunta. Reacciona en pocas palabras y sigue "
    "con otra pregunta de sí o no; si ya lo tienes claro, delega «akinator: adivina X»."
)
RESUME_GUESS = " Tu respuesta «{answer}» está en la pantalla esperando que diga si acertaste."

#: Empujones: el visitante habló y no se delegó nada (``GAMES_NUDGE_SECONDS``). Órdenes cortas:
#: el manager añade al final que es una nota interna (en voz alta se oían). Lo decide ella.
GUESS_NUDGE = (
    "AKINATOR: si el visitante dijo si acertaste o qué era, delega ya «akinator: resultado», "
    "antes de celebrar; si pidió parar o se despidió, delega terminar el juego."
)
LIMIT_NUDGE = (
    "AKINATOR: ya hiciste tus {max} preguntas. Si te dijo qué era, delega «akinator: resultado»; "
    "si no, delega «akinator: adivina X» con tu mejor idea o pregúntale qué era."
)
START_NUDGE = (
    "AKINATOR: si el visitante ya tiene algo en mente y no has hecho tu primera pregunta, hazla: "
    "una corta de sí o no."
)
GIVEUP_NUDGE = (
    "AKINATOR: si ya te dijo qué era, delega «akinator: resultado» con lo que era; si no, "
    "pregúntaselo."
)
#: Tras un turno largo del visitante mientras preguntas (un «sí» o un «no» no lo son): puede
#: ser que lo deje o que diga qué era. En las pruebas con la API real, «Espera, mejor lo
#: dejamos» se quedaba en «Dale, paramos aquí» sin delegar.
ASKING_NUDGE = (
    "AKINATOR: si el visitante pidió parar o se despidió, delega terminar el juego; si dijo qué "
    "era, delega «akinator: resultado»."
)

#: Recordatorio, una vez: la respuesta de Sonia sigue en la pantalla sin resultado.
GUESS_REMIND_TEXT = (
    "AKINATOR: tu respuesta sigue en la pantalla sin resultado. Si ya te dijo si acertaste o qué "
    "era, delega ahora «akinator: resultado», sin celebrar antes; si no, pregúntale si acertaste."
)

#: Avisos silenciosos (``instructions.append``) mientras pregunta.
FEW_LEFT_TEXT = (
    "AKINATOR: llevas {asked} de {max} preguntas. Ve cerrando el círculo con lo que ya sabes."
)
LAST_QUESTION_TEXT = (
    "AKINATOR: la pregunta que acabas de hacer es la {max}, la última. Cuando conteste, arriesga "
    "tu mejor idea con «akinator: adivina X» o, si no tienes ninguna, ríndete y pídele que te "
    "diga qué era. No hagas más preguntas."
)


def build_rules(max_questions: int, min_questions: int, themes: Sequence[Theme]) -> str:
    """Las reglas del juego para GPT-Live (``instruct``), de menos de 1200 caracteres.

    Los temas del banco caben en lo que sobra de las reglas en uso (las de la nube, si las
    hay): con muchos, llevan menos ejemplos cada uno.
    """

    def rules(line: str) -> str:
        return live_text("reglas", RULES_TEXT, max=max_questions, min=min_questions, themes=line)

    budget = INSTRUCT_MAX_CHARS - RULES_MARGIN - len(rules(""))
    line = themes_for_live(themes, budget)
    return rules(line or "tecnología")[:INSTRUCT_MAX_CHARS]


def build_start_script(themes: Sequence[Theme]) -> str:
    """El guion de arranque que lee Sonia: explica el juego y espera a que el visitante piense."""
    names = ", ".join(theme.name.lower() for theme in themes[:START_THEMES])
    return live_text("arranque", START_SCRIPT, themes=names or "tecnología")


# -- prompts editables desde la nube (``sonia.prompts``) ---------------------------------

#: Ids de las piezas: ``juegos/akinator/<pieza>``.
PROMPT_PREFIX = "juegos/akinator/"
PROMPT_GROUP = "Juego: Akinator"


def live_text(piece: str, app_text: str, **values: object) -> str:
    """El texto en uso de la pieza (el de la nube si lo hay y vale; si no, ``app_text``, el
    de la app), con sus marcadores rellenos con ``values``."""
    return BOOK.render(PROMPT_PREFIX + piece, fallback=app_text, **values)


def _piece(
    piece: str,
    title: str,
    default: Callable[[], str],
    *,
    fields: tuple[str, ...] = (),
    required: tuple[str, ...] = (),
    help: str = "",
    instruct: bool = False,
) -> PromptSpec:
    return PromptSpec(
        id=PROMPT_PREFIX + piece,
        group=PROMPT_GROUP,
        title=title,
        default=default,
        fields=fields,
        required=required,
        applies="ronda",
        help=help,
        max_len=INSTRUCT_MAX_CHARS if instruct else PROMPT_MAX_LEN,
    )


_ASKED = "{asked}: cuántas preguntas lleva Sonia. "
_MAX = "{max}: cuántas preguntas puede hacer como mucho (GAME_AKINATOR_MAX_QUESTIONS). "
_ANSWER = "{answer}: la respuesta de la que se habla («Kotlin»). "
_NUDGE = (
    "Empujón tras un turno del visitante sin delegar: una orden corta, sin frases que pueda "
    "repetir (el código añade al final que es una nota interna). "
)


def prompt_specs() -> list[PromptSpec]:
    """Las piezas del Akinator dev editables desde el panel, en su orden."""
    return [
        _piece(
            "reglas",
            "Reglas del juego (al empezar, sin hablar)",
            lambda: RULES_TEXT,
            fields=("max", "min", "themes"),
            instruct=True,
            help=_MAX + "{min}: desde qué pregunta puede arriesgar (GAME_AKINATOR_MIN_QUESTIONS). "
            "{themes}: los temas del banco con ejemplos, recortados para que todo quepa en "
            "1200 caracteres.",
        ),
        _piece(
            "arranque",
            "Guion de arranque: presenta el juego y espera",
            lambda: START_SCRIPT,
            fields=("themes",),
            help="{themes}: los primeros temas del banco, en minúsculas.",
        ),
        _piece(
            "reanudar",
            "Guion si vuelve a pedir el juego que ya está en marcha",
            lambda: RESUME_SCRIPT,
            fields=("asked", "max", "guess"),
            help=_ASKED
            + _MAX
            + "{guess}: si hay una respuesta suya en pantalla, la frase que lo dice (con su "
            "espacio delante); si no, nada.",
        ),
        _piece(
            "adivina",
            "Guion al arriesgar una respuesta («¿Es… X?»)",
            lambda: GUESS_SCRIPT,
            fields=("answer",),
            help=_ANSWER,
        ),
        _piece(
            "pronto",
            "Guion si arriesga antes de la pregunta mínima",
            lambda: EARLY_GUESS_SCRIPT,
            fields=("asked", "min"),
            help=_ASKED + "{min}: desde qué pregunta puede arriesgar.",
        ),
        _piece(
            "repetida",
            "Guion si arriesga una respuesta que ya falló",
            lambda: REPEATED_GUESS_SCRIPT,
            fields=("answer",),
            help=_ANSWER,
        ),
        _piece(
            "acierto",
            "Guion cuando Sonia acierta",
            lambda: WIN_SCRIPT,
            fields=("answer", "asked"),
            help=_ANSWER + _ASKED,
        ),
        _piece(
            "derrota",
            "Guion cuando gana el visitante",
            lambda: LOSE_SCRIPT,
            fields=("answer", "contact"),
            required=("contact",),
            help=_ANSWER + "{contact}: la frase que manda al ganador con el equipo del stand "
            "(TRIVIA_WIN_CONTACT) y dice que no hay premios, con su espacio delante; nada si "
            "no hay contacto.",
        ),
        _piece(
            "fallo",
            "Guion cuando falla y le quedan preguntas",
            lambda: MISS_SCRIPT,
            fields=("answer", "left"),
            help=_ANSWER + "{left}: cuántas preguntas le quedan.",
        ),
        _piece(
            "se_rinde",
            "Guion cuando se rinde y pregunta qué era",
            lambda: GIVEUP_SCRIPT,
            fields=("reason",),
            help="{reason}: por qué se rinde (la frase de que su última respuesta no era y ya "
            "no puede arriesgar más, con su espacio detrás), o nada.",
        ),
        _piece(
            "no_claro",
            "Guion si no quedó claro si acertó",
            lambda: NOT_CLEAR_SCRIPT,
        ),
        _piece(
            "sin_adivinar",
            "Guion si delega el resultado sin haber arriesgado nada",
            lambda: NO_GUESS_SCRIPT,
        ),
        _piece(
            "sin_respuesta",
            "Aviso si dice que acertó sin decir qué era",
            lambda: NO_ANSWER_SCRIPT,
        ),
        _piece(
            "panel_listo",
            "Panel: «Ya lo pensó»",
            lambda: PANEL_READY_SCRIPT,
        ),
        _piece(
            "panel_respuesta",
            "Panel: «Sí», «No» o «No sé» a la pregunta en curso",
            lambda: PANEL_ANSWER_SCRIPT,
            fields=("answer",),
            help="{answer}: lo que contesta el visitante («sí», «no» o «no sé»).",
        ),
        _piece(
            "empujon_arranque",
            "Empujón: aún no hizo la primera pregunta",
            lambda: START_NUDGE,
            help=_NUDGE,
        ),
        _piece(
            "empujon_adivina",
            "Empujón: hay una respuesta suya en pantalla",
            lambda: GUESS_NUDGE,
            help=_NUDGE,
        ),
        _piece(
            "empujon_rendida",
            "Empujón: se rindió y espera saber qué era",
            lambda: GIVEUP_NUDGE,
            help=_NUDGE,
        ),
        _piece(
            "empujon_tope",
            "Empujón: ya hizo todas sus preguntas",
            lambda: LIMIT_NUDGE,
            fields=("max",),
            help=_NUDGE + _MAX,
        ),
        _piece(
            "empujon_turno_largo",
            "Empujón: el visitante habló largo mientras pregunta",
            lambda: ASKING_NUDGE,
            help=_NUDGE,
        ),
        _piece(
            "recuerda_resultado",
            "Recordatorio: su respuesta sigue en pantalla sin resultado",
            lambda: GUESS_REMIND_TEXT,
        ),
        _piece(
            "quedan_pocas",
            "Aviso silencioso: quedan cinco preguntas",
            lambda: FEW_LEFT_TEXT,
            fields=("asked", "max"),
            instruct=True,
            help=_ASKED + _MAX,
        ),
        _piece(
            "ultima_pregunta",
            "Aviso silencioso: acaba de hacer la última pregunta",
            lambda: LAST_QUESTION_TEXT,
            fields=("max",),
            instruct=True,
            help=_MAX,
        ),
    ]
