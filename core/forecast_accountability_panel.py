from __future__ import annotations

from typing import Any, Callable

import streamlit as st

from core.notification_contracts import NotificationChannels


def render_forecast_accountability_actions(
    user_id: str,
    ticker: str,
    report: dict[str, Any],
    channels: NotificationChannels,
    *,
    export_forecast_health_report: Callable[[str], str],
    get_forecast_drift_streak: Callable[..., dict[str, Any]],
    export_model_accountability_report: Callable[[str], str],
    export_monthly_accountability_markdown: Callable[[str], str],
    send_monthly_accountability_email: Callable[..., tuple[bool, str]],
    log_event: Callable[..., Any],
) -> None:
    c_rep1, c_rep2 = st.columns(2)
    with c_rep1:
        if st.button("Xuất report forecast health", use_container_width=True):
            out_path = export_forecast_health_report(user_id)
            st.success(f"Đã xuất report: {out_path}")
            log_event(user_id, "forecast_health_exported", {"path": out_path, "ticker": ticker})
    with c_rep2:
        if st.button("Đánh giá drift kéo dài", use_container_width=True):
            ds = get_forecast_drift_streak(user_id, ticker, checks=3)
            st.info(f"Drift streak hiện tại: {int(ds.get('drift_down_streak') or 0)}/{int(ds.get('checks') or 0)}")
    if st.button("Xuất model accountability report", use_container_width=True):
        out_path = export_model_accountability_report(user_id)
        st.success(f"Đã xuất accountability report: {out_path}")
        log_event(user_id, "model_accountability_exported", {"path": out_path, "ticker": ticker})
    c_rep3, c_rep4 = st.columns(2)
    with c_rep3:
        if st.button("Xuất monthly accountability (Markdown)", use_container_width=True):
            out_md = export_monthly_accountability_markdown(user_id)
            st.success(f"Đã xuất monthly report: {out_md}")
            log_event(user_id, "monthly_accountability_exported", {"path": out_md, "ticker": ticker})
    with c_rep4:
        if st.button("Gửi monthly report qua email", use_container_width=True):
            if not channels.smtp_ready():
                st.warning("Thiếu cấu hình SMTP/Email. Vào phần Notification để cấu hình trước khi gửi.")
                return
            ok_mail, msg_mail = send_monthly_accountability_email(
                user_id,
                channels.email_to,
                smtp_host=channels.smtp_host,
                smtp_port=channels.smtp_port,
                smtp_user=channels.smtp_user,
                smtp_password=channels.smtp_password,
                smtp_from=channels.smtp_from,
            )
            if ok_mail:
                st.success(f"Đã gửi monthly report: {msg_mail}")
                log_event(user_id, "monthly_accountability_emailed", {"path": msg_mail, "ticker": ticker})
            else:
                st.warning(f"Gửi email thất bại: {msg_mail}")
    st.caption(f"Chế độ AI tự chọn cho mã này: `{report.get('task_mode_used', 'balanced')}`")
    dg = report.get("drift_guardrails") or {}
    if dg.get("applied"):
        st.warning(
            "Đã kích hoạt drift guardrails: ép mode `quality` và giảm tỷ trọng vị thế "
            f"({float(dg.get('max_position_pct_before') or 0):.2f}% -> {float(dg.get('max_position_pct_after') or 0):.2f}%)."
        )
