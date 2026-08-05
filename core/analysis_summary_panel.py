from __future__ import annotations

import streamlit as st


def render_analysis_main_metrics(report: dict) -> None:
    val = report.get("valuation", {})
    c1, c2, c3, c4, c5 = st.columns(5)
    price = float(val.get("price") or 0)
    intrinsic = float(val.get("composite_target_price") or val.get("intrinsic_value_graham") or 0)
    mos = val.get("margin_of_safety_composite_pct")
    action = str(report.get("final_action", "HOLD"))
    conf = float(report.get("confidence_score") or 0)
    with c1:
        st.metric("💰 Giá hiện tại", f"{price:,.0f} VND" if price > 0 else "N/A")
    with c2:
        st.metric("💎 Giá trị nội tại", f"{intrinsic:,.0f} VND" if intrinsic > 0 else "N/A")
    with c3:
        st.metric("🧷 Biên an toàn", f"{mos:.1f}%" if mos is not None else "N/A")
    with c4:
        st.metric("🧭 Khuyến nghị cuối", f"{action} ({conf:.0f}%)")
    rel_score = float(report.get("data_reliability_score") or 0.0)
    with c5:
        st.metric("🛡️ Data reliability", f"{rel_score:.1f}/100")
    gate_min = float(report.get("confidence_gate_min") or 65.0)
    if not bool(report.get("gate_passed", True)):
        st.error(
            f"🚧 Data Confidence Gate: {conf:.0f}% < {gate_min:.0f}%.\n"
            "Hệ thống chuyển trạng thái sang **WATCH** (chỉ quan sát), chưa khuyến nghị vào lệnh."
        )
    out_gate = report.get("output_quality") or {}
    if report.get("output_gate_passed") is False:
        reasons = ", ".join([str(x) for x in (out_gate.get("reasons") or [])]) or "unknown"
        st.warning(
            "🧪 Output Quality Gate: kế hoạch giá chưa đạt chuẩn thực chiến, "
            f"hệ thống hạ về **WATCH**. Lý do: `{reasons}`"
        )
    readiness = str(report.get("decision_readiness") or "LOW").upper()
    if readiness == "HIGH":
        st.success("🟢 Decision readiness HIGH: có thể cân nhắc hành động theo plan nếu vẫn đúng khẩu vị rủi ro.")
    elif readiness == "MEDIUM":
        st.warning("🟡 Decision readiness MEDIUM: có tín hiệu nhưng nên vào lệnh thận trọng, ưu tiên giải ngân từng phần.")
    else:
        st.error("🔴 Decision readiness LOW: ưu tiên WATCH, chưa nên mở vị thế mới.")
    st.caption(f"Decision readiness: {readiness} · Confidence {conf:.0f}% · Reliability {rel_score:.1f}/100.")
    align = report.get("decision_alignment") if isinstance(report.get("decision_alignment"), dict) else {}
    if align and str(align.get("alignment") or "") not in ("", "aligned"):
        st.info(
            f"🧭 Decision alignment (`{align.get('alignment')}`): "
            f"Legend **{align.get('legend_view') or '—'}** · Action **{align.get('action_view') or action}** "
            f"→ unified **{align.get('unified_action') or action}**. "
            f"{align.get('note_vi') or ''}"
        )
    latency_s = report.get("latency_seconds")
    if isinstance(latency_s, (float, int)) and latency_s > 0:
        st.caption(f"⏱️ Thời gian phản hồi phân tích: {float(latency_s):.2f}s")


def render_analysis_action_explanation(report: dict) -> None:
    val = report.get("valuation") or {}
    fin = report.get("financials") or {}
    phase = report.get("phase") or {}
    action_raw = str(report.get("final_action") or "WATCH").upper()
    action_label = "SELL" if action_raw == "AVOID" else action_raw
    conf = float(report.get("confidence_score") or 0)
    mos = float(val.get("margin_of_safety_composite_pct") or 0)
    fscore = int(val.get("piotroski_score") or 0)
    phase_name = str(phase.get("phase") or "neutral").upper()
    rev = fin.get("revenue_growth_yoy")
    de = fin.get("debt_to_equity")
    rev_txt = f"{float(rev):.1f}%" if isinstance(rev, (float, int)) else "N/A"
    de_txt = f"{float(de):.2f}" if isinstance(de, (float, int)) else "N/A"
    rel_score = float(report.get("data_reliability_score") or 0.0)
    rel_part = report.get("data_reliability_breakdown") or {}
    readiness = str(report.get("decision_readiness") or "LOW").upper()
    st.markdown("#### 🎯 Vì sao hệ thống đang khuyến nghị như vậy?")
    st.markdown(
        f"- Khuyến nghị hiện tại: **{action_label}** (độ tin cậy `{conf:.0f}%`)\n"
        f"- Mức sẵn sàng hành động: `{readiness}`\n"
        f"- Định giá: MOS `{mos:.1f}%` · F-Score `{fscore}/9`\n"
        f"- Kỹ thuật: pha thị trường `{phase_name}`\n"
        f"- Cơ bản doanh nghiệp: Rev YoY `{rev_txt}` · D/E `{de_txt}`\n"
        f"- Data reliability: `{rel_score:.1f}/100` "
        f"(Technical `{float(rel_part.get('technical_score') or 0):.0f}`, "
        f"Financial `{float(rel_part.get('financial_score') or 0):.0f}`, "
        f"News `{float(rel_part.get('news_score') or 0):.0f}`, "
        f"Backtest `{float(rel_part.get('backtest_score') or 0):.0f}`)"
    )
    align = report.get("decision_alignment") if isinstance(report.get("decision_alignment"), dict) else {}
    if align:
        st.caption(
            f"Decision alignment: `{align.get('alignment')}` · "
            f"Legend `{align.get('legend_view') or '—'}` vs Action `{align.get('action_view') or action_raw}` "
            f"→ `{align.get('unified_action') or action_raw}`. {align.get('note_vi') or ''}"
        )
    if report.get("gate_passed") is False:
        st.warning("Confidence Gate chưa đạt, nên hệ thống ưu tiên WATCH để tránh vào lệnh sớm.")
    if report.get("output_gate_passed") is False:
        st.warning("Output Quality Gate chưa đạt (plan giá chưa thực chiến), nên hệ thống tự hạ về WATCH.")
