from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_runtime_alert_guard_outputs_json_artifact() -> None:
    root = Path(__file__).resolve().parent.parent
    script = root / "scripts" / "runtime_alert_guard.py"
    out_file = root / "artifacts" / "operations" / "runtime_alert_guard_test.json"
    run = subprocess.run(
        [sys.executable, str(script), "--out", str(out_file), "--notify-on", "none", "--min-cx-samples", "0"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    assert run.returncode in (0, 2)
    payload = json.loads(run.stdout)
    assert payload["severity"] in ("ok", "warn", "critical")
    assert "stats" in payload
    assert out_file.exists()
    saved = json.loads(out_file.read_text(encoding="utf-8"))
    assert saved["severity"] == payload["severity"]


def test_runtime_alert_guard_require_ok_can_block() -> None:
    root = Path(__file__).resolve().parent.parent
    script = root / "scripts" / "runtime_alert_guard.py"
    run = subprocess.run(
        [sys.executable, str(script), "--require-ok", "--notify-on", "none", "--min-cx-samples", "999999"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    assert run.returncode in (2, 3)

