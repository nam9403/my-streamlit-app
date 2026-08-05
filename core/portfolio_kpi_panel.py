from __future__ import annotations

from typing import Any, Callable

import pandas as pd
import streamlit as st

from core.notification_contracts import NotificationChannels


def render_trade_alert_kpi_panel(
    user_id: str,
    plan_id: str,
    channels: NotificationChannels,
    *,
    list_trades: Callable[..., list[dict[str, Any]]],
    realized_performance: Callable[..., dict[str, Any]],
    execution_vs_plan_report: Callable[..., list[dict[str, Any]]],
    evaluate_alerts: Callable[[str], list[dict[str, Any]]],
    dispatch_alert_notifications: Callable[..., dict[str, Any]],
    dispatch_external_notifications: Callable[..., dict[str, Any]],
    log_event: Callable[..., Any],
    enqueue_notification: Callable[..., Any],
    get_kpi_dashboard: Callable[..., dict[str, Any]],
    get_cohort_kpi: Callable[..., dict[str, Any]],
    evaluate_decisions: Callable[..., list[dict[str, Any]]],
    decision_scorecard: Callable[..., dict[str, Any]],
    postmortem_report: Callable[..., list[dict[str, Any]]],
    monthly_value_report: Callable[..., dict[str, Any]],
    smart_upgrade_prompt: Callable[..., dict[str, Any]],
) -> None:
    st.subheader("📒 Trade Journal - Realized")
    trades = list_trades(user_id, limit=200)
    if trades:
        tdf = pd.DataFrame(trades)
        st.dataframe(tdf, width="stretch", hide_index=True)
        rp = realized_performance(user_id, days=30)
        r1, r2, r3, r4 = st.columns(4)
        with r1:
            st.metric("Closed trades (30d)", int(rp.get("closed_trades") or 0))
        with r2:
            st.metric("Realized PnL (30d)", f"{float(rp.get('realized_pnl_total') or 0):,.0f}")
        with r3:
            st.metric("Realized % avg", f"{float(rp.get('realized_pct_avg') or 0):.2f}%")
        with r4:
            st.metric("Win rate realized", f"{float(rp.get('win_rate_pct') or 0):.1f}%")
        st.markdown("#### 🧪 Kế hoạch vs Thực thi")
        evp = execution_vs_plan_report(user_id, limit=200)
        if evp:
            evp_df = pd.DataFrame(evp)
            st.dataframe(evp_df, width="stretch", hide_index=True)
        else:
            st.caption("Chưa có trade nào được link với decision để so sánh.")
    else:
        st.caption("Chưa có trade journal nào.")

    fired = evaluate_alerts(user_id)
    st.subheader("🔔 Cảnh báo kích hoạt")
    if fired:
        st.dataframe(pd.DataFrame(fired), width="stretch", hide_index=True)
        if channels.auto_notify:
            sent_stat = dispatch_alert_notifications(user_id, fired, channels.tg_bot, channels.tg_chat)
            ext_stat = dispatch_external_notifications(
                fired,
                webhook_url=channels.webhook_url,
                email_to=channels.email_to,
                smtp_host=channels.smtp_host,
                smtp_port=channels.smtp_port,
                smtp_user=channels.smtp_user,
                smtp_password=channels.smtp_password,
                smtp_from=channels.smtp_from,
            )
            st.caption(
                f"Telegram dispatch: sent={sent_stat['sent']} | "
                f"skipped={sent_stat['skipped']} | failed={sent_stat['failed']}"
            )
            st.caption(f"Webhook/Email dispatch: sent={ext_stat['sent']} | failed={ext_stat['failed']}")
            log_event(user_id, "alert_dispatched", {"telegram": sent_stat, "external": ext_stat})
            if int(sent_stat.get("failed") or 0) > 0:
                # Chỉ lưu nội dung thô — credential được worker resolve từ kho secret theo user_id.
                enqueue_notification(
                    user_id,
                    "alerts",
                    {"fired_alerts": fired},
                    delay_seconds=60,
                )
                st.caption("Một số alert lỗi gửi đã được đưa vào hàng đợi retry.")
    else:
        st.caption("Chưa có cảnh báo nào kích hoạt tại thời điểm hiện tại.")

    st.subheader("📈 KPI sử dụng")
    kpi = get_kpi_dashboard(user_id, days=30)
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Tổng sự kiện", int(kpi.get("events_total") or 0))
    with c2:
        st.metric("Số cảnh báo", int(kpi.get("alerts_total") or 0))
    with c3:
        st.metric("Số vị thế", int(kpi.get("holdings_total") or 0))
    by_event = kpi.get("by_event") or {}
    if by_event:
        ev_df = pd.DataFrame([{"event": k, "count": v} for k, v in by_event.items()]).sort_values("count", ascending=False)
        st.dataframe(ev_df, width="stretch", hide_index=True)

    cohort = get_cohort_kpi(user_id)
    st.subheader("📅 Cohort KPI (7/30 ngày)")
    cohort_df = pd.DataFrame(
        [
            {"Chỉ số": "Active days", "7 ngày": cohort["active_days_7"], "30 ngày": cohort["active_days_30"]},
            {"Chỉ số": "Analyses completed", "7 ngày": cohort["analysis_7"], "30 ngày": cohort["analysis_30"]},
            {"Chỉ số": "Alerts created", "7 ngày": cohort["alerts_created_7"], "30 ngày": cohort["alerts_created_30"]},
            {
                "Chỉ số": "Alerts dispatched",
                "7 ngày": cohort["alerts_dispatched_7"],
                "30 ngày": cohort["alerts_dispatched_30"],
            },
            {"Chỉ số": "Upgrade intent", "7 ngày": cohort["upgrade_intent_7"], "30 ngày": cohort["upgrade_intent_30"]},
            {
                "Chỉ số": "Upgrade success",
                "7 ngày": cohort["upgrade_success_7"],
                "30 ngày": cohort["upgrade_success_30"],
            },
        ]
    )
    st.dataframe(cohort_df, width="stretch", hide_index=True)

    st.subheader("🎯 Outcome Tracker (7/30/90)")
    dec_rows = evaluate_decisions(user_id, limit=120)
    if dec_rows:
        dec_df = pd.DataFrame(dec_rows)
        st.dataframe(dec_df, width="stretch", hide_index=True)
        closed = dec_df[dec_df["Trạng thái"].isin(["STOP_LOSS_HIT", "TAKE_PROFIT_HIT"])]
        tp_n = int((closed["Trạng thái"] == "TAKE_PROFIT_HIT").sum()) if not closed.empty else 0
        sl_n = int((closed["Trạng thái"] == "STOP_LOSS_HIT").sum()) if not closed.empty else 0
        win_rate = (tp_n / max(tp_n + sl_n, 1) * 100.0) if (tp_n + sl_n) > 0 else 0.0
        c_out1, c_out2, c_out3 = st.columns(3)
        with c_out1:
            st.metric("Quyết định đã lưu", len(dec_df))
        with c_out2:
            st.metric("TP hit / SL hit", f"{tp_n}/{sl_n}")
        with c_out3:
            st.metric("Win rate đã đóng", f"{win_rate:.1f}%")
        sc = decision_scorecard(user_id, limit=200)
        c_sc1, c_sc2, c_sc3, c_sc4 = st.columns(4)
        with c_sc1:
            st.metric("Discipline score", f"{float(sc.get('discipline_score') or 0):.1f}/100")
        with c_sc2:
            st.metric("RR trung bình", f"{float(sc.get('rr_avg') or 0):.2f}")
        with c_sc3:
            st.metric("P/L trung bình", f"{float(sc.get('pl_avg_pct') or 0):.2f}%")
        with c_sc4:
            st.metric("Win rate đóng", f"{float(sc.get('win_rate_closed_pct') or 0):.1f}%")

        pm7 = postmortem_report(user_id, days=7, limit=200)
        pm30 = postmortem_report(user_id, days=30, limit=200)
        st.markdown("#### 🧠 Auto Post-mortem")
        c_pm1, c_pm2 = st.columns(2)
        with c_pm1:
            st.caption("Post-mortem 7 ngày")
            if pm7:
                st.dataframe(pd.DataFrame(pm7).head(10), width="stretch", hide_index=True)
            else:
                st.caption("Chưa có quyết định đủ tuổi 7 ngày.")
        with c_pm2:
            st.caption("Post-mortem 30 ngày")
            if pm30:
                st.dataframe(pd.DataFrame(pm30).head(10), width="stretch", hide_index=True)
            else:
                st.caption("Chưa có quyết định đủ tuổi 30 ngày.")

        mv = monthly_value_report(user_id)
        st.markdown("#### 💎 Monthly Value Report")
        st.caption(str(mv.get("value_summary") or ""))
        mv_df = pd.DataFrame(
            [
                {"Chỉ số": "Plan", "Giá trị": mv.get("plan_id")},
                {"Chỉ số": "Analyses 30d", "Giá trị": mv.get("analysis_30d")},
                {"Chỉ số": "Alerts dispatched 30d", "Giá trị": mv.get("alerts_dispatched_30d")},
                {"Chỉ số": "Decisions logged", "Giá trị": mv.get("decisions_logged")},
                {"Chỉ số": "Discipline score", "Giá trị": mv.get("discipline_score")},
                {"Chỉ số": "Avg P/L %", "Giá trị": mv.get("avg_pl_pct")},
                {"Chỉ số": "Win rate closed %", "Giá trị": mv.get("win_rate_closed_pct")},
            ]
        )
        st.dataframe(mv_df, width="stretch", hide_index=True)
    else:
        st.caption("Chưa có quyết định nào. Hãy lưu quyết định để app hậu kiểm giá trị thực.")

    if plan_id == "free":
        sup = smart_upgrade_prompt(user_id, plan_id)
        if bool(sup.get("show")):
            log_event(
                user_id,
                "upgrade_prompt_view",
                {
                    "variant": sup.get("variant"),
                    "variant_source": sup.get("variant_source"),
                    "plan": sup.get("cta_plan"),
                    "roi_x": sup.get("roi_fee_x"),
                    "maturity": sup.get("maturity_score_10"),
                },
            )
            st.info(f"💡 {sup.get('title')}\n\n{sup.get('message')}")
            cta1, cta2 = st.columns(2)
            with cta1:
                if st.button("🚀 Nâng cấp ngay", width="stretch"):
                    log_event(
                        user_id,
                        "upgrade_cta_click",
                        {
                            "variant": sup.get("variant"),
                            "plan": sup.get("cta_plan"),
                            "roi_x": sup.get("roi_fee_x"),
                            "maturity": sup.get("maturity_score_10"),
                        },
                    )
                    st.success("Đã ghi nhận nhu cầu nâng cấp. Vào mục Billing để xác nhận.")
            with cta2:
                if st.button("❓ Xem chi tiết giá trị", width="stretch"):
                    log_event(user_id, "upgrade_info_click", {"variant": sup.get("variant")})
                    st.caption(
                        f"ROI fee x: {sup.get('roi_fee_x')} | "
                        f"Maturity: {sup.get('maturity_score_10')}/10 | "
                        f"Analysis 30d: {sup.get('analysis_30d')}"
                    )
