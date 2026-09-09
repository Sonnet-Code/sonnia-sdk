"""Lip-sync: visemas a partir del texto y envolvente a partir del audio.

No hay alineador fonético (sería otro modelo y más latencia): se usa una
heurística grafema → visema para español y se reparte el resultado a lo largo de
la duración real del audio, contando núcleos vocálicos como sílabas aproximadas.
La envolvente RMS va como respaldo para avatares sin blendshapes de visemas.

Los identificadores son los del conjunto Oculus / Ready Player Me, tal como los
define `docs/protocolo.md`.
"""

from __future__ import annotations

import numpy as np

from sonia.types import VisemeFrame, VisemeId

__all__ = ["envelope_for", "visemes_for"]

#: Vocales (con tildes y diéresis) y el visema de cada una.
# fmt: off
_VOWELS: dict[str, VisemeId] = {
    "a": "aa", "á": "aa", "à": "aa", "ä": "aa", "â": "aa",
    "e": "E", "é": "E", "è": "E", "ë": "E", "ê": "E",
    "i": "ih", "í": "ih", "ì": "ih", "ï": "ih", "î": "ih",
    "o": "oh", "ó": "oh", "ò": "oh", "ö": "oh", "ô": "oh",
    "u": "ou", "ú": "ou", "ù": "ou", "ü": "ou", "û": "ou",
}

#: Consonantes de mapeo directo (los casos con contexto se tratan aparte).
_CONSONANTS: dict[str, VisemeId] = {
    "p": "PP", "b": "PP", "m": "PP",
    "f": "FF", "v": "FF",
    "d": "DD", "t": "DD",
    "k": "kk", "j": "kk",
    "s": "SS", "z": "SS", "x": "SS",
    "n": "nn", "l": "nn",
    "r": "RR",
    "ñ": "CH",
    "w": "ou",
}
# fmt: on

#: Vocales que vuelven suaves a la c y a la g.
_SOFT = frozenset("eiéí")

#: Peso temporal de cada tipo de unidad, en "sílabas" aproximadas. Un núcleo
#: vocálico pesa una sílaba entera; las consonantes, una fracción.
_NUCLEUS_WEIGHT = 1.0
_CONSONANT_WEIGHT = 0.35
_SPACE_WEIGHT = 0.35
_PUNCT_WEIGHT = 0.7

#: Puntuación que se dice callando la boca.
_PAUSE_CHARS = frozenset(".,;:!?¡¿…()[]{}\"'«»—–-\n\t")


def _units(text: str) -> list[tuple[VisemeId, float]]:
    """Convierte el texto en una secuencia de ``(visema, peso)``.

    Maneja los dígrafos del español (ch, ll, rr, qu, gu), la c y la g suaves
    ante e/i, la h muda y la y consonántica.
    """
    lowered = text.lower()
    units: list[tuple[VisemeId, float]] = []
    n = len(lowered)
    i = 0

    def add(viseme: VisemeId, weight: float) -> None:
        if viseme == "sil" and units and units[-1][0] == "sil":
            # Espacios y puntuación seguidos son un único silencio más largo.
            previous, previous_weight = units[-1]
            units[-1] = (previous, previous_weight + weight)
            return
        units.append((viseme, weight))

    while i < n:
        char = lowered[i]
        nxt = lowered[i + 1] if i + 1 < n else ""
        after = lowered[i + 2] if i + 2 < n else ""

        if char.isspace():
            add("sil", _SPACE_WEIGHT)
            i += 1
        elif char in _PAUSE_CHARS:
            add("sil", _PUNCT_WEIGHT)
            i += 1
        elif char in _VOWELS:
            # Grupo vocálico: varios visemas, pero un solo núcleo (una sílaba).
            start = i
            while i < n and lowered[i] in _VOWELS:
                i += 1
            group = lowered[start:i]
            share = _NUCLEUS_WEIGHT / len(group)
            for vowel in group:
                add(_VOWELS[vowel], share)
        elif char == "c":
            if nxt == "h":  # dígrafo ch
                add("CH", _CONSONANT_WEIGHT)
                i += 2
            else:
                add("SS" if nxt in _SOFT else "kk", _CONSONANT_WEIGHT)
                i += 1
        elif char == "l":
            if nxt == "l":  # dígrafo ll
                add("CH", _CONSONANT_WEIGHT)
                i += 2
            else:
                add("nn", _CONSONANT_WEIGHT)
                i += 1
        elif char == "r":
            add("RR", _CONSONANT_WEIGHT)
            i += 2 if nxt == "r" else 1  # rr suena como una sola r fuerte
        elif char == "q":
            add("kk", _CONSONANT_WEIGHT)
            i += 2 if (nxt == "u" and after in _SOFT) else 1  # la u de "que" es muda
        elif char == "g":
            add("kk", _CONSONANT_WEIGHT)
            i += 2 if (nxt == "u" and after in _SOFT) else 1  # la u de "gue" es muda
        elif char == "h":
            i += 1  # h muda: no aporta visema
        elif char == "y":
            # Consonántica salvo cuando es la conjunción o cierra sílaba ("hay").
            add("ih" if not nxt.isalpha() else "CH", _CONSONANT_WEIGHT)
            i += 1
        elif char in _CONSONANTS:
            add(_CONSONANTS[char], _CONSONANT_WEIGHT)
            i += 1
        else:
            # Dígitos y símbolos raros: no sabemos cómo suenan, los ignoramos.
            i += 1

    return units


def visemes_for(text: str, duration: float) -> list[VisemeFrame]:
    """Reparte los visemas de ``text`` a lo largo de ``duration`` segundos.

    Siempre termina con un ``sil`` en ``duration`` para que el avatar cierre la
    boca al acabar la frase.
    """
    total_duration = max(0.0, float(duration))
    units = _units(text)
    total_weight = sum(weight for _, weight in units)

    frames: list[VisemeFrame] = []
    if units and total_weight > 0.0 and total_duration > 0.0:
        elapsed = 0.0
        for viseme, weight in units:
            t = round(total_duration * elapsed / total_weight, 3)
            frames.append(VisemeFrame(t=min(t, total_duration), viseme=viseme))
            elapsed += weight
    else:
        frames.append(VisemeFrame(t=0.0, viseme="sil"))

    end = round(total_duration, 3)
    if frames[-1].viseme == "sil":
        # El último silencio se estira hasta el final en vez de duplicarse.
        frames[-1].t = min(frames[-1].t, end)
        if frames[-1].t < end:
            frames.append(VisemeFrame(t=end, viseme="sil"))
    else:
        frames.append(VisemeFrame(t=end, viseme="sil"))
    return frames


def envelope_for(pcm: bytes, sample_rate: int, interval_ms: int = 20) -> list[float]:
    """Envolvente de amplitud: RMS por ventana, normalizado al máximo de la frase.

    ``pcm`` es PCM s16le mono. Devuelve un valor entre 0 y 1 cada ``interval_ms``
    (0 en silencio total), redondeado a tres decimales.
    """
    if not pcm or sample_rate <= 0 or interval_ms <= 0:
        return []
    window = max(1, int(sample_rate * interval_ms / 1000))
    samples = np.frombuffer(pcm[: len(pcm) - len(pcm) % 2], dtype="<i2").astype(np.float32)
    if samples.size == 0:
        return []
    samples /= 32768.0

    count = int(np.ceil(samples.size / window))
    padded = np.zeros(count * window, dtype=np.float32)
    padded[: samples.size] = samples
    blocks = padded.reshape(count, window)
    rms = np.sqrt(np.mean(np.square(blocks, dtype=np.float64), axis=1))

    peak = float(rms.max())
    if peak <= 0.0:
        return [0.0] * count
    return [round(float(value), 3) for value in rms / peak]
