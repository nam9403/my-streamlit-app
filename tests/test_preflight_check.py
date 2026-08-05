from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _run_preflight(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    root = Path(__file__).resolve().parent.parent
    script = root / "scripts" / "preflight_check.py"
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
    )


def test_preflight_prod_fails_without_secret(monkeypatch) -> None:
    import os

    env = dict(os.environ)
    env.pop("II_APP_SECRET_KEY", None)
    env["II_REQUIRE_APP_SECRET_KEY"] = "1"
    env["II_LOG_JSON"] = "1"
    out = _run_preflight(["--prod"], env)
    assert out.returncode == 1
    assert "Preflight failed" in out.stdout


def test_preflight_prod_passes_with_required_env(monkeypatch) -> None:
    import os

    env = dict(os.environ)
    env["II_APP_SECRET_KEY"] = "vBUjKIQm9RWv6fbf_6A6uDPDVXnTUu18rqzSaP6L5qs="
    env["II_REQUIRE_APP_SECRET_KEY"] = "1"
    env["II_LOG_JSON"] = "1"
    out = _run_preflight(["--prod"], env)
    assert out.returncode == 0
    assert "Preflight passed" in out.stdout
