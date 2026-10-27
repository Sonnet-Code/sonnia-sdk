"""Sonnia Video de punta a punta sin red: Gemini falso, modelo de gestos falso, renderizador
falso (que deja un vídeo mudo con el ffmpeg del equipo) y la mezcla final de verdad."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from sonia.llm.client import Completion
from sonia.types import Message
from sonia.video.errors import VideoError
from sonia.video.pipeline import Pipeline
from sonia.video.renderer import Progress, RendererClient
from sonia.video.script import parse_script, phrase_texts
from sonia.video.voice import VoiceCache, VoiceMaker
from tests.video_fakes import FakeRenderer, Recorder, gemini_handler, synth_take

FFMPEG = shutil.which("ffmpeg") or (
    "/opt/homebrew/bin/ffmpeg" if Path("/opt/homebrew/bin/ffmpeg").is_file() else None
)
pytestmark = pytest.mark.skipif(FFMPEG is None, reason="sin ffmpeg en este equipo")

#: Las claves del contrato con Unity (``docs/video.md``).
JOB_KEYS = {
    "id",
    "kind",
    "output_dir",
    "width",
    "height",
    "fps",
    "supersample",
    "subframes",
    "shutter",
    "duration_s",
    "warmup_s",
    "audio_sample_rate",
    "timeline",
    "scene",
    "encoder",
}


class FakeLLM:
    def __init__(self, answer: str | Exception) -> None:
        self.answer = answer
        self.requests: list[list[Message]] = []
        self.closed = False

    async def complete(self, messages: list[Message]) -> Completion:
        self.requests.append(messages)
        if isinstance(self.answer, Exception):
            raise self.answer
        return Completion(self.answer, "stop")

    async def aclose(self) -> None:
        self.closed = True


def make_script(**extra: Any) -> Any:
    data: dict[str, Any] = {
        "titulo": "prueba",
        "pronunciacion": {"sonnetcode.com": "sónet code punto com"},
        "video": {"formato": "64x112", "calidad": "borrador", "antes": 0.5, "despues": 0.5},
        "frase": [
            {"texto": "¡Hola! Soy Sonia."},
            {"texto": "Visita sonnetcode.com.", "pausa": 0.3},
        ],
    }
    data.update(extra)
    return parse_script(data)


def make_pipeline(
    tmp_path: Path, script: Any, *, llm: FakeLLM, renderer: FakeRenderer | None = None
) -> tuple[Pipeline, FakeRenderer, Recorder, io.StringIO]:
    texts = phrase_texts(script)
    samples, times = synth_take([t.spoken_words for t in texts])
    words = [w for t in texts for w in t.spoken_words]
    gemini = Recorder(
        gemini_handler(samples, [(w, a, b) for w, (a, b) in zip(words, times, strict=True)])
    )
    fake = renderer or FakeRenderer(ffmpeg=FFMPEG)
    stream = io.StringIO()
    assert FFMPEG is not None
    pipeline = Pipeline(
        client=RendererClient(8795, transport=fake.transport),
        voice=VoiceMaker(
            VoiceCache(tmp_path / "cache"), gemini_transport=gemini.transport, backoff_s=0
        ),
        ffmpeg=FFMPEG,
        progress=Progress(stream, every_s=0),
        llm_factory=lambda: llm,
    )
    return pipeline, fake, gemini, stream


@pytest.fixture(autouse=True)
def _gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "falsa")


def test_video_entero(tmp_path: Path) -> None:
    script = make_script()
    llm = FakeLLM(
        '{"gestos": [{"frase": 1, "gesto": "waveCalm"}, {"frase": 2, "gesto": "ninguno"}]}'
    )
    pipeline, fake, gemini, stream = make_pipeline(tmp_path, script, llm=llm)
    result = pipeline.render(script, tmp_path / "videos")

    assert result.video == tmp_path / "videos" / "prueba.mp4"
    assert result.video.is_file() and result.srt.is_file()
    assert llm.closed and len(llm.requests) == 1
    assert {uid: cue.name for uid, cue in result.gestures.items()} == {1: "waveCalm"}

    (job,) = fake.jobs
    assert set(job) == JOB_KEYS
    assert job["kind"] == "video"
    assert (job["width"], job["height"], job["fps"]) == (64, 112, 30)
    assert (job["supersample"], job["subframes"]) == (1, 1)
    assert job["audio_sample_rate"] == 24000
    assert job["duration_s"] == pytest.approx(result.duration_s, abs=1 / 30)
    assert job["encoder"]["ffmpeg"] == FFMPEG
    assert job["encoder"]["path"] == str(Path(job["output_dir"]) / "video_mudo.mp4")
    assert job["scene"]["background"]["mode"] == "stand"
    timeline = job["timeline"]
    audio = [e["audio"] for e in timeline if "audio" in e]
    assert [a["utterance_id"] for a in audio] == [1, 2]
    assert all(Path(a["wav"]).is_file() for a in audio)
    gesture = [e["message"] for e in timeline if e.get("message", {}).get("type") == "gesture"]
    assert gesture == [{"type": "gesture", "name": "waveCalm", "utterance_id": 1}]
    finals = [
        e["message"]["text"]
        for e in timeline
        if e.get("message", {}).get("type") == "transcript" and e["message"]["final"]
    ]
    assert finals == ["¡Hola! Soy Sonnia.", "Visita sonnetcode.com."]
    # El vídeo mudo se borra al acabar; el registro se queda.
    assert not (Path(job["output_dir"]) / "video_mudo.mp4").exists()
    assert (Path(job["output_dir"]) / "registro.json").is_file()

    # La voz en el sitio que dijo el registro (heard_t − t = 0,12).
    assert result.report.delay_s == pytest.approx(0.12)
    assert result.report.voice_at == pytest.approx(0.5 + 0.12)
    srt = result.srt.read_text(encoding="utf-8")
    assert "¡Hola! Soy Sonnia." in srt and "Visita sonnetcode.com." in srt
    assert "Sonia" not in srt

    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        probe = json.loads(
            subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-show_streams",
                    "-show_format",
                    "-of",
                    "json",
                    str(result.video),
                ],
                capture_output=True,
                check=True,
            ).stdout
        )
        assert {s["codec_type"] for s in probe["streams"]} == {"video", "audio"}
        assert float(probe["format"]["duration"]) == pytest.approx(result.duration_s, abs=0.1)

    # Otro vídeo con el mismo texto y otra luz: la voz sale de la caché.
    calls = len(gemini.requests)
    again = pipeline.render(
        make_script(escena={"luz": "dramatica"}, gestos={"modo": "ninguno"}), tmp_path / "videos"
    )
    assert again.take.cached and len(gemini.requests) == calls
    assert fake.jobs[-1]["scene"]["lighting"]["preset"] == "dramatic"
    assert again.gestures == {}


def test_sin_modelo_de_gestos_sale_sin_gestos_y_avisa(tmp_path: Path) -> None:
    script = make_script()
    pipeline, fake, _, _ = make_pipeline(tmp_path, script, llm=FakeLLM(RuntimeError("caído")))
    result = pipeline.render(script, tmp_path / "videos")
    assert result.gestures == {}
    assert any("Sin gestos elegidos: el modelo de gestos falló: caído" in n for n in result.notes)


def test_gestos_manuales_y_acciones(tmp_path: Path) -> None:
    script = make_script(
        gestos={"modo": "manual"},
        frase=[{"texto": "¡Hola! Soy Sonia.", "gesto": "WAVECALM"}, {"texto": "Adiós."}],
        accion=[{"segundo": 0.1, "gesto": "thumbsupcalm"}],
    )
    llm = FakeLLM("no debería usarse")
    pipeline, fake, _, _ = make_pipeline(tmp_path, script, llm=llm)
    result = pipeline.render(script, tmp_path / "videos")
    assert {uid: cue.name for uid, cue in result.gestures.items()} == {1: "waveCalm"}
    assert llm.requests == []
    actions = [e for e in fake.jobs[0]["timeline"] if "action" in e]
    assert actions == [{"t": 0.1, "action": {"name": "thumbsUpCalm", "mirror": False}}]


def test_gesto_manual_inexistente(tmp_path: Path) -> None:
    script = make_script(frase=[{"texto": "Hola.", "gesto": "volar"}])
    pipeline, fake, _, _ = make_pipeline(tmp_path, script, llm=FakeLLM("{}"))
    with pytest.raises(VideoError, match="«volar» no está en el catálogo"):
        pipeline.render(script, tmp_path / "videos")
    assert fake.jobs == []


def test_frase_sin_palabras(tmp_path: Path) -> None:
    script = make_script(frase=[{"texto": "Hola."}, {"texto": "—"}])
    pipeline, fake, gemini, _ = make_pipeline(tmp_path, make_script(), llm=FakeLLM("{}"))
    with pytest.raises(VideoError, match="La frase 2 no tiene palabras"):
        pipeline.render(script, tmp_path / "videos")
    assert gemini.requests == []


def test_vista_previa(tmp_path: Path) -> None:
    script = make_script(escena={"encuadre": "primer-plano"})
    pipeline, fake, gemini, _ = make_pipeline(tmp_path, script, llm=FakeLLM("{}"))
    out = pipeline.still(script, tmp_path / "vista.png")
    assert out.read_bytes().startswith(b"\x89PNG")
    (job,) = fake.jobs
    assert job["kind"] == "still"
    assert job["still_path"].endswith("vista.png")
    assert job["scene"]["framing"]["preset"] == "close"
    assert gemini.requests == []  # sin voz


def test_fondo_transparente_deja_el_mov_y_el_paquete_para_reels(tmp_path: Path) -> None:
    script = make_script(escena={"fondo": "transparente"}, gestos={"modo": "ninguno"})
    pipeline, fake, _, _ = make_pipeline(tmp_path, script, llm=FakeLLM("{}"))
    result = pipeline.render(script, tmp_path / "videos")
    (job,) = fake.jobs
    assert job["scene"]["background"]["mode"] == "transparent"
    assert any(a == "prores_ks" for a in job["encoder"]["args"])
    assert result.video == tmp_path / "videos" / "prueba.mov"
    package = result.package
    assert package is not None and package.root == tmp_path / "videos" / "prueba" / "sonnia"
    frames = package.frame_files()
    assert len(frames) == result.report.frames and frames[0].name == "sonnia_0000.png"
    assert len(list(package.proxy.glob("sonnia_*.png"))) == len(frames)
    for name in ("prueba.png", "voz.wav", "palabras.json", "voz.json", "localizador.json"):
        assert (package.root / name).is_file(), name
    words = json.loads((package.root / "palabras.json").read_text(encoding="utf-8"))
    assert [w["texto"] for w in words][:3] == ["¡Hola!", "Soy", "Sonnia."]
    assert set(words[0]) == {"texto", "inicio", "fin"}
    assert words[0]["inicio"] >= result.report.voice_at - 1e-3
    voice = json.loads((package.root / "voz.json").read_text(encoding="utf-8"))
    assert voice["archivo"] == "voz.wav" and voice["frecuencia"] == 48000
    assert [f["texto"] for f in voice["frases"]] == ["¡Hola! Soy Sonnia.", "Visita sonnetcode.com."]
    assert voice["voz_gemini"]["voz"] == "es-es-techagent-5"
    locator = json.loads((package.root / "localizador.json").read_text(encoding="utf-8"))
    assert (locator["fps"], locator["ancho"], locator["alto"]) == (30, 64, 112)
    assert "izquierda de la pantalla" in locator["notas"]
    first = locator["cuadros"][0]
    assert first["cuadro"] == 0
    assert set(first["cara"]) == {"x", "y"} and set(first["mano_der"]) == {"x", "y", "z"}
    assert len(locator["cuadros"]) == len(frames)
    assert f"count: {len(frames)}" in result.snippet
    assert "words: 'assets/sonnia/palabras.json'" in result.snippet
    assert "voice: 'assets/sonnia/voz.wav'" in result.snippet
    # El vídeo mudo se borra; los cuadros (el paquete) no.
    assert not (Path(job["output_dir"]) / "video_mudo.mov").exists()
    # Otra vez el mismo título fuera de un reel: se reemplaza sin preguntar.
    pipeline.render(script, tmp_path / "videos")


def test_paquete_directo_en_un_reel_con_forzar(tmp_path: Path) -> None:
    reel = tmp_path / "media" / "reels" / "mi-reel"
    reel.mkdir(parents=True)
    script = make_script(
        video={"formato": "64x112", "calidad": "borrador", "reel": str(reel)},
        escena={"fondo": "transparente"},
        gestos={"modo": "ninguno"},
    )
    pipeline, fake, gemini, _ = make_pipeline(tmp_path, script, llm=FakeLLM("{}"))
    with pytest.raises(VideoError, match="no parece un reel"):
        pipeline.render(script, tmp_path / "videos")
    (reel / "reel.config.js").write_text("export default {};\n", encoding="utf-8")
    result = pipeline.render(script, tmp_path / "videos")
    assert result.package is not None and result.package.root == reel / "assets" / "sonnia"
    assert result.package.in_reel and "copia la carpeta" not in result.snippet
    calls = len(fake.jobs)
    # Ya hay cuadros: sin --forzar no se toca nada ni se gasta.
    requests = len(gemini.requests)
    with pytest.raises(VideoError, match="--forzar"):
        pipeline.render(script, tmp_path / "videos")
    assert len(fake.jobs) == calls and len(gemini.requests) == requests
    (reel / "assets" / "sonnia" / "frames" / "sonnia_9999.png").write_bytes(b"viejo")
    pipeline.render(script, tmp_path / "videos", force=True)
    assert not (reel / "assets" / "sonnia" / "frames" / "sonnia_9999.png").exists()
    assert (reel / "reel.config.js").is_file()


def test_fotos_con_gesto_y_rafaga(tmp_path: Path) -> None:
    from sonia.gestures.catalog import GestureCatalog
    from sonia.video.pipeline import PHOTO_QUALITY, photo_times
    from tests.video_fakes import CATALOG

    script = make_script(escena={"fondo": "transparente"}, video={"formato": "4k-vertical"})
    pipeline, fake, gemini, _ = make_pipeline(tmp_path, script, llm=FakeLLM("{}"))
    single = pipeline.photos(script, tmp_path / "fotos", gesture="wavecalm", mirror=True)
    (job,) = fake.jobs
    assert job["kind"] == "still" and (job["width"], job["height"]) == (2160, 3840)
    assert job["supersample"] == PHOTO_QUALITY.supersample == 3
    assert {"t": 0.0, "action": {"name": "waveCalm", "mirror": True}} in job["timeline"]
    wave = GestureCatalog.from_message(CATALOG).get("waveCalm")
    assert [s["t"] for s in job["stills"]] == photo_times(wave)
    assert job["duration_s"] == pytest.approx(max(s["t"] for s in job["stills"]))
    assert [p.name for p in single] == ["prueba.png"]  # el título del guion
    burst = pipeline.photos(script, tmp_path / "fotos", gesture="waveCalm", burst=4, title="ola")
    times = [s["t"] for s in fake.jobs[-1]["stills"]]
    assert times == pytest.approx([0.125, 0.375, 0.625, 0.875])  # waveCalm dura 1 s
    assert [p.name for p in burst] == ["ola_01.png", "ola_02.png", "ola_03.png", "ola_04.png"]
    assert all(p.is_file() for p in burst)
    with pytest.raises(VideoError, match="no está en el catálogo"):
        pipeline.photos(script, tmp_path / "fotos", gesture="volar")
    assert gemini.requests == []  # las fotos no tienen voz


def test_momentos_de_las_fotos() -> None:
    from sonia.gestures.catalog import Gesture
    from sonia.video.pipeline import photo_times

    beat = Gesture(name="g", duration=2.0, core_start=0.5, core_stop=1.5, critical_beat=0.8)
    assert photo_times(beat) == [0.8]
    assert photo_times(Gesture(name="g", duration=2.0, core_start=0.5, core_stop=1.5)) == [1.0]
    assert photo_times(beat, moment=1.7) == [1.7]
    assert photo_times(None) == [0.0]
    assert photo_times(None, burst=3) == pytest.approx([0.5, 1.5, 2.5])
