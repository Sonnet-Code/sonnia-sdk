"""El paquete ``sonnia/`` para los reels de ``media/`` (repo de Sonnet Code).

Con ``fondo = "transparente"``, además del ``.mov`` con alfa, el render deja lo que
consume ``secuencia()`` (``media/framework/render/secuencia.js``) y la línea de tiempo
fija de un reel (``media/README.md``, «Línea de tiempo fija» y «Secuencias de
imágenes»), con el mismo formato que ``reels/devfest-sd-sede/assets/sonnia/``:

- ``frames/sonnia_0000.png``...: RGBA del tamaño del cuadro, desde 0000 (los escribe el
  ffmpeg de Unity en la misma pasada que el ``.mov``), y ``proxy/`` a la mitad.
- ``prueba.png``: el primer cuadro (el ``fallback`` de la secuencia).
- ``voz.wav``: la voz final colocada desde el segundo 0 del vídeo, mono a 48 kHz.
- ``palabras.json``: ``[{"texto", "inicio", "fin"}]``, el texto en pantalla («Sonnia»).
- ``voz.json``: de dónde sale la voz y dónde suena cada frase.
- ``localizador.json``: dónde caen la cara, las manos... en cada cuadro (de los huesos
  que manda Unity en ``registro.json``), para que las escenas sigan a Sonnia.

Con ``reel`` (``--reel``) el paquete va directo a ``<reel>/assets/sonnia/``; si ya hay
cuadros ahí, solo se reemplazan con ``--forzar``.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sonia.video.errors import VideoError
from sonia.video.ffmpeg import Registro
from sonia.video.srt import SrtWord

__all__ = [
    "HAND_BONES",
    "Package",
    "locator",
    "package_for",
    "snippet",
    "voice_info",
    "words_json",
]

#: Los archivos sueltos del paquete (los cuadros van en ``frames/`` y ``proxy/``).
FILES = ("prueba.png", "voz.wav", "palabras.json", "voz.json", "localizador.json")

#: Puntos con distancia a la cámara en el localizador (las manos, para los golpes y toques).
HAND_BONES = frozenset(
    {"mano_der", "mano_izq", "indice_der", "indice_izq", "nudillos_der", "nudillos_izq"}
)

LOCATOR_NOTES = (
    "En píxeles del cuadro (x a la derecha, y hacia abajo); z: metros a la cámara (solo en las "
    "manos). cara: punto medio entre los ojos. _der y _izq son los lados de Sonnia: su mano "
    "derecha (mano_der) sale a la izquierda de la pantalla."
)


@dataclass(frozen=True, slots=True)
class Package:
    """La carpeta ``sonnia/`` de un render con fondo transparente."""

    root: Path
    #: Va dentro de un reel (``<reel>/assets/sonnia``).
    in_reel: bool = False

    @property
    def frames(self) -> Path:
        return self.root / "frames"

    @property
    def proxy(self) -> Path:
        return self.root / "proxy"

    def frame_files(self) -> list[Path]:
        return sorted(self.frames.glob("sonnia_*.png")) if self.frames.is_dir() else []

    def prepare(self, *, force: bool) -> None:
        """Deja la carpeta lista para un render nuevo.

        Si ya tiene cuadros, solo con ``force``: entonces se borran los cuadros, las copias
        y los archivos del paquete (nada más de la carpeta).
        """
        existing = self.frame_files()
        if existing and not force:
            raise VideoError(
                f"Ya hay {len(existing)} cuadros de Sonnia en {self.frames}. "
                "Para reemplazarlos, repite con --forzar."
            )
        for folder in (self.frames, self.proxy):
            if folder.is_dir():
                shutil.rmtree(folder)
        for name in FILES:
            (self.root / name).unlink(missing_ok=True)
        self.frames.mkdir(parents=True, exist_ok=True)
        self.proxy.mkdir(parents=True, exist_ok=True)

    def write_proof(self) -> Path | None:
        """``prueba.png``: el primer cuadro."""
        files = self.frame_files()
        if not files:
            return None
        target = self.root / "prueba.png"
        shutil.copyfile(files[0], target)
        return target

    def write_json(self, name: str, data: Any) -> Path:
        path = self.root / name
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        return path


def package_for(*, reel: str, out_dir: Path, title: str) -> Package:
    """Dónde va el paquete: ``<reel>/assets/sonnia`` o ``<salida>/<titulo>/sonnia``."""
    if reel.strip():
        folder = Path(reel).expanduser()
        if not folder.is_dir():
            raise VideoError(f"No existe la carpeta del reel: {folder}")
        if not (folder / "reel.config.js").is_file():
            raise VideoError(f"{folder} no parece un reel de media/ (no tiene reel.config.js).")
        return Package(folder / "assets" / "sonnia", in_reel=True)
    return Package(out_dir / title / "sonnia")


def words_json(words: Sequence[SrtWord]) -> list[dict[str, Any]]:
    """``palabras.json``: lo que se ve con su tiempo en el vídeo."""
    return [
        {"texto": w.text, "inicio": round(w.start, 3), "fin": round(max(w.end, w.start), 3)}
        for w in words
        if w.text.strip()
    ]


def voice_info(
    *,
    duration_s: float,
    phrases: Sequence[tuple[str, float, float]],
    engine: str,
    voice: str,
    model: str,
    style: str = "",
    settings: dict[str, Any] | None = None,
    voice_at: float,
) -> dict[str, Any]:
    """``voz.json``: de dónde sale la voz, cómo se colocó y dónde suena cada frase."""
    origin = {
        "gemini": f"Gemini ({voice}, {model}, 24 kHz), una toma del guion entero",
        "elevenlabs": f"ElevenLabs ({voice}, {model}, 24 kHz), una toma del guion entero",
        "archivo": f"{voice} (audio grabado)",
    }.get(engine, engine)
    data: dict[str, Any] = {
        "archivo": "voz.wav",
        "duracion": round(duration_s, 3),
        "frecuencia": 48000,
        "origen": origin,
        "proceso": (
            "cortada en frases por el medio de los silencios, colocada donde sonó en Unity "
            f"(empieza en {voice_at:.3f} s) y normalizada a −14 LUFS; generada con sonnia-video"
        ),
        "frases": [
            {"texto": text, "voz": [round(start, 3), round(end, 3)]} for text, start, end in phrases
        ],
    }
    if engine == "gemini":
        data["voz_gemini"] = {"modelo": model, "voz": voice, "estilo": style}
    elif engine == "elevenlabs":
        data["voz_elevenlabs"] = {"modelo": model, "voz": voice, "ajustes": settings or {}}
    return data


def _point(name: str, value: tuple[float, float, float]) -> dict[str, float]:
    point = {"x": round(value[0], 1), "y": round(value[1], 1)}
    if name in HAND_BONES:
        point["z"] = round(value[2], 4)
    return point


def locator(reg: Registro, *, fps: int, width: int, height: int) -> dict[str, Any]:
    """``localizador.json`` desde los huesos de cada cuadro del ``registro.json`` de Unity."""
    frames: list[dict[str, Any]] = []
    for index, bones in enumerate(reg.bones):
        entry: dict[str, Any] = {"cuadro": index}
        for name in sorted(bones):
            entry[name] = _point(name, bones[name])
        frames.append(entry)
    return {
        "fps": fps,
        "ancho": reg.width or width,
        "alto": reg.height or height,
        "notas": LOCATOR_NOTES,
        "cuadros": frames,
    }


def snippet(*, duration_s: float, count: int, in_reel: bool) -> str:
    """Lo que hay que pegar en el reel: la línea de tiempo fija y la secuencia."""
    where = "" if in_reel else "(copia la carpeta sonnia/ en assets/ del reel)\n"
    return (
        f"{where}"
        "// reel.config.js\n"
        f"timeline: {{ duration: {duration_s:.3f}, words: 'assets/sonnia/palabras.json', "
        "voice: 'assets/sonnia/voz.wav' },\n"
        "\n"
        "// en la escena (scenes/<id>.js)\n"
        "import { secuencia } from '../../../framework/render/secuencia.js';\n"
        "const sonnia = secuencia(C, root, {\n"
        "  dir: 'sonnia/frames/', name: (i) => `sonnia_${String(i).padStart(4, '0')}.png`, "
        f"count: {count},\n"
        "  proxy: { dir: 'sonnia/proxy/', name: (i) => `sonnia_${String(i).padStart(4, '0')}.png` },\n"
        "  fallback: 'sonnia/prueba.png',\n"
        "});\n"
        "// en update(t): sonnia.update(t)\n"
    )
