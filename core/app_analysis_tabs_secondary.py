"""
Render secondary analysis tabs (AI + finance) — self-wired panels + ui_services.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from core import ui_services as svc
from core.action_center_panel import (
    build_action_center,
    build_daily_playbook_text,
    build_portfolio_options,
    render_scan_candidates_overview,
)
from core.admin_growth_panel import render_admin_growth_panel
from core.ai_logic import get_provider_health_snapshot
from core.analysis_ai_panel import render_ai_chat_style, render_ai_health_panel
from core.analysis_financial_panel import render_financial_health_tab
from core.analysis_view_panel import render_5s_panel, render_evidence
from core.ops_tail_panel import render_ops_tail_panel
from core.portfolio_kpi_panel import render_trade_alert_kpi_panel
from core.portfolio_overview_panel import render_portfolio_overview
from core.ui_services import GuardedMutations
from scrapers.portal import get_source_sla_report


def render_secondary_analysis_tabs(
    *,
    show_ai: bool,
    show_finance: bool,
    ticker: str,
    report: dict[str, Any],
    valuation: dict[str, Any],
    ohlcv: Any,
    user_id: str,
    plan_id: str,
    notify_cfg: Any,
    watchlist: list[str],
    watchlist_default: list[str],
    profile: str,
    total_capital_vnd: float,
    mutations: GuardedMutations | None = None,
) -> None:
    _ = valuation, ohlcv  # reserved for chart deep-links in future
    mut = mutations
    log_event = mut.log_event if mut else svc.pl.log_event
    dispatch_alert_notifications = (
        mut.dispatch_alert_notifications if mut else svc.pl.dispatch_alert_notifications
    )
    dispatch_external_notifications = (
        mut.dispatch_external_notifications if mut else svc.pl.dispatch_external_notifications
    )
    enqueue_notification = mut.enqueue_notification if mut else svc.pl.enqueue_notification
    dispatch_text_notifications = (
        mut.dispatch_text_notifications if mut else svc.pl.dispatch_text_notifications
    )
    retry_failed_notifications = (
        mut.retry_failed_notifications if mut else svc.pl.retry_failed_notifications
    )

    if show_ai:
        render_ai_chat_style(report)
        with st.expander("Theo dõi AI Health", expanded=False):
            render_ai_health_panel(get_provider_health_snapshot=get_provider_health_snapshot)

    if show_finance:
        with st.expander("📌 Tóm tắt tài chính cốt lõi", expanded=True):
            render_financial_health_tab(report)
        with st.expander("🧾 Bằng chứng dữ liệu chi tiết", expanded=False):
            render_evidence(report)
        st.markdown("---")
        render_portfolio_overview(user_id, portfolio_snapshot=svc.pl.portfolio_snapshot)

        render_trade_alert_kpi_panel(
            user_id,
            plan_id,
            notify_cfg,
            list_trades=svc.pl.list_trades,
            realized_performance=svc.pl.realized_performance,
            execution_vs_plan_report=svc.pl.execution_vs_plan_report,
            evaluate_alerts=svc.pl.evaluate_alerts,
            dispatch_alert_notifications=dispatch_alert_notifications,
            dispatch_external_notifications=dispatch_external_notifications,
            log_event=log_event,
            enqueue_notification=enqueue_notification,
            get_kpi_dashboard=svc.pl.get_kpi_dashboard,
            get_cohort_kpi=svc.pl.get_cohort_kpi,
            evaluate_decisions=svc.pl.evaluate_decisions,
            decision_scorecard=svc.pl.decision_scorecard,
            postmortem_report=svc.pl.postmortem_report,
            monthly_value_report=svc.pl.monthly_value_report,
            smart_upgrade_prompt=svc.pl.smart_upgrade_prompt,
        )

        render_ops_tail_panel(
            user_id,
            report,
            watchlist,
            watchlist_default,
            profile,
            total_capital_vnd,
            ticker,
            notify_cfg,
            st.session_state,
            get_source_sla_report=get_source_sla_report,
            render_5s_panel=render_5s_panel,
            build_action_center=build_action_center,
            build_daily_playbook_text=build_daily_playbook_text,
            dispatch_text_notifications=dispatch_text_notifications,
            log_event=log_event,
            enqueue_notification=enqueue_notification,
            render_scan_candidates_overview=render_scan_candidates_overview,
            build_portfolio_options=build_portfolio_options,
            render_admin_growth_panel=render_admin_growth_panel,
            get_admin_kpi=svc.pl.get_admin_kpi,
            get_notification_queue_diagnostics=svc.pl.get_notification_queue_diagnostics,
            get_notification_fail_reason_summary=svc.pl.get_notification_fail_reason_summary,
            retry_failed_notifications=retry_failed_notifications,
            get_admin_cx_kpi=svc.pl.get_admin_cx_kpi,
            get_upgrade_funnel=svc.pl.get_upgrade_funnel,
            select_upgrade_variant_auto=svc.pl.select_upgrade_variant_auto,
        )
