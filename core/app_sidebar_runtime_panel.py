"""
Sidebar runtime orchestration panel — self-wired nested panels + ui_services.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import streamlit as st

from core import state_manager as sm, ui_services as svc
from core.analysis_helper_service import extract_ticker
from core.app_ui_config import SUBTYPE_LABEL_TO_ID
from core.decision_trade_panel import render_decision_trade_panel
from core.experience_panel import render_experience_panel
from core.opportunity_filter_panel import render_opportunity_filter_panel
from core.portfolio_alert_panel import render_portfolio_alert_panel
from core.ui_services import GuardedMutations
from core.watchlist_controls_panel import render_watchlist_controls


@dataclass
class SidebarRuntimeState:
    runtime_cfg: Any
    watchlist: list[str]
    ticker: str
    autopilot_mode: bool
    profit_focus_mode: bool
    autopilot_limit: int
    autopilot_refresh: bool
    quick_mode: bool
    run_analysis: bool
    min_avg_volume_20: float
    universe_limit: int
    subtype_labels: list[str]
    run_scan: bool


def render_sidebar_runtime_sections(
    *,
    watchlist_default: list[str],
    auth_ready: bool,
    user_id: str,
    profile: str,
    total_capital_vnd: float,
    plan: dict[str, Any],
    plan_label: str,
    plan_id: str,
    tg_bot: str = "",
    tg_chat: str = "",
    webhook_url: str = "",
    email_to: str = "",
    smtp_host: str = "",
    smtp_port: int = 587,
    smtp_user: str = "",
    smtp_password: str = "",
    smtp_from: str = "",
    mutations: GuardedMutations | None = None,
) -> SidebarRuntimeState:
    mut = mutations
    process_notification_queue = mut.process_notification_queue if mut else svc.pl.process_notification_queue
    run_background_cycle = mut.run_background_cycle if mut else (lambda **k: {})
    dispatch_text_notifications = (
        mut.dispatch_text_notifications if mut else svc.pl.dispatch_text_notifications
    )
    upsert_daily_cx_score = mut.upsert_daily_cx_score if mut else svc.pl.upsert_daily_cx_score
    add_holding = mut.add_holding if mut else svc.pl.add_holding
    log_event = mut.log_event if mut else svc.pl.log_event
    add_alert = mut.add_alert if mut else svc.pl.add_alert
    add_decision = mut.add_decision if mut else svc.pl.add_decision
    open_trade = mut.open_trade if mut else svc.pl.open_trade
    close_trade = mut.close_trade if mut else svc.pl.close_trade

    with st.expander("Danh mục theo dõi", expanded=True):
        runtime_cfg = render_watchlist_controls(
            watchlist_default=watchlist_default,
            auth_ready=auth_ready,
            extract_ticker=extract_ticker,
            tg_bot=tg_bot,
            tg_chat=tg_chat,
            webhook_url=webhook_url,
            email_to=email_to,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_user=smtp_user,
            smtp_password=smtp_password,
            smtp_from=smtp_from,
            user_id=user_id,
            process_notification_queue=process_notification_queue,
            run_background_cycle=run_background_cycle,
            dispatch_text_notifications=dispatch_text_notifications,
            upsert_daily_cx_score=upsert_daily_cx_score,
            get_recent_cx_scores=svc.pl.get_recent_cx_scores,
            plan=plan,
        )
        watchlist = list(runtime_cfg.watchlist or [])
        ticker = str(runtime_cfg.ticker or "")
        autopilot_mode = bool(runtime_cfg.autopilot_mode)
        profit_focus_mode = bool(runtime_cfg.profit_focus_mode)
        autopilot_limit = int(runtime_cfg.autopilot_limit or 30)
        autopilot_refresh = bool(runtime_cfg.autopilot_refresh)
        quick_mode = bool(runtime_cfg.quick_mode)
        run_analysis = bool(runtime_cfg.run_analysis)

    with st.expander("⭐ Trải nghiệm khách hàng", expanded=False):
        auth_ready_now = bool(auth_ready and svc.pl.has_auth_user(user_id) and sm.is_auth_ok())
        render_experience_panel(
            auth_ready=auth_ready_now,
            tg_bot=tg_bot,
            tg_chat=tg_chat,
            webhook_url=webhook_url,
            email_to=email_to,
            smtp_host=smtp_host,
            smtp_user=smtp_user,
            smtp_password=smtp_password,
            watchlist=watchlist,
            ticker=ticker,
        )
    st.divider()
    with st.expander("💼 Danh mục & Cảnh báo", expanded=False):
        render_portfolio_alert_panel(
            user_id=user_id,
            ticker=ticker,
            plan=plan,
            plan_label=plan_label,
            plan_id=plan_id,
            add_holding=add_holding,
            log_event=log_event,
            list_alerts=svc.pl.list_alerts,
            can_use_feature=svc.pl.can_use_feature,
            add_alert=add_alert,
        )

        cache_rep = st.session_state.get("report_cache") or {}
        render_decision_trade_panel(
            user_id=user_id,
            ticker=ticker,
            cache_rep=cache_rep,
            add_decision=add_decision,
            log_event=log_event,
            coach_decision_quality_adaptive=svc.pl.coach_decision_quality_adaptive,
            adaptive_position_sizing=svc.pl.adaptive_position_sizing,
            list_decisions=svc.pl.list_decisions,
            open_trade=open_trade,
            close_trade=close_trade,
        )

    st.divider()
    with st.expander("Bộ lọc cơ hội tự động", expanded=False):
        universe_total = sm.get_vn_universe_total()
        opp_cfg = render_opportunity_filter_panel(
            watchlist=watchlist,
            watchlist_default=watchlist_default,
            profile=profile,
            total_capital_vnd=float(total_capital_vnd),
            subtype_label_to_id=SUBTYPE_LABEL_TO_ID,
            compute_top5_for_profile=svc.compute_top5_for_profile,
            plan_scan_limit=int(plan.get("scan_limit") or 20),
            universe_total=universe_total,
        )
        min_avg_volume_20 = float(opp_cfg.get("min_avg_volume_20") or 0.0)
        universe_limit = int(opp_cfg.get("universe_limit") or 40)
        subtype_labels = list(opp_cfg.get("subtype_labels") or [])
        run_scan = bool(opp_cfg.get("run_scan"))

    return SidebarRuntimeState(
        runtime_cfg=runtime_cfg,
        watchlist=watchlist,
        ticker=ticker,
        autopilot_mode=autopilot_mode,
        profit_focus_mode=profit_focus_mode,
        autopilot_limit=autopilot_limit,
        autopilot_refresh=autopilot_refresh,
        quick_mode=quick_mode,
        run_analysis=run_analysis,
        min_avg_volume_20=min_avg_volume_20,
        universe_limit=universe_limit,
        subtype_labels=subtype_labels,
        run_scan=run_scan,
    )
