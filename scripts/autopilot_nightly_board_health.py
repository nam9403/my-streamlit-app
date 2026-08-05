"""
Health check for Autopilot nightly board.

Usage:
  python scripts/autopilot_nightly_board_health.py
  python scripts/autopilot_nightly_board_health.py --require-ok
  python scripts/autopilot_nightly_board_health.py --min-coverage 80 --max-age-hours 36
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


def main() -> int:
    ap = argparse.ArgumentParser(description="Check Autopilot nightly board health.")
    ap.add_argument("--min-coverage", type=float, default=None)
    ap.add_argument("--max-age-hours", type=float, default=None)
    ap.add_argument("--require-ok", action="store_true")
    ap.add_argument(
        "--out",
        default="artifacts/operations/autopilot_nightly_board_health.json",
    )
    args = ap.parse_args()

    from core.autopilot_nightly_board import board_health_report

    report = board_health_report(
        min_coverage_pct=args.min_coverage,
        max_hours=args.max_age_hours,
    )
    out = ROOT / str(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.require_ok and not report.get("ok"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
