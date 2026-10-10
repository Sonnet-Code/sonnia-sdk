"""Lo que tiene que cumplir cada juego del registro (también los que se van rellenando).

Se aplica sola a los seis juegos: ids y nombres, su bloque de ajustes, lo que
necesitan, sus jugadas con esquemas estrictos, sus bancos y que nada de lo que lee
GPT-Live nombre el stack.
"""

from __future__ import annotations

from typing import Any

import pytest

from sonia.actions import build_default_registry
from sonia.config import GamesSettings
from sonia.games import NEEDS, NOT_SAID_VALUES, Game
from sonia.games.banks import is_bank_id
from sonia.games.registry import GAMES, all_games, enabled_games, games_line
from sonia.ws import protocol as p
from tests.games.fakes import brands_in, game_settings

#: Los ids del plan (``docs/plan-juegos.md``, sección 1).
PLAN_IDS = ["ruleta", "poses", "akinator", "piedra_papel_tijera", "wordle", "busqueda"]

#: Las acciones que ya existen: ninguna jugada puede pisarlas.
BUILTIN = set(
    build_default_registry(include_look=True, include_trivia=True, include_agenda=True).names()
)

GAME_CLASSES = all_games()


def test_estan_los_seis_juegos_del_plan_en_su_orden() -> None:
    assert [g.id for g in GAME_CLASSES] == PLAN_IDS


@pytest.mark.parametrize("cls", GAME_CLASSES, ids=lambda c: c.id)
def test_cada_juego_tiene_nombre_bloque_y_necesidades_validos(cls: type[Game]) -> None:
    assert p.is_game_name(cls.id)
    assert cls.title.strip() and cls.spoken.strip()
    assert "Sonia" not in cls.title, "en pantalla se escribe «Sonnia»"
    assert "Sonnia" not in cls.spoken, "GPT-Live lee «Sonia»"
    assert cls.settings_key in GamesSettings.model_fields
    block = getattr(game_settings().games, cls.settings_key)
    assert hasattr(block, "enabled") and hasattr(block, "abandon_seconds")
    assert cls.needs <= NEEDS


@pytest.mark.parametrize("cls", GAME_CLASSES, ids=lambda c: c.id)
def test_las_jugadas_son_estrictas_y_con_su_prefijo(cls: type[Game]) -> None:
    for spec in cls.actions():
        assert spec.name.startswith((f"{cls.settings_key}_", f"{cls.id}_")), spec.name
        assert spec.name not in BUILTIN | {"start_game", "stop_game"}
        params: dict[str, Any] = spec.parameters
        assert params.get("type") == "object"
        properties = params.get("properties") or {}
        assert set(params.get("required") or []) == set(properties), (
            f"{spec.name}: todos los parámetros obligatorios"
        )
        for name, prop in properties.items():
            if "enum" in prop:
                assert set(prop["enum"]) & NOT_SAID_VALUES, (
                    f"{spec.name}.{name}: el enum necesita un valor de «no lo dijo»"
                )
        assert not brands_in(spec.description), spec.name


def test_las_jugadas_no_se_repiten_entre_juegos() -> None:
    names = [spec.name for cls in GAME_CLASSES for spec in cls.actions()]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("cls", GAME_CLASSES, ids=lambda c: c.id)
def test_los_bancos_tienen_id_unico_y_archivo(cls: type[Game]) -> None:
    settings = game_settings()
    on = {entry.game for entry in GAMES if entry.on}
    for bank in cls.banks():
        assert (
            is_bank_id(bank.id)
            and bank.id.startswith(f"{cls.settings_key}_")
            or (bank.id.startswith(f"{cls.id}_"))
        ), bank.id
        assert bank.min_entries >= 1
        if cls in on:
            path = settings.games_dir / cls.id / bank.file
            assert path.is_file(), f"falta el banco de la app {path}"
            parsed = bank.parse(path.read_text(encoding="utf-8"))
            assert len(parsed.entries) >= bank.min_entries


def test_los_bancos_no_se_repiten_entre_juegos() -> None:
    ids = [bank.id for cls in GAME_CLASSES for bank in cls.banks()]
    assert len(ids) == len(set(ids))


def test_la_linea_de_juegos_no_nombra_el_stack_y_es_una() -> None:
    line = games_line(GAME_CLASSES)
    assert line.count("\n") == 0 and not brands_in(line)
    assert games_line([]) == ""


def test_apagados_en_los_ajustes_no_se_ofrecen() -> None:
    settings = game_settings(enabled=False)
    assert enabled_games(settings) == []
