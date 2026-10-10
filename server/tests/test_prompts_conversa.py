"""Prompts de la conversación editables desde la nube (``sonia.prompts.specs_conversa``).

Con los textos de la app, lo que se manda a GPT-Live y a su backend tiene que ser idéntico,
byte a byte, a lo de antes de hacerlo editable: se compara con las instantáneas de
``tests/data/prompts_conversa.json``, sacadas antes del cambio. Si cambias a propósito un
texto de la app, regénalas con ``uv run --no-sync python -m tests.test_prompts_conversa``
desde ``server/`` y revisa el diff.

Sin red ni APIs: ajustes, registros y conocimiento de prueba.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sonia.actions import build_default_registry
from sonia.actions.registry import ActionRegistry
from sonia.config import GestureSettings, LiveSettings, LLMSettings, Settings, VisionSettings
from sonia.live.prompts import build_session_config
from sonia.types import ActionContext, ActionResult, ActionSpec

DATA = Path(__file__).parent / "data"
SNAPSHOTS = DATA / "prompts_conversa.json"
KNOWLEDGE = DATA / "conocimiento"

NOTES = "Hoy a las cinco hay rifa de camisetas en el stand de Sonnet Code."
AGENDA = (
    "AGENDA DEL DEVFEST (prueba):\n- 10:00 Apertura, sala principal.\n- 11:00 Charla de Kotlin."
)
CLOCK = "viernes 9 de octubre de 2026, las diez y media de la mañana"


def snapshot_settings(
    *,
    vision_source: str = "opencv",
    on_turn_start: bool = False,
    interval: float = 0.0,
    meeting: bool = False,
    web_search: bool = True,
    gestures: bool = True,
    gallery_watch: float = 0.0,
    llm_url: str = "https://api.openai.com/v1",
    supports_vision: bool = True,
) -> Settings:
    """Ajustes fijos, sin ``.env``: solo cambia lo que toca a las instrucciones."""
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        live=LiveSettings(api_key="clave-de-prueba", backend_web_search=web_search),
        llm=LLMSettings(
            base_url=llm_url,
            model="modelo-de-vision",
            api_key="clave",
            supports_vision=supports_vision,
        ),
        gestures=GestureSettings(enabled=gestures, api_key="", gemini_api_key=""),
        vision=VisionSettings(
            source=vision_source,  # type: ignore[arg-type]
            on_turn_start=on_turn_start,
            interval_seconds=interval,
        ),
        meeting=meeting,
        gallery_watch_seconds=gallery_watch,
        assets_dir=str(DATA),
    )


async def _no_game(arguments: dict[str, Any], context: ActionContext) -> ActionResult:
    raise AssertionError("no se ejecuta")


def snapshot_registry(kind: str) -> ActionRegistry | None:
    if kind == "completo":
        return build_default_registry(include_look=True, include_trivia=True, include_agenda=True)
    if kind == "basico":
        return build_default_registry(include_look=True)
    if kind == "sin_look":
        return build_default_registry(include_look=False, include_trivia=True, include_agenda=True)
    if kind == "juegos":
        # Solo el nombre de ``start_game``: la línea de los juegos es de ``sonia.games``.
        registry = ActionRegistry()
        registry.register(
            ActionSpec(
                name="start_game",
                description="Empieza un juego.",
                parameters={"type": "object", "properties": {}},
                handler=_no_game,  # type: ignore[arg-type]
            )
        )
        return registry
    assert kind == "ninguno"
    return None


#: Configuraciones representativas: cámara notes, look y none; reunión sí y no; caras, búsqueda,
#: gestos, galería, avisos, agenda y hora, con y sin.
CASES: dict[str, dict[str, Any]] = {
    "stand_look_completo": {
        "settings": {"gallery_watch": 5.0},
        "registry": "completo",
        "gallery": ["logo-sonnet", "equipo"],
        "notes": NOTES,
        "agenda": AGENDA,
        "clock": CLOCK,
        "faces": True,
    },
    "stand_notas_local": {
        "settings": {
            "on_turn_start": True,
            "llm_url": "http://localhost:1234/v1",
            "web_search": False,
            "gestures": False,
        },
        "registry": "basico",
    },
    "stand_notas_nube_caras": {
        "settings": {"interval": 30.0},
        "registry": "completo",
        "faces": True,
        "notes": NOTES,
    },
    "sin_camara": {
        "settings": {"vision_source": "none"},
        "registry": "sin_look",
        "gallery": ["logo-sonnet"],
        "agenda": AGENDA,
        "clock": CLOCK,
    },
    "sin_modelo_de_vision": {
        "settings": {"supports_vision": False, "gallery_watch": 5.0},
        "registry": "basico",
        "faces": True,
    },
    "unity_look": {
        "settings": {"vision_source": "unity", "gestures": False},
        "registry": "basico",
        "clock": CLOCK,
    },
    "reunion_obs": {
        "settings": {"vision_source": "obs"},
        "registry": "basico",
        "notes": NOTES,
        "clock": CLOCK,
    },
    "reunion_meet_sin_camara": {
        "settings": {"meeting": True, "vision_source": "none"},
        "registry": "sin_look",
        "agenda": AGENDA,
    },
    "reunion_pantalla_notas": {
        "settings": {"vision_source": "screen", "on_turn_start": True},
        "registry": "completo",
        "faces": True,
        "gallery": ["equipo"],
    },
    "sin_acciones": {
        "settings": {"web_search": False, "vision_source": "none"},
        "registry": "ninguno",
    },
    "solo_juegos": {
        "settings": {"web_search": False, "vision_source": "none", "gestures": False},
        "registry": "juegos",
        "notes": NOTES,
    },
}


def session_instructions(case: dict[str, Any]) -> dict[str, str]:
    """Las instrucciones de GPT-Live y del backend de una configuración."""
    config = build_session_config(
        snapshot_settings(**case["settings"]),
        registry=snapshot_registry(case["registry"]),
        gallery_ids=list(case.get("gallery", [])),
        knowledge_dir=KNOWLEDGE,
        notes=case.get("notes", ""),
        agenda=case.get("agenda", ""),
        clock_text=case.get("clock", ""),
        faces=case.get("faces", False),
    )
    return {
        "live": config["instructions"],
        "backend": config["delegation"]["responses"]["instructions"],
    }


def build_snapshots() -> dict[str, Any]:
    return {"sesiones": {name: session_instructions(case) for name, case in CASES.items()}}


def load_snapshots() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(SNAPSHOTS.read_text(encoding="utf-8"))
    return data


@pytest.mark.parametrize("name", sorted(CASES))
def test_con_los_textos_de_la_app_las_instrucciones_no_cambian(name: str) -> None:
    expected = load_snapshots()["sesiones"][name]
    got = session_instructions(CASES[name])
    assert got["live"] == expected["live"]
    assert got["backend"] == expected["backend"]


if __name__ == "__main__":
    SNAPSHOTS.write_text(
        json.dumps(build_snapshots(), ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Instantáneas escritas en {SNAPSHOTS}")
