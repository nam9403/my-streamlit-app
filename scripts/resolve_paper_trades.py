"""
Resolve due paper trades + print hit-rate.

  python scripts/resolve_paper_trades.py
  python scripts/resolve_paper_trades.py --force-open
  python scripts/resolve_paper_trades.py --report-only --lookback-days 365
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


def _fetch_price(sym: str) -> float | None:
    try:
        from scrapers.financial_data import fetch_financial_snapshot

        snap = fetch_financial_snapshot(sym) or {}
        px = float(snap.get("price") or 0.0)
        return px if px > 0 else None
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Resolve Autopilot paper trades and report hit-rate.")
    ap.add_argument("--force-open", action="store_true", help="Resolve all OPEN trades regardless of due date")
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--lookback-days", type=int, default=365)
    ap.add_argument("--out", default="artifacts/operations/paper_trade_hitrate.json")
    args = ap.parse_args()

    from core.paper_trade_ledger import hitrate_report, hitrate_report_extended, resolve_due_trades

    resolve_stat = {"resolved": 0, "failed": 0, "still_open": 0}
    if not args.report_only:
        resolve_stat = resolve_due_trades(fetch_price=_fetch_price, force_all_open=bool(args.force_open))
        print(json.dumps({"resolve": resolve_stat}, ensure_ascii=False))

    report = hitrate_report(lookback_days=int(args.lookback_days))
    accountability = hitrate_report_extended(horizons=(30, 90, int(args.lookback_days)))
    payload = {"resolve": resolve_stat, "hitrate": report, "accountability": accountability}
    out = ROOT / str(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
