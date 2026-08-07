from __future__ import annotations

from typing import Any, Callable

import streamlit as st

from core.ui_widgets import safe_int_range_control


def render_opportunity_filter_panel(
    *,
    watchlist: list[str],
    watchlist_default: list[str],
    profile: str,
    total_capital_vnd: float,
    subtype_label_to_id: dict[str, str],
    compute_top5_for_profile: Callable[..., Any],
    plan_scan_limit: int,
    universe_total: int,
) -> dict[str, Any]:
    st.markdown("### Top 5 theo profile")
    run_top5 = st.button("Tính Top 5", use_container_width=True)
    if run_top5:
        top5 = compute_top5_for_profile(tuple((watchlist or watchlist_default)[:12]), profile)
        st.session_state["top5_df"] = top5
    if "top5_df" in st.session_state:
        st.dataframe(st.session_state["top5_df"], use_container_width=True, hide_index=True)
    else:
        st.caption("Chưa chạy Top 5. Bấm **Tính Top 5** khi cần.")

    min_avg_volume_20 = float(
        st.number_input("Thanh khoản tối thiểu (Avg Vol20)", min_value=0.0, value=300_000.0, step=100_000.0)
    )
    slider_key = "opp_universe_limit"
    max_limit = max(20, min(4000, int(plan_scan_limit or 20)))
    if slider_key not in st.session_state:
        st.session_state[slider_key] = int(min(300, max_limit))
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Quét toàn thị trường (full)", use_container_width=True):
            st.session_state[slider_key] = int(max_limit)
    with c2:
        st.caption(f"Universe hiện có: **{int(universe_total)}** mã")
    # Guard: Streamlit slider requires min < max (quota==20 previously crashed login UX).
    default_limit = int(st.session_state.get(slider_key) or min(300, max_limit))
    universe_limit = safe_int_range_control(
        "Số mã quét từ universe",
        min_value=20,
        max_value=int(max_limit),
        value=default_limit,
        step=20,
        key=slider_key,
    )
    universe_limit = int(max(20, min(max_limit, int(universe_limit))))
    st.caption(f"Giới hạn gói hiện tại: **{max_limit}** mã/lần quét.")
    subtype_labels = st.multiselect(
        "Lọc theo tiểu ngành",
        options=list(subtype_label_to_id.keys()),
        default=[],
        help="Để trống = quét toàn bộ tiểu ngành trong universe.",
    )
    run_scan = st.button("🔎 Quét cơ hội tự động", use_container_width=True)

    return {
        "min_avg_volume_20": min_avg_volume_20,
        "universe_limit": universe_limit,
        "subtype_labels": subtype_labels,
        "run_scan": bool(run_scan),
    }
