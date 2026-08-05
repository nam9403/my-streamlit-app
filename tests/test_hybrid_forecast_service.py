from __future__ import annotations

import pandas as pd

from core.hybrid_forecast_service import backtest_hybrid_forecast_1y, build_hybrid_3m_forecast


def _make_uptrend_ohlcv(n: int = 420) -> pd.DataFrame:
    base = 100.0
    closes = []
    vols = []
    for i in range(n):
        closes.append(base + i * 0.22 + (i % 7) * 0.03)
        vols.append(1_000_000 + (i % 20) * 5000)
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": vols,
        }
    )


def test_build_hybrid_3m_forecast_returns_output() -> None:
    ohlcv = _make_uptrend_ohlcv(360)
    current_price = float(ohlcv["close"].iloc[-1])
    out = build_hybrid_3m_forecast(ohlcv, current_price=current_price, horizon_days=63)
    assert out is not None
    assert out.horizon_days == 63
    assert out.train_rows >= 80
    assert out.expected_price > 0


def test_backtest_hybrid_forecast_1y_has_metrics() -> None:
    ohlcv = _make_uptrend_ohlcv(420)
    stat = backtest_hybrid_forecast_1y(ohlcv, horizon_days=63, test_window_days=220)
    assert int(stat.get("samples") or 0) > 0
    assert stat.get("hit_rate_pct") is not None
    assert isinstance(stat.get("model_mix"), dict)
