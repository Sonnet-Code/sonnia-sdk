"""Glosario: carga, forma fonética y corrección de transcripciones."""

from __future__ import annotations

from pathlib import Path

from sonia.glossary import GLOSSARY_FILENAME, correct_transcript, load_glossary, phonetic_key

NAMES = ["Alexander Vegazo", "Sonnet Code", "Sonia", "Juana Casique", "GDG Santo Domingo"]


def test_load_glossary_toma_el_nombre_antes_de_los_dos_puntos(tmp_path: Path) -> None:
    (tmp_path / GLOSSARY_FILENAME).write_text(
        "# Glosario\n\nTexto libre.\n\n- Alexander Vegazo: CEO.\n- Sonia\n* Sonnet Code: empresa\n- Sonia\n",
        encoding="utf-8",
    )
    assert load_glossary(tmp_path) == ["Alexander Vegazo", "Sonia", "Sonnet Code"]
    assert load_glossary(tmp_path / "no-existe") == []


def test_phonetic_key_unifica_confusiones_del_espanol() -> None:
    assert phonetic_key("Vegazo") == phonetic_key("Begaso") == phonetic_key("begasso")
    assert phonetic_key("Henríquez") == phonetic_key("enriques")
    assert phonetic_key("Casique") == phonetic_key("Cazique")
    assert phonetic_key("Sonia") != phonetic_key("Sandra")


def test_corrige_nombre_completo_mal_transcrito() -> None:
    text, changes = correct_transcript("Hola, quiero saber más sobre Alexander Begasov.", NAMES)
    assert text == "Hola, quiero saber más sobre Alexander Vegazo."
    assert changes == [("Alexander Begasov", "Alexander Vegazo")]


def test_corrige_apellido_suelto_y_normaliza_grafia() -> None:
    text, changes = correct_transcript("quién es begaso y qué es sonet code", NAMES)
    assert text == "quién es Vegazo y qué es Sonnet Code"
    # "begaso" suena igual que Vegazo: se normaliza sin contarlo como corrección.
    assert changes == []


def test_no_toca_palabras_que_no_se_parecen() -> None:
    text, changes = correct_transcript("me llamo Sandra y vengo de la plaza", NAMES)
    assert text == "me llamo Sandra y vengo de la plaza"
    assert changes == []


def test_no_desplaza_la_ventana_sobre_nombres_largos() -> None:
    names = ["Biblioteca Nacional Pedro Henríquez Ureña"]
    text, _ = correct_transcript("qué es la biblioteca nacional pedro enríquez ureña", names)
    assert text == "qué es la Biblioteca Nacional Pedro Henríquez Ureña"


def test_texto_vacio_o_sin_glosario() -> None:
    assert correct_transcript("", NAMES) == ("", [])
    assert correct_transcript("hola", []) == ("hola", [])
