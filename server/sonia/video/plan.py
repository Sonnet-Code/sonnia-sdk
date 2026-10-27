"""De la toma de voz a la línea de tiempo del trabajo de Unity.

1. Cada trozo de texto (``script.Unit``) toma el tiempo de sus palabras dichas.
2. La toma se corta en frases (una por ``[[frase]]``) por el medio del silencio entre
   la última palabra de una y la primera de la siguiente, y se quitan los silencios de
   los extremos. Tras cada frase va su ``pausa``. Todo junto es la «voz maestra».
3. Unity recibe cada frase en un WAV al nivel de GPT-Live (``audio.UNITY_SPEECH_RMS``):
   una sola ganancia para todo el guion, con limitador. El vídeo final lleva la voz
   maestra al nivel original (``ffmpeg.finish``).
4. La línea de tiempo repite lo que manda el orquestador en el stand: ``stage_mode`` sin
   conversación y ``state idle``; ``state speaking`` al empezar; por frase su
   ``gesture``, ``speech_start`` y el audio; los ``transcript`` acumulados palabra a
   palabra (con «Sonnia», lo que se lee) y el final; y ``state idle`` al acabar.

Los tiempos de la línea son segundos desde el cuadro 0. La voz maestra empieza en
``antes`` (``Plan.lead_s``): la frase ``k`` suena desde ``lead_s + audio_start``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from sonia.video.audio import (
    Samples,
    quietest_point,
    to_unity_level,
    unity_gain,
    voiced_runs,
    write_wav,
)
from sonia.video.errors import VideoError
from sonia.video.script import Action, PhraseText
from sonia.video.voice import Take

__all__ = [
    "GestureCue",
    "IDLE_AFTER_S",
    "LEAD_IN_S",
    "TRANSCRIPT_DELAY_S",
    "Plan",
    "PlannedPhrase",
    "PlannedUnit",
    "build_plan",
    "build_timeline",
    "write_unity_wavs",
]

#: Retraso aproximado del reproductor de Unity: el subtítulo de una palabra sale cuando suena.
TRANSCRIPT_DELAY_S = 0.15

#: Silencio que se deja antes de la primera voz de la toma y después de la última.
LEAD_IN_S = 0.05
TAIL_KEEP_S = 0.3

#: ``state idle`` va esto después de que acabe la voz (lo que tarda en sonar lo último).
IDLE_AFTER_S = 0.4

#: Modo del stand en el vídeo: sin conversación (no sale la invitación a hablar).
STAGE_MODE = {"type": "stage_mode", "mode": "greeter", "talk": False}


@dataclass(frozen=True, slots=True)
class GestureCue:
    """Un gesto de una frase y el segundo del vídeo en que se manda."""

    name: str
    at: float


@dataclass(frozen=True, slots=True)
class PlannedUnit:
    """Un trozo de texto en pantalla y cuándo se dice (segundos de la voz maestra)."""

    display: str
    start: float
    end: float
    #: Tiene palabras dichas (los de solo puntuación no).
    spoken: bool = True


@dataclass(slots=True)
class PlannedPhrase:
    uid: int
    display: str
    units: list[PlannedUnit]
    #: Dónde empieza y acaba su audio en la voz maestra (con los silencios de alrededor).
    audio_start: float
    audio_end: float
    #: Su audio al nivel original.
    samples: Samples
    pause: float = 0.0

    @property
    def voice_start(self) -> float:
        spoken = [u.start for u in self.units if u.spoken]
        return min(spoken) if spoken else self.audio_start

    @property
    def voice_end(self) -> float:
        spoken = [u.end for u in self.units if u.spoken]
        return max(spoken) if spoken else self.audio_end


@dataclass(slots=True)
class Plan:
    """La voz cortada en frases y colocada, lista para la línea de tiempo."""

    rate: int
    master: Samples
    phrases: list[PlannedPhrase]
    lead_s: float
    tail_s: float
    gain: float
    notes: list[str] = field(default_factory=list)

    @property
    def master_duration(self) -> float:
        return len(self.master) / self.rate

    @property
    def duration_s(self) -> float:
        return self.lead_s + self.master_duration + self.tail_s

    def phrase_t(self, index: int) -> float:
        """Segundo del vídeo en que empieza el audio de la frase ``index``."""
        return self.lead_s + self.phrases[index].audio_start


def _unit_times(
    texts: Sequence[PhraseText], words: Sequence[tuple[float, float]]
) -> list[list[tuple[float, float, bool]]]:
    """Inicio, fin y si se dice, de cada trozo (segundos de la toma)."""
    expected = sum(len(t.spoken_words) for t in texts)
    if expected != len(words):
        raise VideoError(
            f"La toma trae {len(words)} palabras con tiempo y el guion dice {expected} (interno)."
        )
    out: list[list[tuple[float, float, bool]]] = []
    cursor = 0
    last_end = 0.0
    for text in texts:
        units: list[tuple[float, float, bool]] = []
        for unit in text.units:
            count = len(unit.spoken)
            if count:
                span = words[cursor : cursor + count]
                cursor += count
                start, end = span[0][0], max(span[-1][1], span[0][0])
                units.append((start, end, True))
                last_end = end
            else:
                units.append((last_end, last_end, False))
        out.append(units)
    return out


def build_plan(
    texts: Sequence[PhraseText],
    take: Take,
    *,
    pauses: Sequence[float],
    lead_s: float,
    tail_s: float,
) -> Plan:
    """Corta la toma en frases y monta la voz maestra."""
    if not texts:
        raise VideoError("El guion no tiene frases.")
    rate = take.rate
    samples = take.samples
    total = len(samples)
    duration = total / rate
    units = _unit_times(texts, take.words)
    spans: list[tuple[float, float]] = []
    for phrase_units in units:
        spoken = [(a, b) for a, b, said in phrase_units if said]
        spans.append((min(a for a, _ in spoken), max(b for _, b in spoken)) if spoken else (0, 0))
    runs = voiced_runs(samples, rate)
    onset = min([spans[0][0], *([runs[0][0]] if runs else [])])
    offset = max([spans[-1][1], *([runs[-1][1]] if runs else [])])
    cuts = [max(0.0, onset - LEAD_IN_S)]
    for k in range(1, len(texts)):
        previous_end, start = spans[k - 1][1], spans[k][0]
        low, high = min(previous_end, start), max(previous_end, start)
        if high - low < 0.05:
            low, high = low - 0.1, high + 0.1
        cut = quietest_point(samples, rate, max(cuts[-1], low), min(duration, high))
        cuts.append(min(max(cut, cuts[-1] + 0.05), duration))
    cuts.append(min(duration, max(offset + TAIL_KEEP_S, cuts[-1] + 0.05)))
    indices = [min(total, round(c * rate)) for c in cuts]

    pieces: list[Samples] = []
    planned: list[PlannedPhrase] = []
    cursor = 0
    for k, text in enumerate(texts):
        segment = samples[indices[k] : indices[k + 1]].astype(np.float32)
        pause = float(pauses[k]) if k < len(pauses) else 0.0
        start_s = cursor / rate
        shift = start_s - indices[k] / rate
        end_s = start_s + len(segment) / rate
        planned_units = [
            PlannedUnit(
                display=unit.display,
                start=min(max(a + shift, start_s), end_s),
                end=min(max(b + shift, start_s), end_s),
                spoken=said,
            )
            for unit, (a, b, said) in zip(text.units, units[k], strict=True)
        ]
        planned.append(
            PlannedPhrase(
                uid=k + 1,
                display=text.display,
                units=planned_units,
                audio_start=start_s,
                audio_end=end_s,
                samples=segment,
                pause=pause,
            )
        )
        pieces.append(segment)
        cursor += len(segment)
        if pause > 0:
            silence = np.zeros(round(pause * rate), dtype=np.float32)
            pieces.append(silence)
            cursor += len(silence)
    master = np.concatenate(pieces).astype(np.float32) if pieces else np.zeros(0, np.float32)
    return Plan(
        rate=rate,
        master=master,
        phrases=planned,
        lead_s=lead_s,
        tail_s=tail_s,
        gain=unity_gain(master, rate),
    )


def write_unity_wavs(plan: Plan, folder: Path) -> dict[int, Path]:
    """Un WAV por frase al nivel de GPT-Live (``u001.wav``...). Devuelve su ruta por ``uid``."""
    out: dict[int, Path] = {}
    for phrase in plan.phrases:
        leveled = to_unity_level(phrase.samples, plan.rate, plan.gain)
        out[phrase.uid] = write_wav(folder / f"u{phrase.uid:03d}.wav", leveled, plan.rate)
    return out


def _transcript(text: str, final: bool) -> dict[str, Any]:
    return {"type": "transcript", "role": "assistant", "text": text, "final": final}


def build_timeline(
    plan: Plan,
    wavs: Mapping[int, Path],
    *,
    gestures: Mapping[int, GestureCue] | None = None,
    actions: Sequence[Action] = (),
    fps: int = 30,
) -> list[dict[str, Any]]:
    """La línea de tiempo del trabajo (ordenada por ``t``; a igual ``t``, en orden de llegada)."""
    gestures = gestures or {}
    entries: list[tuple[float, int, dict[str, Any]]] = []

    def add(t: float, entry: dict[str, Any]) -> None:
        entries.append((round(max(0.0, t), 4), len(entries), {"t": round(max(0.0, t), 4), **entry}))

    add(0.0, {"message": dict(STAGE_MODE)})
    add(0.0, {"message": {"type": "state", "state": "idle"}})
    add(plan.phrase_t(0), {"message": {"type": "state", "state": "speaking"}})
    for k, phrase in enumerate(plan.phrases):
        t = plan.phrase_t(k)
        # Lo de esta frase no puede llegar después de que empiece la siguiente.
        limit = plan.phrase_t(k + 1) - 0.001 if k + 1 < len(plan.phrases) else float("inf")
        cue = gestures.get(phrase.uid)
        if cue is not None:
            # A su hora: con la frase, o más tarde si aún duraba el gesto anterior.
            message = {"type": "gesture", "name": cue.name, "utterance_id": phrase.uid}
            add(max(t, cue.at), {"message": message})
        add(t, {"message": {"type": "speech_start", "utterance_id": phrase.uid, "text": ""}})
        add(t, {"audio": {"utterance_id": phrase.uid, "wav": str(wavs[phrase.uid])}})
        shown: list[str] = []
        for unit in phrase.units:
            shown.append(unit.display)
            at = t + (unit.start - phrase.audio_start) + TRANSCRIPT_DELAY_S
            add(min(at, limit), {"message": _transcript(" ".join(shown), False)})
        at = t + (phrase.voice_end - phrase.audio_start) + TRANSCRIPT_DELAY_S
        add(min(at, limit), {"message": _transcript(phrase.display, True)})
    for action in actions:
        add(action.at, {"action": {"name": action.gesture, "mirror": action.mirror}})
    last_frame = plan.duration_s - 1.0 / max(1, fps)
    end = min(plan.lead_s + plan.master_duration + IDLE_AFTER_S, max(0.0, last_frame))
    end = math.floor(end * 10_000) / 10_000  # al redondear no puede pasarse del último cuadro
    add(end, {"message": {"type": "state", "state": "idle"}})
    entries.sort(key=lambda item: (item[0], item[1]))
    return [entry for _, _, entry in entries]
