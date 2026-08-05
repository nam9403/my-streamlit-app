"""
Wave 3 — audit PIT statement cache coverage for a universe.

  python scripts/audit_pit_coverage.py --vn30
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import env_bootstrap  # noqa: F401
except Exception:
    pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Audit PIT fundamentals cache coverage")
    ap.add_argument("--vn30", action="store_true")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--json-out", default="artifacts/operations/pit_coverage_latest.json")
    args = ap.parse_args(argv)

    from core.fundamentals_pit import load_statement_rows_cached
    from core.liquid_universe import VN30_SYMBOLS

    if args.vn30 or not str(args.symbols or "").strip():
        symbols = list(VN30_SYMBOLS)[: max(1, int(args.limit))]
    else:
        symbols = [s.strip().upper() for s in str(args.symbols).split(",") if s.strip()]

    rows_out = []
    ok_n = 0
    for sym in symbols:
        try:
            rows, src = load_statement_rows_cached(sym, size=20)
            n = len(rows or [])
            ok = n >= 4
            if ok:
                ok_n += 1
            rows_out.append({"symbol": sym, "rows": n, "source": src, "ok": ok})
            print(f"[pit] {sym}: rows={n} src={src} ok={ok}", flush=True)
        except Exception as exc:
            rows_out.append({"symbol": sym, "rows": 0, "source": "error", "ok": False, "error": exc.__class__.__name__})
            print(f"[pit] {sym}: ERROR {exc.__class__.__name__}", flush=True)

    coverage = round(100.0 * ok_n / max(1, len(symbols)), 2)
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbols_total": len(symbols),
        "symbols_ok": ok_n,
        "coverage_pct": coverage,
        "gate_pass": coverage >= 90.0,
        "per_symbol": rows_out,
        "note_vi": "ok = ≥4 kỳ BCTC trong cache (Fireant/VNDirect). Mục tiêu Wave3 ≥90% VN30.",
    }
    out = ROOT / str(args.json_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"coverage_pct": coverage, "gate_pass": report["gate_pass"], "out": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
