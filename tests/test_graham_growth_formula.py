from __future__ import annotations

import logging

import pytest

from core.config import (
    GRAHAM_CLASSIC_AAA_YIELD_PCT,
    GRAHAM_GROWTH_G_CAP_PCT,
    VN_10Y_BOND_YIELD_DEFAULT_PCT,
    get_settings,
    resolve_vn_10y_bond_yield_pct,
)
from core.valuation import (
    benjamin_graham_value,
    graham_growth_divergence_notes,
    normalize_graham_growth_pct,
    value_investing_summary,
)


def test_normalize_growth_caps_at_15() -> None:
    meta = normalize_graham_growth_pct(40.0)
    assert meta["g_pct"] == GRAHAM_GROWTH_G_CAP_PCT
    assert meta["g_capped"] is True
    assert meta["g_raw_pct"] == 40.0


def test_normalize_growth_negative_falls_back() -> None:
    meta = normalize_graham_growth_pct(-3.0)
    assert meta["g_pct"] == 0.0
    assert meta["g_negative"] is True
    assert meta["fallback_to_graham_number"] is True


def test_benjamin_graham_uses_vn_yield_and_g_cap() -> None:
    # V = EPS × (8.5 + 2×15) × (4.4 / 6.5)
    v_capped = benjamin_graham_value(1000.0, 40.0, bond_yield_pct=6.5)
    v_at_15 = benjamin_graham_value(1000.0, 15.0, bond_yield_pct=6.5)
    assert abs(v_capped - v_at_15) < 1e-6
    expected = 1000.0 * (8.5 + 2.0 * 15.0) * (GRAHAM_CLASSIC_AAA_YIELD_PCT / 6.5)
    assert abs(v_capped - expected) < 1e-6


def test_benjamin_graham_default_y_from_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VN_10Y_BOND_YIELD", raising=False)
    monkeypatch.delenv("II_VN_10Y_BOND_YIELD", raising=False)
    monkeypatch.delenv("II_DEFAULT_BOND_YIELD_PCT", raising=False)
    monkeypatch.delenv("BOND_YIELD_PCT", raising=False)
    get_settings.cache_clear()
    v = benjamin_graham_value(1000.0, 5.0)
    y = VN_10Y_BOND_YIELD_DEFAULT_PCT
    expected = 1000.0 * (8.5 + 10.0) * (GRAHAM_CLASSIC_AAA_YIELD_PCT / y)
    assert abs(v - expected) < 1e-6


def test_vn_10y_env_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VN_10Y_BOND_YIELD", "7.0")
    monkeypatch.delenv("II_VN_10Y_BOND_YIELD", raising=False)
    monkeypatch.delenv("II_DEFAULT_BOND_YIELD_PCT", raising=False)
    monkeypatch.delenv("BOND_YIELD_PCT", raising=False)
    get_settings.cache_clear()
    assert resolve_vn_10y_bond_yield_pct() == 7.0
    assert get_settings().vn_10y_bond_yield_pct == 7.0


def test_divergence_warning_logs(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="core.valuation"):
        notes = graham_growth_divergence_notes(
            200_000.0,
            graham_capped=80_000.0,
            sector_pe_fair=90_000.0,
            symbol="ABC",
        )
    assert len(notes) >= 1
    assert any("Graham Growth" in n for n in notes)
    assert any("Graham Growth" in r.message for r in caplog.records)


def test_summary_caps_g_and_exposes_graham_growth() -> None:
    snap = {
        "symbol": "GG",
        "name": "Growth",
        "price": 50_000.0,
        "currency": "VND",
        "eps": 3_000.0,
        "growth_rate_pct": 45.0,
        "book_value_per_share": 20_000.0,
        "bond_yield_pct": 6.5,
        "source": "test",
        "piotroski": {},
        "roe_5y_avg": 20.0,
        "sector_pe_5y_avg": 12.0,
    }
    s = value_investing_summary(snap)
    assert float(s.get("growth_rate_pct") or 0) == GRAHAM_GROWTH_G_CAP_PCT
    assert float(s.get("growth_rate_pct_raw") or 0) == 45.0
    assert s.get("growth_rate_pct_capped") is True
    assert float(s.get("graham_growth_value") or 0) > 0
    assert float(s.get("vn_10y_bond_yield_pct") or 0) == 6.5
    assert any("trần" in str(n).lower() or "graham growth" in str(n).lower() for n in (s.get("pe_sanity_notes") or []))


def test_negative_g_keeps_graham_number_fallback() -> None:
    snap = {
        "symbol": "NG",
        "name": "NegGrowth",
        "price": 50_000.0,
        "currency": "VND",
        "eps": 3_000.0,
        "growth_rate_pct": -5.0,
        "book_value_per_share": 20_000.0,
        "bond_yield_pct": 6.5,
        "source": "test",
        "piotroski": {},
        "roe_5y_avg": 20.0,
    }
    s = value_investing_summary(snap)
    assert s.get("graham_growth_used") is False
    assert float(s.get("growth_rate_pct") or 0) == 0.0
    assert any("graham number" in str(n).lower() or "g_calc" in str(n).lower() for n in (s.get("pe_sanity_notes") or []))
