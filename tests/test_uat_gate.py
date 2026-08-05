from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_uat_gate_dry_run_lists_manual_items() -> None:
    root = Path(__file__).resolve().parent.parent
    script = root / "scripts" / "uat_gate.py"
    out = subprocess.run(
        [sys.executable, str(script), "--dry-run"],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert out.returncode == 0
    assert "[AUTO] Secret scan" in out.stdout
    assert "[MANUAL] UAT checklist items requiring human sign-off:" in out.stdout
    assert "Product Owner đồng ý phát hành." in out.stdout


def test_uat_gate_skip_automated() -> None:
    root = Path(__file__).resolve().parent.parent
    script = root / "scripts" / "uat_gate.py"
    out = subprocess.run(
        [sys.executable, str(script), "--skip-automated"],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert out.returncode == 0
    assert "[AUTO] Secret scan" not in out.stdout
    assert "[MANUAL] UAT checklist items requiring human sign-off:" in out.stdout
