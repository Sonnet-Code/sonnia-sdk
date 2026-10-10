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

# ---------------------------------------------------------------------------
# Al empezar (``instruct``)
# ---------------------------------------------------------------------------

RULES_TEXT = """\
JUEGO EN MARCHA: la ruleta de Sonia. En tu pantalla gira una ruleta de cinco retos: {segments}.
- La ruleta la gira la pantalla: tú no eliges el reto ni lo adivinas. Cuando pare te llegarán el reto y sus reglas.
- Cada respuesta del visitante se delega: «ruleta: responde» (la letra, acierto, fallo o se rinden), «ruleta: nota» o «ruleta: predicción», según el reto. En la pantalla nada cambia si no lo delegas: nunca digas si acierta, su nota o «ya está» sin haberlo delegado.
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

NUDGE_CHALLENGE = (
    "RULETA: si el visitante dio su respuesta al reto, delégala ya, sin decir si acierta; si "
    "pidió otra vuelta, delega girar; si pidió parar o se despidió, delega terminar el juego."
)
NUDGE_RESULT = (
    "RULETA: si el visitante pidió otra vuelta, delega girar; si no quiere seguir o se "
    "despidió, delega terminar el juego."
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
