"""Pruebas de la persona y de la base de conocimiento editable."""

from __future__ import annotations

from pathlib import Path

from sonia.persona import SYSTEM_PROMPT, host_of, is_local_host, load_knowledge


def test_load_knowledge_concatena_en_orden_e_ignora_readme(tmp_path: Path) -> None:
    (tmp_path / "02-b.md").write_text("Segundo\n", encoding="utf-8")
    (tmp_path / "01-a.md").write_text("Primero\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("No debe entrar", encoding="utf-8")
    (tmp_path / "notas.txt").write_text("Tampoco", encoding="utf-8")

    text = load_knowledge(tmp_path)

    assert text == "Primero\n\nSegundo"


def test_load_knowledge_sin_directorio_devuelve_vacio(tmp_path: Path) -> None:
    assert load_knowledge(tmp_path / "no-existe") == ""


def test_la_base_de_conocimiento_del_repo_existe_y_cabe_en_el_prompt() -> None:
    """La carpeta real assets/knowledge se carga y no se dispara de tamaño."""
    text = load_knowledge()
    assert "DevFest Santo Domingo 2026" in text
    assert "Sonnet Code" in text
    assert len(text.split()) < 3000, "la base de conocimiento cuenta como tokens en cada turno"


def test_persona_es_staff_y_hace_cumplidos_seguros() -> None:
    assert "staff" in SYSTEM_PROMPT
    assert "cumplido" in SYSTEM_PROMPT
    assert "nunca sobre el cuerpo" in SYSTEM_PROMPT


def test_la_persona_no_presume_de_correr_en_local() -> None:
    assert "no inventes detalles técnicos ni digas que corres en local" in SYSTEM_PROMPT
    assert "glosario" not in SYSTEM_PROMPT


def test_host_of_y_is_local_host() -> None:
    assert host_of("https://API.openai.com/v1") == "api.openai.com"
    assert host_of("no es una url") == ""
    assert is_local_host("localhost")
    assert is_local_host("192.168.1.20")
    assert is_local_host("sonia.local")
    assert not is_local_host("api.openai.com")
