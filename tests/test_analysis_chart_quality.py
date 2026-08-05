from __future__ import annotations

import pandas as pd

from core.analysis_chart_panel import (
    _daily_coverage_ratio,
    _merge_ohlcv_primary_with_fallback,
    _technical_signal_score,
    render_candlestick_with_intrinsic,
)


def _make_ohlcv(close_values: list[float], start: str = "2026-01-01") -> pd.DataFrame:
    n = len(close_values)
    close = pd.Series(close_values, dtype=float)
    open_ = close.shift(1).fillna(close.iloc[0])
    high = pd.concat([open_, close], axis=1).max(axis=1) + 0.8
    low = pd.concat([open_, close], axis=1).min(axis=1) - 0.8
    return pd.DataFrame(
        {
            "date": pd.bdate_range(start=start, periods=n),
            "open": open_.to_list(),
            "high": high.to_list(),
            "low": low.to_list(),
            "close": close.to_list(),
            "volume": [1_000_000] * n,
        }
    )


def test_technical_signal_score_strong_buy_on_uptrend() -> None:
    uptrend = [20 + i * 0.9 for i in range(90)]
    df = _make_ohlcv(uptrend)
    score, label, reasons = _technical_signal_score(df)
    assert score >= 60
    assert label in {"BUY", "STRONG BUY"}
    assert reasons


def test_technical_signal_score_sell_on_downtrend() -> None:
    downtrend = [120 - i * 1.0 for i in range(90)]
    df = _make_ohlcv(downtrend)
    score, label, reasons = _technical_signal_score(df)
    assert score <= 45
    assert label in {"WATCH", "REDUCE", "SELL"}
    assert reasons


def test_daily_coverage_ratio_detects_missing_business_days() -> None:
    full = _make_ohlcv([50 + i * 0.1 for i in range(30)])
    sparse = full.drop(index=[5, 11, 20]).reset_index(drop=True)

    ratio, actual, expected, missing = _daily_coverage_ratio(sparse)
    assert expected >= actual
    assert ratio < 1.0
    assert len(missing) >= 3


def test_merge_ohlcv_primary_with_fallback_fills_missing_rows() -> None:
    full = _make_ohlcv([40 + i * 0.3 for i in range(25)])
    primary = full.drop(index=[3, 8, 13]).reset_index(drop=True)
    fallback = full.copy()

    merged = _merge_ohlcv_primary_with_fallback(primary, fallback)
    assert len(merged) == len(full)
    assert "backfill" in str(merged.attrs.get("source", ""))


def test_render_candlestick_modes_smoke(monkeypatch) -> None:
    df = _make_ohlcv([30 + i * 0.2 for i in range(80)])
    valuation = {"composite_target_price": 42.0}

    # Patch streamlit outputs to keep test in pure unit mode.
    monkeypatch.setattr("core.analysis_chart_panel.st.plotly_chart", lambda *args, **kwargs: None)
    monkeypatch.setattr("core.analysis_chart_panel.st.line_chart", lambda *args, **kwargs: None)
    monkeypatch.setattr("core.analysis_chart_panel.st.bar_chart", lambda *args, **kwargs: None)
    monkeypatch.setattr("core.analysis_chart_panel.st.pyplot", lambda *args, **kwargs: None)
    monkeypatch.setattr("core.analysis_chart_panel.st.caption", lambda *args, **kwargs: None)
    monkeypatch.setattr("core.analysis_chart_panel.st.warning", lambda *args, **kwargs: None)

    render_candlestick_with_intrinsic(df, valuation, chart_engine="plotly", compatibility_mode=False)
    render_candlestick_with_intrinsic(df, valuation, chart_engine="matplotlib", compatibility_mode=False)
    render_candlestick_with_intrinsic(df, valuation, chart_engine="plotly", compatibility_mode=True)
