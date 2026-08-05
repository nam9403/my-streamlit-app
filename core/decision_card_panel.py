"""
Mobile-friendly decision card (P2) — one-screen: action, MOS, risk, readiness, legend note.
Wave 5: vì sao không BUY + journal 1-click từ card.
"""

from __future__ import annotations

import html
from typing import Any, Callable

import streamlit as st

from core.decision_action_gate import (
    action_display_vi,
    align_report_action_with_autopilot_board,
    format_missing_items,
    resolve_display_action,
)

_PHASE_VI = {
    "accumulation": "Tích lũy",
    "breakout": "Bùng nổ",
    "neutral": "Trung tính",
    "distribution": "Phân phối",
}

_READINESS_VI = {
    "HIGH": "Cao",
    "MEDIUM": "Trung bình",
    "MED": "Trung bình",
    "LOW": "Thấp",
    "CRITICAL": "Rất thấp",
}

_VERDICT_VI = {
    "NO-GO": "CHƯA ĐẠT DÒNG TIỀN",
    "GO": "ĐẠT",
    "CAUTION": "THẬN TRỌNG",
    "PASS": "ĐẠT",
}


def build_decision_card_payload(report: dict[str, Any] | None, *, symbol: str = "") -> dict[str, Any]:
    sym = str(symbol or (report or {}).get("symbol") or (report or {}).get("ticker") or "").upper()
    # Same action as Autopilot Top when board is fresh (ACB: GIỮ on both, never GIỮ vs QUAN SÁT).
    rep = align_report_action_with_autopilot_board(report if isinstance(report, dict) else {}, symbol=sym)
    gate = resolve_display_action(rep)
    val = rep.get("valuation") if isinstance(rep.get("valuation"), dict) else {}
    phase = rep.get("phase") if isinstance(rep.get("phase"), dict) else {}
    rp = rep.get("risk_plan") if isinstance(rep.get("risk_plan"), dict) else {}
    align = rep.get("decision_alignment") if isinstance(rep.get("decision_alignment"), dict) else {}
    dts = rep.get("data_trust_score") if isinstance(rep.get("data_trust_score"), dict) else {}

    action = str(gate.get("display_action") or "WATCH").upper()
    pe_anomaly = bool(val.get("pe_anomaly_flag") or val.get("eps_anomaly_flag"))
    pb = rep.get("decision_playbook") if isinstance(rep.get("decision_playbook"), dict) else {}
    trig = pb.get("trigger") if isinstance(pb.get("trigger"), dict) else {}
    thesis = pb.get("thesis") if isinstance(pb.get("thesis"), dict) else {}
    setup = pb.get("setup") if isinstance(pb.get("setup"), dict) else {}
    return {
        "symbol": sym,
        "action": action,
        "action_vi": action_display_vi(action),
        "legend": str(val.get("instant_conclusion") or gate.get("legend_view") or "—"),
        "phase": str(phase.get("phase") or "neutral"),
        "mos_pct": val.get("margin_of_safety_composite_pct"),
        "price": val.get("price"),
        "fair_price": val.get("composite_target_price") or val.get("intrinsic_value_graham") or val.get("graham_number"),
        "confidence_pct": rep.get("confidence_score"),
        "readiness": gate.get("decision_readiness") or rep.get("decision_readiness") or "LOW",
        "missing_summary": gate.get("missing_summary") or format_missing_items(rep.get("missing_items")),
        "alignment_note": gate.get("note_vi") or align.get("note_vi") or "",
        "verdict": rep.get("analysis_verdict"),
        "entry": rp.get("entry_price") or trig.get("entry_price"),
        "sl": rp.get("stop_loss_price"),
        "tp": rp.get("take_profit_price"),
        "invalidation": trig.get("invalidation_price") or rp.get("invalidation_price"),
        "entry_hint": trig.get("entry_hint_vi") or rp.get("entry_hint_vi") or "",
        "cancel_if": trig.get("cancel_if_vi") or rp.get("cancel_if_vi") or "",
        "thesis_grade": thesis.get("grade"),
        "setup_status": setup.get("status"),
        "trigger_status": trig.get("status"),
        "playbook_summary": pb.get("summary_vi") or pb.get("user_instruction_vi") or "",
        "why_not_buy": _why_not_buy(action, thesis, setup, trig, pb, val, gate),
        "event_blackout": bool((pb.get("event_blackout") or {}).get("blackout")),
        "event_blackout_note": str((pb.get("event_blackout") or {}).get("note_vi") or ""),
        "data_trust_score": dts.get("score"),
        "data_trust_band": dts.get("band"),
        "show_trade_plan": bool(gate.get("show_trade_plan")),
        "is_conditional": bool(gate.get("is_conditional") or action == "CONDITIONAL_BUY"),
        "pe_anomaly_flag": pe_anomaly,
        "eps_pe_anomaly_warning_vi": str(val.get("eps_pe_anomaly_warning_vi") or "") if pe_anomaly else "",
    }


def _why_not_buy(
    action: str,
    thesis: dict[str, Any],
    setup: dict[str, Any],
    trigger: dict[str, Any],
    playbook: dict[str, Any],
    valuation: dict[str, Any],
    gate: dict[str, Any],
) -> str:
    """Wave 5: one-line reason when action is not BUY."""
    act = str(action or "WATCH").upper()
    if act == "BUY":
        return ""
    bits: list[str] = []
    if act == "AVOID":
        bits.append("Thesis/gate AVOID — đứng ngoài")
    if thesis.get("attractive") is False:
        bits.append("Thesis chưa attractive")
    if str(thesis.get("grade") or "") == "C":
        bits.append("Thesis C")
    setup_st = str(setup.get("status") or "")
    if setup_st in ("WAIT", "ABORT"):
        bits.append(f"Setup {setup_st}")
    trig_st = str(trigger.get("status") or "")
    if trig_st in ("PENDING", "INVALID"):
        bits.append(f"Trigger {trig_st}")
    bo = playbook.get("event_blackout") if isinstance(playbook.get("event_blackout"), dict) else {}
    if bo.get("blackout"):
        bits.append("Event blackout")
    srel = valuation.get("sector_relative") if isinstance(valuation.get("sector_relative"), dict) else {}
    if str(srel.get("band") or "") == "rich":
        bits.append("Đắt hơn peer")
    if gate.get("is_gate_restricted"):
        bits.append("Gate restricted")
    miss = str(gate.get("missing_summary") or "").strip()
    if miss and miss not in ("—", "-"):
        bits.append(f"Thiếu DL: {miss[:40]}")
    if act == "HOLD" and not bits:
        bits.append("Giữ/theo dõi — chưa mở mua mới")
    if act == "CONDITIONAL_BUY":
        bits.append("Chỉ mua có điều kiện — chờ zone/pha")
    if act == "WATCH" and not bits:
        bits.append("Chưa đủ Thesis/Setup/Trigger")
    seen: set[str] = set()
    out: list[str] = []
    for b in bits:
        if b not in seen:
            seen.add(b)
            out.append(b)
    return " · ".join(out[:5])


def _fmt_num(v: Any, *, digits: int = 1, suffix: str = "") -> str:
    if v is None or v == "":
        return "—"
    try:
        f = float(v)
        if abs(f) >= 1000:
            return f"{f:,.0f}{suffix}"
        return f"{f:.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return str(v)


def build_journal_draft_from_card(
    report: dict[str, Any] | None,
    *,
    symbol: str = "",
    horizon_days: int = 40,
) -> dict[str, Any]:
    """Wave 5.3 — prefill decision/trade journal fields from the decision card."""
    card = build_decision_card_payload(report, symbol=symbol)
    rep = report if isinstance(report, dict) else {}
    action = str(card.get("action") or "WATCH").upper()
    side = "BUY" if action == "BUY" else "WATCH"
    readiness = str(card.get("readiness") or rep.get("decision_readiness") or "LOW").upper()
    entry = card.get("entry")
    if entry in (None, ""):
        entry = card.get("price")
    try:
        entry_f = float(entry or 0)
    except (TypeError, ValueError):
        entry_f = 0.0
    try:
        sl_f = float(card.get("sl") or 0)
    except (TypeError, ValueError):
        sl_f = 0.0
    try:
        tp_f = float(card.get("tp") or 0)
    except (TypeError, ValueError):
        tp_f = 0.0
    inv = card.get("invalidation")
    try:
        inv_f = float(inv) if inv not in (None, "") else 0.0
    except (TypeError, ValueError):
        inv_f = 0.0
    if sl_f <= 0 and inv_f > 0:
        sl_f = inv_f
    if sl_f <= 0 and entry_f > 0:
        sl_f = round(entry_f * 0.92, 2)
    if tp_f <= 0 and entry_f > 0:
        fair = card.get("fair_price")
        try:
            fair_f = float(fair) if fair not in (None, "") else 0.0
        except (TypeError, ValueError):
            fair_f = 0.0
        tp_f = round(fair_f, 2) if fair_f > entry_f else round(entry_f * 1.12, 2)
    bits = [
        str(card.get("playbook_summary") or "").strip(),
        f"Action {action}",
    ]
    if card.get("why_not_buy"):
        bits.append(f"WhyNotBuy: {card.get('why_not_buy')}")
    if card.get("thesis_grade") or card.get("setup_status") or card.get("trigger_status"):
        bits.append(
            f"T/S/Tr {card.get('thesis_grade') or '—'}/"
            f"{card.get('setup_status') or '—'}/{card.get('trigger_status') or '—'}"
        )
    thesis = " · ".join(b for b in bits if b)[:500]
    buy_blocked = side == "BUY" and readiness == "LOW"
    ready = entry_f > 0 and sl_f > 0 and tp_f > 0 and not buy_blocked
    return {
        "symbol": str(card.get("symbol") or symbol or "").upper(),
        "side": side,
        "action": action,
        "entry_price": round(entry_f, 2),
        "stop_loss": round(sl_f, 2),
        "take_profit": round(tp_f, 2),
        "thesis": thesis,
        "horizon_days": int(horizon_days),
        "quantity": 100.0,
        "readiness": readiness,
        "buy_blocked": buy_blocked,
        "ready": ready,
        "why_not_buy": str(card.get("why_not_buy") or ""),
    }


def render_journal_one_click(
    report: dict[str, Any] | None,
    *,
    user_id: str,
    symbol: str = "",
    add_decision: Callable[..., tuple[bool, str]] | None = None,
    open_trade: Callable[..., tuple[bool, str]] | None = None,
    log_event: Callable[..., Any] | None = None,
    can_use_feature: Callable[..., tuple[bool, str]] | None = None,
    record_usage: Callable[..., Any] | None = None,
    plan_id: str | None = None,
    horizon_days: int = 40,
) -> None:
    """One button: persist decision (+ optional trade open) from card defaults."""
    if add_decision is None or not user_id:
        return
    draft = build_journal_draft_from_card(report, symbol=symbol, horizon_days=horizon_days)
    sym = draft["symbol"]
    st.caption(
        f"Journal draft: {sym} · {draft['side']} · entry {draft['entry_price']:,.0f} · "
        f"SL {draft['stop_loss']:,.0f} · TP {draft['take_profit']:,.0f} · {draft['horizon_days']}d"
    )
    if draft["buy_blocked"]:
        st.warning("Readiness LOW — khóa ghi journal BUY. Chọn WATCH hoặc chờ tín hiệu mạnh hơn.")
    quota_ok = True
    quota_msg = ""
    if can_use_feature is not None:
        quota_ok, quota_msg = can_use_feature(user_id, "journal_one_click", 1, plan_id=plan_id)
        if not quota_ok:
            st.caption(quota_msg)
    c1, c2 = st.columns(2)
    with c1:
        if st.button(
            "📒 Ghi journal 1 click",
            key=f"journal_one_click_{sym}",
            width="stretch",
            disabled=not (draft["ready"] and quota_ok),
        ):
            ok, msg = add_decision(
                user_id,
                sym,
                draft["side"],
                float(draft["entry_price"]),
                float(draft["stop_loss"]),
                float(draft["take_profit"]),
                draft["thesis"],
                int(draft["horizon_days"]),
            )
            if ok and record_usage is not None:
                try:
                    record_usage(user_id, "journal_one_click", 1)
                except Exception:
                    pass
            if ok and log_event:
                log_event(
                    user_id,
                    "decision_added",
                    {"symbol": sym, "side": draft["side"], "source": "decision_card_one_click"},
                )
            if ok:
                st.success(msg or "Đã ghi journal từ thẻ quyết định.")
            else:
                st.error(msg)
    with c2:
        if open_trade is None:
            st.caption("Trade open: chưa gắn.")
            return
        if st.button(
            "🟢 Mở trade 100 CP",
            key=f"journal_open_trade_{sym}",
            width="stretch",
            disabled=not (draft["entry_price"] > 0 and quota_ok),
        ):
            ok_tr, msg_tr = open_trade(
                user_id,
                sym,
                float(draft["quantity"]),
                float(draft["entry_price"]),
                decision_id=None,
                entry_note=f"1-click từ card · {draft['action']}",
            )
            if ok_tr and record_usage is not None:
                try:
                    record_usage(user_id, "journal_one_click", 1)
                except Exception:
                    pass
            if ok_tr and log_event:
                log_event(
                    user_id,
                    "trade_opened",
                    {"symbol": sym, "qty": draft["quantity"], "source": "decision_card_one_click"},
                )
            if ok_tr:
                st.success(msg_tr)
            else:
                st.error(msg_tr)


def render_mobile_decision_card(
    report: dict[str, Any] | None,
    *,
    symbol: str = "",
    expanded: bool = True,
    user_id: str = "",
    add_decision: Callable[..., tuple[bool, str]] | None = None,
    open_trade: Callable[..., tuple[bool, str]] | None = None,
    log_event: Callable[..., Any] | None = None,
    can_use_feature: Callable[..., tuple[bool, str]] | None = None,
    record_usage: Callable[..., Any] | None = None,
    plan_id: str | None = None,
) -> None:
    """Compact card suitable for mobile / Telegram-style scanning."""
    card = build_decision_card_payload(report, symbol=symbol)
    sym = html.escape(str(card.get("symbol") or "—"))
    action_vi = html.escape(str(card.get("action_vi") or "QUAN SÁT"))
    legend = html.escape(str(card.get("legend") or "—"))
    phase_raw = str(card.get("phase") or "neutral")
    phase = html.escape(_PHASE_VI.get(phase_raw, phase_raw))
    readiness = html.escape(_READINESS_VI.get(str(card.get("readiness") or "").upper(), "Thấp"))
    missing = html.escape(str(card.get("missing_summary") or "—"))
    note = html.escape(str(card.get("alignment_note") or ""))
    verdict = html.escape(_VERDICT_VI.get(str(card.get("verdict") or "").upper(), str(card.get("verdict") or "—")))

    action_colors = {
        "MUA": "#0d7a3a",
        "MUA CÓ ĐIỀU KIỆN": "#2e7d32",
        "GIỮ": "#1a5fb4",
        "QUAN SÁT": "#b8860b",
        "TRÁNH": "#c0392b",
    }
    accent = action_colors.get(action_vi, "#555")

    trust_line = ""
    if card.get("data_trust_score") is not None:
        trust_line = f"Độ tin cậy dữ liệu {card.get('data_trust_score')} ({card.get('data_trust_band') or '—'})"

    plan_bits = []
    if card.get("show_trade_plan"):
        if card.get("entry"):
            plan_bits.append(f"Giá mua {_fmt_num(card.get('entry'))} đ")
        if card.get("sl"):
            plan_bits.append(f"Cắt lỗ {_fmt_num(card.get('sl'))} đ")
        if card.get("tp"):
            plan_bits.append(f"Chốt lời {_fmt_num(card.get('tp'))} đ")
        if card.get("invalidation"):
            plan_bits.append(f"Hủy nếu mất {_fmt_num(card.get('invalidation'))} đ")
    if card.get("action") == "CONDITIONAL_BUY" and card.get("entry_hint"):
        plan_line = html.escape(str(card.get("entry_hint")))
        if plan_bits:
            plan_line = plan_line + " · " + " · ".join(plan_bits)
    else:
        plan_line = " · ".join(plan_bits) if plan_bits else "Không đề xuất vào lệnh (QUAN SÁT/TRÁNH)."

    price_txt = html.escape(_fmt_num(card.get("price")))
    fair_txt = html.escape(_fmt_num(card.get("fair_price")))
    mos_raw = card.get("mos_pct")
    try:
        mos_f = float(mos_raw) if mos_raw not in (None, "") else None
    except (TypeError, ValueError):
        mos_f = None
    mos_txt = _fmt_num(mos_raw, suffix="%")
    if mos_f is not None and mos_f > 0 and not str(mos_txt).startswith("+") and mos_txt != "—":
        mos_txt = f"+{mos_txt}"
    mos_txt = html.escape(mos_txt)
    if mos_f is None:
        mos_emoji, mos_color, mos_note = "🛡️", "#64748b", ""
    elif mos_f < 0:
        mos_emoji, mos_color, mos_note = "🔴", "#b91c1c", "Thị giá cao hơn định giá"
    elif mos_f > 0:
        mos_emoji, mos_color, mos_note = "🟢", "#15803d", "Biên an toàn rộng" if mos_f >= 10 else "Biên an toàn dương"
    else:
        mos_emoji, mos_color, mos_note = "🛡️", "#64748b", "Hòa với định giá"
    mos_note_html = f" <span style='color:#64748b;'>({html.escape(mos_note)})</span>" if mos_note else ""

    playbook_bits = []
    if card.get("thesis_grade"):
        playbook_bits.append(f"Thesis {html.escape(str(card.get('thesis_grade')))}")
    if card.get("setup_status"):
        playbook_bits.append(f"Setup {html.escape(str(card.get('setup_status')))}")
    if card.get("trigger_status"):
        playbook_bits.append(f"Trigger {html.escape(str(card.get('trigger_status')))}")
    playbook_line = " · ".join(playbook_bits)
    summary_esc = html.escape(str(card.get("playbook_summary") or ""))
    cancel_esc = html.escape(str(card.get("cancel_if") or ""))
    playbook_parts: list[str] = []
    if playbook_line or summary_esc:
        inner = f"<b>Playbook</b>{(': ' + playbook_line) if playbook_line else ''}"
        if summary_esc:
            inner += f'<div style="margin-top:4px;font-style:italic;">{summary_esc}</div>'
        if cancel_esc and card.get("is_conditional"):
            inner += f'<div style="margin-top:4px;color:#9a3412;">Hủy: {cancel_esc}</div>'
        playbook_parts.append(
            '<div style="font-size:0.84rem;color:#1e3a5f;margin-top:8px;padding:8px 10px;'
            'border-radius:8px;background:#eef6ff;border:1px solid #bfdbfe;">'
            f"{inner}</div>"
        )
    playbook_html = "".join(playbook_parts)

    with st.expander("📱 Thẻ quyết định (mobile)", expanded=expanded):
        st.markdown(
            f"""
<div style="border:2px solid {accent};border-radius:14px;padding:14px 16px;margin:4px 0;
background:linear-gradient(135deg,#fafafa,#f4f6f8);max-width:480px;">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">
    <div>
      <div style="font-size:1.2rem;font-weight:800;color:#0f172a;">{sym}</div>
      <div style="font-size:24px;font-weight:800;color:#0f172a;margin-top:4px;line-height:1.15;">
        💵 {price_txt} <span style="font-size:0.9rem;font-weight:600;color:#64748b;">đ</span>
      </div>
      <div style="font-size:0.88rem;color:#334155;margin-top:8px;line-height:1.45;">
        {mos_emoji} Định giá: <b>{fair_txt} đ</b> · MOS:
        <b style="color:{mos_color};">{mos_txt}</b>{mos_note_html}
      </div>
    </div>
    <div style="font-size:0.82rem;font-weight:700;color:{accent};border:1.5px solid {accent};
      border-radius:999px;padding:6px 10px;white-space:nowrap;">{action_vi}</div>
  </div>
  <div style="font-size:0.88rem;color:#333;margin-top:10px;">
    Legend: <b>{legend}</b> · Xu hướng: <b>{phase}</b> · Đánh giá: <b>{verdict}</b>
  </div>
  <div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:10px;font-size:0.85rem;">
    <span style="background:#fff;border:1px solid #ddd;border-radius:8px;padding:4px 8px;">
      Biên an toàn <span style="color:{mos_color};font-weight:700;">{mos_txt}</span>
    </span>
    <span style="background:#fff;border:1px solid #ddd;border-radius:8px;padding:4px 8px;">
      Độ tin cậy {_fmt_num(card.get('confidence_pct'), suffix='%')}
    </span>
    <span style="background:#fff;border:1px solid #ddd;border-radius:8px;padding:4px 8px;">
      Sẵn sàng {readiness}
    </span>
  </div>
  <div style="font-size:0.85rem;color:#555;margin-top:8px;">Thiếu dữ liệu: {missing}</div>
  <div style="font-size:0.85rem;color:#555;margin-top:4px;">{html.escape(plan_line)}</div>
  {playbook_html}
  {f'<div style="margin-top:8px;padding:8px 10px;border-radius:8px;border:1px solid #94a3b8;background:#f8fafc;color:#334155;font-size:0.82rem;"><b>Vì sao không BUY:</b> {html.escape(str(card.get("why_not_buy") or ""))}</div>' if card.get("why_not_buy") else ''}
  {f'<div style="margin-top:6px;padding:6px 10px;border-radius:8px;border:1px solid #fcd34d;background:#fffbeb;color:#92400e;font-size:0.8rem;">Event: {html.escape(str(card.get("event_blackout_note") or "Blackout sự kiện"))}</div>' if card.get("event_blackout") else ''}
  {f'<div style="font-size:0.82rem;color:#666;margin-top:6px;">{trust_line}</div>' if trust_line else ''}
  {f'<div style="margin-top:8px;padding:8px 10px;border-radius:8px;border:1px solid #f59e0b;background:#fff7ed;color:#9a3412;font-size:0.82rem;">⚠️ {html.escape(str(card.get("eps_pe_anomaly_warning_vi") or "P/E có dấu hiệu méo do lợi nhuận đột biến."))}</div>' if card.get("pe_anomaly_flag") else ''}
  {f'<div style="font-size:0.82rem;color:#444;margin-top:8px;font-style:italic;">{note}</div>' if note else ''}
</div>
            """,
            unsafe_allow_html=True,
        )
        st.caption("Thẻ tối ưu màn hình hẹp / copy sang Telegram. Không phải lời khuyên đầu tư.")
        if user_id and add_decision is not None:
            render_journal_one_click(
                report,
                user_id=user_id,
                symbol=symbol or str(card.get("symbol") or ""),
                add_decision=add_decision,
                open_trade=open_trade,
                log_event=log_event,
                can_use_feature=can_use_feature,
                record_usage=record_usage,
                plan_id=plan_id,
            )
