#!/usr/bin/env python3
"""
Generate and optionally email monthly accountability reports.

Designed to be scheduler-friendly:
- Can run daily, and only executes on a specific day-of-month (default 1).
- Supports single user or auto-discovery of known users.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import env_bootstrap  # noqa: E402

env_bootstrap.init_app_environment()

from core.observability import configure_observability  # noqa: E402
from core.product_layer import (  # noqa: E402
    export_monthly_accountability_markdown,
    has_delivery_marker,
    list_known_user_ids,
    load_secret,
    send_monthly_accountability_email,
    set_delivery_marker,
)


def _parse_users(raw: str) -> list[str]:
    items = [x.strip() for x in str(raw or "").replace(";", ",").split(",")]
    return [x for x in items if x]


def _apply_retention(report_root: Path, log_file: Path, retention_days: int) -> dict[str, int]:
    days = max(1, int(retention_days))
    cutoff_ts = time() - (days * 86400)
    removed_reports = 0
    removed_logs = 0

    for p in report_root.glob("monthly_accountability_*.md"):
        try:
            if p.stat().st_mtime < cutoff_ts:
                p.unlink(missing_ok=True)
                removed_reports += 1
        except OSError:
            continue

    # Keep log file compact by trimming older lines if file is too large.
    if log_file.exists():
        try:
            lines = log_file.read_text(encoding="utf-8").splitlines()
            if len(lines) > 5000:
                keep = lines[-2000:]
                log_file.write_text("\n".join(keep) + "\n", encoding="utf-8")
                removed_logs = len(lines) - len(keep)
        except OSError:
            pass

    return {"removed_reports": removed_reports, "trimmed_log_lines": removed_logs}


def main() -> int:
    correlation_id = configure_observability("run_monthly_accountability")
    logger = logging.getLogger(__name__)
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", default="", help="Comma-separated user ids. Empty = auto-detect.")
    ap.add_argument("--send-email", action="store_true", help="Send report emails using stored/env SMTP config.")
    ap.add_argument("--day-of-month", type=int, default=1, help="Only execute on this UTC day (1-28).")
    ap.add_argument("--force", action="store_true", help="Ignore day-of-month guard.")
    ap.add_argument("--retention-days", type=int, default=180, help="Delete monthly markdown reports older than N days.")
    ap.add_argument(
        "--marker-prefix",
        default="monthly_accountability",
        help="Idempotency marker prefix stored in DB.",
    )
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    period_key = now.strftime("%Y-%m")
    dom = max(1, min(int(args.day_of_month), 28))
    if not args.force and now.day != dom:
        print(
            json.dumps(
                {
                    "status": "skipped",
                    "reason": f"today_day={now.day}, configured_day={dom}",
                    "generated_at_utc": now.isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    users = _parse_users(args.users)
    if not users:
        users = list_known_user_ids(limit=1000)
    if not users:
        print(json.dumps({"status": "ok", "reports_generated": 0, "emails_sent": 0}, ensure_ascii=False, indent=2))
        return 0

    sent = 0
    failed = 0
    skipped_duplicate = 0
    generated: list[dict[str, str]] = []
    started = datetime.now(timezone.utc)
    for uid in users:
        marker = f"{str(args.marker_prefix).strip()}:{period_key}:{uid}"
        if not args.force and has_delivery_marker(uid, marker):
            skipped_duplicate += 1
            generated.append({"user_id": uid, "skipped": "already_sent_this_period"})
            continue
        try:
            path = export_monthly_accountability_markdown(uid)
            generated.append({"user_id": uid, "path": path})
        except Exception as e:  # pragma: no cover
            failed += 1
            logger.exception("monthly_accountability export_failed user_id=%s", uid)
            generated.append({"user_id": uid, "error": str(e)})
            continue

        if not args.send_email:
            set_delivery_marker(uid, marker)
            continue
        email_to = load_secret(uid, "alert_email_to", os.environ.get("ALERT_EMAIL_TO", ""))
        smtp_host = load_secret(uid, "smtp_host", os.environ.get("SMTP_HOST", ""))
        smtp_port = int(load_secret(uid, "smtp_port", os.environ.get("SMTP_PORT", "587")) or 587)
        smtp_user = load_secret(uid, "smtp_user", os.environ.get("SMTP_USER", ""))
        smtp_password = load_secret(uid, "smtp_password", os.environ.get("SMTP_PASSWORD", ""))
        smtp_from = load_secret(uid, "smtp_from", os.environ.get("SMTP_FROM", ""))
        ok, _msg = send_monthly_accountability_email(
            uid,
            email_to,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_user=smtp_user,
            smtp_password=smtp_password,
            smtp_from=smtp_from,
        )
        if ok:
            sent += 1
            set_delivery_marker(uid, marker)
        else:
            failed += 1
            logger.warning("monthly_accountability email_failed user_id=%s reason=%s", uid, _msg)

    result = {
        "status": "ok",
        "correlation_id": correlation_id,
        "period_key": period_key,
        "reports_generated": len(generated),
        "emails_sent": sent,
        "failed": failed,
        "skipped_duplicate": skipped_duplicate,
        "details": generated[:100],
    }

    # Append run log for audit/operations.
    report_dir = ROOT / "data" / "reports"
    log_dir = report_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "monthly_accountability_runs.jsonl"
    line = {
        "started_at_utc": started.isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        **result,
    }
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
    result["run_log"] = str(log_file)
    result["retention"] = _apply_retention(report_dir, log_file, int(args.retention_days))
    logger.info(
        "monthly_accountability completed users=%s generated=%s sent=%s failed=%s skipped_duplicate=%s",
        len(users),
        len(generated),
        sent,
        failed,
        skipped_duplicate,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

