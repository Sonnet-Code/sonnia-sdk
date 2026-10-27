"""Guion de Sonnia Video: lectura, validación en español, opciones y la regla del nombre."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from sonia.video.errors import VideoError
from sonia.video.script import (
    EXAMPLE,
    Overrides,
    apply_overrides,
    check_files,
    load_script,
    parse_script,
    phrase_texts,
    quality,
    scene_message,
    script_from_text,
    slug,
    split_sentences,
    spoken,
    title_of,
    tts_text,
    video_size,
    written,
)


def script(**data: object) -> object:
    return parse_script({"frase": [{"texto": "Hola."}], **data})


def test_el_ejemplo_es_un_guion_valido_con_todas_las_tablas() -> None:
    data = tomllib.loads(EXAMPLE)
    loaded = parse_script(data)
    assert loaded.title == "gracias-devfest"
    assert loaded.voice.engine == "gemini"
    assert loaded.video.quality == "alta"
    assert [p.gesture for p in loaded.phrases] == ["waveCalm", "", ""]
    assert loaded.phrases[1].pause == pytest.approx(0.3)
    # Todas las opciones de cada tabla salen en el ejemplo (activas o comentadas).
    for key in ("estabilidad", "similitud", "velocidad", "archivo", "reel", "en =", "espejo"):
        assert key in EXAMPLE
    assert set(data["escena"]) == set(loaded.scene.model_dump(by_alias=True))
    assert set(data["video"]) | {"reel"} == set(loaded.video.model_dump(by_alias=True))
    # Sin HUD del stand: ni logo, ni QR, ni subtítulos en pantalla.
    for gone in ("logo =", "qr =", "subtitulos ="):
        assert gone not in EXAMPLE


def test_errores_claros_en_espanol() -> None:
    with pytest.raises(VideoError) as info:
        parse_script(
            {
                "frase": [{"texto": "  "}],
                "video": {"formato": "1081x1920", "fps": "rápido"},
                "escena": {"luz": "neón", "colr": "#fff", "color": "azul"},
                "voz": {"motor": "elevenlabs", "estilo": "alegre"},
            },
            source="guion.toml",
        )
    text = str(info.value)
    assert "guion.toml" in text
    assert "frase → 1 → texto" in text
    assert "pares" in text  # 1081 no vale para H.264
    assert "fps: tiene que ser un número entero" in text
    assert "luz: valor no válido; vale stand, estudio, suave, calida, fria o dramatica" in text
    assert "colr: opción desconocida" in text
    assert "«azul» no es un color" in text
    assert "con ElevenLabs, estilo es un número de 0 a 1" in text


def test_sin_frases_no_vale() -> None:
    with pytest.raises(VideoError, match="frase: falta"):
        parse_script({})


def test_tildes_y_mayusculas_en_las_opciones() -> None:
    loaded = parse_script(
        {
            "frase": [{"texto": "Hola."}],
            "escena": {"luz": "Cálida", "encuadre": "Primer plano", "emocion": "NEUTRA"},
            "video": {"formato": "Cuadrado", "calidad": "Borrador"},
        }
    )
    message = scene_message(loaded.scene)
    assert message["lighting"]["preset"] == "warm"
    assert message["framing"]["preset"] == "close"
    assert message["emotion"] == "neutral"
    assert video_size(loaded.video) == (1080, 1080)
    assert quality(loaded.video).supersample == 1


def test_traduccion_al_contrato() -> None:
    loaded = parse_script(
        {
            "frase": [{"texto": "Hola."}],
            "escena": {
                "fondo": "degradado",
                "color": "#abc",
                "color2": "0b1322",
                "luz": "dramatica",
                "luz_intensidad": 1.2,
                "luz_ambiente": 0.5,
                "contraluz": "#7fb2ff",
                "contraluz_intensidad": 2.0,
                "exposicion": -0.5,
                "encuadre": "americano",
                "zoom": 1.3,
                "desplazar_x": 0.1,
                "desplazar_y": -0.2,
                "camiseta": "lisa",
                "gorra": True,
                "particulas": False,
            },
            "video": {"formato": "horizontal"},
        }
    )
    assert scene_message(loaded.scene) == {
        "background": {"mode": "gradient", "color": "#ABC", "color2": "#0B1322", "image": ""},
        "particles": False,
        "lighting": {
            "preset": "dramatic",
            "key": 1.2,
            "ambient": 0.5,
            "rim_color": "#7FB2FF",
            "rim_intensity": 2.0,
            "exposure": -0.5,
        },
        "framing": {"preset": "cowboy", "zoom": 1.3, "offset_x": 0.1, "offset_y": -0.2},
        "outfit": "plain",
        "cap": True,
        "emotion": "joy",
    }
    assert video_size(loaded.video) == (1920, 1080)


def test_sin_contraluz_la_intensidad_va_a_cero() -> None:
    lighting = scene_message(parse_script({"frase": [{"texto": "Hola."}]}).scene)["lighting"]
    assert lighting["rim_color"] == ""
    assert lighting["rim_intensity"] == 0.0


def test_calidades() -> None:
    def q(name: str) -> tuple[int, int, int, str]:
        v = quality(parse_script({"frase": [{"texto": "a"}], "video": {"calidad": name}}).video)
        return v.supersample, v.subframes, v.crf, v.preset

    assert q("borrador") == (1, 1, 23, "veryfast")
    assert q("normal") == (2, 1, 18, "medium")
    assert q("alta") == (2, 4, 14, "slow")


def test_formato_a_medida() -> None:
    loaded = parse_script({"frase": [{"texto": "a"}], "video": {"formato": "720 x 1280"}})
    assert video_size(loaded.video) == (720, 1280)


def test_nombre_escrito_y_dicho() -> None:
    assert written("Hola, soy Sonia. SONIA. sonía") == "Hola, soy Sonnia. SONNIA. sonnia"
    assert spoken("Soy Sonnia, sonnia, SONNIA") == "Soy Sonia, sonia, SONIA"
    # «Sonoridad» o «Sonias» no son el nombre.
    assert written("Sonoridad") == "Sonoridad"


def test_frases_con_pronunciacion_y_nombre() -> None:
    loaded = parse_script(
        {
            "pronunciacion": {
                "sonnetcode.com": "sónet code punto com",
                "Sonnet Code": "Sónet Coud",
            },
            "frase": [
                {"texto": "Soy Sonia, de Sonnet Code: entra en sonnetcode.com, ¿vale?"},
                {"texto": "Hasta pronto — Sonnia"},
            ],
        }
    )
    first, second = phrase_texts(loaded)
    assert first.display == "Soy Sonnia, de Sonnet Code: entra en sonnetcode.com, ¿vale?"
    assert first.spoken == "Soy Sonia, de Sónet Coud: entra en sónet code punto com, ¿vale?"
    displays = [u.display for u in first.units]
    assert displays == [
        "Soy",
        "Sonnia,",
        "de",
        "Sonnet Code:",
        "entra",
        "en",
        "sonnetcode.com,",
        "¿vale?",
    ]
    by_display = {u.display: u.spoken for u in first.units}
    assert by_display["Sonnia,"] == ("Sonia,",)
    assert by_display["Sonnet Code:"] == ("Sónet", "Coud:")
    assert by_display["sonnetcode.com,"] == ("sónet", "code", "punto", "com,")
    # La raya no se dice; sin punto final, al TTS se le añade uno para que haga la pausa.
    assert [u.spoken for u in second.units][2] == ()
    assert second.spoken == "Hasta pronto — Sonia."
    assert second.display == "Hasta pronto — Sonnia"
    assert tts_text([first, second]) == first.spoken + " " + second.spoken


def test_pronunciacion_sin_distinguir_mayusculas_y_solo_palabras_enteras() -> None:
    loaded = parse_script(
        {"pronunciacion": {"IA": "i a"}, "frase": [{"texto": "La ia y la IAgenda."}]}
    )
    (text,) = phrase_texts(loaded)
    assert text.spoken == "La i a y la IAgenda."


def test_frases_de_un_texto_suelto() -> None:
    assert split_sentences("¡Hola! Soy Sonia. ¿Me ves en sonnetcode.com? Nos vemos… ¡adiós!") == [
        "¡Hola!",
        "Soy Sonia.",
        "¿Me ves en sonnetcode.com?",
        "Nos vemos…",
        "¡adiós!",
    ]
    assert split_sentences("Una sola frase sin punto") == ["Una sola frase sin punto"]
    assert split_sentences("«Dijo hola.» Y se fue.") == ["«Dijo hola.»", "Y se fue."]
    loaded = script_from_text("Hola. Adiós.")
    assert [p.text for p in loaded.phrases] == ["Hola.", "Adiós."]
    with pytest.raises(VideoError):
        script_from_text("   ")


def test_titulo_y_nombre_de_archivo() -> None:
    assert slug("¡Gracias, DevFest 2026!") == "gracias-devfest-2026"
    assert title_of(parse_script({"titulo": "Mi vídeo", "frase": [{"texto": "a"}]})) == "mi-video"
    assert title_of(script_from_text("¡Hola! Soy Sonia, la del stand de Sonnet Code.")) == (
        "hola-soy-sonnia-la-del-stand"
    )
    assert title_of(script_from_text("¿?")) == "sonnia"


def test_flags_pisan_el_guion() -> None:
    base = parse_script(tomllib.loads(EXAMPLE))
    changed = apply_overrides(
        base,
        Overrides(
            voice="elevenlabs:Rachel",
            format="cuadrado",
            fps=24,
            quality="borrador",
            emotion="neutra",
            light="fria",
            background="#000000",
            framing="cuerpo",
            no_gestures=True,
            title="otro",
        ),
    )
    assert changed.voice.engine == "elevenlabs"
    assert changed.voice.voice == "Rachel"
    # Lo propio de Gemini no pasa a ElevenLabs.
    assert changed.voice.model == ""
    assert changed.video.format == "cuadrado"
    assert changed.video.fps == 24
    assert changed.video.quality == "borrador"
    assert changed.scene.emotion == "neutra"
    assert changed.scene.light == "fria"
    assert changed.scene.background == "color"
    assert changed.scene.color == "#000000"
    assert changed.scene.framing == "cuerpo"
    assert changed.gestures.mode == "ninguno"
    assert changed.title == "otro"
    # El guion original no cambia.
    assert base.voice.engine == "gemini"


def test_flag_de_voz_sin_motor_y_de_archivo(tmp_path: Path) -> None:
    base = parse_script(tomllib.loads(EXAMPLE))
    assert apply_overrides(base, Overrides(voice="Leda")).voice.voice == "Leda"
    wav = tmp_path / "voz.wav"
    changed = apply_overrides(base, Overrides(voice=f"archivo:{wav}"))
    assert changed.voice.engine == "archivo"
    assert changed.voice.file == str(wav.resolve())
    with pytest.raises(VideoError, match="No existe el audio"):
        check_files(changed)
    image = tmp_path / "fondo.png"
    image.write_bytes(b"png")
    with_image = apply_overrides(base, Overrides(background=str(image)))
    assert with_image.scene.background == "imagen"
    check_files(with_image)


def test_rutas_relativas_al_guion(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    path = tmp_path / "sub" / "guion.toml"
    path.write_text(
        '[voz]\nmotor = "archivo"\narchivo = "voz.mp3"\n'
        '[escena]\nfondo = "imagen"\nimagen = "../fondo.jpg"\n'
        '[[frase]]\ntexto = "Hola."\n',
        encoding="utf-8",
    )
    loaded = load_script(path)
    assert loaded.voice.file == str((tmp_path / "sub" / "voz.mp3").resolve())
    assert loaded.scene.image == str((tmp_path / "fondo.jpg").resolve())


def test_errores_de_lectura(tmp_path: Path) -> None:
    with pytest.raises(VideoError, match="No existe el guion"):
        load_script(tmp_path / "no.toml")
    bad = tmp_path / "malo.toml"
    bad.write_text("titulo = \n", encoding="utf-8")
    with pytest.raises(VideoError, match="no es un TOML válido"):
        load_script(bad)


def test_motor_archivo_sin_archivo_y_fondo_imagen_sin_imagen() -> None:
    with pytest.raises(VideoError, match='hace falta archivo = "voz.wav"'):
        parse_script({"voz": {"motor": "archivo"}, "frase": [{"texto": "a"}]})
    with pytest.raises(VideoError, match='hace falta imagen = "fondo.png"'):
        parse_script({"escena": {"fondo": "imagen"}, "frase": [{"texto": "a"}]})


def test_estilo_por_motor() -> None:
    eleven = parse_script(
        {"voz": {"motor": "elevenlabs", "estilo": "0,4"}, "frase": [{"texto": "a"}]}
    )
    assert eleven.voice.style == pytest.approx(0.4)
    with pytest.raises(VideoError, match="con Gemini, estilo es un texto"):
        parse_script({"voz": {"estilo": 0.5}, "frase": [{"texto": "a"}]})
    with pytest.raises(VideoError, match="va de 0 a 1"):
        parse_script({"voz": {"motor": "elevenlabs", "estilo": 2}, "frase": [{"texto": "a"}]})


def test_sin_hud_y_fondo_transparente() -> None:
    for gone in ("logo", "qr", "subtitulos"):
        with pytest.raises(VideoError, match=f"«{gone}» ya no existe.*srt"):
            parse_script({"frase": [{"texto": "a"}], "escena": {gone: True}})
    loaded = parse_script({"frase": [{"texto": "a"}], "escena": {"fondo": "transparente"}})
    message = scene_message(loaded.scene)
    assert message["background"]["mode"] == "transparent"
    assert not {"logo", "qr", "subtitles"} & set(message)
    assert video_size(
        parse_script({"frase": [{"texto": "a"}], "video": {"formato": "4k-vertical"}}).video
    ) == (2160, 3840)


def test_reel_y_acciones(tmp_path: Path) -> None:
    with pytest.raises(VideoError, match='necesita fondo = "transparente"'):
        parse_script({"frase": [{"texto": "a"}], "video": {"reel": "x"}})
    base = parse_script({"frase": [{"texto": "a"}]})
    with_reel = apply_overrides(base, Overrides(reel=str(tmp_path / "reel")))
    assert with_reel.scene.background == "transparente"
    assert with_reel.video.reel == str((tmp_path / "reel").resolve())
    acts = parse_script(
        {
            "frase": [{"texto": "a"}],
            "accion": [
                {"gesto": "knockKnock", "en": 0.0, "espejo": True},
                {"gesto": "x", "segundo": 2},
            ],
        }
    ).actions
    assert [(a.gesture, a.at, a.mirror) for a in acts] == [
        ("knockKnock", 0.0, True),
        ("x", 2.0, False),
    ]
