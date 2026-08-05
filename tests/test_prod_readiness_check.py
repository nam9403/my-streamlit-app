from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_prod_readiness_check_dry_run() -> None:
    root = Path(__file__).resolve().parent.parent
    script = root / "scripts" / "prod_readiness_check.py"
    out = subprocess.run(
        [sys.executable, str(script), "--dry-run", "--skip-audit", "--skip-health"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0
    assert "preflight_check.py" in out.stdout
    assert "check_secrets.py" in out.stdout
    assert "stabilize_runtime_reliability.py" in out.stdout
    assert "scale_gate_check.py" in out.stdout
    assert "slo_gate_check.py" in out.stdout
    assert "Production readiness checks passed" in out.stdout


def test_prod_readiness_check_dry_run_require_go() -> None:
    root = Path(__file__).resolve().parent.parent
    script = root / "scripts" / "prod_readiness_check.py"
    out = subprocess.run(
        [sys.executable, str(script), "--dry-run", "--skip-audit", "--skip-health", "--require-go"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0
    assert "scale_gate_check.py --min-cx-samples 0 --require-go" in out.stdout
    assert "slo_gate_check.py --min-cx-samples 0 --require-go" in out.stdout


def test_prod_readiness_check_dry_run_min_cx_samples() -> None:
    root = Path(__file__).resolve().parent.parent
    script = root / "scripts" / "prod_readiness_check.py"
    out = subprocess.run(
        [sys.executable, str(script), "--dry-run", "--skip-audit", "--skip-health", "--min-cx-samples", "12"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0
    assert "scale_gate_check.py --min-cx-samples 12" in out.stdout
    assert "slo_gate_check.py --min-cx-samples 12" in out.stdout
