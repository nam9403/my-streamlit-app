from __future__ import annotations

import pandas as pd

from core.engine import build_investment_context


def test_build_investment_context_derives_financials_when_provider_fails(monkeypatch) -> None:
    import core.engine as eng

    monkeypatch.setenv("II_STRICT_REAL_FINANCIAL_DATA", "0")
    ohlcv = pd.DataFrame(
        {
            "date": pd.date_range("2025-01-01", periods=80, freq="B"),
            "open": [10.0] * 80,
            "high": [11.0] * 80,
            "low": [9.0] * 80,
            "close": [10.5] * 80,
            "volume": [1000.0] * 80,
        }
    )
    snapshot = {
        "revenue": 1200.0,
        "revenue_prev": 1000.0,
        "net_income": 120.0,
        "net_income_prev": 100.0,
        "cost_of_goods_sold": 700.0,
        "debt": 200.0,
        "shareholders_equity": 400.0,
    }

    monkeypatch.setattr(eng, "fetch_ohlcv_history", lambda *a, **k: ohlcv.copy())
    monkeypatch.setattr(eng, "fetch_latest_news", lambda *a, **k: [])
    monkeypatch.setattr(eng, "fetch_financial_indicators", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))

    ctx = build_investment_context("FPT", snapshot, sessions=80, news_limit=5, fast_mode=True)
    fin = ctx.get("financials") or {}
    assert fin.get("source") == "snapshot_derived"
    assert fin.get("gross_margin") is not None
