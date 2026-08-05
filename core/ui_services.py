"""
UI service facade: product/domain callables + auth-guarded mutations.

``core/app_*.py`` panels must not import ``core.product_layer`` directly
(architecture boundary). They import this module instead.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core import product_layer as pl
from core.analysis_forecast_service import (
    apply_drift_guardrails,
    calibrate_report_forecast_with_history,
    recommend_task_mode,
)
from core.analysis_helper_service import extract_ticker, health_badge, profile_match_note
from core.analysis_runtime_service import (
    load_ohlcv_cached,
    load_snapshot_cached,
    load_strategic_report_cached,
    prewarm_watchlist_cache,
    run_bg_warm_job,
)
from core.app_auth_gate import authenticated_mutation, authenticated_user_mutation
from core.background_jobs import run_background_cycle
from core.opportunity_3m_service import build_opportunity_3m_board, load_benchmark_return_3m
from core.report_export import investment_report_html, investment_report_markdown
from core.scanner_service import (
    build_autopilot_simple_view,
    build_daily_action_list,
    build_profit_focus_board,
    load_autopilot_board,
    scan_potential_stocks,
    simple_view_for_plan,
)
from core.strategy_backtest import run_full_backtest_for_ticker
from core.valuation import value_investing_summary
from scrapers.financial_data import list_universe_symbols, universe_subtype_map
from scrapers.portal import fetch_ohlcv_history, get_source_sla_report
from scrapers.vn_listing import tradable_vn_symbol_count_fast


@dataclass
class GuardedMutations:
    """Auth-wrapped writers bound to the current session user."""

    user_id: str
    set_user_plan: Callable[..., Any]
    load_secret: Callable[..., Any]
    save_secret: Callable[..., Any]
    dispatch_text_notifications: Callable[..., Any]
    log_event: Callable[..., Any]
    process_notification_queue: Callable[..., Any]
    migrate_legacy_json_to_sqlite: Callable[..., Any]
    run_background_cycle: Callable[..., Any]
    upsert_daily_cx_score: Callable[..., Any]
    add_holding: Callable[..., Any]
    add_alert: Callable[..., Any]
    add_decision: Callable[..., Any]
    open_trade: Callable[..., Any]
    close_trade: Callable[..., Any]
    record_usage: Callable[..., Any]
    record_forecast_snapshot: Callable[..., Any]
    export_forecast_health_report: Callable[..., Any]
    export_model_accountability_report: Callable[..., Any]
    export_monthly_accountability_markdown: Callable[..., Any]
    send_monthly_accountability_email: Callable[..., Any]
    dispatch_alert_notifications: Callable[..., Any]
    dispatch_external_notifications: Callable[..., Any]
    enqueue_notification: Callable[..., Any]
    retry_failed_notifications: Callable[..., Any]


def universe_symbol_count() -> int:
    return tradable_vn_symbol_count_fast()


def compute_top5_for_profile(symbols: tuple[str, ...], profile: str):
    return scan_potential_stocks(tuple(symbols or ()), profile, 0.0).head(5)


def build_guarded_mutations(user_id: str) -> GuardedMutations:
    uid = str(user_id or "").strip()

    def guarded(func: Callable[..., Any]) -> Callable[..., Any]:
        return authenticated_mutation(uid, func)

    def guarded_user(func: Callable[..., Any]) -> Callable[..., Any]:
        return authenticated_user_mutation(uid, func)

    def run_user_background_cycle(**kwargs: Any) -> Any:
        return run_background_cycle(user_id=uid, **kwargs)

    return GuardedMutations(
        user_id=uid,
        set_user_plan=guarded_user(pl.set_user_plan),
        load_secret=guarded_user(pl.load_secret),
        save_secret=guarded_user(pl.save_secret),
        dispatch_text_notifications=guarded(pl.dispatch_text_notifications),
        log_event=guarded_user(pl.log_event),
        process_notification_queue=guarded(pl.process_notification_queue),
        migrate_legacy_json_to_sqlite=guarded(pl.migrate_legacy_json_to_sqlite),
        run_background_cycle=guarded(run_user_background_cycle),
        upsert_daily_cx_score=guarded_user(pl.upsert_daily_cx_score),
        add_holding=guarded_user(pl.add_holding),
        add_alert=guarded_user(pl.add_alert),
        add_decision=guarded_user(pl.add_decision),
        open_trade=guarded_user(pl.open_trade),
        close_trade=guarded_user(pl.close_trade),
        record_usage=guarded_user(pl.record_usage),
        record_forecast_snapshot=guarded_user(pl.record_forecast_snapshot),
        export_forecast_health_report=guarded_user(pl.export_forecast_health_report),
        export_model_accountability_report=guarded_user(pl.export_model_accountability_report),
        export_monthly_accountability_markdown=guarded_user(pl.export_monthly_accountability_markdown),
        send_monthly_accountability_email=guarded_user(pl.send_monthly_accountability_email),
        dispatch_alert_notifications=guarded_user(pl.dispatch_alert_notifications),
        dispatch_external_notifications=guarded(pl.dispatch_external_notifications),
        enqueue_notification=guarded_user(pl.enqueue_notification),
        retry_failed_notifications=guarded(pl.retry_failed_notifications),
    )


# Re-exports for panels (read-only / domain services)
__all__ = [
    "GuardedMutations",
    "build_guarded_mutations",
    "universe_symbol_count",
    "compute_top5_for_profile",
    "pl",
    "extract_ticker",
    "health_badge",
    "profile_match_note",
    "load_ohlcv_cached",
    "load_snapshot_cached",
    "load_strategic_report_cached",
    "prewarm_watchlist_cache",
    "run_bg_warm_job",
    "apply_drift_guardrails",
    "calibrate_report_forecast_with_history",
    "recommend_task_mode",
    "build_opportunity_3m_board",
    "load_benchmark_return_3m",
    "investment_report_html",
    "investment_report_markdown",
    "build_autopilot_simple_view",
    "build_daily_action_list",
    "build_profit_focus_board",
    "load_autopilot_board",
    "scan_potential_stocks",
    "simple_view_for_plan",
    "run_full_backtest_for_ticker",
    "value_investing_summary",
    "list_universe_symbols",
    "universe_subtype_map",
    "fetch_ohlcv_history",
    "get_source_sla_report",
]
