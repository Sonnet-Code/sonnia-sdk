"""ffmpeg: dónde está, cómo codifica Unity y la mezcla final con la voz.

Unity escribe el vídeo mudo (``video_mudo.mp4``) con los argumentos de
:func:`encoder_args`. Al acabar, :func:`finish` le pone la voz maestra al nivel
original, colocada en ``antes + mediana(heard_t − t)`` del ``registro.json`` (lo que
tardó en sonar cada frase en Unity), comprueba la sincronía de la boca con la voz
(correlación entre ``mouth`` por cuadro y la envolvente de la voz a varios desfases),
la corrige si pasa de dos cuadros, la normaliza a −14 LUFS (``loudnorm`` en dos
pasadas) y la mete en AAC 192k sin recodificar el vídeo, con ``+faststart``.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import statistics
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from sonia.video.audio import Samples, frame_envelope, read_wav, write_wav
from sonia.video.errors import VideoError
from sonia.video.script import Quality

__all__ = [
    "FinishReport",
    "Registro",
    "encoder_args",
    "find_ffmpeg",
    "frame_pattern",
    "heard_delay",
    "finish",
    "loudness_command",
    "measure_sync",
    "mux_command",
    "place_voice",
    "read_registro",
    "transparent_outputs",
    "voice_command",
    "voice_delay",
]

logger = logging.getLogger(__name__)

#: Sonoridad de las redes sociales (Instagram, TikTok, YouTube rondan −14 LUFS).
TARGET_LUFS = -14.0
TRUE_PEAK = -1.5
LOUDNESS_RANGE = 11.0

#: Si el registro no trae lo que tardó en sonar la voz en Unity.
FALLBACK_DELAY_S = 0.1

#: Desfases que se prueban entre la boca y la voz (cuadros a cada lado).
MAX_LAG_FRAMES = 6
#: Por encima de esto se corrige (en cuadros).
CORRECT_ABOVE_FRAMES = 2
#: Por debajo de esta correlación la medida no se cree.
MIN_CORRELATION = 0.3


def find_ffmpeg() -> str:
    """``SONNIA_FFMPEG``, el de ``imageio-ffmpeg``, el del ``PATH`` o el de Homebrew."""
    explicit = os.environ.get("SONNIA_FFMPEG", "").strip()
    if explicit:
        if Path(explicit).is_file():
            return explicit
        raise VideoError(f"SONNIA_FFMPEG apunta a {explicit}, que no existe.")
    try:
        import imageio_ffmpeg

        bundled = str(imageio_ffmpeg.get_ffmpeg_exe())
        if Path(bundled).is_file():
            return bundled
    except Exception:  # noqa: BLE001 - sin el extra «video» o sin su binario: se busca otro
        pass
    for candidate in (
        shutil.which("ffmpeg"),
        "/opt/homebrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
    ):
        if candidate and Path(candidate).is_file():
            return candidate
    raise VideoError(
        "No encuentro ffmpeg. Instálalo (brew install ffmpeg) o pon SONNIA_FFMPEG con su ruta."
    )


def encoder_args(quality: Quality) -> list[str]:
    """Lo que va tras ``-i -`` en el ffmpeg que lanza Unity: H.264 en BT.709 y 4:2:0."""
    return [
        "-vf",
        "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        quality.preset,
        "-crf",
        str(quality.crf),
        "-pix_fmt",
        "yuv420p",
        "-profile:v",
        "high",
        "-colorspace",
        "bt709",
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        "-color_range",
        "tv",
    ]


def frame_pattern(folder: Path) -> Path:
    """Los cuadros de una secuencia: ``sonnia_0000.png``... (lo que lee ``secuencia()`` de los reels)."""
    return folder / "sonnia_%04d.png"


def transparent_outputs(mute: Path, frames: Path, proxy: Path) -> tuple[list[str], str]:
    """Argumentos y ruta final para el ffmpeg de Unity con fondo transparente, en una pasada.

    Tres salidas de los mismos cuadros RGBA (alfa sin premultiplicar): el ``.mov`` ProRes
    4444 con alfa, los PNG del tamaño del cuadro en ``frames`` y la copia a la mitad en
    ``proxy`` (la última salida es el ``path`` del contrato), numerados desde 0000.
    """
    # Sin el ``-vf scale=out_color_matrix...`` del H.264: ProRes toma el RGBA tal cual.
    args = [
        "-map",
        "0:v",
        "-c:v",
        "prores_ks",
        "-profile:v",
        "4444",
        "-pix_fmt",
        "yuva444p10le",
        "-alpha_bits",
        "16",
        "-vendor",
        "apl0",
        str(mute),
        "-map",
        "0:v",
        "-c:v",
        "png",
        "-pix_fmt",
        "rgba",
        "-start_number",
        "0",
        str(frame_pattern(frames)),
        "-map",
        "0:v",
        "-vf",
        "scale=iw/2:ih/2",
        "-c:v",
        "png",
        "-pix_fmt",
        "rgba",
        "-start_number",
        "0",
    ]
    return args, str(frame_pattern(proxy))


# ---------------------------------------------------------------------------
# registro.json
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Registro:
    """Lo que devuelve Unity al acabar un vídeo."""

    fps: float
    frames: int
    skipped: int = 0
    kind: str = ""
    width: int = 0
    height: int = 0
    #: ``utterance_id`` → segundo del vídeo en que sonó su primera muestra.
    heard: dict[int, float] = field(default_factory=dict)
    first_audio: dict[int, float] = field(default_factory=dict)
    #: Apertura de la boca por cuadro (vacío si no vino).
    mouth: list[float] = field(default_factory=list)
    #: Huesos por cuadro: nombre → (x, y, z), x e y en píxeles del cuadro (y hacia abajo) y
    #: z en metros a la cámara (vacío si no vinieron).
    bones: list[dict[str, tuple[float, float, float]]] = field(default_factory=list)


def read_registro(path: Path) -> Registro | None:
    """El ``registro.json`` de Unity (``None`` si no está o no se entiende)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    reg = Registro(
        fps=float(data.get("fps") or 0.0),
        frames=int(data.get("frames") or 0),
        skipped=int(data.get("skipped") or 0),
        kind=str(data.get("kind") or ""),
        width=int(data.get("width") or 0),
        height=int(data.get("height") or 0),
    )
    for item in data.get("utterances") or []:
        if not isinstance(item, dict):
            continue
        try:
            uid = int(item["utterance_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if isinstance(item.get("heard_t"), int | float):
            reg.heard[uid] = float(item["heard_t"])
        if isinstance(item.get("first_audio_t"), int | float):
            reg.first_audio[uid] = float(item["first_audio_t"])
    log = data.get("frames_log") or []
    if isinstance(log, list) and log:
        mouth = [0.0] * len(log)
        bones: list[dict[str, tuple[float, float, float]]] = [{} for _ in log]
        for position, item in enumerate(log):
            if isinstance(item, dict):
                index = int(item.get("i", position))
                if 0 <= index < len(mouth):
                    mouth[index] = float(item.get("mouth") or 0.0)
                    bones[index] = _bones(item.get("bones"))
        reg.mouth = mouth
        if any(bones):
            reg.bones = bones
    return reg


def _bones(raw: Any) -> dict[str, tuple[float, float, float]]:
    out: dict[str, tuple[float, float, float]] = {}
    if not isinstance(raw, dict):
        return out
    for name, value in raw.items():
        if isinstance(value, list | tuple) and len(value) >= 2:
            try:
                x, y = float(value[0]), float(value[1])
                z = float(value[2]) if len(value) > 2 else 0.0
            except (TypeError, ValueError):
                continue
            out[str(name)] = (x, y, z)
    return out


def voice_delay(reg: Registro | None, audio_t: Mapping[int, float]) -> float | None:
    """Mediana de lo que tardó cada frase en sonar en Unity (``heard_t − t``)."""
    if reg is None:
        return None
    delays = []
    for uid, heard in reg.heard.items():
        t = audio_t.get(uid, reg.first_audio.get(uid))
        if t is not None:
            delays.append(heard - t)
    return float(statistics.median(delays)) if delays else None


# ---------------------------------------------------------------------------
# Voz colocada y sincronía
# ---------------------------------------------------------------------------

#: Ventana de la envolvente con la que se compara ``heard.wav`` con la voz maestra.
HEARD_HOP_S = 0.005
#: Retrasos que se prueban (segundos) y correlación mínima para creérselo.
HEARD_MAX_DELAY_S = 0.5
HEARD_MIN_CORRELATION = 0.6


def heard_delay(path: Path, master: Samples, rate: int, *, lead_s: float) -> float | None:
    """Cuánto más tarde que ``lead_s`` sonó la voz en Unity, según ``heard.wav``.

    Se compara la envolvente de lo que sonó con la de la voz maestra puesta en ``lead_s``
    (cada 5 ms, de −0,5 a +0,5 s). ``None`` si no hay ``heard.wav`` o no casa.
    """
    if not path.is_file():
        return None
    try:
        heard, heard_rate = read_wav(path)
    except VideoError:
        return None
    hop_heard = max(1, round(heard_rate * HEARD_HOP_S))
    hop_master = max(1, round(rate * HEARD_HOP_S))

    def envelope(samples: Samples, hop: int) -> npt.NDArray[np.float64]:
        count = len(samples) // hop
        blocks = samples[: count * hop].astype(np.float64).reshape(count, hop)
        return np.sqrt(np.mean(blocks * blocks, axis=1))

    a = envelope(heard, hop_heard)
    offset = round(lead_s / HEARD_HOP_S)
    b = np.concatenate([np.zeros(max(0, offset)), envelope(master, hop_master)])
    count = min(len(a), len(b))
    if count < 20 or not a[:count].any() or not b[:count].any():
        return None
    a, b = a[:count], b[:count]
    max_lag = round(HEARD_MAX_DELAY_S / HEARD_HOP_S)
    best_lag, best = 0, -2.0
    for lag in range(-max_lag, max_lag + 1):
        # heard[i] frente a maestra[i - lag]
        x, y = (a[lag:], b[: count - lag]) if lag >= 0 else (a[: count + lag], b[-lag:])
        if len(x) < 20 or float(np.std(x)) == 0.0 or float(np.std(y)) == 0.0:
            continue
        corr = float(np.corrcoef(x, y)[0, 1])
        if corr > best:
            best_lag, best = lag, corr
    if best < HEARD_MIN_CORRELATION:
        return None
    return best_lag * HEARD_HOP_S


def place_voice(master: Samples, rate: int, *, at_s: float, duration_s: float) -> Samples:
    """La voz maestra empezando en ``at_s`` dentro de un audio de ``duration_s``."""
    total = max(0, round(duration_s * rate))
    out = np.zeros(total, dtype=np.float32)
    start = round(at_s * rate)
    source = master
    if start < 0:
        source = master[-start:]
        start = 0
    end = min(total, start + len(source))
    if end > start:
        out[start:end] = source[: end - start]
    return out


def measure_sync(
    mouth: npt.ArrayLike, voice: npt.ArrayLike, max_lag: int = MAX_LAG_FRAMES
) -> tuple[int, float]:
    """``(desfase, correlación)``: cuántos cuadros va la boca por detrás de la voz (negativo:
    por delante) y lo bien que casan a ese desfase (correlación de Pearson)."""
    a = np.asarray(mouth, dtype=np.float64)
    b = np.asarray(voice, dtype=np.float64)
    count = min(len(a), len(b))
    a, b = a[:count], b[:count]
    best_lag, best = 0, -2.0
    for lag in range(-max_lag, max_lag + 1):
        # boca[i] frente a voz[i - lag]
        if lag >= 0:
            x, y = a[lag:], b[: count - lag]
        else:
            x, y = a[: count + lag], b[-lag:]
        if len(x) < 3 or float(np.std(x)) == 0.0 or float(np.std(y)) == 0.0:
            continue
        corr = float(np.corrcoef(x, y)[0, 1])
        if corr > best:
            best_lag, best = lag, corr
    return best_lag, (best if best > -2.0 else 0.0)


# ---------------------------------------------------------------------------
# Sonoridad y mezcla
# ---------------------------------------------------------------------------


def _loudnorm(measured: Mapping[str, Any] | None) -> str:
    base = f"loudnorm=I={TARGET_LUFS:g}:TP={TRUE_PEAK:g}:LRA={LOUDNESS_RANGE:g}"
    if not measured:
        return base
    return (
        f"{base}:measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
        f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
        f":offset={measured['target_offset']}:linear=true:print_format=none"
    )


def loudness_command(ffmpeg: str, wav: Path) -> list[str]:
    """Primera pasada de ``loudnorm``: mide la sonoridad de la voz."""
    return [
        ffmpeg,
        "-hide_banner",
        "-nostats",
        "-i",
        str(wav),
        "-af",
        _loudnorm(None) + ":print_format=json",
        "-f",
        "null",
        "-",
    ]


def mux_command(
    ffmpeg: str,
    video: Path,
    wav: Path,
    out: Path,
    *,
    duration_s: float,
    measured: Mapping[str, Any] | None,
) -> list[str]:
    """El vídeo mudo (copiado tal cual: H.264 o ProRes con alfa) con la voz a −14 LUFS en AAC."""
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video),
        "-i",
        str(wav),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-af",
        _loudnorm(measured),
        "-ar",
        "48000",
        "-ac",
        "2",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-t",
        f"{duration_s:.3f}",
        "-movflags",
        "+faststart",
        str(out),
    ]


_MEASURED_KEYS = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")


def measure_loudness(ffmpeg: str, wav: Path) -> dict[str, Any] | None:
    """Lo que mide la primera pasada de ``loudnorm`` (``None`` si no se pudo medir)."""
    try:
        result = subprocess.run(
            loudness_command(ffmpeg, wav), capture_output=True, check=False, timeout=300
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = result.stderr.decode("utf-8", errors="replace")
    first, last = text.rfind("{"), text.rfind("}")
    if result.returncode != 0 or first == -1 or last < first:
        return None
    try:
        data = json.loads(text[first : last + 1])
    except ValueError:
        return None
    if not isinstance(data, dict) or not all(k in data for k in _MEASURED_KEYS):
        return None
    try:
        values = [float(str(data[k])) for k in _MEASURED_KEYS]
    except ValueError:
        return None
    if not all(np.isfinite(values)):
        return None
    return {k: data[k] for k in _MEASURED_KEYS}


def voice_command(
    ffmpeg: str, wav: Path, out: Path, *, measured: Mapping[str, Any] | None
) -> list[str]:
    """La voz colocada sola, normalizada como en el vídeo, en WAV mono de 48 kHz (para un reel)."""
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(wav),
        "-af",
        _loudnorm(measured),
        "-ar",
        "48000",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        str(out),
    ]


def run(command: list[str], what: str) -> None:
    try:
        result = subprocess.run(command, capture_output=True, check=False, timeout=1800)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VideoError(f"ffmpeg falló {what}: {exc}") from None
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()[-600:]
        raise VideoError(f"ffmpeg falló {what}:\n{detail}")


@dataclass(slots=True)
class FinishReport:
    """Cómo quedó la voz en el vídeo."""

    #: Segundo del vídeo en que empieza la voz maestra.
    voice_at: float
    #: Lo que tardaba la voz en sonar en Unity, o ``None`` si no se supo.
    delay_s: float | None
    #: De dónde sale ``delay_s``: ``heard.wav`` (lo que sonó), ``heard_t`` (el registro) o ``fijo``.
    delay_source: str = ""
    #: Desfase medido entre la boca y la voz (cuadros; positivo: la boca va detrás).
    lag_frames: int | None = None
    correlation: float | None = None
    #: Lo que se movió la voz para corregir ese desfase (segundos).
    corrected_s: float = 0.0
    loudness_in: float | None = None
    #: Cuadros del vídeo.
    frames: int = 0
    notes: list[str] = field(default_factory=list)


def finish(
    *,
    ffmpeg: str,
    video: Path,
    registro: Path,
    master: Samples,
    rate: int,
    lead_s: float,
    audio_t: Mapping[int, float],
    fps: int,
    duration_s: float,
    out: Path,
    work: Path,
    voice_out: Path | None = None,
) -> FinishReport:
    """Mezcla el vídeo mudo con la voz colocada y normalizada (ver el docstring del módulo).

    Con ``voice_out`` deja además la voz sola, colocada desde el cuadro 0 y normalizada igual,
    en WAV de 48 kHz.
    """
    if not video.is_file():
        raise VideoError(f"Unity no dejó el vídeo mudo en {video}")
    reg = read_registro(registro)
    frames = reg.frames if reg is not None and reg.frames > 0 else round(duration_s * fps)
    length = frames / fps
    notes: list[str] = []
    if reg is not None and reg.skipped:
        notes.append(f"Unity saltó {reg.skipped} cuadros")
    # Lo que sonó de verdad en Unity (heard.wav) manda; si no está o no casa, heard_t.
    delay = heard_delay(registro.parent / "heard.wav", master, rate, lead_s=lead_s)
    source = "heard.wav"
    if delay is None:
        delay = voice_delay(reg, audio_t)
        source = "heard_t"
    if delay is None:
        source = "fijo"
        notes.append(
            f"El registro de Unity no dice cuándo sonó la voz: la pongo {FALLBACK_DELAY_S:g} s tarde"
        )
    at = lead_s + (FALLBACK_DELAY_S if delay is None else delay)
    placed = place_voice(master, rate, at_s=at, duration_s=length)
    report = FinishReport(voice_at=at, delay_s=delay, delay_source=source)
    if reg is not None and reg.mouth:
        envelope = frame_envelope(placed, rate, fps, len(reg.mouth))
        lag, corr = measure_sync(reg.mouth, envelope)
        report.lag_frames, report.correlation = lag, corr
        if corr < MIN_CORRELATION:
            notes.append(f"Sincronía boca-voz no concluyente (correlación {corr:.2f})")
        elif abs(lag) > CORRECT_ABOVE_FRAMES:
            report.corrected_s = lag / fps
            at += report.corrected_s
            report.voice_at = at
            placed = place_voice(master, rate, at_s=at, duration_s=length)
            notes.append(
                f"La boca iba {lag:+d} cuadros respecto a la voz: muevo la voz "
                f"{report.corrected_s * 1000:+.0f} ms"
            )
    wav = write_wav(work / "voz_final.wav", placed, rate)
    measured = measure_loudness(ffmpeg, wav)
    if measured is None:
        notes.append("No se pudo medir la sonoridad: loudnorm en una pasada")
    else:
        report.loudness_in = float(str(measured["input_i"]))
    out.parent.mkdir(parents=True, exist_ok=True)
    run(
        mux_command(ffmpeg, video, wav, out, duration_s=length, measured=measured),
        "al poner la voz",
    )
    if voice_out is not None:
        voice_out.parent.mkdir(parents=True, exist_ok=True)
        run(voice_command(ffmpeg, wav, voice_out, measured=measured), "al guardar la voz")
    report.frames = frames
    report.notes = notes
    return report
