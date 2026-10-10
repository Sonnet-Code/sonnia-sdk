"""El banco de poses de «Simón dice» (``assets/games/poses/poses.md``), editable desde el panel.

Cada pose lleva su id (uno de :data:`~sonia.games.poses.rules.POSE_IDS`: la regla de
detección va en el código), la frase del meme, una instrucción clara y, si se quiere, cómo
la demuestra Sonnia. Desde el backoffice se cambian las frases y las instrucciones y se
activan o desactivan poses; una pose nueva necesita su regla en ``rules.py``.

Formato (también explicado al principio del archivo)::

    ## brazos_arriba
    - orden: Pasaron todos los tests
    - pose: brazos arriba
    - demo:
    - activa: sí

Sonia dice la orden así: «¡Simón dice: pasaron todos los tests, brazos arriba!» (en las
trampas, sin «Simón dice»). Las dos versiones se graban con «Preparar voces».
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sonia.games.banks import BankParse, GameBank, markdown_sections
from sonia.games.poses.rules import POSE_IDS

__all__ = [
    "MAX_MEME_CHARS",
    "MAX_POSE_CHARS",
    "MIN_POSES",
    "NO_DEMO",
    "POSES_BANK",
    "PoseEntry",
    "parse_poses",
]

#: Poses activas mínimas para jugar (y para guardar el banco en la nube).
MIN_POSES = 3

#: Topes de las frases: la orden entera tiene que caber en unos tres segundos, porque la
#: ventana en la que se cuenta se abre cuando termina.
MAX_MEME_CHARS = 60
MAX_POSE_CHARS = 32

#: ``demo`` sin demostración de Sonnia.
NO_DEMO = "ninguna"

_FIELD = re.compile(r"^[-*]?\s*([a-zA-ZáéíóúÁÉÍÓÚ]+)\s*:\s*(.*)$")
_CLIP = re.compile(r"^[A-Za-z0-9_.\-]{1,80}$")
_YES = {"sí", "si", "s", "yes", "true", "1", "activa", "on"}
_NO = {"no", "n", "false", "0", "inactiva", "off"}
_FIELDS = {"orden", "pose", "demo", "activa"}


@dataclass(frozen=True, slots=True)
class PoseEntry:
    """Una pose del banco.

    - ``id``: la regla que la detecta (``brazos_arriba``...).
    - ``meme``: la frase del meme, sin «Simón dice» («Pasaron todos los tests»).
    - ``pose``: la instrucción clara que va detrás («brazos arriba»).
    - ``demo``: cómo la demuestra Sonnia: vacío, la pose por código; el nombre de un clip,
      ese clip; ``ninguna``, sin demostración.
    """

    id: str
    meme: str
    pose: str
    demo: str = ""

    @property
    def label(self) -> str:
        """La instrucción para la pantalla: «Brazos arriba»."""
        return _upper_first(self.pose)

    def order(self, simon: bool) -> str:
        """La orden tal cual la dice Sonia (y como se graba).

        Con ``simon``: «¡Simón dice: pasaron todos los tests, brazos arriba!». Sin él (una
        trampa): «¡Pasaron todos los tests, brazos arriba!».
        """
        if simon:
            return f"¡Simón dice: {_lower_first(self.meme)}, {self.pose}!"
        return f"¡{_upper_first(self.meme)}, {self.pose}!"


def _upper_first(text: str) -> str:
    return text[:1].upper() + text[1:]


def _lower_first(text: str) -> str:
    """Primera letra en minúscula salvo en siglas («PR aprobado» se queda igual)."""
    if len(text) > 1 and text[1].isupper():
        return text
    return text[:1].lower() + text[1:]


def _clean(text: str) -> str:
    """Sin comillas, sin los signos de exclamación del principio y del final, sin espacios de más."""
    text = text.strip().strip("«»\"'“”").strip()
    text = text.lstrip("¡¿").rstrip("!?.,;:").strip()
    return re.sub(r"\s+", " ", text)


def parse_poses(text: str) -> BankParse[PoseEntry]:
    """Lee el banco de poses. Nunca lanza: lo que no entiende va a los avisos.

    Las poses desactivadas (``activa: no``) no son entradas, pero tampoco avisos.
    """
    entries: list[PoseEntry] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for heading, lines in markdown_sections(text):
        pose_id = heading.strip().lower()
        if pose_id not in POSE_IDS:
            warnings.append(
                f"«{heading}» no es una pose que sepa detectar la cámara ({', '.join(POSE_IDS)})"
            )
            continue
        if pose_id in seen:
            warnings.append(f"«{pose_id}» está repetida: vale la primera")
            continue
        fields: dict[str, str] = {}
        for line in lines:
            match = _FIELD.match(line)
            if match is None:
                continue
            name = match.group(1).strip().lower()
            if name in _FIELDS:
                fields.setdefault(name, match.group(2).strip())
        active = fields.get("activa", "sí").strip().lower() or "sí"
        if active in _NO:
            seen.add(pose_id)
            continue
        if active not in _YES:
            warnings.append(f"«{pose_id}»: «activa» tiene que ser sí o no (se da por sí)")
        meme = _clean(fields.get("orden", ""))
        pose = _clean(fields.get("pose", "")).lower()
        if not meme or not pose:
            warnings.append(f"«{pose_id}» necesita «orden:» y «pose:»")
            continue
        if len(meme) > MAX_MEME_CHARS or len(pose) > MAX_POSE_CHARS:
            warnings.append(
                f"«{pose_id}»: la orden (hasta {MAX_MEME_CHARS} caracteres) o la pose (hasta "
                f"{MAX_POSE_CHARS}) son demasiado largas"
            )
            continue
        demo = fields.get("demo", "").strip()
        if demo.lower() == NO_DEMO:
            demo = NO_DEMO
        elif demo and _CLIP.match(demo) is None:
            warnings.append(
                f"«{pose_id}»: «demo» tiene que ser el nombre de un clip; se usa la pose"
            )
            demo = ""
        seen.add(pose_id)
        entries.append(PoseEntry(id=pose_id, meme=meme, pose=pose, demo=demo))
    return BankParse(entries, warnings)


POSES_BANK: GameBank[PoseEntry] = GameBank(
    id="poses_poses",
    title="Poses de «Simón dice»",
    file="poses.md",
    parse=parse_poses,
    min_entries=MIN_POSES,
)
