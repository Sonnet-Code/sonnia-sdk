"""Los textos completos que reciben los modelos, en varias configuraciones (sin red).

Los usa ``test_prompts.py`` para la no regresión del editor de prompts (``docs/prompts.md``):
con los prompts por defecto, cada texto tiene que salir idéntico, byte a byte, al de la
referencia ``data/prompts_referencia.json``, sacada de la rama de partida antes del editor.
Si se cambia un texto por defecto a propósito, se regenera la referencia con
``uv run --no-sync python ../scripts/prompts_referencia.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from sonia.actions import build_default_registry
from sonia.config import (
    AudioSettings,
    GestureSettings,
    LiveSettings,
    LLMSettings,
    Settings,
    ShowcaseSettings,
    VisionSettings,
    WSSettings,
)
from sonia.games.registry import all_games
from sonia.gestures import GestureCatalog, build_system_prompt
from sonia.gestures.prompt import Cooldowns, build_request_message, build_user_message
from sonia.live.prompts import build_session_config
from sonia.live.vision import VisionNarrator
from sonia.llm import Completion
from sonia.types import Frame, Message, TurnDone
from sonia.vision.judge import ModelJudge
from sonia.vision.referee import GeminiReferee

__all__ = ["KNOWLEDGE", "render_shared_cases", "settings_for"]

#: Conocimiento de prueba (el de ``assets/knowledge`` cambia sin tocar código).
KNOWLEDGE = {
    "01-evento.md": "# El evento\n\nEl DevFest Santo Domingo 2026 es el 9 y 10 de octubre.",
    "02-sonnet.md": "# Sonnet Code\n\nSonnet Code hace software a medida con IA.",
    "README.md": "Esto no lo lee Sonia.",
}

NOTES = "La charla de IA se movió a la sala B."
AGENDA = "AGENDA DE HOY (sábado 10 de octubre):\n- 09:00 Apertura, sala principal."
CLOCK = "sábado 10 de octubre de 2026, 09:15"
FRAME = Frame(data=b"\xff\xd8jpeg-de-prueba", mime="image/jpeg", width=4, height=3)

#: Un catálogo de gestos pequeño, con los campos que salen en el prompt.
CATALOG: dict[str, Any] = {
    "type": "gesture_catalog",
    "character": "Sage",
    "gestures": [
        {
            "name": "wave",
            "frequency": "Standard",
            "timing": "Short",
            "impact": "LowImpact",
            "intensity": 2,
            "description": "Waves hello.",
            "intents": ["To Greet"],
            "intent_description": "USE: Greeting\nDO NOT USE: Goodbyes",
            "tags": ["personality:Friendly"],
        },
        {
            "name": "noImpact01",
            "frequency": "Standard",
            "lists": ["Utility_NoImpact"],
            "impact": "NoImpact",
            "special": True,
        },
        {"name": "bigCheer", "frequency": "Rare", "impact": "HighImpact", "intents": ["To Cheer"]},
    ],
}


def settings_for(
    tmp_path: Path,
    *,
    vision_source: str = "opencv",
    on_turn_start: bool = False,
    web_search: bool = True,
    gestures: bool = True,
    meeting: bool = False,
    gallery_watch: float = 5.0,
    llm_base_url: str = "https://api.openai.com/v1",
) -> Settings:
    """Ajustes fijos, sin ``.env``: lo que cambia es lo que mueve las instrucciones."""
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        live=LiveSettings(api_key="clave-de-prueba", backend_web_search=web_search),
        llm=LLMSettings(
            base_url=llm_base_url,
            model="modelo-de-vision",
            api_key="clave",
            supports_vision=True,
        ),
        gestures=GestureSettings(enabled=gestures, gemini_api_key=""),
        audio=AudioSettings(),
        vision=VisionSettings(source=vision_source, on_turn_start=on_turn_start),  # type: ignore[arg-type]
        ws=WSSettings(host="127.0.0.1", port=0),
        showcase=ShowcaseSettings(enabled=False),
        assets_dir=str(tmp_path),
        meeting=meeting,
        gallery_watch_seconds=gallery_watch,
    )


def _knowledge_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "conocimiento"
    directory.mkdir(exist_ok=True)
    for name, text in KNOWLEDGE.items():
        (directory / name).write_text(text, encoding="utf-8")
    return directory


def _session_cases(tmp_path: Path) -> dict[str, str]:
    knowledge = _knowledge_dir(tmp_path)
    full_registry = build_default_registry(
        include_look=True, include_trivia=True, include_agenda=True, games=all_games()
    )
    cases: dict[str, tuple[Settings, Any, dict[str, Any]]] = {
        "sesion/stand_look_completo": (
            settings_for(tmp_path),
            full_registry,
            {
                "gallery_ids": ["logo-gdg", "mapa"],
                "notes": NOTES,
                "agenda": AGENDA,
                "clock_text": CLOCK,
                "faces": True,
            },
        ),
        "sesion/stand_notas_minimo": (
            settings_for(
                tmp_path, on_turn_start=True, web_search=False, gestures=False, gallery_watch=0.0
            ),
            build_default_registry(include_look=True),
            {"gallery_ids": []},
        ),
        "sesion/sin_camara": (
            settings_for(tmp_path, vision_source="none"),
            build_default_registry(include_look=False, include_trivia=True),
            {"gallery_ids": ["a"], "clock_text": CLOCK},
        ),
        "sesion/reunion_look": (
            settings_for(tmp_path, vision_source="obs", meeting=True),
            build_default_registry(include_look=True, include_agenda=True),
            {"gallery_ids": [], "faces": True, "notes": NOTES},
        ),
        "sesion/reunion_notas": (
            settings_for(tmp_path, vision_source="screen", on_turn_start=True),
            build_default_registry(include_look=True),
            {"gallery_ids": ["logo"]},
        ),
        "sesion/unity_look": (
            settings_for(tmp_path, vision_source="unity", web_search=False),
            build_default_registry(include_look=True, include_trivia=True),
            {"gallery_ids": []},
        ),
        "sesion/vision_local_notas": (
            settings_for(tmp_path, on_turn_start=True, llm_base_url="http://127.0.0.1:8000/v1"),
            build_default_registry(include_look=True, games=all_games()),
            {"gallery_ids": [], "agenda": AGENDA},
        ),
        "sesion/sin_registro": (settings_for(tmp_path), None, {"gallery_ids": []}),
    }
    out: dict[str, str] = {}
    for name, (settings, registry, kwargs) in cases.items():
        config = build_session_config(
            settings, registry=registry, knowledge_dir=knowledge, **kwargs
        )
        responses = config["delegation"]["responses"]
        out[name + "/gpt_live"] = config["instructions"]
        out[name + "/backend"] = responses["instructions"]
        # El resto de la sesión (herramientas, modelo, voz), sin repetir las instrucciones.
        rest = {**config, "instructions": "<gpt_live>"}
        rest["delegation"] = {
            **config["delegation"],
            "responses": {**responses, "instructions": "<backend>"},
        }
        out[name + "/config"] = json.dumps(rest, ensure_ascii=False, indent=1, sort_keys=True)
    return out


class _NarratorLLM:
    """El modelo de visión del narrador: graba los mensajes y contesta algo fijo."""

    def __init__(self) -> None:
        self.messages: list[list[Message]] = []

    def stream(self, messages: list[Message]) -> Any:
        self.messages.append(messages)

        async def events() -> Any:
            yield TurnDone(content="Una persona con camisa azul.")

        return events()


class _CompleteLLM:
    """Un modelo con ``complete``: graba los mensajes y contesta ``answer``."""

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.messages: list[list[Message]] = []

    async def complete(self, messages: list[Message]) -> Completion:
        self.messages.append(messages)
        return Completion(content=self.answer)


class _Camera:
    async def capture(self, *, max_width: int | None = None, quality: int | None = None) -> Frame:
        return FRAME


def _dump(messages: list[Message]) -> str:
    return json.dumps(messages, ensure_ascii=False, indent=1, sort_keys=True)


async def _model_cases() -> dict[str, str]:
    out: dict[str, str] = {}

    narrator_llm = _NarratorLLM()
    await VisionNarrator(narrator_llm).describe(FRAME)
    out["vision/narrador"] = _dump(narrator_llm.messages[0])

    catalog = GestureCatalog.from_message(CATALOG)
    out["gestos/sistema"] = build_system_prompt(catalog)
    out["gestos/apertura"] = build_user_message(
        opening=True, user_text="Hola, ¿qué tal?", said=[], recent=()
    )
    out["gestos/frase"] = build_user_message(
        opening=False,
        user_text="¿Qué hace Sonnet Code?",
        said=["Sonnet Code hace software."],
        phrase_text="Y también inteligencia artificial.",
        phrase_index=2,
        phrase_age_s=1.25,
        recent=(("wave", 30.0), ("bigCheer", 200.0)),
        cooldowns=Cooldowns(rare_left_s=100.0, uncommon_left_s=10.0, repeated=("wave",)),
    )
    out["gestos/peticion"] = build_request_message("tocarse un ojo")

    judge_llm = _CompleteLLM('{"visto": true, "objeto": "botella azul"}')
    await ModelJudge(judge_llm, _Camera()).ask("¿Alguien enseña algo azul a la cámara?")
    out["juez/busqueda"] = _dump(judge_llm.messages[0])

    frame = np.zeros((48, 64, 3), dtype=np.uint8)
    poses_llm = _CompleteLLM('{"personas": 1, "brazos_arriba": 1}')
    await GeminiReferee(poses_llm, timeout_s=60.0).poses(frame)
    out["juez/poses"] = _dump(_without_image(poses_llm.messages[0]))
    hands_llm = _CompleteLLM('{"manos": ["piedra"]}')
    await GeminiReferee(hands_llm, timeout_s=60.0).hands(frame)
    out["juez/manos"] = _dump(_without_image(hands_llm.messages[0]))
    return out


def _without_image(messages: list[Message]) -> list[Message]:
    """Los mensajes sin la foto (el JPEG puede cambiar con la versión de OpenCV)."""
    out: list[Message] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            content = [part for part in content if part.get("type") != "image_url"]
            message = {**message, "content": content}
        out.append(message)
    return out


async def render_shared_cases(tmp_path: Path) -> dict[str, str]:
    """Las instrucciones de GPT-Live y del backend, la visión, los gestos y los jueces."""
    out = _session_cases(tmp_path)
    out.update(await _model_cases())
    return out
