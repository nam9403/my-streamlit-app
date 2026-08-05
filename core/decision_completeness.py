"""
Decision completeness gate (P1): thiếu CFO/NI/ROE → không “Mua mạnh” giả, hạ readiness.
Bank-aware: không phạt D/E, CR, CFO kiểu công nghiệp cho ngân hàng.
"""

from __future__ import annotations

from typing import Any


def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _is_bank(snapshot: dict[str, Any] | None, valuation: dict[str, Any] | None = None) -> bool:
    snap = snapshot if isinstance(snapshot, dict) else {}
    val = valuation if isinstance(valuation, dict) else {}
    if bool(val.get("is_bank_sector")) or bool(snap.get("is_bank")):
        return True
    ind = str(val.get("industry_display_vi") or snap.get("industry") or "").lower()
    return "ngân hàng" in ind or "bank" in ind


def assess_decision_completeness(
    snapshot: dict[str, Any] | None,
    valuation: dict[str, Any] | None = None,
    financials: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snap = snapshot if isinstance(snapshot, dict) else {}
    val = valuation if isinstance(valuation, dict) else {}
    fin = financials if isinstance(financials, dict) else {}
    bank = _is_bank(snap, val)

    price = _num(snap.get("price") or val.get("price"))
    eps = _num(snap.get("eps") or val.get("eps") or val.get("eps_for_graham"))
    roe = _num(snap.get("roe") or val.get("roe_5y_avg") or fin.get("roe"))
    ni = _num(snap.get("net_income") or fin.get("net_income"))
    if ni is None and isinstance(snap.get("piotroski"), dict):
        ni = _num(snap["piotroski"].get("net_income"))
    cfo_raw = snap.get("operating_cash_flow")
    if cfo_raw is None:
        cfo_raw = fin.get("operating_cash_flow")
    if cfo_raw is None and isinstance(snap.get("piotroski"), dict):
        cfo_raw = snap["piotroski"].get("operating_cash_flow")
    # Distinguish missing vs real zero: None/"" = missing; 0 is present.
    cfo_missing = cfo_raw is None or cfo_raw == ""
    pe = _num(snap.get("pe_ratio") or val.get("pe_current") or fin.get("pe_ratio"))

    missing: list[str] = []
    if price is None or price <= 0:
        missing.append("price")
    if eps is None or eps == 0:
        missing.append("eps")
    if roe is None:
        missing.append("roe")
    if ni is None:
        missing.append("net_income")
    if (not bank) and cfo_missing:
        missing.append("cfo")
    if (not bank) and pe is None:
        missing.append("pe")

    # Critical gaps that must soften strong-buy / cap readiness.
    critical = [m for m in missing if m in ("price", "eps", "roe", "net_income", "cfo")]
    severity = "high" if ("price" in critical or "eps" in critical) else ("medium" if critical else "low")

    readiness_cap = None
    if severity == "high":
        readiness_cap = "LOW"
    elif severity == "medium":
        readiness_cap = "MEDIUM"

    instant = str(val.get("instant_conclusion") or "").strip()
    soften_legend = bool(critical) and instant == "Mua mạnh"

    notes: list[str] = []
    if soften_legend:
        notes.append(
            "Thiếu dữ liệu nền ( "
            + ", ".join(critical)
            + " ) — hạ Legend 'Mua mạnh' → 'Theo dõi' để tránh tín hiệu giả."
        )
    if bank and cfo_missing:
        notes.append("Ngân hàng: CFO/CR kiểu công nghiệp không bắt buộc.")
    elif (not bank) and cfo_missing:
        notes.append(
            "Thiếu CFO — chạy `python scripts/refresh_financial_indicators.py --symbols <MÃ> --force` "
            "(ưu tiên vnstock cash_flow) hoặc bật II_CFO_BACKFILL=1."
        )

    return {
        "is_bank": bank,
        "missing_items": missing,
        "critical_missing": critical,
        "severity": severity,
        "readiness_cap": readiness_cap,
        "soften_legend": soften_legend,
        "notes": notes,
        "completeness_score": max(0, 100 - 18 * len(critical) - 8 * (len(missing) - len(critical))),
    }


def apply_completeness_to_valuation(snapshot: dict[str, Any], valuation: dict[str, Any]) -> dict[str, Any]:
    """Mutate-safe: return valuation copy with softened Legend when data thin."""
    out = dict(valuation or {})
    gate = assess_decision_completeness(snapshot, out)
    out["decision_completeness"] = gate
    out["missing_items"] = list(gate.get("missing_items") or [])
    if gate.get("soften_legend"):
        out["instant_conclusion"] = "Theo dõi"
        prev = str(out.get("advice") or "")
        note = "; ".join(gate.get("notes") or [])
        out["advice"] = (prev + (" " if prev else "") + note).strip()
        out["legend_softened_by_completeness"] = True
    return out


def apply_completeness_to_report(report: dict[str, Any], snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    """Attach completeness + cap decision_readiness; never upgrade readiness."""
    out = dict(report or {})
    val = out.get("valuation") if isinstance(out.get("valuation"), dict) else {}
    fin = out.get("financials") if isinstance(out.get("financials"), dict) else {}
    snap = snapshot if isinstance(snapshot, dict) else {}
    if not snap and val:
        snap = {"price": val.get("price"), "eps": val.get("eps"), "roe": val.get("roe_5y_avg"), "is_bank": val.get("is_bank_sector")}
    gate = assess_decision_completeness(snap, val, fin)
    out["decision_completeness"] = gate
    out["missing_items"] = list(gate.get("missing_items") or [])
    cap = str(gate.get("readiness_cap") or "").upper()
    cur = str(out.get("decision_readiness") or "LOW").upper()
    order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    if cap and order.get(cap, 0) < order.get(cur, 0):
        out["decision_readiness"] = cap
        out["decision_readiness_capped_by_completeness"] = True
    # Never allow BUY when high-severity gaps
    if gate.get("severity") == "high" and str(out.get("final_action") or "").upper() == "BUY":
        out["final_action"] = "WATCH"
        out["signal_conflict_warning"] = (
            str(out.get("signal_conflict_warning") or "")
            + (" " if out.get("signal_conflict_warning") else "")
            + "Thiếu dữ liệu then chốt — không BUY."
        ).strip()
    return out


def cap_readiness_label(current: str, cap: str | None) -> str:
    cur = str(current or "LOW").upper()
    if not cap:
        return cur
    order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    c = str(cap).upper()
    if order.get(c, 0) < order.get(cur, 0):
        return c
    return cur
