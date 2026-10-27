"""Voz de Sonnia Video con APIs falsas (``httpx.MockTransport``): Gemini, ElevenLabs y la caché."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import numpy as np
import pytest

from sonia.video import elevenlabs as eleven
from sonia.video import gemini
from sonia.video.audio import SAMPLE_RATE, pcm16_bytes, write_wav
from sonia.video.errors import VideoError
from sonia.video.http import request_json
from sonia.video.script import parse_script, phrase_texts, tts_text
from sonia.video.voice import VoiceCache, VoiceMaker
from tests.video_fakes import Recorder, gemini_handler, synth_take


@pytest.fixture
def keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "clave-gemini-falsa")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "clave-eleven-falsa")


def two_phrases(**voice: object) -> tuple[object, list[object]]:
    script = parse_script(
        {
            "voz": voice or {},
            "frase": [{"texto": "Hola, soy Sonnia."}, {"texto": "Nos vemos en 2026."}],
        }
    )
    return script, phrase_texts(script)


def asr_words(
    texts: list[object], times: list[tuple[float, float]]
) -> list[tuple[str, float, float]]:
    words = [w for t in texts for w in t.spoken_words]  # type: ignore[attr-defined]
    return [(w, a, b) for w, (a, b) in zip(words, times, strict=True)]


async def test_gemini_voz_y_tiempos_por_transcripcion(keys: None, tmp_path: Path) -> None:
    script, texts = two_phrases()
    samples, times = synth_take([t.spoken_words for t in texts])  # type: ignore[attr-defined]
    words = asr_words(texts, times)
    # La transcripción escribe el número en cifra y sin signos.
    words = [(w.strip("¡!.,"), a, b) for w, a, b in words]
    recorder = Recorder(gemini_handler(samples, words))
    maker = VoiceMaker(VoiceCache(tmp_path), gemini_transport=recorder.transport, backoff_s=0)
    take = await maker.take(script, texts)  # type: ignore[arg-type]
    assert take.engine == "gemini" and take.timing == "transcripcion" and not take.cached
    assert take.voice == gemini.DEFAULT_VOICE
    assert len(take.words) == len(words)
    assert take.words[0] == pytest.approx(times[0], abs=1e-3)
    assert np.max(np.abs(take.samples - samples)) < 1e-3
    tts, asr = recorder.bodies()
    request = recorder.requests[0]
    assert request.url == "https://generativelanguage.googleapis.com/v1beta/interactions"
    assert request.headers["x-goog-api-key"] == "clave-gemini-falsa"
    assert tts["model"] == gemini.TTS_MODEL
    assert tts["generation_config"] == {"speech_config": [{"voice": gemini.DEFAULT_VOICE}]}
    assert tts["response_format"] == {
        "type": "audio",
        "mime_type": "audio/wav",
        "sample_rate": 24000,
    }
    content = tts["input"][0]["content"][0]
    # Al TTS va «Sonia» (lo que se dice) y el estilo latino por defecto.
    assert content["text"] == tts_text(texts)  # type: ignore[arg-type]
    assert "Sonia" in content["text"] and "Sonnia" not in content["text"]
    assert content["annotations"] == [{"type": "speech_metadata", "style": gemini.DEFAULT_STYLE}]
    assert asr["model"] == gemini.TRANSCRIBE_MODEL
    assert asr["generation_config"]["transcription_config"]["language_codes"] == ["es-419"]
    assert asr["input"][0]["mime_type"] == "audio/wav"


async def test_la_cache_no_vuelve_a_pagar(keys: None, tmp_path: Path) -> None:
    script, texts = two_phrases(voz="Leda", estilo="ninguno")
    samples, times = synth_take([t.spoken_words for t in texts])  # type: ignore[attr-defined]
    recorder = Recorder(gemini_handler(samples, asr_words(texts, times)))
    maker = VoiceMaker(VoiceCache(tmp_path), gemini_transport=recorder.transport, backoff_s=0)
    first = await maker.take(script, texts)  # type: ignore[arg-type]
    assert "annotations" not in recorder.bodies()[0]["input"][0]["content"][0]
    calls = len(recorder.requests)
    again = await maker.take(script, texts)  # type: ignore[arg-type]
    assert again.cached
    assert len(recorder.requests) == calls  # ni voz ni transcripción
    assert again.words == first.words
    # Otro texto sí se paga.
    other, other_texts = two_phrases(voz="Leda", estilo="ninguno")
    other.phrases[0].text = "Hola de nuevo."  # type: ignore[attr-defined]
    await maker.take(other, phrase_texts(other))  # type: ignore[arg-type]
    assert len(recorder.requests) > calls


async def test_sin_clave_dice_donde_ponerla(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    script, texts = two_phrases()
    maker = VoiceMaker(VoiceCache(tmp_path))
    with pytest.raises(VideoError) as info:
        await maker.take(script, texts)  # type: ignore[arg-type]
    assert "GEMINI_API_KEY" in str(info.value)
    assert str(tmp_path / "sonnia-video" / ".env") in str(info.value)


async def test_transcripcion_fallida_usa_el_respaldo_local(keys: None, tmp_path: Path) -> None:
    script, texts = two_phrases()
    samples, _ = synth_take([t.spoken_words for t in texts])  # type: ignore[attr-defined]
    tts = gemini_handler(samples, [])

    def handle(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)["model"] == gemini.TRANSCRIBE_MODEL:
            return httpx.Response(400, json={"error": {"message": "modelo no disponible"}})
        return tts(request)

    maker = VoiceMaker(
        VoiceCache(tmp_path), gemini_transport=httpx.MockTransport(handle), backoff_s=0
    )
    take = await maker.take(script, texts)  # type: ignore[arg-type]
    assert take.timing == "local"
    assert len(take.words) == sum(len(t.spoken_words) for t in texts)  # type: ignore[attr-defined]


async def test_reintentos_con_espera_creciente() -> None:
    answers = [
        httpx.Response(429, json={"error": {"message": "cuota"}}),
        httpx.Response(503),
        httpx.Response(200, json={"ok": 1}),
    ]
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: answers.pop(0))) as client:
        data = await request_json(
            client, "GET", "https://x.test/a", what="Prueba", backoff_s=2, sleep=sleep
        )
    assert data == {"ok": 1}
    assert waits == [2, 4]

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(401, json={"detail": {"message": "clave mala"}})
        )
    ) as client:
        with pytest.raises(VideoError, match="Prueba devolvió 401: clave mala"):
            await request_json(client, "GET", "https://x.test/a", what="Prueba", sleep=sleep)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(500))
    ) as client:
        with pytest.raises(VideoError, match="falló 3 veces"):
            await request_json(
                client, "GET", "https://x.test/a", what="Prueba", tries=3, sleep=sleep
            )


def eleven_handler(
    samples: np.ndarray, *, reject_v4: bool = False, voices: list[dict[str, object]] | None = None
) -> Recorder:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/voices":
            return httpx.Response(
                200,
                json={"voices": voices or [], "has_more": False, "next_page_token": None},
            )
        body = json.loads(request.content)
        if reject_v4 and body["model_id"] == "eleven_v4":
            return httpx.Response(422, json={"detail": [{"msg": "unsupported"}]})
        text = body["text"]
        duration = len(samples) / SAMPLE_RATE
        step = duration / len(text)
        return httpx.Response(
            200,
            json={
                "audio_base64": base64.b64encode(pcm16_bytes(samples)).decode(),
                "alignment": {
                    "characters": list(text),
                    "character_start_times_seconds": [i * step for i in range(len(text))],
                    "character_end_times_seconds": [(i + 1) * step for i in range(len(text))],
                },
                "normalized_alignment": None,
            },
        )

    return Recorder(handle)


async def test_elevenlabs_con_tiempos_por_caracteres(keys: None, tmp_path: Path) -> None:
    script, texts = two_phrases(
        motor="elevenlabs",
        voz="Rachel",
        estabilidad=0.4,
        similitud=0.8,
        estilo=0.2,
        velocidad=1.1,
        idioma="es",
    )
    samples, _ = synth_take([t.spoken_words for t in texts])  # type: ignore[attr-defined]
    voices = [
        {
            "voice_id": "a" * 20,
            "name": "Rachel - calm",
            "category": "premade",
            "labels": {"accent": "american"},
        },
        {"voice_id": "b" * 20, "name": "Rachelle", "category": "cloned"},
    ]
    recorder = eleven_handler(samples, voices=voices)
    maker = VoiceMaker(VoiceCache(tmp_path), eleven_transport=recorder.transport, backoff_s=0)
    take = await maker.take(script, texts)  # type: ignore[arg-type]
    assert take.timing == "elevenlabs"
    assert take.voice == "Rachel - calm"
    assert take.model == eleven.DEFAULT_MODEL
    search, speech = recorder.requests
    assert search.url.params["search"] == "Rachel"
    assert speech.headers["xi-api-key"] == "clave-eleven-falsa"
    assert speech.url.path == f"/v1/text-to-speech/{'a' * 20}/with-timestamps"
    assert speech.url.params["output_format"] == "pcm_24000"
    body = json.loads(speech.content)
    assert body["model_id"] == "eleven_v4"
    assert body["language_code"] == "es"
    assert body["voice_settings"] == {
        "stability": 0.4,
        "similarity_boost": 0.8,
        "style": 0.2,
        "speed": 1.1,
    }
    assert "Sonia" in body["text"]
    # Tiempos repartidos por los caracteres: en orden y dentro de la toma.
    assert all(b[0] >= a[0] for a, b in zip(take.words, take.words[1:], strict=False))
    assert take.words[-1][1] <= take.duration + 1e-6
    # La caché guarda también la alineación: la segunda vez no se llama a nadie.
    again = await maker.take(script, texts)  # type: ignore[arg-type]
    assert again.cached and again.timing == "elevenlabs" and again.words == take.words
    assert len(recorder.requests) == 2


async def test_elevenlabs_v4_rechazado_repite_con_multilingual(keys: None, tmp_path: Path) -> None:
    script, texts = two_phrases(motor="elevenlabs", voz="c" * 20, idioma="es")
    samples, _ = synth_take([t.spoken_words for t in texts])  # type: ignore[attr-defined]
    recorder = eleven_handler(samples, reject_v4=True)
    maker = VoiceMaker(VoiceCache(tmp_path), eleven_transport=recorder.transport, backoff_s=0)
    take = await maker.take(script, texts)  # type: ignore[arg-type]
    assert take.model == eleven.FALLBACK_MODEL
    bodies = recorder.bodies()
    assert [b["model_id"] for b in bodies] == ["eleven_v4", "eleven_multilingual_v2"]
    # multilingual_v2 no acepta language_code; con un id no hace falta buscar la voz.
    assert "language_code" not in bodies[1]
    assert all(r.url.path != "/v2/voices" for r in recorder.requests)


async def test_elevenlabs_voz_desconocida_o_sin_voz(keys: None, tmp_path: Path) -> None:
    recorder = eleven_handler(
        np.zeros(10, np.float32),
        voices=[{"voice_id": "d" * 20, "name": "Otra"}, {"voice_id": "e" * 20, "name": "Más"}],
    )
    async with eleven.ElevenLabsClient("k", transport=recorder.transport, backoff_s=0) as client:
        with pytest.raises(VideoError, match="No encuentro la voz «Nadie».*Otra, Más"):
            await client.resolve_voice("Nadie")
        with pytest.raises(VideoError, match="Falta la voz de ElevenLabs"):
            await client.resolve_voice(" ")
        with pytest.raises(VideoError, match="acepta 5000 por toma"):
            await client.synthesize("x" * 5001, voice_id="d" * 20, model="eleven_v3")


async def test_lista_de_voces_por_paginas() -> None:
    pages = [
        {
            "voices": [{"voice_id": "a" * 20, "name": "Uno"}],
            "has_more": True,
            "next_page_token": "p2",
        },
        {
            "voices": [
                {
                    "voice_id": "b" * 20,
                    "name": "Dos",
                    "labels": {"gender": "female", "accent": "latin"},
                }
            ],
            "has_more": False,
        },
    ]
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=pages[len(seen) - 1])

    async with eleven.ElevenLabsClient("k", transport=httpx.MockTransport(handle)) as client:
        voices = await client.voices()
    assert [v.name for v in voices] == ["Uno", "Dos"]
    assert voices[1].summary == "latin, female"
    assert seen[1].url.params["next_page_token"] == "p2"
    assert seen[0].url.params["page_size"] == "100"


async def test_motor_archivo_con_wav_y_transcripcion(keys: None, tmp_path: Path) -> None:
    script = parse_script(
        {
            "voz": {"motor": "archivo", "archivo": str(tmp_path / "voz.wav")},
            "frase": [{"texto": "Uno dos."}, {"texto": "Tres."}],
        }
    )
    texts = phrase_texts(script)
    samples, times = synth_take([t.spoken_words for t in texts])
    write_wav(tmp_path / "voz.wav", samples)
    recorder = Recorder(
        gemini_handler(samples, [("uno", *times[0]), ("dos", *times[1]), ("tres", *times[2])])
    )
    maker = VoiceMaker(
        VoiceCache(tmp_path / "cache"), gemini_transport=recorder.transport, backoff_s=0
    )
    take = await maker.take(script, texts)
    assert take.engine == "archivo" and take.cached and take.timing == "transcripcion"
    assert [b["model"] for b in recorder.bodies()] == [gemini.TRANSCRIBE_MODEL]  # no se paga voz
    assert take.words[2] == pytest.approx(times[2], abs=1e-3)


async def test_motor_archivo_sin_clave_reparte_por_energia(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    script = parse_script(
        {
            "voz": {"motor": "archivo", "archivo": str(tmp_path / "voz.wav")},
            "frase": [{"texto": "Uno dos."}, {"texto": "Tres."}],
        }
    )
    texts = phrase_texts(script)
    samples, _ = synth_take([t.spoken_words for t in texts])
    write_wav(tmp_path / "voz.wav", samples)
    take = await VoiceMaker(VoiceCache(tmp_path / "cache")).take(script, texts)
    assert take.timing == "local"
    assert len(take.words) == 3


def test_estilo_de_gemini() -> None:
    assert gemini.style_for(None) == gemini.DEFAULT_STYLE
    assert gemini.style_for("") == gemini.DEFAULT_STYLE
    assert gemini.style_for("Ninguno") == ""
    assert gemini.style_for("Habla rápido") == "Habla rápido"
    assert eleven.looks_like_voice_id("21m00Tcm4TlvDq8ikWAM")
    assert not eleven.looks_like_voice_id("Rachel")
