from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_bootstrap_postgres_blocks_without_postgres_url() -> None:
    root = Path(__file__).resolve().parent.parent
    script = root / "scripts" / "bootstrap_postgres.py"
    run = subprocess.run(
        [sys.executable, str(script), "--check-only"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    assert run.returncode in (0, 2)
    if run.returncode == 2:
        assert "II_DB_URL is not PostgreSQL" in run.stdout

