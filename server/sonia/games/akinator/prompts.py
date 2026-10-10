"""Lo que lee GPT-Live en el Akinator dev: las reglas, los guiones y los empujones.

Todo esto es texto para GPT-Live: «Sonia» con una n y nada que nombre el stack (GPT-Live,
OpenAI, Unity...). Las reglas entran al empezar por ``instructions.append`` y no pasan de
1200 caracteres (``INSTRUCT_MAX_CHARS``): con el prompt muy largo dejó de delegar
(7 de octubre de 2026). Los guiones vuelven como resultado de cada jugada, marcados con
``PARA SONIA:``.
"""

from __future__ import annotations

from collections.abc import Sequence

from sonia.games.akinator.bank import Theme, themes_for_live
from sonia.games.base import INSTRUCT_MAX_CHARS

__all__ = [
    "FEW_LEFT_TEXT",
    "GIVEUP_NUDGE",
    "GIVEUP_SCRIPT",
    "GUESS_NUDGE",
    "GUESS_SCRIPT",
    "LAST_QUESTION_TEXT",
    "LIMIT_NUDGE",
    "LOSE_SCRIPT",
    "MISS_SCRIPT",
    "NOT_CLEAR_SCRIPT",
    "NO_GUESS_SCRIPT",
    "RESUME_SCRIPT",
    "WIN_SCRIPT",
    "build_rules",
    "build_start_script",
]

#: Margen bajo el tope de ``instruct`` por si cambia algo al montarlo.
RULES_MARGIN = 20

RULES_TEXT = """\
AKINATOR EN MARCHA: el visitante piensa en algo del mundo tech y tú lo adivinas con preguntas de sí o no ({max} como mucho).
- Una pregunta corta cada vez, solo de sí o no, y espera. Reacciona en pocas palabras. Las haces tú, sin delegar.
- Acepta «sí», «no», «no sé», «a veces» y «probablemente». No repitas preguntas. Lo que hablan entre ellos no es una respuesta.
- Empieza por lo general (¿persona?, ¿lenguaje?, ¿de Google?) y afina.
- Puede ser: {themes}.
- No arriesgues antes de la pregunta {min}. Si lo tienes claro, delega «akinator: adivina X» y pregunta «¿es X?». Cuando diga si acertaste o qué era, delega «akinator: resultado: sí o no, era Y».
- Si llegas a la {max} sin saberlo, arriesga o ríndete y pídele qué era.
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
RESUME_GUESS = " Tu respuesta «{answer}» está en la pantalla esperando que diga si acertaste."

#: Empujones: el visitante habló y no se delegó nada (``GAMES_NUDGE_SECONDS``). Lo decide ella.
GUESS_NUDGE = (
    "AKINATOR: tu respuesta está en la pantalla y el visitante acaba de hablarte. Si te dijo si "
    "acertaste, o qué era, delega «akinator: resultado» ahora mismo (decirlo no basta: la "
    "pantalla solo cambia si delegas). Si solo charlaba, no digas nada."
)
LIMIT_NUDGE = (
    "AKINATOR: ya hiciste tus {max} preguntas y no puedes hacer más. Si el visitante te dijo qué "
    "era, delega «akinator: resultado» con lo que era. Si no, delega «akinator: adivina X» con tu "
    "mejor idea, o ríndete y pregúntale qué era."
)
GIVEUP_NUDGE = (
    "AKINATOR: te has rendido y esperas que te diga qué era. Si ya te lo dijo, delega «akinator: "
    "resultado» con lo que era. Si no, pregúntaselo."
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

    Los temas del banco caben en lo que sobra: con muchos, llevan menos ejemplos cada uno.
    """
    bare = RULES_TEXT.format(max=max_questions, min=min_questions, themes="")
    budget = INSTRUCT_MAX_CHARS - RULES_MARGIN - len(bare)
    line = themes_for_live(themes, budget)
    text = RULES_TEXT.format(max=max_questions, min=min_questions, themes=line or "tecnología")
    return text[:INSTRUCT_MAX_CHARS]


def build_start_script(themes: Sequence[Theme]) -> str:
    """El guion de arranque que lee Sonia: explica el juego y espera a que el visitante piense."""
    names = ", ".join(theme.name.lower() for theme in themes[:START_THEMES])
    return START_SCRIPT.format(themes=names or "tecnología")
