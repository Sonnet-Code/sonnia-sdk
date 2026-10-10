"""Las preguntas de Sonia en su transcripción, para el contador de la pantalla.

Sonia pregunta sin delegar (una delegación por pregunta lo haría lentísimo), así que el
orquestador no sabe cuántas lleva más que mirando lo que dice. Solo sirve para pintar los
20 puntos de la tarjeta y para avisarle de que se queda sin preguntas: no es una cuenta
exacta ni hace falta que lo sea.

El motor llama a :meth:`Game.on_assistant_text` con el texto **acumulado** de la frase en
curso (cada trozo que llega) y, al cerrarse la frase, una vez más con la frase entera
(``final=True``). Por eso el contador:

- **Es idempotente.** Cada pregunta se cuenta una vez, por su texto normalizado (sin
  mayúsculas, tildes ni signos): el mismo texto creciendo, la frase final repitiéndolo o
  Sonia repitiendo la pregunta en otra frase no suben la cuenta.
- **No cuenta las parciales.** Una pregunta existe cuando llega su ``?``; mientras se está
  diciendo («¿Es un lenguaje de progr») no hay nada que contar.
- **Cuenta una por frase.** Si la misma frase trae dos preguntas («¿Es un lenguaje? ¿O una
  herramienta?»), cuenta una, la última. Si la segunda llega cuando la primera ya estaba
  contada (el texto sigue creciendo), la sustituye en la pantalla sin subir la cuenta.
- **No cuenta lo que no es una pregunta del juego**: los «¿verdad?», «¿listo?» y
  «¿cómo dices?» (una sola palabra, o frases hechas).
- **No depende de que llegue el cierre de la frase.** Si no llega, la frase siguiente se
  reconoce porque su texto no continúa el anterior.
- **Aguanta que el «?» llegue tarde.** El texto de la transcripción y el audio que corta el
  motor en frases no van pegados: si la frase se cierra con una pregunta empezada («¿Es un
  lenguaje de programación») y la siguiente empieza por su «?», se juntan.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sonia.games.akinator.bank import normalize

__all__ = [
    "QuestionCounter",
    "QuestionUpdate",
    "extract_questions",
    "is_game_question",
    "is_giving_up",
]

_OPEN = "¿"
#: Donde acaba la frase anterior, para las preguntas sin «¿» (la transcripción las trae con él
#: casi siempre, pero un cierre sin apertura no debe romper nada).
_ENDERS = ".!…:;\n"
_QUESTION_MARK = re.compile(r"\?")

#: Menos de dos palabras no es una pregunta del juego: «¿verdad?», «¿listo?», «¿sí?».
MIN_WORDS = 2

#: Frases hechas que no son una pregunta del juego (ya normalizadas): comprobar que Sonia se
#: oye, pedir que repitan o preguntar si está listo. Se miran por el principio de la pregunta.
_NOT_GAME = (
    "listo",
    "lista",
    "listos",
    "preparado",
    "preparada",
    "verdad",
    "cierto",
    "no es asi",
    "no crees",
    "de acuerdo",
    "perdon",
    "como dices",
    "como dijiste",
    "que dices",
    "que dijiste",
    "me oyes",
    "me escuchas",
    "me entiendes",
    "me explico",
    "estas ahi",
    "estas listo",
    "estas lista",
    "ya lo tienes",
    "ya tienes algo",
    "ya pensaste",
    "ya lo pensaste",
    "puedes repetir",
    "puedes decirlo",
    "quieres otra",
    "jugamos otra",
    "otra partida",
)


#: Cómo empieza la pregunta con la que Sonia se rinde y quiere saber qué era (normalizada).
_GIVING_UP = (
    "que era",
    "cual era",
    "que pensabas",
    "que pensaste",
    "que habias pensado",
    "que tenias en mente",
    "en que pensabas",
    "en que pensaste",
    "en que estabas pensando",
)


def extract_questions(text: str) -> list[str]:
    """Las preguntas completas de ``text`` (acaban en «?»), en orden y con los espacios limpios.

    Cada una empieza en su «¿» (el más cercano a su «?»); si no lo trae, justo después del
    final de la frase anterior.
    """
    found: list[str] = []
    start = 0
    for match in _QUESTION_MARK.finditer(text):
        chunk = text[start : match.end()]
        start = match.end()
        opened = chunk.rfind(_OPEN)
        if opened >= 0:
            question = chunk[opened:]
        else:
            cut = max((chunk[:-1].rfind(ch) for ch in _ENDERS), default=-1)
            question = chunk[cut + 1 :]
        question = " ".join(question.split())
        if question.strip(f"{_OPEN}? "):
            found.append(question)
    return found


def open_question(text: str) -> str:
    """La pregunta empezada («¿...») y sin cerrar al final de ``text``, o vacío."""
    opened = text.rfind(_OPEN)
    if opened < 0 or "?" in text[opened:]:
        return ""
    return " ".join(text[opened:].split())


def is_game_question(question: str) -> bool:
    """¿Es una pregunta del juego y no un «¿verdad?», un «¿listo?» o un «¿cómo dices?»?"""
    key = normalize(question)
    if len(key.split()) < MIN_WORDS:
        return False
    return not any(key == p or key.startswith(p + " ") for p in _NOT_GAME) and not is_giving_up(
        question
    )


def is_giving_up(question: str) -> bool:
    """¿Es la pregunta con la que Sonia se rinde («¿Qué era?»)? No cuenta como pregunta del juego."""
    key = normalize(question)
    return any(key == p or key.startswith(p + " ") for p in _GIVING_UP)


@dataclass(frozen=True, slots=True)
class QuestionUpdate:
    """Lo que cambió al leer un trozo de la transcripción de Sonia."""

    #: Preguntas contadas hasta ahora.
    count: int
    #: La pregunta en curso, tal como salió en la transcripción («¿Es de Google?»).
    text: str
    #: ``True`` si subió la cuenta; ``False`` si solo cambió el texto de la pregunta en curso.
    is_new: bool


class QuestionCounter:
    """Cuenta las preguntas de Sonia a partir de su transcripción (ver el módulo)."""

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._anchor = ""
        #: Pregunta empezada y sin cerrar al final del último texto visto...
        self._tail = ""
        #: ...y la de la frase anterior, a la que la actual puede cerrarle el «?».
        self._carry = ""
        self.count = 0
        self.text = ""

    def feed(self, text: str, *, final: bool = False) -> QuestionUpdate | None:
        """Lee el texto acumulado de la frase en curso (``final``: la frase entera, ya cerrada).

        Devuelve qué cambió, o ``None`` si no hay ninguna pregunta nueva.
        """
        if self._carry and text.lstrip().startswith("?"):
            # El «?» de la pregunta de la frase anterior llegó tarde, en esta.
            text = self._carry + text.lstrip()
        try:
            return self._feed(text)
        finally:
            self._tail = open_question(text)
            if final:
                self.end_sentence()

    def end_sentence(self) -> None:
        """La frase en curso se cerró: la siguiente empieza de cero (aunque no se contara nada)."""
        self._anchor = ""
        self._carry = self._tail
        self._tail = ""

    def _feed(self, text: str) -> QuestionUpdate | None:
        fresh: dict[str, str] = {}
        for question in extract_questions(text):
            key = normalize(question)
            if is_game_question(question) and key not in self._seen:
                fresh[key] = question
        if not fresh:
            return None
        self._seen.update(fresh)
        question = list(fresh.values())[-1]
        body = normalize(text)
        # Una frase que sigue creciendo (el texto de ahora empieza por el de la última cuenta)
        # es la misma frase: la pregunta nueva sustituye a la anterior, no suma.
        same_sentence = bool(self._anchor) and body.startswith(self._anchor)
        self._anchor = body
        self.text = question
        if same_sentence:
            return QuestionUpdate(self.count, question, is_new=False)
        self.count += 1
        return QuestionUpdate(self.count, question, is_new=True)
