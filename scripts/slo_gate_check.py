#!/usr/bin/env python3
"""
SLO / error-budget gate for production release decisions.

Decision model:
  - GO:   healthy margin, safe to ship
  - HOLD: borderline, ship only with explicit approval
  - FIX:  hard breach, block release

Usage:
  python scripts/slo_gate_check.py
  python scripts/slo_gate_check.py --require-go
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
    ap.add_argument("--cx-slo", type=float, default=80.0)
    ap.add_argument("--cx-hard-floor", type=float, default=70.0)
    ap.add_argument("--queue-fail-slo-ratio", type=float, default=0.10)
    ap.add_argument("--queue-fail-hard-ratio", type=float, default=0.25)
    ap.add_argument("--high-retry-slo-ratio", type=float, default=0.40)
    ap.add_argument("--high-retry-hard-ratio", type=float, default=0.60)
    ap.add_argument("--oldest-pending-slo-minutes", type=float, default=120.0)
    ap.add_argument("--oldest-pending-hard-minutes", type=float, default=360.0)
    ap.add_argument("--min-cx-samples", type=int, default=20)
    ap.add_argument("--max-error-budget-burn-pct", type=float, default=100.0)
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

    # Error budget burn based on queue-fail SLO.
    budget = max(1e-9, float(args.queue_fail_slo_ratio))
    burn_pct = (q_ratio / budget) * 100.0

    insufficient_cx = cx_samples < int(args.min_cx_samples)
    no_cx_data = cx_samples == 0
    if insufficient_cx:
        decision = "HOLD"
        reasons.append("Insufficient CX samples for reliable SLO decision.")
    cx_slo_breach = (not insufficient_cx) and (not no_cx_data) and (cx_avg < float(args.cx_slo))
    if (
        cx_slo_breach
        or q_ratio > float(args.queue_fail_slo_ratio)
        or high_retry_ratio > float(args.high_retry_slo_ratio)
        or oldest_pending_age_minutes > float(args.oldest_pending_slo_minutes)
        or burn_pct > float(args.max_error_budget_burn_pct)
    ):
        decision = "HOLD"
        reasons.append("SLO not comfortably met (CX/queue-fail/error-budget).")
    cx_floor_breach = (not insufficient_cx) and (not no_cx_data) and (cx_avg < float(args.cx_hard_floor))
    if (
        cx_floor_breach
        or q_ratio > float(args.queue_fail_hard_ratio)
        or high_retry_ratio > float(args.high_retry_hard_ratio)
        or oldest_pending_age_minutes > float(args.oldest_pending_hard_minutes)
    ):
        decision = "FIX"
        reasons.append("Hard floor breach detected.")

    result = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
        "cx_avg": round(cx_avg, 2),
        "cx_samples": cx_samples,
        "queue_fail_ratio": round(q_ratio, 4),
        "high_retry_ratio": round(high_retry_ratio, 4),
        "oldest_pending_age_minutes": round(oldest_pending_age_minutes, 2),
        "queue_observability": admin.get("notification_observability") or {},
        "error_budget_burn_pct": round(burn_pct, 1),
        "thresholds": {
            "cx_slo": float(args.cx_slo),
            "cx_hard_floor": float(args.cx_hard_floor),
            "queue_fail_slo_ratio": float(args.queue_fail_slo_ratio),
            "queue_fail_hard_ratio": float(args.queue_fail_hard_ratio),
            "high_retry_slo_ratio": float(args.high_retry_slo_ratio),
            "high_retry_hard_ratio": float(args.high_retry_hard_ratio),
            "oldest_pending_slo_minutes": float(args.oldest_pending_slo_minutes),
            "oldest_pending_hard_minutes": float(args.oldest_pending_hard_minutes),
            "min_cx_samples": int(args.min_cx_samples),
            "max_error_budget_burn_pct": float(args.max_error_budget_burn_pct),
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
