#!/usr/bin/env python3
"""
Run predefined upgrade batches only after explicit "ok" confirmation.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BATCH_CONFIG_PATH = ROOT / "config" / "upgrade_batches.json"
ARTIFACT_DIR = ROOT / "artifacts" / "upgrade_runner"


def _load_config(path: Path = BATCH_CONFIG_PATH) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Invalid upgrade batch config format.")
    return raw


def _run_command(command: str) -> tuple[int, str]:
    env = os.environ.copy()
    proc = subprocess.run(
        command,
        cwd=str(ROOT),
        shell=True,
        capture_output=True,
        text=True,
        env=env,
    )
    output = f"$ {command}\n{proc.stdout}{proc.stderr}"
    return int(proc.returncode), output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", default="week1", help="Batch key in config/upgrade_batches.json")
    parser.add_argument("--confirm", default="", help="Must be exactly 'ok' to execute")
    parser.add_argument("--dry-run", action="store_true", help="Only print commands, do not execute.")
    args = parser.parse_args()

    config = _load_config()
    batches = config.get("batches")
    if not isinstance(batches, dict):
        print("[FAIL] Invalid config: missing 'batches' object.")
        return 2

    batch = batches.get(args.batch)
    if not isinstance(batch, dict):
        print(f"[FAIL] Batch not found: {args.batch}")
        print(f"[INFO] Available batches: {', '.join(sorted(batches.keys()))}")
        return 2

    commands = batch.get("commands")
    if not isinstance(commands, list) or not all(isinstance(x, str) for x in commands):
        print(f"[FAIL] Batch '{args.batch}' has invalid commands list.")
        return 2

    print(f"[INFO] Batch: {args.batch}")
    print(f"[INFO] Description: {batch.get('description', '')}")
    for idx, cmd in enumerate(commands, start=1):
        print(f"  {idx}. {cmd}")

    if args.dry_run:
        print("[OK] Dry-run complete.")
        return 0

    if str(args.confirm).strip().lower() != "ok":
        print("[BLOCKED] Execution requires --confirm ok")
        return 3

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    log_path = ARTIFACT_DIR / f"{args.batch}_{ts}.log"
    summary_path = ARTIFACT_DIR / f"{args.batch}_{ts}.json"

    logs: list[str] = []
    steps: list[dict[str, Any]] = []
    for idx, cmd in enumerate(commands, start=1):
        rc, out = _run_command(cmd)
        logs.append(f"=== STEP {idx} | rc={rc} ===\n{out}\n")
        steps.append({"step": idx, "command": cmd, "return_code": rc})
        if rc != 0:
            log_path.write_text("\n".join(logs), encoding="utf-8")
            summary_path.write_text(
                json.dumps(
                    {
                        "batch": args.batch,
                        "status": "failed",
                        "failed_step": idx,
                        "steps": steps,
                        "generated_at_utc": datetime.now(UTC).isoformat(),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(f"[FAIL] Step {idx} failed. See: {log_path.relative_to(ROOT)}")
            return rc

    log_path.write_text("\n".join(logs), encoding="utf-8")
    summary_path.write_text(
        json.dumps(
            {
                "batch": args.batch,
                "status": "ok",
                "steps": steps,
                "generated_at_utc": datetime.now(UTC).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[OK] Batch completed. Logs: {log_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

