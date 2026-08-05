#!/usr/bin/env python3
"""
Evaluate scale gate decision from runtime KPI.

Decision:
  - GO:   healthy to expand pilot/public exposure
  - HOLD: continue current scale, optimize first
  - FIX:  stop scale-up and stabilize immediately

Usage:
  python scripts/scale_gate_check.py
  python scripts/scale_gate_check.py --cx-go 80 --cx-fix 70 --queue-fail-fix-ratio 0.25
  python scripts/scale_gate_check.py --require-go
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.product_layer import get_admin_cx_kpi, get_admin_kpi  # noqa: E402


def _queue_fail_ratio(admin: dict) -> float:
    rows = admin.get("notification_queue") or []
    total = 0
    failed = 0
    for r in rows:
        c = int(r.get("count") or 0)
        total += c
        if str(r.get("status") or "").lower() == "failed":
            failed += c
    return (failed / total) if total > 0 else 0.0


def _runtime_health(admin: dict) -> dict:
    obs = admin.get("notification_observability") or {}
    health = obs.get("runtime_health") or {}
    return health if isinstance(health, dict) else {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--admin-days", type=int, default=30)
    ap.add_argument("--cx-days", type=int, default=14)
    ap.add_argument("--cx-go", type=float, default=80.0)
    ap.add_argument("--cx-fix", type=float, default=70.0)
    ap.add_argument("--queue-fail-go-ratio", type=float, default=0.10)
    ap.add_argument("--queue-fail-fix-ratio", type=float, default=0.25)
    ap.add_argument("--high-retry-go-ratio", type=float, default=0.40)
    ap.add_argument("--high-retry-fix-ratio", type=float, default=0.60)
    ap.add_argument("--oldest-pending-go-minutes", type=float, default=120.0)
    ap.add_argument("--oldest-pending-fix-minutes", type=float, default=360.0)
    ap.add_argument("--min-cx-samples", type=int, default=20)
    ap.add_argument("--require-go", action="store_true", help="Return non-zero unless decision is GO.")
    args = ap.parse_args()

    admin = get_admin_kpi(days=max(1, int(args.admin_days)))
    cx = get_admin_cx_kpi(days=max(1, int(args.cx_days)))
    cx_avg = float(cx.get("avg_score") or 0.0)
    cx_samples = int(cx.get("samples") or 0)
    q_ratio = _queue_fail_ratio(admin)
    health = _runtime_health(admin)
    high_retry_ratio = float(health.get("high_retry_ratio") or 0.0)
    oldest_pending_age_minutes = float(health.get("oldest_pending_age_minutes") or 0.0)

    decision = "GO"
    reasons: list[str] = []
    insufficient_cx = cx_samples < int(args.min_cx_samples)
    no_cx_data = cx_samples == 0
    if insufficient_cx:
        decision = "HOLD"
        reasons.append("Insufficient CX samples for confident scale decision.")
    # When there is no CX data yet, evaluate queue health only.
    cx_go_breach = (not insufficient_cx) and (not no_cx_data) and (cx_avg < float(args.cx_go))
    if (
        cx_go_breach
        or q_ratio > float(args.queue_fail_go_ratio)
        or high_retry_ratio > float(args.high_retry_go_ratio)
        or oldest_pending_age_minutes > float(args.oldest_pending_go_minutes)
    ):
        decision = "HOLD"
        reasons.append("Core KPIs are below GO threshold.")
    cx_fix_breach = (not insufficient_cx) and (not no_cx_data) and (cx_avg < float(args.cx_fix))
    if (
        cx_fix_breach
        or q_ratio > float(args.queue_fail_fix_ratio)
        or high_retry_ratio > float(args.high_retry_fix_ratio)
        or oldest_pending_age_minutes > float(args.oldest_pending_fix_minutes)
    ):
        decision = "FIX"
        reasons.append("Critical KPI breach. Stabilize before expanding.")

    result = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
        "cx_avg": round(cx_avg, 2),
        "cx_samples": cx_samples,
        "queue_fail_ratio": round(q_ratio, 4),
        "high_retry_ratio": round(high_retry_ratio, 4),
        "oldest_pending_age_minutes": round(oldest_pending_age_minutes, 2),
        "queue_observability": admin.get("notification_observability") or {},
        "thresholds": {
            "cx_go": float(args.cx_go),
            "cx_fix": float(args.cx_fix),
            "queue_fail_go_ratio": float(args.queue_fail_go_ratio),
            "queue_fail_fix_ratio": float(args.queue_fail_fix_ratio),
            "high_retry_go_ratio": float(args.high_retry_go_ratio),
            "high_retry_fix_ratio": float(args.high_retry_fix_ratio),
            "oldest_pending_go_minutes": float(args.oldest_pending_go_minutes),
            "oldest_pending_fix_minutes": float(args.oldest_pending_fix_minutes),
            "min_cx_samples": int(args.min_cx_samples),
        },
        "reasons": reasons,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if decision == "FIX":
        return 2
    if bool(args.require_go) and decision != "GO":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
