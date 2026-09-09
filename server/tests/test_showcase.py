"""Animación de stand: elección de números y su paso por el orquestador."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import pytest

from sonia.config import ShowcaseSettings
from sonia.showcase import ATTENTION_DANCE, ATTENTION_FOURTH_WALL, Showcase, load_lines
from tests.test_orchestrator import SlowTTS, make_rig, text_handler


def write_showcase(tmp_path: Path, phrases: list[str], songs: list[str]) -> Path:
    directory = tmp_path / "showcase"
    directory.mkdir(exist_ok=True)
    (directory / "frases.md").write_text(
        "# comentario\n\n" + "\n".join(phrases) + "\n", encoding="utf-8"
    )
    (directory / "cantos.md").write_text("\n".join(songs) + "\n", encoding="utf-8")
    return directory


def test_load_lines_ignora_comentarios_y_vacias(tmp_path: Path) -> None:
    path = tmp_path / "frases.md"
    path.write_text("# titulo\n\n  Hola  \n\n#otra\nAdiós\n", encoding="utf-8")
    assert load_lines(path) == ["Hola", "Adiós"]
    assert load_lines(tmp_path / "no-existe.md") == []


def test_showcase_no_repite_y_respeta_probabilidades(tmp_path: Path) -> None:
    directory = write_showcase(tmp_path, ["a", "b", "c"], ["la la"])
    show = Showcase.from_dir(directory, dance_chance=0.0, gesture_chance=1.0)
    show.rng = random.Random(1)
    assert show.enabled
    seen = [show.next_bit() for _ in range(30)]
    assert all(bit is not None and bit.attention == ATTENTION_FOURTH_WALL for bit in seen)
    texts = [bit.text for bit in seen if bit is not None]
    assert all(a != b for a, b in zip(texts, texts[1:], strict=False)), "no debe repetir seguido"

    dancer = Showcase(["a"], ["la la", "na na"], dance_chance=1.0, rng=random.Random(2))
    bit = dancer.next_bit()
    assert bit is not None and bit.is_dance and bit.attention == ATTENTION_DANCE

    assert Showcase([], []).next_bit() is None
    assert not Showcase([], []).enabled


async def test_frase_ambiental_no_cambia_de_estado(tmp_path: Path) -> None:
    write_showcase(tmp_path, ["Hola, soy Sonia."], [])
    captured: list[dict[str, Any]] = []
    show = ShowcaseSettings(
        first_delay_seconds=0.05,
        interval_min_seconds=5.0,
        interval_max_seconds=5.0,
        dance_chance=0.0,
    )
    async with make_rig(
        tmp_path, text_handler(captured, "Hola"), captured=captured, tick=0.05, showcase=show
    ) as rig:
        await rig.rec.wait_type("speech_end", limit=5.0)
        starts = rig.rec.of_type("speech_start")
        assert starts and starts[0]["ambient"] is True
        assert starts[0]["text"] == "Hola, soy Sonia."
        assert rig.rec.audio(starts[0]["utterance_id"]), "la frase lleva audio"
        # El estado no se ha movido de idle: el avatar sigue en su idle o bailando.
        assert rig.rec.states() == ["idle"]
        # Pero al micrófono se le avisó de que sonaba la voz de Sonia.
        assert rig.speaking[:1] == [True]
        assert captured == [], "la animación de stand no llama al modelo"


async def test_baile_cantado_envia_attention_antes_de_la_voz(tmp_path: Path) -> None:
    write_showcase(tmp_path, [], ["La la la"])
    captured: list[dict[str, Any]] = []
    show = ShowcaseSettings(
        first_delay_seconds=0.05,
        interval_min_seconds=5.0,
        interval_max_seconds=5.0,
        dance_chance=1.0,
    )
    async with make_rig(
        tmp_path, text_handler(captured, "Hola"), captured=captured, tick=0.05, showcase=show
    ) as rig:
        await rig.rec.wait_type("speech_end", limit=5.0)
        kinds = rig.rec.kinds()
        assert kinds.index("attention") < kinds.index("speech_start")
        attention = rig.rec.of_type("attention")[0]
        assert attention["category"] == ATTENTION_DANCE
        assert rig.rec.states() == ["idle"]


async def test_un_turno_corta_la_frase_ambiental(tmp_path: Path) -> None:
    write_showcase(tmp_path, ["Una frase larguísima que no termina nunca de decirse."], [])
    captured: list[dict[str, Any]] = []
    show = ShowcaseSettings(
        first_delay_seconds=0.05,
        interval_min_seconds=5.0,
        interval_max_seconds=5.0,
        dance_chance=0.0,
    )
    async with make_rig(
        tmp_path,
        text_handler(captured, "Respuesta"),
        captured=captured,
        tick=0.05,
        tts=SlowTTS(delay=0.05, ms_per_char=40.0, tone=True),
        showcase=show,
    ) as rig:
        await rig.rec.wait_type("speech_start", limit=5.0)
        assert rig.orch.ambient_active
        await rig.send({"type": "text_input", "text": "hola"})
        await rig.rec.wait_type("stop_speaking", limit=5.0)
        await rig.rec.wait_state("speaking", limit=5.0)
        assert not rig.orch.ambient_active
        starts = rig.rec.of_type("speech_start")
        assert starts[0].get("ambient") is True
        assert all("ambient" not in s for s in starts[1:]), "la respuesta real no es ambiental"


@pytest.mark.parametrize("enabled", [False])
async def test_desactivada_por_configuracion(tmp_path: Path, enabled: bool) -> None:
    write_showcase(tmp_path, ["Hola"], [])
    captured: list[dict[str, Any]] = []
    show = ShowcaseSettings(enabled=enabled, first_delay_seconds=0.05)
    async with make_rig(
        tmp_path, text_handler(captured, "Hola"), captured=captured, tick=0.05, showcase=show
    ) as rig:
        with pytest.raises(TimeoutError):
            await rig.rec.wait_type("speech_start", limit=0.6)
