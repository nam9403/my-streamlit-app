from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def test_run_monthly_accountability_force_mode() -> None:
    root = Path(__file__).resolve().parent.parent
    script = root / "scripts" / "run_monthly_accountability.py"
    r = subprocess.run(
        [sys.executable, str(script), "--force", "--users", "scheduler_test_user"],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=True,
    )
    out = json.loads(r.stdout)
    assert str(out.get("status")) == "ok"
    assert int(out.get("reports_generated") or 0) >= 1


def test_run_monthly_accountability_idempotent_mode() -> None:
    root = Path(__file__).resolve().parent.parent
    script = root / "scripts" / "run_monthly_accountability.py"
    # First run sets marker
    subprocess.run(
        [sys.executable, str(script), "--users", "scheduler_idempotent_user", "--force"],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=True,
    )
    today_dom = str(datetime.now(timezone.utc).day)
    # Second run (non-force) should skip duplicate for same month
    r2 = subprocess.run(
        [sys.executable, str(script), "--users", "scheduler_idempotent_user", "--day-of-month", today_dom],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=True,
    )
    out2 = json.loads(r2.stdout)
    assert str(out2.get("status")) == "ok"
    assert int(out2.get("skipped_duplicate") or 0) >= 1


def test_run_monthly_accountability_retention_deletes_old_markdown() -> None:
    root = Path(__file__).resolve().parent.parent
    report_dir = root / "data" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    old_file = report_dir / "monthly_accountability_retention_test_old.md"
    old_file.write_text("old", encoding="utf-8")
    old_ts = datetime.now(timezone.utc).timestamp() - (190 * 86400)
    os.utime(old_file, (old_ts, old_ts))

    script = root / "scripts" / "run_monthly_accountability.py"
    subprocess.run(
        [sys.executable, str(script), "--force", "--users", "retention_test_user", "--retention-days", "180"],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=True,
    )
    assert not old_file.exists()

