"""Pruebas de la persona y de la base de conocimiento editable."""

from __future__ import annotations

from pathlib import Path

from sonia.config import LLMSettings, Settings, STTSettings, TTSSettings, VisionSettings
from sonia.persona import SYSTEM_PROMPT, build_system_prompt, describe_stack, load_knowledge


def test_load_knowledge_concatena_en_orden_e_ignora_readme(tmp_path: Path) -> None:
    (tmp_path / "02-b.md").write_text("Segundo\n", encoding="utf-8")
    (tmp_path / "01-a.md").write_text("Primero\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("No debe entrar", encoding="utf-8")
    (tmp_path / "notas.txt").write_text("Tampoco", encoding="utf-8")

    text = load_knowledge(tmp_path)

    assert text == "Primero\n\nSegundo"


def test_load_knowledge_sin_directorio_devuelve_vacio(tmp_path: Path) -> None:
    assert load_knowledge(tmp_path / "no-existe") == ""


def test_build_system_prompt_incluye_persona_conocimiento_galeria_y_extra(tmp_path: Path) -> None:
    (tmp_path / "01-evento.md").write_text("# Evento\nDato del evento", encoding="utf-8")

    prompt = build_system_prompt(
        gallery_ids=["logo-sonnet"], extra="ACCIONES", knowledge_dir=tmp_path
    )

    assert prompt.startswith(SYSTEM_PROMPT)
    assert "BASE DE CONOCIMIENTO" in prompt
    assert "Dato del evento" in prompt
    assert "logo-sonnet" in prompt
    assert prompt.endswith("ACCIONES")
    assert prompt.index("Dato del evento") < prompt.index("logo-sonnet") < prompt.index("ACCIONES")


def test_build_system_prompt_sin_conocimiento_no_anade_seccion(tmp_path: Path) -> None:
    prompt = build_system_prompt(knowledge_dir=tmp_path / "vacio")
    assert "BASE DE CONOCIMIENTO" not in prompt
    assert prompt == SYSTEM_PROMPT


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


def _settings(**kw: object) -> Settings:
    base: dict[str, object] = {
        "llm": LLMSettings(base_url="http://localhost:8000/v1", model="modelo-local"),
        "stt": STTSettings(backend="faster_whisper", model="small"),
        "tts": TTSSettings(backend="omnivoice"),
        "vision": VisionSettings(source="opencv", on_turn_start=True),
    }
    base.update(kw)
    return Settings(**base)  # type: ignore[arg-type]


def test_describe_stack_todo_local() -> None:
    text = describe_stack(_settings(), action_names=["look", "show_image"])
    assert "TODO CORRE EN LOCAL" in text
    assert "modelo-local" in text
    assert "OmniVoice en local" in text
    assert "faster-whisper, modelo small" in text
    assert "look, show_image" in text
    assert "PROVISIONAL" not in text


def test_describe_stack_marca_lo_provisional_en_la_nube() -> None:
    settings = _settings(
        llm=LLMSettings(base_url="https://api.moonshot.ai/v1", model="kimi-k3"),
        tts=TTSSettings(backend="gemini"),
        vision=VisionSettings(source="none"),
    )
    text = describe_stack(settings)
    assert "API de Kimi" in text
    assert "Gemini Live" in text
    assert "HAY COMPONENTES PROVISIONALES" in text
    assert "no puedes ver a nadie" in text
    assert "Acciones disponibles: ninguna" in text


def test_build_system_prompt_incluye_el_stack_al_final(tmp_path: Path) -> None:
    prompt = build_system_prompt(knowledge_dir=tmp_path, stack="TU STACK AHORA MISMO: prueba")
    assert prompt.endswith("TU STACK AHORA MISMO: prueba")
