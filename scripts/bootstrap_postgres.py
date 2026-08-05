#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.db_runtime import resolve_db_runtime


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-only", action="store_true", help="Only check connectivity and print status.")
    args = ap.parse_args()

    cfg = resolve_db_runtime(root=ROOT, default_sqlite_path=ROOT / "data" / "app_state.db")
    if cfg.backend != "postgresql":
        print("[BLOCKED] II_DB_URL is not PostgreSQL. Set II_DB_URL=postgresql://user:pass@host:5432/db")
        return 2

    try:
        import psycopg
    except ImportError:
        print("[BLOCKED] Missing PostgreSQL driver. Install: pip install psycopg[binary]")
        return 2

    try:
        with psycopg.connect(cfg.dsn) as c:
            with c.cursor() as cur:
                cur.execute("SELECT version()")
                row = cur.fetchone()
        print(f"[OK] PostgreSQL connectivity established: {str((row or ['unknown'])[0])[:80]}")
    except Exception as e:
        print(f"[FAIL] Cannot connect PostgreSQL: {e.__class__.__name__}")
        return 1

    if args.check_only:
        return 0

    os.environ["II_DB_URL"] = cfg.dsn
    from core.product_layer import _init_db  # noqa: PLC0415

    _init_db()
    print("[OK] PostgreSQL schema bootstrap completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

