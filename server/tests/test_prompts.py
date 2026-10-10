"""Prompts editables desde la nube: el registro (``sonia.prompts``) y el panel (``prompts``).

Sin red ni APIs: piezas de prueba registradas a mano.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from sonia.panel.control import SHARED_SETTINGS, PanelState, normalize_prompts
from sonia.prompts import BOOK, PromptBook, PromptSpec
from tests.test_panel import make_panel_rig

JUEZ = 'Responde solo en JSON: {"visto": true o false}. Busca {objeto}.'


def spec(prompt_id: str = "prueba/juez", default: str = JUEZ) -> PromptSpec:
    return PromptSpec(
        id=prompt_id,
        group="Juez",
        title="Juez de prueba",
        default=lambda: default,
        fields=("objeto",),
        required=("objeto",),
        must_contain=("JSON",),
        applies="ronda",
    )


@pytest.fixture
def global_spec() -> Iterator[str]:
    """Una pieza de prueba en el registro de la app, sin dejar rastro."""
    BOOK.register(spec("prueba/panel"))
    yield "prueba/panel"
    BOOK.set_overrides(None)


def test_rellena_solo_sus_marcadores_y_deja_los_json() -> None:
    book = PromptBook()
    book.register(spec())
    assert book.render("prueba/juez", objeto="una botella", otro="x") == (
        'Responde solo en JSON: {"visto": true o false}. Busca una botella.'
    )
    assert book.text("prueba/juez") == JUEZ
    assert book.source("prueba/juez") == "app"


def test_lo_que_no_vale_dice_por_que() -> None:
    book = PromptBook()
    book.register(spec())
    assert book.validate("prueba/juez", "En JSON: {objeto}") == []
    assert any("vacío" in p for p in book.validate("prueba/juez", "  "))
    assert any("{otro}" in p for p in book.validate("prueba/juez", "JSON {objeto} {otro}"))
    assert any("{objeto}" in p for p in book.validate("prueba/juez", "Solo JSON, sin marcador"))
    assert any("JSON" in p for p in book.validate("prueba/juez", "Sin formato: {objeto}"))
    assert any("largo" in p for p in book.validate("prueba/juez", "JSON {objeto}" + "x" * 70_000))
    assert book.validate("no/existe", "x")


def test_la_nube_manda_solo_si_vale_y_nunca_las_dos() -> None:
    book = PromptBook()
    book.register(spec())
    assert book.set_overrides({"prueba/juez": "Nuevo, en JSON: {objeto}"}) == []
    assert book.source("prueba/juez") == "nube"
    assert book.render("prueba/juez", objeto="X") == "Nuevo, en JSON: X"
    # Una versión rota se ignora con aviso y vuelve la de la app.
    warnings = book.set_overrides({"prueba/juez": "roto"})
    assert warnings and book.source("prueba/juez") == "app"
    assert book.text("prueba/juez") == JUEZ


def test_una_pieza_que_se_registra_despues_recoge_su_version_de_la_nube() -> None:
    book = PromptBook()
    book.set_overrides({"prueba/tarde": "Tarde, en JSON: {objeto}"})
    assert book.overrides() == {"prueba/tarde": "Tarde, en JSON: {objeto}"}
    book.register(spec("prueba/tarde"))
    assert book.source("prueba/tarde") == "nube"


def test_sin_registrar_usa_el_texto_de_la_app_que_le_pasan() -> None:
    book = PromptBook()
    assert book.text("no/existe", "respaldo") == "respaldo"
    assert book.render("no/existe", fallback="hola {nombre}", nombre="Ana") == "hola Ana"
    with pytest.raises(KeyError):
        book.text("no/existe")


def test_el_registro_carga_las_piezas_al_pedir_la_primera() -> None:
    book = PromptBook()
    calls: list[int] = []

    def loader() -> None:
        calls.append(1)
        book.register(spec())

    book.set_loader(loader)
    assert book.text("prueba/juez") == JUEZ
    assert [c["id"] for c in book.catalog()] == ["prueba/juez"]
    assert calls == [1]


def test_el_catalogo_no_lleva_el_texto() -> None:
    book = PromptBook()
    book.register(spec())
    (entry,) = book.catalog()
    assert entry["id"] == "prueba/juez" and entry["source"] == "app"
    assert entry["fields"] == ["objeto"] and entry["applies"] == "ronda"
    assert "text" not in entry and "default" not in entry


def test_los_prompts_de_la_nube_se_normalizan() -> None:
    assert "prompts" in SHARED_SETTINGS
    assert normalize_prompts(None) is None
    assert normalize_prompts({"a/b": "  hola  ", "MAL ID": "x", "c/d": "", "e/f": 3}) == {
        "a/b": "hola"
    }
    with pytest.raises(ValueError):
        normalize_prompts(["a/b"])


async def test_prompts_desde_el_panel(tmp_path: Path, global_spec: str) -> None:
    async with make_panel_rig(tmp_path) as rig:
        control = rig.control
        assert "prompts" in control.capabilities

        ok, message = await control.act("prompt_catalog", {})
        assert ok and global_spec in [p["id"] for p in json.loads(message)["prompts"]]

        ok, message = await control.act("prompt", {"id": global_spec})
        data = json.loads(message)
        assert ok and data["text"] == JUEZ and data["default"] == JUEZ and data["source"] == "app"

        ok, message = await control.act("set_prompt", {"id": global_spec, "text": "Mal: {objeto}"})
        assert not ok and "JSON" in message and control.state.prompts is None

        nuevo = "Busca {objeto} y contesta en JSON."
        ok, message = await control.act("set_prompt", {"id": global_spec, "text": nuevo})
        assert ok and "nube" in message
        assert control.state.prompts == {global_spec: nuevo}
        assert BOOK.source(global_spec) == "nube" and BOOK.render(global_spec, objeto="X") == (
            "Busca X y contesta en JSON."
        )

        # Igual al de la app, o vacío: vuelve al de la app y no queda nada en la nube.
        ok, message = await control.act("set_prompt", {"id": global_spec, "text": JUEZ})
        assert ok and control.state.prompts is None and BOOK.source(global_spec) == "app"

        ok, message = await control.act("prompt", {"id": "no/existe"})
        assert not ok
        ok, message = await control.act("set_prompt", {"id": "../../etc", "text": "x"})
        assert not ok


async def test_los_prompts_guardados_se_aplican_al_arrancar(
    tmp_path: Path, global_spec: str
) -> None:
    state = PanelState(prompts={global_spec: "Arranque, en JSON: {objeto}"})
    async with make_panel_rig(tmp_path, state=state):
        assert BOOK.source(global_spec) == "nube"
        assert BOOK.render(global_spec, objeto="Y") == "Arranque, en JSON: Y"


def test_una_pieza_literal_admite_llaves_y_no_las_toca() -> None:
    book = PromptBook()
    book.register(
        PromptSpec(
            id="prueba/libre", group="Conocimiento", title="t", default=lambda: "x", literal=True
        )
    )
    texto = "Usa {nombre} o {lo_que_sea} si quieres: aquí no hay marcadores."
    assert book.validate("prueba/libre", texto) == []
    assert book.set_overrides({"prueba/libre": texto}) == []
    assert book.render("prueba/libre", nombre="Ana") == texto
    with pytest.raises(ValueError):
        book.register(
            PromptSpec(
                id="prueba/mal",
                group="g",
                title="t",
                default=lambda: "x",
                fields=("a",),
                literal=True,
            )
        )


def test_el_catalogo_lleva_el_tope_de_cada_pieza() -> None:
    book = PromptBook()
    book.register(
        PromptSpec(id="prueba/corta", group="g", title="t", default=lambda: "x", max_len=1200)
    )
    (entry,) = book.catalog()
    assert entry["max_len"] == 1200


def test_la_primera_carga_no_deja_piezas_a_medias_a_otro_hilo() -> None:
    import threading
    import time

    book = PromptBook()
    started = threading.Event()

    def slow_loader() -> None:
        started.set()
        time.sleep(0.2)
        book.register(spec())

    book.set_loader(slow_loader)
    result: list[str] = []
    loader_thread = threading.Thread(target=lambda: book.catalog())
    loader_thread.start()
    started.wait(1)
    # Pide la pieza mientras el otro hilo aún carga: tiene que esperar y encontrarla.
    result.append(book.text("prueba/juez"))
    loader_thread.join(2)
    assert result == [JUEZ]
