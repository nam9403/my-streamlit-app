from __future__ import annotations

from typing import Any, Callable

import pandas as pd
import streamlit as st

from core.analysis_runtime_service import load_snapshot_cached, load_strategic_report_cached


def build_portfolio_options(candidates: pd.DataFrame, total_capital_vnd: float) -> dict[str, pd.DataFrame]:
    if not candidates.empty and "Trạng thái" in candidates.columns:
        candidates = candidates[candidates["Trạng thái"] == "Sẵn sàng"]
    if candidates.empty:
        empty = pd.DataFrame(
            columns=[
                "Mã",
                "Khuyến nghị",
                "Khung thời gian",
                "Tỷ trọng %",
                "Vốn (VND)",
                "Lợi nhuận kỳ vọng (VND)",
                "Rủi ro ước tính (VND)",
            ]
        )
        return {"an_toan": empty, "can_bang": empty, "mao_hiem": empty}

    def _build(top_n: int, max_weight: float, tilt_return: float) -> pd.DataFrame:
        d = candidates.head(top_n).copy()
        if d.empty:
            return pd.DataFrame(
                columns=[
                    "Mã",
                    "Khuyến nghị",
                    "Khung thời gian",
                    "Tỷ trọng %",
                    "Vốn (VND)",
                    "Lợi nhuận kỳ vọng (VND)",
                    "Rủi ro ước tính (VND)",
                ]
            )
        score = d["Expected Return %"] * tilt_return + (35 - d["Risk % (ước tính)"]) * (1 - tilt_return)
        score = score.clip(lower=0.1)
        w = score / score.sum()
        w = w.clip(upper=max_weight)
        w = w / w.sum()
        alloc = total_capital_vnd * w
        pnl = alloc * d["Expected Return %"] / 100.0
        risk_vnd = alloc * d["Risk % (ước tính)"] / 100.0
        out = pd.DataFrame(
            {
                "Mã": d["Mã"].values,
                "Khuyến nghị": d["Khuyến nghị"].values,
                "Khung thời gian": d["Khung thời gian"].values,
                "Tỷ trọng %": (w * 100).round(2).values,
                "Vốn (VND)": alloc.round(0).values,
                "Lợi nhuận kỳ vọng (VND)": pnl.round(0).values,
                "Rủi ro ước tính (VND)": risk_vnd.round(0).values,
            }
        )
        return out

    return {
        "an_toan": _build(top_n=3, max_weight=0.4, tilt_return=0.35),
        "can_bang": _build(top_n=4, max_weight=0.35, tilt_return=0.5),
        "mao_hiem": _build(top_n=5, max_weight=0.3, tilt_return=0.7),
    }


def build_final_opportunity_table(candidates: pd.DataFrame, discount_threshold_pct: float = 20.0) -> pd.DataFrame:
    """Create concise final recommendations from scanned candidates."""
    if candidates.empty:
        return pd.DataFrame(
            columns=["Mã", "Tiểu ngành", "Giá hiện tại", "Giá mục tiêu tích sản", "Chiết khấu", "Thông điệp cuối cùng"]
        )
    d = candidates.copy()
    d = d[d["MOS%"] >= discount_threshold_pct].copy()
    if d.empty:
        return pd.DataFrame(
            columns=["Mã", "Tiểu ngành", "Giá hiện tại", "Giá mục tiêu tích sản", "Chiết khấu", "Thông điệp cuối cùng"]
        )
    out_rows: list[dict] = []
    for _, r in d.head(8).iterrows():
        price = float(r.get("Giá", 0) or 0)
        target_buy = price * (1.0 - discount_threshold_pct / 100.0) if price > 0 else 0
        out_rows.append(
            {
                "Mã": r.get("Mã"),
                "Tiểu ngành": r.get("Tiểu ngành", "Khác"),
                "Giá hiện tại": round(price, 2),
                "Giá mục tiêu tích sản": round(target_buy, 2),
                "Chiết khấu": f">= {discount_threshold_pct:.0f}%",
                "Thông điệp cuối cùng": "Giá đang tốt, có thể mua tích sản dần.",
            }
        )
    return pd.DataFrame(out_rows)


@st.cache_data(ttl=300)
def build_action_center(
    universe: tuple[str, ...],
    profile: str,
    total_capital_vnd: float,
    top_n: int = 8,
) -> pd.DataFrame:
    """Build actionable board with strict ranking."""
    rows: list[dict] = []
    for sym in universe:
        snap = load_snapshot_cached(sym)
        if snap is None:
            continue
        try:
            rep = load_strategic_report_cached(sym, snap, profile, total_capital_vnd, quick_mode=True)
        except Exception:
            continue
        val = rep.get("valuation") or {}
        plan = rep.get("risk_plan") or {}
        conf = float(rep.get("confidence_score") or 0)
        mos = float(val.get("margin_of_safety_composite_pct") or 0)
        act = str(rep.get("final_action") or "WATCH")
        gate = bool(rep.get("gate_passed"))
        entry = float(plan.get("entry_price") or 0)
        sl = float(plan.get("stop_loss_price") or 0)
        tp = float(plan.get("take_profit_price") or 0)
        rr = ((tp - entry) / max(entry - sl, 1e-6)) if entry > 0 and tp > entry and sl < entry else 0.0
        score = (25 if gate else -30) + conf * 0.7 + mos * 0.5 + rr * 8.0
        if act == "BUY":
            score += 20
        elif act == "HOLD":
            score += 8
        elif act == "WATCH":
            score -= 5
        else:
            score -= 12
        rows.append(
            {
                "Mã": sym,
                "Khuyến nghị": act,
                "Gate": "PASS" if gate else "WATCH-ONLY",
                "Confidence %": round(conf, 1),
                "MOS %": round(mos, 1),
                "RR": round(rr, 2),
                "Entry": round(entry, 2) if entry > 0 else None,
                "SL": round(sl, 2) if sl > 0 else None,
                "TP": round(tp, 2) if tp > 0 else None,
                "Điểm hành động": round(score, 2),
                "Tiểu ngành": str(val.get("industry_subtype_label_vi") or "Khác"),
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=["Mã", "Khuyến nghị", "Gate", "Confidence %", "MOS %", "RR", "Entry", "SL", "TP", "Điểm hành động"]
        )
    out = pd.DataFrame(rows).sort_values("Điểm hành động", ascending=False).head(max(1, top_n)).reset_index(drop=True)
    return out


def build_daily_playbook_text(action_df: pd.DataFrame, ticker: str, report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("📘 Daily Playbook")
    lines.append(f"- Mã đang theo dõi chính: {ticker}")
    act = str(report.get("final_action") or "WATCH")
    conf = float(report.get("confidence_score") or 0)
    lines.append(f"- Trạng thái hiện tại: {act} | Confidence: {conf:.1f}%")
    if action_df.empty:
        lines.append("- Chưa có cơ hội nổi bật hôm nay theo tiêu chí hiện tại.")
        return "\n".join(lines)
    lines.append("- Top cơ hội ưu tiên:")
    for _, r in action_df.head(3).iterrows():
        lines.append(
            f"  • {r.get('Mã')} | {r.get('Khuyến nghị')} | Gate {r.get('Gate')} | "
            f"MOS {r.get('MOS %')}% | RR {r.get('RR')}"
        )
    return "\n".join(lines)


def render_action_center_expander(
    user_id: str,
    watchlist: list[str],
    watchlist_default: list[str],
    profile: str,
    total_capital_vnd: float,
    *,
    build_action_center: Callable[..., pd.DataFrame],
    log_event: Callable[..., Any],
) -> None:
    with st.expander("🎯 Action Center (danh sách cơ hội)", expanded=False):
        action_universe = tuple((watchlist or watchlist_default)[: min(12, len(watchlist or watchlist_default))])
        action_df = build_action_center(action_universe, profile, float(total_capital_vnd), top_n=6)
        if action_df.empty:
            st.caption("Chưa đủ dữ liệu để dựng Action Center.")
        else:
            st.dataframe(action_df, use_container_width=True, hide_index=True)
            log_event(user_id, "action_center_viewed", {"rows": int(len(action_df))})


def render_scan_results_expander(
    session_state: dict[str, Any],
    profile: str,
    total_capital_vnd: float,
    effective_quick_mode: bool,
    llm_live: bool,
    *,
    build_final_opportunity_table: Callable[..., pd.DataFrame],
    load_snapshot_cached: Callable[..., Any],
    load_strategic_report_cached: Callable[..., dict[str, Any]],
) -> None:
    if "scan_candidates" not in session_state:
        return
    with st.expander("✅ Kết quả quét mở rộng", expanded=False):
        final_df = build_final_opportunity_table(session_state["scan_candidates"], discount_threshold_pct=20.0)
        if final_df.empty:
            st.info("Chưa có mã nào đạt tiêu chí định giá rẻ >=20% trong lần quét gần nhất.")
            return
        st.dataframe(final_df, use_container_width=True, hide_index=True)
        st.markdown("---")
        st.markdown("**Mở rộng dẫn chứng từng mã**")
        with st.container():
            for _, row in final_df.iterrows():
                sym = str(row["Mã"])
                st.markdown(f"**{sym}** · {row['Thông điệp cuối cùng']}")
                snap_sym = load_snapshot_cached(sym)
                if snap_sym is None:
                    st.caption("Không lấy được snapshot.")
                    continue
                rep_sym = load_strategic_report_cached(
                    sym,
                    snap_sym,
                    profile,
                    total_capital_vnd,
                    quick_mode=effective_quick_mode,
                    llm_live=llm_live,
                )
                st.caption(
                    f"MOS: {float(rep_sym.get('valuation', {}).get('margin_of_safety_composite_pct') or 0):.1f}% | "
                    f"Pha: {rep_sym.get('phase', {}).get('phase', 'neutral')} | "
                    f"F-Score: {rep_sym.get('valuation', {}).get('piotroski_score', 0)}/9"
                )


def render_scan_candidates_overview(
    session_state: dict[str, Any],
    total_capital_vnd: float,
    *,
    build_portfolio_options: Callable[..., dict[str, pd.DataFrame]],
) -> None:
    if "scan_candidates" not in session_state:
        return
    st.markdown("---")
    st.subheader("🔎 Danh sách cổ phiếu tiềm năng tự động")
    candidates = session_state["scan_candidates"]
    if session_state.get("scan_relaxed_used"):
        st.info(
            f"Không có mã đạt ngưỡng Avg Vol20 >= {int(session_state.get('scan_filter_min_vol', 0)):,}. "
            "Hệ thống đã tự quét lại với bộ lọc nới lỏng để vẫn trả ra cơ hội đầu tư."
        )
    if candidates.empty:
        st.warning("Không tìm thấy mã phù hợp bộ lọc hiện tại.")
        return
    st.caption("Các mã có trạng thái `Sẵn sàng` được ưu tiên hiển thị trước.")
    st.dataframe(candidates.head(20), use_container_width=True, hide_index=True)
    plans = session_state.get("scan_portfolios") or build_portfolio_options(candidates, total_capital_vnd)
    st.markdown("### 📦 Gợi ý phân bổ danh mục theo mức rủi ro")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.caption("An toàn")
        st.dataframe(plans["an_toan"], use_container_width=True, hide_index=True)
    with c2:
        st.caption("Cân bằng")
        st.dataframe(plans["can_bang"], use_container_width=True, hide_index=True)
    with c3:
        st.caption("Mạo hiểm")
        st.dataframe(plans["mao_hiem"], use_container_width=True, hide_index=True)
