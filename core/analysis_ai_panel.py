from __future__ import annotations

from typing import Any, Callable

import pandas as pd
import streamlit as st


def render_risk_box(
    report: dict[str, Any],
    profile: str,
    *,
    profile_match_note: Callable[[str, dict[str, Any]], str],
) -> None:
    plan = report.get("risk_plan") or {}
    if not plan:
        st.info("Chưa có kế hoạch rủi ro.")
        return
    try:
        from core.decision_action_gate import trade_plan_is_active

        active = trade_plan_is_active(report)
    except Exception:
        active = str(report.get("final_action") or "").upper() in ("BUY", "HOLD")
    note = profile_match_note(profile, report)
    is_fit = "phù hợp" in note.lower()
    badge_html = (
        "<span class='badge-ok'>Phù hợp hoàn hảo</span>"
        if is_fit
        else "<span class='badge-warn'>Rủi ro cao - Không hợp gu</span>"
    )
    st.markdown("<div class='risk-box'>", unsafe_allow_html=True)
    st.markdown(f"**🛡️ Kế hoạch đi vốn** &nbsp; {badge_html}", unsafe_allow_html=True)
    if not active:
        st.markdown(
            f"- Hành động: **{report.get('final_action') or 'WATCH'}** · Verdict: **{report.get('analysis_verdict') or '—'}**\n"
            f"- {plan.get('display_note_vi') or 'Không đề xuất vào lệnh khi chưa đạt MUA/GIỮ.'}"
        )
        st.markdown("</div>", unsafe_allow_html=True)
        return
    st.markdown(
        f"- Mua vùng: **{plan.get('buy_zone_low')} - {plan.get('buy_zone_high')}**\n"
        f"- Cắt lỗ: **{plan.get('stop_loss_price')}**\n"
        f"- Chốt lời: **{plan.get('take_profit_price') or report.get('take_profit')}**\n"
        f"- Tỷ trọng vốn: **{plan.get('max_position_pct')}%** (~{float(plan.get('allocated_capital_vnd') or 0):,.0f} VND)\n"
        f"- Số lượng dự kiến: **{plan.get('estimated_quantity')} cp**"
    )
    risk_pct = float(plan.get("worst_case_loss_pct_total_capital") or 0)
    risk_norm = min(max(risk_pct / 5.0, 0.0), 1.0)
    st.progress(risk_norm, text=f"Mức rủi ro vị thế: {risk_pct:.2f}% tổng vốn")
    st.markdown("</div>", unsafe_allow_html=True)


def render_ai_chat_style(report: dict[str, Any]) -> None:
    st.caption(
        f"Model: {report.get('llm_provider')} | "
        f"LLM live: {report.get('llm_used')} | "
        f"Cache hit: {report.get('llm_cache_hit', False)} | "
        f"Escalated: {report.get('llm_escalated', False)} | "
        f"Escalation tried: {report.get('llm_escalation_attempted', False)}"
    )
    with st.chat_message("assistant"):
        st.markdown(report.get("analysis_text", "Chưa có kết luận."))
    for i, x in enumerate(report.get("whys_steps") or [], start=1):
        with st.chat_message("assistant"):
            st.markdown(f"**Why {i}:** {x}")


def render_ai_health_panel(*, get_provider_health_snapshot: Callable[[], list[dict[str, Any]]]) -> None:
    st.markdown("### 🩺 AI Health")
    rows = get_provider_health_snapshot()
    if not rows:
        st.caption("Chưa có dữ liệu health. Hãy chạy phân tích thêm vài lần.")
        return
    df = pd.DataFrame(rows)
    if "avg_ms" in df.columns:
        df["avg_ms"] = df["avg_ms"].map(lambda x: round(float(x), 1))
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption("Key được ẩn dạng ***xxxx. cooldown_sec > 0 nghĩa là key đang tạm nghỉ.")
