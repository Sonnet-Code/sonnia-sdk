"""La página del panel: «Developer», con la tarjeta «Prompts de Sonnia» y los editores de
los bancos. Sin navegador: se lee ``index.html`` y ``panel.js`` tal cual se sirven."""

from __future__ import annotations

import re
from html.parser import HTMLParser

from sonia.panel.server import STATIC_DIR
from sonia.prompts import PLACEHOLDER, PROMPT_MAX_LEN

PAGE = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
SCRIPT = (STATIC_DIR / "panel.js").read_text(encoding="utf-8")

#: Elementos sin cierre: no abren nivel.
_VOID = {"area", "br", "col", "hr", "img", "input", "link", "meta", "source", "wbr"}


class _Tree(HTMLParser):
    """Para cada elemento con ``id``: sus atributos y los ``id`` de sus antepasados."""

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[tuple[str, str | None]] = []
        self.attrs: dict[str, dict[str, str | None]] = {}
        self.tags: dict[str, str] = {}
        self.parents: dict[str, list[str]] = {}
        self.ids: list[str] = []

    def _record(self, tag: str, attrs: list[tuple[str, str | None]]) -> str | None:
        values = dict(attrs)
        element_id = values.get("id")
        if element_id:
            self.ids.append(element_id)
            self.attrs[element_id] = values
            self.tags[element_id] = tag
            self.parents[element_id] = [i for _, i in self.stack if i]
        return element_id

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        element_id = self._record(tag, attrs)
        if tag not in _VOID:
            self.stack.append((tag, element_id))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._record(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return


def _tree() -> _Tree:
    tree = _Tree()
    tree.feed(PAGE)
    return tree


def _section(element_id: str) -> str:
    """El HTML de la ``<section>`` o el ``<details>`` con ese ``id``, hasta su cierre."""
    match = re.search(rf'<(section|details)[^>]*\sid="{element_id}"', PAGE)
    assert match, element_id
    tag = match.group(1)
    depth = 0
    for token in re.finditer(rf"<(/?){tag}\b", PAGE[match.start() :]):
        depth += -1 if token.group(1) else 1
        if depth == 0:
            return PAGE[match.start() : match.start() + token.end()]
    raise AssertionError(f"{element_id} sin cerrar")


def test_los_ids_del_panel_existen_y_no_se_repiten() -> None:
    """Todo lo que ``collectElements`` busca por id está en la página, una sola vez."""
    tree = _tree()
    duplicated = {i for i in tree.ids if tree.ids.count(i) > 1}
    assert not duplicated
    listed = re.search(r"const ids = \[(.*?)\];", SCRIPT, re.S)
    assert listed
    wanted = re.findall(r'"([a-z0-9-]+)"', listed.group(1))
    assert "prompt-input" in wanted and "trivia-bank-input" in wanted
    assert [i for i in wanted if i not in tree.attrs] == []


def test_la_tarjeta_de_prompts_esta_en_developer_con_su_capacidad() -> None:
    tree = _tree()
    assert tree.tags["developer"] == "details"
    assert "developer" in tree.parents["dev-prompts"]
    controls = (
        "prompts-load-btn",
        "prompt-group-select",
        "prompt-select",
        "prompt-input",
        "prompt-save-btn",
        "prompt-reset-btn",
        "prompt-default-btn",
    )
    for element in controls:
        assert "dev-prompts" in tree.parents[element], element
        assert tree.attrs[element].get("data-cap") == "prompts", element
    for element in ("prompt-input", "prompt-save-btn", "prompt-reset-btn", "prompt-default-btn"):
        assert tree.attrs[element].get("data-extra") == "prompt_loaded", element
    # La línea de estado, el contador y los datos de la pieza.
    for element in ("prompt-state", "prompt-count", "prompt-check", "prompt-facts", "prompt-help"):
        assert "dev-prompts" in tree.parents[element], element
    # Sin catálogo hasta pulsar «Cargar prompts»; con una app anterior, el aviso.
    assert "hidden" in tree.attrs["prompt-pick"] and "hidden" in tree.attrs["prompt-editor"]
    card = _section("dev-prompts")
    assert ">Prompts de Sonnia<" in card and ">Cargar prompts<" in card
    assert 'data-cap-note="prompts"' in card
    for label in ("Guardar en la nube", "Volver al de la app", "Ver el de la app"):
        assert f">{label}<" in card, label
    # No deja escribir más de lo que acepta el orquestador.
    assert tree.attrs["prompt-input"].get("maxlength") == str(PROMPT_MAX_LEN)


def test_el_panel_pide_y_guarda_los_prompts_como_el_orquestador() -> None:
    for action in ("prompt_catalog", "prompt", "set_prompt"):
        assert f'sendAction("{action}"' in SCRIPT, action
    assert "prompt_loaded: () =>" in SCRIPT
    assert f"const PROMPT_MAX_CHARS = {PROMPT_MAX_LEN};" in SCRIPT
    # El aviso al escribir usa el mismo marcador que valida el orquestador.
    placeholder = re.search(r"const PROMPT_PLACEHOLDER = /(.+)/g;", SCRIPT)
    assert placeholder and placeholder.group(1) == PLACEHOLDER.pattern
    # Al cambiar de Sonnia se suelta el catálogo (otra app puede tener otras piezas).
    assert "closePrompts();" in SCRIPT


def test_los_bancos_se_editan_en_developer() -> None:
    tree = _tree()
    trivia = (
        "trivia-bank-info",
        "trivia-bank-load-btn",
        "trivia-bank-editor",
        "trivia-bank-input",
        "trivia-bank-save-btn",
        "trivia-bank-reset-btn",
        "trivia-bank-state",
    )
    games = (
        "game-bank-info",
        "game-bank-select",
        "game-bank-load-btn",
        "game-bank-detail",
        "game-bank-editor",
        "game-bank-input",
        "game-bank-save-btn",
        "game-bank-reset-btn",
        "game-bank-state",
    )
    for element in trivia:
        assert {"developer", "dev-trivia-bank"} <= set(tree.parents[element]), element
        assert "trivia" not in tree.parents[element], element
    for element in games:
        assert {"developer", "dev-game-banks"} <= set(tree.parents[element]), element
        assert "juegos" not in tree.parents[element], element
    assert 'data-cap-note="trivia_bank"' in _section("dev-trivia-bank")
    assert 'data-cap-note="game_banks"' in _section("dev-game-banks")
    # En el modo fácil queda solo la línea, con su enlace al bloque de Developer.
    for card, block in (("trivia", "dev-trivia-bank"), ("juegos", "dev-game-banks")):
        html = _section(card)
        assert "<textarea" not in html and "<details" not in html, card
        moved = re.search(r'<p class="bank-moved">(.*?)</p>', html)
        assert moved, card
        assert re.sub(r"<[^>]+>", "", moved.group(1)) == "Los bancos se editan en Developer.", card
        assert f'href="#{block}" data-open-developer' in html, card
    # «Avisos de hoy para Sonnia» sigue en el modo fácil.
    assert "developer" not in tree.parents["notes-input"]
    assert "avisos" in tree.parents["notes-input"]
