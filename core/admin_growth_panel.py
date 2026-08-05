from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

import pandas as pd
import streamlit as st


def render_admin_growth_panel(
    *,
    email_to: str,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    smtp_from: str,
    tg_bot: str,
    tg_chat: str,
    webhook_url: str,
    get_admin_kpi: Callable[..., dict[str, Any]],
    get_notification_queue_diagnostics: Callable[..., list[dict[str, Any]]],
    get_notification_fail_reason_summary: Callable[..., list[dict[str, Any]]],
    retry_failed_notifications: Callable[..., int],
    get_admin_cx_kpi: Callable[..., dict[str, Any]],
    get_upgrade_funnel: Callable[..., list[dict[str, Any]]],
    select_upgrade_variant_auto: Callable[..., dict[str, Any]],
    dispatch_text_notifications: Callable[..., dict[str, int]],
) -> None:
    st.markdown("---")
    st.subheader("🧑‍💼 Admin Growth KPI (30 ngày)")
    admin = get_admin_kpi(days=30)
    a1, a2, a3, a4 = st.columns(4)
    with a1:
        st.metric("Users", int(admin.get("users_total") or 0))
    with a2:
        st.metric("Active users (30d)", int(admin.get("active_users_period") or 0))
    with a3:
        st.metric("Events (30d)", int(admin.get("events_period") or 0))
    with a4:
        st.metric("Alerts total", int(admin.get("alerts_total") or 0))
    plans_df = pd.DataFrame(admin.get("plans") or [])
    if not plans_df.empty:
        st.caption("Phân bổ gói dịch vụ")
        st.dataframe(plans_df, width="stretch", hide_index=True)
    ev_df = pd.DataFrame(admin.get("events_by_type") or [])
    if not ev_df.empty:
        st.caption("Sự kiện theo loại (30 ngày)")
        st.dataframe(ev_df, width="stretch", hide_index=True)
    q_df = pd.DataFrame(admin.get("notification_queue") or [])
    if not q_df.empty:
        st.caption("Trạng thái hàng đợi notification")
        st.dataframe(q_df, width="stretch", hide_index=True)
    obs = admin.get("notification_observability") or {}
    obs_reasons_df = pd.DataFrame(obs.get("fail_reasons") or [])
    obs_tiers_df = pd.DataFrame(obs.get("retry_tiers") or [])
    if not obs_reasons_df.empty or not obs_tiers_df.empty:
        st.caption("Queue observability dashboard")
        o1, o2, o3 = st.columns(3)
        high_retry_count = 0
        if not obs_tiers_df.empty:
            high_retry_count = int(
                obs_tiers_df[obs_tiers_df["retry_tier"].isin(["t3_4", "t5_plus"])]["count"].sum()
            )
        with o1:
            st.metric("High retry jobs (t3+)", high_retry_count)
        with o2:
            st.metric("Fail reasons (14-30d)", int(len(obs_reasons_df.index)))
        with o3:
            st.metric("Retry buckets", int(len(obs_tiers_df.index)))
        c_obs1, c_obs2 = st.columns(2)
        with c_obs1:
            if not obs_reasons_df.empty:
                st.caption("Fail reasons (from admin KPI)")
                st.dataframe(obs_reasons_df, width="stretch", hide_index=True)
        with c_obs2:
            if not obs_tiers_df.empty:
                st.caption("Retry tier distribution")
                st.dataframe(obs_tiers_df, width="stretch", hide_index=True)
        if high_retry_count > 0:
            st.warning("Có job retry cao (t3+). Ưu tiên xử lý root cause để tránh queue burn.")
    cqd1, cqd2 = st.columns([2, 1])
    with cqd2:
        if st.button("Retry failed queue", width="stretch"):
            retried_n = retry_failed_notifications(max_rows=50)
            st.caption(f"Đã chuyển {retried_n} job failed về pending.")
    diag_df = pd.DataFrame(get_notification_queue_diagnostics(limit=30))
    if not diag_df.empty:
        with cqd1:
            st.caption("Queue diagnostics (failed/pending ưu tiên)")
        st.dataframe(diag_df, width="stretch", hide_index=True)
    fail_reason_df = pd.DataFrame(get_notification_fail_reason_summary(days=14, limit=10))
    if not fail_reason_df.empty:
        st.caption("Top nguyên nhân queue fail (14 ngày)")
        st.dataframe(fail_reason_df, width="stretch", hide_index=True)
        reason_priority_weight = {
            "invalid_payload": 10,
            "smtp_alert": 9,
            "smtp_text": 9,
            "webhook_alert": 7,
            "webhook_text": 7,
            "telegram_alert": 6,
            "telegram_text": 6,
            "max_retries": 8,
        }
        priority_rows: list[dict[str, object]] = []
        for _, rr in fail_reason_df.iterrows():
            reason = str(rr.get("reason") or "").strip().lower()
            count = int(rr.get("count") or 0)
            weight = int(reason_priority_weight.get(reason, 5))
            impact = count * weight
            if impact >= 40:
                level = "P0"
            elif impact >= 20:
                level = "P1"
            else:
                level = "P2"
            priority_rows.append(
                {
                    "priority": level,
                    "reason": reason or "unknown",
                    "count": count,
                    "impact_score": impact,
                    "action": (
                        "Fix payload source and retry"
                        if reason.startswith("invalid_payload")
                        else "Run channel test and fix config"
                    ),
                }
            )
        if priority_rows:
            pr_df = pd.DataFrame(priority_rows).sort_values(by=["impact_score", "count"], ascending=[False, False])
            st.caption("Auto-priority fix list")
            st.dataframe(pr_df, width="stretch", hide_index=True)
            top_fix = dict(pr_df.iloc[0])
            st.caption(
                f"Ưu tiên hiện tại: {top_fix.get('priority')} | reason={top_fix.get('reason')} | "
                f"impact={int(top_fix.get('impact_score') or 0)}"
            )
        top_row = fail_reason_df.iloc[0]
        top_reason = str(top_row.get("reason") or "").strip().lower()
        st.caption(f"Gợi ý xử lý nhanh theo nguyên nhân chính: `{top_reason or 'unknown'}`")
        if top_reason.startswith("smtp"):
            st.warning("Ưu tiên kiểm tra SMTP host/user/password/from và quyền gửi của tài khoản mail.")
            if st.button("🧪 Test SMTP nhanh", width="stretch"):
                smtp_test = dispatch_text_notifications(
                    f"[SMTP TEST] {datetime.now(timezone.utc).strftime('%H:%M:%SZ')}",
                    email_to=email_to,
                    smtp_host=smtp_host,
                    smtp_port=smtp_port,
                    smtp_user=smtp_user,
                    smtp_password=smtp_password,
                    smtp_from=smtp_from,
                )
                st.caption(f"SMTP test sent={int(smtp_test.get('sent') or 0)} | failed={int(smtp_test.get('failed') or 0)}")
        elif top_reason.startswith("webhook"):
            st.warning("Ưu tiên kiểm tra webhook URL, timeout và endpoint nhận payload.")
            if st.button("🧪 Test Webhook nhanh", width="stretch"):
                webhook_test = dispatch_text_notifications(
                    f"[WEBHOOK TEST] {datetime.now(timezone.utc).strftime('%H:%M:%SZ')}",
                    webhook_url=webhook_url,
                )
                st.caption(
                    f"Webhook test sent={int(webhook_test.get('sent') or 0)} | failed={int(webhook_test.get('failed') or 0)}"
                )
        elif top_reason.startswith("telegram"):
            st.warning("Ưu tiên kiểm tra Telegram bot token/chat id và quyền bot trong nhóm.")
            if st.button("🧪 Test Telegram nhanh", width="stretch"):
                telegram_test = dispatch_text_notifications(
                    f"[TELEGRAM TEST] {datetime.now(timezone.utc).strftime('%H:%M:%SZ')}",
                    telegram_bot_token=tg_bot,
                    telegram_chat_id=tg_chat,
                )
                st.caption(
                    f"Telegram test sent={int(telegram_test.get('sent') or 0)} | failed={int(telegram_test.get('failed') or 0)}"
                )
        elif top_reason.startswith("invalid_payload"):
            st.warning("Queue có payload lỗi định dạng. Nên retry failed sau khi xác nhận payload upstream.")
            if st.button("♻️ Retry failed ngay (guided)", width="stretch"):
                moved = retry_failed_notifications(max_rows=50)
                st.caption(f"Đã đưa {moved} job failed về pending để xử lý lại.")
        else:
            st.info("Kiểm tra `sample_error` trong bảng để khoanh vùng nguyên nhân và chạy test kênh tương ứng.")
    cx_admin = get_admin_cx_kpi(days=14)
    b1, b2 = st.columns(2)
    with b1:
        st.metric("CX avg (14d)", f"{float(cx_admin.get('avg_score') or 0):.1f}/100")
    with b2:
        st.metric("CX samples (14d)", int(cx_admin.get("samples") or 0))
    cx_band_df = pd.DataFrame(cx_admin.get("bands") or [])
    if not cx_band_df.empty:
        st.caption("Phân bổ CX band (14 ngày)")
        st.dataframe(cx_band_df, width="stretch", hide_index=True)
    cx_trend_df = pd.DataFrame(cx_admin.get("trend") or [])
    if not cx_trend_df.empty:
        st.caption("Xu hướng CX theo ngày")
        st.dataframe(cx_trend_df, width="stretch", hide_index=True)
    st.caption("Funnel nâng cấp theo variant (30 ngày)")
    uf = get_upgrade_funnel(days=30)
    if uf:
        st.dataframe(pd.DataFrame(uf), width="stretch", hide_index=True)
        pick = select_upgrade_variant_auto(days=30)
        st.caption(
            f"Auto-selected variant hiện tại: `{pick.get('variant')}` "
            f"(reason={pick.get('reason')}, score={pick.get('score', 'n/a')})"
        )
    else:
        st.caption("Chưa có dữ liệu funnel nâng cấp.")
