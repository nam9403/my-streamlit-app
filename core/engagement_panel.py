from __future__ import annotations

from typing import Any, Callable

import streamlit as st


def render_aha_and_value(
    user_id: str,
    *,
    user_aha_progress: Callable[[str], dict[str, Any]],
    customer_value_snapshot: Callable[[str], dict[str, Any]],
    next_best_action: Callable[[str], dict[str, Any]],
    today_action_board: Callable[[str], list[dict[str, Any]]],
    proof_of_value_report: Callable[[str], dict[str, Any]],
    value_maturity_score: Callable[[str], dict[str, Any]],
    overdue_action_reminders: Callable[[str], list[dict[str, Any]]],
) -> None:
    aha = user_aha_progress(user_id)
    val = customer_value_snapshot(user_id)
    nba = next_best_action(user_id)
    st.subheader("🚀 Aha Journey (7 ngày)")
    st.progress(min(max(float(aha.get("progress_pct") or 0) / 100.0, 0.0), 1.0), text=f"Tiến độ: {aha.get('progress_pct', 0)}%")
    st.caption(f"Bước tiếp theo gợi ý: {aha.get('next_step')}")
    steps = aha.get("steps") or []
    if steps:
        st.caption(" · ".join([f"{'✅' if s.get('done') else '⬜'} {s.get('label')}" for s in steps]))

    st.subheader("💡 Value Snapshot (30 ngày)")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Realized PnL", f"{float(val.get('realized_pnl_30d') or 0):,.0f} VND")
    with c2:
        st.metric("Win rate realized", f"{float(val.get('realized_win_rate_30d') or 0):.1f}%")
    with c3:
        st.metric("Discipline score", f"{float(val.get('discipline_score') or 0):.1f}/100")
    with c4:
        st.metric("Tiết kiệm thời gian", f"~{int(val.get('time_saved_min_est') or 0)} phút")

    st.markdown("### 🎯 Next Best Action (cá nhân hóa)")
    st.info(f"**{nba.get('title')}**\n\n- Vì sao: {nba.get('reason')}\n- Tác động kỳ vọng: {nba.get('target_impact')}")

    st.markdown("### 🗓️ Top 3 việc phải làm hôm nay")
    tasks = today_action_board(user_id)
    for t in tasks:
        mark = "✅" if t.get("status") == "done" else "⬜"
        st.caption(f"{mark} {t.get('task')} — {t.get('impact')}")

    st.markdown("### 💸 Proof of Value")
    pov = proof_of_value_report(user_id)
    p1, p2, p3, p4 = st.columns(4)
    with p1:
        st.metric("Realized PnL 30d", f"{float(pov.get('realized_pnl_30d') or 0):,.0f} VND")
    with p2:
        st.metric("Win-rate 30d", f"{float(pov.get('win_rate_realized_30d') or 0):.1f}%")
    with p3:
        st.metric("Risk Shield", f"{float(pov.get('risk_shield_score') or 0):.1f}/100")
    with p4:
        st.metric("Tiết kiệm thời gian", f"~{int(pov.get('time_saved_min_est') or 0)} phút")
    st.caption(str(pov.get("value_message") or ""))
    monthly_fee = 500_000.0
    realized = float(pov.get("realized_pnl_30d") or 0.0)
    value_ratio = (realized / monthly_fee) if monthly_fee > 0 else 0.0
    st.caption(f"ROI so với phí 500K/tháng (theo Realized PnL 30d): {value_ratio:.2f}x")
    ms = value_maturity_score(user_id)
    st.caption(f"🧭 Maturity Score: {ms.get('score_10')}/10 · {ms.get('level')}")
    reminders = overdue_action_reminders(user_id)
    if reminders:
        st.markdown("### ⏰ Nhắc việc quan trọng")
        for rm in reminders:
            sev = str(rm.get("severity") or "medium")
            tag = "🔴" if sev == "high" else "🟡"
            st.caption(f"{tag} {rm.get('title')}: {rm.get('message')}")


def render_next_best_action_cta(
    user_id: str,
    ticker: str,
    report: dict[str, Any],
    plan_id: str,
    *,
    next_best_action: Callable[[str], dict[str, Any]],
    can_use_feature: Callable[..., tuple[bool, str]],
    add_alert: Callable[..., Any],
    add_decision: Callable[..., tuple[bool, str]],
    log_event: Callable[..., Any],
) -> None:
    nba = next_best_action(user_id)
    nid = str(nba.get("id") or "")
    plan = report.get("risk_plan") or {}
    sl = float(plan.get("stop_loss_price") or 0)
    tp = float(plan.get("take_profit_price") or 0)
    entry = float(plan.get("entry_price") or 0)
    action = str(report.get("final_action") or "WATCH").upper()
    side = "BUY" if action == "BUY" else "WATCH"
    readiness = str(report.get("decision_readiness") or "LOW").upper()

    st.markdown("### ⚡ Thực thi ngay (1-click)")
    if nid == "create_first_alert":
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Tạo alert SL ngay", width="stretch"):
                ok_alert, msg_alert = can_use_feature(user_id, "alert", 1, plan_id=plan_id)
                if not ok_alert:
                    st.error(msg_alert)
                elif sl > 0:
                    add_alert(user_id, ticker, "price_below", sl, "1-click from Next Best Action")
                    log_event(user_id, "alert_created", {"symbol": ticker, "type": "price_below", "auto": True})
                    st.success(f"Đã tạo alert SL cho {ticker} tại {sl:,.2f}.")
                else:
                    st.warning("Không có mức SL hợp lệ từ risk plan.")
        with c2:
            if st.button("Tạo alert TP ngay", width="stretch"):
                ok_alert, msg_alert = can_use_feature(user_id, "alert", 1, plan_id=plan_id)
                if not ok_alert:
                    st.error(msg_alert)
                elif tp > 0:
                    add_alert(user_id, ticker, "price_above", tp, "1-click from Next Best Action")
                    log_event(user_id, "alert_created", {"symbol": ticker, "type": "price_above", "auto": True})
                    st.success(f"Đã tạo alert TP cho {ticker} tại {tp:,.2f}.")
                else:
                    st.warning("Không có mức TP hợp lệ từ risk plan.")
        return

    if nid == "log_first_decision":
        buy_blocked = side == "BUY" and readiness == "LOW"
        if buy_blocked:
            st.error("Decision readiness đang LOW: tạm khóa lưu decision BUY để tránh vào lệnh sớm.")
        if st.button("Lưu decision từ risk plan", width="stretch", disabled=buy_blocked):
            if entry > 0 and sl > 0 and tp > 0:
                ok_dec, msg_dec = add_decision(
                    user_id,
                    ticker,
                    side,
                    float(entry),
                    float(sl),
                    float(tp),
                    "Auto decision from Next Best Action",
                    30,
                )
                if ok_dec:
                    log_event(user_id, "decision_added", {"symbol": ticker, "side": side, "auto": True})
                    st.success("Đã lưu decision mẫu thành công.")
                else:
                    st.error(msg_dec)
            else:
                st.warning("Risk plan chưa đủ Entry/SL/TP để lưu decision.")
        return

    if nid == "do_first_analysis":
        st.caption("Bạn đang ở bước đúng: bấm `🚀 Phân tích ngay` ở sidebar để hoàn tất hành động này.")
        return
    if nid == "tighten_execution":
        st.caption("Gợi ý: mở tab `📊 Sức khỏe tài chính` để xem `Kế hoạch vs Thực thi` và chỉnh điểm vào/ra.")
        return
    if nid == "close_trade_samples":
        st.caption("Gợi ý: hoàn tất thêm các trade đang mở để hệ thống học được phong cách thực thi của bạn.")
        return
    if nid == "complete_aha_journey":
        st.caption("Gợi ý: hoàn tất các bước còn thiếu trong `Aha Journey` để mở khóa cá nhân hóa sâu hơn.")
        return

    st.caption("Bạn đã ở trạng thái tốt. Bước tiếp theo là tối ưu chất lượng RR và tuân thủ kế hoạch.")
