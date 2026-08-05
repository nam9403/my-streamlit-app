"""
Analysis report orchestration (cache + run path).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import pandas as pd
import streamlit as st

from core.ai_logic import AILogicError
from core.ui_bg_analysis import (
    analysis_job_id,
    read_analysis_job_status,
    start_analysis_background_job,
    try_consume_analysis_job,
)
from core.ui_day_cache import day_cache_load, day_cache_save
from scrapers.portal import PortalDataError


def _fresh_request_snapshot(ticker: str, snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    """Giá phải mới tại thời điểm khách yêu cầu — không dùng OHLCV/kho cũ làm giá hiện tại."""
    if not isinstance(snapshot, dict):
        return snapshot
    try:
        from scrapers.financial_data import ensure_request_time_live_price

        return ensure_request_time_live_price(dict(snapshot), str(ticker or "").strip().upper())
    except Exception:
        return dict(snapshot)


def _consume_bg_job(jid: str) -> dict[str, Any] | None:
    from core import pg_analysis_jobs as pgj

    if pgj.pg_analysis_jobs_enabled():
        return pgj.try_consume_completed_result(jid)
    return try_consume_analysis_job(jid)


def _read_bg_job_status(jid: str) -> dict[str, Any] | None:
    from core import pg_analysis_jobs as pgj

    if pgj.pg_analysis_jobs_enabled():
        return pgj.read_job_status(jid)
    return read_analysis_job_status(jid)


def _enqueue_or_start_bg_job(
    jid: str,
    payload: dict[str, Any],
    work_factory: Callable[[], dict[str, Any]],
) -> None:
    from core import pg_analysis_jobs as pgj

    if pgj.pg_analysis_jobs_enabled():
        pgj.enqueue_full_ticker_analysis(jid, payload)
        return
    if not pgj.local_daemon_jobs_allowed():
        raise RuntimeError(
            "Không thể chạy phân tích nền: bật PostgreSQL (II_DB_URL + worker.py) "
            "hoặc II_ALLOW_LOCAL_DAEMON_JOBS=1 cho chế độ local."
        )
    start_analysis_background_job(jid, work_factory)


def analysis_cache_key_parts(
    *,
    user_id: str,
    ticker: str,
    profile: str,
    total_capital_vnd: float,
    plan_id: str,
    effective_quick_mode: bool,
    llm_live: bool,
) -> tuple[Any, ...]:
    return (
        str(user_id or ""),
        str(ticker or "").strip().upper(),
        str(profile or ""),
        float(total_capital_vnd),
        str(plan_id or ""),
        bool(effective_quick_mode),
        bool(llm_live),
    )


def _finalize_cached_report(
    *,
    user_id: str,
    ticker: str,
    profile: str,
    total_capital_vnd: float,
    effective_quick_mode: bool,
    report: dict[str, Any],
    ohlcv: pd.DataFrame,
    recommend_task_mode: Callable[..., str],
    get_forecast_benchmark_by_horizon: Callable[..., Any],
    universe_subtype_map: Callable[..., Any],
    get_forecast_group_benchmark: Callable[..., Any],
    apply_drift_guardrails: Callable[..., tuple[dict[str, Any], str]],
    get_forecast_drift_signal: Callable[..., Any],
    get_forecast_drift_streak: Callable[..., Any],
    calibrate_report_forecast_with_history: Callable[..., dict[str, Any]],
    get_forecast_accuracy_dashboard: Callable[..., Any],
) -> tuple[dict[str, Any], pd.DataFrame]:
    report.setdefault("latency_seconds", 0.0)
    report = calibrate_report_forecast_with_history(
        user_id,
        ticker,
        report,
        get_forecast_accuracy_dashboard=get_forecast_accuracy_dashboard,
    )
    mode_cached = report.setdefault(
        "task_mode_used",
        recommend_task_mode(
            user_id,
            ticker,
            effective_quick_mode,
            get_forecast_benchmark_by_horizon=get_forecast_benchmark_by_horizon,
            universe_subtype_map=universe_subtype_map,
            get_forecast_group_benchmark=get_forecast_group_benchmark,
        ),
    )
    report, mode_cached = apply_drift_guardrails(
        user_id,
        ticker,
        report,
        mode_cached,
        get_forecast_drift_signal=get_forecast_drift_signal,
        get_forecast_drift_streak=get_forecast_drift_streak,
        get_forecast_accuracy_dashboard=get_forecast_accuracy_dashboard,
    )
    report["task_mode_used"] = mode_cached
    return report, ohlcv


def _skeleton_report(ticker: str, profile: str, valuation: dict[str, Any]) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "valuation": valuation,
        "phase": {"phase": "neutral", "reason": "Chưa phân tích đầy đủ", "metrics": {}},
        "financials": {},
        "news": [],
        "whys_steps": [],
        "analysis_text": (
            "Đang ở chế độ **mở nhanh**: chỉ có định giá từ snapshot. "
            "Bấm **Chạy phân tích đầy đủ (nền)** để tải kỹ thuật, tin và 7 Whys — job chạy ngầm, bạn có thể đổi tab hoặc mã khác."
        ),
        "buy_zone": {},
        "take_profit": "N/A",
        "stop_loss": "N/A",
        "llm_used": False,
        "llm_provider": "fast_shell_skeleton",
        "final_action": "CHỜ PHÂN TÍCH",
        "_fast_shell_skeleton": True,
    }


def compute_full_analysis_bundle_threadsafe(
    *,
    user_id: str,
    ticker: str,
    profile: str,
    total_capital_vnd: float,
    plan: dict[str, Any],
    effective_quick_mode: bool,
    recommend_task_mode: Callable[..., str],
    get_forecast_benchmark_by_horizon: Callable[..., Any],
    universe_subtype_map: Callable[..., Any],
    get_forecast_group_benchmark: Callable[..., Any],
    apply_drift_guardrails: Callable[..., tuple[dict[str, Any], str]],
    get_forecast_drift_signal: Callable[..., Any],
    get_forecast_drift_streak: Callable[..., Any],
    value_investing_summary: Callable[..., dict[str, Any]],
    get_forecast_accuracy_dashboard: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """No Streamlit UI; safe for background thread (uses _snapshot/_strategic/_ohlcv impls, not st.cache_data wrappers)."""
    from concurrent.futures import ThreadPoolExecutor

    from core.analysis_runtime_service import _ohlcv_impl, _snapshot_impl, _strategic_report_impl

    # Chạy OHLCV song song với snapshot để che latency mạng khi disk chưa ấm.
    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_snap = pool.submit(_snapshot_impl, ticker)
        fut_ohlcv = pool.submit(_ohlcv_impl, ticker)
        snapshot = fut_snap.result()
        if snapshot is None:
            raise RuntimeError(f"no_snapshot:{ticker}")
        snapshot = _fresh_request_snapshot(ticker, snapshot) or snapshot
        try:
            ohlcv = fut_ohlcv.result()
        except PortalDataError:
            ohlcv = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        except Exception:
            ohlcv = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    valuation = value_investing_summary(snapshot)
    report: dict[str, Any] = {}
    if ohlcv is None or not isinstance(ohlcv, pd.DataFrame):
        ohlcv = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    try:
        task_mode = recommend_task_mode(
            user_id,
            ticker,
            effective_quick_mode,
            get_forecast_benchmark_by_horizon=get_forecast_benchmark_by_horizon,
            universe_subtype_map=universe_subtype_map,
            get_forecast_group_benchmark=get_forecast_group_benchmark,
        )
        report = _strategic_report_impl(
            ticker,
            snapshot,
            profile,
            float(total_capital_vnd),
            quick_mode=effective_quick_mode,
            llm_live=bool(plan["llm_live"]),
            task_mode=task_mode,
        )
        report["task_mode_used"] = task_mode
        report, guarded_mode = apply_drift_guardrails(
            user_id,
            ticker,
            report,
            task_mode,
            get_forecast_drift_signal=get_forecast_drift_signal,
            get_forecast_drift_streak=get_forecast_drift_streak,
            get_forecast_accuracy_dashboard=get_forecast_accuracy_dashboard,
        )
        report["task_mode_used"] = guarded_mode
    except (AILogicError, PortalDataError, ValueError) as e:
        report = {
            "ticker": ticker,
            "valuation": valuation,
            "phase": {"phase": "neutral", "reason": "Thiếu dữ liệu", "metrics": {}},
            "financials": {},
            "news": [],
            "whys_steps": [],
            "analysis_text": f"Không tải đủ dữ liệu nâng cao: {e}",
            "buy_zone": {},
            "take_profit": "N/A",
            "stop_loss": "N/A",
            "llm_used": False,
            "llm_provider": "fallback_error",
        }
    report.pop("_fast_shell_skeleton", None)
    return {"report": report, "ohlcv": ohlcv}


def resolve_analysis_report(
    *,
    run_analysis: bool,
    fast_shell: bool,
    user_id: str,
    ticker: str,
    profile: str,
    total_capital_vnd: float,
    plan: dict[str, Any],
    plan_id: str,
    effective_quick_mode: bool,
    can_use_feature: Callable[..., tuple[bool, str]],
    record_usage: Callable[..., Any],
    log_event: Callable[..., Any],
    load_snapshot_cached: Callable[..., dict[str, Any] | None],
    value_investing_summary: Callable[..., dict[str, Any]],
    recommend_task_mode: Callable[..., str],
    get_forecast_benchmark_by_horizon: Callable[..., Any],
    universe_subtype_map: Callable[..., Any],
    get_forecast_group_benchmark: Callable[..., Any],
    load_strategic_report_cached: Callable[..., dict[str, Any]],
    apply_drift_guardrails: Callable[..., tuple[dict[str, Any], str]],
    get_forecast_drift_signal: Callable[..., Any],
    get_forecast_drift_streak: Callable[..., Any],
    load_ohlcv_cached: Callable[..., pd.DataFrame],
    calibrate_report_forecast_with_history: Callable[..., dict[str, Any]],
    get_forecast_accuracy_dashboard: Callable[..., Any],
    record_forecast_snapshot: Callable[..., Any],
) -> tuple[dict[str, Any], pd.DataFrame]:
    parts = analysis_cache_key_parts(
        user_id=user_id,
        ticker=ticker,
        profile=profile,
        total_capital_vnd=total_capital_vnd,
        plan_id=plan_id,
        effective_quick_mode=effective_quick_mode,
        llm_live=bool(plan["llm_live"]),
    )
    jid = analysis_job_id(parts)

    if (
        not run_analysis
        and "report_cache" in st.session_state
        and st.session_state.get("report_ticker") == ticker
        and st.session_state.get("report_profile") == profile
        and float(st.session_state.get("report_capital", 0)) == float(total_capital_vnd)
    ):
        report = st.session_state["report_cache"]
        ohlcv = st.session_state.get("ohlcv_cache", pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"]))
        st.session_state.pop("analysis_bg_poll_jid", None)
        return _finalize_cached_report(
            user_id=user_id,
            ticker=ticker,
            profile=profile,
            total_capital_vnd=total_capital_vnd,
            effective_quick_mode=effective_quick_mode,
            report=report,
            ohlcv=ohlcv,
            recommend_task_mode=recommend_task_mode,
            get_forecast_benchmark_by_horizon=get_forecast_benchmark_by_horizon,
            universe_subtype_map=universe_subtype_map,
            get_forecast_group_benchmark=get_forecast_group_benchmark,
            apply_drift_guardrails=apply_drift_guardrails,
            get_forecast_drift_signal=get_forecast_drift_signal,
            get_forecast_drift_streak=get_forecast_drift_streak,
            calibrate_report_forecast_with_history=calibrate_report_forecast_with_history,
            get_forecast_accuracy_dashboard=get_forecast_accuracy_dashboard,
        )

    if fast_shell and not run_analysis:
        dc = day_cache_load("full_analysis", parts)
        if isinstance(dc, dict) and isinstance(dc.get("report"), dict):
            st.session_state["report_ticker"] = ticker
            st.session_state["report_profile"] = profile
            st.session_state["report_capital"] = float(total_capital_vnd)
            st.session_state["report_cache"] = dc["report"]
            st.session_state["ohlcv_cache"] = dc.get("ohlcv") or pd.DataFrame(
                columns=["date", "open", "high", "low", "close", "volume"]
            )
            report = st.session_state["report_cache"]
            ohlcv = st.session_state["ohlcv_cache"]
            st.session_state.pop("analysis_bg_poll_jid", None)
            return _finalize_cached_report(
                user_id=user_id,
                ticker=ticker,
                profile=profile,
                total_capital_vnd=total_capital_vnd,
                effective_quick_mode=effective_quick_mode,
                report=report,
                ohlcv=ohlcv,
                recommend_task_mode=recommend_task_mode,
                get_forecast_benchmark_by_horizon=get_forecast_benchmark_by_horizon,
                universe_subtype_map=universe_subtype_map,
                get_forecast_group_benchmark=get_forecast_group_benchmark,
                apply_drift_guardrails=apply_drift_guardrails,
                get_forecast_drift_signal=get_forecast_drift_signal,
                get_forecast_drift_streak=get_forecast_drift_streak,
                calibrate_report_forecast_with_history=calibrate_report_forecast_with_history,
                get_forecast_accuracy_dashboard=get_forecast_accuracy_dashboard,
            )

        consumed = _consume_bg_job(jid)
        if isinstance(consumed, dict) and isinstance(consumed.get("report"), dict):
            report0 = consumed["report"]
            ohlcv0 = consumed.get("ohlcv") or pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
            st.session_state["report_ticker"] = ticker
            st.session_state["report_profile"] = profile
            st.session_state["report_capital"] = float(total_capital_vnd)
            st.session_state["report_cache"] = report0
            st.session_state["ohlcv_cache"] = ohlcv0
            day_cache_save("full_analysis", parts, {"report": report0, "ohlcv": ohlcv0})
            report0["latency_seconds"] = float(report0.get("latency_seconds") or 0.0)
            log_event(
                user_id,
                "analysis_completed_bg",
                {"ticker": ticker, "latency_s": report0.get("latency_seconds"), "action": report0.get("final_action")},
            )
            report = st.session_state["report_cache"]
            ohlcv = st.session_state["ohlcv_cache"]
            report, ohlcv = _finalize_cached_report(
                user_id=user_id,
                ticker=ticker,
                profile=profile,
                total_capital_vnd=total_capital_vnd,
                effective_quick_mode=effective_quick_mode,
                report=report,
                ohlcv=ohlcv,
                recommend_task_mode=recommend_task_mode,
                get_forecast_benchmark_by_horizon=get_forecast_benchmark_by_horizon,
                universe_subtype_map=universe_subtype_map,
                get_forecast_group_benchmark=get_forecast_group_benchmark,
                apply_drift_guardrails=apply_drift_guardrails,
                get_forecast_drift_signal=get_forecast_drift_signal,
                get_forecast_drift_streak=get_forecast_drift_streak,
                calibrate_report_forecast_with_history=calibrate_report_forecast_with_history,
                get_forecast_accuracy_dashboard=get_forecast_accuracy_dashboard,
            )
            record_forecast_snapshot(user_id, ticker, report)
            st.session_state["report_cache"] = report
            st.session_state["ohlcv_cache"] = ohlcv
            st.session_state.pop("analysis_bg_poll_jid", None)
            return report, ohlcv

        req = str(st.session_state.get("analysis_bg_request_for_job_id") or "").strip()
        if req == jid:
            stt = _read_bg_job_status(jid)
            if stt is None or stt.get("state") not in ("pending", "running"):
                ok_analysis, msg_analysis = can_use_feature(user_id, "analysis", 1, plan_id=plan_id)
                if not ok_analysis:
                    st.session_state.pop("analysis_bg_request_for_job_id", None)
                    st.error(msg_analysis + " Nâng cấp gói để tăng hạn mức.")
                    st.stop()

                def _work() -> dict[str, Any]:
                    t0 = time.time()
                    bundle = compute_full_analysis_bundle_threadsafe(
                        user_id=user_id,
                        ticker=ticker,
                        profile=profile,
                        total_capital_vnd=total_capital_vnd,
                        plan=plan,
                        effective_quick_mode=effective_quick_mode,
                        recommend_task_mode=recommend_task_mode,
                        get_forecast_benchmark_by_horizon=get_forecast_benchmark_by_horizon,
                        universe_subtype_map=universe_subtype_map,
                        get_forecast_group_benchmark=get_forecast_group_benchmark,
                        apply_drift_guardrails=apply_drift_guardrails,
                        get_forecast_drift_signal=get_forecast_drift_signal,
                        get_forecast_drift_streak=get_forecast_drift_streak,
                        value_investing_summary=value_investing_summary,
                    )
                    bundle["report"]["latency_seconds"] = round(time.time() - t0, 2)
                    return bundle

                payload = {
                    "user_id": user_id,
                    "ticker": ticker,
                    "profile": profile,
                    "total_capital_vnd": float(total_capital_vnd),
                    "plan_id": plan_id,
                    "effective_quick_mode": effective_quick_mode,
                    "llm_live": bool(plan["llm_live"]),
                }
                record_usage(user_id, "analysis", 1)
                log_event(user_id, "analysis_started_bg", {"ticker": ticker, "plan": plan_id, "quick_mode": effective_quick_mode})
                _enqueue_or_start_bg_job(jid, payload, _work)
            st.session_state.pop("analysis_bg_request_for_job_id", None)

        stt2 = _read_bg_job_status(jid)
        if stt2 and stt2.get("state") in ("pending", "running"):
            snapshot = load_snapshot_cached(ticker)
            if snapshot is None:
                st.error(f"Không lấy được snapshot cho `{ticker}`.")
                st.stop()
            snapshot = _fresh_request_snapshot(ticker, snapshot) or snapshot
            valuation = value_investing_summary(snapshot)
            sk = _skeleton_report(ticker, profile, valuation)
            sk["_analysis_bg_status"] = stt2.get("state")
            st.session_state["analysis_bg_poll_jid"] = jid
            return sk, pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

        snapshot = load_snapshot_cached(ticker)
        if snapshot is None:
            st.error(f"Không lấy được snapshot cho `{ticker}`.")
            st.stop()
        snapshot = _fresh_request_snapshot(ticker, snapshot) or snapshot
        valuation = value_investing_summary(snapshot)
        sk = _skeleton_report(ticker, profile, valuation)
        st.session_state.pop("analysis_bg_poll_jid", None)
        return sk, pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    ok_analysis, msg_analysis = can_use_feature(user_id, "analysis", 1, plan_id=plan_id)
    if not ok_analysis:
        st.error(msg_analysis + " Nâng cấp gói để tăng hạn mức.")
        st.stop()
    record_usage(user_id, "analysis", 1)
    log_event(user_id, "analysis_started", {"ticker": ticker, "plan": plan_id, "quick_mode": effective_quick_mode})
    started = time.time()
    with st.status(f"🤖 Đang phân tích {ticker}...", expanded=True) as status:
        status.write("Đang quét BCTC và định giá...")
        snapshot = load_snapshot_cached(ticker)
        if snapshot is None:
            st.error(f"Không lấy được snapshot cho `{ticker}`.")
            st.stop()
        snapshot = _fresh_request_snapshot(ticker, snapshot) or snapshot

        valuation = value_investing_summary(snapshot)
        report = {}
        ohlcv = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        try:
            status.write("Đang phân tích kỹ thuật & tin tức...")
            task_mode = recommend_task_mode(
                user_id,
                ticker,
                effective_quick_mode,
                get_forecast_benchmark_by_horizon=get_forecast_benchmark_by_horizon,
                universe_subtype_map=universe_subtype_map,
                get_forecast_group_benchmark=get_forecast_group_benchmark,
            )
            report = load_strategic_report_cached(
                ticker,
                snapshot,
                profile,
                total_capital_vnd,
                quick_mode=effective_quick_mode,
                llm_live=bool(plan["llm_live"]),
                task_mode=task_mode,
            )
            report["task_mode_used"] = task_mode
            report, guarded_mode = apply_drift_guardrails(
                user_id,
                ticker,
                report,
                task_mode,
                get_forecast_drift_signal=get_forecast_drift_signal,
                get_forecast_drift_streak=get_forecast_drift_streak,
                get_forecast_accuracy_dashboard=get_forecast_accuracy_dashboard,
            )
            report["task_mode_used"] = guarded_mode
            try:
                ohlcv = load_ohlcv_cached(ticker)
            except PortalDataError:
                ohlcv = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        except (AILogicError, PortalDataError, ValueError) as e:
            st.warning(f"Không tải đủ dữ liệu nâng cao cho `{ticker}`: {e}")
            report = {
                "ticker": ticker,
                "valuation": valuation,
                "phase": {"phase": "neutral", "reason": "Thiếu dữ liệu", "metrics": {}},
                "financials": {},
                "news": [],
                "whys_steps": [],
                "analysis_text": "Chưa đủ dữ liệu để dựng phân tích 7 Whys.",
                "buy_zone": {},
                "take_profit": "N/A",
                "stop_loss": "N/A",
                "llm_used": False,
                "llm_provider": "fallback_error",
            }
        status.write("Đang áp dụng 7 Whys và quản trị rủi ro...")
        report = calibrate_report_forecast_with_history(
            user_id,
            ticker,
            report,
            get_forecast_accuracy_dashboard=get_forecast_accuracy_dashboard,
        )
        st.session_state["report_ticker"] = ticker
        st.session_state["report_profile"] = profile
        st.session_state["report_capital"] = float(total_capital_vnd)
        st.session_state["report_cache"] = report
        st.session_state["ohlcv_cache"] = ohlcv
        status.update(label=f"✅ Hoàn tất phân tích {ticker}", state="complete")
    report["latency_seconds"] = round(time.time() - started, 2)
    log_event(
        user_id,
        "analysis_completed",
        {"ticker": ticker, "latency_s": report.get("latency_seconds"), "action": report.get("final_action")},
    )
    record_forecast_snapshot(user_id, ticker, report)
    day_cache_save("full_analysis", parts, {"report": report, "ohlcv": ohlcv})
    return report, ohlcv
