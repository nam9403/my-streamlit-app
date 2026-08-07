from __future__ import annotations

from typing import Any, Callable

import streamlit as st


def render_portfolio_alert_panel(
    *,
    user_id: str,
    ticker: str,
    plan: dict[str, Any],
    plan_label: str,
    plan_id: str,
    add_holding: Callable[..., None],
    log_event: Callable[..., None],
    list_alerts: Callable[..., list[dict[str, Any]]],
    can_use_feature: Callable[..., tuple[bool, str]],
    add_alert: Callable[..., None],
) -> None:
    c1, c2 = st.columns(2)
    with c1:
        h_symbol = st.text_input("Mã thêm vào danh mục", value=ticker)
        h_qty = st.number_input("Số lượng", min_value=0.0, value=0.0, step=100.0)
    with c2:
        h_cost = st.number_input("Giá vốn", min_value=0.0, value=0.0, step=100.0)
        if st.button("➕ Lưu vị thế", use_container_width=True):
            if h_symbol and h_qty > 0 and h_cost > 0:
                add_holding(user_id, h_symbol, h_qty, h_cost)
                log_event(user_id, "holding_added", {"symbol": h_symbol.upper(), "qty": h_qty})
                st.success("Đã lưu vị thế.")
            else:
                st.warning("Nhập đủ Mã, Số lượng và Giá vốn > 0.")

    current_alerts = list_alerts(user_id)
    st.caption(f"Đã tạo {len(current_alerts)}/{plan['alerts']} cảnh báo theo gói {plan_label}.")
    a_symbol = st.text_input("Mã cảnh báo", value=ticker)
    a_type = st.selectbox(
        "Loại cảnh báo",
        options=["price_above", "price_below"],
        format_func=lambda x: "Giá vượt ngưỡng" if x == "price_above" else "Giá thủng ngưỡng",
    )
    a_threshold = st.number_input("Ngưỡng giá", min_value=0.0, value=0.0, step=100.0)
    a_note = st.text_input("Ghi chú", value="")
    if st.button("🔔 Tạo cảnh báo", use_container_width=True):
        ok_alert, msg_alert = can_use_feature(user_id, "alert", 1, plan_id=plan_id)
        if not ok_alert:
            st.error(msg_alert)
        elif a_symbol and a_threshold > 0:
            add_alert(user_id, a_symbol, a_type, a_threshold, a_note)
            log_event(user_id, "alert_created", {"symbol": a_symbol.upper(), "type": a_type})
            st.success("Đã tạo cảnh báo.")
        else:
            st.warning("Nhập mã và ngưỡng giá hợp lệ.")
