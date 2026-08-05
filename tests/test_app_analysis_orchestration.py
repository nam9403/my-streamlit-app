from __future__ import annotations

import pandas as pd
import streamlit as st

from core.app_analysis_orchestration import resolve_analysis_report


def test_resolve_analysis_report_uses_cached_report_path() -> None:
    st.session_state.clear()
    cached_report = {
        "valuation": {"price": 100.0},
        "task_mode_used": "balanced",
        "final_action": "HOLD",
    }
    cached_ohlcv = pd.DataFrame([{"date": "2025-01-01", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}])
    st.session_state["report_cache"] = dict(cached_report)
    st.session_state["report_ticker"] = "FPT"
    st.session_state["report_profile"] = "growth"
    st.session_state["report_capital"] = 100_000_000.0
    st.session_state["ohlcv_cache"] = cached_ohlcv

    calibrated_called = {"count": 0}
    drift_called = {"count": 0}

    def _calibrate(*args, **kwargs):
        calibrated_called["count"] += 1
        report = dict(args[2])
        report["calibrated"] = True
        return report

    def _drift_guard(*args, **kwargs):
        drift_called["count"] += 1
        report = dict(args[2])
        report["drift_guarded"] = True
        return report, "balanced"

    report, ohlcv = resolve_analysis_report(
        run_analysis=False,
        fast_shell=False,
        user_id="u1",
        ticker="FPT",
        profile="growth",
        total_capital_vnd=100_000_000.0,
        plan={"llm_live": False},
        plan_id="free",
        effective_quick_mode=True,
        can_use_feature=lambda *a, **k: (True, ""),
        record_usage=lambda *a, **k: None,
        log_event=lambda *a, **k: None,
        load_snapshot_cached=lambda *a, **k: None,
        value_investing_summary=lambda *a, **k: {},
        recommend_task_mode=lambda *a, **k: "balanced",
        get_forecast_benchmark_by_horizon=lambda *a, **k: {},
        universe_subtype_map=lambda *a, **k: {},
        get_forecast_group_benchmark=lambda *a, **k: {},
        load_strategic_report_cached=lambda *a, **k: {},
        apply_drift_guardrails=_drift_guard,
        get_forecast_drift_signal=lambda *a, **k: {},
        get_forecast_drift_streak=lambda *a, **k: 0,
        load_ohlcv_cached=lambda *a, **k: pd.DataFrame(),
        calibrate_report_forecast_with_history=_calibrate,
        get_forecast_accuracy_dashboard=lambda *a, **k: {},
        record_forecast_snapshot=lambda *a, **k: None,
    )

    assert calibrated_called["count"] == 1
    assert drift_called["count"] == 1
    assert report["calibrated"] is True
    assert report["drift_guarded"] is True
    assert isinstance(ohlcv, pd.DataFrame)
    assert not ohlcv.empty

