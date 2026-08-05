"""
Action reminder panel rendering.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import streamlit as st


def render_action_reminders(
    *,
    user_id: str,
    overdue_action_reminders: Callable[[str], list[dict[str, Any]]],
    dispatch_text_notifications: Callable[..., dict[str, Any]],
    log_event: Callable[..., Any],
    tg_bot: str,
    tg_chat: str,
    webhook_url: str,
    email_to: str,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    smtp_from: str,
) -> None:
    reminders_now = overdue_action_reminders(user_id)
    if not reminders_now:
        return

    with st.container():
        st.markdown("### 🔔 Action Reminders")
        for rm in reminders_now:
            sev = str(rm.get("severity") or "medium")
            if sev == "high":
                st.warning(f"{rm.get('title')}: {rm.get('message')}")
            else:
                st.info(f"{rm.get('title')}: {rm.get('message')}")
        if st.button("📨 Gửi nhắc việc qua kênh đã cấu hình", width="stretch"):
            text = "Nhắc việc quan trọng:\n" + "\n".join(
                [f"- {x.get('title')}: {x.get('message')}" for x in reminders_now]
            )
            ds = dispatch_text_notifications(
                text,
                telegram_bot_token=tg_bot,
                telegram_chat_id=tg_chat,
                webhook_url=webhook_url,
                email_to=email_to,
                smtp_host=smtp_host,
                smtp_port=smtp_port,
                smtp_user=smtp_user,
                smtp_password=smtp_password,
                smtp_from=smtp_from,
            )
            log_event(user_id, "reminder_dispatched", ds)
            st.caption(f"Dispatch: sent={ds['sent']} | failed={ds['failed']}")

