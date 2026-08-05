from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def return_series_from_ohlcv(ohlcv: pd.DataFrame) -> pd.Series:
    if ohlcv is None or ohlcv.empty or "close" not in ohlcv.columns:
        return pd.Series(dtype=float)
    d = ohlcv.copy()
    d["close"] = pd.to_numeric(d["close"], errors="coerce")
    d = d.dropna(subset=["close"])
    if len(d) < 40:
        return pd.Series(dtype=float)
    return d["close"].pct_change().dropna().astype(float)


@dataclass(frozen=True)
class OptimizedPortfolio:
    weights: dict[str, float]
    expected_return_annual_pct: float
    volatility_annual_pct: float
    sharpe_ratio: float


def mean_variance_optimize(
    *,
    expected_returns_annual: dict[str, float],
    covariance_annual: pd.DataFrame,
    min_weight: float = 0.0,
    max_weight: float = 0.75,
    risk_free_rate: float = 0.03,
    random_trials: int = 6000,
    random_seed: int = 42,
) -> OptimizedPortfolio:
    assets = [k for k in expected_returns_annual.keys() if k in covariance_annual.index and k in covariance_annual.columns]
    if not assets:
        return OptimizedPortfolio(weights={}, expected_return_annual_pct=0.0, volatility_annual_pct=0.0, sharpe_ratio=0.0)
    cov = covariance_annual.loc[assets, assets].to_numpy(dtype=float)
    mu = np.array([float(expected_returns_annual[a]) for a in assets], dtype=float)
    rng = np.random.default_rng(seed=random_seed)
    best_score = -1e18
    best_w = np.zeros(len(assets), dtype=float)

    for _ in range(max(1000, int(random_trials))):
        w = rng.dirichlet(alpha=np.ones(len(assets)))
        if np.any(w < min_weight) or np.any(w > max_weight):
            continue
        w = w / np.sum(w)
        port_ret = float(np.dot(w, mu))
        port_var = float(w @ cov @ w.T)
        port_vol = float(np.sqrt(max(port_var, 1e-12)))
        sharpe = (port_ret - risk_free_rate) / max(port_vol, 1e-6)
        if sharpe > best_score:
            best_score = sharpe
            best_w = w

    if np.sum(best_w) <= 0:
        best_w = np.ones(len(assets), dtype=float) / len(assets)
    port_ret = float(np.dot(best_w, mu))
    port_var = float(best_w @ cov @ best_w.T)
    port_vol = float(np.sqrt(max(port_var, 1e-12)))
    sharpe = (port_ret - risk_free_rate) / max(port_vol, 1e-6)
    weights = {a: round(float(w), 4) for a, w in zip(assets, best_w)}
    return OptimizedPortfolio(
        weights=weights,
        expected_return_annual_pct=round(port_ret * 100.0, 2),
        volatility_annual_pct=round(port_vol * 100.0, 2),
        sharpe_ratio=round(float(sharpe), 3),
    )


def stress_test_portfolio(weights: dict[str, float]) -> list[dict[str, Any]]:
    """
    Stress test đơn giản:
    - market_drop_10: tài sản rủi ro giảm theo beta xấp xỉ.
    - rate_up_1pct: tăng lãi suất gây co hẹp định giá (tech/stock nhạy hơn benchmark).
    """
    w_stock = float(weights.get("stock", 0.0))
    w_bench = float(weights.get("benchmark", 0.0))
    w_cash = float(weights.get("cash", 0.0))

    # Scenario 1: thị trường giảm 10%
    shock_stock = -0.13
    shock_bench = -0.10
    pnl_market = (w_stock * shock_stock) + (w_bench * shock_bench) + (w_cash * 0.0)

    # Scenario 2: lãi suất +1% (co hẹp multiple)
    shock_stock_rate = -0.08
    shock_bench_rate = -0.05
    pnl_rate = (w_stock * shock_stock_rate) + (w_bench * shock_bench_rate) + (w_cash * 0.0)

    return [
        {
            "scenario": "market_drop_10pct",
            "assumption": "Thị trường chung giảm 10%",
            "estimated_portfolio_impact_pct": round(pnl_market * 100.0, 2),
        },
        {
            "scenario": "rate_up_1pct",
            "assumption": "Lãi suất tăng +1%",
            "estimated_portfolio_impact_pct": round(pnl_rate * 100.0, 2),
        },
    ]


def build_portfolio_protector(
    *,
    stock_symbol: str,
    stock_ohlcv: pd.DataFrame,
    benchmark_ohlcv: pd.DataFrame,
    expected_return_3m_pct: float,
) -> dict[str, Any]:
    stock_ret = return_series_from_ohlcv(stock_ohlcv)
    bench_ret = return_series_from_ohlcv(benchmark_ohlcv)

    if stock_ret.empty or bench_ret.empty:
        weights = {"stock": 0.4, "benchmark": 0.3, "cash": 0.3}
        stress = stress_test_portfolio(weights)
        return {
            "optimized_weights": weights,
            "optimizer_note": "Fallback weights do du lieu lich su chua du day.",
            "sharpe_ratio": None,
            "expected_return_annual_pct": None,
            "volatility_annual_pct": None,
            "stress_test": stress,
        }

    n = min(len(stock_ret), len(bench_ret), 240)
    stock_ret = stock_ret.tail(n).reset_index(drop=True)
    bench_ret = bench_ret.tail(n).reset_index(drop=True)
    cash_ret = pd.Series(np.zeros(n, dtype=float))
    frame = pd.DataFrame({"stock": stock_ret, "benchmark": bench_ret, "cash": cash_ret})
    cov_annual = frame.cov() * 252.0

    stock_mu = max(-0.40, min(0.90, (_safe_float(expected_return_3m_pct) / 100.0) * (252.0 / 63.0)))
    bench_mu = float(frame["benchmark"].mean() * 252.0)
    cash_mu = 0.03
    expected = {"stock": stock_mu, "benchmark": bench_mu, "cash": cash_mu}

    opt = mean_variance_optimize(
        expected_returns_annual=expected,
        covariance_annual=cov_annual,
        min_weight=0.0,
        max_weight=0.75,
        risk_free_rate=0.03,
        random_trials=5000,
        random_seed=42,
    )
    weights = opt.weights if opt.weights else {"stock": 0.4, "benchmark": 0.3, "cash": 0.3}
    stress = stress_test_portfolio(weights)
    return {
        "optimized_weights": weights,
        "optimizer_note": f"Tối ưu mean-variance cho {stock_symbol.upper()} + benchmark + cash.",
        "sharpe_ratio": opt.sharpe_ratio,
        "expected_return_annual_pct": opt.expected_return_annual_pct,
        "volatility_annual_pct": opt.volatility_annual_pct,
        "stress_test": stress,
    }
