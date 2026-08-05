#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


TABLES: list[dict[str, Any]] = [
    {"name": "users", "columns": ["user_id", "plan_id", "updated_at"], "conflict": ["user_id"]},
    {"name": "holdings", "columns": ["user_id", "symbol", "quantity", "avg_cost", "updated_at"], "conflict": ["user_id", "symbol"]},
    {"name": "alerts", "columns": ["id", "user_id", "symbol", "type", "threshold", "note", "created_at"], "conflict": ["id"]},
    {"name": "usage_daily", "columns": ["user_id", "usage_date", "feature", "count"], "conflict": ["user_id", "usage_date", "feature"]},
    {"name": "events", "columns": ["id", "user_id", "ts", "event", "meta_json"], "conflict": ["id"]},
    {"name": "notification_sent", "columns": ["dedup_key", "user_id", "sent_at"], "conflict": ["dedup_key"]},
    {
        "name": "notification_queue",
        "columns": ["id", "user_id", "kind", "payload_json", "attempts", "status", "last_error", "next_retry_at", "created_at", "updated_at"],
        "conflict": ["id"],
    },
    {"name": "auth_users", "columns": ["user_id", "pin_hash", "created_at", "updated_at"], "conflict": ["user_id"]},
    {
        "name": "decisions",
        "columns": ["id", "user_id", "symbol", "side", "entry_price", "stop_loss", "take_profit", "thesis", "horizon_days", "created_at"],
        "conflict": ["id"],
    },
    {
        "name": "trades",
        "columns": [
            "id",
            "user_id",
            "decision_id",
            "symbol",
            "side",
            "quantity",
            "entry_price",
            "entry_fee",
            "entry_note",
            "opened_at",
            "status",
            "exit_price",
            "exit_fee",
            "exit_note",
            "closed_at",
        ],
        "conflict": ["id"],
    },
    {
        "name": "forecast_records",
        "columns": [
            "id",
            "user_id",
            "symbol",
            "created_at",
            "horizon_days",
            "base_price",
            "expected_price",
            "expected_return_pct",
            "realized_price",
            "realized_return_pct",
            "abs_error_pct",
            "direction_hit",
            "status",
        ],
        "conflict": ["id"],
    },
    {"name": "premium_trials", "columns": ["user_id", "trial_start_at", "trial_end_at", "trial_consumed", "updated_at"], "conflict": ["user_id"]},
    {"name": "schema_migrations", "columns": ["version", "applied_at"], "conflict": ["version"]},
    {"name": "cx_score_daily", "columns": ["user_id", "score_date", "score", "band", "updated_at"], "conflict": ["user_id", "score_date"]},
]


def build_insert_sql(table: str, columns: list[str], conflict_cols: list[str]) -> str:
    col_str = ", ".join(columns)
    val_str = ", ".join(["%s"] * len(columns))
    conflict_str = ", ".join(conflict_cols)
    return (
        f"INSERT INTO {table} ({col_str}) VALUES ({val_str}) "
        f"ON CONFLICT ({conflict_str}) DO NOTHING"
    )


def _rows_from_sqlite(sqlite_path: Path, table: str, columns: list[str]) -> list[tuple[Any, ...]]:
    with sqlite3.connect(sqlite_path) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(f"SELECT {', '.join(columns)} FROM {table}").fetchall()
    return [tuple(r[col] for col in columns) for r in rows]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sqlite-path", default=str(ROOT / "data" / "app_state.db"))
    ap.add_argument("--postgres-dsn", default=str(os.environ.get("II_DB_URL") or ""))
    args = ap.parse_args()

    sqlite_path = Path(args.sqlite_path)
    dsn = str(args.postgres_dsn or "").strip()
    if not sqlite_path.exists():
        print(f"[BLOCKED] SQLite DB not found: {sqlite_path}")
        return 2
    if not dsn.lower().startswith(("postgres://", "postgresql://")):
        print("[BLOCKED] Provide PostgreSQL DSN via --postgres-dsn or II_DB_URL")
        return 2

    os.environ["II_DB_URL"] = dsn
    from core.product_layer import _init_db  # noqa: PLC0415

    _init_db()

    import psycopg  # noqa: PLC0415

    migrated: dict[str, int] = {}
    with psycopg.connect(dsn) as pg:
        with pg.cursor() as cur:
            for spec in TABLES:
                table = str(spec["name"])
                columns = list(spec["columns"])
                conflict = list(spec["conflict"])
                rows = _rows_from_sqlite(sqlite_path, table, columns)
                if rows:
                    cur.executemany(build_insert_sql(table, columns, conflict), rows)
                migrated[table] = len(rows)
        pg.commit()

    total = sum(int(v) for v in migrated.values())
    print(f"[OK] Migrated SQLite -> PostgreSQL. tables={len(migrated)} rows={total}")
    for name in sorted(migrated.keys()):
        print(f" - {name}: {migrated[name]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

