"""
Watch board rendering panel.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd
import streamlit as st

from core.app_view_helpers import build_watch_rows


def render_watch_board(
    *,
    watchlist: list[str],
    watchlist_default: list[str],
    load_snapshot_cached: Callable[[str], dict[str, Any] | None],
) -> pd.DataFrame:
    watch_rows = build_watch_rows(
        watchlist=list(watchlist or []),
        watchlist_default=watchlist_default,
        load_snapshot_cached=load_snapshot_cached,
    )
    _display_cols = ["Mã", "Giá hiện tại", "Nguồn giá", "Trạng thái"]
    if not watch_rows:
        watch_df = pd.DataFrame(columns=_display_cols)
        with st.container():
            st.markdown("### 💹 Bảng giá theo dõi nhanh")
            st.caption("Watchlist trống — thêm mã ở sidebar để theo dõi giá.")
            st.dataframe(watch_df, use_container_width=True, hide_index=True)
        return watch_df

    watch_df = pd.DataFrame(watch_rows)
    for col in _display_cols:
        if col not in watch_df.columns:
            watch_df[col] = ""
    watch_df = watch_df[[c for c in _display_cols if c in watch_df.columns]]
    watch_df["__ready"] = (watch_df["Trạng thái"] == "Sẵn sàng").astype(int)
    watch_df = watch_df.sort_values(["__ready", "Mã"], ascending=[False, True]).drop(columns=["__ready"])
    with st.container():
        st.markdown("### 💹 Bảng giá theo dõi nhanh")
        st.dataframe(watch_df, use_container_width=True, hide_index=True)
    return watch_df

