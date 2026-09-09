"""Animación de stand: qué hace Sonia sola cuando no hay conversación.

En un stand nadie se acerca a un avatar que está callado y quieto. Cuando
lleva un rato en ``idle``, el orquestador lanza cada cierto tiempo un "número":
una frase corta (saludo, curiosidad, promoción de Sonnet Code) acompañada a
veces de un gesto de cuarta pared, o un baile con una frase "cantada" encima.

Las frases viven en ``assets/showcase/frases.md`` y los cantos en
``assets/showcase/cantos.md`` (una por línea; ``#`` comenta). No se usa el
modelo de lenguaje: los tokens de la cuenta provisional son escasos y para
esto no hacen falta.

El avatar recibe las frases como cualquier otra (``speech_start`` con
``ambient: true``) pero **sin cambiar de estado**: el coreógrafo sigue en idle
o bailando y solo se mueven la boca, las cejas y los ojos.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["Showcase", "ShowcaseBit", "load_lines"]

#: Categorías de gesto de atención que entiende Unity (``AttentionCategory``).
ATTENTION_DANCE = "dance"
ATTENTION_FOURTH_WALL = "fourth_wall"
ATTENTION_SOFT = "soft"


def load_lines(path: Path) -> list[str]:
    """Lee un archivo de frases: una por línea, sin comentarios ni vacías."""
    if not path.is_file():
        return []
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


@dataclass(frozen=True)
class ShowcaseBit:
    """Un número del stand: qué decir y qué gesto acompaña (o ninguno)."""

    text: str
    attention: str | None = None

    @property
    def is_dance(self) -> bool:
        return self.attention == ATTENTION_DANCE


@dataclass
class Showcase:
    """Elige el siguiente número sin repetir el anterior.

    ``dance_chance`` es la probabilidad de que el número sea un baile cantado;
    el resto son frases, la mitad de ellas con un gesto de cuarta pared.
    """

    phrases: list[str]
    songs: list[str]
    dance_chance: float = 0.3
    gesture_chance: float = 0.5
    rng: random.Random = field(default_factory=random.Random)
    _last_text: str | None = field(default=None, init=False)

    @classmethod
    def from_dir(
        cls, directory: Path, *, dance_chance: float = 0.3, gesture_chance: float = 0.5
    ) -> Showcase:
        phrases = load_lines(directory / "frases.md")
        songs = load_lines(directory / "cantos.md")
        logger.info("Animación de stand: %d frases y %d cantos", len(phrases), len(songs))
        return cls(phrases, songs, dance_chance=dance_chance, gesture_chance=gesture_chance)

    @property
    def enabled(self) -> bool:
        return bool(self.phrases or self.songs)

    def next_bit(self) -> ShowcaseBit | None:
        """Devuelve el siguiente número, o ``None`` si no hay material."""
        if not self.enabled:
            return None
        want_dance = self.songs and (not self.phrases or self.rng.random() < self.dance_chance)
        if want_dance:
            text = self._pick(self.songs)
            return ShowcaseBit(text, ATTENTION_DANCE)
        text = self._pick(self.phrases)
        gesture = ATTENTION_FOURTH_WALL if self.rng.random() < self.gesture_chance else None
        return ShowcaseBit(text, gesture)

    def _pick(self, pool: list[str]) -> str:
        candidates = [line for line in pool if line != self._last_text] or pool
        text = self.rng.choice(candidates)
        self._last_text = text
        return text
