#!/usr/bin/env python3
"""Chạy bootstrap Postgres + pytest tích hợp (local).

Yêu cầu: Postgres đang lắng nghe (vd. `docker compose -f docker-compose.postgres.yml up -d`).
Mặc định DSN trùng docker-compose.postgres.yml; ghi đè bằng II_DB_URL.

  python scripts/run_postgres_smoke_local.py
  python scripts/run_postgres_smoke_local.py --dsn postgresql://user:pass@127.0.0.1:5432/db
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DSN = "postgresql://ii_user:ii_pass@127.0.0.1:5432/ii_app"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--dsn",
        default=os.environ.get("II_DB_URL", _DEFAULT_DSN),
        help="PostgreSQL URL (default: env II_DB_URL hoặc URL khớp docker-compose.postgres.yml).",
    )
    args = ap.parse_args()
    dsn = str(args.dsn).strip()
    if not dsn.lower().startswith(("postgres://", "postgresql://")):
        print("[FAIL] DSN phải bắt đầu bằng postgresql:// hoặc postgres://")
        return 2

    env = os.environ.copy()
    env["II_DB_URL"] = dsn

    boot = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "bootstrap_postgres.py")],
        cwd=str(ROOT),
        env=env,
    )
    if boot.returncode != 0:
        print("[FAIL] bootstrap_postgres.py")
        return int(boot.returncode)

    test = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(ROOT / "tests" / "test_postgres_integration_smoke.py")],
        cwd=str(ROOT),
        env=env,
    )
    if test.returncode != 0:
        print("[FAIL] pytest test_postgres_integration_smoke.py")
        return int(test.returncode)

    print("[OK] Postgres smoke local hoàn tất.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
