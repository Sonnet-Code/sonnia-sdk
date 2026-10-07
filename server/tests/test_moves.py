"""Movimientos por voz (``play_animation``): catálogo de Unity, elección del clip y mensaje."""

from __future__ import annotations

import random
from typing import Any

from sonia.actions.moves import MOVES, NO_MOVES, PLAY_ANIMATION, MoveCatalog, play_animation
from sonia.actions.registry import ActionRegistry
from sonia.types import ActionContext

#: Catálogo como el que manda la app de Unity con el set de Genies.
UNITY_CATALOG: dict[str, Any] = {
    "type": "animations",
    "animations": [
        {"clip": "Wave", "group": "greeting"},
        {"clip": "QuickAction_vibe", "group": "dance"},
        {"clip": "WaveGeneric", "group": "fourth_wall"},
        {"clip": "Peace", "group": "fourth_wall"},
        {"clip": "QuickAction_salute", "group": "fourth_wall"},
        {"clip": "QuickAction_twoThumbsUp", "group": "fourth_wall"},
        {"clip": "actions-0224-lookAtObject_Trimmed", "group": "thinking"},
        {"clip": "actions-presentItem_intro", "group": "present"},
        {"clip": "actions-highFive_actionSuccess", "group": "trivia"},
        {"clip": "actions-highFive_actionFail", "group": "trivia"},
        {"clip": "emotions-0049-traitsKind", "group": "trivia"},
    ],
}


class Sent:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def __call__(self, msg: dict[str, Any]) -> None:
        self.messages.append(msg)


def make_catalog(msg: dict[str, Any] | None = UNITY_CATALOG) -> tuple[MoveCatalog, Sent]:
    sent = Sent()
    catalog = MoveCatalog(sent, rng=random.Random(1))
    if msg is not None:
        catalog.update(msg)
    return catalog, sent


def ctx_with(catalog: MoveCatalog | None) -> ActionContext:
    extra: dict[str, Any] = {} if catalog is None else {"moves": catalog}
    return ActionContext(camera=None, avatar=None, gallery_dir="", extra=extra)


def test_todos_los_movimientos_estan_en_el_set_de_genies() -> None:
    catalog, _ = make_catalog()
    assert catalog.available() == list(MOVES)


def test_saludar_vale_por_grupo_y_por_nombre() -> None:
    catalog, _ = make_catalog()
    assert catalog.clips_for("saludar") == ["Wave", "WaveGeneric"]
    assert catalog.clips_for("bailar") == ["QuickAction_vibe"]
    assert catalog.clips_for("no_existe") == []


async def test_lanza_el_clip_entero() -> None:
    catalog, sent = make_catalog()
    result = await play_animation(ctx_with(catalog), {"movimiento": "bailar"})
    assert result.text.startswith("Hecho")
    assert sent.messages == [{"type": "play_animation", "clip": "QuickAction_vibe", "whole": True}]


async def test_movimiento_que_la_app_no_tiene_ofrece_los_que_hay() -> None:
    catalog, sent = make_catalog(
        {"type": "animations", "animations": [{"clip": "Peace", "group": "x"}]}
    )
    result = await play_animation(ctx_with(catalog), {"movimiento": "bailar"})
    assert "no lo tienes" in result.text
    assert "paz" in result.text
    assert sent.messages == []


async def test_sin_catalogo_de_unity_no_se_mueve() -> None:
    catalog, sent = make_catalog(None)
    assert (await play_animation(ctx_with(catalog), {"movimiento": "bailar"})).text == NO_MOVES
    assert (await play_animation(ctx_with(None), {"movimiento": "bailar"})).text == NO_MOVES
    assert sent.messages == []


async def test_el_registro_rechaza_un_movimiento_inventado() -> None:
    registry = ActionRegistry()
    registry.register(PLAY_ANIMATION)
    catalog, sent = make_catalog()
    result = await registry.execute("play_animation", {"movimiento": "volar"}, ctx_with(catalog))
    assert result.text.startswith("Error")
    assert sent.messages == []


# -- gestos concretos («tócate un ojo»): los elige el director de gestos --------


def with_sage(*clips: str) -> dict[str, Any]:
    return {
        "type": "animations",
        "animations": UNITY_CATALOG["animations"] + [{"clip": c, "group": "sage"} for c in clips],
    }


def ctx_with_director(catalog: MoveCatalog, director: Any) -> ActionContext:
    return ActionContext(
        camera=None, avatar=None, gallery_dir="", extra={"moves": catalog, "gestures": director}
    )


async def test_un_gesto_concreto_lo_busca_el_director_y_suena_entero() -> None:
    from tests.test_gestures import FakeGestureLLM, make_director

    llm = FakeGestureLLM('{"gesto": "bigCheer"}')
    director, director_sent = make_director(llm)
    catalog, sent = make_catalog(with_sage("bigCheer", "wave"))
    result = await play_animation(ctx_with_director(catalog, director), {"gesto": "celebrar"})
    assert result.text.startswith("Hecho: Sonia está haciendo «celebrar»")
    # Con lo que se ve de verdad (su ficha), para que Sonia no prometa más.
    assert "(lo que se ve: Gesto bigCheer.)" in result.text
    assert sent.messages == [{"type": "play_animation", "clip": "bigCheer", "whole": True}]
    assert director_sent.messages == []
    assert "«celebrar»" in llm.user()


async def test_un_gesto_que_no_hay_ofrece_los_movimientos_o_usa_el_de_respaldo() -> None:
    from tests.test_gestures import FakeGestureLLM, make_director

    director, _ = make_director(FakeGestureLLM('{"gesto": "ninguno"}'))
    catalog, sent = make_catalog(with_sage("bigCheer"))
    result = await play_animation(ctx_with_director(catalog, director), {"gesto": "volar"})
    assert result.text.startswith("Un gesto que sea «volar» no lo tienes. Puedes hacer: bailar")
    assert sent.messages == []
    # Con un movimiento de respaldo, se hace ese.
    result = await play_animation(
        ctx_with_director(catalog, director), {"gesto": "volar", "movimiento": "bailar"}
    )
    # Y Sonia sabe que no es lo que pidieron.
    assert result.text.startswith("No tienes un gesto que sea «volar»: en su lugar Sonia está")
    assert sent.messages == [{"type": "play_animation", "clip": "QuickAction_vibe", "whole": True}]


async def test_un_gesto_elegido_que_la_app_no_tiene_no_se_manda() -> None:
    from tests.test_gestures import FakeGestureLLM, make_director

    director, _ = make_director(FakeGestureLLM('{"gesto": "bigCheer"}'))
    catalog, sent = make_catalog()  # sin el grupo sage
    result = await play_animation(ctx_with_director(catalog, director), {"gesto": "celebrar"})
    assert "no lo tienes" in result.text
    assert sent.messages == []
    # Sin director tampoco: se ofrece lo que hay.
    result = await play_animation(ctx_with(catalog), {"gesto": "tocarse un ojo"})
    assert "no lo tienes" in result.text
