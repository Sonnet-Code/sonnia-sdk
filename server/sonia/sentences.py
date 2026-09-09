"""Troceado del texto del modelo en frases hablables.

El orquestador va empujando los deltas del LLM con `feed()` y sintetiza cada
frase en cuanto se cierra, sin esperar al final del turno: es lo que mantiene la
latencia por debajo de los dos segundos. Al terminar el turno, `flush()` devuelve
lo que quede en el buffer.

Aquí también se limpia el texto (markdown, emojis, protocolos de URL) porque es
el último punto por el que pasa antes de convertirse en voz.
"""

from __future__ import annotations

import re

__all__ = ["SentenceSplitter", "clean_text"]

#: Puntuación que cierra una frase si va seguida de espacio o de fin de texto.
_TERMINATORS = ".!?;:"

#: Caracteres de cierre que pueden ir después del signo de puntuación final.
_CLOSERS = "\"'”’)]}»…"

#: Abreviaturas frecuentes en español tras las que un punto NO cierra frase.
#: Las de una sola letra (iniciales, "p. ej.") se tratan aparte.
# fmt: off
_ABBREVIATIONS = frozenset({
    "sr", "sra", "srta", "sres", "sras",
    "dr", "dra", "dres", "dn", "dña", "doña",
    "lic", "ing", "arq", "prof", "profa", "gral", "cap", "tte",
    "ud", "uds", "vd", "vds",
    "etc", "aprox", "aprx", "aptdo", "apdo",
    "av", "avda", "avd", "c", "cl", "ctra", "pza", "plza",
    "depto", "dpto", "dcha", "izq", "izqda",
    "núm", "num", "nro", "art", "arts", "pág", "pag", "págs", "pags",
    "ej", "máx", "max", "mín", "min",
    "tel", "teléf", "telf", "ext", "fax",
    "sto", "sta", "san", "ss", "vs",
    "ee", "uu", "aa", "cía", "cia", "cta", "ref", "fig", "vol", "ed", "edit",
    "pról", "trad", "cf", "op", "pp",
})
# fmt: on

# --- Limpieza -------------------------------------------------------------

#: Enlaces markdown: se queda con el texto visible.
_MD_LINK_RE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
#: Encabezados y citas al principio de línea.
_MD_HEADING_RE = re.compile(r"^[ \t]*(?:#{1,6}|>)+[ \t]*", re.MULTILINE)
#: Viñetas y numeración de listas al principio de línea.
_MD_BULLET_RE = re.compile(r"^[ \t]*(?:[-*+•·—–]+|\d+[.)])[ \t]+", re.MULTILINE)
#: Énfasis y código: asteriscos, backticks, tildes de tachado.
_MD_EMPHASIS_RE = re.compile(r"[*`~]+")
#: Guiones bajos solo cuando hacen de énfasis (no dentro de identificadores).
_MD_UNDERSCORE_RE = re.compile(r"(?<!\w)_+|_+(?!\w)")
#: Protocolo de las URLs: se habla el dominio, no el "hache te te pe".
_URL_SCHEME_RE = re.compile(r"\b(?:https?|ftp|ws|wss)://", re.IGNORECASE)
#: Rangos de emoji y símbolos pictográficos (sin tocar la puntuación normal).
_EMOJI_RE = re.compile(
    "["
    "\U0001f000-\U0001faff"
    "\U00002190-\U000021ff"
    "\U00002300-\U000023ff"
    "\U00002600-\U000027bf"
    "\U00002b00-\U00002bff"
    "\U0000fe00-\U0000fe0f"
    "\U0000200d"
    "\U000020e3"
    "]+"
)
_WHITESPACE_RE = re.compile(r"\s+")
#: Espacios que deja la limpieza justo antes de un signo de puntuación.
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+(?=[.,;:!?…])")


def clean_text(text: str) -> str:
    """Deja el texto listo para el TTS: sin markdown, sin emojis y sin protocolos."""
    out = _MD_LINK_RE.sub(r"\1", text)
    out = _MD_HEADING_RE.sub("", out)
    out = _MD_BULLET_RE.sub("", out)
    out = _MD_EMPHASIS_RE.sub("", out)
    out = _MD_UNDERSCORE_RE.sub("", out)
    out = _URL_SCHEME_RE.sub("", out)
    out = _EMOJI_RE.sub(" ", out)
    out = _WHITESPACE_RE.sub(" ", out)
    return _SPACE_BEFORE_PUNCT_RE.sub("", out).strip()


class SentenceSplitter:
    """Acumula deltas de texto y va soltando frases completas.

    Reglas de corte:

    - ``.``, ``!``, ``?``, ``;`` o ``:`` seguidos de espacio o de fin de texto.
    - Salto de línea.
    - ``,`` cuando lo acumulado alcanza ``comma_min_chars`` caracteres.
    - La primera frase del turno usa un umbral de coma más bajo
      (``first_sentence_comma_chars``) para que Sonia empiece a hablar antes.

    No corta en decimales (``3.5``), ni en abreviaturas (``Sr.``, ``p. ej.``,
    ``EE.UU.``), ni en puntos suspensivos a medio llegar.
    """

    def __init__(
        self,
        *,
        comma_min_chars: int = 60,
        first_sentence_comma_chars: int = 40,
        fast_first_sentence: bool = True,
    ) -> None:
        self.comma_min_chars = comma_min_chars
        self.first_sentence_comma_chars = first_sentence_comma_chars
        self.fast_first_sentence = fast_first_sentence
        self._buffer = ""
        self._emitted = 0

    @property
    def pending(self) -> str:
        """Texto acumulado que todavía no forma una frase."""
        return self._buffer

    @property
    def emitted(self) -> int:
        """Frases emitidas desde el último `reset()`."""
        return self._emitted

    def reset(self) -> None:
        """Olvida el buffer y vuelve a considerar la siguiente frase como la primera."""
        self._buffer = ""
        self._emitted = 0

    def feed(self, delta: str) -> list[str]:
        """Añade un trozo de texto y devuelve las frases que hayan quedado cerradas."""
        if not delta:
            return []
        self._buffer += delta
        sentences: list[str] = []
        while True:
            cut = self._find_cut(self._buffer)
            if cut is None:
                break
            raw, self._buffer = self._buffer[:cut], self._buffer[cut:].lstrip()
            sentence = clean_text(raw)
            if sentence:
                sentences.append(sentence)
                self._emitted += 1
        return sentences

    def flush(self) -> str | None:
        """Devuelve lo que quede en el buffer (o ``None`` si no queda nada útil)."""
        raw, self._buffer = self._buffer, ""
        sentence = clean_text(raw)
        if not sentence:
            return None
        self._emitted += 1
        return sentence

    # ------------------------------------------------------------------
    # Interno
    # ------------------------------------------------------------------

    @property
    def _comma_threshold(self) -> int:
        if self.fast_first_sentence and self._emitted == 0:
            return self.first_sentence_comma_chars
        return self.comma_min_chars

    def _find_cut(self, buffer: str) -> int | None:
        """Índice (exclusivo) donde termina la primera frase, o ``None``."""
        length = len(buffer)
        comma_threshold = self._comma_threshold
        for i, char in enumerate(buffer):
            if char == "\n":
                return i
            if char == ",":
                if i + 1 < length and buffer[i + 1].isspace() and i + 1 >= comma_threshold:
                    return self._extend(buffer, i)
                continue
            if char not in _TERMINATORS:
                continue
            if char == "." and not self._dot_closes(buffer, i):
                continue
            end = self._extend(buffer, i)
            # Solo cerramos si sabemos que detrás viene un espacio: el fin de
            # texto se resuelve en flush(), porque el delta siguiente podría
            # continuar la palabra.
            if end < length and buffer[end].isspace():
                return end
        return None

    @staticmethod
    def _extend(buffer: str, index: int) -> int:
        """Incluye los signos de cierre que sigan a la puntuación (comillas, paréntesis)."""
        end = index + 1
        while end < len(buffer) and buffer[end] in _CLOSERS:
            end += 1
        return end

    @staticmethod
    def _dot_closes(buffer: str, index: int) -> bool:
        """¿Este punto cierra frase, o es un decimal, una abreviatura o unos puntos suspensivos?"""
        after = buffer[index + 1] if index + 1 < len(buffer) else ""
        before = buffer[index - 1] if index else ""
        # Decimales y numeraciones tipo "3.5" o "192.168.1.1".
        if before.isdigit() and after.isdigit():
            return False
        # Puntos suspensivos: solo cierra el último punto de la serie.
        if after == ".":
            return False
        # Abreviatura: miramos la palabra que precede al punto.
        start = index
        while start > 0 and (buffer[start - 1].isalpha() or buffer[start - 1] == "."):
            start -= 1
        token = buffer[start:index].rsplit(".", 1)[-1]
        if len(token) == 1 and token.isalpha():
            # Inicial ("J. Calderón") o abreviatura de una letra ("p. ej.").
            return False
        return token.lower() not in _ABBREVIATIONS
