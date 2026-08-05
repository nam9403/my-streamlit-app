from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.vn_market_calendar import CALENDAR_PATH, ensure_calendar_years


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update VN market calendar years in data/market_calendar_vn.json"
    )
    now_year = datetime.now().year
    parser.add_argument("--start-year", type=int, default=now_year - 1, help="Start year (inclusive).")
    parser.add_argument("--end-year", type=int, default=now_year + 2, help="End year (inclusive).")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.end_year < args.start_year:
        raise SystemExit("--end-year must be >= --start-year")

    merged = ensure_calendar_years(args.start_year, args.end_year)
    total_years = sum(1 for y in merged if args.start_year <= y <= args.end_year)
    total_holidays = sum(len(merged[y]) for y in merged if args.start_year <= y <= args.end_year)
    print(f"[OK] Updated VN market calendar: years={total_years}, holidays={total_holidays}")
    print(f"[PATH] {CALENDAR_PATH}")


if __name__ == "__main__":
    main()
