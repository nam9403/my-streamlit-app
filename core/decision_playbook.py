"""
P1 decision playbook — Thesis (6–18m) / Setup (2–12w) / Trigger → action.

Turns eternal WATCH into CONDITIONAL_BUY when valuation is attractive but
timing is not ready. Hard BUY only when all three layers + regime agree.
"""

from __future__ import annotations

from typing import Any


THESIS_GRADES = ("A", "B", "C")
SETUP_STATUSES = ("ARMED", "WAIT", "ABORT")
TRIGGER_STATUSES = ("READY", "PENDING", "INVALID")
PLAYBOOK_ACTIONS = frozenset({"BUY", "CONDITIONAL_BUY", "HOLD", "WATCH", "AVOID"})


def _f(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _i(v: Any, default: int = 0) -> int:
    try:
        if v is None or v == "":
            return default
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _grade_from_score(score: float) -> str:
    if score >= 72:
        return "A"
    if score >= 48:
        return "B"
    return "C"


def evaluate_thesis(
    valuation: dict[str, Any] | None,
    financials: dict[str, Any] | None = None,
    *,
    deep_insight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    6–18 month thesis grade from valuation + earnings quality (+ bank-aware).
    """
    val = valuation if isinstance(valuation, dict) else {}
    fin = financials if isinstance(financials, dict) else {}
    deep = deep_insight if isinstance(deep_insight, dict) else {}
    reasons: list[str] = []
    score = 50.0

    mos = _f(val.get("margin_of_safety_composite_pct"), 0.0)
    fscore = _i(val.get("piotroski_score"), 0)
    legend = val.get("legend_scorecard") if isinstance(val.get("legend_scorecard"), dict) else {}
    is_bank = bool(val.get("is_bank_sector"))
    mos_blocked = bool(val.get("mos_integrity_blocked"))
    pe_anom = bool(val.get("pe_anomaly_flag") or val.get("eps_anomaly_flag"))

    if mos_blocked or pe_anom:
        score -= 28.0
        reasons.append("MOS/PE integrity block — hạ thesis.")
    elif mos >= 25:
        score += 22.0
        reasons.append(f"MOS hấp dẫn ({mos:.1f}%).")
    elif mos >= 12:
        score += 12.0
        reasons.append(f"MOS dương ({mos:.1f}%).")
    elif mos >= 0:
        score += 2.0
        reasons.append(f"MOS mỏng ({mos:.1f}%).")
    elif mos > -15:
        score -= 12.0
        reasons.append(f"MOS âm nhẹ ({mos:.1f}%).")
    else:
        score -= 28.0
        reasons.append(f"MOS âm sâu ({mos:.1f}%) — thesis yếu.")

    if legend.get("graham_pass"):
        score += 8.0
        reasons.append("Graham đạt.")
    if legend.get("buffett_pass"):
        score += 10.0
        reasons.append("Buffett đạt.")
    if legend.get("lynch_pass"):
        score += 6.0
        reasons.append("Lynch đạt.")
    if not any(legend.get(k) for k in ("graham_pass", "buffett_pass", "lynch_pass")):
        score -= 8.0
        reasons.append("Legend chưa đạt.")

    # Quality: industrial F-Score vs bank quality (already scaled 0-9 in valuation)
    if is_bank:
        if fscore >= 6:
            score += 10.0
            reasons.append(f"Bank quality score {fscore}/9.")
        elif fscore >= 3:
            score += 4.0
            reasons.append(f"Bank quality trung bình {fscore}/9.")
        else:
            score -= 6.0
            reasons.append(f"Bank quality thấp {fscore}/9.")
        # Prefer ROE for banks when available
        roe = _f(val.get("roe_5y_avg") or fin.get("roe"), 0.0)
        if roe >= 15:
            score += 6.0
            reasons.append(f"ROE ngân hàng tốt ({roe:.1f}%).")
        elif 0 < roe < 10:
            score -= 5.0
            reasons.append(f"ROE ngân hàng yếu ({roe:.1f}%).")
    else:
        if fscore >= 7:
            score += 12.0
            reasons.append(f"F-Score mạnh {fscore}/9.")
        elif fscore >= 5:
            score += 6.0
            reasons.append(f"F-Score ổn {fscore}/9.")
        elif fscore == 4 and bool(val.get("is_quality_compensated")):
            score += 6.0
            reasons.append(
                str(val.get("quality_offset_note_vi") or "F-Score 4 được bù trừ nhờ ROE cao & CFO khỏe.")
            )
        elif fscore >= 3:
            score += 1.0
        else:
            score -= 8.0
            reasons.append(f"F-Score yếu {fscore}/9.")

    eq = deep.get("earnings_quality") if isinstance(deep.get("earnings_quality"), dict) else {}
    eq_high = bool(eq.get("warning")) and str(eq.get("severity") or "").lower() == "high"
    if eq.get("warning"):
        sev = str(eq.get("severity") or "").lower()
        score -= 18.0 if sev == "high" else 10.0
        reasons.append("Cảnh báo chất lượng lợi nhuận.")

    # Wave 3: sector-relative value nudge
    srel = val.get("sector_relative") if isinstance(val.get("sector_relative"), dict) else {}
    if srel.get("ok"):
        nudge = _f(srel.get("thesis_score_nudge"), 0.0)
        score += max(-12.0, min(12.0, nudge))
        for note in list(srel.get("notes_vi") or [])[:2]:
            reasons.append(str(note))

    rev = fin.get("revenue_growth_yoy")
    if isinstance(rev, (int, float)):
        if rev >= 15:
            score += 6.0
            reasons.append(f"Rev YoY +{float(rev):.1f}%.")
        elif rev < -5:
            score -= 8.0
            reasons.append(f"Rev YoY {float(rev):.1f}%.")

    ni = fin.get("profit_growth_yoy")
    if isinstance(ni, (int, float)):
        if ni >= 15:
            score += 5.0
            reasons.append(f"LN YoY +{float(ni):.1f}%.")
        elif ni < -10:
            score -= 8.0
            reasons.append(f"LN YoY {float(ni):.1f}%.")

    conclusion = str(val.get("instant_conclusion") or "").lower()
    if conclusion == "bỏ qua":
        score -= 15.0
        reasons.append("Legend: Bỏ qua.")
    elif conclusion == "mua mạnh":
        score += 8.0
        reasons.append("Legend: Mua mạnh.")

    score = max(0.0, min(100.0, score))
    grade = _grade_from_score(score)
    # Hard ceiling when integrity blocked
    if mos_blocked and grade == "A":
        grade = "B"
        reasons.append("Ceiling thesis=B vì MOS integrity.")
    # Wave 3: EQ high → không cho thesis A
    if eq_high and grade == "A":
        grade = "B"
        reasons.append("Ceiling thesis=B vì earnings quality high.")

    attractive = grade in ("A", "B") and mos >= 8 and not (mos_blocked and mos < 12)
    # Alpha tune (hist PIT): khi có đủ Rev & LN YoY, entry chỉ attractive nếu cả hai ≥ 0
    if attractive and isinstance(rev, (int, float)) and isinstance(ni, (int, float)):
        if float(rev) < 0.0 or float(ni) < 0.0:
            attractive = False
            reasons.append("Rev&LN YoY chưa đồng thuận ≥0 — không attractive entry.")
    # Wave 3: EQ high blocks attractive entry
    if attractive and eq_high:
        attractive = False
        reasons.append("Earnings quality high — không attractive entry.")
    # Wave 3: rich vs peers blocks attractive unless MOS rất cao
    if attractive and str(srel.get("band") or "") == "rich" and mos < 20:
        attractive = False
        reasons.append("Đắt hơn peer + MOS chưa đủ cao — không attractive entry.")

    return {
        "grade": grade,
        "score": round(score, 1),
        "horizon": "6-18m",
        "is_bank": is_bank,
        "mos_pct": mos,
        "f_score": fscore,
        "sector_relative_band": srel.get("band"),
        "earnings_quality_severity": str(eq.get("severity") or "") if eq else None,
        "reasons_vi": reasons[:8],
        "attractive": attractive,
    }


def evaluate_setup(
    phase: dict[str, Any] | None,
    *,
    market_regime: dict[str, Any] | None = None,
    deep_insight: dict[str, Any] | None = None,
    ohlcv_integrity: dict[str, Any] | None = None,
    data_trust: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """2–12 week setup: ARMED / WAIT / ABORT."""
    ph = phase if isinstance(phase, dict) else {}
    metrics = ph.get("metrics") if isinstance(ph.get("metrics"), dict) else {}
    phase_name = str(ph.get("phase") or "neutral").lower()
    regime = market_regime if isinstance(market_regime, dict) else {}
    regime_label = str(regime.get("label") or "neutral")
    deep = deep_insight if isinstance(deep_insight, dict) else {}
    sm = deep.get("smart_money_flow") if isinstance(deep.get("smart_money_flow"), dict) else {}
    integrity = ohlcv_integrity if isinstance(ohlcv_integrity, dict) else {}
    trust = data_trust if isinstance(data_trust, dict) else {}
    reasons: list[str] = []

    if integrity.get("critical") or integrity.get("block_phase"):
        return {
            "status": "ABORT",
            "phase": phase_name,
            "regime": regime_label,
            "reasons_vi": ["OHLCV integrity fail — abort setup."],
        }
    if metrics.get("rsi_indicator_fail"):
        return {
            "status": "ABORT",
            "phase": phase_name,
            "regime": regime_label,
            "reasons_vi": ["RSI indicator fail — abort setup."],
        }
    if str(trust.get("band") or "").upper() == "LOW":
        reasons.append("Data trust LOW — không ARMED.")

    if phase_name == "distribution":
        status = "ABORT"
        reasons.append("Pha phân phối — abort.")
    elif phase_name in ("accumulation", "breakout"):
        status = "ARMED"
        reasons.append(f"Pha {phase_name} — setup sẵn sàng.")
    else:
        status = "WAIT"
        reasons.append("Pha trung tính — chờ trigger/vùng giá.")

    if regime_label == "risk_off":
        if status == "ARMED":
            status = "WAIT"
        reasons.append("Regime risk-off — hạ ARMED→WAIT.")
    elif regime_label == "risk_on" and status == "WAIT" and phase_name == "neutral":
        reasons.append("Regime risk-on hỗ trợ nhưng pha chưa rõ.")

    sm_bias = str(sm.get("bias") or "neutral").lower()
    if sm_bias == "bearish" and status == "ARMED":
        status = "WAIT"
        reasons.append("Smart money bearish — hạ ARMED→WAIT.")
    elif sm_bias == "bullish" and status == "WAIT" and phase_name != "distribution":
        reasons.append("Smart money nghiêng mua — hỗ trợ setup.")

    if str(trust.get("band") or "").upper() == "LOW" and status == "ARMED":
        status = "WAIT"

    vol_mult = _f(metrics.get("vol_multiple"), 1.0)
    if phase_name == "breakout" and vol_mult < 1.2:
        if status == "ARMED":
            status = "WAIT"
        reasons.append("Breakout thiếu volume xác nhận.")

    return {
        "status": status,
        "phase": phase_name,
        "regime": regime_label,
        "vol_multiple": vol_mult,
        "smart_money_bias": sm_bias,
        "reasons_vi": reasons[:8],
    }


def evaluate_trigger(
    *,
    price: float,
    risk_plan: dict[str, Any] | None = None,
    phase: dict[str, Any] | None = None,
    setup_status: str = "WAIT",
) -> dict[str, Any]:
    """
    Entry trigger: READY if price in buy zone and setup not ABORT;
    PENDING if thesis waiting for zone; INVALID if broken structure.
    """
    rp = risk_plan if isinstance(risk_plan, dict) else {}
    ph = phase if isinstance(phase, dict) else {}
    metrics = ph.get("metrics") if isinstance(ph.get("metrics"), dict) else {}
    phase_name = str(ph.get("phase") or "neutral").lower()

    zone_low = _f(rp.get("buy_zone_low"), 0.0)
    zone_high = _f(rp.get("buy_zone_high"), 0.0)
    entry = _f(rp.get("entry_price"), 0.0)
    sl = _f(rp.get("stop_loss_price"), 0.0)
    px = float(price or 0.0)

    if zone_low <= 0 and entry > 0:
        zone_low = entry * 0.97
        zone_high = entry * 1.03 if zone_high <= 0 else zone_high
    if zone_high <= 0 and zone_low > 0:
        zone_high = zone_low * 1.04
    if entry <= 0 and zone_low > 0 and zone_high > 0:
        entry = (zone_low + zone_high) / 2.0

    invalidation = sl if sl > 0 else (zone_low * 0.96 if zone_low > 0 else 0.0)
    ma50 = _f(metrics.get("ma50"), 0.0)
    if ma50 > 0 and (invalidation <= 0 or ma50 < invalidation):
        # Prefer structural invalidation under MA50 when available and below zone
        if ma50 < zone_low * 0.99:
            invalidation = ma50

    reasons: list[str] = []
    if setup_status == "ABORT" or phase_name == "distribution":
        return {
            "status": "INVALID",
            "buy_zone_low": round(zone_low, 2) if zone_low > 0 else None,
            "buy_zone_high": round(zone_high, 2) if zone_high > 0 else None,
            "entry_price": round(entry, 2) if entry > 0 else None,
            "invalidation_price": round(invalidation, 2) if invalidation > 0 else None,
            "in_buy_zone": False,
            "reasons_vi": ["Setup abort / phân phối — trigger không hợp lệ."],
            "entry_hint_vi": "Không vào lệnh.",
            "cancel_if_vi": (
                f"Hủy nếu giá mất {invalidation:,.0f}." if invalidation > 0 else "Hủy khi pha phân phối kéo dài."
            ),
        }

    in_zone = bool(px > 0 and zone_low > 0 and zone_high > 0 and zone_low <= px <= zone_high)
    below_zone = bool(px > 0 and zone_low > 0 and px < zone_low)
    above_zone = bool(px > 0 and zone_high > 0 and px > zone_high)

    if invalidation > 0 and px > 0 and px < invalidation:
        status = "INVALID"
        reasons.append("Giá đã thủng invalidation.")
        hint = "Abort — chờ cấu trúc mới."
    elif in_zone and setup_status == "ARMED":
        status = "READY"
        reasons.append("Giá trong vùng mua và setup ARMED.")
        hint = f"Được phép giải ngân trong [{zone_low:,.0f} – {zone_high:,.0f}]."
    elif in_zone and setup_status == "WAIT":
        status = "PENDING"
        reasons.append("Giá trong vùng nhưng setup còn WAIT.")
        hint = "Chờ xác nhận pha/volume trước khi mua đầy size."
    elif below_zone:
        status = "PENDING"
        reasons.append("Giá dưới vùng mua — chờ hồi hoặc hạ zone.")
        hint = f"Chờ giá vào [{zone_low:,.0f} – {zone_high:,.0f}]."
    elif above_zone:
        status = "PENDING"
        reasons.append("Giá trên vùng mua — không đuổi.")
        hint = f"Không đuổi; chờ hồi về ≤ {zone_high:,.0f}."
    else:
        status = "PENDING"
        reasons.append("Chưa đủ vùng mua rõ.")
        hint = "Thiết lập vùng mua trước khi trigger."

    cancel = (
        f"Hủy kế hoạch nếu đóng cửa dưới {invalidation:,.0f} hoặc pha chuyển sang phân phối."
        if invalidation > 0
        else "Hủy nếu xuất hiện phân phối kèm volume lớn."
    )
    return {
        "status": status,
        "buy_zone_low": round(zone_low, 2) if zone_low > 0 else None,
        "buy_zone_high": round(zone_high, 2) if zone_high > 0 else None,
        "entry_price": round(entry, 2) if entry > 0 else None,
        "invalidation_price": round(invalidation, 2) if invalidation > 0 else None,
        "in_buy_zone": in_zone,
        "reasons_vi": reasons[:6],
        "entry_hint_vi": hint,
        "cancel_if_vi": cancel,
    }


def resolve_playbook_action(
    *,
    thesis: dict[str, Any],
    setup: dict[str, Any],
    trigger: dict[str, Any],
    confidence: float,
    market_regime: dict[str, Any] | None = None,
    base_max_position_pct: float = 20.0,
) -> dict[str, Any]:
    """
    Map three layers → final recommended action + size cap.

    P1-tune (post historical eval): CONDITIONAL_BUY / BUY chỉ khi Setup ARMED
    và Trigger READY (hoặc PENDING hẹp với Thesis A). Không còn COND chỉ vì
    MOS hấp dẫn + WAIT — đó là HOLD/WATCH (tránh vào lệnh sớm, thua nhóm WATCH).
    """
    grade = str(thesis.get("grade") or "C")
    setup_st = str(setup.get("status") or "WAIT")
    trig_st = str(trigger.get("status") or "PENDING")
    regime = market_regime if isinstance(market_regime, dict) else {}
    regime_label = str(regime.get("label") or "neutral")
    size_mult = _f(regime.get("size_mult"), 0.7)
    conf = float(confidence or 0.0)
    attractive = bool(thesis.get("attractive"))
    notes: list[str] = []

    action = "WATCH"
    if grade == "C" and not attractive:
        action = "AVOID" if _f(thesis.get("mos_pct"), 0.0) < -10 else "WATCH"
        notes.append("Thesis yếu.")
    elif setup_st == "ABORT" or trig_st == "INVALID":
        action = "WATCH"
        notes.append("Setup/trigger không hợp lệ — đứng ngoài.")
    elif grade in ("A", "B") and setup_st == "ARMED" and trig_st == "READY" and conf >= 60:
        if regime_label == "risk_off":
            action = "CONDITIONAL_BUY"
            size_mult = min(size_mult, 0.35)
            notes.append("Đủ thesis/setup/trigger nhưng risk-off → CONDITIONAL_BUY size nhỏ.")
        elif regime.get("allow_hard_buy") or regime_label == "risk_on":
            action = "BUY"
            notes.append("Thesis+Setup+Trigger+risk-on → BUY.")
        else:
            if grade == "A" and conf >= 70:
                action = "BUY"
                size_mult = min(size_mult, 0.7)
                notes.append("Thesis A + conf cao trong regime trung tính → BUY size giảm.")
            else:
                action = "CONDITIONAL_BUY"
                notes.append("Regime trung tính + ARMED/READY → CONDITIONAL_BUY.")
    elif (
        grade == "A"
        and attractive
        and setup_st == "ARMED"
        and trig_st == "PENDING"
        and conf >= 65
        and _f(thesis.get("mos_pct"), 0.0) >= 12
    ):
        # Chỉ Thesis A + ARMED: chờ giá vào zone — vẫn COND, không vào sớm khi WAIT.
        action = "CONDITIONAL_BUY"
        size_mult = min(size_mult, 0.5)
        notes.append("Thesis A + Setup ARMED, trigger PENDING — CONDITIONAL_BUY (chờ zone).")
    elif grade in ("A", "B") and attractive and setup_st in ("WAIT", "ARMED"):
        action = "HOLD"
        notes.append("Định giá hấp dẫn nhưng timing chưa READY — HOLD/theo dõi, không COND sớm.")
    elif grade in ("A", "B") and _i(thesis.get("f_score"), 0) >= 4 and _f(thesis.get("mos_pct"), 0.0) >= 3:
        action = "HOLD"
        notes.append("Nắm giữ / theo dõi vị thế — chưa đủ trigger mua mới.")
    else:
        action = "WATCH"
        notes.append("Chưa đủ lớp quyết định.")

    if conf < 55 and action == "BUY":
        action = "CONDITIONAL_BUY"
        notes.append("Confidence thấp — hạ BUY→CONDITIONAL_BUY.")

    # Hist edge: không giải ngân mới khi thesis không attractive (thiếu đồng thuận growth)
    if action in ("BUY", "CONDITIONAL_BUY") and not attractive:
        action = "HOLD"
        notes.append("Hạ entry→HOLD: thesis chưa attractive (cần Rev&LN YoY đồng thuận nếu có).")

    max_pos = max(5.0, min(25.0, float(base_max_position_pct) * float(size_mult)))
    if action == "CONDITIONAL_BUY":
        max_pos = min(max_pos, 12.0)
    if action in ("WATCH", "AVOID", "HOLD"):
        # HOLD = theo dõi, không giải ngân mới trong playbook size
        max_pos = 0.0

    summary = (
        f"Thesis {grade} · Setup {setup_st} · Trigger {trig_st} · Regime {regime_label} → {action}."
    )
    return {
        "recommended_action": action,
        "size_cap_pct": round(max_pos, 2),
        "size_mult": round(float(size_mult), 3),
        "notes_vi": notes[:6],
        "summary_vi": summary,
        "entry_allowed": action in ("BUY", "CONDITIONAL_BUY"),
        "risk_management_visible": action in ("BUY", "CONDITIONAL_BUY", "HOLD"),
    }


def build_decision_playbook(
    *,
    valuation: dict[str, Any] | None,
    phase: dict[str, Any] | None,
    financials: dict[str, Any] | None = None,
    confidence: float = 0.0,
    risk_plan: dict[str, Any] | None = None,
    deep_insight: dict[str, Any] | None = None,
    market_regime: dict[str, Any] | None = None,
    data_trust: dict[str, Any] | None = None,
    ohlcv_integrity: dict[str, Any] | None = None,
    base_max_position_pct: float = 20.0,
    news: list[dict[str, Any]] | None = None,
    snapshot: dict[str, Any] | None = None,
    as_of: Any = None,
) -> dict[str, Any]:
    """Full P1 playbook payload for report / UI / gates."""
    val = dict(valuation or {}) if isinstance(valuation, dict) else {}
    # Wave 3: attach sector-relative when missing (live cache peers)
    if not isinstance(val.get("sector_relative"), dict) or not val["sector_relative"].get("ok"):
        try:
            from core.sector_relative import attach_sector_relative_to_valuation

            sym = str(val.get("symbol") or (financials or {}).get("symbol") or "")
            val = attach_sector_relative_to_valuation(
                val, symbol=sym, financials=financials, snapshot=snapshot
            )
        except Exception:
            pass
    thesis = evaluate_thesis(val, financials, deep_insight=deep_insight)
    setup = evaluate_setup(
        phase,
        market_regime=market_regime,
        deep_insight=deep_insight,
        ohlcv_integrity=ohlcv_integrity,
        data_trust=data_trust,
    )
    price = _f(val.get("price"), 0.0)
    trigger = evaluate_trigger(
        price=price,
        risk_plan=risk_plan,
        phase=phase,
        setup_status=str(setup.get("status") or "WAIT"),
    )
    resolved = resolve_playbook_action(
        thesis=thesis,
        setup=setup,
        trigger=trigger,
        confidence=confidence,
        market_regime=market_regime,
        base_max_position_pct=base_max_position_pct,
    )
    action = str(resolved.get("recommended_action") or "WATCH")
    notes = list(resolved.get("notes_vi") or [])
    event_bo: dict[str, Any] = {}
    try:
        from core.event_calendar_gate import apply_event_blackout_to_action, assess_event_blackout

        event_bo = assess_event_blackout(
            as_of=as_of,
            news=news,
            snapshot=snapshot if isinstance(snapshot, dict) else None,
            financials=financials if isinstance(financials, dict) else None,
        )
        action, bo_notes = apply_event_blackout_to_action(action, event_bo)
        notes.extend(bo_notes)
        if action == "HOLD" and float(resolved.get("size_cap_pct") or 0) > 0 and str(event_bo.get("severity") or "") == "high":
            resolved = dict(resolved)
            resolved["size_cap_pct"] = 0.0
            resolved["recommended_action"] = "HOLD"
    except Exception:
        event_bo = {"blackout": False}
    size_cap = resolved.get("size_cap_pct")
    if action in ("WATCH", "AVOID", "HOLD"):
        size_cap = 0.0
    elif action == "CONDITIONAL_BUY":
        try:
            size_cap = min(float(size_cap or 12.0), 12.0)
        except (TypeError, ValueError):
            size_cap = 12.0
    return {
        "schema_version": 1,
        "thesis": thesis,
        "setup": setup,
        "trigger": trigger,
        "regime": {
            "label": (market_regime or {}).get("label") if isinstance(market_regime, dict) else "neutral",
            "score": (market_regime or {}).get("score") if isinstance(market_regime, dict) else None,
            "note_vi": (market_regime or {}).get("note_vi") if isinstance(market_regime, dict) else "",
            "allow_hard_buy": bool((market_regime or {}).get("allow_hard_buy"))
            if isinstance(market_regime, dict)
            else False,
        },
        "event_blackout": event_bo,
        "recommended_action": action,
        "size_cap_pct": size_cap,
        "size_mult": resolved.get("size_mult"),
        "notes_vi": notes,
        "summary_vi": str(resolved.get("summary_vi") or ""),
        "user_instruction_vi": _user_instruction(action, thesis, setup, trigger),
        "entry_allowed": bool(resolved.get("entry_allowed", action in ("BUY", "CONDITIONAL_BUY"))),
        "risk_management_visible": bool(
            resolved.get("risk_management_visible", action in ("BUY", "CONDITIONAL_BUY", "HOLD"))
        ),
    }


def _user_instruction(
    action: str,
    thesis: dict[str, Any],
    setup: dict[str, Any],
    trigger: dict[str, Any],
) -> str:
    act = str(action or "WATCH").upper()
    if act == "BUY":
        return (
            f"MUA trong vùng {trigger.get('buy_zone_low')}–{trigger.get('buy_zone_high')}. "
            f"{trigger.get('cancel_if_vi') or ''}"
        ).strip()
    if act == "CONDITIONAL_BUY":
        return (
            f"MUA CÓ ĐIỀU KIỆN: {trigger.get('entry_hint_vi') or 'chờ vùng/pha'}. "
            f"{trigger.get('cancel_if_vi') or ''} "
            f"(Thesis {thesis.get('grade')}, Setup {setup.get('status')})."
        ).strip()
    if act == "HOLD":
        return (
            "GIỮ vị thế hiện có — Không mở mua mới. "
            "Theo dõi SL / trailing stop và vùng quản trị rủi ro để bảo vệ vị thế."
        )
    if act == "AVOID":
        return "TRÁNH — thesis yếu hoặc rủi ro cấu trúc; không giải ngân."
    return (
        f"QUAN SÁT — Thesis {thesis.get('grade')}, Setup {setup.get('status')}, "
        f"Trigger {trigger.get('status')}."
    )


def why_not_buy_summary(
    *,
    action: str,
    thesis: dict[str, Any] | None = None,
    setup: dict[str, Any] | None = None,
    trigger: dict[str, Any] | None = None,
    event_blackout: dict[str, Any] | None = None,
    peer_band: str = "",
) -> str:
    """Wave 5 — compact reason string for board/digest when action is not BUY."""
    act = str(action or "WATCH").upper()
    if act == "BUY":
        return ""
    th = thesis if isinstance(thesis, dict) else {}
    su = setup if isinstance(setup, dict) else {}
    tr = trigger if isinstance(trigger, dict) else {}
    bo = event_blackout if isinstance(event_blackout, dict) else {}
    bits: list[str] = []
    if act == "AVOID":
        bits.append("AVOID")
    if th.get("attractive") is False:
        bits.append("thesis chưa attractive")
    if str(th.get("grade") or "") == "C":
        bits.append("thesis C")
    setup_st = str(su.get("status") or "")
    if setup_st in ("WAIT", "ABORT"):
        bits.append(f"setup {setup_st}")
    trig_st = str(tr.get("status") or "")
    if trig_st in ("PENDING", "INVALID"):
        bits.append(f"trigger {trig_st}")
    if bo.get("blackout"):
        bits.append("event blackout")
    if str(peer_band or th.get("sector_relative_band") or "").lower() == "rich":
        bits.append("đắt hơn peer")
    if act == "CONDITIONAL_BUY":
        bits.append("chờ điều kiện")
    if act == "HOLD" and not bits:
        bits.append("giữ/theo dõi")
    if act == "WATCH" and not bits:
        bits.append("chưa đủ T/S/Tr")
    seen: set[str] = set()
    out: list[str] = []
    for b in bits:
        if b not in seen:
            seen.add(b)
            out.append(b)
    return " · ".join(out[:5])


def compact_playbook_fields(report: dict[str, Any] | None) -> dict[str, Any]:
    """
    Flatten decision_playbook onto scanner/board/digest rows (P2).

    Safe for JSON board persistence — no nested objects required by digest.
    """
    rep = report if isinstance(report, dict) else {}
    pb = rep.get("decision_playbook") if isinstance(rep.get("decision_playbook"), dict) else {}
    if not pb:
        return {}
    thesis = pb.get("thesis") if isinstance(pb.get("thesis"), dict) else {}
    setup = pb.get("setup") if isinstance(pb.get("setup"), dict) else {}
    trigger = pb.get("trigger") if isinstance(pb.get("trigger"), dict) else {}
    regime = pb.get("regime") if isinstance(pb.get("regime"), dict) else {}
    summary = str(pb.get("user_instruction_vi") or pb.get("summary_vi") or "").strip()
    if len(summary) > 140:
        summary = summary[:137] + "…"
    action = str(pb.get("recommended_action") or rep.get("final_action") or "").upper()
    why = why_not_buy_summary(
        action=action,
        thesis=thesis,
        setup=setup,
        trigger=trigger,
        event_blackout=pb.get("event_blackout") if isinstance(pb.get("event_blackout"), dict) else {},
        peer_band=str(thesis.get("sector_relative_band") or ""),
    )
    out: dict[str, Any] = {
        "Thesis": str(thesis.get("grade") or ""),
        "Setup": str(setup.get("status") or ""),
        "Trigger": str(trigger.get("status") or ""),
        "Regime": str(regime.get("label") or ""),
        "Playbook": summary,
        "attractive": bool(thesis.get("attractive")) if "attractive" in thesis else None,
        "PeerBand": str(thesis.get("sector_relative_band") or ""),
        "EQ": str(thesis.get("earnings_quality_severity") or ""),
        "EventBlackout": bool((pb.get("event_blackout") or {}).get("blackout")),
        "Why not BUY": why[:120] if why else "",
        "Entry hint": str(trigger.get("entry_hint_vi") or "")[:120],
        "Cancel if": str(trigger.get("cancel_if_vi") or "")[:120],
        "Invalidation": trigger.get("invalidation_price"),
        "Size cap %": pb.get("size_cap_pct"),
    }
    # Drop empties for compact board JSON
    return {k: v for k, v in out.items() if v not in (None, "", [])}


def apply_playbook_to_action(
    base_action: str,
    playbook: dict[str, Any] | None,
    *,
    prefer_playbook: bool = True,
) -> str:
    """
    Merge legacy _final_action with playbook recommendation.

    Prefer playbook when it upgrades WATCH→CONDITIONAL_BUY or upgrades to BUY
    with full layers; never upgrade AVOID→BUY blindly.
    """
    base = str(base_action or "WATCH").upper()
    pb = playbook if isinstance(playbook, dict) else {}
    rec = str(pb.get("recommended_action") or "").upper()
    if not prefer_playbook or rec not in PLAYBOOK_ACTIONS:
        return base if base in PLAYBOOK_ACTIONS else "WATCH"

    # Integrity / weak thesis: playbook AVOID wins over optimistic base
    if rec == "AVOID":
        return "AVOID"
    if base == "AVOID" and rec in ("WATCH", "CONDITIONAL_BUY", "HOLD"):
        return rec if rec != "CONDITIONAL_BUY" else "WATCH"
    if base == "AVOID":
        return "AVOID"

    # Playbook CONDITIONAL_BUY is the main unlock vs eternal WATCH
    if rec == "CONDITIONAL_BUY" and base in ("WATCH", "HOLD", "CONDITIONAL_BUY"):
        return "CONDITIONAL_BUY"
    if rec == "BUY" and base in ("BUY", "HOLD", "WATCH", "CONDITIONAL_BUY"):
        return "BUY"
    if rec == "HOLD" and base in ("WATCH", "HOLD"):
        return "HOLD"
    if rec == "WATCH":
        # Don't downgrade a hard BUY from legacy unless setup abort
        setup = pb.get("setup") if isinstance(pb.get("setup"), dict) else {}
        if base == "BUY" and str(setup.get("status")) == "ABORT":
            return "WATCH"
        if base == "BUY":
            return "BUY"
        return "WATCH"
    return rec
