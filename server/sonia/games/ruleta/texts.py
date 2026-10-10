"""Lo que lee GPT-Live en la ruleta: reglas (``instruct``), avisos (``speak``) y guiones.

Reglas de todos los juegos (``docs/juegos.md``): «Sonia» (nunca «Sonnia») y ninguna
marca del stack; cada ``instruct`` como mucho 1200 caracteres, también con las entradas
más largas que admiten los bancos (lo comprueban los tests). GPT-Live no sabe la buena de
la trivia relámpago hasta el resultado; la respuesta de la adivinanza y de las preguntas de
Sonnet Code sí la recibe, para juzgar respuestas libres, con la orden de no decirla.

Las delegaciones se nombran como en la trivia («ruleta: responde B», «ruleta: girar»),
y las reglas insisten en que en la pantalla nada cambia sin delegar (lección de la trivia).
"""

from __future__ import annotations

from collections.abc import Callable

from sonia.games.base import INSTRUCT_MAX_CHARS
from sonia.prompts import PROMPT_MAX_LEN, PromptSpec

# ---------------------------------------------------------------------------
# Al empezar (``instruct``)
# ---------------------------------------------------------------------------

RULES_TEXT = """\
JUEGO EN MARCHA: la ruleta de Sonia. En tu pantalla gira una ruleta de cinco retos: {segments}.
- La ruleta la gira la pantalla: tú no eliges el reto ni lo adivinas. Cuando pare te llegarán el reto y sus reglas.
- Cada respuesta del visitante se delega: «ruleta: responde» (la letra, acierto, fallo o se rinden), «ruleta: nota» o «ruleta: predicción», según el reto. En la pantalla nada cambia si no lo delegas: nunca digas si acierta, su nota, que la ruleta gira, que terminas o «ya está» sin haberlo delegado.
- Lo que hablan entre ellos no es una respuesta: si no está claro que te contesta a ti, pregunta.
- Al terminar cada reto, pregunta si quieren otra vuelta: si dicen que sí, delega «ruleta: girar»; si no, delega terminar el juego. Si piden otro reto, también «ruleta: girar».
- Si en cualquier momento se despiden o dicen que ya está («gracias», «hasta luego»), delega terminar el juego.
- No hay premios: si preguntan, no sabes de ninguno; que hablen con {contact}."""

#: Si no hay nadie a quien mandar (``TRIVIA_WIN_CONTACT`` vacío).
NO_CONTACT = "el equipo del stand"

# ---------------------------------------------------------------------------
# Guiones del giro
# ---------------------------------------------------------------------------

START_TEXT = (
    "La ruleta de Sonia está en tu pantalla y ya está girando. Di en una frase y con emoción "
    "que la ruleta elige el reto, sin adivinar cuál: cuando pare te diré el reto y cómo se juega."
)
SPIN_TEXT = (
    "La ruleta gira otra vez en tu pantalla. Di algo corto y con emoción mientras gira, sin "
    "adivinar el reto: cuando pare te diré cuál es y cómo se juega."
)
SKIP_TEXT = (
    "Cambian de reto: el que había se queda sin jugar y la ruleta gira otra vez. Dilo en una "
    "frase corta, sin adivinar el siguiente: cuando pare te diré cuál es."
)

# ---------------------------------------------------------------------------
# Cada reto: reglas (``instruct``, al parar la ruleta) y aviso (``speak``)
# ---------------------------------------------------------------------------

#: Delante de las reglas de cada reto: GPT-Live conserva las del anterior.
NEW_CHALLENGE = "RETO DE LA RULETA (el anterior ya terminó): "

TRIVIA_RULES = (
    NEW_CHALLENGE + "TRIVIA RELÁMPAGO. Pregunta: «{question}». Opciones en tu pantalla, para "
    "que sepas qué letra elige (no las leas): A: {a}; B: {b}; C: {c}. No sabes cuál es la "
    "buena. Cuando el visitante diga su opción, la diga como la diga, pásala a su letra y "
    "delega enseguida «ruleta: responde» con A, B o C; si no lo sabe, «ruleta: responde se "
    "rinden». Nunca digas si acierta sin delegarlo. Tiene {seconds} segundos en el contador."
)
TRIVIA_ANNOUNCE = (
    "RULETA: ha caído en TRIVIA RELÁMPAGO. Anúncialo con emoción en pocas palabras y lee solo "
    "la pregunta, tal cual: «{question}». No leas las opciones: ya están en la pantalla. "
    "Luego espera su respuesta: no digas si acierta, delégala."
)

RIDDLE_RULES = (
    NEW_CHALLENGE + "ADIVINANZA GEEK. La adivinanza: «{riddle}». La respuesta es "
    "«{answer}»{variants}: es SOLO PARA TI, para juzgar lo que contesten; no la digas ni la "
    "insinúes hasta el resultado. Si contestan eso o algo equivalente, delega «ruleta: "
    "responde acierto»; si no, «ruleta: responde fallo» (tienen {tries} intentos); si se "
    "rinden o piden la solución, «ruleta: responde se rinden». Aunque sepas que no es, no lo "
    "digas tú: delega «ruleta: responde fallo» y espera el resultado. La pista sale sola en la "
    "pantalla a los {hint_seconds} segundos."
)
RIDDLE_ANNOUNCE = (
    "RULETA: ha caído en ADIVINANZA GEEK. Anúncialo con emoción en pocas palabras y lee la "
    "adivinanza tal cual: «{riddle}». No digas la respuesta. Luego espera la suya: no digas "
    "si acierta, delégala."
)
VARIANTS_TEXT = "; también valen: {variants}"

EXPLAIN_RULES = (
    NEW_CHALLENGE + "EXPLICA {tech_upper} EN {seconds} SEGUNDOS. El visitante tiene que "
    "explicarte qué es {tech}{description}. El contador de la pantalla arranca cuando empiece "
    "a hablar. Mientras explica, escúchale sin interrumpir ni comentar. Cuando suene «¡Tiempo!» "
    "o te diga que ha terminado, ponle una nota del 1 al 10 según lo bien que lo explicó: "
    "primero delega «ruleta: nota» con la nota y luego coméntala con humor y cariño. Si no "
    "quiere explicarlo, delega «ruleta: responde se rinden»."
)
EXPLAIN_DESCRIPTION = " (para ti: {description})"
EXPLAIN_ANNOUNCE = (
    "RULETA: ha caído en EXPLICA EN {seconds} SEGUNDOS. Anúncialo con emoción en pocas "
    "palabras: el visitante tiene que explicarte qué es {tech} en {seconds} segundos, y el "
    "tiempo arranca cuando empiece a hablar. Luego calla y escucha."
)

FUTURE_RULES = (
    NEW_CHALLENGE + "PREDICE EL FUTURO DE LA IA. Pídele al visitante su predicción sobre la "
    "inteligencia artificial: qué cree que pasará. Cuando te la diga, resúmela en una frase "
    "corta en español (120 caracteres como mucho, sin nombres de personas) y ponle una "
    "probabilidad de 0 a 100, con gracia: delega «ruleta: predicción» con las dos y después "
    "coméntala con humor. Si no quiere predecir nada, delega «ruleta: responde se rinden»."
)
FUTURE_ANNOUNCE = (
    "RULETA: ha caído en PREDICE EL FUTURO DE LA IA. Anúncialo con emoción en pocas palabras "
    "y pídele al visitante su predicción: qué pasará con la inteligencia artificial en los "
    "próximos años."
)

SONNET_QUESTION_RULES = (
    NEW_CHALLENGE + "RETO SORPRESA DE SONNET CODE, una pregunta: «{question}». La respuesta "
    "es «{answer}»{variants}: es SOLO PARA TI, para juzgar lo que conteste; no la digas antes "
    "del resultado. Si contesta eso o algo equivalente, delega «ruleta: responde acierto»; si "
    "no, «ruleta: responde fallo» (tiene {tries} intentos); si se rinde, «ruleta: responde se "
    "rinden»."
)
SONNET_QUESTION_ANNOUNCE = (
    "RULETA: ha caído en el RETO SORPRESA DE SONNET CODE. Anúncialo con emoción en pocas "
    "palabras y haz la pregunta tal cual: «{question}». No digas la respuesta. Luego espera la "
    "suya: no digas si acierta, delégala."
)
SONNET_TASK_RULES = (
    NEW_CHALLENGE + "RETO SORPRESA DE SONNET CODE: «{task}». No lo puedes comprobar: créele. "
    "Cuando te diga que lo ha hecho, delega «ruleta: responde acierto»; si no quiere o no "
    "puede, «ruleta: responde se rinden»."
)
SONNET_TASK_ANNOUNCE = (
    "RULETA: ha caído en el RETO SORPRESA DE SONNET CODE. Anúncialo con emoción en pocas "
    "palabras y cuéntale el reto: «{task}»."
)

# ---------------------------------------------------------------------------
# Mientras se juega el reto (``speak``)
# ---------------------------------------------------------------------------

HINT_TEXT = (
    "RULETA: ya salió la pista de la adivinanza en tu pantalla. Dila tal cual, en una frase y "
    "sin decir la respuesta: «{hint}»."
)
QUIZ_REMIND_TEXT = (
    "RULETA: se acabó el tiempo de la trivia relámpago y no hay respuesta registrada. Si ya te "
    "dijo su opción, delega ahora «ruleta: responde» con su letra, sin decir si acierta. Si no, "
    "pídele en pocas palabras que elija ya, sin leer las opciones."
)
TIME_UP_TEXT = (
    "RULETA: se acabó el tiempo de la explicación. Ponle una nota del 1 al 10 según lo bien que "
    "lo explicó: primero delega «ruleta: nota» con la nota y luego coméntala con humor."
)
#: Si el «¡Tiempo!» grabado no pudo sonar (Sonia hablaba): que lo diga ella.
TIME_UP_SAY_TEXT = (
    "RULETA: se acabó el tiempo de la explicación. Di «¡Tiempo!» y ponle una nota del 1 al 10 "
    "según lo bien que lo explicó: primero delega «ruleta: nota» con la nota y luego coméntala "
    "con humor."
)

#: La frase grabada del final del contador (``say_fixed``, ``phrases``).
TIME_PHRASE = "¡Tiempo!"

# ---------------------------------------------------------------------------
# Resultados (lo que devuelve cada jugada)
# ---------------------------------------------------------------------------

AGAIN_TEXT = (
    " Luego pregunta si quieren otra vuelta a la ruleta: si dicen que sí, delega «ruleta: "
    "girar»; si no, delega terminar el juego."
)
FACT_TEXT = " Si cabe, en media frase: {fact}"

TRIVIA_RIGHT = "Ha elegido la {letter}, «{option}»: es CORRECTA. Celébralo en una frase corta."
TRIVIA_WRONG = (
    "Ha elegido la {letter}, «{option}»: NO es correcta; la buena era la {right_letter}, "
    "«{right_option}». Díselo con cariño en una frase corta."
)
TRIVIA_PASS = (
    "No lo sabe: la buena era la {right_letter}, «{right_option}». Díselo con cariño en una "
    "frase corta."
)

RIDDLE_RIGHT = "¡ACIERTO! Era «{answer}». Celébralo en una frase."
RIDDLE_MISS = (
    "Fallo registrado: no es eso. Anímale a intentarlo otra vez, sin decir ni insinuar la "
    "respuesta. {left}"
)
RIDDLE_MISS_HINT = " Dale la pista, que ya sale en la pantalla: «{hint}»."
RIDDLE_LOST = (
    "Fallo: se acabaron los intentos. La respuesta era «{answer}». Díselo con cariño y con humor."
)
RIDDLE_PASS = "Se rinden: la respuesta era «{answer}». Díselo con humor, en una frase."

EXPLAIN_SCORE = (
    "Nota {score} de 10 en la pantalla. Coméntala con humor y cariño en una frase corta."
)
EXPLAIN_PASS = "No quiere explicarlo, y no pasa nada: dilo con humor en una frase."

FUTURE_DONE = (
    "En la pantalla: «{prediction}», con un {probability} % de probabilidad. Coméntalo con "
    "humor en una frase corta."
)
FUTURE_PASS = "No quiere predecir nada, y no pasa nada: dilo con humor en una frase."

SONNET_RIGHT = "¡ACIERTO! Era «{answer}». Celébralo en una frase."
SONNET_DONE = "¡RETO CUMPLIDO! Celébralo en una frase y dale las gracias."
SONNET_MISS = (
    "Fallo registrado: no es eso. Anímale a intentarlo otra vez, sin decir la respuesta. {left}"
)
SONNET_LOST = "Fallo: la respuesta era «{answer}». Díselo con cariño, en una frase."
SONNET_QUESTION_PASS = "Se rinde: la respuesta era «{answer}». Díselo con humor, en una frase."
SONNET_TASK_PASS = "No quiere hacer el reto, y no pasa nada: dilo con humor en una frase."
SONNET_TASK_FAILED = "No le salió el reto. Anímale con cariño, en una frase."

LEFT_ONE = "Le queda un intento."
LEFT_MANY = "Le quedan {left} intentos."

#: Al llegar a :data:`WIN_MARK` retos superados en la partida (una vez): sin premios.
WIN_CONTACT_TEXT = (
    " Ya lleva {wins} retos superados: dile que pase a saludar a {contact} aquí en el stand. "
    "No sabes qué premios hay: no prometas ninguno."
)

# ---------------------------------------------------------------------------
# Jugadas fuera de turno (``GameError``: Sonia lo lee tal cual)
# ---------------------------------------------------------------------------

SPINNING_WAIT = (
    "La ruleta aún está girando: espera a que pare, enseguida te digo el reto. No adivines cuál "
    "será."
)
ALREADY_SPINNING = "La ruleta ya está girando: espera a que pare."
ROUND_OVER = (
    "Este reto ya terminó y su resultado está en la pantalla. Si quieren otra vuelta, delega "
    "«ruleta: girar»; si no, delega terminar el juego."
)
NOT_SAID_YET = (
    "Aún no ha contestado: espera su respuesta o pregúntale. No digas la respuesta ni si acierta."
)
WRONG_PLAY = {
    "trivia": (
        "En la trivia relámpago delega la letra que eligió (A, B o C), o «se rinden» si no lo "
        "sabe: tú no sabes cuál es la buena."
    ),
    "adivinanza": (
        "En la adivinanza delega «acierto» o «fallo» según lo que contestó (lo juzgas tú con la "
        "respuesta que tienes), o «se rinden»."
    ),
    "explica": (
        "En este reto se pone nota: cuando termine de explicar, delega «ruleta: nota» con una "
        "nota del 1 al 10, o «ruleta: responde se rinden» si no quiere explicarlo."
    ),
    "futuro": (
        "En este reto delega «ruleta: predicción» con su predicción resumida y una probabilidad "
        "de 0 a 100, o «ruleta: responde se rinden» si no quiere predecir."
    ),
    "sonnet": (
        "En el reto de Sonnet Code delega «acierto» si lo contestó bien o lo hizo, «fallo» si "
        "no, o «se rinden»."
    ),
}
NO_PREDICTION = (
    "Aún no hay predicción: pídele al visitante que te diga qué cree que pasará con la IA y "
    "luego delega su predicción resumida con una probabilidad."
)

# ---------------------------------------------------------------------------
# Empujones tras un turno del visitante sin delegación (``nudge``)
# ---------------------------------------------------------------------------

#: Girar solo si lo pidieron: con «si pidió otra vuelta, delega girar», ante una charla entre
#: ellos Sonia decía «Dale, la giro otra vez» sin delegar nada (pruebas con Unity, 10 de
#: octubre de 2026): anunciaba una vuelta que no ocurría.
NUDGE_CHALLENGE = (
    "RULETA: si el visitante te dio su respuesta al reto, delégala ya, sin decir si acierta. "
    "Solo si te pidió otra vuelta, delega girar; si pidió parar o se despidió, delega terminar "
    "el juego. Nunca digas que gira o que terminas sin delegarlo."
)
NUDGE_RESULT = (
    "RULETA: solo si el visitante te pidió otra vuelta, delega girar; si no quiere seguir o se "
    "despidió, delega terminar el juego. Nunca digas que gira o que terminas sin delegarlo."
)
#: Mientras gira la ruleta solo cuenta parar (el reto aún no ha salido).
NUDGE_SPINNING = "RULETA: si el visitante pidió parar o se despidió, delega terminar el juego."

# ---------------------------------------------------------------------------
# Si GPT-Live vuelve a delegar empezar la ruleta en plena partida (``resume``)
# ---------------------------------------------------------------------------

RESUME_SPINNING = (
    "Ya estáis jugando a la ruleta de Sonia y está girando: espera a que pare, enseguida te "
    "digo el reto."
)
RESUME_CHALLENGE = (
    "Ya estáis jugando a la ruleta de Sonia: el reto en pantalla es {spoken}. Sigue con él; si "
    "quieren otro, delega «ruleta: girar»."
)
RESUME_RESULT = (
    "Ya estáis jugando a la ruleta de Sonia y el último reto ya terminó. Pregunta si quieren "
    "otra vuelta: si sí, delega «ruleta: girar»; si no, delega terminar el juego."
)

# ---------------------------------------------------------------------------
# Piezas editables desde el panel de la nube (``sonia.prompts``, petición de Jean del
# 10-oct-2026). ``game.py`` pide el texto en uso al usarlo; con los de la app, lo que
# recibe GPT-Live es idéntico al de siempre (``tests/test_prompts_ruleta.py``). Fase 2:
# los trozos que se pegan a otros (NEW_CHALLENGE, VARIANTS_TEXT, EXPLAIN_DESCRIPTION,
# FACT_TEXT, RIDDLE_MISS_HINT, LEFT_*, NO_CONTACT), las reconducciones fuera de turno
# (``GameError``), la frase grabada TIME_PHRASE y las descripciones de las jugadas.
# ---------------------------------------------------------------------------

#: Prefijo de los ids de las piezas y su grupo en el panel.
PROMPTS = "juegos/ruleta"
GROUP = "Juego: Ruleta"

_INSTRUCT = "Le llega a Sonia sin que hable, 1200 caracteres como mucho (con todo ya relleno). "
_SCRIPT = "Lo que Sonia tiene que decir ahora; ella lo dice con sus palabras. "
_RESULT = (
    "Va tras la jugada que registra el resultado; detrás se añade la pregunta de otra vuelta. "
)


def _spec(
    name: str,
    title: str,
    default: Callable[[], str],
    note: str,
    *,
    fields: tuple[str, ...] = (),
    required: tuple[str, ...] = (),
    instruct: bool = False,
) -> PromptSpec:
    return PromptSpec(
        id=f"{PROMPTS}/{name}",
        group=GROUP,
        title=title,
        default=default,
        fields=fields,
        required=required,
        applies="ronda",
        help=(_INSTRUCT if instruct else "") + note,
        max_len=INSTRUCT_MAX_CHARS if instruct else PROMPT_MAX_LEN,
    )


def prompt_specs() -> list[PromptSpec]:
    """Las piezas de la ruleta que se pueden editar desde el panel, en su orden."""
    answer = "{answer}: la respuesta, solo para que Sonia juzgue (no la dice). "
    variants = "{variants}: «; también valen: ...» con las variantes del banco, o nada. "
    return [
        _spec(
            "reglas",
            "Reglas de la ruleta, al empezar",
            lambda: RULES_TEXT,
            "{segments}: los retos que pueden salir («trivia relámpago, adivinanza geek... y "
            "...»). {contact}: con quién hablar si preguntan por premios (TRIVIA_WIN_CONTACT o "
            "«el equipo del stand»).",
            fields=("segments", "contact"),
            instruct=True,
        ),
        _spec("empezar", "Guion al empezar: la ruleta ya gira", lambda: START_TEXT, _SCRIPT),
        _spec("girar", "Guion de otra vuelta", lambda: SPIN_TEXT, _SCRIPT),
        _spec("saltar", "Guion al cambiar de reto con uno a medias", lambda: SKIP_TEXT, _SCRIPT),
        _spec(
            "otra_vuelta",
            "Final de cada resultado: ¿otra vuelta?",
            lambda: AGAIN_TEXT.strip(),
            "Se añade detrás de cada resultado. Tiene que seguir pidiendo que delegue girar o "
            "terminar el juego.",
        ),
        _spec(
            "equipo",
            "Al superar el tercer reto: que pase a saludar al equipo",
            lambda: WIN_CONTACT_TEXT.strip(),
            "Se añade una vez por partida al resultado del tercer reto superado. {wins}: los "
            "retos superados. {contact}: a quién saludar (TRIVIA_WIN_CONTACT).",
            fields=("wins", "contact"),
            required=("contact",),
        ),
        # -- trivia relámpago --
        _spec(
            "trivia_reglas",
            "Trivia relámpago: reglas del reto",
            lambda: TRIVIA_RULES,
            "{question}: la pregunta. {a}, {b}, {c}: las opciones (Sonia no sabe cuál es la "
            "buena). {seconds}: los segundos del contador.",
            fields=("question", "a", "b", "c", "seconds"),
            required=("a", "b", "c"),
            instruct=True,
        ),
        _spec(
            "trivia_anuncio",
            "Trivia relámpago: anuncio del reto",
            lambda: TRIVIA_ANNOUNCE,
            _SCRIPT + "{question}: la pregunta, para que la lea.",
            fields=("question",),
            required=("question",),
        ),
        _spec(
            "trivia_recordatorio",
            "Trivia relámpago: se acabó el tiempo sin respuesta",
            lambda: QUIZ_REMIND_TEXT,
            _SCRIPT,
        ),
        _spec(
            "trivia_acierto",
            "Trivia relámpago: acierto",
            lambda: TRIVIA_RIGHT,
            _RESULT + "{letter}: la letra que eligió. {option}: su opción.",
            fields=("letter", "option"),
        ),
        _spec(
            "trivia_fallo",
            "Trivia relámpago: fallo",
            lambda: TRIVIA_WRONG,
            _RESULT + "{letter} y {option}: lo que eligió. {right_letter} y {right_option}: "
            "la buena.",
            fields=("letter", "option", "right_letter", "right_option"),
        ),
        _spec(
            "trivia_no_lo_sabe",
            "Trivia relámpago: no lo sabe",
            lambda: TRIVIA_PASS,
            _RESULT + "{right_letter} y {right_option}: la buena.",
            fields=("right_letter", "right_option"),
        ),
        # -- adivinanza geek --
        _spec(
            "adivinanza_reglas",
            "Adivinanza geek: reglas del reto",
            lambda: RIDDLE_RULES,
            "{riddle}: la adivinanza. "
            + answer
            + variants
            + "{tries}: los intentos. {hint_seconds}: los segundos hasta que sale la pista.",
            fields=("riddle", "answer", "variants", "tries", "hint_seconds"),
            required=("answer",),
            instruct=True,
        ),
        _spec(
            "adivinanza_anuncio",
            "Adivinanza geek: anuncio del reto",
            lambda: RIDDLE_ANNOUNCE,
            _SCRIPT + "{riddle}: la adivinanza, para que la lea.",
            fields=("riddle",),
            required=("riddle",),
        ),
        _spec(
            "adivinanza_pista",
            "Adivinanza geek: sale la pista sola",
            lambda: HINT_TEXT,
            _SCRIPT + "{hint}: la pista, para que la diga.",
            fields=("hint",),
            required=("hint",),
        ),
        _spec(
            "adivinanza_acierto",
            "Adivinanza geek: acierto",
            lambda: RIDDLE_RIGHT,
            _RESULT + "{answer}: la respuesta.",
            fields=("answer",),
        ),
        _spec(
            "adivinanza_fallo",
            "Adivinanza geek: fallo con intentos",
            lambda: RIDDLE_MISS,
            "Lo devuelve la jugada del fallo (sin pregunta de otra vuelta: el reto sigue); con "
            "el primer fallo se le añade la pista. {left}: «Le queda un intento.» o «Le quedan "
            "N intentos.».",
            fields=("left",),
        ),
        _spec(
            "adivinanza_perdida",
            "Adivinanza geek: sin intentos",
            lambda: RIDDLE_LOST,
            _RESULT + "{answer}: la respuesta.",
            fields=("answer",),
        ),
        _spec(
            "adivinanza_rendirse",
            "Adivinanza geek: se rinden",
            lambda: RIDDLE_PASS,
            _RESULT + "{answer}: la respuesta.",
            fields=("answer",),
        ),
        # -- explica en 20 segundos --
        _spec(
            "explica_reglas",
            "Explica en 20 segundos: reglas del reto",
            lambda: EXPLAIN_RULES,
            "{tech}: la tecnología como va en una frase («la nube»). {tech_upper}: en "
            "mayúsculas. {seconds}: los segundos para explicarla. {description}: « (para ti: "
            "de qué va)» con la nota del banco, o nada.",
            fields=("tech_upper", "tech", "seconds", "description"),
            required=("tech",),
            instruct=True,
        ),
        _spec(
            "explica_anuncio",
            "Explica en 20 segundos: anuncio del reto",
            lambda: EXPLAIN_ANNOUNCE,
            _SCRIPT + "{tech}: la tecnología. {seconds}: los segundos para explicarla.",
            fields=("tech", "seconds"),
            required=("tech",),
        ),
        _spec(
            "explica_tiempo",
            "Explica en 20 segundos: se acabó el tiempo (con el «¡Tiempo!» grabado)",
            lambda: TIME_UP_TEXT,
            _SCRIPT + "Ya sonó «¡Tiempo!»: tiene que pedirle que delegue la nota.",
        ),
        _spec(
            "explica_tiempo_sin_grabar",
            "Explica en 20 segundos: se acabó el tiempo (sin el «¡Tiempo!» grabado)",
            lambda: TIME_UP_SAY_TEXT,
            _SCRIPT + "No pudo sonar «¡Tiempo!» grabado: que lo diga ella y delegue la nota.",
        ),
        _spec(
            "explica_nota",
            "Explica en 20 segundos: la nota",
            lambda: EXPLAIN_SCORE,
            _RESULT + "{score}: la nota que puso Sonia.",
            fields=("score",),
        ),
        _spec(
            "explica_rendirse",
            "Explica en 20 segundos: no quiere explicarlo",
            lambda: EXPLAIN_PASS,
            _RESULT,
        ),
        # -- predice el futuro de la IA --
        _spec(
            "futuro_reglas",
            "Futuro de la IA: reglas del reto",
            lambda: FUTURE_RULES,
            "La predicción se resume en 120 caracteres como mucho (el tope de la pantalla).",
            instruct=True,
        ),
        _spec(
            "futuro_anuncio", "Futuro de la IA: anuncio del reto", lambda: FUTURE_ANNOUNCE, _SCRIPT
        ),
        _spec(
            "futuro_hecho",
            "Futuro de la IA: la predicción en pantalla",
            lambda: FUTURE_DONE,
            _RESULT + "{prediction}: la predicción resumida. {probability}: su probabilidad.",
            fields=("prediction", "probability"),
        ),
        _spec(
            "futuro_rendirse",
            "Futuro de la IA: no quiere predecir",
            lambda: FUTURE_PASS,
            _RESULT,
        ),
        # -- reto sorpresa de Sonnet Code --
        _spec(
            "sonnet_pregunta_reglas",
            "Sonnet Code, pregunta: reglas del reto",
            lambda: SONNET_QUESTION_RULES,
            "{question}: la pregunta. " + answer + variants + "{tries}: los intentos.",
            fields=("question", "answer", "variants", "tries"),
            required=("answer",),
            instruct=True,
        ),
        _spec(
            "sonnet_pregunta_anuncio",
            "Sonnet Code, pregunta: anuncio del reto",
            lambda: SONNET_QUESTION_ANNOUNCE,
            _SCRIPT + "{question}: la pregunta, para que la haga.",
            fields=("question",),
            required=("question",),
        ),
        _spec(
            "sonnet_acierto",
            "Sonnet Code, pregunta: acierto",
            lambda: SONNET_RIGHT,
            _RESULT + "{answer}: la respuesta.",
            fields=("answer",),
        ),
        _spec(
            "sonnet_fallo",
            "Sonnet Code, pregunta: fallo con intentos",
            lambda: SONNET_MISS,
            "Lo devuelve la jugada del fallo (sin pregunta de otra vuelta: el reto sigue). "
            "{left}: «Le queda un intento.» o «Le quedan N intentos.».",
            fields=("left",),
        ),
        _spec(
            "sonnet_perdida",
            "Sonnet Code, pregunta: sin intentos",
            lambda: SONNET_LOST,
            _RESULT + "{answer}: la respuesta.",
            fields=("answer",),
        ),
        _spec(
            "sonnet_pregunta_rendirse",
            "Sonnet Code, pregunta: se rinde",
            lambda: SONNET_QUESTION_PASS,
            _RESULT + "{answer}: la respuesta.",
            fields=("answer",),
        ),
        _spec(
            "sonnet_reto_reglas",
            "Sonnet Code, reto de stand: reglas del reto",
            lambda: SONNET_TASK_RULES,
            "{task}: el reto, del banco de retos de Sonnet Code.",
            fields=("task",),
            instruct=True,
        ),
        _spec(
            "sonnet_reto_anuncio",
            "Sonnet Code, reto de stand: anuncio del reto",
            lambda: SONNET_TASK_ANNOUNCE,
            _SCRIPT + "{task}: el reto, para que se lo cuente.",
            fields=("task",),
            required=("task",),
        ),
        _spec(
            "sonnet_reto_cumplido",
            "Sonnet Code, reto de stand: cumplido",
            lambda: SONNET_DONE,
            _RESULT,
        ),
        _spec(
            "sonnet_reto_fallido",
            "Sonnet Code, reto de stand: no le salió",
            lambda: SONNET_TASK_FAILED,
            _RESULT,
        ),
        _spec(
            "sonnet_reto_rendirse",
            "Sonnet Code, reto de stand: no quiere hacerlo",
            lambda: SONNET_TASK_PASS,
            _RESULT,
        ),
        # -- empujones y seguir --
        _spec(
            "empujon_reto",
            "Empujón con un reto en juego",
            lambda: NUDGE_CHALLENGE,
            "Tras un turno del visitante sin delegación; es una orden corta, no una frase "
            "que decir (el código le añade que, si no, siga sin decir nada).",
        ),
        _spec(
            "empujon_resultado",
            "Empujón con el resultado en pantalla",
            lambda: NUDGE_RESULT,
            "Tras un turno del visitante sin delegación; orden corta, no una frase que decir.",
        ),
        _spec(
            "empujon_girando",
            "Empujón mientras gira",
            lambda: NUDGE_SPINNING,
            "Tras un turno del visitante sin delegación; orden corta, no una frase que decir.",
        ),
        _spec(
            "seguir_girando",
            "Si vuelve a pedir la ruleta mientras gira",
            lambda: RESUME_SPINNING,
            _SCRIPT,
        ),
        _spec(
            "seguir_reto",
            "Si vuelve a pedir la ruleta con un reto en juego",
            lambda: RESUME_CHALLENGE,
            _SCRIPT + "{spoken}: el reto en pantalla («adivinanza geek»).",
            fields=("spoken",),
        ),
        _spec(
            "seguir_resultado",
            "Si vuelve a pedir la ruleta con el resultado en pantalla",
            lambda: RESUME_RESULT,
            _SCRIPT,
        ),
    ]
