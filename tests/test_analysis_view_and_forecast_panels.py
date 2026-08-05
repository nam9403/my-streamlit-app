from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pandas as pd


@contextmanager
def _ctx():
    yield


def _columns(spec) -> list[Any]:
    if isinstance(spec, int):
        n = spec
    elif isinstance(spec, list):
        n = len(spec)
    else:
        n = 2
    return [_ctx() for _ in range(max(1, n))]


def test_analysis_view_panel_smoke(monkeypatch) -> None:
    import core.analysis_view_panel as v

    monkeypatch.setattr(v.st, "subheader", lambda *a, **k: None)
    monkeypatch.setattr(v.st, "dataframe", lambda *a, **k: None)
    monkeypatch.setattr(v.st, "columns", _columns)
    monkeypatch.setattr(v.st, "markdown", lambda *a, **k: None)
    monkeypatch.setattr(v.st, "metric", lambda *a, **k: None)
    monkeypatch.setattr(v.st, "caption", lambda *a, **k: None)
    monkeypatch.setattr(v.st, "download_button", lambda *a, **k: None)
    monkeypatch.setattr(v.st, "plotly_chart", lambda *a, **k: None)
    monkeypatch.setattr(v.st, "info", lambda *a, **k: None)

    report = {
        "confidence_score": 70,
        "latency_seconds": 2.0,
        "gate_passed": True,
        "data_reliability": {
            "technical": {"ok": True},
            "financial": {"ok": True, "source": "vndirect", "quality_score": 4},
            "news": {"ok": True},
            "backtest": {"ok": True, "samples": 100, "buy_signals": 10},
        },
        "valuation": {"piotroski_score": 7, "margin_of_safety_composite_pct": 12.5, "data_source": "core"},
        "phase": {"phase": "breakout"},
        "financials": {"debt_to_equity": 0.5, "gross_margin": 0.3, "data_trust": {"is_stale": False}},
        "news": [{"title": "n1", "url": "https://x", "source": "s"}],
        "risk_plan": {
            "entry_price": 100,
            "take_profit_price": 120,
            "stop_loss_price": 95,
            "allocated_capital_vnd": 20_000_000,
            "max_position_pct": 20,
            "worst_case_loss_vnd": 1_000_000,
            "worst_case_loss_pct_total_capital": 1.0,
        },
        "total_capital_vnd": 100_000_000,
    }
    ohlcv = pd.DataFrame([{"date": "2025-01-01", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 10}] * 60)
    ohlcv.attrs["source"] = "portal"
    ohlcv.attrs["data_trust"] = {"age_sec": 120.0, "is_stale": False, "fallback_chain": ["a", "b"]}

    v.render_5s_panel(report, [{"success_rate_pct": 90}])
    v.render_health_cards(report, health_badge=lambda _: ("GOOD", "#00ff00"))
    v.render_readiness_checklist(report, ohlcv)
    v.render_evidence(report)
    v.render_report_downloads(
        report,
        investment_report_markdown=lambda _: "# md",
        investment_report_html=lambda _: "<html></html>",
    )
    v.render_risk_plan(report)
    v.render_risk_plan({})  # missing plan branch


def test_analysis_forecast_panel_smoke(monkeypatch) -> None:
    import core.analysis_forecast_panel as f

    monkeypatch.setattr(f.st, "markdown", lambda *a, **k: None)
    monkeypatch.setattr(f.st, "caption", lambda *a, **k: None)
    monkeypatch.setattr(f.st, "columns", _columns)
    monkeypatch.setattr(f.st, "metric", lambda *a, **k: None)
    monkeypatch.setattr(f.st, "dataframe", lambda *a, **k: None)
    monkeypatch.setattr(f.st, "warning", lambda *a, **k: None)
    monkeypatch.setattr(f.st, "success", lambda *a, **k: None)

    f.render_forecast_accuracy("u1", "FPT", get_forecast_accuracy_dashboard=lambda *a, **k: {"records": 10, "resolved": 8, "hit_rate_pct": 70.0, "mape_pct": 8.5, "bias_pct": -1.2})
    f.render_forecast_benchmark("u1", "FPT", get_forecast_benchmark_by_horizon=lambda *a, **k: [{"horizon_days": 30, "samples": 5, "hit_rate_pct": 60.0, "mape_pct": 9.0, "expected_return_pct_avg": 5.0, "realized_return_pct_avg": 4.0, "alpha_pct": -1.0, "beat_expected_pct": 45.0}])
    f.render_forecast_benchmark("u1", "FPT", get_forecast_benchmark_by_horizon=lambda *a, **k: [])  # empty branch
    f.render_model_drift_panel("u1", "FPT", get_forecast_drift_signal=lambda *a, **k: {"status": "drift_down", "message": "warn", "delta_hit_pct": -3.0, "delta_mape_pct": 2.0, "hit_drop_threshold_pct": 2.0, "mape_rise_threshold_pct": 1.0}, get_forecast_drift_streak=lambda *a, **k: {"drift_down_streak": 2, "checks": 3})
    f.render_forecast_portfolio_dashboard("u1", get_forecast_portfolio_dashboard=lambda *a, **k: {"weekly": {"hit_rate_pct": 60.0, "samples": 5}, "monthly": {"hit_rate_pct": 58.0, "samples": 20}, "overall": {"mape_pct": 9.0, "alpha_pct": 1.2}})
    f.render_forecast_regime_dashboard("u1", get_forecast_regime_dashboard=lambda *a, **k: {"bull": {"samples": 3, "hit_rate_pct": 66.0, "alpha_pct": 1.0}, "sideway": {"samples": 2, "hit_rate_pct": 55.0, "alpha_pct": 0.5}, "bear": {"samples": 1, "hit_rate_pct": 40.0, "alpha_pct": -2.0}})
    f.render_forecast_leaderboard("u1", get_forecast_leaderboard=lambda *a, **k: [{"symbol": "FPT", "samples": 8, "hit_rate_pct": 62.0, "mape_pct": 8.0, "alpha_pct": 1.0, "score": 75.0}])
    f.render_forecast_leaderboard("u1", get_forecast_leaderboard=lambda *a, **k: [])  # empty branch
    f.render_sector_mode_suggestions(
        "u1",
        get_forecast_leaderboard=lambda *a, **k: [
            {"symbol": "FPT", "hit_rate_pct": 65.0, "mape_pct": 8.0, "alpha_pct": 1.0},
            {"symbol": "CMG", "hit_rate_pct": 63.0, "mape_pct": 9.0, "alpha_pct": 0.5},
        ],
        universe_subtype_map=lambda: {"FPT": "tech", "CMG": "tech"},
    )
    f.render_sector_mode_suggestions("u1", get_forecast_leaderboard=lambda *a, **k: [], universe_subtype_map=lambda: {})
