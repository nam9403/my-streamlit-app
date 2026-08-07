"""
Unified BUY/WATCH/HOLD/AVOID gate (P1).

Single source for Autopilot board, Simple View, and DSS-style displays so
Legend (instant_conclusion), final_action, and gate_passed stay aligned.
"""

from __future__ import annotations

from typing import Any

VALID_ACTIONS = frozenset({"BUY", "CONDITIONAL_BUY", "HOLD", "WATCH", "AVOID"})

_ACTION_VI = {
    "BUY": "MUA",
    "CONDITIONAL_BUY": "MUA CÓ ĐIỀU KIỆN",
    "HOLD": "GIỮ",
    "WATCH": "QUAN SÁT",
    "AVOID": "TRÁNH",
}

_ACTION_ALIASES = {
    "MUA": "BUY",
    "MUA CÓ ĐIỀU KIỆN": "CONDITIONAL_BUY",
    "CONDITIONAL BUY": "CONDITIONAL_BUY",
    "GIỮ": "HOLD",
    "QUAN SÁT": "WATCH",
    "TRÁNH": "AVOID",
    "SELL": "AVOID",
}


def quality_offset_from_valuation(valuation: dict[str, Any] | None) -> dict[str, Any]:
    """Đọc Quality Offset từ valuation (sau value_investing_summary)."""
    val = valuation if isinstance(valuation, dict) else {}
    qo = val.get("quality_offset") if isinstance(val.get("quality_offset"), dict) else {}
    if qo:
        return dict(qo)
    return {
        "is_quality_compensated": bool(val.get("is_quality_compensated")),
        "conf_boost": 0.0,
        "note_vi": str(val.get("quality_offset_note_vi") or ""),
        "effective_f_score_for_buy_gate": int(val.get("piotroski_score") or 0),
    }


def effective_f_score_for_gate(valuation: dict[str, Any] | None) -> int:
    """
    F-Score dùng cho ngưỡng BUY/alignment.
    Khi Quality Offset: F=4 được coi như đạt ngưỡng F>=6 (không demote cứng vì F=4).
    """
    val = valuation if isinstance(valuation, dict) else {}
    qo = quality_offset_from_valuation(val)
    raw = int(val.get("piotroski_score") or 0)
    if bool(qo.get("is_quality_compensated")):
        try:
            return max(raw, int(qo.get("effective_f_score_for_buy_gate") or 6))
        except (TypeError, ValueError):
            return max(raw, 6)
    return raw


def quality_offset_conf_boost(valuation: dict[str, Any] | None) -> float:
    """Điểm thưởng conf (+5..+10) khi Quality Offset kích hoạt."""
    qo = quality_offset_from_valuation(valuation)
    if not qo.get("is_quality_compensated"):
        return 0.0
    try:
        boost = float(qo.get("conf_boost") or 0.0)
    except (TypeError, ValueError):
        boost = 0.0
    return max(0.0, min(10.0, boost))


def should_skip_fscore_hard_demote(valuation: dict[str, Any] | None, *, raw_f_score: int | None = None) -> bool:
    """True nếu không được hạ BUY→WATCH chỉ vì F-Score = 4 (đã bù trừ chất lượng)."""
    val = valuation if isinstance(valuation, dict) else {}
    fs = int(raw_f_score if raw_f_score is not None else (val.get("piotroski_score") or 0))
    return bool(val.get("is_quality_compensated") or quality_offset_from_valuation(val).get("is_quality_compensated")) and fs == 4


def normalize_action(action: str | None, *, default: str = "WATCH") -> str:
    raw = str(action or default).strip().upper()
    if raw in VALID_ACTIONS:
        return raw
    alias = _ACTION_ALIASES.get(raw)
    if alias:
        return alias
    return default if default in VALID_ACTIONS else "WATCH"


def action_display_vi(action: str | None) -> str:
    return _ACTION_VI.get(normalize_action(action), "QUAN SÁT")


def format_missing_items(items: list[str] | None, *, max_items: int = 4) -> str:
    missing = [str(x).strip() for x in (items or []) if str(x).strip()]
    if not missing:
        return "—"
    if len(missing) <= max_items:
        return ", ".join(missing)
    head = ", ".join(missing[:max_items])
    return f"{head} (+{len(missing) - max_items})"


def _alignment_from_report(report: dict[str, Any], base_action: str) -> dict[str, Any]:
    align = report.get("decision_alignment")
    if isinstance(align, dict) and align.get("unified_action"):
        return align
    val = report.get("valuation") if isinstance(report.get("valuation"), dict) else {}
    phase = report.get("phase") if isinstance(report.get("phase"), dict) else {}
    try:
        from core.ai_logic import _decision_alignment

        return _decision_alignment(val, base_action, phase)
    except Exception:
        return {
            "legend_view": val.get("instant_conclusion"),
            "action_view": base_action,
            "unified_action": base_action,
            "alignment": "unknown",
            "note_vi": "",
        }


def trade_plan_visibility_flags(action: str | None) -> dict[str, bool]:
    """
    Phân lớp hiển thị Trade Plan theo khuyến nghị.

    - BUY / CONDITIONAL_BUY: entry_allowed + risk_management_visible
    - HOLD: chỉ risk_management_visible (SL / quản trị vị thế); Entry khóa
    - WATCH / AVOID: khóa toàn bộ
    """
    act = normalize_action(action)
    entry_allowed = act in ("BUY", "CONDITIONAL_BUY")
    risk_management_visible = act in ("BUY", "CONDITIONAL_BUY", "HOLD")
    return {
        "entry_allowed": bool(entry_allowed),
        "risk_management_visible": bool(risk_management_visible),
        "show_trade_plan": bool(risk_management_visible),
    }


def resolve_display_action(report: dict[str, Any] | None) -> dict[str, Any]:
    """
    Derive the action shown in Autopilot / Simple View from a strategic report.

    Rules (in order):
      1. Start from report final_action + decision_alignment.unified_action
      2. Prefer playbook recommended HOLD/BUY when alignment still says WATCH (stale/soft)
      3. BUY requires gate_passed + output_gate_passed
      4. CONDITIONAL_BUY allowed with gates; shown as actionable plan (conditional)
      5. High-severity completeness → cap at WATCH (BUY/CONDITIONAL/HOLD)
      6. analysis_verdict NO-GO → no BUY (CONDITIONAL may remain if thesis attractive)
    """
    rep = report if isinstance(report, dict) else {}
    base = normalize_action(rep.get("final_action"))
    align = _alignment_from_report(rep, base)
    unified = normalize_action(align.get("unified_action") or base)
    display = unified
    notes: list[str] = []
    note_vi = str(align.get("note_vi") or "").strip()
    if note_vi:
        notes.append(note_vi)

    pb = rep.get("decision_playbook") if isinstance(rep.get("decision_playbook"), dict) else {}
    rec = normalize_action(pb.get("recommended_action") or "")
    # Unify Autopilot board vs Decision Card: playbook HOLD/BUY beats soft WATCH alignment.
    _rank = {"AVOID": 0, "WATCH": 1, "HOLD": 2, "CONDITIONAL_BUY": 3, "BUY": 4}
    preferred = base if _rank.get(base, 1) >= _rank.get(unified, 1) else unified
    if rec in ("HOLD", "BUY", "CONDITIONAL_BUY") and _rank.get(rec, 1) > _rank.get(display, 1):
        display = rec
        if rec == "HOLD" and unified == "WATCH":
            notes.append("Đồng bộ playbook: GIỮ (chờ trigger) — không mở mua mới.")
    elif preferred in ("HOLD", "BUY", "CONDITIONAL_BUY") and display == "WATCH" and _rank.get(preferred, 1) > 1:
        display = preferred

    dc = rep.get("decision_completeness") if isinstance(rep.get("decision_completeness"), dict) else {}
    missing = list(rep.get("missing_items") or dc.get("missing_items") or [])
    readiness = str(rep.get("decision_readiness") or "LOW").upper()

    if display == "BUY":
        if not bool(rep.get("gate_passed")):
            display = "WATCH"
            notes.append("Confidence gate chưa pass — không đề xuất MUA.")
        elif not bool(rep.get("output_gate_passed", True)):
            display = "WATCH"
            notes.append("Output gate chưa pass — không đề xuất MUA.")
        elif str(rep.get("analysis_verdict") or "").upper() == "NO-GO":
            thesis = pb.get("thesis") if isinstance(pb.get("thesis"), dict) else {}
            if str(thesis.get("grade") or "") in ("A", "B") and thesis.get("attractive"):
                display = "CONDITIONAL_BUY"
                notes.append("Verdict NO-GO — hạ MUA cứng xuống MUA CÓ ĐIỀU KIỆN (thesis còn hấp dẫn).")
            else:
                display = "WATCH"
                notes.append("Verdict NO-GO — không đề xuất MUA.")

    if display == "CONDITIONAL_BUY":
        if not bool(rep.get("gate_passed")) and not bool(rep.get("output_gate_passed", True)):
            display = "WATCH"
            notes.append("Gates chưa pass — hủy MUA CÓ ĐIỀU KIỆN.")
        elif not bool(rep.get("output_gate_passed", True)):
            display = "WATCH"
            notes.append("Output gate chưa pass — không đề xuất lệnh có điều kiện.")
        thesis = pb.get("thesis") if isinstance(pb.get("thesis"), dict) else {}
        setup = pb.get("setup") if isinstance(pb.get("setup"), dict) else {}
        if str(setup.get("status") or "") == "ABORT":
            display = "WATCH"
            notes.append("Setup ABORT — hủy CONDITIONAL_BUY.")
        elif str(thesis.get("grade") or "") == "C" and not thesis.get("attractive"):
            display = "WATCH"
            notes.append("Thesis yếu — hủy CONDITIONAL_BUY.")

    if dc.get("severity") == "high" and display in ("BUY", "HOLD", "CONDITIONAL_BUY"):
        display = "WATCH"
        notes.append("Thiếu dữ liệu then chốt — cap hành động ở QUAN SÁT.")

    val = rep.get("valuation") if isinstance(rep.get("valuation"), dict) else {}
    qo_note = str(rep.get("quality_offset_note_vi") or val.get("quality_offset_note_vi") or "").strip()
    if bool(rep.get("is_quality_compensated") or val.get("is_quality_compensated")) and qo_note:
        if qo_note not in notes:
            notes.append(qo_note)

    # Phân lớp Trade Plan:
    # - BUY / CONDITIONAL_BUY: mở Entry + SL/TP
    # - HOLD: khóa Entry ("Không mở mua mới"), vẫn mở SL / quản trị rủi ro
    # - WATCH / AVOID: khóa toàn bộ
    plan_flags = trade_plan_visibility_flags(display)
    entry_allowed = bool(plan_flags["entry_allowed"])
    risk_management_visible = bool(plan_flags["risk_management_visible"])
    show_plan = bool(plan_flags["show_trade_plan"])

    return {
        "display_action": display,
        "final_action": base,
        "unified_action": unified,
        "legend_view": align.get("legend_view"),
        "alignment": str(align.get("alignment") or "unknown"),
        "note_vi": " ".join(n for n in notes if n).strip(),
        "decision_readiness": readiness,
        "missing_items": missing,
        "missing_summary": format_missing_items(missing),
        "show_trade_plan": show_plan,
        "entry_allowed": entry_allowed,
        "risk_management_visible": risk_management_visible,
        "completeness_score": dc.get("completeness_score"),
        "is_conditional": display == "CONDITIONAL_BUY",
        "is_quality_compensated": bool(rep.get("is_quality_compensated") or val.get("is_quality_compensated")),
        "quality_offset_note_vi": qo_note,
    }


def autopilot_board_row_for_symbol(
    symbol: str,
    *,
    max_age_hours: float = 36.0,
) -> dict[str, Any] | None:
    """Fresh Autopilot nightly board row for symbol, or None."""
    sym = str(symbol or "").strip().upper()
    if not sym:
        return None
    try:
        from datetime import datetime, timezone

        from core.autopilot_nightly_board import load_board

        board = load_board()
        if not board:
            return None
        updated = str(board.get("updated_at") or "")
        if updated:
            try:
                dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
                if age_h > float(max_age_hours):
                    return None
            except Exception:
                pass
        rows = board.get("rows") or {}
        row = rows.get(sym) if isinstance(rows, dict) else None
        return row if isinstance(row, dict) else None
    except Exception:
        return None


def autopilot_board_action_for_symbol(
    symbol: str,
    *,
    max_age_hours: float = 36.0,
) -> str | None:
    """
    Canonical action from fresh Autopilot nightly board (same source as Top 10).
    Returns None if board missing/stale/symbol absent.
    """
    row = autopilot_board_row_for_symbol(symbol, max_age_hours=max_age_hours)
    if not row:
        return None
    raw = row.get("Khuyến nghị") or row.get("gate_action")
    act = normalize_action(raw)
    return act if act in VALID_ACTIONS else None


def align_report_action_with_autopilot_board(
    report: dict[str, Any] | None,
    *,
    symbol: str = "",
    max_age_hours: float = 36.0,
) -> dict[str, Any]:
    """
    Force deep-analysis display to match Autopilot Top for the same symbol.

    Skip lock when board quote/MOS lệch mạnh so với phân tích live (board đêm cũ)
    — tránh TRÁNH cứng trong khi định giá live đã MOS dương.
    """
    rep = dict(report) if isinstance(report, dict) else {}
    sym = str(symbol or rep.get("symbol") or rep.get("ticker") or "").strip().upper()
    row = autopilot_board_row_for_symbol(sym, max_age_hours=max_age_hours)
    if not row:
        return rep
    board_act = normalize_action(row.get("Khuyến nghị") or row.get("gate_action"))
    if board_act not in VALID_ACTIONS:
        return rep

    val = rep.get("valuation") if isinstance(rep.get("valuation"), dict) else {}
    live_price = _num_or_none(val.get("price")) or _num_or_none(
        (rep.get("snapshot") or {}).get("price") if isinstance(rep.get("snapshot"), dict) else None
    )
    board_price = _num_or_none(row.get("Giá") or row.get("price"))
    live_mos = _num_or_none(val.get("margin_of_safety_composite_pct"))
    board_mos = _num_or_none(row.get("MOS%"))

    desync_reasons: list[str] = []
    if live_price and board_price and live_price > 0 and board_price > 0:
        rel = abs(live_price - board_price) / max(live_price, board_price)
        if rel >= 0.12:
            desync_reasons.append(f"giá board {board_price:,.0f} vs live {live_price:,.0f} ({rel*100:.0f}%)")
    if live_mos is not None and board_mos is not None and abs(live_mos - board_mos) >= 20.0:
        desync_reasons.append(f"MOS board {board_mos:+.1f}% vs live {live_mos:+.1f}%")

    if desync_reasons:
        align = dict(rep.get("decision_alignment") or {})
        note = str(align.get("note_vi") or "").strip()
        skip = "Không khóa Autopilot (board lệch live: " + "; ".join(desync_reasons) + ")."
        align["note_vi"] = f"{note} {skip}".strip() if note else skip
        rep["decision_alignment"] = align
        rep["action_locked_to_autopilot_board"] = False
        rep["action_autopilot_sync_skipped"] = "board_live_desync"
        return rep

    live = normalize_action(rep.get("final_action"))
    if live == board_act:
        rep["action_locked_to_autopilot_board"] = True
        return rep
    rep["final_action"] = board_act
    align = dict(rep.get("decision_alignment") or {})
    align["unified_action"] = board_act
    align["action_view"] = board_act
    note = str(align.get("note_vi") or "").strip()
    sync_note = f"Đồng bộ Autopilot board: {action_display_vi(board_act)}."
    align["note_vi"] = f"{note} {sync_note}".strip() if note else sync_note
    rep["decision_alignment"] = align
    pb = dict(rep.get("decision_playbook") or {})
    pb["recommended_action"] = board_act
    rep["decision_playbook"] = pb
    rep["action_locked_to_autopilot_board"] = True
    return rep


def enrich_autopilot_row(report: dict[str, Any] | None, row: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge unified gate fields into a scanner/autopilot row dict."""
    out = dict(row or {})
    gate = resolve_display_action(report)
    out["Khuyến nghị"] = gate["display_action"]
    out["gate_action"] = gate["display_action"]
    out["Readiness"] = gate["decision_readiness"]
    out["Thiếu DL"] = gate["missing_summary"]
    note = str(gate.get("note_vi") or "")
    out["Ghi chú Legend"] = (note[:120] + "…") if len(note) > 120 else (note or "—")
    out["missing_items"] = list(gate.get("missing_items") or [])
    out["decision_readiness"] = gate["decision_readiness"]
    out["decision_alignment_note"] = note
    if gate.get("completeness_score") is not None:
        out["completeness_score"] = gate.get("completeness_score")
    return out


def _num_or_none(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def classify_cfo_status(
    cfo: Any,
    *,
    is_bank: bool = False,
    cfo_missing: bool | None = None,
) -> str:
    """Return POSITIVE / NEGATIVE / UNKNOWN (banks skip industrial CFO penalty)."""
    if is_bank:
        return "UNKNOWN"
    missing = bool(cfo_missing) if cfo_missing is not None else (cfo is None or cfo == "")
    if missing:
        return "UNKNOWN"
    val = _num_or_none(cfo)
    if val is None:
        return "UNKNOWN"
    if val < 0:
        return "NEGATIVE"
    return "POSITIVE"


def completeness_is_low(report: dict[str, Any] | None, snap: dict[str, Any] | None = None) -> bool:
    """True when readiness/completeness is LOW (or critical gaps)."""
    rep = report if isinstance(report, dict) else {}
    readiness = str(rep.get("decision_readiness") or "").upper()
    if readiness == "LOW":
        return True
    dc = rep.get("decision_completeness") if isinstance(rep.get("decision_completeness"), dict) else {}
    if str(dc.get("severity") or "").lower() == "high":
        return True
    score = dc.get("completeness_score")
    if score is None:
        score = rep.get("completeness_score")
    try:
        if score is not None and float(score) < 50:
            return True
    except (TypeError, ValueError):
        pass
    # Assess on the fly when report lacks completeness block
    if not dc:
        try:
            from core.decision_completeness import assess_decision_completeness

            val = rep.get("valuation") if isinstance(rep.get("valuation"), dict) else {}
            fin = rep.get("financials") if isinstance(rep.get("financials"), dict) else {}
            gate = assess_decision_completeness(snap or {}, val, fin)
            if str(gate.get("severity") or "").lower() == "high":
                return True
            if float(gate.get("completeness_score") or 100) < 50:
                return True
            if str(gate.get("readiness_cap") or "").upper() == "LOW":
                return True
        except Exception:
            pass
    return False


def evaluate_autopilot_gate_restriction(
    report: dict[str, Any] | None,
    *,
    snapshot: dict[str, Any] | None = None,
    valuation: dict[str, Any] | None = None,
    financials: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Prefilter flags for Autopilot ranking alignment with full decision gate.

    Non-bank CFO < 0 OR completeness LOW → is_gate_restricted (+ 50% score penalty).
    """
    rep = report if isinstance(report, dict) else {}
    snap = snapshot if isinstance(snapshot, dict) else {}
    val = valuation if isinstance(valuation, dict) else (rep.get("valuation") if isinstance(rep.get("valuation"), dict) else {})
    fin = financials if isinstance(financials, dict) else (rep.get("financials") if isinstance(rep.get("financials"), dict) else {})

    is_bank = bool(val.get("is_bank_sector") or snap.get("is_bank"))
    if not is_bank:
        ind = str(val.get("industry_display_vi") or snap.get("industry") or "").lower()
        is_bank = "ngân hàng" in ind or "bank" in ind

    cfo_raw = fin.get("operating_cash_flow")
    if cfo_raw is None:
        cfo_raw = snap.get("operating_cash_flow")
    if cfo_raw is None and isinstance(snap.get("piotroski"), dict):
        cfo_raw = snap["piotroski"].get("operating_cash_flow")

    cfo_status = classify_cfo_status(cfo_raw, is_bank=is_bank)
    low_complete = completeness_is_low(rep, snap)
    verdict = str(rep.get("analysis_verdict") or "").upper()
    gate = resolve_display_action(rep)
    gate_action = normalize_action(gate.get("display_action"))

    reasons: list[str] = []
    restricted = False
    if (not is_bank) and cfo_status == "NEGATIVE":
        restricted = True
        reasons.append("cfo_negative")
    if low_complete:
        restricted = True
        reasons.append("completeness_low")
    if verdict == "NO-GO":
        restricted = True
        reasons.append("verdict_no_go")
    if gate_action == "AVOID":
        restricted = True
        reasons.append("gate_avoid")

    return {
        "cfo_status": cfo_status,
        "gate_action": gate_action,
        "is_gate_restricted": bool(restricted),
        "gate_restrict_reasons": reasons,
        "score_penalty_mult": 0.5 if restricted else 1.0,
        "analysis_verdict": verdict or None,
        "is_bank": is_bank,
    }


def apply_gate_fields_to_scan_row(
    row: dict[str, Any] | None,
    report: dict[str, Any] | None,
    *,
    snapshot: dict[str, Any] | None = None,
    valuation: dict[str, Any] | None = None,
    financials: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach cfo_status / gate_action / is_gate_restricted onto a scan row."""
    out = enrich_autopilot_row(report, row)
    flags = evaluate_autopilot_gate_restriction(
        report,
        snapshot=snapshot,
        valuation=valuation,
        financials=financials,
    )
    out["cfo_status"] = flags["cfo_status"]
    out["gate_action"] = flags["gate_action"]
    out["is_gate_restricted"] = flags["is_gate_restricted"]
    out["gate_restrict_reasons"] = list(flags.get("gate_restrict_reasons") or [])
    out["score_penalty_mult"] = flags["score_penalty_mult"]
    out["analysis_verdict"] = flags.get("analysis_verdict")
    # Keep Khuyến nghị aligned with gate_action
    out["Khuyến nghị"] = flags["gate_action"]
    if flags["is_gate_restricted"]:
        note = str(out.get("Ghi chú Legend") or "")
        extra = "Gate hạn chế xếp hạng (CFO/completeness/NO-GO)."
        if extra not in note:
            merged = (note + " " + extra).strip() if note and note != "—" else extra
            out["Ghi chú Legend"] = (merged[:120] + "…") if len(merged) > 120 else merged
    return out


def apply_trade_plan_visibility(report: dict[str, Any] | None) -> dict[str, Any]:
    """
    Gắn cờ hiển thị Trade Plan theo action:

    - ``entry_allowed``: được mở vùng mua (BUY / CONDITIONAL_BUY)
    - ``risk_management_visible``: hiện SL / TP / quản trị rủi ro (BUY / COND / HOLD)
    - ``trade_plan_active`` / ``show_trade_plan``: còn phần plan nào được hiện

    Integrity P0 khóa Entry (không giải ngân mới); với HOLD vẫn giữ SL/risk visible kèm cảnh báo.
    """
    out = dict(report or {})
    gate = resolve_display_action(out)
    display = normalize_action(gate.get("display_action"))
    flags = trade_plan_visibility_flags(display)
    entry_allowed = bool(flags["entry_allowed"])
    risk_visible = bool(flags["risk_management_visible"])

    integrity_block = False
    integrity_reasons: list[str] = []
    try:
        from core.data_integrity import integrity_blocks_trade_plan

        integrity_block, integrity_reasons = integrity_blocks_trade_plan(out)
    except Exception:
        integrity_block, integrity_reasons = False, []

    if integrity_block:
        # Không cho mở mua mới khi integrity fail; HOLD vẫn xem được SL bảo vệ vị thế.
        entry_allowed = False

    show_plan = bool(entry_allowed or risk_visible)
    out["show_trade_plan"] = show_plan
    out["entry_allowed"] = bool(entry_allowed)
    out["risk_management_visible"] = bool(risk_visible)
    out["trade_plan_integrity_block"] = bool(integrity_block)
    out["trade_plan_integrity_reasons"] = list(integrity_reasons)
    out["is_conditional_buy"] = bool(gate.get("is_conditional") or display == "CONDITIONAL_BUY")

    rp = dict(out.get("risk_plan") or {}) if isinstance(out.get("risk_plan"), dict) else {}
    rp["trade_plan_active"] = show_plan
    rp["entry_allowed"] = bool(entry_allowed)
    rp["risk_management_visible"] = bool(risk_visible)

    pb = out.get("decision_playbook") if isinstance(out.get("decision_playbook"), dict) else {}
    trig = pb.get("trigger") if isinstance(pb.get("trigger"), dict) else {}
    if pb.get("size_cap_pct") is not None:
        rp["playbook_size_cap_pct"] = pb.get("size_cap_pct")
    if trig.get("invalidation_price") is not None:
        rp["invalidation_price"] = trig.get("invalidation_price")
    if trig.get("cancel_if_vi"):
        rp["cancel_if_vi"] = trig.get("cancel_if_vi")
    if trig.get("entry_hint_vi"):
        rp["entry_hint_vi"] = trig.get("entry_hint_vi")

    if not show_plan:
        if integrity_block:
            rp["display_note_vi"] = (
                "P0 integrity: không đề xuất vào lệnh ("
                + ", ".join(integrity_reasons)
                + "). Entry/SL/TP chỉ là tham chiếu nội bộ."
            )
        else:
            rp["display_note_vi"] = (
                "Khuyến nghị QUAN SÁT / TRÁNH — khóa toàn bộ kế hoạch giao dịch. "
                "Entry/SL/TP chỉ là tham chiếu nội bộ, không phải lệnh giao dịch."
            )
    elif display == "HOLD":
        note = "GIỮ: Không mở mua mới. Hiển thị SL / quản trị rủi ro để bảo vệ vị thế đang nắm."
        if integrity_block:
            note += " (Integrity cảnh báo — chỉ dùng SL tham chiếu thận trọng: " + ", ".join(integrity_reasons) + ")."
        rp["display_note_vi"] = note
        rp["entry_hint_vi"] = "Không mở mua mới"
        rp["entry_locked_reason_vi"] = "Không mở mua mới"
    elif out.get("is_conditional_buy"):
        rp["display_note_vi"] = (
            str(trig.get("entry_hint_vi") or "Mua có điều kiện — chỉ vào khi đủ trigger.")
            + " "
            + str(trig.get("cancel_if_vi") or "")
        ).strip()
    elif integrity_block and not entry_allowed:
        rp["display_note_vi"] = (
            "Integrity khóa Entry ("
            + ", ".join(integrity_reasons)
            + "). Có thể xem SL/TP tham chiếu nếu đang nắm giữ."
        )

    out["risk_plan"] = rp

    # Đồng bộ playbook flags
    if isinstance(pb, dict) and pb:
        pb2 = dict(pb)
        pb2["entry_allowed"] = bool(entry_allowed)
        pb2["risk_management_visible"] = bool(risk_visible)
        out["decision_playbook"] = pb2
    return out


def trade_plan_is_active(report: dict[str, Any] | None) -> bool:
    """True nếu có phần Trade Plan được phép hiện (entry hoặc risk management)."""
    rep = report if isinstance(report, dict) else {}
    if "risk_management_visible" in rep or "entry_allowed" in rep:
        return bool(rep.get("risk_management_visible") or rep.get("entry_allowed"))
    rp = rep.get("risk_plan") if isinstance(rep.get("risk_plan"), dict) else {}
    if "risk_management_visible" in rp or "entry_allowed" in rp:
        return bool(rp.get("risk_management_visible") or rp.get("entry_allowed"))
    if "trade_plan_active" in rp:
        return bool(rp.get("trade_plan_active"))
    if "show_trade_plan" in rep:
        return bool(rep.get("show_trade_plan"))
    return bool(resolve_display_action(rep).get("show_trade_plan"))


def trade_plan_entry_allowed(report: dict[str, Any] | None) -> bool:
    rep = report if isinstance(report, dict) else {}
    if "entry_allowed" in rep:
        return bool(rep.get("entry_allowed"))
    rp = rep.get("risk_plan") if isinstance(rep.get("risk_plan"), dict) else {}
    if "entry_allowed" in rp:
        return bool(rp.get("entry_allowed"))
    return bool(resolve_display_action(rep).get("entry_allowed"))


def trade_plan_risk_visible(report: dict[str, Any] | None) -> bool:
    rep = report if isinstance(report, dict) else {}
    if "risk_management_visible" in rep:
        return bool(rep.get("risk_management_visible"))
    rp = rep.get("risk_plan") if isinstance(rep.get("risk_plan"), dict) else {}
    if "risk_management_visible" in rp:
        return bool(rp.get("risk_management_visible"))
    return bool(resolve_display_action(rep).get("risk_management_visible"))
