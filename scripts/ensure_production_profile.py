"""
Verify production profile: Postgres + secrets when II_ENV=prod (P3).

  python scripts/ensure_production_profile.py
  python scripts/ensure_production_profile.py --strict
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import env_bootstrap  # noqa: F401
except Exception:
    pass


def check_production_profile(*, strict: bool = False) -> dict:
    env = str(os.environ.get("II_ENV") or "dev").strip().lower()
    dsn = str(os.environ.get("II_DB_URL") or "").strip()
    pg_jobs = str(os.environ.get("II_USE_PG_ANALYSIS_JOBS") or "0").strip().lower() in ("1", "true", "yes")
    secret = str(os.environ.get("II_APP_SECRET_KEY") or "").strip()
    issues: list[str] = []
    warnings: list[str] = []

    if env == "prod":
        if not dsn.lower().startswith(("postgres://", "postgresql://")):
            issues.append("II_ENV=prod requires II_DB_URL=postgresql://...")
        if not secret:
            issues.append("II_ENV=prod requires II_APP_SECRET_KEY")
        if not pg_jobs:
            warnings.append("II_USE_PG_ANALYSIS_JOBS=0 — khuyến nghị bật worker Postgres trên prod")
        try:
            import psycopg  # noqa: F401
        except Exception:
            try:
                import psycopg2  # noqa: F401
            except Exception:
                issues.append("II_ENV=prod requires psycopg or psycopg2 installed")
    elif strict and dsn:
        if not dsn.lower().startswith(("postgres://", "postgresql://")):
            warnings.append("II_DB_URL set but not postgres DSN")

    ok = len(issues) == 0
    return {
        "ok": ok,
        "env": env,
        "postgres_configured": dsn.lower().startswith(("postgres://", "postgresql://")),
        "pg_jobs": pg_jobs,
        "issues": issues,
        "warnings": warnings,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Ensure production profile (Postgres default on prod).")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()
    rep = check_production_profile(strict=bool(args.strict))
    import json

    print(json.dumps(rep, ensure_ascii=False, indent=2))
    if not rep["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
