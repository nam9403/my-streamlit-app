#!/usr/bin/env python3
"""
Execute technical 5S routine for repository hygiene and reliability.

5S mapping:
- Seiri: remove runtime-generated artifacts
- Seiton: ensure required runtime folders are present and organized
- Seiso: scan secrets/runtime leaks
- Seiketsu: run strict static quality standardization
- Shitsuke: run baseline preflight for continuous discipline
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def _run(cmd: list[str], *, dry_run: bool) -> dict[str, Any]:
    if dry_run:
        return {"command": cmd, "exit_code": 0, "dry_run": True}
    run = subprocess.run(cmd, cwd=str(ROOT))
    return {"command": cmd, "exit_code": int(run.returncode), "dry_run": False}


def _ensure_runtime_folders() -> dict[str, Any]:
    targets = [
        ROOT / "data" / "reports",
        ROOT / "data" / "reports" / "logs",
        ROOT / "artifacts" / "architecture",
    ]
    created: list[str] = []
    for p in targets:
        if not p.exists():
            created.append(str(p.relative_to(ROOT)))
        p.mkdir(parents=True, exist_ok=True)
    return {"targets": [str(p.relative_to(ROOT)) for p in targets], "created": created}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Print plan only, do not execute commands.")
    args = ap.parse_args()

    summary: dict[str, Any] = {"status": "ok", "steps": {}}

    # Seiri
    seiri = _run([sys.executable, "scripts/sanitize_runtime_artifacts.py"], dry_run=bool(args.dry_run))
    summary["steps"]["seiri"] = seiri
    if int(seiri.get("exit_code") or 0) != 0:
        summary["status"] = "failed"

    # Seiton
    seiton = _ensure_runtime_folders()
    summary["steps"]["seiton"] = seiton

    # Seiso
    seiso = _run([sys.executable, "scripts/check_secrets.py"], dry_run=bool(args.dry_run))
    summary["steps"]["seiso"] = seiso
    if int(seiso.get("exit_code") or 0) != 0:
        summary["status"] = "failed"

    # Seiketsu
    seiketsu = _run([sys.executable, "scripts/quality_gate.py", "--strict-static", "--skip-tests"], dry_run=bool(args.dry_run))
    summary["steps"]["seiketsu"] = seiketsu
    if int(seiketsu.get("exit_code") or 0) != 0:
        summary["status"] = "failed"

    # Shitsuke
    shitsuke = _run([sys.executable, "scripts/preflight_check.py"], dry_run=bool(args.dry_run))
    summary["steps"]["shitsuke"] = shitsuke
    if int(shitsuke.get("exit_code") or 0) != 0:
        summary["status"] = "failed"

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())

