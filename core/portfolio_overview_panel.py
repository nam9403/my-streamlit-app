from __future__ import annotations

from typing import Any, Callable

import pandas as pd
import streamlit as st


def render_portfolio_overview(user_id: str, *, portfolio_snapshot: Callable[[str], list[dict[str, Any]]]) -> None:
    st.subheader("💼 Danh mục cá nhân")
    pf_rows = portfolio_snapshot(user_id)
    if pf_rows:
        pf_df = pd.DataFrame(pf_rows)
        st.dataframe(pf_df, use_container_width=True, hide_index=True)
        total_value = float(pf_df["Giá trị"].sum())
        total_pnl = float(pf_df["Lãi/Lỗ"].sum())
        st.caption(f"Tổng giá trị: {total_value:,.0f} VND | Lãi/Lỗ: {total_pnl:,.0f} VND")
    else:
        st.caption("Chưa có vị thế nào trong danh mục.")
