from __future__ import annotations

import pandas as pd

from core.probabilistic_forecast_service import (
    estimate_gbm_mu_sigma,
    monte_carlo_forecast_range,
    signal_alignment_summary,
)


def _ohlcv(n: int = 260) -> pd.DataFrame:
    prices = [100 + i * 0.08 + (i % 5) * 0.03 for i in range(n)]
    return pd.DataFrame({"close": prices})


def test_estimate_gbm_mu_sigma_returns_reasonable_bounds() -> None:
    mu, sigma = estimate_gbm_mu_sigma(_ohlcv(260))
    assert -0.5 <= mu <= 0.8
    assert 0.05 <= sigma <= 1.2


def test_monte_carlo_forecast_range_basic() -> None:
    out = monte_carlo_forecast_range(
        s0=100.0,
        horizon_days=63,
        mu_annual=0.15,
        sigma_annual=0.25,
        simulations=5000,
        target_price=108.0,
        random_seed=7,
    )
    assert out is not None
    assert out.p10_price < out.p50_price < out.p90_price
    assert 0.0 <= out.prob_reach_target_pct <= 100.0


def test_signal_alignment_detects_conflict() -> None:
    res = signal_alignment_summary(
        phase_name="distribution",
        f_score=8,
        mos_pct=18.0,
        news=[{"title": "Công ty bị điều tra và xử phạt"}],
    )
    assert res["stand_aside"] is True
