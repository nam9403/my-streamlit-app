"""
Daily action list rendering panel.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd
import streamlit as st


def render_daily_action_panel(
    *,
    user_id: str,
    plan: dict[str, Any],
    profile: str,
    total_capital_vnd: float,
    effective_quick_mode: bool,
    list_holdings: Callable[[str], list[dict[str, Any]]],
    list_universe_symbols: Callable[..., list[str]],
    build_daily_action_list: Callable[..., pd.DataFrame],
) -> pd.DataFrame | None:
    st.markdown("### 📌 Daily Action List (hôm nay nên làm gì)")
    if st.button("Tải Daily Action List", key="load_daily_action_list_btn", width="content"):
        held_syms = tuple(str(x.get("symbol") or "").upper() for x in list_holdings(user_id))
        daily_universe = tuple(list_universe_symbols(limit=min(60, int(plan["scan_limit"]))))
        with st.spinner("Đang dựng Daily Action List (chạy nền dữ liệu)..."):
            daily_actions = build_daily_action_list(
                daily_universe,
                profile,
                float(total_capital_vnd),
                held_syms,
                quick_mode=effective_quick_mode,
                llm_live=bool(plan["llm_live"]),
            )
        st.session_state["daily_actions_df"] = daily_actions

    daily_actions = st.session_state.get("daily_actions_df")
    if isinstance(daily_actions, pd.DataFrame):
        if daily_actions.empty:
            st.caption("Chưa đủ dữ liệu để dựng Daily Action List.")
        else:
            st.dataframe(daily_actions.head(12), width="stretch", hide_index=True)
            st.caption("Ưu tiên thực thi từ trên xuống: BUY -> HOLD -> WATCH -> SELL.")
    else:
        st.caption("Mặc định không tải khối này khi mở app để tối ưu tốc độ. Bấm 'Tải Daily Action List' khi cần.")
    return daily_actions if isinstance(daily_actions, pd.DataFrame) else None

