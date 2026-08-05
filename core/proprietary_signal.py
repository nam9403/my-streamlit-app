"""
Proprietary blend signal (P3): flow + valuation + phase with walk-forward reliability.

Used for Autopilot ranking and report attachment — not a profit guarantee.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(v)))


def _phase_score(phase: str) -> float:
    ph = str(phase or "neutral").lower()
    return {
        "breakout": 88.0,
        "accumulation": 78.0,
        "neutral": 52.0,
        "distribution": 22.0,
    }.get(ph, 50.0)


def _valuation_score(valuation: dict[str, Any] | None) -> float:
    val = valuation if isinstance(valuation, dict) else {}
    mos = float(val.get("margin_of_safety_composite_pct") or 0.0)
    fscore = int(val.get("piotroski_score") or 0)
    legend = str(val.get("instant_conclusion") or "").lower()
    score = _clamp(mos * 1.2 + fscore * 6.0)
    if legend == "mua mạnh":
        score += 8.0
    elif legend == "bỏ qua":
        score -= 12.0
    return _clamp(score)


def _flow_score(report: dict[str, Any] | None) -> float:
    rep = report if isinstance(report, dict) else {}
    deep = rep.get("deep_insight") if isinstance(rep.get("deep_insight"), dict) else {}
    sm = deep.get("smart_money_flow") if isinstance(deep.get("smart_money_flow"), dict) else {}
    bias = str(sm.get("bias") or "neutral").lower()
    sm_score = float(sm.get("score") or 0.0)
    phase = rep.get("phase") if isinstance(rep.get("phase"), dict) else {}
    metrics = phase.get("metrics") if isinstance(phase.get("metrics"), dict) else {}
    vol_mult = float(metrics.get("vol_multiple") or 1.0)
    base = 50.0 + sm_score * 25.0
    if bias == "bullish":
        base += 12.0
    elif bias == "bearish":
        base -= 15.0
    if vol_mult >= 1.3:
        base += 6.0
    elif vol_mult < 0.8:
        base -= 5.0
    conf = float(rep.get("confidence_score") or 0.0)
    base += (conf - 50.0) * 0.2
    return _clamp(base)


def walkforward_reliability(ohlcv: pd.DataFrame | None, *, symbol: str | None = None) -> float:
    """
    Prefer full opportunity_finder WF (needs ~180 bars). If short window, try
    ohlcv_store backfill then a light 3-segment proxy on available history.
    """
    df = ohlcv
    if (df is None or getattr(df, "empty", True) or len(df) < 180) and symbol:
        try:
            from core.ohlcv_store import load_recent_ohlcv

            stored = load_recent_ohlcv(str(symbol).upper(), sessions=260)
            if stored is not None and not stored.empty and len(stored) > (0 if df is None else len(df)):
                df = stored
        except Exception:
            pass
    if df is None or getattr(df, "empty", True):
        return 0.0
    try:
        from core.opportunity_finder import _walkforward_reliability_3m

        full = float(_walkforward_reliability_3m(df))
        if full > 0:
            return full
    except Exception:
        pass
    # Light proxy when history is thin (<180 bars).
    try:
        d = df.copy()
        d["close"] = pd.to_numeric(d["close"], errors="coerce")
        d = d.dropna(subset=["close"])
        if len(d) < 60:
            return 0.0
        close = d["close"]
        n = len(close)
        segs = [
            close.iloc[max(0, n - 40) : n],
            close.iloc[max(0, n - 80) : max(0, n - 40)],
            close.iloc[max(0, n - 120) : max(0, n - 80)],
        ]
        rets = []
        for s in segs:
            if len(s) < 10:
                continue
            a, b = float(s.iloc[0]), float(s.iloc[-1])
            if a > 0:
                rets.append((b / a - 1.0) * 100.0)
        if not rets:
            return 0.0
        avg = sum(rets) / len(rets)
        var = sum((x - avg) ** 2 for x in rets) / len(rets)
        # Map mild consistency → 0..70 (capped below full WF)
        score = max(0.0, min(70.0, 45.0 + avg * 0.4 - (var ** 0.5) * 0.5))
        return float(round(score, 2))
    except Exception:
        return 0.0


def _playbook_action_nudge(report: dict[str, Any]) -> tuple[float, list[str]]:
    """P3: align blend with P1 playbook / gate action."""
    notes: list[str] = []
    nudge = 0.0
    action = str(report.get("final_action") or "").upper()
    pb = report.get("decision_playbook") if isinstance(report.get("decision_playbook"), dict) else {}
    if not action and pb:
        action = str(pb.get("recommended_action") or "").upper()
    setup = pb.get("setup") if isinstance(pb.get("setup"), dict) else {}
    thesis = pb.get("thesis") if isinstance(pb.get("thesis"), dict) else {}
    setup_st = str(setup.get("status") or "")
    if action == "BUY":
        nudge += 8.0
        notes.append("Playbook/gate BUY — tăng blend.")
    elif action == "CONDITIONAL_BUY":
        nudge += 5.0
        notes.append("Playbook CONDITIONAL_BUY — tăng blend nhẹ.")
    elif action == "AVOID":
        nudge -= 12.0
        notes.append("Playbook/gate AVOID — giảm blend.")
    if setup_st == "ABORT":
        nudge -= 10.0
        notes.append("Setup ABORT — giảm blend.")
    elif setup_st == "ARMED" and str(thesis.get("grade") or "") in ("A", "B"):
        nudge += 3.0
    return nudge, notes


def _flow_reliability_weight(report: dict[str, Any] | None) -> tuple[float, str]:
    """
    Wave 3: flow weight chỉ cao khi smart-money reliability đủ.
    Returns (flow_weight 0.10–0.35, reliability band).
    """
    rep = report if isinstance(report, dict) else {}
    deep = rep.get("deep_insight") if isinstance(rep.get("deep_insight"), dict) else {}
    sm = deep.get("smart_money_flow") if isinstance(deep.get("smart_money_flow"), dict) else {}
    avg_conf = float(sm.get("avg_event_confidence") or 0.0)
    structured_n = int(sm.get("structured_event_count") or 0)
    # Prefer explicit reliability if present
    rel = str(rep.get("smart_money_reliability") or "").upper()
    if not rel:
        if structured_n >= 5 and avg_conf >= 0.75:
            rel = "HIGH"
        elif structured_n >= 2 and avg_conf >= 0.55:
            rel = "MEDIUM"
        else:
            rel = "LOW"
    if rel == "HIGH":
        return 0.30, rel
    if rel == "MEDIUM":
        return 0.20, rel
    return 0.12, rel


def compute_blend_signal(
    report: dict[str, Any] | None,
    *,
    ohlcv: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """
    Blend flow (smart money + vol) + valuation (MOS/F-Score) + phase timing.
    WF reliability down-weights unstable names. Playbook action nudges score (P3).
    Wave 3: flow weight capped by smart-money reliability.
    """
    rep = report if isinstance(report, dict) else {}
    val = rep.get("valuation") if isinstance(rep.get("valuation"), dict) else {}
    phase = rep.get("phase") if isinstance(rep.get("phase"), dict) else {}
    ph = str(phase.get("phase") or "neutral")
    sym = str(rep.get("ticker") or rep.get("symbol") or "").upper() or None

    flow = _flow_score(rep)
    valuation = _valuation_score(val)
    timing = _phase_score(ph)
    wf = walkforward_reliability(ohlcv, symbol=sym)
    nudge, nudge_notes = _playbook_action_nudge(rep)
    flow_w, flow_rel = _flow_reliability_weight(rep)
    # Keep valuation+timing share of remaining mass (0.75/0.60 historically ~ val:timing = 40:25)
    rem = max(0.05, 1.0 - flow_w)
    val_w = rem * (0.40 / 0.65)
    time_w = rem * (0.25 / 0.65)

    raw = flow * flow_w + valuation * val_w + timing * time_w + nudge
    wf_factor = 0.55 + 0.45 * (wf / 100.0) if wf > 0 else 0.75
    blend = _clamp(raw * wf_factor)

    band = "HIGH" if blend >= 70 and wf >= 45 else ("MEDIUM" if blend >= 52 else "LOW")
    notes: list[str] = list(nudge_notes)
    notes.append(f"Flow weight={flow_w:.2f} (SM {flow_rel}).")
    if flow_rel == "LOW":
        notes.append("Smart-money reliability thấp — giảm trọng số flow.")
    if wf < 35 and wf > 0:
        notes.append("WF reliability thấp — giảm trọng số blend.")
    if wf <= 0:
        notes.append("Chưa đủ lịch sử OHLCV cho WF đầy đủ — dùng hệ số thận trọng.")
    if ph == "distribution":
        notes.append("Pha phân phối — ưu tiên thận trọng dù MOS cao.")

    return {
        "flow_score": round(flow, 2),
        "valuation_score": round(valuation, 2),
        "phase_score": round(timing, 2),
        "flow_weight": round(flow_w, 3),
        "valuation_weight": round(val_w, 3),
        "timing_weight": round(time_w, 3),
        "smart_money_reliability": flow_rel,
        "walkforward_reliability_pct": round(wf, 2),
        "playbook_nudge": round(nudge, 2),
        "blend_score": round(blend, 2),
        "blend_band": band,
        "phase": ph,
        "notes_vi": notes[:8],
    }


def proprietary_score_from_row(row: dict[str, Any] | None) -> float:
    """Lightweight score bump for board rows (may include precomputed blend)."""
    r = row if isinstance(row, dict) else {}
    if r.get("Proprietary Score") is not None:
        try:
            return float(r["Proprietary Score"])
        except (TypeError, ValueError):
            pass
    sig = r.get("proprietary_signal") if isinstance(r.get("proprietary_signal"), dict) else {}
    if sig.get("blend_score") is not None:
        return float(sig["blend_score"])
    mos = float(r.get("MOS%") or 0.0)
    exp = float(r.get("Expected Return %") or 0.0)
    ph = str(r.get("Pha") or "neutral").lower()
    ph_bonus = {"breakout": 8, "accumulation": 5, "distribution": -10}.get(ph, 0)
    action = str(r.get("Khuyến nghị") or r.get("gate_action") or "").upper()
    act_bonus = {"BUY": 8, "CONDITIONAL_BUY": 5, "HOLD": 2, "AVOID": -8}.get(action, 0)
    return _clamp(mos * 0.4 + exp * 0.3 + ph_bonus + act_bonus + 20.0)
