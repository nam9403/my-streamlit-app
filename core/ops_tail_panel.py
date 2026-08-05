from __future__ import annotations

from typing import Any, Callable

import pandas as pd
import streamlit as st

from core.notification_contracts import NotificationChannels


def render_ops_tail_panel(
    user_id: str,
    report: dict[str, Any],
    watchlist: list[str],
    watchlist_default: list[str],
    profile: str,
    total_capital_vnd: float,
    ticker: str,
    channels: NotificationChannels,
    session_state: dict[str, Any],
    *,
    get_source_sla_report: Callable[[], list[dict[str, Any]]],
    render_5s_panel: Callable[[dict[str, Any], list[dict[str, Any]]], None],
    build_action_center: Callable[..., pd.DataFrame],
    build_daily_playbook_text: Callable[..., str],
    dispatch_text_notifications: Callable[..., dict[str, Any]],
    log_event: Callable[..., Any],
    enqueue_notification: Callable[..., Any],
    render_scan_candidates_overview: Callable[..., None],
    build_portfolio_options: Callable[..., dict[str, pd.DataFrame]],
    render_admin_growth_panel: Callable[..., None],
    get_admin_kpi: Callable[..., dict[str, Any]],
    get_notification_queue_diagnostics: Callable[..., list[dict[str, Any]]],
    get_notification_fail_reason_summary: Callable[..., list[dict[str, Any]]],
    retry_failed_notifications: Callable[..., int],
    get_admin_cx_kpi: Callable[..., dict[str, Any]],
    get_upgrade_funnel: Callable[..., dict[str, Any]],
    select_upgrade_variant_auto: Callable[..., dict[str, Any]],
) -> None:
    st.subheader("🛜 SLA nguồn dữ liệu")
    sla_rows = get_source_sla_report()
    if sla_rows:
        st.dataframe(pd.DataFrame(sla_rows), width="stretch", hide_index=True)
    else:
        st.caption("Chưa có số liệu SLA nguồn.")
    render_5s_panel(report, sla_rows)

    try:
        from core.product_layer import get_forecast_portfolio_dashboard
        from core.trust_panel import render_trust_panel

        render_trust_panel(
            get_forecast_portfolio_dashboard=get_forecast_portfolio_dashboard,
            user_id=user_id,
        )
    except Exception:
        try:
            from core.trust_panel import render_trust_panel

            render_trust_panel(get_forecast_portfolio_dashboard=None, user_id=user_id)
        except Exception:
            pass
    try:
        from core.slo_ops_panel import render_slo_ops_panel

        render_slo_ops_panel()
    except Exception:
        pass
    try:
        from core.growth_cohort_panel import render_growth_cohort_panel
        from core.product_layer import _conn, get_admin_kpi, get_cohort_kpi, get_upgrade_funnel
        from core.referral_service import fetch_referral_stats

        render_growth_cohort_panel(
            user_id=user_id,
            get_cohort_kpi=get_cohort_kpi,
            get_upgrade_funnel=lambda days=30: get_upgrade_funnel(days=days),
            get_admin_kpi=lambda days=30: get_admin_kpi(days=days),
            referral_stats=lambda days=30: fetch_referral_stats(conn_factory=_conn, days=days),
        )
    except Exception:
        pass

    st.subheader("📬 Daily Playbook")
    action_df_for_playbook = build_action_center(
        tuple((watchlist or watchlist_default)[: min(12, len(watchlist or watchlist_default))]),
        profile,
        float(total_capital_vnd),
        top_n=6,
    )
    playbook_text = build_daily_playbook_text(action_df_for_playbook, ticker, report)
    st.code(playbook_text)
    if st.button("Gửi Daily Playbook ngay", width="stretch"):
        ds = dispatch_text_notifications(
            playbook_text,
            **channels.dispatch_kwargs(),
        )
        log_event(user_id, "playbook_dispatched", ds)
        st.caption(f"Dispatch: sent={ds['sent']} | failed={ds['failed']}")
        if int(ds.get("failed") or 0) > 0:
            # Chỉ lưu nội dung thô — credential được worker resolve từ kho secret theo user_id.
            enqueue_notification(
                user_id,
                "text",
                {"text": playbook_text},
                delay_seconds=90,
            )
            st.caption("Playbook lỗi gửi đã được đưa vào hàng đợi retry.")
    render_scan_candidates_overview(
        session_state,
        total_capital_vnd,
        build_portfolio_options=build_portfolio_options,
    )

    render_admin_growth_panel(
        email_to=channels.email_to,
        smtp_host=channels.smtp_host,
        smtp_port=channels.smtp_port,
        smtp_user=channels.smtp_user,
        smtp_password=channels.smtp_password,
        smtp_from=channels.smtp_from,
        tg_bot=channels.tg_bot,
        tg_chat=channels.tg_chat,
        webhook_url=channels.webhook_url,
        get_admin_kpi=get_admin_kpi,
        get_notification_queue_diagnostics=get_notification_queue_diagnostics,
        get_notification_fail_reason_summary=get_notification_fail_reason_summary,
        retry_failed_notifications=retry_failed_notifications,
        get_admin_cx_kpi=get_admin_cx_kpi,
        get_upgrade_funnel=get_upgrade_funnel,
        select_upgrade_variant_auto=select_upgrade_variant_auto,
        dispatch_text_notifications=dispatch_text_notifications,
    )
