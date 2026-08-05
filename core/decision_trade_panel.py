from __future__ import annotations

from typing import Any, Callable

import streamlit as st


def render_decision_trade_panel(
    *,
    user_id: str,
    ticker: str,
    cache_rep: dict[str, Any],
    add_decision: Callable[..., tuple[bool, str]],
    log_event: Callable[..., None],
    coach_decision_quality_adaptive: Callable[..., dict[str, Any]],
    adaptive_position_sizing: Callable[..., dict[str, Any]],
    list_decisions: Callable[..., list[dict[str, Any]]],
    open_trade: Callable[..., tuple[bool, str]],
    close_trade: Callable[..., tuple[bool, str]],
) -> None:
    st.markdown("#### 📝 Nhật ký quyết định đầu tư")
    d_symbol = st.text_input("Mã quyết định", value=ticker)
    d_side = st.selectbox("Loại quyết định", options=["BUY", "WATCH"])
    d_entry = st.number_input("Entry quyết định", min_value=0.0, value=0.0, step=100.0)
    d_sl = st.number_input("Stop-loss quyết định", min_value=0.0, value=0.0, step=100.0)
    d_tp = st.number_input("Take-profit quyết định", min_value=0.0, value=0.0, step=100.0)
    d_hz = int(st.slider("Khung hậu kiểm (ngày)", min_value=7, max_value=180, value=30, step=1))
    d_thesis = st.text_area("Luận điểm đầu tư", value="", height=80)
    cache_readiness = str(cache_rep.get("decision_readiness") or "LOW").upper()
    coach = coach_decision_quality_adaptive(
        user_id,
        side=d_side,
        entry_price=float(d_entry),
        stop_loss=float(d_sl),
        take_profit=float(d_tp),
        gate_passed=bool(cache_rep.get("gate_passed")),
        confidence_score=float(cache_rep.get("confidence_score") or 0),
    )
    st.caption(
        f"Coach score: {coach['coach_score']}/100 | RR: {coach['rr']} | Verdict: {coach['verdict']} "
        f"| Adaptive: {coach.get('adaptive_profile')}"
    )
    th = coach.get("adaptive_thresholds") or {}
    st.caption(
        f"Ngưỡng cá nhân hóa -> RR tối thiểu: {float(th.get('rr_min') or 0):.2f}, "
        f"GO >= {float(th.get('go_min_score') or 0):.0f}, "
        f"CAUTION >= {float(th.get('caution_min_score') or 0):.0f}"
    )
    phase_metrics = (cache_rep.get("phase") or {}).get("metrics") or {}
    vol_mult = float(phase_metrics.get("vol_multiple") or 1.0)
    base_pos = float((cache_rep.get("risk_plan") or {}).get("max_position_pct") or 20.0)
    sizing = adaptive_position_sizing(
        user_id,
        base_max_position_pct=base_pos,
        confidence_score=float(cache_rep.get("confidence_score") or 0),
        gate_passed=bool(cache_rep.get("gate_passed")),
        vol_multiple=vol_mult,
        coach_verdict=str(coach.get("verdict") or "CAUTION"),
    )
    st.caption(
        f"Tỷ trọng gợi ý (adaptive): {sizing['suggested_position_pct']}% | "
        f"Bucket: {sizing['risk_bucket']} | Discipline: {sizing['discipline_score']}"
    )
    st.caption(sizing["reason"])
    if coach["strengths"]:
        st.caption("✅ " + " | ".join(coach["strengths"]))
    if coach["warnings"]:
        st.warning(" | ".join(coach["warnings"]))
    manual_buy_blocked = d_side == "BUY" and cache_readiness == "LOW"
    if manual_buy_blocked:
        st.error("Decision readiness đang LOW: tạm khóa lưu quyết định BUY. Hãy chờ tín hiệu mạnh hơn hoặc chọn WATCH.")
    if st.button("💾 Lưu quyết định", width="stretch", disabled=manual_buy_blocked):
        if coach["verdict"] == "NO-GO":
            st.error("Coach Mode: NO-GO. Vui lòng chỉnh kế hoạch trước khi lưu.")
            st.stop()
        ok_dec, msg_dec = add_decision(
            user_id,
            d_symbol,
            d_side,
            float(d_entry),
            float(d_sl),
            float(d_tp),
            d_thesis,
            d_hz,
        )
        if ok_dec:
            log_event(
                user_id,
                "decision_added",
                {
                    "symbol": d_symbol.upper(),
                    "side": d_side,
                    "coach_score": coach["coach_score"],
                    "verdict": coach["verdict"],
                },
            )
            st.success(msg_dec)
        else:
            st.error(msg_dec)

    st.markdown("#### 📒 Trade Journal (Realized PnL)")
    tj1, tj2 = st.columns(2)
    with tj1:
        t_symbol = st.text_input("Mã mở lệnh", value=ticker)
        d_opts = list_decisions(user_id, limit=100)
        d_map = {f"{x['id']} | {x['symbol']} | {x['side']}": int(x["id"]) for x in d_opts}
        selected_d = st.selectbox("Link tới Decision (tuỳ chọn)", options=["(không link)"] + list(d_map.keys()))
        t_qty = st.number_input("Số lượng mở", min_value=0.0, value=0.0, step=100.0)
        t_entry = st.number_input("Giá mở thực tế", min_value=0.0, value=0.0, step=100.0)
        t_entry_fee = st.number_input("Phí mở", min_value=0.0, value=0.0, step=1000.0)
        t_entry_note = st.text_input("Ghi chú mở", value="")
        if st.button("🟢 Mở trade", width="stretch"):
            linked_decision_id = d_map.get(selected_d) if selected_d != "(không link)" else None
            ok_tr, msg_tr = open_trade(
                user_id,
                t_symbol,
                float(t_qty),
                float(t_entry),
                decision_id=linked_decision_id,
                entry_fee=float(t_entry_fee),
                entry_note=t_entry_note,
            )
            if ok_tr:
                log_event(user_id, "trade_opened", {"symbol": t_symbol.upper(), "qty": t_qty})
                st.success(msg_tr)
            else:
                st.error(msg_tr)
    with tj2:
        close_id = int(st.number_input("ID trade đóng", min_value=0.0, value=0.0, step=1.0))
        close_price = st.number_input("Giá đóng thực tế", min_value=0.0, value=0.0, step=100.0)
        close_fee = st.number_input("Phí đóng", min_value=0.0, value=0.0, step=1000.0)
        close_note = st.text_input("Ghi chú đóng", value="")
        if st.button("🔴 Đóng trade", width="stretch"):
            ok_cl, msg_cl = close_trade(
                user_id,
                close_id,
                float(close_price),
                exit_fee=float(close_fee),
                exit_note=close_note,
            )
            if ok_cl:
                log_event(user_id, "trade_closed", {"trade_id": close_id})
                st.success(msg_cl)
            else:
                st.error(msg_cl)
