from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_execute_project_5s_dry_run_outputs_all_steps() -> None:
    root = Path(__file__).resolve().parent.parent
    script = root / "scripts" / "execute_project_5s.py"
    run = subprocess.run(
        [sys.executable, str(script), "--dry-run"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0
    payload = json.loads(run.stdout)
    assert payload["status"] == "ok"
    steps = payload["steps"]
    assert "seiri" in steps
    assert "seiton" in steps
    assert "seiso" in steps
    assert "seiketsu" in steps
    assert "shitsuke" in steps

