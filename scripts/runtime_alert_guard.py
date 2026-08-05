#!/usr/bin/env python3
"""
Runtime alert guard for proactive incident prevention.

Generates a health snapshot and raises severity levels:
- ok: stable
- warn: degrading trend, needs attention
- critical: immediate mitigation required
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.product_layer import dispatch_text_notifications, get_admin_cx_kpi, get_admin_kpi  # noqa: E402


def _build_alerts(
    *,
    admin: dict[str, Any],
    cx: dict[str, Any],
    cx_warn: float,
    cx_critical: float,
    queue_warn_ratio: float,
    queue_critical_ratio: float,
    high_retry_warn_ratio: float,
    high_retry_critical_ratio: float,
    oldest_pending_warn_minutes: float,
    oldest_pending_critical_minutes: float,
    min_cx_samples: int,
) -> tuple[str, list[str], dict[str, float | int]]:
    obs = admin.get("notification_observability") or {}
    health = obs.get("runtime_health") or {}
    cx_avg = float(cx.get("avg_score") or 0.0)
    cx_samples = int(cx.get("samples") or 0)

    rows = admin.get("notification_queue") or []
    total = 0
    failed = 0
    for r in rows:
        c = int(r.get("count") or 0)
        total += c
        if str(r.get("status") or "").strip().lower() == "failed":
            failed += c
    queue_fail_ratio = (failed / total) if total > 0 else 0.0

    high_retry_ratio = float(health.get("high_retry_ratio") or 0.0)
    oldest_pending_age_minutes = float(health.get("oldest_pending_age_minutes") or 0.0)

    reasons: list[str] = []
    severity = "ok"

    if cx_samples < int(min_cx_samples):
        severity = "warn"
        reasons.append("Insufficient CX samples for confident runtime judgement.")

    if cx_samples >= int(min_cx_samples):
        if cx_avg < float(cx_critical):
            severity = "critical"
            reasons.append("CX average breached critical floor.")
        elif cx_avg < float(cx_warn):
            severity = "warn" if severity != "critical" else severity
            reasons.append("CX average is below warning threshold.")

    if queue_fail_ratio >= float(queue_critical_ratio):
        severity = "critical"
        reasons.append("Notification queue fail ratio is critical.")
    elif queue_fail_ratio >= float(queue_warn_ratio):
        severity = "warn" if severity != "critical" else severity
        reasons.append("Notification queue fail ratio is elevated.")

    if high_retry_ratio >= float(high_retry_critical_ratio):
        severity = "critical"
        reasons.append("High-retry queue pressure is critical.")
    elif high_retry_ratio >= float(high_retry_warn_ratio):
        severity = "warn" if severity != "critical" else severity
        reasons.append("High-retry queue pressure is elevated.")

    if oldest_pending_age_minutes >= float(oldest_pending_critical_minutes):
        severity = "critical"
        reasons.append("Oldest pending notification age is critical.")
    elif oldest_pending_age_minutes >= float(oldest_pending_warn_minutes):
        severity = "warn" if severity != "critical" else severity
        reasons.append("Oldest pending notification age is elevated.")

    stats: dict[str, float | int] = {
        "cx_avg": round(cx_avg, 2),
        "cx_samples": cx_samples,
        "queue_fail_ratio": round(queue_fail_ratio, 4),
        "high_retry_ratio": round(high_retry_ratio, 4),
        "oldest_pending_age_minutes": round(oldest_pending_age_minutes, 2),
    }
    return severity, reasons, stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days-admin", type=int, default=30)
    ap.add_argument("--days-cx", type=int, default=14)
    ap.add_argument("--min-cx-samples", type=int, default=20)
    ap.add_argument("--cx-warn", type=float, default=80.0)
    ap.add_argument("--cx-critical", type=float, default=70.0)
    ap.add_argument("--queue-warn-ratio", type=float, default=0.10)
    ap.add_argument("--queue-critical-ratio", type=float, default=0.25)
    ap.add_argument("--high-retry-warn-ratio", type=float, default=0.40)
    ap.add_argument("--high-retry-critical-ratio", type=float, default=0.60)
    ap.add_argument("--oldest-pending-warn-minutes", type=float, default=120.0)
    ap.add_argument("--oldest-pending-critical-minutes", type=float, default=360.0)
    ap.add_argument("--require-ok", action="store_true", help="Return non-zero unless severity is ok.")
    ap.add_argument(
        "--notify-on",
        default="critical",
        choices=("none", "warn", "critical"),
        help="Trigger outbound notification on severity >= notify_on.",
    )
    ap.add_argument("--telegram-bot-token", default="")
    ap.add_argument("--telegram-chat-id", default="")
    ap.add_argument("--webhook-url", default="")
    ap.add_argument("--email-to", default="")
    ap.add_argument("--smtp-host", default="")
    ap.add_argument("--smtp-port", type=int, default=587)
    ap.add_argument("--smtp-user", default="")
    ap.add_argument("--smtp-password", default="")
    ap.add_argument("--smtp-from", default="")
    ap.add_argument(
        "--out",
        default=str(ROOT / "artifacts" / "operations" / "runtime_alert_guard.json"),
        help="Output JSON artifact path.",
    )
    args = ap.parse_args()

    admin = get_admin_kpi(days=max(1, int(args.days_admin)))
    cx = get_admin_cx_kpi(days=max(1, int(args.days_cx)))
    severity, reasons, stats = _build_alerts(
        admin=admin,
        cx=cx,
        cx_warn=float(args.cx_warn),
        cx_critical=float(args.cx_critical),
        queue_warn_ratio=float(args.queue_warn_ratio),
        queue_critical_ratio=float(args.queue_critical_ratio),
        high_retry_warn_ratio=float(args.high_retry_warn_ratio),
        high_retry_critical_ratio=float(args.high_retry_critical_ratio),
        oldest_pending_warn_minutes=float(args.oldest_pending_warn_minutes),
        oldest_pending_critical_minutes=float(args.oldest_pending_critical_minutes),
        min_cx_samples=max(0, int(args.min_cx_samples)),
    )

    payload: dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "severity": severity,
        "reasons": reasons,
        "stats": stats,
        "thresholds": {
            "min_cx_samples": int(args.min_cx_samples),
            "cx_warn": float(args.cx_warn),
            "cx_critical": float(args.cx_critical),
            "queue_warn_ratio": float(args.queue_warn_ratio),
            "queue_critical_ratio": float(args.queue_critical_ratio),
            "high_retry_warn_ratio": float(args.high_retry_warn_ratio),
            "high_retry_critical_ratio": float(args.high_retry_critical_ratio),
            "oldest_pending_warn_minutes": float(args.oldest_pending_warn_minutes),
            "oldest_pending_critical_minutes": float(args.oldest_pending_critical_minutes),
        },
    }

    out_path = Path(str(args.out))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    notify_on = str(args.notify_on or "critical").strip().lower()
    sev_rank = {"ok": 0, "warn": 1, "critical": 2}
    notify_rank = {"none": 99, "warn": 1, "critical": 2}
    if sev_rank.get(severity, 0) >= notify_rank.get(notify_on, 99):
        text = (
            f"[RuntimeAlert] severity={severity.upper()} | "
            f"cx={stats['cx_avg']} (n={stats['cx_samples']}) | "
            f"queue_fail={stats['queue_fail_ratio']} | "
            f"high_retry={stats['high_retry_ratio']} | "
            f"oldest_pending_m={stats['oldest_pending_age_minutes']} | "
            f"reasons={'; '.join(reasons) if reasons else 'none'}"
        )
        dispatch_text_notifications(
            text,
            telegram_bot_token=str(args.telegram_bot_token or ""),
            telegram_chat_id=str(args.telegram_chat_id or ""),
            webhook_url=str(args.webhook_url or ""),
            email_to=str(args.email_to or ""),
            smtp_host=str(args.smtp_host or ""),
            smtp_port=int(args.smtp_port),
            smtp_user=str(args.smtp_user or ""),
            smtp_password=str(args.smtp_password or ""),
            smtp_from=str(args.smtp_from or ""),
        )

    if bool(args.require_ok) and severity != "ok":
        return 3 if severity == "warn" else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

