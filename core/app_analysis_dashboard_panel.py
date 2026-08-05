"""
Quick analysis dashboard rendering.
"""

from __future__ import annotations

from typing import Any

import streamlit as st


def render_analysis_quick_dashboard(*, ticker: str, report: dict[str, Any]) -> dict[str, Any]:
    valuation = report.get("valuation", {}) or {}
    phase_q = report.get("phase", {}) or {}
    phase_metrics_q = phase_q.get("metrics", {}) or {}
    action_q_raw = str(report.get("final_action") or "HOLD").upper()
    action_q = "SELL" if action_q_raw == "AVOID" else action_q_raw
    conf_q = float(report.get("confidence_score") or 0)
    price_q = float(valuation.get("price") or 0)
    intrinsic_q = float(valuation.get("composite_target_price") or valuation.get("intrinsic_value_graham") or 0)
    mos_q = float(valuation.get("margin_of_safety_composite_pct") or 0)
    vol_q = float(phase_metrics_q.get("vol_multiple") or 0)
    phase_name_q = str(phase_q.get("phase") or "neutral").upper()
    action_color = "#00f4b0" if action_q == "BUY" else ("#fbac20" if action_q == "HOLD" else "#ff3747")
    action_class = "status-buy" if action_q == "BUY" else ("status-hold" if action_q == "HOLD" else "status-watch")

    st.markdown("### ⚡ Kiểm tra nhanh (nhìn vài giây)")
    q1, q2, q3, q4 = st.columns(4)
    with q1:
        st.markdown(
            f"""
            <div class="quick-card {action_class}">
              <div class="quick-title">Mã đang phân tích</div>
              <div class="quick-value">{ticker}</div>
              <div class="quick-pill" style="color:{action_color}; border-color:{action_color};">{action_q} · {conf_q:.0f}%</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with q2:
        st.markdown(
            f"""
            <div class="quick-card">
              <div class="quick-title">Giá hiện tại / Giá trị</div>
              <div class="quick-value">{price_q:,.0f}</div>
              <div class="quick-sub">Target: {intrinsic_q:,.0f} · MOS: {mos_q:.1f}%</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with q3:
        st.markdown(
            f"""
            <div class="quick-card">
              <div class="quick-title">Pha thị trường</div>
              <div class="quick-value">{phase_name_q}</div>
              <div class="quick-sub">Volume multiple: {vol_q:.2f}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with q4:
        st.markdown(
            """
            <div class="quick-card">
              <div class="quick-title">Hành động nhanh</div>
              <div class="quick-sub">1) Xem tab Định giá</div>
              <div class="quick-sub">2) Kiểm tra Risk Box</div>
              <div class="quick-sub">3) Bấm nút cảnh báo SL/TP</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    rel_score = float(report.get("data_reliability_score") or 0.0)
    rel_gate_ok = bool(report.get("data_reliability_gate_passed", True))
    if rel_gate_ok:
        st.caption(f"Data reliability score: {rel_score:.1f}/100 (gate pass).")
    else:
        st.warning(
            f"Data reliability score thấp ({rel_score:.1f}/100) -> hệ thống tự hạ khuyến nghị về WATCH để giảm rủi ro."
        )
    return valuation

