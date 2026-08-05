from __future__ import annotations

import pandas as pd
import pytest


@pytest.fixture
def _scan_mocks(monkeypatch):
    import core.scanner_service as ss

    def fake_snapshot(sym: str):
        return {"symbol": sym, "price": 100.0}

    def fake_report(sym: str, snap: dict, profile: str, capital: float, quick_mode: bool = True):
        return {
            "valuation": {
                "price": 100.0,
                "margin_of_safety_composite_pct": 25.0 if sym == "AAA" else 5.0,
                "piotroski_score": 8 if sym == "AAA" else 5,
                "industry_subtype_label_vi": "Test",
            },
            "financials": {"revenue_growth_yoy": 20.0 if sym == "AAA" else 3.0},
            "phase": {"phase": "breakout" if sym == "AAA" else "neutral", "metrics": {"vol_multiple": 1.6 if sym == "AAA" else 1.0}},
        }

    def fake_ohlcv(sym: str):
        return pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=30, freq="D"),
                "open": [1.0] * 30,
                "high": [1.0] * 30,
                "low": [1.0] * 30,
                "close": [1.0] * 30,
                "volume": [500_000.0] * 30,
            }
        )

    monkeypatch.setattr(ss, "load_snapshot_cached", fake_snapshot)
    monkeypatch.setattr(ss, "load_strategic_report_cached", fake_report)
    monkeypatch.setattr(ss, "load_ohlcv_cached", fake_ohlcv)
    # scan path gọi _load_scan_ohlcv → fetch_ohlcv_history trước; mock này tránh live HTTP.
    monkeypatch.setattr(ss, "_load_scan_ohlcv", fake_ohlcv)
    return ss


def test_scan_respects_preselect_limit_cap(monkeypatch, _scan_mocks) -> None:
    ss = _scan_mocks
    universe = tuple(f"S{i:03d}" for i in range(400))

    monkeypatch.setenv("II_SCAN_PRESELECT_LIMIT_CAP", "80")

    out = ss.scan_potential_stocks.__wrapped__(universe, "growth", 100_000.0)  # type: ignore[attr-defined]
    assert len(out) <= 80
    assert int(ss.st.session_state["scan_deep_universe_count"]) <= 80


def test_scan_int_env_clamps_invalid(monkeypatch, _scan_mocks) -> None:
    ss = _scan_mocks
    monkeypatch.setenv("II_SCAN_SYMBOL_BATCH_SIZE", "not-a-number")
    monkeypatch.setenv("II_SCAN_MAX_WORKERS", "99")
    df = ss.scan_potential_stocks.__wrapped__(("AAA", "BBB"), "growth", 100_000.0)  # type: ignore[attr-defined]
    assert not df.empty

def test_scan_int_env_public_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    import core.scanner_service as ss

    monkeypatch.delenv("II_SCAN_INT_UNIT_TEST", raising=False)
    assert ss._scan_int_env("II_SCAN_INT_UNIT_TEST", 10, 1, 20) == 10
    monkeypatch.setenv("II_SCAN_INT_UNIT_TEST", "not-int")
    assert ss._scan_int_env("II_SCAN_INT_UNIT_TEST", 10, 1, 20) == 10
    monkeypatch.setenv("II_SCAN_INT_UNIT_TEST", "15")
    assert ss._scan_int_env("II_SCAN_INT_UNIT_TEST", 10, 1, 20) == 15
    monkeypatch.setenv("II_SCAN_INT_UNIT_TEST", "50")
    assert ss._scan_int_env("II_SCAN_INT_UNIT_TEST", 10, 1, 20) == 20


def test_load_scan_ohlcv_prefers_disk_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    import scrapers.portal as portal
    import core.scanner_service as ss

    cached = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=30, freq="D"),
            "close": [1.0] * 30,
            "volume": [1.0] * 30,
        }
    )
    calls = {"live": 0}

    def boom(*_a, **_k):
        calls["live"] += 1
        raise AssertionError("live fetch must not run when disk-first cache hits")

    monkeypatch.setenv("II_SCAN_OHLCV_DISK_FIRST", "1")
    monkeypatch.setattr(ss, "load_ohlcv_cached", lambda _sym: cached)
    monkeypatch.setattr(portal, "fetch_ohlcv_history", boom)
    out = ss._load_scan_ohlcv("FPT")
    assert len(out) == 30
    assert calls["live"] == 0
