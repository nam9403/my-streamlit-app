from __future__ import annotations

from contextlib import contextmanager

import pandas as pd
import pytest
import streamlit as st

from core.ai_logic import AILogicError
from core.app_analysis_orchestration import resolve_analysis_report


@contextmanager
def _dummy_status(*args, **kwargs):
    class _Status:
        def write(self, *a, **k):
            return None

        def update(self, *a, **k):
            return None

    yield _Status()


def test_resolve_analysis_report_run_path_happy_flow(monkeypatch) -> None:
    st.session_state.clear()
    monkeypatch.setattr(st, "status", _dummy_status)
    monkeypatch.setattr(st, "warning", lambda *a, **k: None)
    monkeypatch.setattr(st, "error", lambda *a, **k: None)
    monkeypatch.setattr(st, "stop", lambda: (_ for _ in ()).throw(RuntimeError("stop")))

    usage_calls: list[tuple[str, str, int]] = []
    event_calls: list[str] = []
    snapshot_calls: list[str] = []

    def _record_usage(uid: str, feature: str, n: int) -> None:
        usage_calls.append((uid, feature, n))

    def _log_event(uid: str, event: str, meta) -> None:
        event_calls.append(event)

    def _record_forecast_snapshot(uid: str, ticker: str, report) -> None:
        snapshot_calls.append(f"{uid}:{ticker}:{str(report.get('task_mode_used') or '')}")

    report, ohlcv = resolve_analysis_report(
        run_analysis=True,
        fast_shell=False,
        user_id="u1",
        ticker="FPT",
        profile="growth",
        total_capital_vnd=100_000_000.0,
        plan={"llm_live": True},
        plan_id="pro",
        effective_quick_mode=False,
        can_use_feature=lambda *a, **k: (True, ""),
        record_usage=_record_usage,
        log_event=_log_event,
        load_snapshot_cached=lambda *a, **k: {"symbol": "FPT", "price": 100.0},
        value_investing_summary=lambda *a, **k: {"price": 100.0},
        recommend_task_mode=lambda *a, **k: "balanced",
        get_forecast_benchmark_by_horizon=lambda *a, **k: {},
        universe_subtype_map=lambda *a, **k: {},
        get_forecast_group_benchmark=lambda *a, **k: {},
        load_strategic_report_cached=lambda *a, **k: {"final_action": "HOLD", "analysis_text": "ok"},
        apply_drift_guardrails=lambda *a, **k: ({**a[2], "drift_guarded": True}, "quality"),
        get_forecast_drift_signal=lambda *a, **k: {},
        get_forecast_drift_streak=lambda *a, **k: 0,
        load_ohlcv_cached=lambda *a, **k: pd.DataFrame([{"date": "2025-01-01", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}]),
        calibrate_report_forecast_with_history=lambda *a, **k: {**a[2], "calibrated": True},
        get_forecast_accuracy_dashboard=lambda *a, **k: {},
        record_forecast_snapshot=_record_forecast_snapshot,
    )

    assert usage_calls == [("u1", "analysis", 1)]
    assert "analysis_started" in event_calls and "analysis_completed" in event_calls
    assert snapshot_calls
    assert report.get("task_mode_used") == "quality"
    assert report.get("drift_guarded") is True
    assert report.get("calibrated") is True
    assert float(report.get("latency_seconds") or 0.0) >= 0.0
    assert isinstance(ohlcv, pd.DataFrame)
    assert not ohlcv.empty
    assert st.session_state.get("report_ticker") == "FPT"


def test_resolve_analysis_report_run_path_fallback_when_ai_logic_fails(monkeypatch) -> None:
    st.session_state.clear()
    monkeypatch.setattr(st, "status", _dummy_status)
    monkeypatch.setattr(st, "warning", lambda *a, **k: None)
    monkeypatch.setattr(st, "error", lambda *a, **k: None)
    monkeypatch.setattr(st, "stop", lambda: (_ for _ in ()).throw(RuntimeError("stop")))

    report, _ = resolve_analysis_report(
        run_analysis=True,
        fast_shell=False,
        user_id="u1",
        ticker="FPT",
        profile="growth",
        total_capital_vnd=100_000_000.0,
        plan={"llm_live": True},
        plan_id="pro",
        effective_quick_mode=False,
        can_use_feature=lambda *a, **k: (True, ""),
        record_usage=lambda *a, **k: None,
        log_event=lambda *a, **k: None,
        load_snapshot_cached=lambda *a, **k: {"symbol": "FPT", "price": 100.0},
        value_investing_summary=lambda *a, **k: {"price": 100.0},
        recommend_task_mode=lambda *a, **k: "balanced",
        get_forecast_benchmark_by_horizon=lambda *a, **k: {},
        universe_subtype_map=lambda *a, **k: {},
        get_forecast_group_benchmark=lambda *a, **k: {},
        load_strategic_report_cached=lambda *a, **k: (_ for _ in ()).throw(AILogicError("boom")),
        apply_drift_guardrails=lambda *a, **k: (a[2], a[3]),
        get_forecast_drift_signal=lambda *a, **k: {},
        get_forecast_drift_streak=lambda *a, **k: 0,
        load_ohlcv_cached=lambda *a, **k: pd.DataFrame(),
        calibrate_report_forecast_with_history=lambda *a, **k: a[2],
        get_forecast_accuracy_dashboard=lambda *a, **k: {},
        record_forecast_snapshot=lambda *a, **k: None,
    )

    assert report.get("llm_provider") == "fallback_error"
    assert report.get("analysis_text") == "Chưa đủ dữ liệu để dựng phân tích 7 Whys."
    assert report.get("task_mode_used") is None


def test_resolve_analysis_report_stops_when_feature_gate_denied(monkeypatch) -> None:
    st.session_state.clear()
    monkeypatch.setattr(st, "status", _dummy_status)
    monkeypatch.setattr(st, "warning", lambda *a, **k: None)
    monkeypatch.setattr(st, "error", lambda *a, **k: None)

    class _StopCalled(Exception):
        pass

    monkeypatch.setattr(st, "stop", lambda: (_ for _ in ()).throw(_StopCalled()))

    with pytest.raises(_StopCalled):
        resolve_analysis_report(
            run_analysis=True,
            fast_shell=False,
            user_id="u1",
            ticker="FPT",
            profile="growth",
            total_capital_vnd=100_000_000.0,
            plan={"llm_live": False},
            plan_id="free",
            effective_quick_mode=True,
            can_use_feature=lambda *a, **k: (False, "quota exceeded"),
            record_usage=lambda *a, **k: (_ for _ in ()).throw(AssertionError("record_usage should not be called")),
            log_event=lambda *a, **k: (_ for _ in ()).throw(AssertionError("log_event should not be called")),
            load_snapshot_cached=lambda *a, **k: {},
            value_investing_summary=lambda *a, **k: {},
            recommend_task_mode=lambda *a, **k: "balanced",
            get_forecast_benchmark_by_horizon=lambda *a, **k: {},
            universe_subtype_map=lambda *a, **k: {},
            get_forecast_group_benchmark=lambda *a, **k: {},
            load_strategic_report_cached=lambda *a, **k: {},
            apply_drift_guardrails=lambda *a, **k: (a[2], a[3]),
            get_forecast_drift_signal=lambda *a, **k: {},
            get_forecast_drift_streak=lambda *a, **k: 0,
            load_ohlcv_cached=lambda *a, **k: pd.DataFrame(),
            calibrate_report_forecast_with_history=lambda *a, **k: a[2],
            get_forecast_accuracy_dashboard=lambda *a, **k: {},
            record_forecast_snapshot=lambda *a, **k: None,
        )

