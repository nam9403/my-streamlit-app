#!/usr/bin/env python3
"""
Run lightweight performance benchmark loops for core product-layer flows.

This script is designed for local/staging runtime evidence generation:
- executes selected flows repeatedly
- relies on in-app log_timing metrics for JSONL tracking
- emits benchmark summary artifact for quick review
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _flows(user_id: str) -> dict[str, Callable[[], object]]:
    from core import product_layer as pl

    return {
        "product_layer.get_admin_kpi": lambda: pl.get_admin_kpi(days=30),
        "product_layer.process_notification_queue": lambda: pl.process_notification_queue(max_jobs=20),
        "product_layer.get_notification_queue_diagnostics": lambda: pl.get_notification_queue_diagnostics(limit=20),
        "product_layer.retry_failed_notifications": lambda: pl.retry_failed_notifications(max_rows=20),
        "product_layer.get_kpi_dashboard": lambda: pl.get_kpi_dashboard(user_id, days=30),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--iterations", type=int, default=30, help="Iterations per flow.")
    ap.add_argument("--warmup", type=int, default=2, help="Warmup rounds per flow.")
    ap.add_argument("--sleep-ms", type=int, default=30, help="Sleep between iterations to smooth bursts.")
    ap.add_argument("--user-id", default="staging_user_a", help="User ID for user-scoped flow calls.")
    ap.add_argument(
        "--out-json",
        default=str(ROOT / "artifacts" / "performance" / "perf_benchmark_run.json"),
        help="Output summary JSON path.",
    )
    args = ap.parse_args()

    iterations = max(1, int(args.iterations))
    warmup = max(0, int(args.warmup))
    sleep_ms = max(0, int(args.sleep_ms))
    flow_map = _flows(str(args.user_id))

    summary: dict[str, dict[str, object]] = {}
    for metric, fn in flow_map.items():
        ok = 0
        fail = 0
        last_error = ""
        start = time.perf_counter()
        for _ in range(warmup):
            try:
                fn()
            except Exception as exc:
                last_error = f"{exc.__class__.__name__}: {exc}"
        for _ in range(iterations):
            try:
                fn()
                ok += 1
            except Exception as exc:
                fail += 1
                last_error = f"{exc.__class__.__name__}: {exc}"
            if sleep_ms > 0:
                time.sleep(sleep_ms / 1000.0)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        summary[metric] = {
            "ok_iterations": ok,
            "failed_iterations": fail,
            "elapsed_ms": round(elapsed_ms, 2),
            "last_error": last_error,
        }
        print(f"[FLOW] {metric}: ok={ok} fail={fail} elapsed_ms={elapsed_ms:.2f}")

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "iterations_per_flow": iterations,
        "warmup_per_flow": warmup,
        "sleep_ms": sleep_ms,
        "user_id": str(args.user_id),
        "flows": summary,
    }
    out_path = Path(args.out_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

