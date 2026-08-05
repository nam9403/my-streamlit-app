from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st


def render_financial_health_tab(report: dict[str, Any]) -> None:
    val = report.get("valuation", {})
    pio = val.get("piotroski_block") or {}
    rev = float(pio.get("revenue") or 0)
    rev_p = float(pio.get("revenue_prior") or 0)
    ni = float(pio.get("net_income") or 0)
    ni_p = float(pio.get("net_income_prior") or 0)
    fscore = int(val.get("piotroski_score") or 0)

    c1, c2 = st.columns(2)
    with c1:
        if rev > 0 or rev_p > 0:
            df_rev = pd.DataFrame({"Kỳ trước": [rev_p], "Hiện tại": [rev]}, index=["Doanh thu"])
            st.bar_chart(df_rev.T)
        else:
            st.info("Thiếu dữ liệu doanh thu.")
    with c2:
        if ni > 0 or ni_p > 0:
            df_ni = pd.DataFrame({"Kỳ trước": [ni_p], "Hiện tại": [ni]}, index=["Lợi nhuận"])
            st.bar_chart(df_ni.T)
        else:
            st.info("Thiếu dữ liệu lợi nhuận.")
    c3, c4 = st.columns(2)
    with c3:
        st.metric("📊 F-Score", f"{fscore}/9")
    with c4:
        bt = report.get("backtest_summary") or {}
        st.metric(
            "🧪 Backtest BUY win-rate",
            f"{float(bt.get('buy_win_rate_pct') or 0):.1f}%",
            help=f"Mẫu: {bt.get('buy_signals', 0)} tín hiệu BUY / {bt.get('samples', 0)} phiên",
        )
