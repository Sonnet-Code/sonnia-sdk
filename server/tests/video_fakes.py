"""Falsos de Sonnia Video: voz sintética, APIs de voz y el renderizador de Unity.

Nada de red: las APIs van por ``httpx.MockTransport`` y el renderizador es un
manejador que guarda los trabajos y, si se le pide, deja un vídeo mudo hecho con el
ffmpeg del equipo y un ``registro.json`` como los de Unity.
"""

from __future__ import annotations

import base64
import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from sonia.video.audio import SAMPLE_RATE, Samples
from sonia.video.gemini import wav_bytes


def gesture(name: str, **fields: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "name": name,
        "lists": ["Sage(IDset)"],
        "duration": 1.0,
        "core_start": 0.05,
        "core_stop": 0.4,
        "frequency": "Standard",
        "timing": "Short",
        "impact": "LowImpact",
        "intensity": 2,
        "description": f"Gesto {name}.",
        "intents": ["To Convey"],
        "tags": [],
    }
    item.update(fields)
    return item


CATALOG: dict[str, Any] = {
    "type": "gesture_catalog",
    "character": "Sage",
    "gestures": [
        gesture("waveCalm", intents=["To Greet"], description="Waves hello calmly."),
        gesture("thumbsUpCalm"),
        gesture("explainHands", timing="Long", duration=3.0, core_stop=2.5),
        gesture("shrug", frequency="Uncommon"),
        gesture("palmsUp", frequency="Uncommon"),
        gesture("bigCheer", frequency="Rare", impact="HighImpact"),
        gesture("noImpact01", lists=["Utility_NoImpact"], impact="NoImpact"),
    ],
}


def synth_take(
    phrases: list[list[str]],
    *,
    word_s: float = 0.25,
    gap_s: float = 0.08,
    phrase_gap_s: float = 0.5,
    lead_s: float = 0.4,
    tail_s: float = 0.6,
    amplitude: float = 0.3,
) -> tuple[Samples, list[tuple[float, float]]]:
    """Una «voz» de tonos: cada palabra es un tono de ``word_s``. Devuelve el audio y los
    tiempos exactos de cada palabra."""
    rate = SAMPLE_RATE
    pieces: list[Samples] = [np.zeros(round(lead_s * rate), dtype=np.float32)]
    times: list[tuple[float, float]] = []
    cursor = lead_s
    for p, words in enumerate(phrases):
        for w, _ in enumerate(words):
            n = round(word_s * rate)
            t = np.arange(n) / rate
            tone = (amplitude * np.sin(2 * np.pi * (180 + 40 * w) * t)).astype(np.float32)
            pieces.append(tone)
            times.append((cursor, cursor + word_s))
            cursor += word_s
            if w < len(words) - 1:
                pieces.append(np.zeros(round(gap_s * rate), dtype=np.float32))
                cursor += gap_s
        if p < len(phrases) - 1:
            pieces.append(np.zeros(round(phrase_gap_s * rate), dtype=np.float32))
            cursor += phrase_gap_s
    pieces.append(np.zeros(round(tail_s * rate), dtype=np.float32))
    return np.concatenate(pieces).astype(np.float32), times


class Recorder:
    """Graba las peticiones de un ``MockTransport``."""

    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._handler = handler

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._handler(request)

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests if r.content]

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def gemini_handler(
    samples: Samples, words: list[tuple[str, float, float]]
) -> Callable[[httpx.Request], httpx.Response]:
    """Gemini falso: la voz devuelve ``samples`` en WAV y la transcripción, ``words``."""

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["model"].endswith("-tts"):
            data = base64.b64encode(wav_bytes(samples, SAMPLE_RATE)).decode()
            return httpx.Response(
                200,
                json={
                    "steps": [
                        {"type": "user_input", "content": [{"type": "text", "text": "x"}]},
                        {
                            "type": "model_output",
                            "content": [{"type": "audio", "data": data, "mime_type": "audio/wav"}],
                        },
                    ]
                },
            )
        notes = [
            {"type": "word_info", "text": w, "start_offset": f"{a:.3f}s", "end_offset": f"{b:.3f}s"}
            for w, a, b in words
        ]
        text = " ".join(w for w, _, _ in words)
        return httpx.Response(
            200,
            json={
                "steps": [
                    {
                        "type": "model_output",
                        "content": [{"type": "text", "text": text, "annotations": notes}],
                    }
                ]
            },
        )

    return handle


BONES = ("cabeza", "cara", "mano_der", "mano_izq", "nudillos_der")


def unity_frames(width: int, height: int, frames: int) -> bytes:
    """Cuadros RGBA como los de Unity con fondo transparente: un cuadrado opaco que se mueve."""
    out = np.zeros((frames, height, width, 4), dtype=np.uint8)
    side = max(4, min(width, height) // 4)
    for i in range(frames):
        x = (i * 2) % max(1, width - side)
        out[i, height // 3 : height // 3 + side, x : x + side] = (20, 40, 200, 255)
    return out.tobytes()


def unity_encode(ffmpeg: str, job: dict[str, Any], frames: int) -> None:
    """Lo que hace Unity con el ``encoder`` del trabajo: ``ffmpeg … -i - <args> <path>``."""
    encoder = job["encoder"]
    width, height = job["width"], job["height"]
    for arg in [*encoder["args"], encoder["path"]]:
        if arg.startswith("/") and "%" in arg:
            Path(arg).parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgba",
        "-s",
        f"{width}x{height}",
        "-r",
        str(job["fps"]),
        "-i",
        "-",
        *encoder["args"],
        encoder["path"],
    ]
    subprocess.run(
        command, input=unity_frames(width, height, frames), check=True, capture_output=True
    )


def tiny_png(path: Path, *, alpha: bool) -> None:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (8, 14), (10, 20, 200, 0 if alpha else 255)).save(path)


def mute_video(ffmpeg: str, path: Path, *, width: int, height: int, fps: int, frames: int) -> None:
    """Un vídeo mudo de prueba con el ffmpeg del equipo."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size={width}x{height}:rate={fps}",
            "-frames:v",
            str(frames),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


class FakeRenderer:
    """La app de Unity por HTTP: ``/status``, ``/catalog``, ``/job``, ``/cancel`` y ``/quit``.

    Un trabajo pasa a ``rendering`` y, tras ``polls`` consultas de estado, a ``done``. Con
    ``ffmpeg``, al acabar deja el vídeo mudo y un ``registro.json`` con la voz sonando
    ``delay_s`` tarde y la boca siguiendo a la voz ``mouth_lag`` cuadros por detrás.
    """

    def __init__(
        self,
        *,
        avatar: str = "ready",
        ffmpeg: str | None = None,
        polls: int = 2,
        delay_s: float = 0.12,
        fail: str | None = None,
        outfit: str = "staff",
    ) -> None:
        self.avatar = avatar
        self.outfit = outfit
        self.ffmpeg = ffmpeg
        self.polls = polls
        self.delay_s = delay_s
        self.fail = fail
        self.jobs: list[dict[str, Any]] = []
        self.job: dict[str, Any] | None = None
        self.cancelled = False
        self.quit = False
        self.status_calls = 0
        self.alive = True

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if not self.alive:
            raise httpx.ConnectError("cerrada", request=request)
        path = request.url.path
        if path == "/status":
            self.status_calls += 1
            if self.job is not None and self.job["state"] == "rendering":
                self.job["frame"] = min(self.job["frames"], self.job["frame"] + 10)
                self._left -= 1
                if self._left <= 0:
                    self._finish()
            return httpx.Response(
                200,
                json={
                    "app": "sonnia-video",
                    "version": "1.0.1",
                    "avatar": self.avatar,
                    "outfit": self.outfit,
                    "busy": self.job is not None and self.job["state"] == "rendering",
                    "job": self.job,
                },
            )
        if path == "/catalog":
            if self.avatar == "loading":
                return httpx.Response(503)
            return httpx.Response(200, json=CATALOG)
        if path == "/job":
            job = json.loads(request.content)
            if self.job is not None and self.job["state"] == "rendering":
                return httpx.Response(409, json={"ok": False})
            self.jobs.append(job)
            frames = max(1, round(job["duration_s"] * job["fps"]))
            self.job = {
                "id": job["id"],
                "kind": job["kind"],
                "state": "rendering",
                "frame": 0,
                "frames": frames,
                "render_fps": 20.0,
                "error": None,
            }
            self._left = self.polls
            return httpx.Response(202, json={"ok": True, "id": job["id"]})
        if path == "/cancel":
            self.cancelled = True
            if self.job is not None:
                self.job["state"] = "cancelled"
            return httpx.Response(200, json={"ok": True})
        if path == "/quit":
            self.quit = True
            self.alive = False
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404)

    def _finish(self) -> None:
        assert self.job is not None
        if self.fail:
            self.job.update(state="error", error=self.fail)
            return
        job = self.jobs[-1]
        out = Path(job["output_dir"])
        alpha = job.get("scene", {}).get("background", {}).get("mode") == "transparent"
        if job["kind"] == "still":
            for still in job.get("stills") or [{"path": job["still_path"]}]:
                tiny_png(Path(still["path"]), alpha=alpha)
        elif self.ffmpeg:
            frames = self.job["frames"]
            unity_encode(self.ffmpeg, job, frames)
            audio = [e for e in job["timeline"] if "audio" in e]
            (out / "registro.json").write_text(
                json.dumps(
                    {
                        "fps": job["fps"],
                        "frames": frames,
                        "skipped": 0,
                        "utterances": [
                            {
                                "utterance_id": e["audio"]["utterance_id"],
                                "first_audio_t": e["t"],
                                "heard_t": e["t"] + self.delay_s,
                            }
                            for e in audio
                        ],
                        "kind": job["kind"],
                        "width": job["width"],
                        "height": job["height"],
                        "frames_log": [
                            {
                                "i": i,
                                "rms": 0.0,
                                "mouth": 0.0,
                                "utterance": 0,
                                "bones": {
                                    name: [10.0 + i + k, 20.0 + k, 1.5]
                                    for k, name in enumerate(BONES)
                                },
                            }
                            for i in range(frames)
                        ],
                    }
                ),
                encoding="utf-8",
            )
        self.job["state"] = "done"
        self.job["frame"] = self.job["frames"]

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)
