from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    not str(os.environ.get("II_DB_URL") or "").lower().startswith(("postgres://", "postgresql://")),
    reason="PostgreSQL integration smoke requires II_DB_URL.",
)
def test_postgres_bootstrap_and_admin_kpi_smoke() -> None:
    root = Path(__file__).resolve().parent.parent
    bootstrap = root / "scripts" / "bootstrap_postgres.py"
    run_bootstrap = subprocess.run(
        [sys.executable, str(bootstrap)],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    assert run_bootstrap.returncode == 0, run_bootstrap.stdout + run_bootstrap.stderr

    cmd = (
        "import json; "
        "from core.product_layer import get_admin_kpi; "
        "print(json.dumps(get_admin_kpi(days=1), ensure_ascii=False))"
    )
    run_kpi = subprocess.run(
        [sys.executable, "-c", cmd],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    assert run_kpi.returncode == 0, run_kpi.stdout + run_kpi.stderr
    assert "notification_observability" in run_kpi.stdout

