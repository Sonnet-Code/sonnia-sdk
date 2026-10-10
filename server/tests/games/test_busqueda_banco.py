"""El banco de objetos de la búsqueda relámpago: lo bien formado, lo mal formado, el mínimo de
entradas, que nada hable de las personas y que nada de lo que lee GPT-Live nombre el stack."""

from __future__ import annotations

import pytest

from sonia.games.busqueda import texts as t
from sonia.games.busqueda.bank import (
    COLORS,
    DEFAULT_QUESTION,
    NAME_MAX,
    NAME_MIN,
    OBJECTS,
    announced,
    clean_what,
    key_words,
    mentions_person,
    parse_objects,
)
from sonia.games.busqueda.game import BusquedaGame
from tests.games.fakes import brands_in, game_settings, make_manager

BANK = """\
<!-- Esto es el formato y se ignora. ## algo falso -->
## algo azul
color: azul

## la credencial del DevFest
> En la foto, ¿se ve una credencial o gafete de evento bien a la vista, en una mano o frente a la cámara?

## unas llaves
> Esto no es una pregunta cerrada
color: fucsia

## una camiseta del DevFest

## ab

## algo azul

## un bolígrafo o un lápiz
> ¿Hay alguien con la cara tapada por un bolígrafo, un lápiz o un marcador a la vista?
línea suelta
"""


def test_el_banco_de_la_app_esta_bien_formado() -> None:
    path = game_settings().games_dir / "busqueda" / OBJECTS.file
    parsed = parse_objects(path.read_text(encoding="utf-8"))
    assert parsed.warnings == []
    assert len(parsed.entries) >= 24
    assert len(parsed.entries) >= OBJECTS.min_entries


def test_el_banco_esta_marcado_como_borrador_y_explica_su_formato() -> None:
    path = game_settings().games_dir / "busqueda" / OBJECTS.file
    text = path.read_text(encoding="utf-8")
    head = text.split("-->", 1)[0]
    assert "BORRADOR pendiente de revisión de Jean" in head
    assert "Formato" in head and "color:" in head and "CERRADA" in head


def test_cada_objeto_del_banco_cumple_las_reglas() -> None:
    path = game_settings().games_dir / "busqueda" / OBJECTS.file
    entries = parse_objects(path.read_text(encoding="utf-8")).entries
    names = [e.name.casefold() for e in entries]
    assert len(names) == len(set(names)), "objetos repetidos"
    for entry in entries:
        assert NAME_MIN <= len(entry.name) <= NAME_MAX, entry.name
        assert entry.name == entry.name.strip() and not entry.name[0].isupper(), entry.name
        # Nada que obligue a hablar de la persona: ni gafas ni ropa ni su cuerpo.
        assert not mentions_person(entry.name), entry.name
        assert "?" in entry.question and entry.question.count("?") == 1, entry.question
        assert not mentions_person(entry.question, "question"), entry.question
        assert not brands_in(entry.name) and not brands_in(entry.question)
        assert entry.color == "" or entry.color in COLORS.values()
    # Las preguntas por defecto cuentan solo lo del objeto y dejan fuera la ropa y el fondo.
    assert any(e.question == DEFAULT_QUESTION.format(name=e.name) for e in entries)
    assert all("ropa" in e.question or "gafete" in e.question for e in entries[:4])


def test_el_banco_trae_los_objetos_del_encargo() -> None:
    path = game_settings().games_dir / "busqueda" / OBJECTS.file
    names = {e.name for e in parse_objects(path.read_text(encoding="utf-8")).entries}
    for wanted in (
        "algo azul",
        "algo rojo",
        "la credencial del DevFest",
        "una botella",
        "unas llaves",
        "un sticker",
        "algo con el logo de Google",
    ):
        assert wanted in names, wanted
    assert any("bolígrafo" in n for n in names) and any("cable" in n for n in names)


def test_lo_bien_formado_entra_y_lo_mal_formado_se_salta_con_aviso() -> None:
    parsed = parse_objects(BANK)
    names = [e.name for e in parsed.entries]
    # El comentario del formato no cuenta como sección; los repetidos y cortos se saltan.
    assert names == [
        "algo azul",
        "la credencial del DevFest",
        "unas llaves",
        "un bolígrafo o un lápiz",
    ]
    by_name = {e.name: e for e in parsed.entries}
    assert by_name["algo azul"].color == COLORS["azul"]
    assert by_name["algo azul"].question == DEFAULT_QUESTION.format(name="algo azul")
    assert by_name["la credencial del DevFest"].question.startswith(
        "En la foto, ¿se ve una credencial"
    )
    # Una pregunta que no es cerrada o habla de personas no tira el objeto: va la genérica.
    assert by_name["unas llaves"].question == DEFAULT_QUESTION.format(name="unas llaves")
    assert by_name["un bolígrafo o un lápiz"].question == DEFAULT_QUESTION.format(
        name="un bolígrafo o un lápiz"
    )
    assert by_name["unas llaves"].color == ""
    text = " | ".join(parsed.warnings)
    assert "camiseta" in text and "persona" in text  # la ropa
    assert "ab" in text  # el nombre corto
    assert "repetido" in text
    assert "fucsia" in text  # el color desconocido
    assert "la pregunta debe ser cerrada" in text
    assert "línea que no entiendo" in text


def test_un_banco_vacio_o_sin_objetos_no_lanza() -> None:
    assert parse_objects("").entries == []
    assert parse_objects("solo texto\n> sin encabezado").entries == []
    assert len(parse_objects("## x").warnings) == 1


def test_el_nombre_largo_o_con_marcas_no_entra() -> None:
    parsed = parse_objects(f"## {'x' * (NAME_MAX + 1)}\n\n## <b>algo</b> raro\n\n## algo rojo")
    assert [e.name for e in parsed.entries] == ["algo rojo"]
    assert len(parsed.warnings) == 2


def test_el_banco_exige_su_minimo_para_guardarse_en_la_nube() -> None:
    assert OBJECTS.min_entries == 6
    assert OBJECTS.id == "busqueda_objetos" and OBJECTS.file == "objetos.md"


async def test_el_panel_valida_el_banco_con_el_minimo() -> None:
    manager, _, _, _ = await make_manager([BusquedaGame])
    few = "\n\n".join(f"## algo número {n}" for n in "abcde")
    ok, message = manager.validate_bank(OBJECTS.id, few)
    assert not ok and "hacen falta 6" in message
    enough = "\n\n".join(f"## algo número {n}" for n in "abcdef")
    ok, message = manager.validate_bank(OBJECTS.id, enough)
    assert ok and "6 entradas válidas" in message
    # Con ropa de por medio, esa entrada no cuenta (y se avisa).
    ok, message = manager.validate_bank(OBJECTS.id, enough + "\n\n## una gorra azul")
    assert ok and "Se saltó 1" in message and "gorra" in message
    # El tope de caracteres de los bancos.
    ok, message = manager.validate_bank(OBJECTS.id, enough + "\n" + "x" * 16_000)
    assert not ok and "tope" in message
    # Vacío: vuelve el de la app.
    ok, message = manager.validate_bank(OBJECTS.id, "  ")
    assert ok and "vuelve el de la app" in message


async def test_el_panel_lista_el_banco_y_su_archivo() -> None:
    manager, _, _, _ = await make_manager([BusquedaGame])
    banks = manager.bank_list()
    assert banks == [
        {
            "id": "busqueda_objetos",
            "game": "busqueda",
            "title": "Objetos de la búsqueda relámpago",
            "file": "assets/games/busqueda/objetos.md",
            "min_entries": 6,
            "source": "app",
        }
    ]
    text = manager.bank_text("busqueda_objetos")
    assert text.startswith("<!--") and "## algo azul" in text


# ---------------------------------------------------------------------------
# Lo que dice el modelo de la foto (JudgeAnswer.what): nada de la persona
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "what",
    ["botella azul", "llaves con llavero rojo", "cable USB-C", "Sticker de Kotlin", " mouse. "],
)
def test_un_objeto_corto_pasa(what: str) -> None:
    assert clean_what(what, "algo azul") == what.strip(" .")


@pytest.mark.parametrize(
    "what",
    [
        "",
        "   ",
        "un hombre con una camisa azul",
        "una mujer sosteniendo una botella",
        "persona con gafas",
        "botella en la mano de alguien",
        "sosteniendo una botella",
        "camiseta azul",
        "gorra de Google",
        "la cara de alguien con barba",
        "una botella azul que sostiene un joven de pelo largo y camisa roja",
        "x" * 60,
        "botella <b>azul</b>",
        "botella azul con tapa y una etiqueta grande",
        'llavero: {"visto": true}',
    ],
)
def test_lo_que_habla_de_la_persona_o_no_es_un_objeto_se_cambia_por_lo_pedido(what: str) -> None:
    assert clean_what(what, "algo azul") == "algo azul"


def test_clean_what_deja_el_objeto_en_una_sola_linea_y_corto() -> None:
    assert clean_what("botella\n  azul ", "x") == "botella azul"
    assert clean_what("a b c d e f", "x") == "a b c d e f"  # seis palabras, el tope
    assert clean_what("a b c d e f g", "x") == "x"


def test_clean_what_no_confunde_objetos_con_palabras_que_se_parecen() -> None:
    # «mando» no es un gerundio y «candado» no lleva «ando».
    assert clean_what("mando a distancia", "x") == "mando a distancia"
    assert clean_what("candado", "x") == "candado"
    assert clean_what("cable tipo C", "x") == "cable tipo C"


def test_la_ropa_solo_vale_en_negativo_dentro_de_una_pregunta() -> None:
    assert not mentions_person("No cuentan la ropa ni el fondo", "question")
    assert mentions_person("No cuentan la ropa ni el fondo", "name")
    assert not mentions_person("en una mano o frente a la cámara", "question")
    assert mentions_person("en la mano de alguien", "what")
    assert mentions_person("ese Niño de la Camiseta", "name")  # tildes y mayúsculas


# ---------------------------------------------------------------------------
# Seguir lo que dice Sonia (solo para dar la salida), no entender a nadie
# ---------------------------------------------------------------------------


def test_announced_busca_las_palabras_clave_del_objeto() -> None:
    assert key_words("algo azul") == ["azul"]
    assert key_words("la credencial del DevFest") == ["credencial", "devfest"]
    assert announced("¡El primero que me enseñe algo azul!", "algo azul")
    assert not announced("¡El primero que me enseñe algo rojo!", "algo azul")
    assert announced("la credencial, a ver quién la trae", "la credencial del DevFest")
    assert not announced("a ver quién trae algo", "la credencial del DevFest")
    assert announced("lo que sea", "algo")  # sin palabras clave, nada que comprobar


# ---------------------------------------------------------------------------
# Lo que lee GPT-Live
# ---------------------------------------------------------------------------


def _all_texts() -> dict[str, str]:
    return {
        name: value for name, value in vars(t).items() if name.isupper() and isinstance(value, str)
    }


def test_nada_de_lo_que_lee_gpt_live_nombra_el_stack_ni_dice_sonnia() -> None:
    texts = _all_texts()
    assert len(texts) >= 20
    for name, value in texts.items():
        assert not brands_in(value), name
        assert "Sonnia" not in value, f"{name}: a GPT-Live se le dice «Sonia»"


@pytest.mark.parametrize(("total", "seconds"), [(3, "25"), (99, "1000.5"), (1, "5")])
def test_las_reglas_caben_en_1200_caracteres(total: int, seconds: str) -> None:
    rules = t.RULES_TEXT.format(total=total, seconds=seconds)
    assert len(rules) <= 1_200
    assert "busqueda_check" in rules


def test_las_reglas_dicen_lo_que_hay_que_decir() -> None:
    rules = t.RULES_TEXT.format(total=3, seconds="25")
    assert "Tú no ves nada" in rules  # no se inventa lo que ve
    assert "en la pantalla nada cambia si no lo delegas" in rules
    assert "No uses look" in rules  # la cámara la mira el sistema, no el backend
    assert "nunca de la persona ni de su ropa" in rules
    assert "delega terminarlo" in rules


def test_las_frases_grabadas_son_las_tres_con_tiempo_exacto() -> None:
    assert (t.GO_PHRASE, t.FOUND_PHRASE, t.TIMEOUT_PHRASE) == ("¡Ya!", "¡Lo veo!", "¡Tiempo!")
