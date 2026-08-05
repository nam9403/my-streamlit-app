from __future__ import annotations

from core.liquid_universe import VN30_SYMBOLS, autopilot_universe_mode, resolve_scan_universe


def test_autopilot_universe_mode_defaults_dynamic_liquid(monkeypatch) -> None:
    monkeypatch.delenv("II_AUTOPILOT_UNIVERSE_MODE", raising=False)
    assert autopilot_universe_mode() == "dynamic_liquid"
    monkeypatch.setenv("II_AUTOPILOT_UNIVERSE_MODE", "liquid")
    assert autopilot_universe_mode() == "liquid"
    monkeypatch.setenv("II_AUTOPILOT_UNIVERSE_MODE", "vn30")
    assert autopilot_universe_mode() == "vn30"
    monkeypatch.setenv("II_AUTOPILOT_UNIVERSE_MODE", "rotate_full")
    assert autopilot_universe_mode() == "rotate_full"


def test_resolve_scan_universe_vn30_only(monkeypatch) -> None:
    monkeypatch.setenv("II_AUTOPILOT_UNIVERSE_MODE", "vn30")
    monkeypatch.setenv("II_UNIVERSE_AUTO_ROTATE", "0")
    syms, meta = resolve_scan_universe(30, full_listing=["ZZZ", "AAA"], rotation_day=1)
    assert meta["mode"] == "vn30"
    assert set(syms).issubset(set(VN30_SYMBOLS))
    assert "FPT" in syms
    assert "ZZZ" not in syms


def test_resolve_scan_universe_liquid_prefers_vn30(monkeypatch) -> None:
    monkeypatch.setenv("II_AUTOPILOT_UNIVERSE_MODE", "liquid")
    monkeypatch.setenv("II_UNIVERSE_AUTO_ROTATE", "0")
    full = [f"X{i:03d}" for i in range(50)] + list(VN30_SYMBOLS)
    syms, meta = resolve_scan_universe(20, full_listing=full, rotation_day=10)
    assert meta["mode"] == "liquid"
    # With rotate off and limit 20, first 20 of liquid pool = VN30 head
    assert all(s in VN30_SYMBOLS for s in syms)
    assert syms[0] == "ACB"


def test_resolve_scan_universe_rotate_full_covers_full_listing(monkeypatch) -> None:
    monkeypatch.setenv("II_AUTOPILOT_UNIVERSE_MODE", "rotate_full")
    monkeypatch.setenv("II_UNIVERSE_AUTO_ROTATE", "1")
    monkeypatch.setenv("II_UNIVERSE_ROTATE_STYLE", "sequential")
    full = [f"S{i:03d}" for i in range(100)]
    syms0, meta0 = resolve_scan_universe(10, full_listing=full, rotation_day=0, rotation_key="t")
    syms1, meta1 = resolve_scan_universe(10, full_listing=full, rotation_day=1, rotation_key="t")
    assert meta0["mode"] == "rotate_full"
    assert meta0["pool_size"] == 100
    assert len(syms0) == 10
    assert syms0 == full[0:10]
    assert syms1 == full[10:20]
    assert syms0 != syms1
