"""El contador de preguntas del Akinator dev con transcripciones como las que da el motor.

El motor llama a ``on_assistant_text`` con el texto **acumulado** de la frase en curso por
cada trozo que llega (``final=False``, ya limpio con ``clean_transcript``) y, al cerrarse la
frase, una vez más con la frase entera (``final=True``). Aquí se reproduce eso trozo a trozo.
"""

from __future__ import annotations

import pytest

from sonia.games.akinator.questions import (
    QuestionCounter,
    QuestionUpdate,
    extract_questions,
    is_game_question,
    is_giving_up,
)
from sonia.live.engine import clean_transcript


def sentence(*deltas: str, close: bool = True) -> list[tuple[str, bool]]:
    """Las llamadas que haría el motor para una frase que llega en estos trozos."""
    parts: list[str] = []
    calls: list[tuple[str, bool]] = []
    for delta in deltas:
        parts.append(delta)
        calls.append((clean_transcript("".join(parts)), False))
    if close:
        calls.append((clean_transcript("".join(parts)), True))
    return calls


def run(counter: QuestionCounter, *sentences: list[tuple[str, bool]]) -> list[QuestionUpdate]:
    """Pasa las frases por el contador y devuelve solo los cambios."""
    changes: list[QuestionUpdate] = []
    for calls in sentences:
        for text, final in calls:
            update = counter.feed(text, final=final)
            if update is not None:
                changes.append(update)
    return changes


# Frases tal como las suelta el modelo, en trozos de palabras.
FIRST = sentence(
    "¡Va", "mos", "! ", "Primera", " pregunta", ":", " ¿", "Es", " un", " lenguaje", "?"
)
SECOND = sentence("¡Ajá", ", ", "entonces", " es", " un", " lenguaje", ".", " ¿", "Se", " usa", "?")
THIRD = sentence("Mmm", "...", " ¿", "Lo", " creó", " Google", "?")


# ---------------------------------------------------------------------------
# Sacar las preguntas de un texto
# ---------------------------------------------------------------------------


def test_extrae_las_preguntas_completas_con_su_apertura() -> None:
    text = "¡Ajá! Entonces es un lenguaje. ¿Se usa para móviles? Y dime, ¿lo creó Google?"
    assert extract_questions(text) == ["¿Se usa para móviles?", "¿lo creó Google?"]


def test_una_pregunta_sin_cerrar_no_existe_todavia() -> None:
    assert extract_questions("Vale. ¿Es un lenguaje de progr") == []
    assert extract_questions("¿Es un lenguaje? ¿Y se usa para") == ["¿Es un lenguaje?"]


def test_sin_apertura_empieza_tras_el_final_de_la_frase_anterior() -> None:
    assert extract_questions("Vale. Y es de Google?") == ["Y es de Google?"]
    assert extract_questions("Es de Google?") == ["Es de Google?"]


def test_una_pregunta_con_decimales_no_se_parte() -> None:
    assert extract_questions("¿Salió en la versión 3.5 de Python?") == [
        "¿Salió en la versión 3.5 de Python?"
    ]


@pytest.mark.parametrize(
    "question",
    ["¿Listo?", "¿Verdad?", "¿Sí?", "¿No?", "¿Cómo?", "¿Estás listo?", "¿Cómo dices?", "¿Me oyes?"],
)
def test_lo_que_no_es_una_pregunta_del_juego_no_cuenta(question: str) -> None:
    assert not is_game_question(question)


@pytest.mark.parametrize(
    "question",
    ["¿Es real?", "¿Es de Google?", "¿Existe hoy?", "¿Se usa para hacer apps móviles?"],
)
def test_las_cortas_pero_reales_si_cuentan(question: str) -> None:
    assert is_game_question(question)


def test_rendirse_no_es_una_pregunta_del_juego() -> None:
    for question in ("¿Qué era?", "¿En qué estabas pensando?", "¿Cuál era?", "¿Qué pensabas?"):
        assert is_giving_up(question)
        assert not is_game_question(question)
    # Una pregunta de verdad que contiene «que era» en medio sigue siendo del juego.
    assert not is_giving_up("¿Es algo que era de Microsoft?")
    assert is_game_question("¿Es algo que era de Microsoft?")


# ---------------------------------------------------------------------------
# Contar mientras llegan los trozos
# ---------------------------------------------------------------------------


def test_cuenta_una_vez_cuando_llega_el_signo_y_no_con_las_parciales() -> None:
    counter = QuestionCounter()
    changes = run(counter, FIRST)
    assert [c.count for c in changes] == [1]
    assert changes[0].text == "¿Es un lenguaje?"
    assert changes[0].is_new
    assert counter.count == 1


def test_antes_del_signo_no_hay_nada_que_contar() -> None:
    counter = QuestionCounter()
    for text, final in sentence(
        "Primera", " pregunta", ":", " ¿", "Es", " un", " lenguaje", close=False
    ):
        assert counter.feed(text, final=final) is None
    assert counter.count == 0


def test_el_cierre_de_la_frase_no_la_cuenta_otra_vez() -> None:
    counter = QuestionCounter()
    run(counter, FIRST)
    assert counter.feed(FIRST[-1][0], final=True) is None
    assert counter.count == 1


def test_cada_frase_nueva_suma() -> None:
    counter = QuestionCounter()
    changes = run(counter, FIRST, SECOND, THIRD)
    assert [c.count for c in changes] == [1, 2, 3]
    assert counter.text == "¿Lo creó Google?"


def test_repetir_la_misma_pregunta_en_otra_frase_no_suma() -> None:
    counter = QuestionCounter()
    repeat = sentence("Perdona", ", ", "te", " repito", ":", " ¿", "ES", " un", " lenguaje", "?")
    changes = run(counter, FIRST, repeat)
    assert [c.count for c in changes] == [1]


def test_la_misma_pregunta_con_otra_forma_de_escribirla_es_la_misma() -> None:
    counter = QuestionCounter()
    run(counter, FIRST)
    assert counter.feed("¿es un LENGUAJE?", final=False) is None
    assert counter.feed("¡Es un lenguaje?", final=False) is None
    assert counter.count == 1


def test_dos_preguntas_en_la_misma_frase_cuentan_una_y_se_queda_la_ultima() -> None:
    counter = QuestionCounter()
    calls = sentence(
        "¿", "Es", " un", " lenguaje", "?", " ¿", "O", " es", " una", " herramienta", "?"
    )
    changes = run(counter, calls)
    assert counter.count == 1
    assert [c.is_new for c in changes] == [True, False]
    assert changes[-1].text == "¿O es una herramienta?"


def test_un_verdad_en_la_misma_frase_no_cuenta() -> None:
    counter = QuestionCounter()
    calls = sentence(
        "Entonces", " es", " de", " Google", ",", " ¿", "verdad", "?", " ¿", "Es", " gratis", "?"
    )
    run(counter, calls)
    assert counter.count == 1
    assert counter.text == "¿Es gratis?"


def test_sin_el_cierre_de_la_frase_la_siguiente_se_reconoce_porque_no_continua() -> None:
    counter = QuestionCounter()
    changes = run(
        counter,
        sentence("¿", "Es", " un", " lenguaje", "?", close=False),
        sentence("Vale", ".", " ¿", "Lo", " creó", " Google", "?", close=False),
        sentence("¿", "Es", " gratis", "?", close=False),
    )
    assert [c.count for c in changes] == [1, 2, 3]


def test_el_texto_que_se_acorta_al_limpiar_una_marca_no_cuenta_dos_veces() -> None:
    # «[laugh]» sale limpio de la transcripción: mientras llega la marca el texto se acorta.
    counter = QuestionCounter()
    calls = sentence("¿", "Es", " un", " lenguaje", "?", " [", "lau", "gh", "]", close=True)
    changes = run(counter, calls)
    assert [c.count for c in changes] == [1]
    assert counter.count == 1


def test_un_ruido_de_sonia_con_marcas_no_rompe_la_pregunta() -> None:
    counter = QuestionCounter()
    calls = sentence(
        "[", "laugh", "]", " Vaya", ",", " ¿", "Es", " [", "sigh", "]", " de", " Google", "?"
    )
    changes = run(counter, calls)
    assert counter.count == 1
    assert changes[0].text == "¿Es de Google?"


def test_el_nombre_de_sonia_se_escribe_con_doble_n_en_lo_que_se_ve() -> None:
    counter = QuestionCounter()
    changes = run(counter, sentence("¿", "Es", " algo", " que", " Sonia", " conoce", "?"))
    assert changes[0].text == "¿Es algo que Sonnia conoce?"


def test_veinte_preguntas_seguidas_cuentan_veinte() -> None:
    counter = QuestionCounter()
    questions = [f"¿Es la cosa número {n} de la lista?" for n in range(1, 21)]
    for question in questions:
        words = question.split(" ")
        deltas = [words[0], *(f" {word}" for word in words[1:])]
        run(counter, sentence(*deltas))
    assert counter.count == 20


def test_sin_texto_o_sin_preguntas_no_hay_cambios() -> None:
    counter = QuestionCounter()
    assert counter.feed("") is None
    assert counter.feed("Vale, sigamos con lo siguiente.", final=True) is None
    assert counter.count == 0 and counter.text == ""


def test_una_pregunta_que_se_repite_despues_de_otra_no_vuelve_a_contar() -> None:
    counter = QuestionCounter()
    run(counter, FIRST, SECOND)
    run(counter, sentence("¿", "Es", " un", " lenguaje", "?"))
    assert counter.count == 2


def test_el_signo_que_llega_en_la_frase_siguiente_cierra_la_pregunta() -> None:
    # El motor corta las frases por el silencio del audio, y el texto no va pegado a él: la
    # pregunta puede quedar abierta al final de una frase y su «?» abrir la siguiente.
    counter = QuestionCounter()
    first = sentence("¡Ajá", "! ", "¿", "Es", " un", " lenguaje", " de", " programación")
    second = sentence("?", " Vale", ".", " Mmm", "...")
    changes = run(counter, first, second)
    assert [c.count for c in changes] == [1]
    assert counter.text == "¿Es un lenguaje de programación?"
    # La que viene después sigue contando con normalidad.
    run(counter, sentence("¿", "Lo", " creó", " Google", "?"))
    assert counter.count == 2


def test_una_pregunta_partida_entre_dos_frases_se_junta_entera() -> None:
    # El motor cortó la frase a mitad de la pregunta y la siguiente la termina sin su «¿»
    # (con GPT-Live real salía «principalmente en el navegador?» en la pantalla).
    counter = QuestionCounter()
    first = sentence("Mmm", ". ", "¿", "Corre")
    second = sentence("principalmente", " en", " el", " navegador", "?", " Dime", ".")
    changes = run(counter, first, second)
    assert [c.count for c in changes] == [1]
    assert counter.text == "¿Corre principalmente en el navegador?"
    # La que viene después sigue contando con normalidad.
    run(counter, sentence("¿", "Lo", " creó", " Google", "?"))
    assert counter.count == 2


def test_una_frase_nueva_no_se_junta_con_la_pregunta_abierta_de_antes() -> None:
    # Empieza en mayúscula (o lleva su propio «¿»): no es la continuación.
    counter = QuestionCounter()
    run(counter, sentence("¿", "Es"))
    run(counter, sentence("Perdona", ", ", "¿", "es", " de", " pago", "?"))
    assert counter.count == 1 and counter.text == "¿es de pago?"
    counter = QuestionCounter()
    run(counter, sentence("¿", "Es"))
    run(counter, sentence("Entonces", " es", " de", " pago", "?"))
    assert counter.count == 1 and counter.text == "Entonces es de pago?"


def test_el_signo_tardio_solo_cierra_la_pregunta_de_la_frase_anterior() -> None:
    counter = QuestionCounter()
    run(counter, sentence("¿", "Es", " de", " Google", "?"))
    assert counter.count == 1
    # Una frase que empieza por «?» sin pregunta abierta antes no cuenta nada.
    run(counter, sentence("?", " Eso", " era", " todo", "."))
    assert counter.count == 1
    # Y una frase normal en medio olvida la pregunta abierta de antes.
    counter = QuestionCounter()
    run(counter, sentence("¿", "Es", " de", " Google"))
    run(counter, sentence("Vale", ", ", "sigamos", "."))
    run(counter, sentence("?", " Eso", " era", "."))
    assert counter.count == 0


def test_la_pregunta_abierta_se_reconoce() -> None:
    from sonia.games.akinator.questions import open_question

    assert open_question("Vale. ¿Es un lenguaje") == "¿Es un lenguaje"
    assert open_question("Vale. ¿Es un lenguaje? Sí") == ""
    assert open_question("Vale, sigamos") == ""
    assert open_question("¿Una? ¿Otra") == "¿Otra"


def test_el_contador_aguanta_cualquier_transcripcion_sin_lanzar_ni_bajar() -> None:
    import random

    rng = random.Random(7)
    vocabulary = [
        "¿", "?", ".", "!", "¡", "es", "un", "lenguaje", "de", "Google", "Kotlin", "[", "]",
        "[laugh]", "Sonia", "…", ",", ":", "listo", "qué", "era", "\n", "  ",
    ]  # fmt: skip
    for _ in range(300):
        counter = QuestionCounter()
        previous = 0
        for _ in range(rng.randint(1, 8)):
            parts: list[str] = []
            for _ in range(rng.randint(1, 14)):
                parts.append(rng.choice(vocabulary) + rng.choice(["", " ", " "]))
                text = clean_transcript("".join(parts))
                counter.feed(text, final=False)
                assert counter.count >= previous
                previous = counter.count
            counter.feed(clean_transcript("".join(parts)), final=rng.random() < 0.8)
            assert counter.count >= previous
            previous = counter.count
