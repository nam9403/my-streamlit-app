from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_auto_upgrade_runner_dry_run_lists_commands() -> None:
    root = Path(__file__).resolve().parent.parent
    script = root / "scripts" / "auto_upgrade_runner.py"
    run = subprocess.run(
        [sys.executable, str(script), "--batch", "week1", "--dry-run"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0
    assert "Batch: week1" in run.stdout
    assert "quality_gate.py --strict-static" in run.stdout


def test_auto_upgrade_runner_requires_ok_confirmation() -> None:
    root = Path(__file__).resolve().parent.parent
    script = root / "scripts" / "auto_upgrade_runner.py"
    run = subprocess.run(
        [sys.executable, str(script), "--batch", "week1"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    assert run.returncode == 3
    assert "requires --confirm ok" in run.stdout

