"""ffmpeg de Sonnia Video (con el ffmpeg real del equipo si lo hay) y los subtítulos SRT."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from sonia.video import ffmpeg as ff
from sonia.video.audio import SAMPLE_RATE, frame_envelope, pcm16_to_float
from sonia.video.errors import VideoError
from sonia.video.script import QUALITIES
from sonia.video.srt import SrtWord, build_cues, format_srt, timestamp
from tests.video_fakes import mute_video


def system_ffmpeg() -> str | None:
    try:
        return ff.find_ffmpeg()
    except VideoError:
        return None


FFMPEG = system_ffmpeg()
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="sin ffmpeg en este equipo")


def test_argumentos_del_codificador_por_calidad() -> None:
    args = ff.encoder_args(QUALITIES["alta"])
    assert args[args.index("-crf") + 1] == "14"
    assert args[args.index("-preset") + 1] == "slow"
    assert args[args.index("-c:v") + 1] == "libx264"
    assert args[args.index("-pix_fmt") + 1] == "yuv420p"
    assert "bt709" in args[args.index("-vf") + 1]
    draft = ff.encoder_args(QUALITIES["borrador"])
    assert draft[draft.index("-crf") + 1] == "23"
    assert draft[draft.index("-preset") + 1] == "veryfast"


def test_orden_de_mezcla() -> None:
    command = ff.mux_command(
        "/bin/ffmpeg",
        Path("/t/mudo.mp4"),
        Path("/t/voz.wav"),
        Path("/v/x.mp4"),
        duration_s=12.3456,
        measured={
            "input_i": "-20.1",
            "input_tp": "-3.0",
            "input_lra": "4.0",
            "input_thresh": "-30.5",
            "target_offset": "0.2",
        },
    )
    assert command[0] == "/bin/ffmpeg"
    assert command[command.index("-c:v") + 1] == "copy"
    assert command[command.index("-c:a") + 1] == "aac"
    assert command[command.index("-b:a") + 1] == "192k"
    assert command[command.index("-movflags") + 1] == "+faststart"
    assert command[command.index("-t") + 1] == "12.346"
    loud = command[command.index("-af") + 1]
    assert loud.startswith("loudnorm=I=-14:TP=-1.5:LRA=11:measured_I=-20.1")
    assert "linear=true" in loud
    assert command[-1] == "/v/x.mp4"
    first = ff.loudness_command("/bin/ffmpeg", Path("/t/voz.wav"))
    assert "print_format=json" in first[first.index("-af") + 1]


def test_registro_de_unity(tmp_path: Path) -> None:
    path = tmp_path / "registro.json"
    path.write_text(
        json.dumps(
            {
                "fps": 30,
                "frames": 4,
                "skipped": 1,
                "utterances": [
                    {"utterance_id": 1, "first_audio_t": 0.6, "heard_t": 0.78},
                    {"utterance_id": 2, "first_audio_t": 2.0, "heard_t": 2.2},
                    {"utterance_id": 3, "first_audio_t": 3.0, "heard_t": 3.15},
                ],
                "frames_log": [{"i": i, "mouth": i / 10} for i in range(4)],
            }
        ),
        encoding="utf-8",
    )
    reg = ff.read_registro(path)
    assert reg is not None
    assert reg.frames == 4 and reg.skipped == 1
    assert reg.mouth == [0.0, 0.1, 0.2, 0.3]
    # Mediana de heard_t − t con los t de la línea de tiempo (0,18; 0,2; 0,15).
    assert ff.voice_delay(reg, {1: 0.6, 2: 2.0, 3: 3.0}) == pytest.approx(0.18)
    assert ff.voice_delay(None, {}) is None
    assert ff.read_registro(tmp_path / "no.json") is None


def test_voz_colocada() -> None:
    master = np.ones(10, dtype=np.float32)
    placed = ff.place_voice(master, 10, at_s=0.5, duration_s=2.0)
    assert len(placed) == 20
    assert placed[:5].sum() == 0 and placed[5:15].sum() == 10 and placed[15:].sum() == 0
    early = ff.place_voice(master, 10, at_s=-0.3, duration_s=1.0)
    assert early[:7].sum() == 7 and early[7:].sum() == 0


def test_desfase_entre_boca_y_voz() -> None:
    rng = np.random.default_rng(1)
    voice = np.abs(rng.normal(size=200)).astype(np.float32)
    mouth = np.concatenate([np.zeros(3), voice[:-3]])  # la boca va 3 cuadros detrás
    lag, corr = ff.measure_sync(mouth, voice)
    assert lag == 3 and corr > 0.95
    lag, _ = ff.measure_sync(voice[2:], voice[:-2])  # la boca va 2 cuadros delante
    assert lag == -2
    assert ff.measure_sync(np.zeros(50), voice[:50]) == (0, 0.0)


@needs_ffmpeg
def test_argumentos_validos_para_el_ffmpeg_que_lanza_unity(tmp_path: Path) -> None:
    assert FFMPEG is not None
    out = tmp_path / "video_mudo.mp4"
    width, height, fps = 64, 112, 30
    command = [
        FFMPEG,
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
        str(fps),
        "-i",
        "-",
        *ff.encoder_args(QUALITIES["borrador"]),
        str(out),
    ]
    frames = np.zeros((10, height, width, 4), dtype=np.uint8)
    frames[..., 2] = 200
    frames[..., 3] = 255
    result = subprocess.run(command, input=frames.tobytes(), capture_output=True, check=False)
    assert result.returncode == 0, result.stderr.decode()
    probe = probe_streams(out)
    video = probe["streams"][0]
    assert video["codec_name"] == "h264" and video["pix_fmt"] == "yuv420p"
    assert video.get("color_space") == "bt709"


def probe_streams(path: Path) -> dict[str, object]:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        pytest.skip("sin ffprobe")
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)  # type: ignore[no-any-return]


def decode_audio(path: Path) -> np.ndarray:
    assert FFMPEG is not None
    result = subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-i",
            str(path),
            "-ac",
            "1",
            "-ar",
            str(SAMPLE_RATE),
            "-f",
            "s16le",
            "-",
        ],
        capture_output=True,
        check=True,
    )
    return pcm16_to_float(result.stdout)


@needs_ffmpeg
def test_mezcla_final_con_voz_colocada_corregida_y_normalizada(tmp_path: Path) -> None:
    assert FFMPEG is not None
    fps, frames = 30, 90
    work = tmp_path / "trabajo"
    mute_video(FFMPEG, work / "video_mudo.mp4", width=64, height=112, fps=fps, frames=frames)
    # Voz: 1,5 s de tono suave con un silencio en medio.
    t = np.arange(round(1.5 * SAMPLE_RATE)) / SAMPLE_RATE
    master = (0.05 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    master[round(0.6 * SAMPLE_RATE) : round(0.9 * SAMPLE_RATE)] = 0
    lead, delay = 0.5, 0.1
    voice_at = lead + delay
    # La boca de Unity va 4 cuadros por detrás de esa voz.
    placed = ff.place_voice(master, SAMPLE_RATE, at_s=voice_at, duration_s=frames / fps)
    envelope = frame_envelope(placed, SAMPLE_RATE, fps, frames)
    mouth = np.concatenate([np.zeros(4), envelope[:-4]]) * 10
    (work / "registro.json").write_text(
        json.dumps(
            {
                "fps": fps,
                "frames": frames,
                "utterances": [{"utterance_id": 1, "first_audio_t": lead, "heard_t": lead + delay}],
                "frames_log": [{"i": i, "mouth": float(m)} for i, m in enumerate(mouth)],
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "videos" / "final.mp4"
    report = ff.finish(
        ffmpeg=FFMPEG,
        video=work / "video_mudo.mp4",
        registro=work / "registro.json",
        master=master,
        rate=SAMPLE_RATE,
        lead_s=lead,
        audio_t={1: lead},
        fps=fps,
        duration_s=frames / fps,
        out=out,
        work=work,
    )
    assert report.delay_s == pytest.approx(delay)
    assert report.lag_frames == 4
    assert report.corrected_s == pytest.approx(4 / fps)
    assert report.voice_at == pytest.approx(voice_at + 4 / fps)
    assert any("4 cuadros" in note for note in report.notes)
    probe = probe_streams(out)
    kinds = {s["codec_type"]: s for s in probe["streams"]}  # type: ignore[index, union-attr]
    assert kinds["video"]["codec_name"] == "h264"
    assert kinds["audio"]["codec_name"] == "aac"
    assert kinds["audio"]["sample_rate"] == "48000"
    assert float(probe["format"]["duration"]) == pytest.approx(frames / fps, abs=0.05)  # type: ignore[index]
    # La voz empieza donde dice el informe y suena más fuerte (normalizada a −14 LUFS).
    audio = decode_audio(out)
    onset = int(np.argmax(np.abs(audio) > 0.02)) / SAMPLE_RATE
    assert onset == pytest.approx(report.voice_at, abs=0.03)
    assert float(np.max(np.abs(audio))) > 0.2
    # Sonoridad del MP4 tal cual (estéreo): la de las redes.
    measured = ff.measure_loudness(FFMPEG, out)
    assert measured is not None
    assert float(measured["input_i"]) == pytest.approx(-14, abs=1.0)


@needs_ffmpeg
def test_mezcla_sin_registro(tmp_path: Path) -> None:
    assert FFMPEG is not None
    mute_video(FFMPEG, tmp_path / "video_mudo.mp4", width=64, height=64, fps=30, frames=30)
    master = (0.1 * np.sin(np.arange(SAMPLE_RATE // 2) / 10)).astype(np.float32)
    report = ff.finish(
        ffmpeg=FFMPEG,
        video=tmp_path / "video_mudo.mp4",
        registro=tmp_path / "registro.json",
        master=master,
        rate=SAMPLE_RATE,
        lead_s=0.2,
        audio_t={1: 0.2},
        fps=30,
        duration_s=1.0,
        out=tmp_path / "x.mp4",
        work=tmp_path,
    )
    assert report.delay_s is None
    assert report.voice_at == pytest.approx(0.2 + ff.FALLBACK_DELAY_S)
    assert any("no dice cuándo sonó" in note for note in report.notes)
    assert (tmp_path / "x.mp4").is_file()


def test_mezcla_sin_video_mudo(tmp_path: Path) -> None:
    with pytest.raises(VideoError, match="no dejó el vídeo mudo"):
        ff.finish(
            ffmpeg="ffmpeg",
            video=tmp_path / "no.mp4",
            registro=tmp_path / "r.json",
            master=np.zeros(10, np.float32),
            rate=SAMPLE_RATE,
            lead_s=0,
            audio_t={},
            fps=30,
            duration_s=1,
            out=tmp_path / "o.mp4",
            work=tmp_path,
        )


def test_ffmpeg_desde_la_variable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = tmp_path / "ffmpeg"
    fake.write_text("")
    monkeypatch.setenv("SONNIA_FFMPEG", str(fake))
    assert ff.find_ffmpeg() == str(fake)
    monkeypatch.setenv("SONNIA_FFMPEG", str(tmp_path / "no"))
    with pytest.raises(VideoError, match="SONNIA_FFMPEG"):
        ff.find_ffmpeg()


# ---------------------------------------------------------------------------
# SRT
# ---------------------------------------------------------------------------


def words(text: str, start: float, phrase: int, step: float = 0.3) -> list[SrtWord]:
    return [
        SrtWord(w, start + i * step, start + i * step + 0.25, phrase)
        for i, w in enumerate(text.split())
    ]


def test_srt_lineas_cortas_y_sin_mezclar_frases() -> None:
    long = "Gracias a todos los que pasaron por el stand de Sonnet Code durante los dos días del DevFest"
    items = words("¡Hola! Soy Sonnia.", 0.6, 1) + words(long, 2.0, 2) + words("Adiós.", 9.0, 3)
    cues = build_cues(items)
    assert cues[0].lines == ("¡Hola! Soy Sonnia.",)
    assert cues[-1].lines == ("Adiós.",)
    for cue in cues:
        assert len(cue.lines) <= 2
        assert all(len(line) <= 42 for line in cue.lines)
    middle = [c for c in cues if c not in (cues[0], cues[-1])]
    assert " ".join(" ".join(c.lines) for c in middle) == long
    # Sin solaparse y cada uno con su primera palabra.
    for a, b in zip(cues, cues[1:], strict=False):
        assert a.end <= b.start
    assert cues[0].start == pytest.approx(0.6)
    # Dos líneas equilibradas.
    two = [c for c in cues if len(c.lines) == 2][0]
    assert abs(len(two.lines[0]) - len(two.lines[1])) < 12


def test_srt_formato() -> None:
    assert timestamp(3723.456) == "01:02:03,456"
    text = format_srt(build_cues(words("Hola.", 0.5, 1)))
    assert text == "1\n00:00:00,500 --> 00:00:01,300\nHola.\n"
    assert format_srt([]) == ""


@needs_ffmpeg
def test_salidas_con_alfa_en_una_pasada_como_unity(tmp_path: Path) -> None:
    """ProRes 4444 con alfa, los PNG del cuadro y la copia a la mitad, desde los cuadros RGBA."""
    from tests.video_fakes import unity_encode

    mute = tmp_path / "trabajo" / "video_mudo.mov"
    mute.parent.mkdir(parents=True)
    frames, proxy = tmp_path / "sonnia" / "frames", tmp_path / "sonnia" / "proxy"
    frames.mkdir(parents=True)
    proxy.mkdir(parents=True)
    args, path = ff.transparent_outputs(mute, frames, proxy)
    assert path.endswith("proxy/sonnia_%04d.png")
    job = {"width": 64, "height": 112, "fps": 30, "encoder": {"args": args, "path": path}}
    unity_encode(FFMPEG, job, 12)  # type: ignore[arg-type]
    pngs = sorted(frames.glob("*.png"))
    assert [p.name for p in pngs[:2]] == ["sonnia_0000.png", "sonnia_0001.png"]
    assert len(pngs) == 12 and len(list(proxy.glob("*.png"))) == 12
    from PIL import Image

    with Image.open(pngs[0]) as full, Image.open(proxy / "sonnia_0000.png") as half:
        assert full.mode == "RGBA" and full.size == (64, 112)
        assert half.size == (32, 56)
        alpha = full.getchannel("A")
        assert alpha.getextrema() == (0, 255)  # fondo transparente y Sonnia opaca
    video = probe_streams(mute)["streams"][0]  # type: ignore[index]
    assert video["codec_name"] == "prores"
    assert video["pix_fmt"].startswith("yuva444p")
    assert "4444" in video.get("profile", "")


@needs_ffmpeg
def test_mov_con_voz_en_aac_y_voz_suelta_a_48k(tmp_path: Path) -> None:
    assert FFMPEG is not None
    from tests.video_fakes import unity_encode

    work = tmp_path / "w"
    work.mkdir()
    mute = work / "video_mudo.mov"
    args, path = ff.transparent_outputs(mute, tmp_path / "f", tmp_path / "p")
    (tmp_path / "f").mkdir()
    (tmp_path / "p").mkdir()
    unity_encode(
        FFMPEG, {"width": 64, "height": 112, "fps": 30, "encoder": {"args": args, "path": path}}, 45
    )
    t = np.arange(SAMPLE_RATE) / SAMPLE_RATE
    master = (0.1 * np.sin(2 * np.pi * 200 * t)).astype(np.float32)
    out = tmp_path / "final.mov"
    voice = tmp_path / "sonnia" / "voz.wav"
    report = ff.finish(
        ffmpeg=FFMPEG,
        video=mute,
        registro=work / "registro.json",
        master=master,
        rate=SAMPLE_RATE,
        lead_s=0.2,
        audio_t={1: 0.2},
        fps=30,
        duration_s=1.5,
        out=out,
        work=work,
        voice_out=voice,
    )
    assert report.frames == 45
    streams = {s["codec_type"]: s for s in probe_streams(out)["streams"]}  # type: ignore[index, union-attr]
    assert streams["video"]["codec_name"] == "prores"
    assert streams["audio"]["codec_name"] == "aac"
    wav = probe_streams(voice)["streams"][0]  # type: ignore[index]
    assert (wav["sample_rate"], wav["channels"]) == ("48000", 1)
    # La voz suelta empieza donde la del vídeo.
    audio = decode_audio(voice)
    onset = int(np.argmax(np.abs(audio) > 0.02)) / SAMPLE_RATE
    assert onset == pytest.approx(report.voice_at, abs=0.03)


def test_registro_con_huesos(tmp_path: Path) -> None:
    path = tmp_path / "registro.json"
    path.write_text(
        json.dumps(
            {
                "fps": 30,
                "frames": 2,
                "kind": "video",
                "width": 1080,
                "height": 1920,
                "frames_log": [
                    {
                        "i": 0,
                        "mouth": 0.1,
                        "bones": {"cara": [540.2, 600.0, 1.7], "mano_der": [400, 900, 1.3]},
                    },
                    {"i": 1, "mouth": 0.2, "bones": {"cara": [541, 601, 1.7], "raro": "x"}},
                ],
            }
        ),
        encoding="utf-8",
    )
    reg = ff.read_registro(path)
    assert reg is not None
    assert (reg.kind, reg.width, reg.height) == ("video", 1080, 1920)
    assert reg.bones[0]["mano_der"] == (400.0, 900.0, 1.3)
    assert reg.bones[1] == {"cara": (541.0, 601.0, 1.7)}


def test_retraso_medido_en_lo_que_sono(tmp_path: Path) -> None:
    from sonia.video.audio import resample, write_wav

    rng = np.random.default_rng(3)
    master = np.zeros(SAMPLE_RATE * 2, dtype=np.float32)
    for start in (0.1, 0.7, 1.3):  # tres «palabras» de ruido
        a = round(start * SAMPLE_RATE)
        master[a : a + SAMPLE_RATE // 4] = rng.normal(0, 0.2, SAMPLE_RATE // 4)
    lead, real = 0.5, 0.115
    heard = ff.place_voice(master, SAMPLE_RATE, at_s=lead + real, duration_s=3.0)
    write_wav(tmp_path / "heard.wav", resample(heard, SAMPLE_RATE, 48000), 48000)
    delay = ff.heard_delay(tmp_path / "heard.wav", master, SAMPLE_RATE, lead_s=lead)
    assert delay == pytest.approx(real, abs=0.006)
    assert ff.heard_delay(tmp_path / "no.wav", master, SAMPLE_RATE, lead_s=lead) is None
    write_wav(tmp_path / "silencio.wav", np.zeros(48000, np.float32), 48000)
    assert ff.heard_delay(tmp_path / "silencio.wav", master, SAMPLE_RATE, lead_s=lead) is None


def cut_words(text: str) -> list[list[str]]:
    from sonia.video.srt import split_lines

    return split_lines(text.split())


def test_srt_no_parte_nombres_propios_ni_deja_palabras_solas() -> None:
    long = (
        "¡Gracias a todos los que pasaron por el stand de Sonnet Code en el DevFest Santo Domingo!"
    )
    cues = cut_words(long)
    lines = [line for cue in cues for line in cue]
    for name in ("Sonnet Code", "DevFest Santo Domingo!"):
        assert any(name in line for line in lines), lines
    for cue in cues:
        assert len(cue) <= 2 and all(len(line) <= 42 for line in cue)
        assert all(len(line.split()) > 1 for line in cue), cue  # ninguna palabra sola
    assert " ".join(lines) == long


def test_srt_corta_por_clausulas() -> None:
    cues = cut_words(
        "¡Hola! Soy Sonnia, la mascota de Sonnet Code: una asistente virtual que conversa "
        "contigo en tiempo real."
    )
    assert cues[0] == ["¡Hola! Soy Sonnia,", "la mascota de Sonnet Code:"]
    assert cues[1][0].startswith("una asistente")
    # «Plaza de la Cultura» es un nombre aunque lleve «de la».
    cues = cut_words(
        "Está frente a la Plaza de la Cultura de Santo Domingo, a pocos pasos del metro."
    )
    assert any("Plaza de la Cultura de Santo Domingo," in line for cue in cues for line in cue)
    # Una frase corta, una línea; una que cabe en dos líneas, un solo subtítulo.
    assert cut_words("¡Allá te espero!") == [["¡Allá te espero!"]]
    assert cut_words("¡Hola! Soy Sonnia, la asistente virtual del DevFest.") == [
        ["¡Hola! Soy Sonnia,", "la asistente virtual del DevFest."]
    ]
