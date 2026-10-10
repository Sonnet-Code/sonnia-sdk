"""Prompts de la conversación editables desde la nube (``sonia.prompts.specs_conversa``).

Con los textos de la app, lo que se manda a GPT-Live y a su backend tiene que ser idéntico,
byte a byte, a lo de antes de hacerlo editable: se compara con las instantáneas de
``tests/data/prompts_conversa.json``, sacadas antes del cambio. Si cambias a propósito un
texto de la app, regenéralas con ``uv run --no-sync python -m tests.test_prompts_conversa``
desde ``server/`` y revisa el diff.

Sin red ni APIs: ajustes, registros y conocimiento de prueba.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

import sonia.live.engine as engine_module
from sonia.actions import build_default_registry
from sonia.actions.registry import ActionRegistry
from sonia.config import GestureSettings, LiveSettings, LLMSettings, Settings, VisionSettings
from sonia.live.prompts import LIVE_RULES, build_session_config, gallery_note
from sonia.live.vision import VisionNarrator
from sonia.persona import (
    DEFAULT_KNOWLEDGE_DIR,
    SYSTEM_PROMPT,
    knowledge_files,
    knowledge_prompt_id,
    load_knowledge,
)
from sonia.prompts import BOOK, PLACEHOLDER
from sonia.types import (
    ActionContext,
    ActionResult,
    ActionSpec,
    Frame,
    LLMEvent,
    Message,
    TextDelta,
    TurnDone,
)

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
        knowledge_dir=case.get("knowledge", KNOWLEDGE),
        notes=case.get("notes", ""),
        agenda=case.get("agenda", ""),
        clock_text=case.get("clock", ""),
        faces=case.get("faces", False),
    )
    return {
        "live": config["instructions"],
        "backend": config["delegation"]["responses"]["instructions"],
    }


AHORA = "Ahora: 10:00 Apertura en la sala principal. Después: 11:00 Charla de Kotlin."
ESCENA = "Dos personas con camisetas del DevFest y una gorra roja."


class FakeVisionLLM:
    """Modelo de visión falso: apunta lo que le piden."""

    def __init__(self) -> None:
        self.requests: list[list[Message]] = []

    async def stream(self, messages: list[Message]) -> AsyncIterator[LLMEvent]:
        self.requests.append(messages)
        yield TextDelta("Nadie.")
        yield TurnDone("Nadie.")


def narrator_messages() -> list[Message]:
    llm = FakeVisionLLM()
    asyncio.run(VisionNarrator(llm).describe(Frame(data=b"x")))
    (messages,) = llm.requests
    return messages


def request_prompts() -> dict[str, str]:
    """Lo que se manda en cada petición: visión, «look», animación de stand y notas del motor."""
    e = engine_module
    system, user = narrator_messages()
    return {
        "vision/narrador": str(system["content"]),
        "vision/pregunta": str(user["content"][0]["text"]),  # type: ignore[index]
        "vision/look": BOOK.text("vision/look", fallback=e.LOOK_IMAGE_TEXT),
        "momento/agenda": e.moment_prompt(e.moment_focus("agenda", AHORA)),
        "momento/camara": e.moment_prompt(e.moment_focus("cámara", ESCENA)),
        "momento/invitacion": e.moment_prompt(e.moment_focus("invitación")),
        "frase_stand": e.showcase_prompt("¡Acércate, que no muerdo!"),
        "texto_escrito": e.TEXT_INPUT_TEMPLATE.format(text="¿Dónde está el baño?"),
        "interrupcion": e.INTERRUPT_TEXT,
        "aviso": e.ANNOUNCE_TEMPLATE.format(text="La charla de las 11 cambia a la sala 2."),
        "avisos_del_dia": e.NOTES_TEMPLATE.format(text="Rifa a las cinco."),
        "avisos_retirados": e.NOTES_CLEARED_TEXT,
        "delegacion_fallida": e.DELEGATION_FAILED_TEXT,
        "agenda_cambiada": e.AGENDA_CHANGED_TEMPLATE.format(
            changes="La charla de Kotlin pasa a las 12:00."
        )
        + e.AGENDA_MORE_TEXT,
        "galeria": gallery_note(["nuevo"], ["viejo"], ["logo", "nuevo"], max_chars=1200),
    }


def build_snapshots() -> dict[str, Any]:
    return {
        "sesiones": {name: session_instructions(case) for name, case in CASES.items()},
        "peticiones": request_prompts(),
    }


def load_snapshots() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(SNAPSHOTS.read_text(encoding="utf-8"))
    return data


@pytest.fixture
def cloud() -> Iterator[Callable[[dict[str, str]], None]]:
    """Guarda versiones «de la nube» en el registro de la app y las quita al acabar."""

    def put(overrides: dict[str, str]) -> None:
        assert BOOK.set_overrides(overrides) == []

    yield put
    BOOK.set_overrides(None)


# -- sin regresión con los textos de la app ----------------------------------------------------


@pytest.mark.parametrize("name", sorted(CASES))
def test_con_los_textos_de_la_app_las_instrucciones_no_cambian(name: str) -> None:
    expected = load_snapshots()["sesiones"][name]
    got = session_instructions(CASES[name])
    assert got["live"] == expected["live"]
    assert got["backend"] == expected["backend"]


def test_con_los_textos_de_la_app_las_peticiones_no_cambian() -> None:
    assert request_prompts() == load_snapshots()["peticiones"]


def test_el_conocimiento_de_la_app_sale_igual_que_antes() -> None:
    """Lo de antes: los archivos del stand, sin el README, separados por una línea en blanco."""
    texts = [
        path.read_text(encoding="utf-8").strip()
        for path in sorted(DEFAULT_KNOWLEDGE_DIR.glob("*.md"))
        if path.name.lower() != "readme.md"
    ]
    assert load_knowledge() == "\n\n".join(text for text in texts if text)


def test_todo_lo_que_pide_el_codigo_esta_registrado(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: set[str] = set()
    real = BOOK.text

    def text(prompt_id: str, fallback: str | None = None) -> str:
        asked.add(prompt_id)
        return real(prompt_id, fallback)

    monkeypatch.setattr(BOOK, "text", text)
    for case in CASES.values():
        session_instructions(case)
    request_prompts()
    ours = {
        prompt_id
        for prompt_id in BOOK.ids()
        if prompt_id.split("/")[0] in ("sonnia", "conversacion", "backend", "vision", "animacion")
    }
    assert asked - set(BOOK.ids()) == set()  # nada sin registrar
    assert ours - asked == set()  # ni piezas registradas que no use nadie


def test_cada_pieza_de_la_app_vale_como_version_de_la_nube() -> None:
    """Se puede partir del texto de la app, retocarlo y guardarlo: sus marcadores son los suyos."""
    ids = [
        i
        for i in BOOK.ids()
        if i.split("/")[0]
        in ("sonnia", "conocimiento", "conversacion", "backend", "vision", "animacion")
    ]
    assert len(ids) > 60
    for prompt_id in ids:
        spec = BOOK.spec(prompt_id)
        text = BOOK.default(prompt_id)
        assert text.strip(), prompt_id
        assert BOOK.validate(prompt_id, text) == [], prompt_id
        assert set(PLACEHOLDER.findall(text)) == set(spec.fields), prompt_id
        if prompt_id != "sonnia/persona":  # la nube quita los espacios de los extremos
            assert text == text.strip(), prompt_id


def test_cada_archivo_de_conocimiento_es_una_pieza() -> None:
    files = knowledge_files(DEFAULT_KNOWLEDGE_DIR)
    assert files and all(path.name.lower() != "readme.md" for path in files)
    for path in files:
        prompt_id = knowledge_prompt_id(path)
        assert prompt_id is not None and prompt_id in BOOK
        assert BOOK.spec(prompt_id).group == "Conocimiento"
        assert BOOK.default(prompt_id) == path.read_text(encoding="utf-8").strip()
    assert (
        knowledge_prompt_id(Path("Información del Stand.md"))
        == "conocimiento/informaci-n-del-stand"
    )


# -- con versión de la nube: se usa esa, nunca las dos ---------------------------------------


def test_sonnia_usa_la_persona_de_la_nube(cloud: Callable[[dict[str, str]], None]) -> None:
    case = CASES["stand_look_completo"]
    before = session_instructions(case)
    cloud({"sonnia/persona": "Eres Sonia, la persona de la nube."})
    after = session_instructions(case)
    assert after["live"].startswith("Eres Sonia, la persona de la nube.\n\nCÓMO FUNCIONAS")
    assert SYSTEM_PROMPT.strip() not in after["live"]
    assert after["live"].count("Eres Sonia") == 1
    assert after["backend"] == before["backend"]


def test_conocimiento_usa_el_archivo_de_la_nube_en_su_sitio(
    cloud: Callable[[dict[str, str]], None],
) -> None:
    files = knowledge_files(DEFAULT_KNOWLEDGE_DIR)
    path = files[1]
    prompt_id = knowledge_prompt_id(path)
    assert prompt_id is not None
    original = path.read_text(encoding="utf-8").strip()
    nuevo = "# De la nube\n\nDato que solo está en la nube."
    cloud({prompt_id: nuevo})
    texts = [nuevo if p == path else p.read_text(encoding="utf-8").strip() for p in files]
    assert load_knowledge() == "\n\n".join(texts)
    config = session_instructions({"settings": {}, "registry": "basico", "knowledge": None})
    for text in config.values():
        assert text.count("Dato que solo está en la nube.") == 1
        assert original not in text
    # Solo la carpeta del stand: la de datos de prueba (la segunda) no cambia.
    assert original in load_knowledge([KNOWLEDGE, DEFAULT_KNOWLEDGE_DIR])
    assert "Dato que solo está en la nube." not in load_knowledge(
        [KNOWLEDGE, DEFAULT_KNOWLEDGE_DIR]
    )


NUEVAS_REGLAS = (
    "REGLAS DE LA NUBE\n{setting_rule}\n{clock_rule}\n{camera_rule}\n{trivia_rule}"
    "Delegation policy:\n{capabilities}\n\nDelegate to the backend when:\n"
    "{look_when}{moves_when}{trivia_when}{agenda_when}{search_when}\n"
    "Do not delegate to the backend when:\n{no_delegate_chat}"
)


def test_conversacion_usa_las_reglas_y_las_lineas_de_la_nube(
    cloud: Callable[[dict[str, str]], None],
) -> None:
    case = CASES["stand_look_completo"]
    before = session_instructions(case)
    cloud(
        {
            "conversacion/reglas": NUEVAS_REGLAS,
            "conversacion/delegar/gestos": "- Te pidan un baile: delégalo.",
            "conversacion/capacidades/show_image": "- Enseñar imágenes (nube).",
        }
    )
    after = session_instructions(case)
    live = after["live"]
    assert "REGLAS DE LA NUBE" in live
    assert "CÓMO FUNCIONAS (voz a voz en tiempo real)" not in live
    # Las líneas que se pegan conservan su salto de línea aunque la nube se lo quite.
    assert "- Te pidan un baile: delégalo.\n- El visitante quiera jugar a la trivia" in live
    assert "No te muevas por tu cuenta a cada rato" not in live
    assert live.count("- Enseñar imágenes (nube).") == 1
    assert "- Pantalla: mostrar junto a ti una imagen de la galería." not in live
    assert after["backend"] == before["backend"]


def test_una_version_de_la_nube_que_no_vale_se_ignora() -> None:
    try:
        warnings = BOOK.set_overrides(
            {
                "conversacion/reglas": "Sin marcadores. Delegation policy.",
                "backend/reglas": "Sin la marca del guion.",
                "conversacion/fecha_hora": "Sin la fecha.",
            }
        )
        assert len(warnings) == 3
        case = CASES["stand_look_completo"]
        assert session_instructions(case) == load_snapshots()["sesiones"]["stand_look_completo"]
    finally:
        BOOK.set_overrides(None)
    assert LIVE_RULES.startswith("CÓMO FUNCIONAS")


def test_backend_usa_sus_reglas_de_la_nube(cloud: Callable[[dict[str, str]], None]) -> None:
    case = CASES["reunion_obs"]
    before = session_instructions(case)
    cloud(
        {
            "backend/reglas": "Reglas del backend (nube). Si algo empieza por PARA SONIA:, pásalo.",
            "backend/galeria": "Galería (nube): {imagenes}.",
        }
    )
    after = session_instructions(case)
    assert after["backend"].startswith("Reglas del backend (nube).")
    assert "Eres el backend de Sonia" not in after["backend"]
    assert "Galería (nube): ninguna." in after["backend"]
    assert "Imágenes de la galería al empezar" not in after["backend"]
    assert after["live"] == before["live"]


def test_vision_usa_el_prompt_de_la_nube(cloud: Callable[[dict[str, str]], None]) -> None:
    cloud({"vision/narrador": "Describe la foto (nube).", "vision/pregunta": "¿Qué hay? (nube)"})
    system, user = narrator_messages()
    assert system["content"] == "Describe la foto (nube)."
    assert user["content"][0]["text"] == "¿Qué hay? (nube)"  # type: ignore[index]


def test_animacion_usa_los_momentos_de_la_nube(cloud: Callable[[dict[str, str]], None]) -> None:
    e = engine_module
    cloud(
        {
            "animacion/momento": "Momento (nube): {focus}",
            "animacion/momento/agenda": "Agenda (nube): {text}",
            "animacion/frase": "Di esto (nube): {text}",
        }
    )
    assert e.moment_prompt(e.moment_focus("agenda", "A las diez.")) == (
        "Momento (nube): Agenda (nube): A las diez."
    )
    assert e.moment_prompt(e.moment_focus("invitación")) == (
        "Momento (nube): " + e.MOMENT_FOCUS["invitación"]
    )
    assert e.showcase_prompt("¡Hola!") == "Di esto (nube): ¡Hola!"


def test_los_momentos_no_pasan_del_tope_de_un_append() -> None:
    for prompt_id in ("animacion/momento", "animacion/momento/camara", "animacion/frase"):
        assert BOOK.spec(prompt_id).max_len == engine_module.APPEND_MAX_CHARS
        assert BOOK.validate(prompt_id, "{focus}{text}" + "x" * 1_300)


if __name__ == "__main__":
    SNAPSHOTS.write_text(
        json.dumps(build_snapshots(), ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Instantáneas escritas en {SNAPSHOTS}")
