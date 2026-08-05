from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Callable

import streamlit as st

from core.notification_contracts import NotificationChannels


def render_notification_settings(
    user_id: str,
    *,
    load_secret: Callable[..., str],
    save_secret: Callable[..., Any],
    dispatch_text_notifications: Callable[..., dict[str, Any]],
) -> NotificationChannels:
    tg_bot = st.text_input(
        "Telegram Bot Token",
        value=load_secret(user_id, "telegram_bot_token", os.environ.get("TELEGRAM_BOT_TOKEN", "")),
        type="password",
        help="Dùng để gửi alert realtime ra Telegram.",
    )
    tg_chat = st.text_input(
        "Telegram Chat ID",
        value=load_secret(user_id, "telegram_chat_id", os.environ.get("TELEGRAM_CHAT_ID", "")),
        help="Chat cá nhân/nhóm nhận alert.",
    )
    webhook_url = st.text_input(
        "Webhook URL (tuỳ chọn)",
        value=load_secret(user_id, "alert_webhook_url", os.environ.get("ALERT_WEBHOOK_URL", "")),
        help="Nhận JSON alert để tích hợp hệ thống ngoài.",
    )
    email_to = st.text_input("Email nhận alert (tuỳ chọn)", value=load_secret(user_id, "alert_email_to", os.environ.get("ALERT_EMAIL_TO", "")))
    smtp_host = st.text_input("SMTP host", value=load_secret(user_id, "smtp_host", os.environ.get("SMTP_HOST", "")))
    smtp_port = int(load_secret(user_id, "smtp_port", os.environ.get("SMTP_PORT", "587")) or 587)
    smtp_user = st.text_input("SMTP user", value=load_secret(user_id, "smtp_user", os.environ.get("SMTP_USER", "")))
    smtp_password = st.text_input("SMTP password", value=load_secret(user_id, "smtp_password", os.environ.get("SMTP_PASSWORD", "")), type="password")
    smtp_from = st.text_input("SMTP from", value=load_secret(user_id, "smtp_from", os.environ.get("SMTP_FROM", "")))
    if st.button("💾 Lưu cấu hình kênh gửi an toàn", width="stretch"):
        save_secret(user_id, "telegram_bot_token", tg_bot)
        save_secret(user_id, "telegram_chat_id", tg_chat)
        save_secret(user_id, "alert_webhook_url", webhook_url)
        save_secret(user_id, "alert_email_to", email_to)
        save_secret(user_id, "smtp_host", smtp_host)
        save_secret(user_id, "smtp_port", str(smtp_port))
        save_secret(user_id, "smtp_user", smtp_user)
        save_secret(user_id, "smtp_password", smtp_password)
        save_secret(user_id, "smtp_from", smtp_from)
        st.success("Đã lưu cấu hình kênh gửi vào kho bí mật cục bộ.")
    test_notify_msg = st.text_input(
        "Tin nhắn test notification",
        value=f"[TEST] Investment Intelligence ping @ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%SZ')}",
    )
    if st.button("📨 Gửi test notification", width="stretch"):
        cfg = NotificationChannels(
            tg_bot=tg_bot,
            tg_chat=tg_chat,
            webhook_url=webhook_url,
            email_to=email_to,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_user=smtp_user,
            smtp_password=smtp_password,
            smtp_from=smtp_from,
        )
        test_stat = dispatch_text_notifications(test_notify_msg, **cfg.dispatch_kwargs())
        sent_n = int(test_stat.get("sent") or 0)
        fail_n = int(test_stat.get("failed") or 0)
        if sent_n > 0 and fail_n == 0:
            st.success(f"Test thành công. sent={sent_n}, failed={fail_n}")
        elif sent_n > 0:
            st.warning(f"Test gửi một phần. sent={sent_n}, failed={fail_n}")
        else:
            st.error("Test thất bại. Kiểm tra token/chat_id/webhook/SMTP.")
    auto_notify = st.toggle("🔔 Tự động gửi Telegram khi alert kích hoạt", value=False)
    return NotificationChannels(
        tg_bot=tg_bot,
        tg_chat=tg_chat,
        webhook_url=webhook_url,
        email_to=email_to,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_user=smtp_user,
        smtp_password=smtp_password,
        smtp_from=smtp_from,
        auto_notify=auto_notify,
    )
