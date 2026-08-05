"""
Composite data trust score (0–100) cho snapshot + BCTC + OHLCV — P0 data quality surface.
"""

from __future__ import annotations

from typing import Any


def _f(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _bool_stale(trust: dict[str, Any] | None) -> bool:
    if not isinstance(trust, dict):
        return False
    return bool(trust.get("is_stale"))


def _age_penalty(trust: dict[str, Any] | None, *, stale_penalty: float = 18.0) -> float:
    if not isinstance(trust, dict):
        return 8.0
    if _bool_stale(trust):
        return stale_penalty
    age = trust.get("age_sec")
    if isinstance(age, (int, float)):
        if age > 7200:
            return 12.0
        if age > 3600:
            return 6.0
    return 0.0


def compute_data_trust_score(
    *,
    snapshot: dict[str, Any] | None = None,
    financials: dict[str, Any] | None = None,
    valuation: dict[str, Any] | None = None,
    ohlcv_trust: dict[str, Any] | None = None,
    fin_trust: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Điểm tin cậy dữ liệu 0–100 + breakdown + ghi chú tiếng Việt.

    Không thay thế data_reliability_score trong ai_logic — bổ sung lớp “data hygiene”.
    """
    snap = snapshot if isinstance(snapshot, dict) else {}
    fin = financials if isinstance(financials, dict) else {}
    val = valuation if isinstance(valuation, dict) else {}

    score = 100.0
    breakdown: dict[str, float] = {}
    notes: list[str] = []

    price = _f(snap.get("price"))
    if price is None or price <= 0:
        score -= 25.0
        breakdown["price_missing"] = -25.0
        notes.append("Thiếu giá quote hợp lệ.")
    else:
        breakdown["price_ok"] = 0.0

    eps = _f(snap.get("eps"))
    if eps is None or eps <= 0:
        score -= 8.0
        breakdown["eps_missing"] = -8.0
        notes.append("Thiếu EPS.")
    elif snap.get("eps_normalized"):
        breakdown["eps_normalized"] = 0.0
        notes.append("EPS đã chuẩn hóa đơn vị VND/cp.")

    pe_notes = val.get("pe_sanity_notes") or snap.get("pe_sanity_notes") or []
    if isinstance(pe_notes, list) and pe_notes:
        score -= 15.0
        breakdown["pe_sanity"] = -15.0
        notes.append(str(pe_notes[0]))

    pe_anomaly = bool(val.get("pe_anomaly_flag") or snap.get("pe_anomaly_flag"))
    eps_anomaly = bool(val.get("eps_anomaly_flag") or snap.get("eps_anomaly_flag"))
    if pe_anomaly or eps_anomaly:
        score -= 18.0
        breakdown["pe_eps_anomaly"] = -18.0
        notes.append(
            str(val.get("eps_pe_anomaly_warning_vi") or snap.get("eps_pe_anomaly_warning_vi") or "")
            or "P/E/EPS anomaly — lợi nhuận đột biến; MOS đã siết thận trọng."
        )

    cross = str(snap.get("price_crosscheck_note_vi") or "").strip()
    if cross:
        xmeta = snap.get("price_crosscheck") if isinstance(snap.get("price_crosscheck"), dict) else {}
        # Hard desync (≥8%) penalizes more than soft (≥3%).
        if xmeta.get("hard_desync") or "chặn kế hoạch" in cross.lower():
            score -= 18.0
            breakdown["price_ohlcv_desync"] = -18.0
            notes.append("Quote lệch OHLCV nghiêm trọng (≥8%) — chặn trade plan.")
        else:
            score -= 12.0
            breakdown["price_ohlcv_desync"] = -12.0
            notes.append("Quote lệch OHLCV ≥3%.")

    ohlcv_integrity = snap.get("ohlcv_integrity") if isinstance(snap.get("ohlcv_integrity"), dict) else {}
    if not ohlcv_integrity and isinstance(val.get("phase_metrics"), dict):
        raw_i = val["phase_metrics"].get("ohlcv_integrity")
        if isinstance(raw_i, dict):
            ohlcv_integrity = raw_i
    if ohlcv_integrity.get("critical") or ohlcv_integrity.get("block_forecast_mc"):
        score -= 22.0
        breakdown["ohlcv_integrity"] = -22.0
        notes.append(str(ohlcv_integrity.get("note_vi") or "OHLCV integrity fail."))

    if snap.get("mos_integrity_blocked") or val.get("mos_integrity_blocked"):
        score -= 14.0
        breakdown["mos_integrity"] = -14.0
        notes.append(str(val.get("mos_integrity_note_vi") or snap.get("mos_integrity_note_vi") or "MOS bị chặn do sanity."))

    ohlcv_pen = _age_penalty(ohlcv_trust)
    if ohlcv_pen:
        score -= ohlcv_pen
        breakdown["ohlcv_freshness"] = -ohlcv_pen
        notes.append("OHLCV cache stale hoặc cũ.")

    fin_pen = _age_penalty(fin_trust)
    if fin_pen:
        score -= fin_pen
        breakdown["financial_freshness"] = -fin_pen
        notes.append("Financial indicators stale hoặc cũ.")

    fin_src = str(fin.get("source") or "").lower()
    if fin_src.startswith("unavailable") or not fin:
        score -= 20.0
        breakdown["financial_missing"] = -20.0
        notes.append("Chưa có financial indicators cache.")
    else:
        q = int(float(fin.get("data_quality_score") or 0))
        if q < 3:
            score -= 10.0
            breakdown["financial_thin"] = -10.0
            notes.append(f"Financial mỏng (quality={q}/8).")

    for key, label in (
        ("operating_cash_flow", "CFO"),
        ("debt_to_equity", "D/E"),
        ("revenue_growth_yoy", "Rev YoY"),
    ):
        if fin.get(key) is None and snap.get(key) is None:
            score -= 5.0
            breakdown[f"missing_{key}"] = breakdown.get(f"missing_{key}", 0.0) - 5.0
            notes.append(f"Thiếu {label}.")

    rsi_anom = snap.get("rsi_anomaly")
    rsi_fail = snap.get("rsi_indicator_fail")
    phase_metrics = val.get("phase_metrics") if isinstance(val.get("phase_metrics"), dict) else {}
    if rsi_fail or phase_metrics.get("rsi_indicator_fail"):
        score -= 15.0
        breakdown["rsi_indicator_fail"] = -15.0
        notes.append("RSI indicator fail (cực trị ≈0/100).")
    elif rsi_anom in (1, 1.0, True) or phase_metrics.get("rsi_anomaly"):
        score -= 8.0
        breakdown["rsi_anomaly"] = -8.0
        notes.append("RSI lệch pha xu hướng (rsi_anomaly).")

    gate = snap.get("decision_completeness") or val.get("decision_completeness")
    if isinstance(gate, dict):
        crit = gate.get("critical_missing") or []
        if crit:
            pen = min(20.0, 6.0 * len(crit))
            score -= pen
            breakdown["completeness"] = -pen
            notes.append("Thiếu dữ liệu then chốt: " + ", ".join(str(x) for x in crit))

    score = max(0.0, min(100.0, round(score, 1)))
    if score >= 80:
        band = "HIGH"
        label_vi = "Tin cậy cao"
    elif score >= 55:
        band = "MEDIUM"
        label_vi = "Tin cậy trung bình"
    else:
        band = "LOW"
        label_vi = "Tin cậy thấp — xác minh BCTC trước khi giải ngân"

    return {
        "score": score,
        "band": band,
        "label_vi": label_vi,
        "breakdown": breakdown,
        "notes_vi": notes[:8],
    }
