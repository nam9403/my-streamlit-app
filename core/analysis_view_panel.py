from __future__ import annotations

import json
from typing import Any, Callable

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


def _smart_money_reliability_label(sm: dict[str, Any]) -> tuple[str, str]:
    avg_conf = float(sm.get("avg_event_confidence") or 0.0)
    structured_n = int(sm.get("structured_event_count") or 0)
    if structured_n >= 5 and avg_conf >= 0.75:
        return "HIGH", "🟢"
    if structured_n >= 2 and avg_conf >= 0.55:
        return "MEDIUM", "🟡"
    return "LOW", "🔴"


def render_5s_panel(report: dict[str, Any], sla_rows: list[dict[str, Any]]) -> None:
    conf = float(report.get("confidence_score") or 0)
    latency = float(report.get("latency_seconds") or 0)
    gate = bool(report.get("gate_passed"))
    avg_sla = 0.0
    if sla_rows:
        avg_sla = sum(float(x.get("success_rate_pct") or 0) for x in sla_rows) / len(sla_rows)
    score_sort = 80 if gate else 60
    score_setinorder = 85 if latency <= 2.5 else (70 if latency <= 6 else 55)
    score_shine = 82 if conf >= 65 else 65
    score_standardize = 88 if avg_sla >= 70 else 72
    score_sustain = 86 if report.get("data_reliability") else 68
    rows = [
        {"5S": "Seiri (Sàng lọc)", "Điểm": score_sort, "Ý nghĩa": "Ưu tiên cơ hội hành động rõ ràng, loại nhiễu."},
        {"5S": "Seiton (Sắp xếp)", "Điểm": score_setinorder, "Ý nghĩa": "Luồng thao tác nhanh, ít bước chờ."},
        {"5S": "Seiso (Sạch sẽ)", "Điểm": score_shine, "Ý nghĩa": "Dashboard gọn, thông tin dễ đọc."},
        {"5S": "Seiketsu (Chuẩn hóa)", "Điểm": score_standardize, "Ý nghĩa": "SLA dữ liệu và gate thống nhất."},
        {"5S": "Shitsuke (Duy trì)", "Điểm": score_sustain, "Ý nghĩa": "KPI + cohort duy trì cải tiến liên tục."},
    ]
    st.subheader("🧭 5S Product Health")
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def render_health_cards(
    report: dict[str, Any],
    *,
    health_badge: Callable[[int], tuple[str, str]],
) -> None:
    valuation = report.get("valuation", {})
    phase = report.get("phase", {})
    fin = report.get("financials", {})
    fscore = int(valuation.get("piotroski_score") or 0)
    mos = valuation.get("margin_of_safety_composite_pct")
    status, color = health_badge(fscore)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(
            f"<div style='padding:10px;border-radius:10px;border:1px solid {color};'><b>Sức khỏe</b><br>{status}</div>",
            unsafe_allow_html=True,
        )
    with c2:
        st.metric("Pha thị trường", str(phase.get("phase", "neutral")).upper())
    with c3:
        st.metric("MOS tổng hợp", f"{mos:.1f}%" if mos is not None else "N/A")
    with c4:
        de = fin.get("debt_to_equity")
        st.metric("Nợ/VCSH", f"{de:.2f}" if isinstance(de, (float, int)) else "N/A")
    st.caption(
        "Legend sức khỏe: 🟢 F-Score >= 7 (mạnh), 🟡 4–6 (trung tính), 🔴 < 4 (yếu). "
        "Pha thị trường lấy từ Trend & Flow (accumulation/breakout/distribution/neutral)."
    )


def render_readiness_checklist(report: dict[str, Any], ohlcv: pd.DataFrame) -> None:
    fin = report.get("financials", {})
    news = report.get("news", [])
    phase = report.get("phase", {})

    ohlcv_ok = not ohlcv.empty and len(ohlcv) >= 50
    ohlcv_src = str(ohlcv.attrs.get("source", "")) if ohlcv_ok else ""
    checks = [
        ("OHLCV 50+ phiên", ohlcv_ok),
        ("Financial ratios", any(fin.get(k) is not None for k in ("debt_to_equity", "gross_margin"))),
        ("Tin tức", len(news) > 0),
        ("Pha thị trường", bool(phase.get("phase")) and phase.get("phase") != "neutral"),
        ("LLM live", bool(report.get("llm_used"))),
    ]
    labels = [f"{'✅' if ok else '⚠️'} {name}" for name, ok in checks]
    st.caption("Readiness: " + " · ".join(labels))
    if ohlcv_src:
        st.caption(f"Nguồn OHLCV hiện tại: `{ohlcv_src}`")
    rel = report.get("data_reliability") or {}
    if rel:
        fin_rel = rel.get("financial") or {}
        bt_rel = rel.get("backtest") or {}
        st.caption(
            "Reliability nguồn dữ liệu: "
            f"Kỹ thuật={'✅' if (rel.get('technical') or {}).get('ok') else '⚠️'} | "
            f"Tài chính={'✅' if fin_rel.get('ok') else '⚠️'} "
            f"(source={fin_rel.get('source', 'unknown')}, quality={fin_rel.get('quality_score', 0)}) | "
            f"Tin tức={'✅' if (rel.get('news') or {}).get('ok') else '⚠️'} | "
            f"Backtest={'✅' if bt_rel.get('ok') else '⚠️'} "
            f"(N={bt_rel.get('samples', 0)}, BUY={bt_rel.get('buy_signals', 0)})."
        )
    val = report.get("valuation") or {}
    src_valuation = str(val.get("data_source") or "unknown")
    src_fin = str(((report.get("data_reliability") or {}).get("financial") or {}).get("source") or "unknown")
    src_ohlcv = str(ohlcv.attrs.get("source") or "unknown") if ohlcv_ok else "unknown"
    ohlcv_trust = ohlcv.attrs.get("data_trust") if ohlcv_ok else {}
    if not isinstance(ohlcv_trust, dict):
        ohlcv_trust = {}
    fin_trust = (report.get("financials") or {}).get("data_trust") or {}
    if not isinstance(fin_trust, dict):
        fin_trust = {}

    ohlcv_age = ""
    age_sec = ohlcv_trust.get("age_sec")
    if isinstance(age_sec, (float, int)):
        ohlcv_age = f" (~{float(age_sec)/60.0:.0f} phút tuổi)"
    ohlcv_stale = bool(ohlcv_trust.get("is_stale"))
    fin_stale = bool(fin_trust.get("is_stale"))
    ohlcv_chain = ohlcv_trust.get("fallback_chain") if isinstance(ohlcv_trust.get("fallback_chain"), list) else []
    fin_chain = fin_trust.get("fallback_chain") if isinstance(fin_trust.get("fallback_chain"), list) else []

    st.caption(
        f"Nguồn đang dùng: Định giá=`{src_valuation}` · OHLCV=`{src_ohlcv}`{ohlcv_age} "
        f"({'stale' if ohlcv_stale else 'fresh'}) · Financial=`{src_fin}` "
        f"({'stale' if fin_stale else 'fresh'})"
    )
    if ohlcv_chain:
        st.caption("OHLCV fallback chain: " + " -> ".join(str(x) for x in ohlcv_chain))
    if fin_chain:
        st.caption("Financial fallback chain: " + " -> ".join(str(x) for x in fin_chain))

    try:
        from core.data_trust_score import compute_data_trust_score

        dts = compute_data_trust_score(
            snapshot={
                "price": val.get("price"),
                "eps": val.get("eps") or val.get("eps_for_graham"),
                "eps_normalized": val.get("eps_normalized") or report.get("eps_normalized"),
                "pe_sanity_notes": val.get("pe_sanity_notes"),
                "price_crosscheck_note_vi": report.get("price_crosscheck_note_vi"),
                "decision_completeness": val.get("decision_completeness") or report.get("decision_completeness"),
                "rsi_anomaly": (phase.get("metrics") or {}).get("rsi_anomaly"),
            },
            financials=fin if isinstance(fin, dict) else {},
            valuation=val if isinstance(val, dict) else {},
            ohlcv_trust=ohlcv_trust if isinstance(ohlcv_trust, dict) else None,
            fin_trust=fin_trust if isinstance(fin_trust, dict) else None,
        )
        report["data_trust_score"] = report.get("data_trust_score") or dts
        dts = report["data_trust_score"]
        band = str(dts.get("band") or "LOW")
        tone = "🟢" if band == "HIGH" else ("🟡" if band == "MEDIUM" else "🔴")
        st.caption(
            f"{tone} Data trust score: **{dts.get('score')}** ({dts.get('label_vi')})"
        )
        notes = dts.get("notes_vi") or []
        if notes:
            st.caption("Trust notes: " + " · ".join(str(n) for n in notes[:4]))
    except Exception:
        pass


def render_evidence(report: dict[str, Any]) -> None:
    st.subheader("Bảng số liệu BCTC")
    fin = report.get("financials", {})
    rows = [
        {"Chỉ tiêu": "Nợ/Vốn chủ sở hữu", "Giá trị": fin.get("debt_to_equity")},
        {"Chỉ tiêu": "Biên lợi nhuận gộp", "Giá trị": fin.get("gross_margin")},
        {"Chỉ tiêu": "Tăng trưởng doanh thu YoY", "Giá trị": fin.get("revenue_growth_yoy")},
        {"Chỉ tiêu": "Tăng trưởng doanh thu QoQ", "Giá trị": fin.get("revenue_growth_qoq")},
        {"Chỉ tiêu": "Tăng trưởng lợi nhuận YoY", "Giá trị": fin.get("profit_growth_yoy")},
        {"Chỉ tiêu": "Tăng trưởng lợi nhuận QoQ", "Giá trị": fin.get("profit_growth_qoq")},
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    st.subheader("Tin tức mới nhất")
    for item in report.get("news", []):
        st.markdown(f"- [{item.get('title')}]({item.get('url')}) ({item.get('source')})")
    deep = report.get("deep_insight") or {}
    if deep:
        st.subheader("🧠 Deep Insight")
        eq = deep.get("earnings_quality") or {}
        sm = deep.get("smart_money_flow") or {}
        eq_rows = [
            {"Mục": "Nhãn chất lượng lợi nhuận", "Giá trị": eq.get("label")},
            {"Mục": "Mức độ", "Giá trị": eq.get("severity")},
            {"Mục": "Net Income", "Giá trị": eq.get("net_income")},
            {"Mục": "Operating CFO", "Giá trị": eq.get("operating_cash_flow")},
            {"Mục": "Tăng trưởng LNST YoY %", "Giá trị": eq.get("net_income_growth_yoy_pct")},
            {"Mục": "Tăng trưởng CFO YoY %", "Giá trị": eq.get("operating_cash_flow_growth_yoy_pct")},
        ]
        st.dataframe(pd.DataFrame(eq_rows), width="stretch", hide_index=True)
        notes = eq.get("notes") or []
        if notes:
            st.caption("Earnings quality notes: " + " | ".join(str(x) for x in notes))
        sm_rows = [
            {"Mục": "Smart money bias", "Giá trị": sm.get("bias")},
            {"Mục": "Điểm bias", "Giá trị": sm.get("score")},
            {"Mục": "Nhãn", "Giá trị": sm.get("label")},
            {"Mục": "Data mode", "Giá trị": sm.get("data_mode")},
            {"Mục": "Structured events", "Giá trị": sm.get("structured_event_count")},
            {"Mục": "High-confidence events", "Giá trị": sm.get("high_conf_event_count")},
            {"Mục": "Avg event confidence", "Giá trị": sm.get("avg_event_confidence")},
        ]
        st.dataframe(pd.DataFrame(sm_rows), width="stretch", hide_index=True)
        sig = sm.get("signals") or []
        if sig:
            st.caption("Smart money signals: " + " | ".join(str(x) for x in sig))
        rel_label, rel_icon = _smart_money_reliability_label(sm if isinstance(sm, dict) else {})
        st.caption(f"Smart-money reliability: {rel_icon} {rel_label}")
        top_actors = sm.get("top_actors") or []
        if top_actors:
            st.caption("Top actors: " + " | ".join(str(x) for x in top_actors))
        src_cov = sm.get("source_coverage") or []
        if src_cov:
            st.caption("Smart money sources: " + " | ".join(str(x) for x in src_cov))


def render_report_downloads(
    report: dict[str, Any],
    *,
    investment_report_markdown: Callable[[dict[str, Any]], str],
    investment_report_html: Callable[[dict[str, Any]], str],
) -> None:
    summary = report.get("valuation", {})
    ticker = summary.get("symbol", "stock")
    md = investment_report_markdown(summary)
    html_doc = investment_report_html(summary)
    json_doc = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button("Tải báo cáo Markdown", data=md.encode("utf-8"), file_name=f"{ticker}_bao_cao.md", mime="text/markdown", width="stretch")
    with c2:
        st.download_button(
            "Tải báo cáo HTML (in ra PDF)",
            data=html_doc.encode("utf-8"),
            file_name=f"{ticker}_bao_cao.html",
            mime="text/html",
            width="stretch",
        )
    with c3:
        st.download_button(
            "Tải báo cáo JSON",
            data=json_doc.encode("utf-8"),
            file_name=f"{ticker}_strategic_report.json",
            mime="application/json",
            width="stretch",
        )


def render_risk_plan(report: dict[str, Any]) -> None:
    st.subheader("🛡️ Kế hoạch tác chiến an toàn")
    plan = report.get("risk_plan") or {}
    if not plan:
        st.info("Chưa có risk plan.")
        return
    try:
        from core.decision_action_gate import trade_plan_is_active

        active = trade_plan_is_active(report)
    except Exception:
        active = str(report.get("final_action") or "").upper() in ("BUY", "HOLD")
    if not active:
        note = str(plan.get("display_note_vi") or "").strip()
        st.info(
            note
            or "Khuyến nghị hiện tại không phải MUA/GIỮ — hệ thống không đề xuất vào lệnh "
            "(Entry/SL/TP ẩn để tránh hiểu nhầm)."
        )
        st.caption(f"Hành động: **{report.get('final_action') or 'WATCH'}** · Verdict: **{report.get('analysis_verdict') or '—'}**")
        return
    table = pd.DataFrame(
        [
            {
                "Mua giá nào?": plan.get("entry_price"),
                "Bán giá nào?": plan.get("take_profit_price") or report.get("take_profit"),
                "Cắt lỗ giá nào?": plan.get("stop_loss_price"),
            }
        ]
    )
    st.dataframe(table, width="stretch", hide_index=True)

    alloc = float(plan.get("allocated_capital_vnd") or 0)
    total = float(report.get("total_capital_vnd") or 0)
    cash = max(total - alloc, 0.0)
    fig = go.Figure(data=[go.Pie(labels=["Mã đang phân tích", "Phần vốn còn lại"], values=[alloc, cash], hole=0.45)])
    fig.update_layout(height=320, margin={"l": 10, "r": 10, "t": 30, "b": 10})
    st.plotly_chart(fig, width="stretch")
    st.caption(
        f"Giải ngân tối đa: {plan.get('max_position_pct')}% ~ {alloc:,.0f} VND | "
        f"SL xấu nhất: {plan.get('worst_case_loss_vnd', 0):,.0f} VND "
        f"({plan.get('worst_case_loss_pct_total_capital', 0)}% tổng vốn)."
    )

    protector = report.get("portfolio_protector") or {}
    if protector:
        st.markdown("#### 🧯 Portfolio Protector (Mean-Variance + Stress Test)")
        w = protector.get("optimized_weights") or {}
        w_df = pd.DataFrame(
            [
                {"Rổ tài sản": "Mã phân tích", "Tỷ trọng %": round(float(w.get("stock") or 0.0) * 100.0, 2)},
                {"Rổ tài sản": "Benchmark (VN-Index proxy)", "Tỷ trọng %": round(float(w.get("benchmark") or 0.0) * 100.0, 2)},
                {"Rổ tài sản": "Cash", "Tỷ trọng %": round(float(w.get("cash") or 0.0) * 100.0, 2)},
            ]
        )
        st.dataframe(w_df, width="stretch", hide_index=True)
        c1, c2, c3 = st.columns(3)
        with c1:
            sr = protector.get("sharpe_ratio")
            st.metric("Sharpe (ước tính)", f"{float(sr):.2f}" if isinstance(sr, (float, int)) else "N/A")
        with c2:
            er = protector.get("expected_return_annual_pct")
            st.metric("LN kỳ vọng năm", f"{float(er):.2f}%" if isinstance(er, (float, int)) else "N/A")
        with c3:
            vol = protector.get("volatility_annual_pct")
            st.metric("Biến động năm", f"{float(vol):.2f}%" if isinstance(vol, (float, int)) else "N/A")
        stress = protector.get("stress_test") or []
        if stress:
            st.dataframe(pd.DataFrame(stress), width="stretch", hide_index=True)
        note = str(protector.get("optimizer_note") or "")
        if note:
            st.caption(note)
