from __future__ import annotations

from core.universe_rotation import rotation_offset, rotation_style, slice_universe, universe_auto_rotate_enabled


def test_rotation_offset_bounded(monkeypatch) -> None:
    monkeypatch.setenv("II_UNIVERSE_AUTO_ROTATE", "1")
    monkeypatch.setenv("II_UNIVERSE_ROTATE_STYLE", "hash")
    assert universe_auto_rotate_enabled() is True
    assert rotation_style() == "hash"
    off = rotation_offset(total=1000, window=120, key="k", day_ordinal=42_000)
    assert 0 <= off <= 1000 - 120


def test_rotation_offset_zero_when_total_small() -> None:
    assert rotation_offset(total=50, window=120, key="k", day_ordinal=1) == 0


def test_slice_universe() -> None:
    syms = list("ABCDEFGHIJ")
    assert slice_universe(syms, offset=2, limit=3) == ["C", "D", "E"]


def test_slice_universe_wraps() -> None:
    syms = list("ABCDEFGHIJ")
    assert slice_universe(syms, offset=8, limit=4) == ["I", "J", "A", "B"]


def test_rotation_offset_sequential(monkeypatch) -> None:
    monkeypatch.setenv("II_UNIVERSE_ROTATE_STYLE", "sequential")
    assert rotation_style() == "sequential"
    # day=0 → 0; day=1 → window; day=2 → 2*window
    assert rotation_offset(total=100, window=10, key="k", day_ordinal=0) == 0
    assert rotation_offset(total=100, window=10, key="k", day_ordinal=1) == 10
    assert rotation_offset(total=100, window=10, key="k", day_ordinal=2) == 20
