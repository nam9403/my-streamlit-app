from __future__ import annotations

import pandas as pd

from core.portfolio_protector_service import (
    build_portfolio_protector,
    mean_variance_optimize,
    stress_test_portfolio,
)


def _ohlcv(start: float, drift: float, n: int = 260) -> pd.DataFrame:
    close = [start + i * drift + (i % 5) * 0.1 for i in range(n)]
    return pd.DataFrame(
        {
            "open": close,
            "high": [x * 1.01 for x in close],
            "low": [x * 0.99 for x in close],
            "close": close,
            "volume": [1_000_000 + (i % 10) * 2000 for i in range(n)],
        }
    )


def test_mean_variance_optimize_returns_valid_weights() -> None:
    cov = pd.DataFrame(
        [[0.09, 0.04, 0.0], [0.04, 0.06, 0.0], [0.0, 0.0, 0.0001]],
        columns=["stock", "benchmark", "cash"],
        index=["stock", "benchmark", "cash"],
    )
    out = mean_variance_optimize(
        expected_returns_annual={"stock": 0.18, "benchmark": 0.11, "cash": 0.03},
        covariance_annual=cov,
        min_weight=0.0,
        max_weight=0.75,
        random_trials=2000,
    )
    assert out.weights
    assert abs(sum(out.weights.values()) - 1.0) < 1e-3
    assert out.sharpe_ratio is not None


def test_stress_test_portfolio_returns_scenarios() -> None:
    rows = stress_test_portfolio({"stock": 0.5, "benchmark": 0.3, "cash": 0.2})
    assert len(rows) == 2
    assert rows[0]["scenario"] == "market_drop_10pct"


def test_build_portfolio_protector_integration() -> None:
    stock = _ohlcv(100, 0.25, n=280)
    bench = _ohlcv(1000, 0.12, n=280)
    out = build_portfolio_protector(
        stock_symbol="FPT",
        stock_ohlcv=stock,
        benchmark_ohlcv=bench,
        expected_return_3m_pct=12.0,
    )
    w = out.get("optimized_weights") or {}
    assert "stock" in w and "benchmark" in w and "cash" in w
    assert abs(sum(float(v) for v in w.values()) - 1.0) < 0.05
    assert isinstance(out.get("stress_test"), list)
