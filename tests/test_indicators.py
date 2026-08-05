from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.indicators import add_engine_technical_indicators, compute_macd, wilder_rsi


def test_wilder_rsi_matches_ewm_formula() -> None:
    """RSI must use Wilder EWM (alpha=1/period), not SMA rolling."""
    close = pd.Series([100.0 + i * (1 if i % 2 == 0 else -0.5) for i in range(40)])
    rsi = wilder_rsi(close, period=14)
    delta = close.diff()
    up = delta.clip(lower=0.0)
    down = (-delta).clip(lower=0.0)
    avg_up = up.ewm(alpha=1.0 / 14, adjust=False).mean()
    avg_down = down.ewm(alpha=1.0 / 14, adjust=False).mean()
    rs = avg_up / avg_down.replace(0, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        expected = 100.0 - (100.0 / (1.0 + rs))
    no_loss = avg_down.fillna(0.0) <= 1e-12
    expected = expected.mask(no_loss & (avg_up > 1e-12), 100.0)
    expected = expected.mask(no_loss & (avg_up <= 1e-12), 50.0)
    expected = pd.to_numeric(expected, errors="coerce")
    pd.testing.assert_series_equal(rsi, expected.astype(float), check_names=False)


def test_wilder_rsi_uptrend_is_high() -> None:
    close = pd.Series(np.linspace(50.0, 100.0, 30))
    rsi = wilder_rsi(close, period=14)
    assert float(rsi.iloc[-1]) > 65.0


def test_wilder_rsi_oscillates_not_stuck_at_100() -> None:
    """Regression: loss clip(upper=0) made RSI stuck at 100 forever."""
    rng = np.random.default_rng(42)
    steps = rng.normal(0.0, 1.0, size=80)
    close = pd.Series(100.0 + np.cumsum(steps))
    rsi = wilder_rsi(close, period=14).dropna()
    assert float(rsi.min()) < 90.0
    assert float(rsi.max()) > 10.0
    assert not bool((rsi >= 99.5).all())


def test_compute_macd_returns_three_series() -> None:
    close = pd.Series(np.linspace(10.0, 20.0, 60))
    macd, signal, hist = compute_macd(close)
    assert len(macd) == len(close)
    assert len(signal) == len(close)
    assert len(hist) == len(close)
    assert float(hist.iloc[-1]) == pytest.approx(float(macd.iloc[-1] - signal.iloc[-1]), rel=1e-6)


def test_engine_indicators_include_macd_columns() -> None:
    df = pd.DataFrame(
        {
            "open": np.linspace(10, 20, 60),
            "high": np.linspace(10.5, 20.5, 60),
            "low": np.linspace(9.5, 19.5, 60),
            "close": np.linspace(10, 20, 60),
            "volume": [1_000_000.0] * 60,
        }
    )
    out = add_engine_technical_indicators(df)
    assert "rsi14" in out.columns
    assert "macd" in out.columns
    assert "macd_signal" in out.columns
    assert "macd_hist" in out.columns
    assert pd.notna(out["rsi14"].iloc[-1])
