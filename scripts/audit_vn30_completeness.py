"""
Audit VN30 decision completeness (missing_items) — P1 done-when metric.

  python scripts/audit_vn30_completeness.py
  python scripts/audit_vn30_completeness.py --quick
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import env_bootstrap  # noqa: F401
except Exception:
    pass


def _audit_symbol(sym: str, *, quick: bool) -> dict:
    from core.analysis_runtime_service import _snapshot_impl, _strategic_report_impl
    from core.decision_completeness import assess_decision_completeness

    snap = _snapshot_impl(sym)
    if snap is None:
        return {"symbol": sym, "ok": False, "reason": "no_snapshot", "missing_items": ["price"]}
    try:
        rep = _strategic_report_impl(sym, snap, "growth", 100_000_000.0, quick_mode=quick, llm_live=False)
    except Exception as exc:
        return {"symbol": sym, "ok": False, "reason": exc.__class__.__name__, "missing_items": []}
    val = rep.get("valuation") or {}
    fin = rep.get("financials") or {}
    gate = assess_decision_completeness(snap, val, fin)
    missing = list(gate.get("missing_items") or [])
    return {
        "symbol": sym,
        "ok": True,
        "missing_items": missing,
        "missing_count": len(missing),
        "severity": gate.get("severity"),
        "completeness_score": gate.get("completeness_score"),
        "is_bank": gate.get("is_bank"),
        "decision_readiness": rep.get("decision_readiness"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit VN30 completeness (missing_items).")
    ap.add_argument("--quick", action="store_true", help="Quick strategic report (default)")
    ap.add_argument("--out", default="artifacts/operations/vn30_completeness_audit.json")
    args = ap.parse_args()

    from core.liquid_universe import VN30_SYMBOLS

    rows = [_audit_symbol(sym, quick=True) for sym in VN30_SYMBOLS]
    ok_rows = [r for r in rows if r.get("ok")]
    with_missing = [r for r in ok_rows if int(r.get("missing_count") or 0) > 0]
    avg_missing = (
        sum(int(r.get("missing_count") or 0) for r in ok_rows) / len(ok_rows) if ok_rows else 0.0
    )
    freq: dict[str, int] = {}
    for r in with_missing:
        for item in r.get("missing_items") or []:
            freq[str(item)] = freq.get(str(item), 0) + 1

    payload = {
        "universe": "VN30",
        "symbols_total": len(VN30_SYMBOLS),
        "audited_ok": len(ok_rows),
        "symbols_with_missing": len(with_missing),
        "avg_missing_count": round(avg_missing, 2),
        "missing_frequency": dict(sorted(freq.items(), key=lambda x: -x[1])),
        "rows": rows,
    }

    out = ROOT / str(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "out": str(out),
                "audited_ok": payload["audited_ok"],
                "symbols_with_missing": payload["symbols_with_missing"],
                "avg_missing_count": payload["avg_missing_count"],
                "top_gaps": list(payload["missing_frequency"].items())[:5],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
