#!/usr/bin/env python3
"""
Run UAT gate with automated checks + manual sign-off reminders.

Usage:
  python scripts/uat_gate.py
  python scripts/uat_gate.py --dry-run
  python scripts/uat_gate.py --skip-automated
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UAT_CHECKLIST_PATH = ROOT / "UAT_CHECKLIST.md"


def _run(cmd: list[str], *, dry_run: bool = False) -> int:
    print(f"> {' '.join(cmd)}")
    if dry_run:
        return 0
    out = subprocess.run(cmd, cwd=str(ROOT))
    return int(out.returncode)


def _load_manual_items() -> list[str]:
    if not UAT_CHECKLIST_PATH.exists():
        return []
    raw = UAT_CHECKLIST_PATH.read_text(encoding="utf-8")
    items = re.findall(r"^- \[ \]\s+(.+)$", raw, flags=re.MULTILINE)
    return [x.strip() for x in items if x.strip()]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Print checks only, do not execute them.")
    ap.add_argument("--skip-automated", action="store_true", help="Skip automated checks and show manual checklist only.")
    args = ap.parse_args()

    automated_checks: list[tuple[str, list[str]]] = [
        ("Secret scan", [sys.executable, str(ROOT / "scripts" / "check_secrets.py")]),
        ("Preflight (prod)", [sys.executable, str(ROOT / "scripts" / "preflight_check.py"), "--prod"]),
        (
            "Core UAT tests",
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/test_premium_trial.py",
                "tests/test_professional_pdf.py",
                "tests/test_alert_center.py",
                "tests/test_watchlist_live.py",
            ],
        ),
        ("Health check (offline-safe)", [sys.executable, str(ROOT / "scripts" / "health_check.py"), "--skip-pytest"]),
    ]

    if not args.skip_automated:
        for name, cmd in automated_checks:
            print(f"[AUTO] {name}")
            rc = _run(cmd, dry_run=bool(args.dry_run))
            if rc != 0:
                print(f"[FAIL] {name} failed with exit code {rc}")
                return rc

    manual_items = _load_manual_items()
    print("\n[MANUAL] UAT checklist items requiring human sign-off:")
    if not manual_items:
        print("- (No checklist items found in UAT_CHECKLIST.md)")
    else:
        for idx, item in enumerate(manual_items, start=1):
            print(f"{idx:02d}. [ ] {item}")

    print("\n[OK] UAT gate finished. Complete manual sign-off before go-live.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
