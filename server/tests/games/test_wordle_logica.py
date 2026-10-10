"""Las reglas del Wordle sin pantalla: normalizar, colorear (con letras repetidas), el teclado,
el resumen y el banco de palabras (``sonia/games/wordle/logic.py`` y ``bank.py``)."""

from __future__ import annotations

import itertools
import random
import re
from pathlib import Path

import pytest

from sonia.games.wordle.bank import (
    HINT_MAX_CHARS,
    MIN_WORDS,
    WORDS,
    WordleWord,
    parse_words,
    pick_word,
)
from sonia.games.wordle.logic import (
    GRAY,
    GREEN,
    WORD_LENGTH,
    YELLOW,
    check_word,
    describe_marks,
    normalize_text,
    score_guess,
    used_letters,
)
from tests.games.fakes import brands_in, game_settings

BANK_FILE = game_settings().games_dir / "wordle" / "palabras.md"

# ---------------------------------------------------------------------------
# Colorear: la regla del Wordle de verdad
# ---------------------------------------------------------------------------


def reference_score(guess: str, answer: str) -> str:
    """La misma regla escrita de otra forma (por letra, cuántas amarillas caben), para cruzarla."""
    marks = [GRAY] * len(guess)
    for letter in set(guess):
        green = [i for i in range(len(guess)) if guess[i] == letter == answer[i]]
        for i in green:
            marks[i] = GREEN
        free_in_answer = answer.count(letter) - len(green)
        loose = [i for i in range(len(guess)) if guess[i] == letter and answer[i] != letter]
        for i in loose[:free_in_answer]:
            marks[i] = YELLOW
    return "".join(marks)


@pytest.mark.parametrize(
    ("guess", "answer", "marks"),
    [
        # Lo básico.
        ("REACT", "REACT", "ggggg"),
        ("LINUX", "KAFKA", "xxxxx"),
        ("LINUX", "CLOUD", "yxxgx"),
        # Una letra repetida en el intento y una sola en la palabra: solo la primera (de
        # izquierda a derecha) es amarilla; la segunda, gris.
        ("SPEED", "ABIDE", "xxyxy"),
        # Y si una de las repetidas está en su sitio, esa es la verde y la otra se queda gris
        # aunque vaya antes (sin la pasada de verdes saldría amarilla).
        ("EERIE", "REACT", "xgyxx"),
        ("OVOID", "ABOUT", "xxgxx"),
        # Al revés: dos en la palabra y una en el intento (amarilla), y dos en el intento
        # contra dos en la palabra (una verde y una amarilla).
        ("LLAMA", "SCALA", "yxgxg"),
        ("LLAMA", "CHILL", "yyxxx"),
        ("AAAAA", "SCALA", "xxgxg"),
        ("LAAAA", "SCALA", "yxgxg"),
        # El ejemplo de los manuales del Wordle: BOBBY contra ABBEY.
        ("BOBBY", "ABBEY", "yxgxg"),
        # Tres iguales en la palabra y el intento las agota de una en una.
        ("EEEXX", "XEEEX", "yggyg"),
    ],
)
def test_score_guess_con_letras_repetidas(guess: str, answer: str, marks: str) -> None:
    assert score_guess(guess, answer) == marks
    assert reference_score(guess, answer) == marks


@pytest.mark.parametrize("alphabet", ["AB", "ABC"])
def test_score_guess_coincide_con_la_formulacion_de_referencia(alphabet: str) -> None:
    # Con pocas letras todo se repite: se prueban TODOS los pares posibles.
    words = ["".join(w) for w in itertools.product(alphabet, repeat=WORD_LENGTH)]
    for guess in words:
        for answer in words:
            assert score_guess(guess, answer) == reference_score(guess, answer)


def test_score_guess_con_palabras_reales_nunca_pasa_de_las_letras_que_hay() -> None:
    entries = parse_words(BANK_FILE.read_text(encoding="utf-8")).entries
    rng = random.Random(7)
    for _ in range(2000):
        guess, answer = rng.choice(entries).word, rng.choice(entries).word
        marks = score_guess(guess, answer)
        assert len(marks) == WORD_LENGTH
        for letter in set(guess):
            # Las verdes y las amarillas de una letra no pueden pasar de las que tiene la palabra.
            shown = sum(1 for g, m in zip(guess, marks, strict=True) if g == letter and m != GRAY)
            assert shown <= answer.count(letter)
        assert (marks == GREEN * WORD_LENGTH) == (guess == answer)


def test_score_guess_no_acepta_longitudes_distintas() -> None:
    with pytest.raises(ValueError, match="no tienen las mismas letras"):
        score_guess("LINUX", "WEB")


# ---------------------------------------------------------------------------
# Entender la palabra
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "word"),
    [
        ("kafka", "KAFKA"),
        ("Linux", "LINUX"),
        ("Linux.", "LINUX"),
        ("  react  ", "REACT"),
        # Sin tildes ni diéresis, y la Ñ como N.
        ("PÍXEL", "PIXEL"),
        ("píxel", "PIXEL"),
        ("Ñandú", "NANDU"),
        ("güero", "GUERO"),
        ("nunca", "NUNCA"),
        # Si la deletrean.
        ("l i n u x", "LINUX"),
        ("L-I-N-U-X", "LINUX"),
        ("l, i, n, u, x", "LINUX"),
        ("L.I.N.U.X.", "LINUX"),
    ],
)
def test_se_normaliza_la_palabra(raw: str, word: str) -> None:
    checked = check_word(raw)
    assert checked.ok and checked.word == word and checked.shown == word and not checked.reason


def test_ñ_y_n_son_la_misma_letra() -> None:
    assert check_word("PEÑAS").word == check_word("PENAS").word == "PENAS"
    assert normalize_text("ÑAndÚ") == "NANDU"


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("web", "length"),
        ("Kubernetes", "length"),
        ("react native", "length"),
        ("a", "length"),
        ("ab1cd", "chars"),
        ("12345", "chars"),
        ("l!n+x", "chars"),
        ("ΑΒΓΔΕ", "chars"),  # griego: son letras, pero no las del alfabeto
        ("😀😀😀😀😀", "chars"),
        ("", "empty"),
        ("   ", "empty"),
        ("...", "empty"),
        ("no_lo_dijo", "empty"),
        (None, "empty"),
        (12345, "empty"),
    ],
)
def test_lo_que_no_vale_dice_por_que(raw: object, reason: str) -> None:
    checked = check_word(raw)
    assert not checked.ok and checked.reason == reason


def test_lo_que_se_enseña_al_sacudir_la_fila_cabe_en_ella() -> None:
    assert check_word("Kubernetes").shown == "KUBER"
    assert check_word("web").shown == "WEB"
    assert check_word("ab1cd").shown == "ABCD"
    assert check_word("").shown == ""


# ---------------------------------------------------------------------------
# El teclado y el resumen
# ---------------------------------------------------------------------------


def test_las_letras_usadas_guardan_el_mejor_color() -> None:
    rows = [("CLOUD", "xyyxx"), ("LINUX", "gyxxg")]
    # L: amarilla en el primero y verde en el segundo -> verde; I y U, grises o amarillas.
    assert used_letters(rows) == {"g": "LX", "y": "IO", "x": "CDNU"}
    # Una letra va en un solo grupo.
    groups = used_letters(rows)
    letters = "".join(groups.values())
    assert len(letters) == len(set(letters))
    assert used_letters([]) == {"g": "", "y": "", "x": ""}


def test_una_letra_gris_por_repetida_no_baja_a_la_amarilla() -> None:
    # SPEED contra ABIDE: la primera E es amarilla y la segunda, gris: la E queda amarilla.
    assert used_letters([("SPEED", "xxyxy")]) == {"g": "", "y": "DE", "x": "PS"}


def test_el_resumen_cuenta_verdes_amarillas_y_grises() -> None:
    text = describe_marks("LINUX", "gyxxg")
    assert "bien colocadas (verdes): L (primera) y X (quinta)" in text
    assert "en otro sitio (amarillas): I" in text
    assert "no están (grises): N y U" in text
    assert "Ojo" not in text


def test_el_resumen_avisa_cuando_una_letra_no_se_repite() -> None:
    # Una sola L en la palabra: la ficha gris de la segunda no quiere decir que no exista.
    text = describe_marks("LLAMA", "yxgxg")
    assert "A (tercera y quinta)" in text
    assert "en otro sitio (amarillas): L" in text
    assert "no están (grises): M" in text
    assert "Ojo: de la L solo hay una en la palabra" in text
    # Y con una verde: la E de la segunda posición está, la primera no se repite.
    text = describe_marks("EERIE", "xgyxx")
    assert "E (segunda)" in text and "de la E solo hay una en la palabra" in text
    assert "no están (grises): I" in text


def test_el_resumen_de_dos_amarillas_iguales() -> None:
    text = describe_marks("LLAMA", "yyxxx")
    assert "L (dos veces)" in text
    assert "no están (grises): A y M" in text


def test_el_resumen_nunca_nombra_el_stack() -> None:
    rng = random.Random(3)
    for _ in range(300):
        guess = "".join(rng.choice("ABCDE") for _ in range(5))
        answer = "".join(rng.choice("ABCDE") for _ in range(5))
        assert not brands_in(describe_marks(guess, score_guess(guess, answer)))


# ---------------------------------------------------------------------------
# El banco
# ---------------------------------------------------------------------------

GOOD = """\
<!-- Comentario: se ignora. -->
# Título

## LINUX
> Sistema operativo libre con un pingüino de mascota.

## píxel
> El puntito más pequeño de una pantalla.

## KAFKA
Sin el signo de cita, la línea también vale como pista.
"""


def test_el_banco_bien_formado_se_lee_entero() -> None:
    parsed = parse_words(GOOD)
    assert parsed.warnings == []
    assert parsed.entries == [
        WordleWord("LINUX", "Sistema operativo libre con un pingüino de mascota."),
        WordleWord("PIXEL", "El puntito más pequeño de una pantalla."),
        WordleWord("KAFKA", "Sin el signo de cita, la línea también vale como pista."),
    ]


@pytest.mark.parametrize(
    ("block", "warning"),
    [
        ("## WEB\n> Muy corta.", "«WEB» no tiene 5 letras (tiene 3)"),
        ("## KUBERNETES\n> Muy larga.", "no tiene 5 letras (tiene 10)"),
        ("## L1NUX\n> Con una cifra.", "algo que no es una letra"),
        ("## LINUX\n", "«LINUX» no tiene pista"),
        ("## LINUX\n> Este Linux dice la palabra.", "la pista de «LINUX» dice la propia palabra"),
        ("## PIXEL\n> Es un PÍXEL de pantalla.", "la pista de «PIXEL» dice la propia palabra"),
        ("## LINUX\n> " + "x" * (HINT_MAX_CHARS + 1), "es muy larga"),
    ],
)
def test_lo_mal_formado_se_salta_con_un_aviso(block: str, warning: str) -> None:
    text = f"## REACT\n> La buena.\n\n{block}\n\n## SWIFT\n> Otra buena.\n"
    parsed = parse_words(text)
    assert [e.word for e in parsed.entries] == ["REACT", "SWIFT"]
    assert len(parsed.warnings) == 1 and warning in parsed.warnings[0]


def test_una_palabra_repetida_se_salta() -> None:
    parsed = parse_words("## REACT\n> Una.\n\n## react\n> Otra.\n")
    assert [e.word for e in parsed.entries] == ["REACT"]
    assert parsed.warnings == ["«REACT» está repetida"]


def test_un_banco_vacio_o_basura_no_lanza() -> None:
    assert parse_words("").entries == []
    assert parse_words("hola\n> sola\n##\n").entries == []
    parsed = parse_words("## ¿?\n> Sin letras.\n")
    assert parsed.entries == [] and parsed.warnings == ["«¿?» está vacía"]


def test_el_banco_declara_su_minimo_y_su_archivo() -> None:
    assert WORDS.id == "wordle_palabras" and WORDS.file == "palabras.md"
    assert WORDS.min_entries == MIN_WORDS == 10
    assert WORDS.parse is parse_words


def test_pick_word_no_repite_hasta_agotar() -> None:
    words = [WordleWord(w, "pista") for w in ("REACT", "SWIFT", "KAFKA", "REDIS")]
    rng = random.Random(5)
    recent: dict[str, int] = {}
    seen: list[str] = []
    for match in range(1, 9):
        picked = pick_word(words, rng, recent)
        recent[picked.word] = match
        seen.append(picked.word)
    # Dos vueltas completas: cada ronda de cuatro tiene las cuatro palabras.
    assert sorted(seen[:4]) == sorted(w.word for w in words)
    assert sorted(seen[4:]) == sorted(w.word for w in words)
    # Una palabra nueva en el banco sale antes que las ya jugadas.
    words.append(WordleWord("FLASK", "pista"))
    assert pick_word(words, rng, recent).word == "FLASK"
    with pytest.raises(ValueError, match="no hay palabras"):
        pick_word([], rng, recent)


# ---------------------------------------------------------------------------
# El banco de la app (borrador pendiente de revisión)
# ---------------------------------------------------------------------------


def test_el_banco_de_la_app_esta_bien_formado() -> None:
    text = BANK_FILE.read_text(encoding="utf-8")
    parsed = parse_words(text)
    assert parsed.warnings == [], parsed.warnings
    words = [e.word for e in parsed.entries]
    # «Unas 60 palabras» y todas distintas.
    assert len(words) >= 60 and len(words) == len(set(words))
    assert len(text) < 15_000, "el banco tiene que caber en el tope de la nube"
    for entry in parsed.entries:
        # Cinco letras A-Z, mayúsculas y sin tildes.
        assert re.fullmatch(r"[A-Z]{5}", entry.word), entry.word
        assert entry.hint and len(entry.hint) <= HINT_MAX_CHARS, entry.word
        assert entry.word not in re.sub(r"\s", " ", entry.hint.upper()), entry.word
        # Lo que lee GPT-Live no nombra el stack, ni en la palabra ni en la pista.
        assert not brands_in(entry.word) and not brands_in(entry.hint), entry.word


def test_el_banco_de_la_app_esta_marcado_como_borrador() -> None:
    text = BANK_FILE.read_text(encoding="utf-8")
    assert "pendiente de revisión de Jean" in text


def test_el_banco_de_la_app_empieza_con_las_palabras_del_plan() -> None:
    words = {e.word for e in parse_words(BANK_FILE.read_text(encoding="utf-8")).entries}
    for word in ("LINUX", "REACT", "SWIFT", "KAFKA", "REDIS", "CLOUD", "PIXEL", "FLASK"):
        assert word in words
    assert {"SCALA", "JULIA"} <= words


def test_el_formato_se_explica_al_principio_del_archivo() -> None:
    head = BANK_FILE.read_text(encoding="utf-8").split("-->", 1)[0]
    assert "Formato" in head and "## " in head and "> " in head


@pytest.mark.parametrize("path", [BANK_FILE], ids=lambda p: Path(p).name)
def test_el_banco_se_lee_en_utf8_sin_caracteres_raros(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "�" not in text and "\r" not in text
