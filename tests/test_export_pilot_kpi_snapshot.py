from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_export_pilot_kpi_snapshot_generates_json(tmp_path) -> None:
    root = Path(__file__).resolve().parent.parent
    script = root / "scripts" / "export_pilot_kpi_snapshot.py"
    out_file = tmp_path / "pilot_kpi_snapshot.json"
    run = subprocess.run(
        [sys.executable, str(script), "--out", str(out_file)],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0
    assert out_file.exists()
    raw = json.loads(out_file.read_text(encoding="utf-8"))
    assert "admin" in raw
    assert "cx" in raw
    assert "priority_actions" in raw
    assert isinstance(raw["priority_actions"], list)
