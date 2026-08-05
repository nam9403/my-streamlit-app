from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_scale_gate_check_runs_and_outputs_json() -> None:
    root = Path(__file__).resolve().parent.parent
    script = root / "scripts" / "scale_gate_check.py"
    run = subprocess.run(
        [sys.executable, str(script), "--min-cx-samples", "0"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    assert run.returncode in (0, 2)
    payload = json.loads(run.stdout)
    assert "decision" in payload
    assert payload["decision"] in ("GO", "HOLD", "FIX")
    assert "queue_fail_ratio" in payload
    assert "queue_observability" in payload


def test_scale_gate_check_require_go_can_block_hold() -> None:
    root = Path(__file__).resolve().parent.parent
    script = root / "scripts" / "scale_gate_check.py"
    run = subprocess.run(
        [sys.executable, str(script), "--require-go", "--min-cx-samples", "999999"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    # HOLD should now return strict non-zero code 3.
    assert run.returncode in (2, 3)


def test_scale_gate_with_zero_samples_and_healthy_queue_is_not_fix() -> None:
    root = Path(__file__).resolve().parent.parent
    script = root / "scripts" / "scale_gate_check.py"
    run = subprocess.run(
        [
            sys.executable,
            str(script),
            "--min-cx-samples",
            "999999",
            "--queue-fail-go-ratio",
            "1",
            "--queue-fail-fix-ratio",
            "1",
        ],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    payload = json.loads(run.stdout)
    assert payload["decision"] in ("GO", "HOLD")
