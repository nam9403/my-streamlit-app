from __future__ import annotations

import pandas as pd
import pytest


def test_unified_live_skips_ohlcv_and_applies_fresh_quote(monkeypatch: pytest.MonkeyPatch) -> None:
    import scrapers.financial_data as fd

    monkeypatch.setenv("II_ALIGN_PRICE_WITH_OHLCV", "1")
    monkeypatch.setenv("II_SNAPSHOT_ATTACH_LIVE", "0")
    monkeypatch.setenv("II_UNIFIED_LIVE_PRICE", "1")

    ohlcv_calls = {"n": 0}
    quote_calls = {"n": 0}

    def fake_fetch_ohlcv(sym: str, sessions: int = 80):
        ohlcv_calls["n"] += 1
        df = pd.DataFrame([{"date": "2025-01-01", "close": 11.0, "open": 10.0, "high": 12.0, "low": 9.0, "volume": 1.0}])
        df.attrs["source"] = "test_ohlcv"
        return df

    def fake_get(sym: str, **kw):
        quote_calls["n"] += 1
        assert kw.get("use_cache") is False
        return {"price": 61_500.0, "source": "cafef_hose"}

    monkeypatch.setattr("scrapers.portal.fetch_ohlcv_history", fake_fetch_ohlcv)
    monkeypatch.setattr("scrapers.finance_scraper.get_stock_data", fake_get)

    row: dict = {"price": 59_300.0, "source": "vietstock"}
    fd._resolve_snapshot_market_price(row, "VNM")
    assert ohlcv_calls["n"] == 0
    assert quote_calls["n"] == 1
    assert row["price"] == 61_500.0
    assert str(row.get("price_source") or "").startswith("quote_fresh:")


def test_unified_skip_duplicate_avoids_second_get_stock_data(monkeypatch: pytest.MonkeyPatch) -> None:
    import scrapers.financial_data as fd

    monkeypatch.setenv("II_UNIFIED_LIVE_PRICE", "1")
    monkeypatch.setenv("II_ALIGN_PRICE_WITH_OHLCV", "1")
    monkeypatch.setenv("II_SNAPSHOT_ATTACH_LIVE", "0")

    calls = {"n": 0}

    def fake_get(sym: str, **kw):
        calls["n"] += 1
        return {"price": 61_000.0, "source": "cafef_hose"}

    monkeypatch.setattr("scrapers.finance_scraper.get_stock_data", fake_get)

    row: dict = {"price": 61_000.0, "source": "cafef_hose"}
    fd._resolve_snapshot_market_price(row, "VNM", skip_duplicate_live_quote=True)
    assert calls["n"] == 0
    assert str(row.get("price_source") or "").startswith("quote_fresh:")


def test_unified_off_still_aligns_with_ohlcv_when_plausible(monkeypatch: pytest.MonkeyPatch) -> None:
    import scrapers.financial_data as fd

    monkeypatch.setenv("II_ALIGN_PRICE_WITH_OHLCV", "1")
    monkeypatch.setenv("II_SNAPSHOT_ATTACH_LIVE", "0")
    monkeypatch.setenv("II_UNIFIED_LIVE_PRICE", "0")

    fresh = pd.Timestamp.now().normalize().strftime("%Y-%m-%d")

    def fake_fetch_ohlcv(sym: str, sessions: int = 80):
        df = pd.DataFrame(
            [{"date": fresh, "close": 60_000.0, "open": 59_000.0, "high": 61_000.0, "low": 58_000.0, "volume": 1e6}]
        )
        df.attrs["source"] = "vn_ohlcv"
        return df

    monkeypatch.setattr("scrapers.portal.fetch_ohlcv_history", fake_fetch_ohlcv)

    row: dict = {"price": 59_800.0, "source": "vietstock"}
    fd._resolve_snapshot_market_price(row, "VNM")
    assert float(row["price"]) == 60_000.0
    assert "ohlcv_session_close" in str(row.get("price_source") or "")


def test_stale_ohlcv_does_not_overwrite_quote_when_unified_off(monkeypatch: pytest.MonkeyPatch) -> None:
    import scrapers.financial_data as fd

    monkeypatch.setenv("II_ALIGN_PRICE_WITH_OHLCV", "1")
    monkeypatch.setenv("II_SNAPSHOT_ATTACH_LIVE", "0")
    monkeypatch.setenv("II_UNIFIED_LIVE_PRICE", "0")
    monkeypatch.setenv("II_OHLCV_PRICE_MAX_STALE_DAYS", "3")

    def fake_fetch_ohlcv(sym: str, sessions: int = 80):
        df = pd.DataFrame(
            [
                {
                    "date": "2026-04-29",
                    "close": 44_750.0,
                    "open": 44_000.0,
                    "high": 45_000.0,
                    "low": 43_000.0,
                    "volume": 1e6,
                }
            ]
        )
        df.attrs["source"] = "store_stale"
        return df

    def fake_get(sym: str, **kw):
        return {"price": 30_100.0, "source": "vietstock"}

    monkeypatch.setattr("scrapers.portal.fetch_ohlcv_history", fake_fetch_ohlcv)
    monkeypatch.setattr("scrapers.finance_scraper.get_stock_data", fake_get)

    row: dict = {"price": 28_100.0, "source": "vietstock"}
    fd._resolve_snapshot_market_price(row, "DPG")
    # Không lấy 44,750 từ kho cũ; ưu tiên quote live
    assert float(row["price"]) == 30_100.0
    assert "ohlcv_session_close" not in str(row.get("price_source") or "")


def test_ensure_request_time_live_price_overrides_warehouse(monkeypatch: pytest.MonkeyPatch) -> None:
    import scrapers.financial_data as fd

    def fake_get(sym: str, **kw):
        assert kw.get("use_cache") is False
        return {"price": 30_050.0, "source": "cafef_hose"}

    monkeypatch.setattr("scrapers.finance_scraper.get_stock_data", fake_get)

    row = {"symbol": "DPG", "price": 44_750.0, "price_source": "ohlcv_session_close:store"}
    out = fd.ensure_request_time_live_price(row, "DPG")
    assert float(out["price"]) == 30_050.0
    assert str(out.get("price_source") or "").startswith("request_live:")
