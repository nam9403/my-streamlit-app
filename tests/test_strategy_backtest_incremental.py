from __future__ import annotations

import numpy as np
import pandas as pd

from core.engine import compute_technical_indicators, detect_market_phase_at_index, detect_market_phase_from_ohlcv
from core.strategy_backtest import run_phase_signal_backtest


def _sample_ohlcv(n: int = 200, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    price = 100 + np.cumsum(rng.normal(0, 0.4, size=n))
    return pd.DataFrame(
        {
            "date": pd.date_range("2022-01-01", periods=n, freq="B"),
            "open": price - 0.2,
            "high": price + 0.6,
            "low": price - 0.6,
            "close": price,
            "volume": rng.uniform(800_000, 1_500_000, size=n),
        }
    )


def test_detect_market_phase_at_index_matches_window_method() -> None:
    df = _sample_ohlcv(180)
    ti = compute_technical_indicators(df)
    for i in range(60, len(df)):
        expected = detect_market_phase_from_ohlcv(df.iloc[: i + 1]).phase
        actual = detect_market_phase_at_index(df, ti, i).phase
        assert actual == expected, f"mismatch at index {i}"


def test_incremental_backtest_produces_valid_equity_curve() -> None:
    df = _sample_ohlcv(220)
    bench = pd.Series(df["close"].values, index=df["date"].dt.normalize())
    res = run_phase_signal_backtest(df, bench, warmup=60)
    assert len(res.equity_app) == len(df) - 60
    assert res.app_return_pct == float(res.app_return_pct)
    assert isinstance(res.trades, list)
