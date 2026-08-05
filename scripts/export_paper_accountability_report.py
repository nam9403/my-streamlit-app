"""
Export paper-trade accountability (30/90/365d) to JSON + Markdown.

  python scripts/export_paper_accountability_report.py
  python scripts/export_paper_accountability_report.py --resolve
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
    ap = argparse.ArgumentParser(description="Export paper-trade accountability report.")
    ap.add_argument("--resolve", action="store_true", help="Resolve due trades before export")
    ap.add_argument("--json-out", default="artifacts/operations/paper_trade_accountability.json")
    ap.add_argument("--md-out", default="artifacts/operations/paper_trade_accountability.md")
    args = ap.parse_args()

    from core.paper_trade_ledger import format_hitrate_markdown, hitrate_report_extended, resolve_due_trades

    resolve_stat = {"resolved": 0, "failed": 0, "still_open": 0}
    if args.resolve:
        resolve_stat = resolve_due_trades(fetch_price=_fetch_price)
        print(json.dumps({"resolve": resolve_stat}, ensure_ascii=False))

    report = hitrate_report_extended(horizons=(40, 30, 90, 365))
    payload = {"resolve": resolve_stat, "accountability": report}

    json_out = ROOT / str(args.json_out)
    md_out = ROOT / str(args.md_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_out.write_text(format_hitrate_markdown(report), encoding="utf-8")
    print(json.dumps({"json": str(json_out), "markdown": str(md_out), "windows": report.get("windows")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
