"""Glosario de nombres propios: pistas para el reconocedor y corrección de lo transcrito.

El reconocimiento de voz destroza los nombres propios ("Alexander Vegazo" sale
como "Alexander Begasov"). Tres defensas, todas alimentadas por el mismo archivo
``assets/knowledge/00-glosario.md`` (una viñeta por nombre, el nombre antes de
los dos puntos):

1. El archivo entra en el prompt como el resto de la base de conocimiento, con
   la instrucción de asumir el nombre parecido en vez de decir que no lo conoce.
2. Los nombres se pasan a faster-whisper como ``hotwords`` (sesgo del decodificador).
3. :func:`correct_transcript` sustituye en la transcripción los trozos que
   suenan como un nombre del glosario, comparando en una forma "fonética"
   simplificada del español (b/v, s/z/c, ll/y, h muda, sin tildes), para que el
   modelo y el subtítulo vean el nombre bien escrito.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["GLOSSARY_FILENAME", "correct_transcript", "load_glossary", "phonetic_key"]

#: Archivo del glosario dentro de la base de conocimiento.
GLOSSARY_FILENAME = "00-glosario.md"

#: Parecido mínimo (0..1) entre la forma fonética de lo transcrito y la del nombre.
MATCH_THRESHOLD = 0.8

_BULLET_RE = re.compile(r"^\s*[-*]\s+(.+?)\s*$")
_WORD_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?", re.UNICODE)


def load_glossary(knowledge_dir: str | Path) -> list[str]:
    """Nombres del glosario, en el orden del archivo. Vacío si no existe."""
    path = Path(knowledge_dir) / GLOSSARY_FILENAME
    if not path.is_file():
        return []
    names: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger.warning("No se pudo leer el glosario %s: %s", path, exc)
        return []
    for raw in lines:
        match = _BULLET_RE.match(raw)
        if not match:
            continue
        entry = match.group(1)
        name = entry.split(":", 1)[0].strip().strip("*_`")
        if name and name not in names:
            names.append(name)
    return names


def phonetic_key(text: str) -> str:
    """Forma comparable de un texto: minúsculas, sin tildes y con confusiones del español unificadas."""
    lowered = unicodedata.normalize("NFD", text.lower())
    lowered = "".join(ch for ch in lowered if unicodedata.category(ch) != "Mn")
    lowered = lowered.replace("ll", "y").replace("qu", "k").replace("ch", "x")
    out: list[str] = []
    for i, ch in enumerate(lowered):
        if ch == "h":
            continue
        if ch == "v":
            ch = "b"
        elif ch in "zç":
            ch = "s"
        elif ch == "c":
            nxt = lowered[i + 1] if i + 1 < len(lowered) else ""
            ch = "s" if nxt in "ei" else "k"
        elif ch == "g":
            nxt = lowered[i + 1] if i + 1 < len(lowered) else ""
            ch = "j" if nxt in "ei" else "g"
        elif ch == "w":
            ch = "u"
        elif not ch.isalpha():
            continue
        if out and out[-1] == ch:
            continue  # letras dobles
        out.append(ch)
    return "".join(out)


def correct_transcript(text: str, names: list[str]) -> tuple[str, list[tuple[str, str]]]:
    """Sustituye en ``text`` los trozos que suenan como un nombre del glosario.

    Devuelve el texto corregido y la lista de sustituciones ``(antes, después)``.
    Se comparan ventanas con el mismo número de palabras que el nombre; una
    coincidencia exacta (ignorando mayúsculas) no cuenta como corrección.
    """
    if not text or not names:
        return text, []
    words = [(m.group(0), m.start(), m.end()) for m in _WORD_RE.finditer(text)]
    if not words:
        return text, []

    # Candidatos: el nombre completo y, si tiene varias palabras, también su
    # último apellido solo ("Vegazo"), que es como suele nombrarse a alguien.
    candidates: list[tuple[str, list[str]]] = []
    for name in names:
        parts = name.split()
        if not parts:
            continue
        candidates.append((name, parts))
        surname = parts[-1]
        if len(parts) > 1 and len(phonetic_key(surname)) >= 5:
            candidates.append((surname, [surname]))
    # Los nombres largos primero: "Alexander Vegazo" antes que "Vegazo" o "Sonia".
    candidates.sort(key=lambda item: -len(phonetic_key(item[0])))

    replacements: list[tuple[int, int, str, str]] = []
    taken: list[tuple[int, int]] = []

    for name, parts in candidates:
        key = phonetic_key(name)
        size = len(parts)
        if len(key) < 4:
            continue
        part_keys = [phonetic_key(part) for part in parts]
        for start in range(0, len(words) - size + 1):
            window = words[start : start + size]
            begin, end = window[0][1], window[-1][2]
            if any(not (end <= a or begin >= b) for a, b in taken):
                continue
            original = text[begin:end]
            candidate_key = phonetic_key(original)
            if not candidate_key:
                continue
            if candidate_key == key:
                # Ya está bien (o solo difiere en mayúsculas o tildes): se
                # normaliza a la grafía del glosario sin contarlo como corrección.
                if original != name:
                    replacements.append((begin, end, original, name))
                taken.append((begin, end))
                continue
            ratio = SequenceMatcher(None, candidate_key, key).ratio()
            if ratio < MATCH_THRESHOLD or abs(len(candidate_key) - len(key)) > max(
                2, len(key) // 3
            ):
                continue
            # Las palabras de los extremos deben parecerse también: evita que
            # una ventana desplazada ("la biblioteca nacional pedro enríquez")
            # pase por el nombre entero.
            if size > 1 and not (
                _similar(phonetic_key(window[0][0]), part_keys[0])
                and _similar(phonetic_key(window[-1][0]), part_keys[-1])
            ):
                continue
            replacements.append((begin, end, original, name))
            taken.append((begin, end))

    if not replacements:
        return text, []
    replacements.sort(key=lambda item: item[0])
    pieces: list[str] = []
    cursor = 0
    changes: list[tuple[str, str]] = []
    for begin, end, original, name in replacements:
        pieces.append(text[cursor:begin])
        pieces.append(name)
        cursor = end
        if phonetic_key(original) != phonetic_key(name):
            changes.append((original, name))
    pieces.append(text[cursor:])
    return "".join(pieces), changes


def _similar(a: str, b: str, threshold: float = 0.6) -> bool:
    if not a or not b:
        return False
    return SequenceMatcher(None, a, b).ratio() >= threshold
