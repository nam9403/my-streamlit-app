from __future__ import annotations

from scripts.migrate_sqlite_to_postgres import build_insert_sql


def test_build_insert_sql_uses_postgres_placeholders_and_conflict() -> None:
    sql = build_insert_sql("users", ["user_id", "plan_id"], ["user_id"])
    assert "VALUES (%s, %s)" in sql
    assert "ON CONFLICT (user_id) DO NOTHING" in sql

