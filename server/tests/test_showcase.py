"""Animación de stand: elección de números (su paso por el motor está en test_live)."""

from __future__ import annotations

import random
from pathlib import Path

from sonia.showcase import ATTENTION_DANCE, ATTENTION_FOURTH_WALL, Showcase, load_lines


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


def test_los_momentos_salen_con_su_probabilidad_y_sin_texto() -> None:
    show = Showcase(
        ["a", "b"],
        [],
        dance_chance=0.0,
        gesture_chance=0.0,
        moment_chance=1.0,
        rng=random.Random(3),
    )
    bits = [show.next_bit() for _ in range(10)]
    assert all(bit is not None and bit.moment and bit.text == "" for bit in bits)
    mixed = Showcase(["a", "b"], [], dance_chance=0.0, moment_chance=0.5, rng=random.Random(4))
    kinds = {bit.moment for bit in (mixed.next_bit() for _ in range(40)) if bit is not None}
    assert kinds == {True, False}
    # Sin frases fijas, todo lo que no es baile son momentos.
    only = Showcase([], [], moment_chance=0.6)
    bit = only.next_bit()
    assert only.enabled and bit is not None and bit.moment
