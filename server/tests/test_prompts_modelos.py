"""Las piezas del juez, los gestos, la trivia y los juegos en el registro de prompts.

Cada módulo de ``specs_modelos.MODULES`` declara las suyas con ``prompt_specs()``; aquí se
comprueba el conjunto. Los tests de cada uno (``test_prompts_<módulo>.py``) comprueban
que con los textos de la app no cambia nada y que manda la versión de la nube.
"""

from __future__ import annotations

import logging

import pytest

from sonia.games.registry import all_games
from sonia.prompts import BOOK, specs_modelos
from sonia.prompts.book import APPLIES_TEXT
from tests.games.fakes import brands_in

#: Las que no lee GPT-Live (van a Gemini o al modelo de visión).
OTHER_MODELS = ("juez/", "gestos/")


def all_specs() -> dict[str, list[str]]:
    """``{módulo: [ids]}`` de todas las piezas declaradas."""
    return {
        name: [spec.id for spec in specs_modelos.module_specs(name)]
        for name in specs_modelos.MODULES
    }


def test_cada_modulo_declara_sus_piezas_y_no_se_repite_ninguna() -> None:
    declared = all_specs()
    for name, ids in declared.items():
        assert ids, f"{name} no declara ninguna pieza"
    flat = [prompt_id for ids in declared.values() for prompt_id in ids]
    assert len(flat) == len(set(flat)), "hay ids repetidos"
    games = {game.id for game in all_games()}
    for prompt_id in flat:
        assert prompt_id in BOOK
        top, rest = prompt_id.split("/", 1)
        if top == "juegos":
            assert rest.split("/", 1)[0] in games, prompt_id
        else:
            assert top in {"juez", "gestos", "trivia"}, prompt_id


def test_todas_validan_con_su_texto_de_la_app() -> None:
    for ids in all_specs().values():
        for prompt_id in ids:
            spec = BOOK.spec(prompt_id)
            default = BOOK.default(prompt_id)
            assert BOOK.validate(prompt_id, default) == [], prompt_id
            assert spec.group and spec.title and spec.applies in APPLIES_TEXT
            if not prompt_id.startswith(OTHER_MODELS):
                assert not brands_in(default), prompt_id
                assert spec.applies == "ronda", prompt_id


def test_registrar_otra_vez_no_cambia_nada() -> None:
    before = BOOK.catalog()
    specs_modelos.register_all()
    assert BOOK.catalog() == before


def test_un_modulo_que_falla_no_impide_registrar_los_demas(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(
        specs_modelos, "MODULES", ("sonia.no_existe", *specs_modelos.MODULES), raising=True
    )
    with caplog.at_level(logging.ERROR, logger="sonia.prompts.specs_modelos"):
        specs_modelos.register_all()
    assert "sonia.no_existe" in caplog.text
    assert "juez/busqueda" in BOOK and "juegos/wordle/reglas" in BOOK
