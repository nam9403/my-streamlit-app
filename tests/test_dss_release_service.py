from __future__ import annotations

from core.dss_release_service import evaluate_dss_readiness


def test_evaluate_dss_readiness_commercial_ready() -> None:
    report = {
        "probabilistic_forecast": {
            "forecast_range": {
                "p10_price": 90,
                "p50_price": 100,
                "p90_price": 120,
                "prob_reach_target_pct": 62.0,
            }
        },
        "portfolio_protector": {"optimized_weights": {"stock": 0.5, "benchmark": 0.3, "cash": 0.2}, "stress_test": [1, 2]},
        "deep_insight": {"earnings_quality": {"label": "Ổn"}, "smart_money_flow": {"bias": "neutral"}},
    }
    bt = {"win_rate_pct": 68.0, "predicted_up_samples": 25}
    out = evaluate_dss_readiness(report, bt)
    assert out["decision"] == "COMMERCIAL_READY"
    assert float(out["commercial_score"]) >= 85


def test_evaluate_dss_readiness_not_ready_when_missing() -> None:
    out = evaluate_dss_readiness({}, {"win_rate_pct": None, "predicted_up_samples": 0})
    assert out["decision"] == "NOT_READY"
    assert len(out["missing_items"]) >= 1


def test_evaluate_dss_readiness_engine_backtest_fallback() -> None:
    report = {
        "probabilistic_forecast": {
            "forecast_range": {
                "p10_price": 90,
                "p50_price": 100,
                "p90_price": 120,
                "prob_reach_target_pct": 55.0,
            }
        },
        "portfolio_protector": {
            "optimized_weights": {"stock": 0.5, "benchmark": 0.3, "cash": 0.2},
            "stress_test": [1, 2],
        },
        "deep_insight": {
            "earnings_quality": {"label": "Ổn"},
            "smart_money_flow": {"bias": "bullish", "data_mode": "structured"},
        },
    }
    out = evaluate_dss_readiness(
        report,
        {"win_rate_pct": None, "predicted_up_samples": 0},
        engine_backtest={"buy_win_rate_pct": 58.0, "buy_signals": 12, "samples": 80},
    )
    assert out["checks"]["backtesting_winloss_available"] is True
    assert out["checks"]["backtesting_sample_sufficient"] is True
    assert out["backtesting_source"] == "engine_action_backtest_fallback"
    assert "backtesting_winloss_available" not in out["missing_items"]
