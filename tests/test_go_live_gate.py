from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_go_live_gate_dry_run_writes_artifacts() -> None:
    root = Path(__file__).resolve().parent.parent
    script = root / "scripts" / "go_live_gate.py"
    out = subprocess.run(
        [sys.executable, str(script), "--dry-run", "--env", "preprod"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0
    assert "preflight_check.py --prod" in out.stdout
    assert "prod_readiness_check.py --env preprod --require-go --require-live-data --min-cx-samples 20" in out.stdout
    assert "scale_gate_check.py --min-cx-samples 20 --require-go" in out.stdout
    assert "slo_gate_check.py --min-cx-samples 20 --require-go" in out.stdout
    assert "dss_release_gate.py --symbol FPT --user-id default_user --strict" in out.stdout
    assert "smart_money_event_sync.py --symbols FPT,VNM,HPG,VCB" in out.stdout
    assert "uat_gate.py" in out.stdout
    assert "live_data_stability_benchmark.py --window-days 14 --min-sessions 7 --require-go" in out.stdout
    assert "runtime_alert_guard.py --notify-on critical" in out.stdout

    summary_path = root / "artifacts" / "operations" / "go_live_gate_summary.json"
    md_path = root / "artifacts" / "operations" / "go_live_gate_summary.md"
    assert summary_path.exists()
    assert md_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["decision"] == "PASS"
    assert summary["dry_run"] is True
    assert len(summary["steps"]) >= 4


def test_go_live_gate_dry_run_skip_options() -> None:
    root = Path(__file__).resolve().parent.parent
    script = root / "scripts" / "go_live_gate.py"
    out = subprocess.run(
        [
            sys.executable,
            str(script),
            "--dry-run",
            "--skip-uat",
            "--skip-prod-readiness",
            "--skip-dss-gate",
            "--skip-smart-money-sync",
            "--skip-live-stability",
            "--skip-runtime-alert-guard",
            "--min-cx-samples",
            "12",
        ],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0
    assert "prod_readiness_check.py" not in out.stdout
    assert "uat_gate.py" not in out.stdout
    assert "dss_release_gate.py" not in out.stdout
    assert "smart_money_event_sync.py" not in out.stdout
    assert "live_data_stability_benchmark.py" not in out.stdout
    assert "runtime_alert_guard.py" not in out.stdout
    assert "scale_gate_check.py --min-cx-samples 12 --require-go" in out.stdout
    assert "slo_gate_check.py --min-cx-samples 12 --require-go" in out.stdout

