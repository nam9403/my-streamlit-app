"""
Execute full-ticker analysis jobs outside Streamlit (worker process).

Imports real services; safe to call from scripts/run_pg_job_worker.py only.
"""

from __future__ import annotations

import time
from typing import Any

from core import analysis_forecast_service as afs, product_layer as pl
from core.app_analysis_orchestration import compute_full_analysis_bundle_threadsafe
from core.opportunity_3m_service import build_opportunity_3m_board_impl
from core.valuation import value_investing_summary
from scrapers.financial_data import universe_subtype_map


def execute_full_ticker_job_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Run the same bundle as the in-process background thread.
    `payload` keys: user_id, ticker, profile, total_capital_vnd, plan_id, effective_quick_mode, llm_live.
    """
    user_id = str(payload["user_id"])
    ticker = str(payload["ticker"])
    profile = str(payload["profile"])
    total_capital_vnd = float(payload["total_capital_vnd"])
    effective_quick_mode = bool(payload.get("effective_quick_mode", True))
    llm_live = bool(payload.get("llm_live", False))
    plan = {"llm_live": llm_live}

    t0 = time.time()
    bundle = compute_full_analysis_bundle_threadsafe(
        user_id=user_id,
        ticker=ticker,
        profile=profile,
        total_capital_vnd=total_capital_vnd,
        plan=plan,
        effective_quick_mode=effective_quick_mode,
        recommend_task_mode=afs.recommend_task_mode,
        get_forecast_benchmark_by_horizon=pl.get_forecast_benchmark_by_horizon,
        universe_subtype_map=universe_subtype_map,
        get_forecast_group_benchmark=pl.get_forecast_group_benchmark,
        apply_drift_guardrails=afs.apply_drift_guardrails,
        get_forecast_drift_signal=pl.get_forecast_drift_signal,
        get_forecast_drift_streak=pl.get_forecast_drift_streak,
        value_investing_summary=value_investing_summary,
        get_forecast_accuracy_dashboard=pl.get_forecast_accuracy_dashboard,
    )
    bundle["report"]["latency_seconds"] = round(time.time() - t0, 2)
    return bundle


def execute_finder_3m_job_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Build Finder board off the UI thread. Payload mirrors build_opportunity_3m_board_impl kwargs;
    universe is a list of tickers (JSON-serializable).
    """
    raw_uni = payload.get("universe") or ()
    universe = tuple(str(x).strip().upper() for x in raw_uni if str(x).strip())
    profile = str(payload.get("profile") or "balanced")
    total_capital_vnd = float(payload.get("total_capital_vnd") or 0.0)
    quick_mode = bool(payload.get("quick_mode", True))
    llm_live = bool(payload.get("llm_live", False))
    allowed_raw = payload.get("allowed_subtypes") or ()
    allowed_subtypes = tuple(str(x).strip().lower() for x in allowed_raw if str(x).strip())
    min_avg_volume_20 = float(payload.get("min_avg_volume_20") or 0.0)
    bm = payload.get("benchmark_return_3m_pct")
    benchmark_return_3m_pct = None if bm is None else float(bm)
    min_data_quality_pct = float(payload.get("min_data_quality_pct") or 55.0)
    only_actionable = bool(payload.get("only_actionable", False))
    min_catalyst_score = float(payload.get("min_catalyst_score") or 0.0)
    dynamic_sector_calibration = bool(payload.get("dynamic_sector_calibration", True))
    top_n = int(payload.get("top_n") or 25)

    t0 = time.time()
    df = build_opportunity_3m_board_impl(
        universe,
        profile,
        total_capital_vnd,
        quick_mode=quick_mode,
        llm_live=llm_live,
        allowed_subtypes=allowed_subtypes,
        min_avg_volume_20=min_avg_volume_20,
        benchmark_return_3m_pct=benchmark_return_3m_pct,
        min_data_quality_pct=min_data_quality_pct,
        only_actionable=only_actionable,
        min_catalyst_score=min_catalyst_score,
        dynamic_sector_calibration=dynamic_sector_calibration,
        top_n=top_n,
    )
    return {"finder_df": df, "latency_seconds": round(time.time() - t0, 2), "row_count": int(len(df)) if df is not None else 0, "job_type": "finder_3m_board"}


def execute_deep_scan_job_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Deep Scan off-UI: scan_potential_stocks + portfolio options."""
    from core.action_center_panel import build_portfolio_options
    from core.scanner_service import scan_potential_stocks

    raw_uni = payload.get("universe") or ()
    universe = tuple(str(x).strip().upper() for x in raw_uni if str(x).strip())
    profile = str(payload.get("profile") or "balanced")
    min_avg_volume_20 = float(payload.get("min_avg_volume_20") or 0.0)
    total_capital_vnd = float(payload.get("total_capital_vnd") or 0.0)
    relax_on_empty = bool(payload.get("relax_on_empty", True))

    t0 = time.time()
    candidates = scan_potential_stocks(universe, profile, min_avg_volume_20)
    relaxed_used = False
    if relax_on_empty and getattr(candidates, "empty", True) and min_avg_volume_20 > 0:
        candidates = scan_potential_stocks(universe, profile, 0.0)
        relaxed_used = True
    try:
        from core.scanner_flow_integration import (
            is_scanner_rerank_enabled,
            rerank_candidates_with_flow_journal,
        )

        if is_scanner_rerank_enabled() and candidates is not None and not getattr(candidates, "empty", True):
            reranked, rerank_meta = rerank_candidates_with_flow_journal(candidates)
            if rerank_meta.get("reason") == "applied" and int(rerank_meta.get("applied_count") or 0) > 0:
                candidates = reranked
    except Exception:
        pass
    portfolios = build_portfolio_options(candidates, total_capital_vnd)
    return {
        "candidates": candidates,
        "portfolios": portfolios,
        "relaxed_used": relaxed_used,
        "latency_seconds": round(time.time() - t0, 2),
        "row_count": int(len(candidates)) if candidates is not None else 0,
        "symbol_count": len(universe),
        "job_type": "deep_scan",
    }


def execute_autopilot_job_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Auto Pilot board off-UI."""
    from datetime import date

    from core.scanner_service import load_autopilot_board

    profile = str(payload.get("profile") or "balanced")
    universe_limit = int(payload.get("universe_limit") or 30)
    min_avg_volume_20 = float(payload.get("min_avg_volume_20") or 300_000.0)
    rotation_day = payload.get("rotation_day")
    if rotation_day is None:
        rotation_day = date.today().toordinal()

    t0 = time.time()
    df = load_autopilot_board(
        profile,
        universe_limit=universe_limit,
        min_avg_volume_20=min_avg_volume_20,
        _rotation_day=int(rotation_day),
    )
    return {
        "autopilot_df": df,
        "latency_seconds": round(time.time() - t0, 2),
        "row_count": int(len(df)) if df is not None else 0,
        "job_type": "autopilot_board",
    }


def dispatch_job_payload(job_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    jt = str(job_type or "").strip() or "full_ticker_analysis"
    if jt == "finder_3m_board":
        return execute_finder_3m_job_payload(payload)
    if jt == "deep_scan":
        return execute_deep_scan_job_payload(payload)
    if jt == "autopilot_board":
        return execute_autopilot_job_payload(payload)
    return execute_full_ticker_job_payload(payload)
