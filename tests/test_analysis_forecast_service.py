from __future__ import annotations

import os

from core.analysis_forecast_service import (
    apply_drift_guardrails,
    calibrate_report_forecast_with_history,
    recommend_task_mode,
)


def test_recommend_task_mode_returns_speed_for_quick_mode() -> None:
    out = recommend_task_mode(
        "u1",
        "FPT",
        True,
        get_forecast_benchmark_by_horizon=lambda *a, **k: [],
        universe_subtype_map=lambda: {},
        get_forecast_group_benchmark=lambda *a, **k: {},
    )
    assert out == "speed"


def test_recommend_task_mode_uses_group_fallback_quality() -> None:
    out = recommend_task_mode(
        "u1",
        "FPT",
        False,
        get_forecast_benchmark_by_horizon=lambda *a, **k: [{"samples": 1}],
        universe_subtype_map=lambda: {"FPT": "tech", "CMG": "tech"},
        get_forecast_group_benchmark=lambda *a, **k: {"samples": 10, "hit_rate_pct": 45, "mape_pct": 16, "alpha_pct": -4},
    )
    assert out == "quality"


def test_recommend_task_mode_from_valid_rows_balanced() -> None:
    out = recommend_task_mode(
        "u1",
        "VCB",
        False,
        get_forecast_benchmark_by_horizon=lambda *a, **k: [
            {"samples": 5, "hit_rate_pct": 58, "mape_pct": 11, "alpha_pct": -1.5},
            {"samples": 3, "hit_rate_pct": 56, "mape_pct": 10, "alpha_pct": -1.0},
        ],
        universe_subtype_map=lambda: {"VCB": "bank"},
        get_forecast_group_benchmark=lambda *a, **k: {},
    )
    assert out == "balanced"


def test_apply_drift_guardrails_noop_when_stable() -> None:
    report = {"risk_plan": {"max_position_pct": 20, "allocated_capital_vnd": 10_000_000}}
    out, mode = apply_drift_guardrails(
        "u1",
        "FPT",
        report,
        "speed",
        get_forecast_drift_signal=lambda *a, **k: {"status": "stable"},
        get_forecast_drift_streak=lambda *a, **k: {"drift_down_streak": 1},
    )
    assert mode == "speed"
    assert out["drift_guardrails"]["applied"] is False


def test_apply_drift_guardrails_reduces_risk_and_forces_quality() -> None:
    report = {"risk_plan": {"max_position_pct": 20.0, "allocated_capital_vnd": 40_000_000.0}}
    out, mode = apply_drift_guardrails(
        "u1",
        "FPT",
        report,
        "balanced",
        get_forecast_drift_signal=lambda *a, **k: {"status": "drift_down"},
        get_forecast_drift_streak=lambda *a, **k: {"drift_down_streak": 3},
    )
    assert mode == "quality"
    assert out["risk_plan"]["max_position_pct"] == 15.0
    assert out["risk_plan"]["allocated_capital_vnd"] == 30_000_000.0
    assert out["drift_guardrails"]["applied"] is True


def test_calibrate_report_forecast_missing_forecast() -> None:
    report: dict[str, object] = {}
    out = calibrate_report_forecast_with_history(
        "u1",
        "FPT",
        report,
        get_forecast_accuracy_dashboard=lambda *a, **k: {},
    )
    assert out["forecast_calibration"]["applied"] is False
    assert out["forecast_calibration"]["reason"] == "missing_forecast"


def test_calibrate_report_forecast_insufficient_history(monkeypatch) -> None:
    monkeypatch.setenv("AI_FORECAST_CALIB_MIN_RECORDS", "10")
    report = {
        "valuation": {"price": 100.0},
        "probabilistic_forecast": {"expected_return_pct": 5.0, "scenarios": [{"return_pct": 3.0}]},
    }
    out = calibrate_report_forecast_with_history(
        "u1",
        "FPT",
        report,
        get_forecast_accuracy_dashboard=lambda *a, **k: {"resolved": 3, "bias_pct": 2.0},
    )
    assert out["forecast_calibration"]["applied"] is False
    assert out["forecast_calibration"]["reason"] == "insufficient_history"


def test_calibrate_report_forecast_applies_bias_shift(monkeypatch) -> None:
    monkeypatch.setenv("AI_FORECAST_CALIB_MIN_RECORDS", "3")
    monkeypatch.setenv("AI_FORECAST_BIAS_FACTOR", "0.4")
    report = {
        "valuation": {"price": 100.0},
        "probabilistic_forecast": {
            "expected_return_pct": 5.0,
            "expected_price": 105.0,
            "summary": "base",
            "scenarios": [{"name": "base", "return_pct": 4.0, "target_price": 104.0}],
        },
    }
    out = calibrate_report_forecast_with_history(
        "u1",
        "FPT",
        report,
        get_forecast_accuracy_dashboard=lambda *a, **k: {"resolved": 12, "bias_pct": 2.0},
    )
    cal = out["forecast_calibration"]
    assert cal["applied"] is True
    assert cal["shift_pct"] == 0.8
    fc = out["probabilistic_forecast"]
    assert fc["expected_return_pct"] == 5.8
    assert fc["expected_price"] == 105.8
    assert "đã hiệu chỉnh bias +0.80%" in str(fc["summary"])


def test_calibrate_report_forecast_handles_invalid_env_factor(monkeypatch) -> None:
    monkeypatch.setenv("AI_FORECAST_CALIB_MIN_RECORDS", "3")
    monkeypatch.setenv("AI_FORECAST_BIAS_FACTOR", "bad")
    report = {
        "valuation": {"price": 200.0},
        "probabilistic_forecast": {"expected_return_pct": 0.0, "summary": "", "scenarios": [{"return_pct": 0.0}]},
    }
    out = calibrate_report_forecast_with_history(
        "u1",
        "FPT",
        report,
        get_forecast_accuracy_dashboard=lambda *a, **k: {"resolved": 6, "bias_pct": -4.0},
    )
    assert out["forecast_calibration"]["applied"] is True
    assert out["forecast_calibration"]["factor"] == 0.35


def test_env_sanity() -> None:
    # Keep test module deterministic about env side-effects.
    assert isinstance(os.environ.get("AI_FORECAST_CALIB_MIN_RECORDS", "8"), str)
