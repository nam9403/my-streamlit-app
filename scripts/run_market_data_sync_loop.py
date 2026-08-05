"""
Vòng lặp cập nhật liên tục kho dữ liệu VN (snapshot + OHLCV + BCTC).

  python scripts/run_market_data_sync_loop.py
  python scripts/run_market_data_sync_loop.py --pause-sec 120 --existing-batch-size 300

Dừng: Ctrl+C hoặc kill process.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser(description="Loop smart_market_sync for continuous VN data tank updates.")
    ap.add_argument("--pause-sec", type=float, default=float(os.environ.get("II_SYNC_LOOP_PAUSE_SEC", "90") or 90))
    ap.add_argument("--new-batch-size", type=int, default=250)
    ap.add_argument("--existing-batch-size", type=int, default=350)
    ap.add_argument("--ohlcv-sessions", type=int, default=800)
    ap.add_argument("--sleep-sec", type=float, default=0.15)
    ap.add_argument("--refresh-financial-live", action="store_true", default=True)
    ap.add_argument("--no-refresh-financial-live", action="store_true")
    ap.add_argument("--listing-max-age-hours", type=float, default=2.0)
    args = ap.parse_args()

    script = ROOT / "scripts" / "smart_market_sync.py"
    fin_live = not bool(args.no_refresh_financial_live)
    round_i = 0
    while True:
        round_i += 1
        cmd = [
            sys.executable,
            str(script),
            "--new-batch-size",
            str(max(0, int(args.new_batch_size))),
            "--existing-batch-size",
            str(max(0, int(args.existing_batch_size))),
            "--ohlcv-sessions",
            str(max(80, int(args.ohlcv_sessions))),
            "--sleep-sec",
            str(max(0.0, float(args.sleep_sec))),
            "--listing-max-age-hours",
            str(max(0.0, float(args.listing_max_age_hours))),
        ]
        if fin_live:
            cmd.append("--refresh-financial-live")
        print(
            f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] sync round #{round_i}: {' '.join(cmd[2:])}",
            flush=True,
        )
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        r = subprocess.run(cmd, cwd=str(ROOT), env=env)
        print(
            f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] round #{round_i} exit={r.returncode}; "
            f"pause {args.pause_sec}s",
            flush=True,
        )
        time.sleep(max(30.0, float(args.pause_sec)))


if __name__ == "__main__":
    raise SystemExit(main())
