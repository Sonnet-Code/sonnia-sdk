"""Tests del troceador de frases."""

from __future__ import annotations

from sonia.sentences import SentenceSplitter, clean_text


def _stream(text: str, **kwargs: object) -> list[str]:
    """Empuja el texto carácter a carácter, como llegan los deltas del modelo."""
    splitter = SentenceSplitter(**kwargs)  # type: ignore[arg-type]
    out: list[str] = []
    for char in text:
        out.extend(splitter.feed(char))
    rest = splitter.flush()
    if rest:
        out.append(rest)
    return out


# ---------------------------------------------------------------------------
# Cortes básicos
# ---------------------------------------------------------------------------


def test_corte_por_punto_en_streaming() -> None:
    assert _stream("Hola. ¿Qué tal? Bien; gracias.") == [
        "Hola.",
        "¿Qué tal?",
        "Bien;",
        "gracias.",
    ]


def test_no_corta_hasta_ver_el_espacio() -> None:
    splitter = SentenceSplitter()
    assert splitter.feed("Hola.") == []
    assert splitter.feed(" ") == ["Hola."]
    assert splitter.pending == ""


def test_flush_devuelve_el_resto_y_none_si_no_queda_nada() -> None:
    splitter = SentenceSplitter()
    assert splitter.feed("Sin puntuación final") == []
    assert splitter.flush() == "Sin puntuación final"
    assert splitter.flush() is None


def test_corte_por_salto_de_linea() -> None:
    splitter = SentenceSplitter()
    assert splitter.feed("Primera línea\nSegunda") == ["Primera línea"]
    assert splitter.flush() == "Segunda"


def test_comillas_y_parentesis_se_quedan_con_la_frase() -> None:
    assert _stream('Dijo "hola." Luego se fue.') == ['Dijo "hola."', "Luego se fue."]


# ---------------------------------------------------------------------------
# Falsos positivos
# ---------------------------------------------------------------------------


def test_no_corta_en_decimales() -> None:
    assert _stream("Mide 3.5 metros de largo.") == ["Mide 3.5 metros de largo."]


def test_no_corta_en_abreviaturas() -> None:
    assert _stream("El Sr. Pérez llegó.") == ["El Sr. Pérez llegó."]
    assert _stream("Vino la Dra. Núñez ayer.") == ["Vino la Dra. Núñez ayer."]
    assert _stream("Viene de EE.UU. y de Madrid.") == ["Viene de EE.UU. y de Madrid."]
    assert _stream("Hay muchas, p. ej. esta.") == ["Hay muchas, p. ej. esta."]


def test_puntos_suspensivos_cortan_solo_al_final() -> None:
    assert _stream("Espera... ya voy.") == ["Espera...", "ya voy."]


def test_puntos_suspensivos_parciales_no_cortan() -> None:
    splitter = SentenceSplitter()
    assert splitter.feed("Espera.") == []
    assert splitter.feed(".") == []
    assert splitter.feed(".") == []
    assert splitter.feed(" ya") == ["Espera..."]


def test_url_no_corta_en_los_dos_puntos() -> None:
    frases = _stream("Míralo en https://sonnetcode.com/es y verás.")
    assert frases == ["Míralo en sonnetcode.com/es y verás."]


# ---------------------------------------------------------------------------
# Coma
# ---------------------------------------------------------------------------


def test_coma_corta_cuando_se_acumula_mucho() -> None:
    largo = "Esta frase es bastante larga y sigue creciendo sin parar nunca"
    frases = _stream(f"{largo}, y aquí continúa.", fast_first_sentence=False)
    assert frases[0] == f"{largo},"
    assert frases[1] == "y aquí continúa."


def test_coma_no_corta_si_es_corta() -> None:
    assert _stream("Hola, qué tal.", fast_first_sentence=False) == ["Hola, qué tal."]


def test_primera_frase_corta_antes_en_la_coma() -> None:
    texto = "Claro que sí, con mucho gusto te lo explico, sin problema."
    # 40 caracteres bastan para la primera frase del turno.
    rapido = _stream(texto, comma_min_chars=60, first_sentence_comma_chars=40)
    lento = _stream(texto, comma_min_chars=60, fast_first_sentence=False)
    assert rapido[0] == "Claro que sí, con mucho gusto te lo explico,"
    assert lento[0] == "Claro que sí, con mucho gusto te lo explico, sin problema."


def test_tras_la_primera_frase_vuelve_el_umbral_normal() -> None:
    splitter = SentenceSplitter(comma_min_chars=60, first_sentence_comma_chars=10)
    assert splitter.feed("Hola de nuevo, ") == ["Hola de nuevo,"]
    assert splitter.emitted == 1
    assert splitter.feed("qué gusto verte, de verdad. ") == ["qué gusto verte, de verdad."]


def test_reset_vuelve_a_tratar_la_frase_como_la_primera() -> None:
    splitter = SentenceSplitter(first_sentence_comma_chars=10)
    splitter.feed("Hola de nuevo, ")
    splitter.reset()
    assert splitter.emitted == 0
    assert splitter.pending == ""
    assert splitter.feed("Hola otra vez, ") == ["Hola otra vez,"]


# ---------------------------------------------------------------------------
# Limpieza
# ---------------------------------------------------------------------------


def test_limpia_markdown() -> None:
    assert clean_text("**Hola** y `código` y _texto_") == "Hola y código y texto"
    assert clean_text("## Título") == "Título"
    assert clean_text("- Primero") == "Primero"
    assert clean_text("1. Primero") == "Primero"
    assert clean_text("Mira [la web](https://sonnetcode.com)") == "Mira la web"
    assert clean_text("snake_case se queda") == "snake_case se queda"


def test_limpia_emojis_y_espacios() -> None:
    assert clean_text("Hola 👋 ¿qué tal? 🎉") == "Hola ¿qué tal?"
    assert clean_text("  varios    espacios \n y saltos ") == "varios espacios y saltos"


def test_limpia_el_protocolo_de_las_urls() -> None:
    assert clean_text("Visita https://www.sonnetcode.com/es hoy") == (
        "Visita www.sonnetcode.com/es hoy"
    )


def test_las_frases_salen_limpias() -> None:
    splitter = SentenceSplitter()
    assert splitter.feed("**Hola** 👋. Segunda ") == ["Hola."]
    assert splitter.flush() == "Segunda"


def test_lineas_vacias_no_producen_frases() -> None:
    splitter = SentenceSplitter()
    assert splitter.feed("\n\n\n") == []
    assert splitter.flush() is None
    assert splitter.emitted == 0


# ---------------------------------------------------------------------------
# Frases cortas unidas (min_chars)
# ---------------------------------------------------------------------------


def test_min_chars_une_las_frases_cortas_menos_la_primera() -> None:
    texto = (
        "Hola. Soy Sonia. Estoy en el stand de Sonnet Code. Pregúntame lo que quieras. ¡Anímate!"
    )
    assert _stream(texto, min_chars=40) == [
        "Hola.",
        "Soy Sonia. Estoy en el stand de Sonnet Code.",
        "Pregúntame lo que quieras. ¡Anímate!",
    ]


def test_min_chars_cero_mantiene_el_corte_por_frase() -> None:
    assert _stream("Hola. Soy Sonia. Adiós.", min_chars=0) == ["Hola.", "Soy Sonia.", "Adiós."]


def test_min_chars_respeta_el_salto_de_linea_largo() -> None:
    texto = "Primera.\nSegunda corta.\nTercera bastante más larga que las otras.\nCuarta."
    out = _stream(texto, min_chars=30)
    assert out[0] == "Primera."
    assert out[1] == "Segunda corta. Tercera bastante más larga que las otras."
    assert out[2] == "Cuarta."


def test_hurry_corta_sin_esperar_min_chars() -> None:
    splitter = SentenceSplitter(min_chars=80, comma_min_chars=120, first_sentence_comma_chars=10)
    assert splitter.feed("Primera. ") == ["Primera."]
    # Sin prisa, una frase corta se retiene.
    assert splitter.feed("Segunda corta. ") == []
    # Con prisa sale al momento lo retenido, y también corta por coma temprana.
    assert splitter.feed("Y ahora una coma, aquí. ", hurry=True) == [
        "Segunda corta.",
        "Y ahora una coma,",
        "aquí.",
    ]
