"""Animación de stand: qué hace Sonia sola cuando no hay conversación.

En un stand nadie se acerca a un avatar que está callado y quieto. Cuando
lleva un rato en ``idle``, el orquestador lanza cada cierto tiempo un "número":
una frase corta (saludo, curiosidad, promoción de Sonnet Code) acompañada a
veces de un gesto de cuarta pared, un baile con una frase "cantada" encima o
un **momento**: una invitación que GPT-Live improvisa con lo que pasa ahora
(la charla que toca, lo que ve la cámara o algo que se puede probar), que el
motor prepara al sacarlo (``LiveEngine._request_moment``).

Las frases viven en ``assets/showcase/frases.md`` y los cantos en
``assets/showcase/cantos.md`` (una por línea; ``#`` comenta). Son textos
fijos: si la frase está en la caché de voces (``cache/voice``) suena tal cual
sin gastar; si no, el motor se la pide a GPT-Live para que la diga con su voz.

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
    """Un número del stand: qué decir y qué gesto acompaña (o ninguno).

    Un momento (``moment``) no trae texto: lo improvisa GPT-Live con lo que pasa ahora.
    """

    text: str
    attention: str | None = None
    moment: bool = False

    @property
    def is_dance(self) -> bool:
        return self.attention == ATTENTION_DANCE


@dataclass
class Showcase:
    """Elige el siguiente número sin repetir el anterior.

    ``dance_chance`` es la probabilidad de que el número sea un baile cantado;
    del resto, ``moment_chance`` son momentos y lo demás frases fijas. Frases y
    momentos llevan un gesto de cuarta pared con ``gesture_chance``.
    """

    phrases: list[str]
    songs: list[str]
    dance_chance: float = 0.3
    gesture_chance: float = 0.5
    moment_chance: float = 0.0
    rng: random.Random = field(default_factory=random.Random)
    _last_text: str | None = field(default=None, init=False)

    @classmethod
    def from_dir(
        cls,
        directory: Path,
        *,
        dance_chance: float = 0.3,
        gesture_chance: float = 0.5,
        moment_chance: float = 0.0,
    ) -> Showcase:
        phrases = load_lines(directory / "frases.md")
        songs = load_lines(directory / "cantos.md")
        logger.info("Animación de stand: %d frases y %d cantos", len(phrases), len(songs))
        return cls(
            phrases,
            songs,
            dance_chance=dance_chance,
            gesture_chance=gesture_chance,
            moment_chance=moment_chance,
        )

    @property
    def enabled(self) -> bool:
        return bool(self.phrases or self.songs or self.moment_chance > 0)

    def next_bit(self) -> ShowcaseBit | None:
        """Devuelve el siguiente número, o ``None`` si no hay material."""
        if not self.enabled:
            return None
        talk = bool(self.phrases) or self.moment_chance > 0
        want_dance = self.songs and (not talk or self.rng.random() < self.dance_chance)
        if want_dance:
            text = self._pick(self.songs)
            return ShowcaseBit(text, ATTENTION_DANCE)
        gesture = ATTENTION_FOURTH_WALL if self.rng.random() < self.gesture_chance else None
        if self.moment_chance > 0 and (not self.phrases or self.rng.random() < self.moment_chance):
            return ShowcaseBit("", gesture, moment=True)
        return ShowcaseBit(self._pick(self.phrases), gesture)

    def _pick(self, pool: list[str]) -> str:
        candidates = [line for line in pool if line != self._last_text] or pool
        text = self.rng.choice(candidates)
        self._last_text = text
        return text
