from __future__ import annotations

import streamlit as st


def render_experience_panel(
    *,
    auth_ready: bool,
    tg_bot: str,
    tg_chat: str,
    webhook_url: str,
    email_to: str,
    smtp_host: str,
    smtp_user: str,
    smtp_password: str,
    watchlist: list[str],
    ticker: str,
) -> None:
    channel_ready = bool((tg_bot and tg_chat) or webhook_url or (email_to and smtp_host and smtp_user and smtp_password))
    watch_ready = len(watchlist) >= 3
    flow_ready = bool(ticker and ticker.strip())
    score = int(auth_ready) + int(channel_ready) + int(watch_ready) + int(flow_ready)
    st.progress(score / 4.0, text=f"Experience readiness: {score}/4")
    st.caption(
        " • ".join(
            [
                f"Auth: {'OK' if auth_ready else 'Thiếu'}",
                f"Kênh gửi: {'OK' if channel_ready else 'Thiếu'}",
                f"Watchlist: {'OK' if watch_ready else 'Nên >=3 mã'}",
                f"Ticker: {'OK' if flow_ready else 'Thiếu'}",
            ]
        )
    )
    if score < 4:
        st.info("Gợi ý: hoàn tất các mục còn thiếu để trải nghiệm mượt và cá nhân hóa tốt hơn.")
    else:
        st.success("Trải nghiệm đã ở mức tốt, sẵn sàng dùng luồng chính hằng ngày.")
