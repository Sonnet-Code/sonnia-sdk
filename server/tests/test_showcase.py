"""Idle animation: picking bits (how the engine plays them is tested in test_live)."""

from __future__ import annotations

import random
from pathlib import Path

from sonia.showcase import ATTENTION_DANCE, ATTENTION_FOURTH_WALL, Showcase, load_lines


def write_showcase(tmp_path: Path, phrases: list[str], songs: list[str]) -> Path:
    directory = tmp_path / "showcase"
    directory.mkdir(exist_ok=True)
    (directory / "lines.md").write_text(
        "# comment\n\n" + "\n".join(phrases) + "\n", encoding="utf-8"
    )
    (directory / "chants.md").write_text("\n".join(songs) + "\n", encoding="utf-8")
    return directory


def test_load_lines_skips_comments_and_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "lines.md"
    path.write_text("# title\n\n  Hello  \n\n#another\nGoodbye\n", encoding="utf-8")
    assert load_lines(path) == ["Hello", "Goodbye"]
    assert load_lines(tmp_path / "missing.md") == []


def test_showcase_does_not_repeat_and_respects_chances(tmp_path: Path) -> None:
    directory = write_showcase(tmp_path, ["a", "b", "c"], ["la la"])
    show = Showcase.from_dir(directory, dance_chance=0.0, gesture_chance=1.0)
    show.rng = random.Random(1)
    assert show.enabled
    seen = [show.next_bit() for _ in range(30)]
    assert all(bit is not None and bit.attention == ATTENTION_FOURTH_WALL for bit in seen)
    texts = [bit.text for bit in seen if bit is not None]
    assert all(a != b for a, b in zip(texts, texts[1:], strict=False)), (
        "must not repeat back to back"
    )

    dancer = Showcase(["a"], ["la la", "na na"], dance_chance=1.0, rng=random.Random(2))
    bit = dancer.next_bit()
    assert bit is not None and bit.is_dance and bit.attention == ATTENTION_DANCE

    assert Showcase([], []).next_bit() is None
    assert not Showcase([], []).enabled


def test_moments_come_with_their_chance_and_no_text() -> None:
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
    # Without fixed lines, everything that is not a dance is a moment.
    only = Showcase([], [], moment_chance=0.6)
    bit = only.next_bit()
    assert only.enabled and bit is not None and bit.moment
