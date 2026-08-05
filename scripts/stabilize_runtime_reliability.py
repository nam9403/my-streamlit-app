#!/usr/bin/env python3
"""
Best-effort runtime reliability stabilization before strict release gates.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.product_layer import process_notification_queue, retry_failed_notifications  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-retries", type=int, default=500)
    ap.add_argument("--max-jobs", type=int, default=500)
    ap.add_argument("--passes", type=int, default=3)
    args = ap.parse_args()

    retried_total = 0
    processed_total = 0
    sent_total = 0
    failed_total = 0

    for _ in range(max(1, int(args.passes))):
        moved = retry_failed_notifications(max_rows=max(1, int(args.max_retries)))
        retried_total += int(moved)
        stat = process_notification_queue(max_jobs=max(1, int(args.max_jobs)))
        processed_total += int(stat.get("processed") or 0)
        sent_total += int(stat.get("sent") or 0)
        failed_total += int(stat.get("failed") or 0)
        if int(moved) == 0 and int(stat.get("processed") or 0) == 0:
            break

    print(
        json.dumps(
            {
                "retried": retried_total,
                "processed": processed_total,
                "sent": sent_total,
                "failed": failed_total,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

